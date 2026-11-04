# Taskflow & Task Registry

## Invariants
- **Identity**: a task is identified by its Jira key (`ONB-1164`) or a free slug, never by a repo name; repos are bound inside it with `ai-governance taskflow bind`.
- **Resume first**: when the user names a task, run `taskflow show <id>` and `status <id>` before assuming there is no prior context; `here` gives the task bound to the current branch.
- **Record progress** with `new`, `summary`, `step add|done`, `fact`, `decide --why` and `note`, never with loose `.md` files.
- **Approvals**: record each user approval with `approve <id> --action <a> --target <t> --user-reply "<their words>"`. Risky actions need the user's explicit phrase, never a bare "ok".
