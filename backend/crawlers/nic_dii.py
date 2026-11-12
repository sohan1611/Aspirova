"""NIC Digital India Internship: one notice per explicitly announced intake."""

import re
from datetime import datetime
from typing import Any

from crawlers.government import GovernmentAdapter, IST, html_tree, iso, official_url, parse_date

HOME_URL = "https://dii.nic.in/"
SCHEDULE_URL = HOME_URL + "timelines"
_EDITION = re.compile(r"\b(winter|summer)\s+(\d{4})\b", re.I)


class NicDiiAdapter(GovernmentAdapter):
    source_slug = "nic_dii"

    def collect(self) -> list[dict[str, Any]]:
        schedule = html_tree(self.get(SCHEDULE_URL).text)
        heading = next(
            (
                h
                for h in schedule.nodes()
                if h.tag in {"h2", "h3", "h4"} and "Schedule of Various Activities" in h.text()
            ),
            None,
        )
        edition = _EDITION.search(heading.text()) if heading else None
        if not edition:
            raise ValueError("missing NIC intake schedule heading")
        session, year = edition.group(1).lower(), edition.group(2)
        activities: dict[str, str] = {}
        tables = list(schedule.nodes("table", "table-bordered"))
        if len(tables) != 1:
            raise ValueError("missing/ambiguous NIC schedule table")
        for row in tables[0].nodes("tr"):
            cells = list(row.nodes("td"))
            if len(cells) == 3:
                activities[cells[1].text()] = cells[2].text()
        window = activities.get("Application Submission by Interns", "")
        end_match = re.search(
            r"(?:to|[-–])\s*(\d{1,2}(?:st|nd|rd|th)?\s+\w+\s+\d{4})", window, re.I
        )
        start_text = re.split(r"\s+to\s+", window, flags=re.I)[0]
        if not end_match:
            raise ValueError("missing NIC application window")
        if not re.search(r"\d{4}", start_text):
            start_text += " " + year
        start = parse_date(start_text)
        due = parse_date(end_match.group(1), end=True)
        home_html = self.get(HOME_URL).text
        home = html_tree(home_html)
        announcement = next(
            (
                h.text()
                for h in home.nodes()
                if h.tag in {"h1", "h2", "h3", "h4"}
                and "Digital India Internship" in h.text()
                and _EDITION.search(h.text())
            ),
            "",
        )
        home_edition = _EDITION.search(announcement)
        if not home_edition or home_edition.group(0).lower() != f"{session} {year}":
            raise ValueError("NIC home/schedule intake mismatch")
        constants: dict[str, str] = {}
        for name, expected in (("registrationStart", start), ("registrationEnd", due)):
            match = re.search(rf"\b{name}\s*=\s*new Date\(\s*['\"]([^'\"]+)['\"]", home_html)
            if match:
                precise = datetime.fromisoformat(match.group(1))
                if precise.utcoffset() is None or precise.astimezone(IST).date() != expected.date():
                    raise ValueError("NIC inline/schedule application date conflict")
                constants[name] = match.group(1)
                if name == "registrationEnd":
                    due = precise.astimezone(IST)
        guidelines = [
            official_url(a.attrs["href"], HOME_URL)
            for a in home.nodes("a")
            if "guidelines" in a.attrs.get("href", "").lower()
        ]
        self._expected = 1
        return [
            {
                "external_id": f"{session}-{year}",
                "title": announcement,
                "company": "National Informatics Centre",
                "url": SCHEDULE_URL,
                "description": f"{announcement}. Application Submission by Interns: {window}.",
                "deadline": iso(due),
                "confidence": "explicit",
                "posted_at": iso(parse_date(activities.get("Launch Date"))),
                "meta": {
                    "original_dates": activities,
                    "inline_dates": constants,
                    "application_start": iso(start),
                    "guidelines": sorted(set(guidelines)),
                    "posted_at_provenance": "labelled Launch Date",
                    "homepage_programme_duration": [
                        h.text() for h in home.nodes("h4") if "Internship Duration" in h.text()
                    ],
                    "deadline_precision": "second" if "registrationEnd" in constants else "day",
                },
            }
        ]
