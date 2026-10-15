# 专属于你的健身管家 · 多 Agent 协作平台

一个面向作品集展示的本地多 Agent 健身管理平台。它用独立的专业 Agent 生成训练建议，保留冲突和运行轨迹，并根据实际训练反馈提交版本化学习提案。

## 核心技术

- React + TypeScript 前端
- FastAPI + Pydantic API
- LangGraph 工作流编排
- PostgreSQL 业务数据与 LangGraph checkpoint
- Celery + Redis 后台任务
- Ollama 本地模型适配器，默认 `qwen2.5:3b`
- OpenAI-compatible 云模型适配器，默认支持阿里云百炼 `qwen-plus`
- Docker Compose 一键运行

Agent 在编排图中是独立节点、独立模型调用、独立上下文和独立数据库运行记录。专业 Agent 在逻辑上并行分支，但 Ollama 生成由单槽 semaphore 串行化，以适配 RTX 3050 Ti 4GB 显存。冲突时触发最多一轮定向复核。

## 启动模拟演示

需要 Docker Desktop / Docker Compose。

```powershell
Copy-Item .env.example .env
# 将 .env 中的 MODEL_PROVIDER 改为 fake
docker compose up --build
```

浏览器打开 `http://localhost:8080`。`MODEL_PROVIDER=fake` 会明确标为模拟 Provider，不会伪称是真实模型推理。输入备注 `演示冲突` 可触发恢复 Agent 与训练 Agent 的意见冲突，展示复核路径。

## 启动阿里云百炼真实推理

在项目根目录的 `.env` 设置：

```text
MODEL_PROVIDER=openai_compatible
MODEL_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MODEL_NAME=qwen-plus
MODEL_API_KEY=你的百炼 API Key
```

随后重建 API 和 Worker：

```powershell
docker compose up --build -d
```

每个 Agent 都会独立请求 `qwen-plus`，并将结构化输出、耗时和失败状态写入运行轨迹。超时、限流、服务错误和无效 JSON 最多重试一次；鉴权失败立即停止。真实调用失败时不会自动回退到 Fake Provider。

完整 API Key 只注入后端容器，不进入前端、数据库或 Git。网页只显示是否已配置以及脱敏尾号。云端模式会把每个 Agent 所需的个人档案、当日记录和有限历史发送到百炼，请勿填写不必要的敏感信息。

## 启动本地 Ollama 模型

1. 在宿主机安装并启动 Ollama。
2. 拉取模型：

```powershell
ollama pull qwen2.5:3b
```

3. 在 `.env` 设置：

```text
MODEL_PROVIDER=ollama
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_MODEL=qwen2.5:3b
```

4. 执行 `docker compose up --build`。设置页首部和每条 run trace 会标明真实 provider 与模型。真实推理依赖宿主机硬件及已下载模型；默认 Compose 不会自动下载数 GB 模型文件。

## 工作流

```text
手动记录
  -> 确定性安全/数据检查
  -> 数据质检 Agent
  -> 恢复 / 训练 / 减脂 Agent 独立分析
  -> 冲突检测 -> 最多一轮定向复核
  -> 总教练 Agent 协调
  -> 风险 Agent 审核
  -> 确定性最终门
  -> 训练计划与运行轨迹
  -> 完成数据 -> 学习 Agent 提案 -> 自动应用或待确认
```

学习只更新受控的结构化个人画像，不在线微调模型。典型 RPE 至少 3 条相关记录且值域有效时可低风险自动应用；其他提案保留待确认。每个版本可追踪，模型不能修改提示词、安全规则或权限。

## 服务与接口

- Web UI: `http://localhost:8080`
- API docs: `http://localhost:8000/docs`
- Health: `http://localhost:8000/api/v1/health/ready`
- Runtime: `http://localhost:8000/api/v1/system/runtime`

## 测试

```powershell
cd services/api
python --version  # Python 3.12+
pip install -e ".[test]"
pytest
```

当前自动测试覆盖 Fake Provider、云端 Provider 与 Agent 工作流，不会调用真实百炼额度，也不需要 Ollama。检查前端构建：

```powershell
cd apps/web
npm install
npm run build
```

## 隐私与边界

- 默认模拟模式不访问任何模型服务。
- Ollama 模式只请求配置的本地服务，不包含云端模型集成。
- 百炼模式会把 Agent 所需的健身上下文发送到配置的云端接口，页面会明确显示云端状态。
- Compose 端口默认绑定到本机回环地址。
- 应用是训练建议工具，不是医疗诊断；疼痛/异常症状和确定性规则优先于模型建议。
- 当前示例使用本地演示数据库凭据，不可直接暴露到局域网或公网。

## 验证状态与边界

前端已通过 TypeScript 检查和 Vite 生产构建；后端源码通过 Python 编译检查，24 个 pytest 测试均通过。Docker Compose 的 PostgreSQL、Redis、API、Worker 和 Web 链路已经实际运行；百炼真实请求需要用户自行配置 API Key 后验证。

项目是求职作品原型：目前自主学习仅管理受控的 `typical_rpe` 画像参数，不会微调模型；周报采用确定性统计，不是医疗判断；Fake Provider 用于无模型演示，只有显式配置 Ollama 才会执行真实本地推理。运行历史和学习版本保存在 PostgreSQL，删除数据接口会清除应用记录。
