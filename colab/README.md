# Colab 一键复现 · 下一代 YaoBi Agent UI（含 ngrok 公网）

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/pariskang/Yao-Bi-Agent/blob/main/colab/YaoBi_Skill_Colab.ipynb)

本目录提供两种 Colab 启动方式：

1. **点击上方徽章打开 Notebook**：适合交互式逐步运行。
2. **直接运行脚本**：适合复制到 Colab 单元格后一键启动完整 UI：

```bash
!git clone --depth 1 https://github.com/pariskang/Yao-Bi-Agent.git /content/Yao-Bi-Agent
%cd /content/Yao-Bi-Agent
!python colab/launch_yaobi_colab.py --backend mock --ngrok-token "$NGROK_AUTHTOKEN" --no-preload
```

启动完成后脚本会打印：

- `local`：Colab VM 内本地地址；
- `public`：ngrok 公网 HTTPS 地址，可直接分享给医师端体验；
- `provider`：当前 Tao/LLM 后端与模型名；
- `yaobi_server.log`：后端日志，便于排查模型加载、API Key、端点超时等问题。

## 完整功能覆盖

脚本启动的是 `backend.server`，同源提供前端 UI 与 `/api/*`：

| UI/能力 | 端点/模块 | Colab 中是否可用 |
|---|---|---|
| 智能问答 | `POST /api/chat` | ✅ |
| 自主多步规划 | `POST /api/autonomous` | ✅ |
| 下一代 Agent 控制台 | `POST /api/agentic` | ✅ TaskGraph、subagent、loop、critic、judge、ClinicalExperienceGraph |
| 对话式问诊 | `POST /api/interview` | ✅ 多轮槽位抽取、红旗硬停、模型追问 |
| 读片/检验报告 | `imaging_report_skill` | ✅ 可由下一代 Agent 或问答路由调用 |
| 智能体协作 | `POST /api/collaboration` | ✅ ReasoningAgent / ExperienceAgent 等 |
| Tao 自动追问 | `POST /api/followup_probe` | ✅ |
| 经验推理/总结 | `POST /api/reasoning`、`/api/summary` | ✅ |
| 医师反馈闭环 | `POST /api/feedback` | ✅ |

## 多 Provider 运行示例

`launch_yaobi_colab.py` 通过环境变量/CLI 参数配置 `DaoClient`，同一个 UI 流程可切换不同供应商：

```bash
# 1) 免费快速验证完整 UI 与后端流程（无外部 API）
!python colab/launch_yaobi_colab.py --backend mock --ngrok-token "$NGROK_AUTHTOKEN" --no-preload

# 2) Poe：读片/报告叠加可选择 Gemini-3.1-Pro
!python colab/launch_yaobi_colab.py --backend poe --model-id Gemini-3.1-Pro --api-key "$POE_API_KEY" --ngrok-token "$NGROK_AUTHTOKEN" --no-preload

# 3) MiniMax（中国内地网络环境常用）
!python colab/launch_yaobi_colab.py --backend minimax --model-id abab6.5s-chat --api-key "$MINIMAX_API_KEY" --ngrok-token "$NGROK_AUTHTOKEN" --no-preload

# 4) Azure OpenAI
!python colab/launch_yaobi_colab.py --backend azure --azure-endpoint "$AZURE_OPENAI_ENDPOINT" --azure-deployment "$AZURE_OPENAI_DEPLOYMENT" --api-key "$AZURE_OPENAI_API_KEY" --ngrok-token "$NGROK_AUTHTOKEN" --no-preload

# 5) OpenAI / Anthropic / OpenAI-compatible HTTP
!python colab/launch_yaobi_colab.py --backend openai --model-id gpt-4o-mini --api-key "$OPENAI_API_KEY" --ngrok-token "$NGROK_AUTHTOKEN" --no-preload
!python colab/launch_yaobi_colab.py --backend anthropic --model-id claude-3-5-sonnet-latest --api-key "$ANTHROPIC_API_KEY" --ngrok-token "$NGROK_AUTHTOKEN" --no-preload
!python colab/launch_yaobi_colab.py --backend http --endpoint-url "$TAO_ENDPOINT_URL" --api-key "$TAO_API_KEY" --ngrok-token "$NGROK_AUTHTOKEN" --no-preload

# 6) Transformers 本地 Dao1（推荐 A100 80GB/H100；首次下载较慢）
!python colab/launch_yaobi_colab.py --backend transformers --model-id CMLM/Dao1-30b-a3b --ngrok-token "$NGROK_AUTHTOKEN"
```

> 公网暴露时建议设置 `YAOBI_CLINICIAN_TOKEN` 或传入 `--clinician-token`，并在 UI 设置页填入同一令牌；否则医生端功能会按服务端 RBAC 锁定为患者视图，避免公网误开放。

## 常见排查

| 现象 | 排查方式 |
|---|---|
| Colab 打开公网链接为空白 | 先看 `yaobi_server.log`，再访问 `<public>/api/health`。 |
| `Connection refused` | 后端尚未健康；脚本会轮询 `/api/health`，失败时打印日志尾部。 |
| 外部 API 不工作 | 确认 `--backend`、`--model-id`、`--api-key`、`--endpoint-url` 或 Azure 参数匹配。 |
| 本地 Dao1 加载慢/OOM | 使用 `--no-preload` 先打开 UI；或改用 `mock`/外部 API/小模型。 |
| 医师端被锁定 | 公网环境需设置 `YAOBI_CLINICIAN_TOKEN` 并在 UI 设置中填入。 |

## 安全边界

Colab 版本仍遵循仓库服务端守卫：模型只负责规划、追问、证据组织与医师复核草案；患者端不得输出最终诊断、完整处方、可执行剂量或替代线下诊疗建议。读片/检验结果只作为报告文本的结构化线索，不替代放射科/检验科正式结论。
