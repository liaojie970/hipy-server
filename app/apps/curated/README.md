# 精选内容 (Curated)

面向**家庭局域网**的「人工审核白名单」内容源。把 B 站等站点的视频逐条审核入库，生成一个只包含
已批准视频的 TVBox 源（`亲子精选`），用于给孩子看电视/学习时做内容把关。

## 能力

- **站点适配器可扩展**：`providers/` 下 `BaseProvider` + `bilibili.py` + `registry.py`，未来加 `youtube.py` 即可。
- **两种入库方式**：关键词搜索勾选 / 粘贴链接（支持一行一个，自动解析）。
- **人工审核**：每条内容有 `审核状态(0待审/1通过/2拒绝)` 和 `前台可见(0/1)`；
  **只有「已通过 + 可见」的内容**才会出现在运行时源里。
- **播放**：用后台配置的 Cookie 实时解析 B 站直链（`playurl`），Cookie 只存数据库，不落任何 web 目录。
- **代理可配**：站点配置里可填 `proxy`。留空=跟随系统/环境代理；`none`=强制直连；也可写 `127.0.0.1:7897`。
  若本机无法直连 B 站（需要代理才能打开网页），请务必在「站点管理」里填写代理地址。
- **内容校验**：对已入库内容做「账号可见性 + 可播放」双重校验，结果记在 `view_status`（0未校验/1正常/2异常）。
- **儿童配置一键生成**：自动创建 `reg=亲子精选` 的订阅，返回只含该源的配置地址。

## 目录结构

```
apps/curated/
├── providers/          # 站点适配器 (base / bilibili / registry)
├── models/             # curated_provider / category / media / episode
├── curd/               # 数据访问层
├── schemas/            # 入参校验
├── service.py          # 业务服务 (后台 API 与运行时源共用)
├── views.py            # 后台 REST API
└── init_menu.py        # 后台菜单初始化 (启动时幂等执行)
```

运行时源：`t4/spiders/亲子精选.py`（type4，直接读精选库，无需额外接口）。

## 后台 API (`/api/v1/curated`)

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET  | `/providers/available` | 支持的站点类型 |
| GET/POST/PUT/DELETE | `/providers` `/providers/{id}` | 站点(含 Cookie)管理 |
| POST | `/providers/test` | 测试站点配置(可传 config 不入库) |
| GET/POST/PUT/DELETE | `/categories` `/categories/{id}` | 分类管理 |
| GET  | `/media` `/media/{id}` | 内容库列表/详情(含选集) |
| POST | `/media/batch` | 批量入库(三层去重、并发补详情) |
| PUT  | `/media/status/batch` | 批量审核 |
| POST | `/media/visible/batch` | 批量显示/隐藏 |
| POST | `/media/remove/batch` | 批量删除 |
| POST | `/search` | 站点搜索 |
| POST | `/resolve` | 解析粘贴链接 |
| GET  | `/play` | 解析播放直链 |
| POST | `/media/check/batch` | 批量校验可见性+可播放 |
| GET  | `/kid_config` | 生成儿童专用配置地址(自动建订阅) |
| GET  | `/catalog` | 精选库快照(调试) |

## 使用流程

1. **站点管理**：给「哔哩哔哩」填入登录后的 Cookie（至少 `SESSDATA`），点「测试连通」确认登录态。
   - 若本机直连 B 站不通，请在「网络代理」里填代理地址，例如 `127.0.0.1:7897`（Clash/V2Ray 常见端口）。
2. **分类管理**：建好分类，如 `科普知识`、`英语启蒙`、`动画`。
3. **搜索入库**：关键词搜索勾选，或粘贴链接解析；选择入库分类与审核状态。
4. **内容库**：对待审内容「通过/拒绝」，对已通过内容「显示/隐藏」；可对内容做「校验」（账号可见性+可播放）。
5. **源管理**：在 hipy 后台「源管理」点一次 **刷新源**，`亲子精选.py` 会被扫描进数据库。
6. **生成配置**：普通配置里会出现名称为「亲子精选(hipy_t4)」的源。
7. **儿童配置**：在「内容库」点「儿童配置」，一键生成只含该源的地址（自动创建订阅）。

## 批量入库说明

- **三层去重保障**：
  1. **数据库层（硬约束）**：`curated_media` 上有唯一索引 `uq_curated_media_provider_media(provider_code, media_id)`，
     即使绕过应用层并发写入也不可能出现重复行。启动时自动创建；旧库若已有重复行，会先按「活跃优先、其次 id 最小」
     保留一条并物理删除多余行（含其选集）。
  2. **应用层**：入库统一走 `upsertByProviderMediaId`。命中已有记录（包括曾被删除的）就**就地更新并复活**，
     不会新增第二行；若因并发触发唯一约束冲突，会回滚后改走更新。
  3. **前端**：勾选「跳过已入库」时，已入库的行不可勾选、单个「入库」按钮置灰，提交前也会再过滤一次。
