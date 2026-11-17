"""Compare Python to execution of the actual TypeScript for every taxonomy key."""

import json
import shutil
import subprocess
from pathlib import Path

from core.taxonomy import STREAMS, TAXONOMY_PATH, build_feed_terms, expand_to_search_terms


def test_backend_taxonomy_is_byte_identical_to_frontend_canonical():
    canonical = Path(__file__).resolve().parents[2] / "frontend" / "lib" / "taxonomy.json"

    # Byte-identical apart from the checkout's line endings (Windows autocrlf).
    def content(path: Path) -> bytes:
        return path.read_bytes().replace(b"\r\n", b"\n")

    assert content(TAXONOMY_PATH) == content(canonical)


def test_backend_expansion_equals_frontend_for_every_key():
    profiles = []
    for stream in STREAMS:
        for division in stream["divisions"]:
            for interest in division["interests"]:
                profile = {
                    "stream": stream["key"],
                    "divisions": [division["key"]],
                    "interests": [interest["key"]],
                    "country": None,
                }
                profiles.append(
                    {"profile": profile, "skills": [" Python ", "PYTHON", "SQL"], "maxChars": 480}
                )
        profiles.append(
            {
                "profile": {
                    "stream": stream["key"],
                    "divisions": [d["key"] for d in reversed(stream["divisions"])],
                    "interests": [i["key"] for d in stream["divisions"] for i in d["interests"]],
                },
                "skills": [],
                "maxChars": 480,
            }
        )
    for limit in (0, 5, 16, 19, 480):
        profiles.append(
            {
                "profile": {
                    "stream": "engineering",
                    "divisions": ["cse", "it", "cse"],
                    "interests": ["data_science", "web_dev", "missing"],
                },
                "skills": ["Python", " web development ", "SQL"],
                "maxChars": limit,
            }
        )
    profiles.append(
        {
            "profile": {"stream": "missing", "divisions": [], "interests": []},
            "skills": ["Python"],
            "maxChars": 480,
        }
    )
    # JS caps UTF-16 code units, including skills outside the BMP.
    profiles.append(
        {
            "profile": {"stream": None, "divisions": [], "interests": []},
            "skills": ["Python", "😀", "SQL"],
            "maxChars": 8,
        }
    )
    node = shutil.which("node")
    assert node, "Taxonomy parity requires Node 24+"
    frontend = Path(__file__).resolve().parents[2] / "frontend"
    result = subprocess.run(
        [node, "scripts/taxonomy-parity.mjs"],
        cwd=frontend,
        input=json.dumps(profiles),
        text=True,
        capture_output=True,
        check=True,
    )
    expected = json.loads(result.stdout)
    assert len(expected) == len(profiles)
    for case, actual in zip(profiles, expected, strict=True):
        assert expand_to_search_terms(case["profile"]) == actual["expanded"], case
        assert (
            build_feed_terms(case["profile"], case["skills"], case["maxChars"]) == actual["feed"]
        ), case
