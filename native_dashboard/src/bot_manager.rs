// This module is Windows-only (the dashboard targets Windows + WebView2 exclusively)
#[cfg(not(target_os = "windows"))]
compile_error!("bot_manager.rs requires Windows (uses CommandExt, taskkill, etc.)");

use chrono::{DateTime, Local};
use serde::{Deserialize, Serialize};
use std::fs;
use std::io::{Read, Seek, SeekFrom};
use std::os::windows::process::CommandExt;
use std::path::PathBuf;
use std::process::{Child, Command};
use sysinfo::System;

const CREATE_NO_WINDOW: u32 = 0x08000000;

/// Absolute path to taskkill.exe so we don't fall through to a poisoned
/// PATH entry. On every supported Windows build this lives in System32.
///
/// The `%SystemRoot%` env var is validated the same way `open_folder` in
/// main.rs validates it: accept the env value only if it canonicalizes to
/// the same target as `C:\Windows`. A poisoned `SystemRoot=C:\Attacker`
/// would otherwise let an attacker-planted `taskkill.exe` run with our
/// privileges; falling back to the hardcoded default closes that gap.
fn taskkill_path() -> String {
    let sysroot_canonical = std::env::var("SystemRoot")
        .ok()
        .and_then(|s| std::fs::canonicalize(&s).ok());
    let default_root_canonical = std::fs::canonicalize("C:\\Windows").ok();
    match (sysroot_canonical, default_root_canonical.as_ref()) {
        (Some(env_root), Some(def_root)) if &env_root == def_root => env_root
            .join("System32")
            .join("taskkill.exe")
            .to_string_lossy()
            .into_owned(),
        // Windows genuinely not installed on C: — `C:\Windows` failed to
        // canonicalize, so the hardcoded fallback below cannot exist either and
        // every taskkill spawn would silently fail (orphaned bots from previous
        // sessions become unkillable from the UI). A validated env SystemRoot is
        // the only remaining source; trust it only if the taskkill.exe it points
        // at actually exists. On a normal C:\Windows host this arm never fires,
        // so the strict equality check above stays the anti-poisoning gate.
        (Some(env_root), None) => {
            let candidate = env_root.join("System32").join("taskkill.exe");
            if candidate.is_file() {
                candidate.to_string_lossy().into_owned()
            } else {
                String::from("C:\\Windows\\System32\\taskkill.exe")
            }
        }
        // Fallback to the canonical default — virtually every Windows
        // install has SystemRoot=C:\Windows, and if the env var is missing
        // or fails to canonicalize-match we must not trust it.
        _ => String::from("C:\\Windows\\System32\\taskkill.exe"),
    }
}

/// Validate a candidate Python interpreter path the same way the `PYTHON_CMD`
/// branch in `BotManager::new` does: the file must exist, canonicalize, and have
/// a `python`/`python3` basename. Returns the canonicalized absolute path on
/// success, `None` (with a warning) otherwise. Shared so the env-var branch and
/// the PATH-resolution fallback apply identical checks — and so the interpreter
/// is always pinned to a validated absolute path, mirroring `taskkill_path()` /
/// `explorer.exe` pinning, never a bare relative name resolved at spawn time.
fn validate_python_path(p: &std::path::Path) -> Option<String> {
    if !p.exists() {
        return None;
    }
    let canonical = match p.canonicalize() {
        Ok(c) => c,
        Err(_) => return None,
    };
    let fname = canonical.file_name().unwrap_or_default().to_string_lossy();
    let fname_lower = fname.to_lowercase();
    if fname_lower == "python.exe"
        || fname_lower == "python3.exe"
        || fname_lower == "python"
        || fname_lower == "python3"
    {
        Some(canonical.to_string_lossy().to_string())
    } else {
        None
    }
}

/// Resolve `python`/`python3` against the `PATH` env var to a validated absolute
/// path, instead of spawning the bare name and letting Windows' `CreateProcessW`
/// re-resolve it (which also searches the current/application directory) at every
/// spawn — the PATH-hijack-to-RCE vector this file already pins `taskkill.exe`
/// and `explorer.exe` against. We do the lookup ONCE at construction and pin the
/// result, so a poisoned PATH entry planted later cannot redirect the spawn. A
/// legitimate install that relies on a `python` on PATH still works: the real
/// interpreter is found here and recorded as an absolute path. Returns `None` if
/// no validated interpreter is found on PATH.
fn resolve_python_on_path() -> Option<String> {
    let path_var = std::env::var_os("PATH")?;
    // Try the common interpreter basenames in priority order.
    let candidates = ["python.exe", "python3.exe"];
    for dir in std::env::split_paths(&path_var) {
        for name in &candidates {
            if let Some(resolved) = validate_python_path(&dir.join(name)) {
                return Some(resolved);
            }
        }
    }
    None
}

#[derive(Debug, Serialize, Deserialize)]
pub struct BotStatus {
    pub is_running: bool,
    pub pid: Option<u32>,
    pub uptime: String,
    pub memory_mb: f64,
    pub mode: String,
}

/// Progress of a dashboard-initiated bot start.
///
/// `is_running` alone is a flat boolean and can't tell a slow-but-healthy
/// cold start apart from a process that crashed during startup — both look
/// like "not running yet". That ambiguity is what made the old frontend poll
/// fire a spurious "Bot start timed out" warning on every cold start. By
/// pairing the PID-file signal with the liveness of the `Child` we spawned in
/// `start()`, we can report the three states the UI actually needs to react
/// to differently.
///
/// Serialized internally-tagged on `state` so the TypeScript side can switch
/// on a discriminated union (`{ state: "running" }`, `{ state: "exited",
/// code: 1 }`, …).
#[derive(Debug, Serialize, Deserialize, PartialEq)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum StartProgress {
    /// `bot.pid` is written and its cmdline verifies — the bot is up.
    Running,
    /// The spawned process is still alive but hasn't written its PID yet
    /// (still importing / running startup checks). Normal on a cold start;
    /// the UI should keep waiting, NOT warn.
    Starting,
    /// The process we spawned has already exited without ever reaching the
    /// running state — startup genuinely failed (bad token `sys.exit`, an
    /// import-time crash, …). `code` is the OS exit code when known.
    Exited { code: Option<i32> },
    /// No tracked startup child: the bot was started outside the dashboard,
    /// or the start outcome was already consumed. The caller should fall back
    /// to plain status polling.
    Unknown,
}

pub struct BotManager {
    base_path: PathBuf,
    /// Canonicalized `base_path` (lowercased string form), computed once at
    /// construction. Used as a fallback comparison in `process_belongs_to_us`
    /// so a process whose cmdline/cwd uses a Windows 8.3 short path (e.g.
    /// `C:\Users\RUNNER~1\BOT`) still matches our long-form `base_path` — a
    /// plain substring/equality check would otherwise fail closed and the bot
    /// would look dead in the UI. `None` if canonicalization failed (the
    /// path doesn't exist yet), in which case we fall back to the literal
    /// `base_path` check only. NB: only `base_path` is canonicalized once here;
    /// each candidate process's cwd/exe is still canonicalized per-iteration in
    /// `process_belongs_to_us` (intentionally — see the comment at that call
    /// site for why that one cannot be hoisted or cached).
    base_path_canonical: Option<String>,
    /// Process snapshot used by every is_running / get_status / orphan-kill
    /// path. ⚠️ NEVER call `sys.refresh_processes(...)` directly on this —
    /// always go through `Self::refresh_processes_with_cmd`. The plain
    /// `refresh_processes` does NOT populate `process.cmd()` in sysinfo
    /// 0.38, which silently breaks our PID-reuse defence (see helper doc).
    sys: System,
    python_cmd: String,
    /// Held Child handles so we can `wait()` on stop and avoid leaking
    /// Windows process handles / zombie process descriptors.
    child: Option<Child>,
    dev_watcher_child: Option<Child>,
}

#[allow(dead_code)]
impl BotManager {
    pub fn new(base_path: PathBuf) -> Self {
        let mut sys = System::new();
        Self::refresh_processes_with_cmd(&mut sys);
        // Resolve the interpreter to a VALIDATED ABSOLUTE PATH, pinned once here
        // (never a bare relative "python" re-resolved by CreateProcessW at spawn
        // time — that path-search includes the current/application directory and
        // PATH, the PATH-hijack-to-RCE vector this file pins taskkill.exe and
        // explorer.exe against). Order: PYTHON_CMD env → bundled .venv → a
        // `python`/`python3` found on PATH. If none validates, store an empty
        // sentinel; start()/start_dev() then refuse to spawn and return an
        // explicit error rather than launching an unpinned name.
        let python_cmd = std::env::var("PYTHON_CMD")
            .ok()
            .and_then(|cmd| {
                let resolved = validate_python_path(std::path::Path::new(&cmd));
                if resolved.is_none() {
                    eprintln!(
                        "WARNING: PYTHON_CMD '{}' is not a usable Python interpreter, ignoring",
                        cmd
                    );
                }
                resolved
            })
            .or_else(|| {
                let venv_python = base_path.join(".venv").join("Scripts").join("python.exe");
                validate_python_path(&venv_python)
            })
            .or_else(resolve_python_on_path)
            .unwrap_or_default();
        if python_cmd.is_empty() {
            eprintln!(
                "WARNING: No trusted Python interpreter found (PYTHON_CMD unset/invalid, no \
                 .venv under base_path, none on PATH); Start/Start-Dev will report an error \
                 until PYTHON_CMD is set to an absolute interpreter path."
            );
        }
        // Canonicalize base_path once so process_belongs_to_us can match
        // processes that report a Windows 8.3 short path form of the same dir.
        // Fail-closed: if the path can't be canonicalized we keep None and the
        // comparison falls back to the literal base_path check.
        let base_path_canonical = std::fs::canonicalize(&base_path)
            .ok()
            .map(|p| p.to_string_lossy().to_lowercase().to_string());
        Self {
            base_path,
            base_path_canonical,
            sys,
            python_cmd,
            child: None,
            dev_watcher_child: None,
        }
    }

