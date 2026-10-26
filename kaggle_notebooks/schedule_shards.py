"""Submit independent partitions with a durable ledger and account slot limits."""
import argparse
import hashlib
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

from commit_shard_versions import (
    ROOT, REPO_ROOT, load_plan, parse_credentials, load_credential,
    physical_partitions, partition_kernel_slug, render_shard_version, plan_for_part, render_part_version,
    write_version, run_push,
)
from generate_notebooks import pinned_checkout_source

TERMINAL = {'COMPLETE', 'ERROR', 'CANCEL_ACKNOWLEDGED', 'CANCELLED', 'NO_RUNS'}


def latest_revision():
    """Resolve GitHub main once, without changing the local checkout."""
    result = subprocess.run(
        ['git', 'ls-remote', '--exit-code', 'origin', 'refs/heads/main'],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=30,
    )
    revision = result.stdout.split()[0] if result.stdout.split() else ''
    if result.returncode or not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('Cannot resolve origin/main; check Git connectivity or supply --revision SHA')
    return revision


def select_revision(requested, previous):
    if requested is None and previous is not None:
        revision = previous['revision']
    elif requested in (None, 'latest'):
        revision = latest_revision()
    else:
        revision = requested
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('--revision must be latest or a full Git commit SHA')
    return revision


def status_name(value):
    return str(value.status).rsplit('.', 1)[-1].upper()


