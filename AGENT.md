# AGENT.md · 给 AI 助手 / 协作者的落地须知

> 这份文件是**给自动化助手看的**（人也可以看）。目标是：拿到本项目后不必重新摸索环境，
> 不会重复踩已经踩过的坑。人看的完整说明见 `README.md`、`docs/live-source-guide.md`、
> `hipy手机部署与使用手册.md`。

---

## 1. 项目速览

`hipy-server` = FastAPI + SQLAlchemy(SQLite) + APScheduler + Vue 前端，做 TVBox 的
源/直播源聚合、内容搜索、定时任务。生产环境跑在一台**未 root 的小米 9 SE（Android 11）
的 Termux** 里，局域网访问。

| 组件 | 位置 | 端口 |
| --- | --- | --- |
| 后端 | `~/hipy/app`（`python main.py`） | 5707 |
| 前端 | `~/hipy/dist`（`spa_server.py`） | 8080 |
| SSH | Termux sshd，用户 `u0_a212` | 8022 |
| 数据库 | `~/hipy/app/db/hipy.db` | — |
| 运行数据 | `~/hipy/app/t4/files/{m3u,json,txt,logo}` | — |

- 登录：`admin / 123456`；前端提交 `md5(明文)`，后端存 `bcrypt(md5(pwd))`。
- 鉴权头是 **`token: <值>`**（不是 `Authorization: Bearer`）。
- API 前缀 `/api/v1/...`。

---

## 2. 本机（Windows 开发机）环境

- **必须用 `venv/Scripts/python.exe`** 跑本项目的 Python。系统 `python` 是 3.12 + pydantic 2，
  一 import `core.config` 就炸；venv 里是 pydantic 1.10.18 / apscheduler 3.10.4。
- 语法自检：`venv/Scripts/python.exe -m py_compile <file>`。
- 本机有代理时注意：GitHub 相关请求要走 `127.0.0.1:7897`；curl 测手机请加 `--noproxy '*'`。

---

## 3. 部署到手机：**一律优先 `.\deploy-phone.ps1`（走 SSH）**

> 这是本项目最重要的一条约定，见 2026-10 的教训：**adb 连接不稳定**，经常
> `adb devices` 变空 / `5555` 拒绝连接，导致部署和排障中断；SSH 一直很稳。

```powershell
.\deploy-phone.ps1                 # 全量：构建前端 + 备份 + 上传 + 迁移 + 重启 + 健康检查
.\deploy-phone.ps1 -SkipBuild -SkipRestart
.\deploy-phone.ps1 -RefreshLive    # 顺带跑一次直播源聚合
```

单独同步一两个文件（最快，够用）：

```bash
scp -F ~/.ssh/config app/tasks/live_health.py hipy:~/hipy/app/tasks/live_health.py
ssh -F ~/.ssh/config hipy 'md5sum ~/hipy/app/tasks/live_health.py'
```

- `~/.ssh/config` 里已配好 `Host hipy`（IP、8022、`id_ed25519_hipy`），所以命令里只要写 `hipy`。
- **传完必须核对 md5**：Windows 上是 CRLF，手机上是 LF，比较前先
  `sed -i "s/\r$//" <file>` 或本地 `sed 's/\r$//' file | md5sum`。
- 只有在 SSH 完全不可用时才退回 adb 直推：
  `adb shell "run-as com.termux sh -c 'cat > files/home/hipy/app/xxx.py'"`（见第 6 节风险）。

---

## 4. 重启 / 探活 / 看门狗

```bash
# 从本机发起（注意 setsid + 三个重定向，否则 SSH 通道会被挂住不返回）
ssh -F ~/.ssh/config hipy 'bash ~/hipy/_restart.sh' </dev/null
ssh -F ~/.ssh/config hipy 'setsid nohup bash ~/hipy/start_all.sh >/dev/null 2>&1 </dev/null' </dev/null
curl -s -o /dev/null -w '%{http_code}\n' -m 5 http://127.0.0.1:5707/docs   # 200 才算活着
tail -20 ~/hipy/watchdog.log                              # 看门狗日志
```

