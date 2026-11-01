"""Prepare configuration C and run the v24 recipe from a pinned source snapshot."""
from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from typepro.training.type_changing import POLICY as EXPRESSION_POLICY, sha256
from typepro.training.contract_changing import POLICY as CONTRACT_POLICY, build

CODE_FILES = {EXPRESSION_POLICY: 'typepro/training/type_changing.py',
              CONTRACT_POLICY: 'typepro/training/contract_changing.py'}


def process_identity(pid):
    """Linux process birth time prevents waiting on a reused PID."""
    try:
        stat = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return None if stat[0] == 'Z' else stat[19]
    except FileNotFoundError:
        return None


def gpu_busy():
    output = subprocess.check_output([
        'nvidia-smi', '--id=0', '--query-compute-apps=pid', '--format=csv,noheader,nounits',
    ], text=True)
    return any(line.strip().isdigit() for line in output.splitlines())


def validate_data(data, baseline, code_path=None):
    audit = json.loads((data / 'type_intervention_audit.json').read_text())
    if audit['policy'] not in CODE_FILES or audit['seed'] != baseline['seed']:
        raise ValueError('Augmentation policy/seed mismatch')
    if audit['source_splits'] != baseline['dataset_splits']:
        raise ValueError('Source differs from baseline')
    if audit['code_sha256'] != sha256(code_path or ROOT / CODE_FILES[audit['policy']]):
        raise ValueError('Dataset was generated with different augmentation code')
    if audit['counts']['original_rows'] != baseline['dataset_splits']['train']['rows']:
        raise ValueError('Original training row count changed')
    if not audit['counts']['synthetic_rows']:
        raise ValueError('Configuration C requires synthetic examples')
    for split in ('train', 'validation', 'test'):
        if sha256(data / f'{split}.jsonl') != audit['output_hashes'][split]:
            raise ValueError(f'{split} hash mismatch')
        if split != 'train' and audit['output_hashes'][split] != baseline['dataset_splits'][split]['sha256']:
            raise ValueError('Validation/test must be byte-identical to baseline')
        if sha256(Path(baseline['data_dir']) / f'{split}.jsonl') != baseline['dataset_splits'][split]['sha256']:
            raise ValueError('Baseline source changed')
    verification = data / 'contract_transport_verification.json'
    if audit['policy'] == CONTRACT_POLICY and verification.is_file():
        report = json.loads(verification.read_text())
        if not report.get('passed') or report.get('output_hashes') != audit['output_hashes']:
            raise ValueError('Independent dataset verification failed or is stale')
        audit['independent_verification'] = report
    return audit


def require_training_ready(audit, baseline):
    """Do not repeat the cancelled, under-covered 133-example pilot."""
    if audit['policy'] != CONTRACT_POLICY or not audit.get('readiness', {}).get('passed'):
        raise ValueError('Dataset has not passed the contract-transport coverage gate; prepare data only')
    if audit['tokenizer'] != baseline['model'] or audit['limits']['prompt_limit'] != baseline['input_length'] - baseline['label_length']:
        raise ValueError('Token audit differs from the requested model/context budget')
    if not audit.get('independent_verification', {}).get('passed'):
        raise ValueError('Run the independent contract-changing dataset audit before training')
    if audit['independent_verification'].get('label_length') != baseline['label_length']:
        raise ValueError('Independent annotation budget differs from requested label length')


