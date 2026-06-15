from __future__ import annotations

import importlib
import importlib.util
import json
import os
import urllib.request
from dataclasses import dataclass
from threading import Lock, Thread
from typing import Any, Literal

from backend.llm.prompt_templates import (
    CONSULTATION_PROMPT_TEMPLATE,
    EMERGENCY_REFERRAL_PROMPT_TEMPLATE,
    EXPERIENCE_SUMMARY_PROMPT_TEMPLATE,
    FOLLOWUP_PROBE_PROMPT_TEMPLATE,
    INTERVIEW_EXTRACTION_PROMPT_TEMPLATE,
    INTERVIEW_QUESTION_PROMPT_TEMPLATE,
    PROBE_FREEFORM_PROMPT_TEMPLATE,
    QUESTION_PROMPT_TEMPLATE,
    REASONING_PROMPT_TEMPLATE,
    REPORT_PROMPT_TEMPLATE,
    SKILL_PLAN_PROMPT_TEMPLATE,
    SKILL_ROUTING_PROMPT_TEMPLATE,
    SYSTEM_PROMPT,
)

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
    load_in_4bit: bool = False
    load_in_8bit: bool = False
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
            load_in_4bit=os.getenv("TAO_LOAD_IN_4BIT", "false").lower() == "true",
            load_in_8bit=os.getenv("TAO_LOAD_IN_8BIT", "false").lower() == "true",
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
    # Load lifecycle for the heavy transformers backend so callers (server health,
    # Colab warmup) can observe progress instead of blocking blindly on the first
    # request: "idle" → "loading" → "ready"/"error". This is what lets the UI report
    # "still loading" vs. "load failed" instead of surfacing an opaque Connection refused.
    _load_state: Literal["idle", "loading", "ready", "error"] = "idle"
    _load_error: str | None = None

    def __init__(self, config: DaoGenerationConfig | None = None) -> None:
        self.config = config or DaoGenerationConfig.from_env()

    def load_status(self) -> dict[str, Any]:
        """Non-blocking snapshot of the model load lifecycle (safe to poll from /api/health).

        ``mock``/``http`` need no local weights, so they report ``ready`` immediately;
        ``disabled`` reports ``disabled``; ``transformers`` reflects the real load state
        (``idle`` → ``loading`` → ``ready``/``error``). This is read without the model lock
        on purpose so a health check never blocks behind a multi-minute 30B load.
        """

        backend = self.config.backend
        if backend == "disabled":
            state = "disabled"
        elif backend in {"mock", "http"}:
            state = "ready"
        else:
            state = self.__class__._load_state
        return {
            "backend": backend,
            "state": state,
            "model_loaded": self.__class__._model is not None,
            "error": self.__class__._load_error,
        }

    def preload(self) -> dict[str, Any]:
        """Eagerly load the runtime so the first real request is fast and failures are visible.

        Decoupling the heavy ``transformers`` load from the HTTP request handler is what
        prevents a load failure (e.g. an OOM-killed 30B FP16 load) from masquerading as an
        opaque ``Connection refused`` on the next warmup. Catchable errors are returned as
        ``{"ok": False, ...}`` with the real cause; ``mock``/``http``/``disabled`` are no-ops.
        """

        backend = self.config.backend
        if backend == "disabled":
            return {"ok": False, "state": "disabled", "backend": backend, "reason": "Tao backend disabled (set TAO_BACKEND=transformers/http/mock)."}
        if backend in {"mock", "http"}:
            self.__class__._load_state = "ready"
            return {"ok": True, "state": "ready", "backend": backend, "model_id": self.config.model_id}
        if backend == "transformers":
            self.__class__._load_state = "loading"
            self.__class__._load_error = None
            try:
                self._load_transformers_runtime()
            except Exception as exc:  # noqa: BLE001 — surface the real cause instead of crashing the preload thread
                self.__class__._load_state = "error"
                self.__class__._load_error = f"{type(exc).__name__}: {exc}"
                return {"ok": False, "state": "error", "backend": backend, "model_id": self.config.model_id, "reason": self.__class__._load_error}
            return {"ok": True, "state": "ready", "backend": backend, "model_id": self.config.model_id}
        return {"ok": False, "state": "error", "backend": backend, "reason": f"Unsupported Tao backend: {backend}"}

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

    def _dispatch(self, prompt: str, mock_value: str, task: str) -> str:
        """Backend dispatch shared by structured generation tasks.

        Deterministic callers remain responsible for guarding output before it
        can surface as clinical text; this only routes prompt → backend.
        """

        if self.config.backend == "disabled":
            raise DaoRuntimeError(f"Tao {task} runtime is disabled. Set TAO_BACKEND=http or transformers to enable.")
        if self.config.backend == "mock":
            return mock_value
        if self.config.backend == "http":
            return self._generate_http(prompt)
        if self.config.backend == "transformers":
            return self._generate_transformers(prompt)
        raise DaoRuntimeError(f"Unsupported Tao backend: {self.config.backend}")

    def generate_followup_probes(self, probe_context: dict[str, Any]) -> str:
        max_probes = int(probe_context.get("max_probes", 2))
        body = FOLLOWUP_PROBE_PROMPT_TEMPLATE.format(
            max_probes=max_probes,
            probe_context=json.dumps(probe_context, ensure_ascii=False, indent=2, default=str),
        )
        return self._dispatch(self.build_prompt(body), self._mock_followup_probes(probe_context), "follow-up probe")

    def generate_reasoning(self, reasoning_context: dict[str, Any]) -> str:
        body = REASONING_PROMPT_TEMPLATE.format(
            reasoning_context=json.dumps(reasoning_context, ensure_ascii=False, indent=2, default=str)
        )
        return self._dispatch(self.build_prompt(body), self._mock_reasoning(reasoning_context), "reasoning")

    def generate_experience_summary(self, summary_context: dict[str, Any]) -> str:
        body = EXPERIENCE_SUMMARY_PROMPT_TEMPLATE.format(
            summary_context=json.dumps(summary_context, ensure_ascii=False, indent=2, default=str)
        )
        return self._dispatch(self.build_prompt(body), self._mock_experience_summary(summary_context), "experience summary")

    def route_skill(self, routing_context: dict[str, Any]) -> str:
        body = SKILL_ROUTING_PROMPT_TEMPLATE.format(
            routing_context=json.dumps(routing_context, ensure_ascii=False, indent=2, default=str)
        )
        return self._dispatch(self.build_prompt(body), self._mock_route_skill(routing_context), "skill routing")

    def generate_consultation(self, consultation_context: dict[str, Any]) -> str:
        """Tao-primary professional answer: the model is the main reasoner.

        Unlike the JSON overlay tasks, this returns free-form professional Markdown grounded
        in the supplied rule/mined evidence — the model combines those experience cues with
        its own TCM knowledge. The caller guards it with ``guard_consultation`` before use.
        """

        body = CONSULTATION_PROMPT_TEMPLATE.format(
            scope=consultation_context.get("scope", "全面会诊"),
            question=consultation_context.get("question", ""),
            evidence=json.dumps(consultation_context.get("evidence", {}), ensure_ascii=False, indent=2, default=str),
        )
        return self._dispatch(self.build_prompt(body), self._mock_consultation(consultation_context), "consultation")

    def extract_slots(self, user_text: str) -> str:
        """Tao extracts structured YaoBi slots from one free-text turn (JSON object)."""

        body = INTERVIEW_EXTRACTION_PROMPT_TEMPLATE.format(user_text=user_text)
        return self._dispatch(self.build_prompt(body), self._mock_extract_slots(user_text), "slot extraction")

    def generate_interview_question(self, interview_context: dict[str, Any]) -> str:
        """Tao autonomously asks the next follow-up turn, grounded in stage/slots/patterns."""

        body = INTERVIEW_QUESTION_PROMPT_TEMPLATE.format(
            stage=interview_context.get("stage", ""),
            stage_goal=interview_context.get("stage_goal", ""),
            target_slots=", ".join(interview_context.get("target_slots", []) or []) or "（无指定，按鉴别价值自选）",
            candidate_patterns=json.dumps(interview_context.get("candidate_patterns", []), ensure_ascii=False, default=str),
            case_summary=json.dumps(interview_context.get("case_summary", {}), ensure_ascii=False, default=str),
        )
        return self._dispatch(self.build_prompt(body), self._mock_interview_question(interview_context), "interview question")

    def generate_emergency_referral(self, referral_context: dict[str, Any]) -> str:
        """Tao reasons over detected red flags and produces ER referral clinical guidance.

        Output is free-form Markdown for clinicians (not a diagnosis or prescription):
        clinical significance of each flag, what to bring to the ER, precautions, and urgency
        classification.  The caller guards the result with ``guard_consultation`` before use.
        """

        flags = referral_context.get("red_flags") or []
        body = EMERGENCY_REFERRAL_PROMPT_TEMPLATE.format(
            red_flags="\n".join(f"- {f}" for f in flags) or "- （危险信号待明确）",
            case_summary=json.dumps(referral_context.get("case_summary", {}), ensure_ascii=False, indent=2, default=str),
        )
        return self._dispatch(self.build_prompt(body), self._mock_emergency_referral(referral_context), "emergency referral")

    def _mock_emergency_referral(self, ctx: dict[str, Any]) -> str:
        flags = ctx.get("red_flags") or []
        safety_level = ctx.get("safety_level", "high")
        is_emergency = safety_level == "emergency"
        level_label = "**Ⅰ级急诊（立即就诊）**" if is_emergency else "**Ⅱ级急诊（2小时内就诊）**"
        flags_md = "\n".join(f"- {f}" for f in flags) or "- 高风险信号（详见问诊记录）"
        clinical_meaning = (
            "马尾神经位于脊髓圆锥以下，受压后若未及时手术减压，可能导致永久性大小便功能障碍及下肢感觉运动缺失。"
            "神经功能保护的时间窗有限（通常以48小时为关键节点），尽早影像确认和手术决策是预后的关键。"
            if is_emergency else
            "上述危险信号提示可能存在感染性、肿瘤性或骨折性脊柱病变，需尽快影像学确认与专科评估。"
        )
        urgency_reason = (
            "马尾神经受压的可能性不能排除，时间窗决定预后，需立即脊柱外科/神经外科评估。"
            if is_emergency else
            "危险信号提示需要专科排除严重病变，建议尽快就医而非等待普通门诊。"
        )
        return (
            f"## 急诊转诊临床参考（供执业医师审核 · 非患者自用）\n\n"
            f"### 一、危险信号临床意义\n"
            f"{flags_md}\n\n"
            f"{clinical_meaning}\n\n"
            f"### 二、就诊时建议携带的信息\n"
            f"1. 各症状出现/加重的确切时间（尤其大小便障碍、肢体无力的起始时刻）\n"
            f"2. 近期腰椎影像资料（MRI/CT/X线报告及原始图像，如有）\n"
            f"3. 目前用药清单（止痛药/抗凝/激素/降糖等）\n"
            f"4. 既往脊柱手术史、肿瘤病史及药物过敏史\n\n"
            f"### 三、转诊前注意事项\n"
            f"- 避免剧烈弯腰、扭转或搬运重物，防止加重神经损伤\n"
            f"- 建议平卧位等待或由120急救担架搬运，避免长时间坐位移动\n"
            f"- 如症状骤然加重（双下肢完全无力/完全失禁），立即拨打120急救\n"
            f"- 镇痛药物是否使用请由急诊接诊医师判断，就医前请勿擅自用药以免影响评估\n\n"
            f"### 四、紧迫度评级\n"
            f"{level_label}\n"
            f"理由：{urgency_reason}\n\n"
            f"> 本内容为供执业医师参考的急诊转诊辅助信息，最终处置由接诊医师决定，患者不可据此自行用药。"
        )

    def generate_probe_questions(self, probe_context: dict[str, Any]) -> str:
        """Tao-primary follow-up: the model freely asks the next clarifying questions."""

        max_probes = int(probe_context.get("max_probes", 2))
        body = PROBE_FREEFORM_PROMPT_TEMPLATE.format(
            max_probes=max_probes,
            theme=probe_context.get("current_state_theme", "本状态主题"),
            context=json.dumps(
                {"last_answers": probe_context.get("last_answers", {}), "normalized_tags": probe_context.get("normalized_tags", [])},
                ensure_ascii=False, default=str,
            ),
        )
        return self._dispatch(self.build_prompt(body), self._mock_probe_questions(probe_context), "probe questions")

    def plan_skills(self, plan_context: dict[str, Any]) -> str:
        max_steps = int(plan_context.get("max_steps", 4))
        body = SKILL_PLAN_PROMPT_TEMPLATE.format(
            max_steps=max_steps,
            plan_context=json.dumps(plan_context, ensure_ascii=False, indent=2, default=str),
        )
        return self._dispatch(self.build_prompt(body), self._mock_plan_skills(plan_context), "skill planning")

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

    def _mock_followup_probes(self, probe_context: dict[str, Any]) -> str:
        allowed = probe_context.get("allowed_fields") or []
        theme = probe_context.get("current_state_theme", "本状态主题")
        max_probes = int(probe_context.get("max_probes", 2))
        probes = []
        for field in allowed[:max_probes]:
            probes.append({
                "probe_text": f"围绕{theme}，能否再具体描述与“{field}”相关的细节？",
                "field_hint": field,
                "reason": "Tao结合上一轮回答，在本状态主题内补充澄清，用于区分鉴别线索（待医师复核）。",
            })
        if not probes:
            probes.append({
                "probe_text": f"关于{theme}，还有没有补充的细节想告诉医生？",
                "field_hint": None,
                "reason": "Tao在本状态主题内做开放补充，仅作为线索，不做判断。",
            })
        return json.dumps({
            "probes": probes[:max_probes],
            "final_diagnosis": None,
            "complete_prescription": None,
            "patient_executable_dose": None,
            "administration_instruction": None,
        }, ensure_ascii=False)

    def _mock_reasoning(self, reasoning_context: dict[str, Any]) -> str:
        chain = reasoning_context.get("reasoning_chain") or []
        lines = ["# Tao 辨证推理教学解释（叠加层）", ""]
        for step in chain:
            lines.append(f"- **{step.get('title', '')}**：{step.get('content', '')}")
        lines.append("")
        lines.append("以上为基于规则结论的推理过程语言化表达，全部为倾向性、非最终口吻，需医师结合查体、影像、舌脉审定。")
        return json.dumps({
            "reasoning_markdown": "\n".join(lines),
            "final_diagnosis": None,
            "complete_prescription": None,
            "patient_executable_dose": None,
            "administration_instruction": None,
        }, ensure_ascii=False)

    def _mock_experience_summary(self, summary_context: dict[str, Any]) -> str:
        mode = summary_context.get("mode", "case")
        points = list(summary_context.get("key_points_seed") or [])
        if mode == "experience":
            body = "# 沈钦荣腰痹经验规律总结（脱敏统计，教学用）\n\n以上规律来自脱敏聚合统计，体现高频证候、核心方剂路线与用药特色，均为待专家审核的研究信号。"
        else:
            body = "# 医案按语（教学复盘）\n\n本案辨证、治法与方剂路线倾向见上，体现沈老益气养血、温通经络、顾护肝肾脾胃的思路，仅作教学复盘，需医师审核。"
        if not points:
            points = ["辨证以证候倾向为纲，结合腰腿症状与神经线索", "治法体现温通与扶正并重", "用药特色需结合安全复核"]
        return json.dumps({
            "summary_markdown": body,
            "key_points": points,
            "final_diagnosis": None,
            "complete_prescription": None,
            "patient_executable_dose": None,
            "administration_instruction": None,
        }, ensure_ascii=False)

    def _mock_route_skill(self, routing_context: dict[str, Any]) -> str:
        # The mock honours the deterministic keyword hint so routing is testable;
        # a real backend would let the model choose from allowed_intents itself.
        allowed = routing_context.get("allowed_intents") or []
        hint = routing_context.get("hint_intent")
        intent = hint if hint in allowed else (allowed[0] if allowed else "capabilities")
        return json.dumps({"intent": intent, "reason": "Tao 依据问题语义选择该技能（mock 沿用关键词提示）。"}, ensure_ascii=False)

    def _mock_plan_skills(self, plan_context: dict[str, Any]) -> str:
        # Honour the deterministic hint plan so multi-step planning stays testable;
        # a real backend would decompose the question into ordered intents itself.
        allowed = set(plan_context.get("allowed_intents") or [])
        hint = [s for s in (plan_context.get("hint_plan") or []) if s.get("intent") in allowed]
        if not hint:
            hint = [{"intent": (plan_context.get("allowed_intents") or ["capabilities"])[0], "reason": "默认单步"}]
        return json.dumps({"plan": hint}, ensure_ascii=False)

    def _mock_consultation(self, ctx: dict[str, Any]) -> str:
        ev = ctx.get("evidence", {}) or {}
        question = str(ctx.get("question", "")).strip()
        scope = ctx.get("scope", "全面会诊")
        syns = ev.get("syndrome_candidates") or []
        routes = ev.get("formula_routes") or []
        modules = ev.get("herb_modules") or []
        tags = ev.get("normalized_tags") or []
        safety = ev.get("safety") or {}
        top = (syns[0].get("name") or syns[0].get("pattern")) if syns else "气血痹阻、筋脉失养"
        alt = "、".join((s.get("name") or s.get("pattern") or "") for s in syns[1:3]) or "寒湿痹阻、肝肾不足"
        route = (routes[0].get("name") if routes else None) or "独活寄生汤加减"
        mods = "、".join(m.get("name", "") for m in modules[:4]) or "祛风湿通络、益气养血、补益肝肾"
        clue = "、".join(tags[:8]) or "待四诊补充"
        return (
            f"# 腰痹病案分析（{scope} · 结合沈钦荣经验 · 供执业医师审核）\n\n"
            f"## 一、四诊辨析与病机\n"
            f"据所述「{question[:80]}」，本案以腰痛为主症。结合线索（{clue}）：跌扑、负重每致经筋损伤、气血瘀阻；"
            f"久则气血亏虚、筋脉失养；遇冷加重、得温则缓提示寒凝经脉、阳气不展；脉细多为气血不足之象。"
            f"病位在腰府筋脉，与肝、肾、脾相关，病性多属本虚标实、虚实夹杂。\n\n"
            f"## 二、证型判断（倾向性，供医师审定）\n"
            f"主证倾向「{top}」；次选可虑「{alt}」。辨证依据：上述症舌脉与既往史的相互印证，"
            f"以及沈老“益气养血、温通经络、顾护肝肾脾胃”之经验思路。\n\n"
            f"## 三、治法\n以益气养血、温经通络为主，兼顾活血化瘀、补益肝肾，标本同治。\n\n"
            f"## 四、选方与方义\n"
            f"可考虑「{route}」为底化裁：方中独活、桑寄生祛风湿、补肝肾为君；"
            f"细辛、桂枝温经散寒，当归、川芎养血活血为臣；佐以杜仲、牛膝强筋骨、引药下行；"
            f"使以炙甘草调和诸药。随证加减：瘀重酌加活血通络之品，寒甚增温阳散寒，"
            f"麻木掣痛可虑虫类搜剔（需医师审核）。\n\n"
            f"## 五、用药功效模块与经验剂量范围\n"
            f"涉及模块：{mods}。各药经验用量区间需由医师按体质、合并病与耐受审定，此处不作患者可执行医嘱。\n\n"
            f"## 六、安全、鉴别与随访\n"
            f"安全状态参考：{safety.get('status', '待评估')}。附片、细辛、虫类等须医师重点审核配伍与用量；"
            f"注意排除马尾综合征、肿瘤、感染、骨折等红旗信号；合并病及肝肾功能、胃肠耐受需复核；"
            f"建议面诊查体与影像复核后随访调整。\n\n"
            f"> 本分析为供执业医师审核的研究 / 教学草案，最终诊断与处方须医师面诊后确定，患者不可据此自行用药。"
        )

    def _mock_probe_questions(self, ctx: dict[str, Any]) -> str:
        theme = ctx.get("current_state_theme", "本状态主题")
        bank = {
            "疼痛": ["这种腰痛更像胀痛、刺痛还是冷痛？", "受凉或阴雨天疼痛会不会明显加重，热敷能缓解吗？"],
            "放射": ["腰痛会不会串到臀部或下肢？走一段路是否加重、休息能否缓解？", "咳嗽或用力时腿部串痛会加重吗？"],
            "中医": ["平时怕冷还是怕热？口苦、口干明显吗？", "睡眠和胃口怎么样，和腰痛发作有没有一起变化？"],
            "合并": ["以前吃过的止痛药有没有引起胃部不适或反酸？", "是否在用抗凝、激素或降糖类药物？"],
        }
        chosen: list[str] = []
        for key, qs in bank.items():
            if key in theme:
                chosen = qs
                break
        if not chosen:
            chosen = ["关于" + theme + "，还有哪些细节想补充给医生？", "这些症状最近有没有新的变化？"]
        return "\n".join(chosen[: int(ctx.get("max_probes", 2))])

    def _mock_extract_slots(self, user_text: str) -> str:
        import re as _re

        t = user_text or ""
        def has(*ks: str) -> bool:
            return any(k in t for k in ks)

        def tri(*ks: str) -> bool | None:
            # negation-aware tri-state: True (present) / False (explicitly denied) / None (unmentioned),
            # so "没有无力 / 无发热 / 否认外伤" records an answered-absent slot rather than a missing one.
            found_pos = found_neg = False
            for k in ks:
                for m in _re.finditer(_re.escape(k), t):
                    pre = t[max(0, m.start() - 3):m.start()]
                    if any(n in pre for n in ("无", "没", "否", "非", "排除", "未")):
                        found_neg = True
                    else:
                        found_pos = True
            return True if found_pos else (False if found_neg else None)

        demo: dict[str, Any] = {}
        pain: dict[str, Any] = {}
        ortho: dict[str, Any] = {}
        tcm: dict[str, Any] = {}
        hist: dict[str, Any] = {}

        m = _re.search(r"(\d{1,3})\s*岁", t)
        if m:
            demo["age"] = int(m.group(1))
        elif "青年" in t:
            demo["age"] = 28
        if "女" in t:
            demo["sex"] = "女"
        elif "男" in t:
            demo["sex"] = "男"

        if has("腰腿", "腿痛", "下肢"):
            pain["pain_location"] = "腰部及下肢"
        elif has("腰"):
            pain["pain_location"] = "腰部"
        for key, kws in (
            ("radiation", ("放射", "串", "窜")), ("numbness", ("麻", "麻木")),
            ("weakness", ("无力", "乏力", "抬不起")), ("night_pain", ("夜间痛", "夜里痛", "夜间加重", "夜痛")),
            ("cold_damp_trigger", ("遇冷", "受寒", "受凉", "阴雨", "涉水", "天冷")),
            ("trauma_history", ("跌", "摔", "扭", "外伤", "跌扑", "闪了", "搬")),
        ):
            v = tri(*kws)
            if v is not None:
                pain[key] = v
        for nature in ("刺痛", "冷痛", "胀痛", "灼痛", "酸痛"):
            if nature in t:
                pain["pain_nature"] = nature
                break
        md = _re.search(r"(\d+\s*[年月周天])", t)
        if md:
            pain["duration"] = md.group(1)
        elif "反复" in t:
            pain["onset"] = "反复发作"

        for key, kws in (
            ("bowel_bladder_dysfunction", ("大小便", "失禁", "尿不", "解不出")), ("saddle_anesthesia", ("会阴", "鞍区")),
            ("progressive_weakness", ("进行性", "越来越无力", "越来越没力")), ("fever", ("发热", "发烧", "寒战")),
            ("tumor_history", ("肿瘤", "癌")), ("unexplained_weight_loss", ("消瘦", "体重下降", "变瘦")),
            ("severe_trauma", ("车祸", "高处坠", "重物砸", "严重外伤")),
        ):
            v = tri(*kws)
            if v is not None:
                ortho[key] = v

        if has("怕冷", "畏寒"):
            tcm["cold_heat"] = "怕冷"
        elif has("怕热", "五心烦热"):
            tcm["cold_heat"] = "怕热"
        if has("冷痛"):
            tcm["cold_pain"] = True
        if has("困重", "沉重"):
            tcm["limb_heaviness"] = True
        if has("定处", "固定"):
            tcm["fixed_pain"] = True
        if has("腰膝酸软", "酸软"):
            tcm["waist_knee_soreness"] = True
        if has("口干", "口渴"):
            tcm["thirst"] = "口干"
        if has("失眠", "睡不", "多梦", "早醒"):
            tcm["sleep"] = "欠佳"
        if has("纳差", "胃口差", "食少"):
            tcm["appetite"] = "纳差"
        if "舌淡" in t:
            tcm["tongue_body"] = "淡"
        elif has("舌暗", "暗紫", "紫暗"):
            tcm["tongue_body"] = "暗紫"
        elif "舌红" in t:
            tcm["tongue_body"] = "红"
        if "薄白" in t:
            tcm["tongue_coating"] = "薄白"
        elif "白腻" in t:
            tcm["tongue_coating"] = "白腻"
        elif "黄腻" in t:
            tcm["tongue_coating"] = "黄腻"
        for pulse in ("细", "弦", "沉", "滑", "数", "紧"):
            if f"脉{pulse}" in t or f"脉象{pulse}" in t:
                tcm["pulse"] = pulse
                break

        if "骨质疏松" in t:
            hist["osteoporosis"] = True
        if has("椎间盘", "椎管狭窄", "滑脱"):
            hist["western_diagnosis"] = t[:60]
        if has("MRI", "CT", "X线", "X光", "核磁", "片子", "磁共振"):
            hist["imaging"] = "有影像检查"

        out: dict[str, Any] = {}
        if demo:
            out["demographics"] = demo
        if "腰" in t:
            out["chief_complaint"] = t[:40]
        if pain:
            out["pain_slots"] = pain
        if ortho:
            out["ortho_neuro_slots"] = ortho
        if tcm:
            out["tcm_slots"] = tcm
        if hist:
            out["history_slots"] = hist
        return json.dumps(out, ensure_ascii=False)

    def _mock_interview_question(self, ctx: dict[str, Any]) -> str:
        targets = ctx.get("target_slots", []) or []
        phrase = {
            "chief_complaint": "目前最主要的不适是什么，痛了多久了",
            "bowel_bladder_dysfunction": "最近有没有大小便控制困难、或突然解不出来",
            "saddle_anesthesia": "会阴部（坐着接触座位的部位）有没有发麻",
            "progressive_weakness": "下肢力气是不是越来越差、走路发软或拖步",
            "severe_trauma": "这次发作前有没有明显的摔伤、扭伤或外伤",
            "fever": "有没有发热、寒战或近期感染",
            "tumor_history": "既往有没有肿瘤病史，近期有没有不明原因消瘦",
            "night_pain": "夜里痛得明显吗，会不会痛醒",
            "radiation": "腰痛会不会向臀部或腿脚放射",
            "numbness": "腿脚有没有发麻",
            "weakness": "腿有没有发软、使不上劲",
            "cold_damp_trigger": "受凉或阴雨天会不会加重，热敷能不能缓解",
            "pain_nature": "疼痛更像酸痛、胀痛、刺痛还是冷痛",
            "duration": "这次腰痛大概持续多久了，是急性还是反复发作",
            "tongue_body": "方便的话看下舌头，舌质偏淡、偏红还是偏暗紫",
            "tongue_coating": "舌苔是薄白、白腻还是黄腻",
            "pulse": "如果量过脉，脉象偏细、偏弦还是偏沉",
            "cold_heat": "平时是怕冷还是怕热",
            "waist_knee_soreness": "有没有腰膝酸软、乏力的感觉",
            "sleep": "睡眠怎么样",
            "stool": "大便情况如何",
            "urine": "小便清长还是偏黄",
            "western_diagnosis": "之前医院有没有诊断过（如椎间盘突出、椎管狭窄）",
            "imaging": "做过腰椎 X 线、CT 或核磁吗",
            "osteoporosis": "有没有骨质疏松",
        }
        chosen = [phrase[s] for s in targets if s in phrase][:4]
        if not chosen:
            chosen = ["还可以多说说目前最困扰你的症状，以及加重或缓解的因素"]
        return "为了更准确地帮医生判断，我想再了解几点：" + "；".join(chosen) + "？"

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

        quant = "4bit" if self.config.load_in_4bit else "8bit" if self.config.load_in_8bit else "none"
        signature = (self.config.model_id, f"{self.config.torch_dtype}:{quant}", self.config.device_map, self.config.attn_implementation)
        with self._model_lock:
            if (
                self.__class__._tokenizer is None
                or self.__class__._model is None
                or self.__class__._model_signature != signature
            ):
                self.__class__._load_state = "loading"
                self.__class__._load_error = None
                try:
                    dtype = getattr(torch, self.config.torch_dtype, torch.float16)
                    from_pretrained_kwargs: dict[str, Any] = {
                        "trust_remote_code": True,
                        "device_map": self.config.device_map,
                        "attn_implementation": self.config.attn_implementation,
                    }
                    # Optional 4-bit / 8-bit quantization lets large models (e.g. the 30B MoE
                    # CMLM/Dao1-30b-a3b) fit a single A100/L4; requires the bitsandbytes package.
                    if self.config.load_in_4bit or self.config.load_in_8bit:
                        from_pretrained_kwargs["quantization_config"] = transformers.BitsAndBytesConfig(
                            load_in_4bit=self.config.load_in_4bit,
                            load_in_8bit=self.config.load_in_8bit and not self.config.load_in_4bit,
                            bnb_4bit_compute_dtype=dtype,
                            bnb_4bit_quant_type="nf4",
                            bnb_4bit_use_double_quant=True,
                        )
                    else:
                        from_pretrained_kwargs["torch_dtype"] = dtype
                    self.__class__._tokenizer = transformers.AutoTokenizer.from_pretrained(self.config.model_id, trust_remote_code=True)
                    self.__class__._model = transformers.AutoModelForCausalLM.from_pretrained(
                        self.config.model_id,
                        **from_pretrained_kwargs,
                    )
                    self.__class__._model_signature = signature
                except Exception as exc:  # noqa: BLE001 — record cause so health/warmup report it, then re-raise
                    self.__class__._load_state = "error"
                    self.__class__._load_error = f"{type(exc).__name__}: {exc}"
                    raise
            self.__class__._load_state = "ready"
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
        # Convert any transformers/torch/load/OOM failure into DaoRuntimeError so every caller
        # (routing, consultation, probe, interview) degrades gracefully to deterministic rules
        # instead of surfacing an opaque HTTP 500 — and the real cause is preserved in the message.
        try:
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
        except DaoRuntimeError:
            raise
        except Exception as exc:  # noqa: BLE001 — surface cause, never crash the request
            raise DaoRuntimeError(f"transformers backend failed: {type(exc).__name__}: {exc}") from exc
