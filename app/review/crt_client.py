"""Client for mediacloud/collection-review-tool's reviewer-queue API.

Endpoints used (backend/routes/api.py):
  GET  /api/review-queues/<guid>                       queue + stats
  GET  /api/review-queues/<guid>/guidelines            rendered markdown guidelines
  GET  /api/review-queues/<guid>/items?decision=...    items (paginated)
  POST /api/review-queues/<guid>/items/<id>/decide     {"decision", "removal_reason"?, "skip_note"?}

The AI never calls `decide` by itself: only the human approval step does.
"""
import json
from pathlib import Path

import requests

from ..config import settings
from .fixtures import MOCK_QUEUE, MOCK_QUEUE_GUID

DEFAULT_GUIDELINES = (Path(__file__).parent / "default_guidelines.md").read_text(encoding="utf-8")


class LiveCRT:
    def __init__(self, base_url: str | None = None):
        self.base = (base_url or settings.CRT_BASE_URL).rstrip("/") + "/api"

    def _get(self, path, **params):
        r = requests.get(self.base + path, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def queue(self, guid: str) -> dict:
        return self._get(f"/review-queues/{guid}")["review"]

    def guidelines(self, guid: str) -> str:
        try:
            return self._get(f"/review-queues/{guid}/guidelines").get("guidelines") or DEFAULT_GUIDELINES
        except requests.RequestException:
            return DEFAULT_GUIDELINES

    def items(self, guid: str, decision: str | None = "undecided", limit: int = 500) -> list[dict]:
        out, page = [], 1
        while len(out) < limit:
            params = {"page": page, "page_size": 100}
            if decision:
                params["decision"] = decision
            data = self._get(f"/review-queues/{guid}/items", **params)
            out += data["items"]
            if len(out) >= data["total"] or not data["items"]:
                break
            page += 1
        return out[:limit]

    def decide(self, guid: str, item_id: int, decision: str, removal_reason: str | None = None,
               skip_note: str | None = None) -> dict:
        body = {"decision": decision}
        if decision == "remove":
            body["removal_reason"] = removal_reason or "Removed after AI-assisted human review"
        if decision == "skip" and skip_note:
            body["skip_note"] = skip_note
        r = requests.post(f"{self.base}/review-queues/{guid}/items/{item_id}/decide", json=body, timeout=30)
        if r.status_code >= 400:
            raise RuntimeError(f"collection-review-tool returned {r.status_code}: {r.text[:300]}")
        return r.json()


class MockCRT:
    """In-process stand-in so Task 2 can be demoed without the review tool running."""
    state_file = settings.DATA_DIR / "mock_crt_decisions.json"

    def _state(self) -> dict:
        return json.loads(self.state_file.read_text()) if self.state_file.exists() else {}

    def queue(self, guid: str) -> dict:
        st = self._state()
        return {"queue_guid": MOCK_QUEUE_GUID, "name": "Sudan - National (demo) - Queue 1",
                "collection_id": 34412379, "undecided_count": sum(1 for i in MOCK_QUEUE if str(i["id"]) not in st),
                "stats": {"total": len(MOCK_QUEUE)}}

    def guidelines(self, guid: str) -> str:
        return DEFAULT_GUIDELINES

    def items(self, guid: str, decision: str | None = "undecided", limit: int = 500) -> list[dict]:
        st = self._state()
        out = []
        for it in MOCK_QUEUE:
            d = st.get(str(it["id"]), {}).get("decision", "undecided")
            if decision is None or d == decision:
                out.append({**it, "decision": d, "is_new_source": False})
        return out[:limit]

    def decide(self, guid, item_id, decision, removal_reason=None, skip_note=None) -> dict:
        if decision == "remove" and not removal_reason:
            raise RuntimeError('removal_reason is required when decision is "remove"')
        st = self._state()
        st[str(item_id)] = {"decision": decision, "removal_reason": removal_reason, "skip_note": skip_note}
        self.state_file.write_text(json.dumps(st, indent=2))
        return {"id": item_id, "decision": decision}

    def reset(self):
        self.state_file.unlink(missing_ok=True)


def get_client():
    return LiveCRT() if settings.CRT_MODE == "live" else MockCRT()
