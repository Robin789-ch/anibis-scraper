import sqlite3
import unittest
from contextlib import closing
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from anibis_deals.tools import clear_table_rows, main


class ToolsTest(unittest.TestCase):
    def test_clear_table_only_empties_the_requested_table(self) -> None:
        with TemporaryDirectory() as directory:
            database = Path(directory) / "offers.sqlite3"
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("CREATE TABLE offers (listingID TEXT)")
                connection.execute("CREATE TABLE parsed (listingID TEXT)")
                connection.execute("INSERT INTO offers VALUES ('1')")
                connection.executemany("INSERT INTO parsed VALUES (?)", [("1",), ("2",)])
                connection.commit()

            self.assertEqual(clear_table_rows(database, "parsed"), 2)

            with closing(sqlite3.connect(database)) as connection:
                self.assertEqual(connection.execute("SELECT count(*) FROM parsed").fetchone()[0], 0)
                self.assertEqual(connection.execute("SELECT count(*) FROM offers").fetchone()[0], 1)
                self.assertIsNotNone(
                    connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'parsed'"
                    ).fetchone()
                )

            with self.assertRaises(ValueError):
                clear_table_rows(database, "not_a_project_table")

    def test_command_cancels_unless_explicitly_confirmed(self) -> None:
        with TemporaryDirectory() as directory:
            database = Path(directory) / "offers.sqlite3"
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("CREATE TABLE parsed (listingID TEXT)")
                connection.execute("INSERT INTO parsed VALUES ('1')")
                connection.commit()

            with patch("builtins.input", return_value="no"), patch(
                "sys.stdout", new_callable=StringIO
            ) as output:
                self.assertEqual(
                    main(
                        [
                            "clear-table-rows",
                            "parsed",
                            "--database",
                            str(database),
                        ]
                    ),
                    0,
                )

            self.assertIn("nothing was changed", output.getvalue())
            with closing(sqlite3.connect(database)) as connection:
                self.assertEqual(
                    connection.execute("SELECT count(*) FROM parsed").fetchone()[0], 1
                )


if __name__ == "__main__":
    unittest.main()
