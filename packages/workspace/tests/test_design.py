from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from workspace_engine.cli import design as design_cli
from workspace_engine.design.changes import _parse_unified_diff, changed_lines
from workspace_engine.design.config import DesignConfig, LayersConfig
from workspace_engine.design.layers import extract_imports, go_module_name, layer_violations
from workspace_engine.design.metrics import measure, supported
from workspace_engine.design.report import format_text, to_dict

# --- fixtures: violating + clean function per priority language -----------------

JAVA_VIOLATING = """
public class Big {
    public int deep(int a, int b, int c, int d, int e) {
        if (a > 0) {
            if (b > 0) {
                if (c > 0) {
                    if (d > 0) {
                        return a + b + c + d + e;
                    }
                }
            }
        }
        return 0;
    }
}
"""

JAVA_CLEAN = """
public class Small {
    public int add(int a, int b) {
        return a + b;
    }
}
"""

TS_VIOLATING = """
function tooManyArgs(a: number, b: number, c: number, d: number, e: number): number {
    return a + b + c + d + e;
}
"""

TS_CLEAN = """
function add(a: number, b: number): number {
    return a + b;
}
"""

JS_VIOLATING = """
function complex(x) {
    if (x === 1) { return 1; }
    else if (x === 2) { return 2; }
    else if (x === 3) { return 3; }
    else if (x === 4) { return 4; }
    else if (x === 5) { return 5; }
    else if (x === 6) { return 6; }
    else if (x === 7) { return 7; }
    else if (x === 8) { return 8; }
    else if (x === 9) { return 9; }
    else if (x === 10) { return 10; }
    return 0;
}
"""

JS_CLEAN = """
function add(a, b) {
    return a + b;
}
"""


def _py_nested_ifs(depth: int) -> str:
    lines = ["def deep(a):"]
    for level in range(depth):
        lines.append(" " * (4 * (level + 1)) + "if a:")
    lines.append(" " * (4 * (depth + 1)) + "return a")
    return "\n".join(lines) + "\n"


PY_VIOLATING = _py_nested_ifs(5)

PY_CLEAN = "def add(a, b):\n    return a + b\n"

PY_SELF_METHOD = "class C:\n    def method(self, a, b):\n        return a + b\n"

GO_VIOLATING = """
package main

func tooManyArgs(a int, b int, c int, d int, e int) int {
	return a + b + c + d + e
}
"""

GO_CLEAN = """
package main

func add(a int, b int) int {
	return a + b
}
"""

KOTLIN_SRC = "fun add(a: Int, b: Int): Int {\n    return a + b\n}\n"
CSHARP_SRC = "class C {\n    int Add(int a, int b) {\n        return a + b;\n    }\n}\n"
PHP_SRC = "<?php\nfunction add($a, $b) {\n    return $a + $b;\n}\n"
RUST_SRC = "fn add(a: i32, b: i32) -> i32 {\n    a + b\n}\n"


def _long_function(name: str, lines: int) -> str:
    body = "\n".join(f"    x = {i}" for i in range(lines))
    return f"def {name}():\n{body}\n    return x\n"


# --- config ----------------------------------------------------------------------


def test_config_defaults(tmp_path: Path) -> None:
    config = DesignConfig.load(tmp_path)
    assert config.mode == "block"
    assert config.max_complexity == 10
    assert config.max_function_lines == 40
    assert config.max_args == 4
    assert config.max_nesting == 3


def test_config_overrides(tmp_path: Path) -> None:
    (tmp_path / ".ai-governance").mkdir()
    (tmp_path / ".ai-governance" / "config.toml").write_text(
        '[design]\nmode = "warn"\nmax_complexity = 20\n'
    )
    config = DesignConfig.load(tmp_path)
    assert config.mode == "warn"
    assert config.max_complexity == 20
    assert config.max_function_lines == 40


def test_config_invalid_mode(tmp_path: Path) -> None:
    (tmp_path / ".ai-governance").mkdir()
    (tmp_path / ".ai-governance" / "config.toml").write_text('[design]\nmode = "bogus"\n')
    with pytest.raises(ValueError, match="mode"):
        DesignConfig.load(tmp_path)


def test_config_unknown_key(tmp_path: Path) -> None:
    (tmp_path / ".ai-governance").mkdir()
    (tmp_path / ".ai-governance" / "config.toml").write_text("[design]\nbogus = 1\n")
    with pytest.raises(ValueError, match="unknown"):
        DesignConfig.load(tmp_path)


# --- supported ---------------------------------------------------------------


def test_supported_known_and_unknown() -> None:
    assert supported("foo.py")
    assert supported("foo.java")
    assert supported("foo.ts")
    assert not supported("foo.dart")


# --- metrics: per-language, per-metric ---------------------------------------


def _measure_one(tmp_path: Path, filename: str, source: str, config: DesignConfig | None = None):
    path = tmp_path / filename
    path.write_text(source)
    return measure(tmp_path, [path], config or DesignConfig())


def test_java_complexity_and_nesting_violation(tmp_path: Path) -> None:
    violations = _measure_one(tmp_path, "Big.java", JAVA_VIOLATING)
    metrics = {v.metric for v in violations}
    assert "nesting" in metrics


def test_java_clean(tmp_path: Path) -> None:
    assert _measure_one(tmp_path, "Small.java", JAVA_CLEAN) == []


