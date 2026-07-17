"""Offline, rule-based SQL review — no API key required.

Runs a set of static heuristics over the query text to flag common correctness, performance,
and safety problems (SELECT *, UPDATE/DELETE without WHERE, non-sargable predicates, accidental
cross joins, etc.). These are heuristics: they can miss issues and occasionally over-flag, so
findings are phrased as "consider" rather than hard rules. The Claude review is the deeper pass.
"""

from __future__ import annotations

import re

import sqlparse

# severity -> (emoji, label, sort rank)
SEVERITY = {
    "high": ("🔴", "High", 0),
    "medium": ("🟠", "Medium", 1),
    "low": ("🟡", "Low", 2),
    "info": ("🔵", "Info", 3),
}


def _finding(severity: str, title: str, detail: str, suggestion: str = "") -> dict:
    return {"severity": severity, "title": title, "detail": detail, "suggestion": suggestion}


def _strip_parens(s: str) -> str:
    """Removes balanced-parenthesis groups so we can inspect top-level structure (e.g. commas)."""
    out, depth = [], 0
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(ch)
    return "".join(out)


def _extract_from(stmt: str) -> str:
    m = re.search(
        r"\bFROM\b(.*?)(\bWHERE\b|\bGROUP\b|\bORDER\b|\bHAVING\b|\bLIMIT\b|"
        r"\bJOIN\b|\bINNER\b|\bLEFT\b|\bRIGHT\b|\bFULL\b|\bCROSS\b|\bNATURAL\b|$)",
        stmt, re.IGNORECASE | re.DOTALL,
    )
    return m.group(1) if m else ""


def _extract_where(stmt: str) -> str:
    m = re.search(
        r"\bWHERE\b(.*?)(\bGROUP\b|\bORDER\b|\bHAVING\b|\bLIMIT\b|\bWINDOW\b|$)",
        stmt, re.IGNORECASE | re.DOTALL,
    )
    return m.group(1) if m else ""


_SARG_FUNCS = r"UPPER|LOWER|DATE|YEAR|MONTH|DAY|TRUNC|CAST|CONVERT|SUBSTR|SUBSTRING|COALESCE|IFNULL|LEFT|RIGHT"


