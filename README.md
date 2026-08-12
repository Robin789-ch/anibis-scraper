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

## Setup

```bash
uv sync
```

The project has no third-party Python dependencies.

## Run

```bash
uv run python anibis_scraper.py "macbook" --output offers.jsonl
```

Filter locally by Anibis's exact primary category ID:

```bash
uv run python anibis_scraper.py "macbook" --category computers --output offers.jsonl
```

Category filtering happens after each search page is downloaded, so it reduces
the output but not the number of requests to Anibis.

Optionally upsert every returned offer into a local SQLite database while still
writing the normal JSONL output:

```bash
uv run python anibis_scraper.py "macbook" --database offers.sqlite3 --output offers.jsonl
```

The `offers` table uses Anibis's listing ID as its primary key. Running the
scraper again updates the existing offer fields and `lastSeen` instead of
inserting a duplicate. The `offer_price_history` table stores the initial raw
price string and appends another row only when that string changes. Its
`observedAt` value is when the scraper first saw the new price. Existing
databases are seeded with their currently known price when the history table is
first created. All database writes for a run use one transaction.

The output file must not already exist, which prevents accidental overwrites.

By default the scraper follows all result pages sequentially with a one-second
delay. Progress goes to stderr, so stdout can be redirected safely:

```bash
uv run python anibis_scraper.py "macbook" > offers.jsonl
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
uv run python -m unittest -v
```

## Why plain HTTP instead of a browser?

The search UI redirects `/{language}/q?query=...` to a canonical search URL.
Each result page embeds the same structured listing data used by the React UI
inside its `__NEXT_DATA__` script, including all requested fields. Reading
that document is faster, requires no browser runtime, and avoids brittle CSS
selectors. The scraper follows the canonical URL with `?page=2`, `?page=3`,
and so on until the reported total is exhausted.
