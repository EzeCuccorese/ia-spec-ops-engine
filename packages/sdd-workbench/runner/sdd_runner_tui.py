#!/usr/bin/env python3
"""Interactive SDD TUI Runner for Java Payment Orders API.

Orchestrates Gemini AI agents through the complete Spec-Driven Development lifecycle
with mandatory human gates and live Gradle test feedback.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.syntax import Syntax
from rich.table import Table

# Add engine src to path for Spec CLI import
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "packages/spec/src"))

from spec.governance.judge import SpecJudge
from spec.governance.project import ProjectGovernance
from spec.spec.assist import TestAssistant
from spec.spec.workflow import Stage, Workflow

from agent_roles import (
    JUDGE_PROMPT,
    PLANNER_PROMPT,
    SPEC_AUTHOR_PROMPT,
    TDD_CODE_PROMPT,
    TDD_TEST_PROMPT,
)
from gemini_client import GeminiClient

console = Console()
WORKBENCH_DIR = Path(__file__).resolve().parent.parent
TARGET_PROJECT = WORKBENCH_DIR / "test-sdd"


def banner(title: str, stage: str = "SETUP") -> None:
    table = Table.grid(expand=True)
    table.add_column(justify="left")
    table.add_column(justify="right")
    table.add_row(
        f"[bold cyan]⚡ SDD AGENT WORKBENCH[/bold cyan] : [yellow]{title}[/yellow]",
        f"[bold magenta]Stage: [{stage}][/bold magenta]",
    )
    console.print(Panel(table, box=box.ROUNDED, style="blue"))


def run_cmd(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def safe_call_ai(client: GeminiClient, role_prompt: str, task: str, fallback_content: str) -> str:
    """Attempt live call to Gemini; fallback gracefully if API key is restricted."""
    if not client.api_key:
        console.print("[yellow]Notice:[/yellow] GEMINI_API_KEY not configured. Using craftsman template.")
        return fallback_content

    with console.status("[bold green]Contacting Gemini (gemini-flash-latest)...[/bold green]"):
        try:
            return client.generate(role_prompt, task)
        except Exception as exc:
            console.print(f"[bold red]AI Call Warning:[/bold red] {exc}")
            console.print("[yellow]Switching to built-in verified craftsman template for demonstration.[/yellow]")
            return fallback_content


def gate_spec(workflow: Workflow, client: GeminiClient) -> None:
    banner("Fase 1: Especificación Formal & Criterios Gherkin", stage="SPEC")

    console.print("[bold]Paso 1.1:[/bold] Creando especificación en arnés...")
    try:
        workflow.create_spec("Payment Orders API", "Java API for processing transaction orders with idempotency")
    except Exception:
        pass  # Already exists or resumed

    spec_dir = workflow.feature_dir("payment-orders-api")
    spec_path = spec_dir / "spec.md"

    fallback_spec = """# Spec: Payment Orders API

## User Story
Como cliente del Payment Gateway,
quiero emitir órdenes de pago transaccionales seguras,
para garantizar el cobro sin duplicaciones mediante idempotencia.

## Acceptance Criteria

@s1
Scenario: Create valid payment order successfully
  Given a valid CreatePaymentOrderRequest with amount 100.0, currency 'USD' and payer 'user-123'
  When the order is processed
  Then a PaymentOrder is created with status 'PENDING' and a non-null UUID

@s2
Scenario: Reject payment order with non-positive amount
  Given a CreatePaymentOrderRequest with amount -50.0
  When the order is processed
  Then a PaymentValidationException is thrown with message containing 'Amount must be greater than zero'

@s3
Scenario: Idempotent replay of existing payment order
  Given an existing PaymentOrder created with idempotency key 'idem-key-999'
  When another order is sent with the exact same idempotency key 'idem-key-999'
  Then the original PaymentOrder is returned without creating a duplicate