    /// Reap a stored Child if its underlying process has exited. Always non-blocking.
    /// Used to avoid leaking handles when the bot exits on its own.
    fn reap_finished_children(&mut self) {
        if let Some(c) = self.child.as_mut() {
            if let Ok(Some(_)) = c.try_wait() {
                self.child = None;
            }
        }
        if let Some(c) = self.dev_watcher_child.as_mut() {
            if let Ok(Some(_)) = c.try_wait() {
                self.dev_watcher_child = None;
            }
        }
    }

    /// Force-kill a still-live tracked normal-mode bot child (tree) and wait().
    ///
    /// `is_running()` only reports true once bot.py has written bot.pid, so a
    /// bot still in its multi-second cold start (imports / FAISS / RAG load) is
    /// invisible to the `is_running()` guards in `start()`/`start_dev()`. Both
    /// spawn paths must therefore tear down any tracked-but-still-booting normal
    /// bot before spawning, or two bot.py processes end up connected to Discord
    /// on the same token. `reap_finished_children()` only releases ALREADY-exited
    /// children, so it cannot cover the booting case. Dropping the handle without
    /// wait() would (on Windows) close the handle and leave the process running
    /// detached (an orphan), so we taskkill the tree, then kill()+wait().
    fn kill_tracked_bot_child(&mut self) {
        self.reap_finished_children();
        if let Some(mut old) = self.child.take() {
            let old_pid = old.id();
            let _ = Command::new(taskkill_path())
                .args(["/PID", &old_pid.to_string(), "/F", "/T"])
                .creation_flags(CREATE_NO_WINDOW)
                .output();
            let _ = old.kill();
            let _ = old.wait();
        }
    }

    fn pid_file(&self) -> PathBuf {
        self.base_path.join("bot.pid")
    }

    /// **The only correct way to refresh processes in this module.**
    ///
    /// ## Why this exists (read before "simplifying"):
    ///
    /// `sysinfo::System::refresh_processes(ProcessesToUpdate::All, true)` —
    /// the obvious one-liner you'd reach for — silently does NOT populate
    /// `process.cmd()` in sysinfo 0.38. Its default `ProcessRefreshKind`
    /// includes memory/cpu/exe/disk_usage/tasks but omits `cmd`.
    ///
    /// Every "is the bot still running?" path in this file relies on
    /// inspecting `process.cmd()` to verify the cmdline contains
    /// `bot.py` + `base_path` — this is our defence against Windows PID
    /// reuse, where a recycled PID could otherwise be reported as our
    /// bot. If `cmd()` returns the empty slice (which it does without
    /// `with_cmd()`), the check fails *closed*: `is_running` returns
    /// false, so `get_status` never reports the bot as running and
    /// `start_progress` can never reach `Running` — the status badge
    /// stays stopped and the bot looks dead in the UI even when it's
    /// running fine.
    ///
    /// This was a real regression introduced in PR #75 (audit-fixes,
    /// 2026-05-06) when the cmdline check was added to is_running but
    /// the matching refresh-kind change was not.
    ///
    /// ## Rules:
    /// - Call `Self::refresh_processes_with_cmd(&mut self.sys)` (or
    ///   `&mut sys` in the constructor) before any code that reads
    ///   `process.cmd()`, `process.memory()`, or relies on the live
    ///   process list reflecting reality.
    /// - Do NOT call `self.sys.refresh_processes(...)` directly.
    /// - Do NOT switch the `with_cmd` arg to `OnlyIfNotSet` — Windows
    ///   PID reuse can hand the same PID to a different process between
    ///   refreshes; we want the cmdline re-read every time.
    fn refresh_processes_with_cmd(sys: &mut System) {
        sys.refresh_processes_specifics(
            sysinfo::ProcessesToUpdate::All,
            true,
            sysinfo::ProcessRefreshKind::nothing()
                .with_memory()
                .with_cpu()
                .with_exe(sysinfo::UpdateKind::OnlyIfNotSet)
                .with_cmd(sysinfo::UpdateKind::Always)
                // `with_cwd` is required for `process.cwd()` to be populated
                // (like `with_cmd` above). The "belongs to us" check accepts a
                // process whose cwd == base_path even when base_path is absent
                // from argv — the dev-watcher spawns the bot with a RELATIVE
                // "bot.py" + cwd=PROJECT_ROOT, so base_path never appears in
                // argv unless the interpreter itself lives under base_path.
                .with_cwd(sysinfo::UpdateKind::Always),
        );
    }

    /// Whether `process` belongs to THIS dashboard's project tree.
    ///
    /// Two ways a `bot.py` process can be ours:
    ///   1. its joined argv contains `base_path` (the production `start()` path
    ///      spawns with the absolute `base_path.join("bot.py")`), or
    ///   2. its working directory IS `base_path`. The dev-watcher spawns the bot
    ///      with a RELATIVE `"bot.py"` arg and `cwd=PROJECT_ROOT`, so the
    ///      base_path string never lands in argv unless the interpreter itself
    ///      lives under base_path (true for the bundled `.venv`, false for a bare
    ///      `python` on PATH / an external PYTHON_CMD) — the cwd match recovers
    ///      that case so dev-mode bots aren't reported as stopped.
    ///
    /// `base_path_str` is the caller-precomputed lowercased base_path so each
    /// site keeps its existing single allocation. `base_path_canonical` is the
    /// canonicalized lowercased base_path (`self.base_path_canonical`) used as a
    /// fallback so a process reporting a Windows 8.3 short path of the same
    /// directory still matches — see the field doc on `BotManager`.
    fn process_belongs_to_us(
        process: &sysinfo::Process,
        cmdline: &str,
        base_path_str: &str,
        base_path_canonical: Option<&str>,
    ) -> bool {
        if base_path_str.is_empty() {
            return false;
        }
        if cmdline.contains(base_path_str) {
            return true;
        }
        if process
            .cwd()
            .map(|cwd| cwd.to_string_lossy().to_lowercase() == base_path_str)
            .unwrap_or(false)
        {
            return true;
        }
        // Fallback for Windows 8.3 short paths: the literal string compares
        // above miss when the process reports e.g. `C:\Users\RUNNER~1\BOT` for
        // our long-form base_path. Canonicalize the process cwd / exe and the
        // base_path (precomputed) and compare those. Fail-closed: any
        // canonicalize error simply yields no match here.
        //
        // NOTE for future audits: the cwd/exe canonicalize below is per-process
        // by nature — each Python process has its OWN cwd/exe that resolves
        // independently, so it CANNOT be hoisted out of the orphan-scan loop the
        // way `base_path` is (base_path is canonicalized exactly once into the
        // `base_path_canonical` field). It already runs only on the slow path:
        // we reach here only after the `cmdline.contains` / `cwd == base_path`
        // string fast-paths above both miss, and the exe canonicalize is skipped
        // entirely once the cwd canonicalize matches (early `return true`), so
        // the syscall cost is already bounded. The only loop caller is
        // `kill_orphan_bot_processes`, hit on start/stop/restart — never the
        // frequent status poll — so that cost is acceptable. This is a
        // fail-closed security check (resolving the 8.3 short path + symlinks is
        // what defeats path aliasing and thus Windows PID-reuse), so it must NOT
        // be cached, memoized across iterations, or gated behind a flag — any
        // such caching would reopen a TOCTOU / PID-reuse hole.
        if let Some(base_canon) = base_path_canonical {
            let cwd_matches = process
                .cwd()
                .and_then(|cwd| std::fs::canonicalize(cwd).ok())
                .map(|c| c.to_string_lossy().to_lowercase() == base_canon)
                .unwrap_or(false);
            if cwd_matches {
                return true;
            }
            // Accept a process whose canonicalized exe lives under base_path
            // (covers the bundled `.venv` interpreter spawn where base_path
            // never appears literally in argv). Use component-aware
            // `Path::starts_with` rather than a raw string prefix so a
            // base_path of `...\bot` does NOT prefix-match an unrelated
            // interpreter living under a sibling `...\bot-other\.venv\...`.
            // Both sides are lowercased first to keep the case-insensitive
            // match the surrounding code relies on.
            let exe_under_base = process
                .exe()
                .and_then(|exe| std::fs::canonicalize(exe).ok())
                .map(|c| {
                    let exe_lower = c.to_string_lossy().to_lowercase();
                    std::path::Path::new(&exe_lower).starts_with(std::path::Path::new(base_canon))
                })
                .unwrap_or(false);
            if exe_under_base {
                return true;
            }
        }
        false
    }

