#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod bot_manager;
mod database;

use bot_manager::{BotManager, BotStatus, RestartBegin, StartProgress, StopOutcome};
use database::{
    ChannelInfo, DashboardConversation, DashboardConversationDetail, DatabaseService, DbStats,
    UserInfo,
};
use std::process::Stdio;
use std::sync::{Arc, LazyLock, Mutex};
use std::time::Instant;
use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager, State, WindowEvent,
};

// Separator between error-log entries. Lazily computed once at first
// use (instead of ``"=".repeat(80)`` on every log write/read) — the
// rebuild was ~300ns each call but happens on a hot path.
static ERROR_LOG_SEPARATOR: LazyLock<String> = LazyLock::new(|| "=".repeat(80));

// Every character a log viewer/editor may render as a HARD LINE BREAK. The
// frontend error log records are delimited by a "\n"+SEPARATOR run, so any of
// these slipping through verbatim in attacker-influenced error_type/message/
// stack text could fake a new log line. Keep this the single source of truth so
// the three sanitization sites in `log_frontend_error` can't drift apart:
//   \n \r        ASCII line feed / carriage return
//   U+000B U+000C vertical tab / form feed
//   U+0085        NEL ("Next Line")
//   U+2028 U+2029 Unicode line / paragraph separator
const LOG_LINEBREAK_CHARS: [char; 7] = [
    '\n', '\r', '\u{0B}', '\u{0C}', '\u{85}', '\u{2028}', '\u{2029}',
];

/// Sanitize a single-line log field: replace every [`LOG_LINEBREAK_CHARS`] with
/// a space (so it cannot forge a new log record) and clamp to `max` chars on a
/// char boundary. Used for the error_type / message fields of the frontend
/// error log.
fn sanitize_log_field(input: &str, max: usize) -> String {
    input
        .replace(LOG_LINEBREAK_CHARS, " ")
        .chars()
        .take(max)
        .collect()
}

struct AppState {
    bot_manager: Arc<Mutex<BotManager>>,
    db_service: Arc<Mutex<DatabaseService>>,
    // Rolling rate-limit window for frontend error logging (per second).
    // Monotonic-clock based: tuple is (window_start_instant, errors_in_window).
    // Using ``Instant`` (monotonic) instead of ``SystemTime`` so an NTP
    // backstep cannot make the bucket appear to have moved backwards in
    // time and silently disable the rate limit.
    frontend_error_rate: Mutex<(Instant, u32)>,
    // Per-file Mutex serializing concurrent log-rotation attempts on the
    // dashboard error log. Without this, two simultaneous frontend errors
    // could both observe ``len > 5MB``, both call ``rename``, and the
    // second call would overwrite the first rotated archive or fail with
    // an OS error on Windows where the destination already exists.
    error_log_rotation: Mutex<()>,
    // Serializes bot LIFECYCLE operations (start / stop / restart / start_dev).
    // The per-op `bot_manager` lock is now released across the multi-second
    // stop/restart wait (so the high-frequency status/log polls stay
    // responsive), which opened a window where a concurrent `start_bot` could
    // spawn a fresh bot that `stop_finish`'s orphan sweep would then kill. This
    // SEPARATE lock — never taken by the get_status/get_logs pollers — restores
    // that mutual exclusion without re-freezing the pollers. Held for the whole
    // duration of each lifecycle command.
    bot_lifecycle: Arc<Mutex<()>>,
}

// Helper macro to lock the bot-manager mutex, RECOVERING a poisoned lock rather
// than failing. A one-off panic elsewhere poisons the mutex; the BotManager
// guards no invariant that a panic could leave permanently broken (same
// reasoning `get_status` uses for its `into_inner()` recovery), so reporting
// "lock poisoned" forever would brick every command that takes this lock. We
// still yield a `Result` so the existing `lock_bot_manager!(state)?` call sites
// keep compiling — after the poison recovery there is no error case left, so the
// `?` is infallible but harmless.
macro_rules! lock_bot_manager {
    ($state:expr) => {
        Ok::<_, String>($state.bot_manager.lock().unwrap_or_else(|e| e.into_inner()))
    };
}

#[tauri::command]
fn get_status(state: State<AppState>) -> Result<BotStatus, String> {
    match state.bot_manager.try_lock() {
        Ok(mut manager) => Ok(manager.get_status()),
        // A one-off panic elsewhere poisons the lock; recover the guard rather
        // than reporting "busy" forever (which would brick the status panel).
        Err(std::sync::TryLockError::Poisoned(p)) => {
            let mut manager = p.into_inner();
            Ok(manager.get_status())
        }
        Err(std::sync::TryLockError::WouldBlock) => {
            // Lock is genuinely held by start/stop/restart. Returning a fake
            // "running" BotStatus would mislead the UI into showing the bot as
            // healthy even when it might be mid-stop or mid-crash. Return a
            // typed error so the frontend can render its own busy / loading
            // state.
            Err("busy".to_string())
        }
    }
}

#[tauri::command]
async fn start_bot(state: State<'_, AppState>) -> Result<String, String> {
    let manager = state.bot_manager.clone();
    let lifecycle = state.bot_lifecycle.clone();

    tauri::async_runtime::spawn_blocking(move || {
        // Serialize against any concurrent stop/restart for the whole op
        // (recover a poisoned lock — it guards no data).
        let _op = lifecycle.lock().unwrap_or_else(|e| e.into_inner());
        let mut mgr = manager
            .lock()
            .unwrap_or_else(|e| e.into_inner()); // recover a poisoned lock — same policy as lock_bot_manager! (an Err here would brick Start/Stop/Restart until app restart while status/logs recover)
        mgr.start()
    })
    .await
    .map_err(|e| format!("Task failed: {}", e))?
}

/// Report progress of a dashboard-initiated start so the frontend can tell a
/// slow-but-healthy cold start apart from a real startup failure (see
/// [`StartProgress`]). Polled by `waitForStart()` after `start_bot` returns.
///
/// `start()` only holds the manager lock for the ~50ms spawn, so by the time
/// the frontend polls this the lock is free; we use the same `spawn_blocking`
/// + blocking-lock pattern as the other bot-control commands rather than
/// `get_status`'s `try_lock` (whose "busy" error exists for the high-frequency
/// background status poll, not this short start window).
#[tauri::command]
async fn get_start_progress(state: State<'_, AppState>) -> Result<StartProgress, String> {
    let manager = state.bot_manager.clone();

    tauri::async_runtime::spawn_blocking(move || {
        let mut mgr = manager
            .lock()
            .unwrap_or_else(|e| e.into_inner()); // recover a poisoned lock — same policy as lock_bot_manager! (an Err here would brick Start/Stop/Restart until app restart while status/logs recover)
        Ok(mgr.start_progress())
    })
    .await
    .map_err(|e| format!("Task failed: {}", e))?
}

#[tauri::command]
async fn stop_bot(state: State<'_, AppState>) -> Result<String, String> {
    let manager = state.bot_manager.clone();
    let lifecycle = state.bot_lifecycle.clone();

    tauri::async_runtime::spawn_blocking(move || {
        // Hold the lifecycle lock across the ENTIRE stop (incl. the lock-free
        // wait below) so a concurrent start can't spawn a bot into the window
        // where Phase 3's orphan sweep would kill it. Recover a poisoned lock.
        let _op = lifecycle.lock().unwrap_or_else(|e| e.into_inner());
        // Phase 1 (lock-held, quick): validate + fire the kill.
        let pid = {
            let mut mgr = manager
                .lock()
                .unwrap_or_else(|e| e.into_inner()); // recover a poisoned lock — same policy as lock_bot_manager! (an Err here would brick Start/Stop/Restart until app restart while status/logs recover)
            match mgr.stop_begin()? {
                // Early-return branches already completed the stop — done.
                StopOutcome::Done(msg) => return Ok(msg),
                StopOutcome::Polling(pid) => pid,
            }
        }; // <- BotManager lock dropped here, BEFORE the wait loop below.

        // Phase 2 (lock-free wait): poll for the killed process to disappear,
        // re-acquiring the lock only for the quick `process_is_gone` check each
        // tick and releasing it across the sleep. This keeps concurrent
        // status/log polls responsive (they need the same lock).
        for _ in 0..6 {
            std::thread::sleep(std::time::Duration::from_millis(500));
            let gone = {
                let mut mgr = manager
                    .lock()
                    .unwrap_or_else(|e| e.into_inner()); // recover a poisoned lock — same policy as lock_bot_manager! (an Err here would brick Start/Stop/Restart until app restart while status/logs recover)
                mgr.process_is_gone(pid)
            };
            if gone {
                break;
            }
        }

        // Phase 3 (lock-held, quick): orphan sweep + reap + delete PID file.
        let mut mgr = manager
            .lock()
            .unwrap_or_else(|e| e.into_inner()); // recover a poisoned lock — same policy as lock_bot_manager! (an Err here would brick Start/Stop/Restart until app restart while status/logs recover)
        mgr.stop_finish()
    })
    .await
    .map_err(|e| format!("Task failed: {}", e))?
}

