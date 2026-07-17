# SQL Optimizer

A small local SQL workbench (a mini DBeaver): save database connections, run queries, keep a
button bar of favorite/predefined queries, and send any query to Claude for a static review
(correctness, security, performance, and locking concerns) before you run it.

Runs entirely in one Docker container. Backend/UI is Python + [Streamlit](https://streamlit.io/),
with an animated glassmorphism UI.

## Run the prebuilt image (GitHub Container Registry)

Every push to `main` publishes a Docker image to this repo's GHCR package:

```bash
docker run --rm -p 8501:8501 \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -v "$(pwd)/data:/app/data" \
  ghcr.io/cunninghamb505/sql-optimizer:latest
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

## Favorite queries

Add a named query (optionally bound to a specific connection) under "Manage favorite queries".
It shows up as a button — clicking it loads the SQL into the editor (and switches the active
connection, if one is bound).

## Analyze with Claude

Sends only the SQL text currently in the editor (plus the target dialect name, e.g.
"PostgreSQL") to the Claude API for review — connection URLs, credentials, and query results are
never sent. Requires `ANTHROPIC_API_KEY` to be set on the container.

## Notes / limitations

- This is a single-user local tool: there's no authentication on the web UI itself. Don't expose
  port 8501 beyond localhost/your own machine without adding one.
- Query execution runs whatever SQL you type with no statement whitelist — treat it the same as
  you would a `psql`/`sqlcmd` shell against that connection.
