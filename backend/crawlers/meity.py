"""MeitY's public careers CMS, including NeGD and DIC notices."""

import math
import re
from typing import Any

from crawlers.common import extract_text
from crawlers.government import (
    GovernmentAdapter,
    application_dates,
    iso,
    official_url,
    parse_date,
)

CAREERS_URL = "https://www.meity.gov.in/offerings/vacancies?target_lang=en"
API_URL = "https://www.meity.gov.in/cms/wp-json/post-page/careers_post"
PAGE_SIZE = 50
MAX_PAGES = 5


def _attachments(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "url" and isinstance(item, str) and item:
                try:
                    url = official_url(item, CAREERS_URL)
                except ValueError:
                    continue
                if url not in found:
                    found.append(url)
            elif isinstance(item, (dict, list)):
                found.extend(url for url in _attachments(item) if url not in found)
    elif isinstance(value, list):
        for item in value:
            found.extend(url for url in _attachments(item) if url not in found)
    return found


class MeityCareersAdapter(GovernmentAdapter):
    source_slug = "meity_careers"

    def collect(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        totals = None
        for page in range(1, MAX_PAGES + 1):
            data = self.get(f"{API_URL}?limit={PAGE_SIZE}&page={page}").json()
            if not isinstance(data, dict) or not isinstance(data.get("posts"), list):
                raise ValueError("missing careers collection")
            current = tuple(data.get(key) for key in ("total_items", "total_pages", "current_page"))
            if any(type(value) is not int for value in current):
                raise ValueError("missing pagination counts")
            total, pages, current_page = current
            if (
                total < 0
                or pages != max(1, math.ceil(total / PAGE_SIZE))
                or current_page != page
                or pages > MAX_PAGES
            ):
                raise ValueError("invalid/truncated careers pagination")
            if totals is None:
                totals = (total, pages)
                self._expected = total
            if totals != (total, pages):
                raise ValueError("careers inventory changed during traversal")
            posts = data["posts"]
            if len(posts) != min(PAGE_SIZE, max(total - (page - 1) * PAGE_SIZE, 0)):
                raise ValueError("truncated careers page")
            for post in posts:
                if not isinstance(post, dict) or not post.get("ID"):
                    raise ValueError("missing CMS notice ID")
                key = str(post["ID"])
                if key in seen:
                    raise ValueError("duplicate CMS notice across pages")
                seen.add(key)
                records.append(self.notice(post))
            if page == pages:
                if len(seen) != total:
                    raise ValueError("careers count mismatch")
                return records
        raise ValueError("careers page cap reached")

    def notice(self, post: dict[str, Any]) -> dict[str, Any]:
        acf = post.get("acf_data")
        acf = acf if isinstance(acf, dict) else {}
        title = extract_text(post.get("post_title") or acf.get("careers_title"))
        if not title:
            raise ValueError("missing careers title")
        description = extract_text(acf.get("careers_content") or post.get("post_content"))
        attachments = _attachments(acf)
        due = parse_date(acf.get("date"), end=True)
        prose_dates = application_dates(description)
        cutoffs = [parse_date(value, end=True) for value in prose_dates]
        conflict = bool(cutoffs and any(value != (due or cutoffs[0]) for value in cutoffs))
        if conflict:
            due = None
        elif due is None and cutoffs:
            due = cutoffs[0]
        signal = f"{title} {description}"
        if re.search(r"\bNeGD\b|National e-Governance Division", signal, re.I):
            company = "National e-Governance Division"
        elif re.search(r"\bDIC\b|Digital India (?:Corporation|BHASHINI)", signal, re.I):
            company = "Digital India Corporation"
        else:
            company = "Ministry of Electronics and Information Technology"
        return {
            "external_id": str(post["ID"]),
            "title": title,
            "company": company,
            "url": attachments[0] if attachments else CAREERS_URL,
            "description": description or title,
            "deadline": iso(due),
            "confidence": "explicit" if due else "unknown",
            "posted_at": iso(parse_date(acf.get("published_date"))),
            # The real BHASHINI title paraphrases 'young professionals'; the
            # accompanying source label states the role exactly.
            "role_label": acf.get("pdf_title") or "",
            "meta": {
                "cms_id": post["ID"],
                "attachments": attachments,
                "original_dates": {
                    key: acf.get(key) for key in ("date", "published_date", "start_date")
                },
                "application_dates_in_content": prose_dates,
                "deadline_conflict": conflict,
                "missing_acf": not bool(acf),
            },
        }
