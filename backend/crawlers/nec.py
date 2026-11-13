"""North Eastern Council's public internship intake table and detail pages."""

import re
from typing import Any

from crawlers.government import (
    GovernmentAdapter,
    application_dates,
    html_tree,
    iso,
    official_url,
    parse_date,
)

LIST_URL = "https://necouncil.gov.in/nec-internship-applications"
MAX_DETAILS = 6


class NecInternshipsAdapter(GovernmentAdapter):
    source_slug = "nec_internships"

    def collect(self) -> list[dict[str, Any]]:
        tree = html_tree(self.get(LIST_URL).text)
        table = tree.one("table", "cols-3")
        if table.tag == "missing":
            raise ValueError("missing NEC intake table")
        if any("next" in a.attrs.get("rel", "").split() for a in tree.nodes("a")):
            raise ValueError("unexpected NEC pagination")
        rows = [r for r in table.nodes("tr") if r.one("td").tag != "missing"]
        if not rows or len(rows) > MAX_DETAILS:
            raise ValueError("empty/truncated NEC intake table")
        records = []
        seen: set[str] = set()
        for row in rows:
            cells = list(row.nodes("td"))
            link = cells[0].one("a")
            title = link.text()
            if len(cells) != 3 or not title or not link.attrs.get("href"):
                raise ValueError("malformed NEC intake")
            url = official_url(link.attrs["href"], LIST_URL)
            detail = html_tree(self.get(url).text)
            headings = [
                h.text()
                for h in detail.nodes()
                if h.tag in {"h1", "h2"} and "internship" in h.text().lower()
            ]
            cutoffs = application_dates(title)
            detail_cutoffs = [d for h in headings for d in application_dates(h)]
            if len(cutoffs) != 1 or not detail_cutoffs:
                raise ValueError("missing NEC application deadline/detail")
            due = parse_date(cutoffs[0], end=True)
            if any(parse_date(d, end=True) != due for d in detail_cutoffs):
                raise ValueError("NEC table/detail cutoff conflict")
            session = re.search(r"\b(winter|summer)\b", title, re.I)
            detail_session = re.search(r"\b(winter|summer)\b", " ".join(headings), re.I)
            if not session or not detail_session or session[0].lower() != detail_session[0].lower():
                raise ValueError("missing/conflicting NEC intake session")
            attachments = [
                official_url(a.attrs["href"], LIST_URL)
                for a in cells[1].nodes("a")
                if a.attrs.get("href")
            ]
            # Use the notice's publication directory, never the cutoff year.
            # This also survives an extension into January or a renamed detail
            # slug. If unavailable, retain the official notice path identity.
            published = next(
                (
                    m
                    for attachment in attachments
                    if (m := re.search(r"/files/(\d{4})-\d{2}/", attachment))
                ),
                None,
            )
            key = f"{session[0].lower()}-{published[1]}" if published else url.split("/", 3)[-1]
            if key in seen:
                raise ValueError("ambiguous duplicate NEC intake")
            seen.add(key)
            records.append(
                {
                    "external_id": key,
                    "title": title,
                    "company": "North Eastern Council",
                    "url": url,
                    "deadline": iso(due),
                    "confidence": "explicit",
                    "description": title + ". " + cells[1].text(),
                    "meta": {
                        "original_dates": {"application_cutoff": cutoffs[0]},
                        "attachments": attachments,
                        "detail_title": headings,
                        "intake_identity_provenance": (
                            "session and notice publication directory"
                            if published
                            else "notice path"
                        ),
                        "posted_at_provenance": "not stated; footer update ignored",
                    },
                }
            )
        self._expected = len(rows)
        return records
