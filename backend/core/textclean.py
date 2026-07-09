"""Shared cleanup for text received from external sources."""

import re

import ftfy


def fix_text(value: str | None) -> str | None:
    """Repair mojibake and normalize surrounding/internal whitespace."""
    if value is None:
        return None
    return re.sub(r"\s+", " ", ftfy.fix_text(value)).strip()
