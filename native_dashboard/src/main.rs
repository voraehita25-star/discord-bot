#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod bot_manager;
mod database;

use bot_manager::{BotManager, BotStatus};
use database::{
    ChannelInfo,
    DashboardConversation,
    DashboardConversationDetail,
    DatabaseService,
    DbStats,
    UserInfo,
};
use std::sync::{Arc, Mutex};
use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager, State, WindowEvent,
};

struct AppState {
    bot_manager: Arc<Mutex<BotManager>>,
    db_service: Mutex<DatabaseService>,
    // Rolling rate-limit window for frontend error logging (per second).
    // Tuple: (window_start_unix_seconds, errors_in_current_second).
    frontend_error_rate: Mutex<(u64, u32)>,
}

// Helper macro to safely lock mutex and handle poisoned state
macro_rules! lock_bot_manager {
    ($state:expr) => {
        $state.bot_manager.lock()
            .map_err(|e| format!("Failed to acquire bot manager lock: {}", e))
    };
}

macro_rules! lock_db_service {
    ($state:expr) => {
        $state.db_service.lock()
            .map_err(|e| format!("Failed to acquire database lock: {}", e))
    };
}

#[tauri::command]
fn get_status(state: State<AppState>) -> Result<BotStatus, String> {
    match state.bot_manager.try_lock() {
        Ok(mut manager) => Ok(manager.get_status()),
        Err(_) => {
            // Lock is held by start/stop/restart — return busy status
            // so the UI doesn't freeze waiting for the mutex.
            // Note: is_running is unknown here since we can't check,
            // the mode field signals the UI to show a loading state.
            Ok(BotStatus {
                is_running: true,
                pid: None,
                uptime: "...".to_string(),
                memory_mb: 0.0,
                mode: "Updating...".to_string(),
            })
        }
    }
}

#[tauri::command]
async fn start_bot(state: State<'_, AppState>) -> Result<String, String> {
    let manager = state.bot_manager.clone();
    
    tauri::async_runtime::spawn_blocking(move || {
        let mut mgr = manager.lock()
            .map_err(|e| format!("Failed to acquire bot manager lock: {}", e))?;
        mgr.start()
    })
    .await
    .map_err(|e| format!("Task failed: {}", e))?
}

#[tauri::command]
async fn stop_bot(state: State<'_, AppState>) -> Result<String, String> {
    let manager = state.bot_manager.clone();
    
    tauri::async_runtime::spawn_blocking(move || {
        let mut mgr = manager.lock()
            .map_err(|e| format!("Failed to acquire bot manager lock: {}", e))?;
        mgr.stop()
    })
    .await
    .map_err(|e| format!("Task failed: {}", e))?
}

#[tauri::command]
async fn restart_bot(state: State<'_, AppState>) -> Result<String, String> {
    let manager = state.bot_manager.clone();
    
    tauri::async_runtime::spawn_blocking(move || {
        let mut mgr = manager.lock()
            .map_err(|e| format!("Failed to acquire bot manager lock: {}", e))?;
        mgr.restart()
    })
    .await
    .map_err(|e| format!("Task failed: {}", e))?
}

