"""Paired, project-bootstrap evaluation on a frozen outcome roster."""
from __future__ import annotations
import argparse
from collections import defaultdict, Counter
import json
import random
from statistics import median
from pathlib import Path
from typepro.data.graph_dataset import read_jsonl, sha256, verify_graph_dataset
from typepro.shared.type_labels import normalize_type_label


def quantile(values, probability):
    if not values:
        return None
    ordered=sorted(values)
    return ordered[round((len(ordered)-1)*probability)]


def compare(ledger, baseline_predictions, graph_predictions, bootstrap_samples=2000, seed=13):
    if bootstrap_samples < 1:
        raise ValueError('bootstrap_samples must be positive')
    def prediction_index(rows):
        result={}
        for row in rows:
            key=row.get('target_id') or row['id']
            if key in result:
                raise ValueError('Duplicate prediction identity')
            result[key]=row
        return result
    baseline=prediction_index(baseline_predictions)
    graph=prediction_index(graph_predictions)
    def correct(row,predictions):
        prediction=predictions.get(row['target_id'],predictions.get(row['id']))
        if prediction is None:
            return False
        try:
            return normalize_type_label(prediction['prediction'])==normalize_type_label(row['label'])
        except (ValueError,KeyError):
            return False
    records=[]
    tokens=[]
    runtimes=[]
    for row in ledger:
        if row.get('audit') and row['outcome'] in {'ready','unresolved'}:
            tokens.append(row['audit']['prompt_tokens'])
        runtimes.append(row.get('elapsed_seconds',0))
        before=correct(row,baseline)
        after=row['outcome'] in {'ready','unresolved'} and correct(row,graph)
        records.append(dict(project=row['target']['project'],scope=row['target']['scope'],
                            before=before,after=after,outcome=row['outcome'],
                            common_ready=(row['outcome'] in {'ready','unresolved'} and
                                          (row['target_id'] in baseline or row['id'] in baseline) and
                                          (row['target_id'] in graph or row['id'] in graph))))
    if not records:
        raise ValueError('Empty comparison roster')
    projects=defaultdict(list)
    for r in records:
        projects[r['project']].append(r)
    names=sorted(projects)
    rng=random.Random(seed)
    deltas=[]
    for _ in range(bootstrap_samples):
        sample=[row for name in rng.choices(names,k=len(names)) for row in projects[name]]
        deltas.append(sum(r['after']-r['before'] for r in sample)/len(sample))
    def metrics(rows):
        n=len(rows)
        return dict(targets=n, baseline_em=sum(r['before'] for r in rows)/n if n else None,
                    graph_em=sum(r['after'] for r in rows)/n if n else None,
                    fixes=sum(not r['before'] and r['after'] for r in rows),
                    regressions=sum(r['before'] and not r['after'] for r in rows))
    return dict(end_to_end=metrics(records),common_ready=metrics([r for r in records if r['common_ready']]),
                outcomes=dict(Counter(r['outcome'] for r in records)),
                by_scope={scope:metrics([r for r in records if r['scope']==scope]) for scope in ('arg','return')},
                by_project={p:metrics(rows) for p,rows in projects.items()},
                paired_project_bootstrap=dict(seed=seed,samples=bootstrap_samples,
                    delta_ci95=[quantile(deltas,.025),quantile(deltas,.975)]),
                tokens=dict(median=median(tokens) if tokens else None,p95=quantile(tokens,.95)),
                runtime_seconds=dict(median=median(runtimes),p95=quantile(runtimes,.95)),
                conclusion='inconclusive; acceptance thresholds and independent validation must be frozen before model comparison')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--graph-dataset',type=Path,required=True)
    parser.add_argument('--baseline-predictions',type=Path,required=True)
    parser.add_argument('--graph-predictions',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--baseline-sha',required=True)
    parser.add_argument('--experiment-sha',required=True)
    args=parser.parse_args()
    manifest=verify_graph_dataset(args.graph_dataset)
    result=compare(read_jsonl(args.graph_dataset/'outcomes.jsonl'),
                   read_jsonl(args.baseline_predictions),read_jsonl(args.graph_predictions))
    result.update(baseline_sha=args.baseline_sha,experiment_sha=args.experiment_sha,
                  graph_dataset_manifest_sha256=sha256(args.graph_dataset/'manifest.json'),
                  baseline_predictions_sha256=sha256(args.baseline_predictions),
                  graph_predictions_sha256=sha256(args.graph_predictions), fingerprints=manifest)
    args.output.write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':
    main()