#[tauri::command]
async fn restart_bot(state: State<'_, AppState>) -> Result<String, String> {
    let manager = state.bot_manager.clone();
    let lifecycle = state.bot_lifecycle.clone();

    tauri::async_runtime::spawn_blocking(move || {
        // Hold the lifecycle lock across the ENTIRE restart (stop wait + start)
        // so no concurrent start/stop can interleave. Recover a poisoned lock.
        let _op = lifecycle.lock().unwrap_or_else(|e| e.into_inner());
        // Phase 1 (lock-held, quick): begin the stop side of the restart.
        let plan = {
            let mut mgr = manager
                .lock()
                .unwrap_or_else(|e| e.into_inner()); // recover a poisoned lock — same policy as lock_bot_manager! (an Err here would brick Start/Stop/Restart until app restart while status/logs recover)
            mgr.restart_begin()
        }; // <- lock dropped before any wait below.

        // Phase 2 (lock-free wait, optional): poll the old PID gone, re-locking
        // only for the quick `process_is_gone` check each tick and releasing the
        // lock across the sleep so status/log polls stay responsive.
        let (poll_pid, needs_finish) = match plan {
            RestartBegin::StartNow => (None, false),
            RestartBegin::PollThenFinish(pid) => (Some(pid), true),
            RestartBegin::PollThenStart(pid) => (Some(pid), false),
        };
        if let Some(pid) = poll_pid {
            for _ in 0..10 {
                std::thread::sleep(std::time::Duration::from_millis(500));
                let gone = {
                    let mut mgr = manager
                        .lock()
                        .unwrap_or_else(|e| e.into_inner()); // recover a poisoned lock — same policy as lock_bot_manager! (an Err here would brick Start/Stop/Restart until app restart while status/logs recover)
                    mgr.process_is_gone(pid)
                };
                if gone {
                    break;
                }
            }
        }

        // Phase 3 (lock-held, quick): finish the stop teardown if the begin
        // phase fired a kill, then start the bot again.
        let mut mgr = manager
            .lock()
            .unwrap_or_else(|e| e.into_inner()); // recover a poisoned lock — same policy as lock_bot_manager! (an Err here would brick Start/Stop/Restart until app restart while status/logs recover)
        if needs_finish {
            let _ = mgr.stop_finish();
        }
        mgr.start()
    })
    .await
    .map_err(|e| format!("Task failed: {}", e))?
}

#[tauri::command]
async fn start_dev_bot(state: State<'_, AppState>) -> Result<String, String> {
    let manager = state.bot_manager.clone();
    let lifecycle = state.bot_lifecycle.clone();

    tauri::async_runtime::spawn_blocking(move || {
        // Serialize against any concurrent stop/restart for the whole op
        // (recover a poisoned lock — it guards no data).
        let _op = lifecycle.lock().unwrap_or_else(|e| e.into_inner());
        let mut mgr = manager
            .lock()
            .unwrap_or_else(|e| e.into_inner()); // recover a poisoned lock — same policy as lock_bot_manager! (an Err here would brick Start/Stop/Restart until app restart while status/logs recover)
        mgr.start_dev()
    })
    .await
    .map_err(|e| format!("Task failed: {}", e))?
}

#[tauri::command]
fn get_logs(state: State<AppState>, count: usize) -> Result<Vec<String>, String> {
    let count = count.min(10_000); // Cap at 10k lines to prevent abuse
    match state.bot_manager.try_lock() {
        Ok(manager) => Ok(manager.read_logs(count)),
        // A one-off panic elsewhere poisons the lock; recover the guard and still
        // serve logs rather than wedging the log panel on a "busy" placeholder
        // forever (mirrors get_status's into_inner() recovery — the BotManager
        // guards no invariant a panic could permanently corrupt).
        Err(std::sync::TryLockError::Poisoned(p)) => Ok(p.into_inner().read_logs(count)),
        // Lock is genuinely held by a start/stop/restart op — surface the busy
        // placeholder so the frontend keeps polling.
        Err(std::sync::TryLockError::WouldBlock) => Ok(vec![
            "[Dashboard] Bot manager busy — retrying...".to_string(),
        ]),
    }
}

#[tauri::command]
fn clear_logs(state: State<AppState>) -> Result<String, String> {
    let manager = lock_bot_manager!(state)?;
    manager.clear_logs()
}

#[tauri::command]
fn get_base_path(state: State<AppState>) -> Result<String, String> {
    let manager = lock_bot_manager!(state)?;
    Ok(manager.base_path().to_string_lossy().to_string())
}

#[tauri::command]
fn get_logs_path(state: State<AppState>) -> Result<String, String> {
    let manager = lock_bot_manager!(state)?;
    Ok(manager.logs_dir().to_string_lossy().to_string())
}

#[tauri::command]
fn get_data_path(state: State<AppState>) -> Result<String, String> {
    let manager = lock_bot_manager!(state)?;
    Ok(manager.data_dir().to_string_lossy().to_string())
}

// DB commands run their lock-holding rusqlite work inside
// `tauri::async_runtime::spawn_blocking` (mirroring `start_bot`) so a slow or
// SQLITE_BUSY-blocked query can't pin an IPC worker and freeze unrelated
// invokes (status polls, log refresh, chat). Input validation stays on the
// async thread — it's cheap and takes no lock — and only the actual DB call
// moves onto the blocking pool. `db_service` is an `Arc<Mutex<_>>` so the
// handle can be cloned into the `'static` closure.
#[tauri::command]
async fn get_db_stats(state: State<'_, AppState>) -> Result<DbStats, String> {
    let db = state.db_service.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let db = db
            .lock()
            .map_err(|e| format!("Failed to acquire database lock: {}", e))?;
        db.get_stats()
    })
    .await
    .map_err(|e| format!("Task failed: {}", e))?
}

#[tauri::command]
async fn get_recent_channels(
    state: State<'_, AppState>,
    limit: i32,
) -> Result<Vec<ChannelInfo>, String> {
    let limit = limit.clamp(1, 100); // Cap to prevent abuse
    let db = state.db_service.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let db = db
            .lock()
            .map_err(|e| format!("Failed to acquire database lock: {}", e))?;
        db.get_recent_channels(limit)
    })
    .await
    .map_err(|e| format!("Task failed: {}", e))?
}

#[tauri::command]
async fn get_top_users(state: State<'_, AppState>, limit: i32) -> Result<Vec<UserInfo>, String> {
    let limit = limit.clamp(1, 100); // Cap to prevent abuse
    let db = state.db_service.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let db = db
            .lock()
            .map_err(|e| format!("Failed to acquire database lock: {}", e))?;
        db.get_top_users(limit)
    })
    .await
    .map_err(|e| format!("Task failed: {}", e))?
}

#[tauri::command]
async fn get_dashboard_conversations_native(
    state: State<'_, AppState>,
    limit: i32,
) -> Result<Vec<DashboardConversation>, String> {
    let limit = limit.clamp(1, 200);
    let db = state.db_service.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let db = db
            .lock()
            .map_err(|e| format!("Failed to acquire database lock: {}", e))?;
        db.get_dashboard_conversations(limit)
    })
    .await
    .map_err(|e| format!("Task failed: {}", e))?
}

#[tauri::command]
async fn get_dashboard_conversation_detail_native(
    state: State<'_, AppState>,
    conversation_id: String,
) -> Result<DashboardConversationDetail, String> {
    if conversation_id.trim().is_empty() {
        return Err("Missing conversation ID".to_string());
    }

    let db = state.db_service.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let db = db
            .lock()
            .map_err(|e| format!("Failed to acquire database lock: {}", e))?;
        db.get_dashboard_conversation_detail(&conversation_id)?
            .ok_or_else(|| "Conversation not found".to_string())
    })
    .await
    .map_err(|e| format!("Task failed: {}", e))?
}

#[tauri::command]
async fn clear_history(state: State<'_, AppState>) -> Result<i32, String> {
    let db = state.db_service.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let db = db
            .lock()
            .map_err(|e| format!("Failed to acquire database lock: {}", e))?;
        db.clear_history()
    })
    .await
    .map_err(|e| format!("Task failed: {}", e))?
}

#[tauri::command]
async fn show_confirm_dialog(app: tauri::AppHandle, message: String) -> Result<bool, String> {
    use tauri::async_runtime::channel;
    use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
    // Async callback variant (not `blocking_show()`): the previous version
    // blocked the IPC worker for the entire dialog, freezing every other
    // invoke (status polls, log refresh, chat) while the prompt was open.
    // Use Tauri's bundled async channel rather than pulling in a direct
    // tokio dependency.
    let (tx, mut rx) = channel::<bool>(1);
    app.dialog()
        .message(&message)
        .title("Confirm")
        .kind(MessageDialogKind::Warning)
        .buttons(MessageDialogButtons::OkCancelCustom(
            "Yes".into(),
            "No".into(),
        ))
        .show(move |confirmed| {
            // Receiver may have been dropped if the caller cancelled the
            // invoke — ignore the send error in that case. blocking_send
            // because this callback fires on a non-async thread.
            let _ = tx.blocking_send(confirmed);
        });
    rx.recv()
        .await
        .ok_or_else(|| "dialog channel closed before reply".to_string())
}

