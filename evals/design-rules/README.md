# design-rules eval

Answers, with data, whether giving Claude Code the text rules `01-clean-code-solid.md`
and `11-self-documenting-code.md` reduces design violations (measured by
`ws design`, deterministically) compared to giving no rules, and whether text
rules still help once a deterministic Stop-hook gate is in place.

This eval directory is standalone — it is not part of any installable
package and is not collected by the repo's pytest (`testpaths` in the root
`pyproject.toml` only points at `packages/*/tests`).

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
- `summarize.py`: turns `results/results.csv` into `results/summary.md`.

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

Flags: `--tasks` (comma-separated, default all three), `--conditions`
(comma-separated, default all four), `--reps` (default 1), `--model`
(default `sonnet`), `--dry-run`.

**Cost warning**: each run is a real `claude -p ... --model sonnet` call
against a nontrivial coding task (writing a new module + tests). The full
matrix at `--reps 3` is 36 real agent runs; budget accordingly before
running it. Start with `--reps 1` on one task/condition to sanity-check
cost per run, then scale up.

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