#[tauri::command]
async fn start_dev_bot(state: State<'_, AppState>) -> Result<String, String> {
    let manager = state.bot_manager.clone();
    
    tauri::async_runtime::spawn_blocking(move || {
        let mut mgr = manager.lock()
            .map_err(|e| format!("Failed to acquire bot manager lock: {}", e))?;
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
        Err(_) => Ok(vec!["[Dashboard] Bot manager busy — retrying...".to_string()]),
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

#[tauri::command]
fn get_db_stats(state: State<AppState>) -> Result<DbStats, String> {
    let db = lock_db_service!(state)?;
    Ok(db.get_stats())
}

#[tauri::command]
fn get_recent_channels(state: State<AppState>, limit: i32) -> Result<Vec<ChannelInfo>, String> {
    let limit = limit.clamp(1, 100); // Cap to prevent abuse
    let db = lock_db_service!(state)?;
    Ok(db.get_recent_channels(limit))
}

#[tauri::command]
fn get_top_users(state: State<AppState>, limit: i32) -> Result<Vec<UserInfo>, String> {
    let limit = limit.clamp(1, 100); // Cap to prevent abuse
    let db = lock_db_service!(state)?;
    Ok(db.get_top_users(limit))
}

#[tauri::command]
fn get_dashboard_conversations_native(state: State<AppState>, limit: i32) -> Result<Vec<DashboardConversation>, String> {
    let limit = limit.clamp(1, 200);
    let db = lock_db_service!(state)?;
    db.get_dashboard_conversations(limit)
}

#[tauri::command]
fn get_dashboard_conversation_detail_native(
    state: State<AppState>,
    conversation_id: String,
) -> Result<DashboardConversationDetail, String> {
    if conversation_id.trim().is_empty() {
        return Err("Missing conversation ID".to_string());
    }

    let db = lock_db_service!(state)?;
    db.get_dashboard_conversation_detail(&conversation_id)?
        .ok_or_else(|| "Conversation not found".to_string())
}

#[tauri::command]
fn clear_history(state: State<AppState>) -> Result<i32, String> {
    let db = lock_db_service!(state)?;
    db.clear_history()
}

#[tauri::command]
fn show_confirm_dialog(app: tauri::AppHandle, message: String) -> bool {
    use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
    app.dialog()
        .message(&message)
        .title("Confirm")
        .kind(MessageDialogKind::Warning)
        .buttons(MessageDialogButtons::OkCancelCustom("Yes".into(), "No".into()))
        .blocking_show()
}

#[tauri::command]
fn delete_channels_history(state: State<AppState>, channel_ids: Vec<String>) -> Result<i32, String> {
    if channel_ids.is_empty() {
        return Ok(0);
    }
    if channel_ids.len() > 100 {
        return Err("Too many channels (max 100)".to_string());
    }
    // Parse string IDs to i64 (avoids JavaScript Number precision loss for Discord Snowflake IDs)
    let parsed_ids: Vec<i64> = channel_ids
        .iter()
        .map(|id| id.parse::<i64>().map_err(|e| format!("Invalid channel ID '{}': {}", id, e)))
        .collect::<Result<Vec<_>, _>>()?;
    let db = lock_db_service!(state)?;
    db.delete_channels_history(&parsed_ids)
}

#[tauri::command]
fn open_folder(path: String, state: State<AppState>) -> Result<(), String> {
    let path_obj = std::path::Path::new(&path);
    if !path_obj.exists() {
        return Err(format!("Path does not exist: {}", path));
    }
    
    // Canonicalize to resolve symlinks and .. traversal
    let canonical = path_obj.canonicalize()
        .map_err(|e| format!("Failed to resolve path: {}", e))?;
    
    // Only allow opening directories (not arbitrary files)
    if !canonical.is_dir() {
        return Err("Path is not a directory".to_string());
    }

    // Security: restrict to known subdirectories of the bot base path
    let manager = lock_bot_manager!(state)?;
    let base_path = manager.base_path().canonicalize()
        .map_err(|e| format!("Failed to resolve base path: {}", e))?;
    if !canonical.starts_with(&base_path) {
        return Err("Access denied: path is outside the bot directory".to_string());
    }
    
    std::process::Command::new("explorer")
        .arg(canonical.as_os_str())
        .spawn()
        .map_err(|e| format!("Failed to open folder: {}", e))?;
    
    Ok(())
}

#[tauri::command]
fn log_frontend_error(state: State<AppState>, error_type: String, message: String, stack: Option<String>) -> Result<String, String> {
    use std::io::Write;

    // Rate limit: cap at 20 errors/sec. Stops a frontend render-loop bug from
    // filling the log file and pinning the Tauri worker on disk I/O.
    {
        let now_secs = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);
        let mut rate = state.frontend_error_rate.lock()
            .map_err(|e| format!("rate-limit lock poisoned: {}", e))?;
        if rate.0 == now_secs {
            if rate.1 >= 20 {
                return Ok("Error dropped (rate limit)".to_string());
            }
            rate.1 += 1;
        } else {
            *rate = (now_secs, 1);
        }
    }

    // Sanitize inputs to prevent log injection (strip newlines and Unicode line separators, limit length)
    let error_type = error_type.replace(['\n', '\r', '\u{2028}', '\u{2029}'], " ").chars().take(256).collect::<String>();
    let message = message.replace(['\n', '\r', '\u{2028}', '\u{2029}'], " ").chars().take(4096).collect::<String>(); // Limit message size and strip newlines
    
    let manager = lock_bot_manager!(state)?;
    let log_dir = manager.logs_dir();
    let error_log_path = log_dir.join("dashboard_errors.log");
    
    // Ensure logs directory exists
    if !log_dir.exists() {
        let _ = std::fs::create_dir_all(&log_dir);
    }
    
    let timestamp = chrono::Local::now().format("%Y-%m-%d %H:%M:%S").to_string();
    let stack_trace = stack
        .unwrap_or_else(|| "No stack trace".to_string())
        .chars().take(16384).collect::<String>(); // Limit stack trace size
    
    let log_entry = format!(
        "\n[{}] {}\nMessage: {}\nStack: {}\n{}",
        timestamp, error_type, message, stack_trace, "=".repeat(80)
    );
    
    // Rotate error log if it exceeds 5 MB
    if error_log_path.exists() {
        if let Ok(meta) = std::fs::metadata(&error_log_path) {
            if meta.len() > 5 * 1024 * 1024 {
                let old_path = error_log_path.with_extension("log.old");
                let _ = std::fs::remove_file(&old_path);
                if let Err(e) = std::fs::rename(&error_log_path, &old_path) {
                    eprintln!("Failed to rotate error log: {}", e);
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

    // Forward to Sentry if a DSN was configured at startup
    if sentry::Hub::current().client().is_some_and(|c| c.is_enabled()) {
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
            // Split by separator and take last N entries
            let entries: Vec<&str> = content.split("=".repeat(80).as_str()).collect();
            Ok(entries.iter()
                .rev()
                .filter(|s| !s.trim().is_empty())
                .take(count)
                .map(|s| s.trim().to_string())
                .collect())
        }
        Err(_) => Ok(vec!["Failed to read error log.".to_string()])
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
    manager.base_path().join("data").join("telemetry_optout.flag")
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
        std::fs::write(&flag, b"")
            .map_err(|e| format!("Failed to disable telemetry: {}", e))?;
    }
    Ok(())
}

#[tauri::command]
fn get_ws_token(state: State<AppState>) -> Result<String, String> {
    let manager = lock_bot_manager!(state)?;
    let env_path = manager.base_path().join(".env");
    if !env_path.exists() {
		return Ok(std::env::var("DASHBOARD_WS_TOKEN").unwrap_or_default());
    }
    Ok(
        read_dotenv_value(&env_path, "DASHBOARD_WS_TOKEN")
            .or_else(|| std::env::var("DASHBOARD_WS_TOKEN").ok())
            .unwrap_or_default(),
    )
}

fn normalize_ws_connect_host(host: &str) -> String {
    match host.trim() {
        "" | "0.0.0.0" | "::" | "[::]" | "::1" | "[::1]" => "localhost".to_string(),
        value => value.to_string(),
    }
}

fn env_flag_is_truthy(value: Option<String>) -> bool {
    value
        .map(|raw| matches!(raw.trim().to_ascii_lowercase().as_str(), "1" | "true" | "yes" | "on"))
        .unwrap_or(false)
}

#[tauri::command]
fn get_ws_endpoint(state: State<AppState>) -> Result<String, String> {
    let manager = lock_bot_manager!(state)?;
    let env_path = manager.base_path().join(".env");

    let ws_host = read_dotenv_value(&env_path, "WS_DASHBOARD_HOST")
        .or_else(|| std::env::var("WS_DASHBOARD_HOST").ok())
        .unwrap_or_else(|| "127.0.0.1".to_string());
    let ws_port = read_dotenv_value(&env_path, "WS_DASHBOARD_PORT")
        .or_else(|| std::env::var("WS_DASHBOARD_PORT").ok())
        .filter(|value| !value.trim().is_empty())
        .unwrap_or_else(|| "8765".to_string());
    let ws_require_tls = env_flag_is_truthy(
        read_dotenv_value(&env_path, "WS_REQUIRE_TLS")
            .or_else(|| std::env::var("WS_REQUIRE_TLS").ok()),
    );
    let ws_scheme = if ws_require_tls { "wss" } else { "ws" };

    Ok(format!(
        "{}://{}:{}/ws",
        ws_scheme,
        normalize_ws_connect_host(&ws_host),
        ws_port.trim(),
    ))
}

/// Read a single key from a .env file without requiring AppState.
fn read_dotenv_value(env_path: &std::path::Path, key: &str) -> Option<String> {
    let content = std::fs::read_to_string(env_path).ok()?;
    let prefix = format!("{}=", key);
    for line in content.lines() {
        let line = line.trim();
        if let Some(val) = line.strip_prefix(&prefix) {
            let val = val.trim().trim_matches('"').trim_matches('\'');
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

/// Resolve production base path by checking saved config and common locations.
fn resolve_production_base_path(exe_path: &Option<std::path::PathBuf>) -> std::path::PathBuf {
    // 1. Check saved config from a previous successful run
    let config_path = get_config_path();
    if let Ok(saved) = std::fs::read_to_string(&config_path) {
        let saved_path = std::path::PathBuf::from(saved.trim());
        if saved_path.join("bot.py").exists() {
            return saved_path;
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

fn main() {
    // Base path for the bot files - use BOT_BASE_PATH env var or default
    let base_path = std::env::var("BOT_BASE_PATH")
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|_| {
            // Check if we're in dev mode (executable is in target/debug or target/release)
            let exe_path = std::env::current_exe().ok();
            let is_dev = exe_path.as_ref()
                .and_then(|p| p.to_str())
                .map(|s| s.contains("target\\debug") || s.contains("target\\release") || s.contains("target/debug") || s.contains("target/release"))
                .unwrap_or(false);
            
            if is_dev {
                // Dev mode: go up from native_dashboard/target/debug to BOT folder
                exe_path
                    .and_then(|p| p.parent().map(|p| p.to_path_buf())) // debug/
                    .and_then(|p| p.parent().map(|p| p.to_path_buf())) // target/
                    .and_then(|p| p.parent().map(|p| p.to_path_buf())) // native_dashboard/
                    .and_then(|p| p.parent().map(|p| p.to_path_buf())) // BOT/
                    .unwrap_or_else(|| {
                        eprintln!("WARNING: Could not determine bot base path, using current directory");
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
                && dsn.split('/').nth(2)  // Extract host from https://HOST/...
                    .is_some_and(|host| {
                        let host_part = host.split('@').next_back().unwrap_or(host);
                        host_part.ends_with(".sentry.io") || host_part.ends_with(".sentry.io:")
                    })
        })
        .map(|dsn| {
            sentry::init((dsn, sentry::ClientOptions {
                release: sentry::release_name!(),
                ..Default::default()
            }))
        });

    let bot_manager = BotManager::new(base_path.clone());
    let db_service = DatabaseService::new(base_path.join("data").join("bot_database.db"));

    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(AppState {
            bot_manager: Arc::new(Mutex::new(bot_manager)),
            db_service: Mutex::new(db_service),
            frontend_error_rate: Mutex::new((0, 0)),
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
                .icon(app.default_window_icon()
                    .ok_or("Default window icon not configured in tauri.conf.json")?
                    .clone())
                .menu(&menu)
                .show_menu_on_left_click(false)
                .tooltip("디스코드 봇 대시보드")
                .on_menu_event(|app, event| {
                    match event.id.as_ref() {
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
                    }
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
                use tauri_plugin_dialog::{DialogExt, MessageDialogKind, MessageDialogButtons};
                
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
        assert_eq!(read_dotenv_value(&path, "TOKEN"), Some("wrapped-in-double".to_string()));
        assert_eq!(read_dotenv_value(&path, "TOKEN2"), Some("single-quoted".to_string()));
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
}
