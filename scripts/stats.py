"""Collect profile stats from all my repositories and render assets/numbers.svg.

Env:
  STATS_TOKEN    GitHub token that can read every repo to include (required)
  STATS_AUTHORS  comma-separated author emails/names that are me (required)
  STATS_EXCLUDE  comma-separated repo names to skip (optional)
  STATS_WORKDIR  where to clone (optional, default: a temp dir)
"""
import base64, datetime as dt, json, os, pathlib, re, subprocess, sys, tempfile, urllib.request, warnings

warnings.simplefilter('ignore', SyntaxWarning)  # other people's code we parse may have bad escapes

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from endpoints import scan as scan_endpoints

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOKEN = os.environ['STATS_TOKEN']
AUTHORS = [a.strip() for a in os.environ['STATS_AUTHORS'].split(',') if a.strip()]
EXCLUDE = {x.strip() for x in os.environ.get('STATS_EXCLUDE', '').split(',') if x.strip()}

CODE_EXT = {'.py', '.js', '.jsx', '.ts', '.tsx', '.go', '.swift', '.kt', '.java', '.gd', '.sh', '.sql',
            '.html', '.css', '.scss', '.vue', '.rb', '.rs', '.c', '.cc', '.cpp', '.h', '.mjs', '.cjs'}
SKIP_PATH = re.compile(r'(^|/)(node_modules|vendor|dist|build|migrations|\.venv|venv|site-packages|static/vendor)/'
                       r'|\.min\.(js|css)$|(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|poetry\.lock)$')
BULK = 3000  # ponytail: a file over 3k lines is treated as generated/vendored and skipped


def api(url, data=None):
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data else None,
                                 headers={'Authorization': f'Bearer {TOKEN}', 'Accept': 'application/vnd.github+json'})
    return json.load(urllib.request.urlopen(req, timeout=60))


def list_repos():
    repos, page = [], 1
    while True:
        batch = api(f'https://api.github.com/user/repos?per_page=100&page={page}'
                    '&affiliation=owner,collaborator,organization_member')
        repos += batch
        if len(batch) < 100:
            break
        page += 1
    return [r for r in repos if not r['fork'] and r['name'] not in EXCLUDE and r['size'] > 0]


def git_env():
    # The token goes through git config env vars, never argv or the clone URL.
    auth = base64.b64encode(f'x-access-token:{TOKEN}'.encode()).decode()
    return {**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GIT_CONFIG_COUNT': '1',
            'GIT_CONFIG_KEY_0': 'http.https://github.com/.extraheader',
            'GIT_CONFIG_VALUE_0': f'AUTHORIZATION: basic {auth}'}


def main_branch(repo_dir):
    """The branch with the most files. Some projects live on develop, others keep stale feature branches."""
    refs = subprocess.run(['git', '-C', str(repo_dir), 'for-each-ref', '--format=%(refname:lstrip=3)', 'refs/remotes/origin'],
                          capture_output=True, text=True).stdout.split()
    size = lambda ref: len(subprocess.run(['git', '-C', str(repo_dir), 'ls-tree', '-r', '--name-only', f'origin/{ref}'],
                                          capture_output=True, text=True).stdout.splitlines())
    refs = [r for r in refs if r != 'HEAD']
    return max(refs, key=size) if refs else None


def commits(repo_dir):
    args = ['git', '-C', str(repo_dir), 'log', '--all', '--no-merges', '--format=%H'] + [f'--author={a}' for a in AUTHORS]
    return set(subprocess.run(args, capture_output=True, text=True).stdout.split())


def owned_lines(repo_dir, seen_blobs):
    """Lines in the current code whose last author (git blame) is me. Identical files across repos count once."""
    tree = subprocess.run(['git', '-C', str(repo_dir), 'ls-tree', '-r', 'HEAD'], capture_output=True, text=True).stdout
    mine = re.compile('|'.join(re.escape(a) for a in AUTHORS))
    total = 0
    for row in tree.splitlines():
        meta, path = row.split('\t', 1)
        blob = meta.split()[2]
        if (pathlib.PurePath(path).suffix.lower() not in CODE_EXT or SKIP_PATH.search(path) or blob in seen_blobs):
            continue
        seen_blobs.add(blob)
        out = subprocess.run(['git', '-C', str(repo_dir), 'blame', '--line-porcelain', 'HEAD', '--', path],
                             capture_output=True, text=True, errors='ignore').stdout
        heads = [l for l in out.splitlines() if l.startswith(('author ', 'author-mail '))]
        if len(heads) > 2 * BULK:
            continue
        total += sum(1 for name, mail in zip(heads[::2], heads[1::2]) if mine.search(name) or mine.search(mail))
    return total