#[tauri::command]
async fn delete_channels_history(
    state: State<'_, AppState>,
    channel_ids: Vec<String>,
) -> Result<i32, String> {
    if channel_ids.is_empty() {
        return Ok(0);
    }
    if channel_ids.len() > 100 {
        return Err("Too many channels (max 100)".to_string());
    }
    // Parse string IDs to i64 (avoids JavaScript Number precision loss for
    // Discord Snowflake IDs). Discord snowflakes are 64-bit unsigned but
    // are always positive (timestamp-based), so a negative value indicates
    // a malformed payload — reject explicitly so a frontend bug doesn't
    // forward signed-cast garbage into the DB layer.
    let parsed_ids: Vec<i64> = channel_ids
        .iter()
        .map(|id| {
            let parsed = id
                .parse::<i64>()
                .map_err(|e| format!("Invalid channel ID '{}': {}", id, e))?;
            if parsed <= 0 {
                return Err(format!("Channel ID must be positive, got: {}", id));
            }
            Ok(parsed)
        })
        .collect::<Result<Vec<_>, _>>()?;
    let db = state.db_service.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let db = db
            .lock()
            .map_err(|e| format!("Failed to acquire database lock: {}", e))?;
        db.delete_channels_history(&parsed_ids)
    })
    .await
    .map_err(|e| format!("Task failed: {}", e))?
}

#[tauri::command]
fn open_folder(path: String, state: State<AppState>) -> Result<(), String> {
    // Reject oversized paths before any filesystem syscall — Windows
    // MAX_PATH is 260 and even with long-path support the practical
    // upper bound for an Explorer-launchable directory is well below
    // 4 KiB. Anything past this is almost certainly hostile input.
    if path.len() > 4096 {
        return Err("Path too long".to_string());
    }
    let path_obj = std::path::Path::new(&path);
    if !path_obj.exists() {
        return Err(format!("Path does not exist: {}", path));
    }

    // Canonicalize to resolve symlinks and .. traversal
    let canonical = path_obj
        .canonicalize()
        .map_err(|e| format!("Failed to resolve path: {}", e))?;

    // Symlink-safe directory check: reject paths whose final component is
    // itself a symlink (canonicalize follows them, but we still want to
    // refuse so an attacker can't park a symlink inside the bot dir that
    // points elsewhere — the canonicalized target may pass starts_with
    // because we evaluate it relative to the SAME canonicalized base
    // below, but the original path's symlink-ness is the actual signal).
    let symlink_meta =
        std::fs::symlink_metadata(&path).map_err(|e| format!("Failed to stat path: {}", e))?;
    if symlink_meta.file_type().is_symlink() {
        return Err("Access denied: symlinked paths are not allowed".to_string());
    }

    // Only allow opening directories (not arbitrary files)
    if !canonical.is_dir() {
        return Err("Path is not a directory".to_string());
    }

    // Security: restrict to known subdirectories of the bot base path
    let manager = lock_bot_manager!(state)?;
    let base_path = manager
        .base_path()
        .canonicalize()
        .map_err(|e| format!("Failed to resolve base path: {}", e))?;
    if !canonical.starts_with(&base_path) {
        return Err("Access denied: path is outside the bot directory".to_string());
    }
    // Drop the manager guard before spawning a child process so a slow
    // explorer launch doesn't keep the lock held longer than necessary.
    drop(manager);

    // Resolve an absolute path to explorer.exe under %SystemRoot% so a
    // poisoned PATH entry (or an attacker-planted explorer.exe in the
    // application directory) cannot get executed instead of the system one.
    // Validate that the env-var value resembles a real Windows root —
    // a poisoned ``SystemRoot=C:\Attacker`` would otherwise let an
    // attacker-planted explorer.exe run with our process privileges.
    // We canonicalize the env value AND the hardcoded default and
    // accept the env path only if both canonicalize to the same target.
    // This is stricter than the previous "last segment is 'windows'"
    // check, which would accept e.g. ``C:\\Attacker\\Windows``.
    let sysroot_canonical = std::env::var("SystemRoot")
        .ok()
        .and_then(|s| std::fs::canonicalize(&s).ok());
    let default_root_canonical = std::fs::canonicalize("C:\\Windows").ok();
    let explorer_path = match (sysroot_canonical, default_root_canonical.as_ref()) {
        (Some(env_root), Some(def_root)) if &env_root == def_root => {
            env_root.join("explorer.exe").to_string_lossy().into_owned()
        }
        // Windows not on C: (C:\Windows failed to canonicalize) — the hardcoded
        // fallback can't exist either, so trust a validated env SystemRoot iff
        // the explorer.exe it points at exists. Mirrors taskkill_path() in
        // bot_manager.rs; on a normal C:\Windows host this arm never fires and
        // the strict equality above remains the anti-poisoning gate.
        (Some(env_root), None) => {
            let candidate = env_root.join("explorer.exe");
            if candidate.is_file() {
                candidate.to_string_lossy().into_owned()
            } else {
                String::from("C:\\Windows\\explorer.exe")
            }
        }
        _ => String::from("C:\\Windows\\explorer.exe"),
    };

    // TOCTOU note: there is an inherent race between the canonicalize/check
    // above and the spawn below — a local attacker with write access to a
    // subdirectory could swap a folder for a symlink in this window. We
    // pass the already-canonicalized path (rather than the user's input)
    // so explorer.exe receives the resolved target string, but Windows
    // filesystem lookup still happens at spawn time. Threat model is
    // local-only and the user could already navigate there manually.
    // Detach stdio so the spawned explorer.exe doesn't keep the
    // dashboard's stdin/stdout/stderr handles open. Without this, on
    // platforms that inherit handles by default the child could pin
    // a console window or leak file descriptors back into our process.
    std::process::Command::new(&explorer_path)
        .arg(canonical.as_os_str())
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|e| format!("Failed to open folder: {}", e))?;

    Ok(())
}

#[tauri::command]
fn log_frontend_error(
    state: State<AppState>,
    error_type: String,
    message: String,
    stack: Option<String>,
) -> Result<String, String> {
    use std::io::Write;

    // Rate limit: cap at 20 errors/sec. Stops a frontend render-loop bug from
    // filling the log file and pinning the Tauri worker on disk I/O.
    // Uses ``Instant::now()`` (monotonic) so NTP backsteps or manual wall-
    // clock changes can't make the bucket appear to have moved backwards
    // and silently disable the limit.
    {
        let now = Instant::now();
        let mut rate = state
            .frontend_error_rate
            .lock()
            .map_err(|e| format!("rate-limit lock poisoned: {}", e))?;
        if now.duration_since(rate.0).as_secs() < 1 {
            if rate.1 >= 20 {
                return Ok("Error dropped (rate limit)".to_string());
            }
            rate.1 += 1;
        } else {
            *rate = (now, 1);
        }
    }

    // Sanitize inputs to prevent log injection: strip every newline / Unicode
    // line-break character (see LOG_LINEBREAK_CHARS) and clamp length so an
    // attacker-influenced frontend string can't fake a new line in
    // dashboard_errors.log.
    let error_type = sanitize_log_field(&error_type, 256);
    let message = sanitize_log_field(&message, 4096); // Limit message size and strip newlines

    let manager = lock_bot_manager!(state)?;
    let log_dir = manager.logs_dir();
    let error_log_path = log_dir.join("dashboard_errors.log");

    // Ensure logs directory exists
    if !log_dir.exists() {
        let _ = std::fs::create_dir_all(&log_dir);
    }

    // Use UTC so log timestamps are unambiguous when correlating
    // dashboard logs with bot logs (which already use UTC). Local time
    // here meant a log read in another timezone could be off by hours.
    let timestamp = chrono::Utc::now()
        .format("%Y-%m-%d %H:%M:%S UTC")
        .to_string();
    // Stack traces are multi-line by nature so we tab-indent every line
    // instead of stripping (preserves readability) but we still strip the
    // Unicode line separators that could otherwise fake a new log entry.
    //
    // Derive the set to neutralize from LOG_LINEBREAK_CHARS (the single source
    // of truth) minus '\n'/'\r', which we handle specially below, so this can't
    // drift out of sync if a new line-break char is added there.
    let stack_other_linebreaks: Vec<char> = LOG_LINEBREAK_CHARS
        .into_iter()
        .filter(|c| *c != '\n' && *c != '\r')
        .collect();
    let stack_trace = stack
        .unwrap_or_else(|| "No stack trace".to_string())
        // Replace the Unicode line-break characters that aren't the genuine "\n"
        // record structure (VT/FF/NEL/U+2028/U+2029) so a crafted stack can't
        // fake a new log line; \r is dropped and \n is preserved-then-indented.
        .replace(&stack_other_linebreaks[..], " ")
        .replace('\r', "")
        .replace('\n', "\n  ")
        .chars()
        .take(16384)
        .collect::<String>(); // Limit stack trace size

    let log_entry = format!(
        "\n[{}] {}\nMessage: {}\nStack: {}\n{}",
        timestamp,
        error_type,
        message,
        stack_trace,
        ERROR_LOG_SEPARATOR.as_str()
    );

    // Rotate error log if it exceeds 5 MB.
    // Held under ``error_log_rotation`` so two concurrent log writers
    // can't both see ``len > 5MB`` and both attempt the rename — on
    // Windows the second rename would fail because the destination
    // exists, and on POSIX the first archive would be lost.
    if error_log_path.exists() {
        if let Ok(meta) = std::fs::metadata(&error_log_path) {
            if meta.len() > 5 * 1024 * 1024 {
                let _rot_guard = state
                    .error_log_rotation
                    .lock()
                    .map_err(|e| format!("rotation lock poisoned: {}", e))?;
                // Re-check size under the lock — another writer may have
                // already rotated while we were waiting on the mutex.
                if let Ok(meta2) = std::fs::metadata(&error_log_path) {
                    if meta2.len() > 5 * 1024 * 1024 {
                        let old_path = error_log_path.with_extension("log.old");
                        let _ = std::fs::remove_file(&old_path);
                        if let Err(e) = std::fs::rename(&error_log_path, &old_path) {
                            eprintln!("Failed to rotate error log: {}", e);
                        }
                    }
                }
            }
        }
    }

    // Append to error log file
    let mut file = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&error_log_path)
        .map_err(|e| format!("Failed to open error log: {}", e))?;

    file.write_all(log_entry.as_bytes())
        .map_err(|e| format!("Failed to write error log: {}", e))?;

    // Forward to Sentry only if (a) a DSN was configured at startup AND (b) the
    // user has NOT opted out of telemetry at runtime. The Rust _sentry_guard is
    // initialized once in main() and never torn down, so checking is_enabled()
    // alone honors only the startup DSN state — a user who toggles telemetry OFF
    // mid-session (set_telemetry_enabled writes telemetry_optout.flag) would keep
    // shipping events until restart. Re-read the opt-out flag on every forward so
    // the runtime consent toggle takes effect immediately. (`manager` is the same
    // guard locked above for the log write, so this adds no extra lock.)
    if !telemetry_flag_path(&manager).exists()
        && sentry::Hub::current()
            .client()
            .is_some_and(|c| c.is_enabled())
    {
        sentry::capture_message(
            &format!("[{}] {}", error_type, message),
            sentry::Level::Error,
        );
    }

    Ok(format!("Error logged to: {}", error_log_path.display()))
}

