"""Unit tests for toolkit-menu: catalog schema, path existence, command building, context."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_TOOLKIT_DIR = Path(__file__).resolve().parents[3]
_MENU_DIR = _TOOLKIT_DIR / "devscripts" / "services" / "toolkit_menu"
sys.path.insert(0, str(_MENU_DIR))

from catalog import CatalogError, Script, load_catalog  # noqa: E402
from context import _parse_dotenv, detect_context  # noqa: E402
from runner import (  # noqa: E402
    FlagInjectionError,
    build_command,
    run_embedded,
    terminate_process,
)

CATALOG_PATH = _MENU_DIR / "scripts.json"


@pytest.fixture(scope="module")
def scripts() -> tuple[Script, ...]:
    return load_catalog(CATALOG_PATH)


def test_catalog_loads(scripts: tuple[Script, ...]) -> None:
    assert len(scripts) >= 15


def test_every_script_path_exists(scripts: tuple[Script, ...]) -> None:
    missing = [s.path for s in scripts if not (_TOOLKIT_DIR / s.path).exists()]
    assert not missing, f"catalog points at non-existent scripts: {missing}"


def test_no_duplicate_names(scripts: tuple[Script, ...]) -> None:
    names = [s.name for s in scripts]
    assert len(names) == len(set(names))


def test_bad_danger_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(
        '{"scripts":[{"name":"x","path":"p","danger":"nope","contexts":["workspace"]}]}'
    )
    with pytest.raises(CatalogError):
        load_catalog(bad)


def test_empty_contexts_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text('{"scripts":[{"name":"x","path":"p","danger":"safe","contexts":[]}]}')
    with pytest.raises(CatalogError):
        load_catalog(bad)


def test_missing_path_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text('{"scripts":[{"name":"x","danger":"safe","contexts":["workspace"]}]}')
    with pytest.raises(CatalogError):
        load_catalog(bad)


def test_flag_missing_flag_key_rejected(tmp_path: Path) -> None:
    # A flag entry with a valid 'type' but no 'flag' key must raise the documented
    # CatalogError contract, not a bare KeyError.
    bad = tmp_path / "bad.json"
    bad.write_text(
        '{"scripts":[{"name":"x","path":"p","danger":"safe","contexts":["workspace"],'
        '"flags":[{"type":"switch","help":"no flag key here"}]}]}'
    )
    with pytest.raises(CatalogError):
        load_catalog(bad)


def test_traversal_path_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(
        '{"scripts":[{"name":"x","path":"../../etc/passwd","danger":"safe",'
        '"contexts":["workspace"]}]}'
    )
    with pytest.raises(CatalogError):
        load_catalog(bad)


def test_absolute_path_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(
        '{"scripts":[{"name":"x","path":"/etc/passwd","danger":"safe",'
        '"contexts":["workspace"]}]}'
    )
    with pytest.raises(CatalogError):
        load_catalog(bad)


def test_run_unit_tests_catalog_uses_test_file_flag(scripts: tuple[Script, ...]) -> None:
    """docker/scripts/run-unit-tests.sh's arg parser only accepts --test-file
    (not --test) — its catalog entry must match the real script or the menu
    hands the user a flag that exits 2 with 'Unknown argument'."""
    entry = next(s for s in scripts if s.name in ("run-unit-tests", "run-unit-tests.sh"))
    flag_names = [f.flag for f in entry.flags]
    assert "--test-file" in flag_names
    assert "--test" not in flag_names


def test_prereqs_must_be_a_list_not_a_string(tmp_path: Path) -> None:
    # A bare string for 'prereqs' must be rejected, not silently iterated
    # character-by-character into prereqs=('g', 'i', 't', ...).
    bad = tmp_path / "bad.json"
    bad.write_text(
        '{"scripts":[{"name":"x","path":"p","danger":"safe",'
        '"contexts":["workspace"],"prereqs":"git required"}]}'
    )
    with pytest.raises(CatalogError):
        load_catalog(bad)


def test_duplicate_sanitized_flag_ids_rejected(tmp_path: Path) -> None:
    # Two flags whose strings differ but sanitize to the same widget id (per
    # screens.py's FlagsScreen._wid()) must fail at catalog-load time, not
    # crash Textual's FlagsScreen.compose() with a MountError at runtime.
    bad = tmp_path / "bad.json"
    bad.write_text(
        '{"scripts":[{"name":"x","path":"p","danger":"safe","contexts":["workspace"],'
        '"flags":[{"flag":"--foo bar","type":"switch","help":"a"},'
        '{"flag":"--foo-bar","type":"switch","help":"b"}]}]}'
    )
    with pytest.raises(CatalogError):
        load_catalog(bad)


def _script(**kw) -> Script:
    raw = {
        "name": "t.sh",
        "path": "t.sh",
        "summary": "",
        "danger": "safe",
        "interactive": False,
        "contexts": ["workspace"],
        "prereqs": [],
        "flags": [],
    }
    raw.update(kw)
    from catalog import _parse_script

    return _parse_script(raw)


def test_build_command_switches_and_values() -> None:
    s = _script(
        path="scripts/install-deps.sh",
        flags=[
            {"flag": "--force", "type": "switch", "help": ""},
            {"flag": "--parallel", "type": "value", "help": ""},
            {"flag": "<repo>", "type": "arg", "help": ""},
        ],
    )
    cmd = build_command(
        s, {"--force": True, "--parallel": "4", "<repo>": "ms-orders"}
    )
    assert cmd == ["bash", "scripts/install-deps.sh", "--force", "--parallel", "4", "ms-orders"]


def test_build_command_skips_empty_and_false() -> None:
    s = _script(
        flags=[
            {"flag": "--force", "type": "switch", "help": ""},
            {"flag": "--parallel", "type": "value", "help": ""},
        ],
    )
    assert build_command(s, {"--force": False, "--parallel": ""}) == ["bash", "t.sh"]


def test_build_command_python_interpreter() -> None:
    s = _script(path="scripts/run-workspace.py")
    assert build_command(s, {})[0] == "python3"


def test_build_command_arg_multiple_values() -> None:
    # '<repo...>' fields take several space-separated operands.
    s = _script(
        path="scripts/reset-repos.sh",
        flags=[{"flag": "<repo...>", "type": "arg", "help": ""}],
    )
    cmd = build_command(s, {"<repo...>": "ms-orders ms-payments"})
    assert cmd == ["bash", "scripts/reset-repos.sh", "ms-orders", "ms-payments"]


def test_build_command_arg_quoted_value_with_spaces() -> None:
    # A single operand containing spaces survives intact when quoted (shlex).
    s = _script(flags=[{"flag": "<workspace-name>", "type": "arg", "help": ""}])
    cmd = build_command(s, {"<workspace-name>": '"my workspace"'})
    assert cmd == ["bash", "t.sh", "my workspace"]


def test_build_command_arg_rejects_flag_injection() -> None:
    # A destructive script must not let an arg field smuggle an option flag.
    s = _script(
        path="scripts/reset-repos.sh",
        danger="destructive",
        flags=[{"flag": "<repo...>", "type": "arg", "help": ""}],
    )
    with pytest.raises(FlagInjectionError):
        build_command(s, {"<repo...>": "ms-orders --force"})


def test_build_command_arg_rejects_single_leading_dash() -> None:
    s = _script(flags=[{"flag": "<repo>", "type": "arg", "help": ""}])
    with pytest.raises(FlagInjectionError):
        build_command(s, {"<repo>": "--force"})


def test_build_command_arg_unterminated_quote_raises_flag_injection_error() -> None:
    # An unterminated quote (e.g. typed mid-keystroke) must not crash the app with
    # a bare ValueError from shlex.split — it must surface as the same typed error
    # callers already handle (FlagInjectionError), with a user-friendly message.
    s = _script(flags=[{"flag": "<workspace-name>", "type": "arg", "help": ""}])
    with pytest.raises(FlagInjectionError):
        build_command(s, {"<workspace-name>": '"my workspace'})


def test_preview_markup_escapes_untrusted_tokens() -> None:
    # A command token containing Rich/Textual markup (e.g. an 'arg' value like
    # "[/]") must render as literal text in the command preview, not be
    # interpreted as markup — Static.update() with markup=True (the default)
    # raises MarkupError on unbalanced tags, which would crash the app.
    pytest.importorskip(
        "textual", reason="textual is an optional TUI dep", exc_type=ImportError
    )
    from textual.widgets import Static

    from screens import _preview_markup

    cmd = ["bash", "t.sh", "[/]"]
    markup = _preview_markup(cmd)

    static = Static()
    static.update(markup)  # must not raise textual.markup.MarkupError

    assert "[/]" in str(static.content)


def test_detect_context_toolkit_root() -> None:
    ctx = detect_context(_TOOLKIT_DIR, cwd=_TOOLKIT_DIR)
    assert ctx.context == "toolkit-root"
    assert ctx.run_dir == _TOOLKIT_DIR


def test_reason_unavailable() -> None:
    ctx = detect_context(_TOOLKIT_DIR, cwd=_TOOLKIT_DIR)
    assert ctx.reason_unavailable(("toolkit-root",)) is None
    assert ctx.reason_unavailable(("workspace",)) == "Solo desde un workspace"


def test_detect_context_env_unreadable_no_crash(tmp_path: Path) -> None:
    """An unreadable config/.env (here: a directory) must not crash detection.

    Without repositories/ there's no way to look like a workspace, so the
    unreadable .env must fall through to the toolkit-root fallback rather than
    raising IsADirectoryError from _parse_dotenv.
    """
    fake_ws = tmp_path / "ws"
    (fake_ws / "config" / ".env").mkdir(parents=True)  # .env is a dir, not a file

    ctx = detect_context(_TOOLKIT_DIR, cwd=fake_ws)  # must not raise

    assert ctx.context == "toolkit-root"
    assert ctx.run_dir == _TOOLKIT_DIR


def test_detect_context_valid_workspace(tmp_path: Path) -> None:
    """A readable config/.env + repositories/ dir detects as a workspace."""
    fake_ws = tmp_path / "ws"
    (fake_ws / "config").mkdir(parents=True)
    (fake_ws / "config" / ".env").write_text("WORKSPACE_REPOSITORIES_DIR=repositories\n")
    (fake_ws / "repositories").mkdir()

    ctx = detect_context(_TOOLKIT_DIR, cwd=fake_ws)

    assert ctx.context == "workspace"
    assert ctx.run_dir == fake_ws.resolve()


def test_detect_context_nested_cwd_inside_repo(tmp_path: Path) -> None:
    """cwd nested inside repositories/<repo>/ (the realistic working location)
    must still detect the workspace root, not fall through to toolkit-root."""
    fake_ws = tmp_path / "ws"
    (fake_ws / "config").mkdir(parents=True)
    (fake_ws / "config" / ".env").write_text("WORKSPACE_REPOSITORIES_DIR=repositories\n")
    repo_dir = fake_ws / "repositories" / "myrepo"
    repo_dir.mkdir(parents=True)

    ctx = detect_context(_TOOLKIT_DIR, cwd=repo_dir)

    assert ctx.context == "workspace"
    assert ctx.run_dir == fake_ws.resolve()


def test_detect_context_deeply_nested_cwd(tmp_path: Path) -> None:
    """cwd nested several levels under repositories/<repo>/ still resolves to
    the workspace root."""
    fake_ws = tmp_path / "ws"
    (fake_ws / "config").mkdir(parents=True)
    (fake_ws / "config" / ".env").write_text("WORKSPACE_REPOSITORIES_DIR=repositories\n")
    deep_dir = fake_ws / "repositories" / "myrepo" / "src" / "nested"
    deep_dir.mkdir(parents=True)

    ctx = detect_context(_TOOLKIT_DIR, cwd=deep_dir)

    assert ctx.context == "workspace"
    assert ctx.run_dir == fake_ws.resolve()


def test_detect_context_toolkit_root_outside_any_workspace(tmp_path: Path) -> None:
    """A cwd nested under an unrelated dir tree (no workspace marker anywhere
    in its ancestry) must still fall back to toolkit-root, not misdetect."""
    stray_dir = tmp_path / "some" / "unrelated" / "nested" / "dir"
    stray_dir.mkdir(parents=True)

    ctx = detect_context(_TOOLKIT_DIR, cwd=stray_dir)

    assert ctx.context == "toolkit-root"
    assert ctx.run_dir == _TOOLKIT_DIR


def test_parse_dotenv_strips_export_prefix(tmp_path: Path) -> None:
    """`export VAR=value` must parse to key VAR, matching docker/installer/config.sh's
    documented supported .env dialect."""
    env_file = tmp_path / ".env"
    env_file.write_text("export AI_REPOSITORIES_DIR=repositories\nexport AWS_PROFILE=example-dev\n")

    cfg = _parse_dotenv(env_file)

    assert cfg == {"AI_REPOSITORIES_DIR": "repositories", "AWS_PROFILE": "example-dev"}


def test_parse_dotenv_strips_export_prefix_with_extra_whitespace(tmp_path: Path) -> None:
    """Extra whitespace between `export` and the var name must still parse."""
    env_file = tmp_path / ".env"
    env_file.write_text("export  AWS_PROFILE=example-dev\n")

    cfg = _parse_dotenv(env_file)

    assert cfg == {"AWS_PROFILE": "example-dev"}


def test_parse_dotenv_without_export_still_works(tmp_path: Path) -> None:
    """A plain `VAR=value` line (no export) must be unaffected by the fix."""
    env_file = tmp_path / ".env"
    env_file.write_text("AWS_PROFILE=example-dev\n")

    cfg = _parse_dotenv(env_file)

    assert cfg == {"AWS_PROFILE": "example-dev"}


def test_parse_dotenv_value_containing_export_word_not_misparsed(tmp_path: Path) -> None:
    """A value that merely contains the substring 'export' must not be mangled,
    and a key that isn't literally the `export` keyword must not be stripped."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        'NOTES=we export data nightly\nexported_flag=true\nexport QUOTED="value with spaces"\n'
    )

    cfg = _parse_dotenv(env_file)

    assert cfg == {
        "NOTES": "we export data nightly",
        "exported_flag": "true",
        "QUOTED": "value with spaces",
    }