    fn dev_watcher_pid_file(&self) -> PathBuf {
        self.base_path.join("dev_watcher.pid")
    }

    fn get_dev_watcher_pid(&self) -> Option<u32> {
        fs::read_to_string(self.dev_watcher_pid_file())
            .ok()?
            .trim()
            .parse()
            .ok()
    }

    /// True if the process's ENTRY SCRIPT basename — the first non-interpreter,
    /// non-flag argv token (skip cmd[0] and any leading `-` option) — equals
    /// `script`. `cmd` items and `script` are expected already lowercased. This is
    /// the exact gate `reap_orphan_dev_watcher` uses; `stop_dev_watcher` and
    /// `get_status`'s mode detection call it so all three cannot drift (a bare
    /// python-name + `process_belongs_to_us` match would force-kill / mislabel an
    /// unrelated project python after Windows PID reuse).
    fn entry_script_is(cmd: &[String], script: &str) -> bool {
        cmd.iter()
            .skip(1)
            .find(|arg| !arg.starts_with('-'))
            .map(|arg| {
                std::path::Path::new(arg.as_str())
                    .file_name()
                    .map(|f| f.to_string_lossy().to_lowercase() == script)
                    .unwrap_or(false)
            })
            .unwrap_or(false)
    }

    fn stop_dev_watcher(&mut self) {
        if let Some(pid) = self.get_dev_watcher_pid() {
            // Verify the PID actually points at a python process before
            // killing — Windows recycles PIDs aggressively and the watcher
            // may have died long ago, leaving the PID assigned to an
            // unrelated foreground program (browser, IDE, etc.). The
            // production stop() does the same name check; this path used
            // to skip it.
            Self::refresh_processes_with_cmd(&mut self.sys);
            let base_path_str = self.base_path.to_string_lossy().to_lowercase().to_string();
            // Require BOTH a python name AND that the process belongs to our own
            // project tree (cmdline references base_path OR cwd IS base_path) AND
            // that its entry script is dev_watcher.py — a bare PID match is never
            // trusted because Windows reuses PIDs, so after reuse the recorded PID
            // could map to an unrelated python process tree (enforces the same
            // entry-script + belongs-to-us gate as reap_orphan_dev_watcher).
            let is_ours = self
                .sys
                .process(sysinfo::Pid::from_u32(pid))
                .map(|p| {
                    let name = p.name().to_string_lossy().to_lowercase();
                    if !name.contains("python") {
                        return false;
                    }
                    let cmd: Vec<String> = p
                        .cmd()
                        .iter()
                        .map(|s| s.to_string_lossy().to_lowercase().to_string())
                        .collect();
                    // Entry-script gate (previously missing): only kill when this
                    // python's ENTRY SCRIPT is dev_watcher.py — mirrors
                    // reap_orphan_dev_watcher so a stale/reused PID pointing at an
                    // unrelated project python (pytest under base_path, the bot
                    // itself) is not force-killed.
                    if !Self::entry_script_is(&cmd, "dev_watcher.py") {
                        return false;
                    }
                    let cmdline = cmd.join(" ");
                    Self::process_belongs_to_us(
                        p,
                        &cmdline,
                        &base_path_str,
                        self.base_path_canonical.as_deref(),
                    )
                })
                .unwrap_or(false);

            if is_ours {
                let _ = Command::new(taskkill_path())
                    .args(["/PID", &pid.to_string(), "/F", "/T"])
                    .creation_flags(CREATE_NO_WINDOW)
                    .output();
            }
            let _ = fs::remove_file(self.dev_watcher_pid_file());
        }

        // Reap our stored dev-watcher Child to release the process handle.
        if let Some(mut c) = self.dev_watcher_child.take() {
            let _ = c.kill();
            let _ = c.wait();
        }
    }

    /// Kill any orphan bot.py processes that may have survived a previous stop.
    /// Uses sysinfo to scan all processes for python running bot.py.
    /// Scoped to THIS dashboard's project tree (self.base_path) so we never
    /// kill someone else's unrelated bot.py running on the same machine.
    ///
    /// Returns `true` if at least one orphan was sent a kill. This return value
    /// is INFORMATIONAL ONLY — every current caller discards it (the kills are
    /// best-effort and the subsequent `process_is_gone` polling is what the
    /// orchestration actually waits on); it is kept as a return rather than `()`
    /// so a future caller can branch on "did we kill anything" without a rework.
    /// This method NEVER sleeps — the lock-held callers (`start`/`stop`/`restart`
    /// orchestration in main.rs) must drop the BotManager lock before waiting for
    /// the killed processes to die, so a multi-second wait can't freeze the
    /// concurrent status/log polls (which acquire the same lock).
    fn kill_orphan_bot_processes(&mut self) -> bool {
        Self::refresh_processes_with_cmd(&mut self.sys);

        // Ignore script file basenames (not substring-match on joined cmdline —
        // a user path like C:\Users\test_user\BOT\bot.py would falsely trip "test_").
        let ignore_basenames = ["bot_manager.py", "dev_watcher.py", "self_healer.py"];
        let base_path_str = self.base_path.to_string_lossy().to_lowercase().to_string();
        let mut pids_to_kill: Vec<u32> = Vec::new();

        for (pid, process) in self.sys.processes() {
            let name = process.name().to_string_lossy().to_lowercase();
            if !name.contains("python") {
                continue;
            }

            let cmd: Vec<String> = process
                .cmd()
                .iter()
                .map(|s| s.to_string_lossy().to_lowercase().to_string())
                .collect();
            let cmdline = cmd.join(" ");

            // Collect basenames of every arg so we can match script files precisely.
            let basenames: Vec<String> = cmd
                .iter()
                .map(|arg| {
                    std::path::Path::new(arg.as_str())
                        .file_name()
                        .map(|f| f.to_string_lossy().to_lowercase().to_string())
                        .unwrap_or_default()
                })
                .collect();

            let has_bot_py = basenames.iter().any(|b| b == "bot.py");
            // Skip pytest-style processes, but ONLY when the ENTRY SCRIPT itself
            // is a test_* file — not when any later argv token happens to be a
            // test_ path (e.g. a legit bot launched with `--config
            // test_local.yaml` would otherwise be wrongly skipped + orphaned).
            // The entry script is the first non-interpreter argv element: skip
            // the interpreter (cmd[0]) and any leading `-` option flags.
            let is_test = cmd
                .iter()
                .skip(1)
                .find(|arg| !arg.starts_with('-'))
                .map(|arg| {
                    std::path::Path::new(arg.as_str())
                        .file_name()
                        .map(|f| f.to_string_lossy().to_lowercase().starts_with("test_"))
                        .unwrap_or(false)
                })
                .unwrap_or(false);
            let is_ignored_script = basenames
                .iter()
                .any(|b| ignore_basenames.contains(&b.as_str()));
            // Only kill processes that belong to our own base_path (argv
            // references base_path, OR the process cwd IS base_path for the
            // dev-watcher's relative-"bot.py" spawn) — never reach across to
            // other Discord-bot installs on the same host.
            let belongs_to_us = Self::process_belongs_to_us(
                process,
                &cmdline,
                &base_path_str,
                self.base_path_canonical.as_deref(),
            );

            if has_bot_py && !is_test && !is_ignored_script && belongs_to_us {
                pids_to_kill.push(pid.as_u32());
            }
        }

        for pid in &pids_to_kill {
            let _ = Command::new(taskkill_path())
                .args(["/PID", &pid.to_string(), "/F", "/T"])
                .creation_flags(CREATE_NO_WINDOW)
                .output();
        }

        // The previous design slept 2s here to let the killed trees terminate,
        // but that ran while the BotManager lock was held — freezing every
        // concurrent status/log poll. The wait now lives in the lock-free
        // orchestration in main.rs (which drops the guard, sleeps, re-locks).
        !pids_to_kill.is_empty()
    }

