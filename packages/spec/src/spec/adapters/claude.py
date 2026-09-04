from __future__ import annotations

from pathlib import Path

from spec.core.ownership import DeleteResult, OwnershipManifest
from spec.core.paths import PathBoundary
from spec.core.write import SafeWriter, WriteResult

from .codex import END_MARKER, PATTERN, START_MARKER, CodexAdapter


class ClaudeAdapter:
    target = "CLAUDE.md"
    governance_file = ".spec/governance.md"

    def __init__(self, root: str | Path) -> None:
        self.root = root
        self.boundary = PathBoundary(root)

    def install(self) -> WriteResult:
        manifest = OwnershipManifest(self.root)
        writer_res = SafeWriter(self.root, manifest).write(
            self.governance_file,
            CodexAdapter.render(),
            mode=0o644,
        )

        claude_path = self.boundary.resolve(self.target)
        content = claude_path.read_text(encoding="utf-8") if claude_path.exists() else ""
        block = f"{START_MARKER}\n@.spec/governance.md\n{END_MARKER}\n"

        if START_MARKER in content and END_MARKER in content:
            new_content = PATTERN.sub(block, content)
        else:
            stripped = content.rstrip()
            new_content = f"{stripped}\n\n{block}" if stripped else block

        claude_path.write_text(new_content, encoding="utf-8")
        return writer_res

    def uninstall(self, *, dry_run: bool = True) -> DeleteResult:
        manifest = OwnershipManifest(self.root)
        if manifest.get(self.governance_file) is not None:
            del_res = manifest.delete_owned(self.governance_file, dry_run=dry_run)
        else:
            del_res = DeleteResult(path=self.governance_file, deleted=False, would_delete=False)

        claude_path = self.boundary.resolve(self.target)
        if claude_path.exists() and not dry_run:
            content = claude_path.read_text(encoding="utf-8")
            if START_MARKER in content and END_MARKER in content:
                cleaned = PATTERN.sub("", content)
                if not cleaned.strip():
                    claude_path.unlink(missing_ok=True)
                else:
                    claude_path.write_text(cleaned.rstrip() + "\n", encoding="utf-8")

        return del_res
