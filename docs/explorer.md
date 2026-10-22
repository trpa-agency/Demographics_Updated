# Demographic Data Explorer

`explorer/index.html` is a single web page that reads the TRPA demographic services live. It uses the TRPA dashboard stack: Calcite for layout, Plotly for charts, AG Grid for tables, and the ArcGIS Maps SDK for the map. It reads data only.

## Tabs

| Tab | What it shows |
|---|---|
| Overview | Record counts and year range for each source, what each source holds, and how data gets there |
| Variables | Every variable in a source with its years, record count, and value range. Select a row to see the Census Bureau definition, the TRPA note from `config/variables.csv`, a chart by year, and a table of values present. |
| Coverage | A heat map of record counts by category (or by variable inside a category) and year. Gaps show missing years. |
| Data quality | Eleven checks against the published services, each with a CSV export, including known errors still published |
| Geography | Map of basin tracts, block groups, and blocks by boundary year, with counts |
| Glossary | Plain-language definitions |

## Sources it reads

* Demographics MapServer layers 18, 27, and 28
* Climate Resilience Dashboard MapServer layer 135
* Census Bureau variable definitions from `api.census.gov`
* `../config/variables.csv` for TRPA names, aggregation rules, and notes on known problems
* `../config/corrections/*.csv` for the known-error check

## Hosting

Publish the repository with GitHub Pages from the root of the main branch. The page is then at `https://<org>.github.io/<repo>/explorer/`. Serving from the root lets the page read `config/variables.csv`.

To use it on your own computer, double-click `tools/6_open_explorer.bat`. It starts a small web server that only this computer can reach and opens the page at `http://127.0.0.1:8000/explorer/index.html`. Leave the black window open while you use the page. Close it to stop the server.

Do not open `index.html` by double-clicking it. The browser then runs it from a `file:///` address and blocks it from reading `config/variables.csv` and the corrections files. The page shows a warning when this happens. The live data still loads, but TRPA notes, the known-errors check, and the added-medians check are empty.

Python users can run the same server from the repository folder:

```
python -m http.server 8000 --bind 127.0.0.1
```

Then open `http://127.0.0.1:8000/explorer/`.

## Changing it

The page is one HTML file with no build step. Service addresses are at the top of the script in `SERVER` and `SOURCES`. Data quality checks are in the `CHECKS` list; each has a title, description, severity, and a `run` function that returns rows.
