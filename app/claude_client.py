"""Sends a SQL query to Claude for a static review (correctness, security, performance, locking).

Only the SQL text and the target dialect name are ever sent — never the connection URL,
credentials, or query results. This is a static-analysis feature, not a live EXPLAIN/execution.
"""

import os

import anthropic

MODEL = "claude-sonnet-5"

SYSTEM_PROMPT = """\
You are a senior database engineer reviewing a SQL query before it ships. You will be told the \
target SQL dialect and given the raw query text. Review it for:

1. Correctness — logic bugs, ambiguous joins, off-by-one conditions, NULL-handling mistakes.
2. Security — signs the query was built by unsafely concatenating/formatting untrusted input \
(e.g. leftover string-format placeholders, suspicious string concatenation patterns), and any \
use of overly broad grants or dynamic SQL execution.
3. Performance — SELECT *, missing WHERE/LIMIT clauses, non-sargable predicates (functions on \
indexed columns), implicit cross joins, N+1-shaped patterns, missing/likely-missing indexes.
4. Locking & transactions — UPDATE/DELETE without a WHERE clause or LIMIT, long-running \
transactions, statements likely to cause lock escalation or block other writers.

Respond in markdown with this structure:
- **Verdict**: one line — looks good / needs changes / do not run as-is
- **Findings**: a bullet list, each tagged with severity (Critical/Warning/Suggestion)
- **Suggested rewrite**: a corrected/optimized version of the query in a sql code block, or \
"No changes needed" if none are warranted

Be concise. Do not repeat the query back verbatim outside of the rewrite block.
"""


class ClaudeNotConfiguredError(RuntimeError):
    pass


def is_configured() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def analyze_query(sql: str, db_type: str | None) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ClaudeNotConfiguredError(
            "ANTHROPIC_API_KEY is not set. Provide it as an environment variable to the container."
        )

    client = anthropic.Anthropic(api_key=api_key)
    dialect_line = f"Target SQL dialect: {db_type}\n\n" if db_type else ""

    response = client.messages.create(
        model=MODEL,
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"{dialect_line}Query to review:\n\n```sql\n{sql}\n```",
            }
        ],
    )
    return "".join(block.text for block in response.content if block.type == "text")
