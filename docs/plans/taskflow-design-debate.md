# Plan: design debate mode for taskflow

Status: implemented on `docs/taskflow-design-debate-plan` (validated against `main` at `1bd575b`; Section 6 live Orca acceptance run pending active Orca desktop daemon).
Line numbers below are from the initial baseline `22d02da`; check current lines before editing.

## 1. Outcome

A user can ask several agents from different providers to argue about a design before any
code is written, and gets one document that says who refuted whom, with what evidence, and
what is left to decide.

Today the pieces exist but the user has to wire them by hand, and nothing summarizes the
result.

## 2. Where the ideas come from

Two skills written for Orca by a teammate were reviewed. They are not copied into this
repository: they belong to their author, they are written for one setup (fixed model names,
project paths), and everything the implementation needs from them is restated here.

Ideas already in the engine (taskflow, PR #63):

- A second round where an agent reads the earlier rounds and refutes them (`--rebut`).
- A scratch directory per round, outside every repository, for throwaway proofs.
- A check that the launched agent and model are the ones requested (`launch.effective`).
- `CHANGE:` lines with path and line for every required change.
- Build, then review by another provider, repeat until agreement (validator and judges).

Ideas missing, which this plan adds:

| # | Missing piece | Delivery |
|---|---|---|
| a | A debate between N agents: independent thesis, then everyone refutes everyone | 1 |
| b | A closing document: who refuted whom, with what proof, who changed position | 2 |
| c | Permission and duty to research the web, with a source per claim | 3 |
| d | Duty to open the real visual artifacts (images, rendered HTML) under discussion | 3 |
| e | Reasoning effort per role | 4 |
| f | A list of models that must never be launched (cost guard) | 4 |

Out of scope: a fixed panel with named models and fixed roles per provider. The engine stays
neutral: the user names the seats.

## 3. What exists today (verified by reading the code)

All paths are under `packages/ai-governance/src/ai_governance/`.

- Roles: `taskflow/models.py:12` (`ROLES = planner, validator, builder, judge`).
  Only planner and validator can be dispatched: `taskflow/dispatch.py:44` (`DISPATCHABLE`).
- Role to agent and model: settings keys `taskflow.<role>_agent` and `taskflow.<role>_model`
  (`settings.py:80-91`, `taskflow/config.py:43-52`). There is no effort key anywhere.
- Providers: no closed list. Allowed agents come from `taskflow.allowed_agents`
  (`settings.py:75-76`, default `antigravity, codex, claude`); `config.agent_error`
  (`taskflow/config.py:131`) refuses anything else. Provider is the text before `/` in the
  agent id (`taskflow/agents.py:44-49`).
- "Different provider from the builder" applies to validator and judge only
  (`taskflow/agents.py:28`, `taskflow/dispatch.py:105`).
- Pending rounds: one pending dispatch per `(role, phase, focus)`
  (`taskflow/dispatch.py:215`, `:233`).
- Rebuttal: `round dispatch --rebut N` (repeatable). `rebuttal_rounds`
  (`taskflow/dispatch.py:187`) requires each referenced round to be settled and valid.
  `_spec_text` (`taskflow/dispatch.py:205`) appends `CROSS_EXAMINATION`
  (`taskflow/prompts.py:23`), which lists the round files; the worker reads them itself.
  One worker per dispatch; there is no all-against-all construct.
- Per round the worker writes `runs/N/receipt.txt` and `runs/N/answer.txt`; scratch is
  `runs/N/scratch` under the task directory (`taskflow/dispatch.py:148-184`).
- Collect writes one round file per round (`taskflow/collect.py:285-308`) with the verdict,
  the `Cross-examines rounds:` line, the scratch path and the `CHANGE:` lines. Nothing
  crosses rounds.
- Launch line: `orca.worker_start_argv` (`taskflow/orca.py:97-106`).
- Launch receipt check: `taskflow/collect.py:165-229`.
- Prompts say nothing about web research or visual artifacts. `READ_ONLY_LIMIT`
  (`taskflow/prompts.py:13`) forbids changing the repository or the environment.
- Budget: the bundled `taskflow` skill text must stay at or under 1024 bytes
  (`tests/test_taskflow_agents.py:485`). It is 978 bytes now: 46 bytes free.

Verified during implementation:

- No prior `denied_models` setting or model deny-list existed anywhere in the repository
  before Delivery 4.
- `orca orchestration worker-start --help` confirms `--effort <level>` exists and requires
  `--model`.
- `manual` workflow is blocked for `planner`/`validator`/`judge` (`Manual tasks have no agent
  rounds`) and allowed for `debater`.
- `collect` (`_outcome`) marks non-verdict rounds (`planner` and `debater`) `valid` with
  verdict `info` when the worker ends `succeeded` on a clean tree.
- Parallel multi-seat dispatch (distinct `focus` per `(role, phase, focus)`) and any-order
  `collect` (by `--round` and `--dispatch-id`) are verified.

## 4. Design decisions

1. **A debate is a set of ordinary rounds.** No new storage for answers. A debater round is
   dispatched, collected and stored exactly like a planner round. The debate adds one small
   state file and two commands that print several dispatches at once.
2. **New dispatchable role `debater`.** Read-only, same limits as a validator. It is not in
   `INDEPENDENT_ROLES`: a debater may share the builder's provider. The debate has its own
   rule instead: at least two different providers among the seats.
3. **A seat is `focus`.** Each seat uses its agent id as the round focus (plus `-2`, `-3` if
   an agent id repeats), so the existing one-pending-per-`(role, phase, focus)` rule lets N
   seats run at once without changing it.
4. **Seats are named by the user**, each must pass `config.agent_error`. No default panel.
   The model for a seat is the agent's default unless `--model agent=model` is given.
5. **The engine still launches nothing.** Every command prints launch lines; the user or the
   calling agent runs them and then collects, as today.
6. **The closing document is built by parsing fixed-format lines, not by a model.** Same
   approach as `CHANGE:`. A seat that does not write the lines is reported as such; the
   document never invents a cell.
7. **Debate works in any workflow**, including `manual`: it has no gates and moves no phase.
8. **Web and visual duties are opt-in flags**, so existing planner and validator prompts do
   not change.
9. **No backward compatibility work.** No migration of old tasks.

## 5. Deliveries

One pull request per delivery, each from `main`, each one outcome. Titles are Conventional
Commits; all four are `feat`, so each raises the minor version.

### Delivery 1: run a debate

Title: `feat(taskflow): add a debate between agents of different providers`

Commands:

```text
taskflow debate <id> open --topic-file <file> --agents <a,b,c>
                          [--model <agent>=<model>]...
taskflow debate <id> cross
taskflow debate <id> status
```

`open`:

- Refuses: fewer than two seats; fewer than two providers; an agent `agent_error` refuses;
  an open debate already on the task; a missing or empty topic file.
- Dispatches one `debater` round per seat with the topic as the request and the thesis
  block below. Prints one launch line per seat, in seat order, then the collect hint.
- Writes `debate.json` in the task directory: topic file digest, seats (focus, agent,
  model), thesis round number per seat, cross round number per seat (empty), flags.

`cross`:

- Refuses while any thesis round is still pending.
- Drops seats whose thesis round is invalid, with one warning line each. Refuses if fewer
  than two valid seats remain.
- For each remaining seat, dispatches a `debater` round that rebuts the thesis rounds of
  all the other seats (the existing `rebuttal_rounds` path) plus the cross block below.
- Records the cross round numbers in `debate.json`.

`status`: one line per seat with thesis round, cross round and state
(`pending`, `collected`, `invalid`, `dropped`).

Prompt text (new constants in `taskflow/prompts.py`, wording may be tightened):

```text
THESIS
You are one seat in a design debate. Other agents answer the same question without seeing
your answer. Take a position and defend it with evidence you produced (code you read, a
command or throwaway script you ran in the scratch directory). List the assumptions that
would change your mind. End with one line exactly like `POSITION: <one sentence>`.

CROSS (appended after the existing cross-examination block)
For each claim of another seat you address, write one line exactly like
`REBUT: round <NNN> | <their claim> | <your evidence> | refuted|agreed|open`.
For each change in your own position write
`CHANGED: <what you changed> | round <NNN>`.
End with one line exactly like `POSITION: <one sentence>`.
```

Files:

- `taskflow/models.py`: add the role.
- `taskflow/dispatch.py`: `debater` in `DISPATCHABLE`; seat validation; multi-dispatch.
- `taskflow/prompts.py`: the two blocks and a `POSITION` parser.
- `taskflow/parser.py`, `taskflow/round_cli.py` (or a new `taskflow/debate_cli.py` if
  `round_cli.py` would pass the design limits): the `debate` subcommand.
- New `taskflow/debate.py`: `debate.json` read and write, seat naming, state.
- `taskflow/collect.py`: accept a `debater` round (no verdict line required; record the
  `POSITION` line in the round file).
- `taskflow/guide.py`: the debate section of `taskflow --help`.
- `install/content.py`: at most one short clause in the `taskflow` skill (46 bytes free);
  if it does not fit, leave the skill unchanged and rely on the guide.
- Tests: `tests/test_taskflow_dispatch.py`, or a new `tests/test_taskflow_debate.py`.

Tests (each must fail on a real bug, none on wording):

- `open` with three seats writes three specs, three launch lines and `debate.json`.
- `open` refuses one provider repeated in every seat, a disallowed agent, a second debate.
- Two seats with the same agent id get distinct focus and both stay pending.
- `cross` refuses while a thesis is pending.
- `cross` gives every seat the rounds of the others and never its own.
- `cross` drops an invalid seat and still runs with two valid ones; refuses with one.
- A collected `debater` round is valid without a verdict line and keeps its `POSITION`.
- A debater may use the builder's provider; a validator still may not.

### Delivery 2: the closing document

Title: `feat(taskflow): write a debate synthesis with the cross-examination matrix`

Command: `taskflow debate <id> close [--partial]`

- Refuses while cross rounds are pending, unless `--partial`.
- Parses the `REBUT:`, `CHANGED:` and `POSITION:` lines of every collected cross round and
  the `POSITION:` line of every thesis round.
- Writes `synthesis.md` in the task directory and prints its path. Running it again
  rewrites the same content (no timestamps in the body).
- Records each `open` entry into `task.steps` (prefixed with `[debate]` or `[debate #N]`
  for later debates, idempotent on repeated `close` runs).
- Marks the debate closed in `debate.json`, so a new one can be opened.

Sections of `synthesis.md`, in this order:

1. Topic (first lines of the topic file) and seats (focus, agent, model, rounds).
2. Matrix: rows are authors, columns are targets, each cell is the count of
   `refuted / agreed / open`. A seat with zero `REBUT:` lines (`not lines and not malformed`)
   gets `no structured lines`; a seat whose `REBUT:` lines are all malformed or target invalid
   rounds shows `0 / 0 / 0` (with details under Missing).
3. Refutations: one line per `refuted` entry with author, target, claim and evidence.
4. Position changes: each `CHANGED:` line, and for each seat the thesis `POSITION` next to
   the cross `POSITION`.
5. Open points: every `open` entry. These are the decisions left for the user.
6. Missing: seats dropped, rounds pending (with `--partial`), malformed lines (quoted).

Files:

- New `taskflow/synthesis.py`: parsing and rendering, no I/O beyond reading round answers.
- `taskflow/prompts.py`: `REBUT` and `CHANGED` parsers next to the `CHANGE` one.
- `taskflow/debate.py`, the debate CLI module, `taskflow/guide.py`.
- Tests: `tests/test_taskflow_debate.py`.

Tests:

- Three seats with known lines produce the expected counts per cell.
- A `REBUT:` line pointing to a round that is not a seat of this debate is listed under
  Missing, not counted.
- A malformed line (wrong number of fields, unknown outcome) is listed under Missing.
- A seat with no structured lines shows as such and does not break the matrix.
- `close` refuses with a pending cross round; `--partial` writes and names it.
- Two runs produce identical files.

### Delivery 3: web research and visual artifacts

Title: `feat(taskflow): let a round require web sources and visual inspection`

Flags on `debate open` and on `round dispatch`:

- `--web`: appends "You may research the web. Every claim that rests on an external source
  carries its URL; a claim with no URL counts as assumed."
- `--artifact <path>` (repeatable): appends "Open each of these files and describe what you
  saw before using it as evidence; do not argue from the file name:" plus the absolute
  paths. Refuses a path that does not exist.

For a debate, the flags are stored in `debate.json` and reused by `cross`.

Files: `taskflow/prompts.py`, `taskflow/dispatch.py`, `taskflow/parser.py`,
`taskflow/debate.py`, `taskflow/guide.py`, tests in the dispatch and debate test files.

Tests:

- Without flags, a planner or validator spec is byte-identical to today's.
- `--web` and `--artifact` add their block to the spec; `cross` repeats them.
- A missing artifact path is refused before anything is written.

Note: whether a given agent can actually reach the web in a read-only worker depends on the
agent, not on the engine. The acceptance run below must record what each one did.

### Delivery 4: effort and model deny-list

Title: `feat(taskflow): add reasoning effort per role and a model deny-list`

Precondition: run `orca orchestration worker-start --help` and confirm `--effort` exists and
which values it takes. If it does not exist, drop the effort half and ship the deny-list.

- Settings `taskflow.<role>_effort` (empty by default; empty adds nothing to the launch
  line) for planner, validator, builder, judge and debater. `--effort <value>` goes after
  `--model` in `orca.worker_start_argv`.
- Setting `taskflow.denied_models`: list of model ids, empty by default. A dispatch whose
  model is in the list is refused with the setting named in the message. On collect, a
  launch receipt whose effective model is in the list fails the same way as a mismatch.
- A repository file may add to the deny-list but never remove from it (same trust rule the
  runner fields already follow, `taskflow/config.py:281`, `:349`).

Files: `settings.py`, `taskflow/config.py`, `taskflow/orca.py`, `taskflow/dispatch.py`,
`taskflow/collect.py`, `taskflow/guide.py`, tests in the dispatch and agents test files.

Tests:

- An effort value reaches the launch line; an empty one leaves the line as today.
- A denied model is refused at dispatch for a role and for a debate seat.
- A receipt reporting a denied effective model fails collect.
- A repository config cannot shorten the user's deny-list.

### Implementation note (consolidated branch)

All 4 deliveries are implemented together on `docs/taskflow-design-debate-plan` for
consolidated review (validated against `main` at `1bd575b`):

- **Delivery 4 `--effort` and `denied_models` fail-closed rules:** Because
  `orca orchestration worker-start --help` confirms `--effort <level>` requires `--model`,
  `orca.worker_start_argv` refuses `--effort` without a non-empty `model`, and dispatch/seat
  validation requires an explicit or default model whenever `taskflow.<role>_effort` or
  `taskflow.denied_models` is active (resolving built-in defaults such as `codex` ->
  `gpt-6.1-sol`, and refusing implicit empty-model launches such as `claude` without
  `--model`). At `collect`, an active deny-list also requires a verified launched model in
  `launch.json`, and `matches_denied_model` matches exact `provider/model` entries as well as
  unprefixed model names with or without any `provider/` prefix (mismatched explicit prefixes
  such as `a/x` vs `b/x` stay distinct).
- **`debate.py` provider and artifact checks:** `assign_seats` enforces at least 2 distinct
  providers when opening a debate (`open`), and `_valid_cross_seats` re-checks that at
  least 2 valid thesis seats AND at least 2 distinct providers remain after dropping
  invalid seats before `cross` dispatches. `debate.json` records `topic_sha` and
  `artifact_digests` (SHA-256 per regular artifact file via `_resolve_artifact_digests`),
  and `_cross_topic` / `_cross_artifacts` re-verify those digests before `cross` runs.

## 6. Acceptance run (after each delivery, on a real machine)

Tests are not enough: nothing is done until a real run through Orca shows it.

1. `taskflow new debate-demo --title "Debate demo"` and a topic file with a small, real
   design question about this repository.
2. `taskflow debate debate-demo open --topic-file <file> --agents codex,antigravity`
   (add a third provider if one is allowed on the machine).
3. Run each printed line, collect each round. Check: one spec and one scratch directory per
   seat, launch receipts verified, each answer ends with `POSITION:`.
4. `taskflow debate debate-demo cross`, run and collect. Check: each spec lists the other
   seats' round files and not its own; answers carry `REBUT:` lines.
5. (Delivery 2) `taskflow debate debate-demo close`. Read `synthesis.md` against the raw
   answers: every cell must be traceable to a line.
6. (Delivery 3) Repeat with `--web` and one `--artifact`; record per agent whether it cited
   URLs and described the artifact.
7. (Delivery 4) Set a denied model and confirm the refusal; set an effort and confirm it in
   the launch receipt.

Report, per step: done, failed with the exact line, or could not be verified and why.

## 7. Working rules for the implementer

- Read the root `AGENTS.md` first. Code, docs, CLI output and commits in English, with
  nothing specific to one company, product or person.
- One branch from `main` per delivery. Never push to `main`, never force-push, never skip
  the pre-push checks.
- Stay inside the file list of the delivery. Needing another file means stop and say why.
- No refactors or renames of existing code on the way.
- Do not raise a size budget to make text fit; shorten the text.
- Every new test protects observable behavior. No tests of log text, signatures or mocks
  that assert themselves.
- Use the root `.venv` for `pytest` and `ruff`. Run only the affected test files while
  iterating; the pre-push checks run the rest.
- The engine never launches an agent. No subprocess call to an agent CLI in `taskflow/`.

## 8. Owner decisions & open questions

- Should `debater` be allowed to share the builder's provider? **Yes (confirmed)**: a debate
  happens before there is a builder's work to be independent from, while the debate itself
  still requires at least two distinct providers.
- Should `close` also record the open points in taskflow, or only write the document?
  **Both (confirmed)**: `close` writes `synthesis.md` and records each `open` point into
  `task.steps` (prefixed with `[debate]`, deduplicated for idempotency).
- A fourth provider launched through another agent CLI (for example a model reached through
  an editor's agent) only needs its id in `taskflow.allowed_agents`. It is untested; try it
  apart from these deliveries.
- **Consolidated delivery status:** All 4 deliveries are implemented on
  `docs/taskflow-design-debate-plan` for consolidated review. See the Section 5
  implementation note for Delivery 4 `--effort` without `--model` behavior and
  `debate.py` distinct-provider + artifact-digest checks.
