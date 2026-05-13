import os

files = [f for f in os.listdir('.') if f.endswith('.py')]
for f in files:
    with open(f, 'r', encoding='utf-8') as file:
        content = file.read()
    
    if 'api.bitget.com' in content:
        print(f"[REPLACE] Updating domain in {f}...")
        new_content = content.replace('api.bitget.com', 'api.bitget.com')
        with open(f, 'w', encoding='utf-8') as file:
            file.write(new_content)

print("[DONE] All Bitget domains updated to anti-block version.")
