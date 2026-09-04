import tempfile
from pathlib import Path

from workspace_engine.cli.clean_workspace import clean_workspace
from workspace_engine.cli.set_java import detect_required_java_version
from workspace_engine.cli.stop_workspace import stop_workspace
from workspace_engine.services.render_agents import render_agents_md
from workspace_engine.utils import (
    FileLock,
    ProjectType,
    detect_project_type,
    parse_dotenv,
)


def test_file_lock():
    with tempfile.TemporaryDirectory() as tmpdir:
        lock_file = Path(tmpdir) / "test.lock"
        with FileLock(lock_file):
            assert lock_file.exists()
        # El archivo queda como descriptor de kernel, pero el lock se libera
        with FileLock(lock_file):
            assert lock_file.exists()


def test_detect_project_type():
    with tempfile.TemporaryDirectory() as tmpdir:
        d = Path(tmpdir)
        (d / "pom.xml").touch()
        assert detect_project_type(d) == ProjectType.MAVEN

        (d / "pom.xml").unlink()
        (d / "gradlew").touch()
        assert detect_project_type(d) == ProjectType.GRADLE

        (d / "gradlew").unlink()
        (d / "package.json").touch()
        assert detect_project_type(d) == ProjectType.NODE

        (d / "package.json").unlink()
        (d / "go.mod").touch()
        assert detect_project_type(d) == ProjectType.GO

        (d / "go.mod").unlink()
        (d / "pyproject.toml").touch()
        assert detect_project_type(d) == ProjectType.PYTHON


def test_parse_dotenv():
    with tempfile.TemporaryDirectory() as tmpdir:
        env_path = Path(tmpdir) / ".env"
        env_path.write_text('FOO=bar\n# Comment\nBAZ="hello world"\nEMPTY=\n')
        res = parse_dotenv(env_path)
        assert res["FOO"] == "bar"
        assert res["BAZ"] == "hello world"
        assert res["EMPTY"] == ""


def test_render_agents_md():
    with tempfile.TemporaryDirectory() as tmpdir:
        template = Path(tmpdir) / "template.md"
        template.write_text("# Workspace: {{WORKSPACE_NAME}}\n\n{{REPOSITORIES_LIST}}\n")
        rendered = render_agents_md(template, "my-feature", "repositories", ["repo-a", "repo-b"])
        assert "# Workspace: my-feature" in rendered
        assert "- repo-a" in rendered
        assert "- repo-b" in rendered


def test_clean_workspace():
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        (ws / ".git").mkdir()
        ai_dir = ws / ".ai-toolkit"
        ai_dir.mkdir()
        (ai_dir / "workspace.json").write_text("{}")
        (ai_dir / "cache.tmp").write_text("data")

        repos = ws / "repositories" / "my-service" / "node_modules"
        repos.mkdir(parents=True)
        (repos / "dummy.js").write_text("x")

        code = clean_workspace(ws)
        assert code == 0
        assert (ai_dir / "workspace.json").exists()
        assert not (ai_dir / "cache.tmp").exists()
        assert not (ws / "repositories" / "my-service" / "node_modules").exists()


def test_stop_workspace_empty():
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        (ws / ".git").mkdir()
        code = stop_workspace(ws)
        assert code == 0


def test_detect_required_java_version():
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        (ws / "pom.xml").write_text(
            "<project><properties><java.version>17</java.version></properties></project>"
        )
        assert detect_required_java_version(ws) == "17"

        (ws / "pom.xml").unlink()
        (ws / "build.gradle").write_text("sourceCompatibility = '21'")
        assert detect_required_java_version(ws) == "21"
