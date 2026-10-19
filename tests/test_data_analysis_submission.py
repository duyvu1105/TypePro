"""Token analysis submissions execute and record the selected source revision."""
import json
import sys
from pathlib import Path

import pytest


NOTEBOOK_DIR = Path(__file__).resolve().parents[1] / "kaggle_notebooks"
sys.path.insert(0, str(NOTEBOOK_DIR))
import commit_data_analysis as analysis
import generate_notebooks as generator


def test_payload_pins_source_and_keeps_analysis_private(tmp_path):
    revision = "a" * 40
    analysis.write_payload(tmp_path, revision)
    notebook = json.loads((tmp_path / "typepro_data_analysis.ipynb").read_text())
    setup = notebook["cells"][1]["source"]
    assert revision in setup
    assert analysis.REVISION_MARKER not in json.dumps(notebook)
    assert '"checkout", "--detach", REVISION' in setup
    assert 'actual_revision != REVISION' in setup
    assert '"revision": actual_revision' in notebook["cells"][-1]["source"]
    metadata = json.loads((tmp_path / "kernel-metadata.json").read_text())
    assert metadata["id"] == "duyvu1105/typepro-python-data-token-analysis"
    assert metadata["is_private"] is True
    assert metadata["dataset_sources"] == analysis.DATASET_SOURCES
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            compile(cell["source"], "analysis", "exec")


@pytest.mark.parametrize("revision", ["main", "a" * 39, "z" * 40])
def test_payload_rejects_unpinned_revision(tmp_path, revision):
    with pytest.raises(ValueError, match="full Git SHA"):
        analysis.write_payload(tmp_path, revision)


def test_analysis_dry_run_does_not_require_credentials(tmp_path, monkeypatch, capsys):
    def fail(*args):
        pytest.fail("Dry-run must not read credentials")

    monkeypatch.setattr(analysis, "load_credential", fail)
    analysis.main(["--output-dir", str(tmp_path)])
    assert json.loads(capsys.readouterr().out)["pushed"] is False


def test_analysis_artifact_matches_generator():
    assert json.loads(analysis.NOTEBOOK_PATH.read_text(encoding="utf-8")) == (
        generator.data_analysis_notebook("https://github.com/duyvu1105/TypePro.git", "main")
    )
