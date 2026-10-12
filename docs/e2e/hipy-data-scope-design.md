# HiPy 数据范围（行级隔离）实施方案

> 目标：在现有"功能级权限标签"之上，增加一层**数据范围（行级）控制**。
> 甲方 2026-10-10 已确认的规则见下。

## 一、目标模型（已确认）

角色级**数据范围**三档，后台可切换：

| 档位 | 值 | 含义 | 角色初值 |
|---|---|---|---|
| 仅本人 | 1 | 只看/只改自己创建的 | — |
| 本人 + 超管只读 | 2 | 看自己 + 超管(creator_id=1)的；只能改自己的 | general、Operation |
| 全部 | 3 | 不隔离 | admin |

规则细节：

1. 一般用户可**增删改自己创建**的数据
2. 一般用户之间**互不可见**
3. 超管数据（`creator_id == 1`）对档位 2 的用户**只读**：可见、**不可改、不可删**
4. 管理员（Operation）**与一般用户同档**（也隔离）
5. 覆盖**全部业务模块**

## 二、"全部业务模块"的落点（10 个实体）

| 模块 | 实体 | 表 |
|---|---|---|
| curated | CuratedCategory / CuratedEpisode / CuratedMedia / CuratedProvider | curated_* |
| vod | VodRules / VodSubs / VodConfigs | t_vod_* |
| hiker | HikerRule / HikerRuleType / HikerDeveloper | t_hiker_* |

**不纳入**（属管理域，保持现状）：`permission/*`（用户/角色/菜单/标签）、`system/*`（字典/配置）、
`monitor/*`（任务/日志）、`report/*`、`user/*`、`web/*`。
→ 若你希望 monitor 的"定时任务"也隔离，请指出。

## 三、技术设计

### 3.1 数据模型

`t_roles` 增加列 `data_scope`（Integer，默认 2，非空）：

```sql
ALTER TABLE t_roles ADD COLUMN data_scope INTEGER DEFAULT 2;
UPDATE t_roles SET data_scope = 3 WHERE key = 'admin';
UPDATE t_roles SET data_scope = 2 WHERE key IN ('general', 'Operation');
```

同步改 `apps/permission/models/role.py` 的 `Roles`，以及后台角色新增/编辑接口与前端表单。

### 3.2 统一工具（新增 `app/common/data_scope.py`）

```python
SUPER_ADMIN_ID = 1          # 超管数据所有者（甲方口径：creator_id=1）

def user_scope(db, user) -> int:
    """返回当前用户角色的最大数据范围：3/2/1；超管恒为 3"""

def apply_scope(query, model, db, user):
    """对查询追加数据范围条件（列表/详情统一调用）"""
    s = user_scope(db, user)
    if s == 3: return query
    if s == 2: return query.filter(or_(model.creator_id == user['id'],
                                       model.creator_id == SUPER_ADMIN_ID))
    return query.filter(model.creator_id == user['id'])

def ensure_writable(obj, db, user):
    """写/删前校验归属：超管数据只读；他人数据不可见亦不可写"""
    if user_scope(db, user) == 3: return
    if obj is None or obj.creator_id != user['id']:
        raise UserPermError()   # 或专门的"无数据权限"
```

### 3.3 改造落点（每个实体 5 类接口）

- 列表查询 → `apply_scope`
- 详情查询 → `apply_scope`（查不到即视为无权限）
- 新增 → `creator_id` 取当前用户（基类已保证）
- 修改 / 删除 → 先 `ensure_writable`
- **批量接口**（如 `curated/media` 的 batch visible/status/remove、批量删除）→ 逐个 `ensure_writable`，
  部分无权限时整体拒绝或跳过（需定策略，见"待定"）

## 四、需要一并处理的冲突点（重要）

1. **`/curated/media` 目前是"未认证即可读"**（此前确认过"刻意公开"）。
   但按新模型，它是**后台"内容库"管理列表**，应当按数据范围过滤 → 与"公开"冲突。
   建议：**后台管理列表按范围过滤；客户端取数走 `catalog` / `kid_config`（订阅维度）**，两条路径分开。
   若客户端确实在直接调 `/curated/media`，需要先确认，否则会打断客户端。
2. **`creator_id=0` 的系统内置数据**（如 1 条 provider、1 条 vod_rule、1 条 vod_subs）：
   按甲方口径（只认 `creator_id=1`）→ 档位 2 的用户**看不到**这些内置数据。
   若这些内置数据是必须可见的基础数据，需要放宽为 `in_ (0, 1)`。**待确认。**
3. **档位 2 用户对超管数据"只读"** 在前端要体现：内容库里超管的行应隐藏/禁用"编辑/删除"按钮
   （后端为准，前端可后置到第二阶段）。

## 五、实施阶段（建议）

| 阶段 | 内容 | 验收 |
|---|---|---|
| S1 | 加 `data_scope` 列 + `data_scope.py` 工具 + **curated 4 实体**改造 | 矩阵测试（见下）通过 |
| S2 | vod 3 + hiker 3 实体改造 | 同上 |
| S3 | 批量接口细化 + 前端按钮态 + 角色管理页的"数据范围"表单项 | 端到端复测 |

**验收矩阵**（每个实体、每类操作）：

| 操作者 \ 数据所有者 | 自己 | 其他一般用户 | 超管(creator_id=1) |
|---|---|---|---|
| admin | 读/改/删 ✅ | ✅ | ✅ |
| general A | 读/改/删 ✅ | **不可见** | **可见、不可改删** |
| Operation | 同 general A | 不可见 | 可见、不可改删 |

## 六、待确认（2 点需甲方定，2 点我方按建议先定）

**我方按建议先定（如有异议请指出）：**
1. "全部业务模块" = 上表 **10 个实体**；`monitor` 的定时任务/日志属管理域，**不纳入**。
2. 批量接口遇到"部分无权限"时的策略 = **整体拒绝**（返回被拒明细），避免半成功状态。

**需甲方确认：**
1. `creator_id=0` 的系统内置数据：档位 2 用户应当**可见**（放宽为 0 或 1）还是**不可见**（严格只认 1）？
2. `/curated/media` 拆成"后台管理列表(按范围过滤) + 客户端读路径(catalog/kid_config)"是否可行——
   客户端现在是否直接调用 `/curated/media`？
