"""guard search_tsv trigger to text-relevant changes only

The BEFORE INSERT OR UPDATE trigger recomputed opportunities.search_tsv on
EVERY row update - 4x to_tsvector plus a per-row company lookup - even when
only is_hidden / last_seen_at / status / deadline changed. scripts.compute_hidden
issues one UPDATE across every opportunity row, so that recompute fired
table-wide and blew past statement_timeout (QueryCanceled). Guard the function
so an UPDATE that touches no text-relevant column (title, summary,
description_raw, company_id) keeps its existing vector; INSERT always computes
(there is no OLD row). FTS depends only on those columns, so no vector goes
stale. Pure CREATE OR REPLACE FUNCTION - the trigger itself is unchanged and
there is no table lock.

Revision ID: e5a9c2f1b6d3
Revises: d8f3a1c6b4e2
Create Date: 2026-07-14 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5a9c2f1b6d3"
down_revision: Union[str, Sequence[str], None] = "d8f3a1c6b4e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_GUARDED_FUNCTION = """
    CREATE OR REPLACE FUNCTION opportunities_search_tsv_trigger() RETURNS trigger AS $$
    DECLARE
        company_name_text text;
    BEGIN
        -- Skip the (expensive) FTS recompute when an UPDATE changes no
        -- text-relevant column - is_hidden/last_seen_at/status/deadline bumps
        -- keep the existing vector. INSERT always computes (no OLD row).
        IF TG_OP = 'UPDATE'
           AND NEW.title IS NOT DISTINCT FROM OLD.title
           AND NEW.summary IS NOT DISTINCT FROM OLD.summary
           AND NEW.description_raw IS NOT DISTINCT FROM OLD.description_raw
           AND NEW.company_id IS NOT DISTINCT FROM OLD.company_id
        THEN
            RETURN NEW;
        END IF;

        SELECT name INTO company_name_text FROM companies WHERE id = NEW.company_id;

        NEW.search_tsv :=
            setweight(to_tsvector('english', coalesce(NEW.title, '')), 'A') ||
            setweight(to_tsvector('english', coalesce(company_name_text, '')), 'A') ||
            setweight(to_tsvector('english', coalesce(NEW.summary, '')), 'B') ||
            setweight(to_tsvector('english', coalesce(NEW.description_raw, '')), 'C');

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
"""


_UNGUARDED_FUNCTION = """
    CREATE OR REPLACE FUNCTION opportunities_search_tsv_trigger() RETURNS trigger AS $$
    DECLARE
        company_name_text text;
    BEGIN
        SELECT name INTO company_name_text FROM companies WHERE id = NEW.company_id;

        NEW.search_tsv :=
            setweight(to_tsvector('english', coalesce(NEW.title, '')), 'A') ||
            setweight(to_tsvector('english', coalesce(company_name_text, '')), 'A') ||
            setweight(to_tsvector('english', coalesce(NEW.summary, '')), 'B') ||
            setweight(to_tsvector('english', coalesce(NEW.description_raw, '')), 'C');

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(_GUARDED_FUNCTION)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(_UNGUARDED_FUNCTION)
