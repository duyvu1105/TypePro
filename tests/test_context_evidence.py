"""Preserve proven callers and documentation without relaxing scope safety."""
import ast
import copy
import json
import sys
from pathlib import Path

import pytest

from typepro.analysis.ast_context_slicer import FunctionCatalog, reduce_function
from typepro.audit.context import audit, POLICY, MASKING
from typepro.analysis.export_slices import export_one
from typepro.analysis.function_methods import Function_methods
from typepro.analysis.project_index import scan_project


def project(tmp_path, sources):
    for name, source in sources.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding='utf-8')
    parsed, _ = scan_project(tmp_path)
    return Function_methods.from_parsed(tmp_path, parsed)


@pytest.mark.parametrize('prefix,helper,expected', [
    ('from helper import *', 'def convert(x): return x', True),
    ('from helper import *', '__all__ = ["convert"]\ndef convert(x): return x', True),
    ('from helper import *', '__all__ = []\ndef convert(x): return x', False),
    ('from helper import *', '__all__ = exports\ndef convert(x): return x', False),
    ('from helper import *', '__all__ = ["convert"]\n__all__.clear()\ndef convert(x): return x', False),
    ('from helper import *', 'def __getattr__(name): return other\ndef convert(x): return x', False),
    ('from helper import *', 'exec(code)\ndef convert(x): return x', False),
    ('from missing import *', 'def convert(x): return x', False),
    ('from helper import *\nfrom missing import *', 'def convert(x): return x', False),
    ('from missing import *\nfrom helper import convert', 'def convert(x): return x', True),
    ('from helper import *\nconvert = other', 'def convert(x): return x', False),
    ('if enabled:\n from helper import *', 'def convert(x): return x', False),
    ('from helper import *\nfrom other import *', 'def convert(x): return x', False),
    ('from helper import *', 'from other import *', False),
    ('from helper import *', '__all__ = ["__all__", "convert"]\ndef convert(x): return x', True),
])
def test_wildcard_resolution_fails_closed(tmp_path, prefix, helper, expected):
    methods = project(tmp_path, {
        'app.py': prefix + '\ndef caller(x): return convert(x)\n',
        'helper.py': helper + '\n',
        'other.py': 'from helper import *\ndef convert(x): return 99\n',
    })
    catalog = methods.context_catalog
    caller = catalog.trees[str((tmp_path / 'app.py').resolve())].body[-1]
    record, _ = catalog.resolve(caller.body[0].value, tmp_path / 'app.py', caller)
    assert (record is not None) == expected
    if record:
        assert record[1] == 'helper.convert'


def test_relative_wildcard_import_and_local_override(tmp_path):
    methods = project(tmp_path, {
        'pkg/app.py': 'from .helper import *\ndef caller(x): return convert(x)\n',
        'pkg/helper.py': 'from missing import *\ndef convert(x): return x\n',
    })
    cat = methods.context_catalog
    caller = cat.trees[str((tmp_path / 'pkg/app.py').resolve())].body[-1]
    # The function overrides an earlier star, but unknown namespace export
    # policy in the helper still prevents using it via a star import.
    assert cat.resolve(caller.body[0].value, tmp_path / 'pkg/app.py', caller)[0] is None
    methods = project(tmp_path, {
        'pkg/app.py': 'from .helper import *\ndef caller(x): return convert(x)\n',
        'pkg/helper.py': 'def convert(x): return x\n',
    })
    cat = methods.context_catalog
    caller = cat.trees[str((tmp_path / 'pkg/app.py').resolve())].body[-1]
    assert cat.resolve(caller.body[0].value, tmp_path / 'pkg/app.py', caller)[0][1] == 'pkg.helper.convert'


