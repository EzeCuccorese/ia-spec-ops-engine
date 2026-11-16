"""Skills: one real directory per skill, exposed to Claude, Codex and Antigravity via symlinks."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from ai_governance import skills
from ai_governance.install.doctor import FAIL, check
from ai_governance.install.installer import install_user, uninstall_user
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
    (path / "scripts" / "run.sh").write_text(f"echo {body}\n")
    return path


def _claude(home: Path, name: str) -> Path:
    return home / ".claude" / "skills" / name


def _antigravity(home: Path, name: str) -> Path:
    return home / ".gemini" / "config" / "skills" / name


def _codex(home: Path, name: str) -> Path:
    return home / ".agents" / "skills" / name


def test_personal_skill_is_linked_to_every_agent(installed: Path, store: Path) -> None:
    source = _make_skill(store, "demo-skill")
    skills.sync_skills()
    for link in (
        _claude(installed, "demo-skill"),
        _codex(installed, "demo-skill"),
        _antigravity(installed, "demo-skill"),
    ):
        assert link.is_symlink()
        assert os.readlink(link) == str(source.resolve())
        assert (link / "scripts" / "run.sh").is_file()
    assert not (installed / ".codex" / "skills" / "demo-skill").exists()


def test_install_links_skills_without_a_separate_sync(home: Path, store: Path) -> None:
    _make_skill(store, "demo-skill")
    install_user(AGENT_IDS)
    assert _claude(home, "demo-skill").is_symlink()
    install_user(AGENT_IDS)
    assert _claude(home, "demo-skill").is_symlink()


def test_sync_never_overwrites_a_foreign_entry(installed: Path, store: Path) -> None:
    _make_skill(store, "demo-skill")
    foreign = _make_skill(installed / ".claude" / "skills", "demo-skill", body="mine")
    skills.sync_skills()
    assert not foreign.is_symlink()
    assert "mine" in (foreign / "SKILL.md").read_text()
    assert _codex(installed, "demo-skill").is_symlink()


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


def test_company_pack_skill_is_linked(installed: Path, tmp_path: Path) -> None:
    source = _make_skill(tmp_path / "corporate" / "acme" / "skills", "pack-skill")
    skills.sync_skills()
    assert os.readlink(_claude(installed, "pack-skill")) == str(source.resolve())
    assert _codex(installed, "pack-skill").is_symlink()


def test_rm_removes_store_directory_and_links(installed: Path, store: Path) -> None:
    _make_skill(store, "demo-skill")
    skills.sync_skills()
    assert skills.remove_skill("demo-skill") == 0
    assert not (store / "demo-skill").exists()
    assert not _claude(installed, "demo-skill").is_symlink()
    assert not _codex(installed, "demo-skill").is_symlink()


def test_rm_refuses_a_company_skill(installed: Path, tmp_path: Path) -> None:
    source = _make_skill(tmp_path / "corporate" / "acme" / "skills", "pack-skill")
    with pytest.raises(SkillError, match="only personal"):
        skills.remove_skill("pack-skill")
    assert source.is_dir()


def test_add_copies_into_the_store_and_links(installed: Path, store: Path, tmp_path: Path) -> None:
    origin = _make_skill(tmp_path / "elsewhere", "demo-skill")
    assert skills.add_skill(origin, name="renamed") == 0
    assert (store / "renamed" / "scripts" / "run.sh").is_file()
    assert os.readlink(_claude(installed, "renamed")) == str((store / "renamed").resolve())
    with pytest.raises(SkillError):
        skills.add_skill(tmp_path / "elsewhere", name="nope")


def test_uninstall_removes_skill_links(installed: Path, store: Path) -> None:
    _make_skill(store, "demo-skill")
    skills.sync_skills()
    uninstall_user(AGENT_IDS)
    assert not _claude(installed, "demo-skill").is_symlink()
    assert not _codex(installed, "demo-skill").is_symlink()


def test_doctor_flags_a_link_whose_source_vanished(installed: Path, store: Path) -> None:
    source = _make_skill(store, "demo-skill")
    skills.sync_skills()
    for child in sorted(source.rglob("*"), reverse=True):
        child.unlink() if child.is_file() else child.rmdir()
    source.rmdir()
    failing = [row for row in check(installed) if row[1] == FAIL]
    assert any("demo-skill" in row[2] for row in failing)


def test_migrate_moves_the_real_directory_and_relinks(installed: Path, store: Path) -> None:
    _make_skill(installed / ".agents" / "skills", "legacy")
    (installed / ".claude" / "skills").mkdir(parents=True, exist_ok=True)
    _claude(installed, "legacy").symlink_to("../../.agents/skills/legacy")
    (installed / ".codex" / "skills").mkdir(parents=True)
    (installed / ".codex" / "skills" / "legacy").symlink_to("../../.agents/skills/legacy")

    assert skills.migrate_skills(MigrateOptions()) == 0

    assert (store / "legacy" / "scripts" / "run.sh").is_file()
    assert os.readlink(_claude(installed, "legacy")) == str((store / "legacy").resolve())
    assert os.readlink(_codex(installed, "legacy")) == str((store / "legacy").resolve())
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
    assert os.readlink(_codex(installed, "legacy")) == str((store / "legacy").resolve())


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
    assert os.readlink(_claude(installed, "legacy")) == str(moved.resolve())


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
    _codex(installed, "demo-skill").unlink()
    _make_skill(installed / ".claude" / "skills", "extra")
    capsys.readouterr()

    assert skills.main(["list"]) == 0
    listed = capsys.readouterr().out
    assert "claude=linked" in listed and "codex=missing" in listed and "extra" in listed

    assert skills.main(["sync"]) == 0
    assert _codex(installed, "demo-skill").is_symlink()
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


def test_install_keeps_existing_skill_links_on_collision(
    installed: Path, store: Path, tmp_path: Path
) -> None:
    _make_skill(store, "demo-skill")
    install_user(AGENT_IDS)
    _make_skill(tmp_path / "corporate" / "acme" / "skills", "demo-skill")

    report = install_user(AGENT_IDS)
    assert any("provided twice" in w for w in report.warnings)
    assert _claude(installed, "demo-skill").is_symlink()
