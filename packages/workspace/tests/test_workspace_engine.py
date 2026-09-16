import tempfile
from pathlib import Path

from workspace_engine.cli.clean_workspace import clean_workspace
from workspace_engine.cli.set_java import detect_required_java_version
from workspace_engine.cli.stop_workspace import stop_workspace
from workspace_engine.common import (
    ProjectType,
    detect_project_type,
    parse_dotenv,
)
from workspace_engine.services.render_agents import render_agents_md, update_workspace_agents


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

    # Test packaged template fallback
    packaged_rendered = render_agents_md(None, "demo-ws", "repositories", ["api", "web"])
    assert "# Workspace: demo-ws" in packaged_rendered
    assert "- api" in packaged_rendered
    assert "- web" in packaged_rendered
    assert "Dedicated Worktrees & Branch Discipline" in packaged_rendered
    assert ".lavish" not in packaged_rendered
    assert "claude-yolo" not in packaged_rendered
    assert "docker/scripts/run-unit-tests.sh" not in packaged_rendered


def test_repository_updates_preserve_workspace_policy_and_notes(tmp_path):
    workspace = tmp_path / "feature"
    workspace.mkdir()
    update_workspace_agents(workspace, ["api"])
    target = workspace / "AGENTS.md"
    target.write_text(target.read_text() + "\n## Custom notes\n\nKeep this decision.\n")
    update_workspace_agents(workspace, ["api", "web"])
    content = target.read_text()
    assert "Dedicated Worktrees & Branch Discipline" in content
    assert "- api" in content and "- web" in content
    assert "Keep this decision." in content
    update_workspace_agents(workspace, ["web"])
    content = target.read_text()
    assert "- api" not in content and "- web" in content
    assert "Dedicated Worktrees & Branch Discipline" in content
    assert "Keep this decision." in content


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
