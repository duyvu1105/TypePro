# Graph context implementation and validation

Status: experimental implementation, not a production rollout or an accuracy
claim. Work is on `experiment/graph-context-v1`; baseline checkpoint is
`6f5d69f` and its source parent is the original v24 SHA
`a498310a55833428e67e63f3c94b8b9a8a33ed92`. No rollback was needed because the
initial main already matched that source exactly. Main contains only the plan
and baseline verification report added to that source.

## Implemented path

`TargetSpec` contains project, source path, qualified lexical function, scope,
parameter/return name, optional definition occurrence, and original record
identity. Labels are separate inputs to the exporter and are attached after
selection. Duplicate metadata records are preserved; ambiguous repeated source
definitions fail with `target_not_found` unless an occurrence is provided.

The graph path is independent of the historical slicers and lexical candidate
ranking. It uses original checked-out source, a project structural catalog with
annotations removed, and lazy masked target overlays. Structural function graphs
are reused across targets. Cache entries retain no target seeds or annotated
source overlays, with limits of 64 entries, 100,000 nodes and 64 MiB of accounted
node/edge data. Source catalogs remain resident for one project at a time.

The builder distinguishes assignment sites, joins reaching definitions, propagates
loop definitions to a finite fixed point, and records def-use, control, return,
yield, element, unpack, field, call and may-alias edges. Conditional exits,
implicit None and source spans remain visible. Comprehensions use separate binding scopes and iterable/element edges.
Unsupported exception, context manager, closure and dynamic mutation effects create explicit
unresolved nodes and preserve complete affected scopes.

The resolver follows exact lexical/import identity, scoped wildcards, local
imports, reexports and verified project module aliases. It indexes incoming
callers once per project and retains their actual argument evidence. It binds ordinary positional,
keyword, positional-only and default parameters. Callsite-specific graph copies
keep independent actual/formal bindings apart. Shadowed builtins are not certified.
Builtin iterable contracts connect source operands to element evidence; verified
source callbacks used by map have separate element/formal/return links. Local
list literals support append/extend contracts without guessing receiver types. Structural
call summaries use SCCs and a bounded monotone fixed point. Recursion still records
an unresolved gap for runtime binding/dispatch; the structural summary does not
claim a closed recursive Python semantics.

Source support includes exact module declarations, alias cycles, lexical class
owners and relevant field/property/constructor declarations. Fixtures are searched
in the test module, ancestor conftest files and explicitly declared source
plugins, with explicit names, dependency traversal, scope checks and nearest
overrides. Dynamic parametrization, unavailable plugins and runtime request
contexts remain explicit gaps. Frozen
KB support uses exact imported identities and masked returned definition copies;
it never invokes a legacy reducer to select graph evidence.

Return selection walks dependency paths backwards. Argument selection first
follows uses/constraints, then includes their prerequisites. Rendering removes
unrelated statements when dependencies are resolved, preserves control wrappers,
and explicitly labels excerpts as source fragments. Docstrings of selected
source functions remain in the prompt, including when their bodies are reduced.
Docstrings are not treated as verified symbol-resolution facts. Class/member
ownership is shown separately from file identity. Conflicting explicit field
annotations remain separate evidence and are recorded in the audit.

Packing measures the complete system/user/assistant-prefix chat template with
the actual tokenizer. Mandatory evidence and group prerequisites are atomic;
overbudget targets retain their evidence and required token count without a
truncated prompt. Train collation, length measurement and inference share the
same prompt builder. Oversized prompts/completions raise explicit errors instead
of slicing token IDs. Inference explicitly requests greedy decoding. Tokenizer
fingerprints include template, vocabulary, backend tokenization configuration,
special tokens and semantic initialization options, excluding local path/padding
state. Length caches include the packing/tokenizer fingerprint.

## Dataset and execution interfaces

The graph dataset schema is `typepro-graph-dataset-v1`, separate from baseline
raw-slice schemas. All roster entries are written to `roster.jsonl`; every
processed target has an entry in `outcomes.jsonl`, including timeout, parse,
missing-target and budget failures. Ready/unresolved model rows contain the
prompt, label and provenance; large graph diagnostics remain in the ledger.
Verification streams the ledger and checks roster coverage, split/project
isolation, fingerprints, file hashes, mandatory groups and graph references.
Export also re-tokenizes ready prompts for exact count verification.

Project checkouts must be clean and at their locked revision. Optional cloning
creates missing checkouts at exact commits and removes only checkouts created by
that export. Frozen KBs require the existing v7 source-evidence schema and exact
file hashes, are copied byte-for-byte, and are retained through merge. Merge
checks implementation/source/dependency/tokenizer/budget compatibility, preserves
the exact global roster, and reads ledger rows by byte offset rather than loading
all graph audits into memory. An interrupted/incomplete export lacks a valid
release manifest and is rejected.

Local invocation (requires original sources or explicit cloning, frozen project
KBs, a frozen tokenizer and flat project-to-hash lock JSONs):

```bash
.venv/bin/python -m typepro.data.graph_dataset \
  --baseline datasets/typepro-python-generative-v24 \
  --repos-root /path/to/locked/repositories \
  --source-lock /path/to/source_locks.json \
  --dependency-lock /path/to/dependency_locks.json \
  --dependency-root /path/to/baseline-with-project-kbs \
  --tokenizer /path/to/frozen/tokenizer \
  --output /path/to/new/graph-export
.venv/bin/python -m typepro.data.verify --data-dir /path/to/new/graph-export
.venv/bin/python -m typepro.data.merge \
  --shard-build-dirs /path/to/part1 /path/to/part2 \
  --graph-roster /path/to/global/roster.jsonl --work-dir /path/to/new/merge
```

