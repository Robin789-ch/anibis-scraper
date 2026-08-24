"""Parse unprocessed offers with an LLM."""

import asyncio
import logging
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from pydantic_ai import Agent

logger = logging.getLogger(__name__)


class MacBookModel(BaseModel):
    serie: Literal["Air", "Pro", "Other"]
    generationCPU: Literal["M1", "M2", "M3", "M4", "M5", "Other"]
    familyCPU: Literal["Base", "Pro", "Max", "Ultra", "Other"]
    RAM: int
    storageSize: int
    screenSize: int
    damaged: bool
    batteryHealth: int = Field(ge=0, le=100)
    year: int = Field(ge=0, le=date.today().year)


load_dotenv()

agent = Agent(
    "openrouter:deepseek/deepseek-v4-flash-0731",
    output_type=MacBookModel,
    instructions=(
        "You are an expert in computer hardware. Label MacBook computers from "
        "online seller listings.\n"
        "serie: Air for MacBook Air, Pro for MacBook Pro, or Other if the listing "
        "is not for a MacBook.\n"
        "generationCPU: M1 through M5 for the corresponding Apple Silicon "
        "generation, or Other for Intel, non-Apple-Silicon, or unknown CPUs.\n"
        "familyCPU: Base for an Apple Silicon chip without a Pro, Max, or Ultra "
        "suffix; otherwise Pro, Max, Ultra, or Other for non-Apple-Silicon CPUs.\n"
        "RAM: Installed RAM or unified memory in GB.\n"
        "storageSize: SSD storage capacity in GB.\n"
        "screenSize: Screen diagonal in inches.\n"
        "damaged: True if the laptop is damaged, otherwise False.\n"
        "batteryHealth: Maximum battery capacity from 0 to 100. Use a stated "
        "percentage when available; otherwise estimate pessimistically from a "
        "qualitative description.\n"
        "year: Production year.\n"
        "Use 0 for any unknown numeric value. Do not invent missing specifications."
    ),
)

CREATE_PARSED_TABLE = """
CREATE TABLE IF NOT EXISTS parsed (
    listingID TEXT PRIMARY KEY,
    serie TEXT,
    generationCPU TEXT,
    familyCPU TEXT,
    RAM INTEGER,
    storageSize INTEGER,
    screenSize INTEGER,
    damaged BOOLEAN,
    batteryHealth INTEGER,
    year INTEGER
)
"""

INSERT_PARSED = """
INSERT INTO parsed (
    listingID, serie, generationCPU, familyCPU, RAM, storageSize,
    screenSize, damaged, batteryHealth, year
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


async def _parse_offer(row: tuple[str, str | None, str | None]) -> tuple:
    listing_id, title, description = row
    result = await agent.run(f"title: {title}\n\ndescription: {description}")
    spec = result.output
    return (
        listing_id,
        spec.serie,
        spec.generationCPU,
        spec.familyCPU,
        spec.RAM,
        spec.storageSize,
        spec.screenSize,
        spec.damaged,
        spec.batteryHealth,
        spec.year,
    )


async def _parse_offers(rows: list[tuple], batch_size: int) -> list[tuple]:
    parsed = []
    batch_count = (len(rows) + batch_size - 1) // batch_size
    for start in range(0, len(rows), batch_size):
        batch_number = start // batch_size + 1
        batch = rows[start : start + batch_size]
        logger.info(
            "Parser batch started: %d/%d (%d offers)",
            batch_number,
            batch_count,
            len(batch),
        )
        parsed.extend(
            await asyncio.gather(*map(_parse_offer, batch))
        )
        logger.info("Parser progress: %d/%d offers", len(parsed), len(rows))
    return parsed


def parse_database(database: Path, batch_size: int = 20) -> int:
    """Parse every offer not already present in ``parsed``."""
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")

    with closing(sqlite3.connect(database)) as connection:
        connection.execute(CREATE_PARSED_TABLE)
        connection.commit()
        rows = connection.execute(
            """
            SELECT listingID, title, description
            FROM offers
            WHERE listingID NOT IN (SELECT listingID FROM parsed)
            """
        ).fetchall()
        logger.info("Parser found %d unparsed offers", len(rows))
        if not rows:
            return 0

        parsed = asyncio.run(_parse_offers(rows, batch_size))
        connection.executemany(INSERT_PARSED, parsed)
        connection.commit()

    return len(parsed)
