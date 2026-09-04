from __future__ import annotations

import json
from ai_governance.frugality.guard import ContextGuard
from ai_governance.frugality.output_trimmer import OutputTrimmer
from ai_governance.frugality.pre_check import PreCheck
from ai_governance.frugality.test_trimmer import TestTrimmer

CFG = {
    "umbral_chars": 500,
    "min_lineas_listado": 50,
    "prefijo_homogeneo_pct": 0.7,
    "head_lineas": 5,
    "tail_lineas": 5,
    "test_umbral_chars": 200,
    "test_head_lineas": 2,
    "test_tail_lineas": 3,
    "test_contexto_antes": 2,
    "test_contexto_despues": 5,
}


def test_trim_pytest_all_passed() -> None:
    lines = [
        "============================= test session starts ==============================",
        "platform darwin -- Python 3.14.0",
        "collected 50 items",
    ]
    for i in range(1, 41):
        lines.append(f"tests/test_module.py::test_case_{i:02d} PASSED")
    lines.extend([
        "",
        "============================== 50 passed in 1.20s ==============================",
    ])
    full_output = "\n".join(lines)

    trimmed = TestTrimmer.trim(full_output, CFG)
    assert len(trimmed) < len(full_output)
    assert "lines of green test output omitted for frugality" in trimmed
    assert "test session starts" in trimmed
    assert "50 passed in 1.20s" in trimmed
    assert "test_case_20 PASSED" not in trimmed


def test_trim_pytest_with_failures() -> None:
    lines = [
        "============================= test session starts ==============================",
        "platform darwin -- Python 3.14.0",
        "collected 20 items",
    ]
    for i in range(1, 10):
        lines.append(f"tests/test_mod.py::test_ok_{i} PASSED")
    lines.extend([
        "______________________________ test_bad_auth _______________________________",
        ">       assert status == 200",
        "E       AssertionError: assert 401 == 200",
        "tests/test_mod.py:55: AssertionError",
    ])
    for i in range(11, 20):
        lines.append(f"tests/test_mod.py::test_ok_{i} PASSED")
    lines.extend([
        "",
        "=========================== short test summary info ============================",
        "FAILED tests/test_mod.py::test_bad_auth - AssertionError: assert 401 == 200",
        "========================= 1 failed, 19 passed in 0.5s ==========================",
    ])
    full_output = "\n".join(lines)

    trimmed = TestTrimmer.trim(full_output, CFG)
    assert "AssertionError: assert 401 == 200" in trimmed
    assert "FAILED tests/test_mod.py::test_bad_auth" in trimmed
    assert "1 failed, 19 passed" in trimmed
    assert "test_ok_18 PASSED" not in trimmed


def test_output_trimmer_large_json() -> None:
    data = [{"id": i, "name": f"item_{i}", "val": i * 10} for i in range(100)]
    json_str = json.dumps(data)

    trimmed = OutputTrimmer.trim_listing(json_str, CFG, reference="see /tmp/out.txt")
    assert trimmed is not None
    assert "JSON array of 100 items" in trimmed
    assert "jq -r '.[].id' <file>" in trimmed
    assert "see /tmp/out.txt" in trimmed


def test_output_trimmer_homogeneous_listing() -> None:
    lines = [f"/src/components/item_{i:03d}.tsx" for i in range(80)]
    raw = "\n".join(lines)

    trimmed = OutputTrimmer.trim_listing(raw, CFG)
    assert trimmed is not None
    assert "lines omitted for frugality" in trimmed
    assert "/src/components/item_000.tsx" in trimmed
    assert "/src/components/item_079.tsx" in trimmed


def test_output_trimmer_skips_git_diff() -> None:
    assert OutputTrimmer.should_skip("git diff HEAD~1") is True
    assert OutputTrimmer.should_skip("git show abcdef") is True
    assert OutputTrimmer.should_skip("git format-patch -1") is True
    assert OutputTrimmer.should_skip("git status") is False


def test_pre_check_wasteful_commands() -> None:
    assert PreCheck.check_command("cat package-lock.json") is not None
    assert PreCheck.check_command("curl https://api.example.com/huge") is not None
    assert PreCheck.check_command("curl https://api.example.com/huge | jq .") is None
    assert PreCheck.check_command("git log") is not None
    assert PreCheck.check_command("git log -n 10") is None
    assert PreCheck.check_command("git log --oneline -5") is None
    assert PreCheck.check_command("cat package-lock.json #nofrugal") is None


def test_context_guard() -> None:
    normal = ContextGuard.evaluate(40_000, threshold=100_000)
    assert normal["status"] == "normal"

    warning = ContextGuard.evaluate(75_000, threshold=100_000)
    assert warning["status"] == "warning"

    critical = ContextGuard.evaluate(110_000, threshold=100_000)
    assert critical["status"] == "critical"
