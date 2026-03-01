import re

def fix_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Replace 'from datetime import datetime, timezone' with 'from datetime import datetime, timezone'
        content = content.replace('from datetime import datetime, timezone', 'from datetime import datetime, timezone')
        content = content.replace('from datetime import datetime, timezone', 'from datetime import datetime, timezone')
        
        # Replace 'datetime.now(timezone.utc)' with 'datetime.now(timezone.utc)'
        content = content.replace('datetime.now(timezone.utc)', 'datetime.now(timezone.utc)')
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Fixed {filepath}")
    except Exception as e:
        print(f"Error fixing {filepath}: {e}")

fix_file('utils/monitoring/structured_logger.py')
fix_file('cogs/ai_core/api/ws_dashboard.py')
