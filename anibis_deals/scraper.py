#!/usr/bin/env python3
"""Scrape Anibis offers into SQLite."""

import argparse
import json
import math
import sqlite3
import sys
import time
from collections.abc import Iterable, Iterator
from contextlib import nullcontext
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, TextIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

USER_AGENT = "Mozilla/5.0 (compatible; anibis-scraper/0.1; personal-use)"

CREATE_OFFERS_TABLE = """
CREATE TABLE IF NOT EXISTS offers (
    listingID TEXT PRIMARY KEY,
    title TEXT,
    price TEXT,
    date TEXT,
    description TEXT,
    city TEXT,
    postcode TEXT,
    url TEXT NOT NULL,
    lastSeen TEXT NOT NULL
)
"""

CREATE_PRICE_HISTORY_TABLE = """
CREATE TABLE IF NOT EXISTS offer_price_history (
    listingID TEXT NOT NULL,
    price TEXT,
    observedAt TEXT NOT NULL,
    PRIMARY KEY (listingID, observedAt)
)
"""

INSERT_PRICE_CHANGE = """
INSERT INTO offer_price_history (listingID, price, observedAt)
SELECT ?, ?, ?
WHERE NOT EXISTS (
    SELECT 1 FROM offers WHERE listingID = ? AND price IS ?
)
"""

UPSERT_OFFER = """
INSERT INTO offers (
    listingID, title, price, date, description, city, postcode, url, lastSeen
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(listingID) DO UPDATE SET
    title = excluded.title,
    price = excluded.price,
    date = excluded.date,
    description = excluded.description,
    city = excluded.city,
    postcode = excluded.postcode,
    url = excluded.url,
    lastSeen = excluded.lastSeen
"""


class ScraperError(RuntimeError):
    """A readable scraper failure."""


class NextDataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._inside_next_data = False
        self._parts: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag == "script" and dict(attrs).get("id") == "__NEXT_DATA__":
            self._inside_next_data = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._inside_next_data:
            self._inside_next_data = False

    def handle_data(self, data: str) -> None:
        if self._inside_next_data:
            self._parts.append(data)

    @property
    def next_data(self) -> str:
        return "".join(self._parts)


def parse_search_page(html: str) -> dict[str, Any]:
    parser = NextDataParser()
    parser.feed(html)
    if not parser.next_data:
        raise ScraperError("Anibis response did not contain __NEXT_DATA__")

    try:
        page = json.loads(parser.next_data)
        queries = page["props"]["pageProps"]["dehydratedState"]["queries"]
        result = next(
            query["state"]["data"]
            for query in queries
            if query.get("queryKey", [None])[0] == "SearchListingsByConstraints"
        )
    except (json.JSONDecodeError, KeyError, StopIteration, TypeError) as error:
        raise ScraperError("Anibis search data had an unexpected shape") from error

    # Tolerate both React Query cache shapes used by Anibis.
    return result.get("searchListingsByQuery", result)


def fetch_page(url: str, timeout: float) -> tuple[dict[str, Any], str]:
    request = Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-CH,en;q=0.8",
            "User-Agent": USER_AGENT,
        },
    )

    for attempt in range(3):
        try:
            with urlopen(request, timeout=timeout) as response:
                final_url = response.geturl()
                if urlsplit(final_url).hostname not in {"anibis.ch", "www.anibis.ch"}:
                    raise ScraperError(f"Unexpected redirect to {final_url}")
                charset = response.headers.get_content_charset() or "utf-8"
                html = response.read().decode(charset)
                return parse_search_page(html), final_url
        except HTTPError as error:
            if error.code not in {429, 500, 502, 503, 504} or attempt == 2:
                raise ScraperError(f"Anibis returned HTTP {error.code}") from error
            retry_after = error.headers.get("Retry-After")
            try:
                wait = min(float(retry_after), 60.0) if retry_after else 2**attempt
            except ValueError:
                wait = 2**attempt
        except URLError as error:
            if attempt == 2:
                raise ScraperError(f"Could not reach Anibis: {error.reason}") from error
            wait = 2**attempt
        time.sleep(wait)

    raise AssertionError("unreachable")


def page_url(canonical_url: str, page: int) -> str:
    parts = urlsplit(canonical_url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode({"page": page}), ""))


