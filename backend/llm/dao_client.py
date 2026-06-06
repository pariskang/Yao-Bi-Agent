from __future__ import annotations

import importlib
import importlib.util
import json
import os
import urllib.request
from dataclasses import dataclass
from threading import Lock
from typing import Any, Literal

from backend.llm.prompt_templates import REPORT_PROMPT_TEMPLATE, SYSTEM_PROMPT

DaoBackend = Literal["disabled", "mock", "http", "transformers"]


@dataclass
class DaoGenerationConfig:
    model_id: str = "CMLM/Dao1-30b-a3b"
    backend: DaoBackend = "disabled"
    endpoint_url: str | None = None
    api_key: str | None = None
    temperature: float = 0.3
    top_p: float = 0.85
    repetition_penalty: float = 1.1
    max_new_tokens: int = 2048
    do_sample: bool = True
    torch_dtype: str = "float16"
    device_map: str = "auto"
    attn_implementation: str = "eager"
    timeout_seconds: int = 120

    @classmethod
    def from_env(cls) -> "DaoGenerationConfig":
        return cls(
            model_id=os.getenv("TAO_MODEL_ID", cls.model_id),
            backend=os.getenv("TAO_BACKEND", "disabled"),  # type: ignore[arg-type]
            endpoint_url=os.getenv("TAO_ENDPOINT_URL"),
            api_key=os.getenv("TAO_API_KEY"),
            temperature=float(os.getenv("TAO_TEMPERATURE", "0.3")),
            top_p=float(os.getenv("TAO_TOP_P", "0.85")),
            repetition_penalty=float(os.getenv("TAO_REPETITION_PENALTY", "1.1")),
            max_new_tokens=int(os.getenv("TAO_MAX_NEW_TOKENS", "2048")),
            do_sample=os.getenv("TAO_DO_SAMPLE", "true").lower() == "true",
            timeout_seconds=int(os.getenv("TAO_TIMEOUT_SECONDS", "120")),
        )


class DaoRuntimeError(RuntimeError):
    """Raised when Tao runtime generation cannot complete."""


class DaoClient:
    """Runtime client for Tao/Dao1 report explanation.

    The client is safe-by-default (`backend="disabled"`). Production deployments can
    opt into either an OpenAI-compatible HTTP endpoint or local Transformers loading.
    Deterministic rule outputs remain the source of truth; Tao only rewrites them into
    a teaching explanation and must pass output guards before being surfaced.
    """

    _model_lock = Lock()
    _tokenizer: Any = None
    _model: Any = None

    def __init__(self, config: DaoGenerationConfig | None = None) -> None:
        self.config = config or DaoGenerationConfig.from_env()

    def build_prompt(self, user_content: str, history: list[dict[str, str]] | None = None) -> str:
        text = f"<|im_start|>system\n{SYSTEM_PROMPT}<|im_end|>\n"
        for turn in history or []:
            text += f"<|im_start|>{turn['role']}\n{turn['content']}<|im_end|>\n"
        text += f"<|im_start|>user\n{user_content}<|im_end|>\n<|im_start|>assistant\n"
        return text

    def build_report_prompt(self, structured_rule_outputs: dict[str, Any]) -> str:
        rule_outputs = json.dumps(structured_rule_outputs, ensure_ascii=False, indent=2, default=str)
        return REPORT_PROMPT_TEMPLATE.format(rule_outputs=rule_outputs)

    def generate(self, structured_rule_outputs: dict[str, Any]) -> str:
        prompt = self.build_prompt(self.build_report_prompt(structured_rule_outputs))
        if self.config.backend == "disabled":
            raise DaoRuntimeError("Tao runtime is disabled. Set TAO_BACKEND=http or transformers to enable generation.")
        if self.config.backend == "mock":
            return self._generate_mock(structured_rule_outputs)
        if self.config.backend == "http":
            return self._generate_http(prompt)
        if self.config.backend == "transformers":
            return self._generate_transformers(prompt)
        raise DaoRuntimeError(f"Unsupported Tao backend: {self.config.backend}")

    def _generate_mock(self, structured_rule_outputs: dict[str, Any]) -> str:
        tags = "、".join(structured_rule_outputs.get("normalized_tags", [])[:8]) or "未提供"
        route = (structured_rule_outputs.get("formula_route") or {}).get("name", "未形成稳定路线")
        return json.dumps(
            {
                "markdown_report": (
                    "# Tao 教学解释补充\n\n"
                    f"- 规则证据标签：{tags}\n"
                    f"- 方剂路线信号：{route}。\n"
                    "- 以上仅为沈钦荣腰痹经验规则的教学解释，需医生结合查体、影像与舌脉复核。\n"
                    "- 本内容不构成诊断、处方或治疗建议。"
                ),
                "final_diagnosis": None,
                "complete_prescription": None,
                "patient_executable_dose": None,
                "administration_instruction": None,
            },
            ensure_ascii=False,
        )

    def _generate_http(self, prompt: str) -> str:
        if not self.config.endpoint_url:
            raise DaoRuntimeError("TAO_ENDPOINT_URL is required when TAO_BACKEND=http.")
        payload = {
            "model": self.config.model_id,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": self.config.temperature,
            "top_p": self.config.top_p,
            "max_tokens": self.config.max_new_tokens,
        }
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        request = urllib.request.Request(self.config.endpoint_url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
            body = json.loads(response.read().decode("utf-8"))
        if "choices" in body:
            choice = body["choices"][0]
            return choice.get("message", {}).get("content") or choice.get("text", "")
        if "text" in body:
            return body["text"]
        if "generated_text" in body:
            return body["generated_text"]
        raise DaoRuntimeError("HTTP Tao endpoint response did not contain choices/text/generated_text.")

    def _generate_transformers(self, prompt: str) -> str:
        if importlib.util.find_spec("transformers") is None:
            raise DaoRuntimeError("transformers is not installed. Install optional runtime dependencies before TAO_BACKEND=transformers.")
        if importlib.util.find_spec("torch") is None:
            raise DaoRuntimeError("torch is not installed. Install optional runtime dependencies before TAO_BACKEND=transformers.")

        transformers = importlib.import_module("transformers")
        torch = importlib.import_module("torch")

        with self._model_lock:
            if self.__class__._tokenizer is None or self.__class__._model is None:
                dtype = getattr(torch, self.config.torch_dtype)
                self.__class__._tokenizer = transformers.AutoTokenizer.from_pretrained(self.config.model_id, trust_remote_code=True)
                self.__class__._model = transformers.AutoModelForCausalLM.from_pretrained(
                    self.config.model_id,
                    torch_dtype=dtype,
                    trust_remote_code=True,
                    device_map=self.config.device_map,
                    attn_implementation=self.config.attn_implementation,
                )
        tokenizer = self.__class__._tokenizer
        model = self.__class__._model
        inputs = tokenizer(prompt, return_tensors="pt", add_special_tokens=False).to(model.device)
        outputs = model.generate(
            **inputs,
            max_new_tokens=self.config.max_new_tokens,
            do_sample=self.config.do_sample,
            temperature=self.config.temperature,
            top_p=self.config.top_p,
            repetition_penalty=self.config.repetition_penalty,
            use_cache=True,
        )
        generated = outputs[0][inputs["input_ids"].shape[-1] :]
        return tokenizer.decode(generated, skip_special_tokens=True)