    /// Reap an ORPHANED `dev_watcher.py` that belongs to THIS project tree.
    ///
    /// `kill_orphan_bot_processes` deliberately ignores `dev_watcher.py` (it's a
    /// supervisor, not the bot), and `stop_dev_watcher` can only find a watcher
    /// it recorded a PID file for. That leaves a gap: if the dashboard dies
    /// between `start_dev`'s `Command::spawn()` and the `fs::write` of the PID
    /// file, the watcher survives with NO PID file and nothing reaps it on the
    /// next launch — it keeps hot-reloading bot.py forever. This scan closes that
    /// gap conservatively: it kills ONLY python processes whose ENTRY SCRIPT is
    /// `dev_watcher.py` AND that `process_belongs_to_us` (cmdline references
    /// base_path, or cwd IS base_path — the dev-watcher spawns with cwd=base_path)
    /// — never another install's watcher. The currently-tracked watcher (the PID
    /// in our PID file, if any) is excluded so a live dev session isn't killed.
    ///
    /// Like `kill_orphan_bot_processes`, this NEVER sleeps (lock-held callers must
    /// not block the status/log pollers). Returns `true` if anything was killed.
    fn reap_orphan_dev_watcher(&mut self) -> bool {
        Self::refresh_processes_with_cmd(&mut self.sys);

        let base_path_str = self.base_path.to_string_lossy().to_lowercase().to_string();
        // The watcher we're legitimately tracking — never reap it as an "orphan".
        let tracked_pid = self.get_dev_watcher_pid();
        let mut pids_to_kill: Vec<u32> = Vec::new();

        for (pid, process) in self.sys.processes() {
            let pid_u32 = pid.as_u32();
            if Some(pid_u32) == tracked_pid {
                continue;
            }
            let name = process.name().to_string_lossy().to_lowercase();
            if !name.contains("python") {
                continue;
            }

            let cmd: Vec<String> = process
                .cmd()
                .iter()
                .map(|s| s.to_string_lossy().to_lowercase().to_string())
                .collect();
            let cmdline = cmd.join(" ");

            // Match on the ENTRY SCRIPT basename only (first non-interpreter,
            // non-flag argv token) so an unrelated process that merely passes a
            // "dev_watcher.py" string as a later argument isn't swept.
            if !Self::entry_script_is(&cmd, "dev_watcher.py") {
                continue;
            }

            // Only OUR project's watcher — never reach across installs.
            if Self::process_belongs_to_us(
                process,
                &cmdline,
                &base_path_str,
                self.base_path_canonical.as_deref(),
            ) {
                pids_to_kill.push(pid_u32);
            }
        }

        for pid in &pids_to_kill {
            let _ = Command::new(taskkill_path())
                .args(["/PID", &pid.to_string(), "/F", "/T"])
                .creation_flags(CREATE_NO_WINDOW)
                .output();
        }
        // A reaped orphan's PID file (if it somehow had one that no longer maps to
        // it) is left to stop_dev_watcher/start_dev to overwrite — we only touch
        // processes here.
        !pids_to_kill.is_empty()
    }

    pub fn log_file(&self) -> PathBuf {
        self.base_path.join("logs").join("bot.log")
    }

    pub fn logs_dir(&self) -> PathBuf {
        self.base_path.join("logs")
    }

    pub fn data_dir(&self) -> PathBuf {
        self.base_path.join("data")
    }

    pub fn base_path(&self) -> &PathBuf {
        &self.base_path
    }

    /// Return up to the last `count` lines of the bot log.
    ///
    /// NOTE (return contract): the tail read is capped at 1 MiB. The line
    /// budget is estimated at ~1 KiB/line, so on a log whose average line
    /// exceeds ~100 bytes a large request can return FEWER than `count` lines
    /// even when more exist — only the trailing ~1 MiB is scanned. This is an
    /// intentional bound to avoid loading a multi-MB log into memory.
    pub fn read_logs(&self, count: usize) -> Vec<String> {
        let log_path = self.log_file();

        if !log_path.exists() {
            return vec![];
        }

        let file = match fs::File::open(&log_path) {
            Ok(f) => f,
            Err(_) => return vec![],
        };

        // Read from end of file to avoid loading entire file into memory
        let metadata = match file.metadata() {
            Ok(m) => m,
            Err(_) => return vec![],
        };

        let file_size = metadata.len();
        if file_size == 0 {
            return vec![];
        }

        // Read at most 1MB from end of file (enough for ~count lines)
        let max_read: u64 = std::cmp::min(file_size, (count as u64).saturating_mul(1024)); // ~1KB per line estimate
        let max_read = std::cmp::min(max_read, 1024 * 1024); // Cap at 1MB
        let start_pos = file_size.saturating_sub(max_read);

        let mut file = file;
        if file.seek(SeekFrom::Start(start_pos)).is_err() {
            return vec![];
        }

        // Read as raw bytes and convert with lossy UTF-8 to avoid
        // corruption when seek lands on a multi-byte character boundary
        let mut raw_bytes = Vec::new();
        if file.read_to_end(&mut raw_bytes).is_err() {
            return vec![];
        }
        let buffer = String::from_utf8_lossy(&raw_bytes);

        let lines: Vec<String> = buffer.lines().map(|l| l.to_string()).collect();

        // If we started mid-file, skip potentially partial first line
        let skip = if start_pos > 0 { 1 } else { 0 };
        lines
            .into_iter()
            .skip(skip)
            .rev()
            .take(count)
            .collect::<Vec<_>>()
            .into_iter()
            .rev()
            .collect()
    }

    pub fn clear_logs(&self) -> Result<String, String> {
        let log_path = self.log_file();

        if !log_path.exists() {
            return Ok("No logs to clear".to_string());
        }

        // Truncate the file instead of deleting (keeps file but empties content)
        fs::write(&log_path, "").map_err(|e| format!("Failed to clear logs: {}", e))?;

        Ok("Logs cleared".to_string())
    }

    pub fn get_pid(&self) -> Option<u32> {
        fs::read_to_string(self.pid_file())
            .ok()?
            .trim()
            .parse()
            .ok()
    }

    /// Whether `process` is OUR running bot: it must have a `bot.py` argv token
    /// AND `process_belongs_to_us` (cmdline references base_path, or cwd IS
    /// base_path). Shared by `is_running` and `get_status` so the two can't drift.
    ///
    /// Fail CLOSED: there is intentionally NO `base_path_str.is_empty()` escape
    /// hatch. `process_belongs_to_us` already returns false on an empty
    /// base_path, so a degenerate/unset base_path (e.g. `BOT_BASE_PATH=""`)
    /// correctly reports "not ours" instead of collapsing to "any python with a
    /// bot.py arg" — which would reopen the cross-install / Windows PID-reuse
    /// false-positive these checks exist to close.
    fn is_our_bot_process(
        process: &sysinfo::Process,
        base_path_str: &str,
        base_path_canonical: Option<&str>,
    ) -> bool {
        let cmd: Vec<String> = process
            .cmd()
            .iter()
            .map(|s| s.to_string_lossy().to_lowercase().to_string())
            .collect();
        let has_bot_py = cmd.iter().any(|arg| {
            std::path::Path::new(arg.as_str())
                .file_name()
                .map(|f| f.to_string_lossy().eq_ignore_ascii_case("bot.py"))
                .unwrap_or(false)
        });
        if !has_bot_py {
            return false;
        }
        let cmdline = cmd.join(" ");
        Self::process_belongs_to_us(process, &cmdline, base_path_str, base_path_canonical)
    }

    pub fn is_running(&mut self) -> bool {
        if let Some(pid) = self.get_pid() {
            Self::refresh_processes_with_cmd(&mut self.sys);
            // PID alone is not enough — Windows recycles PIDs aggressively.
            // Verify the cmdline references both bot.py AND our base_path so we
            // don't report "running" for an unrelated PID-reuse.
            let base_path_str = self.base_path.to_string_lossy().to_lowercase().to_string();
            if let Some(process) = self.sys.process(sysinfo::Pid::from_u32(pid)) {
                return Self::is_our_bot_process(
                    process,
                    &base_path_str,
                    self.base_path_canonical.as_deref(),
                );
            }
            false
        } else {
            false
        }
    }

    /// Whether the OS process with `pid` no longer exists (a fresh refresh
    /// shows no such PID). Used by the lock-free stop/restart orchestration in
    /// main.rs to poll for termination WITHOUT holding the BotManager lock
    /// across the inter-poll sleep. A single quick lock per tick keeps the
    /// concurrent status/log polls responsive.
    pub fn process_is_gone(&mut self, pid: u32) -> bool {
        Self::refresh_processes_with_cmd(&mut self.sys);
        self.sys.process(sysinfo::Pid::from_u32(pid)).is_none()
    }

    /// Format uptime from PID file modification time.
    fn format_uptime_from_pid_file(&self) -> String {
        let pid_file = self.pid_file();
        if !pid_file.exists() {
            return "-".to_string();
        }

        if let Ok(metadata) = fs::metadata(&pid_file) {
            if let Ok(modified) = metadata.modified() {
                let start: DateTime<Local> = modified.into();
                let now = Local::now();
                let duration = now.signed_duration_since(start);

                // Clamp to 0 to prevent negative uptime from clock skew
                let total_secs = duration.num_seconds().max(0);
                let hours = total_secs / 3600;
                let mins = (total_secs % 3600) / 60;
                let secs = total_secs % 60;

                if hours > 0 {
                    return format!("{}h {}m {}s", hours, mins, secs);
                } else if mins > 0 {
                    return format!("{}m {}s", mins, secs);
                } else {
                    return format!("{}s", secs);
                }
            }
        }
        "-".to_string()
    }

