# HiPy 后端 E2E 测试报告 v1

- 时间：2026-10-10
- 被测实例：`http://172.21.80.1:5707`（Windows 侧运行，DB = `app/db/hipy.db`）
- 前端：`http://127.0.0.1:8080`（WSL dev server）
- 口径：**只读**。判定看 HTTP 200 里的**业务 `code`**（`0`=成功、`5004`=未登录/过期、`400`=参数错误），不能只看 HTTP 状态码。
- 身份：用浏览器真实登录态（cookie `Admin-Token`）导出 token，脚本只读 token 文件，全程不接触密码。

## 一、结论速览

| 组 | 内容 | 结果 |
|---|---|---|
| A | 认证与身份 | 通过 |
| B | 精选内容（T1 核心） | 通过 —— **T1 现象无法复现** |
| C/D | 越权探针 | **发现：读接口普遍只校验登录、不校验权限**（35/36） |
| L | 只读闭环/基线 | 通过，基线未变 |

## 二、A 组 · 认证与身份

- `GET /user/info` + user token → `code=0`，`username=user`，角色 `['general']`
- 篡改 token → `code=5004 未登录或登录过期`（**正确拒绝**）
- 未带 token 访问受保护接口 → `code=5004`（**正确**）
- 附注：登出（`POST /logout`）会**作废 token**，因此切换账号后旧 token 立即失效（这是预期行为，但会影响多账号并行测试的取 token 方式）。

## 三、B 组 · 精选内容（T1：user 能否看到 admin 设置的数据）

| 检查 | 结果 |
|---|---|
| user `GET /curated/media` | `code=0`，**total=354**（与 admin 相同） |
| user `GET /curated/catalog` | `code=0`，`categories=6`、`media=354` |
| user `GET /curated/categories` | `code=0` |
| user `GET /user/routers` | `code=0`，顶层 36 个节点，**含「精选内容」(`/curated`)** |

DB 侧：`curated_media` 354 条，其中 `status=1 且 visible=1` 的也是 **354** 条（全部可见）。

**结论：菜单层、接口层、数据层三层均正常，T1（user 看不到 admin 在精选内容里设置的数据）在当前代码与数据下无法复现。** 早前静态分析推测"可能已被 2026-10-10 15:23→16:09 的 `permission.js` 改动修掉"，与此一致。

## 四、C/D 组 · 越权（RBAC）—— 主要发现

用普通用户（user / 角色 general）token，遍历 openapi 中 36 个无路径参数的只读 GET：

- **35 个返回 `code=0`（成功读到数据）**，仅 1 个因参数错误无法判定
- 明确被权限拒绝的：**0 个**

其中需要重点关注的（不属于此前已确认"刻意公开"的那 20 个）：

```
/api/v1/permission/user            ← 用户列表
/api/v1/permission/role            ← 角色
/api/v1/permission/menu            /simple/list  /simple/tree   ← 菜单
/api/v1/permission/perm-label      ← 权限标签
/api/v1/system/config-setting      ← 系统配置
/api/v1/system/dict/data  /dict/detail   ← 字典
/api/v1/monitor/server             ← 服务器监控
/api/v1/vods/configs/list  /vods/houses/list
/api/v1/user/info  /user/routers  /user/routers-tree
/api/v1/curated/kid_config         ← 且该接口带写副作用
```

**判读（已修正，见 4.1）**：读接口**并非"登录即可读"**。实测"普通用户能读后台接口"的**真实原因是角色授权过宽**：general 角色被授予了 17 个 `:get` 标签。

### 4.1 修正与定性（第 2 轮复核）

初次结论（"读接口只校验登录、不校验权限"）**有误**，证据如下：

- `deps.user_perm()` 的实现是标准的**接口级权限标签**模型：`perm_labels` → 查标签已授予哪些角色（Redis 缓存）→ 与用户角色求交；`is_superuser` 旁路；`AUTO_ADD_PERM_LABEL` 时自动把新标签入库供后台勾选。
- 57 个 GET 中 **18 个确实声明了 `:get` 标签**（`/permission/user|role|menu|perm-label`、`/system/config-setting|dict/*` 等）。
- 库内 `t_perm_label_role`：**general（角色2）持有 23 个标签，其中 17 个是 `:get`**，含
  `perm:user:get`、`perm:role:get`、`perm:menu:get`、`perm:label:get`、
  `system:config-setting:get`、`system:dict:get`、`system:dict:detail:get`、
  `monitor:server:get`、`monitor:cache:get`、`monitor:pip:get`、`curated:*:get`、`vod:*:get`。
