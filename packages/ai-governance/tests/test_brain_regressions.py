"""Targeted regression tests for second brain store, archive, search, and CLI fixes."""

from __future__ import annotations

import stat
import sys
from pathlib import Path

import pytest
from ai_governance.brain import archive as brain_archive
from ai_governance.brain import cli as brain_cli
from ai_governance.brain import search as brain_search
from ai_governance.brain.search import SearchQuery, SearchSources, search
from ai_governance.brain.store import (
    BrainNote,
    BrainStore,
    NoteDraft,
    NoteFilter,
    SecretContentError,
    has_secret,
    parse_note,
    serialize_note,
)
from ai_governance.taskflow.models import Task
from ai_governance.taskflow.store import TaskStore


@pytest.fixture()
def brain_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    root = tmp_path / "brain"
    monkeypatch.setenv("AI_GOVERNANCE_BRAIN_DIR", str(root))
    monkeypatch.setenv("AI_GOVERNANCE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("AI_GOVERNANCE_AGENT", "1")
    return root


# -- 1. Atomic add() race & collision safety -----------------------------------------------


def test_store_add_retries_unique_slug_when_concurrent_writer_wins_race(
    brain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = BrainStore(brain_env)
    real_unique = BrainStore._unique_slug
    raced = False

    def racing_unique(self: BrainStore, scope: str, base_slug: str) -> str:
        nonlocal raced
        slug = real_unique(self, scope, base_slug)
        if not raced:
            raced = True
            target = self.note_path(scope, slug)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("---\ntitle: Winner\nkind: gotcha\n---\n\nWinner body.\n", "utf-8")
        return slug

    monkeypatch.setattr(BrainStore, "_unique_slug", racing_unique)
    created = store.add(NoteDraft(body="Second writer body", title="Same Title"))
    assert created.slug == "same-title-2"
    assert store.get("same-title").body == "Winner body."
    assert store.get("same-title-2").body == "Second writer body"


# -- 2. Expanded has_secret detection ------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        '{"password": "s3cr3tValue"}',
        "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA\n-----END RSA PRIVATE KEY-----",
        "Authorization: Bearer super-secret-token-123",
        "Connect to https://u:p4ss@host/x for staging",
        "Token github_pat_" + "A1b2C3d4E5f6G7h8I9j0K1l2",
        "aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    ],
    ids=[
        "json-quoted-password",
        "pem-rsa-private-key",
        "authorization-bearer",
        "url-basic-auth",
        "github-fine-grained-pat",
        "aws-secret-access-key",
    ],
)
def test_has_secret_rejects_expanded_credential_shapes(brain_env: Path, payload: str) -> None:
    assert has_secret(payload) is True
    store = BrainStore(brain_env)
    with pytest.raises(SecretContentError, match="secret or credential"):
        store.add(NoteDraft(body=payload))
    assert not brain_env.exists() or list(brain_env.rglob("*.md")) == []


# -- 3. Unique archive filenames, collision safety & scope migration -----------------------


def test_archive_distinguishes_similar_task_ids_without_overwriting(
    brain_env: Path, tmp_path: Path
) -> None:
    b_store = BrainStore(brain_env)
    t_store = TaskStore(tmp_path / "state" / "taskflow")
    for task_id in ("build_one", "build-one", "PROJ-1_2", "proj-1-2"):
        t_store.create(Task(id=task_id, title=f"Title for {task_id}", summary=f"Body {task_id}"))
    opts = brain_archive.ArchiveOptions(brain_store=b_store, task_store=t_store)
    results = [
        brain_archive.archive_task(tid, opts)
        for tid in ("build_one", "build-one", "PROJ-1_2", "proj-1-2")
    ]
    slugs = {r.note.slug for r in results}
    assert len(slugs) == 4
    assert len(b_store.list(NoteFilter(kind="archive"))) == 4


def test_archive_preserves_normal_note_on_slug_collision_and_stays_idempotent(
    brain_env: Path, tmp_path: Path
) -> None:
    b_store = BrainStore(brain_env)
    t_store = TaskStore(tmp_path / "state" / "taskflow")
    t_store.create(Task(id="TASK-77", title="Collision task", summary="Archive body"))
    colliding_slug = brain_archive.archive_slug("TASK-77")
    b_store.add(NoteDraft(body="Do not overwrite me", title="Normal", slug=colliding_slug))

    opts = brain_archive.ArchiveOptions(brain_store=b_store, task_store=t_store)
    first = brain_archive.archive_task("TASK-77", opts)
    assert first.action == "created"
    assert first.note.slug != colliding_slug
    assert b_store.get(colliding_slug).body == "Do not overwrite me"
    assert b_store.get(colliding_slug).kind == "gotcha"

    second = brain_archive.archive_task("TASK-77", opts)
    assert second.action == "unchanged"
    assert second.note.slug == first.note.slug


def test_archive_scope_change_moves_note_without_leaving_duplicates(
    brain_env: Path, tmp_path: Path
) -> None:
    b_store = BrainStore(brain_env)
    t_store = TaskStore(tmp_path / "state" / "taskflow")
    t_store.create(Task(id="TASK-88", title="Move scope", summary="Initial"))

    first = brain_archive.archive_task(
        "TASK-88", brain_archive.ArchiveOptions(b_store, t_store, scope="acme")
    )
    assert first.action == "created" and first.note.path is not None and first.note.path.is_file()

    preview = brain_archive.archive_task(
        "TASK-88", brain_archive.ArchiveOptions(b_store, t_store, scope="personal", dry_run=True)
    )
    assert preview.action == "would-update" and first.note.path.is_file()

    moved = brain_archive.archive_task(
        "TASK-88", brain_archive.ArchiveOptions(b_store, t_store, scope="personal")
    )
    assert moved.action == "updated" and moved.note.scope == "personal"
    assert not first.note.path.exists()
    assert len(b_store.list(NoteFilter(kind="archive"))) == 1


# -- 4. Safe brain edit --------------------------------------------------------------------


def _write_editor_script(path: Path, body: str) -> str:
    path.write_text(body, encoding="utf-8")
    return f"{sys.executable} {path}"


def test_cmd_edit_uses_private_temp_file_and_ignores_partial_write_on_nonzero_exit(
    brain_env: Path, tmp_path: Path
) -> None:
    store = BrainStore(brain_env)
    note = store.add(NoteDraft(body="Original safe body", title="Editable", slug="safe-edit"))
    assert note.path is not None
    original_raw = note.path.read_text(encoding="utf-8")
    seen_file = tmp_path / "seen.txt"
    editor = _write_editor_script(
        tmp_path / "partial_fail.py",
        "import os, stat, sys\n"
        f"p = sys.argv[1]\n"
        f"mode = stat.S_IMODE(os.stat(p).st_mode)\n"
        f"open({str(seen_file)!r}, 'w').write(f'{{p}}|{{oct(mode)}}')\n"
        "open(p, 'w').write('CORRUPTED PARTIAL WRITE')\n"
        "sys.exit(1)\n",
    )
    assert brain_cli.main(["edit", "safe-edit", "--editor", editor]) == 1
    seen_path, seen_mode = seen_file.read_text(encoding="utf-8").split("|")
    assert Path(seen_path).resolve() != note.path.resolve()
    assert seen_mode == oct(stat.S_IRUSR | stat.S_IWUSR)
    assert note.path.read_text(encoding="utf-8") == original_raw


def test_cmd_edit_rejects_invalid_frontmatter_and_preserves_live_file(
    brain_env: Path, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    store = BrainStore(brain_env)
    note = store.add(NoteDraft(body="Valid body", title="FM Test", slug="fm-test"))
    assert note.path is not None
    original_raw = note.path.read_text(encoding="utf-8")

    unclosed = _write_editor_script(
        tmp_path / "unclosed.py",
        "import sys; open(sys.argv[1], 'w').write('---\\ntitle: Broken\\nno closing fence\\n')\n",
    )
    assert brain_cli.main(["edit", "fm-test", "--editor", unclosed]) == 1
    assert "Invalid frontmatter" in capsys.readouterr().err
    assert note.path.read_text(encoding="utf-8") == original_raw

    bad_kind = _write_editor_script(
        tmp_path / "bad_kind.py",
        "import sys; p = sys.argv[1]; "
        "t = open(p).read().replace('kind: gotcha', 'kind: bogus'); "
        "open(p, 'w').write(t)\n",
    )
    assert brain_cli.main(["edit", "fm-test", "--editor", bad_kind]) == 1
    assert "Invalid note kind" in capsys.readouterr().err
    assert note.path.read_text(encoding="utf-8") == original_raw


def test_cmd_edit_forces_original_scope_and_aborts_on_concurrent_edit(
    brain_env: Path, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    store = BrainStore(brain_env)
    note = store.add(NoteDraft(body="Before edit", title="Scope Lock", slug="scope-lock"))
    assert note.path is not None

    scope_hijack = _write_editor_script(
        tmp_path / "hijack.py",
        "import sys; p = sys.argv[1]; "
        "t = open(p).read().replace('scope: personal', 'scope: acme').replace('Before', 'After'); "
        "open(p, 'w').write(t)\n",
    )
    assert brain_cli.main(["edit", "scope-lock", "--editor", scope_hijack]) == 0
    reloaded = store.get("scope-lock", scope="personal")
    assert reloaded.scope == "personal" and "After edit" in reloaded.body
    assert not (brain_env / "acme" / "scope-lock.md").exists()

    concurrent = _write_editor_script(
        tmp_path / "concurrent.py",
        f"import sys\n"
        f"open({str(note.path)!r}, 'a').write('\\nExternal edit.\\n')\n"
        f"open(sys.argv[1], 'a').write('\\nMy edit.\\n')\n",
    )
    capsys.readouterr()
    assert brain_cli.main(["edit", "scope-lock", "--editor", concurrent]) == 1
    assert "changed on disk" in capsys.readouterr().err
    live_text = note.path.read_text(encoding="utf-8")
    assert "External edit." in live_text and "My edit." not in live_text


# -- 5. Import selection before deduplication ----------------------------------------------


def test_import_select_filters_before_title_deduplication(brain_env: Path, tmp_path: Path) -> None:
    claude_dir = tmp_path / "claude"
    mem = claude_dir / "proj" / "memory"
    mem.mkdir(parents=True)
    (mem / "alpha.md").write_text("---\nname: Shared Finding\n---\nAlpha body.\n", encoding="utf-8")
    (mem / "beta.md").write_text("---\nname: Shared Finding\n---\nBeta body.\n", encoding="utf-8")
    entries = [
        brain_archive._RawEntry(
            slug="alpha",
            title="Shared Finding",
            kind="reference",
            body="Alpha body.",
            source="claude:proj/alpha.md",
            origin_path=str(mem / "alpha.md"),
            mtime=1.0,
        ),
        brain_archive._RawEntry(
            slug="beta",
            title="Shared Finding",
            kind="reference",
            body="Beta body.",
            source="claude:proj/beta.md",
            origin_path=str(mem / "beta.md"),
            mtime=2.0,
        ),
    ]
    b_store = BrainStore(brain_env)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(brain_archive, "_discover_claude", lambda _d: entries)
        report = brain_archive.import_memories(
            brain_archive.ImportOptions(source="claude", select=("beta",), apply=True),
            b_store,
        )
    assert [n.slug for n in report.imported] == ["beta"]
    assert b_store.get("beta").body == "Beta body."


# -- 6. Frontmatter round-trip with Unicode line separators --------------------------------


def test_frontmatter_roundtrip_preserves_unicode_line_separators() -> None:
    tricky_title = "Line\u2028Sep\u2029Next\u0085Line"
    note = BrainNote(
        slug="unicode-sep",
        title=tricky_title,
        kind="reference",
        scope="personal",
        body="Body text.",
        tags=("a\u2028b", "c\u2029d"),
        source="src\u0085ref",
        created="2026-01-01",
        updated="2026-01-01",
    )
    parsed = parse_note(serialize_note(note), slug=note.slug, scope=note.scope)
    assert parsed.title == tricky_title
    assert parsed.tags == ("a\u2028b", "c\u2029d")
    assert parsed.source == "src\u0085ref"


# -- 7. Non-UTF-8 files skip and warn ------------------------------------------------------


def test_non_utf8_files_warn_and_skip_in_store_and_archive(brain_env: Path, tmp_path: Path) -> None:
    store = BrainStore(brain_env)
    store.add(NoteDraft(body="Good note", title="Valid"))
    bad_note = brain_env / "personal" / "corrupt-note.md"
    bad_note.write_bytes(b"\xff\xfe\x00invalid utf8")

    with pytest.warns(UserWarning, match="Skipping unreadable brain note"):
        listed = store.list()
    assert [n.slug for n in listed] == ["valid"]

    claude_bad = tmp_path / "claude" / "p1" / "memory" / "bad.md"
    claude_bad.parent.mkdir(parents=True)
    claude_bad.write_bytes(b"\x80\x81\x82")
    with pytest.warns(UserWarning, match="Skipping unreadable memory file"):
        assert brain_archive._read_claude_entry(claude_bad) is None

    codex_bad = tmp_path / "codex" / "MEMORY.md"
    codex_bad.parent.mkdir(parents=True)
    codex_bad.write_bytes(b"\xff\xfe")
    with pytest.warns(UserWarning, match="Skipping unreadable memory file"):
        assert brain_archive._split_codex_memory_md(codex_bad) == []


# -- 8 & 9. Search: unscoped rules & lazy/cached infer_scope -------------------------------


def test_unscoped_search_searches_all_available_corporate_rule_scopes(
    brain_env: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    corp_dir = tmp_path / "corp"
    for pack in ("acme", "globex"):
        (corp_dir / pack / "rules").mkdir(parents=True)
        (corp_dir / pack / "rules" / "guide.md").write_text(
            f"# {pack} Deploy Guide\nCheck staging health.\n", encoding="utf-8"
        )
    monkeypatch.setenv("AI_GOVERNANCE_CORPORATE_DIR", str(corp_dir))
    sources = SearchSources(brain_store=BrainStore(brain_env), corporate_dir=corp_dir)

    hits = search(SearchQuery(text="staging", kind="rule"), sources)
    assert {h.scope for h in hits} == {"acme", "globex"}
    assert search(SearchQuery(text="staging", kind="rule", scope="personal"), sources) == []


def test_search_skips_infer_scope_when_unscoped_and_caches_by_repo_path(
    brain_env: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    b_store = BrainStore(brain_env)
    t_store = TaskStore(tmp_path / "state" / "taskflow")
    shared_repo = tmp_path / "acme" / "service"
    shared_repo.mkdir(parents=True)
    t_store.create(Task(id="TASK-1", title="Deploy alpha", repos=[{"path": str(shared_repo)}]))
    t_store.create(Task(id="TASK-2", title="Deploy beta", repos=[{"path": str(shared_repo)}]))
    corp_dir = tmp_path / "corp"
    corp_dir.mkdir()

    calls: list[Path] = []

    def fake_infer_scope(cwd: Path | None = None, root: Path | None = None) -> str:
        assert cwd is not None
        calls.append(cwd)
        return "acme"

    monkeypatch.setattr(brain_search, "infer_scope", fake_infer_scope)
    sources = SearchSources(b_store, t_store, corp_dir)

    unscoped = search(SearchQuery(text="deploy", kind="task"), sources)
    assert len(unscoped) == 2
    assert calls == []

    scoped = search(SearchQuery(text="deploy", kind="task", scope="acme"), sources)
    assert len(scoped) == 2
    assert len(calls) == 1


# -- 10. Preserve first-line indentation in body -------------------------------------------


def test_body_preserves_first_line_indentation_across_roundtrip(brain_env: Path) -> None:
    indented = "    def example():\n        return 42"
    store = BrainStore(brain_env)
    added = store.add(NoteDraft(body=indented, title="Code snippet"))
    reloaded = store.get(added.slug)
    assert reloaded.body == indented
