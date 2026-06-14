# YaoBi-Skill：沈钦荣腰痹经验规则智能体

**English:** Shen-Qinrong YaoBi Rule Agent

YaoBi-Skill 是一个面向名老中医腰痹医案研究的轻量化规则智能体项目。系统通过结构化医案抽取、沈钦荣经验规则匹配、方剂模块解释、安全审查与 Dao1-30b-a3b 中医语言生成能力，将隐性诊疗经验转化为可追溯、可审核、可教学的规则化知识系统。

> **用途边界：** 本项目仅用于名老中医经验研究、医案复盘、教学训练、处方经验挖掘与科研标注，不构成诊断、处方或治疗建议，不提供患者自用方案。

## 架构原则

```text
Case Intake 表单 / 医案文本输入
  ↓
case_extract_skill：结构化抽取
  ↓
case_normalize_skill：标签标准化
  ↓
syndrome_router_skill：证型候选规则评分
  ↓
formula_base_selector_skill：方剂路线匹配
  ↓
herb_module_composer_skill：非处方药物模块解释
  ↓
conflict_checker_skill：互斥与冲突检查
  ↓
safety_guard_skill：红旗与合规安全审查
  ↓
report_generation_skill：研究/教学报告生成
```

核心原则：**Rule-first、Evidence-traceable、Doctor-reviewable、Non-prescriptive**。

## Dao1-30b-a3b 角色

Dao1-30b-a3b 仅用于中医理论解释、方义说明、规则命中结果转写成教学报告、医案语言润色与不确定性说明。规则判断由确定性规则引擎完成，模型不得直接输出临床诊断、患者可执行处方或剂量医嘱。v0.2 新增可选 Tao Runtime：默认关闭，支持 mock/http/transformers 后端；模型输出必须是 JSON object，经过 JSON repair 与 forbidden-output guard 后，才会叠加到确定性规则报告，否则自动回退确定性模板。v0.4 增加 `DaoClient.chat()` 直接 Transformers 推理入口，可按 Dao1 示例直接加载 `CMLM/Dao1-30b-a3b` 并使用 `TextIteratorStreamer` 流式输出，无需 FastAPI 包装。

## 快速开始

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
python -m backend.main --text "患者女，68岁，腰痛反复5年，加重1月，伴下肢麻木，畏寒，舌暗苔白腻，脉细缓，既往骨质疏松。"

# 可选：启用 Tao Runtime 叠加解释；若未配置或输出不安全，会自动回退确定性报告
TAO_BACKEND=mock python -m backend.main --text "患者女，68岁，腰痛反复5年。" --use-llm

# 直接本地加载 Dao1/Tao（不封装 FastAPI），按模型卡风格使用 Transformers + streamer
TAO_BACKEND=transformers TAO_MAX_NEW_TOKENS=512 python -m backend.main --tao-chat "请基于规则线索解释本案" --stream
```


## 自动问诊：YaoBi-CaseGuide Skill

本项目现在同时包含 `YaoBi_CaseGuide_Hermes_Agent`，用于自动导引患者生成高质量腰痹医案。该模块提供 12 个问诊 Skill：知情脱敏、红旗筛查、主诉生成、疼痛特征、神经骨科、中医四诊、沈老规则信号、合并病用药、动态补问、医案结构化、质量评分和医生交接。

`CaseGuideSession` 按有限状态机运行，默认每个状态最多 3 轮追问、每轮最多返回 1–3 个高价值问题；追问预算可配置（`CaseGuideSession(max_followups_per_state=N, questions_per_turn=M)` 或运行中 `set_max_followups(N)` / `set_questions_per_turn(M)`）。每轮都会叠加上一轮答案、当前规则标签、沈老经验信号、候选证型和方剂路线信号深化补问。v0.3 支持可选 Tao 问诊叠加：确定性规则先给出候选问题 id，Tao 只能在 JSON 合约内重排、患者友好化改写和解释追问理由，不能新增问题 id、诊断、处方或剂量；失败或违规则回退规则问题。v0.4 新增自主问诊驱动器 `run_scripted_interview(answers)`：状态机自主推进全部问诊状态，无可答问题或追问预算用尽时自动终止当前状态的追问，并返回完整 transcript 供审计回放。调用方也可通过 `end_current_state()` 手动结束当前状态进入下一状态；红旗问题未答完时（任何方式）不允许离开红旗筛查状态，若命中 urgent 会硬停止后续问诊并提示线下/急诊评估。最终输出标准化医案、结构化标签、风险提示、沈老经验规则线索和医生复核清单。

> 若用户要求“诊断和处方”，系统只输出候选证型/方剂路线信号与药物模块解释，并全部标注为“待医生复核/非处方”；不得生成最终诊断、临床处方、患者自服剂量或替代医生治疗建议。



## xlsx 医案规则挖掘（脱敏）

`backend/mining/xlsx_case_miner.py` 可将门诊 xlsx 导出转化为可审核的候选规则：

```bash
pip install .[mining]
python -m backend.mining.xlsx_case_miner --xlsx data/private/门诊导出.xlsx \
    --yaml rules/11_mined_rule_candidates.yaml --frontend frontend/mined_rules.js
