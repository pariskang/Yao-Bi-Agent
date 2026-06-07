from __future__ import annotations

import importlib
import importlib.util
import json
import os
import urllib.request
from dataclasses import dataclass
from threading import Lock, Thread
from typing import Any, Literal

from backend.llm.prompt_templates import QUESTION_PROMPT_TEMPLATE, REPORT_PROMPT_TEMPLATE, SYSTEM_PROMPT

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
            torch_dtype=os.getenv("TAO_TORCH_DTYPE", cls.torch_dtype),
            device_map=os.getenv("TAO_DEVICE_MAP", cls.device_map),
            attn_implementation=os.getenv("TAO_ATTN_IMPLEMENTATION", cls.attn_implementation),
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
    _model_signature: tuple[str, str, str, str] | None = None

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

    def build_question_prompt(self, question_context: dict[str, Any]) -> str:
        context = json.dumps(question_context, ensure_ascii=False, indent=2, default=str)
        return QUESTION_PROMPT_TEMPLATE.format(question_context=context)

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

    def generate_question_plan(self, question_context: dict[str, Any]) -> str:
        prompt = self.build_prompt(self.build_question_prompt(question_context))
        if self.config.backend == "disabled":
            raise DaoRuntimeError("Tao question runtime is disabled. Set TAO_BACKEND=http or transformers to enable question planning.")
        if self.config.backend == "mock":
            return self._generate_question_mock(question_context)
        if self.config.backend == "http":
            return self._generate_http(prompt)
        if self.config.backend == "transformers":
            return self._generate_transformers(prompt)
        raise DaoRuntimeError(f"Unsupported Tao backend: {self.config.backend}")

    def chat(
        self,
        history: list[dict[str, str]],
        user_input: str,
        stream_callback: Any | None = None,
    ) -> str:
        """Direct Tao chat inference without a FastAPI wrapper.

        This mirrors the Dao1/Tao model-card style: build a Qwen chat prompt, load
        `CMLM/Dao1-30b-a3b` through Transformers when `backend=transformers`, and
        optionally stream decoded tokens to a callback. The caller still remains
        responsible for applying task-specific guards before surfacing clinical text.
        """

        prompt = self.build_prompt(user_input, history)
        if self.config.backend == "disabled":
            raise DaoRuntimeError("Tao direct chat is disabled. Set TAO_BACKEND=transformers for local model inference.")
        if self.config.backend == "mock":
            return "Tao mock direct reply: 已收到问题；当前项目中模型输出仍需规则与安全 guard 复核。"
        if self.config.backend == "http":
            return self._generate_http(prompt)
        if self.config.backend == "transformers":
            return self._generate_transformers(prompt, stream_callback=stream_callback)
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

    def _generate_question_mock(self, question_context: dict[str, Any]) -> str:
        questions = []
        for question in question_context.get("candidate_questions", [])[:3]:
            questions.append({
                "id": question.get("id"),
                "question": question.get("question"),
                "reason": f"Tao结合当前规则线索建议追问：{question.get('reason', '补齐关键变量')}"
            })
        return json.dumps({
            "questions": questions,
            "final_diagnosis": None,
            "complete_prescription": None,
            "patient_executable_dose": None,
            "administration_instruction": None,
        }, ensure_ascii=False)

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

    def _load_transformers_runtime(self) -> tuple[Any, Any, Any]:
        if importlib.util.find_spec("transformers") is None:
            raise DaoRuntimeError("transformers is not installed. Install optional runtime dependencies before TAO_BACKEND=transformers.")
        if importlib.util.find_spec("torch") is None:
            raise DaoRuntimeError("torch is not installed. Install optional runtime dependencies before TAO_BACKEND=transformers.")

        transformers = importlib.import_module("transformers")
        torch = importlib.import_module("torch")

        signature = (self.config.model_id, self.config.torch_dtype, self.config.device_map, self.config.attn_implementation)
        with self._model_lock:
            if (
                self.__class__._tokenizer is None
                or self.__class__._model is None
                or self.__class__._model_signature != signature
            ):
                dtype = getattr(torch, self.config.torch_dtype, torch.float16)
                self.__class__._tokenizer = transformers.AutoTokenizer.from_pretrained(self.config.model_id, trust_remote_code=True)
                self.__class__._model = transformers.AutoModelForCausalLM.from_pretrained(
                    self.config.model_id,
                    torch_dtype=dtype,
                    trust_remote_code=True,
                    device_map=self.config.device_map,
                    attn_implementation=self.config.attn_implementation,
                )
                self.__class__._model_signature = signature
        return transformers, self.__class__._tokenizer, self.__class__._model

    def _model_input_device(self, model: Any) -> Any | None:
        embeddings = model.get_input_embeddings() if hasattr(model, "get_input_embeddings") else None
        weight = getattr(embeddings, "weight", None)
        if getattr(weight, "device", None) is not None:
            return weight.device
        if getattr(model, "device", None) is not None:
            return model.device
        device_map = getattr(model, "hf_device_map", None) or {}
        for device in device_map.values():
            if str(device) not in {"cpu", "disk"}:
                return device
        return None

    def _tokenize_for_model(self, tokenizer: Any, model: Any, prompt: str) -> Any:
        inputs = tokenizer(prompt, return_tensors="pt", add_special_tokens=False)
        device = self._model_input_device(model)
        return inputs.to(device) if device is not None else inputs

    def _generate_transformers(self, prompt: str, stream_callback: Any | None = None) -> str:
        transformers, tokenizer, model = self._load_transformers_runtime()
        inputs = self._tokenize_for_model(tokenizer, model, prompt)
        generate_kwargs = dict(
            **inputs,
            max_new_tokens=self.config.max_new_tokens,
            do_sample=self.config.do_sample,
            temperature=self.config.temperature,
            top_p=self.config.top_p,
            repetition_penalty=self.config.repetition_penalty,
            use_cache=True,
        )
        if stream_callback is not None:
            streamer = transformers.TextIteratorStreamer(tokenizer, skip_prompt=True, skip_special_tokens=True)
            thread = Thread(target=model.generate, kwargs={**generate_kwargs, "streamer": streamer})
            thread.start()
            response = ""
            for token in streamer:
                stream_callback(token)
                response += token
            thread.join()
            return response

        outputs = model.generate(**generate_kwargs)
        generated = outputs[0][inputs["input_ids"].shape[-1] :]
        return tokenizer.decode(generated, skip_special_tokens=True)
