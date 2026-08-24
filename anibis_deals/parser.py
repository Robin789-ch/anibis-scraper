"""Parse unprocessed offers with an LLM."""

import asyncio
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from pydantic_ai import Agent


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
        "You are an expert in computer hardware. Label the MacBook in the seller "
        "listing. Use serie Air, Pro, or Other; generationCPU M1 through M5 or "
        "Other; and familyCPU Base, Pro, Max, Ultra, or Other. If Apple Silicon "
        "family is omitted, use Base. Return RAM and storageSize in GB, screenSize "
        "in inches, damaged as a boolean, batteryHealth from 0 to 100, and year. "
        "Use 0 when battery health or year is absent. Estimate battery health "
        "pessimistically from qualitative descriptions."
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
    for start in range(0, len(rows), batch_size):
        parsed.extend(
            await asyncio.gather(*map(_parse_offer, rows[start : start + batch_size]))
        )
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
        if not rows:
            return 0

        parsed = asyncio.run(_parse_offers(rows, batch_size))
        connection.executemany(INSERT_PARSED, parsed)
        connection.commit()

    return len(parsed)
