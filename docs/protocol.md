# YaoBi-Skill Protocol

## 定位

YaoBi-Skill 是“确定性规则引擎 + LLM 教学解释 + 医生复核”的轻量化 Hermes 风格智能体项目。系统服务于名老中医腰痹医案研究、教学训练、处方经验挖掘与科研标注。

## 非处方化边界

- 不做最终诊断。
- 不给患者可执行处方。
- 不输出“请按此方服用”。
- 所有方剂、药物、剂量内容均标注为历史经验规则或教学解释。
- 附片、细辛、虫类药、乌头类药物必须提示不可自行使用。

## Skill 总线

1. `case_extract_skill`：只抽取字段，不诊断。
2. `case_normalize_skill`：把原始表述转为规则标签。
3. `syndrome_router_skill`：按 YAML 规则给候选证型评分。
4. `formula_base_selector_skill`：输出方剂路线信号，不生成处方。
5. `herb_module_composer_skill`：输出药物模块，不合成完整处方。
6. `conflict_checker_skill`：检查路线与药物模块冲突。
7. `safety_guard_skill`：识别红旗、特殊药物和合规风险。
8. `report_generation_skill`：生成固定结构 Markdown 报告。

## 患者问诊导引状态机

```yaml
states:
  S0_CONSENT:
    goal: 知情提示、非诊疗声明、隐私脱敏
    next: S1_REDFLAG
  S1_REDFLAG:
    goal: 排除需要立即就医的危险信号
    next_if_safe: S2_BASIC
    next_if_danger: S_EMERGENCY_NOTICE
  S2_BASIC:
    goal: 采集年龄、性别、职业、主诉、病程
    next: S3_PAIN_PROFILE
  S3_PAIN_PROFILE:
    goal: 采集疼痛部位、性质、程度、诱因、缓解因素
    next: S4_NEURO_ORTHO
  S4_NEURO_ORTHO:
    goal: 采集放射痛、麻木、无力、大小便、影像诊断
    next: S5_TCM_CORE
  S5_TCM_CORE:
    goal: 采集中医寒热、湿、气血、舌象、脉象等信息
    next: S6_SHEN_SIGNAL
  S6_SHEN_SIGNAL:
    goal: 针对沈老经验规则补问高价值变量
    next: S7_COMORBIDITY
  S7_COMORBIDITY:
    goal: 采集骨质疏松、糖尿病、高血压、NSAIDs、肌松药等
    next: S8_ADAPTIVE_REPAIR
  S8_ADAPTIVE_REPAIR:
    goal: 动态补问缺失字段
    next: S9_CASE_SUMMARY
  S9_CASE_SUMMARY:
    goal: 生成医案草稿，让患者确认
    next: S10_FINAL_REPORT
  S10_FINAL_REPORT:
    goal: 输出标准化医案、标签、规则命中、医生复核清单
```
