"""Regression tests for py-utils-web-004.

find_all_bot_processes / find_all_dev_watchers used to carry a dead ignore-list
guard (``not any(x in matched_name ...)``) that could never fire because
``matched_name`` was always the literal basename ('bot.py' / 'dev_watcher.py').
The guard was removed; the exact-basename match alone does the filtering. These
tests assert the real, observable behavior so the filter cannot silently
regress.

These live in a dedicated, uniquely-owned module (and uniquely-named classes)
because tests/test_self_healer.py already defines two classes named
TestFindAllBotProcesses / TestFindAllDevWatchers, so pytest collects only the
last definition of each — extra methods added to the earlier copies are
silently dropped.
"""

from unittest.mock import MagicMock, patch


def _proc(pid: int, cmdline: list[str]) -> MagicMock:
    p = MagicMock()
    p.info = {
        "pid": pid,
        "name": "python",
        "cmdline": cmdline,
        "create_time": 1000.0,
    }
    return p


class TestAudit3FindAllBotProcesses:
    """Exact-basename matching for find_all_bot_processes."""

    def test_matches_exact_bot_py(self):
        """A real `python bot.py` is matched."""
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()
        with patch("psutil.process_iter", return_value=[_proc(4321, ["python", "bot.py"])]):
            with patch("psutil.Process", return_value=MagicMock()):
                result = healer.find_all_bot_processes()

        assert len(result) == 1
        assert result[0]["pid"] == 4321

    def test_matches_bot_py_under_test_env_path(self):
        """`C:\\test_env\\bot.py` must NOT be dropped just because its path
        contains a 'test_' token — the removed ignore-list previously risked
        undercounting real bots and defeating duplicate detection."""
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()
        proc = _proc(5555, ["python", "C:\\test_env\\bot.py"])
        with patch("psutil.process_iter", return_value=[proc]):
            with patch("psutil.Process", return_value=MagicMock()):
                result = healer.find_all_bot_processes()

        assert len(result) == 1
        assert result[0]["pid"] == 5555

    def test_does_not_match_test_bot_or_backup(self):
        """Exact basename match rejects 'test_bot.py' and 'bot.py_backup'."""
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()
        procs = [
            _proc(6001, ["python", "test_bot.py"]),
            _proc(6002, ["python", "bot.py_backup"]),
        ]
        with patch("psutil.process_iter", return_value=procs):
            result = healer.find_all_bot_processes()

        assert len(result) == 0


class TestAudit3FindAllDevWatchers:
    """Exact-basename matching for find_all_dev_watchers."""

    def test_matches_exact_dev_watcher_py(self):
        """A real `python scripts\\dev_watcher.py` is matched."""
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()
        proc = _proc(7001, ["python", "scripts\\dev_watcher.py"])
        with patch("psutil.process_iter", return_value=[proc]):
            with patch("psutil.Process", return_value=MagicMock()):
                result = healer.find_all_dev_watchers()

        assert len(result) == 1
        assert result[0]["pid"] == 7001

    def test_does_not_match_pytest_dev_watcher(self):
        """Exact basename match rejects `python -m pytest
        tests/test_dev_watcher.py` so a heal action won't kill the test runner."""
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()
        proc = _proc(7002, ["python", "-m", "pytest", "tests/test_dev_watcher.py"])
        with patch("psutil.process_iter", return_value=[proc]):
            result = healer.find_all_dev_watchers()

        assert len(result) == 0
