from __future__ import annotations

import json
from pathlib import Path

import pytest
from workspace_engine.cli import design as design_cli
from workspace_engine.design.config import DesignConfig
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
