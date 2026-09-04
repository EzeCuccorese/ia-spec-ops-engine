from __future__ import annotations

import sys
from pathlib import Path

# Configure paths so tests can import from both spec engine src and workbench runner
SPEC_DIR = Path(__file__).resolve().parents[1]
SPEC_SRC = SPEC_DIR / "src"
WORKBENCH_RUNNER = SPEC_DIR / "workbench" / "runner"

for p in (str(SPEC_SRC), str(WORKBENCH_RUNNER)):
    if p not in sys.path:
        sys.path.insert(0, p)

import agent_roles
from clean_workbench import TARGET_PROJECT, clean_project
from gemini_client import GeminiClient
from sdd_runner_tui import parse_and_apply_java_files
from spec.governance.audit import ProjectAuditor
from spec.governance.project import ProjectGovernance
from spec.spec.workflow import Workflow


def test_agent_roles_prompts_imported_and_valid_strings() -> None:
    """1. All prompts in agent_roles.py can be imported and are non-empty valid strings."""
    expected_prompts = [
        ("LANGUAGE_DIRECTIVE", agent_roles.LANGUAGE_DIRECTIVE),
        ("JAVA_CRAFTSMANSHIP_RULES", agent_roles.JAVA_CRAFTSMANSHIP_RULES),
        ("INTERVIEW_GENERATOR_PROMPT", agent_roles.INTERVIEW_GENERATOR_PROMPT),
        ("SPEC_AUTHOR_PROMPT", agent_roles.SPEC_AUTHOR_PROMPT),
        ("PLANNER_PROMPT", agent_roles.PLANNER_PROMPT),
        ("TDD_TEST_PROMPT", agent_roles.TDD_TEST_PROMPT),
        ("TDD_CODE_PROMPT", agent_roles.TDD_CODE_PROMPT),
        ("REMEDIATION_CRAFTSMAN_PROMPT", agent_roles.REMEDIATION_CRAFTSMAN_PROMPT),
        ("JUDGE_PROMPT", agent_roles.JUDGE_PROMPT),
    ]

    for name, prompt_value in expected_prompts:
        assert isinstance(prompt_value, str), f"{name} should be a string"
        assert len(prompt_value.strip()) > 0, f"{name} should not be empty"

    # Verify key architectural invariants embedded in prompts
    assert "SPANISH" in agent_roles.LANGUAGE_DIRECTIVE
    assert "ENGLISH" in agent_roles.LANGUAGE_DIRECTIVE
    assert "Dependency Injection" in agent_roles.JAVA_CRAFTSMANSHIP_RULES
    assert "VERDICT: APPROVED" in agent_roles.JUDGE_PROMPT
    assert "@s1" in agent_roles.SPEC_AUTHOR_PROMPT


def test_clean_workbench_cleans_test_sdd_and_passes_governance_audit() -> None:
    """2. clean_project(force=True, verbose=False) cleans test-sdd, leaves state in IDLE, and passes audit."""
    assert TARGET_PROJECT.exists(), f"Workbench test-sdd must exist at {TARGET_PROJECT}"

    # Setup simulated dirty state in test-sdd
    dummy_src = TARGET_PROJECT / "src" / "main" / "java" / "com" / "cucco" / "payments"
    dummy_src.mkdir(parents=True, exist_ok=True)
    (dummy_src / "DirtyPaymentOrder.java").write_text(
        "package com.cucco.payments;\npublic class DirtyPaymentOrder {}\n",
        encoding="utf-8",
    )

    dummy_build = TARGET_PROJECT / "build" / "classes"
    dummy_build.mkdir(parents=True, exist_ok=True)
    (dummy_build / "dummy.class").write_text("binary", encoding="utf-8")

    dummy_gradle = TARGET_PROJECT / ".gradle" / "cache"
    dummy_gradle.mkdir(parents=True, exist_ok=True)
    (dummy_gradle / "cache.bin").write_text("cache", encoding="utf-8")

    spec_dir = TARGET_PROJECT / ".spec"
    spec_dir.mkdir(parents=True, exist_ok=True)
    dummy_spec = spec_dir / "specs" / "dirty-spec"
    dummy_spec.mkdir(parents=True, exist_ok=True)
    (dummy_spec / "spec.md").write_text("# Dirty Spec", encoding="utf-8")

    dummy_evidence = spec_dir / "evidence"
    dummy_evidence.mkdir(parents=True, exist_ok=True)
    (dummy_evidence / "test-run.log").write_text("dirty log", encoding="utf-8")

    dummy_state = spec_dir / "state.json"
    dummy_state.write_text('{"active_feature": "dirty-spec"}', encoding="utf-8")

    # Execute clean_project
    clean_project(force=True, verbose=False)

    # Invariant checks: All generated and build dirs removed
    assert not (TARGET_PROJECT / "src").exists(), "src/ should be deleted by clean_project"
    assert not (TARGET_PROJECT / "build").exists(), "build/ should be deleted by clean_project"
    assert not (TARGET_PROJECT / ".gradle").exists(), ".gradle/ should be deleted by clean_project"
    assert not (spec_dir / "specs").exists(), ".spec/specs/ should be deleted by clean_project"
    assert not (spec_dir / "evidence").exists(), ".spec/evidence/ should be deleted by clean_project"

    # State check: state.json unlinked, workflow in IDLE (status is None)
    assert not dummy_state.exists(), ".spec/state.json should be unlinked"
    workflow = Workflow(TARGET_PROJECT)
    assert workflow.status() is None, "Workflow should be at resting IDLE state"

    # Base governance files preserved/initialized
    assert (spec_dir / "policy.json").is_file(), ".spec/policy.json must exist"
    assert (spec_dir / "verification.json").is_file(), ".spec/verification.json must exist"

    # Governance audits pass successfully
    report = ProjectAuditor(TARGET_PROJECT).audit()
    assert report.passed is True, f"ProjectAuditor failed with items: {report.items}"

    gov_report = ProjectGovernance(TARGET_PROJECT).audit()
    assert gov_report.passed is True, "ProjectGovernance audit should pass"


