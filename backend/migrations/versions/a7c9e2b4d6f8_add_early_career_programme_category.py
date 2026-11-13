"""Allow early-career hiring programmes.

Revision ID: a7c9e2b4d6f8
Revises: d9a3b7e1f5c2
"""

from alembic import op

revision = "a7c9e2b4d6f8"
down_revision = "d9a3b7e1f5c2"
branch_labels = None
depends_on = None

OLD_CATEGORIES = (
    "research_internship",
    "fellowship",
    "government_internship",
    "open_source",
    "international_research",
    "corporate_research",
    "recurring_competition",
    "scholarship",
    "conference",
)


def _replace(categories: tuple[str, ...]) -> None:
    op.drop_constraint("ck_programmes_category", "programmes", type_="check")
    values = ", ".join(f"'{category}'" for category in categories)
    op.create_check_constraint("ck_programmes_category", "programmes", f"category IN ({values})")


def upgrade() -> None:
    _replace((*OLD_CATEGORIES, "early_career"))


def downgrade() -> None:
    # Restoring the old constraint intentionally fails transactionally if rows
    # still use early_career. Reclassify/remove those rows before downgrading.
    _replace(OLD_CATEGORIES)
