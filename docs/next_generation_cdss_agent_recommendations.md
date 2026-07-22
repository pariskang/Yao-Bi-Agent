# 下一代腰痹 CDSS 智能体改造建议

> 本建议稿基于当前 `Yao-Bi-Agent`、压缩包参考版 `Yao-Bi-Agent-main (1).zip`，以及 `Shanghan-Hermes-main (2).zip` 的代码与文档对照。目标不是把系统退回“规则表驱动”的固定流水线，而是在保留安全边界、证据可追溯和医师终审的基础上，把规则降级为**可解释软约束**，让模型/智能体成为能规划、取证、反思、循环改进的下一代 CDSS 协作系统。

## 1. 总体判断

当前仓库已明显强于压缩包中的旧版 Yao-Bi：已有自主多步 QA、智能体编排、批判者、运行预算、共形预测、主动问诊、接地性检查、审计与反馈闭环。下一步不宜继续堆叠硬编码规则，而应把 CDSS 的核心范式从“规则命中 → 模板报告”升级为：

```text
患者/医师叙述
  ↓
动态病例状态图谱（症状、否定、时间线、检查、治疗反应、风险、偏好）
  ↓
Planner 生成可变计划（含检索、问诊、鉴别、批判、复核）
  ↓
Subagents 并行/串行执行：证据检索、假设生成、鉴别、风险、用药、经验队列、指南/文献、患者沟通
  ↓
Critic/Judge 进行安全、证据、矛盾、认知偏差、适用性审查
  ↓
若信息不足或冲突明显：进入 follow-up / replan loop
  ↓
输出给医师的“候选决策包”：预测集、证据链、反证、缺失信息、下一步建议、患者沟通稿
  ↓
医师反馈 → 误差归因 → 规则/提示/评测集/检索库候选更新
```

其中规则只应承担三类职责：

1. **安全底线**：红旗、患者端边界、隐私、药物相互作用等仍可为硬门控。
2. **可解释先验**：证型、方路、经验模块应作为 soft prior / evidence feature，而不是唯一裁决器。
3. **评测与校准锚点**：规则提供可审计基线，用来发现模型偏航、幻觉和数据漂移。

## 2. 从 Shanghan-Hermes 借鉴的关键设计

`Shanghan-Hermes` 最值得迁移的不是某个具体经方工具，而是“证据工程 + 循环智能体”架构：

| Hermes 设计 | 对腰痹 CDSS 的启发 | 建议落点 |
|---|---|---|
| 条文级 `clause_id`、证据回源、CitationGuard | 腰痹不能只有规则 id，还要有医案片段、沈老经验出处、队列统计、指南/文献出处的统一证据对象 | 新增 `EvidencePacket` schema，贯穿全部 skill 与 agent 输出 |
| DeepResearcher 的 plan → subagent → critique → iterate | CDSS 不能一次性输出，应允许模型发现缺口后自动追问、补检索、重跑鉴别 | 把现有 `AutonomousQAAgent` 扩展为 bounded loop，而非固定 max 3 step |
| 多专家合议与独立 evidence packet | 不同子智能体应独立取证，再由 Judge 汇总，不要共享同一个规则结论造成“伪共识” | 拆分 Syndrome/Formula/Safety/Retrieval/PatientPreference/Guideline agents 的独立上下文 |
| Scope/quotation/citation 审计 | 输出中的每个证型、方剂、药物、剂量、风险声明均应可定位到证据来源或标注为模型推断 | 强化 `groundedness_skill` 为声明级 claim ledger |
| 研究平台的 goldset、diff、dashboard | 临床系统每次规则/模型/提示更新都应知道改变了哪些病例结论 | 新增 Decision Diff Agent 与 regression dashboard |

## 3. 当前系统的主要瓶颈

### 3.1 规则仍过度像“裁决器”

现有 `syndrome_router_skill`、`formula_base_selector_skill`、`conflict_checker_skill` 能给稳定解释，但在复杂病例中容易形成固定路径：先证型排序，再方路匹配，再安全检查。下一代 CDSS 应把这些结果变成**概率化、可反驳的候选假设**：

