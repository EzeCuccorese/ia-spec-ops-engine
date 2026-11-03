"""Part of ``cli`` (split out, no behavior change)."""

from __future__ import annotations

GUIDE = """\
Flow (one task or subtask at a time):
  plan -> validate -> work -> judge -> [staging] -> review -> done   (exit: findings)

  1. Start:     taskflow new <ID> --title "..."   (ID = Jira key, or a slug until it exists)
                taskflow bind <ID> --repo <worktree> --integration-branch <branch>
  2. plan:      taskflow round <ID> dispatch --role planner --prompt-file brief.md
                (run the printed worker line, end your turn, then `round <ID> collect`; see below)
                taskflow phase <ID> validate
  3. validate:  taskflow round <ID> dispatch --role validator --prompt-file review.md
                (same cycle: run the line, end your turn, collect)
                show the user the final plan; on their ok in the chat:
                taskflow approve <ID> --action plan --target <ID> --user-reply "<their words>"
                taskflow phase <ID> work
  4. work:      taskflow tdd <ID> red --cmd "<test>"   (before the change; must fail)
                implement, then taskflow tdd <ID> green --cmd "<same test>"; commit
                taskflow phase <ID> judge
  5. judge:     taskflow judge <ID>   (the engine runs the checks on a throwaway copy of HEAD, then
                PRINTS one `orchestration worker-start` line per required judge: run it, end your
                turn, then `taskflow round <ID> collect --round N --dispatch-id <ID>`)
                block/concerns -> taskflow phase <ID> work, fix, judge again
  6. staging:   optional unless a risk rule asks for it. The USER deploys and approves.
                taskflow deploy <ID> --env staging --repo <path> --sha <sha> --provenance ci
                taskflow evidence <ID> --kind staging --file results.md --deployed-sha <sha>
  7. review:    clean up/rebase, taskflow judge <ID> again on the final SHA
  8. done:      only after the user confirms production (approve --action prod)

Human gates (the engine never runs them itself): ticket, push, pr, comment, slack,
staging, deploy, prod. Run `taskflow ask <ID> --action A --target T`, put the tag it
prints in your question to the user, wait for the reply, then record it with
`taskflow approve`. Risky actions (deploy, prod, migration, infra, permissions, delete,
policy-downgrade, restaging) need --consequence (what breaks if it goes wrong, plainly)
and a reply that names the action and the target, typed by the user; "ok"/"dale" is
refused. Production actions are refused after 16:00, and on Friday after 13:00.

Agents never run from the engine or from a shell. Planner, validator and judge rounds are
Orca workers:
  1. taskflow round <ID> dispatch --role validator --prompt-file review.md
       reserves the round and PRINTS ONE `orchestration worker-start` line (judges: `taskflow judge <ID>`)
  2. Run that line. END YOUR TURN. Orca wakes you when the worker reports worker_done.
  3. taskflow round <ID> collect --round N --dispatch-id <the id Orca gave you>
       settles it. A running worker: wait with `orca orchestration check --wait --types worker_done`.
       A stuck worker: `orca orchestration worker-stop --dispatch <id>`, then
       taskflow round <ID> abort --round N --reason "..." (--dispatch-id <id> | --never-started)
       --never-started is your own assertion that no worker started; it is recorded, not proven
The builder is YOU (the coordinating session): write the code yourself. Do not edit or commit
while a reader round is pending: the round becomes invalid and must be re-dispatched.
Never launch agent CLIs yourself. A judge is a reader: the engine runs the checks, the worker reads.
The worker writes a receipt (round token + its dispatch id) and its answer under runs/N/;
collect accepts only the dispatch id that matches that receipt.

One worktree per task: tasks sharing a worktree make `here` ambiguous and reviewers mix
contexts. `round dispatch` already prepends the task context (goal, plan path, decisions, facts,
repos), so a prompt only needs the specific question.

Code tasks always run tri-agent: "different agents" means different Orca sessions (planner,
validator and each judge) and the builder is the coordinating session. The validator and every judge must also be a different
provider than the builder; the planner may share the builder's provider. A repository can
narrow the allowed agents (`[taskflow] allowed_agents` in its .ai-governance/config.toml).
Another workflow only when the user asks for it; record it before leaving plan:
  taskflow approve <ID> --action workflow --target <ID> --user-reply "<their words>"
manual is for tracking only (no code, no phases).

TDD is mandatory unless the user asks to skip it:
  taskflow approve <ID> --action tdd-skip --target <ID> --user-reply "<their words>"
  taskflow tdd <ID> skip --reason "..."

In a Claude Code session --user-reply must be one whole message the user typed in this
session; one reply covers every ordinary request asked together in that question, a
risky action needs its own reply; risky actions are approved only there.

Any code change after a verdict or approval makes it stale: `taskflow status <ID>` shows
what is stale, what is missing for the next phase and the exact next command.
Another owner's branch: taskflow findings <ID> --out findings.md, hand it over, close.
Nothing of this tool or of the agents goes into tickets, commits, PRs or Slack.
"""
