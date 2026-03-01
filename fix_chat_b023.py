import re

def fix_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Let's fix the nonlocal variables in _iter_with_idle_timeout
    old_def = r'async def _iter_with_idle_timeout\(\):\n\s+\"\"\"Wrap async iterator with per-chunk idle timeout\.\"\"\"\n\s+nonlocal _first_chunk_time, _idle_timeout_hit'
    new_def = r'async def _iter_with_idle_timeout\(\):\n                \"\"\"Wrap async iterator with per-chunk idle timeout\.\"\"\"\n                nonlocal _first_chunk_time, _idle_timeout_hit, stream, _stream_start, chunks_count'
    
    content = re.sub(old_def, new_def, content)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

fix_file('cogs/ai_core/api/dashboard_chat.py')