The existing exporter also routes `--graph-context` to this entrypoint. The
legacy entrypoint remains available for baseline comparisons, with no invocation
from the graph path and no per-sample legacy fallback.

## Kaggle isolation

`generate_notebooks.py --graph-profile PROFILE.json --graph-output DIRECTORY`
and `schedule_shards.py --graph-profile PROFILE.json` render the experiment.
The scheduler requires an exact full SHA containing graph code and belonging to
`experiment/graph-context-v1`; it never resolves GitHub main for this profile.
It preserves the production 21 coordinates, 7 jobs per account, original
visibility, and account-wide five-active-job limits. Inputs may be public or explicitly shared with all three runner accounts.
Slugs start with
`typepro-graph-v1`, scheduler state/output paths are separate, and a generated
merge notebook attaches precisely the 21 experiment Datasets. The experiment
final Dataset is private under `duyvu1105/typepro-graph-v1-final`. Publishers
reject baseline slugs and incorrect physical coordinates.

An explicit profile has this structure (replace placeholders with checked locks;
this is not an existing uploaded input Dataset):

```json
{
  "schema_version": "typepro-graph-experiment-profile-v1",
  "branch": "experiment/graph-context-v1",
  "revision": "FULL_CHECKED_EXPERIMENT_SHA",
  "input_dataset": "duyvu1105/typepro-graph-v1-inputs",
  "input_manifest_sha256": "SHA256_OF_INPUT_MANIFEST_JSON",
  "input_public": true
}
```

That frozen input contains `baseline/` with the v24 files and project KBs,
`tokenizer/`, flat `source_locks.json` and `dependency_locks.json`, and
`input_manifest.json` with a `files` mapping of relative paths to SHA256 hashes.
Shard/merge notebooks validate those locks before using inputs. Publishing
credentials are loaded only from Kaggle Secrets for the expected account.
No credential was inspected during implementation.

## Validation and remaining experimental work

The baseline's 480 tests passed before branching. The v24 source revision,
manifest and all split hashes were checked. Freezing the actual v24 roster
preserved 51,735 records: 44,764 train, 3,694 validation and 3,277 test.

Synthetic tests cover reassignment, branch joins, loops, early/implicit exits,
finally, mutation, nested/comprehension scopes, callsite identity, positional/
keyword/default binding, shadowing, recursion, alias cycles, fixture overrides,
annotation masking under cold/warm caches and reversed query order, packing,
Unicode, completion budgets, EOS/label masking and exact merge rejection.
A local Qwen 0.5B tokenizer smoke check preserved the assistant boundary and
train/infer prompt parity (105 prompt tokens and 3 completion tokens before the
scope-label presentation adjustment). This was a tokenizer check, not model
inference or training. Final test counts and dry-run results are recorded below
in the final verification section below.

Resolution remains deliberately conservative for open receiver dispatch,
multiple inheritance/MRO, dynamic callbacks and plugin injection, mutation and
exception/finally ordering. Gaps retain visible source; this is not proof of complete Python
semantics. Baseline KBs may already contain reduced third-party definitions;
missing source evidence is not reconstructed or restamped as complete evidence.

The local v24 download contains split files and a KB index but no project KB
payloads. Original locked project checkouts are also not supplied here. Therefore
no full source/dependency-locked export, v24 source re-export parity experiment,
model EM comparison, ablation, project holdout validation or training was run.
These remain M7 acceptance work and the separately authorized experiment stage,
not claims implied by passing synthetic tests. The comparison harness in
`typepro.audit.graph_comparison` reports end-to-end/common-ready EM, fixes and
regressions, coverage, tokens/runtime and a paired project-bootstrap interval;
thresholds, checkpoint, holdout and variants must be frozen before using it.
No Git push, Kaggle job, Dataset publication or training was performed.

## Final verification

- Full suite after the main implementation batch: **529 passed in 40.68s**.
- A subsequent generic optional-alias hypothesis fix was checked with the
  graph module tests: **41 passed in 3.26s**, including its new regression test.
  The full suite was not rerun for that final isolated fix, following the request
  to reduce repeated testing.
- Three-account notebook regeneration and production dry-run succeeded for all
  21 coordinates. The generated production notebooks/plans have no tracked diff.
- The context comparison preserves the original 17 fixture sources, Qwen
  tokenizer and 6144/64 budget. It includes both actual prompts and a common-format
  control, source/evidence token counts, outcome coverage and explicit development
  evidence checks. Earlier reports remain untouched.
- These fixtures have been used during development; they are not an independent
  confirmation set. Missing gold/prediction data is never used to select evidence.

The final measurements are recorded in
`outputs/audit/graph-context-v1/size-comparison-final/report.md` and its JSON
counterpart. They do not establish dataset-wide coverage or model accuracy.

Final fixture result: actual prompts **2,468 → 2,369 tokens (-4.01%)**;
common-format prompts **2,341 → 2,249 (-3.93%)**; source/evidence tokens
**892 → 797 (-10.65%)**. Eight prompts are shorter and nine are longer; the
median per-target change is **+0.85%**. Outcomes remain six ready and eleven
unresolved, with no parse/export/budget failures in these fixtures. All 15 explicit
development evidence checks pass. This is a modest aggregate reduction, not
uniform compression or an accuracy/holdout result.

Implementation source commit: `453bcba45198b44602b5f604a65f75ce9db7b3ea`. The final measurement
source fingerprints were checked against the committed files.
The graph scheduler dry-run pinned that exact SHA and rendered **21 jobs
(7/7/7) plus one merge notebook**; all 22 notebooks parsed successfully.
This dry-run used an explicitly render-only input-manifest placeholder, so it
verifies profile/revision/coordinate isolation, not Dataset availability or remote
execution. The frozen source/KB input bundle still needs to be prepared before
any authorized real launch.
