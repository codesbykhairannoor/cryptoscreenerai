import ast

def find_undefined_names(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        tree = ast.parse(f.read())

    defined_names = set()
    used_names = set()

    # Get all globally defined names
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    defined_names.add(target.id)
        elif isinstance(node, ast.FunctionDef):
            defined_names.add(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                defined_names.add(alias.name or alias.asname)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                defined_names.add(alias.asname or alias.name)

    # Add common built-ins
    defined_names.update(['print', 'len', 'range', 'round', 'float', 'int', 'str', 'list', 'dict', 'set', 'tuple', 'Exception', 'enumerate', 'abs', 'min', 'max', 'sum', 'sorted', 'bool', 'True', 'False', 'None', 'getattr', 'setattr', 'hasattr', 'id', 'open', 'type', 'isinstance', 'vars', 'super', 'map', 'filter', 'all', 'any', 'zip'])

    # Find used but undefined names
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if node.id not in defined_names:
                used_names.add(node.id)

    return used_names

if __name__ == "__main__":
    undefined = find_undefined_names(r'd:\cryptoscreenerai-main\cryptoscreenerai-main\backend\crypto_engine.py')
    print("UNDEFINED NAMES FOUND:")
    for name in sorted(undefined):
        print(f"- {name}")
