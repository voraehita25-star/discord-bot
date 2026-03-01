import re

def fix_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    content = content.replace('from None from None', 'from None')
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

fix_file('cogs/ai_core/api/dashboard_chat.py')
