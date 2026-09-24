import json
import subprocess
import sys
from pathlib import Path

from workspace_engine.services.detect import MAX_DEPTH, detect_stacks


def _touch(root: Path, relative: str, content: str = "") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_detects_java_docker_and_ci(tmp_path: Path) -> None:
    _touch(tmp_path, "pom.xml")
    _touch(tmp_path, "src/main/java/App.java")
    _touch(tmp_path, "Dockerfile")
    _touch(tmp_path, ".github/workflows/ci.yml")
    _touch(tmp_path, "src/main/resources/db/migration/V1__init.sql")

    stacks = detect_stacks(tmp_path).stacks

    assert stacks == ["docker", "github-actions", "java", "migrations", "sql"]


def test_detects_react_only_from_dependency(tmp_path: Path) -> None:
    _touch(tmp_path, "package.json", json.dumps({"dependencies": {"react": "^19"}}))
    _touch(tmp_path, "tsconfig.json")
    assert {"node", "react", "typescript"} <= set(detect_stacks(tmp_path).stacks)

    other = tmp_path / "other"
    _touch(other, "package.json", json.dumps({"dependencies": {"express": "^5"}}))
    assert "react" not in detect_stacks(other).stacks


def test_skips_dependency_folders_and_respects_depth(tmp_path: Path) -> None:
    _touch(tmp_path, "node_modules/lib/setup.py")
    _touch(tmp_path, ".venv/lib/site.py")
    _touch(tmp_path, "/".join(["d"] * (MAX_DEPTH + 1)) + "/go.mod")
    assert detect_stacks(tmp_path).stacks == []


def test_markers_are_bounded_and_json_contract_is_versioned(tmp_path: Path) -> None:
    for index in range(5):
        _touch(tmp_path, f"pkg/mod{index}.py")
    data = detect_stacks(tmp_path).to_dict()
    assert data["schema_version"] == 1
    assert data["stacks"] == ["python"]
    assert len(data["markers"]["python"]) == 3


def test_ws_detect_cli_json(tmp_path: Path) -> None:
    _touch(tmp_path, "go.mod")
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from workspace_engine.cli.main import main; sys.argv=sys.argv[1:]; main()",
            "ws",
            "detect",
            "--dir",
            str(tmp_path),
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        env={
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
            "PATH": "/usr/bin:/bin",
        },
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["stacks"] == ["go"]
