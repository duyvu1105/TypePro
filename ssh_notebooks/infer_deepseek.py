"""Compatibility entry point; implementation: typepro.inference.deepseek."""
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if __name__ == '__main__':
    from typepro.runtime import run_main
    run_main(lambda: importlib.import_module('typepro.inference.deepseek').main(), 'inference')
else:
    sys.modules[__name__] = importlib.import_module('typepro.inference.deepseek')