def command_for(baseline, data, output):
    command = [sys.executable, '-m', 'accelerate.commands.launch', '--num_machines', '1',
               '--num_processes', '1', '--mixed_precision', baseline['mixed_precision'],
               '-m', 'typepro', 'finetune', '--data-dir', str(data),
               '--output-dir', str(output), '--model-name', baseline['model']]
    for key in ('input_length', 'label_length', 'epochs', 'batch_size',
                'gradient_accumulation_steps', 'learning_rate', 'seed', 'mixed_precision'):
        command.extend(['--' + key.replace('_', '-'), str(baseline[key])])
    # Match the historical v24 launcher, including its length-grouped sampler.
    command.extend(['--attn-implementation', 'sdpa', '--gradient-checkpointing',
                    '--group-by-length', '--length-cache', '--length-log-every', '1000',
                    '--preview-samples', '0', '--log-every', '50',
                    '--inference-batch-size', '1', '--infer-after-training'])
    return command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-output', type=Path, default=ROOT / 'outputs/qwen25-coder-05b-v24-6k-2ep')
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'datasets/typepro-python-generative-v24-contract-changing-c-s13')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'outputs/qwen25-coder-05b-v24-6k-2ep-type-changing-c')
    parser.add_argument('--wait-for-pid', type=int)
    parser.add_argument('--wait-for-idle-gpu', action='store_true', help='Opt in to waiting for GPU 0; otherwise start immediately')
    parser.add_argument('--data-workers', type=int, default=4, help='CPU workers used only if the derived dataset needs generating')
    parser.add_argument('--prepare-only', action='store_true', help='Generate and validate data, without reserving an output')
    args = parser.parse_args()
    baseline = json.loads((args.baseline_output / 'launch_config.json').read_text())
    data, output = args.data_dir.resolve(), args.output_dir.resolve()
    if output.exists() and not args.prepare_only:
        raise FileExistsError(output)
    if not data.exists():
        from transformers import AutoTokenizer
        tokenizer = AutoTokenizer.from_pretrained(baseline['model'], local_files_only=True)
        build(baseline['data_dir'], data, baseline['seed'], tokenizer=tokenizer,
              prompt_limit=baseline['input_length'] - baseline['label_length'],workers=args.data_workers)
    audit = validate_data(data, baseline)
    command = command_for(baseline, data, output)
    if args.prepare_only:
        print(json.dumps(dict(status='validated', counts=audit['counts'], command=command), indent=2))
        return
    require_training_ready(audit, baseline)
    dirty = subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True)
    if dirty.strip():
        raise ValueError('Commit source changes before launching the pinned experiment')
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    birth = process_identity(args.wait_for_pid) if args.wait_for_pid else None
    output.mkdir(parents=True, exist_ok=False)
    snapshot = output / 'source_snapshot'
    snapshot.mkdir()
    archive = subprocess.check_output([
        'git', 'archive', revision, 'typepro', 'pyproject.toml', 'requirements',
        'ssh_notebooks/run_type_changing.py',
    ], cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(snapshot, filter='data')
    cfg = dict(baseline, data_dir=str(data), output_dir=str(output),
               dataset_splits={s: dict(file=f'{s}.jsonl', sha256=audit['output_hashes'][s],
                                      rows=(audit['counts']['original_rows'] + audit['counts']['synthetic_rows']
                                            if s == 'train' else baseline['dataset_splits'][s]['rows']))
                               for s in ('train', 'validation', 'test')},
               configuration='C: original + checked return-contract transport', augmentation=audit,
               baseline_output=str(args.baseline_output.resolve()), git_revision=revision,
               source_snapshot=str(snapshot), command=command, group_by_length=True, length_cache=True,
               decoding=dict(do_sample=False, num_beams=1), wait_for_pid=args.wait_for_pid,
               wait_for_pid_birth=birth, wait_for_idle_gpu=args.wait_for_idle_gpu,
               budget_note='Same two epochs and hyperparameters; extra rows increase steps/tokens versus baseline.')
    (output / 'launch_config.json').write_text(json.dumps(cfg, indent=2) + '\n')

    def status(state, **fields):
        record = dict(status=state, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), **fields)
        temp = output / 'run_status.json.tmp'
        temp.write_text(json.dumps(record, indent=2) + '\n')
        temp.replace(output / 'run_status.json')
        print(json.dumps(record), flush=True)

    try:
        while True:
            predecessor = birth is not None and process_identity(args.wait_for_pid) == birth
            busy = args.wait_for_idle_gpu and gpu_busy()
            if not predecessor and not busy:
                break
            status('waiting', predecessor_running=predecessor, gpu_busy=busy)
            time.sleep(30)
        validate_data(data, baseline, snapshot / CODE_FILES[audit['policy']])
        status('training_and_inference')
        environment = dict(os.environ, CUDA_VISIBLE_DEVICES='0', TOKENIZERS_PARALLELISM='false',
                           PYTHONUNBUFFERED='1', PYTHONPATH=str(snapshot))
        with (output / 'train_tmux.log').open('w') as log:
            result = subprocess.run(command, cwd=snapshot, env=environment, stdout=log, stderr=subprocess.STDOUT)
        status('complete' if result.returncode == 0 else 'failed', exit_code=result.returncode)
        if result.returncode:
            raise SystemExit(result.returncode)
    except Exception as e:
        status('failed', error=str(e))
        raise


if __name__ == '__main__':
    main()
