"""Skills: one real source directory per skill, copied to Claude, Codex and Antigravity."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from ai_governance import skills
from ai_governance.install.doctor import FAIL, WARN, check
from ai_governance.install.engine import LinkArtifact, _record
from ai_governance.install.installer import (
    global_ledger,
    install_user,
    sync_skill_links,
    uninstall_user,
)
from ai_governance.skills import MigrateOptions, SkillError

AGENT_IDS = ["claude", "codex", "antigravity"]


@pytest.fixture
def home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("AI_GOVERNANCE_STATE_DIR", str(home / "state"))
    monkeypatch.setenv("AI_GOVERNANCE_CONFIG_DIR", str(home / ".config" / "ai-governance"))
    monkeypatch.setenv("AI_GOVERNANCE_PERSONAL_DIR", str(tmp_path / "personal"))
    monkeypatch.setenv("AI_GOVERNANCE_CORPORATE_DIR", str(tmp_path / "corporate"))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.delenv("AI_GOVERNANCE_BIN_DIR", raising=False)
    return home


@pytest.fixture
def store(tmp_path: Path) -> Path:
    return tmp_path / "personal" / "skills"


@pytest.fixture
def installed(home: Path) -> Path:
    install_user(AGENT_IDS)
    return home


def _make_skill(parent: Path, name: str, body: str = "demo") -> Path:
    path = parent / name
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text(f"---\nname: {name}\n---\n{body}\n")
    (path / "scripts").mkdir()
    script = path / "scripts" / "run.sh"
    script.write_text(f"echo {body}\n")
    script.chmod(0o755)
    return path


def _claude(home: Path, name: str) -> Path:
    return home / ".claude" / "skills" / name


def _antigravity(home: Path, name: str) -> Path:
    return home / ".gemini" / "config" / "skills" / name


def _codex(home: Path, name: str) -> Path:
    return home / ".agents" / "skills" / name


def test_personal_skill_is_copied_to_every_agent(installed: Path, store: Path) -> None:
    _make_skill(store, "demo-skill")
    skills.sync_skills()
    for copy in (
        _claude(installed, "demo-skill"),
        _codex(installed, "demo-skill"),
        _antigravity(installed, "demo-skill"),
    ):
        assert copy.is_dir() and not copy.is_symlink()
        script = copy / "scripts" / "run.sh"
        assert script.read_text() == "echo demo\n"
        assert os.access(script, os.X_OK)
    assert not (installed / ".codex" / "skills" / "demo-skill").exists()


def test_install_copies_skills_without_a_separate_sync(home: Path, store: Path) -> None:
    _make_skill(store, "demo-skill")
    install_user(AGENT_IDS)
    copy = _claude(home, "demo-skill")
    assert copy.is_dir() and not copy.is_symlink()
    second = install_user(AGENT_IDS)
    assert ("unchanged", str(copy)) in second.changes


def test_sync_updates_modified_and_deletes_removed_source_files(
    installed: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _make_skill(store, "demo-skill")
    skills.sync_skills()
    (source / "SKILL.md").write_text("---\nname: demo-skill\n---\nupdated\n")
    (source / "notes.md").write_text("new file\n")
    shutil.rmtree(source / "scripts")
    capsys.readouterr()

    assert skills.list_skills() == 0
    assert "claude=outdated" in capsys.readouterr().out
    assert any(s == WARN and "outdated" in d and "demo-skill" in d for _, s, d in check(installed))

    skills.sync_skills()
    for copy in (
        _claude(installed, "demo-skill"),
        _codex(installed, "demo-skill"),
        _antigravity(installed, "demo-skill"),
    ):
        assert "updated" in (copy / "SKILL.md").read_text()
        assert (copy / "notes.md").read_text() == "new file\n"
        assert not (copy / "scripts").exists()


def test_sync_protects_locally_edited_copy_unless_forced(
    installed: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_skill(store, "demo-skill")
    skills.sync_skills()
    claude_copy = _claude(installed, "demo-skill")
    (claude_copy / ".DS_Store").write_bytes(b"junk")
    pycache = claude_copy / "__pycache__"
    pycache.mkdir()
    (pycache / "mod.cpython-311.pyc").write_bytes(b"pyc")
    assert skills.list_skills() == 0
    assert "claude=synced" in capsys.readouterr().out

    (claude_copy / "SKILL.md").write_text("local edit\n")
    capsys.readouterr()

    assert skills.list_skills() == 0
    listed = capsys.readouterr().out
    assert "claude=edited" in listed and "codex=synced" in listed
    assert any(
        s == WARN and "edited locally" in d and "demo-skill" in d for _, s, d in check(installed)
    )

    report = sync_skill_links()
    assert any("edited locally" in w for w in report.warnings)
    assert (claude_copy / "SKILL.md").read_text() == "local edit\n"

    assert skills.main(["sync", "--force"]) == 0
    assert "demo" in (claude_copy / "SKILL.md").read_text()

    (claude_copy / "SKILL.md").write_text("keep on delete\n")
    shutil.rmtree(store / "demo-skill")
    delete_report = sync_skill_links()
    assert any("edited locally; not removed" in w for w in delete_report.warnings)
    assert (claude_copy / "SKILL.md").read_text() == "keep on delete\n"
    assert not _codex(installed, "demo-skill").exists()


def test_sync_never_overwrites_a_foreign_entry(installed: Path, store: Path) -> None:
    _make_skill(store, "demo-skill")
    foreign = _make_skill(installed / ".claude" / "skills", "demo-skill", body="mine")
    report = sync_skill_links()
    assert any("not created by ai-governance" in w for w in report.warnings)
    assert not foreign.is_symlink()
    assert "mine" in (foreign / "SKILL.md").read_text()
    codex_copy = _codex(installed, "demo-skill")
    assert codex_copy.is_dir() and not codex_copy.is_symlink()


def test_old_ledger_link_is_replaced_by_copy_on_sync(
    installed: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _make_skill(store, "demo-skill")
    claude_entry = _claude(installed, "demo-skill")
    claude_entry.parent.mkdir(parents=True, exist_ok=True)
    claude_entry.symlink_to(source.resolve())
    ledger = global_ledger()
    artifact = LinkArtifact(claude_entry, str(source.resolve()))
    _record(
        ledger,
        {
            "agent": "claude",
            "kind": "link",
            "path": ledger.key(artifact.path),
            "target": artifact.target,
        },
    )
    ledger.save(sync_skill_links(dry_run=True), dry_run=False)
    capsys.readouterr()

    assert skills.list_skills() == 0
    assert "claude=outdated" in capsys.readouterr().out

    skills.sync_skills()
    assert claude_entry.is_dir() and not claude_entry.is_symlink()
    assert (claude_entry / "scripts" / "run.sh").read_text() == "echo demo\n"
    updated_ledger = global_ledger()
    assert updated_ledger.find("link", claude_entry) is None
    assert updated_ledger.find("dir", claude_entry) is not None


def test_name_collision_between_layers_is_an_error(
    installed: Path, store: Path, tmp_path: Path
) -> None:
    _make_skill(store, "demo-skill")
    _make_skill(tmp_path / "corporate" / "acme" / "skills", "demo-skill")
    with pytest.raises(SkillError) as raised:
        skills.collect()
    message = str(raised.value)
    assert "personal" in message and "company:acme" in message


def test_collision_with_a_bundled_skill_is_an_error(installed: Path, store: Path) -> None:
    _make_skill(store, "taskflow")
    with pytest.raises(SkillError, match="bundled"):
        skills.collect()


def test_company_pack_skill_is_copied(installed: Path, tmp_path: Path) -> None:
    _make_skill(tmp_path / "corporate" / "acme" / "skills", "pack-skill", body="corp")
    skills.sync_skills()
    for copy in (_claude(installed, "pack-skill"), _codex(installed, "pack-skill")):
        assert copy.is_dir() and not copy.is_symlink()
        assert "corp" in (copy / "SKILL.md").read_text()


def test_rm_removes_store_directory_and_copies(installed: Path, store: Path) -> None:
    _make_skill(store, "demo-skill")
    skills.sync_skills()
    assert skills.remove_skill("demo-skill") == 0
    assert not (store / "demo-skill").exists()
    assert not _claude(installed, "demo-skill").exists()
    assert not _codex(installed, "demo-skill").exists()
    assert not _antigravity(installed, "demo-skill").exists()


def test_rm_refuses_a_company_skill(installed: Path, tmp_path: Path) -> None:
    source = _make_skill(tmp_path / "corporate" / "acme" / "skills", "pack-skill")
    with pytest.raises(SkillError, match="only personal"):
        skills.remove_skill("pack-skill")
    assert source.is_dir()


def test_add_copies_into_the_store_and_agents(installed: Path, store: Path, tmp_path: Path) -> None:
    origin = _make_skill(tmp_path / "elsewhere", "demo-skill")
    assert skills.add_skill(origin, name="renamed") == 0
    assert (store / "renamed" / "scripts" / "run.sh").is_file()
    copy = _claude(installed, "renamed")
    assert copy.is_dir() and not copy.is_symlink()
    assert (copy / "scripts" / "run.sh").read_text() == "echo demo\n"
    with pytest.raises(SkillError, match="not a skill directory"):
        skills.add_skill(tmp_path / "elsewhere", name="nope")


def test_uninstall_removes_skill_copies(installed: Path, store: Path) -> None:
    _make_skill(store, "demo-skill")
    skills.sync_skills()
    uninstall_user(AGENT_IDS)
    assert not _claude(installed, "demo-skill").exists()
    assert not _codex(installed, "demo-skill").exists()
    assert not _antigravity(installed, "demo-skill").exists()


def test_doctor_flags_outdated_source_and_missing_copy(installed: Path, store: Path) -> None:
    source = _make_skill(store, "demo-skill")
    skills.sync_skills()
    assert not any("demo-skill" in d and s != "OK" for _, s, d in check(installed))
    shutil.rmtree(source)
    assert any(s == WARN and "outdated" in d and "demo-skill" in d for _, s, d in check(installed))
    shutil.rmtree(_claude(installed, "demo-skill"))
    assert any(s == FAIL and "missing" in d and "demo-skill" in d for _, s, d in check(installed))


def test_migrate_moves_the_real_directory_and_creates_copies(installed: Path, store: Path) -> None:
    _make_skill(installed / ".agents" / "skills", "legacy")
    (installed / ".claude" / "skills").mkdir(parents=True, exist_ok=True)
    _claude(installed, "legacy").symlink_to("../../.agents/skills/legacy")
    (installed / ".codex" / "skills").mkdir(parents=True)
    (installed / ".codex" / "skills" / "legacy").symlink_to("../../.agents/skills/legacy")

    assert skills.migrate_skills(MigrateOptions()) == 0

    assert (store / "legacy" / "scripts" / "run.sh").is_file()
    for copy in (
        _claude(installed, "legacy"),
        _codex(installed, "legacy"),
        _antigravity(installed, "legacy"),
    ):
        assert copy.is_dir() and not copy.is_symlink()
        assert (copy / "scripts" / "run.sh").read_text() == "echo demo\n"
    assert not (installed / ".codex" / "skills" / "legacy").exists()
    assert [p.name for p in store.iterdir()] == ["legacy"]


def test_migrate_refuses_differing_copies(
    installed: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_skill(installed / ".agents" / "skills", "legacy", body="one")
    _make_skill(installed / ".claude" / "skills", "legacy", body="two")

    assert skills.migrate_skills(MigrateOptions(names=["legacy"])) == 1

    assert not store.exists()
    assert _claude(installed, "legacy").is_dir() and not _claude(installed, "legacy").is_symlink()
    assert (_codex(installed, "legacy") / "scripts" / "run.sh").read_text() == "echo one\n"
    out = capsys.readouterr()
    printed = "".join((out.out + out.err).split())  # the console may wrap long paths
    assert str(_claude(installed, "legacy")) in printed
    assert str(_codex(installed, "legacy")) in printed


def test_migrate_from_picks_one_differing_copy(installed: Path, store: Path) -> None:
    _make_skill(installed / ".agents" / "skills", "legacy", body="one")
    keep = _make_skill(installed / ".claude" / "skills", "legacy", body="two")

    options = MigrateOptions(names=["legacy"], picked=keep)
    assert skills.migrate_skills(options) == 0
    assert (store / "legacy" / "scripts" / "run.sh").read_text() == "echo two\n"
    codex_copy = _codex(installed, "legacy")
    assert codex_copy.is_dir() and not codex_copy.is_symlink()
    assert (codex_copy / "scripts" / "run.sh").read_text() == "echo two\n"


def test_migrate_dry_run_changes_nothing(installed: Path, store: Path) -> None:
    real = _make_skill(installed / ".agents" / "skills", "legacy")
    (installed / ".claude" / "skills").mkdir(parents=True, exist_ok=True)
    _claude(installed, "legacy").symlink_to("../../.agents/skills/legacy")

    assert skills.migrate_skills(MigrateOptions(dry_run=True)) == 0

    assert real.is_dir() and not real.is_symlink()
    assert _claude(installed, "legacy").is_symlink()
    assert os.readlink(_claude(installed, "legacy")) == "../../.agents/skills/legacy"
    assert not store.exists()


def test_migrate_into_a_pack(installed: Path, tmp_path: Path) -> None:
    _make_skill(installed / ".agents" / "skills", "legacy")

    assert skills.migrate_skills(MigrateOptions(names=["legacy"], pack="acme")) == 1  # no such pack
    (tmp_path / "corporate" / "acme").mkdir(parents=True)
    assert skills.migrate_skills(MigrateOptions(names=["legacy"], pack="acme")) == 0
    moved = tmp_path / "corporate" / "acme" / "skills" / "legacy"
    assert (moved / "SKILL.md").is_file()
    copy = _claude(installed, "legacy")
    assert copy.is_dir() and not copy.is_symlink()


def test_migrate_leaves_bundled_and_dot_entries_alone(installed: Path, store: Path) -> None:
    _make_skill(installed / ".agents" / "skills", "legacy")
    (installed / ".agents" / "skills" / ".system").mkdir()
    bundled = installed / ".agents" / "skills" / "test-audit"
    assert bundled.is_dir()

    assert skills.migrate_skills(MigrateOptions()) == 0

    assert (bundled / "SKILL.md").is_file() and not bundled.is_symlink()
    assert (installed / ".agents" / "skills" / ".system").is_dir()
    assert [p.name for p in store.iterdir()] == ["legacy"]


def test_cli_lifecycle_list_states_and_errors(
    installed: Path, store: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert skills.main([]) == 0
    assert skills.main(["list"]) == 0
    assert "No skills found" in capsys.readouterr().out

    origin = _make_skill(tmp_path / "src", "demo-skill")
    assert skills.main(["add", str(origin)]) == 0
    shutil.rmtree(_codex(installed, "demo-skill"))
    _make_skill(installed / ".claude" / "skills", "extra")
    capsys.readouterr()

    assert skills.main(["list"]) == 0
    listed = capsys.readouterr().out
    assert "claude=synced" in listed and "codex=missing" in listed and "extra" in listed

    assert skills.main(["sync"]) == 0
    codex_copy = _codex(installed, "demo-skill")
    assert codex_copy.is_dir() and not codex_copy.is_symlink()
    assert skills.main(["rm", "demo-skill"]) == 0
    assert skills.main(["rm", "demo-skill"]) == 1


def test_sync_warns_when_no_agents_installed(
    home: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_skill(store, "demo-skill")
    assert skills.sync_skills() == 0
    captured = capsys.readouterr()
    assert "No agent installed" in captured.out + captured.err


def test_skill_validation_and_unknown_pack_errors(
    installed: Path, store: Path, tmp_path: Path
) -> None:
    origin = _make_skill(tmp_path / "src", "demo-skill")
    for bad_name in ("", "bad name"):
        with pytest.raises(SkillError, match="Invalid skill name"):
            skills.add_skill(origin, name=bad_name)
    assert skills.add_skill(origin) == 0
    with pytest.raises(SkillError, match="already exists"):
        skills.add_skill(origin)
    (tmp_path / "corporate").mkdir()
    with pytest.raises(SkillError, match="Unknown corporate pack"):
        skills.collect(pack_names=["unknown"])


def test_migrate_skips_non_skills_and_handles_edge_errors(
    installed: Path, store: Path, tmp_path: Path
) -> None:
    claude_skills = installed / ".claude" / "skills"
    claude_skills.mkdir(parents=True, exist_ok=True)
    (claude_skills / "README.md").write_text("docs\n")
    (claude_skills / "empty-dir").mkdir()

    legacy = _make_skill(installed / ".agents" / "skills", "legacy")
    (legacy / "alias").symlink_to("SKILL.md")
    assert skills.main(["migrate"]) == 0
    assert (store / "legacy" / "alias").is_symlink()
    assert (_claude(installed, "legacy") / "alias").is_symlink()

    (claude_skills / "broken").symlink_to(tmp_path / "missing")
    assert skills.migrate_skills(MigrateOptions(names=["broken"])) == 1
    assert skills.migrate_skills(MigrateOptions(names=["legacy"])) == 1  # already provided
    assert skills.migrate_skills(MigrateOptions(names=["absent"])) == 1  # not found
    with pytest.raises(SkillError, match="--from needs exactly one"):
        skills.migrate_skills(MigrateOptions(names=["a", "b"], picked=tmp_path))

    dup = _make_skill(installed / ".agents" / "skills", "dup")
    assert skills.migrate_skills(MigrateOptions(names=["dup"], picked=tmp_path / "other")) == 1
    (store / "dup").mkdir()
    assert dup.is_dir() and skills.migrate_skills(MigrateOptions(names=["dup"])) == 1


def test_migrate_dry_run_under_symlinked_home_omits_self_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    real_home = tmp_path / "real-home"
    real_home.mkdir()
    link_home = tmp_path / "link-home"
    link_home.symlink_to(real_home)
    monkeypatch.setattr(Path, "home", lambda: link_home)
    monkeypatch.setenv("AI_GOVERNANCE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("AI_GOVERNANCE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("AI_GOVERNANCE_PERSONAL_DIR", str(tmp_path / "personal"))
    install_user(["claude"])
    _make_skill(link_home / ".claude" / "skills", "legacy")
    capsys.readouterr()

    assert skills.migrate_skills(MigrateOptions(dry_run=True)) == 0
    out = capsys.readouterr().out
    assert "move " in out and "delete " not in out


def test_install_keeps_existing_skill_copies_on_collision(
    installed: Path, store: Path, tmp_path: Path
) -> None:
    _make_skill(store, "demo-skill")
    install_user(AGENT_IDS)
    _make_skill(tmp_path / "corporate" / "acme" / "skills", "demo-skill")

    report = install_user(AGENT_IDS)
    assert any("provided twice" in w for w in report.warnings)
    copy = _claude(installed, "demo-skill")
    assert copy.is_dir() and not copy.is_symlink()


def test_personal_skills_dir_defaults_to_repo_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from ai_governance import skills
    from ai_governance.skills import personal_skills_dir

    repo_root = Path(__file__).resolve().parents[3]
    monkeypatch.delenv("AI_GOVERNANCE_PERSONAL_DIR", raising=False)
    assert personal_skills_dir() == repo_root / "skills"
    assert personal_skills_dir(tmp_path) == tmp_path / "skills"

    # Wheel install (no checkout skills/ directory at parents[4]) falls back to personal_root/skills
    fake_wheel = tmp_path / "venv" / "lib" / "py" / "site-packages" / "ai_governance" / "skills.py"
    monkeypatch.setattr(skills, "__file__", str(fake_wheel))
    assert personal_skills_dir() == skills.config_dir() / "personal" / "skills"

    monkeypatch.setattr(skills, "__file__", "/a/b/skills.py")
    assert personal_skills_dir() == skills.config_dir() / "personal" / "skills"

    monkeypatch.setenv("AI_GOVERNANCE_PERSONAL_DIR", str(tmp_path / "custom"))
    assert personal_skills_dir() == tmp_path / "custom" / "skills"


def test_orca_and_bundled_skills_are_ignored_and_rejected(
    installed: Path, store: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in ("orchestration", "orca-cli", "orca-computer-use", "computer-use"):
        _make_skill(installed / ".agents" / "skills", name)
    origin = _make_skill(tmp_path / "src", "orca-cli")
    capsys.readouterr()

    assert skills.migrate_skills(MigrateOptions()) == 0
    assert not store.exists()
    assert skills.list_skills() == 0
    assert "No skills found" in capsys.readouterr().out

    with pytest.raises(SkillError, match="managed externally"):
        skills.add_skill(origin)
    assert skills.migrate_skills(MigrateOptions(names=["orca-cli"])) == 1
    assert skills.migrate_skills(MigrateOptions(names=["test-audit"])) == 1
