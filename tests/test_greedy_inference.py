"""Exercise the actual generation call without loading GPU dependencies."""
import ast
from pathlib import Path
from types import SimpleNamespace


def test_generation_explicitly_overrides_sampling_and_beams():
    path = Path(__file__).resolve().parents[1] / 'typepro/inference/generative.py'
    tree = ast.parse(path.read_text())
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute) and n.func.attr == 'generate')
    received = {}
    def generate(**kwargs):
        received.update(kwargs)
        return 'generated'
    result = eval(compile(ast.Expression(call), str(path), 'eval'), dict(
        model=SimpleNamespace(generate=generate), encoded={'input_ids': [1]},
        args=SimpleNamespace(label_length=64), tokenizer=SimpleNamespace(pad_token_id=0)))
    assert result == 'generated'
    assert received == dict(input_ids=[1], max_new_tokens=64, pad_token_id=0,
                            do_sample=False, num_beams=1)
