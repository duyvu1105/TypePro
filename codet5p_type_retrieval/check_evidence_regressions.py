"""Replay user-reported evidence losses; write slices and explicit checks.

Fixtures reproduce the supplied code patterns, not historical dataset checkouts
or model accuracy. --python-dir allows the same fixtures against an old snapshot.
"""
from __future__ import annotations
import argparse
import ast
import copy
import json
import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path


CASES = [
    dict(id='superset_collection', project='apache/incubator-superset', file='superset/databases/utils.py',
         function='get_foreign_keys_metadata', name='get_foreign_keys_metadata', scope='return',
         sources={'superset/databases/utils.py': '''def get_foreign_keys_metadata(database: Any, table: Table) -> HiddenGold:
    foreign_keys = database.get_foreign_keys(table)
    for fk in foreign_keys:
        fk['column_names'] = fk.pop('constrained_columns')
        fk['type'] = 'fk'
    return foreign_keys
'''}, required=[('slice', 'for fk in foreign_keys:'), ('slice', "fk['column_names'] = fk.pop('constrained_columns')"), ('slice', "fk['type'] = 'fk'")]),
    dict(id='workshop_range', project='RacingTadpole/python-workshop', file='t03_ducktypes.py',
         function='as_strings', name='ints', scope='arg', sources={'t03_ducktypes.py': '''from typing import Sequence
def as_strings(ints: HiddenGold) -> Sequence[str]:
    return [str(x) for x in ints]
as_strings(range(1, 3))
'''}, required=[('slice', 'as_strings(range(1, 3))')]),
    dict(id='workshop_newtype', project='RacingTadpole/python-workshop', file='t07_newtype.py',
         function='get_username', name='user_id', scope='arg', sources={'t07_newtype.py': '''from typing import NewType
UserId = NewType('UserId', int)
def get_username(user_id: HiddenGold) -> str:
    return f'user{user_id}'
get_username(UserId(4606))
'''}, required=[('slice', "NewType('UserId', int)"), ('slice', 'get_username(UserId(4606))')]),
    dict(id='foolbox_tuple_alias', project='jonasrauber/foolbox', file='tests/test_models.py',
         function='test_preprocessing', name='fmodel_and_data', scope='arg', sources={'tests/test_models.py': '''from typing import Tuple
import foolbox as fbn
import eagerpy as ep
ModelAndData = Tuple[fbn.Model, ep.Tensor, ep.Tensor]
def test_preprocessing(fmodel_and_data: HiddenGold) -> None:
    fmodel, x, y = fmodel_and_data
    return fmodel(x)
''' + '\n'.join(f'class Noise{i}: pass' for i in range(15))},
         required=[('slice_or_candidates', 'ModelAndData'), ('slice_or_candidates', 'Tuple[fbn.Model, ep.Tensor, ep.Tensor]')]),
    dict(id='subhub_symlink', project='mozilla/subhub', file='src/hub/vendor/customer.py',
         function='get_previous_plan_amount', name='previous_plan', scope='arg',
         git_link=('src/hub/shared', '../shared'), sources={
             'src/hub/vendor/customer.py': '''from hub.shared import vendor
class Customer:
    def get_previous_plan_amount(self, previous_plan: HiddenGold) -> int:
        plan = vendor.retrieve_stripe_plan(previous_plan)
        return plan.get('amount', 0)
''', 'src/shared/vendor.py': '''def retrieve_stripe_plan(plan_id: str) -> Plan:
    return lookup(plan_id)
'''}, required=[('slice', 'retrieve_stripe_plan(plan_id: str)')]),
    dict(id='mapping_constructor', project='jwnwilson/python_types', file='main.py',
         function='expect_user_mapping', name='user_mapping', scope='arg', sources={'main.py': '''class User: pass
def expect_user_mapping(user_mapping: HiddenGold) -> None:
    for key in user_mapping:
        print(f'User: {user_mapping[key]}')
expect_user_mapping({'test': User()})
'''}, required=[('slice', "expect_user_mapping({'test': User()})")]),
    dict(id='adventofcode_lambda', project='dmeleshko/adventofcode', file='y2018/day03/day03.py',
         function='part1', name='claims', scope='arg', sources={'y2018/day03/day03.py': '''import typing
from itertools import chain
class Claim: pass
def make_grid(claims: typing.List[Claim]) -> typing.List[typing.List[int]]:
    return []
def part1(claims: HiddenGold) -> int:
    grid = make_grid(claims)
    count = len(list(filter(lambda x: x == -1, chain.from_iterable(grid))))
    return count
'''}, required=[('slice', 'make_grid(claims: typing.List[Claim])')]),
    dict(id='nicecream_wildcards', project='altcatalin/nicecream-history', file='api/database.py',
         function='fetch_bookmark', name='fetch_bookmark', scope='return', sources={
             'api/database.py': '''from api.schemas import *
async def fetch_bookmark(database, bookmark_id: int) -> HiddenGold:
    return await database.fetch_one(bookmark_id)
''', 'api/schemas.py': 'class BookmarkSchema: pass\n',
             'api/auth.py': 'def private_path(handler): return handler\n',
             'api/views.py': '''from api.auth import *
from api.database import *
from api.schemas import *
async def post_user_bookmarks_handler(request):
    database = request.app['database']
    bookmark_id = 7
    return await fetch_bookmark(database, bookmark_id)
async def delete_user_bookmarks_handler(request):
    database = request.app['database']
    return await fetch_bookmark(database, request['path']['bookmark_id'])
'''}, required=[('slice', 'fetch_bookmark(database, bookmark_id)'), ('slice', "fetch_bookmark(database, request['path']['bookmark_id'])")]),
    dict(id='mort_documented_caller', project='alexdong/mort', file='mort/driver.py',
         function='submit_request', name='targets', scope='arg', sources={'mort/driver.py': '''from typing import List, Dict
def submit_request(path: str, targets: HiddenGold) -> str:
    """Browser descriptors, for example [{'os': 'Windows'}]."""
    request_payload = {'url': path, 'browsers': targets}
    return send(request_payload)
def load_screenshots(path: str, targets: List[Dict]) -> None:
    submit_request(path, targets)
'''}, required=[('slice', "[{'os': 'Windows'}]"), ('slice', 'load_screenshots(path: str, targets: List[Dict])')]),
]


