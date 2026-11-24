# 团队协作规则（3 人）

适用于 `DriverAnalyticsMongo`（MongoDB + FastAPI + JS），也适用于 `DriverAnalyticsNeon`（ASP.NET + PostgreSQL）。

## 1. 角色

| 人 | 看板负责 | 仓库角色 |
|---|---|---|
| Weiming | PBI #16 #17 #39 | 集成人：唯一有权合并 `main` 的人，负责最终验收 |
| Olawale | PBI #14 #22 #30 | 开发：认证 / 注册 / 员工风险列表 |
| Bashiru | PBI #15 #26 #34 | 开发：车辆 / 历史 / 平台与测试 |

集成人也要写代码，但**不能合并自己没被 review 过的 PR**（自己开的 PR 由另一人 review）。

## 2. 分支模型

- `main` 永远可运行，只接受 PR，禁止直接 push。
- 一个 Task 一个分支：`task/<Task编号>-<短名>`，例如 `task/20-start-trip`。
- 分支从最新 `main` 拉，生命周期不超过 3 天；超过就拆小。

```bash
git switch main && git pull
git switch -c task/20-start-trip
```

## 3. 提交信息

```
#20 add POST /api/analytics/start with vehicle ownership check
```

- 开头写 Task 编号，Azure Boards 会自动把 commit 关联到该 Task（也可写 `AB#20`）。
- 一行说清"做了什么"，不写"update""fix bug"。
- 一个 commit 只做一件事；格式化、改文案单独提交。

## 4. 提交前到底要不要 0 error

分两级，不要一刀切：

| 时点 | 要求 |
|---|---|
| 本地 `commit` | 允许 WIP，**不强制**。但建议至少能编译（`python -m compileall` / `dotnet build`） |
| `push` 到远端分支 | **error 必须为 0**；单元测试必须全绿；新增 warning 要在 PR 里说明 |
| 开 PR / 合并 | `verify.ps1` 退出码 0；CI 绿；1 人 approve；无未解决评论 |

warning 不强求 0——课程项目里 warning 一堆，强求只会逼人跳过检查。真正卡的是：**编译 error、测试 fail、主流程跑不通**。

本地闸门（推之前跑一次，约 20 秒）：

```powershell
powershell -ExecutionPolicy Bypass -File .\verify.ps1
```

它会依次检查：Python 语法编译 → 评分单元测试 → API 健康检查 + 32 项冒烟 → .NET 编译（存在 csproj 时）→ 前端 JS 语法。任何一步失败即退出码 1。

建议启用 Git 钩子，让 `push` 自动跑：

```bash
git config core.hooksPath .githooks
```

## 5. PR 规则

- 一个 PR 只对应一个 Task，改动 ≤ 300 行（超了拆）。
- 标题：`#20 Start trip endpoint`；描述用 `pull_request_template.md`。
- 必须写"怎么验证的"：跑了哪些测试、浏览器点了哪几步、贴截图或日志。
- 合并方式统一 **Squash**，合并后删分支。
- 合并后把 Task 拖到 Done；PBI 的所有 Task Done 才关 PBI。

## 6. 冲突与回滚

- 每天至少 `git fetch && git rebase origin/main` 一次，冲突由**后提交的人**解决。
- 谁的 PR 把 `main` 弄红，谁在 30 分钟内修；修不好就 revert 自己的 merge commit，不准"先合了再说"。
- 禁止 `git push --force` 到 `main`；自己的功能分支可以 force-with-lease。

## 7. 每日节奏

- 早上 10 分钟：昨天做了什么、今天做哪个 Task、有没有阻塞。
- 每天至少合并 1 个 PR，避免最后一天集中合并。
- 演示前 24 小时冻结 `main`，只修 bug。

## 8. 命令速查

```bash
# 开始一个 Task
git switch main && git pull && git switch -c task/20-start-trip

# 提交
git add -A && git commit -m "#20 add start endpoint"

# 推送前自检
powershell -ExecutionPolicy Bypass -File .\verify.ps1

# 推送并开 PR
git push -u origin task/20-start-trip

# 同步主线
git fetch origin && git rebase origin/main
```