- 因此实测 user 能读 `/permission/user` 等，是**该角色本就持有该读标签** → 校验生效、配置过宽。

**定性：这是"授权配置"问题，不是"接口缺校验"的代码缺陷。**

另有两处次要项：

- 声明模式一致：管辖接口（列表/详情）带 `:get` 标签；辅助接口（`max-order-num`、`role/select/list`、`dict/type/{_type}`、`config-setting/key/{key}`）**刻意不带**，供任何登录用户做下拉/排序。属可接受的折中，但敏感域的辅助接口建议补标签。
- 代码缺陷（小）：`/permission/menu/{menu_id}` 的标签写成 **`perm:menu:gut`**（应为 `perm:menu:put`），拼写错误会导致该写权限实际校验错标签。

## 五、L 组 · 只读闭环与基线

| 项 | 结果 |
|---|---|
| L3 状态一致性 | `media=354`，其中 `status=1&visible=1` = 354（一致） |
| L8 基线 | `curated_media=354`、`curated_category=6`、`curated_provider=1`、`t_users=4`、`t_subs=10` |
| 库是否被改动 | 未改动（对照基线一致） |

## 六、执行中的两个插曲（如实记录）

1. `/curated/kid_config` 默认 `ensure=True`，会创建订阅（写操作）。本轮调用时该订阅（id=10「亲子精选」）已于 **2026-09-30 08:45:35** 存在，故未产生任何写入；**但这是该 GET 的隐含副作用**，后续扫描已将其列入跳过名单。
2. 第一轮探针只看 HTTP 状态码，把 3 个"HTTP 200 + 业务 code=5004"的接口误判为通过；已改为按业务 `code` 判定并重跑。

## 七、未完成 / 阻塞

- **admin 侧对比测试**：为切换账号登录，admin token 被登出作废，需重新取一次 admin 登录态（保持登录不登出）。
- **写路径验证（dry-run）**：本次未做任何写操作；按约定写路径仅做参数/权限校验的 dry-run。
- **L1/L2 运行时消费闭环**：L2 按约定只验到"订阅生成 + 可见集合一致"，未跑 t4 引擎。
- **不可测项**：真实 TVBox/客户端播放、外部站点搜索（flaky）。

## 八、第 2 轮补充：admin 侧对比与写接口静态核查

### 8.1 admin ↔ user 对比（真实登录态）

| 项 | admin | user |
|---|---|---|
| `GET /user/info` | `code=0`，角色 `超级管理员/admin` | `code=0`，角色 `general` |
| 菜单顶层节点 | 44 | 36 |
| `GET /curated/media` total | 354 | 354 |
| **admin 可读但 user 不可读的只读接口** | — | **0 个** |

即：读接口对两个角色**无差别**，权限标签不作用于读接口。与此前 C/D 组结论一致，并给出了量化。

### 8.2 写接口静态核查（不执行任何写，只读源码）

扫描 `apps/**/views.py` 的 54 个写接口（post/put/delete/patch）：

- **41 个带 `deps.user_perm([...])` 权限依赖**（写操作是受权限管控的）
- 13 个不带，其中 11 个属合理的自助接口（login/logout/register/forget-password/check availability/info/password/avatar）

### 8.3 ★ 发现：两个高危写接口只用硬编码共享密钥保护

```
PUT /api/v1/web/database_update   数据库升级（会执行 update_db()）
PUT /api/v1/web/rules_refresh     刷新源列表
```

- 二者**都没有登录鉴权、也没有 `user_perm` 权限依赖**，靠请求体里的 `auth_code` 与 `settings.DATABASE_UPDATE_AUTH` 比对
- 而该值在 `app/core/config.py:118` 是**硬编码默认值**（6 字符，且与某个账号名同名），仓库里可见；`hipy.conf` 未覆盖它
- 影响：任何能读到仓库/猜到该值的人，都能在**未登录**的情况下触发**数据库升级**或刷新源列表
- 建议：改为走登录 + `user_perm`，密钥改为环境变量注入且强随机

## 九、附件

- 未认证可读接口清单：`unauth_open_endpoints.json`
- 普通用户可读接口清单：`rbac_user_scan.json`
- 本轮明细：`e2e_round3_result.json`
- 清单（用例源）：`docs/e2e/hipy-e2e-checklist.md` v0.3