def test_typescript_args_violation(tmp_path: Path) -> None:
    violations = _measure_one(tmp_path, "big.ts", TS_VIOLATING)
    assert any(v.metric == "args" for v in violations)


def test_typescript_clean(tmp_path: Path) -> None:
    assert _measure_one(tmp_path, "small.ts", TS_CLEAN) == []


def test_javascript_complexity_violation(tmp_path: Path) -> None:
    violations = _measure_one(tmp_path, "big.js", JS_VIOLATING)
    assert any(v.metric == "complexity" for v in violations)


def test_javascript_clean(tmp_path: Path) -> None:
    assert _measure_one(tmp_path, "small.js", JS_CLEAN) == []


def test_python_nesting_violation(tmp_path: Path) -> None:
    violations = _measure_one(tmp_path, "deep.py", PY_VIOLATING)
    assert any(v.metric == "nesting" for v in violations)


def test_python_clean(tmp_path: Path) -> None:
    assert _measure_one(tmp_path, "small.py", PY_CLEAN) == []


def test_python_self_not_counted_as_arg(tmp_path: Path) -> None:
    config = DesignConfig(max_args=2)
    violations = _measure_one(tmp_path, "m.py", PY_SELF_METHOD, config)
    assert not any(v.metric == "args" for v in violations)


def test_python_length_violation(tmp_path: Path) -> None:
    config = DesignConfig(max_function_lines=5)
    violations = _measure_one(tmp_path, "long.py", _long_function("long_fn", 20), config)
    assert any(v.metric == "length" for v in violations)


def test_go_args_violation(tmp_path: Path) -> None:
    violations = _measure_one(tmp_path, "big.go", GO_VIOLATING)
    assert any(v.metric == "args" for v in violations)


def test_go_clean(tmp_path: Path) -> None:
    assert _measure_one(tmp_path, "small.go", GO_CLEAN) == []


@pytest.mark.parametrize(
    "filename,source",
    [
        ("a.kt", KOTLIN_SRC),
        ("a.cs", CSHARP_SRC),
        ("a.php", PHP_SRC),
        ("a.rs", RUST_SRC),
    ],
)
def test_smoke_other_languages(tmp_path: Path, filename: str, source: str) -> None:
    violations = _measure_one(tmp_path, filename, source)
    assert violations == []


# --- exclude / missing / unsupported -----------------------------------------


def test_exclude_globs(tmp_path: Path) -> None:
    vendor = tmp_path / "node_modules"
    vendor.mkdir()
    (vendor / "big.js").write_text(JS_VIOLATING)
    violations = measure(tmp_path, [vendor / "big.js"], DesignConfig())
    assert violations == []


def test_missing_file_skipped(tmp_path: Path) -> None:
    assert measure(tmp_path, [tmp_path / "missing.py"], DesignConfig()) == []


def test_unsupported_file_skipped(tmp_path: Path) -> None:
    path = tmp_path / "readme.dart"
    path.write_text("void main() {}\n")
    assert measure(tmp_path, [path], DesignConfig()) == []


# --- report --------------------------------------------------------------------


def test_report_text_pass() -> None:
    text = format_text([], DesignConfig(), files=3)
    assert "PASS (3 files)" in text


def test_report_text_violations_block_mode(tmp_path: Path) -> None:
    violations = _measure_one(tmp_path, "deep.py", PY_VIOLATING)
    text = format_text(violations, DesignConfig(), files=1)
    assert "✘ design:" in text
    assert "deep.py" in text


def test_report_text_warn_prefix(tmp_path: Path) -> None:
    violations = _measure_one(tmp_path, "deep.py", PY_VIOLATING)
    text = format_text(violations, DesignConfig(mode="warn"), files=1)
    assert text.splitlines()[-1].startswith("⚠")


def test_report_to_dict_shape(tmp_path: Path) -> None:
    violations = _measure_one(tmp_path, "deep.py", PY_VIOLATING)
    payload = to_dict(violations, DesignConfig(), files=1)
    assert payload["schema_version"] == 1
    assert payload["status"] == "fail"
    assert payload["files"] == 1
    assert isinstance(payload["violations"], list)
    assert payload["violations"][0]["metric"]


# --- CLI -------------------------------------------------------------------------


def test_cli_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "deep.py").write_text(PY_VIOLATING)
    code = design_cli.design(["--dir", str(tmp_path), str(tmp_path / "deep.py"), "--json"])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["status"] == "fail"
    assert code == 1


def test_cli_warn_mode_exit_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / ".ai-governance").mkdir()
    (tmp_path / ".ai-governance" / "config.toml").write_text('[design]\nmode = "warn"\n')
    (tmp_path / "deep.py").write_text(PY_VIOLATING)
    code = design_cli.design(["--dir", str(tmp_path), str(tmp_path / "deep.py")])
    out = capsys.readouterr().out
    assert code == 0
    assert "⚠" in out


