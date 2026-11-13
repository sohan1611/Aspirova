"""ISRO's mixed recruitment archive: dated, future application rows only."""

import re
from typing import Any
from urllib.parse import urlsplit

from crawlers.government import (
    GovernmentAdapter,
    html_tree,
    iso,
    official_url,
    parse_date,
    student_notice,
)

LIST_URL = "https://www.isro.gov.in/CurrentOpportunities.html"
MAX_DETAILS = 12
_FIELDS = ("slno", "post", "advtNum", "opendate", "closedate", "Details")


class IsroAdapter(GovernmentAdapter):
    source_slug = "isro"

    def collect(self) -> list[dict[str, Any]]:
        tree = html_tree(self.get(LIST_URL).text)
        groups = list(tree.nodes(cls="list"))
        if not groups:
            raise ValueError("missing ISRO catalogue")
        if any("next" in a.attrs.get("rel", "").split() for a in tree.nodes("a")):
            raise ValueError("unexpected ISRO pagination")
        candidates: dict[str, dict[str, Any]] = {}
        total = 0
        for group in groups:
            if not group.has_class("row"):
                continue
            fields = [n for n in group.nodes() if any(n.has_class(c) for c in _FIELDS)]
            # Modern entries have six columns. Historical panels omit BOTH
            # application date columns entirely, leaving four. Split at slno,
            # never at the enclosing .row.list (which may hold several notices).
            notices = []
            for node in fields:
                if node.has_class("slno"):
                    notices.append([])
                if not notices:
                    raise ValueError("missing ISRO logical notice boundary")
                notices[-1].append(node)
            if not notices:
                raise ValueError("missing ISRO logical row")
            for cells in notices:
                names = _FIELDS if len(cells) == 6 else ("slno", "post", "advtNum", "Details")
                if len(cells) != len(names) or any(
                    not node.has_class(cls)
                    # Several centre panels reuse advtNum for the two date
                    # cells. Their six-column order still establishes meaning.
                    and not (len(cells) == 6 and index in {3, 4} and node.has_class("advtNum"))
                    for index, (node, cls) in enumerate(zip(cells, names))
                ):
                    raise ValueError("unexpected ISRO logical row order")
                total += 1
                if len(cells) == 4:
                    self._counts["skipped_closed"] += 1
                    continue
                title, ad, start, close = [c.text() for c in cells[1:5]]
                if not title:
                    raise ValueError("missing ISRO role title")
                # Old archive dates and undated rows never establish openness.
                due = parse_date(close, end=True)
                if due is None or due <= self._now():
                    self._counts["skipped_closed"] += 1
                    continue
                if not student_notice(title):
                    self._counts["skipped_irrelevant"] += 1
                    continue
                link = cells[5].one("a").attrs.get("href", "")
                if not link:
                    raise ValueError("missing ISRO detail URL")
                url = official_url(link, LIST_URL)
                key = urlsplit(url).path.lstrip("/")
                record = {
                    "external_id": key,
                    "title": title,
                    "url": url,
                    "company": "Indian Space Research Organisation",
                    "deadline": iso(due),
                    "confidence": "explicit",
                    "description": title,
                    "meta": {
                        "advertisement_number": ad,
                        "original_dates": {"opening_date": start, "closing_date": close},
                    },
                }
                if key in candidates:
                    self._counts["duplicates"] += 1
                    if candidates[key]["deadline"] != record["deadline"]:
                        raise ValueError("conflicting duplicate ISRO row")
                candidates[key] = record
        if total == 0 or len(candidates) > MAX_DETAILS:
            raise ValueError("empty/truncated ISRO catalogue or detail cap reached")
        self._expected = total
        records = []
        for record in candidates.values():
            detail = html_tree(self.get(record["url"]).text)
            labelled: dict[str, str] = {}
            for row in detail.nodes("tr"):
                cells = list(row.nodes("td"))
                for index in range(0, len(cells) - 1, 2):
                    labelled[cells[index].text()] = cells[index + 1].text()

            def field(label: str) -> str:
                return next(
                    (value for key, value in labelled.items() if label.lower() in key.lower()), ""
                )

            status = field("Status")
            raw_cutoff = field("Last Date for Submission")
            if not status or not raw_cutoff:
                raise ValueError("missing ISRO detail status/application deadline")
            due = parse_date(raw_cutoff, end=True)
            if not re.search(r"\bOpen\b", status, re.I) or due <= self._now():
                self._counts["skipped_closed"] += 1
                continue
            centre = field("ISRO Centre").rsplit("/", 1)[-1].strip()
            record["company"] = f"ISRO – {centre}" if centre else record["company"]
            record["location"] = field("Location").rsplit("/", 1)[-1].strip() or None
            record["deadline"] = iso(due)
            record["posted_at"] = iso(parse_date(field("Advertisement Date")))
            record["description"] = (
                record["title"] + ". " + "; ".join(f"{k}: {v}" for k, v in labelled.items())
            )
            record["meta"]["original_dates"].update(
                {
                    "detail_closing_date": raw_cutoff,
                    "advertisement_date": field("Advertisement Date"),
                }
            )
            record["meta"].update(
                {
                    "centre": centre,
                    "status": status,
                    "detail_advertisement_number": field("Advertisement Number"),
                }
            )
            records.append(record)
        return records