    pub fn get_status(&mut self) -> BotStatus {
        // Single process refresh for all status fields (instead of 3-5 separate refreshes)
        Self::refresh_processes_with_cmd(&mut self.sys);

        let pid = self.get_pid();
        // Mirror is_running()'s cmdline verification — pure PID existence is
        // unreliable on Windows due to aggressive PID reuse.
        let base_path_str = self.base_path.to_string_lossy().to_lowercase().to_string();
        // Bind before the borrow of self.sys below so the closure doesn't take a
        // second borrow of self.
        let base_path_canonical = self.base_path_canonical.clone();
        let is_running = pid
            .and_then(|p| self.sys.process(sysinfo::Pid::from_u32(p)))
            // Same fail-closed bot.py + ownership check as is_running() (shared
            // helper) — no is_empty() escape hatch, so an empty/degenerate
            // base_path reports "not running" rather than matching unrelated
            // python processes.
            .map(|process| {
                Self::is_our_bot_process(process, &base_path_str, base_path_canonical.as_deref())
            })
            .unwrap_or(false);

        let uptime = if is_running {
            self.get_uptime_no_refresh()
        } else {
            "-".to_string()
        };
        let memory_mb = if is_running {
            pid.and_then(|p| self.sys.process(sysinfo::Pid::from_u32(p)))
                .map(|proc| proc.memory() as f64 / 1024.0 / 1024.0)
                .unwrap_or(0.0)
        } else {
            0.0
        };

        let mode = {
            // Verify the dev-watcher PID still maps to a python process that
            // belongs to OUR project tree, not just that *some* process holds
            // that PID. Windows recycles PIDs aggressively (the module invariant
            // every other status/kill path honors), so a bare is_some() / name-
            // only check would falsely report mode="Dev" if the watcher died and
            // its PID was reused. Scope with process_belongs_to_us, consistent
            // with the main-bot is_running check above.
            let dev_running = self
                .get_dev_watcher_pid()
                .and_then(|p| self.sys.process(sysinfo::Pid::from_u32(p)))
                .map(|proc| {
                    let name = proc.name().to_string_lossy().to_lowercase();
                    if !name.contains("python") {
                        return false;
                    }
                    let cmd: Vec<String> = proc
                        .cmd()
                        .iter()
                        .map(|s| s.to_string_lossy().to_lowercase().to_string())
                        .collect();
                    // Same entry-script gate as stop_dev_watcher so the mode badge
                    // stays honest after PID reuse (display-only; kills nothing).
                    if !Self::entry_script_is(&cmd, "dev_watcher.py") {
                        return false;
                    }
                    let cmdline = cmd.join(" ");
                    // Fail CLOSED, consistent with the main-bot check above and
                    // process_belongs_to_us' own empty-base_path guard — no
                    // is_empty() escape hatch that would let any python+base_path
                    // process masquerade as our dev-watcher under PID reuse.
                    Self::process_belongs_to_us(
                        proc,
                        &cmdline,
                        &base_path_str,
                        base_path_canonical.as_deref(),
                    )
                })
                .unwrap_or(false);
            if dev_running {
                "Dev".to_string()
            } else if is_running {
                "Normal".to_string()
            } else {
                "-".to_string()
            }
        };

        BotStatus {
            is_running,
            pid,
            uptime,
            memory_mb,
            mode,
        }
    }

    /// Get uptime without refreshing processes (used by get_status which already refreshed)
    fn get_uptime_no_refresh(&self) -> String {
        self.format_uptime_from_pid_file()
    }

    /// Report the progress of a dashboard-initiated start (see [`StartProgress`]).
    ///
    /// Resolution order:
    ///   1. If `is_running()` (PID file written + cmdline verified) → `Running`.
    ///      This is authoritative and wins regardless of child bookkeeping.
    ///   2. Otherwise inspect the `Child` handle stored by `start()`:
    ///        * alive (`try_wait() == Ok(None)`) → `Starting` (still booting).
    ///        * exited (`Ok(Some(status))`)      → `Exited { code }` (failed).
    ///        * un-queryable (`Err`)             → `Exited { code: None }`,
    ///          so the UI fails closed rather than spinning forever.
    ///   3. No tracked child → `Unknown`.
    ///
    /// `try_wait()` is non-blocking and reaps the zombie on exit; we leave the
    /// (now-reaped) handle in place so repeated polls stay idempotent and the
    /// existing `start()`/`stop()` reap paths can still clear it.
    pub fn start_progress(&mut self) -> StartProgress {
        if self.is_running() {
            return StartProgress::Running;
        }
        match self.child.as_mut() {
            Some(child) => match child.try_wait() {
                Ok(None) => StartProgress::Starting,
                Ok(Some(status)) => StartProgress::Exited {
                    code: status.code(),
                },
                Err(_) => StartProgress::Exited { code: None },
            },
            None => StartProgress::Unknown,
        }
    }

    pub fn start(&mut self) -> Result<String, String> {
        // Refuse to spawn without a pinned, validated interpreter. An empty
        // python_cmd means new() found no trusted python (PYTHON_CMD/.venv/PATH
        // all failed); spawning a bare "python" here would be the PATH-hijack
        // vector this file pins taskkill.exe/explorer.exe against.
        if self.python_cmd.is_empty() {
            return Err(
                "No trusted Python interpreter found; set PYTHON_CMD to an absolute interpreter \
                 path"
                    .to_string(),
            );
        }
        if self.is_running() {
            return Err("Bot is already running".to_string());
        }

        // Kill any orphan bot.py processes that survived a previous stop
        self.kill_orphan_bot_processes();
        // Tear down any dev watcher before a normal start. reap_orphan_dev_watcher
        // only sweeps UNTRACKED watchers (PID-file orphans); a still-live watcher
        // we spawned ourselves (start_dev whose bot hasn't written bot.pid yet, so
        // is_running() above returned false) is tracked in dev_watcher_child and
        // would keep hot-reloading a SECOND bot underneath this one — two bots on
        // one token. stop_dev_watcher() kills the tracked watcher tree + waits;
        // reap_orphan_dev_watcher() then covers the untracked-orphan case.
        self.stop_dev_watcher();
        self.reap_orphan_dev_watcher();

        // Remove old PID file first
        let _ = fs::remove_file(self.pid_file());

        let bot_script = self.base_path.join("bot.py");

        let child = Command::new(&self.python_cmd)
            .arg(&bot_script)
            .current_dir(&self.base_path)
            .creation_flags(CREATE_NO_WINDOW)
            .spawn()
            .map_err(|e| format!("Failed to start bot: {}", e))?;

        // Keep the Child handle so we can wait() on it during stop(). Dropping
        // it without waiting leaves a process descriptor on POSIX (zombie) and
        // leaks the Win32 process handle until our own dashboard exits.
        // Reap any previously-tracked Child that already exited, then kill any
        // still-live tracked child's tree first (mirroring stop()'s teardown) so
        // overwriting self.child below can't orphan a still-booting bot.
        self.kill_tracked_bot_child();
        self.child = Some(child);

        // Return as soon as spawn() succeeds. The previous design held the
        // BotManager lock for up to 10s waiting for bot.py to write bot.pid,
        // which made the UI freeze for ~1s on every Start click. The frontend
        // now tight-polls `get_status` after the start invocation returns and
        // surfaces the "Running" / failure transition itself — that path
        // detects success within 100–300ms typical and reports failures via
        // the same status poll without us holding the lock open.
        Ok("Bot starting...".to_string())
    }

    pub fn start_dev(&mut self) -> Result<String, String> {
        // Same pinned-interpreter requirement as start() — never spawn the
        // dev watcher via an unpinned bare "python".
        if self.python_cmd.is_empty() {
            return Err(
                "No trusted Python interpreter found; set PYTHON_CMD to an absolute interpreter \
                 path"
                    .to_string(),
            );
        }
        if self.is_running() {
            return Err("Bot is already running".to_string());
        }

        // Tear down a still-booting normal-mode bot. is_running() above only
        // returns true once bot.pid exists, so a normal Start still in its
        // cold-start window (self.child alive, no bot.pid yet) slips past that
        // guard; without this kill, dev mode spawns a SECOND bot underneath the
        // booting one — two bot.py on the same Discord token. Mirrors start()'s
        // own teardown of a booting child.
        self.kill_tracked_bot_child();
        self.kill_orphan_bot_processes();

        // Stop any existing dev watcher first (the one we have a PID file for),
        // then sweep any ORPHANED watcher with no PID file — e.g. a previous
        // start_dev whose PID-file write never completed because the dashboard
        // crashed in between. Without this sweep a second dev session would
        // spawn a duplicate watcher on top of the orphan.
        self.stop_dev_watcher();
        self.reap_orphan_dev_watcher();

        let dev_watcher = self.base_path.join("scripts").join("dev_watcher.py");

        // Dev mode: run dev_watcher.py hidden with CREATE_NO_WINDOW
        let child = Command::new(&self.python_cmd)
            .arg(&dev_watcher)
            .current_dir(&self.base_path)
            .creation_flags(CREATE_NO_WINDOW)
            .spawn()
            .map_err(|e| format!("Failed to start dev watcher: {}", e))?;

        // Save dev_watcher PID for later cleanup. If the write fails we can
        // never reap this watcher after a dashboard restart (no PID file and
        // no surviving in-memory handle), so it would leak as an orphan that
        // keeps hot-reloading the bot. Rather than proceed with an untrackable
        // watcher, kill the just-spawned tree and surface the failure.
        let pid_path = self.dev_watcher_pid_file();
        let pid = child.id();
        // Hold onto the Child handle so stop_dev_watcher() can wait() on it
        // and release the OS handle cleanly. Previously we dropped here and
        // the handle leaked until the dashboard itself exited.
        self.reap_finished_children();
        self.dev_watcher_child = Some(child);
        if let Err(e) = fs::write(&pid_path, pid.to_string()) {
            eprintln!(
                "⚠️ Failed to write dev_watcher PID {} to {}: {} — killing untrackable watcher",
                pid,
                pid_path.display(),
                e,
            );
            // Tear down the watcher tree we just spawned so it can't linger as
            // an orphan, then report the failure to the caller.
            let _ = Command::new(taskkill_path())
                .args(["/PID", &pid.to_string(), "/F", "/T"])
                .creation_flags(CREATE_NO_WINDOW)
                .output();
            if let Some(mut c) = self.dev_watcher_child.take() {
                let _ = c.kill();
                let _ = c.wait();
            }
            return Err(format!(
                "Failed to track dev watcher (PID file write failed): {}",
                e
            ));
        }

        // Return as soon as the watcher is spawned + its PID recorded. The old
        // design slept 3s (then another 2s) here while holding the BotManager
        // lock, just to choose a nicer return message — freezing every
        // concurrent status/log poll for up to 5s. The dev-watcher boots the bot
        // asynchronously and the periodic `get_status` poll flips the badge to
        // "Dev" once it's up, so we don't need to block here at all (mirrors
        // `start()`'s spawn-and-return pattern).
        Ok("Dev Watcher launched - bot starting...".to_string())
    }

