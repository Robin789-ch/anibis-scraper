import io
import json
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from anibis_scraper import (
    page_url,
    parse_search_page,
    result_nodes,
    scrape,
    to_offer,
    write_offers,
)


class ScraperTest(unittest.TestCase):
    def test_parses_next_data_and_maps_requested_fields(self) -> None:
        node = {
            "listingID": "42",
            "title": "MacBook",
            "formattedPrice": "500.-",
            "timestamp": "2026-08-12T12:00:00+02:00",
            "body": "Good condition",
            "postcodeInformation": {"locationName": "Bern", "postcode": "3000"},
            "seoInformation": {"frSlug": "berne/informatique/macbook"},
        }
        payload = {
            "props": {
                "pageProps": {
                    "dehydratedState": {
                        "queries": [
                            {
                                "queryKey": ["SearchListingsByConstraints", 0],
                                "state": {
                                    "data": {
                                        "listings": {
                                            "totalCount": 1,
                                            "edges": [{"node": node}],
                                        },
                                        "galleryListings": [],
                                    }
                                },
                            }
                        ]
                    }
                }
            }
        }
        html = (
            '<script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(payload)
            + "</script>"
        )

        result = parse_search_page(html)
        offer = to_offer(next(result_nodes(result)))

        self.assertEqual(
            offer,
            {
                "listingID": "42",
                "title": "MacBook",
                "price": "500.-",
                "date": "2026-08-12T12:00:00+02:00",
                "description": "Good condition",
                "city": "Bern",
                "postcode": "3000",
                "url": "https://www.anibis.ch/fr/vi/berne/informatique/macbook/42",
            },
        )

    def test_page_url_replaces_existing_query_parameters(self) -> None:
        self.assertEqual(
            page_url("https://www.anibis.ch/fr/q/cherche/token?sorting=newest", 2),
            "https://www.anibis.ch/fr/q/cherche/token?page=2",
        )

    @patch("anibis_scraper.fetch_page")
    def test_filters_by_primary_category_before_applying_limit(self, fetch_page) -> None:
        nodes = [
            {
                "listingID": "1",
                "title": "MacBook sleeve",
                "primaryCategory": {"categoryID": "computerComponentsAccessories"},
            },
            {
                "listingID": "2",
                "title": "MacBook Pro",
                "primaryCategory": {"categoryID": "computers"},
            },
        ]
        fetch_page.return_value = (
            {
                "listings": {
                    "totalCount": len(nodes),
                    "edges": [{"node": node} for node in nodes],
                },
                "galleryListings": [],
            },
            "https://www.anibis.ch/fr/q/cherche/token",
        )

        offers = list(scrape("macbook", category="computers", limit=1))

        self.assertEqual([offer["title"] for offer in offers], ["MacBook Pro"])
        self.assertIn("lastSeen", offers[0])

    def test_database_upserts_offer_and_updates_last_seen(self) -> None:
        offer = {
            "listingID": "42",
            "title": "MacBook Pro",
            "price": "500.-",
            "date": "2026-08-12T12:00:00+02:00",
            "description": "Good condition",
            "city": "Bern",
            "postcode": "3000",
            "url": "https://www.anibis.ch/fr/vi/berne/informatique/macbook/42",
            "lastSeen": "2026-08-12T12:01:00+00:00",
        }

        with TemporaryDirectory() as directory:
            database = Path(directory) / "offers.sqlite3"
            write_offers([offer], io.StringIO(), database)
            write_offers(
                [{**offer, "lastSeen": "2026-08-13T07:00:00+00:00"}],
                io.StringIO(),
                database,
            )
            write_offers(
                [
                    {
                        **offer,
                        "price": "450.-",
                        "lastSeen": "2026-08-13T08:00:00+00:00",
                    }
                ],
                io.StringIO(),
                database,
            )

            with sqlite3.connect(database) as connection:
                rows = connection.execute(
                    "SELECT listingID, price, lastSeen FROM offers"
                ).fetchall()
                price_history = connection.execute(
                    """
                    SELECT listingID, price, observedAt
                    FROM offer_price_history
                    ORDER BY observedAt
                    """
                ).fetchall()

        self.assertEqual(rows, [("42", "450.-", "2026-08-13T08:00:00+00:00")])
        self.assertEqual(
            price_history,
            [
                ("42", "500.-", "2026-08-12T12:01:00+00:00"),
                ("42", "450.-", "2026-08-13T08:00:00+00:00"),
            ],
        )

    def test_existing_database_seeds_current_price_history(self) -> None:
        with TemporaryDirectory() as directory:
            database = Path(directory) / "offers.sqlite3"
            with sqlite3.connect(database) as connection:
                connection.execute(
                    """
                    CREATE TABLE offers (
                        listingID TEXT PRIMARY KEY, title TEXT, price TEXT,
                        date TEXT, description TEXT, city TEXT, postcode TEXT,
                        url TEXT NOT NULL, lastSeen TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    "INSERT INTO offers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "42",
                        "MacBook Pro",
                        "500.-",
                        None,
                        None,
                        None,
                        None,
                        "https://www.anibis.ch/fr/vi/macbook/42",
                        "2026-08-12T12:01:00+00:00",
                    ),
                )

            write_offers(
                [
                    {
                        "listingID": "42",
                        "title": "MacBook Pro",
                        "price": "500.-",
                        "date": None,
                        "description": None,
                        "city": None,
                        "postcode": None,
                        "url": "https://www.anibis.ch/fr/vi/macbook/42",
                        "lastSeen": "2026-08-13T08:00:00+00:00",
                    }
                ],
                io.StringIO(),
                database,
            )

            with sqlite3.connect(database) as connection:
                history = connection.execute(
                    "SELECT price, observedAt FROM offer_price_history"
                ).fetchall()

        self.assertEqual(history, [("500.-", "2026-08-12T12:01:00+00:00")])


if __name__ == "__main__":
    unittest.main()
