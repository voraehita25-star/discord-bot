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
        // Fallback to the canonical default — virtually every Windows
        // install has SystemRoot=C:\Windows, and if the env var is missing
        // or fails to canonicalize-match we must not trust it.
        _ => String::from("C:\\Windows\\System32\\taskkill.exe"),
    }
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
        // Use PYTHON_CMD env var, or .venv/Scripts/python.exe if it exists, or "python"
        let python_cmd = std::env::var("PYTHON_CMD")
            .ok()
            .and_then(|cmd| {
                // Validate that PYTHON_CMD points to a real python executable
                let p = std::path::Path::new(&cmd);
                // Verify the file actually exists
                if !p.exists() {
                    eprintln!("WARNING: PYTHON_CMD '{}' does not exist, ignoring", cmd);
                    return None;
                }
                // Canonicalize to resolve symlinks and verify real path
                let canonical = match p.canonicalize() {
                    Ok(c) => c,
                    Err(e) => {
                        eprintln!(
                            "WARNING: PYTHON_CMD '{}' cannot be resolved: {}, ignoring",
                            cmd, e
                        );
                        return None;
                    }
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
                    eprintln!(
                        "WARNING: PYTHON_CMD '{}' does not look like a Python executable, ignoring",
                        cmd
                    );
                    None
                }
            })
            .unwrap_or_else(|| {
                let venv_python = base_path.join(".venv").join("Scripts").join("python.exe");
                if venv_python.exists() {
                    venv_python.to_string_lossy().to_string()
                } else {
                    "python".to_string()
                }
            });
        Self {
            base_path,
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
                .with_cmd(sysinfo::UpdateKind::Always),
        );
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

    fn stop_dev_watcher(&mut self) {
        if let Some(pid) = self.get_dev_watcher_pid() {
            // Verify the PID actually points at a python process before
            // killing — Windows recycles PIDs aggressively and the watcher
            // may have died long ago, leaving the PID assigned to an
            // unrelated foreground program (browser, IDE, etc.). The
            // production stop() does the same name check; this path used
            // to skip it.
            Self::refresh_processes_with_cmd(&mut self.sys);
            let is_python = self
                .sys
                .process(sysinfo::Pid::from_u32(pid))
                .map(|p| p.name().to_string_lossy().to_lowercase().contains("python"))
                .unwrap_or(false);

            if is_python {
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
    fn kill_orphan_bot_processes(&mut self) {
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
            let is_test = basenames.iter().any(|b| b.starts_with("test_"));
            let is_ignored_script = basenames
                .iter()
                .any(|b| ignore_basenames.contains(&b.as_str()));
            // Only kill processes whose cmdline references our own base_path —
            // never reach across to other Discord-bot installs on the same host.
            let belongs_to_us = !base_path_str.is_empty() && cmdline.contains(&base_path_str);

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

        if !pids_to_kill.is_empty() {
            // Wait for processes to fully terminate
            std::thread::sleep(std::time::Duration::from_secs(2));
        }
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

    pub fn is_running(&mut self) -> bool {
        if let Some(pid) = self.get_pid() {
            Self::refresh_processes_with_cmd(&mut self.sys);
            if let Some(process) = self.sys.process(sysinfo::Pid::from_u32(pid)) {
                // PID alone is not enough — Windows recycles PIDs aggressively.
                // Verify the cmdline references both bot.py AND our base_path
                // so we don't report "running" for an unrelated PID-reuse.
                let cmd: Vec<String> = process
                    .cmd()
                    .iter()
                    .map(|s| s.to_string_lossy().to_lowercase().to_string())
                    .collect();
                let cmdline = cmd.join(" ");
                let base_path_str = self.base_path.to_string_lossy().to_lowercase().to_string();
                let has_bot_py = cmd.iter().any(|arg| {
                    std::path::Path::new(arg.as_str())
                        .file_name()
                        .map(|f| f.to_string_lossy().eq_ignore_ascii_case("bot.py"))
                        .unwrap_or(false)
                });
                return has_bot_py
                    && (base_path_str.is_empty() || cmdline.contains(&base_path_str));
            }
            false
        } else {
            false
        }
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
        let is_running = pid
            .and_then(|p| self.sys.process(sysinfo::Pid::from_u32(p)))
            .map(|process| {
                let cmd: Vec<String> = process
                    .cmd()
                    .iter()
                    .map(|s| s.to_string_lossy().to_lowercase().to_string())
                    .collect();
                let cmdline = cmd.join(" ");
                let has_bot_py = cmd.iter().any(|arg| {
                    std::path::Path::new(arg.as_str())
                        .file_name()
                        .map(|f| f.to_string_lossy().eq_ignore_ascii_case("bot.py"))
                        .unwrap_or(false)
                });
                has_bot_py && (base_path_str.is_empty() || cmdline.contains(&base_path_str))
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
            // Verify the dev-watcher PID still maps to a python process, not
            // just that *some* process holds that PID. Windows recycles PIDs
            // aggressively (the module invariant every other status/kill path
            // honors), so a bare is_some() check would falsely report mode="Dev"
            // if the watcher died and its PID was reused. Mirror stop_dev_watcher.
            let dev_running = self
                .get_dev_watcher_pid()
                .and_then(|p| self.sys.process(sysinfo::Pid::from_u32(p)))
                .map(|proc| proc.name().to_string_lossy().to_lowercase().contains("python"))
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
                Ok(Some(status)) => StartProgress::Exited { code: status.code() },
                Err(_) => StartProgress::Exited { code: None },
            },
            None => StartProgress::Unknown,
        }
    }

    pub fn start(&mut self) -> Result<String, String> {
        if self.is_running() {
            return Err("Bot is already running".to_string());
        }

        // Kill any orphan bot.py processes that survived a previous stop
        self.kill_orphan_bot_processes();

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
        // Reap any previously-tracked Child that already exited so the slot is empty.
        self.reap_finished_children();
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
        if self.is_running() {
            return Err("Bot is already running".to_string());
        }

        // Stop any existing dev watcher first
        self.stop_dev_watcher();

        let dev_watcher = self.base_path.join("scripts").join("dev_watcher.py");

        // Dev mode: run dev_watcher.py hidden with CREATE_NO_WINDOW
        let child = Command::new(&self.python_cmd)
            .arg(&dev_watcher)
            .current_dir(&self.base_path)
            .creation_flags(CREATE_NO_WINDOW)
            .spawn()
            .map_err(|e| format!("Failed to start dev watcher: {}", e))?;

        // Save dev_watcher PID for later cleanup. If the write fails we can
        // never kill this watcher again, so log loudly instead of swallowing
        // the error — that used to leak orphan watchers across restarts.
        let pid_path = self.dev_watcher_pid_file();
        let pid = child.id();
        // Hold onto the Child handle so stop_dev_watcher() can wait() on it
        // and release the OS handle cleanly. Previously we dropped here and
        // the handle leaked until the dashboard itself exited.
        self.reap_finished_children();
        self.dev_watcher_child = Some(child);
        if let Err(e) = fs::write(&pid_path, pid.to_string()) {
            eprintln!(
                "⚠️ Failed to write dev_watcher PID {} to {}: {} — orphan risk on restart",
                pid,
                pid_path.display(),
                e,
            );
        }

        std::thread::sleep(std::time::Duration::from_secs(3));

        if self.is_running() {
            Ok("Dev Watcher started (hot reload enabled)".to_string())
        } else {
            // Dev watcher takes time to start bot, check again
            std::thread::sleep(std::time::Duration::from_secs(2));
            if self.is_running() {
                Ok("Dev Watcher started (hot reload enabled)".to_string())
            } else {
                Ok("Dev Watcher launched - bot starting...".to_string())
            }
        }
    }

    pub fn stop(&mut self) -> Result<String, String> {
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
                    self.kill_orphan_bot_processes();
                    return Ok(
                        "Bot stopped (no PID file; killed tracked startup process)".to_string()
                    );
                }
                return Err("Bot is not running".to_string());
            }
        };

        if !self.is_running() {
            return Err("Bot is not running".to_string());
        }

        // Verify PID still belongs to a Python/bot process before killing
        // to prevent killing an unrelated process after PID reuse
        Self::refresh_processes_with_cmd(&mut self.sys);
        if let Some(process) = self.sys.process(sysinfo::Pid::from_u32(pid)) {
            let name = process.name().to_string_lossy().to_lowercase();
            if !name.contains("python") {
                // PID was reused by a non-Python process — stale PID file
                let _ = fs::remove_file(self.pid_file());
                return Err("Bot PID was stale (process is no longer Python)".to_string());
            }
        } else {
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

        // Wait up to 3 seconds for exit
        for _ in 0..6 {
            std::thread::sleep(std::time::Duration::from_millis(500));
            Self::refresh_processes_with_cmd(&mut self.sys);
            if self.sys.process(sysinfo::Pid::from_u32(pid)).is_none() {
                break;
            }
        }

        // Kill any remaining orphan bot.py processes
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

    pub fn restart(&mut self) -> Result<String, String> {
        if self.is_running() {
            let old_pid = self.get_pid();
            self.stop()?;
            // Poll until process is gone (max 5 seconds)
            if let Some(pid) = old_pid {
                for _ in 0..10 {
                    std::thread::sleep(std::time::Duration::from_millis(500));
                    Self::refresh_processes_with_cmd(&mut self.sys);
                    if self.sys.process(sysinfo::Pid::from_u32(pid)).is_none() {
                        break;
                    }
                }
            }
        }
        self.start()
    }
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
}