def _analyze_statement(stmt: str, findings: list[dict]) -> None:
    up = stmt.upper()
    verb_match = re.match(r"\s*(WITH|SELECT|INSERT|UPDATE|DELETE|MERGE|CREATE|ALTER|DROP|TRUNCATE)", up)
    verb = verb_match.group(1) if verb_match else ""

    where = _extract_where(stmt)
    has_where = bool(where.strip())

    # --- safety --------------------------------------------------------------
    if verb in ("UPDATE", "DELETE") and not has_where:
        findings.append(_finding(
            "high", f"{verb} without a WHERE clause",
            f"This {verb} has no WHERE clause, so it affects every row in the table.",
            "Add a WHERE clause (test it first with a matching SELECT).",
        ))

    if verb in ("DROP", "TRUNCATE"):
        findings.append(_finding(
            "medium", f"Destructive statement ({verb})",
            f"{verb} permanently removes data/objects and typically cannot be rolled back.",
            "Double-check the target and make sure you have a backup.",
        ))

    if re.search(r"(=|!=|<>)\s*NULL", up):
        findings.append(_finding(
            "high", "Comparison to NULL with =/!=",
            "`= NULL` / `<> NULL` always evaluate to unknown, so rows never match.",
            "Use `IS NULL` / `IS NOT NULL` instead.",
        ))

    # --- performance ---------------------------------------------------------
    if re.search(r"\bSELECT\s+(DISTINCT\s+)?(?:[\w.]+\s*,\s*)*\*", up) or re.search(r"\bSELECT\s+\*", up):
        findings.append(_finding(
            "medium", "SELECT *",
            "Selecting all columns reads more data than needed and breaks if the schema changes.",
            "List only the columns you actually use.",
        ))

    if re.search(r"\bLIKE\s+N?'%", up):
        findings.append(_finding(
            "medium", "Leading-wildcard LIKE",
            "A pattern that starts with `%` can't use a normal index, forcing a full scan.",
            "Anchor the pattern (`'abc%'`) or use a full-text index for substring search.",
        ))

    if has_where and re.search(
        rf"\b({_SARG_FUNCS})\s*\([^)]*\)\s*(=|<|>|<=|>=|<>|!=|\bLIKE\b|\bIN\b)",
        where, re.IGNORECASE,
    ):
        findings.append(_finding(
            "medium", "Function applied to a column in WHERE",
            "Wrapping a column in a function (e.g. `YEAR(col) = 2024`) prevents index use (non-sargable).",
            "Rewrite as a range (`col >= '2024-01-01' AND col < '2025-01-01'`) or add a functional index.",
        ))

    if re.search(r"\bNOT\s+IN\s*\(\s*SELECT", up):
        findings.append(_finding(
            "medium", "NOT IN (subquery)",
            "If the subquery returns any NULL, `NOT IN` yields no rows — a common silent bug — and it "
            "often optimizes worse than the alternative.",
            "Prefer `NOT EXISTS (...)` or a LEFT JOIN / IS NULL anti-join.",
        ))

    # implicit (comma) join in FROM
    from_clause = _extract_from(stmt)
    if from_clause and "," in _strip_parens(from_clause):
        findings.append(_finding(
            "medium", "Implicit (comma) join",
            "Comma-separated tables in FROM are an implicit join; a missing/incorrect WHERE link "
            "silently becomes a cross join.",
            "Use explicit `JOIN ... ON ...` syntax.",
        ))

    # JOIN without ON/USING (excluding CROSS/NATURAL joins, which legitimately have none)
    joins = len(re.findall(r"\bJOIN\b", up))
    cross_natural = len(re.findall(r"\b(CROSS|NATURAL)\s+JOIN\b", up))
    conditioned = len(re.findall(r"\bON\b", up)) + len(re.findall(r"\bUSING\b", up))
    if joins - cross_natural > conditioned:
        findings.append(_finding(
            "medium", "JOIN without an ON/USING condition",
            "A JOIN appears to have no join condition, which produces a Cartesian product (every row "
            "paired with every other).",
            "Add `ON <left> = <right>` (or `USING (col)`), or write `CROSS JOIN` if that's intended.",
        ))

    if has_where and re.search(r"\bOR\b", where, re.IGNORECASE):
        findings.append(_finding(
            "low", "OR in WHERE clause",
            "OR across different columns can stop the planner from using indexes efficiently.",
            "Consider `IN (...)` for one column, or a UNION of index-friendly lookups.",
        ))

    if verb in ("SELECT", "WITH"):
        no_limit = not re.search(r"\b(LIMIT|TOP|FETCH\s+(FIRST|NEXT))\b", up)
        aggregate_only = bool(re.search(r"\bGROUP\s+BY\b", up)) or bool(
            re.match(r"\s*SELECT\s+(COUNT|SUM|AVG|MIN|MAX)\s*\(", up)
        )
        if no_limit and not aggregate_only and re.search(r"\bFROM\b", up):
            findings.append(_finding(
                "low", "No row limit",
                "Without a LIMIT/TOP the query can return a very large result set.",
                "Add a limit while exploring (e.g. `LIMIT 100`, or `TOP 100` on SQL Server).",
            ))

    if re.search(r"\bSELECT\s+DISTINCT\b", up):
        findings.append(_finding(
            "low", "SELECT DISTINCT",
            "DISTINCT sometimes masks duplicate rows produced by a join fan-out rather than fixing it.",
            "Confirm the duplicates are expected; otherwise correct the join granularity.",
        ))


def analyze_sql(sql: str, dialect: str | None = None) -> list[dict]:
    """Runs all offline rules and returns findings sorted by severity (most severe first)."""
    findings: list[dict] = []
    if not sql or not sql.strip():
        return findings

    clean = sqlparse.format(sql, strip_comments=True)
    statements = [s for s in sqlparse.split(clean) if s.strip()]

    if len(statements) > 1:
        findings.append(_finding(
            "info", "Multiple statements",
            f"{len(statements)} statements detected. The query runner executes one statement at a time.",
            "Run them separately, or keep a single statement per query.",
        ))

    for stmt in statements:
        _analyze_statement(stmt, findings)

    findings.sort(key=lambda f: SEVERITY[f["severity"]][2])
    return findings
