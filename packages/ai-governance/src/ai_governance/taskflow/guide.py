"""Part of ``cli`` (split out, no behavior change)."""

from __future__ import annotations

GUIDE = """\
Flow (one task or subtask at a time):
  plan -> validate -> work -> judge -> [staging] -> review -> done   (exit: findings)

  1. Start:     taskflow new <ID> --title "..."   (ID = Jira key, or a slug until it exists)
                taskflow bind <ID> --repo <worktree> --integration-branch <branch>
  2. plan:      taskflow round <ID> run --role planner --prompt-file brief.md
                taskflow phase <ID> validate
  3. validate:  taskflow round <ID> run --role validator --prompt-file review.md
                show the user the final plan; on their ok in the chat:
                taskflow approve <ID> --action plan --target <ID> --user-reply "<their words>"
                taskflow phase <ID> work
  4. work:      taskflow tdd <ID> red --cmd "<test>"   (before the change; must fail)
                implement, then taskflow tdd <ID> green --cmd "<same test>"; commit
                taskflow phase <ID> judge
  5. judge:     taskflow judge <ID>   (isolated copy of HEAD, checks + every required judge)
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

One worktree per task: tasks sharing a worktree make `here` ambiguous and reviewers mix
contexts. `round run` already prepends the task context (goal, plan path, decisions, facts,
repos), so a prompt only needs the specific question.

Code tasks always run tri-agent: planner, validator and each judge are separate sessions and the
builder is the coordinating session. The validator and every judge must also be a different
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