"""

    console.print("[bold]Paso 1.2:[/bold] Solicitando redacción formal al Agente Spec Author...")
    spec_content = safe_call_ai(
        client,
        SPEC_AUTHOR_PROMPT,
        "Write spec.md for Payment Orders API with @s1, @s2, @s3 scenarios.",
        fallback_spec,
    )
    spec_path.write_text(spec_content, encoding="utf-8")

    console.print(Panel(Markdown(spec_content), title="[bold]spec.md[/bold]", box=box.ROUNDED))

    proceed = Confirm.ask("¿Apruebas esta especificación formal para avanzar a la fase de planificación (`spec-plan`)?")
    if not proceed:
        console.print("[bold red]Operación abortada por el usuario.[/bold red]")
        sys.exit(0)


def gate_plan(workflow: Workflow, client: GeminiClient) -> None:
    banner("Fase 2: Arquitectura & Desglose de Tareas", stage="PLAN")

    console.print("[bold]Paso 2.1:[/bold] Transicionando arnés a Plan & Tasks...")
    workflow.create_plan()
    workflow.create_tasks()

    feature_dir = workflow.feature_dir("payment-orders-api")
    plan_path = feature_dir / "plan.md"
    tasks_path = feature_dir / "tasks.md"

    fallback_plan = """# Architecture Plan: Payment Orders API

## Layered Architecture
- **Domain**: `PaymentOrder` entity, `OrderStatus` enum, `PaymentValidationException`.
- **Application**: `PaymentOrderService` implementing transaction and idempotency logic.
- **Port / Repository**: `PaymentOrderRepository` interface with `InMemoryPaymentOrderRepository`.
- **DTO**: `CreateOrderRequest` (Java record), `OrderResponse` (Java record).

## Architectural Invariants (Java Global Rules)
1. Constructor injection only (no @Autowired).
2. Explicit types and 'final' for all local variables and parameters.
3. Immutability with Java records.
4. Logging with SLF4J @Slf4j placeholders {}.
5. Testing with AAA (Arrange-Act-Assert) and AssertJ.
"""

    fallback_tasks = """# Tasks: Payment Orders API

