"""Official identities for the frontend's curated straight-to-source companies."""

import json
from pathlib import Path

EXTERNAL_COMPANIES: list[dict[str, str]] = json.loads(
    (Path(__file__).resolve().parents[1] / "data/external_companies.json").read_text(
        encoding="utf-8"
    )
)