def implementation_fingerprint(python_dir):
    names = ['ast_context_slicer.py', 'type_aliases.py', 'slicing_code_class.py',
             'project_kb.py', 'project_index.py', 'function_methods.py', 'export_slices.py', 'target_context.py',
             'signature_contracts.py', 'source_notes.py', 'import_analyzer.py', 'type_defined.py']
    return {name: hashlib.sha256((python_dir / name).read_bytes()).hexdigest()
            for name in names if (python_dir / name).exists()}


def replay(case, root, annotation='HiddenGold'):
    from export_slices import export_one
    from function_methods import Function_methods
    from project_index import scan_project
    from project_kb import build_project_kb
    for name, source in case['sources'].items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source.replace('HiddenGold', annotation), encoding='utf-8')
    if case.get('git_link'):
        name, destination = case['git_link']
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(destination, encoding='utf-8')
        subprocess.run(['git', 'init', '-q', str(root)], check=True, capture_output=True)
        digest = subprocess.run(['git', '-C', str(root), 'hash-object', '-w', '--stdin'],
                                input=destination, capture_output=True, text=True, check=True).stdout.strip()
        subprocess.run(['git', '-C', str(root), 'update-index', '--add', '--cacheinfo',
                        f'120000,{digest},{name}'], check=True, capture_output=True)
    parsed, _ = scan_project(root)
    methods = Function_methods.from_parsed(root, parsed)
    kb = build_project_kb(root, parsed_files=parsed)
    path = root / case['file']
    function = next(n for n in ast.walk(ast.parse(path.read_text(encoding='utf-8')))
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == case['function'])
    row = dict(scope=case['scope'], name=case['name'], loc=f"{case['function']}@{function.lineno}", gttype=annotation)
    kb_before = copy.deepcopy(kb)
    trees_before = {str(p): ast.dump(tree) for p, _, _, tree in parsed}
    source_before = path.read_bytes()
    result = export_one(row, path, function_methods=methods, project_kb=kb)
    if result is None:
        raise AssertionError(f"No export for {case['id']}")
    code = result['interprocedural_slice']
    candidates = result['recommendation_types']
    candidate_text = '\n'.join(f"{c['name']}\n{c['definition']}" for c in candidates)
    checks = [{'where': where, 'evidence': text,
               'passed': text in (code if where == 'slice' else code + '\n' + candidate_text)}
              for where, text in case['required']]
    checks.extend([dict(where='slice', evidence='target annotation masked', passed='<mask>' in code and annotation not in code and annotation not in candidate_text),
                   dict(where='source', evidence='KB, shared AST and checkout unchanged', passed=kb == kb_before and path.read_bytes() == source_before and all(ast.dump(tree) == trees_before[str(p)] for p, _, _, tree in parsed)),
                   dict(where='candidates', evidence='top-10 and 8k cap',
                        passed=len(candidates) <= 10 and all(len(c['definition']) <= 8000 for c in candidates))])
    # Normalize temporary paths so the evidence artifact is reproducible.
    diagnostics = json.loads(json.dumps(result.get('recommendation_diagnostics', {})).replace(
        str(root).replace('\\', '\\\\'), '<fixture_root>'))
    return dict(id=case['id'], project=case['project'], file=case['file'],
                passed=all(c['passed'] for c in checks), checks=checks, slice=code,
                candidates=candidates, diagnostics=diagnostics)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--python-dir', type=Path, default=Path(__file__).resolve().parents[1] / 'Python')
    args = parser.parse_args()
    sys.path.insert(0, str(args.python_dir.resolve()))
    rows = []
    with tempfile.TemporaryDirectory(prefix='typepro-evidence-audit-') as temporary:
        for case in CASES:
            root = Path(temporary) / case['id']
            root.mkdir()
            rows.append(replay(case, root))
    report = dict(scope='supplied-pattern regression fixtures; no model inference',
                  implementation_sha256=implementation_fingerprint(args.python_dir.resolve()),
                  passed=sum(r['passed'] for r in rows), total=len(rows), cases=rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'cases'}))
    return 0 if report['passed'] == report['total'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