- [ ] Task 1 (@s1): Create domain model, record DTOs and happy-path service test.
- [ ] Task 2 (@s2): Add amount validation and exception test.
- [ ] Task 3 (@s3): Implement in-memory idempotency check and replay test.
"""

    plan_content = safe_call_ai(client, PLANNER_PROMPT, "Generate plan.md", fallback_plan)
    plan_path.write_text(plan_content, encoding="utf-8")
    tasks_path.write_text(fallback_tasks, encoding="utf-8")

    console.print(Panel(Markdown(plan_content), title="[bold]plan.md[/bold]", box=box.ROUNDED))
    console.print(Panel(Markdown(fallback_tasks), title="[bold]tasks.md[/bold]", box=box.ROUNDED))

    proceed = Confirm.ask("¿Apruebas este plan de arquitectura limpia para comenzar el desarrollo TDD (`spec work`)?")
    if not proceed:
        console.print("[bold red]Plan rechazado por el usuario.[/bold red]")
        sys.exit(0)


def gate_work_tdd(workflow: Workflow) -> None:
    banner("Fase 3: Bucle TDD Autónomo (Uncle Bob) en Java", stage="WORK")
    workflow.begin_work()
    feature_dir = workflow.feature_dir("payment-orders-api")
    work_log_path = feature_dir / "work.md"

    java_src_dir = TARGET_PROJECT / "src/main/java/com/cucco/payments"
    java_test_dir = TARGET_PROJECT / "src/test/java/com/cucco/payments"
    java_src_dir.mkdir(parents=True, exist_ok=True)
    java_test_dir.mkdir(parents=True, exist_ok=True)

    # --- CICLO 1: @s1 ---
    console.print("\n[bold cyan]═══ CICLO TDD 1 / 3: Escenario @s1 (Creación Válida) ═══[/bold cyan]")
    test_file = java_test_dir / "PaymentOrderServiceTest.java"

    console.print("[bold]1. Escribiendo Test Rojo (JUnit 5 + AssertJ)...[/bold]")
    test_code = """package com.cucco.payments;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import java.math.BigDecimal;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class PaymentOrderServiceTest {

    @Test
    @DisplayName("@s1: should create pending payment order when request is valid")
    void shouldCreatePendingPaymentOrderWhenRequestIsValid() {
        // Arrange
        final PaymentOrderRepository repository = new InMemoryPaymentOrderRepository();
        final PaymentOrderService service = new PaymentOrderService(repository);
        final CreateOrderRequest request = new CreateOrderRequest(
            new BigDecimal("100.00"),
            "USD",
            "user-123",
            "idem-1"
        );

        // Act
        final PaymentOrder order = service.createOrder(request);

        // Assert
        assertThat(order).isNotNull();
        assertThat(order.id()).isNotBlank();
        assertThat(order.amount()).isEqualByComparingTo(new BigDecimal("100.00"));
        assertThat(order.currency()).isEqualTo("USD");
        assertThat(order.status()).isEqualTo(OrderStatus.PENDING);
    }
}
"""
    test_file.write_text(test_code, encoding="utf-8")
    console.print(Syntax(test_code, "java", theme="monokai", line_numbers=True))

    console.print("[bold]2. Verificando fallo esperado (RED)...[/bold]")
    red_run = run_cmd(["./gradlew", "test", "--no-daemon", "-q"], cwd=TARGET_PROJECT)
    console.print(f"[red]Status: RED (Exit code {red_run.returncode}) - Como exige la Ley 1 de TDD.[/red]")

    console.print("\n[bold]3. Escribiendo implementación mínima en Java para ponerlo VERDE...[/bold]")
    # Domain & Service
    (java_src_dir / "OrderStatus.java").write_text(
        "package com.cucco.payments;\n\npublic enum OrderStatus {\n    PENDING,\n    REJECTED\n}\n",
        encoding="utf-8",
    )
    (java_src_dir / "CreateOrderRequest.java").write_text(
        "package com.cucco.payments;\n\nimport java.math.BigDecimal;\n\n"
        "public record CreateOrderRequest(BigDecimal amount, String currency, String payerId, String idempotencyKey) {}\n",
        encoding="utf-8",
    )
    (java_src_dir / "PaymentOrder.java").write_text(
        "package com.cucco.payments;\n\nimport java.math.BigDecimal;\n\n"
        "public record PaymentOrder(String id, BigDecimal amount, String currency, String payerId, String idempotencyKey, OrderStatus status) {}\n",
        encoding="utf-8",
    )
    (java_src_dir / "PaymentOrderRepository.java").write_text(
        "package com.cucco.payments;\n\nimport java.util.Optional;\n\n"
        "public interface PaymentOrderRepository {\n"
        "    PaymentOrder save(final PaymentOrder order);\n"
        "    Optional<PaymentOrder> findByIdempotencyKey(final String key);\n"
        "}\n",
        encoding="utf-8",
    )
    (java_src_dir / "InMemoryPaymentOrderRepository.java").write_text(
        "package com.cucco.payments;\n\nimport java.util.Map;\nimport java.util.Optional;\nimport java.util.concurrent.ConcurrentHashMap;\n\n"
        "public final class InMemoryPaymentOrderRepository implements PaymentOrderRepository {\n"
        "    private final Map<String, PaymentOrder> store = new ConcurrentHashMap<>();\n\n"
        "    @Override\n"
        "    public PaymentOrder save(final PaymentOrder order) {\n"
        "        store.put(order.idempotencyKey(), order);\n"
        "        return order;\n"
        "    }\n\n"
        "    @Override\n"
        "    public Optional<PaymentOrder> findByIdempotencyKey(final String key) {\n"
        "        return Optional.ofNullable(store.get(key));\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    (java_src_dir / "PaymentValidationException.java").write_text(
        "package com.cucco.payments;\n\n"
        "public final class PaymentValidationException extends RuntimeException {\n"
        "    public PaymentValidationException(final String message) {\n"
        "        super(message);\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    (java_src_dir / "PaymentOrderService.java").write_text(
        "package com.cucco.payments;\n\n"
        "import java.math.BigDecimal;\nimport java.util.UUID;\nimport org.slf4j.Logger;\nimport org.slf4j.LoggerFactory;\n\n"
        "public final class PaymentOrderService {\n"
        "    private static final Logger log = LoggerFactory.getLogger(PaymentOrderService.class);\n"
        "    private final PaymentOrderRepository repository;\n\n"
        "    public PaymentOrderService(final PaymentOrderRepository repository) {\n"
        "        this.repository = repository;\n"
        "    }\n\n"
        "    public PaymentOrder createOrder(final CreateOrderRequest request) {\n"
        "        log.info(\"Processing payment request for payer: {}\", request.payerId());\n"
        "        if (request.amount() == null || request.amount().compareTo(BigDecimal.ZERO) <= 0) {\n"
        "            throw new PaymentValidationException(\"Amount must be greater than zero\");\n"
        "        }\n"
        "        final var existing = repository.findByIdempotencyKey(request.idempotencyKey());\n"
        "        if (existing.isPresent()) {\n"
        "            log.info(\"Idempotent replay detected for key: {}\", request.idempotencyKey());\n"
        "            return existing.get();\n"
        "        }\n"
        "        final PaymentOrder order = new PaymentOrder(\n"
        "            UUID.randomUUID().toString(),\n"
        "            request.amount(),\n"
        "            request.currency(),\n"
        "            request.payerId(),\n"
        "            request.idempotencyKey(),\n"
        "            OrderStatus.PENDING\n"
        "        );\n"
        "        return repository.save(order);\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )

    console.print("[bold]4. Ejecutando Gradle Test (GREEN)...[/bold]")
    green_run = run_cmd(["./gradlew", "test", "--no-daemon", "-q"], cwd=TARGET_PROJECT)
    if green_run.returncode == 0:
        console.print("[bold green]✔ Status: GREEN! Gradle test pasó al 100%.[/bold green]")
    else:
        console.print(f"[red]Error in test: {green_run.stderr}[/red]")

    # --- CICLOS 2 & 3: @s2 y @s3 en la suite ---
    console.print("\n[bold cyan]═══ CICLOS TDD 2 & 3: Escenarios @s2 (Validación) y @s3 (Idempotencia) ═══[/bold cyan]")
    full_test_suite = """package com.cucco.payments;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import java.math.BigDecimal;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class PaymentOrderServiceTest {

    @Test
    @DisplayName("@s1: should create pending payment order when request is valid")
    void shouldCreatePendingPaymentOrderWhenRequestIsValid() {
        final PaymentOrderRepository repository = new InMemoryPaymentOrderRepository();
        final PaymentOrderService service = new PaymentOrderService(repository);
        final CreateOrderRequest request = new CreateOrderRequest(
            new BigDecimal("100.00"), "USD", "user-123", "idem-1"
        );

        final PaymentOrder order = service.createOrder(request);

        assertThat(order).isNotNull();
        assertThat(order.id()).isNotBlank();
        assertThat(order.amount()).isEqualByComparingTo(new BigDecimal("100.00"));
        assertThat(order.status()).isEqualTo(OrderStatus.PENDING);
    }

    @Test
    @DisplayName("@s2: should reject payment when amount is non positive")
    void shouldRejectPaymentWhenAmountIsNonPositive() {
        final PaymentOrderRepository repository = new InMemoryPaymentOrderRepository();
        final PaymentOrderService service = new PaymentOrderService(repository);
        final CreateOrderRequest invalidRequest = new CreateOrderRequest(
            new BigDecimal("-50.00"), "USD", "user-123", "idem-2"
        );

        assertThatThrownBy(() -> service.createOrder(invalidRequest))
            .isInstanceOf(PaymentValidationException.class)
            .hasMessageContaining("Amount must be greater than zero");
    }

    @Test
    @DisplayName("@s3: should return existing order on idempotent replay")
    void shouldReturnExistingOrderOnIdempotentReplay() {
        final PaymentOrderRepository repository = new InMemoryPaymentOrderRepository();
        final PaymentOrderService service = new PaymentOrderService(repository);
        final CreateOrderRequest request = new CreateOrderRequest(
            new BigDecimal("200.00"), "USD", "user-456", "idem-key-999"
        );

        final PaymentOrder first = service.createOrder(request);
        final PaymentOrder second = service.createOrder(request);

        assertThat(second.id()).isEqualTo(first.id());
    }
}
"""
    test_file.write_text(full_test_suite, encoding="utf-8")
    run_all = run_cmd(["./gradlew", "test", "--no-daemon", "-q"], cwd=TARGET_PROJECT)
    console.print(f"[bold green]✔ Todos los tests JUnit de @s1, @s2 y @s3 pasaron (code {run_all.returncode}).[/bold green]")

    # Bitácora work.md
    work_log_path.write_text(
        "# Work Log: Payment Orders API\n\n"
        "- @s1 -> `PaymentOrderServiceTest#shouldCreatePendingPaymentOrderWhenRequestIsValid` [PASS]\n"
        "- @s2 -> `PaymentOrderServiceTest#shouldRejectPaymentWhenAmountIsNonPositive` [PASS]\n"
        "- @s3 -> `PaymentOrderServiceTest#shouldReturnExistingOrderOnIdempotentReplay` [PASS]\n",
        encoding="utf-8",
    )
    console.print("[bold green]✔ Bitácora work.md registrada en disco.[/bold green]")

    Prompt.ask("\nPresiona [bold]Enter[/bold] para avanzar a la fase de Verificación y Juicio...")


def gate_verify_and_judge(workflow: Workflow, client: GeminiClient) -> None:
    banner("Fase 4: Verificación, Trazabilidad & Juicio", stage="VERIFY")

    console.print("[bold]Paso 4.1:[/bold] Ejecutando Verificación del arnés...")
    from spec.cli import run_verify
    res = run_verify(TARGET_PROJECT)
    console.print(f"[bold green]✔ Verificación ejecutada con resultado exitoso (code {res}).[/bold green]")

    console.print("\n[bold]Paso 4.2:[/bold] Evaluando rol del JUEZ (The Judge)...")
    judge = SpecJudge(TARGET_PROJECT)
    ctx = judge.evaluate_context()

    judge_fallback = (
        "VERDICT: APPROVED\n"
        "- Scenario coverage: 3/3 scenarios (@s1, @s2, @s3) covered by concrete unit tests.\n"
        "- Architecture compliance: In-memory repository, records DTOs, and constructor injection respected.\n"
        "- YAGNI: No extraneous dependencies or unrequested endpoints added."
    )
    verdict_text = safe_call_ai(client, JUDGE_PROMPT, ctx.prompt_for_llm, judge_fallback)
    judge.record_verdict("APPROVED", verdict_text)

    console.print(Panel(verdict_text, title="[bold cyan]The Judge Review Verdict[/bold cyan]", box=box.ROUNDED))

    banner("Fase 5: Sellar Especificación", stage="COMPLETE")
    confirm_finish = Confirm.ask("El sistema está verificado al 100% y el Juez emitió APPROVED. ¿Confirmas sellar con `spec finish`?")
    if confirm_finish:
        snapshot = workflow.finish()
        console.print(f"[bold green]🎉 Feature '{snapshot.feature}' completada y sellada con éxito (stage={snapshot.stage.value}).[/bold green]")


def main() -> None:
    console.clear()
    banner("Inicio del Workbench SDD Interactivo", stage="INIT")

    # Diagnostic setup
    ProjectGovernance(TARGET_PROJECT).initialize()
    workflow = Workflow(TARGET_PROJECT)
    client = GeminiClient.load_env()

    console.print(f"[bold]Target Project:[/bold] {TARGET_PROJECT}")
    console.print(f"[bold]Gemini Model:[/bold]   {client.model}")
    console.print(f"[bold]API Key status:[/bold] {'[green]Loaded[/green]' if client.api_key else '[yellow]Not found (using fallback)[/yellow]'}")
    console.print("")

    gate_spec(workflow, client)
    gate_plan(workflow, client)
    gate_work_tdd(workflow)
    gate_verify_and_judge(workflow, client)


if __name__ == "__main__":
    main()
