"""Rough static count of HTTP endpoints (method + route) in FastAPI/Flask and Django REST code."""
import ast, re, sys, pathlib, collections
HTTP = {'get','post','put','patch','delete'}
VS = {'ModelViewSet':6,'ReadOnlyModelViewSet':2}
MIX = {'ListModelMixin':1,'CreateModelMixin':1,'RetrieveModelMixin':1,'UpdateModelMixin':2,'DestroyModelMixin':1}
GEN = {'ListAPIView':1,'CreateAPIView':1,'RetrieveAPIView':1,'DestroyAPIView':1,'UpdateAPIView':2,'ListCreateAPIView':2,
       'RetrieveUpdateAPIView':3,'RetrieveDestroyAPIView':2,'RetrieveUpdateDestroyAPIView':4}
SKIP = re.compile(r'/(\.venv|venv|env|site-packages|node_modules|migrations|tests?)/')
def bname(b):
    return b.attr if isinstance(b, ast.Attribute) else getattr(b, 'id', '')
def scan(root):
    classes, fastapi, router_regs, paths, api_views = {}, 0, [], [], 0
    for f in pathlib.Path(root).rglob('*.py'):
        if SKIP.search(str(f)): continue
        try: t = ast.parse(f.read_text(errors='ignore'))
        except Exception: continue
        for n in ast.walk(t):
            if isinstance(n, ast.ClassDef):
                classes[n.name] = n
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for d in n.decorator_list:
                    if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute):
                        a = d.func.attr
                        if a in HTTP or a == 'api_route': fastapi += 1
                        elif a == 'route':
                            m = [k for k in d.keywords if k.arg == 'methods']
                            fastapi += len(m[0].value.elts) if m and isinstance(m[0].value, ast.List) else 1
                    if isinstance(d, ast.Call) and bname(d.func) == 'api_view':
                        api_views += len(d.args[0].elts) if d.args and isinstance(d.args[0], ast.List) else 1
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'register' and len(n.args) >= 2:
                router_regs.append(bname(n.args[1]))
            if isinstance(n, ast.Call) and bname(n.func) in ('path','re_path') and len(n.args) >= 2:
                v = n.args[1]
                if isinstance(v, ast.Call) and isinstance(v.func, ast.Attribute) and v.func.attr == 'as_view':
                    paths.append(bname(v.func.value))
    def vs_count(name, seen=()):
        c = classes.get(name)
        if not c or name in seen: return VS.get(name, 0) + MIX.get(name, 0)
        total = 0
        for b in c.bases:
            bn = bname(b)
            total += VS.get(bn) or MIX.get(bn) or (vs_count(bn, seen + (name,)) if bn in classes else 0)
        for item in c.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(bname(d.func if isinstance(d, ast.Call) else d) == 'action' for d in item.decorator_list):
                total += 1
        return total
    def view_count(name):
        c = classes.get(name)
        if not c: return 1
        n = sum(GEN.get(bname(b), 0) for b in c.bases)
        if n: return n
        if any(bname(b) in VS or bname(b) in MIX or bname(b).endswith('ViewSet') for b in c.bases): return vs_count(name)
        m = sum(1 for i in c.body if isinstance(i, (ast.FunctionDef, ast.AsyncFunctionDef)) and i.name in HTTP)
        return m or 1
    drf = sum(vs_count(r) for r in router_regs) + sum(view_count(p) for p in paths) + api_views
    return fastapi, drf
if __name__ == '__main__':
    rows = []
    for d in sys.argv[1:]:
        fa, dj = scan(d)
        if fa or dj: rows.append((fa + dj, fa, dj, pathlib.Path(d).name))
    for r in sorted(rows, reverse=True): print(*r, sep='\t')
    print('TOTAL', sum(r[0] for r in rows), 'repos', len(rows))
