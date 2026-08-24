# Anibis deal finder

Refreshes Anibis MacBook listings, classifies new listings with an LLM, ranks
the best-priced 1%, and sends each previously unnotified prospect to Telegram.

## Setup

Create `.env` with:

```dotenv
OPENROUTER_API_KEY=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

Then run the complete workflow:

```bash
uv run python main.py
```

Defaults are the `macbook` query, the `computers` category, French listings,
`offers.sqlite3`, and the top 1%. Successful notifications are recorded in the
database, so later runs do not resend them.

Run the local checks without network calls:

```bash
uv run python -m unittest discover -v
```

## Layout

```text
main.py                     complete workflow
anibis_deals/
  scraper.py                Anibis → SQLite
  parser.py                 unparsed SQLite rows → LLM labels
  analysis.py               robust price model → top prospects
  telegram.py               new prospects → Telegram
tests/                      network-free checks
Price_analysis.ipynb        exploratory source of the price model
```

The scraper can still be run alone when needed:

```bash
uv run python -m anibis_deals.scraper macbook \
  --category computers --database offers.sqlite3 --output offers.jsonl
```

Delete the rows from one table without deleting its schema or touching the
other tables (the command asks for confirmation):

```bash
uv run python -m anibis_deals.tools clear-table-rows parsed
```

Clearing `parsed` makes the next workflow run classify the whole stored dataset
again. Other choices are `offers`, `offer_price_history`, and `notifications`.
Automated scripts must opt in explicitly with `--yes`.

## Usage constraint

Anibis's conditions of use prohibit automated scripts that collect information
from the site. Obtain written permission from Anibis before running the scraper.
The implementation only reads public server-rendered search pages; it does not
use private APIs, bypass access controls, or collect seller contact details.
