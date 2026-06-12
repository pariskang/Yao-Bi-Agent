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
config/       Hermes、模型和安全配置
rules/        YAML 规则库
backend/      轻量 Python 技能、规则引擎和 CLI
backend/llm/  Dao1/Tao Runtime、JSON repair、输出安全校验与提示模板
docs/         Protocol、UI 与安全政策
tests/        规则与安全回归测试
```


## 功能完整性审核

详细审核见 [`docs/final_functionality_audit.md`](docs/final_functionality_audit.md)。结论：当前项目是研究/CDSS MVP 的核心功能实现，不是临床产品意义上的“完美完成”；真实生产仍需前端、API、持久化、LLM 服务、专家验证、安全工程和合规审查。

## 免责声明

本项目输出的方剂、药物、剂量与加减信息只能作为历史医案经验规律、教学分析或规则命中解释。附片、细辛、虫类药、乌头类药物等均需医生审核，不可自行使用。
