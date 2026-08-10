with open('src/driverdna/db.py', 'r') as f:
    lines = f.readlines()
for i in range(max(0, 938 - 100), min(len(lines), 938 + 10)):
    if '"""' in lines[i]:
        print(f"{i+1}: {lines[i].strip()}")
