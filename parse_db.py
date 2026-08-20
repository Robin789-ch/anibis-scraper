import asyncio
import sqlite3
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
    year: int = Field(ge=0, le=2026)


load_dotenv()

agent = Agent(
    # "openrouter:nvidia/nemotron-3.5-lightning:free",
    "openrouter:deepseek/deepseek-v4-flash-0731",
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
        "damaged: True if the laptop is damaged, False if not damaged.\n"
        "batteryHealth: Percentage of the battery health as an integer. Give an estimate if "
        "the description contains only a qualitative estimation. A full battery on Apple Silicon "
        "typically last 15 to 20 hours. Write 0 if no information is given at all.\n"
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


def clear_table(cursor: sqlite3.Cursor):
    cursor.execute("DROP TABLE IF EXISTS parsed")


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
                            damaged BOOLEAN,
                            batteryHealth INTEGER,
                            year INTEGER
                            );"""
    cursor.execute(new_table_query)


def init_db_connection(db):
    sqliteConnection = sqlite3.connect(db)

    print(f"Successful connection to {db}")
    return sqliteConnection


def parse_db(sqliteConnection, max_rq=20):

    cursor = sqliteConnection.cursor()

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
    queries = cursor.fetchall()

    if len(queries) == 0:
        return 0

    print(f"Unprocessed: {len(queries)} rows")

    num_rq = max(max_rq, len(queries))
    results = asyncio.run(LLM_Parser_Vectorized(queries[:num_rq]))

    rows = [
        (
            listingID,
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
        damaged,
        batteryHealth,
        year
        ) 
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
        rows,
    )

    print(f"Successfully processed {len(results)} offers.\n")
    sqliteConnection.commit()
    return 1


if __name__ == "__main__":
    # asyncio.run(LLM_Parser())
    conn = init_db_connection("offers.sqlite3")
    cursor = conn.cursor()

    # Clear the parsed table
    # clear_table(cursor)

    # cursor.execute("DELETE FROM parsed WHERE listingID = ?", ("54763724",))
    # conn.commit()

    # Create the 'parsed' table if it does not exist.
    create_parsed_table(cursor)

    parse_db(conn)

    print("All waiting offers have been processed !")
