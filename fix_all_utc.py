import os
import re

def fix_utc_imports(directory):
    for root, _, files in os.walk(directory):
        if '.venv' in root or 'tests' in root or 'node_modules' in root or '.git' in root:
            continue
        for file in files:
            if file.endswith('.py'):
                filepath = os.path.join(root, file)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    if 'from datetime import timezone' in content or 'timezone.utc' in content or 'from datetime import datetime, timezone' in content:
                        content = content.replace('from datetime import datetime, timezone', 'from datetime import datetime, timezone')
                        content = content.replace('from datetime import datetime, timezone', 'from datetime import datetime, timezone')
                        content = content.replace('from datetime import timezone', 'from datetime import timezone')
                        content = content.replace('timezone.utc', 'timezone.utc')
                        content = content.replace('timezone.utc', 'timezone.utc')
                        
                        with open(filepath, 'w', encoding='utf-8') as f:
                            f.write(content)
                        print(f'Fixed timezone.utc in {filepath}')
                except Exception as e:
                    pass

fix_utc_imports('.')