- **默认跳过已入库**（`skip_existing=true`）：重复点击「批量入库」会瞬间返回并提示「跳过 N 条」，幂等且秒回。
  如需用最新信息刷新已有条目（如 Cookie 换后拉最新选集），请先取消勾选「跳过已入库」（前端会以 `skip_existing=false` 提交）。
- **删除后可重新入库**：删除为逻辑删除；后来同一个媒体再次入库时，会复用原行并复活，不会产生重复数据。
- **返回结构**：`{success, skipped, errors, created, updated, skipped_count, failed}`，前端按「新增/更新/跳过/失败」分类展示。
- **性能**：入库前一次性查出已存在记录；需要补详情的条目用线程池（8 并发）拉取；选集改为 `add_all` 单次提交
  （部分 B 站合集有上千集，逐集 `commit` 会产生上千次磁盘同步）。实测 19 条新内容约 3 秒，1000 集条目约 0.8 秒。

## 给孩子一个「只含精选」的配置（推荐）

在「源订阅」里新建一条订阅：

- `reg`：`亲子精选`（正向匹配，只保留该源）
- `mode`：`0`（正向匹配）
- `status`：启用

然后孩子的 TVBox 使用：

```
http://<你的局域网IP>:5707/config/0?sub=<订阅码>
```

该配置里就只会有「亲子精选」这一个源。其他家人仍可用不带 `sub` 的完整配置，或使用别的订阅码。

## 多站点扩展

1. 新建 `providers/xxx.py`，继承 `BaseProvider`，实现 `search / resolve_url / get_detail / check_viewable / resolve_play / test`。
2. 在 `providers/registry.py` 的 `PROVIDERS` 中注册。
3. 后台「站点管理」即可新增该站点类型并配置 Cookie。

## 代理说明

- **服务端全局覆盖**：在 `configs/.env` 里配置 `SERVER_PROXY=http://127.0.0.1:7897`，启动时会把
  `HTTP_PROXY/HTTPS_PROXY` 强制改写为该值（并把 `localhost,127.0.0.1` 加入 `NO_PROXY`）。
  适用于 IDE/父进程注入了不可用代理（如 `127.0.0.1:17890`）导致请求卡死的情况。
- **新安装/首次启动会为默认的「哔哩哔哩」站点预填代理 `127.0.0.1:7897`**（可在「站点管理」里改）。
  对已存在但未填写代理字段的 B 站站点，启动时也会一次性补齐。若想跟随系统代理，把该字段清空即可（不再自动补）。
- 站点配置 `proxy` 为空时遵循系统/环境代理（`HTTP_PROXY`/`HTTPS_PROXY` 或 Windows 系统代理）。
- 若环境变量里的代理是坏的（例如被设成 `127.0.0.1:17890` 但真实代理是 `7897`），会导致请求卡住超时。
  此时请在「站点管理」里显式填代理，或修好环境变量。
- `proxy=none` 可强制直连（适用于能直连 B 站的服务器/网络）。

## 单元测试

后端（`app/` 目录下执行，使用独立的临时 SQLite，不会碰到真实的 `db/hipy.db`）：

```bash
../venv/Scripts/python.exe -m pip install -r requirements-dev.txt   # 首次: 装 pytest
../venv/Scripts/python.exe -m pytest
```

覆盖内容：

| 文件 | 覆盖点 |
| --- | --- |
| `tests/test_curated_dedup.py` | 三层去重：应用层 upsert、软删除复活（id 不变）、数据库唯一约束、并发撞约束回滚改更新、批量入库的跳过/刷新/失败分支、搜索「已入库」标注、运行时只返回审核通过的媒体 |
| `tests/test_curated_episodes.py` | 选集覆盖式替换、**单次 commit**（回归 1000 集慢的坑）、排序与缺省值兜底 |
| `tests/test_curated_unique_index.py` | 老库去重迁移（活跃优先 / id 最小）、幂等性、建索引后拒绝重复、全新库自带约束 |
| `tests/test_curated_utils.py` | config 解析/序列化、`_is_active`、站点代理优先级（防 IDE 注入死代理）、站点注册表 |

`conftest.py` 会在导入任何 app 模块**之前**把 `SQLALCHEMY_ENGINE=sqlite`、`SQL_DATABASE=hipy_test_<pid>` 写入环境变量，
并用 `FakeProvider` 替换真实站点适配器，因此测试**完全不联网**。会话结束后自动删除临时库文件。

前端（`hipy-ui/dashboard` 目录下执行）：

```bash
npm run test:unit        # jest
```

覆盖内容：`tests/unit/utils/dedupe.spec.js`（去重键计算：幂等方法/FormData 跳过、acquire/release 生命周期）
与 `tests/unit/utils/requestDedupe.spec.js`（与 axios 拦截器集成：并发相同 POST 只发一次、失败后释放、GET 与上传不去重）。
