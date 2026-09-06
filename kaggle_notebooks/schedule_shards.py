"""Submit independent partitions with a durable ledger and account slot limits."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
import time

from commit_shard_versions import (
    ROOT, REPO_ROOT, load_plan, parse_credentials, load_credential,
    physical_partitions, partition_kernel_slug, render_shard_version,
    write_version, run_push,
)

TERMINAL = {'COMPLETE', 'ERROR', 'CANCEL_ACKNOWLEDGED', 'CANCELLED', 'NO_RUNS'}


def status_name(value):
    return str(value.status).rsplit('.', 1)[-1].upper()


def save(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(state, indent=2), encoding='utf-8')
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--push', action='store_true')
    parser.add_argument('--watch', action='store_true')
    parser.add_argument('--revision', required=True)
    parser.add_argument('--state', type=Path, default=REPO_ROOT / 'typepro_kernel_versions' / 'rerun_state.json')
    parser.add_argument('--max-active', type=int, default=5)
    parser.add_argument('--poll-seconds', type=int, default=60)
    args = parser.parse_args()
    if not re.fullmatch(r'[0-9a-f]{40}', args.revision):
        parser.error('--revision must be a full Git commit SHA')
    if not 1 <= args.max_active <= 5:
        parser.error('--max-active must be 1..5')
    _, _, plans = load_plan(ROOT / 'shard_account_plan.json')
    if not all(plan.independent_parts for plan in plans):
        parser.error('Scheduling requires independent partition kernels')
    credentials = parse_credentials([], plans)
    jobs = []
    for plan in plans:
        template = json.loads(plan.notebook_path.read_text(encoding='utf-8'))
        for part, (index, count) in enumerate(physical_partitions(plan.assigned_shards[0])):
            rendered = render_shard_version(template, plan.assigned_shards[0], plan.assigned_shards,
                plan.dataset_owner, plan.public_dataset, physical_shard_index=index, physical_shard_count=count)
            clone_cells = [cell for cell in rendered['cells'] if '"git", "clone"' in ''.join(cell.get('source', []))]
            if len(clone_cells) != 1:
                raise ValueError('Expected exactly one clone cell')
            source = ''.join(clone_cells[0]['source'])
            clone_cells[0]['source'] = source + '\nrun(["git", "-C", REPO_DIR, "checkout", "--detach", ' + repr(args.revision) + '])\n'
            directory = args.state.parent / 'scheduled' / plan.runner_account / f'{index:02d}'
            write_version(directory, plan, rendered, part_index=part)
            jobs.append({'account': plan.runner_account, 'kernel': f'{plan.runner_account}/{partition_kernel_slug(plan, part)}',
                         'shard_index': index, 'shard_count': count, 'dataset': f'{plan.dataset_owner}/typepro-build-shard-{index:02d}',
                         'payload': str(directory), 'status': 'pending'})
    if not args.push:
        print(json.dumps({'revision': args.revision, 'jobs': jobs}, indent=2))
        return
    state = json.loads(args.state.read_text()) if args.state.exists() else {'revision': args.revision, 'jobs': jobs}
    if state['revision'] != args.revision or [j['kernel'] for j in state['jobs']] != [j['kernel'] for j in jobs]:
        raise ValueError('Ledger does not match this revision/plan; use a new state file')
    if any(job['status'] == 'submitting' for job in state['jobs']):
        raise ValueError('Ambiguous prior submission; inspect kernel version before updating ledger')
    save(args.state, state)
    with tempfile.TemporaryDirectory(prefix='typepro_scheduler_auth_') as auth_dir:
        while True:
            for account, credential_path in credentials.items():
                credential = load_credential(credential_path, account)
                os.environ['KAGGLE_CONFIG_DIR'] = auth_dir
                os.environ['KAGGLE_USERNAME'] = credential['username']
                os.environ['KAGGLE_KEY'] = credential['key']
                os.environ.pop('KAGGLE_API_TOKEN', None)
                from kaggle.api.kaggle_api_extended import KaggleApi
                api = KaggleApi()
                api.authenticate()
                kernels = []
                for page in range(1, 101):
                    batch = api.kernels_list(mine=True, page=page, page_size=100, sort_by='dateRun')
                    kernels.extend(batch)
                    if len(batch) < 100:
                        break
                else:
                    raise RuntimeError('Account kernel listing exceeded pagination limit')
                run_times = {kernel.ref: str(kernel.last_run_time) for kernel in kernels}
                refs = set(run_times)
                submitted_refs = {job['kernel'] for job in state['jobs'] if job['account'] == account and job['status'] != 'pending'}
                refs.update(submitted_refs)
                def check(ref):
                    cache = state.setdefault('status_cache', {})
                    cached = cache.get(ref, {})
                    if ref not in submitted_refs and cached.get('run_time') == run_times.get(ref) and cached.get('status') in TERMINAL:
                        return ref, cached['status']
                    for attempt in range(6):
                        try:
                            status = status_name(api.kernels_status(ref))
                            break
                        except Exception as error:
                            response = getattr(error, 'response', None)
                            if response is not None and response.status_code == 404 and 'No runs found for this kernel' in response.text:
                                status = 'NO_RUNS'
                                break
                            if response is not None and response.status_code in (429, 502, 503, 504) and attempt < 5:
                                print(f'Waiting for Kaggle API rate limit: {ref}', flush=True)
                                time.sleep(min(60, 10 * (attempt + 1)))
                                continue
                            raise
                    cache[ref] = {'run_time': run_times.get(ref), 'status': status}
                    save(args.state, state)
                    time.sleep(0.5)
                    return ref, status
                statuses = dict(check(ref) for ref in sorted(refs))
                active = {ref for ref, status in statuses.items() if status not in TERMINAL}
                for job in state['jobs']:
                    if job['account'] == account and job['status'] != 'pending':
                        job['remote_status'] = statuses.get(job['kernel'], 'UNKNOWN')
                slots = max(0, args.max_active - len(active))
                print(json.dumps({'account': account, 'active': sorted(active), 'free_slots': slots}), flush=True)
                for job in state['jobs']:
                    if job['account'] != account or job['status'] != 'pending' or slots == 0:
                        continue
                    if job['kernel'] in active:
                        continue
                    job['status'] = 'submitting'
                    save(args.state, state)
                    output = run_push(Path(job['payload']), credential, Path(auth_dir))
                    job.update(status='submitted', cli_output=output, submitted_at=datetime.now(timezone.utc).isoformat())
                    save(args.state, state)
                    job['remote_status'] = status_name(api.kernels_status(job['kernel']))
                    slots -= 1  # Reserve the slot even if status propagation is delayed.
                    print(json.dumps(job), flush=True)
                save(args.state, state)
            pending = sum(job['status'] == 'pending' for job in state['jobs'])
            print(json.dumps({'pending': pending, 'state': str(args.state)}), flush=True)
            if not pending or not args.watch:
                break
            time.sleep(max(10, args.poll_seconds))


if __name__ == '__main__':
    main()
