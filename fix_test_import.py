import os
import re

filepath = 'tests/test_dashboard_chat.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# Remove the import os added in the middle of the file
content = content.replace('import os\n', '', 1)

# Add it after from __future__ import annotations if it exists
if 'from __future__ import annotations' in content:
    content = content.replace('from __future__ import annotations', 'from __future__ import annotations\nimport os')
else:
    content = 'import os\n' + content

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
