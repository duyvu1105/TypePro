"""Measure graph/v24 prompt and source-evidence tokens on identical local sources.

Fixtures are development tests, not a dataset holdout or a model accuracy result.
No downloads, model inference, gold-based selection, or policy tuning is performed.
"""
from __future__ import annotations
import argparse
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path
from statistics import median
import tempfile
import time

from typepro.analysis.evidence_graph import TargetSpec, digest
from typepro.analysis.graph_context import GraphContextProject
from typepro.analysis.graph_render import render_groups
from typepro.analysis.target_context import render_masks
from typepro.audit.regressions import CASES, replay
from typepro.data.preprocess import format_input, normalized_recommendations
from typepro.shared.context_packing import tokenizer_fingerprint
from typepro.shared.generative_chat import chat_token_ids


def independent_cases():
    return [
        dict(id='straight_line_noise',function='f',name='f',scope='return',sources={'m.py':
             'def f(value: object) -> HiddenGold:\n'+''.join(f'    unused_{i} = {i}\n' for i in range(30))+'    return value\n'}),
        dict(id='reassignment',function='f',name='f',scope='return',sources={'m.py':
             'def f() -> HiddenGold:\n    value = 1\n    value = "replacement"\n    return value\n'}),
        dict(id='branch_join',function='f',name='f',scope='return',sources={'m.py':
             'def f(flag: bool) -> HiddenGold:\n    if flag:\n        value = 1\n    else:\n        value = "text"\n    return value\n'}),
        dict(id='loop_mutation',function='f',name='f',scope='return',sources={'m.py':
             'def f(values: list) -> HiddenGold:\n    result = []\n    for value in values:\n        result.append(value)\n    return result\n'}),
        dict(id='documented_helper',function='f',name='f',scope='return',sources={'m.py':
             'def helper(value: str) -> str:\n    """Return the supplied text without changing it."""\n    return value\n\ndef f(value: str) -> HiddenGold:\n    """Target documentation stays in context."""\n    unused = 42\n    return helper(value)\n'}),
        dict(id='arg_callers',function='f',name='value',scope='arg',sources={'m.py':
             'def f(value: HiddenGold) -> object:\n    return value\n\ndef caller() -> object:\n    return f({"name": "example"})\n'}),
        dict(id='class_field',function='f',name='f',scope='return',sources={'m.py':
             'class Owner:\n    value: str\n    unrelated: int\n    def __init__(self, value: str):\n        self.value = value\n    def f(self) -> HiddenGold:\n        return self.value\n'}),
        dict(id='dynamic_receiver',function='f',name='f',scope='return',sources={'m.py':
             'def f(service, key: str) -> HiddenGold:\n    response = service.fetch(key)\n    return response.payload\n'}),
    ]


def token_count(tokenizer,text):
    return len(tokenizer.encode(text,add_special_tokens=False))


def summarize(rows):
    comparable=[r for r in rows if r.get('graph_prompt_tokens') is not None and r.get('v24_prompt_tokens') is not None]
    if not comparable:
        return dict(targets=len(rows),comparable=0)
    before=sum(r['v24_prompt_tokens'] for r in comparable)
    after=sum(r['graph_prompt_tokens'] for r in comparable)
    source_before=sum(r['v24_evidence_tokens'] for r in comparable)
    source_after=sum(r['graph_evidence_tokens'] for r in comparable)
    ratios=[r['graph_prompt_tokens']/r['v24_prompt_tokens'] for r in comparable]
    return dict(targets=len(rows),comparable=len(comparable),
        smaller=sum(r['graph_prompt_tokens']<r['v24_prompt_tokens'] for r in comparable),
        larger=sum(r['graph_prompt_tokens']>r['v24_prompt_tokens'] for r in comparable),
        equal=sum(r['graph_prompt_tokens']==r['v24_prompt_tokens'] for r in comparable),
        v24_total_prompt_tokens=before,graph_total_prompt_tokens=after,
        total_prompt_change_percent=100*(after/before-1),median_prompt_change_percent=100*(median(ratios)-1),
        v24_total_evidence_tokens=source_before,graph_total_evidence_tokens=source_after,
        evidence_change_percent=100*(source_after/source_before-1),
        common_format_v24_tokens=sum(r['v24_common_format_tokens'] for r in comparable),
        common_format_graph_tokens=sum(r['graph_common_format_tokens'] for r in comparable),
        common_format_change_percent=100*(sum(r['graph_common_format_tokens'] for r in comparable)/sum(r['v24_common_format_tokens'] for r in comparable)-1),
        graph_outcomes=dict(Counter(r['graph_outcome'] for r in rows if 'graph_outcome' in r)),
        v24_overbudget=sum(r.get('v24_overbudget',False) for r in rows),
        graph_overbudget=sum(r.get('graph_outcome')=='budget_exceeded' for r in rows))