def test_detect_context_valid_workspace_export_style_env(tmp_path: Path) -> None:
    """End-to-end regression: a workspace whose config/.env uses the `export VAR=value`
    style must still be detected as a workspace (not silently fall back to toolkit-root).

    Uses a non-default repos dir name so the assertion can't false-pass via
    cfg.get("WORKSPACE_REPOSITORIES_DIR", "repositories")'s default fallback —
    it only works if `export ` is actually stripped and the real key is read.
    """
    fake_ws = tmp_path / "ws"
    (fake_ws / "config").mkdir(parents=True)
    (fake_ws / "config" / ".env").write_text("export WORKSPACE_REPOSITORIES_DIR=custom_repos\n")
    (fake_ws / "custom_repos").mkdir()

    ctx = detect_context(_TOOLKIT_DIR, cwd=fake_ws)

    assert ctx.context == "workspace"
    assert ctx.run_dir == fake_ws.resolve()


def test_run_embedded_exposes_process_via_on_start(tmp_path: Path) -> None:
    """on_start receives the live Popen so a caller can cancel it."""
    captured: list[subprocess.Popen[str]] = []
    code = run_embedded(
        ["bash", "-c", "echo hi"],
        tmp_path,
        on_line=lambda _line: None,
        on_start=captured.append,
    )

    assert code == 0
    assert len(captured) == 1
    assert captured[0].pid > 0


def test_terminate_process_kills_running_process(tmp_path: Path) -> None:
    """A long-running process is stopped by terminate_process; it is reaped."""
    procs: list[subprocess.Popen[str]] = []
    lines: list[str] = []

    def _starter(proc: subprocess.Popen[str]) -> None:
        procs.append(proc)
        terminate_process(proc)  # cancel immediately

    code = run_embedded(
        ["bash", "-c", "echo start; sleep 60; echo never"],
        tmp_path,
        on_line=lines.append,
        on_start=_starter,
    )

    assert procs[0].poll() is not None  # reaped, not orphaned
    assert code != 0  # killed/terminated -> non-zero exit
    assert "never" not in lines  # was stopped before finishing


def test_terminate_process_noop_when_already_finished(tmp_path: Path) -> None:
    """terminate_process on a finished process returns without error."""
    holder: list[subprocess.Popen[str]] = []
    run_embedded(
        ["bash", "-c", "true"],
        tmp_path,
        on_line=lambda _line: None,
        on_start=holder.append,
    )

    terminate_process(holder[0])  # must not raise
