# HiPy 权限收敛方案（general 角色最小权限 + 源头治理）

> 结论先行：**框架方向是对的（接口级权限标签 + 角色授权），实现也正确；
> 问题是"普通用户(general)"被授了管理域读权限，而且有机制会持续把它灌回来。**
> 修的地方是**授权配置 + 两处授予逻辑**，不是改权限框架。

## 一、机制说明（读码结论）

`deps.user_perm([...])` 的工作方式：

1. 接口声明所需标签（如 `perm:user:get`）
2. 查"该标签授予了哪些角色"（Redis 缓存 `getLabelsRoleIds`）
3. 与当前用户的角色求交，有交集即放行
4. `is_superuser` 直接旁路（所以 admin 角色名下只挂 8 个标签，属正常）
5. `AUTO_ADD_PERM_LABEL` 当前为 **False**（运行时不会自动造标签）

声明规律一致：**管辖接口（列表/详情）带 `:get` 标签**；辅助接口（`max-order-num`、
`role/select/list`、`dict/type/{_type}`、`config-setting/key/{key}`）刻意不带，供任何登录用户做下拉/排序。

## 二、P1 · general 角色最小权限清单

现状：general（角色2）持有 **23 个**标签，其中 17 个 `:get`。

### 建议保留（业务域读，7 个）

| 标签 | 用途 |
|---|---|
| `curated:media:get` | 精选内容-媒体列表 |
| `curated:provider:get` | 精选内容-站点 |
| `vod:configs:get` | 配置中心 |
| `vod:rules:get` | 源管理 |
| `vod:houses:get` | 源仓库 |
| `hiker:developer:get` | 开发者 |
| （可选）`report:excel_generate:get` | 报表导出——若不需要普通用户导出则去掉 |

### 建议去掉（管理域读，10 个）

| 标签 | 去掉理由 |
|---|---|
| `perm:user:get` | 用户管理 |
| `perm:role:get` | 角色管理 |
| `perm:menu:get` | 菜单管理 |
| `perm:label:get` | 权限标识管理 |
| `system:config-setting:get` | 系统配置 |
| `system:dict:get` | 字典管理 |
| `system:dict:detail:get` | 字典明细 |
| `monitor:server:get` | 服务器监控 |
| `monitor:cache:get` | 缓存监控 |
| `monitor:pip:get` | 依赖管理 |

### 需要你决定的（写标签，6 个）

`curated:category:post`、`curated:category:put`、`curated:media:post`、`curated:media:put`、
`curated:provider:post`、`curated:provider:put`

→ 「一般用户」是否应该能**增删改精选内容**？
   - 若 general = 普通使用者 → **全去掉**
   - 若 general = 运营/内容维护 → **保留**

### 落地方式

- **已运行的库**：后台「角色管理 → 一般用户 → 编辑」取消勾选上表"去掉"的标签（不动代码，立即生效）
- **未来部署**：改种子 `app/db/init_data/perm_label_role.csv`，删除 `role_id=2` 对应的那些行

### 结论（甲方 2026-10-10 已定）

- **精选内容写标签：保留**（general = 内容运营角色，保留 `curated:category|media|provider` 的 `:post`/`:put`）
- **管理域读标签：去掉**（10 个，见上表）
- **P2 授予范围：只授予 `admin` + `general` + `Operation` 三个角色**（保持现状行为，但不再"授予所有角色"）

## 三、P2 · 源头治理（不收窄源头就会被灌回来）

### 源头 1：种子数据（curated 之外的全部标签）

`app/db/init_data/perm_label_role.csv` 明确把 15 个标签授予 `role_id=2`：

```
1  perm:user:get            6  perm:menu:get        18 system:dict:detail:get
2  system:dict:get          7  perm:role:get        26 monitor:server:get
3  system:config-setting:get 8 perm:label:get       30 report:excel_generate:get
16 hiker:developer:get     40 monitor:pip:get       53 monitor:cache:get
64 vod:configs:get         68 vod:rules:get         69 vod:houses:get
```

这是**原项目的初始授权设定**（时间戳 2023-12~2024-07），即"一般用户"在原作者眼里就含管理域读权限。
→ 要在种子层收敛，就删掉其中管理域的行（保留 16/64/68/69 等业务标签）。

### 源头 2：`curated/init_menu.py`（★ 会自动再灌回）

```python
# 授予所有角色
role_ids = [r.id for r in db.query(Roles).filter(Roles.is_deleted == 0).all()]
for mid in menu_ids:
    for rid in role_ids:
        ... db.add(RoleMenu(role_id=rid, menu_id=mid))
# 权限标签同样授予所有角色
for label in CURATED_PERM_LABELS:
    _ensure_perm_label(db, label, role_ids)     # ← 把标签授予"每一个"角色
```

由提交 `9b0421a feat(init_menu): 添加权限标签以确保角色授予` 引入。

问题：**任何角色**（包括 general）都会被授予 curated 的**全部权限标签（含读和写）**，
且每次跑初始化都会补齐缺失的授权。**只在后台取消勾选，下次初始化会被再灌回来。**

建议改为：
- 只授予**指定角色**（如 `admin` + 运营角色），而不是"所有未删除角色"
- 或从配置/常量读取目标角色 key 列表
- 写标签（`:post/:put/:delete`）默认不授予非管理角色

## 四、附带发现（小）

- `/permission/menu/{menu_id}` 的标签写成 **`perm:menu:gut`**（应为 `perm:menu:put`）——
  拼写错误会让该写权限校验到错的标签，实际等于失效。
- 两个高危写接口 `PUT /web/database_update`、`PUT /web/rules_refresh` 无登录鉴权、
  仅靠硬编码密钥（`app/core/config.py:118`），已单独开卡。

## 五、优先级建议

| 优先级 | 动作 | 成本 |
|---|---|---|
| P1 | 后台取消 general 的管理域读标签 | 低（配置，立即生效） |
| P2 | 改 `curated/init_menu.py` 的"授予所有角色" | 低（1 处代码） |
| P3 | 改种子 `perm_label_role.csv`（未来部署） | 低 |
| P4 | 修 `perm:menu:gut` 拼写 | 极低 |
| P5 | 两处高危写接口加登录 + 权限依赖 | 中 |
