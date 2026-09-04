# Cross-Session Progress Tracker

Global progress registry for active engineering tasks across sessions, stored in `~/.claude/progress/`.

Each task is keyed by its Jira issue key (e.g. `ONB-1164`) or a freeform slug. Tasks cross repositories, so repositories are attributes inside the task, not the task's identity.

- `progress list`: List all currently active tasks.
- `progress show <id> [--full]`: Inspect task state and full log.
- `progress here`: Automatically detect active task from git branch.
- `progress new <id> --title "..."`: Create a new task.

Keep state compact (~300 tokens) so sessions can be cleared and resumed with minimal token usage.
