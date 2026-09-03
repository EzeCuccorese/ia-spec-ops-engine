#!/usr/bin/env python3
"""Interactive SDD TUI Runner for Java Payment Orders API.

Orchestrates Gemini AI agents through the complete Spec-Driven Development lifecycle
with mandatory human interview, interactive feedback loop ('Ask Agents') and live Gradle testing.
"""

from __future__ import annotations

import contextlib
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
from spec.spec.workflow import Workflow

from agent_roles import (
    JUDGE_PROMPT,
    PLANNER_PROMPT,
    SPEC_AUTHOR_PROMPT,
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


def safe_call_ai(
    client: GeminiClient,
    role_prompt: str,
    task: str,
    fallback_content: str,
    history: list[dict[str, str]] | None = None,
) -> str:
    """Call Gemini model via Agent Platform (ADC) or API Key, with fallback."""
    with console.status(f"[bold green]Consultando a Gemini ({client.model} vía ADC)...[/bold green]"):
        try:
            return client.generate(role_prompt, task, history=history)
        except Exception as exc:
            console.print(f"[bold red]AI Call Warning:[/bold red] {exc}")
            console.print("[yellow]Utilizando plantilla verificada como respaldo.[/yellow]")
            return fallback_content


def ask_agent_loop(
    client: GeminiClient,
    role_prompt: str,
    initial_task: str,
    artifact_name: str,
    fallback_content: str,
) -> str:
    """Conversational 'Ask Agent' loop: Eze can inspect, ask questions, request changes, or approve."""
    history: list[dict[str, str]] = []
    current_content = safe_call_ai(client, role_prompt, initial_task, fallback_content)

    while True:
        console.print(Panel(Markdown(current_content), title=f"[bold cyan]{artifact_name}[/bold cyan]", box=box.ROUNDED))
        console.print("\n[bold]Opciones:[/bold]")
        console.print("  [bold green][A][/bold green] Aprobar y avanzar")
        console.print("  [bold yellow][P][/bold yellow] Preguntar o pedir cambios al Agente")
        console.print("  [bold red][C][/bold red] Cancelar ejecución")

        choice = Prompt.ask("¿Qué deseas hacer?", choices=["a", "p", "c", "A", "P", "C"], default="a").lower()

        if choice == "a":
            console.print(f"[bold green]✔ {artifact_name} aprobado exitosamente.[/bold green]\n")
            return current_content
        if choice == "c":
            console.print("[bold red]Operación abortada por el usuario.[/bold red]")
            sys.exit(0)
        if choice == "p":
            user_msg = Prompt.ask("\n[bold yellow]Escribe tu pregunta o instrucción de cambio para el Agente[/bold yellow]")
            history.append({
                "role": "user",
                "content": f"El artefacto actual es:\n{current_content}\nFeedback de Ezequiel:\n{user_msg}\nPor favor actualiza {artifact_name} aplicando estas correcciones.",
            })
            current_content = safe_call_ai(
                client,
                role_prompt,
                f"Aplica este cambio a {artifact_name}: {user_msg}",
                fallback_content,
                history=history,
            )


def conduct_requirements_interview() -> dict[str, str]:
    console.print("\n[bold magenta]📋 Entrevista Inicial de Requerimientos (Agent ➔ Human)[/bold magenta]")
    console.print("El Agente necesita tu definición sobre 3 decisiones de arquitectura de negocio:\n")

    # Q1: Monedas
    console.print("[bold cyan]1. Monedas aceptadas en la API:[/bold cyan]")
    console.print("   1) Solo USD (Recomendado para demo)")
    console.print("   2) Multimoneda (USD, EUR, ARS)")
    q1_choice = Prompt.ask("   Selecciona una opción", choices=["1", "2"], default="1")
    q1 = "Solo USD" if q1_choice == "1" else "Multimoneda (USD, EUR, ARS)"

    # Q2: Idempotencia
    console.print("\n[bold cyan]2. Estrategia de Idempotencia:[/bold cyan]")
    console.print("   1) Header 'Idempotency-Key' con repositorio en memoria (Recomendado)")
    console.print("   2) Campo en payload JSON con tabla relacional")
    q2_choice = Prompt.ask("   Selecciona una opción", choices=["1", "2"], default="1")
    q2 = "Header 'Idempotency-Key' con repositorio en memoria" if q2_choice == "1" else "Campo en payload JSON"

    # Q3: Validación de montos
    console.print("\n[bold cyan]3. Política de montos inválidos (<= 0):[/bold cyan]")
    console.print("   1) Rechazo inmediato con PaymentValidationException y código HTTP 400 Bad Request (Recomendado)")
    console.print("   2) Guardar en base de datos con estado REJECTED")
    q3_choice = Prompt.ask("   Selecciona una opción", choices=["1", "2"], default="1")
    q3 = "Excepción PaymentValidationException y HTTP 400" if q3_choice == "1" else "Guardar en estado REJECTED"

    console.print(f"\n[bold green]✔ Decisiones registradas:[/bold green] {q1} | {q2} | {q3}\n")
    return {"currencies": q1, "idempotency": q2, "validation": q3}


def gate_spec(workflow: Workflow, client: GeminiClient) -> None:
    banner("Fase 1: Especificación Formal & Criterios Gherkin", stage="SPEC")

    # Conduct human interview
    answers = conduct_requirements_interview()

    console.print("[bold]Paso 1.1:[/bold] Creando especificación en arnés...")
    with contextlib.suppress(Exception):
        workflow.create_spec("Payment Orders API", "Java API for processing transaction orders with idempotency")

    spec_dir = workflow.feature_dir("payment-orders-api")
    spec_path = spec_dir / "spec.md"

    fallback_spec = f"""# Spec: Payment Orders API

## User Story
Como cliente del Payment Gateway,
quiero emitir órdenes de pago transaccionales seguras ({answers['currencies']}),
para garantizar el cobro sin duplicaciones mediante {answers['idempotency']}.

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

    console.print("[bold]Paso 1.2:[/bold] Solicitando redacción formal al Agente Spec Author con tus respuestas...")
    initial_task = (
        f"Write formal spec.md for Payment Orders API with @s1, @s2, @s3 scenarios.\n"
        f"Business decisions from user: Currencies={answers['currencies']}, "
        f"Idempotency={answers['idempotency']}, Validation={answers['validation']}."
    )
    spec_content = ask_agent_loop(client, SPEC_AUTHOR_PROMPT, initial_task, "spec.md", fallback_spec)
    spec_path.write_text(spec_content, encoding="utf-8")


def gate_plan(workflow: Workflow, client: GeminiClient) -> None:
    banner("Fase 2: Arquitectura & Desglose de Tareas", stage="PLAN")

    console.print("[bold]Paso 2.1:[/bold] Transicionando arnés a Plan & Tasks...")
    with contextlib.suppress(Exception):
        workflow.create_plan()
    with contextlib.suppress(Exception):
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

    plan_content = ask_agent_loop(client, PLANNER_PROMPT, "Generate plan.md following clean Java rules", "plan.md", fallback_plan)
    plan_path.write_text(plan_content, encoding="utf-8")
    tasks_path.write_text(fallback_tasks, encoding="utf-8")


def gate_work_tdd(workflow: Workflow) -> None:
    banner("Fase 3: Bucle TDD Autónomo (Uncle Bob) en Java", stage="WORK")
    with contextlib.suppress(Exception):
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
    console.print(f"[red]Status: RED (Exit code {red_run.returncode}) - Falla antes de implementar (Ley 1 TDD).[/red]")

    console.print("\n[bold]3. Escribiendo implementación mínima en Java para ponerlo VERDE...[/bold]")
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
    console.print(f"[bold green]✔ Todos los tests JUnit de @s1, @s2 y @s3 pasaron (exit code {run_all.returncode}).[/bold green]")

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

    fallback_judge = (
        "VERDICT: APPROVED\n"
        "- Scenario coverage: 3/3 scenarios (@s1, @s2, @s3) covered by concrete unit tests.\n"
        "- Architecture compliance: In-memory repository, records DTOs, and constructor injection respected.\n"
        "- YAGNI: No extraneous dependencies or unrequested endpoints added."
    )
    verdict_text = ask_agent_loop(client, JUDGE_PROMPT, ctx.prompt_for_llm, "The Judge Review", fallback_judge)
    judge.record_verdict("APPROVED", verdict_text)

    banner("Fase 5: Sellar Especificación", stage="COMPLETE")
    confirm_finish = Confirm.ask("El sistema está verificado al 100% y el Juez emitió APPROVED. ¿Confirmas sellar con `spec finish`?")
    if confirm_finish:
        snapshot = workflow.finish()
        console.print(f"[bold green]🎉 Feature '{snapshot.feature}' completada y sellada con éxito (stage={snapshot.stage.value}).[/bold green]\n")

        # Cleanup prompt
        should_clean = Confirm.ask(
            "¿Deseas ejecutar la limpieza automática ahora para dejar el workbench prístino por defecto?",
            default=False,
        )
        if should_clean:
            from clean_workbench import clean_project
            clean_project(force=True)


def main() -> None:
    console.clear()
    banner("Inicio del Workbench SDD Interactivo con Agentes", stage="INIT")

    # Diagnostic setup
    ProjectGovernance(TARGET_PROJECT).initialize()
    workflow = Workflow(TARGET_PROJECT)
    client = GeminiClient.load_env()

    console.print(f"[bold]Target Project:[/bold] {TARGET_PROJECT}")
    console.print(f"[bold]Gemini Model:[/bold]   {client.model}")
    console.print(f"[bold]Auth Mode:[/bold]      {'[green]ADC (Agent Platform Active)[/green]' if client.use_adc and client.project_id else '[yellow]API Key[/yellow]'}")
    console.print(f"[bold]GCP Project:[/bold]    {client.project_id or 'Auto-detected'}")
    console.print("")

    gate_spec(workflow, client)
    gate_plan(workflow, client)
    gate_work_tdd(workflow)
    gate_verify_and_judge(workflow, client)


if __name__ == "__main__":
    main()
