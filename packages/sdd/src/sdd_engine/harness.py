"""
sdd_engine.harness — Arnés de ejecución multi-agente y orquestador de tareas SDD.
"""

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Dict, Any, Iterable, Union

from sdd_engine.utils import run_command_safe
from sdd_engine import memory, feature, verify
from sdd_engine.invariants import (
    HarnessConfig,
    TaskResult,
    VerificationPayload,
    calculate_scope_drift_penalty,
    DEFAULT_MAX_STEPS,
    DEFAULT_DRIFT_PENALTY_THRESHOLD,
)



@dataclass
class SDDTask:
    id: str
    description: str
    completed: bool
    line_number: int


def get_tasks_file(feature_name: Optional[str] = None, target_dir: str = ".") -> Optional[Path]:
    td = memory.get_project_dir(target_dir)
    feat = feature_name or feature.get_active_feature(td)
    
    if feat:
        spec_tasks = td / ".specify" / "specs" / feat / "tasks.md"
        if spec_tasks.exists():
            return spec_tasks
            
    # Fallback to finding any tasks.md
    found = list((td / ".specify" / "specs").glob("**/tasks.md"))
    if found:
        return found[0]
        
    return None


def parse_tasks(tasks_file: Optional[Path]) -> List[SDDTask]:
    if not tasks_file or not tasks_file.exists():
        return []
        
    lines = tasks_file.read_text().splitlines()

    tasks = []
    task_counter = 1
    
    for idx, line in enumerate(lines, start=1):
        match = re.match(r"^\s*-\s*\[([ xX])\]\s*(.+)$", line)
        if match:
            is_completed = match.group(1).lower() == "x"
            desc = match.group(2).strip()
            
            # Extract task ID if present e.g. T1: or 1.1 -
            id_match = re.match(r"^([A-Za-z0-9\.\-]+)[\:\-]\s*(.+)$", desc)
            if id_match:
                task_id = id_match.group(1)
            else:
                task_id = f"task-{task_counter:02d}"
                task_counter += 1
                
            tasks.append(SDDTask(
                id=task_id,
                description=desc,
                completed=is_completed,
                line_number=idx
            ))
            
    return tasks


def get_next_pending_task(tasks_file: Path) -> Optional[SDDTask]:
    tasks = parse_tasks(tasks_file)
    for t in tasks:
        if not t.completed:
            return t
    return None


def mark_task_completed(tasks_file: Path, task: SDDTask) -> bool:
    if not tasks_file.exists():
        return False
        
    lines = tasks_file.read_text().splitlines()
    if 1 <= task.line_number <= len(lines):
        line = lines[task.line_number - 1]
        lines[task.line_number - 1] = re.sub(r"\[\s*\]", "[x]", line, count=1)
        tasks_file.write_text("\n".join(lines) + "\n")
        return True
    return False


def build_task_context(task: SDDTask, feature_name: Optional[str] = None, target_dir: str = ".") -> Dict[str, Any]:
    td = memory.get_project_dir(target_dir)
    feat = feature_name or feature.get_active_feature(td)
    spec_dir = td / ".specify" / "specs" / feat if feat else None
    
    context = {
        "task_id": task.id,
        "description": task.description,
        "feature_name": feat or "default",
        "spec_summary": "",
        "checklist_summary": "",
        "memory_summary": "",
    }
    
    if spec_dir and spec_dir.exists():
        spec_md = spec_dir / "spec.md"
        if spec_md.exists():
            # Include first 100 lines of spec for context
            spec_lines = spec_md.read_text().splitlines()[:100]
            context["spec_summary"] = "\n".join(spec_lines)
            
        chk_md = spec_dir / "checklist.md"
        if chk_md.exists():
            context["checklist_summary"] = chk_md.read_text()
            
    mem_md = td / ".specify" / "memory.md"
    if mem_md.exists():
        mem_lines = mem_md.read_text().splitlines()[:50]
        context["memory_summary"] = "\n".join(mem_lines)
        
    return context


