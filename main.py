"""Run the complete Anibis prospect workflow."""

from pathlib import Path

from anibis_deals.analysis import find_best_prospects
from anibis_deals.parser import parse_database
from anibis_deals.scraper import refresh_database
from anibis_deals.telegram import notify_new_prospects

DATABASE = Path(__file__).with_name("offers.sqlite3")


def main(
    database: Path = DATABASE,
    query: str = "macbook",
    category: str = "computers",
    top_share: float = 0.01,
) -> None:
    scraped = refresh_database(database, query, category=category)
    parsed = parse_database(database)
    prospects = find_best_prospects(database, top_share)
    notified = notify_new_prospects(database, prospects)
    print(
        f"Done: {scraped} scraped, {parsed} parsed, "
        f"{len(prospects)} top prospects, {notified} new notifications."
    )


if __name__ == "__main__":
    main()
