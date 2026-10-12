# HiPy 后端 E2E 测试报告 v2（数据范围上线后实测）

- 时间：2026-10-12
- 被测实例：`http://172.21.80.1:5707`（Windows 侧，DB = `app/db/hipy.db`）
- 代码版本：master `4573783`（含 seed / websec / uidinfo / s3api / s2）+ hipy-ui `e4d6979`
- 后端进程：**2026-10-12 15:28:35 重启**（新代码已生效，见第三节证据）
- 口径：**全程只读 + 写路径 dry-run**（不产生任何写入）

## 一、结论速览

| 组 | 内容 | 结果 |
|---|---|---|
| 部署 | 新代码是否生效 | ✅ 生效（未认证探针全部 5004） |
| 数据范围 | 一般用户能否看到超管数据 | ✅ 能看到（354 条精选内容等） |
| 数据范围 | 一般用户对超管数据是否只读 | ✅ 写操作全部 5403 拒绝 |
| 数据范围 | 一般用户之间是否隔离 | ✅ 隔离（副本实测：他人数据不可见不可写） |
| 权限收敛 | 种子/角色数据范围 | ✅ 已落地（admin=3 / general=2 / Operation=2） |
| 基线 | 是否产生副作用 | ✅ 零写入（计数与基线一致） |

## 二、方法

- 身份获取：**可见浏览器窗口由用户本人登录**，脚本只从会话里取 `Admin-Token` cookie；
  **全程不接触、不打印密码**。token 存 600 权限文件，用完即删。
- 判定口径：该后端是 **HTTP 200 + 业务 `code`**（`0` 成功 / `5004` 未登录 / `5403` 权限不足 / `400` 参数错误），
  **不能只看 HTTP 状态码**。
- 写路径：一律 dry-run——用"对**不存在的 id**发起写请求"或"对**超管的数据**发起写请求"来判别，
  并在每步之后复核库计数，确保零写入。

## 三、部署验证（新代码是否真的生效）

重启前，`curated/media`、`curated/providers` 等**未带 token 也能读到数据**（code=0）；
重启后同一批探针：

| 探针（未带 token） | 重启前 | 重启后 |
|---|---|---|
| `GET /api/v1/curated/media` | code=0 | **code=5004** |
| `GET /api/v1/curated/providers` | code=0 | **code=5004** |
| `GET /api/v1/curated/categories` | code=0 | **code=5004** |
| `GET /api/v1/hiker/hiker_rule` | code=0 | **code=5004** |
| `GET /api/v1/vods/rules/list` | code=0 | **code=5004** |
| `PUT /database_update` | 可未认证触达 | **code=5004** |
| `PUT /rules_refresh` | 可未认证触达 | **code=5004** |

> 注：`/database_update`、`/rules_refresh` 挂在**根路径**（不是 `/api/v1/web/...`）。

**解释器核实**：`GET /api/v1/monitor/server` 的 `jvm` 字段显示
`home = J:\...\hipy-server\venv\Scripts\python.exe`，`paths` 含
`...\hipy-server\venv\Lib\site-packages` ⇒ **实际解释器就是仓库 venv，第三方包也从 venv 解析**，
不存在"跑在 miniconda 上"的问题（此前据进程镜像路径的判断有误，已在本文纠正）。

## 四、数据范围（行级隔离）实测

### 4.1 读

| 资源 | admin | user(一般用户) |
|---|---|---|
| 精选内容 `/curated/media` | 354 | **354** |
| 源规则 `/vods/rules/list` | 485 | **485** |
| 订阅 `/vods/subs` | 7 | **7** |
| 分类 `/curated/categories` | 6 | **6** |
| 站点 `/curated/providers` | 1 | **1** |

> 现有业务数据**全部属于超管(creator_id=1)与系统(creator_id=0)**，而档位 2 的读范围 = 本人 + 公共(0/1)
> ⇒ user 与 admin 看到同样多的数据，**正是"超管数据对一般用户可见"这条需求的直接体现**。

### 4.2 写（dry-run）

| 探针 | 结果 |
|---|---|
| user 改超管的媒体（对真实 id） | **5403 权限不足** |
| user 批量改超管媒体的可见性 | **5403** |
| user 批量删 / 删超管媒体 | **5403** |
| user 改不存在的媒体 | **5403**（数据范围守卫拦下） |
| admin 改不存在的媒体 | code=0（**通过守卫**，无写入） |

> 关键：`curated:media:put` 标签 **general 角色是持有的**，所以"改/批量改"被拒**不是标签问题，
> 而是**数据范围守卫（ensure_writable）**生效 ⇒ 证明新机制本身在起作用。

### 4.3 跨用户隔离（库副本实测，非线上写入）

在库副本里插入一条 `creator_id=3`(user) 的数据后：

| 操作者 | 可见 | 可写 |
|---|---|---|
| admin(档位3) | ✅ | ✅ |
| 另一个一般用户(档位2) | ❌ 不可见 | ❌ 不可写 |
| user 本人 | ✅ | ✅ |

## 五、基线与零副作用

- 基线：`curated_media=354`（其中 status=1 且 visible=1 也是 354）、`curated_category=6`、
  `curated_provider=1`、`t_vod_rules=485`、`t_vod_subs=10`、`t_hiker_rule=1`
- 全部测试结束后复核：**与基线完全一致** ⇒ 本轮未产生任何写入
- 数据范围 S1 首轮演练时误触的 `GET /curated/kid_config`（该接口默认会建订阅）经核实
  **未产生写入**（该订阅早在 2026-09-30 已存在）

## 六、本轮随测试修复/交付的问题

| 项 | 处置 |
|---|---|
| getMenus 越权（空授权返回全部菜单） | 已修复并合入 |
| 权限收敛：种子给 general 的管理域读标签 | 已删（种子文件），并在后台收窄 |
| `curated/init_menu.py` 把菜单/标签授予"所有角色" | 改为只授予 admin/general/Operation |
| 高危写接口无鉴权 + 硬编码执行码 | 已加登录+权限；执行码改环境变量并**轮换** |
| 数据范围（行级隔离）S1/S2/S3 | 全部实现并合入（10 个业务实体 + 角色配置 + 前端按钮态） |
| `/user/info` 不返回 id（前端判权拿不到） | 已补 |
| 仓库 CRLF/LF 全仓抖动（近千"伪修改"、多次挡合并） | 加 `.gitattributes` 治本（hipy-server 伪修改 971→0） |

## 七、已知局限与待办

1. **`DEFAULT_SNIFFER=playwright` 但 venv 未装 playwright** → 定时"嗅探器"任务报
   `缺少playwright` 而无法激活（功能降级，非崩溃）。若要启用：把 playwright 装进 **venv** 并 `playwright install chromium`。
2. `providers/categories/media` 及 `hiker/*`、`vods/rules|subs` 等**由"未认证可读"变为"需登录"**——
   甲方已确认接受（客户端走订阅/config 生成路径，不直接调这些管理接口）。
3. **不可测项**：真实 TVBox/客户端播放、外部站点搜索（flaky）；L2 运行时闭环按约定只验到
   "订阅生成 + 可见集合一致"，未跑 t4 引擎。
4. 定时任务相关接口（`/monitor/job*`、`/monitor/logininfor/list`）仍为"登录即可读"（无权限标签）——
   属管理域，是否加标签另行决定。

## 八、附件（scratch 目录，非仓库）

- `e2e_final_result.json`（user 侧明细）、`e2e_admin_side.json`（admin 侧明细）
- `unauth_open_endpoints.json`、`rbac_user_scan.json`
- 用例清单：`docs/e2e/hipy-e2e-checklist.md` v0.3
