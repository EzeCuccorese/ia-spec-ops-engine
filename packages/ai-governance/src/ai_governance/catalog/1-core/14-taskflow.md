# Taskflow & Task Registry

## Invariants
- **Task Identity**: Identify tasks by Jira key (`TASK-1164`) or a descriptive slug, never by repo name. Bind repos with `ai-governance taskflow bind`.
- **Resume First**: Before resuming/switching to a named task, run `ai-governance taskflow show <id>` and `status <id>` instead of assuming no prior context. Use `here` for the branch's task.
- **Task Notebook**: Record multi-step progress in Taskflow (`new`, `summary`, `step add|done`, `fact`, `decide --why`, `note`) rather than creating loose `.md` files.
- **Approvals**: Log each risky-action authorization with `approve <id> --action <a> --target <t> --user-reply "<their words>"`. Risky actions need an explicit authorizing phrase, never "ok".
- **Design Debates**: Use `debate open|cross|status|close` and `round collect|abort` to run multi-provider design debates on a task when cross-model review is needed.
- **Second Brain**: Run `ai-governance brain search <query>` before asking about prior context; store durable lessons via `ai-governance brain add`, not agent-local memory.
