"""Responses of the real Orca CLI, copied from ``orca orchestration worker-list|worker-show
--json`` (ids, paths and the cursor shortened; keys, nesting and value kinds as observed).

Both commands answer ``{"ok": true, "result": {...}}``. ``worker-list`` has the rows under
``result.workers``, the opaque page cursor in ``result.nextCursor`` (absent on the last page)
and a ``scope``. Rows of live workers carry ``agent`` (``codex/gpt-6.1-sol``); released ones
have no ``agent``. ``worker-show`` never reports the agent.
"""

from __future__ import annotations

WORKSPACE = "440c54c1-4547-42ac-9692-3d444d12393d::/Users/dev/projects/repo"

REAL_LIST = {
    "ok": True,
    "result": {
        "workers": [
            {
                "dispatchId": "ctx_567cabb2d960",
                "taskId": "task_eff66e14abd3",
                "state": "succeeded",
                "liveness": "live",
                "agent": "codex/gpt-6.1-sol",
                "terminal": "term_660774c8-6703-4b3b-817f-505c0c3b172c",
                "terminalState": "reclaimable",
                "workspace": WORKSPACE,
                "host": "local",
                "autoReleaseAt": "2026-11-03T22:07:28Z",
            },
            {
                "dispatchId": "ctx_bdad03bd0cfe",
                "taskId": "task_befc6e3d10a1",
                "state": "succeeded",
                "liveness": "exited",
                "terminal": "term_1bc5ce25-9918-477d-acce-1d799bae8a32",
                "terminalState": "released",
                "workspace": WORKSPACE,
                "host": "local",
            },
        ],
        "scope": {"run": "run_e4d520826255", "source": "bound"},
        "nextCursor": "eyJ2ZXJzaW9uIjoyLCJzbmFwc2hvdCI6eyJkYXRhYmFzZUlkIjoxMDd9fQ",
        "warnings": [
            "Showing 2 of 14 Dispatches, newest first; more are on later pages. "
            "Follow page.nextCursor with --cursor."
        ],
    },
}

REAL_SHOW_LIVE = {
    "ok": True,
    "result": {
        "dispatchId": "ctx_567cabb2d960",
        "taskId": "task_eff66e14abd3",
        "runId": "run_e4d520826255",
        "state": "succeeded",
        "stage": "settled",
        "liveness": "live",
        "terminal": "term_660774c8-6703-4b3b-817f-505c0c3b172c",
        "terminalState": "reclaimable",
        "workspace": WORKSPACE,
        "autoReleaseAt": "2026-11-03T22:07:28Z",
    },
}

REAL_SHOW_RELEASED = {
    "ok": True,
    "result": {
        "dispatchId": "ctx_bdad03bd0cfe",
        "taskId": "task_befc6e3d10a1",
        "runId": "run_e4d520826255",
        "state": "succeeded",
        "stage": "settled",
        "liveness": "exited",
        "terminal": "term_1bc5ce25-9918-477d-acce-1d799bae8a32",
        "terminalState": "released",
        "workspace": WORKSPACE,
        "waitingOnHuman": "unknown",
    },
}
