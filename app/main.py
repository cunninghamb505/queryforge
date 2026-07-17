import pandas as pd
import streamlit as st

from datetime import datetime

import streamlit.components.v1 as components

from app import db
from app import connections as conn_lib
from app import claude_client
from app import report
from app import analyzer
from app.theme import inject_theme

APP_NAME = "QueryForge"

st.set_page_config(page_title=APP_NAME, layout="wide")
inject_theme()

# --- session state defaults ------------------------------------------------

st.session_state.setdefault("sql_editor", "SELECT 1;")
st.session_state.setdefault("active_connection_id", None)
st.session_state.setdefault("last_result", None)
st.session_state.setdefault("last_error", None)
st.session_state.setdefault("last_analysis", None)
st.session_state.setdefault("analysis_error", None)
st.session_state.setdefault("local_findings", None)


def set_editor_text(sql_text: str, connection_id: int | None = None):
    st.session_state["sql_editor"] = sql_text
    if connection_id is not None:
        st.session_state["active_connection_id"] = connection_id
    st.session_state["local_findings"] = None
    st.session_state["last_result"] = None
    st.session_state["last_error"] = None
    st.session_state["last_analysis"] = None
    st.session_state["analysis_error"] = None


# --- sidebar: connection management ----------------------------------------

st.sidebar.header("Connections")

all_connections = db.list_connections()
connections_by_id = {c.id: c for c in all_connections}

if all_connections:
    ids = [c.id for c in all_connections]
    if st.session_state["active_connection_id"] not in ids:
        st.session_state["active_connection_id"] = ids[0]

    st.sidebar.selectbox(
        "Active connection",
        options=ids,
        format_func=lambda cid: connections_by_id[cid].name,
        key="active_connection_id",
    )
else:
    st.sidebar.info("No saved connections yet. Add one below.")

with st.sidebar.expander("+ Add connection", expanded=not all_connections):
    with st.form("add_connection_form"):
        new_name = st.text_input("Name")
        new_type = st.selectbox("Type", options=db.DB_TYPES)
        new_url = st.text_input(
            "Connection URL",
            placeholder={
                "PostgreSQL": "postgresql+psycopg2://user:pass@host:5432/dbname",
                "SQLite": "sqlite:////app/data/mydb.sqlite",
                "SQL Server": "mssql+pyodbc://user:pass@host:1433/dbname",
            }["PostgreSQL"],
        )
        col_test, col_save = st.columns(2)
        test_clicked = col_test.form_submit_button("Test")
        save_clicked = col_save.form_submit_button("Save", type="primary")

        if test_clicked:
            if not new_url:
                st.error("Enter a connection URL first.")
            else:
                ok, message = conn_lib.test_connection(new_type, new_url)
                (st.success if ok else st.error)(message)

        if save_clicked:
            if not new_name or not new_url:
                st.error("Name and URL are required.")
            else:
                try:
                    db.create_connection(new_name, new_type, new_url)
                    st.success(f"Saved connection '{new_name}'.")
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Could not save connection: {exc}")

if all_connections:
    st.sidebar.caption("Saved connections")
    for c in all_connections:
        row = st.sidebar.columns([4, 1])
        row[0].write(f"**{c.name}** · {c.db_type}")
        if row[1].button("🗑", key=f"del_conn_{c.id}", help="Delete connection"):
            db.delete_connection(c.id)
            st.rerun()

active_connection = connections_by_id.get(st.session_state["active_connection_id"])

# --- main area ---------------------------------------------------------------

st.title(APP_NAME)
st.caption(
    "A mini SQL workbench — manage connections, run queries, review them offline or with Claude, "
    "and export polished reports."
)

# Favorite queries bar
st.subheader("Favorite queries")
favorites = db.list_favorite_queries()

if favorites:
    cols_per_row = 4
    for i in range(0, len(favorites), cols_per_row):
        row_favs = favorites[i : i + cols_per_row]
        row_cols = st.columns(cols_per_row)
        for col, fav in zip(row_cols, row_favs):
            with col:
                st.button(
                    fav.name,
                    key=f"fav_btn_{fav.id}",
                    use_container_width=True,
                    on_click=set_editor_text,
                    args=(fav.sql_text, fav.connection_id),
                )
else:
    st.caption("No favorite queries yet. Add one below.")

