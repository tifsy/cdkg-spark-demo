"""Central configuration (env vars / .env)."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "y")


class Settings:
    # ---- storage on the DGX Spark --------------------------------------
    DATA_DIR = Path(os.getenv("DATA_DIR", ROOT / "data")).resolve()
    RAW_DIR = DATA_DIR / "raw"          # immutable raw Media Cloud dumps (JSONL, partitioned by date)
    DB_PATH = DATA_DIR / "cdkg.db"      # structured store (articles, mentions, clusters, AI reviews)

    # ---- Media Cloud ----------------------------------------------------
    MEDIACLOUD_API_KEY = os.getenv("MEDIACLOUD_API_KEY", "")

    # ---- Local LLM on the Spark (any OpenAI-compatible server) ----------
    # Ollama: http://localhost:11434/v1   vLLM / NIM: http://localhost:8000/v1
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")   # "openai" | "mock"
    LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
    LLM_API_KEY = os.getenv("LLM_API_KEY", "ollama")
    LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:14b")
    LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "180"))
    # "0" for deterministic extraction; leave empty to use the model's default
    # (dropped automatically if the model rejects it)
    LLM_TEMPERATURE = os.getenv("LLM_TEMPERATURE", "0").strip()
    # false: an LLM error is reported as an error (no silent heuristic results)
    LLM_FALLBACK = _bool("LLM_FALLBACK", False)
    EXTRACTION_MODEL_VERSION = os.getenv("EXTRACTION_MODEL_VERSION", "")  # defaults to LLM_MODEL

    # ---- Collection review tool ----------------------------------------
    # "mock" = built-in demo queue, "live" = a running mediacloud/collection-review-tool
    CRT_MODE = os.getenv("CRT_MODE", "mock")
    CRT_BASE_URL = os.getenv("CRT_BASE_URL", "http://localhost:5000").rstrip("/")
    # Site inspector: "live" fetches homepages over HTTP, "fixture" uses bundled snapshots (offline demo)
    INSPECTOR_MODE = os.getenv("INSPECTOR_MODE", "fixture")
    INSPECTOR_BACKEND = os.getenv("INSPECTOR_BACKEND", "requests")  # "requests" | "crawl4ai"
    # Below this confidence the agent never proposes keep/remove; it proposes skip.
    REVIEW_MIN_CONFIDENCE = float(os.getenv("REVIEW_MIN_CONFIDENCE", "0.70"))

    # ---- Web server ----------------------------------------------------
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", "8080"))
    # Optional shared token for write endpoints (Tailscale already limits who can reach the box)
    APP_TOKEN = os.getenv("APP_TOKEN", "")
    # When true, the API never returns article full text (Media Cloud licensing, proposal §3.5)
    HIDE_FULLTEXT = _bool("HIDE_FULLTEXT", True)

    @property
    def model_version(self) -> str:
        return self.EXTRACTION_MODEL_VERSION or f"{self.LLM_PROVIDER}:{self.LLM_MODEL}"


settings = Settings()
settings.RAW_DIR.mkdir(parents=True, exist_ok=True)
