# Group3F26-Backend

Driver Analytics System — Python REST API + MongoDB 后端。

前端在独立仓库 `-Group3F26-Frontend`，本仓库只放 API、评分引擎、数据访问与测试。

## 目录结构

```
Group3F26-Backend/
├── app/
│   ├── api/               # 路由层（按用例分模块）
│   ├── core/              # 配置、安全、评分规则
│   ├── db/                # MongoDB 连接与索引
│   ├── models/            # Pydantic 请求/响应模型
│   ├── services/          # GPS 回放、行程引擎、业务编排
│   └── data/              # gps-trace.csv、mock-dimensions.json
├── tests/                 # 单元测试 + API 冒烟
├── scripts/               # 启动/初始化/数据清理脚本
├── docs/                  # 接口契约、ER 说明、排障
├── requirements.txt
├── .env.example
└── README.md
```

空目录用 `.gitkeep` 占位，避免 Git 忽略空文件夹；放入真实文件后可以删掉对应的 `.gitkeep`。

## 模块与看板对应

| 目录/文件 | 负责 Task | 负责人 |
|---|---|---|
| `app/api/auth.py` | #23 #24 | Olawale |
| `app/api/drivers.py` | #18 #21 #31 #32 | Olawale |
| `app/api/vehicles.py` | #19 #44 | Bashiru |
| `app/api/analytics.py` | #20 #46 #47 #27 #28 | Bashiru / Weiming |
| `app/core/scoring.py` | #40 #41 #42 | Weiming |
| `app/core/security.py` | #18 #23 | Olawale |
| `app/db/mongo.py`、`indexes.py` | #21 #36 | Olawale / Bashiru |
| `app/services/gps_source.py` | #49 #50 | Weiming |
| `app/services/session_engine.py` | #47 #48 | Weiming |
| `app/data/` | #49 | Weiming |
| `tests/` | #37 #42 | 全员 |
| `scripts/` | #35 | Bashiru |
| `docs/` | #38 | Bashiru |

## 本地运行（占位，代码落地后补全）

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

## 接口约定

- 所有业务接口前缀 `/api`
- 鉴权头 `X-Auth-Token`
- 错误响应统一 `{ "message": "..." }`
- 字段名统一 camelCase，时间统一 ISO 8601

## 分支与提交

见根目录 `CONTRIBUTING.md`（本地 `DriverAnalyticsMongo` 工程内）。核心规则：

- 一个 Task 一个分支：`task/<编号>-<短名>`
- commit 以 `#<编号>` 开头
- push 前跑 `verify` 脚本，error 必须为 0
