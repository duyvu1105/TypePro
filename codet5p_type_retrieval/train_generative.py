"""Compatibility entry point; implementation: typepro.training.generative."""
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if __name__ == '__main__':
    from typepro.runtime import run_main
    run_main(lambda: importlib.import_module('typepro.training.generative').main(), 'training')
else:
    sys.modules[__name__] = importlib.import_module('typepro.training.generative')