def test_parse_and_apply_java_files_creates_expected_files(tmp_path: Path) -> None:
    """3. parse_and_apply_java_files correctly parses 'FILE: path\n```java\ncode\n```'."""
    raw_ai_output = """Here is the implementation:

FILE: src/main/java/com/cucco/payments/PaymentOrder.java
```java
package com.cucco.payments;

public record PaymentOrder(String id, long amount, String status) {
    public PaymentOrder {
        if (amount <= 0) {
            throw new IllegalArgumentException("Amount must be positive");
        }
    }
}
```

And here is the corresponding JUnit test:

FILE: src/test/java/com/cucco/payments/PaymentOrderTest.java
```java
package com.cucco.payments;

import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.assertThat;

class PaymentOrderTest {
    @Test
    void shouldCreateValidOrder() {
        final PaymentOrder order = new PaymentOrder("ord-1", 1000L, "PENDING");
        assertThat(order.id()).isEqualTo("ord-1");
    }
}
```
"""

    written_paths = parse_and_apply_java_files(raw_ai_output, tmp_path)

    expected_order_path = tmp_path / "src/main/java/com/cucco/payments/PaymentOrder.java"
    expected_test_path = tmp_path / "src/test/java/com/cucco/payments/PaymentOrderTest.java"

    assert len(written_paths) == 2
    assert expected_order_path in written_paths
    assert expected_test_path in written_paths

    assert expected_order_path.is_file()
    assert expected_test_path.is_file()

    order_content = expected_order_path.read_text(encoding="utf-8")
    assert "public record PaymentOrder(String id, long amount, String status)" in order_content
    assert "package com.cucco.payments;" in order_content

    test_content = expected_test_path.read_text(encoding="utf-8")
    assert "class PaymentOrderTest" in test_content
    assert "assertThat(order.id()).isEqualTo(\"ord-1\");" in test_content


def test_parse_and_apply_java_files_fallback_heuristic(tmp_path: Path) -> None:
    """3b. parse_and_apply_java_files fallback heuristic detects Java class definitions when FILE: is omitted."""
    raw_fallback = """```java
package com.cucco.payments;

public class PaymentOrderService {
    public String ping() {
        return "pong";
    }
}
```
"""
    written = parse_and_apply_java_files(raw_fallback, tmp_path)
    expected_path = tmp_path / "src/main/java/com/cucco/payments/PaymentOrderService.java"

    assert len(written) == 1
    assert expected_path.is_file()
    assert "public class PaymentOrderService" in expected_path.read_text(encoding="utf-8")


def test_gemini_client_instantiation_and_normalization() -> None:
    """4. GeminiClient class can be directly instantiated with clean configuration."""
    client = GeminiClient(
        api_key="direct_api_key_123",
        model="models/gemini-2.5-flash",
        use_adc=False,
        project_id="test-specops-project",
        location="us-central1",
    )

    assert client.api_key == "direct_api_key_123"
    # Verifies 'models/' prefix normalization
    assert client.model == "gemini-2.5-flash"
    assert client.use_adc is False
    assert client.project_id == "test-specops-project"
    assert client.location == "us-central1"


def test_gemini_client_load_env_from_file(tmp_path: Path) -> None:
    """4b. GeminiClient.load_env can parse a custom .env file cleanly."""
    mock_env = tmp_path / ".env"
    mock_env.write_text(
        """# SDD Workbench Config
GEMINI_API_KEY=mock_key_from_env
GEMINI_MODEL_TARGET=gemini-flash-latest
GCP_PROJECT_ID=env-gcp-project
GCP_LOCATION=global
USE_AGENT_PLATFORM=false
""",
        encoding="utf-8",
    )

    client = GeminiClient.load_env(env_path=mock_env)

    assert client.api_key == "mock_key_from_env"
    assert client.model == "gemini-flash-latest"
    assert client.project_id == "env-gcp-project"
    assert client.location == "global"
    assert client.use_adc is False


def test_gemini_client_load_env_default_resolution() -> None:
    """4c. GeminiClient.load_env executes cleanly without throwing unexpected exceptions."""
    # load_env with no path traverses candidate locations or environment variables safely
    client = GeminiClient.load_env()
    assert isinstance(client, GeminiClient)
    assert isinstance(client.model, str)
    assert len(client.model) > 0