> **别在 SSH 前台直接跑 `start_all.sh`**：它会 `termux-wake-lock` 并挂后台进程，
> 终端不返回 → 本机这条命令会一直挂着（2026-10-28 就这样白等了 4 小时，服务其实早起来了）。
> 一律 `setsid nohup ... >/dev/null 2>&1 </dev/null` 或直接用 `_restart.sh`，
> 并且本机所有远程命令都带 `timeout` + `</dev/null`。

- 后端脚本：`start_all.sh`（含看门狗第 5 步）、`start_backend.sh`、`_restart.sh`、
  `_watchdog.sh`、`_fix.sh`（设好 HOME/PREFIX/PY/PATH，跑 python 用它包一层：
  `bash ~/hipy/_fix.sh python -m tasks.live_health --stats`）。
- 看门狗：60s 探一次 `/docs`，连续 3 次非 200 → `pkill` + 重启；另外**所有任务的下次
  执行时间都过期 15 分钟以上**（调度器罢工）也重启。
- **改完 Python 代码必须重启后端才生效**：`_format_fun` 用 `importlib.import_module`，
  已加载的模块不会重新读盘。

---

## 5. 已踩过的坑（不要重犯）

1. **调度器静默罢工**：在 APScheduler 的事件回调（`job_listener`）里直接 `remove_job`，
   轮末 `update_job` 抛 `JobLookupError` 会打断整个调度循环 —— 网页/接口全正常，但所有定时
   任务永不执行、`next_run` 冻结。已改为 `_defer_remove()` + 回调兜异常。
2. **进程池 fork 继承监听 socket**：`ProcessPoolExecutor` 在手机上 fork 出的子进程会继承
   5707 的监听 fd，主进程死后端口仍被占、无人 accept → 表现为"网页转圈假死"。
   手机 `.env` 必须 `SCHEDULER_EXECUTOR=thread`（`SCHEDULER_POOL_SIZE=4`）。
3. **runas_app 域的后端杀不掉**：用 `adb shell run-as` 拉起的进程属于 `runas_app` 域，
   从 Termux/SSH 会话（`untrusted_app_27`）里 `pkill` 会 `Permission denied`，
   只能 `adb shell am force-stop com.termux` 或手机设置里强制停止 Termux。
   → **所以拉服务一律在 SSH/Termux 会话里做，别用 adb run-as。**
   这种进程连接口都杀不动：`am force-stop com.termux` / `am kill` 都无效（实测），
   唯一办法是**同域杀**：`adb shell 'run-as com.termux kill -9 <pid>'`。
6. **Termux 会话的一次性自启钩子**：`~/.bashrc`、`~/.profile` 里有一行
   `[ -f $HOME/hipy/.autostart_once ] && [ -t 1 ] && bash $HOME/hipy/_autostart_once.sh`，
   只要 `touch ~/hipy/.autostart_once` 再让用户打开一次 Termux，服务就会在 app 域自动拉起
   （标记执行后自动删除，不会反复触发）。
4. **不要在两个任务里写同一份 m3u/mytv**：`live_source`（03:30 重建）与 `live_check`
   （0/6/12/18 点复查）共用一把锁 `t4/files/json/.live_check.lock`，抢不到就放弃本轮；
   `tv_spider` 默认 `write_mytv=false`。
5. **测活并发打满上行会误杀**：`check.workers=8`、`check.timeout=10`，
   `health.max_drop_ratio=0.5` 是保险丝（超了就回滚/中止，不覆盖 m3u）。
6. **JSON 配置写盘**：`json.dumps(..., ensure_ascii=False, indent=2)` + 末尾换行 +
   `newline='\n'`，否则手机和仓库会来回漂格式。