- 每个候选证型输出 `supporting_evidence`、`contradicting_evidence`、`missing_discriminators`、`prior_score`、`model_likelihood`、`calibrated_probability`。
- 方路不再写成“推荐路线”，而是写成 `candidate_intervention_frame`，附适用条件、反证条件、需复核条件。
- 冲突规则区分 `hard_stop`、`requires_confirmation`、`soft_warning`、`watch_item`，避免把教学性提醒误作临床禁令。

### 3.2 Agent loop 还不够“自我驱动”

当前 `AutonomousQAAgent` 已有 plan/execute/critique/replan，但 replan 主要针对安全与弃权。建议升级为通用 loop：

```text
while not converged and budget remains:
    Planner 读取病例状态、已有发现、critic gaps
    选择下一批 subagent tasks（可并行）
    Subagents 产出结构化 evidence packets
    Critics 评估：安全、证据充分性、矛盾、鉴别覆盖、角色边界、可行动性
    Judge 决定：继续追问 / 检索 / 输出预测集 / 中止转诊
```

需要注意：loop 不应让模型无限自由；限制应是**预算、角色、证据合约和输出守卫**，而不是固定规则路径。

### 3.3 缺少“病例状态图谱”作为共享记忆

当前 `case_state` 是字典式结构，足以服务规则引擎，但不利于下一代智能体对时间线、治疗反应、否定信息和不确定信息做推理。建议引入 `ClinicalStateGraph`：

- 节点：症状、体征、舌脉、影像/检查、既往病、用药、治疗反应、偏好、风险、证型假设、方路假设。
- 边：支持、反证、时间先后、因果假设、需要追问、来源于。
- 每个节点保留 `polarity`、`temporality`、`source_span`、`confidence`、`last_updated_turn`。
- 规则/模型/检索都只向图谱写入候选事实，不直接覆盖最终结论。

## 4. 具体修改建议

### P0：先把“硬规则裁决”改成“软约束假设层”

1. 新增 `backend/engine/hypothesis_engine.py`：把证型、方路、风险都建模为 `Hypothesis`，字段包括 `prior_score`、`evidence_for`、`evidence_against`、`missing_info`、`uncertainty_reason`、`recommended_next_action`。
2. 修改 `syndrome_router_skill`：保留现有规则命中，但输出从 `candidate score` 升级为 `hypothesis packet`；明确哪些分数来自规则先验、哪些来自病例证据富集、哪些来自模型补充解释。
3. 修改 `formula_base_selector_skill`：不再只返回 top formula；返回方路预测集，并为每个方路列出“适用前提/反证/待补问”。
4. 修改 `report_generation_skill` 与 `tao_consultation_skill`：输出措辞从“推荐/主方”统一改成“候选路径/需医师复核的经验框架”。

### P1：把 AutonomousQAAgent 升级为 Loop Agent

1. 新增 `backend/agents/loop_agent.py`，复用 Hermes `DeepResearcher` 思路，但面向临床任务：
   - `PlannerAgent`：根据病例状态和 critic gaps 选择任务。
   - `EvidenceSubagent`：调用规则、病例队列、文献/指南检索。
   - `DifferentialSubagent`：比较 top-N 证型/方路。
   - `SafetySubagent`：持续监测红旗、禁忌、角色边界。
   - `CriticAgent`：检查矛盾、未接地声明、过度确定、缺失鉴别。
   - `JudgeAgent`：决定继续追问、输出预测集、或中止转诊。
2. loop 终止条件：`safety_halt`、`clinician_ready`、`need_human_input`、`budget_exhausted`、`low_value_next_question`。
3. loop 输出必须包含 `rounds`、`tasks`、`observations`、`critic_findings`、`decision_state`，便于 UI 时间线展示。

### P1：强化 subagent 独立性，避免伪共识

当前 orchestrator 的多个 agent 多数读取同一黑板和上游结论。建议改为“双层黑板”：

- `private_workspace`：每个 subagent 独立上下文，只能看到任务、必要病例事实和自己的证据包。
- `shared_ledger`：只写入结构化结论、证据、置信度和自评，不共享自由文本推理。
- `ConsensusJudge`：汇总时检查不同 subagent 是否真正引用了不同证据来源，而不是复述同一个规则结果。

