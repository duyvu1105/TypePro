"""Offline tests for the resumable DeepSeek inference runner."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ssh_notebooks import infer_deepseek


class FakeResponse:
    def __init__(self, prediction: str | None = None, status: int = 200, reason: str = "stop"):
        self.prediction = prediction
        self.status_code = status
        self.reason = reason
        self.headers = {}

    def json(self):
        return {
            "model": "deepseek-flash",
            "choices": [{
                "message": {"content": self.prediction},
                "finish_reason": self.reason,
            }],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2},
        }


class FakeSession:
    def __init__(self, responses: list[FakeResponse]):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, *, headers, json, timeout):
        self.calls.append((url, headers, json, timeout))
        return self.responses.pop(0)


def sample_args(tmp_path: Path, *, max_new=None, score_only=False):
    test_path = tmp_path / "test.jsonl"
    if not test_path.exists():
        rows = [
            {"id": "one", "input": "def f(x: <mask>):\n    return x + 1", "label": "int"},
            {"id": "two", "input": "def g(x: <mask>):\n    return x.lower()", "label": "str"},
        ]
        test_path.write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )
    return infer_deepseek.parse_args([
        "--input", str(test_path),
        "--output-dir", str(tmp_path / "out"),
        *(["--max-new", str(max_new)] if max_new is not None else []),
        *(["--score-only"] if score_only else []),
    ])


def test_resume_and_score_without_repeating_completed_calls(tmp_path):
    first = FakeSession([FakeResponse("int")])
    summary = infer_deepseek.run_inference(
        sample_args(tmp_path, max_new=1), session=first, api_key="test-key"
    )
    assert summary["status"] == "partial"
    assert (summary["completed"], summary["remaining"]) == (1, 1)
    assert summary["exact_match_accuracy_full_test"] is None
    assert len(first.calls) == 1
    assert "str" not in first.calls[0][2]["messages"][1]["content"]

    second = FakeSession([FakeResponse("str")])
    summary = infer_deepseek.run_inference(
        sample_args(tmp_path), session=second, api_key="test-key"
    )
    assert summary["status"] == "complete"
    assert summary["exact_matches"] == 2
    assert summary["exact_match_accuracy_full_test"] == 1.0
    assert summary["prompt_tokens"] == 20
    assert len(second.calls) == 1
    predictions = [
        json.loads(line)
        for line in (tmp_path / "out/test_predictions.jsonl").read_text().splitlines()
    ]
    assert [row["id"] for row in predictions] == ["one", "two"]
    assert all(row["exact_match"] for row in predictions)

    scored = infer_deepseek.run_inference(sample_args(tmp_path, score_only=True))
    assert scored == summary


def test_checkpoint_rejects_changed_model_or_input(tmp_path):
    infer_deepseek.run_inference(
        sample_args(tmp_path, max_new=1),
        session=FakeSession([FakeResponse("int")]), api_key="test-key",
    )
    args = sample_args(tmp_path)
    args.model = "deepseek-v4-pro"
    with pytest.raises(ValueError, match="another dataset/model"):
        infer_deepseek.run_inference(args, session=FakeSession([]), api_key="test-key")


def test_retry_and_incomplete_response(tmp_path, monkeypatch):
    monkeypatch.setattr(infer_deepseek.time, "sleep", lambda seconds: None)
    session = FakeSession([FakeResponse(status=429), FakeResponse("int")])
    result = infer_deepseek.request_prediction(
        session, "test-key", "input", model="deepseek-flash",
        max_tokens=128, temperature=0, max_retries=1,
    )
    assert result[:2] == ("int", "stop")
    assert len(session.calls) == 2

    with pytest.raises(RuntimeError, match="Incomplete completion"):
        infer_deepseek.run_inference(
            sample_args(tmp_path, max_new=1),
            session=FakeSession([FakeResponse("List[", reason="length")]),
            api_key="test-key",
        )
    assert json.loads((tmp_path / "out/summary.json").read_text())["completed"] == 0


def test_key_from_env_file_without_shell_execution(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    path = tmp_path / ".env"
    path.write_text("# comment\nDEEPSEEK_API_KEY='placeholder'\n", encoding="utf-8")
    path.chmod(0o600)
    assert infer_deepseek.load_api_key(path) == "placeholder"
    path.chmod(0o644)
    with pytest.raises(PermissionError, match="mode 600"):
        infer_deepseek.load_api_key(path)