def test_cli_off_mode(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / ".ai-governance").mkdir()
    (tmp_path / ".ai-governance" / "config.toml").write_text('[design]\nmode = "off"\n')
    code = design_cli.design(["--dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0
    assert out.strip() == "design: off"


def test_cli_files_from(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "deep.py").write_text(PY_VIOLATING)
    list_file = tmp_path / "files.txt"
    list_file.write_text("deep.py\n")
    code = design_cli.design(["--dir", str(tmp_path), "--files-from", str(list_file)])
    assert code == 1
    out = capsys.readouterr().out
    assert "deep.py" in out


def test_cli_pass_no_violations(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "small.py").write_text(PY_CLEAN)
    code = design_cli.design(["--dir", str(tmp_path), str(tmp_path / "small.py")])
    out = capsys.readouterr().out
    assert code == 0
    assert "PASS" in out


# --- nesting: own engine, not lizard's max_nested_structures --------------------


def test_python_elif_same_level_as_if(tmp_path: Path) -> None:
    source = (
        "def route(a):\n"
        "    if a == 1:\n"
        "        return 1\n"
        "    elif a == 2:\n"
        "        return 2\n"
        "    elif a == 3:\n"
        "        return 3\n"
        "    else:\n"
        "        return 0\n"
    )
    config = DesignConfig(max_nesting=1)
    violations = _measure_one(tmp_path, "route.py", source, config)
    assert not any(v.metric == "nesting" for v in violations)


def test_python_nested_def_measured_separately(tmp_path: Path) -> None:
    source = (
        "def outer(a):\n"
        "    if a:\n"
        "        if a > 1:\n"
        "            if a > 2:\n"
        "                pass\n"
        "\n"
        "    def inner(b):\n"
        "        return b\n"
        "\n"
        "    return inner\n"
    )
    config = DesignConfig(max_nesting=5)
    violations = _measure_one(tmp_path, "outer.py", source, config)
    # deep 'if' chain lives in outer(); inner() is trivial and must not inherit outer's depth
    assert not any(v.metric == "nesting" for v in violations)


def test_java_else_if_chain_no_extra_level(tmp_path: Path) -> None:
    source = """
public class Router {
    public int route(int a) {
        if (a == 1) {
            return 1;
        } else if (a == 2) {
            return 2;
        } else if (a == 3) {
            return 3;
        } else {
            return 0;
        }
    }
}
"""
    config = DesignConfig(max_nesting=1)
    violations = _measure_one(tmp_path, "Router.java", source, config)
    assert not any(v.metric == "nesting" for v in violations)


def test_java_string_with_braces_not_counted(tmp_path: Path) -> None:
    source = """
public class S {
    public String describe() {
        String s = "{ if (x) { } }";
        return s;
    }
}
"""
    config = DesignConfig(max_nesting=0)
    violations = _measure_one(tmp_path, "S.java", source, config)
    assert not any(v.metric == "nesting" for v in violations)


def test_typescript_object_literal_and_lambda_not_counted(tmp_path: Path) -> None:
    source = """
function build(items: number[]): object {
    const config = { retries: 3, nested: { a: 1, b: 2 } };
    const doubled = items.map((x) => { return x * 2; });
    return { config, doubled };
}
"""
    config = DesignConfig(max_nesting=0)
    violations = _measure_one(tmp_path, "build.ts", source, config)
    assert not any(v.metric == "nesting" for v in violations)


def test_typescript_real_nesting_detected(tmp_path: Path) -> None:
    source = """
function deep(a: number, b: number): number {
    if (a > 0) {
        for (let i = 0; i < b; i++) {
            if (i % 2 === 0) {
                while (a > 0) {
                    a -= 1;
                }
            }
        }
    }
    return a;
}
"""
    violations = _measure_one(tmp_path, "deep.ts", source, DesignConfig(max_nesting=3))
    assert any(v.metric == "nesting" and v.value == 4 for v in violations)


def test_brace_nesting_line_comment_control_keyword_ignored(tmp_path: Path) -> None:
    source = """
public class C {
    public int f(int a) {
        // if (a) { if (a) { if (a) { } } }
        return a;
    }
}
"""
    config = DesignConfig(max_nesting=0)
    violations = _measure_one(tmp_path, "C.java", source, config)
    assert not any(v.metric == "nesting" for v in violations)


def test_brace_nesting_block_comment_control_keyword_ignored(tmp_path: Path) -> None:
    source = """
public class C {
    public int f(int a) {
        /* if (a) { if (a) { } } */
        if (a > 0) {
            return a;
        }
        return 0;
    }
}
"""
    config = DesignConfig(max_nesting=0)
    violations = _measure_one(tmp_path, "C.java", source, config)
    assert any(v.metric == "nesting" and v.value == 1 for v in violations)


def test_python_for_while_with_try_nesting(tmp_path: Path) -> None:
    source = (
        "def f(a):\n"
        "    for i in range(a):\n"
        "        while i > 0:\n"
        "            with open('x') as fh:\n"
        "                try:\n"
        "                    fh.read()\n"
        "                except OSError:\n"
        "                    pass\n"
        "                finally:\n"
        "                    pass\n"
        "            i -= 1\n"
    )
    config = DesignConfig(max_nesting=3)
    violations = _measure_one(tmp_path, "f.py", source, config)
    assert any(v.metric == "nesting" and v.value == 4 for v in violations)


def test_python_match_statement_nesting(tmp_path: Path) -> None:
    source = (
        "def f(a):\n"
        "    if a:\n"
        "        match a:\n"
        "            case 1:\n"
        "                return 1\n"
        "            case _:\n"
        "                return 0\n"
        "    return -1\n"
    )
    config = DesignConfig(max_nesting=1)
    violations = _measure_one(tmp_path, "f.py", source, config)
    assert any(v.metric == "nesting" and v.value == 2 for v in violations)


def test_python_nested_class_body_walked_at_same_depth(tmp_path: Path) -> None:
    # A class defined inside a function is not its own measured scope (only
    # FunctionDef/AsyncFunctionDef/Lambda are), so its body is walked as part
    # of the enclosing function's nesting.
    source = "def outer(a):\n    class Inner:\n        if a:\n            x = 1\n    return Inner\n"
    config = DesignConfig(max_nesting=0)
    violations = _measure_one(tmp_path, "outer.py", source, config)
    assert any(v.metric == "nesting" for v in violations)


def test_ruby_nesting_not_computed(tmp_path: Path) -> None:
    # Ruby is analyzable by lizard but has no nesting engine: deep nesting must
    # never surface as a "nesting" violation, however low the limit is.
    source = "def f(a)\n  if a\n    if a\n      if a\n        1\n      end\n    end\n  end\nend\n"
    config = DesignConfig(max_nesting=0)
    violations = _measure_one(tmp_path, "f.rb", source, config)
    assert not any(v.metric == "nesting" for v in violations)


def test_measure_skips_undecodable_file(tmp_path: Path) -> None:
    path = tmp_path / "bad.py"
    path.write_bytes(b"\xff\xfe\x00def f():\n    pass\n")
    assert measure(tmp_path, [path], DesignConfig()) == []


def test_measure_skips_python_syntax_error(tmp_path: Path) -> None:
    path = tmp_path / "broken.py"
    path.write_text("def f(:\n    pass\n")
    assert measure(tmp_path, [path], DesignConfig()) == []


def test_config_no_design_table_returns_defaults(tmp_path: Path) -> None:
    (tmp_path / ".ai-governance").mkdir()
    (tmp_path / ".ai-governance" / "config.toml").write_text("[other]\nkey = 1\n")
    config = DesignConfig.load(tmp_path)
    assert config == DesignConfig()


def test_config_design_not_a_table(tmp_path: Path) -> None:
    (tmp_path / ".ai-governance").mkdir()
    (tmp_path / ".ai-governance" / "config.toml").write_text('design = "nope"\n')
    with pytest.raises(ValueError, match="must be a table"):
        DesignConfig.load(tmp_path)


# --- CLI: file collection -------------------------------------------------------


def test_cli_collects_directory_via_walk(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "deep.py").write_text(PY_VIOLATING)
    (sub / ".hidden").mkdir()
    (sub / ".hidden" / "skip.py").write_text(PY_VIOLATING)
    excluded = sub / "node_modules"
    excluded.mkdir()
    (excluded / "big.js").write_text(JS_VIOLATING)
    code = design_cli.design(["--dir", str(tmp_path), str(sub)])
    out = capsys.readouterr().out
    assert code == 1
    assert "deep.py" in out
    assert "skip.py" not in out
    assert "big.js" not in out


def test_cli_walk_excludes_file_by_glob_pattern(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "deep.py").write_text(PY_VIOLATING)
    (sub / "bundle.min.js").write_text(JS_VIOLATING)
    code = design_cli.design(["--dir", str(tmp_path), str(sub)])
    out = capsys.readouterr().out
    assert code == 1
    assert "deep.py" in out
    assert "bundle.min.js" not in out


def test_cli_repo_files_via_git_ls_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "deep.py").write_text(PY_VIOLATING)
    subprocess.run(["git", "add", "deep.py"], cwd=tmp_path, check=True)
    code = design_cli.design(["--dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 1
    assert "deep.py" in out


def test_cli_repo_files_fallback_walk_when_not_a_git_repo(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "deep.py").write_text(PY_VIOLATING)
    code = design_cli.design(["--dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 1
    assert "deep.py" in out


def test_cli_changed_flag_uses_changed_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "deep.py").write_text(PY_VIOLATING)
    monkeypatch.setattr(design_cli, "changed_files", lambda root: ["deep.py"])
    code = design_cli.design(["--dir", str(tmp_path), "--changed"])
    out = capsys.readouterr().out
    assert code == 1
    assert "deep.py" in out


def test_go_nesting_real_and_chained_else(tmp_path: Path) -> None:
    source = """
package main

func classify(a int) int {
	if a > 0 {
		if a > 10 {
			return 2
		} else if a > 5 {
			return 1
		}
	}
	return 0
}
"""
    violations = _measure_one(tmp_path, "classify.go", source, DesignConfig(max_nesting=1))
    assert any(v.metric == "nesting" and v.value == 2 for v in violations)


# --- new vs. legacy classification -----------------------------------------------


def _git(root: Path, *args: str) -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        GIT_CONFIG_GLOBAL="/dev/null",
        GIT_AUTHOR_NAME="t",
        GIT_AUTHOR_EMAIL="t@e.x",
        GIT_COMMITTER_NAME="t",
        GIT_COMMITTER_EMAIL="t@e.x",
    )
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, env=env)


def _complex_function(name: str, branches: int = 12) -> str:
    """A Python function whose cyclomatic complexity exceeds the default limit (10)."""
    lines = [f"def {name}(x):"]
    for i in range(branches):
        keyword = "if" if i == 0 else "elif"
        lines.append(f"    {keyword} x == {i}:")
        lines.append(f"        return {i}")
    lines.append("    return -1")
    return "\n".join(lines) + "\n"


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    (root / "module.py").write_text(_complex_function("legacy_complex"))
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "init")
    _git(root, "checkout", "-q", "-b", "feature")
    return root


def _complexity_origins(payload: dict) -> dict[str, str]:
    return {
        v["symbol"].split("(")[0].strip(): v["origin"]
        for v in payload["violations"]
        if v["metric"] == "complexity"
    }


def test_changed_lines_untracked_is_none(git_repo: Path) -> None:
    (git_repo / "new_file.py").write_text("x = 1\n")
    result = changed_lines(git_repo)
    assert result.get("new_file.py") is None


def test_parse_unified_diff_skips_deleted_file() -> None:
    diff = (
        "diff --git a/removed.py b/removed.py\n"
        "deleted file mode 100644\n"
        "--- a/removed.py\n"
        "+++ /dev/null\n"
        "@@ -1,2 +0,0 @@\n"
        "-x = 1\n"
        "-y = 2\n"
    )
    result = _parse_unified_diff(diff)
    assert "removed.py" not in result


def test_parse_unified_diff_ignores_malformed_hunk_header() -> None:
    diff = "+++ b/f.py\n@@ not a real hunk header @@\n+x = 1\n"
    result = _parse_unified_diff(diff)
    assert result == {"f.py": set()}


def test_changed_lines_modified_line_set(git_repo: Path) -> None:
    (git_repo / "module.py").write_text((git_repo / "module.py").read_text() + "\nextra = 1\n")
    result = changed_lines(git_repo)
    assert "module.py" in result
    assert isinstance(result["module.py"], set)
    assert result["module.py"]


def test_full_repo_scan_marks_everything_legacy(tmp_path: Path) -> None:
    (tmp_path / "deep.py").write_text(PY_VIOLATING)
    violations = measure(tmp_path, [tmp_path / "deep.py"], DesignConfig())
    assert violations and all(v.origin == "legacy" for v in violations)


def test_new_function_is_new_untouched_legacy_stays_legacy(
    git_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    content = (git_repo / "module.py").read_text()
    (git_repo / "module.py").write_text(content + "\n" + _complex_function("new_complex"))
    design_cli.design(["--dir", str(git_repo), "--changed", "--json"])
    payload = json.loads(capsys.readouterr().out)
    origins = _complexity_origins(payload)
    assert origins["legacy_complex"] == "legacy"
    assert origins["new_complex"] == "new"


def test_editing_a_line_in_legacy_function_marks_it_new(
    git_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = (git_repo / "module.py").read_text().splitlines()
    idx = next(i for i, line in enumerate(lines) if "if x == 0" in line)
    lines[idx] = lines[idx] + "  # touched"
    (git_repo / "module.py").write_text("\n".join(lines) + "\n")
    design_cli.design(["--dir", str(git_repo), "--changed", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert _complexity_origins(payload)["legacy_complex"] == "new"


def test_untracked_file_is_new(git_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (git_repo / "extra.py").write_text(_complex_function("untracked_complex"))
    design_cli.design(["--dir", str(git_repo), "--changed", "--json"])
    payload = json.loads(capsys.readouterr().out)
    origins = _complexity_origins(payload)
    assert origins["untracked_complex"] == "new"
    assert "legacy_complex" not in origins  # module.py untouched: not in --changed scope


def test_files_from_mode_uses_same_diff_classification(
    git_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    content = (git_repo / "module.py").read_text()
    (git_repo / "module.py").write_text(content + "\n" + _complex_function("new_complex"))
    list_file = git_repo / "files.txt"
    list_file.write_text("module.py\n")
    design_cli.design(["--dir", str(git_repo), "--files-from", str(list_file), "--json"])
    payload = json.loads(capsys.readouterr().out)
    origins = _complexity_origins(payload)
    assert origins["legacy_complex"] == "legacy"
    assert origins["new_complex"] == "new"


def test_report_format_text_sections_order_and_footer() -> None:
    from workspace_engine.design.metrics import Violation

    violations = [
        Violation("a.py", "new_fn(...)", 1, 5, "complexity", 15, 10, origin="new"),
        Violation("b.py", "old_fn(...)", 1, 5, "length", 50, 40, origin="legacy"),
    ]
    text = format_text(violations, DesignConfig(), files=2)
    assert "New code" in text
    assert "Pre-existing code" in text
    assert "Fix one at a time: ws design --focus" in text
    assert text.index("New code") < text.index("Pre-existing code")
    assert "→ extract branches into named functions / guard clauses" in text
    assert "→ extract steps into well-named functions" in text


# --- ws design --focus -----------------------------------------------------------


def test_cli_focus_reports_violation_and_exit_code(
    git_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = design_cli.design(["--dir", str(git_repo), "--focus", "module.py:1"])
    out = capsys.readouterr().out
    assert code == 1
    assert "legacy_complex" in out
    assert "complexity" in out
    assert "FAIL" in out
    assert "Hints:" in out
    assert "extract branches" in out
    assert "module.py:1-" in out


def test_cli_focus_pass_within_limits(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "small.py").write_text(PY_CLEAN)
    code = design_cli.design(["--dir", str(tmp_path), "--focus", "small.py:1"])
    out = capsys.readouterr().out
    assert code == 0
    assert "Within limits." in out


def test_cli_focus_no_function_found(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "small.py").write_text(PY_CLEAN)
    code = design_cli.design(["--dir", str(tmp_path), "--focus", "small.py:999"])
    out = capsys.readouterr().out
    assert code == 1
    assert "no function found" in out


def test_cli_focus_bad_spec(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = design_cli.design(["--dir", str(tmp_path), "--focus", "nocolon"])
    out = capsys.readouterr().out
    assert code == 1
    assert "path:line" in out


def test_cli_focus_non_integer_line(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "small.py").write_text(PY_CLEAN)
    code = design_cli.design(["--dir", str(tmp_path), "--focus", "small.py:notaline"])
    out = capsys.readouterr().out
    assert code == 1
    assert "path:line" in out


def test_cli_focus_absolute_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "small.py"
    target.write_text(PY_CLEAN)
    code = design_cli.design(["--dir", str(tmp_path), "--focus", f"{target}:1"])
    out = capsys.readouterr().out
    assert code == 0
    assert "Within limits." in out


def test_cli_focus_missing_file_no_function(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = design_cli.design(["--dir", str(tmp_path), "--focus", "missing.py:1"])
    out = capsys.readouterr().out
    assert code == 1
    assert "no function found" in out


def test_cli_focus_ruby_function_has_no_nesting_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "small.rb").write_text("def f(a)\n  a + 1\nend\n")
    code = design_cli.design(["--dir", str(tmp_path), "--focus", "small.rb:1"])
    out = capsys.readouterr().out
    assert code == 0
    assert "nesting" not in out


def test_cli_focus_truncates_long_function_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _long_function("very_long", 200)
    (tmp_path / "long.py").write_text(source)
    code = design_cli.design(["--dir", str(tmp_path), "--focus", "long.py:1"])
    out = capsys.readouterr().out
    assert code == 1
    assert "more line(s) omitted" in out


# --- layers: architecture profile boundary check ---------------------------------

_LAYERS = LayersConfig(order=("adapters", "application", "domain"), paths={})


def _write_config(root: Path, extra: str = "") -> None:
    (root / ".ai-governance").mkdir(exist_ok=True)
    (root / ".ai-governance" / "config.toml").write_text(
        'profiles = ["architecture"]\n[design.layers]\norder = ["adapters", "application", "domain"]\n'
        + extra
    )


def test_java_domain_importing_adapters_is_violation(tmp_path: Path) -> None:
    domain = tmp_path / "com/acme/domain"
    domain.mkdir(parents=True)
    (domain / "Order.java").write_text(
        "package com.acme.domain;\nimport com.acme.adapters.Db;\npublic class Order {}\n"
    )
    violations = layer_violations(tmp_path, [domain / "Order.java"], _LAYERS)
    assert len(violations) == 1
    assert violations[0].metric == "layers"
    assert "domain → adapters" in violations[0].symbol


def test_java_adapters_importing_domain_is_ok(tmp_path: Path) -> None:
    adapters = tmp_path / "com/acme/adapters"
    adapters.mkdir(parents=True)
    (adapters / "Db.java").write_text(
        "package com.acme.adapters;\nimport com.acme.domain.Order;\npublic class Db {}\n"
    )
    assert layer_violations(tmp_path, [adapters / "Db.java"], _LAYERS) == []


def test_java_commented_import_ignored(tmp_path: Path) -> None:
    domain = tmp_path / "com/acme/domain"
    domain.mkdir(parents=True)
    (domain / "Order.java").write_text(
        "package com.acme.domain;\n// import com.acme.adapters.Db;\npublic class Order {}\n"
    )
    assert layer_violations(tmp_path, [domain / "Order.java"], _LAYERS) == []


def test_python_relative_import_violation(tmp_path: Path) -> None:
    domain = tmp_path / "app/domain"
    adapters = tmp_path / "app/adapters"
    domain.mkdir(parents=True)
    adapters.mkdir(parents=True)
    (domain / "order.py").write_text("from ..adapters import db\n")
    violations = layer_violations(tmp_path, [domain / "order.py"], _LAYERS)
    assert len(violations) == 1
    assert violations[0].metric == "layers"


def test_ts_relative_violation_bare_ignored(tmp_path: Path) -> None:
    domain = tmp_path / "src/domain"
    adapters = tmp_path / "src/adapters"
    domain.mkdir(parents=True)
    adapters.mkdir(parents=True)
    (domain / "order.ts").write_text(
        "import { Db } from '../adapters/db';\nimport React from 'react';\n"
    )
    violations = layer_violations(tmp_path, [domain / "order.ts"], _LAYERS)
    assert len(violations) == 1
    assert "db" in violations[0].symbol


def test_go_module_stripped_from_import_path(tmp_path: Path) -> None:
    (tmp_path / "go.mod").write_text("module example.com/app\n")
    domain = tmp_path / "domain"
    domain.mkdir()
    (domain / "order.go").write_text(
        'package domain\n\nimport (\n\t"example.com/app/adapters"\n\t"fmt"\n)\n'
    )
    module = go_module_name(tmp_path)
    assert module == "example.com/app"
    violations = layer_violations(tmp_path, [domain / "order.go"], _LAYERS)
    assert len(violations) == 1


def test_custom_layer_paths(tmp_path: Path) -> None:
    config = LayersConfig(
        order=("adapters", "domain"),
        paths={"adapters": ("**/infra/**",)},
    )
    infra = tmp_path / "infra"
    infra.mkdir()
    (infra / "Order.java").write_text(
        "package infra;\nimport core.domain.Order;\npublic class Order {}\n"
    )
    assert layer_violations(tmp_path, [infra / "Order.java"], config) == []
    core = tmp_path / "core/domain"
    core.mkdir(parents=True)
    (core / "Order.java").write_text(
        "package core.domain;\nimport infra.Db;\npublic class Order {}\n"
    )
    assert len(layer_violations(tmp_path, [core / "Order.java"], config)) == 1


def test_extract_imports_unknown_extension_returns_empty() -> None:
    assert extract_imports("f.txt", "txt", "irrelevant", None) == []


def test_kotlin_import_violation(tmp_path: Path) -> None:
    domain = tmp_path / "app/domain"
    domain.mkdir(parents=True)
    (domain / "Order.kt").write_text("package app.domain\nimport app.adapters.Db\nclass Order\n")
    violations = layer_violations(tmp_path, [domain / "Order.kt"], _LAYERS)
    assert len(violations) == 1
    assert "domain → adapters" in violations[0].symbol


def test_csharp_using_violation(tmp_path: Path) -> None:
    domain = tmp_path / "app/domain"
    domain.mkdir(parents=True)
    (domain / "Order.cs").write_text(
        "using app.adapters;\nnamespace app.domain { class Order {} }\n"
    )
    violations = layer_violations(tmp_path, [domain / "Order.cs"], _LAYERS)
    assert len(violations) == 1
    assert "domain → adapters" in violations[0].symbol


def test_csharp_using_static_ignored(tmp_path: Path) -> None:
    domain = tmp_path / "app/domain"
    domain.mkdir(parents=True)
    (domain / "Order.cs").write_text(
        "using static app.adapters.Db;\nnamespace app.domain { class Order {} }\n"
    )
    assert layer_violations(tmp_path, [domain / "Order.cs"], _LAYERS) == []


def test_php_use_violation(tmp_path: Path) -> None:
    domain = tmp_path / "app/domain"
    domain.mkdir(parents=True)
    (domain / "Order.php").write_text(
        "<?php\nnamespace app\\domain;\nuse app\\adapters\\Db;\nclass Order {}\n"
    )
    violations = layer_violations(tmp_path, [domain / "Order.php"], _LAYERS)
    assert len(violations) == 1
    assert "domain → adapters" in violations[0].symbol


def test_rust_use_violation(tmp_path: Path) -> None:
    domain = tmp_path / "app/domain"
    domain.mkdir(parents=True)
    (domain / "order.rs").write_text("use crate::app::adapters::Db;\nfn f() {}\n")
    violations = layer_violations(tmp_path, [domain / "order.rs"], _LAYERS)
    assert len(violations) == 1
    assert "domain → adapters" in violations[0].symbol


def test_dart_package_import_violation(tmp_path: Path) -> None:
    domain = tmp_path / "app/domain"
    domain.mkdir(parents=True)
    (domain / "order.dart").write_text("import 'package:app/adapters/db.dart';\nclass Order {}\n")
    violations = layer_violations(tmp_path, [domain / "order.dart"], _LAYERS)
    assert len(violations) == 1
    assert "domain → adapters" in violations[0].symbol


def test_dart_relative_import_violation(tmp_path: Path) -> None:
    domain = tmp_path / "app/domain"
    adapters = tmp_path / "app/adapters"
    domain.mkdir(parents=True)
    adapters.mkdir(parents=True)
    (domain / "order.dart").write_text("import '../adapters/db.dart';\nclass Order {}\n")
    violations = layer_violations(tmp_path, [domain / "order.dart"], _LAYERS)
    assert len(violations) == 1


def test_js_dynamic_import_and_require_violations(tmp_path: Path) -> None:
    domain = tmp_path / "app/domain"
    adapters = tmp_path / "app/adapters"
    domain.mkdir(parents=True)
    adapters.mkdir(parents=True)
    (domain / "order.mjs").write_text(
        "const db = require('../adapters/db');\n"
        "async function load() { await import('../adapters/other'); }\n"
    )
    violations = layer_violations(tmp_path, [domain / "order.mjs"], _LAYERS)
    assert len(violations) == 2


def test_python_plain_dotted_import_violation(tmp_path: Path) -> None:
    domain = tmp_path / "app/domain"
    domain.mkdir(parents=True)
    (domain / "order.py").write_text("x = 1\nimport app.adapters.db\ny = 2\n")
    violations = layer_violations(tmp_path, [domain / "order.py"], _LAYERS)
    assert len(violations) == 1


def test_python_absolute_from_import_violation(tmp_path: Path) -> None:
    domain = tmp_path / "app/domain"
    domain.mkdir(parents=True)
    (domain / "order.py").write_text("from app.adapters import db\n")
    violations = layer_violations(tmp_path, [domain / "order.py"], _LAYERS)
    assert len(violations) == 1


def test_python_bare_relative_from_import_no_dotted(tmp_path: Path) -> None:
    domain = tmp_path / "app/domain"
    domain.mkdir(parents=True)
    (domain / "order.py").write_text("from . import sibling\n")
    assert layer_violations(tmp_path, [domain / "order.py"], _LAYERS) == []


def test_go_import_block_with_blank_line_and_self_import(tmp_path: Path) -> None:
    (tmp_path / "go.mod").write_text("module example.com/app\n")
    domain = tmp_path / "domain"
    domain.mkdir()
    (domain / "order.go").write_text(
        'package domain\n\nimport (\n\t"example.com/app"\n\n\t"fmt"\n)\n'
    )
    violations = layer_violations(tmp_path, [domain / "order.go"], _LAYERS)
    # "example.com/app" resolves to the repo root, which is not a configured layer.
    assert violations == []


def test_go_module_name_skips_leading_comment_line(tmp_path: Path) -> None:
    (tmp_path / "go.mod").write_text("// generated\nmodule example.com/app\n")
    assert go_module_name(tmp_path) == "example.com/app"


def test_go_module_name_missing_module_line_returns_none(tmp_path: Path) -> None:
    (tmp_path / "go.mod").write_text("go 1.21\n")
    assert go_module_name(tmp_path) is None


def test_file_outside_any_layer_is_ignored(tmp_path: Path) -> None:
    other = tmp_path / "scripts"
    other.mkdir()
    (other / "tool.py").write_text("import app.adapters.db\n")
    assert layer_violations(tmp_path, [other / "tool.py"], _LAYERS) == []


def test_layer_violations_skips_unrecognized_extension(tmp_path: Path) -> None:
    domain = tmp_path / "app/domain"
    domain.mkdir(parents=True)
    (domain / "notes.txt").write_text("import app.adapters.db\n")
    assert layer_violations(tmp_path, [domain / "notes.txt"], _LAYERS) == []


def test_layer_violations_skips_undecodable_file(tmp_path: Path) -> None:
    domain = tmp_path / "app/domain"
    domain.mkdir(parents=True)
    path = domain / "order.py"
    path.write_bytes(b"\xff\xfeimport app.adapters.db\n")
    assert layer_violations(tmp_path, [path], _LAYERS) == []


def test_unresolvable_relative_import_is_not_a_violation(tmp_path: Path) -> None:
    domain = tmp_path / "app/domain"
    domain.mkdir(parents=True)
    (domain / "order.ts").write_text("import something from 'plain-package';\n")
    assert layer_violations(tmp_path, [domain / "order.ts"], _LAYERS) == []


def test_layers_violation_origin_new_when_import_line_changed(tmp_path: Path) -> None:
    from workspace_engine.design.layers import violations_for_file

    domain = tmp_path / "app/domain"
    domain.mkdir(parents=True)
    path = domain / "order.py"
    path.write_text("x = 1\nimport app.adapters.db\n")
    violations = violations_for_file(
        tmp_path, path, _LAYERS, None, changed={"app/domain/order.py": {2}}
    )
    assert len(violations) == 1
    assert violations[0].origin == "new"


def test_layers_violation_origin_legacy_when_untouched(tmp_path: Path) -> None:
    from workspace_engine.design.layers import violations_for_file

    domain = tmp_path / "app/domain"
    domain.mkdir(parents=True)
    path = domain / "order.py"
    path.write_text("x = 1\nimport app.adapters.db\n")
    violations = violations_for_file(
        tmp_path, path, _LAYERS, None, changed={"app/domain/order.py": {1}}
    )
    assert len(violations) == 1
    assert violations[0].origin == "legacy"


def test_config_layers_none_by_default(tmp_path: Path) -> None:
    config = DesignConfig.load(tmp_path)
    assert config.layers is None
    assert config.profiles == ()


def test_config_layers_parsed(tmp_path: Path) -> None:
    _write_config(tmp_path, '[design.layers.paths]\nadapters = ["**/infra/**"]\n')
    config = DesignConfig.load(tmp_path)
    assert config.profiles == ("architecture",)
    assert config.layers is not None
    assert config.layers.order == ("adapters", "application", "domain")


def test_cli_profile_off_no_layer_check(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    domain = tmp_path / "com/acme/domain"
    domain.mkdir(parents=True)
    (domain / "Order.java").write_text(
        "package com.acme.domain;\nimport com.acme.adapters.Db;\npublic class Order {}\n"
    )
    code = design_cli.design(["--dir", str(tmp_path), str(domain / "Order.java")])
    out = capsys.readouterr().out
    assert code == 0
    assert "layers" not in out


def test_cli_profile_on_no_layers_configured_note(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".ai-governance").mkdir()
    (tmp_path / ".ai-governance" / "config.toml").write_text('profiles = ["architecture"]\n')
    (tmp_path / "small.py").write_text(PY_CLEAN)
    code = design_cli.design(["--dir", str(tmp_path), str(tmp_path / "small.py")])
    out = capsys.readouterr().out
    assert code == 0
    assert "layers: not configured ([design.layers])" in out


def test_cli_profile_on_layers_violation_blocks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    domain = tmp_path / "com/acme/domain"
    domain.mkdir(parents=True)
    (domain / "Order.java").write_text(
        "package com.acme.domain;\nimport com.acme.adapters.Db;\npublic class Order {}\n"
    )
    _write_config(tmp_path)
    code = design_cli.design(["--dir", str(tmp_path), str(domain / "Order.java")])
    out = capsys.readouterr().out
    assert code == 1
    assert "layers" in out
    assert "domain → adapters" in out