推荐新增 `agent_independence_score`：

```text
independence = unique_evidence_sources / total_claims
```

当独立性过低时，报告应提示“多智能体意见并非真正独立，不能视为强共识”。

### P1：建设病例检索与经验队列智能体

参考旧版 Yao-Bi 中的 `case_retrieval_skill.py`，现有系统已有“规则引擎 ↔ 队列高频方路”一致性概念，但下一步应升级为 case-based reasoning：

1. 建立脱敏病例向量/特征索引，严格去标识化，只保存结构化特征、标签、医师终审结论和随访结果。
2. 新增 `SimilarCaseAgent`：返回相似病例簇，而不是单条病例；显示相似点、关键差异和结局分布。
3. 与规则输出做三态 concordance：`corroborating`、`supplementary`、`divergent`。
4. divergent 不自动否定规则，也不自动否定模型，而是触发 critic：为什么规则与经验队列不同？是否证据缺失？是否病例亚型不同？

### P2：引入“动态问诊的信息增益 + 患者偏好”

现有 EIG 主动问诊可继续深化：

- 问题选择目标从“降低证型熵”扩展为多目标：红旗排除、鉴别价值、患者负担、隐私敏感度、可回答性、下一步临床可行动性。
- 每个追问给出 `expected_value` 与 `why_this_question_now`。
- 允许模型生成新问题，但必须绑定到 `field_hint`、`hypothesis_gap` 或 `safety_gap`；没有绑定则丢弃。
- 增加 `PatientPreferenceAgent`：收集职业、生活限制、就医可及性、治疗目标、风险偏好。该信息不决定处方，但影响医师决策包中的沟通建议和复核优先级。

### P2：把 groundedness 从“实体检查”升级为“声明级账本”

建议每个最终报告段落拆成 claim：

```json
{
  "claim": "本案存在寒湿阻络倾向",
  "claim_type": "syndrome_tendency",
  "support": ["case_span:...", "rule:R003", "cohort:..."],
  "counterevidence": ["case_span:否认畏寒"],
  "status": "supported | weakly_supported | inferred | unsupported",
  "patient_visible": false
}
```

输出到医师端时，`unsupported` 不是一律删除，而是标注“模型推断，需复核”；患者端则默认不展示。

### P2：新增 Decision Diff Agent

每次规则、提示词、模型或病例数据更新后，自动回答：

- 哪些 golden cases 的 top-1/top-2 证型改变？
- 哪些方路从 included 变为 excluded？
- 哪些安全告警等级变化？
- 改变是来自规则、模型、检索资料还是阈值？
- 是否需要专家复核或更新测试集？

这能避免系统越变越“聪明”但不可控。

### P3：多模型/多角色专家合议

面向未来可支持：

- `ClassicalTCMAgent`：偏经典方证与医案经验。
- `ModernOrthoAgent`：偏现代骨科/神经风险和检查路径。
- `PharmacologySafetyAgent`：偏药物相互作用与禁忌。
- `PatientCommunicationAgent`：偏患者可理解解释。
- `MethodologyCriticAgent`：专门找证据漏洞、过拟合、样本偏倚。

不同 agent 可使用不同模型或不同提示上下文。合议不是投票，而是由 `ConsensusJudge` 输出：共识点、分歧点、分歧原因、需要医师裁决的问题。


## 5. 专家经验 Skill 化：从“经验条文”到“可调用能力”

下一代系统应把沈老经验拆成一组可组合、可审计、可被模型自由调用的 **Experience Skills**，而不是把专家经验固化成单一路径规则。每个 skill 都应有统一合约：`when_to_call`、`inputs`、`outputs`、`evidence_contract`、`soft_constraints`、`hard_safety_bounds`、`patient_visibility`、`failure_mode`。

### 5.1 Skill 分层

