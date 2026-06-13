"""
Guard against documentation drifting from the code constants it describes.

Each test pins a value that has a single source of truth in the code and is
also quoted in a human-facing doc. If the code value changes without the doc
being updated (or vice-versa), the matching test fails in CI — turning the
recurring "audit keeps re-finding stale docs" class of findings into an
immediate red build instead of something a future audit has to rediscover.

Covers the doc-accuracy findings from the 2026-06-13 line audit:
  - STREAMING_TIMEOUT_INITIAL / MAX_HISTORY_ITEMS  -> docs/DEVELOPER_GUIDE.md
  - ai_user / ai_guild rate limits                 -> docs/TROUBLESHOOTING.md
  - dashboard per-image size cap                   -> native_dashboard/README.md
  - DB migration subtree kept in the Docker context -> .dockerignore
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _lines_mentioning(doc: str, needle: str) -> list[str]:
    """Return the doc lines that reference ``needle`` (e.g. a constant name)."""
    return [ln for ln in doc.splitlines() if needle in ln]


class TestProcessingLimitDocs:
    """docs/DEVELOPER_GUIDE.md Processing Limits table must match constants.py."""

    def test_streaming_timeout_initial_matches_doc(self):
        from cogs.ai_core.data.constants import STREAMING_TIMEOUT_INITIAL

        doc = _read("docs/DEVELOPER_GUIDE.md")
        lines = _lines_mentioning(doc, "STREAMING_TIMEOUT_INITIAL")
        assert lines, "DEVELOPER_GUIDE.md no longer documents STREAMING_TIMEOUT_INITIAL"
        wanted = f"{int(STREAMING_TIMEOUT_INITIAL)}s"
        assert any(wanted in ln for ln in lines), (
            f"DEVELOPER_GUIDE.md must say STREAMING_TIMEOUT_INITIAL is {wanted} "
            f"(code value = {STREAMING_TIMEOUT_INITIAL}); found: {lines}"
        )

    def test_max_history_items_matches_doc(self):
        from cogs.ai_core.data.constants import MAX_HISTORY_ITEMS

        doc = _read("docs/DEVELOPER_GUIDE.md")
        lines = _lines_mentioning(doc, "MAX_HISTORY_ITEMS")
        assert lines, "DEVELOPER_GUIDE.md no longer documents MAX_HISTORY_ITEMS"
        assert any(str(MAX_HISTORY_ITEMS) in ln for ln in lines), (
            f"DEVELOPER_GUIDE.md must document MAX_HISTORY_ITEMS={MAX_HISTORY_ITEMS}; "
            f"found: {lines}"
        )


class TestRateLimitDocs:
    """docs/TROUBLESHOOTING.md rate-limit section must match rate_limiter.py."""

    def _configs(self):
        from utils.reliability.rate_limiter import RateLimiter

        return RateLimiter()._configs

    def test_ai_user_limit_matches_doc(self):
        cfg = self._configs()["ai_user"]
        doc = _read("docs/TROUBLESHOOTING.md")
        lines = _lines_mentioning(doc, "ai_user")
        assert lines, "TROUBLESHOOTING.md no longer documents the ai_user limit"
        assert any(str(cfg.requests) in ln for ln in lines), (
            f"TROUBLESHOOTING.md must say ai_user is {cfg.requests} req/"
            f"{cfg.window}s; found: {lines}"
        )

    def test_ai_guild_limit_matches_doc(self):
        cfg = self._configs()["ai_guild"]
        doc = _read("docs/TROUBLESHOOTING.md")
        lines = _lines_mentioning(doc, "ai_guild")
        assert lines, "TROUBLESHOOTING.md no longer documents the ai_guild limit"
        assert any(str(cfg.requests) in ln for ln in lines), (
            f"TROUBLESHOOTING.md must say ai_guild is {cfg.requests} req/"
            f"{cfg.window}s; found: {lines}"
        )


class TestDashboardImageCapDoc:
    """native_dashboard/README.md image cap must match ws_dashboard.py."""

    def test_image_cap_matches_doc(self):
        from cogs.ai_core.api.ws_dashboard import DashboardWebSocketServer

        cap_mb = DashboardWebSocketServer.MAX_IMAGE_SIZE_BYTES // (1024 * 1024)
        doc = _read("native_dashboard/README.md")
        image_lines = [ln for ln in doc.splitlines() if "Images" in ln and "MB" in ln]
        assert image_lines, "native_dashboard/README.md no longer documents the image cap"
        assert any(f"{cap_mb} MB" in ln for ln in image_lines), (
            f"native_dashboard/README.md must document the image cap as {cap_mb} MB "
            f"(code MAX_IMAGE_SIZE_BYTES = {DashboardWebSocketServer.MAX_IMAGE_SIZE_BYTES}); "
            f"found: {image_lines}"
        )


class TestDockerignoreKeepsMigrations:
    """The repo-root .dockerignore must keep the DB migration subtree in context.

    bot startup -> run_migrations() reads scripts/maintenance/migrations/, and
    discover_migrations() returns [] when that dir is absent. The repo excludes
    scripts/ for image hygiene, so a re-include exception for the migrations
    subtree must remain or the built image silently runs zero migrations.
    """

    def test_migrations_reinclude_present(self):
        di = _read(".dockerignore")
        assert "scripts/" in di, ".dockerignore unexpectedly stopped excluding scripts/"
        reinclude = [
            ln.strip()
            for ln in di.splitlines()
            if ln.strip().startswith("!") and "scripts/maintenance/migrations" in ln
        ]
        assert reinclude, (
            ".dockerignore excludes scripts/ but no '!scripts/maintenance/migrations...' "
            "re-include remains — migrations would be missing from the Docker image"
        )

    def test_migration_files_actually_exist(self):
        mig_dir = ROOT / "scripts" / "maintenance" / "migrations"
        sql = list(mig_dir.glob("*.sql"))
        assert sql, "no migration .sql files found — the re-include guard is moot"