#[tauri::command]
fn get_dashboard_errors(state: State<AppState>, count: usize) -> Result<Vec<String>, String> {
    let count = count.min(500); // Cap to prevent abuse
    let manager = lock_bot_manager!(state)?;
    let error_log_path = manager.logs_dir().join("dashboard_errors.log");

    if !error_log_path.exists() {
        return Ok(vec!["No errors logged yet.".to_string()]);
    }

    // Cap file read to 10 MB to prevent OOM on huge log files
    let metadata = std::fs::metadata(&error_log_path)
        .map_err(|e| format!("Failed to read error log metadata: {}", e))?;
    if metadata.len() > 10 * 1024 * 1024 {
        return Err("Error log too large (>10 MB). Please clear it first.".to_string());
    }

    match std::fs::read_to_string(&error_log_path) {
        Ok(content) => {
            // Split on the NEWLINE-PREFIXED separator. Every record is written as
            // "...\n{SEPARATOR}", and sanitized message/stack can never contain
            // "\n" immediately followed by '=' (message strips all newlines; the
            // stack rewrites "\n" -> "\n  "), so this delimiter cannot be faked by
            // user content — unlike the bare 80-'=' run, which a crafted
            // message/stack could embed to fragment one entry into two. Backward
            // compatible: existing logs were already written with the leading \n.
            let separator = format!("\n{}", ERROR_LOG_SEPARATOR.as_str());
            let entries: Vec<&str> = content.split(separator.as_str()).collect();
            Ok(entries
                .iter()
                .rev()
                .filter(|s| !s.trim().is_empty())
                .take(count)
                .map(|s| s.trim().to_string())
                .collect())
        }
        Err(_) => Ok(vec!["Failed to read error log.".to_string()]),
    }
}

#[tauri::command]
fn clear_dashboard_errors(state: State<AppState>) -> Result<String, String> {
    let manager = lock_bot_manager!(state)?;
    let error_log_path = manager.logs_dir().join("dashboard_errors.log");

    if error_log_path.exists() {
        std::fs::write(&error_log_path, "")
            .map_err(|e| format!("Failed to clear error log: {}", e))?;
    }

    Ok("Dashboard errors cleared".to_string())
}

// ============================================================================
// Telemetry opt-in/out (#35)
// ============================================================================

/// Path to the opt-out flag file. Presence = opted out; absence = opted in.
/// Stored under `data/` next to the bot's database so both the Python bot
/// (sentry_integration.py) and the Rust dashboard read the same file.
fn telemetry_flag_path(manager: &BotManager) -> std::path::PathBuf {
    manager
        .base_path()
        .join("data")
        .join("telemetry_optout.flag")
}

#[tauri::command]
fn get_telemetry_enabled(state: State<AppState>) -> Result<bool, String> {
    let manager = lock_bot_manager!(state)?;
    Ok(!telemetry_flag_path(&manager).exists())
}

#[tauri::command]
fn set_telemetry_enabled(state: State<AppState>, enabled: bool) -> Result<(), String> {
    let manager = lock_bot_manager!(state)?;
    let flag = telemetry_flag_path(&manager);
    if enabled {
        // Opt IN: remove the flag (idempotent — ignore "not found").
        if flag.exists() {
            std::fs::remove_file(&flag)
                .map_err(|e| format!("Failed to re-enable telemetry: {}", e))?;
        }
    } else {
        // Opt OUT: create parent dir if needed, then write an empty marker file.
        if let Some(parent) = flag.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        std::fs::write(&flag, b"").map_err(|e| format!("Failed to disable telemetry: {}", e))?;
    }
    Ok(())
}

#[tauri::command]
fn get_ws_token(state: State<AppState>) -> Result<String, String> {
    let manager = lock_bot_manager!(state)?;
    let env_path = manager.base_path().join(".env");
    let token = if env_path.exists() {
        read_dotenv_value(&env_path, "DASHBOARD_WS_TOKEN")
            .or_else(|| std::env::var("DASHBOARD_WS_TOKEN").ok())
    } else {
        std::env::var("DASHBOARD_WS_TOKEN").ok()
    };
    // Surface the missing-token case explicitly. The previous version
    // swallowed the absence and returned "" — frontend then opened the
    // WS with no token and got a confusing "401: missing token" with no
    // hint that .env wasn't configured.
    match token {
        Some(t) if !t.is_empty() => Ok(t),
        _ => Err("DASHBOARD_WS_TOKEN is not set in .env or environment".to_string()),
    }
}

fn normalize_ws_connect_host(host: &str) -> String {
    match host.trim() {
        "" | "0.0.0.0" | "::" | "[::]" | "::1" | "[::1]" => "localhost".to_string(),
        value => {
            // A raw IPv6 literal (contains ':' but isn't already bracketed)
            // must be wrapped in '[' ... ']' before it is joined with ':port'
            // — otherwise ``ws://2001:db8::5:8765/ws`` makes the address
            // colons ambiguous with the port and ``new WebSocket()`` can't
            // parse it. Hostnames and IPv4 literals contain no ':' so they
            // are returned verbatim.
            if value.contains(':') && !value.starts_with('[') {
                format!("[{value}]")
            } else {
                value.to_string()
            }
        }
    }
}

fn env_flag_is_truthy(value: Option<String>) -> bool {
    value
        .map(|raw| {
            matches!(
                raw.trim().to_ascii_lowercase().as_str(),
                "1" | "true" | "yes" | "on"
            )
        })
        .unwrap_or(false)
}

// ⚠️ CSP CONSTRAINT — KEEP THIS ENDPOINT AND THE CSP IN SYNC.
// This endpoint is configurable via WS_DASHBOARD_HOST / WS_DASHBOARD_PORT /
// WS_REQUIRE_TLS, but the webview's Content-Security-Policy `connect-src` is
// HARDCODED to exactly the four loopback :8765 origins:
//     ws://127.0.0.1:8765  wss://127.0.0.1:8765
//     ws://localhost:8765  wss://localhost:8765
// (defined in tauri.conf.json `app.security.csp` and duplicated in the
// <meta http-equiv="Content-Security-Policy"> in ui/index.html).
// The CSP is INTENTIONALLY tight (a security control — do NOT widen it to a
// wildcard port to "fix" a custom config). Consequence: if an operator sets
// WS_DASHBOARD_PORT to anything other than 8765, this function returns e.g.
// `ws://127.0.0.1:9000/ws`, the browser blocks it per CSP, and the chat panel
// fails to connect. A custom port therefore REQUIRES manually editing the CSP
// in BOTH files above. The loopback wss form and a custom HOST self-heal (the
// CSP already lists the wss:8765 origins and the TS client falls back to the
// :8765 host candidates), so the PORT is the one knob the CSP does not follow.
// See env.example (WS_DASHBOARD_PORT) for the operator-facing note.
#[tauri::command]
fn get_ws_endpoint(state: State<AppState>) -> Result<String, String> {
    let manager = lock_bot_manager!(state)?;
    let env_path = manager.base_path().join(".env");

    let ws_host = read_dotenv_value(&env_path, "WS_DASHBOARD_HOST")
        .or_else(|| std::env::var("WS_DASHBOARD_HOST").ok())
        .unwrap_or_else(|| "127.0.0.1".to_string());
    let ws_port = read_dotenv_value(&env_path, "WS_DASHBOARD_PORT")
        .or_else(|| std::env::var("WS_DASHBOARD_PORT").ok())
        .and_then(|v| v.trim().parse::<u16>().ok())
        .filter(|p| *p != 0)
        .map(|p| p.to_string())
        .unwrap_or_else(|| "8765".to_string());
    let ws_require_tls = env_flag_is_truthy(
        read_dotenv_value(&env_path, "WS_REQUIRE_TLS")
            .or_else(|| std::env::var("WS_REQUIRE_TLS").ok()),
    );
    let ws_scheme = if ws_require_tls { "wss" } else { "ws" };

    // Warn (don't fail) when the resolved port diverges from the CSP-permitted
    // 8765 — the connection will be blocked by the webview CSP and the only
    // symptom otherwise is an opaque "connection failed" in the chat panel.
    if ws_port != "8765" {
        eprintln!(
            "WARNING: WS_DASHBOARD_PORT resolved to {} but the dashboard CSP only permits \
             loopback :8765 — the chat WebSocket will be blocked unless you also edit the \
             connect-src CSP in tauri.conf.json and ui/index.html.",
            ws_port,
        );
    }

    Ok(format!(
        "{}://{}:{}/ws",
        ws_scheme,
        normalize_ws_connect_host(&ws_host),
        ws_port,
    ))
}

