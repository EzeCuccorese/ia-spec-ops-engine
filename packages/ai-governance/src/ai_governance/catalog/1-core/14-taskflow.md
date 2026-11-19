# Taskflow & Task Registry

## Invariants
- **Task Identity**: Identify every task by its Jira key (`TASK-1164`) or a descriptive slug, never by a repository name. Bind repositories to a task with `ai-governance taskflow bind`.
- **Resume First**: When resuming or switching to a named task, run `ai-governance taskflow show <id>` and `status <id>` before assuming there is no prior context. Use `here` to find the task bound to the current branch.
- **Task Notebook**: Record multi-step progress in Taskflow (`new`, `summary`, `step add|done`, `fact`, `decide --why`, `note`) rather than creating loose `.md` files.
- **Approvals**: Record every user authorization for a risky action with `approve <id> --action <a> --target <t> --user-reply "<their words>"`. Risky actions require the user's explicit authorizing phrase, never a bare "ok".
- **Design Debates**: Use `debate open|cross|status|close` and `round collect|abort` to run multi-provider design debates on a task when cross-model review is needed.
- **Second Brain**: Run `ai-governance brain search <query>` before asking about prior context; save durable cross-agent lessons with `ai-governance brain add` instead of agent-local memory.
