# AI漫剧制作平台（次元世界 AI漫剧工坊）

基于 FastAPI + LangGraph + MySQL + Vue3 + Element Plus 的 AI 漫剧自动化生产平台。

## 技术栈

- **前端**：Vue 3.5+ / TypeScript / Vite 6 / Element Plus / Pinia / Vue Router
- **后端**：FastAPI 0.115+ / Python 3.12 / LangGraph / LiteLLM / SQLAlchemy 2.0 async
- **数据库**：MySQL 8.0（asyncmy 驱动）
- **缓存/队列**：Redis 7 / ARQ
- **视频处理**：FFmpeg 6

## 快速启动

```powershell
# 一键启动全部服务（MySQL、Redis、后端、Worker、前端）
.\start.ps1

# 停止全部服务
.\stop.ps1

# 查看服务状态
.\start.ps1 -Status
```

## 目录结构

```
manga-studio/
├── apps/web/              # Vue3 创作端
├── services/api/          # FastAPI 后端
│   ├── app/
│   │   ├── api/v1/        # 路由层
│   │   ├── core/          # 配置/安全/数据库/日志
│   │   ├── models/        # SQLAlchemy ORM
│   │   ├── domains/       # 领域服务
│   │   ├── agents/        # LangGraph 智能体
│   │   ├── providers/     # LLM/图像/视频/TTS Provider
│   │   └── tasks/         # ARQ 任务
│   └── alembic/           # 数据库迁移
├── deploy/                # docker-compose、nginx
└── docs/                  # 文档
```

## 默认账号

- 用户名：`admin`
- 密码：`123456`
