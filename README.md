### hipy-server 后端项目

##### 技术栈:  python|fastapi|redis|sqlachemy|postgresql|mysql|sqlite|playwright

[套装传送门:hipy-ui](https://github.com/hjdhnx/hipy-ui/)
[巨人的肩膀](https://github.com/JohnDoe1996/fastAPI-vue)
[手机端搭建教程下载](https://wwi.lanzoup.com/iODLy1rykpjc)
[推荐PC端使用zyplayer新版](https://github.com/Hiram-Wong/ZyPlayer/releases)
[并发测试](https://runnergo.apipost.cn/)
[android tv_box推荐下载](https://wwi.lanzoup.com/igYqY1wazxmj)
[android mobile_box推荐下载【tb】](https://wwi.lanzoup.com/ioaM11yjw0li)
[android mobile_box推荐下载【eb】](https://wwvy.lanzouo.com/igDY72eqvt7a)
[android mobile_box推荐下载【tim版tvbox】](https://wwvy.lanzouo.com/iE3Kh2eqvuaj)
[PC Player推荐下载](https://wwi.lanzoup.com/iukwn25lol9i)
[PC 嗅探器推荐下载](https://wwi.lanzoup.com/i4h1T1ztt8fi)
[gpt-4o免费用](https://www.coze.com/s/Zs8Mqh1pY/)
[gpt-4o写筛选](https://www.coze.com/s/Zs8MqmrBF/)
[写源简述](./写源简述.md)
[未来计划](./未来计划.md)
[BOX待修bug描述](./box_bug/bug描述.md)
[他人博客教程](https://www.soeasy.website/TVBox/hipy.html)

#### zy佬一键部署

```shell
bash -c "$(curl -fsSLk https://zy.catni.cn/release/latest/setup.sh)"
```

# hipy-server

[压测工具](https://runnergo.apipost.cn/)
[组件文档](https://element.eleme.io/#/zh-CN/component/input)
[系统资源监控](https://zhuanlan.zhihu.com/p/664812265)
[ws,jinja](https://www.jianshu.com/p/ca9b257a1a44)
[cachetools文档](https://cachetools.readthedocs.io/en/stable/#cachetools.Cache)
[alembic参考文档](https://zhuanlan.zhihu.com/p/306898869?utm_id=0)
[playwright参考文档](https://playwright.dev/python/docs/api/class-playwright)
[zyplayer参考](https://wwi.lanzoup.com/iPbFb23bpdaf)

```shell
alembic init alembic

# sqlalchemy.url = mysql+pymysql://root:root@localhost:3306/hipy
sqlalchemy.url = postgresql://hipy:hipy@localhost:5432/hipy

# import sys, os
# sys.path.append(os.path.join(os.path.dirname(__file__), "./"))
# from db.base_class import Base
# target_metadata = Base.metadata
from apps.system.models.config_settings import ConfigSettings
target_metadata = ConfigSettings.metadata

alembic revision --autogenerate -m "init"
alembic upgrade head
```

### 账号:

| 角色     | 用户名 | 密码     |
| -------- | ------ | -------- |
| 管理员   | admin  | admin123 |
| 运维员   | opt    | opt123   |
| 普通用户 | user   | 123456   |
| 道长     | hjdhnx | 123456   |

### Redis 配置:

本项目 Redis 仅用于登录 token / 验证码缓存。配置写在 `app/configs/.env`：

| 配置项         | 说明       | 本机示例      |
| -------------- | ---------- | ------------- |
| `REDIS_HOST` | Redis 地址 | `127.0.0.1` |
| `REDIS_PORT` | 端口       | `6379`      |
| `REDIS_DB`   | 库号       | `3`         |
| `REDIS_PWD`  | 密码       | `123456`    |

> `REDIS_PWD` 与 `REDIS_PASSWORD` 等价，填任意一个即可（`REDIS_PASSWORD` 优先）。
> 密码含 `@` `/` `:` 等特殊字符无需手动转义，`config.getRedisURL()` 会自动 urlencode。

本机当前使用的 Redis 配置（本地自带 Redis 服务，`requirepass 123456`）：

```ini
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_DB=3
REDIS_PASSWORD=123456
REDIS_PWD=123456
```

若需连接远程 Redis（示例）：

```ini
REDIS_HOST=192.168.120.153
REDIS_PORT=6379
REDIS_DB=6
REDIS_PASSWORD=vrv@1234
REDIS_PWD=vrv@1234
```

> ⚠️ 务必使用**本机可达**的 Redis。若指向不可达地址，连接会阻塞请求，尤其当 Redis 无响应时会导致接口 500 / 超时，甚至整站卡死。
> 连接池已配置 `socket_connect_timeout=3` / `socket_timeout=5`（见 `app/db/cache.py`），可在 Redis 故障时快速失败而非拖死服务。

> 快速自检：`python -c "import redis;print(redis.Redis(host='127.0.0.1',port=6379,db=3,password='123456').ping())"`
> 或运行 `.\run.ps1 -Target Backend -Mode Status`，会一并显示 Redis 连接状态。

## 项目目录结构

> 说明：后端实际运行代码全部位于 `app/` 目录，**所有 python 命令（pip / uvicorn / initial_data）都要先 `cd app` 再执行**。
> 下文以 `app/` 为根展示目录树，并标注每个目录的定位。

```text
hipy-server/
├── app/                          # 【后端主程序】运行时的工作目录
│   ├── main.py                   # 程序入口：创建 FastAPI 应用并用 uvicorn 启动
│   ├── initial_data.py           # 数据库初始化脚本：写入初始数据（账号/菜单/源等）
│   ├── decoder.py / encoder.py   # 源规则编/解码小工具（离线脚本）
│   ├── get_vip_parse.py          # 采集解析地址的辅助脚本
│   ├── hipy_mysql.sql            # MySQL 建表 + 初始数据 SQL
│   ├── hipy_pgsql.sql            # PostgreSQL 建表 + 初始数据 SQL
│   ├── requirements.txt          # 生产依赖
│   ├── requirements-dev.txt      # 开发依赖
│   │
│   ├── core/                     # 【核心基础设施】框架层，不含业务
│   │   ├── config.py             # Settings 配置类，读取 configs/.env（含数据库/Redis）
│   │   ├── constants.py          # 全局常量（token 前缀、过期时间、BASE_DIR 等）
│   │   ├── server.py             # InitializeApp：挂载静态目录、Redis、路由、定时任务、嗅探器
│   │   ├── middleware.py         # 全局中间件
│   │   └── logger.py             # 日志初始化
│   │
│   ├── common/                   # 【通用业务组件】跨模块复用的“地基”
│   │   ├── curd_base.py          # CRUDBase 泛型基类：分页/搜索/软删除/批量操作
│   │   ├── deps.py               # FastAPI 依赖：get_db / get_redis / check_jwt_token / user_perm
│   │   ├── resp.py               # 统一响应体（respSuccessJson / respErrorJson）
│   │   ├── error_code.py         # 错误码枚举
│   │   ├── exceptions.py         # 全局异常注册
│   │   ├── schemas.py            # 通用 Pydantic 模型
│   │   ├── security.py           # JWT 生成与密码哈希校验
│   │   ├── task_apscheduler.py   # APScheduler 定时任务（持久化到数据库）
│   │   └── sys_schedule.py       # 系统调度辅助
│   │
│   ├── db/                       # 【数据库层】连接与初始化
│   │   ├── session.py            # engine / SessionLocal（SQLAlchemy 会话）
│   │   ├── base_class.py         # ORM Base 基类
│   │   ├── fields.py             # 公共字段封装（creator_id / 时间戳 / is_deleted 等）
│   │   ├── cache.py              # Redis 注册与连接（异步 aioredis + 同步 redis）
│   │   ├── init_db.py            # 初始数据导入逻辑
│   │   └── init_data/            # 初始数据 CSV（菜单/用户/角色/权限/字典/源等）
│   │
│   ├── apps/                     # 【业务模块】每个子目录是一个垂直切片，见下方约定
│   │   ├── __init__.py           # 汇总各模块路由，统一挂载到 /api/v1
│   │   ├── base_template/        # 新模块脚手架模板（models/curd/schemas/views）
│   │   ├── user/                 # 用户：登录/注册/验证码/找回密码
│   │   ├── permission/           # RBAC 权限：用户、角色、菜单、权限标签
│   │   ├── system/               # 系统设置与数据字典
│   │   ├── vod/                  # 核心业务：爬虫源规则/订阅/配置/源仓库
│   │   ├── hiker/                # 海阔视界源管理（开发者/规则类型/规则）
│   │   ├── monitor/              # 监控：服务器信息、登录日志、定时任务、pip、缓存
│   │   ├── report/               # Excel 报表导出（reports/ 下每个报表一个文件）
│   │   ├── web/                  # 网页端点：TVBox 配置生成、T4 静态文件、ws
│   │   └── curated/              # 精选内容（providers 站点适配器 + service 业务层）
│   │
│   ├── t4/                       # 【T4/drpy 引擎】JS 源运行环境
│   │   ├── core/                 # 引擎核心：app / loader / runner / trigger
│   │   ├── base/                 # 基础解析器（htmlParser，多语言实现）
│   │   ├── qjs_drpy/             # QuickJS 运行时模块
│   │   ├── spiders/              # 本地 spider 脚本与运行日志
│   │   └── files/                # 内置源与库：JS/JSON/M3U/JAR/PHP/drpy_libs 等
│   │
│   ├── sniffer/                  # 【嗅探器】selenium / playwright 抓取真实播放地址
│   ├── tasks/                    # 【独立任务脚本】爬虫与定时任务（可被调度器调用）
│   ├── network/                  # 【网络层】统一请求封装（request.py）
│   ├── utils/                    # 【工具集】验证码、邮件、加密、路径、server_info、QuickJS 等
│   ├── templates/                # 模板页面与前端静态资源（/web 挂载）
│   ├── static/                   # 静态资源（/static 挂载）
│   ├── media/                    # 上传媒体文件（/media 挂载，含头像）
│   ├── configs/                  # 环境配置模板：*.env（sqlite/mysql/pg）、日志、supervisor
│   ├── alembic/                  # 数据库迁移脚本
│   ├── tests/                    # pytest 测试
│   ├── email-templates/          # 邮件模板（注册/找回密码）
│   ├── log/                      # 运行日志输出目录
│   └── whl/                      # 离线依赖 wheel 包
│
├── docker-compose.yml            # 一键部署编排（含 redis 服务）
├── hipy-all-docker/              # 全量 Docker 构建（nginx 等周边）
├── Dockerfile-hipy-server        # 后端镜像构建文件
├── run.ps1                       # Windows 运维脚本（启动/状态检查等）
├── timer/                        # 定时/嗅探相关辅助脚本
├── box_bug/                      # 已知问题记录
├── logs/                         # 部署级日志
└── README.md
```

### 目录定位与设计约定

项目采用 **分层 + 按业务垂直切分** 的组织方式，定位如下：

- **`core/` 框架层**：只放与具体业务无关的基础设施（配置、常量、应用装配、中间件、日志）。新增全局能力优先放这里。
- **`common/` 通用组件层**：跨模块复用的业务地基，最典型的是 `curd_base.py`（CRUDBase）和 `deps.py`（依赖注入）。
- **`db/` 数据访问层**：数据库连接、ORM Base、公共字段、Redis 连接、初始数据，全部与业务解耦。
- **`apps/` 业务模块层**：核心。每个业务目录是一个“垂直切片”，内部统一遵循四件套：

  | 子目录/文件                | 职责                                                      |
  | -------------------------- | --------------------------------------------------------- |
  | `models/`                | SQLAlchemy ORM 模型（建表）                               |
  | `schemas/`               | Pydantic 出入参模型（校验/序列化）                        |
  | `curd/`                  | 数据访问逻辑，继承`common/curd_base.py` 的 `CRUDBase` |
  | `views.py` 或 `views/` | FastAPI 路由，只做参数校验与流程编排                      |

  新增业务模块时，直接复制 **`apps/base_template/`** 脚手架，再在 `apps/__init__.py` 中 `include_router` 注册即可。
- **`apps/curated/` 例外的三层结构**：`providers/`（站点适配器，新增站点继承 `BaseProvider` 并在 `registry` 注册）、`service.py`（业务服务层，可同时被后台 API 与运行时源调用）、`views.py`（HTTP 接口）。
- **`t4/` 源引擎层**：TVBox/drpy JS 源的运行与解析环境，与后台 API 分离，`files/` 内是内置源与依赖库。
- **`sniffer/` 与 `tasks/`**：旁路能力。嗅探器负责抓取播放地址，`tasks/` 是可由定时任务调度的独立脚本。
- **`utils/`**：无状态工具函数集合，任何层都可以引用。

### 相关文档

| 文档 | 内容 |
| --- | --- |
| [docs/hipy-vod-source-guide.md](docs/hipy-vod-source-guide.md) | 视频源管理使用说明：源规则 / 订阅配置 / 上游仓库的定位、数据流，TVBox 该复制哪个配置地址，以及订阅正则到底在过滤哪份数据（实现细节） |
| [docs/live-source-guide.md](docs/live-source-guide.md) | 直播源接入与管理：fanmingming/live、Tvlist、iptv-org 三个外部源如何聚合、去重、补台标、缓存台标与 EPG、测活，并接入 `vod_zb_file` / 定时任务 / `/epg` 接口 |
| [deploy-phone.ps1](deploy-phone.ps1) | 电脑一键同步到手机：自动定位手机 IP、构建前端、备份、上传后端/前端、迁移数据库、重启并健康检查 |

### 请求流转（便于定位问题）

```text
HTTP 请求
  └─> core/middleware.py        全局中间件（CORS 等）
        └─> apps/<模块>/views.py  路由处理
              ├─ common/deps.py       依赖注入（鉴权 jwt / 权限 / db / redis）
              ├─ apps/<模块>/schemas 入参校验
              ├─ apps/<模块>/curd    数据读写（继承 CRUDBase）
              └─ common/resp.py      统一响应
                    └─ db/session.py + db/cache.py  数据库 / Redis
```

> 路由注册集中在 `app/apps/__init__.py`，业务 API 统一前缀 `/api/v1`，网页端点（配置生成/静态文件/ws）走无前缀的 `web_router`。

## 项目部署

> 注意：
> 本源码中所有配置文件都使用 配置文件模板(.example)的形式上传, 目的是为了方便我自己的配置信息不被泄露。
> 部署项目时需要将[.example]后缀去掉才能使用。需要用到配置文件的地方均在后续说明有列出。
> 最低运行条件:python3.8,安装了redis,.env配置的sqlite数据库,正确安装完整的requirements.txt

### FIRST

克隆项目主分支

```shell
git clone -b master https://github.com/hjdhnx/hipy-server.git
```

数据库中创建DB

```sql
CREATE
DATABASE hipy;  -- 仅供参考根据自己项目名和所用的数据库类型 修改SQL， 
```

运行脚本初始化数据库数据

```shell
cd ./hipy-server/app
python initial_data.py
```

### APP

1. 安装python3、virtualenv(pycharm自带)、Nginx、 supervisor

```shell
# 略
```

2. 安装必要第三方库

```shell
cd ./hipy-server/app   # 进入到后端程序代码的根目录

# 没有pycharm的注意下面两行代码，有的就跳过
python -m virtualenv venv     # 创建虚拟环境
source ./venv/bin/activate      # 进入虚拟环境

python -m pip install -i https://mirrors.cloud.tencent.com/pypi/simple --upgrade pip # 用腾讯源临时升级pip
pip config set global.index-url https://mirrors.cloud.tencent.com/pypi/simple # 换源
pip install -r requirements.txt   # 安装库  可使用谷内源：  -i https://pypi.tuna.tsinghua.edu.cn/simple
```

3. 准备程序配置文件

```shell
cp ./configs/.env.example  ./configs/.env    # 复制配置模板

vim ./configs/.env     # 拷贝配置文件

# python main.py   # 测试项目是否成功运行，
```

> 根据需要修改.env的配置内容，配置所有的参数参考 ./core/config.py -> class Settings

4. 使用supervisor管理项目(生产环境)

```shell
cp ./configs/supervisor.conf.example  ./configs/supervisor.conf   # 拷贝配置文件

sudo ln -s /home/ubuntu/opt/hipy-server/app/configs/supervisor.conf /etc/supervisor/conf.d/hipy-server.conf   # 配置文件软链到supervisor的配置文件目录， 此处目录路径仅供参考

vim ./configs/supervisor.conf    # 编辑配置文件,已有参考配置，按需修改

sudo supervisorctl update     # 更新supervisor

sudo supervisorctl start hipy-server:   # 启动项目
```

### github被墙无法提交代码的操作说明

[看这篇文章就够了](https://raw.hellogithub.com/hosts)

懒人直通车:
[到作者github上下载程序](https://github.com/oldj/SwitchHosts/releases) 或着
[道长的蓝奏云](https://wwi.lanzoup.com/iYyVp1mtojwd)

程序里配置下面的链接并刷新即可

```text
https://raw.hellogithub.com/hosts
```

### 大文件查找命令

```shell
find / -type f -size +50M | xargs ls -Slh
```

### 防白嫖，禁止ip直接访问

nginx配置

```shell
server {
	listen 8009;
	server_name server.web.cn;

	if ($host != 'server.web.cn') {
	return 444; #444为不响应请求，节省服务器资源；403为拒绝请求，会响应请求
	}
}

```

### 版权

前端VUE代码使用若依修改vue-element-admin的进行修改，版权参照他们的版权。
后端FastAPI代码基于fastAPI-vue二次开发，可供学习和商用，禁止直接转卖代码，转载代码请带上出处。

### 致谢

- FastAPI
- vue
- element
- vue-element-admin
- 若依Ruoyi

### 免责声明

1. 此程序仅用于学习研究，不保证其合法性、准确性、有效性，请根据情况自行判断，本人对此不承担任何保证责任。
2. 由于此程序仅用于学习研究，您必须在下载后 24 小时内将所有内容从您的计算机或手机或任何存储设备中完全删除，若违反规定引起任何事件本人对此均不负责。
3. 请勿将此程序用于任何商业或非法目的，若违反规定请自行对此负责。
4. 此程序涉及应用与本人无关，本人对因此引起的任何隐私泄漏或其他后果不承担任何责任。
5. 本人对任何程序引发的问题概不负责，包括但不限于由程序错误引起的任何损失和损害。
6. 如果任何单位或个人认为此程序可能涉嫌侵犯其权利，应及时通知并提供身份证明，所有权证明，我们将在收到认证文件确认后删除此程序。
7. 所有直接或间接使用、查看此程序的人均应该仔细阅读此声明。本人保留随时更改或补充此声明的权利。一旦您使用或复制了此程序，即视为您已接受此免责声明。
