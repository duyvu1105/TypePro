"""Automatic graph Dataset verification and merge lifecycle for graph runs."""
from datetime import datetime, timezone
import json
import re
import time
from pathlib import Path

from commit_shard_versions import run_push


MERGE_REF = 'duyvu1105/merge-dataset'
FINAL_REF = 'duyvu1105/typepro-graph-v1-final'
FAILED = {'ERROR', 'CANCELLED', 'CANCEL_ACKNOWLEDGED', 'NO_RUNS'}


def kernel_version(api, ref):
    from kagglesdk.kernels.types.kernels_api_service import ApiGetKernelRequest
    request = ApiGetKernelRequest()
    request.user_name, request.kernel_slug = ref.split('/')
    with api.build_kaggle_client() as client:
        result = client.kernels.kernels_api_client.get_kernel(request)
    return int(result.metadata.current_version_number)


def exact_dataset(api, reference):
    owner, slug = reference.split('/')
    for page in range(1, 101):
        items = api.dataset_list(user=owner, search=slug, page=page)
        for item in items:
            if item.ref == reference:
                return item
        if len(items) < 20:
            return None
    raise RuntimeError('Dataset listing exceeded pagination limit: ' + reference)


def graph_payload_present(names):
    return 'graph-dataset.zip' in names or {'manifest.json', 'outcomes.jsonl'} <= names


def dataset_files(api, reference):
    names, token = set(), None
    for _ in range(100):
        for attempt in range(6):
            try:
                result = api.dataset_list_files(reference, page_size=100,
                                                **({'page_token': token} if token else {}))
                break
            except Exception as error:
                response = getattr(error, 'response', None)
                if response is not None and response.status_code in (429, 502, 503, 504) and attempt < 5:
                    time.sleep(min(60, 10 * (attempt + 1)))
                    continue
                raise
        names.update(item.name for item in result.files)
        if graph_payload_present(names):
            break
        token = result.next_page_token
        if not token:
            break
    return names


def version_from_output(output):
    match = re.search(r'Kernel version (\d+)', output)
    if not match:
        raise RuntimeError('Kaggle did not report the submitted merge version')
    return int(match.group(1))


def merge_tick(api, credential, auth_dir, state, persist, merge_dir, bundle):
    merge = state.setdefault('merge', {'phase': 'waiting_shards'})
    phase = merge['phase']
    if phase == 'complete':
        return True
    if phase in ('submitting', 'error'):
        raise RuntimeError('Graph merge needs inspection: ' + json.dumps(merge))

    if phase == 'waiting_shards':
        failed = [j['kernel'] for j in state['jobs'] if j.get('remote_status') in FAILED]
        if failed:
            merge.update(phase='error', error='Graph shard failed: ' + ', '.join(failed))
            persist()
            raise RuntimeError(merge['error'])
        incomplete = [j['kernel'] for j in state['jobs']
                      if j.get('status') != 'submitted' or j.get('remote_status') != 'COMPLETE']
        if incomplete:
            merge.update(waiting_for=incomplete, checked_at=datetime.now(timezone.utc).isoformat())
            persist()
            return False
        datasets = {}
        for job in state['jobs']:
            expected = version_from_output(job.get('cli_output', ''))
            actual = kernel_version(api, job['kernel'])
            status = str(api.kernels_status(job['kernel']).status).rsplit('.', 1)[-1].upper()
            if actual != expected or status != 'COMPLETE':
                raise RuntimeError(f"Shard version/status changed: {job['kernel']} expected v{expected}, got v{actual} {status}")
            item = exact_dataset(api, job['dataset'])
            if item is None or int(item.current_version_number) <= job.get('dataset_baseline', -1):
                merge.update(waiting_for_dataset=job['dataset'])
                persist()
                return False
            names = dataset_files(api, job['dataset'])
            if not graph_payload_present(names):
                merge.update(waiting_for_dataset_files=job['dataset'], files=sorted(names))
                persist()
                return False
            datasets[job['dataset']] = int(item.current_version_number)

        try:
            status = str(api.kernels_status(MERGE_REF).status).rsplit('.', 1)[-1].upper()
            if status not in FAILED | {'COMPLETE'}:
                merge.update(waiting_reason='Graph merge kernel is already active')
                persist()
                return False
        except Exception as error:
            response = getattr(error, 'response', None)
            if response is None or response.status_code != 404:
                raise
        previous = exact_dataset(api, FINAL_REF)
        previous_version = int(previous.current_version_number) if previous else 0
        merge.update(phase='submitting', input_versions=datasets,
                     previous_final_version=previous_version)
        persist()
        output = run_push(merge_dir, credential, auth_dir)
        merge.update(phase='submitted', version=version_from_output(output), cli_output=output)
        persist()
        print(json.dumps({'graph_merge': merge}), flush=True)
        return False

    actual = kernel_version(api, MERGE_REF)
    if actual != merge['version']:
        raise RuntimeError(f"Graph merge version changed: expected {merge['version']}, got {actual}")
    status = str(api.kernels_status(MERGE_REF).status).rsplit('.', 1)[-1].upper()
    merge['remote_status'] = status
    if status in FAILED:
        merge.update(phase='error', error='Graph merge ended with ' + status)
        persist()
        raise RuntimeError(merge['error'])
    if status == 'COMPLETE':
        current = exact_dataset(api, FINAL_REF)
        names = dataset_files(api, FINAL_REF) if current else set()
        if current and int(current.current_version_number) > merge['previous_final_version'] and graph_payload_present(names):
            merge.update(phase='complete', final_version=int(current.current_version_number),
                         final_files=sorted(names))
        else:
            merge.update(phase='error', error='Merge COMPLETE without a new verified graph Dataset',
                         final_files=sorted(names))
            persist()
            raise RuntimeError(merge['error'])
    persist()
    return merge['phase'] == 'complete'
