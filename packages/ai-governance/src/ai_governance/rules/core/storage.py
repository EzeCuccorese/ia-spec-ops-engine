from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path

from .catalog import RuleDefinition


class RuleStorage:
    """Manages storing rule markdown files and manifest in global (~) or local (.specops) directories."""

    def __init__(self, target_dir: Path) -> None:
        self.target_dir = Path(target_dir)

    @classmethod
    def global_storage(cls) -> RuleStorage:
        return cls(Path.home() / ".specops" / "rules")

    @classmethod
    def local_storage(cls, root: Path | None = None) -> RuleStorage:
        base = root or Path.cwd()
        return cls(base / ".specops" / "rules")

    def save_rules(self, rules: list[RuleDefinition]) -> Path:
        self.target_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = self.target_dir / "manifest.json"

        existing_by_file: dict[str, dict] = {}
        if manifest_path.exists():
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                for r_item in data.get("rules", []):
                    existing_by_file[r_item.get("file", "")] = r_item
            except (json.JSONDecodeError, UnicodeDecodeError, OSError):
                pass

        manifest_rules: list[dict] = []
        for r in rules:
            dest = self.target_dir / r.relative_path
            dest.parent.mkdir(parents=True, exist_ok=True)

            if dest.exists():
                disk_sha256 = hashlib.sha256(dest.read_bytes()).hexdigest()
                if r.relative_path in existing_by_file:
                    recorded_sha256 = existing_by_file[r.relative_path].get("sha256")
                    if disk_sha256 != recorded_sha256:
                        # User modified this rule file! Preserve user edits, do not overwrite.
                        manifest_rules.append(
                            {
                                "id": r.id,
                                "category": r.category,
                                "file": r.relative_path,
                                "description": r.description,
                                "sha256": recorded_sha256,
                                "triggers": {"globs": list(r.globs)},
                            }
                        )
                        continue
                else:
                    # File exists but was unowned / not in manifest; preserve user file
                    continue

            # Write clean canonical rule content
            dest.write_text(r.content, encoding="utf-8")
            manifest_rules.append(
                {
                    "id": r.id,
                    "category": r.category,
                    "file": r.relative_path,
                    "description": r.description,
                    "sha256": r.sha256,
                    "triggers": {"globs": list(r.globs)},
                }
            )

        # Atomic manifest write
        tmp_manifest = self.target_dir / f"manifest.json.tmp.{os.getpid()}"
        try:
            with open(tmp_manifest, "w", encoding="utf-8") as f:
                f.write(json.dumps({"schema_version": 1, "rules": manifest_rules}, indent=2) + "\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_manifest, manifest_path)
        finally:
            if tmp_manifest.exists():
                tmp_manifest.unlink(missing_ok=True)

        return self.target_dir

    def delete_owned(self) -> list[Path]:
        """Removes only files owned by the manifest that have not been modified by the user.

        Preserves user modifications and unowned legacy files.
        """
        deleted: list[Path] = []
        manifest_path = self.target_dir / "manifest.json"
        if not manifest_path.exists():
            return deleted

        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            return deleted

        manifest_rules = data.get("rules", [])
        for item in manifest_rules:
            rel_file = item.get("file")
            if not rel_file:
                continue
            file_path = self.target_dir / rel_file
            if not file_path.exists():
                continue

            disk_sha256 = hashlib.sha256(file_path.read_bytes()).hexdigest()
            recorded_sha256 = item.get("sha256")

            # Only delete if file is clean and unmodified from the recorded manifest sha256
            if disk_sha256 == recorded_sha256:
                file_path.unlink()
                deleted.append(file_path)

        # Remove manifest.json
        manifest_path.unlink(missing_ok=True)

        # Clean up empty parent directories without touching directories that contain user files
        for root, _dirs, _files in os.walk(self.target_dir, topdown=False):
            p = Path(root)
            if p != self.target_dir:
                with contextlib.suppress(OSError):
                    p.rmdir()
        with contextlib.suppress(OSError):
            self.target_dir.rmdir()

        return deleted

    # Backwards compatibility alias: replace destructive wiping with non-destructive delete_owned
    delete_all = delete_owned
