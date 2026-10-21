"""Thin client for a local, OpenAI-compatible LLM server on the DGX Spark.

Works with Ollama (`/v1`), vLLM, SGLang, llama.cpp server or NVIDIA NIM, and also with
hosted OpenAI-compatible APIs such as https://api.openai.com/v1 (set LLM_API_KEY).
No vendor SDK needed: plain HTTP via `requests`.

If LLM_PROVIDER=mock, the caller-supplied heuristic is used (labelled
model_version="heuristic"). If the server fails, the call raises an error,
unless LLM_FALLBACK=true, in which case the heuristic is used and labelled
"heuristic-fallback".
"""
import json
import logging
import re
from typing import Callable

import requests

from .config import settings

log = logging.getLogger("llm")

_THINK = re.compile(r"<think>.*?</think>", re.S)


def _parse_json(text: str) -> dict:
    text = _THINK.sub("", text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise
        return json.loads(m.group(0))


def health() -> dict:
    if settings.LLM_PROVIDER == "mock":
        return {"ok": True, "provider": "mock", "model": "heuristic"}
    try:
        r = requests.get(f"{settings.LLM_BASE_URL}/models",
                         headers={"Authorization": f"Bearer {settings.LLM_API_KEY}"}, timeout=5)
        r.raise_for_status()
        models = [m.get("id") for m in r.json().get("data", [])]
        return {"ok": settings.LLM_MODEL in models or not models, "provider": "openai-compatible",
                "base_url": settings.LLM_BASE_URL, "model": settings.LLM_MODEL, "available": models}
    except Exception as e:
        return {"ok": False, "provider": "openai-compatible", "base_url": settings.LLM_BASE_URL,
                "model": settings.LLM_MODEL, "error": str(e)}


def chat_json(system: str, user: str, fallback: Callable[[], dict] | None = None,
              temperature: float = 0.0) -> tuple[dict, str]:
    """Return (parsed_json, model_version)."""
    if settings.LLM_PROVIDER == "mock":
        if not fallback:
            raise RuntimeError("LLM_PROVIDER=mock but no heuristic fallback provided")
        return fallback(), "heuristic"

    payload = {
        "model": settings.LLM_MODEL,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
    }
    if settings.LLM_TEMPERATURE != "":
        payload["temperature"] = float(settings.LLM_TEMPERATURE)
    last_err = None
    for attempt in range(3):
        try:
            r = requests.post(f"{settings.LLM_BASE_URL}/chat/completions", json=payload,
                              headers={"Authorization": f"Bearer {settings.LLM_API_KEY}"},
                              timeout=settings.LLM_TIMEOUT)
            if r.status_code == 400 and "temperature" in r.text and "temperature" in payload:
                # some hosted reasoning models (e.g. GPT-5 family) only accept the default temperature
                log.info("Model rejected temperature; retrying without it")
                payload.pop("temperature")
                continue
            if r.status_code >= 400:
                raise requests.HTTPError(f"HTTP {r.status_code}: {r.text[:300]}")
            content = r.json()["choices"][0]["message"]["content"]
            return _parse_json(content), settings.model_version
        except (requests.RequestException, KeyError) as e:
            last_err = e
            break                       # server/auth problem: retrying won't help
        except json.JSONDecodeError as e:
            last_err = e                # bad JSON: retry once with a nudge
            payload["messages"].append({"role": "user",
                                        "content": "Return ONLY one valid JSON object."})
    if fallback and settings.LLM_FALLBACK:
        log.warning("LLM call failed, using heuristic fallback: %s", last_err)
        return fallback(), "heuristic-fallback"
    raise RuntimeError(f"LLM call failed: {last_err}")
