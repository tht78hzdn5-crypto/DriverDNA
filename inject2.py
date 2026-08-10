import os

with open('src/driverdna/db.py', 'r') as f:
    lines = f.readlines()

mig = ""
with open('migration008.txt', 'r') as f:
    mig = f.read()

for i, l in enumerate(lines):
    if l.startswith(')'):
        lines.insert(i, '    """\n' + mig + '    """,\n')
        break

with open('src/driverdna/db.py', 'w') as f:
    f.writelines(lines)
