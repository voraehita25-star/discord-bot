"""Tests for utils.media.ffmpeg_path executable resolution.

Covers the FFmpeg path resolver's precedence (FFMPEG_PATH env > bundled
./ffmpeg/bin > system PATH > "ffmpeg" fallback), the `_looks_like_ffmpeg`
validation guard, and `is_ffmpeg_available`. All filesystem / PATH / env
lookups are mocked so the tests are hermetic and deterministic regardless
of whether ffmpeg is actually installed on the host.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from utils.media import ffmpeg_path as fp


def _make_fake_ffmpeg(tmp_path: Path, name: str | None = None) -> Path:
    """Create a real file on disk that passes `_looks_like_ffmpeg`.

    The file is named so its basename contains 'ffmpeg' and is made
    readable/executable (os.access(X_OK) is satisfied for an existing
    regular file on Windows; on POSIX we chmod +x to be safe).
    """
    if name is None:
        name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    tmp_path.mkdir(parents=True, exist_ok=True)
    f = tmp_path / name
    f.write_text("#!/bin/sh\n")
    if os.name != "nt":
        f.chmod(0o755)
    return f


class TestLooksLikeFfmpeg:
    """Tests for the `_looks_like_ffmpeg` validation guard."""

    def test_real_ffmpeg_file_passes(self, tmp_path):
        f = _make_fake_ffmpeg(tmp_path)
        assert fp._looks_like_ffmpeg(f) is True

    def test_nonexistent_path_rejected(self, tmp_path):
        missing = tmp_path / "ffmpeg"
        assert fp._looks_like_ffmpeg(missing) is False

    def test_directory_rejected(self, tmp_path):
        d = tmp_path / "ffmpeg"
        d.mkdir()
        # A directory is not a file, so is_file() is False.
        assert fp._looks_like_ffmpeg(d) is False

    def test_name_without_ffmpeg_rejected(self, tmp_path):
        # An existing, executable file whose name does NOT contain 'ffmpeg'
        # must be rejected (the /etc/passwd spoofing guard).
        f = tmp_path / "passwd"
        f.write_text("root:x:0:0\n")
        if os.name != "nt":
            f.chmod(0o755)
        assert fp._looks_like_ffmpeg(f) is False

    def test_name_match_is_case_insensitive(self, tmp_path):
        f = _make_fake_ffmpeg(tmp_path, name="FFMPEG.exe" if os.name == "nt" else "FFMPEG")
        assert fp._looks_like_ffmpeg(f) is True

    def test_substring_name_match(self, tmp_path):
        # Basename merely needs to *contain* 'ffmpeg'.
        nm = "my-ffmpeg-build.exe" if os.name == "nt" else "my-ffmpeg-build"
        f = _make_fake_ffmpeg(tmp_path, name=nm)
        assert fp._looks_like_ffmpeg(f) is True

    def test_not_executable_rejected(self, tmp_path):
        # File exists with correct name, but os.access(X_OK) is False.
        f = _make_fake_ffmpeg(tmp_path)
        with patch.object(fp.os, "access", return_value=False) as m_access:
            assert fp._looks_like_ffmpeg(f) is False
        m_access.assert_called_once_with(f, os.X_OK)


class TestGetFfmpegExecutableEnvOverride:
    """FFMPEG_PATH env var takes highest precedence."""

    def test_env_absolute_path_wins(self, tmp_path, monkeypatch):
        f = _make_fake_ffmpeg(tmp_path)
        monkeypatch.setenv("FFMPEG_PATH", str(f))
        # Even if bundled + PATH exist, the env path must be returned first.
        with (
            patch.object(fp, "_project_root", return_value=tmp_path),
            patch.object(fp.shutil, "which", return_value="/usr/bin/ffmpeg"),
        ):
            assert fp.get_ffmpeg_executable() == str(f)

    def test_env_expands_user_home(self, tmp_path, monkeypatch):
        f = _make_fake_ffmpeg(tmp_path)
        # ~/<name> should expanduser to the tmp file.
        monkeypatch.setenv("FFMPEG_PATH", str(Path("~") / f.name))
        with patch.object(fp.Path, "expanduser", return_value=f):
            assert fp.get_ffmpeg_executable() == str(f)

    def test_env_whitespace_stripped(self, tmp_path, monkeypatch):
        f = _make_fake_ffmpeg(tmp_path)
        monkeypatch.setenv("FFMPEG_PATH", f"   {f}   ")
        result = fp.get_ffmpeg_executable()
        assert result == str(f)

    def test_env_blank_falls_through(self, tmp_path, monkeypatch):
        # Whitespace-only env value is treated as unset → falls to bundled/PATH.
        monkeypatch.setenv("FFMPEG_PATH", "   ")
        bundled = _make_fake_ffmpeg(tmp_path / "ffmpeg" / "bin", name=fp._BUNDLED_RELATIVE.name)
        with patch.object(fp, "_project_root", return_value=tmp_path):
            assert fp.get_ffmpeg_executable() == str(bundled)

    def test_env_bare_name_resolved_via_path(self, tmp_path, monkeypatch):
        # FFMPEG_PATH="ffmpeg" (not an existing file) → resolved through which().
        f = _make_fake_ffmpeg(tmp_path)
        monkeypatch.setenv("FFMPEG_PATH", "ffmpeg")
        with patch.object(fp.shutil, "which", return_value=str(f)) as m_which:
            assert fp.get_ffmpeg_executable() == str(f)
        m_which.assert_called_once_with("ffmpeg")

    def test_env_pointing_at_non_ffmpeg_file_rejected(self, tmp_path, monkeypatch):
        # Env points at a real executable that is NOT ffmpeg (e.g. /etc/passwd).
        bad = tmp_path / "passwd"
        bad.write_text("data")
        if os.name != "nt":
            bad.chmod(0o755)
        monkeypatch.setenv("FFMPEG_PATH", str(bad))
        # which() also can't resolve the bogus path → falls through to fallback.
        with (
            patch.object(fp, "_project_root", return_value=tmp_path),
            patch.object(fp.shutil, "which", return_value=None),
        ):
            assert fp.get_ffmpeg_executable() == "ffmpeg"

    def test_env_bare_name_which_returns_non_ffmpeg_rejected(self, tmp_path, monkeypatch):
        # which() resolves the bare name but to a file whose basename does NOT
        # contain 'ffmpeg' → fails _looks_like_ffmpeg → fall through to fallback.
        bad = tmp_path / "mplayer"
        bad.write_text("data")
        if os.name != "nt":
            bad.chmod(0o755)
        monkeypatch.setenv("FFMPEG_PATH", "ffmpeg")
        with (
            patch.object(fp, "_project_root", return_value=tmp_path),
            patch.object(fp.shutil, "which", return_value=str(bad)),
        ):
            assert fp.get_ffmpeg_executable() == "ffmpeg"


class TestGetFfmpegExecutableBundled:
    """Second precedence: bundled ./ffmpeg/bin/ffmpeg(.exe)."""

    def test_bundled_used_when_no_env(self, tmp_path, monkeypatch):
        monkeypatch.delenv("FFMPEG_PATH", raising=False)
        bundled = _make_fake_ffmpeg(tmp_path / "ffmpeg" / "bin", name=fp._BUNDLED_RELATIVE.name)
        with patch.object(fp, "_project_root", return_value=tmp_path):
            # PATH should not even be consulted when bundled exists.
            with patch.object(fp.shutil, "which") as m_which:
                assert fp.get_ffmpeg_executable() == str(bundled)
            m_which.assert_not_called()

    def test_bundled_path_layout(self, tmp_path, monkeypatch):
        # Confirm the resolver looks at <root>/ffmpeg/bin/<exe>, not elsewhere.
        monkeypatch.delenv("FFMPEG_PATH", raising=False)
        # Created for its side effect (the fake bundled binary on disk); the
        # resolver's return value is asserted via `result` below.
        _make_fake_ffmpeg(tmp_path / "ffmpeg" / "bin", name=fp._BUNDLED_RELATIVE.name)
        with patch.object(fp, "_project_root", return_value=tmp_path):
            result = Path(fp.get_ffmpeg_executable())
        assert result == tmp_path / fp._BUNDLED_RELATIVE
        assert result.parent.name == "bin"
        assert result.parent.parent.name == "ffmpeg"


class TestGetFfmpegExecutablePath:
    """Third precedence: `ffmpeg` on system PATH."""

    def test_path_used_when_no_env_no_bundled(self, tmp_path, monkeypatch):
        monkeypatch.delenv("FFMPEG_PATH", raising=False)
        f = _make_fake_ffmpeg(tmp_path)
        with (
            patch.object(fp, "_project_root", return_value=tmp_path / "no_bundle"),
            patch.object(fp.shutil, "which", return_value=str(f)) as m_which,
        ):
            assert fp.get_ffmpeg_executable() == str(f)
        m_which.assert_called_once_with("ffmpeg")

    def test_path_result_validated(self, tmp_path, monkeypatch):
        # which() returns a path, but the file fails _looks_like_ffmpeg → fallback.
        monkeypatch.delenv("FFMPEG_PATH", raising=False)
        with (
            patch.object(fp, "_project_root", return_value=tmp_path / "no_bundle"),
            patch.object(fp.shutil, "which", return_value=str(tmp_path / "ghost-ffmpeg")),
        ):
            # The "ghost" path does not exist → is_file() False → fallback.
            assert fp.get_ffmpeg_executable() == "ffmpeg"


class TestGetFfmpegExecutableFallback:
    """Final fallback: literal "ffmpeg" string."""

    def test_returns_ffmpeg_when_nothing_found(self, tmp_path, monkeypatch):
        monkeypatch.delenv("FFMPEG_PATH", raising=False)
        with (
            patch.object(fp, "_project_root", return_value=tmp_path / "no_bundle"),
            patch.object(fp.shutil, "which", return_value=None),
        ):
            assert fp.get_ffmpeg_executable() == "ffmpeg"

    def test_always_returns_a_string(self, tmp_path, monkeypatch):
        monkeypatch.delenv("FFMPEG_PATH", raising=False)
        with (
            patch.object(fp, "_project_root", return_value=tmp_path / "no_bundle"),
            patch.object(fp.shutil, "which", return_value=None),
        ):
            assert isinstance(fp.get_ffmpeg_executable(), str)


class TestPrecedenceOrdering:
    """End-to-end precedence: env > bundled > PATH."""

    def test_env_beats_bundled_and_path(self, tmp_path, monkeypatch):
        env_f = _make_fake_ffmpeg(tmp_path / "env", name=fp._BUNDLED_RELATIVE.name)
        _make_fake_ffmpeg(tmp_path / "ffmpeg" / "bin", name=fp._BUNDLED_RELATIVE.name)
        path_f = _make_fake_ffmpeg(tmp_path / "onpath", name=fp._BUNDLED_RELATIVE.name)
        monkeypatch.setenv("FFMPEG_PATH", str(env_f))
        with (
            patch.object(fp, "_project_root", return_value=tmp_path),
            patch.object(fp.shutil, "which", return_value=str(path_f)),
        ):
            assert fp.get_ffmpeg_executable() == str(env_f)

    def test_bundled_beats_path(self, tmp_path, monkeypatch):
        monkeypatch.delenv("FFMPEG_PATH", raising=False)
        bundled = _make_fake_ffmpeg(tmp_path / "ffmpeg" / "bin", name=fp._BUNDLED_RELATIVE.name)
        path_f = _make_fake_ffmpeg(tmp_path / "onpath", name=fp._BUNDLED_RELATIVE.name)
        with (
            patch.object(fp, "_project_root", return_value=tmp_path),
            patch.object(fp.shutil, "which", return_value=str(path_f)),
        ):
            assert fp.get_ffmpeg_executable() == str(bundled)


class TestNoMemoization:
    """The resolver is not cached; it re-reads env/PATH on every call."""

    def test_reflects_env_change_between_calls(self, tmp_path, monkeypatch):
        first = _make_fake_ffmpeg(tmp_path / "a", name=fp._BUNDLED_RELATIVE.name)
        second = _make_fake_ffmpeg(tmp_path / "b", name=fp._BUNDLED_RELATIVE.name)
        monkeypatch.setenv("FFMPEG_PATH", str(first))
        assert fp.get_ffmpeg_executable() == str(first)
        # Change env → next call must reflect the new value (no stale cache).
        monkeypatch.setenv("FFMPEG_PATH", str(second))
        assert fp.get_ffmpeg_executable() == str(second)

    def test_which_consulted_each_call(self, tmp_path, monkeypatch):
        monkeypatch.delenv("FFMPEG_PATH", raising=False)
        f = _make_fake_ffmpeg(tmp_path)
        with (
            patch.object(fp, "_project_root", return_value=tmp_path / "no_bundle"),
            patch.object(fp.shutil, "which", return_value=str(f)) as m_which,
        ):
            fp.get_ffmpeg_executable()
            fp.get_ffmpeg_executable()
        # Not memoized → which("ffmpeg") is called on both invocations.
        assert m_which.call_count == 2


class TestIsFfmpegAvailable:
    """Tests for `is_ffmpeg_available`."""

    def test_true_when_resolves_to_existing_file(self, tmp_path, monkeypatch):
        f = _make_fake_ffmpeg(tmp_path)
        monkeypatch.setenv("FFMPEG_PATH", str(f))
        assert fp.is_ffmpeg_available() is True

    def test_true_when_fallback_resolvable_via_which(self, tmp_path, monkeypatch):
        # get_ffmpeg_executable() returns the literal "ffmpeg" (not a file),
        # but which("ffmpeg") resolves it → available.
        monkeypatch.delenv("FFMPEG_PATH", raising=False)
        with (
            patch.object(fp, "_project_root", return_value=tmp_path / "no_bundle"),
            patch.object(fp.shutil, "which", return_value=str(_make_fake_ffmpeg(tmp_path))),
        ):
            assert fp.is_ffmpeg_available() is True

    def test_false_when_nothing_available(self, tmp_path, monkeypatch):
        monkeypatch.delenv("FFMPEG_PATH", raising=False)
        with (
            patch.object(fp, "_project_root", return_value=tmp_path / "no_bundle"),
            patch.object(fp.shutil, "which", return_value=None),
        ):
            # get_ffmpeg_executable() → "ffmpeg" (not a file); which() → None.
            assert fp.is_ffmpeg_available() is False


class TestModuleConstants:
    """Sanity checks on module-level constants and the project-root helper."""

    def test_bundled_relative_layout(self):
        parts = fp._BUNDLED_RELATIVE.parts
        assert parts[0] == "ffmpeg"
        assert parts[1] == "bin"
        assert "ffmpeg" in parts[2].lower()

    def test_bundled_relative_extension_matches_os(self):
        if os.name == "nt":
            assert fp._BUNDLED_RELATIVE.name == "ffmpeg.exe"
        else:
            assert fp._BUNDLED_RELATIVE.name == "ffmpeg"

    def test_project_root_points_at_repo(self):
        root = fp._project_root()
        # ffmpeg_path.py lives at <root>/utils/media/ffmpeg_path.py.
        assert (root / "utils" / "media" / "ffmpeg_path.py").is_file()
