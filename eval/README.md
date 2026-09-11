# Eval conventions

Spec + directory structure only for now — there is no runnable scorer script yet,
because there's no real skill/agent content to score against. This doc is the
convention a future runner will be built against.

## Fixture format

Each agent/skill that opts into eval keeps its cases under the directory named in
its `contract.yaml` (`eval.fixtures_dir`, see `docs/contracts.md`):

```
fixtures/
  case-001/
    input.json      # what gets fed in — shape matches the contract's `inputs`
    expected.json    # what a passing run should look like
  case-002/
    ...
```

`expected.json` describes *how* to check the output, not just a literal value:

```json
{
  "match_type": "exact | contains | schema",
  "value": "..."
}
```

- `exact` — output must equal `value` verbatim.
- `contains` — output must include `value` (substring/keyword/subset check).
- `schema` — output must validate against the JSON Schema at `value` (a path).

## Scoring rubric

Each fixture case is scored on three dimensions, 0-2 each:

| Dimension | 0 | 1 | 2 |
|---|---|---|---|
| Correctness | Wrong or harmful output | Partially correct | Fully matches `expected.json` |
| Contract compliance | Violates a stated precondition/side-effect | Minor deviation from the contract | Fully within the agent/skill's `contract.yaml` |
| Format | Output shape is invalid/unusable | Mostly valid, some drift | Exactly matches the expected shape |

**Pass threshold:** average score ≥ 1.5 *and* no dimension scored 0.

## How an agent/skill opts in

1. Point `eval.fixtures_dir` in its `contract.yaml` at a `fixtures/` directory.
2. Add at least one `case-NNN/` with `input.json` + `expected.json`.
3. (Future) run the not-yet-built runner against it; until then, cases can be
   exercised and scored by hand using this rubric.

## Results

Once a runner exists, its output lands in `eval/results/` (gitignored — not created
yet, since nothing writes there today).