7. 手机 kill 后 `ps` 看不到别的域的进程；`/proc/net/tcp`、cgroup 都读不到，别指望定位端口归属。
8. **`Drpy` 每次重建都会漏线程**：`t4/qjs_drpy/qjs_drpy.py` 里每个实例自带
   `ThreadPoolExecutor(max_workers=1)` + quickjs Context，旧实例不 `shutdown()` 就是泄漏。
   已在 `Drpy.close()` / `vod_views._release_vod()` 里修掉（48h 曾涨到 RSS 903MB、线程 413），
   看门狗也加了 RSS>1200MB / 线程>600 自动重启的兜底。
9. **`pkill -f xxx.sh` 会把自己那条 SSH 命令也匹配进去**（远程命令字符串里含同样文本），
   结果是自杀式断连。要带括号避坑：`pkill -f "[_]watchdog.sh"`。
10. **Termux 时区/时钟正常，但本机会跑偏**：远程命令一律带 `timeout`，别用“等它返回”估算耗时。

---

## 6. 定时任务（`t_job`，迁移脚本注册，不走 UI）

| id | job_id | 函数 | cron | 职责 |
| --- | --- | --- | --- | --- |
| 16 | `tv_spider` | `tasks.tv_spider.main` | `0 45 3 * * ?` | 抓 ssili126/tv 的 txt 列表 → `txt/tv.txt`（**不写** mytv.txt） |
| 17 | `live_source` | `tasks.live_source.main` | `0 30 3 * * ?` | 拉上游 + 测活 + 去重 + 重建 `m3u/live_merged.m3u` + 台标/EPG |
| 18 | `live_check` | `tasks.live_health.main` | `0 0 0/6 * * ?` | 只复查现有 m3u，按台账剔新死线 |

- 注册/改 cron 用迁移脚本：`app/db/migrate_live_health.py`（幂等，`--cron/--disable`）。
- 直接改 DB（手机没有 sqlite3 二进制，用 python）：
  `python -c "import sqlite3;c=sqlite3.connect('db/hipy.db');c.execute('update t_job set cron_expression=? where job_id=?',('0 45 3 * * ?','tv_spider'));c.commit()"`
- 改完要重启后端才会按新 cron 装载。

---

## 7. 直播源/测活关键文件

| 文件 | 作用 |
| --- | --- |
| `app/tasks/live_source.py` | 聚合主流程（拉源→去重→测活→频道去重→写 m3u/meta/死链报告） |
| `app/tasks/live_health.py` | 三级测活 + 台账状态机 + `live_check` 任务 + CLI |
| `scripts/_watchdog.sh` | 手机看门狗脚本的仓库副本（实际运行在 `~/hipy/_watchdog.sh`）；改完要 scp 回手机 |
| `app/t4/files/json/live_sources.json` | 源列表与 `check` / `health` / `output` 参数 |
| `app/t4/files/json/live_health.json` | 台账（`ok/suspect/dead`、失败次数、冷却时间），**不入库、不提交** |
| `app/t4/files/json/live_dead_report.json` | 死链报告（`#` 注释文本格式，不是合法 JSON） |

常用运维命令（手机）：

```bash
bash ~/hipy/_fix.sh python -m tasks.live_health --stats       # 看台账
bash ~/hipy/_fix.sh python -m tasks.live_health --recheck     # 立刻复查现有 m3u
bash ~/hipy/_fix.sh python -m tasks.live_source               # 立刻重建（会吃 3~6 分钟）
cp ~/hipy/app/t4/files/m3u/live_merged.m3u.bak ~/hipy/app/t4/files/m3u/live_merged.m3u  # 回滚
```

---

## 8. 提交前自检

1. `venv/Scripts/python.exe -m py_compile` 所有改动的 py；
2. JSON 用 `python -m json.tool` 过一遍；
3. 手机端 md5 与本地一致（`sed 's/\r$//'` 后比对）；
4. 后端重启后 `curl /docs` 200、`/api/v1/monitor/job/now` 的 `next_run` 在未来；
5. 更新对应文档：`docs/live-source-guide.md`（技术细节）、
   `hipy手机部署与使用手册.md`（使用者视角）。