class HarnessSession:
    def __init__(
        self,
        feature_name: Optional[str] = None,
        max_retries: int = 3,
        target_dir: str = ".",
        config: Optional[HarnessConfig] = None,
    ):
        self.target_dir = memory.get_project_dir(target_dir)
        self.feature_name = feature_name or feature.get_active_feature(self.target_dir)
        self.max_retries = max_retries
        self.tasks_file = get_tasks_file(self.feature_name, self.target_dir)
        self.config = config or HarnessConfig()
        self.executed_steps = 0

    def increment_steps(self, count: int = 1) -> int:
        self.executed_steps += count
        return self.executed_steps

    def reset_steps(self) -> None:
        self.executed_steps = 0

    def status(self) -> Dict[str, Any]:
        tasks = parse_tasks(self.tasks_file)
        completed = [t for t in tasks if t.completed]
        pending = [t for t in tasks if not t.completed]
        return {
            "feature": self.feature_name or "None",
            "tasks_file": str(self.tasks_file) if self.tasks_file else "None",
            "total_tasks": len(tasks),
            "completed_tasks": len(completed),
            "pending_tasks": len(pending),
            "next_task": pending[0] if pending else None,
            "executed_steps": self.executed_steps,
            "config": self.config.to_dict(),
        }

    def run_next(self) -> Dict[str, Any]:
        next_task = get_next_pending_task(self.tasks_file)
        if not next_task:
            return {
                "status": "ALL_COMPLETED",
                "message": "All tasks in tasks.md are completed."
            }
            
        ctx = build_task_context(next_task, self.feature_name, self.target_dir)
        
        # Log Leader Dispatch event
        memory.log_task_event(
            task_id=next_task.id,
            role="leader",
            title=f"Dispatched task: {next_task.description}",
            details=(
                f"Feature: {self.feature_name}\n"
                f"Task ID: {next_task.id}\n"
                f"Max Retries: {self.max_retries}\n"
                f"Max Steps: {self.config.max_steps}\n"
                f"Drift Penalty Threshold: {self.config.drift_penalty_threshold}"
            ),
            status="DISPATCHED",
            target_dir=self.target_dir,
        )
        
        return {
            "status": "TASK_DISPATCHED",
            "task": next_task,
            "context": ctx,
            "max_retries": self.max_retries,
            "max_steps": self.config.max_steps,
            "drift_penalty_threshold": self.config.drift_penalty_threshold,
            "executed_steps": self.executed_steps,
        }

    def verify_task(
        self,
        modified_files: Optional[List[Union[str, Path]]] = None,
        get_check_url: Optional[str] = None,
        run_tests: bool = True,
        run_linter: bool = True,
        run_get_check_flag: bool = True,
        run_security: bool = True,
    ) -> VerificationPayload:
        """
        Executes unified automated verification suite (verify.py) on target_dir.
        """
        return verify.run_verification(
            target_dir=str(self.target_dir),
            modified_files=modified_files,
            get_check_url=get_check_url,
            run_tests=run_tests,
            run_linter=run_linter,
            run_get_check_flag=run_get_check_flag,
            run_security=run_security,
        )

    def evaluate_task_execution(
        self,
        task_id: str,
        role: str = "WORKER",
        summary: str = "",
        details: str = "",
        executed_steps: Optional[int] = None,
        modified_files: Optional[Iterable[Union[str, Path]]] = None,
        expected_files: Optional[Iterable[Union[str, Path]]] = None,
        scope_drift_penalty: Optional[float] = None,
        verification_payload: Optional[VerificationPayload] = None,
        auto_verify: bool = False,
    ) -> TaskResult:
        if executed_steps is not None:
            self.executed_steps = executed_steps

        steps = self.executed_steps

        if scope_drift_penalty is not None:
            drift_penalty = scope_drift_penalty
        else:
            drift_penalty = calculate_scope_drift_penalty(
                modified_files=modified_files or [],
                expected_files=expected_files or [],
                executed_steps=steps,
                max_steps=self.config.max_steps,
            )

        if auto_verify and verification_payload is None:
            mod_list = [Path(f) for f in modified_files] if modified_files else None
            verification_payload = self.verify_task(modified_files=mod_list)

        if steps > self.config.max_steps or drift_penalty > self.config.drift_penalty_threshold:
            status = "REMEDIATION_REQUIRED"
        elif verification_payload is not None and not verification_payload.passed:
            status = "FAIL" if role.upper() == "QA" else "REMEDIATION_REQUIRED"
        else:
            status = "PASS" if role.upper() == "QA" else "SUCCESS"

        return TaskResult(
            task_id=task_id,
            role=role.upper(),
            status=status,
            executed_steps=steps,
            scope_drift_penalty=drift_penalty,
            summary=summary,
            details=details,
        )

    def record_worker_result(
        self,
        task_id: str,
        summary: str,
        details: str,
        status: str = "SUCCESS",
        executed_steps: Optional[int] = None,
        modified_files: Optional[Iterable[Union[str, Path]]] = None,
        expected_files: Optional[Iterable[Union[str, Path]]] = None,
        scope_drift_penalty: Optional[float] = None,
        verification_payload: Optional[VerificationPayload] = None,
        auto_verify: bool = False,
    ) -> Path:
        eval_result = self.evaluate_task_execution(
            task_id=task_id,
            role="WORKER",
            summary=summary,
            details=details,
            executed_steps=executed_steps,
            modified_files=modified_files,
            expected_files=expected_files,
            scope_drift_penalty=scope_drift_penalty,
            verification_payload=verification_payload,
            auto_verify=auto_verify,
        )

        final_status = eval_result.status if eval_result.status in ("REMEDIATION_REQUIRED", "FAIL") else status

        full_details = (
            f"Summary: {summary}\n\n"
            f"Executed Steps: {eval_result.executed_steps} / {self.config.max_steps}\n"
            f"Scope Drift Penalty: {eval_result.scope_drift_penalty:.4f} (threshold: {self.config.drift_penalty_threshold})\n"
        )

        if verification_payload is not None:
            full_details += (
                f"Verification Passed: {verification_payload.passed}\n"
                f"Linter: {verification_payload.linter_status} | Tests: {verification_payload.test_status} | GET: {verification_payload.confirmation_read_status} | Security: {verification_payload.security_status}\n"
            )
            if verification_payload.remediation_instructions:
                full_details += f"Remediation: {verification_payload.remediation_instructions}\n"

        full_details += f"\n{details}"

        return memory.log_task_event(
            task_id=task_id,
            role="worker",
            title=f"Worker implementation for {task_id}",
            details=full_details,
            status=final_status,
            target_dir=self.target_dir,
        )

    def record_qa_result(
        self,
        task_id: str,
        summary: str,
        details: str,
        passed: bool,
        executed_steps: Optional[int] = None,
        modified_files: Optional[Iterable[Union[str, Path]]] = None,
        expected_files: Optional[Iterable[Union[str, Path]]] = None,
        scope_drift_penalty: Optional[float] = None,
        verification_payload: Optional[VerificationPayload] = None,
        auto_verify: bool = False,
        auto_commit: bool = True,
    ) -> Path:
        if auto_verify and verification_payload is None:
            mod_list = [Path(f) for f in modified_files] if modified_files else None
            verification_payload = self.verify_task(modified_files=mod_list)

        if verification_payload is not None and not verification_payload.passed:
            passed = False

        eval_result = self.evaluate_task_execution(
            task_id=task_id,
            role="QA",
            summary=summary,
            details=details,
            executed_steps=executed_steps,
            modified_files=modified_files,
            expected_files=expected_files,
            scope_drift_penalty=scope_drift_penalty,
            verification_payload=verification_payload,
        )

        if eval_result.status in ("REMEDIATION_REQUIRED", "FAIL"):
            status_str = eval_result.status
            passed = False
        else:
            status_str = "PASS" if passed else "FAIL"

        full_details = (
            f"Summary: {summary}\n\n"
            f"Executed Steps: {eval_result.executed_steps} / {self.config.max_steps}\n"
            f"Scope Drift Penalty: {eval_result.scope_drift_penalty:.4f} (threshold: {self.config.drift_penalty_threshold})\n"
        )

        if verification_payload is not None:
            full_details += (
                f"Verification Passed: {verification_payload.passed}\n"
                f"Linter: {verification_payload.linter_status} | Tests: {verification_payload.test_status} | GET: {verification_payload.confirmation_read_status} | Security: {verification_payload.security_status}\n"
            )
            if verification_payload.remediation_instructions:
                full_details += f"Remediation: {verification_payload.remediation_instructions}\n"

        full_details += f"\n{details}"

        log_path = memory.log_task_event(
            task_id=task_id,
            role="qa",
            title=f"QA Validation for {task_id}",
            details=full_details,
            status=status_str,
            target_dir=self.target_dir,
        )

        if passed:
            tasks = parse_tasks(self.tasks_file)
            target = next((t for t in tasks if t.id == task_id), None)
            if target:
                mark_task_completed(self.tasks_file, target)
                task_desc = target.description
            else:
                task_desc = summary or details or "completed"

            if auto_commit:
                self.commit_task_completion(task_id=task_id, description=task_desc)

        return log_path

    def commit_task_completion(self, task_id: str, description: str) -> Optional[str]:
        """
        Executes an Aider-style automatic git commit when QA validates a task with passed=True.
        Formats commit message as: `sdd(task): complete <task_id> - <description>`
        Returns stdout of commit command, or None if git commit failed or no changes staged.
        """
        clean_desc = description.strip()
        clean_desc = re.sub(rf"^(?:task-?\d+|{re.escape(task_id)})[:\-\s]*", "", clean_desc, flags=re.IGNORECASE).strip()
        if not clean_desc:
            clean_desc = description.strip()

        commit_msg = f"sdd(task): complete {task_id} - {clean_desc}"

        git_env = os.environ.copy()
        git_env.update({"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"})

        code_add, out_add, err_add = run_command_safe(["git", "add", "-A"], cwd=str(self.target_dir), env=git_env)
        if code_add != 0:
            return None

        code_st, out_st, _ = run_command_safe(["git", "status", "--porcelain"], cwd=str(self.target_dir), env=git_env)
        if code_st != 0 or not out_st.strip():
            return None

        code_commit, out_commit, err_commit = run_command_safe(
            ["git", "-c", "user.name=SDD Agent", "-c", "user.email=sdd@devscripts.local", "-c", "commit.gpgsign=false", "commit", "-m", commit_msg],
            cwd=str(self.target_dir),
            env=git_env,
        )
        if code_commit == 0:
            return out_commit.strip()
        return None
