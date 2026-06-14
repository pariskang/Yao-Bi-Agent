"""YaoBi-Skill HTTP server: serves the static UI **and** the genuine Tao-in-the-loop API.

This is the bridge the static frontend was missing. The browser UI calls these JSON
endpoints, so the language model **actually** drives skill selection (constrained
function-calling), multi-step planning, rule-bounded follow-up probes, and the
reasoning/experience agents — instead of the client-side keyword stubs.

Safety invariants are unchanged and enforced server-side: the model only *selects /
sequences / rewrites* registered skills; clinical content comes from deterministic rules
and de-identified mined data; patient requests for final diagnosis / prescription / dose
are blocked by ``patient_request_guard_skill``; Tao output passes JSON repair + output
guard and falls back to rules on any violation.

Zero extra dependencies (stdlib ``http.server`` only). The Tao runtime is selected purely
through environment variables consumed by ``DaoClient`` (``TAO_BACKEND``, ``TAO_MODEL_ID``,
``TAO_LOAD_IN_4BIT`` …), so the same server runs with mock, an HTTP endpoint, or a local
``transformers`` model such as ``CMLM/Dao1-30b-a3b``.
"""

from __future__ import annotations

import argparse
import http.server
import json
import time
from pathlib import Path
from typing import Any

from backend.agents.autonomous_agent import AutonomousQAAgent
from backend.agents.conversation import ConversationSession
from backend.agents.orchestrator import AgentOrchestrator
from backend.agents.skill_router import suggested_questions
from backend.llm.dao_client import DaoClient, DaoRuntimeError
from backend.skills.case_extract_skill import case_extract_skill
from backend.skills.case_normalize_skill import case_normalize_skill
from backend.skills.mined_evidence_skill import load_mined_rules
from backend.skills.tao_followup_probe_skill import tao_followup_probe_skill

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT / "frontend"

# Shared, process-wide client (the heavy transformers model is cached on the class).
CLIENT = DaoClient()
TAO_ENABLED = CLIENT.config.backend in {"mock", "http", "transformers"}

# Map frontend intake stages to FSM states and the fields Tao may hint at (must mirror the
# allowed fields so a generated probe cannot drive a state jump or invent a new field).
STAGE_TO_STATE = {
    "pain": "S3_PAIN_PROFILE",
    "neuro": "S4_NEURO_ORTHO",
    "tcm": "S5_TCM_CORE",
    "comorbidity": "S7_COMORBIDITY",
}
STAGE_FIELDS = {
    "pain": ["location", "radiation", "pain_nature", "severity", "aggravating", "relieving"],
    "neuro": ["numbness", "numbness_location", "weakness", "walking_limitation", "imaging", "western_diagnosis"],
    "tcm": ["cold_heat", "cold_relation", "dampness", "sleep", "appetite", "mouth_taste", "tongue_color", "tongue_coating"],
    "comorbidity": ["diseases", "medications", "anticoagulant", "allergy"],
}


def tao_info() -> dict[str, Any]:
    c = CLIENT.config
    return {
        "enabled": TAO_ENABLED,
        "backend": c.backend,
        "model_id": c.model_id,
        "quantization": "4bit" if c.load_in_4bit else "8bit" if c.load_in_8bit else "none",
    }


def _case_state(data: dict[str, Any]) -> dict[str, Any]:
    """Bridge the frontend's computed tags into the backend case_state shape."""

    red = data.get("red_flags") or {}
    return {
        "normalized_tags": list(data.get("tags") or []),
        "red_flags": {"status": red.get("status"), "positive_items": list(red.get("positive_items") or [])},
        "neuro_ortho": data.get("neuro_ortho") or {},
        "comorbidity": data.get("comorbidity") or {},
    }


def _role(data: dict[str, Any]) -> str:
    return "clinician" if data.get("doctor_mode", True) else "patient"


def _enrich_with_question(data: dict[str, Any], question: str) -> dict[str, Any]:
    """Extract structured tags from the free-text question and merge with intake tags.

    This lets the chat answer a typed clinical description (e.g. "腰痛、下肢麻木、遇冷加重、
    舌暗苔白腻") with real rule-engine candidates, instead of only the questionnaire tags.
    Extraction stays deterministic; the language model still only selects which skill runs.
    """

    merged = dict(data)
    try:
        case_json = case_extract_skill(question)
        extracted = case_normalize_skill(case_json).get("normalized_tags") or []
        merged["tags"] = sorted(set(data.get("tags") or []) | set(extracted))
        red = dict(data.get("red_flags") or {})
        rf_items = list(red.get("positive_items") or []) + list(case_json.get("red_flags") or [])
        if rf_items:
            red["positive_items"] = sorted(set(rf_items))
            red.setdefault("status", "caution")
        merged["red_flags"] = red
    except Exception:
        pass  # never let extraction break the request; fall back to provided tags
    return merged


# --------------------------------------------------------------------------- handlers
def handle_health(_data: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, "tao": tao_info(), "mined_loaded": bool(load_mined_rules()), "service": "yaobi-skill"}


def handle_starters(_data: dict[str, Any]) -> dict[str, Any]:
    return {"starters": suggested_questions(), "tao": tao_info()}


