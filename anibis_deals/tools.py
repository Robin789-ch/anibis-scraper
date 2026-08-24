"""Small maintenance tools for the local database."""

import argparse
import sqlite3
from contextlib import closing
from pathlib import Path

TABLES = ("offers", "offer_price_history", "parsed", "notifications")
DEFAULT_DATABASE = Path(__file__).parents[1] / "offers.sqlite3"


def clear_table_rows(database: Path, table: str) -> int:
    """Delete every row from one known table, preserving its schema."""
    if table not in TABLES:
        raise ValueError(f"table must be one of: {', '.join(TABLES)}")
    if not database.is_file():
        raise FileNotFoundError(database)

    with closing(sqlite3.connect(database)) as connection:
        if not connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone():
            return 0
        deleted = connection.execute(f'DELETE FROM "{table}"').rowcount
        connection.commit()
        return deleted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Explicit, schema-preserving database maintenance tools."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    clear = commands.add_parser(
        "clear-table-rows",
        help="delete all rows from one table without deleting the table",
    )
    clear.add_argument("table", choices=TABLES)
    clear.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    clear.add_argument(
        "--yes", action="store_true", help="skip confirmation (for scripts)"
    )
    args = parser.parse_args(argv)

    if not args.yes:
        print(
            f"This will delete ALL ROWS from '{args.table}' in {args.database}.\n"
            "The table, its schema, and every other table will be preserved."
        )
        if input("Type 'yes' to continue: ").strip().lower() != "yes":
            print("Cancelled; nothing was changed.")
            return 0

    try:
        deleted = clear_table_rows(args.database, args.table)
    except (OSError, sqlite3.Error, ValueError) as error:
        parser.error(str(error))
    print(f"Cleared {deleted} rows from {args.table}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
