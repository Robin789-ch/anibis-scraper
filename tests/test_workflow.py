import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pandas as pd

from anibis_deals.analysis import rank_prospects
from anibis_deals.parser import MacBookModel, parse_database
from anibis_deals.telegram import notify_new_prospects


class WorkflowTest(unittest.TestCase):
    def test_price_model_ranks_the_cheapest_equivalent_listing_first(self) -> None:
        market = pd.DataFrame(
            [
                {
                    "listingID": str(index),
                    "serie": "Air",
                    "generationCPU": "M2",
                    "familyCPU": "Base",
                    "RAM": 16,
                    "storageGB": 512,
                    "screenSize": 13,
                    "batteryHealth": 90,
                    "year": 2023,
                    "price": 300 if index == 0 else 900,
                }
                for index in range(100)
            ]
        )

        ranked = rank_prospects(market)

        self.assertEqual(ranked.iloc[0]["listingID"], "0")
        self.assertEqual(ranked.iloc[0]["rankPosition"], 1)

    @patch("anibis_deals.parser.agent.run", new_callable=AsyncMock)
    def test_parser_only_processes_unparsed_offers(self, run) -> None:
        run.return_value = SimpleNamespace(
            output=MacBookModel(
                serie="Air",
                generationCPU="M2",
                familyCPU="Base",
                RAM=16,
                storageSize=512,
                screenSize=13,
                damaged=False,
                batteryHealth=90,
                year=2023,
            )
        )
        with TemporaryDirectory() as directory:
            database = Path(directory) / "offers.sqlite3"
            with closing(sqlite3.connect(database)) as connection:
                connection.execute(
                    "CREATE TABLE offers (listingID TEXT, title TEXT, description TEXT)"
                )
                connection.execute("INSERT INTO offers VALUES ('1', 'Air', 'Nice')")
                connection.commit()

            with self.assertLogs("anibis_deals.parser", level="INFO") as logs:
                self.assertEqual(parse_database(database), 1)
            self.assertEqual(parse_database(database), 0)

        run.assert_awaited_once()
        messages = [record.getMessage() for record in logs.records]
        self.assertIn("Parser batch started: 1/1 (1 offers)", messages)
        self.assertIn("Parser progress: 1/1 offers", messages)

    def test_successful_notification_is_sent_only_once(self) -> None:
        prospect = {
            "listingID": "1",
            "serie": "Pro",
            "generationCPU": "M3",
            "familyCPU": "Pro",
            "RAM": 18,
            "storageGB": 512,
            "screenSize": 14,
            "price": 1_190,
            "expectedPrice": 1_650,
            "url": "https://www.anibis.ch/listing/1",
        }
        with TemporaryDirectory() as directory:
            database = Path(directory) / "offers.sqlite3"
            with (
                patch("anibis_deals.telegram.send_message") as send,
                patch("anibis_deals.telegram.deal_plot", return_value=object()),
                patch("matplotlib.pyplot.close"),
            ):
                market = pd.DataFrame([prospect])
                self.assertEqual(notify_new_prospects(database, [prospect], market), 1)
                self.assertEqual(notify_new_prospects(database, [prospect], market), 0)

        send.assert_called_once()

    @patch("main.notify_new_prospects", return_value=1)
    @patch(
        "main.find_best_prospects",
        return_value=([{"listingID": "1"}], pd.DataFrame()),
    )
    @patch("main.parse_database", return_value=2)
    @patch("main.refresh_database", return_value=10)
    def test_main_runs_the_complete_workflow(self, refresh, parse, find, notify) -> None:
        from main import main

        database = Path("test.sqlite3")
        with self.assertLogs("main", level="INFO") as logs:
            main(database)

        refresh.assert_called_once_with(database, "macbook", category="computers")
        parse.assert_called_once_with(database)
        find.assert_called_once_with(database, 0.01)
        notify.assert_called_once()
        self.assertEqual(notify.call_args.args[:2], (database, [{"listingID": "1"}]))
        messages = [record.getMessage() for record in logs.records]
        self.assertIn("Step completed: scrape (offers=10)", messages)
        self.assertIn("Step completed: parse (offers=2)", messages)
        self.assertIn("Step completed: rank (prospects=1)", messages)
        self.assertIn("Step completed: notify (notifications=1)", messages)

    @patch("main.parse_database", side_effect=RuntimeError("LLM unavailable"))
    @patch("main.refresh_database", return_value=10)
    def test_main_logs_the_failing_step(self, refresh, parse) -> None:
        from main import main

        with self.assertLogs("main", level="INFO") as logs:
            with self.assertRaisesRegex(RuntimeError, "LLM unavailable"):
                main(Path("test.sqlite3"))

        self.assertIn("Workflow failed during step: parse", logs.output[-1])
        self.assertIsNotNone(logs.records[-1].exc_info)


if __name__ == "__main__":
    unittest.main()
