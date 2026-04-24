// =============================================================================
// NOTE: cargo build --release only produces bot-dashboard.exe
// The Korean-named exe (디스코드 봇 대시보드.exe) is a COPY, not a separate build.
// After building, ALWAYS run the post-build copy:
//
//   Option 1: Use the build scripts (recommended):
//     .\scripts\build-release.ps1    (builds + copies both exes)
//     .\scripts\build-tauri.ps1      (builds + copies + creates installer)
//
//   Option 2: Manual copy after cargo build:
//     Copy-Item target\release\bot-dashboard.exe "target\release\디스코드 봇 대시보드.exe"
//     Copy-Item target\release\bot-dashboard.exe ..\bot-dashboard.exe
//     Copy-Item target\release\bot-dashboard.exe "..\디스코드 봇 대시보드.exe"
//
// NEVER deploy only one exe — both must be updated together.
// =============================================================================

fn main() {
    tauri_build::build();
}