```

- **脱敏优先**：姓名、病案号、地址、医师工号、就诊序号在内存中即被丢弃，自由文本只做关键词扫描后丢弃；产物仅含聚合统计与 xlsx 行号引用。原始 xlsx 放在 `data/private/`（已 gitignore，`*.xlsx` 全局禁入仓库）。
- **挖掘内容**：证型/症状/西医诊断分布、药物频次、功效模块、签名方剂命中（独活寄生汤、当归四逆汤、桂枝芍药知母汤、黄芪桂枝五物汤、小柴胡类、四物/八珍底盘）、症状↔方药关联规则（support/confidence/lift）、重点药物剂量分布（细辛、附片、全蝎、蜈蚣、麻黄等）。
- **审核边界**：所有候选规则 `status: pending_expert_review`、`clinician_only: true`，仅作为医师端研究证据由 `mined_evidence_skill` 注入 `final_report`，不参与自动决策、不向患者输出；剂量分布仅为经验研究信号，不构成可执行剂量。
- **数据质量诚实声明**：门诊导出的"中医四诊"栏多为模板文本，舌脉信息不可用于挖掘，产物中以 `data_quality.tongue_pulse_usable=false` 明示。

## 多智能体自主协作编排

`backend/agents/` 把原本"顺序调用 skill"的隐式流程，显式化为"多个智能体在共享黑板上自主协作"：

- **共享黑板**（`Blackboard`）：智能体的共享工作记忆与消息载体；上游智能体写入结论，下游读取并续接，形成自主接力。
- **智能体编排器**（`AgentOrchestrator`）：按依赖顺序运行 11 个智能体——`CaseStructuringAgent → RedFlagAgent → OrthoRiskAgent → TcmSyndromeAgent → FormulaReasoningAgent → HerbModuleAgent → ConflictSafetyAgent → EvidenceTraceAgent → ReasoningAgent → ExperienceAgent → PhysicianReviewAgent`，并记录完整 `collaboration_trace`（角色、规则/语言模型、置信度、证据、语言模型守卫状态、显式 handoff）。
- **自主控制流**：`RedFlagAgent` 命中急诊红旗时**自主中止**下游临床智能体（其余记为 skipped），仅 `EmergencyNoticeAgent` 续跑——这是基于内容的真实自主决策，而非固定流水线。
- **语言模型在环**：仅 `ReasoningAgent`、`ExperienceAgent` 调用 Tao，且每个智能体都声明 `used_llm` 与语言模型运行时/守卫状态；其余为确定性规则智能体。
- **人类终审**：`PhysicianReviewAgent` 仅装配草案，最终诊断/处方/剂量交执业医师签名。

每个智能体只是**包装已有的、经测试的 skill**，因此确定性输出仍是事实来源，语言模型输出仍受守卫且可选。`CaseGuideSession.run_agent_collaboration()` 是独立入口；`final_report()` 现以编排器为唯一"大脑"，在保留全部既有返回键的同时附带 `agent_collaboration` 协作轨迹。UI 左侧「智能体协作」模块以时间轴可视化整个协作过程。

## Tao 模型增强：自动追问 / 经验推理 / 经验总结

在“确定性规则为准、Tao 仅叠加、失败回退”的统一安全管线下（JSON Repair + Output Guard），新增三项基于 Tao 的能力：

1. **规则约束内自动追问**（`tao_followup_probe_skill`）：与只能重排/改写既有规则问题的 `tao_question_planner_skill` 不同，本技能允许 Tao 在“当前状态临床主题”内**生成新的澄清式追问**，但施加硬约束——只在临床内容状态启用（红旗筛查/知情/人口学不开放生成式追问）、每轮最多 `tao_probe_budget` 个、`field_hint` 必须取自本状态允许字段或为 null、**不驱动状态跳转**（仅作为补充线索记入 `tao_probe_answers`）、出现诊断/处方/剂量即整轮作废回退。`CaseGuideSession(use_llm_questions=True, tao_probe_budget=2)` 开启。
2. **医师经验辨证推理**（`physician_reasoning_skill`）：先由规则构建确定性推理链（症状/标签 → 证候倾向 → 治法 → 方剂路线 → 药物模块 → 安全复核 → 沈老经验信号），Tao 仅把推理链“语言化”为辨证教学解释，不得新增规则层没有的证型/方剂/药物，全部为倾向性、非最终口吻；患者角色一律拦截。
3. **案例经验总结自动生成**（`case_experience_summary_skill`）：`mode="case"` 生成单案「医案按语」，`mode="experience"` 基于脱敏挖掘统计生成「经验规律总结」；确定性总结为事实来源，Tao 仅润色，不得新增数据外结论，不得产出最终诊断/可执行处方/剂量。

三项能力均以 `draft_for_clinician_review`、`patient_visible=false` 输出，并随 `final_report` 一并返回。UI 在左侧导航新增「经验推理」「经验总结」模块，问诊页提供「Tao 自动追问」开关，最终报告新增「经验推理」「经验按语」标签页。

## CDSS 草案模块

项目新增 `cdss_recommendation_skill`，用于医生端 CDSS 自动生成候选诊断、候选证型、方剂路线和药物模块草案。该草案状态固定为 `draft_for_clinician_review`，不是最终诊断、不是签名处方、不是患者可见医嘱，也不会生成患者可执行剂量；最终医嘱仍需 `physician_review_skill` 医师手工录入并签名。

## 医师审核模块

项目新增 `physician_review_skill` 作为医生端审核闭环：模型/规则只生成医案、鉴别方向、候选证型、方剂路线信号和药物模块解释；最终诊断、完整处方、剂量、煎服法和疗程只能由 `licensed_physician` 手工录入、签名并锁定，系统会拒绝模型生成的最终诊断或处方。

## Hermes 风格编排

智能体配置位于 [`config/hermes_agent.yaml`](config/hermes_agent.yaml)，工具 schema 位于 [`config/hermes_tools.json`](config/hermes_tools.json)。默认调用顺序为：

1. `case_extract_skill`
2. `case_normalize_skill`
3. `syndrome_router_skill`
4. `formula_base_selector_skill`
5. `herb_module_composer_skill`
6. `conflict_checker_skill`
7. `safety_guard_skill`
8. `report_generation_skill`

## 目录结构

```text
config/          Hermes、模型和安全配置
rules/           YAML 规则库（含 11_mined_rule_candidates.yaml 挖掘候选规则）
backend/         轻量 Python 技能、规则引擎和 CLI
backend/agents/  多智能体编排层：共享黑板、智能体定义、AgentOrchestrator 协作轨迹
backend/llm/     Dao1/Tao Runtime、JSON repair、输出安全校验与提示模板
backend/mining/  xlsx 医案脱敏挖掘管道（频次/关联规则/签名方剂/剂量分布）
frontend/        零依赖静态 UI：总览看板、智能问诊、规则挖掘、证据回溯、医师审核、评估与安全、设置
data/private/    本地原始 xlsx（gitignore，绝不入库）
docs/            Protocol、UI 与安全政策
tests/           规则、安全、挖掘与前端回归测试
```


## 功能完整性审核

详细审核见 [`docs/final_functionality_audit.md`](docs/final_functionality_audit.md)。结论：当前项目是研究/CDSS MVP 的核心功能实现，不是临床产品意义上的“完美完成”；真实生产仍需前端、API、持久化、LLM 服务、专家验证、安全工程和合规审查。

## 免责声明

本项目输出的方剂、药物、剂量与加减信息只能作为历史医案经验规律、教学分析或规则命中解释。附片、细辛、虫类药、乌头类药物等均需医生审核，不可自行使用。
