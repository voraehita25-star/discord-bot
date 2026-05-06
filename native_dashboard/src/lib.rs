// bot_manager.rs uses Windows-only APIs (CommandExt::creation_flags, taskkill).
// Only expose it on Windows so CI builds on Linux can still type-check the rest.
#[cfg(target_os = "windows")]
pub mod bot_manager;
pub mod database;
