"""Tests for the junk-test checks of ``ws design`` (``test-*`` metrics)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from workspace_engine.cli import design as design_cli
from workspace_engine.design.config import CHECKS, DesignConfig
from workspace_engine.design.report import HINTS
from workspace_engine.design.testquality import TEST_CHECKS, is_test_file, junk_test_violations

FILES = {"java": "ATest.java", "ts": "a.test.ts", "py": "test_a.py", "go": "a_test.go"}
WRAPPERS = {
    "java": "class ATest {{\n  @Test\n  void t() {{\n    {}\n  }}\n}}\n",
    "ts": "it('t', async () => {{\n  {}\n}});\n",
    "py": "def test_t(self, x, a):\n    {}\n",
    "go": "package a\n\nfunc TestT(t *testing.T) {{\n\t{}\n}}\n",
}


def run(
    tmp_path: Path, name: str, source: str, checks: tuple[str, ...] = TEST_CHECKS
) -> list[tuple[str, str, int]]:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    return [
        (v.metric, v.symbol, v.start_line) for v in junk_test_violations(tmp_path, [path], checks)
    ]


def flagged(tmp_path: Path, lang: str, statements: str, metric: str) -> bool:
    """Whether ``metric`` fires for a test of language ``lang`` holding ``statements``."""
    found = run(tmp_path, FILES[lang], WRAPPERS[lang].format(statements), (metric,))
    return [m for m, _, _ in found] == [metric]


# --- test-file detection ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("relative", "source", "expected"),
    [
        ("src/test/java/a/Helper.java", "", True),
        ("src/main/java/a/FooTest.java", "", True),
        ("src/main/java/a/FooIT.java", "", True),
        ("src/main/java/a/Foo.java", "", False),
        ("app/src/test/kotlin/FooTest.kt", "", True),
        ("web/foo.test.ts", "", True),
        ("web/foo.spec.jsx", "", True),
        ("web/__tests__/util.js", "", True),
        ("web/foo.ts", "", False),
        ("pkg/test_foo.py", "", True),
        ("pkg/foo_test.py", "", True),
        ("pkg/tests/helpers/util.py", "", True),
        ("pkg/foo.py", "", False),
        ("pkg/foo_test.go", "", True),
        ("pkg/foo.go", "", False),
        ("Calc/CalcTests.cs", "", True),
        ("Calc/Calc.cs", "", False),
        ("tests/FooTest.php", "", True),
        ("lib/foo_test.dart", "", True),
        ("src/lib.rs", "#[test]\nfn a() {}", True),
        ("src/lib.rs", "fn a() {}", False),
        ("notes.txt", "", False),
    ],
)
def test_is_test_file_by_convention(relative: str, source: str, expected: bool) -> None:
    assert is_test_file(relative, relative.rsplit(".", 1)[1], source) is expected


def test_non_test_files_are_never_checked(tmp_path: Path) -> None:
    assert run(tmp_path, "helper.py", "def test_x():\n    pass\n") == []


# --- test-no-assert -------------------------------------------------------------------

RUN = {"java": "svc.run();", "ts": "svc.run();", "py": "svc.run()", "go": "svc.Run()"}


@pytest.mark.parametrize("lang", sorted(FILES))
def test_no_assert_flags_a_test_that_only_runs_code(tmp_path: Path, lang: str) -> None:
    assert flagged(tmp_path, lang, RUN[lang], "test-no-assert")


@pytest.mark.parametrize(
    ("lang", "statement"),
    [
        ("java", "assertThat(x).isEqualTo(1);"),
        ("java", "assertThrows(IllegalStateException.class, () -> svc.run());"),
        ("java", "verify(repo).save(any());"),
        ("java", 'fail("never");'),
        ("java", 'mockMvc.perform(get("/x")).andExpect(status().isOk());'),
        ("java", "assertOrderIsPlaced(order);"),
        ("java", "expectNoErrors();"),
        ("java", "checkInvariants();"),
        ("ts", "expect(x).toBe(1);"),
        ("ts", "assert.equal(x, 1);"),
        ("ts", "assert(x);"),
        ("ts", "await expect(p).resolves.toBe(1);"),
        ("ts", "expectValid(x);"),
        ("ts", "checkOutput(x);"),
        ("ts", "screen.getByText('hello');"),
        ("ts", "t.is(x, 1);"),
        ("py", "assert x"),
        ("py", "self.assertEqual(x, 1)"),
        ("py", "mock.assert_called_once()"),
        ("py", "self.fail('no')"),
        ("py", "check_result(x)"),
        ("py", "self._assert_valid(x)"),
        ("py", "raise AssertionError('bad')"),
        ("py", "with pytest.raises(ValueError):\n        run()"),
        ("py", "with pytest.warns(UserWarning):\n        run()"),
        ("py", "with self.assertRaises(ValueError):\n        run()"),
        ("go", 't.Fatalf("no %d", 1)'),
        ("go", "assert.Equal(t, 1, got)"),
        ("go", "require.NoError(t, err)"),
        ("go", "assertResult(t, got)"),
        ("go", "mockRepo.AssertExpectations(t)"),
        (
            "go",
            "for _, c := range cases {\n\t\tt.Run(c, func(t *testing.T) { assert.Equal(t, 1, c) })\n\t}",
        ),
    ],
)
def test_no_assert_accepts_every_assertion_form_and_local_helper(
    tmp_path: Path, lang: str, statement: str
) -> None:
    assert not flagged(tmp_path, lang, statement, "test-no-assert")


@pytest.mark.parametrize(
    ("name", "source", "symbols"),
    [
        (
            "FooTest.java",
            "class FooTest {\n  @Test\n  void quiet() {\n    run();\n  }\n\n"
            "  @Test\n  void checks() {\n    assertEquals(2, run());\n  }\n}\n",
            [("quiet", 2)],
        ),
        (
            "FooTest.kt",
            "class FooTest {\n  @Test\n  fun `quiet`() {\n    run()\n  }\n\n"
            "  @Test\n  fun a() = runTest {\n    run()\n  }\n\n"
            "  @Test\n  fun b() =\n    assertEquals(1, run())\n}\n",
            [("quiet", 2), ("a", 7)],
        ),
        (
            "a.test.ts",
            "describe('d', () => {\n  it('quiet', () => {\n    run();\n  });\n"
            "  test('checks', () => expect(run()).toBe(2));\n});\n",
            [("quiet", 2)],
        ),
        (
            "test_a.py",
            "def test_quiet():\n    run()\n\n\nclass TestSvc:\n    def test_method(self):\n        run()\n",
            [("test_quiet", 1), ("test_method", 6)],
        ),
        (
            "a_test.go",
            "package a\n\nfunc TestQuiet(t *testing.T) {\n\trun()\n}\n\n"
            "func (s *Suite) TestSuiteQuiet() {\n\trun()\n}\n\n"
            "func (s *Suite) TestSuiteOk() {\n\ts.Equal(1, run())\n}\n",
            [("TestQuiet", 3), ("TestSuiteQuiet", 7)],
        ),
    ],
)
def test_no_assert_reports_symbol_and_line_of_each_quiet_test(
    tmp_path: Path, name: str, source: str, symbols: list[tuple[str, int]]
) -> None:
    found = run(tmp_path, name, source, ("test-no-assert",))
    assert [(symbol, line) for _, symbol, line in found] == symbols


@pytest.mark.parametrize(
    ("name", "source"),
    [
        ("ATest.java", "class A {\n  @Disabled\n  @Test\n  void t() {\n    run();\n  }\n}\n"),
        ("ATest.java", "interface A {\n  @Test\n  void t();\n}\n"),
        (
            "ATest.java",
            "class A {\n  @Test(expected = IllegalStateException.class)\n  void t() {\n    run();\n  }\n}\n",
        ),
        (
            "a.test.js",
            "it.skip('later', () => {\n  run();\n});\nit.todo('x');\nit('ref', handler);\n",
        ),
        (
            "test_a.py",
            "import pytest\n\ndef helper():\n    run()\n\n@pytest.mark.skip\ndef test_s():\n    run()\n",
        ),
        ("test_a.py", "def test_a(:\n"),
        (
            "a_test.go",
            'package a\n\nfunc TestB(t *testing.T) {\n\tt.Skip("later")\n}\n\nfunc TestMain(m *testing.M) {\n\tos.Exit(m.Run())\n}\n',
        ),
        ("a.test.ts", "it('t', () => {\n  run(\n"),
        ("ATest.java", "class A {\n  @Test\n  void t() {\n    run();\n"),
        ("a_test.go", "package a\n\nfunc TestT(t *testing.T) {\n\trun()\n"),
    ],
)
def test_no_assert_ignores_skipped_abstract_and_malformed_tests(
    tmp_path: Path, name: str, source: str
) -> None:
    assert run(tmp_path, name, source, ("test-no-assert",)) == []


@pytest.mark.parametrize(
    ("name", "source", "count"),
    [
        (
            "a.test.js",
            "it('expect(1).toBe(1)', () => {\n  // expect(x).toBe(1)\n  run('assert(x)');\n});\n",
            1,
        ),
        ("a.test.js", "it.each([[1], [2]])('quiet %i', (n) => {\n  run(n);\n});\n", 1),
        ("a.test.js", "it.each`\n  a | b\n  ${1} | ${2}\n`('quiet', () => {\n  run();\n});\n", 1),
        (
            "a_test.go",
            "package a\n\nfunc TestA(t *testing.T) {\n\tmsg := err.Error()\n\t_ = msg\n}\n",
            1,
        ),
        (
            "test_a.py",
            "def test_a():\n    try:\n        run()\n    except ValueError:\n        raise\n",
            1,
        ),
    ],
)
def test_no_assert_is_not_fooled_by_lookalikes(
    tmp_path: Path, name: str, source: str, count: int
) -> None:
    assert len(run(tmp_path, name, source, ("test-no-assert",))) == count


# --- test-trivial-assert --------------------------------------------------------------


@pytest.mark.parametrize(
    ("lang", "statement", "trivial"),
    [
        ("java", "assertTrue(true);", True),
        ("java", "assertFalse(false);", True),
        ("java", "assertEquals(a, a);", True),
        ("java", "assertEquals(1, 1);", True),
        ("java", "assertThat(a).isEqualTo(a);", True),
        ("java", "assertThat(true).isTrue();", True),
        ("java", "assertNull(null);", True),
        ("java", "assertEquals(expected, actual);", False),
        ("java", "assertEquals(0.0, actual, 0.0);", False),
        ("java", "assertEquals(next(), next());", False),
        ("java", 'assertTrue(list.contains("true"));', False),
        ("java", "assertThat(a).isNotEqualTo(a);", False),
        ("ts", "expect(true).toBe(true);", True),
        ("ts", "expect(1).toBe(1);", True),
        ("ts", "expect(x).toEqual(x);", True),
        ("ts", "expect(true).toBeTruthy();", True),
        ("ts", "assert(true);", True),
        ("ts", "assert.equal(x, x);", True),
        ("ts", "expect(x).not.toBe(x);", False),
        ("ts", "expect(f(1)).toBe(f(1));", False),
        ("ts", "expect(result).toBe(1);", False),
        ("py", "assert True", True),
        ("py", "assert 1", True),
        ("py", "assert not False", True),
        ("py", "assert x == x", True),
        ("py", "self.assertTrue(True)", True),
        ("py", "self.assertEqual(a, a)", True),
        ("py", "self.assertIsNone(None)", True),
        ("py", "self.assertFalse(False)", True),
        ("py", "assert x == a", False),
        ("py", "assert x != x", False),
        ("py", "assert f() == f()", False),
        ("py", "assert False", False),
        ("py", "self.assertEqual(x, a)", False),
        ("go", "assert.True(t, true)", True),
        ("go", "assert.Equal(t, got, got)", True),
        ("go", "require.Nil(t, nil)", True),
        ("go", "assert.Equal(t, want, got)", False),
        ("go", "assert.True(t, ok)", False),
    ],
)
def test_trivial_assert_flags_only_assertions_that_cannot_fail(
    tmp_path: Path, lang: str, statement: str, trivial: bool
) -> None:
    assert flagged(tmp_path, lang, statement, "test-trivial-assert") is trivial


# --- test-mock-only -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("lang", "statement", "mock_only"),
    [
        ("java", "verify(repo).save(any());\n    verifyNoMoreInteractions(repo);", True),
        ("java", "then(repo).should().save(any());", True),
        ("java", "verify(repo).save(any());\n    assertEquals(1, svc.run());", False),
        ("java", "then(actual).isEqualTo(1);", False),
        (
            "ts",
            "expect(spy).toHaveBeenCalledWith(1);\n  expect(spy).not.toHaveBeenCalledTimes(2);",
            True,
        ),
        ("ts", "expect(spy).toHaveBeenCalled();\n  expect(result).toBe(1);", False),
        ("py", "repo.save.assert_called_once_with(1)", True),
        ("py", "repo.save.assert_called_once()\n    assert svc.run() == 1", False),
        ("go", "repo.AssertExpectations(t)", True),
        ("go", "repo.AssertExpectations(t)\n\tassert.Equal(t, 1, run())", False),
        ("go", "svc.Run()", False),
    ],
)
def test_mock_only_flags_tests_that_never_check_a_result(
    tmp_path: Path, lang: str, statement: str, mock_only: bool
) -> None:
    assert flagged(tmp_path, lang, statement, "test-mock-only") is mock_only


# --- test-sleep -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("lang", "statement", "sleeps"),
    [
        ("java", "Thread.sleep(500);", True),
        ("java", "TimeUnit.SECONDS.sleep(1);", True),
        ("java", '// Thread.sleep(500);\n    String s = "Thread.sleep(1)";', False),
        ("ts", "await new Promise(r => setTimeout(r, 500));", True),
        ("ts", "await sleep(500);", True),
        ("ts", "const t = setTimeout(cb, 5);", False),
        ("py", "time.sleep(0.5)", True),
        ("py", "time.sleep(0)", False),
        ("py", "clock.sleep(1)", False),
        ("py", "while not ready(): time.sleep(0.1)", False),  # polling with a deadline
        ("go", "time.Sleep(time.Second)", True),
        ("go", "clock.Sleep(time.Second)", False),
    ],
)
def test_sleep_flags_real_sleeps_only(
    tmp_path: Path, lang: str, statement: str, sleeps: bool
) -> None:
    assert flagged(tmp_path, lang, statement, "test-sleep") is sleeps


@pytest.mark.parametrize(
    ("name", "source", "sleeps"),
    [
        ("ATest.kt", "class A {\n  @Test\n  fun t() {\n    Thread.sleep(500)\n  }\n}\n", True),
        ("CalcTests.cs", "class CalcTests {\n  void T() {\n    Thread.Sleep(500);\n  }\n}\n", True),
        ("lib.rs", "#[test]\nfn t() {\n    std::thread::sleep(d);\n}\n", True),
        ("test_a.py", "from time import sleep\n\ndef test_t():\n    sleep(1)\n", True),
        (
            "a.test.ts",
            "jest.useFakeTimers();\nit('t', async () => {\n  await new Promise(r => setTimeout(r, 5));\n});\n",
            False,
        ),
        ("util.py", "import time\n\ndef wait():\n    time.sleep(1)\n", False),
    ],
)
def test_sleep_covers_other_languages_and_respects_fake_timers(
    tmp_path: Path, name: str, source: str, sleeps: bool
) -> None:
    found = run(tmp_path, name, source, ("test-sleep",))
    assert [m for m, _, _ in found] == (["test-sleep"] if sleeps else [])


# --- test-duplicate -------------------------------------------------------------------

PY_A = "def test_a():\n    x = build(1)\n    y = x + 1\n    assert y == 2\n\n\n"
JAVA_DUP = (
    "class ATest {{\n  @Test\n  void first() {{\n    int a = compute(1);\n    int b = a + 1;\n"
    "    assertEquals(2, b);\n  }}\n\n  @Test\n  void second() {{\n    int x = compute(7);\n"
    "    int y = x + 4;\n    assertEquals(9, y);\n  }}\n\n  @Test\n  void other() {{\n"
    "    int a = {call}(1);\n    int b = a + 1;\n    assertEquals(2, b);\n  }}\n}}\n"
)
TS_DUP = (
    "describe('a', () => {\n  it('one', () => {\n    const r = build(1);\n    const s = r + 1;\n"
    "    expect(s).toBe(2);\n  });\n  it('two', () => {\n    const q = build(4);\n"
    "    const w = q + 8;\n    expect(w).toBe(9);\n  });\n});\n"
    "describe('b', () => {\n  it('three', () => {\n    const r = build(1);\n"
    "    const s = r + 1;\n    expect(s).toBe(2);\n  });\n});\n"
)
GO_DUP = (
    "package a\n\nfunc TestOne(t *testing.T) {\n\tgot := Add(1, 2)\n\twant := 3\n"
    "\tassert.Equal(t, want, got)\n}\n\nfunc TestTwo(t *testing.T) {\n\tres := Add(5, 6)\n"
    "\texp := 11\n\tassert.Equal(t, exp, res)\n}\n\nfunc TestThree(t *testing.T) {\n"
    "\tgot := Sub(1, 2)\n\twant := -1\n\tassert.Equal(t, want, got)\n}\n"
)


@pytest.mark.parametrize(
    ("name", "source", "repeats"),
    [
        (
            "test_a.py",
            PY_A
            + "def test_b():\n    value = build(5)\n    total = value + 9\n    assert total == 3\n",
            [("test_b", 7)],
        ),
        ("ATest.java", JAVA_DUP.format(call="other"), [("second", 9)]),
        ("ATest.java", JAVA_DUP.format(call="compute"), [("second", 9), ("other", 16)]),
        ("a.test.ts", TS_DUP, [("two", 7)]),
        ("a_test.go", GO_DUP, [("TestTwo", 9)]),
        (
            "test_a.py",
            PY_A + "def test_b():\n    x = make(1)\n    y = x + 1\n    assert y == 2\n",
            [],
        ),
        (
            "test_a.py",
            "def test_a():\n    x = build(1)\n    assert x\n\n\ndef test_b():\n    x = build(2)\n    assert x\n",
            [],
        ),
        (
            "test_a.py",
            "import pytest\n\n@pytest.mark.parametrize('n', [1])\ndef test_a(n):\n    x = build(n)\n"
            "    y = x + 1\n    assert y\n\n\ndef test_b(n):\n    x = build(n)\n    y = x + 1\n    assert y\n",
            [],
        ),
        (
            "test_a.py",
            "class TestOne:\n    def test_c(self):\n        x = build(1)\n        y = x + 1\n        assert y\n\n\n"
            "class TestTwo:\n    def test_c(self):\n        x = build(1)\n        y = x + 1\n        assert y\n",
            [],
        ),
        (
            "test_a.py",
            "def test_a():\n    '''doc'''\n    x = build(1)\n    y = x + 1\n\n\n"
            "def test_b():\n    x = build(1)\n    y = x + 1\n",
            [],
        ),
    ],
)
def test_duplicate_flags_repeated_bodies_within_one_scope(
    tmp_path: Path, name: str, source: str, repeats: list[tuple[str, int]]
) -> None:
    found = run(tmp_path, name, source, ("test-duplicate",))
    assert [(symbol, line) for _, symbol, line in found] == repeats


# --- classification, config and CLI ---------------------------------------------------


@pytest.mark.parametrize(
    ("changed", "origin"),
    [
        ({"test_a.py": {2}}, "new"),
        ({"test_a.py": {9}}, "legacy"),
        ({"test_a.py": None}, "new"),
        ({"other.py": {2}}, "legacy"),
        (None, "legacy"),
    ],
)
def test_violation_shape_and_origin_follow_the_changed_lines(
    tmp_path: Path, changed: dict[str, set[int] | None] | None, origin: str
) -> None:
    path = tmp_path / "test_a.py"
    path.write_text("def test_a():\n    run()\n    other()\n")
    [violation] = junk_test_violations(tmp_path, [path], TEST_CHECKS, changed)
    assert (violation.metric, violation.value, violation.limit, violation.origin) == (
        "test-no-assert",
        1,
        0,
        origin,
    )
    assert (violation.start_line, violation.end_line) == (1, 3)


def test_disabled_checks_and_unreadable_inputs_report_nothing(tmp_path: Path) -> None:
    quiet = tmp_path / "test_a.py"
    quiet.write_text("def test_a():\n    run()\n")
    bad = tmp_path / "test_bad.py"
    bad.write_bytes(b"\xff\xfe def test_a(): pass")
    (tmp_path / "tests").mkdir()
    assert junk_test_violations(tmp_path, [quiet], ("complexity", "test-sleep")) == []
    assert junk_test_violations(tmp_path, [quiet], ("complexity",)) == []
    assert junk_test_violations(tmp_path, [bad, tmp_path / "tests"], TEST_CHECKS) == []


def test_test_checks_are_configurable_and_hinted(tmp_path: Path) -> None:
    (tmp_path / ".ai-governance").mkdir()
    (tmp_path / ".ai-governance" / "config.toml").write_text(
        '[design]\nchecks = ["test-sleep", "test-mock-only"]\n'
    )
    assert set(TEST_CHECKS) <= set(CHECKS) & set(HINTS)
    assert DesignConfig.load(tmp_path).checks == ("test-sleep", "test-mock-only")


@pytest.mark.parametrize(
    ("config", "code"),
    [("", 1), ('[design]\nchecks = ["complexity"]\n', 0)],
)
def test_cli_reports_junk_tests_unless_their_check_is_disabled(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], config: str, code: int
) -> None:
    (tmp_path / ".ai-governance").mkdir()
    (tmp_path / ".ai-governance" / "config.toml").write_text(config)
    (tmp_path / "test_a.py").write_text("def test_a():\n    run()\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)  # untracked = new code
    exit_code = design_cli.design(["--dir", str(tmp_path), "--changed"])
    out = capsys.readouterr().out
    assert exit_code == code
    assert ("assert the observable result or delete the test" in out) is bool(code)
