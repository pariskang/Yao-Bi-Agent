"""Hosted-provider backends (Poe / Azure OpenAI / MiniMax) over the OpenAI-compatible path.

The network layer is faked at ``urllib.request.urlopen`` so these tests assert the real
request construction (URL, credential header, model naming per provider) and the shared
retry/error discipline — without any live credentials or network access.
"""

from __future__ import annotations

import importlib
import io
import json
import urllib.request

import pytest

from backend.llm.dao_client import (
    OPENAI_COMPAT_BACKENDS,
    DaoClient,
    DaoGenerationConfig,
    DaoRuntimeError,
)


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _capture_urlopen(monkeypatch, response_body: dict):
    """Patch urlopen to record the outgoing request and return a canned JSON body."""

    captured: dict = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["headers"] = {k.lower(): v for k, v in request.header_items()}
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _FakeResponse(json.dumps(response_body).encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return captured


_OPENAI_REPLY = {"choices": [{"message": {"content": "OK：仅供医师审核的教学解释。"}}]}


def _client(backend: str, **cfg) -> DaoClient:
    return DaoClient(DaoGenerationConfig(backend=backend, **cfg))


# ------------------------------------------------------------------------------- poe

def test_poe_backend_uses_poe_api_and_bearer_key(monkeypatch):
    monkeypatch.setenv("POE_API_KEY", "poe-key-1")
    monkeypatch.delenv("POE_API_BASE", raising=False)
    monkeypatch.delenv("POE_MODEL", raising=False)
    captured = _capture_urlopen(monkeypatch, _OPENAI_REPLY)
    reply = _client("poe").chat([], "测试")
    assert "教学解释" in reply
    assert captured["url"] == "https://api.poe.com/v1/chat/completions"
    assert captured["headers"]["authorization"] == "Bearer poe-key-1"
    # Dao1 default model id never leaks to Poe — provider default applies.
    assert captured["payload"]["model"] == "Claude-Sonnet-4.5"
    assert captured["payload"]["messages"][0]["role"] == "system"


def test_poe_model_and_base_overrides(monkeypatch):
    monkeypatch.setenv("POE_API_KEY", "poe-key-1")
    monkeypatch.setenv("POE_API_BASE", "https://proxy.example/v1/")
    monkeypatch.setenv("POE_MODEL", "GPT-5")
    captured = _capture_urlopen(monkeypatch, _OPENAI_REPLY)
    _client("poe").chat([], "测试")
    assert captured["url"] == "https://proxy.example/v1/chat/completions"
    assert captured["payload"]["model"] == "GPT-5"


def test_poe_requires_key(monkeypatch):
    monkeypatch.delenv("POE_API_KEY", raising=False)
    with pytest.raises(DaoRuntimeError, match="POE_API_KEY"):
        _client("poe").chat([], "测试")


# ----------------------------------------------------------------------------- azure

def test_azure_backend_builds_deployment_url_and_api_key_header(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://myres.openai.azure.com/")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-tcm")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "az-key-1")
    monkeypatch.delenv("AZURE_OPENAI_API_VERSION", raising=False)
    captured = _capture_urlopen(monkeypatch, _OPENAI_REPLY)
    _client("azure").chat([], "测试")
    assert captured["url"] == (
        "https://myres.openai.azure.com/openai/deployments/gpt-4o-tcm/chat/completions"
        "?api-version=2024-06-01"
    )
    assert captured["headers"]["api-key"] == "az-key-1"
    assert "authorization" not in captured["headers"]


def test_azure_requires_endpoint_deployment_and_key(monkeypatch):
    for var in ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT", "AZURE_OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(DaoRuntimeError, match="AZURE_OPENAI_ENDPOINT"):
        _client("azure").chat([], "测试")


# --------------------------------------------------------------------------- minimax

def test_minimax_backend_defaults(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "mm-key-1")
    monkeypatch.delenv("MINIMAX_API_BASE", raising=False)
    monkeypatch.delenv("MINIMAX_MODEL", raising=False)
    captured = _capture_urlopen(monkeypatch, {**_OPENAI_REPLY, "base_resp": {"status_code": 0, "status_msg": ""}})
    _client("minimax").chat([], "测试")
    assert captured["url"] == "https://api.minimax.io/v1/text/chatcompletion_v2"
    assert captured["headers"]["authorization"] == "Bearer mm-key-1"
    assert captured["payload"]["model"] == "MiniMax-Text-01"


def test_minimax_application_error_raises_for_fallback(monkeypatch):
    # MiniMax signals failures inside an HTTP-200 body; that must become DaoRuntimeError
    # so every caller keeps its deterministic-rules fallback.
    monkeypatch.setenv("MINIMAX_API_KEY", "mm-key-1")
    _capture_urlopen(monkeypatch, {"base_resp": {"status_code": 1004, "status_msg": "invalid api key"}})
    with pytest.raises(DaoRuntimeError, match="1004"):
        _client("minimax").chat([], "测试")


# ------------------------------------------------------------------- shared behaviour

def test_explicit_tao_model_id_overrides_provider_default(monkeypatch):
    monkeypatch.setenv("POE_API_KEY", "poe-key-1")
    monkeypatch.delenv("POE_MODEL", raising=False)
    captured = _capture_urlopen(monkeypatch, _OPENAI_REPLY)
    _client("poe", model_id="Claude-Opus-4.1").chat([], "测试")
    assert captured["payload"]["model"] == "Claude-Opus-4.1"


def test_provider_backends_report_ready_without_local_weights():
    for backend in OPENAI_COMPAT_BACKENDS:
        status = _client(backend).load_status()
        assert status["state"] == "ready", backend


def test_server_enables_tao_for_provider_backends(monkeypatch):
    monkeypatch.setenv("TAO_BACKEND", "poe")
    monkeypatch.setenv("POE_API_KEY", "poe-key-1")
    import backend.server as server_module

    server = importlib.reload(server_module)
    assert server.TAO_ENABLED is True
    assert server.handle_health({})["tao"]["backend"] == "poe"
    assert server.handle_health({})["tao"]["load_state"] == "ready"
    # Restore the default module state for subsequent test files.
    monkeypatch.setenv("TAO_BACKEND", "mock")
    importlib.reload(server_module)


def test_low_grounding_consultation_falls_back_on_real_backend(monkeypatch):
    # A hosted-provider answer whose clinical entities are not backed by the case
    # evidence must not carry the decision: below TAO_GROUNDING_MIN the deterministic
    # rule answer is served (the model may only extend the explanation layer).
    from backend.skills.tao_consultation_skill import tao_consultation_skill

    monkeypatch.setenv("POE_API_KEY", "poe-key-1")
    monkeypatch.delenv("TAO_GROUNDING_MIN", raising=False)
    ungrounded = "综合判断为湿热痹阻证，建议四妙丸加减，含苍术、黄柏、牛膝、薏苡仁。"
    _capture_urlopen(monkeypatch, {"choices": [{"message": {"content": ungrounded}}]})
    out = tao_consultation_skill(
        "腰痛遇冷加重", "证候辨析",
        {"syndrome_candidates": [{"name": "肾阳不足证", "score": 6}], "formula_routes": [{"name": "当归四逆汤加减"}]},
        fallback_text="规则答案", dao_client=_client("poe"), use_llm=True, user_role="clinician",
    )
    assert out["source"] == "deterministic_rules_fallback"
    assert out["used_llm"] is False
    assert out["tao_runtime"]["status"] == "grounding_rejected"
    assert out["answer"] == "规则答案"


def test_grounded_consultation_passes_on_real_backend(monkeypatch):
    from backend.skills.tao_consultation_skill import tao_consultation_skill

    monkeypatch.setenv("POE_API_KEY", "poe-key-1")
    grounded = "证候倾向肾阳不足证，路线可循当归四逆汤加减（当归、桂枝、细辛、白芍），供执业医师审核。"
    _capture_urlopen(monkeypatch, {"choices": [{"message": {"content": grounded}}]})
    out = tao_consultation_skill(
        "腰痛遇冷加重", "证候辨析",
        {"syndrome_candidates": [{"name": "肾阳不足证", "score": 6}], "formula_routes": [{"name": "当归四逆汤加减"}]},
        fallback_text="规则答案", dao_client=_client("poe"), use_llm=True, user_role="clinician",
    )
    assert out["source"] == "tao_primary_grounded"
    assert out["used_llm"] is True


def test_dispatch_routes_structured_tasks_through_provider(monkeypatch):
    # The guarded skill-routing path (structured_json profile) must also flow through
    # the provider, not only free-form chat.
    monkeypatch.setenv("MINIMAX_API_KEY", "mm-key-1")
    captured = _capture_urlopen(
        monkeypatch,
        {"choices": [{"message": {"content": '{"intent": "syndrome_inquiry", "reason": "test"}'}}]},
    )
    raw = _client("minimax").route_skill({"question": "什么证型", "allowed_intents": ["syndrome_inquiry"]})
    assert json.loads(raw)["intent"] == "syndrome_inquiry"
    assert captured["payload"]["model"] == "MiniMax-Text-01"
