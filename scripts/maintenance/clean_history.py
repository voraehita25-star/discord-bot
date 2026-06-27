"""
Script to clean empty AI responses from JSON history files.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

# Resolve DATA_DIR relative to THIS file rather than the caller's CWD.
# `Path("data")` was relative-to-CWD, so running the script from a
# different directory silently operated on the wrong (or no) files.
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


def clean_history_files() -> None:
    """Iterate through history files and remove empty model responses."""
    files = list(DATA_DIR.glob("ai_history_*.json"))
    total_removed: int = 0
    files_affected: int = 0

    print(f"Found {len(files)} history files.")

    for filepath in files:
        changed = False
        try:
            history = json.loads(filepath.read_text(encoding="utf-8"))

            # Structural guard: a corrupt file whose top-level JSON isn't a list
            # would make `for item in history` / item.get raise an uncaught
            # TypeError/AttributeError that aborts the whole run. Skip just it.
            if not isinstance(history, list):
                print(f"Skipping {filepath}: top-level JSON is not a list.")
                continue

            new_history = []
            for item in history:
                # Non-dict element (corrupt entry) — preserve verbatim, don't crash.
                if not isinstance(item, dict):
                    new_history.append(item)
                    continue
                # Check criteria: role is 'model' AND parts is essentially empty
                if item.get("role") == "model":
                    parts = item.get("parts", [])
                    is_empty = True

                    if parts:
                        for part in parts:
                            text = ""
                            if isinstance(part, str):
                                text = part
                            elif isinstance(part, dict) and "text" in part:
                                text = part["text"] if isinstance(part["text"], str) else ""

                            # If we find any text that isn't whitespace, it's not empty
                            if text and text.strip():
                                is_empty = False
                                break
                    else:
                        is_empty = True  # parts is empty list

                    if is_empty:
                        # Found an empty model message, skip it (remove)
                        changed = True
                        continue

                # Keep the item
                new_history.append(item)

            if changed:
                removed_count = len(history) - len(new_history)
                total_removed += removed_count
                files_affected += 1

                # Make a sidecar backup of the original before rewriting —
                # the atomic-replace below is crash-safe but doesn't help
                # if the cleaning logic itself was buggy. Use a
                # timestamped suffix so consecutive runs don't clobber
                # each other's backups (the previous `.bak` overwrote the
                # last clean copy on every re-run).
                try:
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    bak_path = filepath.with_suffix(f"{filepath.suffix}.{ts}.bak")
                    bak_path.write_bytes(filepath.read_bytes())
                except OSError as e:
                    print(f"Warning: could not back up {filepath}: {e}")

                # Atomic write: tmp file + os.replace so a crash mid-write
                # can never corrupt an existing history file.
                tmp_path = filepath.with_suffix(filepath.suffix + ".tmp")
                try:
                    tmp_path.write_text(
                        json.dumps(new_history, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    tmp_path.replace(filepath)
                except Exception:
                    try:
                        tmp_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                    raise

                print(f"Cleaned {filepath}: Removed {removed_count} empty messages.")

        # Tolerate write-path errors per-file too: the atomic-write block
        # re-raises any non-OSError (e.g. TypeError from json.dumps on a
        # non-serializable value, or UnicodeEncodeError). Without TypeError/
        # ValueError here, one such file would abort the whole run and skip
        # every remaining file plus the final summary.
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as e:
            print(f"Error processing {filepath}: {e}")

    print(f"Done. Removed {total_removed} messages across {files_affected} files.")


if __name__ == "__main__":
    clean_history_files()
