"""Contract tests for the cross-agent second brain (store, search, archive, import, CLI)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
from ai_governance.brain import archive as brain_archive
from ai_governance.brain import cli as brain_cli
from ai_governance.brain.search import SearchQuery, SearchSources, search
from ai_governance.brain.store import (
    BrainNote,
    BrainStore,
    NoteDraft,
    NoteFilter,
    SecretContentError,
    brain_root,
    derive_title,
    infer_repo,
    infer_scope,
    is_stale,
    parse_note,
    parse_ref,
    serialize_note,
    slugify,
)
from ai_governance.rules.catalog import RuleCatalog
from ai_governance.taskflow import cli as taskflow_cli
from ai_governance.taskflow.models import Task
from ai_governance.taskflow.store import TaskStore


@pytest.fixture()
def brain_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    root = tmp_path / "brain"
    monkeypatch.setenv("AI_GOVERNANCE_BRAIN_DIR", str(root))
    monkeypatch.setenv("AI_GOVERNANCE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("AI_GOVERNANCE_AGENT", "1")
    return root


def _init_repo(path: Path, *, remote: str = "") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "dev@example.com"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Dev"], check=True)
    if remote:
        subprocess.run(["git", "-C", str(path), "remote", "add", "origin", remote], check=True)
    return path


def _seed_rules_for_search(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path]:
    corp_dir = tmp_path / "corp"
    (corp_dir / "acme" / "rules").mkdir(parents=True)
    (corp_dir / ".hidden").mkdir(parents=True)
    (corp_dir / "acme" / "rules" / "deploy.md").write_text(
        "---\ntrigger: always_on\n---\n# Staging Deploy Guide\nVerify VPN before staging deploys.\n",
        encoding="utf-8",
    )
    (corp_dir / "acme" / "rules" / "plain_rule.md").write_text(
        "No heading here, only staging checklist.\n", encoding="utf-8"
    )
    monkeypatch.setenv("AI_GOVERNANCE_CORPORATE_DIR", str(corp_dir))

    pers_dir = tmp_path / "personal"
    (pers_dir / "rules").mkdir(parents=True)
    (pers_dir / "rules" / "style.md").write_text(
        "---\ntrigger: always_on\n---\n# Personal Style\nKeep staging tests fast.\n",
        encoding="utf-8",
    )
    (pers_dir / "rules" / "unrelated.md").write_text(
        "# Other\nNothing relevant.\n", encoding="utf-8"
    )
    return pers_dir, corp_dir


def _seed_search_world(
    brain_env: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> SearchSources:
    b_store = BrainStore(brain_env)
    b_store.add(
        NoteDraft(
            title="VPN before staging",
            body="Connect VPN before deploying to staging cluster.\n\n" + ("long " * 35),
            kind="gotcha",
            scope="acme",
            tags=("vpn", "staging"),
        )
    )
    b_store.add(NoteDraft(title="Local Python", body="Mention staging checks.", kind="howto"))
    pers_dir, corp_dir = _seed_rules_for_search(monkeypatch, tmp_path)
    t_store = TaskStore(tmp_path / "state" / "taskflow")
    acme_repo = _init_repo(tmp_path / "acme" / "orders")
    t_store.create(
        Task(
            id="TASK-99",
            title="Rollout staging gateway",
            summary="Enable canary checks in staging",
            status="closed",
            facts=[{"text": "Staging secret api_key=leakme123 must stay hidden"}],
            decisions=[{"text": "Use blue-green", "why": "safer staging rollback"}],
            links=[{"title": "Staging dashboard", "url": "https://dash.example/staging"}],
            references=[{"kind": "jira", "value": "TASK-99", "url": "https://jira/TASK-99"}],
            repos=[{"path": ""}, {"path": str(acme_repo)}],
        )
    )
    t_store.create(Task(id="TASK-100", title="Personal notes", summary="Not a match"))
    return SearchSources(b_store, t_store, pers_dir, corp_dir)


def _seed_claude_memories(tmp_path: Path) -> Path:
    claude_dir = tmp_path / "claude-projects"
    wt1 = claude_dir / "repo-wt1" / "memory"
    wt2 = claude_dir / "repo-wt2" / "memory"
    wt1.mkdir(parents=True)
    wt2.mkdir(parents=True)
    (wt1 / "MEMORY.md").write_text("# Index\n- link\n", encoding="utf-8")
    old_note = wt1 / "feedback_node.md"
    old_note.write_text(
        "---\nno-colon-line\nname: Node version\ntype: feedback\n---\nOld body.\n", encoding="utf-8"
    )
    os.utime(old_note, (1_700_000_000, 1_700_000_000))
    new_note = wt2 / "feedback_node.md"
    new_note.write_text(
        "---\nname: Node version\ntype: feedback\n---\nUse Node 20 via nvm.\n", encoding="utf-8"
    )
    os.utime(new_note, (1_700_001_000, 1_700_001_000))
    (wt2 / "secret_note.md").write_text(
        f"---\nname: Bad secret\ntype: reference\n---\nUse {'ghp_' + 'a' * 30}.\n",
        encoding="utf-8",
    )
    (wt2 / "empty.md").write_text("---\nname: Empty\n---\n", encoding="utf-8")
    (wt1 / "existing.md").write_text(
        "---\nname: Existing note\n---\nDuplicate.\n", encoding="utf-8"
    )
    return claude_dir


# -- store & frontmatter -------------------------------------------------------------------


def test_brain_root_uses_env_override_or_data_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("AI_GOVERNANCE_BRAIN_DIR", raising=False)
    monkeypatch.setenv("AI_GOVERNANCE_DATA_DIR", str(tmp_path / "xdg-data"))
    assert brain_root() == tmp_path / "xdg-data" / "brain"

    monkeypatch.setenv("AI_GOVERNANCE_BRAIN_DIR", str(tmp_path / "custom-brain"))
    assert brain_root() == tmp_path / "custom-brain"


def test_frontmatter_roundtrip_handles_special_chars_and_markdown_hr(tmp_path: Path) -> None:
    note = BrainNote(
        slug="api-gotcha",
        title='TASK-1: Don\'t use "latest" [v2] #note',
        kind="gotcha",
        scope="personal",
        body="Line one\n\n---\n\nLine after horizontal rule.",
        tags=("true", 'say "hi", ok', "node-20"),
        repos=("payments-api",),
        source="PR #42: fix",
        created="2026-01-10",
        updated="2026-02-15",
    )
    rendered = serialize_note(note)
    parsed = parse_note(rendered, slug=note.slug, scope=note.scope, path=tmp_path / "api-gotcha.md")
    assert parsed.title == note.title
    assert parsed.kind == "gotcha"
    assert parsed.tags == note.tags
    assert parsed.repos == ("payments-api",)
    assert parsed.source == note.source
    assert parsed.created == "2026-01-10" and parsed.updated == "2026-02-15"
    assert "---" in parsed.body and "Line after horizontal rule." in parsed.body


def test_parse_note_handles_block_lists_single_quotes_and_plain_markdown(tmp_path: Path) -> None:
    raw = (
        "---\n# comment line\nnot a pair\ntitle: 'O''Brien''s rule'\n"
        "source: \"bad\\escape\"\ntags:\n  - alpha\n  - 'beta'\n"
        "repos: solo-repo\nempty_val: \n---\n\nBody text.\n"
    )
    parsed = parse_note(raw, slug="hand-edited", scope="personal")
    assert parsed.title == "O'Brien's rule"
    assert parsed.source == r"bad\escape"
    assert parsed.tags == ("alpha", "beta")
    assert parsed.repos == ("solo-repo",)
    assert parsed.kind == "reference"

    plain_file = tmp_path / "plain.md"
    plain_file.write_text("# Heading Title\n\nSome detail.\n", encoding="utf-8")
    plain = parse_note(
        plain_file.read_text(encoding="utf-8"), slug="plain", scope="acme", path=plain_file
    )
    assert plain.title == "Heading Title" and plain.scope == "acme" and len(plain.created) == 10
    assert derive_title("   \n\n") == "Untitled note"
    assert derive_title("x" * 100).endswith("…")


def test_store_add_collision_get_ambiguity_and_missing(brain_env: Path) -> None:
    store = BrainStore(brain_env)
    n1 = store.add(NoteDraft(body="Use Node 20 for local dev.", repos=("web-app",), tags=("node",)))
    n2 = store.add(NoteDraft(body="Use Node 20 for local dev.", repos=("web-app",)))
    assert n1.slug == "use-node-20-for-local-dev"
    assert n2.slug == "use-node-20-for-local-dev-2"
    assert store.get(n1.slug).ref == n1.ref and store.get(n1.ref).body == n1.body

    with pytest.raises(FileExistsError, match="already exists"):
        store.add(NoteDraft(body="Dup", slug=n1.slug))

    store.add(NoteDraft(body="Same slug in acme", scope="acme", slug=n1.slug))
    with pytest.raises(ValueError, match="Ambiguous note"):
        store.get(n1.slug)
    assert store.get(n1.slug, scope="acme").scope == "acme"
    assert store.get(f"acme/{n1.slug}").scope == "acme"

    with pytest.raises(FileNotFoundError, match="not found"):
        store.get("does-not-exist")
    with pytest.raises(FileNotFoundError, match="not found"):
        store.get("personal/does-not-exist")


@pytest.mark.parametrize(
    ("bad_call", "pattern"),
    [
        (lambda s: s.add(NoteDraft(body="   ")), "empty"),
        (lambda s: s.add(NoteDraft(body="hi", kind="bogus")), "Invalid note kind"),
        (lambda s: s.add(NoteDraft(body="hi", scope="../etc")), "Invalid scope"),
        (lambda s: s.add(NoteDraft(body="hi", slug="../escape")), "Invalid note slug"),
        (lambda s: s.add(NoteDraft(body="hi", slug="UpperCase")), "Invalid note slug"),
        (lambda s: parse_ref("a/b/c"), "Invalid note reference"),
        (lambda s: s.list(NoteFilter(stale_days=0)), "stale_days"),
    ],
    ids=[
        "empty-body",
        "bad-kind",
        "bad-scope",
        "traversal-slug",
        "uppercase-slug",
        "three-part-ref",
        "nonpositive-stale-days",
    ],
)
def test_store_validation_rejects_invalid_inputs(brain_env: Path, bad_call, pattern: str) -> None:
    store = BrainStore(brain_env)
    with pytest.raises(ValueError, match=pattern):
        bad_call(store)


@pytest.mark.parametrize(
    "draft",
    [
        NoteDraft(body="Use token " + "ghp_" + "a" * 30 + " for staging"),
        NoteDraft(body="Key is " + "sk-" + "a" * 28),
        NoteDraft(body="AWS " + "AKIA" + "0" * 16 + " here"),
        NoteDraft(body="jwt " + "eyJ" + "a" * 15 + "." + "eyJ" + "b" * 15 + "." + "c" * 15),
        NoteDraft(body="Safe body", title="api_key=supersecret123"),
        NoteDraft(body="Safe body", tags=("password=hunter2",)),
        NoteDraft(body="Safe body", source="token: " + "xoxb-" + "1" * 12 + "-abc"),
    ],
    ids=[
        "github-token",
        "openai-key",
        "aws-key",
        "jwt",
        "title-apikey",
        "tag-password",
        "source-slack",
    ],
)
def test_store_rejects_secret_content_without_writing_to_disk(
    brain_env: Path, draft: NoteDraft
) -> None:
    store = BrainStore(brain_env)
    with pytest.raises(SecretContentError, match="secret or credential"):
        store.add(draft)
    assert not brain_env.exists() or list(brain_env.rglob("*.md")) == []


def test_store_list_filters_by_kind_scope_repo_and_stale(brain_env: Path) -> None:
    store = BrainStore(brain_env)
    notes = (
        BrainNote(
            "old-gotcha",
            "Old",
            "gotcha",
            "personal",
            "Old",
            repos=("RepoA",),
            created="2025-01-01",
            updated="2025-01-01",
        ),
        BrainNote(
            "fresh-ref",
            "Fresh",
            "reference",
            "acme",
            "Fresh",
            repos=("repoa",),
            created="2026-11-01",
            updated="2026-11-01",
        ),
        BrainNote("weird-date", "Weird", "howto", "personal", "Bad", created="bad", updated="bad"),
    )
    for note in notes:
        store.save(note)
    (brain_env / "personal" / "README.md").write_text("# Ignore me\n", encoding="utf-8")

    assert store.count_for_repo("repoa") == 2
    assert [n.slug for n in store.list(NoteFilter(kind="gotcha"))] == ["old-gotcha"]
    assert [n.slug for n in store.list(NoteFilter(scope="acme"))] == ["fresh-ref"]
    assert [n.slug for n in store.list(NoteFilter(scope="missing"))] == []
    stale = store.list(NoteFilter(stale_days=90, today=date(2026, 11, 19)))
    assert [n.slug for n in stale] == ["old-gotcha"]
    assert is_stale(notes[2], days=30, today=date(2026, 11, 19)) is False
    with pytest.raises(ValueError, match="stale_days"):
        is_stale(notes[0], days=0)


def test_infer_repo_is_stable_across_worktrees_bare_repos_and_missing_dirs(tmp_path: Path) -> None:
    main_repo = _init_repo(tmp_path / "payments-service")
    (main_repo / "README.md").write_text("hi\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(main_repo), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(main_repo), "commit", "-q", "-m", "init"], check=True)
    sub = main_repo / "src"
    sub.mkdir()
    wt = tmp_path / "throwaway-worktree-99"
    subprocess.run(
        ["git", "-C", str(main_repo), "worktree", "add", "-q", "-b", "wt", str(wt)], check=True
    )
    bare = tmp_path / "shared.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)

    assert infer_repo(main_repo) == "payments-service"
    assert infer_repo(sub) == "payments-service"
    assert infer_repo(wt) == "payments-service"
    assert infer_repo(bare) == "shared"
    assert infer_repo(tmp_path) is None
    assert infer_repo(tmp_path / "nonexistent") is None
    assert slugify("!!!") == "note"


def test_infer_scope_detects_company_from_path_remote_or_existing_brain_scope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    corp = tmp_path / "corporate-rules"
    (corp / "acme" / "rules").mkdir(parents=True)
    monkeypatch.setenv("AI_GOVERNANCE_CORPORATE_DIR", str(corp))
    brain_dir = tmp_path / "brain"
    (brain_dir / "globex").mkdir(parents=True)

    by_path = _init_repo(tmp_path / "acme" / "billing")
    by_remote = _init_repo(tmp_path / "misc" / "svc", remote="git@github.com:globex/svc.git")
    no_remote = _init_repo(tmp_path / "personal" / "toy")

    assert infer_scope(by_path, root=brain_dir) == "acme"
    assert infer_scope(by_remote, root=brain_dir) == "globex"
    assert infer_scope(no_remote, root=brain_dir) == "personal"


# -- unified search ------------------------------------------------------------------------


def test_unified_search_hits_brain_taskflow_and_rules_with_filters(
    brain_env: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sources = _seed_search_world(brain_env, monkeypatch, tmp_path)

    all_hits = search(SearchQuery(text="staging"), sources)
    assert {h.source for h in all_hits} == {"brain", "taskflow", "rule"}
    task_hit = next(h for h in all_hits if h.source == "taskflow")
    assert "TASK-99" in task_hit.title and "leakme123" not in task_hit.snippet
    assert all(len(h.snippet) <= 120 for h in all_hits)

    only_gotcha = search(SearchQuery(text="staging", kind="gotcha"), sources)
    assert len(only_gotcha) == 1 and only_gotcha[0].kind == "gotcha"
    assert search(SearchQuery(text="staging", kind="task"), sources)[0].source == "taskflow"

    acme_rules = search(SearchQuery(text="staging", kind="rule", scope="acme"), sources)
    assert {h.title for h in acme_rules} == {"Staging Deploy Guide", "plain_rule"}

    personal_only = search(SearchQuery(text="staging", scope="personal"), sources)
    assert all(h.scope == "personal" for h in personal_only)
    assert {h.source for h in personal_only} == {"brain", "rule"}


def test_search_handles_missing_sources_unreadable_rules_and_validation(
    brain_env: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pers_dir = tmp_path / "personal"
    (pers_dir / "rules").mkdir(parents=True)
    bad_rule = pers_dir / "rules" / "broken.md"
    bad_rule.write_text("# Broken\nhello\n", encoding="utf-8")
    real_read = Path.read_text

    def failing_read(self: Path, *a, **kw) -> str:
        if self == bad_rule:
            raise OSError("permission denied")
        return real_read(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", failing_read)
    sources = SearchSources(
        brain_store=BrainStore(brain_env),
        personal_dir=pers_dir,
        corporate_dir=tmp_path / "no-corp-dir",
    )
    assert search(SearchQuery(text="hello"), sources) == []

    with pytest.raises(ValueError, match="empty"):
        search(SearchQuery(text="   "))
    with pytest.raises(ValueError, match="Invalid search kind"):
        search(SearchQuery(text="ok", kind="unknown"))
    with pytest.raises(ValueError, match="limit"):
        search(SearchQuery(text="ok", limit=0))


# -- archive & taskflow close hook ---------------------------------------------------------


def test_archive_task_is_idempotent_scrubs_secrets_and_supports_dry_run(
    brain_env: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    corp = tmp_path / "corp"
    (corp / "acme" / "rules").mkdir(parents=True)
    monkeypatch.setenv("AI_GOVERNANCE_CORPORATE_DIR", str(corp))

    b_store = BrainStore(brain_env)
    t_store = TaskStore(tmp_path / "state" / "taskflow")
    repo = _init_repo(tmp_path / "acme" / "my-service")
    t_store.create(
        Task(
            id="TASK-42",
            title="Harden checkout",
            summary="Stop duplicate orders",
            status="closed",
            facts=[{"text": "Token password=secretval should be scrubbed"}],
            decisions=[{"text": "Return 409", "why": "owner enforces uniqueness"}],
            links=[{"title": "ADR", "url": "https://example.com/adr"}],
            references=[{"kind": "pr", "value": "#77", "url": "https://gh/org/repo/pull/77"}],
            repos=[{"path": ""}, {"path": str(repo), "branch": "feat/checkout", "pr": "#77"}],
        )
    )
    opts = brain_archive.ArchiveOptions(brain_store=b_store, task_store=t_store)
    preview = brain_archive.archive_task(
        "TASK-42", brain_archive.ArchiveOptions(b_store, t_store, dry_run=True)
    )
    assert preview.action == "would-create" and b_store.list() == []

    first = brain_archive.archive_task("TASK-42", opts)
    assert first.action == "created" and first.note.scope == "acme"
    assert first.note.repos == ("my-service",)
    assert "secretval" not in first.note.body and "[redacted]" in first.note.body

    assert brain_archive.archive_task("TASK-42", opts).action == "unchanged"
    t_store.mutate("TASK-42", lambda t: t.facts.append({"text": "Verified in staging"}))
    third = brain_archive.archive_task("TASK-42", opts)
    assert third.action == "updated" and len(b_store.list()) == 1

    explicit = brain_archive.archive_task(
        "TASK-42", brain_archive.ArchiveOptions(b_store, t_store, scope="personal")
    )
    assert explicit.note.scope == "personal"


def test_taskflow_close_archives_automatically_and_warns_without_blocking_on_failure(
    brain_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    t_store = TaskStore(tmp_path / "state" / "taskflow")
    t_store.create(Task(id="TASK-10", title="Ship archive", summary="All green"))
    assert taskflow_cli.main(["close", "TASK-10", "--reason", "done"]) == 0
    assert t_store.get("TASK-10").status == "closed"
    archived = BrainStore(brain_env).get("archive-task-10")
    assert archived.kind == "archive" and "All green" in archived.body

    t_store.create(Task(id="TASK-11", title="Close survives error"))
    monkeypatch.setattr(
        brain_archive, "archive_task", lambda *_a, **_k: (_ for _ in ()).throw(OSError("disk full"))
    )
    capsys.readouterr()
    assert taskflow_cli.main(["close", "TASK-11", "--reason", "done anyway"]) == 0
    assert t_store.get("TASK-11").status == "closed"
    assert "WARN: could not archive 'TASK-11'" in capsys.readouterr().err


# -- curated import (Claude & Codex) -------------------------------------------------------


def test_import_claude_deduplicates_worktrees_skips_secrets_and_defaults_to_dry_run(
    brain_env: Path, tmp_path: Path
) -> None:
    claude_dir = _seed_claude_memories(tmp_path)
    b_store = BrainStore(brain_env)
    b_store.add(NoteDraft(body="Already here", title="Existing note"))

    preview = brain_archive.import_memories(
        brain_archive.ImportOptions(source="claude", source_dir=claude_dir, apply=False), b_store
    )
    by_slug = {c.slug: c for c in preview.candidates}
    assert preview.applied is False and len(b_store.list()) == 1
    assert by_slug["node-version"].duplicates == 1 and by_slug["node-version"].kind == "gotcha"
    assert by_slug["bad-secret"].status == "secret"
    assert by_slug["existing-note"].status == "duplicate"

    applied = brain_archive.import_memories(
        brain_archive.ImportOptions(source="claude", source_dir=claude_dir, apply=True), b_store
    )
    assert applied.applied is True and [n.slug for n in applied.imported] == ["node-version"]
    assert "Use Node 20 via nvm." in b_store.get("node-version").body
    with pytest.raises(FileNotFoundError):
        b_store.get("bad-secret")


def test_import_codex_and_missing_or_unreadable_sources(
    brain_env: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    codex_dir = tmp_path / "codex-memories"
    codex_dir.mkdir()
    (codex_dir / "MEMORY.md").write_text(
        "# Codex Memory\n\n## Empty Section\n\n## Gradle Cache\nRun --no-daemon.\n\n"
        "## Postgres Port\nLocal docker runs on 5433.\n",
        encoding="utf-8",
    )
    (codex_dir / "extra.md").write_text("Standalone note body.\n", encoding="utf-8")

    b_store = BrainStore(brain_env)
    report = brain_archive.import_memories(
        brain_archive.ImportOptions(
            source="codex", source_dir=codex_dir, select=("postgres-port",), apply=True
        ),
        b_store,
    )
    assert [n.slug for n in report.imported] == ["postgres-port"]
    assert "5433" in b_store.get("postgres-port").body

    empty_claude = brain_archive.import_memories(
        brain_archive.ImportOptions(source="claude", source_dir=tmp_path / "missing-claude"),
        b_store,
    )
    empty_codex = brain_archive.import_memories(
        brain_archive.ImportOptions(source="codex", source_dir=tmp_path / "missing-codex"), b_store
    )
    assert empty_claude.candidates == () and empty_codex.candidates == ()

    monkeypatch.setattr(
        Path, "read_text", lambda self, *a, **kw: (_ for _ in ()).throw(OSError("io"))
    )
    assert brain_archive._read_claude_entry(codex_dir / "extra.md") is None
    assert brain_archive._split_codex_memory_md(codex_dir / "MEMORY.md") == []

    with pytest.raises(ValueError, match="Unsupported import source"):
        brain_archive.import_memories(brain_archive.ImportOptions(source="other"), b_store)


# -- CLI end-to-end ------------------------------------------------------------------------


def test_brain_cli_add_and_show_and_secret_rejection(
    brain_env: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "demo-repo")
    monkeypatch.chdir(repo)
    assert brain_cli.main([]) == 0
    assert "ai-governance brain" in capsys.readouterr().out

    assert brain_cli.main(["add", "Auto-detect repo gotcha"]) == 0
    assert "Saved personal/auto-detect-repo-gotcha" in capsys.readouterr().out
    assert BrainStore(brain_env).get("auto-detect-repo-gotcha").repos == ("demo-repo",)

    assert (
        brain_cli.main(
            [
                "add",
                "Run uv sync before pytest",
                "--kind",
                "howto",
                "--tag",
                "uv,pytest",
                "--source",
                "TASK-1",
                "--json",
            ]
        )
        == 0
    )
    added = json.loads(capsys.readouterr().out)
    assert added["slug"] == "run-uv-sync-before-pytest" and added["tags"] == ["uv", "pytest"]

    assert brain_cli.main(["show", added["slug"]]) == 0
    assert "Run uv sync before pytest" in capsys.readouterr().out
    assert brain_cli.main(["show", added["slug"], "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ref"] == added["ref"]

    assert brain_cli.main(["add", "Leak " + "ghp_" + "a" * 30, "--no-repo"]) == 1
    assert "secret or credential" in capsys.readouterr().err


def test_brain_cli_list_and_search_text_and_json(
    brain_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    BrainStore(brain_env).add(
        NoteDraft(body="Run uv sync before pytest", kind="howto", repos=("demo-repo",))
    )
    assert brain_cli.main(["list", "--repo", "demo-repo"]) == 0
    assert "personal/run-uv-sync-before-pytest" in capsys.readouterr().out

    assert brain_cli.main(["list", "--json"]) == 0
    assert len(json.loads(capsys.readouterr().out)) == 1

    assert brain_cli.main(["list", "--stale"]) == 0
    assert "No brain notes found" in capsys.readouterr().out

    assert brain_cli.main(["search", "pytest"]) == 0
    assert "Run uv sync before pytest" in capsys.readouterr().out

    assert brain_cli.main(["search", "pytest", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["source"] == "brain"

    assert brain_cli.main(["search", "nonexistent-needle"]) == 0
    assert "No matches" in capsys.readouterr().out


def test_brain_cli_edit_updates_noop_reverts_on_secret_and_handles_bad_editor(
    brain_env: Path, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    store = BrainStore(brain_env)
    note = store.add(NoteDraft(body="Initial body", title="Editable", slug="editable"))
    assert note.path is not None

    noop = tmp_path / "noop.py"
    noop.write_text("import sys; sys.exit(0)\n", encoding="utf-8")
    assert brain_cli.main(["edit", "editable", "--editor", f"{sys.executable} {noop}"]) == 0
    assert brain_cli.main(["edit", "editable", "--editor", "   "]) == 1

    editor_ok = tmp_path / "edit_ok.py"
    editor_ok.write_text(
        "import sys; p = sys.argv[1]; "
        "t = open(p).read().replace('Initial body', 'Updated body'); "
        "open(p, 'w').write(t)\n",
        encoding="utf-8",
    )
    assert brain_cli.main(["edit", "editable", "--editor", f"{sys.executable} {editor_ok}"]) == 0
    assert "Updated body" in store.get("editable").body

    editor_secret = tmp_path / "edit_secret.py"
    editor_secret.write_text(
        "import sys; open(sys.argv[1], 'a').write('\\npassword=supersecret\\n')\n",
        encoding="utf-8",
    )
    capsys.readouterr()
    assert (
        brain_cli.main(["edit", "editable", "--editor", f"{sys.executable} {editor_secret}"]) == 1
    )
    assert "secret or credential" in capsys.readouterr().err
    assert "supersecret" not in note.path.read_text(encoding="utf-8")

    editor_fail = tmp_path / "edit_fail.py"
    editor_fail.write_text("import sys; sys.exit(2)\n", encoding="utf-8")
    assert brain_cli.main(["edit", "editable", "--editor", f"{sys.executable} {editor_fail}"]) == 1


def test_brain_cli_archive_and_import_subcommands(
    brain_env: Path, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    t_store = TaskStore(tmp_path / "state" / "taskflow")
    assert brain_cli.main(["archive"]) == 1
    assert "Provide a task id" in capsys.readouterr().err
    assert brain_cli.main(["archive", "--all-closed"]) == 0
    assert "No closed tasks" in capsys.readouterr().out

    t_store.create(Task(id="TASK-A", title="Closed A", status="closed", summary="Done A"))
    t_store.create(Task(id="TASK-B", title="Closed B", status="closed", summary="Done B"))
    assert brain_cli.main(["archive", "TASK-A"]) == 0
    assert "created: personal/archive-task-a" in capsys.readouterr().out
    assert brain_cli.main(["archive", "--all-closed"]) == 0
    assert "TASK-B" in capsys.readouterr().out
    assert brain_cli.main(["archive", "--all-closed", "--json"]) == 0
    assert {r["task_id"] for r in json.loads(capsys.readouterr().out)} == {"TASK-A", "TASK-B"}

    claude_dir = tmp_path / "claude"
    assert brain_cli.main(["import", "--from", "claude", "--source-dir", str(claude_dir)]) == 0
    assert "No candidate notes" in capsys.readouterr().out

    (claude_dir / "p1" / "memory").mkdir(parents=True)
    (claude_dir / "p1" / "memory" / "tip.md").write_text(
        "---\nname: Tip\n---\nUse uv.\n", encoding="utf-8"
    )
    assert brain_cli.main(["import", "--from", "claude", "--dry-run", "--apply"]) == 1
    assert (
        brain_cli.main(["import", "--from", "claude", "--source-dir", str(claude_dir), "--dry-run"])
        == 0
    )
    assert "Dry-run: 1 new candidate(s)" in capsys.readouterr().out
    assert (
        brain_cli.main(["import", "--from", "claude", "--source-dir", str(claude_dir), "--apply"])
        == 0
    )
    assert "Imported 1 note(s)" in capsys.readouterr().out
    assert (
        brain_cli.main(["import", "--from", "claude", "--source-dir", str(claude_dir), "--json"])
        == 0
    )
    assert json.loads(capsys.readouterr().out)["applied"] is False


def test_every_brain_subcommand_has_help_and_taskflow_rule_stays_within_budget() -> None:
    parser = brain_cli.build_parser()
    sub = next(a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction")
    described = {choice.dest: choice.help for choice in sub._choices_actions}
    assert set(described) == {"add", "search", "show", "list", "edit", "archive", "import"}
    assert all(text for text in described.values())

    rule = RuleCatalog().get("14-taskflow")
    assert rule is not None
    assert "ai-governance brain search" in rule.content
    assert "ai-governance brain add" in rule.content
    assert len(rule.content.encode("utf-8")) <= 1500
