# Colab 一键复现 · 真·Tao 在环 UI（含 ngrok 公网）

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/pariskang/Yao-Bi-Agent/blob/claude/focused-planck-3dv9we/colab/YaoBi_Skill_Colab.ipynb)

[`YaoBi_Skill_Colab.ipynb`](YaoBi_Skill_Colab.ipynb) 在 Google Colab 上一键复现全部功能，**前端 UI 通过后端 API 真正调用语言模型（Tao）自主选择并调用 skill、自主问诊**，并经 **ngrok** 暴露为公网链接。

## 它和"纯静态"版的区别

纯静态前端把路由/规划/追问都用浏览器端关键词规则模拟——"Tao 选择 / Tao 在环"只是标签。本笔记本启动 **`backend.server`**（零额外依赖的 stdlib HTTP 服务，同源提供 UI + `/api/*`），前端改为调用真实端点：

| UI 模块 | 端点 | 语言模型真实职责 |
|---|---|---|
| 智能问答 | `POST /api/chat` | `route_skill` 在受限技能集内**真实选择** skill（JSON 修复 + 越界回退） |
| 自主多步 | `POST /api/autonomous` | `plan_skills` **真实规划**多步并委派子智能体 |
| Tao 自动追问 | `POST /api/followup_probe` | 规则约束内**真实生成**澄清式追问（经 Output Guard） |
| 智能体协作 | `POST /api/collaboration` | `ReasoningAgent`/`ExperienceAgent` **真实调用 Tao** |
| 经验推理/总结 | `POST /api/reasoning` `…/summary` | `physician_reasoning_skill` / `case_experience_summary_skill` 真实润色 |

UI 右上角显示**真实运行时徽章**（在线后端 + 模型名）；只有模型真正路由时才标 `Tao 选择 ✓`，否则如实标 `关键词回退`/`离线`。

## 用法

1. 点上方 **Open In Colab**。建议先在「运行时 → 更改运行时类型」选 **GPU（A100/L4）**。
2. 依次运行：
   - **①** 克隆 + 基础依赖
   - **②** 选 Tao 运行时（默认 **Dao1-30B 本地 4-bit**；备选：小模型免费 T4 / 外部 HTTP / mock）
   - **③** ngrok authtoken
   - **④** ★ 启动服务并取公网链接
   - **⑤** 预热 30B 模型（首次下载较慢）
   - **⑥** 验证 `method=llm`（模型真实路由）
   - **⑦–⑩** 规则 CLI、全量测试、脱敏挖掘、清理

## Tao 运行时（通过环境变量切换，`DaoClient` 消费）

| 变量 | 说明 |
|---|---|
| `TAO_BACKEND` | `transformers`（本地）/ `http`（OpenAI 兼容）/ `mock` / `disabled` |
| `TAO_MODEL_ID` | 默认 `CMLM/Dao1-30b-a3b`；可换 `Qwen/Qwen2.5-3B-Instruct` 等小模型 |
| `TAO_LOAD_IN_4BIT` / `TAO_LOAD_IN_8BIT` | 量化加载（让 30B 适配单卡 A100/L4，需 `bitsandbytes`） |
| `TAO_ENDPOINT_URL` / `TAO_API_KEY` | `http` 后端的接口与密钥 |

## 安全边界（服务端强制，不变）

语言模型只负责**选择/编排/改写技能**；最终诊断、完整处方、患者可执行剂量由 `patient_request_guard` 与 Output Guard 拦截，违规回退确定性规则。仅供研究/教学/医师复核。

## 没有 GPU？

在 **②** 改用 `TAO_BACKEND=mock`（验证 UI 与管线）或小模型（`Qwen/Qwen2.5-3B-Instruct`，免费 T4 可跑），或 `http` 指向你自己的推理服务。前端会如实显示当前运行时。