    /// First, lock-held phase of a stop. Performs all the quick work — PID
    /// validation, dev-watcher teardown, and firing the `taskkill` — then hands
    /// control back so the caller can wait for the process to die WITHOUT
    /// holding the BotManager lock. Returns a [`StopOutcome`] telling the caller
    /// whether there is anything left to poll/finish.
    ///
    /// Splitting `stop()` this way mirrors the `start()`/`get_start_progress`
    /// pattern: the old monolithic `stop()` slept up to 3s (exit poll) + 2s
    /// (orphan kill) while the lock was held, freezing every concurrent
    /// status/log poll for ~5s. The inter-poll sleeps now live in the lock-free
    /// orchestration in main.rs.
    pub fn stop_begin(&mut self) -> Result<StopOutcome, String> {
        let pid = match self.get_pid() {
            Some(pid) => pid,
            None => {
                // No PID file. Normally that means the bot isn't running — but
                // if bot.py crashed or hung during startup BEFORE it wrote
                // bot.pid, we may still hold the Child handle from start().
                // Without this branch, stop() returned "not running" and could
                // never kill that process tree, leaving an orphan + a UI stuck
                // on "starting". Kill the tracked child's tree here.
                if let Some(mut c) = self.child.take() {
                    let child_pid = c.id();
                    let _ = Command::new(taskkill_path())
                        .args(["/PID", &child_pid.to_string(), "/F", "/T"])
                        .creation_flags(CREATE_NO_WINDOW)
                        .output();
                    let _ = c.kill();
                    let _ = c.wait();
                    self.stop_dev_watcher();
                    // Orphan sweep is best-effort here; the killed child tree is
                    // already torn down via `c.kill()`/taskkill above, so we
                    // don't make the caller wait on a poll for this branch.
                    self.kill_orphan_bot_processes();
                    return Ok(StopOutcome::Done(
                        "Bot stopped (no PID file; killed tracked startup process)".to_string(),
                    ));
                }
                // Dev mode tracks the watcher in dev_watcher_child, NOT
                // self.child (start_dev spawns dev_watcher.py, which spawns
                // bot.py as a grandchild). bot.pid is legitimately absent while
                // dev mode is live — during the multi-second cold start and on
                // every hot-reload/crash respawn (dev_watcher.py unlinks bot.pid
                // before relaunching bot.py). Reaching here with a live watcher
                // means Stop was pressed in that gap: without tearing the watcher
                // down it survives and respawns bot.py, so Stop silently fails.
                // Mirror the stale-PID branches below and stop it here.
                if self.dev_watcher_child.is_some() || self.get_dev_watcher_pid().is_some() {
                    self.stop_dev_watcher();
                    // Sweep an orphaned watcher and any bot.py it respawned whose
                    // pid we never captured, so nothing is left to relaunch.
                    self.reap_orphan_dev_watcher();
                    self.kill_orphan_bot_processes();
                    return Ok(StopOutcome::Done(
                        "Dev mode stopped (watcher terminated)".to_string(),
                    ));
                }
                return Err("Bot is not running".to_string());
            }
        };

        if !self.is_running() {
            // A bot.pid existed (we got past get_pid) but is_running() says the
            // process is gone/reused — i.e. the bot crashed or was killed
            // externally. is_running() performs the same PID-reuse validation as
            // the stale-PID branches below, so from this state those branches
            // are unreachable; do their cleanup HERE instead of erroring out and
            // leaving the stale bot.pid (and a zombie Child handle) behind until
            // the next start().
            if let Some(mut c) = self.child.take() {
                let _ = c.kill();
                let _ = c.wait();
            }
            // Stop a live dev_watcher too: if dev mode was active and the bot is
            // just momentarily absent (hot-reload/crash gap), returning without
            // this leaves the watcher running — and it respawns bot.py, so "Stop"
            // silently fails to stop dev mode. Mirrors the main kill path.
            self.stop_dev_watcher();
            let _ = fs::remove_file(self.pid_file());
            return Err("Bot is not running".to_string());
        }

        // Verify PID still belongs to a Python/bot process before killing
        // to prevent killing an unrelated process after PID reuse
        Self::refresh_processes_with_cmd(&mut self.sys);
        if let Some(process) = self.sys.process(sysinfo::Pid::from_u32(pid)) {
            let name = process.name().to_string_lossy().to_lowercase();
            if !name.contains("python") {
                // PID was reused by a non-Python process — stale PID file.
                // Reap any still-tracked startup Child first so a child that
                // spawned but never wrote bot.pid isn't orphaned on this early
                // return (mirrors the no-PID-file branch above).
                if let Some(mut c) = self.child.take() {
                    let _ = c.kill();
                    let _ = c.wait();
                }
                // Also stop a live dev_watcher (see the !is_running branch above):
                // leaving it running lets it respawn the bot after "Stop".
                self.stop_dev_watcher();
                let _ = fs::remove_file(self.pid_file());
                return Err("Bot PID was stale (process is no longer Python)".to_string());
            }
        } else {
            // PID gone (reused/exited). Reap any still-tracked startup Child
            // first so it isn't orphaned on this early return.
            if let Some(mut c) = self.child.take() {
                let _ = c.kill();
                let _ = c.wait();
            }
            // Also stop a live dev_watcher so it doesn't respawn the bot post-Stop.
            self.stop_dev_watcher();
            let _ = fs::remove_file(self.pid_file());
            return Err("Bot process no longer exists".to_string());
        }

        // IMPORTANT: Stop dev_watcher FIRST so it doesn't restart the bot
        self.stop_dev_watcher();

        // Force kill the bot process tree immediately
        let _ = Command::new(taskkill_path())
            .args(["/PID", &pid.to_string(), "/F", "/T"])
            .creation_flags(CREATE_NO_WINDOW)
            .output();

        // Hand back to the caller to poll `process_is_gone(pid)` (lock dropped
        // between ticks) and then call `stop_finish()`.
        Ok(StopOutcome::Polling(pid))
    }

    /// Final, lock-held phase of a stop, run after the caller has waited for the
    /// bot PID to disappear (or the wait timed out). Sweeps remaining orphans,
    /// reaps the tracked Child, and deletes the PID file. Kept separate from
    /// `stop_begin` so the inter-poll sleeps happen with the lock released.
    pub fn stop_finish(&mut self) -> Result<String, String> {
        // Kill any remaining orphan bot.py processes (no sleep — see method doc)
        self.kill_orphan_bot_processes();

        // Reap our own tracked Child (if any) so its Win32/POSIX process
        // descriptor is released and we don't leak it across restarts.
        if let Some(mut c) = self.child.take() {
            let _ = c.kill();
            let _ = c.wait();
        }

        // Delete PID file
        let _ = fs::remove_file(self.pid_file());

        Ok("Bot stopped".to_string())
    }

    /// Begin a restart. If the bot is running, run `stop_begin()` and tell the
    /// caller how to proceed (see [`RestartBegin`]) so the lock-free
    /// orchestration in main.rs can drop the guard between termination polls,
    /// then re-lock to finish + `start()`.
    ///
    /// A benign `stop_begin()` failure is swallowed (not propagated): if the bot
    /// process exits on its own between the `is_running()` check and the stop, we
    /// still want to fall through to a fresh start rather than abort the restart.
    pub fn restart_begin(&mut self) -> RestartBegin {
        if !self.is_running() {
            return RestartBegin::StartNow;
        }
        let old_pid = self.get_pid();
        match self.stop_begin() {
            // Process already torn down in the begin phase (no-PID-file /
            // stale-PID branches) — finish the teardown now; nothing to poll.
            Ok(StopOutcome::Done(_)) => {
                let _ = self.stop_finish();
                RestartBegin::StartNow
            }
            // Normal path: a kill was fired. Caller must poll the PID gone (lock
            // released between ticks), call `stop_finish()`, then `start()`.
            Ok(StopOutcome::Polling(pid)) => RestartBegin::PollThenFinish(pid),
            // Benign failure (e.g. the bot exited on its own). The stale-PID
            // error branches in `stop_begin` already reaped the child + removed
            // the PID file, so there's nothing to finish; just wait out the old
            // PID (if any) then start.
            Err(_) => match old_pid {
                Some(pid) => RestartBegin::PollThenStart(pid),
                None => RestartBegin::StartNow,
            },
        }
    }
}