| 层级 | Skill 类型 | 作用 | 软约束示例 |
|---|---|---|---|
| L0 安全底线 | `red_flag_screen`、`patient_request_guard`、`drug_risk_guard` | 患者安全、角色边界、急诊转诊 | 绝大多数为硬约束；但非急症风险可为 advisory |
| L1 经验识别 | `shen_pattern_signal_skill`、`pain_phenotype_skill`、`tcm_four_diagnosis_skill` | 从病例中识别沈老经验信号和中医四诊证据 | “寒湿倾向”“瘀阻倾向”仅作为候选信号 |
| L2 假设生成 | `experience_hypothesis_skill`、`syndrome_hypothesis_skill`、`formula_frame_skill` | 生成证型/治法/方路假设集合 | 输出 top-N 预测集，不强行唯一裁决 |
| L3 鉴别与反证 | `differential_skill`、`counterevidence_skill`、`conflict_audit_skill` | 找反证、互斥、需补问点 | 反证触发降置信或追问，不自动否定 |
| L4 个体化适配 | `comorbidity_medication_skill`、`preference_skill`、`followup_response_skill` | 合并病、用药、患者偏好、疗效反馈 | 只生成复核建议和风险提示，不给患者可执行处方 |
| L5 解释与交接 | `clinician_reasoning_skill`、`patient_education_skill`、`handoff_skill` | 医师决策包、患者解释、复诊摘要 | 医师端可深，患者端必须降权、去处方化 |

### 5.2 ExpertExperienceSkill 合约

```python
@dataclass
class ExpertExperienceSkill:
    skill_id: str
    expert_source: str
    capability: Literal[
        "extract_signal", "generate_hypothesis", "differentiate",
        "compose_frame", "audit_safety", "explain", "ask_followup"
    ]
    when_to_call: list[str]
    required_inputs: list[str]
    optional_inputs: list[str]
    output_schema: str
    evidence_contract: list[str]
    soft_constraints: list[str]
    hard_safety_bounds: list[str]
    allowed_roles: list[Literal["patient", "clinician", "researcher"]]
    can_call_tools: bool = False
    can_delegate_subagents: bool = False
```

### 5.3 推荐新增/改造的专家经验 skills

读片/检验检查应是独立 skill，而不是埋在神经骨科问诊里：`imaging_report_skill` 读取腰椎 MRI/CT/X 线正式报告、检验检查摘要或影像附件线索，输出结构损害、神经压迫、感染/肿瘤/骨折/马尾等红旗影像信号、与沈医师腰痹经验的关系、以及下一轮需核对的问题。推荐生产读片模型走 Poe API 并配置 `TAO_MODEL_ID=Gemini-3.1-Pro`；中国内地部署可使用 MiniMax，国际部署可用 OpenAI/Azure/Anthropic。无论何种模型，影像/检验只作为现代医学风险与鉴别证据，不替代正式报告、不单独裁定证型或处方。

1. `shen_experience_signal_skill`：把“沈老经验线索”拆成疼痛部位、寒热、瘀象、虚损、痹阻、夹湿、久病入络等多维信号，输出 evidence packet。
2. `experience_hypothesis_skill`：根据经验信号生成候选“经验辨证框架”，但必须同时输出反证和缺失信息。
3. `formula_frame_skill`：不直接给方，而是生成“方路框架 + 适用条件 + 禁忌/慎用 + 需医师复核点”。
4. `counterevidence_skill`：专门寻找与当前证型/方路假设相冲突的症状、否定描述、合并病和药物。
5. `followup_strategy_skill`：根据 hypothesis gaps 生成下一轮问诊目标；模型可自由生成自然语言问题，但必须绑定到 gap id。
6. `experience_adaptation_skill`：处理疗效反馈和复诊变化，如疼痛减轻但麻木未改善、寒象消退但瘀象仍在等，输出“调整方向候选”，不输出患者可执行加减。
7. `clinician_decision_package_skill`：面向医生汇总候选假设、证据、反证、队列一致性、风险、待确认问题。

## 6. 模型自由规划的 Agentic CDSS 模式

用户不应被迫按固定表单提问。建议把入口改成“用户自由提问 → 模型理解意图 → 自主选择 skill/tool/subagent/loop/graph”的 agentic pattern：

