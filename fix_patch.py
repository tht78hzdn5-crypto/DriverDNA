with open('db_patch4.py', 'r') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if line.strip().startswith('r"'):
        lines[i] = line.replace('"""', '\\"\\"\\"')
    elif line.strip().startswith("r'"):
        lines[i] = line.replace('"""', '\\"\\"\\"')

with open('db_patch4.py', 'w') as f:
    f.writelines(lines)
