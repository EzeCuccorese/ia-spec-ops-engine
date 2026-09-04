"""
test_trimmer.py — Specialized test output condenser for coding agents.
Reduces green test noise by up to 95% while keeping failure traces and summary lines intact.
"""

from __future__ import annotations

import re
from typing import Any

TEST_CMD_RE = re.compile(
    r"\b(jest|vitest|mocha|ava|tap|nyc)\b"
    r"|\bpytest\b|\bnosetests?\b|\btox\b"
    r"|\bgo\s+test\b|\bcargo\s+test\b"
    r"|\brspec\b|\bminitest\b|\bphpunit\b"
    r"|\bgradle\w*\s+.*\btest\b|\bmvn\w*\s+.*\btest\b"
    r"|\bdotnet\s+test\b|\bctest\b"
    r"|\b(npm|yarn|pnpm|bun)\s+(run\s+)?test\b",
    re.IGNORECASE,
)

FAIL_MARKER_RE = re.compile(
    r"\bFAIL(ED)?\b|✕|✗|×|--- FAIL:|AssertionError|"
    r"Traceback \(most recent call last\)|panicked at|"
    r"^E\s{3}|Failures:|^Error:\s",
    re.MULTILINE,
)


class TestTrimmer:
    @staticmethod
    def is_test_command(cmd: str) -> bool:
        return bool(TEST_CMD_RE.search(cmd))

    @staticmethod
    def trim(stdout: str, cfg: dict[str, Any], reference: str = "") -> str:
        lineas = stdout.splitlines()
        n = len(lineas)
        if n == 0:
            return stdout

        tail_n = min(cfg.get("test_tail_lineas", 15), n)
        inicio_resumen = n - tail_n
        resumen_final = lineas[inicio_resumen:]

        indices_falla = [
            i for i, l in enumerate(lineas[:inicio_resumen]) if FAIL_MARKER_RE.search(l)
        ]

        partes = []
        if not indices_falla:
            head_n = min(cfg.get("test_head_lineas", 3), inicio_resumen)
            partes.append("\n".join(lineas[:head_n]))
            omitidas = inicio_resumen - head_n
            if omitidas > 0:
                partes.append(f"[... {omitidas} lines of green test output omitted for frugality ...]")
            anterior_fin = inicio_resumen - 1
        else:
            antes = cfg.get("test_contexto_antes", 3)
            despues = cfg.get("test_contexto_despues", 30)
            bloques: list[tuple[int, int]] = []
            for i in indices_falla:
                ini, fin = max(0, i - antes), min(inicio_resumen - 1, i + despues)
                if bloques and ini <= bloques[-1][1] + 1:
                    bloques[-1] = (bloques[-1][0], max(bloques[-1][1], fin))
                else:
                    bloques.append((ini, fin))

            anterior_fin = -1
            for ini, fin in bloques:
                omitidas = ini - anterior_fin - 1
                if omitidas > 0:
                    partes.append(f"[... {omitidas} test output lines omitted ...]")
                partes.append("\n".join(lineas[ini : fin + 1]))
                anterior_fin = fin

        if inicio_resumen > anterior_fin + 1:
            omitidas = inicio_resumen - anterior_fin - 1
            if omitidas > 0:
                partes.append(f"[... {omitidas} lines omitted ...]")

        partes.append("\n".join(resumen_final))

        result = "\n\n".join(partes)
        if reference:
            result += f"\n\n{reference}"
        return result
