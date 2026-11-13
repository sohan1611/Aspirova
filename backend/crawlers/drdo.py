"""English vacancies cards on DRDO's migrated official origin."""

import re
from typing import Any

from crawlers.government import GovernmentAdapter, html_tree, iso, official_url, parse_date

ORIGIN = "https://xn--m1b0a2bb8esed.xn--11b7cb3a6a.xn--h2brj9c"
LIST_URL = ORIGIN + "/drdo/en/offerings/vacancies?items_per_page=50"
MAX_PAGES = 3


class DrdoAdapter(GovernmentAdapter):
    source_slug = "drdo"

    def collect(self) -> list[dict[str, Any]]:
        notices: dict[str, dict[str, Any]] = {}
        visited: set[str] = set()
        url = LIST_URL
        for _ in range(MAX_PAGES):
            if url in visited:
                raise ValueError("repeated DRDO page")
            visited.add(url)
            tree = html_tree(self.get(url).text)
            cards = list(tree.nodes(cls="vacanciess-box-content"))
            if not cards:
                raise ValueError("missing DRDO cards")
            for card in cards:

                def field(name: str) -> str:
                    return card.one(cls="vacanciess-" + name).text()

                title = field("title")
                link = card.one(cls="vacanciess-view-node").one("a").attrs.get("href", "")
                if not title or not link:
                    raise ValueError("malformed DRDO card")
                notice_url = official_url(link, ORIGIN)
                ad = field("advertisment-no-content")
                key = re.sub(r"\s+", " ", ad).strip().casefold() or notice_url.split("?", 1)[0]
                dates = {
                    name: field(name)
                    for name in ("date-publish-content", "start-date-content", "due-date-content")
                }
                due = parse_date(dates["due-date-content"], end=True)
                # The captured label is only 'End Date'. No detail/PDF evidence
                # confirms application meaning, so this must remain inferred.
                lab = re.search(
                    r"\b(DGRE|TBRL|CASDIC|DRDE|DMRL|DYSL-CT|ARDE|RCI|CEPTAM)\b", title, re.I
                )
                if not lab:
                    lab = re.match(r"([A-Z][A-Z0-9-]{1,15})/", ad)
                location = re.search(
                    r"\b(Chandigarh|Gwalior|Bengaluru|Hyderabad|Pune|Chennai)\b", title, re.I
                )
                record = {
                    "external_id": key,
                    "title": title,
                    "url": notice_url,
                    "company": (
                        f"DRDO – {lab.group(1).upper()}"
                        if lab
                        else "Defence Research and Development Organisation"
                    ),
                    "location": location.group(1) if location else None,
                    "description": title + ". " + field("desc"),
                    "deadline": iso(due),
                    "confidence": "inferred" if due else "unknown",
                    "posted_at": iso(parse_date(dates["date-publish-content"])),
                    "meta": {
                        "advertisement_number": ad,
                        "original_dates": dates,
                        "deadline_label": "End Date",
                        "language": "en",
                        "notice_urls": [notice_url],
                    },
                }
                previous = notices.get(key)
                if previous:
                    self._counts["duplicates"] += 1
                    # Consolidate an original and extension into one application
                    # notice. The later cutoff wins, independently of card order.
                    urls = sorted(set(previous["meta"]["notice_urls"] + [notice_url]))
                    if (record.get("deadline") or "") >= (previous.get("deadline") or ""):
                        notices[key] = record
                    notices[key]["meta"]["notice_urls"] = urls
                else:
                    notices[key] = record
            next_links = [
                a
                for a in tree.nodes("a")
                if "next" in a.attrs.get("rel", "").split()
                or a.attrs.get("title", "").lower() == "go to next page"
                or ("next" in a.text().lower() and "page=" in a.attrs.get("href", ""))
            ]
            if not next_links:
                if len(cards) >= 50:
                    raise ValueError("full DRDO page without pagination evidence")
                return list(notices.values())
            url = official_url(next_links[0].attrs["href"], url)
        raise ValueError("DRDO pagination cap reached")
