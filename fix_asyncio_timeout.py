import re

files = [
    'cogs/ai_core/core/message_queue.py',
    'cogs/ai_core/api/dashboard_chat.py',
    'utils/reliability/shutdown_manager.py',
    'utils/web/url_fetcher.py'
]

for filepath in files:
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Replace except TimeoutError with except asyncio.TimeoutError
        content = content.replace('except TimeoutError:', 'except asyncio.TimeoutError:')
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Fixed {filepath}")
    except Exception as e:
        print(f"Error fixing {filepath}: {e}")