with st.expander("Manage favorite queries"):
    with st.form("add_favorite_form", clear_on_submit=True):
        fav_name = st.text_input("Button label")
        fav_sql = st.text_area("SQL", height=100)
        fav_conn_options = [None] + [c.id for c in all_connections]
        fav_conn_id = st.selectbox(
            "Bind to connection (optional)",
            options=fav_conn_options,
            format_func=lambda cid: "— none —" if cid is None else connections_by_id[cid].name,
        )
        if st.form_submit_button("Add favorite", type="primary"):
            if not fav_name or not fav_sql:
                st.error("Label and SQL are required.")
            else:
                db.create_favorite_query(fav_name, fav_sql, fav_conn_id)
                st.rerun()

    if favorites:
        st.caption("Existing favorites")
        for fav in favorites:
            row = st.columns([4, 1])
            row[0].write(f"**{fav.name}**")
            if row[1].button("🗑", key=f"del_fav_{fav.id}"):
                db.delete_favorite_query(fav.id)
                st.rerun()

# Query editor
st.subheader("Query editor")
if active_connection:
    st.caption(f"Running against **{active_connection.name}** ({active_connection.db_type})")
else:
    st.warning("No active connection selected — add one in the sidebar to run queries.")

st.text_area("SQL", key="sql_editor", height=200, label_visibility="collapsed")

run_col, check_col, analyze_col = st.columns(3)
run_clicked = run_col.button("▶ Run Query", type="primary", use_container_width=True, disabled=not active_connection)
check_clicked = check_col.button(
    "🔍 Quick check", use_container_width=True,
    help="Offline rule-based SQL review — no API key needed.",
)
analyze_clicked = analyze_col.button(
    "✨ Analyze with Claude", use_container_width=True,
    help="Deeper AI review (requires ANTHROPIC_API_KEY).",
)

if check_clicked:
    st.session_state["local_findings"] = analyzer.analyze_sql(
        st.session_state["sql_editor"],
        active_connection.db_type if active_connection else None,
    )

if run_clicked:
    st.session_state["last_error"] = None
    st.session_state["last_result"] = None
    try:
        result = conn_lib.run_query(
            active_connection.db_type, active_connection.url, st.session_state["sql_editor"]
        )
        result["sql"] = st.session_state["sql_editor"]
        result["connection_label"] = f"{active_connection.name} ({active_connection.db_type})"
        st.session_state["last_result"] = result
    except Exception as exc:  # noqa: BLE001
        st.session_state["last_error"] = str(exc)

if analyze_clicked:
    st.session_state["analysis_error"] = None
    st.session_state["last_analysis"] = None
    try:
        st.session_state["last_analysis"] = claude_client.analyze_query(
            st.session_state["sql_editor"],
            active_connection.db_type if active_connection else None,
        )
    except claude_client.ClaudeNotConfiguredError as exc:
        st.session_state["analysis_error"] = str(exc)
    except Exception as exc:  # noqa: BLE001
        st.session_state["analysis_error"] = f"Claude API call failed: {exc}"

# Results
if st.session_state["last_error"]:
    st.error(st.session_state["last_error"])