/// Outcome of [`BotManager::stop_begin`]: either the stop is already complete
/// (an early-return branch handled everything) or there is a bot PID the caller
/// must wait on — with the lock released between polls — before invoking
/// [`BotManager::stop_finish`].
pub enum StopOutcome {
    /// The stop fully completed in the begin phase; the carried message is the
    /// final result. Nothing left to poll or finish.
    Done(String),
    /// The bot process was sent a kill; poll `process_is_gone(pid)` (lock-free)
    /// then call `stop_finish()`.
    Polling(u32),
}

/// How the lock-free restart orchestration in main.rs should proceed after the
/// quick `restart_begin()` phase.
pub enum RestartBegin {
    /// Nothing to wait on — call `start()` straight away.
    StartNow,
    /// A kill was fired; poll `process_is_gone(pid)` (lock-free), then call
    /// `stop_finish()` and finally `start()`.
    PollThenFinish(u32),
    /// `stop_begin()` failed benignly after already cleaning up; just poll
    /// `process_is_gone(pid)` (lock-free) then call `start()` (no `stop_finish`).
    PollThenStart(u32),
}

// Legacy function removed - use BotManager::read_logs() instead

// ============================================================================
// Unit tests for the start-progress state machine. This module is Windows-only
// (enforced by the `compile_error!` at the top of the file), so the tests use
// `cmd.exe` / `ping.exe`, which always exist on a supported Windows host. Run
// with `cargo test`.
// ============================================================================
#[cfg(test)]
mod tests {
    use super::*;
    use std::process::Command;

    /// A `BotManager` rooted at an empty temp dir — no `bot.pid` exists, so
    /// `is_running()` is always false and `start_progress()` resolves purely on
    /// the tracked `Child`. The `TempDir` is returned so it outlives the manager.
    fn manager_in_temp() -> (tempfile::TempDir, BotManager) {
        let dir = tempfile::tempdir().expect("create tempdir");
        let bm = BotManager::new(dir.path().to_path_buf());
        (dir, bm)
    }

    /// Refresh `bm.sys` until `pid` appears in the snapshot (or a short budget
    /// elapses). A just-`spawn()`ed child can occasionally lag the first process
    /// refresh; retry a few times so the cmdline-inspection tests aren't flaky.
    /// Leaves a fresh snapshot loaded for the caller to read.
    fn wait_until_in_snapshot(bm: &mut BotManager, pid: u32) {
        for _ in 0..50 {
            BotManager::refresh_processes_with_cmd(&mut bm.sys);
            if bm.sys.process(sysinfo::Pid::from_u32(pid)).is_some() {
                return;
            }
            std::thread::sleep(std::time::Duration::from_millis(20));
        }
    }

    #[test]
    fn start_progress_is_unknown_with_no_child_and_no_pid() {
        let (_dir, mut bm) = manager_in_temp();
        // Nothing spawned, no PID file → we can't say anything about a start.
        assert_eq!(bm.start_progress(), StartProgress::Unknown);
    }

    #[test]
    fn start_progress_reports_exit_code_when_spawned_child_died() {
        let (_dir, mut bm) = manager_in_temp();
        // Stand in for a bot.py that crashed during startup: a process that
        // exits deterministically with a known code. `wait()` first so there's
        // no race — the child is guaranteed gone before we poll.
        let mut child = Command::new("cmd")
            .args(["/C", "exit", "7"])
            .creation_flags(CREATE_NO_WINDOW)
            .spawn()
            .expect("spawn cmd /C exit 7");
        let _ = child.wait();
        bm.child = Some(child);

        match bm.start_progress() {
            StartProgress::Exited { code } => assert_eq!(code, Some(7)),
            other => panic!("expected Exited {{ code: Some(7) }}, got {other:?}"),
        }
    }

    #[test]
    fn start_progress_is_starting_while_spawned_child_is_alive() {
        let (_dir, mut bm) = manager_in_temp();
        // Stand in for a bot.py still grinding through cold-start imports: a
        // long-lived process that hasn't written a PID file.
        let child = Command::new("ping")
            .args(["-n", "30", "127.0.0.1"])
            .creation_flags(CREATE_NO_WINDOW)
            .spawn()
            .expect("spawn ping");
        bm.child = Some(child);

        assert_eq!(bm.start_progress(), StartProgress::Starting);

        // Don't leave the stand-in process running past the test.
        if let Some(mut c) = bm.child.take() {
            let _ = c.kill();
            let _ = c.wait();
        }
    }

    // ------- restart_begin (#28) -------

    #[test]
    fn restart_begin_is_start_now_when_no_pid_file() {
        // An empty temp dir has no `bot.pid`, so `is_running()` is false and a
        // restart has nothing to stop — it should jump straight to starting.
        // Matched (not `==`) so `RestartBegin` need not derive PartialEq.
        let (_dir, mut bm) = manager_in_temp();
        assert!(
            matches!(bm.restart_begin(), RestartBegin::StartNow),
            "restart with no running bot should be StartNow",
        );
    }

    // ------- process_is_gone (#28) -------

    #[test]
    fn process_is_gone_true_after_spawned_process_exits() {
        let (_dir, mut bm) = manager_in_temp();
        // Spawn a process that exits immediately, reap it, then confirm a fresh
        // refresh no longer lists its PID. (Windows can reuse PIDs, but the
        // window between wait() and the refresh below is far too small to flake
        // in practice — the existing start_progress tests rely on the same
        // spawn-and-reap timing.)
        let mut child = Command::new("cmd")
            .args(["/C", "exit", "0"])
            .creation_flags(CREATE_NO_WINDOW)
            .spawn()
            .expect("spawn cmd /C exit 0");
        let pid = child.id();
        let _ = child.wait();
        assert!(
            bm.process_is_gone(pid),
            "exited+reaped process should report gone",
        );
    }

    // ------- process_belongs_to_us short-circuit / fail-closed (#27) -------

    #[test]
    fn process_belongs_to_us_matches_a_process_rooted_at_base_path() {
        // Lock the cwd-based "belongs to us" recovery the doc comment describes:
        // a process whose working directory IS base_path is recognised as ours
        // even though base_path never appears in its argv (here a bare `ping`).
        // This mirrors the dev-watcher case (bot spawned with a RELATIVE
        // "bot.py" + cwd=PROJECT_ROOT). `process_belongs_to_us` does NOT filter
        // on a "python" name — that lives in the orphan loop — so `ping` with
        // the right cwd is a valid stand-in.
        //
        // NB on which branch fires: sysinfo reports a process cwd WITH a
        // trailing separator (`...\dir\`) whereas `base_path` has none, so the
        // plain `cwd == base_path` string compare misses by one char and it is
        // the canonicalize fallback (the block this task documents) that matches
        // — exactly the path that resolves 8.3 short-path / separator / symlink
        // differences. So we pass the real `base_path_canonical`; with `None` it
        // would (correctly) fail to match, which the empty-base_path test covers.
        let (dir, mut bm) = manager_in_temp();
        let base_path_str = dir.path().to_string_lossy().to_lowercase();
        // Sanity: a tempdir exists, so construction canonicalized it.
        assert!(
            bm.base_path_canonical.is_some(),
            "base_path_canonical should be Some for an existing tempdir",
        );

        let mut child = Command::new("ping")
            .args(["-n", "30", "127.0.0.1"])
            .current_dir(dir.path())
            .creation_flags(CREATE_NO_WINDOW)
            .spawn()
            .expect("spawn ping");
        let pid = child.id();

        BotManager::refresh_processes_with_cmd(&mut bm.sys);
        let belongs = bm
            .sys
            .process(sysinfo::Pid::from_u32(pid))
            .map(|p| {
                BotManager::process_belongs_to_us(
                    p,
                    "",
                    &base_path_str,
                    bm.base_path_canonical.as_deref(),
                )
            })
            .expect("spawned ping should be in the refreshed snapshot");

        // Clean up before asserting so a failure never leaks the stand-in.
        let _ = child.kill();
        let _ = child.wait();

        assert!(
            belongs,
            "a process whose cwd == base_path must be recognised as ours",
        );
    }

    // ------- interpreter pinning / no-bare-"python" fallback (dash-rust-missed-1) -------

    #[test]
    fn validate_python_path_rejects_nonexistent_and_non_python() {
        // A path that doesn't exist → None (can't be pinned).
        assert!(
            validate_python_path(std::path::Path::new(
                "C:\\definitely\\does\\not\\exist\\python.exe"
            ))
            .is_none(),
            "a nonexistent path must not validate as an interpreter",
        );
        // An existing file whose basename is NOT python* → None. cmd.exe always
        // exists on a supported Windows host (the module is Windows-only).
        let cmd_exe = std::path::Path::new("C:\\Windows\\System32\\cmd.exe");
        if cmd_exe.exists() {
            assert!(
                validate_python_path(cmd_exe).is_none(),
                "a non-python executable must not validate as an interpreter",
            );
        }
    }

