"""Run the complete Anibis prospect workflow."""

import logging
from pathlib import Path

from anibis_deals.analysis import find_best_prospects
from anibis_deals.parser import parse_database
from anibis_deals.scraper import refresh_database
from anibis_deals.telegram import notify_new_prospects

DATABASE = Path(__file__).with_name("offers.sqlite3")
logger = logging.getLogger(__name__)


def main(
    database: Path = DATABASE,
    query: str = "macbook",
    category: str = "computers",
    top_share: float = 0.01,
) -> None:
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger.setLevel(logging.INFO)
    logging.getLogger("anibis_deals").setLevel(logging.INFO)
    logger.info(
        "Workflow started: database=%s query=%r category=%r top_share=%s",
        database,
        query,
        category,
        top_share,
    )

    step = "scrape"
    try:
        logger.info("Step started: %s", step)
        scraped = refresh_database(database, query, category=category)
        logger.info("Step completed: %s (offers=%d)", step, scraped)

        step = "parse"
        logger.info("Step started: %s", step)
        parsed = parse_database(database)
        logger.info("Step completed: %s (offers=%d)", step, parsed)

        step = "rank"
        logger.info("Step started: %s", step)
        prospects = find_best_prospects(database, top_share)
        logger.info("Step completed: %s (prospects=%d)", step, len(prospects))

        step = "notify"
        logger.info("Step started: %s", step)
        notified = notify_new_prospects(database, prospects)
        logger.info("Step completed: %s (notifications=%d)", step, notified)
    except Exception:
        logger.exception("Workflow failed during step: %s", step)
        raise

    logger.info(
        "Workflow completed: scraped=%d parsed=%d prospects=%d notified=%d",
        scraped,
        parsed,
        len(prospects),
        notified,
    )


if __name__ == "__main__":
    main()
