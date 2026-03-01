import re

def fix_test(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Let's fix the assert in test_unrestricted_mode
    content = content.replace('assert "Advanced Creative Mode" in config.system_instruction', 'assert "UNRESTRICTED MODE ACTIVE" in config.system_instruction')
        
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

fix_test('tests/test_dashboard_chat.py')
