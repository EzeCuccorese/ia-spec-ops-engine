# Interaction and Working Guidelines

## Response Formatting

- **Do not repeat code in summaries**: Do not copy or paste full blocks of modified or written code into final chat summaries. Simply list the affected files and summarize their main purpose.

## Code Editing Standards

- **Preserve existing formatting and spacing**: Limit edits strictly to the scope required to fulfill the task. Do not alter blank lines, tabs, or formatting of unrelated code to keep git diffs clean and readable.
- **Bounded Scope**: Modify only the files and lines necessary for the requested feature or fix.

## Result Verification

- **Verify results before advancing**: Following any resource mutation (API requests, database writes, configuration changes), execute a mandatory read operation (e.g., GET request, DB query) to verify correctness before completing the step.
- **Faithful Outcome Reporting**: If tests fail or a pipeline step is skipped, report the exact result transparently along with relevant error logs or explanations.
