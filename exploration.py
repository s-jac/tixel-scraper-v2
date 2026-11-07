#!/usr/bin/env python3
"""Probe Tixel's public HTML without assuming it contains complete inventory.

Install: python3 -m pip install requests
Example: python3 exploration.py --city Sydney --pages 3 --events 3
         python3 exploration.py --event-url https://tixel.com/au/music-tickets/...

The output directory contains the exact response HTML and a JSON report. This is
an exploration tool, not a claim that every event or listing was captured.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import quote, urljoin, urlparse


BASE = "https://tixel.com"
EVENT_PATH = re.compile(r"^/au/[^/?#]*-tickets/(?!$).+")
PRICE = re.compile(r"\$([\d,]+(?:\.\d{2})?)\s+ea\s+incl\.\s+fees\s*[•·]\s*(\d+)\s+tickets?", re.I)
FROM_PRICE = re.compile(r"^From\s+\$([\d,]+(?:\.\d{2})?)$", re.I)
RELATIVE_TIME = re.compile(
    r"^(?:about\s+)?(?:\d+|a|an)\s+"
    r"(?:seconds?|minutes?|hours?|days?|weeks?|months?|years?)\s+ago$|^yesterday$",
    re.I,
)


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[dict[str, str]] = []
        self.text: list[str] = []
        self._anchors: list[dict[str, object]] = []
        self._skip = 0
        self.script_markers: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip += 1
        if tag == "a":
            self._anchors.append({"href": attributes.get("href") or "", "text": []})

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._skip:
            self._skip -= 1
        if tag == "a" and self._anchors:
            anchor = self._anchors.pop()
            label = " ".join(anchor["text"])  # type: ignore[arg-type]
            self.links.append({"href": str(anchor["href"]), "text": label})

    def handle_data(self, data: str) -> None:
        if self._skip:
            for marker in ("__NEXT_DATA__", "__NUXT__", "listings", "tickets"):
                if marker in data:
                    self.script_markers.add(marker)
            return
        value = " ".join(data.split())
        if value:
            self.text.append(value)
            for anchor in self._anchors:
                anchor["text"].append(value)  # type: ignore[union-attr]


def parse(html: str) -> PageParser:
    page = PageParser()
    page.feed(html)
    return page


def event_links(page: PageParser, base_url: str) -> list[dict[str, str]]:
    found: dict[str, str] = {}
    for link in page.links:
        url = urljoin(base_url, link["href"])
        parsed = urlparse(url)
        if parsed.netloc == "tixel.com" and EVENT_PATH.match(parsed.path):
            found.setdefault(url, link["text"])
    return [{"url": url, "label": label} for url, label in found.items()]


def section(lines: list[str], start: str, end: str | None) -> list[str]:
    try:
        first = next(i for i, line in enumerate(lines) if line.lower() == start.lower()) + 1
    except StopIteration:
        return []
    last = next((i for i in range(first, len(lines)) if end and lines[i].lower() == end.lower()), len(lines))
    return lines[first:last]


def inspect_event(page: PageParser, url: str) -> dict[str, object]:
    lines = page.text
    activity = section(lines, "Live activity", "Buy tickets")
    buy = section(lines, "Buy tickets", "Event info")
    sales: list[dict[str, str | None]] = []
    for i, line in enumerate(activity):
        if " sold to " in line:
            when = next((x for x in activity[i + 1:i + 5] if RELATIVE_TIME.match(x)), None)
            sales.append({"activity": line, "relative_time": when})
        elif line.lower() == "sold to" and 0 < i < len(activity) - 1:
            when = next((x for x in activity[i + 2:i + 6] if RELATIVE_TIME.match(x)), None)
            sales.append({"activity": f"{activity[i - 1]} sold to {activity[i + 1]}",
                          "relative_time": when})
    listings = []
    price_groups = []
    for i, line in enumerate(buy):
        match = PRICE.search(line)
        if match:
            listings.append({
                "price_aud_including_fees": float(match.group(1).replace(",", "")),
                "ticket_count": int(match.group(2)),
                "preceding_text": buy[max(0, i - 2):i],
                "following_text": buy[i + 1:i + 4],
            })
        from_match = FROM_PRICE.match(line)
        if from_match:
            price_groups.append({
                "from_price_aud": float(from_match.group(1).replace(",", "")),
                "ticket_type": buy[i - 2] if i >= 2 else None,
                "availability_text": buy[i - 1] if i >= 1 else None,
            })
    return {
        "url": url,
        "page_heading": lines[:5],
        "live_activity_found": bool(activity),
        "buy_tickets_found": bool(buy),
        "sales_visible": sales,
        "visible_listing_count": len(listings),
        "visible_listings": listings,
        "visible_price_groups": price_groups,
        "inventory_claim": next((" ".join(buy[i:i + 2]) for i, x in enumerate(buy)
                                 if "listings" in x.lower() and i + 1 < len(buy)
                                 and "available" in buy[i + 1].lower()), None),
        "script_markers": sorted(page.script_markers),
    }


def fetch(session: object, url: str, target: Path, delay: float) -> tuple[PageParser, dict[str, object]]:
    # Import here so parser checks can run even before requests is installed.
    response = session.get(url, timeout=30)  # type: ignore[attr-defined]
    response.raise_for_status()
    target.write_text(response.text, encoding="utf-8")
    page = parse(response.text)
    metadata = {
        "requested_url": url,
        "final_url": response.url,
        "status": response.status_code,
        "bytes": len(response.content),
        "html_file": str(target),
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    if delay:
        time.sleep(delay)
    return page, metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--city", default="Sydney")
    parser.add_argument("--pages", type=int, default=3, help="maximum city pages to inspect")
    parser.add_argument("--events", type=int, default=3, help="maximum discovered events to inspect")
    parser.add_argument("--event-url", help="inspect this event directly (instead of city discovery)")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between requests")
    parser.add_argument("--output", type=Path, default=Path("exploration-output"))
    args = parser.parse_args()
    if args.pages < 1 or args.events < 0 or args.delay < 0:
        parser.error("pages must be >= 1, events >= 0, and delay >= 0")
    try:
        import requests
    except ImportError:
        parser.error("requests is required: python3 -m pip install requests")

    args.output.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": "TixelExploration/0.1 (public HTML research)"})
    report: dict[str, object] = {"city_pages": [], "events": [], "errors": []}
    found: dict[str, str] = {}

    if args.event_url:
        urls = [args.event_url]
    else:
        city = quote(args.city, safe="")
        for number in range(1, args.pages + 1):
            url = f"{BASE}/au/discover/{city}" + (f"?page={number}" if number > 1 else "")
            try:
                page, metadata = fetch(session, url, args.output / f"city-{number}.html", args.delay)
                links = event_links(page, url)
                new = 0
                for item in links:
                    if item["url"] not in found:
                        found[item["url"]] = item["label"]
                        new += 1
                next_links = [link["href"] for link in page.links if link["text"].strip().lower() == "next"]
                metadata.update({"event_links": links, "new_event_links": new,
                                 "next_page_links": next_links})
                report["city_pages"].append(metadata)  # type: ignore[union-attr]
                print(f"City page {number}: {len(links)} event links, {new} new")
                if not links or not next_links or (number > 1 and new == 0):
                    break
            except requests.RequestException as exc:
                report["errors"].append({"url": url, "error": str(exc)})  # type: ignore[union-attr]
                print(f"City page {number}: {exc}", file=sys.stderr)
                break
        urls = list(found)[:args.events]

    for number, url in enumerate(urls, 1):
        try:
            page, metadata = fetch(session, url, args.output / f"event-{number}.html", args.delay)
            details = inspect_event(page, url)
            details.update(metadata)
            report["events"].append(details)  # type: ignore[union-attr]
            print(f"Event {number}: {len(details['sales_visible'])} visible sales, "
                  f"{details['visible_listing_count']} price cards, "
                  f"{len(details['visible_price_groups'])} price groups — {url}")
        except requests.RequestException as exc:
            report["errors"].append({"url": url, "error": str(exc)})  # type: ignore[union-attr]
            print(f"Event {number}: {exc}", file=sys.stderr)

    output = args.output / "report.json"
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Report: {output}")
    return 0 if not report["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