    #[test]
    fn validate_python_path_accepts_a_real_python_basename() {
        // Create a real file named python.exe in a temp dir and confirm it
        // validates to an absolute (canonicalized) path. Content is irrelevant —
        // validation is existence + canonicalize + basename, matching the
        // PYTHON_CMD branch (which never executes the file just to validate it).
        let dir = tempfile::tempdir().expect("create tempdir");
        let fake = dir.path().join("python.exe");
        std::fs::write(&fake, b"not really an exe").expect("write fake python.exe");
        let resolved =
            validate_python_path(&fake).expect("a file named python.exe should validate");
        assert!(
            std::path::Path::new(&resolved).is_absolute(),
            "validated interpreter path must be absolute (pinned), got {resolved}",
        );
        assert!(
            resolved.to_lowercase().ends_with("python.exe"),
            "validated path should keep the python.exe basename, got {resolved}",
        );
    }

    #[test]
    fn start_refuses_to_spawn_without_a_pinned_interpreter() {
        // Simulate new() having found NO trusted interpreter (PYTHON_CMD unset,
        // no .venv, none on PATH): python_cmd is the empty sentinel. start()
        // must fail closed with an explicit error rather than spawning a bare,
        // PATH-resolved "python" — the hijack-to-RCE vector this file pins
        // taskkill.exe/explorer.exe against.
        let (_dir, mut bm) = manager_in_temp();
        bm.python_cmd = String::new();
        let err = bm.start().expect_err("start with no interpreter must Err");
        assert!(
            err.contains("No trusted Python interpreter"),
            "start() error should name the missing-interpreter cause, got: {err}",
        );
        // And nothing was spawned/tracked.
        assert!(
            bm.child.is_none(),
            "start() must not spawn or track a child when no interpreter is pinned",
        );
    }

    #[test]
    fn start_dev_refuses_to_spawn_without_a_pinned_interpreter() {
        let (_dir, mut bm) = manager_in_temp();
        bm.python_cmd = String::new();
        let err = bm
            .start_dev()
            .expect_err("start_dev with no interpreter must Err");
        assert!(
            err.contains("No trusted Python interpreter"),
            "start_dev() error should name the missing-interpreter cause, got: {err}",
        );
        assert!(
            bm.dev_watcher_child.is_none(),
            "start_dev() must not spawn/track a watcher when no interpreter is pinned",
        );
    }

    #[test]
    fn process_belongs_to_us_false_on_empty_base_path() {
        // Lock the fail-closed guard: an empty `base_path_str` returns false up
        // front (before any string or canonicalize compare), and `None` for
        // `base_path_canonical` means the canonicalize fallback is also skipped.
        // Together this proves an unknown/unset base_path never matches anything
        // — the contract the new doc comment leans on.
        let (_dir, mut bm) = manager_in_temp();

        let mut child = Command::new("ping")
            .args(["-n", "30", "127.0.0.1"])
            .creation_flags(CREATE_NO_WINDOW)
            .spawn()
            .expect("spawn ping");
        let pid = child.id();

        BotManager::refresh_processes_with_cmd(&mut bm.sys);
        let belongs = bm
            .sys
            .process(sysinfo::Pid::from_u32(pid))
            .map(|p| BotManager::process_belongs_to_us(p, "some unrelated cmdline", "", None))
            .expect("spawned ping should be in the refreshed snapshot");

        let _ = child.kill();
        let _ = child.wait();

        assert!(
            !belongs,
            "empty base_path must fail closed and never match a process",
        );
    }

    // ------- is_our_bot_process fail-closed on empty base_path (dash-rust-3) ----

    #[test]
    fn is_our_bot_process_fails_closed_on_empty_base_path_even_with_bot_py() {
        // Regression: is_running()/get_status() used to accept a process via
        // `has_bot_py && (base_path_str.is_empty() || belongs_to_us)`. That
        // is_empty() disjunct meant a degenerate empty base_path (e.g.
        // BOT_BASE_PATH="") collapsed the check to "any process with a bot.py
        // arg", reopening the cross-install / PID-reuse false-positive. The fix
        // removed the disjunct, so even a process that DOES carry a `bot.py` argv
        // token must NOT be claimed when base_path is empty.
        //
        // Build a real, long-lived process whose argv genuinely contains a
        // `bot.py` token (so the has_bot_py half is unambiguously true): cmd.exe
        // stays alive running `ping -n 30` and carries `bot.py` as a clean,
        // separate argv element after `&& rem` (a no-op comment) so ping doesn't
        // reject it as a bad parameter and the process keeps running.
        let (dir, mut bm) = manager_in_temp();
        let mut child = Command::new("cmd")
            .args(["/C", "ping", "-n", "30", "127.0.0.1", "&&", "rem", "bot.py"])
            .current_dir(dir.path())
            .creation_flags(CREATE_NO_WINDOW)
            .spawn()
            .expect("spawn cmd carrying a bot.py arg");
        let pid = child.id();
        wait_until_in_snapshot(&mut bm, pid);

        // Positive control: with the REAL base_path (the cwd of the child), the
        // process IS recognised as ours — proving has_bot_py is genuinely true
        // and the test isn't vacuously passing.
        let real_base = dir.path().to_string_lossy().to_lowercase();
        let claimed_with_real_base = bm
            .sys
            .process(sysinfo::Pid::from_u32(pid))
            .map(|p| {
                BotManager::is_our_bot_process(p, &real_base, bm.base_path_canonical.as_deref())
            })
            .expect("spawned cmd should be in the refreshed snapshot");

        // The fix under test: with an EMPTY base_path (and no canonical
        // fallback), the same bot.py-carrying process must NOT be claimed.
        let claimed_with_empty_base = bm
            .sys
            .process(sysinfo::Pid::from_u32(pid))
            .map(|p| BotManager::is_our_bot_process(p, "", None))
            .expect("spawned cmd should be in the refreshed snapshot");

        let _ = child.kill();
        let _ = child.wait();

        assert!(
            claimed_with_real_base,
            "positive control: a bot.py process rooted at base_path must be claimed",
        );
        assert!(
            !claimed_with_empty_base,
            "empty base_path must fail closed and NOT claim a bot.py process \
             (the is_empty() escape hatch must stay removed)",
        );
    }

    // ------- reap_orphan_dev_watcher scoping (dash-rust-7) ----------------------

    #[test]
    fn reap_orphan_dev_watcher_ignores_non_python_and_foreign_processes() {
        // Conservative-scoping guard: the orphan sweep must NEVER kill a process
        // that isn't a python running OUR dev_watcher.py. A non-python process
        // (cmd.exe carrying a "dev_watcher.py" arg, even rooted at base_path)
        // must survive — the name filter requires "python" — and the call must
        // report it killed nothing.
        let (dir, mut bm) = manager_in_temp();
        let mut decoy = Command::new("cmd")
            .args([
                "/C",
                "ping",
                "-n",
                "30",
                "127.0.0.1",
                "&&",
                "rem",
                "dev_watcher.py",
            ])
            .current_dir(dir.path())
            .creation_flags(CREATE_NO_WINDOW)
            .spawn()
            .expect("spawn cmd decoy carrying a dev_watcher.py arg");
        let decoy_pid = decoy.id();
        wait_until_in_snapshot(&mut bm, decoy_pid);

        let killed_any = bm.reap_orphan_dev_watcher();

        // The decoy (non-python) must still be alive.
        let still_alive = !bm.process_is_gone(decoy_pid);

        let _ = decoy.kill();
        let _ = decoy.wait();

        assert!(
            !killed_any,
            "reap_orphan_dev_watcher must not kill a non-python process",
        );
        assert!(
            still_alive,
            "a non-python decoy carrying a dev_watcher.py arg must survive the sweep",
        );
    }

    #[test]
    fn reap_orphan_dev_watcher_noop_when_nothing_to_reap() {
        // On a clean temp-rooted manager there is no python+dev_watcher.py
        // process under base_path, so the sweep must be a no-op (kills nothing).
        let (_dir, mut bm) = manager_in_temp();
        assert!(
            !bm.reap_orphan_dev_watcher(),
            "no orphan watcher present -> sweep must report nothing killed",
        );
    }

    #[test]
    fn entry_script_is_matches_only_the_entry_script() {
        let dev = |args: &[&str]| {
            let cmd: Vec<String> = args.iter().map(|s| s.to_lowercase()).collect();
            BotManager::entry_script_is(&cmd, "dev_watcher.py")
        };
        // Entry script (with path, either separator) matches.
        assert!(dev(&["c:\\py\\python.exe", "scripts\\dev_watcher.py"]));
        assert!(dev(&["python.exe", "-u", "scripts/dev_watcher.py"]));
        // A different entry script must NOT match (this is the bug the gate closes).
        assert!(!dev(&["python.exe", "bot.py"]));
        // dev_watcher.py only as a LATER arg must NOT match (entry is bot.py).
        assert!(!dev(&["python.exe", "bot.py", "--note", "dev_watcher.py"]));
        // `-m pytest` entry token resolves to "pytest", not our script.
        assert!(!dev(&["python.exe", "-m", "pytest"]));
        // Interpreter-only argv -> false.
        assert!(!dev(&["python.exe"]));
    }
}
