from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path


class GeminiClient:
    """Enterprise Gemini Client supporting ADC (Application Default Credentials) via Agent Platform
    and API Key via Google AI Studio.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        use_adc: bool = True,
        project_id: str | None = None,
        location: str = "global",
    ) -> None:
        self.api_key = (api_key or os.environ.get("GEMINI_API_KEY", "")).strip()
        self.model = (model or os.environ.get("GEMINI_MODEL_TARGET", "gemini-flash-latest")).strip()
        if self.model.startswith("models/"):
            self.model = self.model.replace("models/", "")

        self.use_adc = use_adc
        self.project_id = (project_id or os.environ.get("GCP_PROJECT_ID", "")).strip()
        self.location = (location or os.environ.get("GCP_LOCATION", "global")).strip()

        # If project_id not set, attempt to read from gcloud
        if not self.project_id and self.use_adc:
            try:
                self.project_id = (
                    subprocess.check_output(
                        ["gcloud", "config", "get-value", "project"],
                        stderr=subprocess.DEVNULL,
                    )
                    .decode()
                    .strip()
                )
            except Exception:
                self.project_id = ""

    @classmethod
    def load_env(cls, env_path: Path | str | None = None) -> GeminiClient:
        candidates = [
            Path(env_path) if env_path else None,
            Path(__file__).parent.parent / ".env",
            Path.cwd() / "packages/spec/workbench/.env",
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
        model = loaded.get("GEMINI_MODEL_TARGET") or os.environ.get(
            "GEMINI_MODEL_TARGET", "gemini-flash-latest"
        )
        project_id = loaded.get("GCP_PROJECT_ID") or os.environ.get("GCP_PROJECT_ID", "")
        location = loaded.get("GCP_LOCATION") or os.environ.get("GCP_LOCATION", "global")
        use_adc_val = (
            loaded.get("USE_AGENT_PLATFORM") or loaded.get("USE_VERTEX_AI", "true")
        ).lower() in ("true", "1", "yes")

        return cls(
            api_key=key,
            model=model,
            use_adc=use_adc_val,
            project_id=project_id,
            location=location,
        )

    def _get_adc_token(self) -> str:
        # Try application-default first, then print-access-token
        for cmd in [
            ["gcloud", "auth", "application-default", "print-access-token"],
            ["gcloud", "auth", "print-access-token"],
        ]:
            try:
                token = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()
                if token and token.startswith("ya29."):
                    return token
            except Exception:
                continue
        raise RuntimeError(
            "ADC token not available. Please run: 'gcloud auth application-default login'"
        )

    def generate(
        self, system_instruction: str, user_prompt: str, history: list[dict[str, str]] | None = None
    ) -> str:
        """Call Gemini model via Agent Platform (ADC) or Google AI Studio (API Key)."""
        contents = []

        # System instruction as initial developer/user context
        system_text = f"System Instructions:\n{system_instruction}\n"
        if history:
            for item in history:
                role = "user" if item.get("role") == "user" else "model"
                contents.append({"role": role, "parts": [{"text": item.get("content", "")}]})

        # Add current user prompt
        contents.append(
            {
                "role": "user",
                "parts": [{"text": f"{system_text}\nTask:\n{user_prompt}"}],
            }
        )

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": 0.1,
                "topP": 0.95,
            },
        }

        # Route 1: Agent Platform with ADC
        if self.use_adc and self.project_id:
            token = self._get_adc_token()
            if self.location == "global":
                url = f"https://aiplatform.googleapis.com/v1/projects/{self.project_id}/locations/global/publishers/google/models/{self.model}:generateContent"
            else:
                url = f"https://{self.location}-aiplatform.googleapis.com/v1/projects/{self.project_id}/locations/{self.location}/publishers/google/models/{self.model}:generateContent"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            }
        # Route 2: Google AI Studio with API Key
        elif self.api_key:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
            headers = {"Content-Type": "application/json"}
        else:
            raise ValueError(
                "Neither ADC (gcloud auth application-default login) nor GEMINI_API_KEY is configured."
            )

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                candidates = data.get("candidates", [])
                if not candidates:
                    raise RuntimeError(f"No candidates returned: {data}")
                parts = candidates[0].get("content", {}).get("parts", [])
                return "".join(part.get("text", "") for part in parts)
        except urllib.error.HTTPError as err:
            err_body = err.read().decode("utf-8")
            raise RuntimeError(f"Gemini API Error (HTTP {err.code}): {err_body}") from err
        except Exception as err:
            raise RuntimeError(f"Connection error to Gemini: {err}") from err
