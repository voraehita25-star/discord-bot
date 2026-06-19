"""Regression tests for audit-2 group ``infra``.

These guard config/infra-as-code files (no application logic), so the checks
are static assertions over the file contents — they fail if a fix is reverted.

Covers the confirmed findings:

* ``infra-config-1`` — the stale duplicate ``docker/.dockerignore`` (a weaker
  fork that omitted ``*.db`` / ``cookies.txt`` / persona data / the ``.env.*``
  glob) must not exist; the authoritative ``/.dockerignore`` is the single
  source of truth, since every build context is the repo root.
* ``infra-config-2`` — CI must pin ruff / mypy / bandit so the ruff gate and the
  mypy baseline are reproducible (no version skew vs ``.pre-commit-config.yaml``).
* ``infra-config-3`` — ``requirements.txt`` must not ship unbounded ``>=`` lines;
  each gets a conservative upper cap so Docker/CI can't silently resolve a
  breaking new major at build time.
* EXTRA (tester-found) — ``scripts/run_tests.ps1`` must invoke the venv
  interpreter, not a bare ``python`` that resolves to a pytest-less system
  Python in a stripped-PATH shell.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


# ----------------------------------------------------------------------------
# infra-config-1 — stale docker/.dockerignore removed; root one stays strong
# ----------------------------------------------------------------------------
def test_stale_docker_dockerignore_is_gone():
    assert not (REPO_ROOT / "docker" / ".dockerignore").exists(), (
        "docker/.dockerignore is a dead, weaker fork; the build context is "
        "always the repo root so only /.dockerignore is read. Re-introducing "
        "it is a secret-baking trap."
    )


def test_authoritative_dockerignore_excludes_secrets_and_data():
    text = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8")
    # The exclusions the stale fork was missing — these protect against baking
    # secrets / user data into the image via ``COPY . .``.
    for needed in (
        ".env.*",  # glob, not just literal .env
        "cookies.txt",
        ".claude/",
        "*.db",
        "*.sqlite",
        "cogs/ai_core/data/faust_data.py",
        "cogs/ai_core/data/roleplay_data.py",
    ):
        assert needed in text, f"/.dockerignore lost its exclusion for: {needed}"


# ----------------------------------------------------------------------------
# infra-config-2 — CI pins lint/type tooling (no unpinned installs)
# ----------------------------------------------------------------------------
@pytest.fixture(scope="module")
def ci_yaml() -> str:
    return (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def test_ci_pins_ruff_to_precommit_version(ci_yaml: str):
    # Must match the SHA-pinned ruff-pre-commit rev (v0.15.17).
    assert "ruff==0.15.17" in ci_yaml
    # And must NOT install ruff unpinned anywhere.
    assert "pip install ruff\n" not in ci_yaml
    assert "pip install ruff " not in ci_yaml


def test_ci_pins_mypy(ci_yaml: str):
    assert 'pip install pytest pytest-asyncio pytest-cov "mypy~=2.1.0"' in ci_yaml
    # The old unpinned form (trailing bare ``mypy``) must be gone.
    assert "pytest-cov mypy\n" not in ci_yaml
    # And the looser ~=2.0 spec (permits any 2.x minor -> can flake the gate)
    # must not reappear.
    assert '"mypy~=2.0"' not in ci_yaml


def test_ci_pins_bandit_to_precommit_version(ci_yaml: str):
    assert 'pip install "bandit[toml]==1.9.4"' in ci_yaml
    assert "pip install bandit[toml]\n" not in ci_yaml


# ----------------------------------------------------------------------------
# infra-config-3 — no unbounded >= in requirements.txt
# ----------------------------------------------------------------------------
def test_requirements_have_upper_bounds():
    text = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
    offenders: list[str] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()  # drop inline comments
        if not line or line.startswith("#"):
            continue
        # Strip platform markers (``; sys_platform == ...``) before checking.
        spec = line.split(";", 1)[0].strip()
        if ">=" in spec:
            # An upper bound is present iff there's a ``<`` somewhere in the spec.
            if "<" not in spec:
                offenders.append(spec)
    assert not offenders, f"unbounded >= requirements (need an upper cap): {offenders}"


# ----------------------------------------------------------------------------
# EXTRA — run_tests.ps1 uses the venv interpreter, not bare python
# ----------------------------------------------------------------------------
def test_run_tests_uses_venv_python():
    text = (REPO_ROOT / "scripts" / "run_tests.ps1").read_text(encoding="utf-8")
    assert r".venv\Scripts\python.exe" in text
    # The bare invocation that hit system Python (no pytest) must be gone.
    assert "& python @args_list" not in text
