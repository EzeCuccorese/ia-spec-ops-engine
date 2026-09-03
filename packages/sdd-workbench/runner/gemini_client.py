from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path


class GeminiClient:
    """Client for Google Gemini using standard library with zero external dependencies."""

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = (api_key or os.environ.get("GEMINI_API_KEY", "")).strip()
        self.model = (model or os.environ.get("GEMINI_MODEL_TARGET", "gemini-flash-latest")).strip()
        if self.model.startswith("models/"):
            self.model = self.model.replace("models/", "")

    @classmethod
    def load_env(cls, env_path: Path | str | None = None) -> GeminiClient:
        candidates = [
            Path(env_path) if env_path else None,
            Path(__file__).parent.parent / ".env",
            Path.cwd() / "packages/sdd-workbench/.env",
            Path.cwd() / ".env",
        ]
        loaded: dict[str, str] = {}
        for cand in candidates:
            if cand and cand.is_file():
                for line in cand.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        loaded[k.strip()] = v.strip().strip("'\"")
                break

        key = loaded.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY", "")
        model = loaded.get("GEMINI_MODEL_TARGET") or os.environ.get("GEMINI_MODEL_TARGET", "gemini-flash-latest")
        return cls(api_key=key, model=model)

    def generate(self, system_instruction: str, user_prompt: str) -> str:
        if not self.api_key:
            raise ValueError(
                "GEMINI_API_KEY is not set. Please provide it in packages/sdd-workbench/.env or environment."
            )

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": f"System Instructions:\n{system_instruction}\n\nTask:\n{user_prompt}"}],
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "topP": 0.95,
            },
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                candidates = data.get("candidates", [])
                if not candidates:
                    raise RuntimeError(f"No response candidates returned: {data}")
                parts = candidates[0].get("content", {}).get("parts", [])
                return "".join(part.get("text", "") for part in parts)
        except urllib.error.HTTPError as err:
            err_body = err.read().decode("utf-8")
            if "API_KEY_SERVICE_BLOCKED" in err_body or err.code == 401:
                raise RuntimeError(
                    f"Google Cloud Error (HTTP {err.code}): API_KEY_SERVICE_BLOCKED.\n"
                    "The current key is restricted in Google Cloud Console. To fix:\n"
                    "1. Go to https://aistudio.google.com/ -> Create API Key.\n"
                    "2. Put it in packages/sdd-workbench/.env as GEMINI_API_KEY=AIzaSy...\n"
                    f"Raw error: {err_body}"
                ) from err
            raise RuntimeError(f"Gemini API Error (HTTP {err.code}): {err_body}") from err
        except Exception as err:
            raise RuntimeError(f"Connection error to Gemini API: {err}") from err