/// Read a single key from a .env file without requiring AppState.
///
/// Tolerates two common variants that ``dotenv`` accepts but a naive
/// ``strip_prefix`` would miss:
///   1. A UTF-8 BOM (``\u{feff}``) on the first line — Windows editors
///      such as Notepad save files this way by default.
///   2. A leading ``export `` prefix — shells use this form so the
///      same file can be ``source``d.
fn read_dotenv_value(env_path: &std::path::Path, key: &str) -> Option<String> {
    let content = std::fs::read_to_string(env_path).ok()?;
    let prefix = format!("{}=", key);
    for (idx, raw_line) in content.lines().enumerate() {
        let mut line = raw_line.trim();
        if idx == 0 {
            line = line.trim_start_matches('\u{feff}');
        }
        // ``export KEY=val`` is valid in .env files that double as shell
        // scripts; strip the prefix so the key-match below still works.
        if let Some(rest) = line.strip_prefix("export ") {
            line = rest.trim_start();
        }
        if let Some(val) = line.strip_prefix(&prefix) {
            // Mirror python-dotenv (the bot parses the SAME file):
            //   * A quoted value returns the content between the quotes, and any
            //     trailing text after the closing quote (an inline comment) is
            //     discarded. `#` INSIDE the quotes is preserved.
            //   * An unquoted value has its ` # comment` stripped.
            // The old code required the WHOLE trimmed value to be quote-wrapped,
            // so `KEY="tok"  # rotate` fell through to the unquoted branch and
            // returned `"tok"` WITH quotes → the dashboard sent a quoted token,
            // the bot expected `tok`, and the WS handshake 401'd with no hint.
            let t = val.trim();
            let first = t.chars().next();
            let val: &str = if first == Some('"') || first == Some('\'') {
                let q = first.unwrap();
                // Closing quote = first matching quote after the opener. Index 1
                // is a char boundary (the opener is a 1-byte ASCII quote).
                match t[1..].find(q) {
                    // Content between the quotes; trailing comment (if any) dropped.
                    Some(rel) => &t[1..rel + 1],
                    // Unterminated quote (malformed) — treat as unquoted, matching
                    // the prior fall-through for a mismatched pair like `"value'`.
                    None => match t.find(" #") {
                        Some(i) => t[..i].trim_end(),
                        None => t,
                    },
                }
            } else {
                match t.find(" #") {
                    Some(i) => t[..i].trim_end(),
                    None => t,
                }
            };
            if !val.is_empty() {
                return Some(val.to_string());
            }
        }
    }
    None
}

/// Get the path to the dashboard config file that stores the bot base path.
fn get_config_path() -> std::path::PathBuf {
    dirs::config_dir()
        .unwrap_or_else(|| std::path::PathBuf::from("."))
        .join("com.botdashboard.desktop")
        .join("bot_path.txt")
}

/// Save the bot base path to a config file so it persists across installs.
fn save_base_path_config(base_path: &std::path::Path) {
    let config_path = get_config_path();
    if let Some(parent) = config_path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    let _ = std::fs::write(&config_path, base_path.to_string_lossy().as_bytes());
}

/// Return the list of directory roots under which a saved bot base path
/// is trusted to live. Any path written into ``bot_path.txt`` that does
/// not canonicalise under one of these roots is ignored — that file
/// lives in ``%APPDATA%`` (user-writable) and another process running
/// as the same user could otherwise redirect the dashboard to ``python
/// <attacker_dir>/bot.py``. Keeping the allowlist tight to typical
/// install locations bounds that risk without forcing operators to set
/// ``BOT_BASE_PATH`` every launch.
fn allowed_base_roots(exe_path: &Option<std::path::PathBuf>) -> Vec<std::path::PathBuf> {
    let mut roots: Vec<std::path::PathBuf> = Vec::new();
    if let Some(home) = dirs::home_dir() {
        roots.push(home.clone());
    }
    if let Some(docs) = dirs::document_dir() {
        roots.push(docs);
    }
    if let Some(desktop) = dirs::desktop_dir() {
        roots.push(desktop);
    }
    if let Some(downloads) = dirs::download_dir() {
        roots.push(downloads);
    }
    if let Some(exe) = exe_path.as_ref().and_then(|p| p.parent()) {
        roots.push(exe.to_path_buf());
    }
    // Canonicalise the roots ahead of comparison so symlink shenanigans
    // on either side ("the attacker created %HOME%/.../link → C:\evil")
    // get resolved consistently. Skip any root that fails to canonicalise.
    roots
        .into_iter()
        .filter_map(|r| std::fs::canonicalize(&r).ok())
        .collect()
}

/// Check whether an already-canonicalized path lives under one of the trusted
/// install-location roots. Callers must pass a path that has itself been
/// produced by ``std::fs::canonicalize`` so the prefix comparison is against
/// the same resolution used for every other decision about this path.
fn canonical_is_under_allowed_root(
    canon: &std::path::Path,
    exe_path: &Option<std::path::PathBuf>,
) -> bool {
    let roots = allowed_base_roots(exe_path);
    if roots.is_empty() {
        // No trustable root resolved — refuse to trust an attacker-writable
        // marker file rather than fall back to "trust everything".
        return false;
    }
    roots.iter().any(|root| canon.starts_with(root))
}

/// Resolve production base path by checking saved config and common locations.
fn resolve_production_base_path(exe_path: &Option<std::path::PathBuf>) -> std::path::PathBuf {
    // 1. Check saved config from a previous successful run. The marker file
    // lives in ``%APPDATA%\com.botdashboard.desktop\bot_path.txt`` which is
    // user-writable, so an attacker-controlled folder with a ``bot.py`` in
    // it could otherwise redirect the dashboard's ``python bot.py`` spawn.
    // Reject saved paths that don't canonicalise under one of the trusted
    // install-location roots; treat that as "no saved value" and fall
    // through to the next resolution strategy.
    let config_path = get_config_path();
    if let Ok(saved) = std::fs::read_to_string(&config_path) {
        let saved_path = std::path::PathBuf::from(saved.trim());
        // Canonicalize ONCE and bind every subsequent decision — the bot.py
        // existence check, the allowed-root confinement check, and the value
        // we return (which BotManager later spawns ``python bot.py`` from) — to
        // that single resolution. Doing the checks against separate resolutions
        // of the same string left a TOCTOU window where a same-user attacker
        // who can write the user-writable marker file could swap the directory
        // between the existence check and the spawn.
        if let Ok(canonical) = std::fs::canonicalize(&saved_path) {
            if canonical.join("bot.py").exists() {
                if canonical_is_under_allowed_root(&canonical, exe_path) {
                    return canonical;
                } else {
                    eprintln!(
                        "WARNING: Saved bot_path.txt points outside trusted roots ({}); ignoring.",
                        canonical.display(),
                    );
                }
            }
        }
    }

    // 2. Check if exe is directly in the bot folder (legacy layout)
    if let Some(ref exe) = exe_path {
        if let Some(parent) = exe.parent() {
            if parent.join("bot.py").exists() {
                return parent.to_path_buf();
            }
        }
    }

    // 3. Check common user paths
    if let Some(home) = dirs::home_dir() {
        let candidates = [
            home.join("BOT"),
            home.join("bot"),
            home.join("Desktop").join("BOT"),
            home.join("Documents").join("BOT"),
        ];
        for candidate in &candidates {
            if candidate.join("bot.py").exists() {
                return candidate.clone();
            }
        }
    }

    // 4. Fallback to exe parent
    eprintln!("WARNING: Could not find bot.py in any known location. Set BOT_BASE_PATH env var.");
    exe_path
        .as_ref()
        .and_then(|p| p.parent().map(|p| p.to_path_buf()))
        .unwrap_or_else(|| {
            std::env::current_dir().unwrap_or_else(|_| std::path::PathBuf::from("."))
        })
}

/// Hard cap on the length of any free-text field shipped to Sentry. Frontend
/// `console.error` payloads (which become the `[type] message` we forward) can
/// carry large chat bodies or server-error blobs; truncating bounds how much
/// arbitrary content can leave the machine even after path redaction.
const SENTRY_TEXT_MAX: usize = 2048;

