import ast
import copy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'Python'))
from export_slices import export_one
from function_methods import Function_methods
from project_index import scan_project
from project_kb import build_project_kb
from target_context import MASK, mask_annotation, mask_definition, read_source, source_overlay


@pytest.mark.parametrize('scope,name,function,line', [
    ('arg', 'container', 'create_attacker', 2),
    ('return', 'fetch', 'fetch', 4),
    ('return', 'load', 'load', 7),
])
def test_shared_kb_is_reused_unchanged_with_masked_source(tmp_path, monkeypatch, scope, name, function, line):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'data').mkdir()
    project = tmp_path / 'repo'
    project.mkdir()
    source = project / 'app.py'
    (project / 'caller.py').write_text(
        'from app import create_attacker, fetch\n'
        'result = create_attacker("ip", "ubuntu")\nvalue = fetch()\n', encoding='utf-8')
    outputs = []
    kb = None
    for gold in ('HiddenGoldA', 'HiddenGoldB'):
        source.write_text(
            'class Visible: pass\n'
            f'def create_attacker(ip: str, container: {gold}) -> bool:\n    return bool(container)\n'
            f'def fetch() -> {gold}:\n    return Visible()\n'
            'class Owner:\n'
            f'    def load(self, count: int) -> {gold}:\n        return Visible()\n', encoding='utf-8')
        # Change ONLY the target annotation; all other contracts stay constant.
        tree = ast.parse(source.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == gold:
                parent_target = next((f for f in ast.walk(tree) if isinstance(f, ast.FunctionDef)
                                      and f.name == function), None)
                target_ann = (next(a.annotation for a in parent_target.args.args if a.arg == name)
                              if scope == 'arg' else parent_target.returns)
                if node is not target_ann:
                    node.id = 'OtherContract'
        source.write_text(ast.unparse(tree) + '\n', encoding='utf-8')
        # ast.unparse may insert blank lines; use the actual target location.
        target = next(n for n in ast.walk(ast.parse(source.read_text())) if isinstance(n, ast.FunctionDef) and n.name == function)
        parsed, _ = scan_project(project)
        methods = Function_methods.from_parsed(project, parsed)
        if kb is None:
            kb = build_project_kb(project)
        kb_before = copy.deepcopy(kb)
        original = source.read_bytes()
        row = {'name': name, 'scope': scope, 'loc': f'{function}@{target.lineno}', 'gttype': gold}
        with monkeypatch.context() as guard:
            def forbidden(*args, **kwargs):
                raise AssertionError('Per-sample project rebuild is forbidden')
            guard.setattr('project_kb.build_project_kb', forbidden)
            guard.setattr(Function_methods, 'from_parsed', forbidden)
            guard.setattr('type_signal_analyzer.ProjectTypeAnalyzer._build', forbidden)
            result = export_one(row, source, function_methods=methods, project_kb=kb)
        assert kb == kb_before
        assert result is not None
        assert source.read_bytes() == original
        assert '<mask>' in result['interprocedural_slice']
        context = result['interprocedural_slice'] + str(result['recommendation_types'])
        assert gold not in result['interprocedural_slice']
        assert '-> ' + gold not in context
        assert 'container: ' + gold not in context
        assert MASK not in context
        assert 'int' in str(result['recommendation_types']) or scope == 'arg'
        outputs.append((result['interprocedural_slice'], result['recommendation_types']))
    assert outputs[0] == outputs[1]


def test_overlay_restores_on_error_and_preserves_unicode_multiline(tmp_path):
    source = 'def f(\u00e9: tuple[\n    str, int\n]):\n    pass\n'
    path = tmp_path / 'source.py'
    path.write_text(source, encoding='utf-8')
    annotation = ast.parse(source).body[0].args.args[0].annotation
    masked = mask_annotation(source, annotation)
    ast.parse(masked)
    assert masked.count('\n') == source.count('\n')
    with pytest.raises(RuntimeError):
        with source_overlay(path, masked):
            assert read_source(path) == masked
            raise RuntimeError('stop')
    assert read_source(path) == source


@pytest.mark.parametrize('definition', [
    'function target(value: HiddenGold) -> bool',
    'class Owner:\n    def target(\n        self, value: HiddenGold,\n',
])
def test_incomplete_candidate_signature_cannot_expose_target(definition):
    masked = mask_definition(definition, 'target', 'value', 'arg')
    assert 'HiddenGold' not in masked
