import os, pathlib, tempfile
os.environ.setdefault('STATS_TOKEN', 'x')
os.environ.setdefault('STATS_AUTHORS', 'me@example.com')
from stats import short
from endpoints import scan

assert [short(n) for n in (999, 2655, 205195)] == ['999', '2.6k+', '205k+']

with tempfile.TemporaryDirectory() as d:
    pathlib.Path(d, 'api.py').write_text(
        'from fastapi import APIRouter\nrouter = APIRouter()\n'
        '@router.get("/a")\ndef a(): ...\n@router.post("/a")\ndef b(): ...\n')
    pathlib.Path(d, 'urls.py').write_text(
        'from rest_framework import viewsets, routers\n'
        'class BookViewSet(viewsets.ModelViewSet):\n    pass\n'
        'router = routers.DefaultRouter()\nrouter.register("books", BookViewSet)\n')
    assert scan(d) == (2, 6), scan(d)
print('ok')
