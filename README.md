# Philo

Philo 是一个轻量级、可嵌入的 Python LLM Agent 框架。它提供 ReAct 工具循环、MCP 接入、技能系统、两层记忆、上下文压缩、多入口运行，以及独立的 PostgreSQL 数据访问层。

## 特性

- **ReAct 循环**：模型推理、工具调用、结果回填，支持最大迭代数和检查点恢复。
- **工具系统**：内置 Shell、文件、消息、网页抓取工具，支持参数校验与安全限制。
- **MCP**：支持 stdio、SSE、Streamable HTTP 三种传输方式。
- **技能**：通过 `SKILL.md` 按需加载领域知识，避免污染系统提示词。
- **记忆**：`MEMORY.md` 保存长期事实，`HISTORY.md` 保存可检索的事件日志。
- **上下文管理**：Token 统计、阈值压缩、历史摘要、工具结果截断。
- **多入口**：一次性任务、交互式 CLI、飞书机器人、Python API 与批量调用。
- **数据库 API**：PostgreSQL、pgvector、TimescaleDB、JSONB 和原始 SQL。

## 环境要求

- Python 3.12+
- 一个兼容 OpenAI Chat Completions 的模型服务

## 安装

```bash
git clone git@github.com:bayes1900/philo.git
cd philo
pip install -e .

# 可选：飞书渠道
pip install -e ".[feishu]"

# 可选：数据库 API
pip install -e ".[database]"
```

## 快速开始

先编辑 `philo/cfgops/o0.py`，至少设置工作区、模型地址和 API Key：

```python
pcfg.workspace = "/path/to/your/workspace"
pcfg.llm = PhiloOpenAiLlm(
    modelName="your-model",
    contextWindow=32768,
    url="http://127.0.0.1:8000/v1",
    apiKey=os.getenv("PHILO_API_KEY"),
)
```

运行一次性任务：

```bash
python -m philo.cfgops.o0
```

运行交互式 CLI：

```bash
python -m philo.cfgops.i0
# 输入 /stop 退出
```

或直接使用 Python API：

```python
from philo import reactSync

result = reactSync(
    "用三句话介绍这个项目",
    workspace="/tmp/philo-demo",
)
print(result["content"])
```

## 命令行入口

安装后也可以使用：

```bash
philo-oneshot
philo-interactive
philo-server
```

飞书服务端需要先配置：

```bash
export BOT0_APPID="cli_xxx"
export BOT0_APPSECRET="xxx"
philo-server
```

## 目录结构

```text
philo/
├── agent/       # ReAct 循环、上下文、记忆、技能、工具与 MCP 管理
├── cfgops/      # 一次性、交互式、飞书服务端配置模板
├── config/      # PhiloConfig 与 McpEntry
├── dbapi/       # PostgreSQL / pgvector / TimescaleDB / JSONB API
├── infra/       # 消息总线、会话、CLI、引擎与渠道
├── llm/         # LLM 与 Embedding 适配
├── tools/       # 内置工具与 MCP 工具包装
└── utils/       # 日志、路径、YAML 等工具
```

## 许可

本项目使用 [MIT License](LICENSE)。
