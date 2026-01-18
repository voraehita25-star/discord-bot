"""
Script to clean empty AI responses from JSON history files.
"""

from __future__ import annotations

import json
from pathlib import Path

DATA_DIR = Path("data")


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

            new_history = []
            for item in history:
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
                                text = part["text"]

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

                # Write back
                filepath.write_text(
                    json.dumps(new_history, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

                print(f"Cleaned {filepath}: Removed {removed_count} empty messages.")

        except (OSError, json.JSONDecodeError) as e:
            print(f"Error processing {filepath}: {e}")

    print(f"Done. Removed {total_removed} messages across {files_affected} files.")


if __name__ == "__main__":
    clean_history_files()
