"""Persistent, per-process console and lifecycle audits without logging credentials."""
import json
import os
import re
import subprocess
import sys
import time
import traceback
import uuid
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path


def redact(text):
    for key, value in os.environ.items():
        if any(word in key.upper() for word in ('TOKEN', 'SECRET', 'PASSWORD', 'API_KEY', 'KAGGLE_KEY')) and len(value) >= 6:
            text = text.replace(value, '[REDACTED]')
    return re.sub(r'(?i)(Bearer\s+)[^\s"\x27]+', r'\1[REDACTED]', text)


class Tee:
    def __init__(self, console, log):
        self.console, self.log = console, log

    def write(self, text):
        text = redact(text)
        self.console.write(text)
        self.log.write(text)
        self.log.flush()
        return len(text)

    def flush(self):
        self.console.flush()
        self.log.flush()

    def isatty(self):
        return False

    @property
    def encoding(self):
        return self.console.encoding


def run_main(function, stage, *, audit_root=None):
    root = Path(audit_root or os.environ.get('TYPEPRO_AUDIT_DIR', 'outputs/audit'))
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
    folder = root / f'{stamp}-{stage}-{uuid.uuid4().hex[:8]}'
    folder.mkdir(parents=True)
    started = time.monotonic()
    state = dict(stage=stage, status='running', started_at=datetime.now(timezone.utc).isoformat(),
                 pid=os.getpid(), rank=os.environ.get('RANK', '0'), python=sys.version,
                 cwd=str(Path.cwd()), option_names=[a.split('=', 1)[0] for a in sys.argv[1:] if a.startswith('--')])
    try:
        state['git_revision'] = subprocess.check_output(
            ['git', '-C', str(Path(__file__).resolve().parents[1]), 'rev-parse', 'HEAD'],
            stderr=subprocess.DEVNULL, timeout=5, text=True).strip()
    except (OSError, subprocess.SubprocessError):
        state['git_revision'] = None

    def save():
        temporary = folder / 'run.json.tmp'
        temporary.write_text(json.dumps(state, indent=2), encoding='utf-8')
        temporary.replace(folder / 'run.json')

    save()
    with (folder / 'console.log').open('w', encoding='utf-8') as log:
        with redirect_stdout(Tee(sys.stdout, log)), redirect_stderr(Tee(sys.stderr, log)):
            try:
                result = function()
                state.update(status='complete', exit_code=0)
                return result
            except SystemExit as error:
                code = error.code if isinstance(error.code, int) else (0 if error.code is None else 1)
                state.update(status='complete' if code == 0 else 'failed', exit_code=code)
                raise
            except BaseException as error:
                state.update(status='interrupted' if isinstance(error, KeyboardInterrupt) else 'failed',
                             exit_code=130 if isinstance(error, KeyboardInterrupt) else 1,
                             error_type=type(error).__name__, error=redact(str(error)))
                traceback.print_exc()
                raise
            finally:
                state.update(finished_at=datetime.now(timezone.utc).isoformat(),
                             elapsed_seconds=round(time.monotonic() - started, 3))
                save()