```text
User asks freely
  ↓
Intent + Role + Scope gate
  ↓
Planner sees: user question, ClinicalStateGraph, skill registry, tool registry, budget, safety policy
  ↓
Planner emits TaskGraph, not a fixed sequence
  ↓
Executor runs tool calls / skill calls / subagent delegations / graph updates
  ↓
Critics inspect safety, grounding, contradictions, uncertainty, usefulness
  ↓
Judge decides: answer now, ask follow-up, retrieve more, delegate specialist, abstain, or safety halt
```

### 6.1 TaskGraph 而非固定 pipeline

Planner 输出应从 `list[step]` 升级为 `TaskGraph`：

```python
@dataclass
class AgentTask:
    task_id: str
    task_type: Literal["skill", "tool", "subagent", "graph_query", "graph_update", "critic", "judge"]
    target: str
    input_refs: list[str]
    depends_on: list[str]
    expected_output: str
    stop_if: list[str]
    rationale: str
```

TaskGraph 支持：

- **并行**：安全筛查、病例结构化、经验信号提取可并行执行。
- **条件分支**：红旗阳性则停止临床推理；证据不足则进入问诊 loop；证据冲突则调用 counterevidence/differential subagent。
- **图谱读写**：每个 skill 不只返回文本，还更新 `ClinicalStateGraph`。
- **动态重排**：critic 发现未接地声明后，planner 可插入 retrieval 或 evidence binding 任务。

### 6.2 自主问诊 loop

自主问诊不应只是“下一题生成器”，而应是模型围绕假设缺口持续优化信息采集：

```text
Loop state: hypotheses + graph + answered questions + safety status
1. Identify highest-value uncertainty gap
2. Generate candidate questions
3. Score questions by information gain, safety, burden, answerability
4. Ask 1–3 questions
5. Update graph with answer, including negation/uncertainty/temporality
6. Re-score hypotheses
7. Stop when ready_for_clinician or more questions are low-value
```

每个问题必须说明：`question_text`、`target_gap`、`expected_information_gain`、`what_answer_would_change`、`patient_friendly_reason`。这样模型是“会问诊的智能体”，不是机械清单。

### 6.3 自主诊疗建议 loop（医师端）

医师端的“诊疗建议”应被定义为 **clinician decision support package**，不是自动处方：

1. `GenerateHypotheses`：生成证型/现代风险/方路/检查建议候选集。
2. `BindEvidence`：为每个候选绑定病例片段、规则、队列、文献或模型推断来源。
3. `FindCounterevidence`：主动找反证和不适用条件。
4. `PersonalizeFrame`：结合年龄、合并病、用药、偏好、疗效反馈形成复核重点。
5. `SafetyAudit`：药物、红旗、患者端边界、特殊人群。
6. `CritiqueDraft`：检查过度确定、未接地、遗漏鉴别、伪共识。
7. `ReviseOrAsk`：若不合格，自动追问或补检索；若合格，输出候选决策包。

输出格式建议：

```json
{
  "decision_support_package": {
    "hypothesis_set": [],
    "candidate_care_frames": [],
    "safety_review": {},
    "questions_before_action": [],
    "counterevidence": [],
    "claim_ledger": [],
    "clinician_review_required": true,
    "patient_visible_summary": "...去诊断/去处方化解释..."
  }
}
```

## 7. Graph：让病例、经验和推理成为可更新知识图

建议新增 `ClinicalExperienceGraph`，连接三类图：

1. **Case Graph**：患者本案事实与时间线。
2. **Experience Graph**：沈老经验信号、证型、治法、方路、药物模块之间的软连接。
3. **Decision Graph**：本轮智能体生成的假设、证据、反证、追问、医师反馈。

Graph 的价值是让模型可以查询“为什么现在不能下结论”“哪些节点冲突”“哪个问题最能区分两个假设”。例如：

```text
MATCH (h:Hypothesis)-[:MISSING]->(g:Gap)
WHERE h.rank <= 3 AND g.expected_information_gain > 0.2
RETURN g.question_target, h.label
```

不要求一开始上复杂图数据库；可先用内存 dataclass + JSON 序列化，未来再迁移到图存储。


## 8. 建议的数据与接口契约