/// Redact absolute filesystem paths from a free-text string and truncate it.
///
/// The Rust dashboard's only Sentry events are the `capture_message` forwards in
/// `log_frontend_error`, whose `[type] message` body can embed absolute paths
/// (install dir, user profile, source locations) that deanonymize the
/// machine/user. This is the single path-normalization point, wired into the
/// `before_send` hook in `sentry::init`. It scrubs absolute *paths* only; the
/// dashboard handles no API keys/tokens/PII, so it is intentionally narrower
/// than the Python bot's before_send (`utils/monitoring/sentry_integration.py`).
///
/// Coverage is deliberately limited. `before_send` applies this scrubber to
/// `event.message` and each `event.exception.values[].value`, and nulls
/// `event.server_name` separately. It does NOT walk stacktrace frames
/// (`abs_path` / `filename`): those are not free text we control here, so this
/// function makes no claim over them.
///
/// Dependency-free (no `regex` crate). It scans PER LINE: split `input` on `\n`,
/// and for each line locate the first span that *looks like* an absolute path:
///   * a Windows drive path   — `X:\...` or `X:/...`
///   * a UNC / extended path  — `\\...` or `//...`
///   * a POSIX absolute path  — a `/` followed by a non-whitespace char
///
/// The prefix is matched *anywhere inside* the line, not just at its start, so a
/// path glued to surrounding punctuation/quotes (`'C:\…'`, `(C:\…)`), carrying a
/// non-whitespace prefix (`at:C:\…`), or behind a `file://` scheme
/// (`file:///C:/…`) still gets redacted instead of leaking the user/host segment.
///
/// Fail-closed for privacy: once a path prefix is found, EVERYTHING from that
/// prefix to end-of-line is replaced by a single `<path>`. Windows profile dirs
/// routinely contain spaces (`Users\First Last`, `Program Files`), so a
/// token-by-token scrub would leak every segment after the first space. We trade
/// that trailing diagnostic context for the guarantee that no path segment
/// survives. Lines with no path-like span are kept verbatim.
///
/// Relative tokens, identifiers, and ordinary words are left intact. Conservative
/// by design: it only ever *removes* information, so a false positive degrades a
/// line's tail to `<path>` and never leaks more.
fn scrub_sentry_text(input: &str) -> String {
    // Return the byte offset within `line` where an absolute-path prefix begins,
    // scanning every position (not just index 0) so a path glued to a quote,
    // bracket, or scheme prefix is still found. `None` => no path-like span.
    fn find_path_start(line: &str) -> Option<usize> {
        let bytes = line.as_bytes();
        for i in 0..bytes.len() {
            let rest = &bytes[i..];
            // UNC (\\server\share) or POSIX-ish (//...) prefix.
            if rest.starts_with(b"\\\\") || rest.starts_with(b"//") {
                return Some(i);
            }
            // Windows drive path: letter, ':', then '\' or '/'.
            if rest.len() >= 3
                && rest[0].is_ascii_alphabetic()
                && rest[1] == b':'
                && (rest[2] == b'\\' || rest[2] == b'/')
            {
                return Some(i);
            }
            // POSIX absolute path: a '/' immediately followed by a non-whitespace
            // path char. Requiring the next byte to be non-whitespace keeps a bare
            // separator like "a / b" (and a trailing "/") from looking like a path.
            if rest[0] == b'/' && rest.len() > 1 && !rest[1].is_ascii_whitespace() {
                return Some(i);
            }
        }
        None
    }

    // Scrub PER LINE: once a path prefix is found, collapse it and everything to
    // end-of-line into a single `<path>`. This over-redacts the line's tail on
    // purpose so no path segment after a space (Windows `Users\First Last`) can
    // survive — fail-closed for privacy. Lines without a path are left verbatim.
    let scrubbed = input
        .split('\n')
        .map(|line| match find_path_start(line) {
            None => line.to_string(),
            Some(start) => format!("{}<path>", &line[..start]),
        })
        .collect::<Vec<_>>()
        .join("\n");

    // Truncate on a char boundary (take(N) over chars) so we never split a
    // multi-byte UTF-8 sequence, and append an ellipsis marker when clamped.
    if scrubbed.chars().count() > SENTRY_TEXT_MAX {
        let mut out: String = scrubbed.chars().take(SENTRY_TEXT_MAX).collect();
        out.push_str("…[truncated]");
        out
    } else {
        scrubbed
    }
}

fn main() {
    // Base path for the bot files - use BOT_BASE_PATH env var or default
    let base_path = std::env::var("BOT_BASE_PATH")
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|_| {
            // Check if we're in dev mode (executable is in target/debug or target/release)
            let exe_path = std::env::current_exe().ok();
            let is_dev = exe_path
                .as_ref()
                .and_then(|p| p.to_str())
                .map(|s| {
                    s.contains("target\\debug")
                        || s.contains("target\\release")
                        || s.contains("target/debug")
                        || s.contains("target/release")
                })
                .unwrap_or(false);

            if is_dev {
                // Dev mode: go up from native_dashboard/target/debug to BOT folder
                exe_path
                    .and_then(|p| p.parent().map(|p| p.to_path_buf())) // debug/
                    .and_then(|p| p.parent().map(|p| p.to_path_buf())) // target/
                    .and_then(|p| p.parent().map(|p| p.to_path_buf())) // native_dashboard/
                    .and_then(|p| p.parent().map(|p| p.to_path_buf())) // BOT/
                    .unwrap_or_else(|| {
                        eprintln!(
                            "WARNING: Could not determine bot base path, using current directory"
                        );
                        std::env::current_dir().unwrap_or_else(|_| std::path::PathBuf::from("."))
                    })
            } else {
                // Production: installed via NSIS to AppData, need to find the actual bot folder.
                // Strategy: check a saved config file, then common locations, then fallback.
                resolve_production_base_path(&exe_path)
            }
        });

    // Save base path to config so future installs can find it automatically
    if base_path.join("bot.py").exists() {
        save_base_path_config(&base_path);
    }

    // Initialize Sentry if DSN is configured (reads from .env or SENTRY_DSN env var).
    // The guard must live for the entire duration of main() to flush events on exit.
    let env_path = base_path.join(".env");
    let _sentry_guard = read_dotenv_value(&env_path, "SENTRY_DSN")
        .or_else(|| std::env::var("SENTRY_DSN").ok())
        .filter(|dsn| {
            // Validate DSN is a legitimate Sentry URL (HTTPS + host ends with .sentry.io)
            dsn.starts_with("https://")
                && dsn
                    .split('/')
                    .nth(2) // Extract host from https://HOST/...
                    .is_some_and(|host| {
                        // Strip optional port suffix and userinfo prefix.
                        let host_part = host.split('@').next_back().unwrap_or(host);
                        let host_no_port = host_part.split(':').next().unwrap_or(host_part);
                        // Standard Sentry SaaS DSN host is `oXXXXXX.ingest.sentry.io`.
                        // The previous check accepted any subdomain of sentry.io,
                        // including ones an attacker could obtain (defunct
                        // subdomain takeover) — narrow to the documented ingest
                        // host or the bare apex.
                        host_no_port == "sentry.io"
                            || host_no_port == "ingest.sentry.io"
                            || host_no_port.ends_with(".ingest.sentry.io")
                    })
        })
        .map(|dsn| {
            sentry::init((
                dsn,
                sentry::ClientOptions {
                    release: sentry::release_name!(),
                    // Never ship absolute paths, the machine hostname, or
                    // oversized free text to the third-party ingest. Frontend
                    // error forwards routinely embed the install dir, the user's
                    // profile path, and large chat/server-error bodies, and the
                    // SDK auto-populates the hostname into `server_name`.
                    //
                    // Coverage: we scrub `event.message` and every
                    // `event.exception.values[].value` in place, and null
                    // `event.server_name`. We do NOT walk stacktrace frame
                    // `abs_path`/`filename` — those are not scrubbed here.
                    //
                    // Scope note: the text scrubber only redacts absolute *paths*
                    // and truncates — it is deliberately NARROWER than the Python
                    // bot's before_send (utils/monitoring/sentry_integration.py),
                    // which also strips API keys/tokens/PII. The Rust dashboard
                    // never handles those secrets, so path redaction + truncation
                    // is the relevant control here; do not mistake it for a full
                    // secret scrubber.
                    before_send: Some(std::sync::Arc::new(|mut event| {
                        if let Some(msg) = event.message.take() {
                            event.message = Some(scrub_sentry_text(&msg));
                        }
                        for exc in event.exception.values.iter_mut() {
                            if let Some(val) = exc.value.take() {
                                exc.value = Some(scrub_sentry_text(&val));
                            }
                        }
                        // Drop the auto-populated machine hostname so it never
                        // leaves the machine (fail-closed; not free text we scrub).
                        event.server_name = None;
                        Some(event)
                    })),
                    ..Default::default()
                },
            ))
        });

    let bot_manager = BotManager::new(base_path.clone());
    let db_service = DatabaseService::new(base_path.join("data").join("bot_database.db"));

    tauri::Builder::default()
        // Single-instance must be the FIRST registered plugin (per its docs) so
        // a second launch is intercepted before anything else initializes. The
        // close button hides to tray, so users WILL double-click the shortcut
        // again: without this a second full process starts — two tray icons and
        // two BotManagers racing the same bot.pid across processes (the
        // bot_lifecycle mutex is per-process and cannot serialize them). Show +
        // focus the existing window instead.
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.unminimize();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_dialog::init())
        .manage(AppState {
            bot_manager: Arc::new(Mutex::new(bot_manager)),
            db_service: Arc::new(Mutex::new(db_service)),
            frontend_error_rate: Mutex::new((Instant::now(), 0)),
            error_log_rotation: Mutex::new(()),
            bot_lifecycle: Arc::new(Mutex::new(())),
        })
        .setup(|app| {
            // Create tray menu
            let show_item = MenuItem::with_id(app, "show", "แสดง Dashboard", true, None::<&str>)?;
            let quit_item = MenuItem::with_id(app, "quit", "ปิดโปรแกรม", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show_item, &quit_item])?;

            // Build tray icon
            // WARNING: DO NOT MODIFY THE TOOLTIP TEXT BELOW!
            // The Korean text "디스코드 봇 대시보드" is INTENTIONAL.
            // This is a design choice by the owner - DO NOT CHANGE IT!
            // ห้ามแก้ไข tooltip นี้เด็ดขาด! ตั้งใจให้เป็นภาษาเกาหลี
            let _tray = TrayIconBuilder::new()
                .icon(
                    app.default_window_icon()
                        .ok_or("Default window icon not configured in tauri.conf.json")?
                        .clone(),
                )
                .menu(&menu)
                .show_menu_on_left_click(false)
                .tooltip("디스코드 봇 대시보드")
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "show" => {
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                    "quit" => {
                        app.exit(0);
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        let app = tray.app_handle();
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                })
                .build(app)?;

            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                // Prevent default close
                api.prevent_close();

                let window_clone = window.clone();
                let app_handle = window.app_handle().clone();

                // Use non-blocking callback-based dialog to avoid starving the async runtime
                use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};

                app_handle
                    .dialog()
                    .message("กด Yes เพื่อปิดโปรแกรม หรือ No เพื่อซ่อนไปที่ System Tray")
                    .title("ปิดโปรแกรม")
                    .kind(MessageDialogKind::Info)
                    .buttons(MessageDialogButtons::YesNo)
                    .show(move |confirmed| {
                        if confirmed {
                            // User clicked Yes - quit the app
                            app_handle.exit(0);
                        } else {
                            // User clicked No - hide to tray
                            let _ = window_clone.hide();
                        }
                    });
            }
        })
        .invoke_handler(tauri::generate_handler![
            get_status,
            get_start_progress,
            start_bot,
            start_dev_bot,
            stop_bot,
            restart_bot,
            get_logs,
            clear_logs,
            get_base_path,
            get_logs_path,
            get_data_path,
            get_db_stats,
            get_recent_channels,
            get_top_users,
            get_dashboard_conversations_native,
            get_dashboard_conversation_detail_native,
            clear_history,
            show_confirm_dialog,
            delete_channels_history,
            open_folder,
            log_frontend_error,
            get_dashboard_errors,
            clear_dashboard_errors,
            get_ws_token,
            get_ws_endpoint,
            get_telemetry_enabled,
            set_telemetry_enabled
        ])
        .run(tauri::generate_context!())
        .unwrap_or_else(|e| {
            eprintln!("Error while running tauri application: {}", e);
            std::process::exit(1);
        });
}

