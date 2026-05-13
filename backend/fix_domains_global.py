import os

# Scan all python files in backend and its subdirectories
root_dir = '.'
for root, dirs, files in os.walk(root_dir):
    for f in files:
        if f.endswith('.py'):
            file_path = os.path.join(root, f)
            with open(file_path, 'r', encoding='utf-8') as file:
                content = file.read()
            
            if 'api.bitget.com' in content:
                print(f"[REPLACE] Updating domain in {file_path}...")
                new_content = content.replace('api.bitget.com', 'api.bitget.com')
                with open(file_path, 'w', encoding='utf-8') as file:
                    file.write(new_content)

print("[DONE] Global Bitget domain update completed.")
