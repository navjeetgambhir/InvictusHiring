"""Tests for the AST-based SQL safety validator."""
import pytest
from app.services.sql_ast_validator import validate_sql


# ── Passing cases ─────────────────────────────────────────────────────────────

class TestPassingQueries:
    def test_simple_select(self):
        result = validate_sql("SELECT * FROM jd_requests")
        assert result.passed
        assert result.normalized_sql is not None

    def test_select_with_where(self):
        result = validate_sql("SELECT id, title FROM jd_requests WHERE status = 'published'")
        assert result.passed

    def test_select_with_join(self):
        sql = (
            "SELECT r.title, COUNT(a.id) AS applications "
            "FROM jd_requests r "
            "LEFT JOIN candidate_applications a ON a.request_id = r.id "
            "GROUP BY r.title"
        )
        assert validate_sql(sql).passed

    def test_select_with_subquery(self):
        sql = (
            "SELECT * FROM candidate_applications "
            "WHERE screening_score = (SELECT MAX(screening_score) FROM candidate_applications)"
        )
        assert validate_sql(sql).passed

    def test_select_with_cte(self):
        sql = (
            "WITH ranked AS ("
            "  SELECT id, title, ROW_NUMBER() OVER (ORDER BY created_at DESC) AS rn "
            "  FROM jd_requests"
            ") SELECT * FROM ranked WHERE rn <= 10"
        )
        assert validate_sql(sql).passed

    def test_normalized_sql_returned(self):
        result = validate_sql("select id from jd_requests limit 5")
        assert result.passed
        assert result.normalized_sql is not None


# ── DML / DDL must be blocked ─────────────────────────────────────────────────

class TestForbiddenStatements:
    def test_insert_blocked(self):
        result = validate_sql("INSERT INTO users (name) VALUES ('x')")
        assert not result.passed
        assert any("INSERT" in v or "SELECT" in v for v in result.violations)

    def test_update_blocked(self):
        result = validate_sql("UPDATE jd_requests SET status = 'deleted'")
        assert not result.passed

    def test_delete_blocked(self):
        result = validate_sql("DELETE FROM candidate_applications WHERE id = '123'")
        assert not result.passed

    def test_drop_blocked(self):
        result = validate_sql("DROP TABLE users")
        assert not result.passed

    def test_truncate_blocked(self):
        result = validate_sql("TRUNCATE TABLE jd_requests")
        assert not result.passed

    def test_create_blocked(self):
        result = validate_sql("CREATE TABLE evil (id INT)")
        assert not result.passed

    def test_alter_blocked(self):
        result = validate_sql("ALTER TABLE users ADD COLUMN secret TEXT")
        assert not result.passed


# ── Stacked / injected queries ────────────────────────────────────────────────

class TestStackedQueries:
    def test_stacked_select_insert(self):
        result = validate_sql("SELECT 1; INSERT INTO users (name) VALUES ('x')")
        assert not result.passed

    def test_stacked_two_selects(self):
        # Even two SELECTs stacked is disallowed — single-statement policy
        result = validate_sql("SELECT 1; SELECT 2")
        assert not result.passed


# ── Dangerous PostgreSQL functions ────────────────────────────────────────────

class TestForbiddenFunctions:
    def test_pg_read_file_blocked(self):
        result = validate_sql("SELECT pg_read_file('/etc/passwd')")
        assert not result.passed

    def test_pg_ls_dir_blocked(self):
        result = validate_sql("SELECT * FROM pg_ls_dir('/tmp')")
        assert not result.passed

    def test_pg_sleep_blocked(self):
        result = validate_sql("SELECT pg_sleep(10)")
        assert not result.passed


# ── Unknown table references ──────────────────────────────────────────────────

class TestTableAllowlist:
    def test_unknown_table_blocked(self):
        result = validate_sql("SELECT * FROM pg_shadow")
        assert not result.passed
        assert any("pg_shadow" in v for v in result.violations)

    def test_information_schema_blocked(self):
        result = validate_sql("SELECT * FROM information_schema.tables")
        assert not result.passed

    def test_all_known_tables_allowed(self):
        known = [
            "jd_requests", "jd_drafts", "chat_messages",
            "job_postings", "candidate_applications", "users", "past_jds",
        ]
        for table in known:
            assert validate_sql(f"SELECT id FROM {table} LIMIT 1").passed, table


# ── Comment injection ─────────────────────────────────────────────────────────

class TestCommentInjection:
    def test_block_comment_flagged(self):
        result = validate_sql("SELECT /* injected */ * FROM jd_requests")
        assert not result.passed


# ── Violation reporting ───────────────────────────────────────────────────────

class TestViolationReporting:
    def test_failure_reason_non_empty_on_fail(self):
        result = validate_sql("DELETE FROM users")
        assert not result.passed
        assert result.failure_reason != ""

    def test_no_violations_on_pass(self):
        result = validate_sql("SELECT id FROM users LIMIT 1")
        assert result.passed
        assert result.violations == []