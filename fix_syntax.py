import re

def fix_file(filepath, replacements):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    for old, new in replacements:
        content = re.sub(old, new, content)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

fix_file('cogs/spotify_handler.py', [
    (r'raise ConnectionError\("Spotify client recreation failed"\) from None from None', r'raise ConnectionError("Spotify client recreation failed") from None'),
])

fix_file('scripts/bot_manager.py', [
    (r'check=False,\n\s*check=False,', r'check=False,'),
    (r'check=False,\n\s*check=False, cwd=', r'check=False, cwd='),
])

fix_file('scripts/dev_watcher.py', [
    (r'check=False,\n\s*check=False,', r'check=False,'),
])