def run(tokenizer,output,input_length=6144,label_length=64):
    from typepro.analysis.graph_builder import functions
    import ast
    output=Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError('Keep prior measurements; choose a new empty output directory')
    output.mkdir(parents=True,exist_ok=True)
    cases=[]
    for case in independent_cases():
        cases.append(dict(case,project='synthetic/'+case['id'],file='m.py',required=[],group='independent_synthetic'))
    cases.extend(dict(case,group='development_known') for case in CASES)
    rows=[]
    with tempfile.TemporaryDirectory(prefix='typepro-graph-size-') as directory:
        for case in cases:
            started=time.monotonic()
            row=dict(id=case['id'],group=case['group'],scope=case['scope'],source_hash=digest(case['sources']))
            try:
                old=replay(case,Path(directory)/case['id'])
                recommendations=normalized_recommendations({'recommendation_types':old['candidates']},10)
                source=case['sources'][case['file']]
                matches=[(q,n) for q,n in functions(ast.parse(source)) if n.name==case['function']]
                if len(matches)!=1:
                    raise ValueError('Fixture function identity is ambiguous')
                qualified=matches[0][0]
                target=TargetSpec(case['project'],case['file'],qualified,case['scope'],case['name'])
                from typepro.analysis.project_index import project_module_aliases
                graph=GraphContextProject(case['project'],case['sources'],'fixture:'+row['source_hash'],
                                          'no-external-dependency-kb',module_aliases=project_module_aliases(Path(directory)/case['id'])).query(target,tokenizer,input_length,label_length)
                old_prompt=format_input(case['name'],qualified,case['scope'],old['slice'],recommendations)
                old_evidence='\n\n'.join([old['slice'],*[r['definition'] for r in recommendations]])
                retained=set(graph['audit']['retained_groups']) if 'audit' in graph else set()
                graph_evidence='\n\n'.join(render_masks(g['text']) for g in graph.get('full_evidence',[]) if g['id'] in retained)
                graph_tokens=graph.get('audit',{}).get('prompt_tokens')
                row.update(v24_prompt_tokens=len(chat_token_ids(tokenizer,old_prompt)),
                           graph_prompt_tokens=graph_tokens,v24_slice_tokens=token_count(tokenizer,old['slice']),
                           v24_candidate_tokens=token_count(tokenizer,'\n\n'.join(r['definition'] for r in recommendations)),
                           v24_evidence_tokens=token_count(tokenizer,old_evidence),graph_evidence_tokens=token_count(tokenizer,graph_evidence),
                           v24_common_format_tokens=len(chat_token_ids(tokenizer,format_input(case['name'],qualified,case['scope'],old_evidence,[]))),
                           graph_common_format_tokens=len(chat_token_ids(tokenizer,format_input(case['name'],qualified,case['scope'],graph_evidence,[]))),
                           graph_outcome=graph['outcome'],graph_unresolved_count=len(graph['gaps']),
                           graph_mandatory_tokens=graph.get('audit',{}).get('mandatory_tokens'),
                           v24_candidate_count=len(recommendations),
                           graph_group_count=len(retained),
                           v24_overbudget=len(chat_token_ids(tokenizer,old_prompt))>input_length-label_length,
                           elapsed_seconds=time.monotonic()-started)
                checks=[]
                for where,evidence in case.get('required',()):
                    checks.append(dict(evidence=evidence,v24_present=evidence in old_evidence,graph_present=evidence in graph_evidence))
                row['development_evidence_checks']=checks
                row['prompt_change_percent']=100*(graph_tokens/row['v24_prompt_tokens']-1) if graph_tokens is not None else None
                (output/(case['id']+'.json')).write_text(json.dumps(dict(metrics=row,v24_prompt=old_prompt,
                    graph_prompt=graph.get('input'),graph_full_evidence=graph.get('full_evidence'),gaps=graph['gaps']),indent=2)+'\n')
            except Exception as error:
                row['error']=f'{type(error).__name__}: {error}'
            rows.append(row)
    import hashlib
    source_root=Path(__file__).resolve().parents[2]
    paths=[*source_root.glob('typepro/analysis/graph*.py'),source_root/'typepro/analysis/evidence_graph.py',source_root/'typepro/shared/context_packing.py']
    import subprocess
    revision=subprocess.check_output(['git','-C',str(source_root),'rev-parse','HEAD'],text=True).strip()
    report=dict(experiment_head=revision,baseline_source_sha='a498310a55833428e67e63f3c94b8b9a8a33ed92',implementation_fingerprint={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},description='Same-source v24 versus graph; development fixtures, no accuracy claim',
                tokenizer_fingerprint=tokenizer_fingerprint(tokenizer),input_length=input_length,label_length=label_length,
                summary=summarize(rows),by_group={group:summarize([r for r in rows if r['group']==group])
                                                for group in ('independent_synthetic','development_known')},rows=rows)
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    lines=['# Graph versus v24 context size','',
           'Same source and Qwen tokenizer; untruncated complete chat prompts. This is a local fixture comparison, not a dataset-wide result.','',
           '| Case | Group | v24 prompt | Graph prompt | Change | v24 evidence | Graph evidence | Graph outcome |',
           '| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |']
    for r in rows:
        if 'error' in r:
            lines.append(f"| {r['id']} | {r['group']} | | | | | | ERROR: {r['error']} |")
        else:
            lines.append(f"| {r['id']} | {r['group']} | {r['v24_prompt_tokens']} | {r['graph_prompt_tokens']} | {r['prompt_change_percent']:+.1f}% | {r['v24_evidence_tokens']} | {r['graph_evidence_tokens']} | {r['graph_outcome']} |")
    lines+=['','```json',json.dumps(report['summary'],indent=2),'```','',
            'Source-evidence counts exclude each policy’s prompt headers but retain docstrings and selected candidate definitions. Graph source identity/excerpt wrappers remain included in the complete-prompt counts.',
            'A reduction is not evidence that correctness improved. Unresolved gaps and any missing support require review before model evaluation. No policy was tuned using these measurements.']
    (output/'report.md').write_text('\n'.join(lines)+'\n')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tokenizer',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    from transformers import AutoTokenizer
    tokenizer=AutoTokenizer.from_pretrained(args.tokenizer,local_files_only=True)
    report=run(tokenizer,args.output)
    print(json.dumps(dict(summary=report['summary'],by_group=report['by_group'],errors=[r for r in report['rows'] if 'error' in r]),indent=2))


if __name__=='__main__':
    main()
