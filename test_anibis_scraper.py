import json
import unittest
from unittest.mock import patch

from anibis_scraper import page_url, parse_search_page, result_nodes, scrape, to_offer


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


if __name__ == "__main__":
    unittest.main()
