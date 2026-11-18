"""Part of ``cli`` (split out, no behavior change)."""

from __future__ import annotations

GUIDE = """\
Flow (durable task notebook + human gates + multi-provider design debate):

  1. Notebook:  taskflow new <ID> --title "..."   (ID = Jira key or slug)
                taskflow bind <ID> --repo <worktree> --integration-branch <branch>
                taskflow summary|step|fact|decide|link|reference|note <ID> ...
                taskflow status [<ID>] | show [<ID>] | here | list | close <ID> [--reason "..."]

  2. Human gates (the engine never runs them itself): ticket, push, pr, comment, slack,
     staging, deploy, prod. Run `taskflow ask <ID> --action A --target T`, put the tag it
     prints in your question to the user, wait for the reply, then record it with:
     taskflow approve <ID> --action A --target T --user-reply "<their words>"
     Risky actions (deploy, prod, migration, infra, permissions, delete, restaging) need
     --consequence (what breaks if it goes wrong) and a reply naming action and target;
     "ok"/"dale" is refused. Production actions are refused after 16:00, and Friday after 13:00.

  3. Design debate (at least 2 providers, Orca workers only):
     taskflow debate <ID> open --topic-file <file> --agents <a,b> [--model a=m] [--web] [--artifact P]
     Run each printed `orchestration worker-start` line (it saves runs/N/launch.json),
     END YOUR TURN. Orca wakes you when workers report worker_done. Then settle each round:
     taskflow round <ID> collect --round N --dispatch-id <ID from Orca>
     A stuck worker: `orca orchestration worker-stop --dispatch <id>`, then
     taskflow round <ID> abort --round N --reason "..." (--dispatch-id <id> | --never-started)
     --never-started is your own assertion that no worker started; it is recorded, not proven.
     Then:
     taskflow debate <ID> cross              (all-against-all cross-examination)
     taskflow debate <ID> status             (pending/collected/invalid per seat)
     taskflow debate <ID> close [--partial]  (writes synthesis.md; records open points as steps)

Agents never run from the engine or from a shell. Never launch agent CLIs yourself.
One worktree per task: tasks sharing a worktree make `here` ambiguous.
Nothing of this tool or of the agents goes into tickets, commits, PRs or Slack.
"""
