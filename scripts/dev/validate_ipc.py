#!/usr/bin/env python3
"""Opt-in END-TO-END validation of the Tauri dashboard's REAL Rust IPC bridge.

Launches the built dashboard ``.exe`` through ``tauri-driver`` (W3C WebDriver over
WebView2) and invokes read-only Rust commands two ways:
  A) ``window.__TAURI_INTERNALS__.invoke`` — the raw IPC bridge
  B) ``import('@tauri-apps/api/core').invoke`` — exercises the import-map path
     (proves IPC works with ``withGlobalTauri: false`` — the H5 hardening)
No side effects (no start/stop/clear commands are called).

Prerequisites (one-time, Windows):
    cargo install tauri-driver --locked
    # download msedgedriver matching your WebView2 runtime version into
    #   native_dashboard/.drivers/msedgedriver.exe   (https://msedgedriver.microsoft.com)
    pip install selenium
    cargo tauri build --no-bundle      # so target/release/<app>.exe exists

Run from the repo root::

    python scripts/dev/validate_ipc.py

Exit code 0 = real Rust IPC round-trip works (bridge + import-map); 1 otherwise.
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_NATIVE = _REPO / "native_dashboard"
_PORT = 4444

# The Tauri release binary may be named after the cargo bin or the productName.
_APP_CANDIDATES = [
    _NATIVE / "target" / "release" / "bot-dashboard.exe",
    _NATIVE / "target" / "release" / "Discord Bot Dashboard.exe",
]
_MSED = _NATIVE / ".drivers" / "msedgedriver.exe"
_TD = Path.home() / ".cargo" / "bin" / "tauri-driver.exe"


def _find_app() -> Path | None:
    for p in _APP_CANDIDATES:
        if p.exists():
            return p
    # fall back to any .exe in target/release
    rel = _NATIVE / "target" / "release"
    if rel.is_dir():
        exes = [p for p in rel.glob("*.exe") if "deps" not in str(p)]
        if exes:
            return exes[0]
    return None


def main() -> int:
    from selenium import webdriver
    from selenium.webdriver.common.options import ArgOptions

    app = _find_app()
    for label, p in (("app", app), ("msedgedriver", _MSED), ("tauri-driver", _TD)):
        present = p is not None and Path(p).exists()
        print(f"{label}: {'OK' if present else 'MISSING'} | {p}")
        if not present:
            print("Prerequisite missing — see the module docstring for setup.")
            return 1

    td = subprocess.Popen(
        [str(_TD), "--port", str(_PORT), "--native-driver", str(_MSED)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    time.sleep(3.0)

    driver = None
    a_ok = b_ok = False
    try:
        opts = ArgOptions()
        opts.set_capability("tauri:options", {"application": str(app)})
        driver = webdriver.Remote(command_executor=f"http://127.0.0.1:{_PORT}", options=opts)
        driver.set_script_timeout(20)

        deadline = time.time() + 30
        ready = False
        while time.time() < deadline:
            try:
                st = driver.execute_script(
                    "return [document.readyState, !!window.__TAURI_INTERNALS__]"
                )
                if st and st[0] == "complete" and st[1]:
                    ready = True
                    break
            except Exception:
                pass
            time.sleep(0.5)
        print(f"page ready + __TAURI_INTERNALS__: {ready}")

        a = driver.execute_async_script(
            "const cb=arguments[arguments.length-1];"
            "try{window.__TAURI_INTERNALS__.invoke('get_base_path')"
            ".then(r=>cb({ok:true,v:r})).catch(e=>cb({ok:false,e:String(e)}));}"
            "catch(e){cb({ok:false,e:String(e)});}"
        )
        print(f"[A get_base_path via __TAURI_INTERNALS__]: {a}")
        a_ok = bool(a.get("ok")) and isinstance(a.get("v"), str) and len(a.get("v", "")) > 0

        b = driver.execute_async_script(
            "const cb=arguments[arguments.length-1];"
            "import('@tauri-apps/api/core').then(m=>m.invoke('get_status'))"
            ".then(r=>cb({ok:true,v:r})).catch(e=>cb({ok:false,e:String(e)}));"
        )
        print(f"[B get_status via import-map]: {b}")
        b_ok = bool(b.get("ok")) and b.get("v") is not None
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass
        td.terminate()
        try:
            _o, err = td.communicate(timeout=5)
        except Exception:
            td.kill()
            err = b""
        tail = (err or b"").decode("utf-8", "replace")[-400:].strip()
        if tail:
            print(f"--- tauri-driver stderr ---\n{tail}")

    ok = a_ok and b_ok
    print(f"RESULT: {'PASS — Rust IPC round-trip works (bridge + import-map)' if ok else f'FAIL (bridge={a_ok}, importmap={b_ok})'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
