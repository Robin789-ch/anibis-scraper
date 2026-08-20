import asyncio
import sqlite3
from typing import Literal

import pandas as pd
from dotenv import load_dotenv
from keyring.backends.macOS.api import create_query
from pydantic import BaseModel, Field
from pydantic_ai import Agent


class MacBookModel(BaseModel):
    serie: Literal["Air", "Pro", "Other"]
    generationCPU: Literal["M1", "M2", "M3", "M4", "M5", "Other"]
    familyCPU: Literal["Base", "Pro", "Max", "Ultra", "Other"]
    RAM: int
    storageSize: int
    screenSize: int
    year: int = Field(ge=0, le=2026)


load_dotenv()

agent = Agent(
    "openrouter:nvidia/nemotron-3.5-lightning:free",
    output_type=MacBookModel,
    instructions=(
        "You are an expert in computer hardware. Your task is to label MacBook "
        "computers from online seller listings.\n"
        "Return the following fields in this exact format:\n\n"
        "serie: 'Air' for MacBook Air, 'Pro' for MacBook Pro, or 'Other' if the "
        "listing is not for a MacBook.\n"
        "generationCPU: 'M1' through 'M5' for the corresponding Apple Silicon "
        "generation, or 'Other' if it does not use Apple Silicon.\n"
        "familyCPU: For Apple Silicon only, use 'Base', 'Pro', 'Max', or 'Ultra'. "
        "Use 'Other' if it is not Apple Silicon. If the Apple Silicon family is "
        "not specified, use 'Base'.\n"
        "RAM: Installed RAM or unified memory, in GB.\n"
        "storageSize: SSD storage capacity, in GB.\n"
        "screenSize: Screen diagonal, in inches.\n"
        "year: Production year. Use '0' if the year is not mentioned."
    ),
)


async def LLM_Parser(query):

    listingID, title, description = query
    prompt = f"title: {title},\n\n description: {description}"
    result = await agent.run(prompt)

    return listingID, result.output


async def LLM_Parser_Vectorized(queries):
    return await asyncio.gather(*(LLM_Parser(query) for query in queries))


def create_parsed_table(cursor: sqlite3.Cursor):
    new_table_query = """CREATE TABLE IF NOT EXISTS 
                        parsed (
                            listingID TEXT PRIMARY KEY,
                            serie STRING,
                            generationCPU STRING,
                            familyCPU STRING,
                            RAM INTEGER,
                            storageSize INTEGER,
                            screenSize INTEGER,
                            year INTEGER
                            );"""
    cursor.execute(new_table_query)


def parse_db():

    sqliteConnection = sqlite3.connect("offers.sqlite3")
    cursor = sqliteConnection.cursor()

    # Create the 'parsed' table if it does not exist.
    create_parsed_table(cursor)

    unprocessed = """SELECT 
                        listingID,
                        title,
                        description
                    FROM offers
                    WHERE listingID NOT IN (
                        SELECT listingID FROM parsed
                    )
                    """

    cursor.execute(unprocessed)
    rows = cursor.fetchall()

    print(f"Unprocessed: {len(rows)} rows")

    queries = rows[:3]

    results = asyncio.run(LLM_Parser_Vectorized(queries))

    rows = [
        (
            listingID,
            spec.serie,
            spec.generationCPU,
            spec.familyCPU,
            spec.RAM,
            spec.storageSize,
            spec.screenSize,
            spec.year,
        )
        for listingID, spec in results
    ]

    cursor.executemany(
        """INSERT INTO parsed 
        (
        listingID,
        serie,
        generationCPU,
        familyCPU,
        RAM,
        storageSize,
        screenSize,
        year
        ) 
        VALUES (?,?,?,?,?,?,?,?)""",
        rows,
    )

    sqliteConnection.commit()
    return


if __name__ == "__main__":
    # asyncio.run(LLM_Parser())
    parse_db()