def handle_chat(data: dict[str, Any]) -> dict[str, Any]:
    question = str(data.get("question") or "").strip()
    if not question:
        return {"error": "empty question"}
    session = ConversationSession(case_state=_case_state(_enrich_with_question(data, question)), use_llm=TAO_ENABLED, dao_client=CLIENT, user_role=_role(data))
    return {"turn": session.ask(question), "tao": tao_info()}


def handle_autonomous(data: dict[str, Any]) -> dict[str, Any]:
    question = str(data.get("question") or "").strip()
    if not question:
        return {"error": "empty question"}
    agent = AutonomousQAAgent(case_state=_case_state(_enrich_with_question(data, question)), use_llm=TAO_ENABLED, dao_client=CLIENT, user_role=_role(data))
    return {"turn": agent.run(question), "tao": tao_info()}


def handle_followup_probe(data: dict[str, Any]) -> dict[str, Any]:
    stage = str(data.get("stage") or "")
    state = STAGE_TO_STATE.get(stage)
    if not state:
        return {"probes": [], "tao_probe_runtime": {"enabled": TAO_ENABLED, "status": "not_applicable"}, "tao": tao_info()}
    cs = _case_state(data)
    result = tao_followup_probe_skill(
        cs,
        state,
        STAGE_FIELDS.get(stage, []),
        rule_context={"normalized_tags": cs["normalized_tags"], "stage": stage},
        last_answers=data.get("last_answers") or {},
        max_probes=int(data.get("budget", 2) or 2),
        dao_client=CLIENT,
        use_llm=TAO_ENABLED,
    )
    result["tao"] = tao_info()
    return result


def handle_reasoning(data: dict[str, Any]) -> dict[str, Any]:
    session = ConversationSession(case_state=_case_state(data), use_llm=TAO_ENABLED, dao_client=CLIENT, user_role=_role(data))
    return {"result": session.invoke("reasoning_inquiry"), "tao": tao_info()}


def handle_summary(data: dict[str, Any]) -> dict[str, Any]:
    session = ConversationSession(case_state=_case_state(data), use_llm=TAO_ENABLED, dao_client=CLIENT, user_role=_role(data))
    return {"result": session.invoke("experience_inquiry"), "tao": tao_info()}


def handle_collaboration(data: dict[str, Any]) -> dict[str, Any]:
    result = AgentOrchestrator().run(_case_state(data), use_llm=TAO_ENABLED, dao_client=CLIENT)
    result.pop("blackboard", None)  # internal working memory, not needed by the UI
    result["tao"] = tao_info()
    return result


def handle_warmup(_data: dict[str, Any]) -> dict[str, Any]:
    if not TAO_ENABLED or CLIENT.config.backend == "disabled":
        return {"ok": False, "reason": "Tao backend disabled (set TAO_BACKEND).", "tao": tao_info()}
    started = time.time()
    try:
        reply = CLIENT.chat([], "请用一句话说明你在本系统中的角色边界。")
    except DaoRuntimeError as exc:
        return {"ok": False, "reason": str(exc), "tao": tao_info()}
    return {"ok": True, "ms": int((time.time() - started) * 1000), "reply_preview": str(reply)[:160], "tao": tao_info()}


ROUTES_GET = {"/api/health": handle_health, "/api/starters": handle_starters}
ROUTES_POST = {
    "/api/chat": handle_chat,
    "/api/autonomous": handle_autonomous,
    "/api/followup_probe": handle_followup_probe,
    "/api/reasoning": handle_reasoning,
    "/api/summary": handle_summary,
    "/api/collaboration": handle_collaboration,
    "/api/warmup": handle_warmup,
}


class Handler(http.server.SimpleHTTPRequestHandler):
    """Serves /api/* as JSON and everything else as static files from frontend/."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    def log_message(self, fmt: str, *args: Any) -> None:  # keep Colab output quiet
        pass

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.end_headers()

    def _send_json(self, obj: Any, status: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            parsed = json.loads(raw.decode("utf-8"))
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        handler = ROUTES_GET.get(path)
        if handler is not None:
            self._dispatch(handler, {})
            return
        super().do_GET()

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        handler = ROUTES_POST.get(path)
        if handler is None:
            self._send_json({"error": f"unknown endpoint {path}"}, status=404)
            return
        self._dispatch(handler, self._read_json())

    def _dispatch(self, handler: Any, data: dict[str, Any]) -> None:
        try:
            self._send_json(handler(data))
        except Exception as exc:  # never crash the UI; surface a JSON error
            self._send_json({"error": f"{type(exc).__name__}: {exc}"}, status=500)


def make_server(port: int = 8000, host: str = "0.0.0.0") -> http.server.ThreadingHTTPServer:
    return http.server.ThreadingHTTPServer((host, port), Handler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the YaoBi-Skill UI + Tao-in-the-loop API")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()
    httpd = make_server(args.port, args.host)
    info = tao_info()
    print(f"YaoBi-Skill server on http://{args.host}:{args.port}  (frontend: {FRONTEND_DIR})")
    print(f"Tao runtime: enabled={info['enabled']} backend={info['backend']} model={info['model_id']} quant={info['quantization']}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()


if __name__ == "__main__":
    main()
