# Colab 一键复现（含 ngrok 公网 UI）

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/pariskang/Yao-Bi-Agent/blob/claude/focused-planck-3dv9we/colab/YaoBi_Skill_Colab.ipynb)

[`YaoBi_Skill_Colab.ipynb`](YaoBi_Skill_Colab.ipynb) 在 Google Colab 上**一键复现 YaoBi-Skill 的全部功能**，并通过 **ngrok** 把完整 UI 暴露为**公网链接**。

## 用法

1. 点上方 **Open In Colab** 徽章打开笔记本。
2. 从上到下依次运行单元格：
   - **①** 克隆仓库 + 安装依赖（核心依赖仅 `pyyaml`）。
   - **②** 填入 ngrok authtoken（免费注册：<https://dashboard.ngrok.com/get-started/your-authtoken>）。
   - **③** ★ 启动 UI 并打印**公网链接** `https://xxxx.ngrok-free.app`，点开即是完整界面。
   - **④–⑨** 复现后端 CLI、多智能体协作、全量测试（85 项）、脱敏挖掘、Tao 叠加。
3. 没有 ngrok token？运行 **③-B**，用 Colab 内置端口代理同样能打开 UI。

## 复现了什么

- **完整前端 UI**：11 个模块——总览看板、智能问诊（FSM）、智能问答、智能体协作、经验推理、经验总结、规则挖掘、证据回溯、医师审核、评估与安全、设置。
- **后端全部能力**：规则引擎、Plan → 子智能体委派 → 综合（ReAct / Plan-and-Execute）、CaseGuide 有限状态机、xlsx 脱敏挖掘、JSON Repair + Output Guard、可选 Tao（`CMLM/Dao1-30b-a3b`）大模型叠加。

## 说明

- 前端是**零依赖静态 SPA**，所有逻辑在浏览器端自洽运行、不依赖后端 API；因此"复现 UI" = 用 `http.server` 托管 `frontend/` 目录并经 ngrok 映射公网。
- 笔记本默认克隆 `main` 分支；如需特定分支，在 **①** 单元格修改 `BRANCH` 变量。
- ngrok 免费版首次访问会出现确认页，点 **Visit Site** 即可进入。
- **用途边界**：仅用于研究、教学与医师复核，不输出最终诊断、完整处方或患者可执行剂量。
