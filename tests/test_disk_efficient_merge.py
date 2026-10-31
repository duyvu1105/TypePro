import errno
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

from typepro.analysis.evidence_bundle import build_bundle, RETRIEVAL_SCHEMA
from typepro.data.merge import copy_checked
from typepro.data.prepare import finalize_dataset, parse_args, count_jsonl
from typepro.publishing.final import package_final
from typepro.shared.jsonl_io import open_text, split_path
from typepro.shared.data_utils import iter_records


def test_linked_staging_does_not_copy_or_change_input(tmp_path, monkeypatch):
    source = tmp_path / 'mounted' / 'raw.jsonl'
    source.parent.mkdir()
    source.write_text('immutable original\n')
    destination = tmp_path / 'working' / 'raw.jsonl'
    monkeypatch.setattr('typepro.data.merge.shutil.copy2', lambda *a: pytest.fail('copied input bytes'))
    copy_checked(source, destination, link=True)
    assert destination.samefile(source)
    destination.unlink()
    assert source.read_text() == 'immutable original\n'


@pytest.mark.skipif(os.name == 'nt', reason='Windows symlinks may require administrator privileges')
def test_cross_mount_staging_links_to_readonly_input(tmp_path, monkeypatch):
    source = tmp_path / 'mounted.jsonl'
    source.write_text('original')
    def cross_device(*args):
        raise OSError(errno.EXDEV, 'cross-device')
    monkeypatch.setattr('typepro.data.merge.os.link', cross_device)
    destination = tmp_path / 'working.jsonl'
    copy_checked(source, destination, link=True)
    assert destination.is_symlink() and destination.read_text() == 'original'
    destination.unlink()
    assert source.read_text() == 'original'


def row(split):
    code = 'def target(x: <mask>):\n    return x'
    return dict(id=split, split=split, file=f'repos/owner/{split}/app.py',
                name='x', scope='arg', target_function='target', gttype='str',
                interprocedural_slice=code, recommendation_types=[],
                candidate_policy_version='candidate-lexical-v3',
                context_policy_version='ast-context-v7-verified-signature-evidence',
                evidence_bundle=build_bundle(code, [], [], {}))


def test_compressed_finalization_verification_and_publish_preserve_all_data(tmp_path, monkeypatch):
    work, output = tmp_path / 'build', tmp_path / 'final'
    raw, metadata = work / 'raw_slices', work / 'metadata'
    raw.mkdir(parents=True)
    metadata.mkdir()
    mounted = tmp_path / 'mounted'
    mounted.mkdir()
    kb_bytes = b'{"records":[],"schema_version":"typepro-project-kb-v7-source-evidence"}'
    for split in ('train', 'validation', 'test'):
        value = row(split)
        original = mounted / f'{split}.jsonl'
        original.write_text(json.dumps(value) + '\n', encoding='utf-8')
        copy_checked(original, raw / f'owner__{split}.jsonl', link=True)
        (metadata / f'{split}.json').write_text(json.dumps([value]))
        kb_source = mounted / f'{split}_kb.json'
        kb_source.write_bytes(kb_bytes)
        copy_checked(kb_source, work / 'project_kb' / f'owner__{split}' / 'knowledge_base.json', link=True)
        status = work / 'project_status' / f'owner__{split}.json'
        status.parent.mkdir(exist_ok=True)
        status.write_text(json.dumps(dict(project=f'owner/{split}', exported=1)))
    (metadata / 'split_manifest.json').write_text('{"split_profile":"paper_project"}')
    (work / 'runtime_manifest.json').write_text(json.dumps(dict(retrieval_schema_version=RETRIEVAL_SCHEMA)))
    monkeypatch.setattr(sys, 'argv', ['prepare', '--compress-output', '--preview-samples', '0'])
    args = parse_args()
    manifest = finalize_dataset(args, work, output, Path(__file__).resolve().parents[1])
    assert not raw.exists() and not (work / 'project_kb').exists()
    assert len(list(mounted.glob('*.jsonl'))) == 3
    for split in ('train', 'validation', 'test'):
        path = split_path(output, split)
        assert path.name == f'{split}.jsonl.gz' == manifest['output'][split]['file']
        assert count_jsonl(path) == manifest['output'][split]['rows'] == 1
        record = list(iter_records(path))[0]
        assert record['evidence_bundle'] == row(split)['evidence_bundle']
        assert record['label'] == 'str'
        final_kb = output / 'project_kb' / f'owner__{split}' / 'knowledge_base.json'
        assert final_kb.samefile(mounted / f'{split}_kb.json')
        assert final_kb.read_bytes() == kb_bytes
    subprocess.run([sys.executable, '-m', 'typepro.data.verify', '--data-dir', str(output)], check=True, capture_output=True)
    payload = tmp_path / 'payload'
    index = package_final(output, payload)
    assert len(index) == 3
    with zipfile.ZipFile(payload / 'typepro.analysis.project_kb.zip') as archive:
        for split in ('train', 'validation', 'test'):
            assert archive.read(f'owner__{split}/knowledge_base.json') == kb_bytes
    with open_text(payload / 'train.jsonl.gz') as handle:
        assert json.loads(next(handle))['evidence_bundle'] == row('train')['evidence_bundle']


def test_compressed_preprocess_matches_uncompressed_rows(tmp_path):
    raw = tmp_path / 'raw.jsonl'
    value = row('train')
    value['interprocedural_slice'] += '\n# repeated source evidence' * 500
    raw.write_text(json.dumps(value) + '\n', encoding='utf-8')
    for name, flags in [('plain', []), ('gzip', ['--compress-output'])]:
        subprocess.run([sys.executable, '-m', 'typepro.data.preprocess', '--input', str(raw),
                        '--output-dir', str(tmp_path / name), *flags], check=True, capture_output=True)
    plain = tmp_path / 'plain' / 'train.jsonl'
    compressed = tmp_path / 'gzip' / 'train.jsonl.gz'
    assert list(iter_records(plain)) == list(iter_records(compressed))
    assert compressed.stat().st_size < plain.stat().st_size / 4


def test_manifest_selects_compressed_split_even_if_old_plain_file_exists(tmp_path):
    (tmp_path / 'train.jsonl').write_text('old')
    (tmp_path / 'manifest.json').write_text(json.dumps(dict(output=dict(train=dict(file='train.jsonl.gz')))))
    assert split_path(tmp_path, 'train') == tmp_path / 'train.jsonl.gz'
