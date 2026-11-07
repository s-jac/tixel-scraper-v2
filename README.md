# Tixel scraper exploration

This repository is an early probe of what can be collected from Tixel's public
Australian event pages with Python `requests`. It does not yet produce a complete
market snapshot.

## Use the virtual environment

Run Python and install packages through `.venv`:

```bash
python3 -m venv .venv             # only if .venv does not already exist
.venv/bin/python -m pip install requests
.venv/bin/python exploration.py --city Sydney --pages 3 --events 3
```

The existing `.venv` can be reused. The script defaults to three city pages,
three event pages, and a one-second pause between requests. Inspect a specific
event with:

```bash
.venv/bin/python exploration.py \
  --event-url https://tixel.com/au/music-tickets/2026/11/10/foo-fighters-accor-stadium-sydne
```

Each run writes the fetched HTML and `report.json` to `exploration-output/`.
That directory is ignored by Git. The HTML is useful when a page's layout does
not match the parser's assumptions.

## What we know so far

- City discovery pages such as <https://tixel.com/au/discover/Sydney> have
  numbered pagination and event links. The first local run found 21 event links
  on each of pages 1–3: 21 new on page 1, then 20 new on each subsequent page.
  Event URLs should therefore be deduplicated across pages and cities.
- Event pages can expose an event date/time and venue, a **Live activity** feed,
  and a **Buy tickets** section. The activity feed may show a sale with a relative
  time, such as “about 1 hour ago,” but does not show the price paid. It also
  contains other activity, such as waitlist joins.
- The **Buy tickets** section can take different forms. Some pages show
  individual listing cards with a price per ticket including fees, quantity,
  and seat details. The three pages fetched in the first local run instead
  showed ticket-type groups with availability and a **From $** price. Those
  group prices are minimum advertised prices, not every listing price.
- Counts such as “15+ listings available” are approximate. A page may show
  fewer price cards or groups than the stated inventory. No listing-created
  timestamp was visible in the pages examined.
- A later snapshot can show that a visible price or listing changed or
  disappeared. That alone does not establish that a sale occurred or its final
  price. Relative activity times are also not exact transaction timestamps.

The first local run fetched three Sydney discovery pages and three event pages
successfully. Its original output of `0 visible sales, 0 visible price cards`
for those events was partly a parser limitation: sale text was split across HTML
nodes, and prices appeared as ticket-type groups. The parser now recognises both
formats. Re-parsing the saved HTML found 2 visible sales and 4 price groups for
Motown Day Party, 10 sales and 3 groups for Guy Montgomery, and 0 sales and 2
groups for MC Pat Flynn. These counts describe only what was visible in the
saved responses.

## Next questions

1. Check whether the ticket-type groups open additional public listing data,
   and whether all listings can be paged through.
2. Check how reliably city pages cover Australian events, including events
   outside the main cities and events with no current resale listings.
3. Decide which fields a recurring snapshot should store. At minimum: fetch
   time, event URL, event date/time, venue, visible sales with their relative
   times, visible prices, quantities, and the form in which each price appeared.

Public pages examined so far do not provide a complete history of sale prices
or exact sale times. Complete transaction data would require an authorised
source from Tixel.
