import re

filepath = 'cogs/ai_core/api/ws_dashboard.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace('tz=UTC', 'tz=timezone.utc')

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