def contributions():
    q = 'query{user(login:"%s"){contributionsCollection{contributionYears}}}'
    login = api('https://api.github.com/user')['login']
    years = api('https://api.github.com/graphql', {'query': q % login})['data']['user']['contributionsCollection']['contributionYears']
    parts = ' '.join(f'y{y}: contributionsCollection(from:"{y}-01-01T00:00:00Z", to:"{y}-12-31T23:59:59Z")'
                     '{contributionCalendar{totalContributions}}' for y in years)
    data = api('https://api.github.com/graphql', {'query': 'query{user(login:"%s"){%s}}' % (login, parts)})['data']['user']
    return sum(v['contributionCalendar']['totalContributions'] for v in data.values()), min(years)


def short(n):
    if n < 1000:
        return f'{n}'
    if n < 10_000:
        return f'{n // 100 / 10:g}k+'
    return f'{n // 1000}k+'


def render(stats):
    font = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"
    mono = 'ui-monospace,SFMono-Regular,Menlo,Consolas,monospace'
    cells = [(short(stats['lines']), 'lines of code', 'authored by me, live code'),
             (short(stats['commits']), 'commits', f"in {stats['repos_touched']} repositories"),
             (f"~{stats['endpoints'] // 10 * 10}", 'API endpoints', f"across {stats['endpoint_projects']} projects"),
             (short(stats['contributions']), 'contributions', f"on GitHub since {stats['since']}")]
    # Own dark card, so the text stays readable on GitHub's light theme too.
    body = ('<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0b1222"/>'
            '<stop offset="1" stop-color="#121f3a"/></linearGradient></defs><rect width="1000" height="138" rx="18" fill="url(#bg)"/>')
    for i, (num, label, sub) in enumerate(cells):
        x = i * 250
        if i:
            body += f'<line x1="{x}" y1="26" x2="{x}" y2="104" stroke="#2a3a5c"/>'
        body += (f'<text x="{x + 125}" y="58" text-anchor="middle" class="t" font-size="34" font-weight="800" fill="#e8edf7">{num}</text>'
                 f'<text x="{x + 125}" y="84" text-anchor="middle" class="t" font-size="14.5" font-weight="600" fill="#9fb0d0">{label}</text>'
                 f'<text x="{x + 125}" y="104" text-anchor="middle" class="m" font-size="11.5" fill="#6d7d9e">{sub}</text>')
    body += (f'<text x="980" y="126" text-anchor="end" class="m" font-size="10" fill="#4f5d7a">'
             f"auto-updated {stats['updated']}</text>")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 138" width="1000" height="138">'
            f'<style>.t{{font-family:{font}}}.m{{font-family:{mono}}}</style>{body}</svg>')


def main():
    work = pathlib.Path(os.environ.get('STATS_WORKDIR') or tempfile.mkdtemp())
    env = git_env()
    lines, shas, touched, endpoints, ep_projects, seen_blobs = 0, set(), 0, 0, 0, set()
    for r in list_repos():
        d = work / r['full_name'].replace('/', '__')
        if d.exists():
            subprocess.run(['git', '-C', str(d), 'fetch', '-q', '--all'], env=env, capture_output=True)
        else:
            res = subprocess.run(['git', 'clone', '-q', r['clone_url'], str(d)], env=env, capture_output=True, text=True)
            if res.returncode:
                print(f"skip {r['name']}: clone failed", file=sys.stderr)
                continue
        branch = main_branch(d)
        if branch:
            subprocess.run(['git', '-C', str(d), 'checkout', '-q', '-B', branch, f'origin/{branch}'], capture_output=True)
        s = commits(d)
        shas |= s
        touched += bool(s)
        lines += owned_lines(d, seen_blobs)
        fa, dj = scan_endpoints(d)
        endpoints += fa + dj
        ep_projects += bool(fa + dj)
    total, since = contributions()
    stats = {'lines': lines, 'commits': len(shas), 'repos_touched': touched, 'endpoints': endpoints,
             'endpoint_projects': ep_projects, 'contributions': total, 'since': since}
    out = ROOT / 'stats.json'
    old = json.loads(out.read_text()) if out.exists() else {}
    if {k: v for k, v in old.items() if k != 'updated'} == stats:
        print('no changes')
        return
    stats['updated'] = dt.date.today().isoformat()
    (ROOT / 'assets').mkdir(exist_ok=True)
    (ROOT / 'assets' / 'numbers.svg').write_text(render(stats))
    out.write_text(json.dumps(stats, indent=2) + '\n')
    print(json.dumps(stats))


if __name__ == '__main__':
    main()
