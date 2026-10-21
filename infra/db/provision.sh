#!/usr/bin/env bash
# Provision the Aspirova Postgres server on a fresh DigitalOcean droplet.
#
# Target: Ubuntu 24.04, Basic Regular 1 vCPU / 1 GB / 25 GB SSD, region SGP1
# (same city as the Render API). Run once, as root:
#
#   ssh root@<droplet-ip> 'bash -s' < infra/db/provision.sh
#
# Safe to re-run: every step checks before it changes anything.
#
# Mirrors production Supabase wherever it changes results: Postgres 17, ICU
# en-US collation over en_US.UTF-8, UTC, and vector / pg_trgm / citext in
# `public`. The app connects as `aspirova_app` - owner of the database, NOT a
# superuser - over TLS with scram-sha-256. `postgres` is local-socket only.
#
# Sizing comes from the 2026-10-21 restore test on a 1 CPU / 1 GB copy of
# production: 551 MiB warm, 788 MiB peak while crawling, never OOM.
set -euo pipefail

PG_MAJOR=17
DB_NAME=aspirova
APP_ROLE=aspirova_app
PASSWORD_FILE=/root/aspirova_app_password
CONF_DIR=/etc/postgresql/$PG_MAJOR/main
export DEBIAN_FRONTEND=noninteractive

log() { printf '\n== %s\n' "$*"; }

log "swap: a 2 GB safety net under 1 GB of RAM"
if ! swapon --show=NAME --noheadings | grep -qx /swapfile; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
fi
grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
echo 'vm.swappiness = 10' > /etc/sysctl.d/90-aspirova.conf
sysctl -q --system

log "locale: en_US.UTF-8 (production's lc_collate / lc_ctype)"
locale -a | grep -qix 'en_US.utf8' || locale-gen en_US.UTF-8 >/dev/null

log "packages: PostgreSQL $PG_MAJOR + pgvector from the PGDG repository"
if [ ! -f /etc/apt/sources.list.d/pgdg.list ]; then
  apt-get update -qq
  apt-get install -y -qq curl ca-certificates >/dev/null
  install -d /usr/share/postgresql-common/pgdg
  curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
    https://www.postgresql.org/media/keys/ACCC4CF8.asc
  echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt $(. /etc/os-release && echo "$VERSION_CODENAME")-pgdg main" \
    > /etc/apt/sources.list.d/pgdg.list
fi
apt-get update -qq
apt-get install -y -qq "postgresql-$PG_MAJOR" "postgresql-$PG_MAJOR-pgvector" ufw unattended-upgrades >/dev/null

log "server settings for 1 vCPU / 1 GB"
cat > "$CONF_DIR/conf.d/aspirova.conf" <<'EOF'
# Aspirova production. Sized from the 2026-10-21 restore test (see provision.sh).
listen_addresses = '*'
max_connections = 60                # API pool 20, x2 while Render overlaps a deploy, + jobs
shared_buffers = 256MB
effective_cache_size = 640MB
work_mem = 4MB
maintenance_work_mem = 64MB
random_page_cost = 1.1              # SSD
effective_io_concurrency = 200
wal_compression = on
max_wal_size = 1GB
checkpoint_completion_target = 0.9
shared_preload_libraries = 'pg_stat_statements'
timezone = 'UTC'
log_timezone = 'UTC'
password_encryption = 'scram-sha-256'
ssl = on
ssl_min_protocol_version = 'TLSv1.2'
log_min_duration_statement = 2000   # log any statement slower than 2 s
tcp_keepalives_idle = 60
EOF

log "client auth: the app role over TLS only; superuser stays local"
HBA="$CONF_DIR/pg_hba.conf"
if ! grep -q 'aspirova: app over TLS' "$HBA"; then
  cat >> "$HBA" <<EOF

