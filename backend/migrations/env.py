from logging.config import fileConfig

from sqlalchemy import pool

from alembic import context

from core.config import get_settings
from core.db import make_engine
from core.models import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# DATABASE_URL always comes from core.config (.env), never from alembic.ini
# (Doc 08: no secrets in code/config files). NOTE: deliberately NOT routed
# through config.set_main_option()/configparser - a percent-encoded password
# (e.g. %40, %23) is misread by configparser as interpolation syntax and
# raises ValueError. The engine is built directly from the settings object
# instead, in both code paths below.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emits SQL, no DB connection)."""
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode against the real database."""
    connectable = make_engine(poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