def save(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(state, indent=2), encoding='utf-8')
    for attempt in range(10):
        try:
            temporary.replace(path)
            break
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.2 * (attempt + 1))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--graph-profile',type=Path,help='Explicit graph experiment inputs/revision; isolated jobs and ledger')
    parser.add_argument('--push', action='store_true')
    parser.add_argument('--watch', action='store_true')
    parser.add_argument('--reuse-project-kb', action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument('--account', action='append', choices=['duyvu1105', 'duymign', 'vdduy1105'], default=[])
    parser.add_argument('--revision', help='Default: GitHub main for a new run, saved SHA when resuming; accepts latest or a full SHA')
    parser.add_argument('--source-bundle', type=Path, help='Embed an incremental Git bundle advertising --revision; requires its base in the cloned repo')
    parser.add_argument('--state', type=Path, default=REPO_ROOT / 'typepro_kernel_versions' / 'latest_run.json')
    parser.add_argument('--new-run', action='store_true', help='Prepare a fresh dry-run and archive the previous ledger')
    parser.add_argument('--max-active', type=int, default=5)
    parser.add_argument('--jobs-per-account', type=int)
    parser.add_argument('--skip-jobs-per-account', type=int, default=0)
    parser.add_argument('--poll-seconds', type=int, default=60)
    args = parser.parse_args()
    if args.new_run and args.push:
        parser.error('Run --new-run without --push first, then submit with --push --watch')
    if not 1 <= args.max_active <= 5:
        parser.error('--max-active must be 1..5')
    if args.jobs_per_account is not None and args.jobs_per_account < 1:
        parser.error('--jobs-per-account must be >= 1')
    if args.skip_jobs_per_account < 0:
        parser.error('--skip-jobs-per-account must be >= 0')
    graph_plan = None
    if args.graph_profile:
        from graph_profile import render_profile
        if args.source_bundle:
            parser.error('Graph profiles require an available exact experiment SHA; source bundles are not supported')
        if args.state == REPO_ROOT/'typepro_kernel_versions'/'latest_run.json':
            args.state = REPO_ROOT/'typepro_kernel_versions'/'graph-context-v1'/'latest_run.json'
        if args.state.resolve() == (REPO_ROOT/'typepro_kernel_versions'/'latest_run.json').resolve():
            parser.error('Graph experiment cannot use the production scheduler ledger')
        graph_plan=render_profile(args.graph_profile,args.state.parent,args.revision)
        args.revision=graph_plan['revision']
    previous = json.loads(args.state.read_text(encoding='utf-8')) if args.state.exists() else None
    if (previous is not None and not args.new_run
            and previous.get('reuse_project_kb', False) != args.reuse_project_kb):
        parser.error('KB reuse differs from saved ledger; use a fresh --state')
    try:
        args.revision = select_revision(args.revision, None if args.new_run else previous)
    except ValueError as error:
        parser.error(str(error))
    bundle = args.source_bundle.read_bytes() if args.source_bundle else None
    bundle_sha256 = hashlib.sha256(bundle).hexdigest() if bundle is not None else None
    if args.source_bundle:
        heads = subprocess.run(['git', 'bundle', 'list-heads', str(args.source_bundle.resolve())],
                               cwd=REPO_ROOT, capture_output=True, text=True, check=True)
        if not any(line.split()[0] == args.revision for line in heads.stdout.splitlines()):
            parser.error('Source bundle does not advertise the requested revision')
        subprocess.run(['git', 'bundle', 'verify', str(args.source_bundle.resolve())],
                       cwd=REPO_ROOT, capture_output=True, text=True, check=True)
    if previous is not None and not args.new_run and previous.get('source_bundle_sha256') != bundle_sha256:
        parser.error('Source bundle differs from saved ledger; supply the same bundle or use a new state')
    _, _, plans = load_plan(ROOT / 'shard_account_plan.json')
    if not all(plan.independent_parts for plan in plans):
        parser.error('Scheduling requires independent partition kernels')
    credentials = parse_credentials([], plans)
    if graph_plan:
        jobs=graph_plan['jobs']
    else:
        jobs = []
        jobs_by_account = {}
        seen_by_account = {}
        for plan in plans:
            template = json.loads(plan.notebook_path.read_text(encoding='utf-8'))
            for part, (index, count) in enumerate(physical_partitions(plan.assigned_shards[0])):
                part_plan = plan_for_part(plan, part)
                seen_jobs = seen_by_account.get(part_plan.runner_account, 0)
                seen_by_account[part_plan.runner_account] = seen_jobs + 1
                if seen_jobs < args.skip_jobs_per_account:
                    continue
                account_jobs = jobs_by_account.get(part_plan.runner_account, 0)
                if args.jobs_per_account is not None and account_jobs >= args.jobs_per_account:
                    continue
                rendered = render_part_version(template, plan, part, reuse_project_kb=args.reuse_project_kb)
                clone_cells = [cell for cell in rendered['cells'] if '"git", "clone"' in ''.join(cell.get('source', []))]
                if len(clone_cells) != 1:
                    raise ValueError('Expected exactly one clone cell')
                source = ''.join(clone_cells[0]['source'])
                marker = '\nPIPELINE_DIR = '
                if marker not in source:
                    raise ValueError('Expected pipeline setup after repository checkout')
                checkout = pinned_checkout_source(args.revision, bundle)
                clone_cells[0]['source'] = source.replace(marker, checkout + marker, 1)
                rendered.setdefault('metadata', {}).setdefault('typepro', {}).update(
                    source_revision=args.revision, source_bundle_sha256=bundle_sha256)
                directory = args.state.parent / 'scheduled' / part_plan.runner_account / f'{index:02d}'
                write_version(directory, part_plan, rendered, part_index=part)
                jobs.append({'account': part_plan.runner_account, 'kernel': f'{part_plan.runner_account}/{partition_kernel_slug(part_plan, part)}',
                             'shard_index': index, 'shard_count': count, 'dataset': f'{part_plan.dataset_owner}/typepro-build-shard-{index:02d}' + ('-of-40' if count == 40 else ''),
                             'payload': str(directory), 'status': 'pending'})
                jobs_by_account[part_plan.runner_account] = account_jobs + 1
    state = previous if previous is not None and not args.new_run else {
        'revision': args.revision, 'source_bundle_sha256': bundle_sha256,
        'reuse_project_kb': args.reuse_project_kb, 'jobs': jobs,
        'graph_profile': graph_plan['profile'] if graph_plan else None}
    if state.get('graph_profile') != (graph_plan['profile'] if graph_plan else None):
        raise ValueError('Experiment profile differs from saved ledger')
    if state['revision'] != args.revision or [j['kernel'] for j in state['jobs']] != [j['kernel'] for j in jobs]:
        raise ValueError('Ledger does not match this revision/plan; use --new-run or a new --state file')
    if any(job['status'] == 'submitting' for job in state['jobs']):
        raise ValueError('Ambiguous prior submission; inspect kernel version before updating ledger')
    if args.new_run and previous is not None:
        archive = args.state.with_name(args.state.stem + '-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
        save(archive, previous)
    save(args.state, state)
    if not args.push:
        print(json.dumps({'revision': args.revision, 'state': str(args.state), 'jobs': state['jobs']}, indent=2))
        return
    with tempfile.TemporaryDirectory(prefix='typepro_scheduler_auth_') as auth_dir:
        while True:
            for account, credential_path in credentials.items():
                if args.account and account not in args.account:
                    continue
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
            pending = sum(job['status'] == 'pending' and (not args.account or job['account'] in args.account) for job in state['jobs'])
            print(json.dumps({'pending': pending, 'state': str(args.state)}), flush=True)
            if not pending or not args.watch:
                break
            time.sleep(max(10, args.poll_seconds))


if __name__ == '__main__':
    main()
