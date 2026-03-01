import os
import re

def fix_test(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # We need to add patch for os.environ
    content = content.replace('with patch("cogs.ai_core.api.dashboard_chat.DB_AVAILABLE", False):', 'with patch("cogs.ai_core.api.dashboard_chat.DB_AVAILABLE", False), patch.dict(os.environ, {"DASHBOARD_ALLOW_UNRESTRICTED": "1"}):')
    
    # Add import os if not there
    if 'import os' not in content:
        content = 'import os\n' + content
        
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

fix_test('tests/test_dashboard_chat.py')
