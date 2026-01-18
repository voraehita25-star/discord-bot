"""
Test script for bot_manager.py functions
"""

import sys

sys.path.insert(0, ".")

from scripts.bot_manager import (
    find_all_bot_processes,
    find_all_dev_watcher_processes,
    get_bot_status,
)

print("=" * 60)
print("  BOT MANAGER FUNCTION TESTS")
print("=" * 60)
print()

# Test 1: Status Detection
print("[TEST 1] get_bot_status()")
try:
    status = get_bot_status()
    print(f"  ✅ Running: {status['running']}")
    print(f"  ✅ All PIDs: {status['all_pids']}")
    print(f"  ✅ Dev Watcher PIDs: {status['dev_watcher_pids']}")
    print(f"  ✅ Memory: {status['memory_mb']} MB")
    print(f"  ✅ Launcher: {status['launcher']['name']}")
except Exception as e:
    print(f"  ❌ FAILED: {e}")
print()

# Test 2: Process Finding
print("[TEST 2] find_all_bot_processes()")
try:
    bots = find_all_bot_processes()
    print(f"  ✅ Bot processes found: {len(bots)}")
    for pid in bots:
        print(f"      - PID: {pid}")
except Exception as e:
    print(f"  ❌ FAILED: {e}")
print()

# Test 3: Dev Watcher Finding
print("[TEST 3] find_all_dev_watcher_processes()")
try:
    watchers = find_all_dev_watcher_processes()
    print(f"  ✅ Dev watchers found: {len(watchers)}")
    for pid in watchers:
        print(f"      - PID: {pid}")
except Exception as e:
    print(f"  ❌ FAILED: {e}")
print()

# Test 4: Colors Module
print("[TEST 4] Colors class import")
try:
    from scripts.bot_manager import Colors

    print(f"  ✅ Colors.GREEN: {Colors.GREEN!r}")
    print(f"  ✅ Colors.RED: {Colors.RED!r}")
    print(f"  ✅ Colors.RESET: {Colors.RESET!r}")
except Exception as e:
    print(f"  ❌ FAILED: {e}")
print()

# Test 5: Box Drawing Functions
print("[TEST 5] Box drawing functions")
try:
    from scripts.bot_manager import box_bottom, box_mid, box_top, get_display_width, pad_line

    top = box_top()
    mid = box_mid()
    bottom = box_bottom()
    line = pad_line("Test Line")
    width = get_display_width("Hello 🤖 สวัสดี")
    print(f"  ✅ box_top() works: {len(top)} chars")
    print(f"  ✅ box_mid() works: {len(mid)} chars")
    print(f"  ✅ box_bottom() works: {len(bottom)} chars")
    print(f"  ✅ pad_line() works: {len(line)} chars")
    print(f"  ✅ get_display_width() = {width}")
except Exception as e:
    print(f"  ❌ FAILED: {e}")
print()

# Test 6: Self-Healer Import
print("[TEST 6] SelfHealer import")
try:
    from scripts.bot_manager import SELF_HEALER_AVAILABLE

    print(f"  ✅ SELF_HEALER_AVAILABLE: {SELF_HEALER_AVAILABLE}")
    if SELF_HEALER_AVAILABLE:
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer("test_script")
        diagnosis = healer.diagnose()
        print(f"  ✅ SelfHealer.diagnose() works: {len(diagnosis['issues'])} issues")
except Exception as e:
    print(f"  ❌ FAILED: {e}")
print()

print("=" * 60)
print("  ALL TESTS COMPLETED")
print("=" * 60)
