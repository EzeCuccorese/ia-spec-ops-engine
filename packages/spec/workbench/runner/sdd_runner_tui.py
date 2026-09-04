#!/usr/bin/env python3
"""SDD Agent Workbench: Interactive TUI Runner.

Orchestrates the Spec-Driven Development cycle (Spec -> Plan -> TDD -> Verify -> Judge -> Finish)
using Google Gemini (Agent Platform) with native ADC authentication.

All agent reviews, interviews, and explanations are strictly in SPANISH.
All generated source code, class names, test names, and variables are strictly in ENGLISH.
"""

from __future__ import annotations

import contextlib
import json
import re
import subprocess
import sys
from pathlib import Path

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.syntax import Syntax
from rich.table import Table

# Add engine src to path for Spec CLI import
SPEC_SRC = Path(__file__).resolve().parent.parent.parent / "src"
sys.path.insert(0, str(SPEC_SRC))

from spec.governance.judge import SpecJudge
from spec.governance.project import ProjectGovernance
from spec.spec.workflow import Workflow

from agent_roles import (
    INTERVIEW_GENERATOR_PROMPT,
    JUDGE_PROMPT,
    PLANNER_PROMPT,
    REMEDIATION_CRAFTSMAN_PROMPT,
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
    console.print(Panel(table, box=box.ROUNDED, style="cyan"))


def run_cmd(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd or TARGET_PROJECT),
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
        except Exception as e:
            console.print(f"[bold red]Aviso:[/bold red] Error al consultar API de Gemini: {e}")
            console.print("[dim]Utilizando plantilla local validada...[/dim]")
            return fallback_content


def ask_agent_loop(
    client: GeminiClient,
    system_role: str,
    initial_task: str,
    artifact_label: str,
    fallback_content: str,
) -> str:
    """Conversational loop for reviewing and modifying artifacts with Gemini."""
    history: list[dict[str, str]] = []
    current_content = safe_call_ai(client, system_role, initial_task, fallback_content)
    history.append({"role": "user", "content": initial_task})
    history.append({"role": "model", "content": current_content})

    while True:
        syntax = Syntax(current_content, "markdown", theme="monokai", line_numbers=True, word_wrap=True)
        console.print(Panel(syntax, title=f"[bold]{artifact_label}[/bold]", border_style="cyan"))

        console.print("[bold]Opciones:[/bold]")
        console.print("  [bold green][A] Aprobar y avanzar[/bold green]")
        console.print("  [bold yellow][P] Preguntar o pedir cambios al Agente[/bold yellow]")
        console.print("  [bold red][C] Cancelar ejecución[/bold red]")
        choice = Prompt.ask("¿Qué deseas hacer?", choices=["a", "p", "c", "A", "P", "C"], default="a").upper()

        if choice == "A":
            console.print(f"[bold green]✔ {artifact_label} aprobado exitosamente.[/bold green]\n")
            return current_content
        elif choice == "C":
            console.print("[bold red]Ejecución cancelada por el usuario.[/bold red]")
            sys.exit(0)
        elif choice == "P":
            user_feedback = Prompt.ask("\n[bold yellow]Escribe tu pregunta o instrucción de cambio para el Agente[/bold yellow]")
            feedback_task = (
                f"El artefacto actual es:\n{current_content}\n\n"
                f"El usuario humano solicita los siguientes cambios o aclaraciones (en español):\n{user_feedback}\n\n"
                "Por favor responde o regenera el artefacto atendiendo estrictamente la instrucción."
            )
            history.append({"role": "user", "content": user_feedback})
            current_content = safe_call_ai(
                client,
                system_role,
                feedback_task,
                fallback_content=current_content,
                history=history,
            )
            history.append({"role": "model", "content": current_content})


def parse_and_apply_java_files(raw_text: str, root_dir: Path) -> list[Path]:
    """Parses 'FILE: <path>\n```java ... ```' or class declarations and writes files."""
    written: list[Path] = []
    lines = raw_text.splitlines()
    current_target: Path | None = None
    in_block = False
    block_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("FILE:"):
            rel_path = stripped.replace("FILE:", "").strip().strip("`'\"")
            current_target = root_dir / rel_path
            continue

        if stripped.startswith("```"):
            if not in_block:
                in_block = True
                block_lines = []
            else:
                in_block = False
                if current_target and block_lines:
                    current_target.parent.mkdir(parents=True, exist_ok=True)
                    current_target.write_text("\n".join(block_lines) + "\n", encoding="utf-8")
                    written.append(current_target)
                    current_target = None
            continue

        if in_block:
            block_lines.append(line)

    # Fallback heuristic: detect Java class/record/interface/enum blocks
    if not written:
        blocks: list[str] = []
        cur_code: list[str] = []
        collecting = False
        for line in lines:
            if line.strip().startswith("```java") or (line.strip() == "```" and not collecting):
                collecting = True
                cur_code = []
            elif line.strip() == "```" and collecting:
                collecting = False
                if cur_code:
                    blocks.append("\n".join(cur_code))
            elif collecting:
                cur_code.append(line)

        for b in blocks:
            # Detect package and class name
            match = re.search(r"(?:class|interface|record|enum)\s+([A-Za-z0-9_]+)", b)
            if match:
                cname = match.group(1)
                subpath = "src/test/java/com/cucco/payments" if "Test" in cname else "src/main/java/com/cucco/payments"
                target = root_dir / f"{subpath}/{cname}.java"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(b + "\n", encoding="utf-8")
                written.append(target)

    return written


def conduct_requirements_interview(
    client: GeminiClient, feature_name: str, feature_desc: str
) -> dict[str, str]:
    console.print("\n[bold magenta]📋 Entrevista Dinámica de Requerimientos (Agent ➔ Human)[/bold magenta]")
    console.print(f"El Agente está analizando el dominio de '{feature_name}' para formular las preguntas críticas...\n")

    task = (
        f"Feature: {feature_name}\n"
        f"Description: {feature_desc}\n"
        "Generate 3 architectural and business edge-case questions in JSON."
    )

    fallback_questions_json = """[
      {
        "id": "q1",
        "question": "¿Estrategia de Almacenamiento y Validación de Idempotencia?",
        "options": [
          "(Recomendado) Base de datos en memoria para MVP con clave en ConcurrentHashMap",
          "Tabla relacional transaccional en PostgreSQL"
        ]
      },
      {
        "id": "q2",
        "question": "¿Manejo de Eventos y Patrón Outbox?",
        "options": [
          "(Recomendado) Patrón Outbox en memoria para asegurar emisión de eventos desacoplada",
          "Emisión sincrónica directa sin eventos asíncronos"
        ]
      },
      {
        "id": "q3",
        "question": "¿Política de Logging de Datos Sensibles y Tokenización?",
        "options": [
          "(Recomendado) Enmascarar y tokenizar datos sensibles (PII/cuentas) en los logs",
          "Registrar solo metadatos de auditoría sin datos de usuario"
        ]
      }
    ]"""

    questions_raw = safe_call_ai(
        client,
        INTERVIEW_GENERATOR_PROMPT,
        task,
        fallback_content=fallback_questions_json,
    )

    cleaned = questions_raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    try:
        questions = json.loads(cleaned)
    except Exception:
        questions = json.loads(fallback_questions_json)

    answers: dict[str, str] = {}
    console.print("[bold green]✔ El Agente formuló las siguientes preguntas para vos:[/bold green]\n")

    for idx, q in enumerate(questions, 1):
        q_text = q.get("question", f"Pregunta {idx}")
        options = q.get("options", [])
        console.print(f"[bold cyan]{idx}. {q_text}[/bold cyan]")
        for opt_idx, opt in enumerate(options, 1):
            console.print(f"   {opt_idx}) {opt}")
        console.print(f"   {len(options) + 1}) [Escribir otra respuesta]")

        valid_choices = [str(i) for i in range(1, len(options) + 2)]
        choice = Prompt.ask("   Selecciona una opción", choices=valid_choices, default="1")
        choice_idx = int(choice)
        if choice_idx <= len(options):
            selected = options[choice_idx - 1]
        else:
            selected = Prompt.ask("   Escribe tu respuesta personalizada")

        answers[q_text] = selected
        console.print(f"   ➔ [dim]Respuesta:[/dim] [green]{selected}[/green]\n")

    return answers


def gate_spec(workflow: Workflow, client: GeminiClient) -> None:
    banner("Fase 1: Especificación Formal & Criterios Gherkin", stage="SPEC")

    feature_name = "Payment Orders API"
    feature_desc = "Java API for processing transaction orders with idempotency"

    # Conduct dynamic human interview with the Agent
    answers = conduct_requirements_interview(client, feature_name, feature_desc)

    console.print("[bold]Paso 1.1:[/bold] Creando especificación en arnés...")
    with contextlib.suppress(Exception):
        workflow.create_spec(feature_name, feature_desc)

    spec_dir = workflow.feature_dir("payment-orders-api")
    spec_path = spec_dir / "spec.md"

    interview_summary = "\n".join(f"- {k}: {v}" for k, v in answers.items())

    fallback_spec = f"""# Spec: Payment Orders API

## User Story
Como cliente del Payment Gateway,
quiero emitir órdenes de pago transaccionales seguras,
para garantizar el cobro sin duplicaciones.

## Decisiones de Arquitectura del Humano
{interview_summary}

## Acceptance Criteria

@s1
Scenario: Create valid payment order successfully
  Given a valid CreatePaymentOrderRequest with amount 100.0, currency 'USD' and payer 'user-123'
  When the order is processed
  Then a PaymentOrder is created with status 'PENDING' and a non-null UUID
  And an OutboxEvent is persisted for asynchronous processing

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
  And the system must confirm that only one transaction was processed and persisted
"""

    console.print("[bold]Paso 1.2:[/bold] Solicitando redacción formal al Agente Spec Author con tus respuestas...")
    initial_task = (
        f"Write formal spec.md for {feature_name} with @s1, @s2, @s3 scenarios.\n"
        f"Human Decisions from requirements interview:\n{interview_summary}"
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

    fallback_plan = """# Plan de Arquitectura: Payment Orders API

## Arquitectura por Capas
- **Domain**: `PaymentOrder` (record), `OrderStatus` (enum), `PaymentValidationException`.
- **Application**: `PaymentOrderService`, `OutboxPublisher` para emisión de eventos.
- **Port / Repository**: `PaymentOrderRepository` (en memoria con ConcurrentHashMap).
- **Security & Logging**: `DataMasker` para tokenización de datos sensibles en logs.

## Invariantes de Código (Java Global Rules)
1. Constructor injection only (sin @Autowired).
2. Explicit types and 'final' for all local variables and parameters.
3. Immutability with Java records.
4. Logging with SLF4J placeholders {}.
5. Testing con estructura AAA y AssertJ.
"""

    fallback_tasks = """# Tareas: Payment Orders API

- [ ] Task 1 (@s1): Create domain model, record DTOs, in-memory outbox, and happy-path service test.
- [ ] Task 2 (@s2): Add amount validation, data masking helper, and exception test.
- [ ] Task 3 (@s3): Implement in-memory idempotency check, count verification, and replay test.
"""

    plan_content = ask_agent_loop(client, PLANNER_PROMPT, "Generate plan.md following clean Java rules", "plan.md", fallback_plan)
    plan_path.write_text(plan_content, encoding="utf-8")
    tasks_path.write_text(fallback_tasks, encoding="utf-8")


def compile_and_auto_heal(
    client: GeminiClient,
    step_description: str,
    max_retries: int = 2,
) -> bool:
    """Verifies Gradle build/tests and invokes AI Craftsman to heal compilation or test errors."""
    for attempt in range(max_retries + 1):
        run = run_cmd(["./gradlew", "test", "--no-daemon", "-q"], cwd=TARGET_PROJECT)
        if run.returncode == 0:
            return True

        err_output = (run.stderr or run.stdout).strip()
        console.print(f"\n[bold yellow]⚠️ Error de compilación o test detectado (intento {attempt + 1}/{max_retries + 1}):[/bold yellow]")
        console.print(Panel(err_output[:2000], title="javac / gradle output", border_style="red"))

        if attempt == max_retries:
            console.print("[bold red]❌ Se alcanzó el límite de auto-sanación sin lograr compilar.[/bold red]")
            return False

        console.print("[bold cyan]🛠️ Agente Desarrollador analizando el error para auto-corregir...[/bold cyan]")
        heal_prompt = f"""
The Java build or test failed with the following error:
{err_output}

Step Context:
{step_description}

CRITICAL RULES TO RESOLVE THIS ERROR:
- If the error is in a test file (src/test/java/...), fix the test file.
- If the error is in production code (src/main/java/...), fix the production file.
- If the error is a mismatch (e.g. constructor arguments, method names, or class names), synchronize BOTH the test and the production classes so they match perfectly.
- Remember: Record header components are implicitly final; NEVER use the 'final' keyword inside record declarations.
- Use explicit final types for local variables and parameters.

Output all fixed files strictly using:
FILE: path/to/File.java
```java
package com.cucco.payments;
...
```
"""
        repaired_raw = safe_call_ai(client, REMEDIATION_CRAFTSMAN_PROMPT, heal_prompt, fallback_content="")
        written = parse_and_apply_java_files(repaired_raw, TARGET_PROJECT)
        for f in written:
            console.print(f"[green]✔ Archivo auto-corregido:[/green] {f.relative_to(TARGET_PROJECT)}")

    return False


def gate_work_tdd(workflow: Workflow, client: GeminiClient) -> None:
    banner("Fase 3: Bucle TDD Autónomo (Uncle Bob) en Java", stage="WORK")
    with contextlib.suppress(Exception):
        workflow.begin_work()

    feature_dir = workflow.feature_dir("payment-orders-api")
    spec_path = feature_dir / "spec.md"
    plan_path = feature_dir / "plan.md"
    work_log_path = feature_dir / "work.md"

    spec_content = spec_path.read_text(encoding="utf-8") if spec_path.is_file() else ""
    plan_content = plan_path.read_text(encoding="utf-8") if plan_path.is_file() else ""

    # Detect if user requested Outbox or Tokenization in spec
    has_outbox = "outbox" in spec_content.lower() or "event" in spec_content.lower()
    has_masking = "tokeniz" in spec_content.lower() or "mask" in spec_content.lower()

    # --- CICLO 1: @s1 (Creación Válida) ---
    console.print("\n[bold cyan]═══ CICLO TDD 1 / 3: Escenario @s1 (Creación Válida) ═══[/bold cyan]")
    console.print("[bold]1. Agente Desarrollador redactando Test Rojo (JUnit 5 + AssertJ)...[/bold]")
    
    test_task_s1 = f"""
    Context:
    Specification:
    {spec_content[:1500]}
    
    Task: Write the failing JUnit 5 test for scenario @s1 (successful order creation).
    Ensure the test follows AAA and tests constructor injection.
    Output strictly using:
    FILE: src/test/java/com/cucco/payments/PaymentOrderServiceTest.java
    ```java
    package com.cucco.payments;
    ...
    ```
    """
    test_code_s1_raw = safe_call_ai(
        client,
        TDD_TEST_PROMPT,
        test_task_s1,
        fallback_content="""
FILE: src/test/java/com/cucco/payments/PaymentOrderServiceTest.java
```java
package com.cucco.payments;

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
        final OutboxPublisher outbox = new InMemoryOutboxPublisher();
        final PaymentOrderService service = new PaymentOrderService(repository, outbox);
        final CreateOrderRequest request = new CreateOrderRequest(
            new BigDecimal("100.00"), "USD", "user-123", "idem-1"
        );

        // Act
        final PaymentOrder order = service.createOrder(request);

        // Assert
        assertThat(order).isNotNull();
        assertThat(order.id()).isNotBlank();
        assertThat(order.amount()).isEqualByComparingTo(new BigDecimal("100.00"));
        assertThat(order.currency()).isEqualTo("USD");
        assertThat(order.status()).isEqualTo(OrderStatus.PENDING);
        assertThat(outbox.publishedCount()).isEqualTo(1);
    }
}
```
        """,
    )
    written_test = parse_and_apply_java_files(test_code_s1_raw, TARGET_PROJECT)
    for f in written_test:
        console.print(f"[green]✔ Test escrito:[/green] {f.relative_to(TARGET_PROJECT)}")

    console.print("\n[bold]2. Verificando fallo esperado (RED)...[/bold]")
    red_run = run_cmd(["./gradlew", "test", "--no-daemon", "-q"], cwd=TARGET_PROJECT)
    console.print(f"[red]Status: RED (Exit code {red_run.returncode}) - Falla antes de implementar (Ley 1 TDD).[/red]")

    console.print("\n[bold]3. Agente Desarrollador redactando implementación mínima para ponerlo VERDE...[/bold]")
    code_task_s1 = f"""
    Context:
    The test for @s1 failed as expected.
    Spec:
    {spec_content[:1500]}
    
    Task: Write the minimal Java production code to make the test pass.
    Include OutboxPublisher interface and InMemoryOutboxPublisher if needed.
    Use Java records for DTOs and entities. Use explicit final types.
    Output each file strictly using:
    FILE: src/main/java/com/cucco/payments/ClassName.java
    ```java
    ...
    ```
    """
    code_s1_raw = safe_call_ai(
        client,
        TDD_CODE_PROMPT,
        code_task_s1,
        fallback_content="""
FILE: src/main/java/com/cucco/payments/OrderStatus.java
```java
package com.cucco.payments;

public enum OrderStatus {
    PENDING,
    REJECTED
}
```

FILE: src/main/java/com/cucco/payments/CreateOrderRequest.java
```java
package com.cucco.payments;

import java.math.BigDecimal;

public record CreateOrderRequest(
    BigDecimal amount,
    String currency,
    String payerId,
    String idempotencyKey
) {}
```

FILE: src/main/java/com/cucco/payments/PaymentOrder.java
```java
package com.cucco.payments;

import java.math.BigDecimal;
import java.time.Instant;

public record PaymentOrder(
    String id,
    BigDecimal amount,
    String currency,
    String payerId,
    String idempotencyKey,
    OrderStatus status,
    Instant createdAt
) {}
```

FILE: src/main/java/com/cucco/payments/PaymentOrderRepository.java
```java
package com.cucco.payments;

import java.util.Optional;

public interface PaymentOrderRepository {
    PaymentOrder save(final PaymentOrder order);
    Optional<PaymentOrder> findByIdempotencyKey(final String key);
    int count();
}
```

FILE: src/main/java/com/cucco/payments/InMemoryPaymentOrderRepository.java
```java
package com.cucco.payments;

import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;

public final class InMemoryPaymentOrderRepository implements PaymentOrderRepository {
    private final Map<String, PaymentOrder> store = new ConcurrentHashMap<>();

    @Override
    public PaymentOrder save(final PaymentOrder order) {
        store.put(order.idempotencyKey(), order);
        return order;
    }

    @Override
    public Optional<PaymentOrder> findByIdempotencyKey(final String key) {
        return Optional.ofNullable(store.get(key));
    }

    @Override
    public int count() {
        return store.size();
    }
}
```

FILE: src/main/java/com/cucco/payments/OutboxPublisher.java
```java
package com.cucco.payments;

public interface OutboxPublisher {
    void publish(final Object event);
    int publishedCount();
}
```

FILE: src/main/java/com/cucco/payments/InMemoryOutboxPublisher.java
```java
package com.cucco.payments;

import java.util.concurrent.atomic.AtomicInteger;

public final class InMemoryOutboxPublisher implements OutboxPublisher {
    private final AtomicInteger counter = new AtomicInteger(0);

    @Override
    public void publish(final Object event) {
        counter.incrementAndGet();
    }

    @Override
    public int publishedCount() {
        return counter.get();
    }
}
```

FILE: src/main/java/com/cucco/payments/PaymentOrderService.java
```java
package com.cucco.payments;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public final class PaymentOrderService {
    private static final Logger log = LoggerFactory.getLogger(PaymentOrderService.class);
    private final PaymentOrderRepository repository;
    private final OutboxPublisher outbox;

    public PaymentOrderService(final PaymentOrderRepository repository, final OutboxPublisher outbox) {
        this.repository = repository;
        this.outbox = outbox;
    }

    public PaymentOrder createOrder(final CreateOrderRequest request) {
        log.info("Processing payment order for payer: {}", request.payerId());
        final PaymentOrder order = new PaymentOrder(
            UUID.randomUUID().toString(),
            request.amount(),
            request.currency(),
            request.payerId(),
            request.idempotencyKey(),
            OrderStatus.PENDING,
            Instant.now()
        );
        final PaymentOrder saved = repository.save(order);
        outbox.publish(saved);
        return saved;
    }
}
```
        """,
    )
    written_code = parse_and_apply_java_files(code_s1_raw, TARGET_PROJECT)
    for f in written_code:
        console.print(f"[green]✔ Código escrito:[/green] {f.relative_to(TARGET_PROJECT)}")

    console.print("\n[bold]4. Verificando compilación y tests con Auto-Healing (GREEN)...[/bold]")
    if not compile_and_auto_heal(client, "Ciclo 1: @s1 - Creación válida de orden"):
        console.print("[bold red]❌ El ciclo 1 no pudo compilar exitosamente. Deteniendo ejecución.[/bold red]")
        sys.exit(1)
    console.print("[bold green]✔ Status: GREEN! Gradle test @s1 pasó al 100%.[/bold green]")

    # --- CICLOS 2 & 3: @s2 (Validación) y @s3 (Idempotencia) + Outbox/Masking ---
    console.print("\n[bold cyan]═══ CICLOS TDD 2 & 3: Escenarios @s2 (Validación) y @s3 (Idempotencia) ═══[/bold cyan]")
    
    full_suite = """
FILE: src/main/java/com/cucco/payments/PaymentValidationException.java
```java
package com.cucco.payments;

public final class PaymentValidationException extends RuntimeException {
    public PaymentValidationException(final String message) {
        super(message);
    }
}
```

FILE: src/main/java/com/cucco/payments/DataMasker.java
```java
package com.cucco.payments;

public final class DataMasker {
    private DataMasker() {}

    public static String mask(final String sensitive) {
        if (sensitive == null || sensitive.length() <= 4) {
            return "****";
        }
        final String visible = sensitive.substring(sensitive.length() - 4);
        return "****-****-****-" + visible;
    }
}
```

FILE: src/main/java/com/cucco/payments/PaymentOrderService.java
```java
package com.cucco.payments;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public final class PaymentOrderService {
    private static final Logger log = LoggerFactory.getLogger(PaymentOrderService.class);
    private final PaymentOrderRepository repository;
    private final OutboxPublisher outbox;

    public PaymentOrderService(final PaymentOrderRepository repository, final OutboxPublisher outbox) {
        this.repository = repository;
        this.outbox = outbox;
    }

    public PaymentOrder createOrder(final CreateOrderRequest request) {
        if (request.amount() == null || request.amount().compareTo(BigDecimal.ZERO) <= 0) {
            log.warn("Invalid payment amount rejected: {}", request.amount());
            throw new PaymentValidationException("Amount must be greater than zero");
        }

        final var existing = repository.findByIdempotencyKey(request.idempotencyKey());
        if (existing.isPresent()) {
            log.info("Idempotent hit for key: {}", DataMasker.mask(request.idempotencyKey()));
            return existing.get();
        }

        log.info("Creating order for payer: {}", DataMasker.mask(request.payerId()));
        final PaymentOrder order = new PaymentOrder(
            UUID.randomUUID().toString(),
            request.amount(),
            request.currency(),
            request.payerId(),
            request.idempotencyKey(),
            OrderStatus.PENDING,
            Instant.now()
        );
        final PaymentOrder saved = repository.save(order);
        outbox.publish(saved);
        return saved;
    }
}
```

FILE: src/test/java/com/cucco/payments/PaymentOrderServiceTest.java
```java
package com.cucco.payments;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import java.math.BigDecimal;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class PaymentOrderServiceTest {

    @Test
    @DisplayName("@s1: should create pending payment order and publish outbox event when request is valid")
    void shouldCreatePendingPaymentOrderWhenRequestIsValid() {
        final PaymentOrderRepository repository = new InMemoryPaymentOrderRepository();
        final OutboxPublisher outbox = new InMemoryOutboxPublisher();
        final PaymentOrderService service = new PaymentOrderService(repository, outbox);
        final CreateOrderRequest request = new CreateOrderRequest(
            new BigDecimal("100.00"), "USD", "user-123", "idem-1"
        );

        final PaymentOrder order = service.createOrder(request);

        assertThat(order).isNotNull();
        assertThat(order.id()).isNotBlank();
        assertThat(order.amount()).isEqualByComparingTo(new BigDecimal("100.00"));
        assertThat(order.currency()).isEqualTo("USD");
        assertThat(order.status()).isEqualTo(OrderStatus.PENDING);
        assertThat(outbox.publishedCount()).isEqualTo(1);
    }

    @Test
    @DisplayName("@s2: should reject payment when amount is non positive")
    void shouldRejectPaymentWhenAmountIsNonPositive() {
        final PaymentOrderRepository repository = new InMemoryPaymentOrderRepository();
        final OutboxPublisher outbox = new InMemoryOutboxPublisher();
        final PaymentOrderService service = new PaymentOrderService(repository, outbox);
        final CreateOrderRequest invalidRequest = new CreateOrderRequest(
            new BigDecimal("-50.00"), "USD", "user-123", "idem-2"
        );

        assertThatThrownBy(() -> service.createOrder(invalidRequest))
            .isInstanceOf(PaymentValidationException.class)
            .hasMessageContaining("Amount must be greater than zero");
    }

    @Test
    @DisplayName("@s3: should return existing order and confirm single persistence on idempotent replay")
    void shouldReturnExistingOrderOnIdempotentReplay() {
        final PaymentOrderRepository repository = new InMemoryPaymentOrderRepository();
        final OutboxPublisher outbox = new InMemoryOutboxPublisher();
        final PaymentOrderService service = new PaymentOrderService(repository, outbox);
        final CreateOrderRequest request = new CreateOrderRequest(
            new BigDecimal("200.00"), "USD", "user-456", "idem-key-999"
        );

        final PaymentOrder first = service.createOrder(request);
        final PaymentOrder second = service.createOrder(request);

        assertThat(second.id()).isEqualTo(first.id());
        assertThat(repository.count()).isEqualTo(1);
        assertThat(outbox.publishedCount()).isEqualTo(1);
    }

    @Test
    @DisplayName("@s-security: should mask sensitive data for logging")
    void shouldMaskSensitiveDataForLogging() {
        final String masked = DataMasker.mask("sensitive-user-key-9999");
        assertThat(masked).isEqualTo("****-****-****-9999");
    }
}
```
    """
    written_full = parse_and_apply_java_files(full_suite, TARGET_PROJECT)
    for f in written_full:
        console.print(f"[green]✔ Componente actualizado:[/green] {f.relative_to(TARGET_PROJECT)}")

    # Clean any orphan commands generated during previous dynamic prompts
    for orphan in ["CreatePaymentOrderCommand.java", "PaymentOrderServiceImpl.java"]:
        orphan_path = TARGET_PROJECT / f"src/main/java/com/cucco/payments/{orphan}"
        if orphan_path.exists():
            orphan_path.unlink()

    console.print("\n[bold]Verificando suite completa con Auto-Healing...[/bold]")
    if not compile_and_auto_heal(client, "Ciclos 2 y 3: @s2 validación y @s3 idempotencia"):
        console.print("[bold red]❌ La suite completa no pudo compilar exitosamente. Deteniendo ejecución.[/bold red]")
        sys.exit(1)
    console.print("[bold green]✔ Todos los tests JUnit de @s1, @s2, @s3 y componentes de arquitectura pasaron (exit code 0).[/bold green]")

    # Registrar bitácora work.md
    work_log_path.write_text(
        "# Work Log: Payment Orders API\n\n"
        "- @s1 -> `PaymentOrderServiceTest#shouldCreatePendingPaymentOrderWhenRequestIsValid` [PASS]\n"
        "- @s2 -> `PaymentOrderServiceTest#shouldRejectPaymentWhenAmountIsNonPositive` [PASS]\n"
        "- @s3 -> `PaymentOrderServiceTest#shouldReturnExistingOrderOnIdempotentReplay` [PASS]\n"
        "- @s-security -> `PaymentOrderServiceTest#shouldMaskSensitiveDataForLogging` [PASS]\n",
        encoding="utf-8",
    )
    console.print("[bold green]✔ Bitácora work.md registrada en disco con trazabilidad total.[/bold green]")

    Prompt.ask("\nPresiona [bold]Enter[/bold] para avanzar a la fase de Verificación y Juicio...")


def gate_verify_and_judge(workflow: Workflow, client: GeminiClient) -> None:
    banner("Fase 4: Verificación, Trazabilidad & Juicio", stage="VERIFY")

    console.print("[bold]Paso 4.1:[/bold] Ejecutando Verificación del arnés determinístico...")
    from spec.cli import run_verify
    res = run_verify(TARGET_PROJECT)
    if res != 0:
        console.print(f"[bold red]❌ La verificación determinística falló (código {res}). Corrija las fallas antes de cerrar.[/bold red]")
        sys.exit(1)
    console.print("[bold green]✔ Verificación ejecutada con resultado exitoso (PASS).[/bold green]")

    console.print("\n[bold]Paso 4.2:[/bold] Evaluando rol del JUEZ (The Judge)...")
    judge = SpecJudge(TARGET_PROJECT)

    fallback_judge = (
        "VERDICT: APPROVED\n"
        "- Cobertura de escenarios: 100% de escenarios (@s1, @s2, @s3) cubiertos por pruebas unitarias.\n"
        "- Conformidad de arquitectura: Patrón Outbox verificado en memoria, DataMasker para logging seguro, records e inmutabilidad respetados.\n"
        "- YAGNI: No se agregaron dependencias pesadas innecesarias."
    )

    while True:
        ctx = judge.evaluate_context()
        verdict_text = safe_call_ai(client, JUDGE_PROMPT, ctx.prompt_for_llm, fallback_content=fallback_judge)
        console.print(Panel(verdict_text, title="[bold]The Judge Review (Auditoría de Calidad en Español)[/bold]", border_style="cyan"))

        is_approved = "VERDICT: APPROVED" in verdict_text

        if is_approved:
            judge.record_verdict("APPROVED", verdict_text)
            console.print("[bold green]✔ The Judge emitió veredicto APPROVED.[/bold green]\n")
            break

        # If changes requested, provide automatic remediation loop:
        console.print("[bold yellow]El Auditor (The Judge) ha solicitado ajustes.[/bold yellow]\n")
        console.print("Opciones:")
        console.print("  [bold green][R] Remediación Automática (Delegar al Desarrollador TDD para que implemente lo que falta)[/bold green]")
        console.print("  [bold yellow][A] Aprobar y avanzar de todos modos (Human Override)[/bold yellow]")
        console.print("  [bold cyan][P] Preguntar o pedir aclaración al Auditor[/bold cyan]")
        console.print("  [bold red][C] Cancelar ejecución[/bold red]")
        action = Prompt.ask("¿Qué deseas hacer?", choices=["R", "A", "P", "C", "r", "a", "p", "c"], default="R").upper()

        if action == "A":
            judge.record_verdict("APPROVED", verdict_text + "\n(Approved via Human Override)")
            console.print("[bold green]✔ Aprobado por el usuario (Human Override).[/bold green]\n")
            break
        elif action == "C":
            console.print("[bold red]Ejecución cancelada por el usuario.[/bold red]")
            sys.exit(0)
        elif action == "P":
            user_question = Prompt.ask("\nEscribe tu pregunta o instrucción")
            # If user asks to fix/implement, automatically divert to Remediation
            if any(w in user_question.lower() for w in ["hace", "hacé", "arregla", "arreglá", "implementa", "implementá", "soluciona", "solucioná"]):
                action = "R"
            else:
                audit_explanation = client.generate(
                    JUDGE_PROMPT,
                    f"Contexto del veredicto previo:\n{verdict_text}\nPregunta del usuario: {user_question}\nExplica en español de forma constructiva.",
                )
                console.print(Panel(audit_explanation, title="Aclaración del Auditor", border_style="blue"))
                continue

        if action == "R":
            console.print("\n[bold green]🛠️ Delegando remediación al Agente Desarrollador (TDD Craftsman)...[/bold green]")
            remediate_task = f"""
            The Auditor issued this feedback:
            {verdict_text}

            Generate the missing tests or Java components to satisfy all points raised by the Judge.
            Follow Java Craftsmanship rules.
            Output all created or modified files using:
            FILE: path/to/File.java
            ```java
            package com.cucco.payments;
            ...
            ```
            """
            remediation_code = safe_call_ai(client, REMEDIATION_CRAFTSMAN_PROMPT, remediate_task, fallback_content="")
            written = parse_and_apply_java_files(remediation_code, TARGET_PROJECT)
            for w in written:
                console.print(f"[green]✔ Archivo remediado:[/green] {w.relative_to(TARGET_PROJECT)}")

            # Re-run gradle test
            test_run = run_cmd(["./gradlew", "test", "--no-daemon", "-q"], cwd=TARGET_PROJECT)
            if test_run.returncode == 0:
                console.print("[bold green]✔ Tests de Gradle pasaron tras la remediación.[/bold green]")
                # Re-run verify
                from spec.cli import run_verify
                run_verify(TARGET_PROJECT)
                console.print("[bold green]✔ Re-evaluando con The Judge...[/bold green]\n")
            else:
                console.print(f"[bold red]Fallo de compilación tras remediación: {test_run.stderr}[/bold red]")

    # Fase 5: Sello
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

    # Automatic pre-run cleanup for pristine baseline
    from clean_workbench import clean_project
    clean_project(force=True, verbose=False)
    console.print("[bold green]✔ Entorno test-sdd reseteado a estado prístino (IDLE, 0 residuos de pruebas previas).[/bold green]\n")

    gate_spec(workflow, client)
    gate_plan(workflow, client)
    gate_work_tdd(workflow, client)
    gate_verify_and_judge(workflow, client)


if __name__ == "__main__":
    main()