def test_nicecream_two_real_call_patterns_survive(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    methods = project(tmp_path, {
        'api/schemas.py': 'class BookmarkSchema: pass\n',
        'api/auth.py': 'def private_path(handler): return handler\n',
        'api/database.py': '''from api.schemas import *
async def fetch_bookmark(database, bookmark_id) -> HiddenGold:
    return database.fetch_one(bookmark_id)
''',
        'api/views.py': '''from api.auth import *
from api.database import *
from api.schemas import *
async def post_user_bookmarks_handler(request):
    database = request.app['database']
    bookmark_id = 7
    data = await fetch_bookmark(database, bookmark_id)
    unrelated = 'drop_me'
    return data
async def delete_user_bookmarks_handler(request):
    database = request.app['database']
    data = await fetch_bookmark(database, request['path']['bookmark_id'])
    return data
''',
    })
    assert len(methods.context_catalog.callers('api.database.fetch_bookmark')) == 2
    result = export_one({'scope': 'return', 'name': 'fetch_bookmark',
                         'loc': 'fetch_bookmark@2', 'gttype': 'HiddenGold'},
                        tmp_path / 'api/database.py', function_methods=methods, project_kb={'records': []})
    code = result['interprocedural_slice']
    assert 'async def post_user_bookmarks_handler(request):' in code
    assert 'async def delete_user_bookmarks_handler(request):' in code
    assert "request['path']['bookmark_id']" in code
    assert 'drop_me' not in code and 'HiddenGold' not in code


def test_mort_parameter_docstring_and_caller_contract_are_preserved(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    outputs = []
    for gold in ('HiddenGoldA', 'HiddenGoldB'):
        methods = project(tmp_path, {'driver.py': f'''from typing import List, Dict
def submit_request(path: str, targets: {gold}) -> str:
    """Browser descriptors, for example [{{'os': 'Windows'}}]."""
    request_payload = {{'url': path, 'browsers': targets}}
    noise = 'target_noise'
    return send(request_payload)
def load_screenshots(path: str, targets: List[Dict], count: int = 1) -> None:
    """Load screenshots for browser descriptors."""
    noise = 'caller_noise'
    for i in range(count):
        submit_request(path, targets)
'''})
        before = copy.deepcopy(methods.context_catalog.trees)
        result = export_one({'scope': 'arg', 'name': 'targets', 'loc': 'submit_request@2', 'gttype': gold},
                            tmp_path / 'driver.py', function_methods=methods, project_kb={'records': []})
        code = result['interprocedural_slice']
        assert "[{'os': 'Windows'}]" in code
        assert 'targets: List[Dict]' in code
        assert 'def load_screenshots(' in code and 'Load screenshots for browser descriptors.' in code
        assert 'target_noise' not in code and 'caller_noise' not in code
        assert gold not in code and 'targets: <mask>' in code
        assert all(ast.dump(tree) == ast.dump(before[path]) for path, tree in methods.context_catalog.trees.items())
        outputs.append(code)
    assert outputs[0] == outputs[1]


def test_recursive_caller_target_signature_stays_masked(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    methods = project(tmp_path, {'app.py': '''def target(value: HiddenGold):
    """Documented recursive input."""
    if value:
        return target(value[1:])
    return value
'''})
    result = export_one({'scope': 'arg', 'name': 'value', 'loc': 'target@1', 'gttype': 'HiddenGold'},
                        tmp_path / 'app.py', function_methods=methods, project_kb={'records': []})
    assert 'HiddenGold' not in result['interprocedural_slice']
    assert 'Documented recursive input.' in result['interprocedural_slice']


def test_docstring_preservation_does_not_keep_arbitrary_strings():
    function = ast.parse('def f(value):\n """Useful documentation."""\n "unrelated string"\n return value\n').body[0]
    reduced = reduce_function(function, ['value'])
    assert ast.get_docstring(reduced.node) == 'Useful documentation.'
    assert 'unrelated string' not in ast.unparse(reduced.node)
    assert ast.get_docstring(function) == 'Useful documentation.'


def test_opaque_caller_keeps_documented_signature_and_exact_call_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    methods = project(tmp_path, {'app.py': '''def target(value: HiddenGold):
    return value
def caller(items: list[dict]):
    """Items describe browsers."""
    class Local:
        secret = 'opaque_noise'
    target(items)
'''})
    result = export_one({'scope': 'arg', 'name': 'value', 'loc': 'target@1', 'gttype': 'HiddenGold'},
                        tmp_path / 'app.py', function_methods=methods, project_kb={'records': []})
    code = result['interprocedural_slice']
    assert 'def caller(items: list[dict]):' in code
    assert 'Items describe browsers.' in code and 'target(items)' in code
    assert 'opaque_noise' not in code and 'class Local' not in code


def test_signature_only_callee_keeps_docstring_without_expanding_body(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    methods = project(tmp_path, {'app.py': '''def helper(value: str) -> int:
    """Return the number of browser descriptors."""
    noise = 'callee_noise'
    return len(value)
def target(value: HiddenGold):
    return helper(value)
'''})
    result = export_one({'scope': 'arg', 'name': 'value', 'loc': 'target@5', 'gttype': 'HiddenGold'},
                        tmp_path / 'app.py', function_methods=methods, project_kb={'records': []})
    code = result['interprocedural_slice']
    assert 'Return the number of browser descriptors.' in code
    assert 'def helper(value: str) -> int:' in code
    assert 'callee_noise' not in code and 'return len(value)' not in code


@pytest.mark.parametrize('policy', [POLICY, 'ast-context-v3-recursive-signature-first'])
def test_context_audit_rejects_previous_policy(tmp_path, policy):
    row = {'context_policy_version': policy, 'target_masking_version': MASKING,
           'candidate_definition_max_chars': 8000, 'recommendation_types': [],
           'interprocedural_slice': 'def target(value: <mask>):\n    return value'}
    (tmp_path / 'raw.jsonl').write_text(json.dumps(row) + '\n', encoding='utf-8')
    if policy == POLICY:
        assert audit(tmp_path)['verified']
    else:
        with pytest.raises(ValueError, match='Incompatible context policy'):
            audit(tmp_path)