def result_nodes(result: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for listing in result.get("galleryListings", []):
        if isinstance(listing, dict):
            yield listing
    for edge in result.get("listings", {}).get("edges", []):
        node = edge.get("node") if isinstance(edge, dict) else None
        if isinstance(node, dict):
            yield node


def to_offer(node: dict[str, Any], language: str = "fr") -> dict[str, Any]:
    location = node.get("postcodeInformation") or {}
    localization = node.get("localization") or {}
    slug = (node.get("seoInformation") or {}).get(f"{language}Slug")
    listing_id = node.get("listingID")
    return {
        "listingID": listing_id,
        "title": localization.get("title", node.get("title")),
        "price": node.get("formattedPrice"),
        "date": node.get("timestamp"),
        "description": localization.get("body", node.get("body")),
        "city": location.get("locationName"),
        "postcode": location.get("postcode"),
        "url": (
            f"https://www.anibis.ch/{language}/vi/{slug + '/' if slug else ''}{listing_id}"
            if listing_id
            else None
        ),
    }


def scrape(
    query: str,
    *,
    category: str | None = None,
    language: str = "fr",
    delay: float = 1.0,
    timeout: float = 30.0,
    limit: int | None = None,
) -> Iterator[dict[str, Any]]:
    first_url = f"https://www.anibis.ch/{language}/q?{urlencode({'query': query})}"
    result, canonical_url = fetch_page(first_url, timeout)
    edges = result.get("listings", {}).get("edges", [])
    total = int(result.get("listings", {}).get("totalCount", 0))
    page_size = len(edges)
    pages = math.ceil(total / page_size) if page_size else 1
    seen: set[str] = set()
    emitted = 0

    for page in range(1, pages + 1):
        if page > 1:
            time.sleep(delay)
            result, _ = fetch_page(page_url(canonical_url, page), timeout)
        print(f"page {page}/{pages}", file=sys.stderr)

        for node in result_nodes(result):
            if category and (node.get("primaryCategory") or {}).get(
                "categoryID"
            ) != category:
                continue
            listing_id = str(node.get("listingID", ""))
            if listing_id and listing_id in seen:
                continue
            if listing_id:
                seen.add(listing_id)
            offer = to_offer(node, language)
            offer["lastSeen"] = datetime.now(UTC).isoformat()
            yield offer
            emitted += 1
            if limit is not None and emitted >= limit:
                return


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def non_negative_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return number


def positive_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export every Anibis result for a search query as JSON Lines."
    )
    parser.add_argument("query", help='search text, for example "macbook"')
    parser.add_argument("-o", "--output", type=Path, help="output file (default: stdout)")
    parser.add_argument("--database", type=Path, help="upsert offers into a SQLite file")
    parser.add_argument("--category", help='exact primary category ID, e.g. "computers"')
    parser.add_argument("--language", choices=("de", "fr", "it"), default="fr")
    parser.add_argument("--delay", type=non_negative_float, default=1.0)
    parser.add_argument("--timeout", type=positive_float, default=30.0)
    parser.add_argument("--limit", type=positive_int, help="stop after this many results")
    return parser


def write_offers(
    offers: Iterable[dict[str, Any]],
    output: TextIO | None = None,
    database: Path | None = None,
) -> int:
    connection = sqlite3.connect(database, timeout=30) if database else None
    written = 0
    try:
        if connection:
            connection.execute(CREATE_OFFERS_TABLE)
            history_exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                ("offer_price_history",),
            ).fetchone()
            connection.execute(CREATE_PRICE_HISTORY_TABLE)
            if not history_exists:
                connection.execute(
                    """
                    INSERT INTO offer_price_history (listingID, price, observedAt)
                    SELECT listingID, price, lastSeen FROM offers
                    """
                )

        for offer in offers:
            if connection:
                listing_id = offer.get("listingID")
                url = offer.get("url")
                if not listing_id:
                    raise ScraperError("Offer is missing its listingID and cannot be stored")
                if not url:
                    raise ScraperError("Offer is missing its URL and cannot be stored")
                price = offer.get("price")
                connection.execute(
                    INSERT_PRICE_CHANGE,
                    (
                        str(listing_id),
                        price,
                        offer["lastSeen"],
                        str(listing_id),
                        price,
                    ),
                )
                connection.execute(
                    UPSERT_OFFER,
                    (
                        str(listing_id),
                        offer.get("title"),
                        price,
                        offer.get("date"),
                        offer.get("description"),
                        offer.get("city"),
                        offer.get("postcode"),
                        url,
                        offer["lastSeen"],
                    ),
                )
            if output:
                json.dump(offer, output, ensure_ascii=False)
                output.write("\n")
            written += 1

        if connection:
            connection.commit()
    except BaseException:
        if connection:
            connection.rollback()
        raise
    finally:
        if connection:
            connection.close()
    return written


def refresh_database(
    database: Path,
    query: str = "macbook",
    *,
    category: str | None = "computers",
    language: str = "fr",
    delay: float = 1.0,
    timeout: float = 30.0,
    limit: int | None = None,
) -> int:
    """Refresh ``database`` and return the number of scraped offers."""
    return write_offers(
        scrape(
            query,
            category=category,
            language=language,
            delay=delay,
            timeout=timeout,
            limit=limit,
        ),
        database=database,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.query.strip():
        print("error: query must not be empty", file=sys.stderr)
        return 2
    category = args.category.strip() if args.category else None
    if args.category is not None and not category:
        print("error: category must not be empty", file=sys.stderr)
        return 2

    try:
        output_context = (
            args.output.open("w", encoding="utf-8")
            if args.output
            else nullcontext(sys.stdout)
        )
        with output_context as output:
            write_offers(
                scrape(
                    args.query.strip(),
                    category=category,
                    language=args.language,
                    delay=args.delay,
                    timeout=args.timeout,
                    limit=args.limit,
                ),
                output,
                args.database,
            )
    except (OSError, ScraperError, sqlite3.Error) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
