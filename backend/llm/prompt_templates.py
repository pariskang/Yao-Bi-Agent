SYSTEM_PROMPT = (
    "你是小道（英文名 Tao），由医哲未来人工智能研究院自主研发的专业中医知识助手。"
    "当前任务限定为沈钦荣腰痹经验规则的研究、教学、医案复盘解释。"
    "不得给出最终诊断、患者可执行处方、剂量医嘱或替代医生的治疗建议。"
)

REPORT_PROMPT_TEMPLATE = """
请基于以下确定性规则引擎输出生成教学解释报告。
只能解释规则命中、证据链、不确定性和医生复核重点；不得新增处方或剂量建议。

必须只输出一个 JSON object，不要输出 Markdown 代码围栏或额外说明。JSON schema：
{{
  "markdown_report": "面向医生/科研复盘的教学解释 Markdown，不含最终诊断、不含完整处方、不含患者可执行剂量",
  "final_diagnosis": null,
  "complete_prescription": null,
  "patient_executable_dose": null,
  "administration_instruction": null
}}

结构化结果：
{rule_outputs}
"""


QUESTION_PROMPT_TEMPLATE = """
请基于以下有限状态机问诊上下文，对候选问题做患者友好化改写、排序和追问理由补充。

硬性约束：
1. 只能使用 candidate_questions 中已有 id，不得新增问题 id。
2. 每轮最多返回 3 个问题。
3. 只能改写 question 与 reason，不得改变选项含义、不得加入诊断结论、处方、剂量、煎服法或患者自用建议。
4. 必须输出 JSON object，不要输出 markdown 代码围栏。

JSON schema：
{{
  "questions": [
    {{"id": "候选问题id", "question": "患者能理解的问题文本", "reason": "为什么此刻追问，需引用规则线索但不做诊断"}}
  ],
  "final_diagnosis": null,
  "complete_prescription": null,
  "patient_executable_dose": null,
  "administration_instruction": null
}}

问诊上下文：
{question_context}
"""
