import re

files_to_fix = [
    ('cogs/ai_core/logic.py', [
        (r'from \.processing\.intent_detector import Intent, detect_intent', r'from .processing.intent_detector import Intent, detect_intent  # noqa: F401'),
        (r'from \.cache\.analytics import get_ai_stats, log_ai_interaction', r'from .cache.analytics import get_ai_stats, log_ai_interaction  # noqa: F401'),
        (r'from \.cache\.ai_cache import ai_cache, context_hasher', r'from .cache.ai_cache import ai_cache, context_hasher  # noqa: F401'),
        (r'from \.memory\.history_manager import history_manager', r'from .memory.history_manager import history_manager  # noqa: F401'),
    ]),
    ('cogs/spotify_handler.py', [
        (r'raise ConnectionError\("Spotify client recreation failed"\)', r'raise ConnectionError("Spotify client recreation failed") from None'),
    ]),
    ('scripts/bot_manager.py', [
        (r'shell=False,', r'shell=False,\n        check=False,'),
    ]),
    ('scripts/dev_watcher.py', [
        (r'shell=False,', r'shell=False,\n        check=False,'),
    ])
]

for filepath, replacements in files_to_fix:
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        for old, new in replacements:
            content = re.sub(old, new, content)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f'Fixed {filepath}')
    except Exception as e:
        print(f'Error fixing {filepath}: {e}')

