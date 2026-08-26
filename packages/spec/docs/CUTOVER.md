# Legacy cutover plan

The legacy engine remains reference material until this checklist is accepted. Passing unit tests
alone does not authorize deletion.

## Evidence already automated

- Path escape and symlink escape rejection.
- Atomic owned-file generation and digest tracking.
- Refusal to overwrite or remove unowned/user-modified files.
- Full SDD transition order and passing-evidence requirement.
- Verification argv safety, timeout/missing-tool semantics, and bounded evidence.
- End-to-end init → adapter → SDD → verify → finish → adapter removal in a temporary project.

## Manual soak gate

Use v2 for at least three real changes of different sizes. For each, record:

1. time from idea to first useful verification;
2. any manual state repair;
3. false-green or unclear verification result;
4. instruction conflict with an existing `AGENTS.md`;
5. friction that caused bypassing Spec.

Cutover is rejected if any run loses user content, requires editing state/evidence, or reports a
false `PASS`.

## Cutover operation

1. Tag or archive the current legacy commit.
2. Promote `next/` contents to the repository root in a dedicated branch.
3. Re-run the full test and CLI smoke gates from the promoted layout.
4. Replace the root README and packaging metadata with v2 sources.
5. Remove the old `packages/sdd`, legacy installers, rules, and misleading documentation only after
   reviewing the exact Git diff.
6. Keep `spec-devops/` archived or move it to a separate repository; never merge it into v2.

No automated v2 command performs this deletion.