### 8.1 EvidencePacket

```python
@dataclass
class EvidencePacket:
    source_type: Literal["case_span", "rule", "cohort", "guideline", "classic", "model_inference"]
    source_id: str
    quote_or_summary: str
    supports: list[str]
    contradicts: list[str]
    reliability: Literal["high", "moderate", "low", "unknown"]
    patient_visible: bool
```

### 8.2 HypothesisPacket

```python
@dataclass
class HypothesisPacket:
    hypothesis_id: str
    label: str
    domain: Literal["syndrome", "formula_route", "risk", "next_action"]
    prior_score: float
    posterior_score: float | None
    uncertainty: str
    evidence_for: list[EvidencePacket]
    evidence_against: list[EvidencePacket]
    missing_discriminators: list[str]
    soft_constraints: list[str]
    hard_constraints: list[str]
    clinician_review_required: bool = True
```

### 8.3 LoopDecision

```python
@dataclass
class LoopDecision:
    state: Literal["continue", "ask_followup", "ready_for_clinician", "safety_halt", "abstain"]
    reason: str
    next_tasks: list[str]
    budget_snapshot: dict
    confidence_summary: dict
```

## 9. UI/产品形态建议

1. **时间线面板**：展示 loop 每轮 planner 选择、subagent 输出、critic 发现、judge 决定。
2. **假设对比面板**：top-N 证型/方路并排，显示支持、反证、缺失信息、队列一致性。
3. **证据账本面板**：每个声明可展开证据来源，区分规则、病例片段、队列统计、模型推断。
4. **追问价值面板**：告诉医师/患者为什么现在问这个问题，以及回答会改变什么。
5. **医师反馈面板**：反馈不仅是 thumbs up/down，还应要求选择误差类型：抽取错、否定识别错、证据不足、规则不适用、模型过度推断、患者端措辞不当。

## 10. 评测与治理建议

下一代 CDSS 评测不能只看 top-1 准确率，应增加：

- 预测集覆盖率与平均集合大小。
- 红旗召回率、误报率、否定语义鲁棒性。
- 追问信息增益：回答前后熵下降、医师认为有用比例。
- 声明级接地率：supported / weakly_supported / inferred / unsupported 比例。
- loop 收敛率：平均轮数、预算耗尽率、低价值追问率。
- subagent 独立性：独立证据源比例。
- 医师反馈采纳率与错误归因分布。
- Decision Diff 稳定性：更新后关键安全输出是否无意漂移。

## 11. 推荐实施路线

### 第 1 阶段：结构化软约束

- 新增 `EvidencePacket`、`HypothesisPacket`。
- 改造证型和方路输出为 hypothesis packets。
- 报告统一改成候选、倾向、预测集、复核点，减少确定性裁决口吻。

### 第 2 阶段：Loop Agent

- 新增 `loop_agent.py`。
- 把现有 critics 接入 round-based loop。
- UI 展示 rounds / critic gaps / replan decisions。

### 第 3 阶段：病例检索与相似队列

- 在合规前提下建立脱敏结构化病例索引。
- SimilarCaseAgent 输出簇级证据和 concordance。
- divergent 触发自动复核 loop。

### 第 4 阶段：声明级接地与决策 diff

- 把 final report 拆 claim ledger。
- 新增 Decision Diff Agent。
- CI 中加入 golden case diff 报告。

### 第 5 阶段：多模型专家合议

- 支持不同 agent 独立上下文、独立模型、独立 evidence packet。
- ConsensusJudge 输出共识/分歧/医师裁决问题。

## 12. 关键原则

1. **硬约束只保留在安全、隐私、角色边界和审计层**。
2. **临床知识规则全部尽量软化为可解释先验、反证条件和复核点**。
3. **模型不是润色器，而是 planner、hypothesis generator、critic 和 communication agent**。
4. **subagent 要有独立证据包，避免同源复述造成虚假合议**。
5. **loop 要真实改变下一步行动：追问、补检索、重排假设、弃权或转诊**。
6. **所有智能输出都必须能被医师看到“为什么、凭什么、哪里不确定、下一步问什么”**。

