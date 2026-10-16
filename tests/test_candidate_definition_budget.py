"""Candidate-only, syntax-preserving 8k summaries after member selection."""
import ast
import copy
import sys
from pathlib import Path

import pytest

from typepro.analysis.ast_context_slicer import limit_candidate_definition
from typepro.analysis.project_kb import top_project_types
from typepro.data.preprocess import normalized_recommendations


@pytest.mark.parametrize('size', [7999, 8000, 8001, 430474])
def test_unicode_boundary_uses_signature_summary_only_above_budget(size):
    prefix, suffix = 'def parse(value: str) -> int:\n    payload = "', '"\n    return len(payload)\n'
    definition = prefix + '\u03bb' * (size - len(prefix) - len(suffix)) + suffix
    output, diagnostic = limit_candidate_definition(definition)
    assert len(output) <= 8000
    ast.parse(output)
    if size <= 8000:
        assert output == definition and diagnostic['mode'] == 'full'
    else:
        assert output == 'def parse(value: str) -> int:\n    pass'
        assert diagnostic['mode'] == 'signature_docstring'


def test_large_class_preserves_headers_attributes_and_documented_methods():
    definition = '''class Client(Base):
    """A browser client."""
    timeout: int = 30
    kind = 'browser'
    @classmethod
    def make(cls, descriptors: list[dict]) -> 'Client':
        """Construct from browser descriptors."""
        payload = "''' + 'x' * 9000 + '''"
        return cls(payload)
    async def send(self, request: bytes, /, *, timeout: int = 3) -> bytes:
        """Send a request."""
        return await transport(request)
'''
    output, _ = limit_candidate_definition(definition)
    tree = ast.parse(output)
    cls = tree.body[0]
    assert ast.get_docstring(cls) == 'A browser client.'
    assert 'class Client(Base):' in output and 'timeout: int' in output
    assert 'kind = ...' in output and '@classmethod' in output
    assert "descriptors: list[dict]" in output
    assert 'async def send(self, request: bytes, /, *, timeout: int=3) -> bytes:' in output
    assert 'Construct from browser descriptors.' in output and 'Send a request.' in output
    assert 'payload' not in output and 'transport(request)' not in output


def test_docstrings_shorten_at_paragraph_boundaries_after_signatures():
    paragraph = 'Browser descriptors. ' * 150
    documentation = '\n\n'.join([paragraph, paragraph, paragraph, paragraph])
    source = f'def parse(value: list[dict]) -> int:\n    """{documentation}"""\n    return len(value)\n'
    output, diagnostic = limit_candidate_definition(source)
    doc = ast.get_docstring(ast.parse(output).body[0], clean=False)
    assert doc and len(doc) < len(documentation)
    assert all(part == paragraph for part in doc.split('\n\n'))
    assert 'def parse(value: list[dict]) -> int:' in output
    assert len(output) <= 8000 and diagnostic['docstrings_shortened']


def test_huge_single_paragraph_is_omitted_without_cutting_signature():
    source = 'def parse(value: list[dict]):\n    """' + 'x' * 10000 + '"""\n    return value\n'
    output, diagnostic = limit_candidate_definition(source)
    assert ast.get_docstring(ast.parse(output).body[0]) is None
    assert 'value: list[dict]' in output and diagnostic['docstrings_shortened']


def test_signature_budget_omits_whole_members_and_preserves_parseability():
    source = 'class Parser:\n' + ''.join(f'    def method_{i}(self, value: list[dict]) -> int: return 1\n' for i in range(500))
    output, diagnostic = limit_candidate_definition(source)
    node = ast.parse(output).body[0]
    assert len(output) <= 8000 and diagnostic['omitted_declarations'] > 0
    assert all(isinstance(s, ast.FunctionDef) for s in node.body)
    assert node.body[0].name == 'method_0'


@pytest.mark.parametrize('source', [
    'def parse(value: Literal["' + 'x' * 9000 + '"]): return value',
    'class Broken:\n' + '!' * 9000,
])
def test_oversized_or_invalid_header_is_omitted_safely(source):
    output, _ = limit_candidate_definition(source)
    assert len(output) <= 8000 and output.startswith('# candidate definition omitted:')
    ast.parse(output)


def test_member_selection_precedes_budget_and_shared_kb_stays_complete():
    definition = 'class Client:\n    """Browser client."""\n    def send(self, value):\n        return value.read()\n    def unused(self):\n        return "' + 'x' * 10000 + '"\n'
    kb = {'records': [{'name': 'Client', 'qualified_name': 'app.Client', 'kind': 'class',
                       'source': 'project', 'definition': definition, 'members': ['send', 'unused']}]}
    before = copy.deepcopy(kb)
    candidate = top_project_types(kb, 'client', 'client.send(value)', target_members={'methods': ['send']})[0]
    assert 'return value.read()' in candidate['definition']
    assert 'Browser client.' in candidate['definition']
    assert 'def unused' not in candidate['definition']
    assert candidate['definition_reduction']['mode'] == 'full'
    assert kb == before


def test_masking_ranking_and_preprocessing_share_summary_policy():
    records = [{'name': f'Type{i}', 'qualified_name': f'app.Type{i}', 'source': 'project', 'kind': 'class',
                'definition': f'class Type{i}:\n    def target(self, value: HiddenGold):\n        """Browser descriptors."""\n        return "' + 'x' * 9000 + '"\n'} for i in range(12)]
    kb = {'records': records}
    before = copy.deepcopy(kb)
    seeds = [{'qualified_name': r['qualified_name']} for r in reversed(records)]
    candidates = top_project_types(kb, 'value', 'target(value)', seeds,
                                   target_function='target', target_scope='arg')
    assert [c['name'] for c in candidates] == [r['name'] for r in reversed(records)][0:10]
    assert all('HiddenGold' not in c['definition'] and 'Browser descriptors.' in c['definition'] for c in candidates)
    assert kb == before
    normalized = normalized_recommendations({'recommendation_types': candidates}, 10)
    assert [n['definition'] for n in normalized] == [c['definition'] for c in candidates]
    for item in normalized:
        ast.parse(item['definition'])


def test_preprocessing_summarizes_large_external_definitions_without_mutation():
    definition = 'def parse(value: str):\n    """Browser descriptors."""\n    return "' + 'x' * 9000 + '"'
    row = {'recommendation_types': [{'name': 'Parser', 'definition': definition}]}
    before = copy.deepcopy(row)
    output = normalized_recommendations(row, 10)[0]['definition']
    assert output == limit_candidate_definition(definition)[0]
    assert row == before


def test_imported_kb_signature_lists_receive_complete_method_suites():
    definition = 'class External(Base):\n    # public methods\n' + ''.join(
        f'    def method_{i}(self, descriptors: list[dict]) -> bytes:\n' for i in range(180))
    output, diagnostic = limit_candidate_definition(definition)
    tree = ast.parse(output)
    assert len(output) <= 8000
    assert 'class External(Base):' in output
    assert 'def method_0(self, descriptors: list[dict]) -> bytes:' in output
    assert diagnostic['mode'] == 'signature_docstring'
    assert all(isinstance(s.body[0], ast.Pass) for s in tree.body[0].body)
