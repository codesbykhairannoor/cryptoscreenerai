import ast

def get_undefined_globals(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()
    
    tree = ast.parse(content)
    
    # Names defined at the top level
    globals_defined = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    globals_defined.add(target.id)
        elif isinstance(node, ast.FunctionDef):
            globals_defined.add(node.name)
        elif isinstance(node, ast.ClassDef):
            globals_defined.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                globals_defined.add(alias.asname or alias.name)

    # Built-ins
    globals_defined.update(['print', 'len', 'range', 'round', 'float', 'int', 'str', 'list', 'dict', 'set', 'tuple', 'Exception', 'enumerate', 'abs', 'min', 'max', 'sum', 'sorted', 'bool', 'True', 'False', 'None', 'getattr', 'setattr', 'hasattr', 'id', 'open', 'type', 'isinstance', 'vars', 'super', 'map', 'filter', 'all', 'any', 'zip', 'round', 'pow', 'repr', 'reversed', 'format', 'hash', 'next', 'iter', 'callable', 'property', 'staticmethod', 'classmethod'])

    undefined_globals = set()

    class NameVisitor(ast.NodeVisitor):
        def __init__(self):
            self.scopes = [globals_defined.copy()]

        def visit_FunctionDef(self, node):
            # Add args to local scope
            local_scope = set()
            for arg in node.args.args:
                local_scope.add(arg.arg)
            if node.args.vararg:
                local_scope.add(node.args.vararg.arg)
            if node.args.kwarg:
                local_scope.add(node.args.kwarg.arg)
            
            # Add locally assigned names
            for subnode in ast.walk(node):
                if isinstance(subnode, ast.Assign):
                    for target in subnode.targets:
                        if isinstance(target, ast.Name):
                            local_scope.add(target.id)
                elif isinstance(subnode, (ast.For, ast.With)):
                    # Simplify: things in for loops or with statements are local
                    for target in ast.walk(subnode):
                        if isinstance(target, ast.Name) and isinstance(target.ctx, ast.Store):
                            local_scope.add(target.id)

            self.scopes.append(local_scope)
            self.generic_visit(node)
            self.scopes.pop()

        def visit_Name(self, node):
            if isinstance(node.ctx, ast.Load):
                # Check if name is in any current scope
                if not any(node.id in scope for scope in self.scopes):
                    undefined_globals.add(node.id)

    visitor = NameVisitor()
    visitor.visit(tree)
    return undefined_globals

if __name__ == "__main__":
    undefined = get_undefined_globals(r'd:\cryptoscreenerai-main\cryptoscreenerai-main\backend\crypto_engine.py')
    print("REALLY UNDEFINED NAMES:")
    for name in sorted(undefined):
        print(f"- {name}")