elif st.session_state["last_result"]:
    result = st.session_state["last_result"]
    elapsed_ms = result.get("elapsed_ms")
    if result["kind"] == "rows":
        df: pd.DataFrame = result["dataframe"]
        summary = report.summarize(df, elapsed_ms)

        # --- fancy summary tiles ---
        t1, t2, t3, t4 = st.columns(4)
        t1.metric("Rows", f"{summary['rows']:,}")
        t2.metric("Columns", f"{summary['cols']:,}")
        t3.metric("Numeric cols", f"{summary['numeric_cols']:,}")
        t4.metric("Query time", f"{elapsed_ms:.0f} ms" if elapsed_ms is not None else "—")

        st.dataframe(df, use_container_width=True)

        if df.empty:
            st.info("Query returned no rows — nothing to chart or export.")
        else:
            # --- build & export report ---
            with st.expander("📊 Build & export report", expanded=False):
                numeric_cols = report.numeric_columns(df)

                cfg1, cfg2 = st.columns(2)
                rpt_title = cfg1.text_input("Report title", value="Query Report", key="rpt_title")
                rpt_subtitle = cfg2.text_input(
                    "Subtitle / author", value="", key="rpt_subtitle",
                    placeholder="e.g. Weekly metrics — prepared by …",
                )
                rpt_accent = cfg1.color_picker("Accent color", value="#8b5cf6", key="rpt_accent")
                rpt_table_limit = cfg2.number_input(
                    "Max rows in report table", min_value=1, max_value=100_000,
                    value=min(len(df), 500), step=50, key="rpt_table_limit",
                )
                rpt_notes = st.text_area(
                    "Notes (optional)", value="", key="rpt_notes",
                    placeholder="Context, caveats, takeaways… shown in the report.",
                )

                st.caption("Include in report")
                s1, s2, s3, s4 = st.columns(4)
                inc_summary = s1.checkbox("Summary", value=True, key="rpt_inc_summary")
                inc_chart = s2.checkbox("Chart", value=bool(numeric_cols), key="rpt_inc_chart")
                inc_sql = s3.checkbox("SQL query", value=True, key="rpt_inc_sql")
                inc_table = s4.checkbox("Data table", value=True, key="rpt_inc_table")

                chart_svg = None
                if inc_chart:
                    if not numeric_cols:
                        st.warning("No numeric columns available to chart.")
                    else:
                        ch1, ch2, ch3 = st.columns(3)
                        chart_type = ch1.selectbox(
                            "Chart type", ["bar", "line", "area"], key="rpt_chart_type"
                        )
                        x_col = ch2.selectbox(
                            "X axis (labels)", list(df.columns), key="rpt_chart_x"
                        )
                        default_y = numeric_cols[:1]
                        y_cols = ch3.multiselect(
                            "Y axis (values)", numeric_cols, default=default_y, key="rpt_chart_y"
                        )
                        if y_cols:
                            labels = df[x_col].astype(str).tolist()
                            series = [{"name": c, "values": df[c].tolist()} for c in y_cols]
                            chart_svg = report.svg_chart(
                                labels, series, chart_type=chart_type, accent=rpt_accent
                            )
                            if chart_svg:
                                components.html(
                                    f'<div style="background:#fff;border-radius:10px;padding:10px">{chart_svg}</div>',
                                    height=420, scrolling=True,
                                )
                        else:
                            st.caption("Pick at least one Y column to render a chart.")

                html_report = report.build_html_report(
                    df,
                    title=rpt_title or "Query Report",
                    subtitle=rpt_subtitle,
                    notes=rpt_notes,
                    sql=result.get("sql", ""),
                    connection_label=result.get("connection_label", ""),
                    summary=summary,
                    accent=rpt_accent,
                    include_sql=inc_sql,
                    include_summary=inc_summary,
                    include_chart=inc_chart,
                    include_table=inc_table,
                    table_row_limit=int(rpt_table_limit),
                    chart_svg=chart_svg,
                    generated_at=datetime.now(),
                )

                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                st.markdown("**Download**")
                d1, d2, d3, d4 = st.columns(4)
                d1.download_button(
                    "📄 HTML report", data=html_report.encode("utf-8"),
                    file_name=f"report-{stamp}.html", mime="text/html",
                    use_container_width=True,
                )
                d2.download_button(
                    "🧾 CSV", data=report.to_csv_bytes(df),
                    file_name=f"results-{stamp}.csv", mime="text/csv",
                    use_container_width=True,
                )
                d3.download_button(
                    "📊 Excel", data=report.to_excel_bytes(df),
                    file_name=f"results-{stamp}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )
                d4.download_button(
                    "{ } JSON", data=report.to_json_bytes(df),
                    file_name=f"results-{stamp}.json", mime="application/json",
                    use_container_width=True,
                )
    elif result["rowcount"] < 0:
        # Some drivers (e.g. sqlite3) report -1 for DDL/statements where rowcount isn't meaningful.
        st.success("Statement executed successfully.")
    else:
        st.success(f"{result['rowcount']} row(s) affected.")

# Offline quick check
if st.session_state["local_findings"] is not None:
    findings = st.session_state["local_findings"]
    st.subheader("🔍 Quick check (offline)")
    if not findings:
        st.success("No issues flagged by the offline rules. For a deeper review, use Analyze with Claude.")
    else:
        counts = {}
        for f in findings:
            counts[f["severity"]] = counts.get(f["severity"], 0) + 1
        badge = "  ".join(
            f"{analyzer.SEVERITY[s][0]} {counts[s]} {analyzer.SEVERITY[s][1].lower()}"
            for s in ("high", "medium", "low", "info") if s in counts
        )
        st.caption(f"{len(findings)} finding(s) — {badge}")
        for f in findings:
            emoji, label, _ = analyzer.SEVERITY[f["severity"]]
            with st.container(border=True):
                # Title is kept outside the bold span so titles containing markdown
                # characters (e.g. "SELECT *") don't break the formatting.
                st.markdown(f"**{emoji} {label}** · {f['title']}")
                st.markdown(f["detail"])
                if f["suggestion"]:
                    st.markdown(f"→ _{f['suggestion']}_")
        st.caption("Heuristic checks — they can miss issues or occasionally over-flag. Not a substitute for testing.")

# Claude analysis
if st.session_state["analysis_error"]:
    st.error(st.session_state["analysis_error"])
    st.info("No API key? Use **🔍 Quick check** for an offline, rule-based review instead.")
elif st.session_state["last_analysis"]:
    st.subheader("✨ Claude's review")
    st.markdown(st.session_state["last_analysis"])