// ============================================================================
// Unit tests — pure helper coverage (no Tauri runtime, no filesystem except
// tempfile in `read_dotenv_value` cases). Run with `cargo test`.
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    // ------- normalize_ws_connect_host -------

    #[test]
    fn normalize_maps_bind_all_addresses_to_localhost() {
        for bind_all in ["", "0.0.0.0", "::", "[::]", "::1", "[::1]"] {
            assert_eq!(
                normalize_ws_connect_host(bind_all),
                "localhost",
                "expected {bind_all:?} to normalize to localhost",
            );
        }
    }

    #[test]
    fn normalize_preserves_concrete_hosts() {
        assert_eq!(normalize_ws_connect_host("example.com"), "example.com");
        assert_eq!(normalize_ws_connect_host("10.0.0.5"), "10.0.0.5");
        assert_eq!(normalize_ws_connect_host("  localhost  "), "localhost");
    }

    // ------- env_flag_is_truthy -------

    #[test]
    fn env_flag_recognizes_common_truthy_values() {
        for truthy in ["1", "true", "TRUE", "True", "yes", "on", "  true ", "ON"] {
            assert!(
                env_flag_is_truthy(Some(truthy.to_string())),
                "expected {truthy:?} to be truthy",
            );
        }
    }

    #[test]
    fn env_flag_rejects_falsy_and_missing() {
        for falsy in ["0", "false", "no", "off", "", " ", "whatever"] {
            assert!(
                !env_flag_is_truthy(Some(falsy.to_string())),
                "expected {falsy:?} to be falsy",
            );
        }
        assert!(!env_flag_is_truthy(None));
    }

    // ------- read_dotenv_value -------

    /// Build a temp .env file with the given body. Returns the path; drops the
    /// file at scope end is handled by the tempfile::NamedTempFile lifetime
    /// attached to the returned PathBuf via leak-free tempdir.
    fn write_env(body: &str) -> (tempfile::TempDir, std::path::PathBuf) {
        let dir = tempfile::tempdir().expect("tempdir");
        let path = dir.path().join(".env");
        let mut f = std::fs::File::create(&path).expect("create .env");
        f.write_all(body.as_bytes()).expect("write .env");
        (dir, path)
    }

    #[test]
    fn dotenv_returns_none_for_missing_file() {
        let missing = std::path::PathBuf::from("/this/path/does/not/exist/.env");
        assert_eq!(read_dotenv_value(&missing, "ANYTHING"), None);
    }

    #[test]
    fn dotenv_returns_none_for_missing_key() {
        let (_tmp, path) = write_env("FOO=bar\nBAZ=qux\n");
        assert_eq!(read_dotenv_value(&path, "MISSING"), None);
    }

    #[test]
    fn dotenv_returns_value_for_present_key() {
        let (_tmp, path) = write_env("FOO=bar\nBAZ=qux\n");
        assert_eq!(read_dotenv_value(&path, "FOO"), Some("bar".to_string()));
        assert_eq!(read_dotenv_value(&path, "BAZ"), Some("qux".to_string()));
    }

    #[test]
    fn dotenv_strips_surrounding_quotes() {
        let (_tmp, path) = write_env("TOKEN=\"wrapped-in-double\"\nTOKEN2='single-quoted'\n");
        assert_eq!(
            read_dotenv_value(&path, "TOKEN"),
            Some("wrapped-in-double".to_string())
        );
        assert_eq!(
            read_dotenv_value(&path, "TOKEN2"),
            Some("single-quoted".to_string())
        );
    }

    #[test]
    fn dotenv_ignores_empty_values() {
        // Ensures an empty `KEY=` in .env doesn't override an env var fallback.
        let (_tmp, path) = write_env("EMPTY=\nFILLED=ok\n");
        assert_eq!(read_dotenv_value(&path, "EMPTY"), None);
        assert_eq!(read_dotenv_value(&path, "FILLED"), Some("ok".to_string()));
    }

    #[test]
    fn dotenv_returns_first_match_when_duplicated() {
        let (_tmp, path) = write_env("DUP=first\nDUP=second\n");
        assert_eq!(read_dotenv_value(&path, "DUP"), Some("first".to_string()));
    }

    #[test]
    fn dotenv_strips_inline_comment_on_unquoted_value() {
        // python-dotenv (the bot's parser of the same file) strips ` # ...`
        // on unquoted values — the dashboard must agree or a commented token
        // line yields an opaque 401.
        let (_tmp, path) = write_env("TOKEN=abc  # rotate monthly\n");
        assert_eq!(read_dotenv_value(&path, "TOKEN"), Some("abc".to_string()));
    }

    #[test]
    fn dotenv_keeps_hash_inside_quoted_value() {
        let (_tmp, path) = write_env("TOKEN=\"abc # not a comment\"\n");
        assert_eq!(
            read_dotenv_value(&path, "TOKEN"),
            Some("abc # not a comment".to_string())
        );
    }

    #[test]
    fn dotenv_strips_quotes_and_trailing_comment() {
        // Regression: `KEY="tok"  # rotate` used to fall through to the unquoted
        // branch (the whole trimmed value wasn't quote-wrapped) and return
        // `"tok"` WITH quotes, so the dashboard sent a quoted token and the bot
        // 401'd. python-dotenv drops both quotes and the trailing comment.
        let (_tmp, path) = write_env("TOKEN=\"mytoken\"  # rotate monthly\n");
        assert_eq!(read_dotenv_value(&path, "TOKEN"), Some("mytoken".to_string()));
        let (_tmp2, path2) = write_env("TOKEN2='single'  # note\n");
        assert_eq!(read_dotenv_value(&path2, "TOKEN2"), Some("single".to_string()));
    }

    // ------- sanitize_log_field (audit dash-rust-5: log-injection completeness) -

    #[test]
    fn sanitize_strips_all_unicode_line_breaks() {
        // The regression: U+0085 (NEL) — and the other newline-class chars — must
        // be replaced with a space so a crafted frontend string can never forge a
        // new log line. Build a string containing EVERY LOG_LINEBREAK_CHARS char.
        let raw = "a\nb\rc\u{0B}d\u{0C}e\u{85}f\u{2028}g\u{2029}h";
        let out = sanitize_log_field(raw, 4096);
        // No line-break character survives.
        for ch in LOG_LINEBREAK_CHARS {
            assert!(
                !out.contains(ch),
                "sanitized field still contains line-break char {:?}",
                ch,
            );
        }
        // Specifically NEL — the char the prior sanitizer missed.
        assert!(!out.contains('\u{85}'), "U+0085 (NEL) must be stripped");
        // Each break was replaced 1:1 with a space (length preserved, content
        // visible), so the visible letters remain in order.
        assert_eq!(out, "a b c d e f g h");
    }

    #[test]
    fn sanitize_nel_cannot_fake_a_record_separator() {
        // A NEL immediately followed by the '='-run that the log splitter keys on
        // must not survive as a real line break — after sanitization there is no
        // '\n' adjacent to the '=' run, so get_dashboard_errors can't be tricked
        // into splitting one record into two.
        let attack = format!("evil\u{85}{}", "=".repeat(80));
        let out = sanitize_log_field(&attack, 4096);
        assert!(!out.contains('\n'), "no real newline may be introduced");
        assert!(
            !out.contains('\u{85}'),
            "NEL must be neutralized to a space"
        );
    }

    #[test]
    fn sanitize_clamps_to_max_chars() {
        let raw = "x".repeat(1000);
        assert_eq!(sanitize_log_field(&raw, 256).chars().count(), 256);
    }

    #[test]
    fn sanitize_truncates_on_char_boundary_without_panicking() {
        // Multi-byte chars must not be split mid-sequence by the length clamp.
        let raw = "✓".repeat(10);
        let out = sanitize_log_field(&raw, 3);
        assert_eq!(out, "✓✓✓");
    }

    // ------- scrub_sentry_text (audit dash-rust-2: privacy / path redaction) ----

    #[test]
    fn scrub_redacts_windows_drive_paths() {
        let out = scrub_sentry_text("error at C:\\Users\\alice\\BOT\\bot.py line 5");
        assert!(
            !out.contains("alice"),
            "absolute Windows path (with user name) must be redacted: {out}",
        );
        assert!(
            out.contains("<path>"),
            "redacted token marker expected: {out}"
        );
        // The non-path prefix survives; the path tail (incl. "line 5") collapses
        // to a single <path> through end-of-line (fail-closed).
        assert_eq!(out, "error at <path>");
    }

    #[test]
    fn scrub_redacts_unc_and_posix_paths() {
        let unc = scrub_sentry_text("opened \\\\server\\share\\secret.db ok");
        assert!(!unc.contains("server"), "UNC path must be redacted: {unc}");
        assert!(unc.contains("<path>"));

        let posix = scrub_sentry_text("read /home/bob/.ssh/id_rsa now");
        assert!(
            !posix.contains("bob"),
            "POSIX path must be redacted: {posix}"
        );
        assert!(posix.contains("<path>"));
    }

    #[test]
    fn scrub_redacts_forward_slash_windows_paths() {
        let out = scrub_sentry_text("at C:/Users/carol/app failed");
        assert!(
            !out.contains("carol"),
            "forward-slash drive path must redact: {out}"
        );
        assert!(out.contains("<path>"));
    }

    #[test]
    fn scrub_preserves_ordinary_text() {
        let msg = "TypeError cannot read property foo of undefined";
        assert_eq!(scrub_sentry_text(msg), msg);
    }

    #[test]
    fn scrub_truncates_oversized_text() {
        let raw = "word ".repeat(2000); // ~10k chars, no paths
        let out = scrub_sentry_text(&raw);
        assert!(
            out.chars().count() <= SENTRY_TEXT_MAX + "…[truncated]".chars().count(),
            "scrubbed text must be clamped near SENTRY_TEXT_MAX, got {}",
            out.chars().count(),
        );
        assert!(out.ends_with("…[truncated]"));
    }

    #[test]
    fn scrub_does_not_leak_bare_slash_or_protocol_relative() {
        // A lone "/" is not a path token; protocol-relative "//host" IS redacted
        // (it matches the UNC/'//' rule) — both behaviors are intentional.
        assert_eq!(scrub_sentry_text("a / b"), "a / b");
        let pr = scrub_sentry_text("see //evil.example/x");
        assert!(
            pr.contains("<path>"),
            "protocol-relative token should redact: {pr}"
        );
    }

    // -- dash-rust-2 completeness: prefix matched ANYWHERE in a token, so a path
    // glued to punctuation / a scheme can't leak the user/host segment. The
    // earlier (split-then-first-char) scrubber leaked all of these. --

    #[test]
    fn scrub_redacts_quote_wrapped_path() {
        // Single-quoted path: a leading quote glued to the path must not block
        // detection. The leading run (incl. the opening quote) survives; the path
        // and the trailing quote collapse to <path> through end-of-line.
        let out = scrub_sentry_text("open 'C:\\Users\\alice\\secret.txt'");
        assert!(!out.contains("alice"), "quoted path leaked user: {out}");
        assert_eq!(out, "open '<path>");
    }

    #[test]
    fn scrub_redacts_double_quote_wrapped_path() {
        // Trailing text after the path ("failed") is intentionally swallowed by
        // the end-of-line redaction; only the non-path prefix survives.
        let out = scrub_sentry_text("read \"C:\\Users\\dave\\app.log\" failed");
        assert!(
            !out.contains("dave"),
            "double-quoted path leaked user: {out}"
        );
        assert_eq!(out, "read \"<path>");
    }

    #[test]
    fn scrub_redacts_paren_wrapped_path() {
        // Parenthesized source location, e.g. "(C:\...\bot.py:5)". The closing
        // paren and trailing text collapse into the end-of-line <path>.
        let out = scrub_sentry_text("stack (C:\\Users\\erin\\bot.py) here");
        assert!(
            !out.contains("erin"),
            "paren-wrapped path leaked user: {out}"
        );
        assert_eq!(out, "stack (<path>");
    }

    #[test]
    fn scrub_redacts_scheme_prefixed_path() {
        // A non-whitespace prefix glued in front (e.g. "at:C:\...") must not
        // shield the path from detection. Trailing text ("line 3") is swallowed.
        let out = scrub_sentry_text("at:C:\\Users\\frank\\bot.py line 3");
        assert!(!out.contains("frank"), "prefixed path leaked user: {out}");
        assert_eq!(out, "at:<path>");
    }

    #[test]
    fn scrub_redacts_file_url() {
        // file:// URLs embed an absolute path after the scheme. The earliest match
        // is the drive-style "e:/" inside "file:/" (letter,':','/'), so redaction
        // starts there and runs to end-of-line, swallowing the trailing "ok".
        let out = scrub_sentry_text("loaded file:///C:/Users/carol/index.html ok");
        assert!(!out.contains("carol"), "file:// URL leaked user: {out}");
        assert_eq!(out, "loaded fil<path>");

        // POSIX-rooted file URL — same "e:/" match point.
        let posix = scrub_sentry_text("see file:///home/grace/.ssh/config");
        assert!(
            !posix.contains("grace"),
            "posix file:// URL leaked user: {posix}"
        );
        assert_eq!(posix, "see fil<path>");
    }

    #[test]
    fn scrub_redacts_unc_glued_to_punctuation() {
        // UNC path wrapped in quotes — the leading "\\\\" prefix is mid-token.
        let out = scrub_sentry_text("opened '\\\\server\\share\\secret.db'");
        assert!(
            !out.contains("server"),
            "quoted UNC path leaked host: {out}"
        );
        assert_eq!(out, "opened '<path>");
    }

    // -- FIX 1 (privacy, fail-closed): a path containing a SPACE must not leak any
    // segment after the first space. The earlier per-token scrubber leaked the
    // surname in Windows profile dirs ("Users\First Last"); end-of-line redaction
    // closes that. We assert the username is ABSENT, not merely that <path> shows. --

    #[test]
    fn scrub_spaced_path_does_not_leak_surname_in_backtrace() {
        // Classic JS stack frame: "(C:\Users\Jane Doe\app\main.js:10:5)".
        let out =
            scrub_sentry_text("at Object.<anonymous> (C:\\Users\\Jane Doe\\app\\main.js:10:5)");
        assert!(!out.contains("Doe"), "spaced path leaked surname: {out}");
        assert!(
            !out.contains("Jane"),
            "spaced path leaked given name: {out}"
        );
        assert!(out.contains("<path>"), "redacted marker expected: {out}");
        // Only the path tail collapses; the non-path lead-in is preserved.
        assert_eq!(out, "at Object.<anonymous> (<path>");
    }

    #[test]
    fn scrub_spaced_path_does_not_leak_surname_bare() {
        let out = scrub_sentry_text("C:\\Users\\John Smith\\AppData\\creds");
        assert!(!out.contains("Smith"), "spaced path leaked surname: {out}");
        assert!(
            !out.contains("John"),
            "spaced path leaked given name: {out}"
        );
        assert_eq!(out, "<path>");
    }

    #[test]
    fn scrub_multiline_preserves_clean_line_redacts_path_line() {
        // A clean line stays verbatim; only the line carrying an absolute path is
        // redacted, and that line is redacted to end-of-line.
        let input = "TypeError: boom\n    at C:\\Users\\Mary Jane\\app\\main.js:1:1\nend of trace";
        let out = scrub_sentry_text(input);
        assert!(!out.contains("Mary"), "multiline leaked given name: {out}");
        assert!(!out.contains("Jane"), "multiline leaked surname: {out}");
        assert_eq!(out, "TypeError: boom\n    at <path>\nend of trace");
    }
}
