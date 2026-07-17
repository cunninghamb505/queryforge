# QueryForge

A small local SQL workbench (a mini DBeaver): save database connections, run queries, keep a
button bar of favorite/predefined queries, review queries **offline** with a built-in rule-based
analyzer or **with Claude** for a deeper static review (correctness, security, performance, and
locking concerns), and export polished reports.

Runs entirely in one Docker container. Backend/UI is Python + [Streamlit](https://streamlit.io/),
with an animated glassmorphism UI.

## Run the prebuilt image (GitHub Container Registry)

Every push to `main` publishes a Docker image to this repo's GHCR package:

```bash
docker run --rm -p 8501:8501 \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -v "$(pwd)/data:/app/data" \
  ghcr.io/cunninghamb505/queryforge:latest
```

Then open http://localhost:8501. (If the package is private, run
`docker login ghcr.io` first, or make the package public under the repo's
Packages settings.)

## Supported databases

- PostgreSQL
- SQLite
- SQL Server (via ODBC Driver 18, bundled in the image)

## Setup

1. Copy `.env.example` to `.env` and add your Anthropic API key:

   ```bash
   cp .env.example .env
   # edit .env and set ANTHROPIC_API_KEY=sk-ant-...
   ```

2. Build and start the container:

   ```bash
   docker compose up --build
   ```

3. Open http://localhost:8501

Saved connections and favorite queries persist in `./data` on the host (mounted into the
container), so they survive rebuilds/restarts. `./data/secret.key` is the encryption key used to
encrypt connection URLs at rest — back it up if you want saved connections to remain readable
after deleting the volume, and don't commit `data/` to source control (it's already in
`.gitignore`).

## Adding a connection

In the sidebar, pick a database type and paste a connection URL:

| Type        | Example URL                                                  |
|-------------|---------------------------------------------------------------|
| PostgreSQL  | `postgresql+psycopg2://user:pass@host:5432/dbname`             |
| SQLite      | `sqlite:////app/data/mydb.sqlite` (path is inside the container; put files under the mounted `./data` folder to access them from the host too) |
| SQL Server  | `mssql+pyodbc://user:pass@host:1433/dbname` (the ODBC driver and `TrustServerCertificate=yes` are appended automatically if omitted) |

Use **Test** before **Save** to confirm the app can reach the database. Connection URLs are
encrypted before being written to `data/app_metadata.db`.

## Favorite queries (quick-run buttons)

Favorite queries appear as buttons above the editor. There are two ways to create one:

- **⭐ Save as button** (next to the query actions) — saves whatever is currently in the editor,
  including a query you just optimized. Give it a label, optionally bind a connection, and
  optionally tick **Run immediately when clicked**.
- **Manage favorite queries** — a form to add one manually.

Clicking a favorite loads its SQL into the editor (and switches the active connection if one is
bound). If it was saved with **run immediately**, it also executes on click (shown with a ⚡) —
true one-click quick-run.

After **✨ Analyze with Claude**, its suggested rewrite is extracted into an **Optimized query**
panel with a **⬆ Use in editor** button, so you can load the optimized SQL and then **⭐ Save as
button** to keep it.

## Results & exportable reports

After running a `SELECT`, results are shown with summary tiles (row/column counts, numeric
columns, query time) and the data grid. Open **📊 Build & export report** to assemble a
customizable report:

- Set a **title**, **subtitle/author**, **notes**, and an **accent color**.
- Toggle which sections to include: summary, chart, SQL query, data table.
- Add a **chart** (bar / line / area) by picking an X column and one or more numeric Y columns —
  rendered as inline SVG.
- Choose the max number of rows to embed in the report table.

Then download in one click:

- **HTML report** — a single self-contained file (inlined CSS + SVG chart), great for sharing or
  printing to PDF from a browser.
- **CSV**, **Excel (.xlsx)**, or **JSON** of the raw result set.

## Reviewing a query

Two ways to review the SQL in the editor:

- **🔍 Quick check (offline)** — a built-in, rule-based analyzer. No API key required. Flags common
  issues such as `SELECT *`, `UPDATE`/`DELETE` without a `WHERE`, `= NULL` comparisons,
  leading-wildcard `LIKE '%…'`, functions on columns in `WHERE` (non-sargable), implicit/comma
  joins and joins missing an `ON`, `NOT IN (subquery)`, missing row limits, and destructive DDL.
  Each finding comes with a severity and a suggested fix. These are heuristics — they can miss
  things or occasionally over-flag.
- **✨ Analyze with Claude** — a deeper AI review. Sends only the SQL text and the target dialect
  name (e.g. "PostgreSQL") to the Claude API — connection URLs, credentials, and query results are
  never sent. Requires `ANTHROPIC_API_KEY` to be set on the container.

## Notes / limitations

- This is a single-user local tool: there's no authentication on the web UI itself. Don't expose
  port 8501 beyond localhost/your own machine without adding one.
- Query execution runs whatever SQL you type with no statement whitelist — treat it the same as
  you would a `psql`/`sqlcmd` shell against that connection.
