"""Publish verified experiment datasets only to isolated graph slugs."""
from pathlib import Path
import re
import zipfile
from typepro.data.graph_dataset import verify_graph_dataset
from typepro.publishing.kaggle_dataset_utils import publish_dataset


def publish_graph_dataset(root, dataset_id, public=False):
    root=Path(root)
    manifest=verify_graph_dataset(root)
    slug=dataset_id.split('/')[-1]
    if not re.fullmatch(r'typepro-graph-v1-(?:data-\d+-of-\d+|final)',slug):
        raise ValueError('Refusing graph publication into a baseline Dataset slug')
    if '-data-' in slug:
        partition=manifest.get('partition',{})
        expected=f"typepro-graph-v1-data-{partition.get('shard_index',-1):02d}-of-{partition.get('shard_count',-1):02d}"
        if slug!=expected:
            raise ValueError('Graph Dataset slug/partition mismatch')
    if slug.endswith('-final') and (public or dataset_id!='duyvu1105/typepro-graph-v1-final'):
        raise ValueError('Final experiment Dataset must be private under duyvu1105')
    payload=root.parent/(root.name+'-publish')
    payload.mkdir(exist_ok=True)
    archive=payload/'graph-dataset.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(root.rglob('*')):
            if path.is_file() and not path.is_symlink():
                bundle.write(path,path.relative_to(root).as_posix())
    return publish_dataset(payload,dataset_id,slug,'Verified graph-context-v1 outcome ledger and source evidence',public=public)
