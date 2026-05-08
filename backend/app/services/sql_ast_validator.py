"""
AST-based SQL safety validator for the NLP-to-SQL analytics agent.

Uses sqlglot to parse and walk the SQL AST rather than relying on string/keyword
matching, which can be bypassed with comment injection, whitespace tricks, or
case variations.

Checks:
  1. Parse succeeds (no syntax errors)
  2. Exactly one statement
  3. Root statement is SELECT
  4. No DML/DDL nodes anywhere in the tree (INSERT, UPDATE, DELETE, DROP, …)
  5. No dangerous PostgreSQL functions (pg_read_file, pg_ls_dir, COPY, …)
  6. All referenced tables exist in the known application schema
  7. No stacked-query or comment-injection patterns (belt-and-suspenders regex)
"""

import re
from dataclasses import dataclass, field

import sqlglot
import sqlglot.expressions as exp
from loguru import logger

# ── Known tables in the Invictus Hiring schema ────────────────────────────────

_ALLOWED_TABLES: frozenset[str] = frozenset({
    "jd_requests",
    "jd_drafts",
    "chat_messages",
    "job_postings",
    "candidate_applications",
    "users",
    "past_jds",
})

# AST node types that must never appear anywhere in a safe read-only query
_FORBIDDEN_NODE_TYPES: tuple[type, ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.TruncateTable,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.Grant,
    exp.Revoke,
    exp.Command,       # COPY, VACUUM, ANALYZE …
    exp.Use,
    exp.Set,
)

# PostgreSQL functions that could exfiltrate data or execute OS commands
_FORBIDDEN_FUNCTIONS: frozenset[str] = frozenset({
    "pg_read_file",
    "pg_read_binary_file",
    "pg_ls_dir",
    "pg_stat_file",
    "pg_sleep",           # DoS via long sleep
    "pg_cancel_backend",
    "pg_terminate_backend",
    "copy_to",
    "lo_export",
    "lo_import",
    "dblink",
    "dblink_exec",
})

# Belt-and-suspenders: regex checks that catch obfuscation the parser might not flag
_DANGEROUS_PATTERNS: list[re.Pattern] = [
    re.compile(r";\s*\S", re.IGNORECASE),               # stacked statements
    re.compile(r"--\s*$", re.IGNORECASE | re.MULTILINE), # trailing comment (suspicious)
    re.compile(r"/\*.*?\*/", re.DOTALL),                  # block comments (injection vector)
    re.compile(r"\bxp_cmdshell\b", re.IGNORECASE),       # SQL Server escape
    re.compile(r"\bcopy\b\s+\w+\s+\bto\b", re.IGNORECASE),  # COPY … TO (file write)
]


@dataclass
class ASTValidationResult:
    passed: bool
    violations: list[str] = field(default_factory=list)
    normalized_sql: str | None = None   # sqlglot-canonicalized SQL when passed

    @property
    def failure_reason(self) -> str:
        return "; ".join(self.violations) if self.violations else ""


def validate_sql(raw_sql: str) -> ASTValidationResult:
    """
    Validate *raw_sql* using a full AST parse + rule walk.

    Returns ASTValidationResult.passed=True only when every check passes.
    All violations are collected so callers can log the full picture.
    """
    violations: list[str] = []

    # ── 0. Belt-and-suspenders regex pre-check ────────────────────────────────
    # Strip trailing semicolon before regex scan so single-statement queries like
    # "SELECT count(*) FROM ...;" don't false-positive the stacked-query pattern.
    sql_for_regex = raw_sql.strip().rstrip(';')
    for pattern in _DANGEROUS_PATTERNS:
        if pattern.search(sql_for_regex):
            violations.append(f"Suspicious pattern detected: {pattern.pattern!r}")

    # ── 1. Parse ──────────────────────────────────────────────────────────────
    try:
        statements = sqlglot.parse(raw_sql, dialect="postgres", error_level=sqlglot.ErrorLevel.RAISE)
    except sqlglot.errors.ParseError as exc:
        violations.append(f"SQL parse error: {exc}")
        logger.warning(f"AST validator: parse error | {exc} | sql={raw_sql[:120]}")
        return ASTValidationResult(passed=False, violations=violations)

    # ── 2. Exactly one statement ──────────────────────────────────────────────
    if len(statements) != 1:
        violations.append(
            f"Expected exactly 1 statement, got {len(statements)} — stacked queries are not allowed."
        )

    if not statements:
        return ASTValidationResult(passed=False, violations=violations)

    stmt = statements[0]

    # ── 3. Root must be SELECT ────────────────────────────────────────────────
    if not isinstance(stmt, exp.Select):
        violations.append(
            f"Only SELECT statements are permitted; got {type(stmt).__name__}."
        )

    # ── 4. No forbidden DML/DDL nodes anywhere in the tree ───────────────────
    for node in stmt.walk():
        if isinstance(node, _FORBIDDEN_NODE_TYPES):
            violations.append(f"Forbidden SQL operation in query tree: {type(node).__name__}.")

    # ── 5. No dangerous function calls ───────────────────────────────────────
    for func_node in stmt.find_all(exp.Anonymous, exp.Func):
        func_name = (
            func_node.name.lower()
            if hasattr(func_node, "name") and func_node.name
            else ""
        )
        if func_name in _FORBIDDEN_FUNCTIONS:
            violations.append(f"Forbidden function call: {func_name}().")

    # ── 6. Only tables from the known schema ─────────────────────────────────
    # Collect CTE names so their aliases aren't flagged as unknown tables.
    cte_names: set[str] = {
        cte.alias.lower()
        for cte in stmt.find_all(exp.CTE)
        if cte.alias
    }
    for table_node in stmt.find_all(exp.Table):
        name = table_node.name.lower() if table_node.name else ""
        if name and name not in _ALLOWED_TABLES and name not in cte_names:
            violations.append(f"Reference to unknown table: {name!r}.")

    # ── 7. Build normalized SQL for safe logging ──────────────────────────────
    normalized: str | None = None
    if not violations:
        try:
            normalized = stmt.sql(dialect="postgres")
        except Exception:
            normalized = raw_sql  # fallback to original if generation fails

    passed = len(violations) == 0
    if not passed:
        logger.warning(
            f"AST validator: BLOCKED | violations={violations} | sql={raw_sql[:200]}"
        )
    else:
        logger.debug(f"AST validator: passed | sql={normalized or raw_sql[:120]}")

    return ASTValidationResult(passed=passed, violations=violations, normalized_sql=normalized)