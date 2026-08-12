# Anibis scraper

Exports every result from an Anibis keyword search as newline-delimited JSON
(JSONL). Each line contains exactly:

- `title`
- `price` (the display value, such as `"500.-"` or `"Gratuit"`)
- `date` (ISO 8601)
- `description`
- `city`
- `postcode`

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

The output file must not already exist, which prevents accidental overwrites.

By default the scraper follows all result pages sequentially with a one-second
delay. Progress goes to stderr, so stdout can be redirected safely:

```bash
uv run python anibis_scraper.py "macbook" > offers.jsonl
```

Useful options:

```text
--language de|fr|it   Site language (default: fr)
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
inside its `__NEXT_DATA__` script, including all six requested fields. Reading
that document is faster, requires no browser runtime, and avoids brittle CSS
selectors. The scraper follows the canonical URL with `?page=2`, `?page=3`,
and so on until the reported total is exhausted.
