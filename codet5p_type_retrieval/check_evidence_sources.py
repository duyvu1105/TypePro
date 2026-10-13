"""Repeat evidence checks on pinned upstream target/dependency source files.

Use --manifest with a prior report to reuse its exact Git revisions. This does
not check an entire repository, a historical Dataset checkout, or model accuracy.
Downloaded project code is parsed, never imported or executed.
"""
from __future__ import annotations
import argparse
import ast
import copy
import hashlib
import json
import sys
import tempfile
import urllib.request
from pathlib import Path

from check_evidence_regressions import CASES, replay, implementation_fingerprint

SOURCE_PATHS = {
    'workshop_range': ('python_workshop/types/t03_ducktypes.py', []),
    'workshop_newtype': ('python_workshop/types/t07_newtype.py', []),
    'foolbox_tuple_alias': ('tests/test_models.py', []),
    'subhub_symlink': ('src/hub/vendor/customer.py', ['src/shared/vendor.py']),
    'mapping_constructor': ('main.py', []),
    'adventofcode_lambda': ('y2018/day03/day03.py', []),
    'nicecream_wildcards': ('api/database.py', ['api/views.py', 'api/schemas.py', 'api/auth.py']),
    'mort_documented_caller': ('mort/driver.py', ['mort/controller.py']),
    'superset_collection': ('superset/databases/utils.py', []),
}


def download(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'TypePro-evidence-regression'})
    return urllib.request.urlopen(request, timeout=30).read().decode('utf-8-sig')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--manifest', type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Python'))
    revisions = {}
    if args.manifest:
        for row in json.loads(args.manifest.read_text(encoding='utf-8'))['cases']:
            revisions[row.get('repository') or row['project']] = row['revision']
    rows = []
    with tempfile.TemporaryDirectory(prefix='typepro-upstream-evidence-') as temporary:
        for fixture in CASES:
            case = copy.deepcopy(fixture)
            repo = case['project']
            row = dict(id=case['id'], repository=repo)
            try:
                if repo not in revisions:
                    revisions[repo] = json.loads(download(f'https://api.github.com/repos/{repo}/commits/HEAD'))['sha']
                revision = revisions[repo]
                filename, extra = SOURCE_PATHS[case['id']]
                base = f'https://raw.githubusercontent.com/{repo}/{revision}/'
                case['sources'] = {name: download(base + name) for name in [filename, *extra]}
                case['file'] = filename
                if case.get('git_link'):
                    link, _ = case['git_link']
                    tree = json.loads(download(f'https://api.github.com/repos/{repo}/git/trees/{revision}?recursive=1'))['tree']
                    entry = next(n for n in tree if n['path'] == link)
                    if entry['mode'] != '120000':
                        raise ValueError('Expected a source-controlled symlink')
                    case['git_link'] = (link, download(base + link))
                if case['id'] == 'mort_documented_caller':
                    # This upstream revision calls submit_request from capture;
                    # the historical sample names its caller load_screenshots.
                    case['required'] = [('slice', 'Windows'), ('slice', 'targets: List[Dict]')]
                root = Path(temporary) / case['id']
                root.mkdir()
                result = replay(case, root, annotation='NotUsedForRetrieval')
                if case['id'] == 'mort_documented_caller':
                    original = next(n for n in ast.walk(ast.parse(case['sources'][filename]))
                                    if isinstance(n, ast.FunctionDef) and n.name == case['function'])
                    rendered = next(n for n in ast.walk(ast.parse(result['slice'].replace('<mask>', '__TYPEPRO_TARGET_MASK__')))
                                    if isinstance(n, ast.FunctionDef) and n.name == case['function'])
                    result['checks'].append(dict(where='slice', evidence='complete target docstring preserved',
                                                 passed=ast.get_docstring(original) == ast.get_docstring(rendered)))
                    result['passed'] = all(c['passed'] for c in result['checks'])
                row.update(result, revision=revision, repository=repo,
                           source_url=f'https://github.com/{repo}/blob/{revision}/{filename}',
                           source_sha256={name: hashlib.sha256(text.encode()).hexdigest() for name, text in case['sources'].items()},
                           status='passed' if result['passed'] else 'failed_evidence_check')
            except Exception as error:
                row.update(status='source_unavailable_or_changed', reason=f'{type(error).__name__}: {error}', passed=False)
            rows.append(row)
            print(json.dumps(dict(id=row['id'], status=row['status'], revision=row.get('revision'))), flush=True)
    report = dict(scope='pinned upstream target/dependency files only; no historical Dataset or model inference',
                  implementation_sha256=implementation_fingerprint(Path(__file__).resolve().parents[1] / 'Python'),
                  passed=sum(r['passed'] for r in rows), total=len(rows), cases=rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    return 0 if report['passed'] == report['total'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
