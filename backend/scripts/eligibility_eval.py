"""Read-only evaluation of private JSONL samples; never opens a database.

    python -m scripts.eligibility_eval --sample /private/sample.jsonl --labels /private/labels.jsonl

Lists use per-value TP/FP/FN. An empty citizenship list is a stated requirement
with unmapped country and is scored separately from null (not stated).
"""

import argparse
import json
from collections import Counter
from pathlib import Path

from core.eligibility_facts import extract_eligibility_facts

DIMENSIONS = (
    "grad_years",
    "stages",
    "final_year_only",
    "degree_levels",
    "college_restriction",
    "citizenship",
    "remote_mode",
    "remote_regions",
    "work_authorization",
    "visa_sponsorship",
    "timezones",
)


def _rows(path: Path) -> dict[str, dict]:
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        identifier = str(row["id"])
        if identifier in rows:
            raise ValueError(f"Duplicate id: {identifier}")
        rows[identifier] = row
    return rows


def _tokens(value: object) -> set:
    if value is None:
        return set()
    if isinstance(value, list):
        return set(value) if value else {"stated_country_unclear"}
    if isinstance(value, dict):
        return {tuple(sorted(value.items()))}
    return {value}


def evaluate(samples: dict[str, dict], labels: dict[str, dict]) -> tuple[dict, list[dict]]:
    scores = {
        draw: {key: Counter(TP=0, FP=0, FN=0) for key in DIMENSIONS}
        for draw in ("random", "eligibility_words", "overall")
    }
    errors = []
    if set(samples) != set(labels):
        raise ValueError("Sample and label ids must match exactly")
    for identifier, sample in samples.items():
        labelled = labels[identifier]
        if any(key not in labelled for key in DIMENSIONS):
            raise ValueError(f"Missing label dimension for id: {identifier}")
        draw = sample.get("draw")
        if draw not in {"random", "eligibility_words"}:
            raise ValueError(f"Invalid or missing draw for id: {identifier}")
        facts = extract_eligibility_facts(
            sample.get("title"),
            sample.get("description_raw"),
            sample.get("meta")
            or {
                "eligibility": sample.get("meta_eligibility"),
                "sponsorship": sample.get("meta_sponsorship"),
            },
            location=sample.get("location"),
            is_remote=sample.get("is_remote"),
        )
        for key in DIMENSIONS:
            actual = facts.get(key, {}).get("value")
            expected = labelled[key]
            predicted, truth = _tokens(actual), _tokens(expected)
            for group in (draw, "overall"):
                scores[group][key].update(
                    TP=len(predicted & truth), FP=len(predicted - truth), FN=len(truth - predicted)
                )
            if predicted != truth:
                errors.append(
                    {
                        "id": identifier,
                        "draw": draw,
                        "dimension": key,
                        "extracted": actual,
                        "labelled": expected,
                    }
                )
    return scores, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    args = parser.parse_args()
    scores, errors = evaluate(_rows(args.sample), _rows(args.labels))
    for draw, dimensions in scores.items():
        for dimension, counts in dimensions.items():
            tp, fp, fn = counts["TP"], counts["FP"], counts["FN"]
            precision = f"{tp / (tp + fp):.4f}" if tp + fp else "n/a"
            recall = f"{tp / (tp + fn):.4f}" if tp + fn else "n/a"
            print(
                f"draw={draw} dimension={dimension} TP={tp} FP={fp} FN={fn} "
                f"precision={precision} recall={recall}"
            )
    for error in errors:
        print(json.dumps(error, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
