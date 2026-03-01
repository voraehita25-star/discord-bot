import re

def fix_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Fix B904
    content = re.sub(
        r'raise TimeoutError\(\n\s+f\"Idle timeout: no chunk for \{chunk_idle_timeout\}s \"\n\s+f\"\(chunks=\{chunks_count\}, elapsed=\{_elapsed:\.1f\}s\)\"\n\s+\)',
        r'raise TimeoutError(\n                                f"Idle timeout: no chunk for {chunk_idle_timeout}s "\n                                f"(chunks={chunks_count}, elapsed={_elapsed:.1f}s)"\n                            ) from None',
        content
    )
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

fix_file('cogs/ai_core/api/dashboard_chat.py')