# aspirova: app over TLS only. postgres has no remote rule, so it is local-socket only.
hostssl $DB_NAME $APP_ROLE 0.0.0.0/0 scram-sha-256
hostssl $DB_NAME $APP_ROLE ::/0      scram-sha-256
EOF
fi
systemctl restart "postgresql@$PG_MAJOR-main"

log "role and database"
if [ ! -s "$PASSWORD_FILE" ]; then
  (umask 077 && openssl rand -hex 24 > "$PASSWORD_FILE")
fi
sudo -u postgres psql -v ON_ERROR_STOP=1 -q <<SQL
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$APP_ROLE') THEN
    CREATE ROLE $APP_ROLE LOGIN;
  END IF;
END \$\$;
ALTER ROLE $APP_ROLE PASSWORD '$(cat "$PASSWORD_FILE")';
SQL
if [ -z "$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname = '$DB_NAME'")" ]; then
  # Database-level ICU: matches production's datlocprovider=i / en-US without
  # re-initialising the cluster. Without it, ORDER BY name changes order.
  sudo -u postgres psql -v ON_ERROR_STOP=1 -q -c \
    "CREATE DATABASE $DB_NAME OWNER $APP_ROLE TEMPLATE template0 ENCODING 'UTF8' LOCALE_PROVIDER icu ICU_LOCALE 'en-US' LOCALE 'en_US.UTF-8'"
fi
# pg_dump --schema=public carries no CREATE EXTENSION, and vector needs a
# superuser to install, so the extensions exist before any restore.
sudo -u postgres psql -d "$DB_NAME" -v ON_ERROR_STOP=1 -q <<SQL
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
GRANT pg_read_all_stats TO $APP_ROLE;
SQL

log "firewall: SSH (rate-limited) and Postgres only"
ufw limit OpenSSH >/dev/null
ufw allow 5432/tcp >/dev/null
ufw --force enable >/dev/null

log "ssh: keys only"
# 01- sorts before cloud-init's 50- file, and sshd keeps the FIRST value it reads.
printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\n' > /etc/ssh/sshd_config.d/01-aspirova.conf
# try-reload-or-restart: on 24.04 ssh may be socket-activated and idle, where a
# plain reload fails and would abort this script halfway.
sshd -t && systemctl try-reload-or-restart ssh

log "automatic updates, kept out of crawl and digest hours"
# Security updates plus PGDG minor releases. A minor release restarts Postgres
# for a few seconds; pool_pre_ping in core/db.py reconnects. 21:00 UTC (02:30
# IST) is after the 19:17 backup and hours before the 06:05 crawl.
cat > /etc/apt/apt.conf.d/52aspirova-upgrades <<'EOF'
Unattended-Upgrade::Origins-Pattern { "origin=apt.postgresql.org"; };
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "21:30";
EOF
mkdir -p /etc/systemd/system/apt-daily-upgrade.timer.d
cat > /etc/systemd/system/apt-daily-upgrade.timer.d/override.conf <<'EOF'
[Timer]
OnCalendar=
OnCalendar=*-*-* 21:00
RandomizedDelaySec=15m
EOF
systemctl daemon-reload

log "check"
sudo -u postgres psql -d "$DB_NAME" -tA <<'SQL'
SELECT 'server   ' || current_setting('server_version');
SELECT 'locale   ' || datlocprovider || ' ' || datlocale || ' / ' || datcollate FROM pg_database WHERE datname = current_database();
SELECT 'owner    ' || pg_get_userbyid(datdba) FROM pg_database WHERE datname = current_database();
SELECT 'ext      ' || string_agg(extname || ' ' || extversion, ', ' ORDER BY extname) FROM pg_extension;
SELECT 'buffers  ' || current_setting('shared_buffers') || ', max_connections ' || current_setting('max_connections');
SELECT 'ssl      ' || current_setting('ssl');
SQL
swapon --show=NAME,SIZE --noheadings | sed 's/^/swap     /'
ufw status | sed -n '1p;5,$p'
echo
echo "The app password is in $PASSWORD_FILE (root-only). This script never prints it."
