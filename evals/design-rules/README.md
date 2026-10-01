# design-rules eval

Answers, with data, whether giving Claude Code the text rules `01-clean-code-solid.md`
and `11-self-documenting-code.md` reduces design violations (measured by
`ws design`, deterministically) compared to giving no rules, and whether text
rules still help once a deterministic Stop-hook gate is in place.

This eval directory is standalone — it is not part of any installable
package and is not collected by the repo's pytest (`testpaths` in the root
`pyproject.toml` does not include `evals/`).

## Layout

- `fixture/`: a small, clean (0 `ws design` violations) Python project — an
  order/pricing service (`src/shop/`) with models, a repository, a service,
  and pytest tests.
- `tasks/*.md`: three tasks that invite complexity (discount rules engine,
  CSV order import, payment client with retries).
- `hidden_tests/<task>/`: acceptance tests copied into the run copy only
  after the agent finishes, to score correctness. These assume a plausible
  API shape (e.g. `DiscountEngine`, `Discount.percentage(...)`,
  `import_orders_csv(...)`, `PaymentClient`) inferred from the task text; an
  agent that solves the task with different names will fail hidden tests
  even if the behavior is otherwise correct — a known limitation of
  behavior-only task specs.
- `run.py`: orchestrates task x condition x repetition runs.
- `mutate.py`: stdlib mutation step used by `run.py` (see Test-guidance conditions).
- `summarize.py`: turns `results/results.csv` into `results/summary.md` and
  `results/tests-summary.md` (and prints the summary).

## Conditions

- `none`: no rules, no gate.
- `rules`: `01` + `11` copied into the run copy's `.claude/rules/`.
- `gate`: no rules; a Stop hook in the run copy's `.claude/settings.json`
  runs `ws design --changed --json` and blocks the stop (exit code 2, output
  on stderr) once when it fails.
- `rules+gate`: both.

## Running

```bash
# see the commands without calling claude (no cost)
uv run python evals/design-rules/run.py --dry-run --reps 1

# one real run (costs money — see below)
uv run python evals/design-rules/run.py --tasks discounts --conditions none --reps 1

# full matrix (3 tasks x 4 conditions x N reps = 12*N real `claude -p` calls)
uv run python evals/design-rules/run.py --reps 3

uv run python evals/design-rules/summarize.py
```

Flags: `--tasks` (comma-separated: `discounts`, `csv_import`,
`payment_client`; default all three), `--conditions` (comma-separated, default
the four design conditions), `--reps` (default 1), `--model` (default the
exact id `claude-sonnet-5-5`), `--dry-run`, `--missing-only` (skip
task/condition/rep combinations that already have a valid row in
`results/results.csv`).

**Cost warning**: each run is a real `claude -p ... --model claude-sonnet-5-5` call
against a nontrivial coding task (writing a new module + tests). The full
matrix at `--reps 3` is 36 real agent runs; budget accordingly before
running it. Start with `--reps 1` on one task/condition to sanity-check
cost per run, then scale up.

Each run passes `--settings '{"syncClaudeAiSkills": false, "syncClaudeAiPlugins": false}'`
so claude.ai account skills and plugins do not leak into the runs.

## Isolation caveats

- `--setting-sources project` restricts the run to the run copy's
  `.claude/settings.json` (and any `.claude/settings.local.json` there,
  which this eval does not create), so the user's global
  `~/.claude/rules/*` and global settings are not loaded — this is what
  makes `none` vs `rules` a clean comparison.
- `--permission-mode bypassPermissions` is used so the agent can edit files
  and run Bash inside the temp run directory non-interactively. This is
  scoped by `cwd` (the temp copy), not by a sandbox: the agent technically
  has the same OS-level permissions as the invoking user for that process.
  Only run this against throwaway temp directories, never a real repo.
- `ws` is made resolvable inside the run via a small PATH shim script that
  forwards `ws ...` to `uv run --project <repo root> ws ...`, since the run
  copy has no venv of its own.
- Network calls from the agent (if any) are not blocked; the tasks are
  designed to need none (stdlib-only fixture, injected transport for the
  payment task).

## Decision rule (see `summarize.py`)

- A text rule is **kept** if `rules` reduces violations per 100 added lines
  by >= 30% vs `none`, without lowering the hidden-test pass rate.
- Text rules are **worth it on top of the gate** if `rules+gate` reduces
  violations per 100 lines by >= 30% vs `gate` alone, or if it costs fewer
  turns/less money for the same outcome.

## Test-guidance conditions

Second question: does the testing guidance (rule `04-testing-patterns.md` +
the `test-audit` skill, `TEST_AUDIT_SKILL` in `ai_governance/install/content.py`)
cut useless test code without hurting correctness? Same tasks, all of which
already ask for unit tests.

- `tests-none`: no rules, no skill, no gate.
- `tests-rules`: `04` copied to `.claude/rules/`, skill written to
  `.claude/skills/test-audit/SKILL.md`.
- `tests-gate`: the Stop-hook gate (`ws design --changed`, which includes the
  `test-*` quality checks), no guidance.
- `tests-rules+gate`: both.

```bash
uv run python evals/design-rules/run.py --conditions tests-none,tests-rules,tests-gate,tests-rules+gate --reps 3
```

Extra per-run CSV columns: `test_loc_added` / `prod_loc_added` (`.py` lines
added, split by test path: a `tests/` dir, `test_*.py`, `*_test.py`,
`conftest.py`), `test_functions_added` (added `def test...` lines in test
files), `test_violations` (`ws design` violations whose metric starts with
`test-`), `mutants_killed` / `mutants_total`.

Mutation score (`mutate.py`): before the hidden tests are copied in, up to 10
seeded (fixed seed) AST mutations are applied one at a time to the new
production modules under `src/` (modified ones if none are new): comparison
flips (`<`/`<=`, `>`/`>=`, `==`/`!=`), `+`/`-`, `*`->`//`, `True`/`False`,
and return value -> `None`. Only the agent's own tests run (hidden tests
excluded), 60 s timeout per mutant (a timeout counts as killed). If the
baseline suite is red or nothing is mutable, the row records 0/0 and is
left out of the score. Mutation is measured on every condition. Note the
mutant sample is small (about 10 per run), so read differences of a few
points as noise.

Decision rule (test table in `summarize.py`, each guidance condition vs its
baseline: `tests-rules` vs `tests-none`, `tests-rules+gate` vs `tests-gate`):
keep the guidance if test LOC per 100 prod LOC drops >= 20% OR test-quality
violations per run drop >= 30%, AND the mutation score drops by no more than 5
points AND the hidden pass rate does not drop.
