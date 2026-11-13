"""Allow government recruitment exams in the programme registry.

Revision ID: b8d1f3a5c7e9
Revises: a7c9e2b4d6f8
"""

from alembic import op

revision = "b8d1f3a5c7e9"
down_revision = "a7c9e2b4d6f8"
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
    "early_career",
)


def _replace(categories: tuple[str, ...]) -> None:
    op.drop_constraint("ck_programmes_category", "programmes", type_="check")
    values = ", ".join(f"'{category}'" for category in categories)
    op.create_check_constraint("ck_programmes_category", "programmes", f"category IN ({values})")


def upgrade() -> None:
    _replace((*OLD_CATEGORIES, "government_exam"))


def downgrade() -> None:
    # Fails transactionally until exam rows have been reclassified or removed.
    _replace(OLD_CATEGORIES)
