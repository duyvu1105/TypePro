"""Workflow audits and package entry points survive migration and failures."""
import json
import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

from typepro.runtime import run_main


def test_generated_kaggle_cells_have_valid_python_syntax():
    root = Path(__file__).resolve().parents[1]
    for path in (root / 'kaggle_notebooks').glob('*.ipynb'):
        notebook = json.loads(path.read_text(encoding='utf-8'))
        for index, cell in enumerate(notebook['cells']):
            if cell['cell_type'] == 'code':
                compile(cell['source'], f'{path.name}:cell-{index}', 'exec')


def test_notebook_repository_script_and_dependency_paths_exist():
    root = Path(__file__).resolve().parents[1]

    def repository_path(node):
        if isinstance(node, ast.Name):
            return {'REPO_DIR': root, 'PIPELINE_DIR': root / 'typepro'}.get(node.id)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            left, right = repository_path(node.left), repository_path(node.right)
            if isinstance(left, Path) and isinstance(right, str):
                return left / right

    for folder in ('kaggle_notebooks', 'ssh_notebooks', 'vastai_notebooks'):
        for path in (root / folder).glob('*.ipynb'):
            notebook = json.loads(path.read_text(encoding='utf-8'))
            for cell in notebook['cells']:
                if cell['cell_type'] != 'code':
                    continue
                source = cell['source']
                if isinstance(source, list):
                    source = ''.join(source)
                for node in ast.walk(ast.parse(source)):
                    target = repository_path(node)
                    if isinstance(target, Path) and target.suffix in ('.py', '.txt'):
                        assert target.is_file(), f'{path.name}: missing {target}'


@pytest.mark.parametrize('failure,status', [(None, 'complete'), (RuntimeError, 'failed'), (KeyboardInterrupt, 'interrupted')])
def test_runtime_records_lifecycle_and_redacts_secrets(tmp_path, monkeypatch, failure, status):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'sensitive-test-token')

    def command():
        print('credential sensitive-test-token')
        if failure:
            raise failure('sensitive-test-token')

    if failure:
        with pytest.raises(failure):
            run_main(command, 'test', audit_root=tmp_path)
    else:
        run_main(command, 'test', audit_root=tmp_path)
    folder, = tmp_path.iterdir()
    state = json.loads((folder / 'run.json').read_text())
    assert state['status'] == status
    assert state['elapsed_seconds'] >= 0
    assert 'sensitive-test-token' not in (folder / 'console.log').read_text()
    assert 'sensitive-test-token' not in (folder / 'run.json').read_text()
    assert '[REDACTED]' in (folder / 'console.log').read_text()


@pytest.mark.parametrize('script', ['analysis/export_slices.py', 'data/prepare.py', 'audit/regressions.py'])
def test_direct_entrypoints_work_outside_repository(tmp_path, script):
    root = Path(__file__).resolve().parents[1]
    environment = dict(os.environ)
    environment.pop('PYTHONPATH', None)
    result = subprocess.run(
        [sys.executable, str(root / 'typepro' / script), '--help'],
        cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert 'usage:' in result.stdout


@pytest.mark.parametrize('notebook', ['01_typepro_shard_00.ipynb', '12_train_and_infer.ipynb', '13_data_analysis.ipynb'])
def test_notebook_imports_package_from_fresh_working_directory(tmp_path, notebook):
    root = Path(__file__).resolve().parents[1]
    cells = json.loads((root / 'kaggle_notebooks' / notebook).read_text(encoding='utf-8'))['cells']
    setup_statements = []
    for cell in cells:
        if cell['cell_type'] != 'code':
            continue
        tree = ast.parse(cell['source'])
        if 'from typepro.' in cell['source']:
            break
        setup_statements.extend(node for node in tree.body if isinstance(node, ast.If)
                                and 'sys.path.insert' in ast.unparse(node))
    # Execute the real import bootstrap, stopping before dataset/model loading.
    statements = list(setup_statements)
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == 'transformers':
            continue
        statements.append(node)
        if isinstance(node, ast.ImportFrom) and (node.module or '').startswith('typepro.'):
            break
    setup = f'import sys\nfrom pathlib import Path\nREPO_DIR = Path({str(root)!r})\nPIPELINE_DIR = REPO_DIR / "typepro"\n'
    script = setup + ast.unparse(ast.Module(body=statements, type_ignores=[]))
    environment = dict(os.environ)
    environment.pop('PYTHONPATH', None)
    result = subprocess.run([sys.executable, '-c', script], cwd=tmp_path,
                            env=environment, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_deepseek_lock_prevents_concurrent_writer(tmp_path):
    from typepro.inference.deepseek import exclusive_run_lock
    lock = tmp_path / 'inference.lock'
    with exclusive_run_lock(lock):
        with pytest.raises(RuntimeError, match='Another DeepSeek'):
            with exclusive_run_lock(lock):
                pytest.fail('Acquired a lock already held by another writer')
    with exclusive_run_lock(lock):
        pass
