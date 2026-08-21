# Anibis scraper

Exports every result from an Anibis keyword search as newline-delimited JSON
(JSONL). Each line contains exactly:

- `listingID` (Anibis's stable offer identifier)
- `title`
- `price` (the display value, such as `"500.-"` or `"Gratuit"`)
- `date` (ISO 8601)
- `description`
- `city`
- `postcode`
- `url`
- `lastSeen` (UTC time when the offer was parsed)

## Important usage constraint

Anibis's current [conditions of use](https://www.anibis.help/hc/fr/articles/14609777649170-Conditions-d-utilisation)
prohibit automated scripts that collect information from the site. Obtain
written permission from Anibis before using this scraper. `robots.txt` does not
disallow public search pages, but that is not a substitute for permission.

This project only reads public, server-rendered search pages. It does not use
the disallowed `/api/` path, bypass access controls, solve CAPTCHAs, or collect
seller account/contact fields. Keep the default delay or increase it.

Requires Python 3.11 or newer. The project has no third-party dependencies.

## Run

```bash
python3 anibis_scraper.py "macbook" --output offers.jsonl
```

Filter locally by Anibis's exact primary category ID:

```bash
python3 anibis_scraper.py "macbook" --category computers --output offers.jsonl
```

Category filtering happens after each search page is downloaded, so it reduces
the output but not the number of requests to Anibis.

Optionally upsert every returned offer into a local SQLite database while still
writing the normal JSONL output:

```bash
python3 anibis_scraper.py "macbook" --database offers.sqlite3 --output offers.jsonl
```

The `offers` table uses Anibis's listing ID as its primary key. Running the
scraper again updates the existing offer fields and `lastSeen` instead of
inserting a duplicate. The `offer_price_history` table stores the initial raw
price string and appends another row only when that string changes. Its
`observedAt` value is when the scraper first saw the new price. Existing
databases are seeded with their currently known price when the history table is
first created. All database writes for a run use one transaction.

If the output file already exists, it is overwritten.

By default the scraper follows all result pages sequentially with a one-second
delay. Progress goes to stderr, so stdout can be redirected safely:

```bash
python3 anibis_scraper.py "macbook" > offers.jsonl
```

Useful options:

```text
--language de|fr|it   Site language (default: fr)
--category ID         Keep offers whose primary category exactly matches ID
--database PATH       Upsert offers into a SQLite database
--delay SECONDS       Pause between pages (default: 1.0)
--timeout SECONDS     HTTP timeout (default: 30.0)
--limit COUNT         Stop early; useful for a small verification run
```

Run the checks with:

```bash
python3 -m unittest -v
```

## Telegram good-buy notifications

Create a bot with Telegram's `@BotFather`, send that bot any message, then set
its token and your chat ID:

```bash
export TELEGRAM_BOT_TOKEN="123456:replace-me"
export TELEGRAM_CHAT_ID="123456789"
```

Call `send_message` with the listing details and either an image or a function
that returns one:

```python
from telegram_bot import dummy_plot, send_message

send_message(
    specs="MacBook Pro 14-inch · M3 Pro · 18 GB RAM · 512 GB SSD",
    price=1190,
    expectedPrice=1650,
    url="https://www.anibis.ch/",
    image=lambda: dummy_plot(expected_price=1650, actual_price=1190),
)
```

For a dummy end-to-end notification, run `python3 telegram_bot.py`. The `image`
argument also accepts PNG bytes, a binary file, an image path, or a Matplotlib
figure. No real listing data is connected yet.

## Why plain HTTP instead of a browser?

The search UI redirects `/{language}/q?query=...` to a canonical search URL.
Each result page embeds the same structured listing data used by the React UI
inside its `__NEXT_DATA__` script, including all requested fields. Reading
that document is faster, requires no browser runtime, and avoids brittle CSS
selectors. The scraper follows the canonical URL with `?page=2`, `?page=3`,
and so on until the reported total is exhausted.
