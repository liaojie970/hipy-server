# 直播源接入与管理：fanmingming/live + Tvlist + iptv-org

> 本文说明如何把下面三个外部直播源项目接入 hipy-server，并用「配置 + 定时任务」的方式长期维护。
>
> - `fanmingming/live`：可直连访问的电视/广播图标库与直播源，自带台标和 EPG，质量相对稳定。
> - `imDazui/Tvlist-awesome-m3u-m3u8`：IPTV / M3U 资源汇总，文件多、覆盖广，但失效率和地域性都较高。
> - `iptv-org/iptv`：全球公开 IPTV 频道合集，按国家/地区/语言拆分成 m3u，频道数量最多，但以英文名为主，部分频道有地区限制。

## 一、先搞清楚：本项目里的「直播」在哪

hipy-server 的直播不走「源规则 / 订阅配置」，而是直接写进自动生成的 TVBox 配置：

```
后台「参数配置」
  ├─ vod_zb_use   = file | url        # 用本地文件还是外链
  ├─ vod_zb_file  = txt/mytv.txt      # 本地文件（value_type=file）
  └─ vod_zb_url   = https://...       # 外链（value_type=url）
        │
        ▼
t4/files/txt/config.txt 里的 "lives" 字段
        │
        ▼
/config/{mode} 生成的配置 → TVBox 等播放端的「直播」页
```

关键点：

- `vod_zb_file` 填的是 **相对 `t4/files/` 的路径**，例如 `txt/mytv.txt`、`m3u/live_merged.m3u`。
  生成配置时会自动拼成 `http://<你的地址>/files/<该路径>`。
- `m3u` 是 `vod_rule_group` 字典里已注册的文件分组，`/files/m3u/xxx.m3u` 可以直接访问。
- 本项目**没有**直播源的后台增删改查页面。要做「管理」，本质上就是管理下面这份文件：
  - 源清单：`t4/files/json/live_sources.json`（本文新增）
  - 聚合任务：`tasks/live_source.py`（本文新增）
  - 聚合产物：`t4/files/m3u/live_merged.m3u`（可选镜像到 `t4/files/txt/mytv.txt` 兼容旧配置）

## 二、三个源怎么定位

| 项目 | 适合做什么 | 不适合做什么 |
| --- | --- | --- |
| `fanmingming/live` | 作为**主源**。它提供 `tv/m3u/index.m3u`（IPv4）、`ipv6.m3u`、`itv.m3u`、`radio/m3u/index.m3u`，每条频道自带 `tvg-id / tvg-name / tvg-logo`，还有 EPG `e.xml`。台标库就是仓库里的 `tv/*.png`、`radio/*.png`。 | 频道数量有限，主要是央视、卫视和部分港澳台/海外。 |
| `Tvlist-awesome-m3u-m3u8` | 作为**补充池**。`m3u/` 下有大量按地区/运营商拆分的文件，可以按需挑选，例如 `CCTV.m3u`、`_CCTVHD.m3u8`、`台湾香港澳门202506.m3u`。 | 不适合把 5000 条大合集直接塞进配置：失效多、体积大、播放端加载慢。 |
| `iptv-org/iptv` | 作为**海外/港澳台补充**。按国家拆分的 `countries/cn.m3u`、`hk.m3u`、`tw.m3u` 体积小、带台标和分组；`streams/*.m3u` 是原始数据，条数更多但不带台标。 | 全球主列表 `index.m3u` 有 2000+ 频道，体积大、英文名多，不适合默认开启；直播源本身不保证可用。 |

推荐策略：

1. **fanmingming 做主源**（优先级 1，默认启用）；
2. **Tvlist 只挑 1～3 个文件做补充**（优先级 20+）；
3. **iptv-org 按国家/地区选**（优先级 30+），默认开中国、香港、台湾；
4. 聚合时**按 `tvg-id` / 频道名去重**，同频道优先保留 fanmingming；
5. 需要更高可用性时再打开**并发测活**。

## 三、快速开始（推荐方案：本地聚合）

### 1. 看一眼源清单

`app/t4/files/json/live_sources.json` 里默认启用了五个源：

```json
{
  "sources": [
    { "name": "fanmingming-ipv4", "url": "https://live.fanmingming.com/tv/m3u/index.m3u", "enabled": true, "priority": 1 },
    { "name": "tvlist-cctv", "url": ".../m3u/CCTV.m3u", "enabled": true, "priority": 20 },
    { "name": "iptv-org-cn", "url": "https://iptv-org.github.io/iptv/countries/cn.m3u", "enabled": true, "priority": 30 },
    { "name": "iptv-org-hk", "url": "https://iptv-org.github.io/iptv/countries/hk.m3u", "enabled": true, "priority": 31 },
    { "name": "iptv-org-tw", "url": "https://iptv-org.github.io/iptv/countries/tw.m3u", "enabled": true, "priority": 32 }
  ]
}
```

`fallback_urls` 会在主地址不通时自动回退到 GitHub raw（再结合 `request.github_proxies` 加速）。
默认还会把台标下载到本地、把 fanmingming 的 `e.xml` 裁剪后缓存到本地，详见第六节。
`fanmingming` 的 `live.fanmingming.com` 在部分网络下会超时，所以默认配了 raw 回退；
iptv-org 的 `countries/*.m3u` 是 GitHub Pages 生成的版本，带台标，回退的 `streams/*.m3u` 是原始文件，条数更多但**不带台标**。

#### 国内网络下实际会走哪条路

| 源 | 首先尝试 | 失败后 |
| --- | --- | --- |
| `fanmingming` | `live.fanmingming.com`（非 GitHub） | `raw.githubusercontent.com`，走 `github_proxies` 加速 |
| `Tvlist` | `raw.githubusercontent.com`，走 `github_proxies` 加速 | 直连 raw |
| `iptv-org` | `iptv-org.github.io`（GitHub Pages） | `raw.githubusercontent.com`，走 `github_proxies` 加速 |

- `github_proxies` 是**有序列表**，默认 `gh-proxy.com`、`ghproxy.net`；哪个通用哪个，也可以换成你自己的反代。
- 加速站都是第三方服务，不保证长期可用；全部失败后任务还会直连 raw 再试一次。
- 所有源都失败时任务会报错，**不会覆盖**上一份 `live_merged.m3u`；成功但条数低于 `output.min_final_count` 时同样不覆盖。

### 2. 生成一次聚合结果

有三种触发方式，按场景选：

| 方式 | 做什么 | 适合 |
| --- | --- | --- |
| `python -m tasks.live_source` | 只跑一次聚合，不启动 Web 服务 | 第一次生成、调试源 |
| `.\run.ps1` | 编译并启动后端 + 前端；**本身不直接跑聚合** | 日常启动系统 |
| 后台「定时任务 → 执行一次」 | 让调度器跑一次 | 服务已启动、临时刷新 |

在 `app/` 目录下执行（用项目自带 venv 时换成 `..\venv\Scripts\python.exe`）：

```shell
cd app
python -m tasks.live_source
```

`-m` 是必要的：`tasks/live_source.py` 里有 `from core.logger import logger`、
`from utils.define import ...` 这类导入，默认以 `app/` 为根目录。`python -m tasks.live_source` 会让 Python 把 `app/` 放进
`sys.path`；而 `python tasks/live_source.py` 会把 `tasks/` 当成根目录，容易报
`ModuleNotFoundError: core`。

`.\run.ps1` 只负责启动服务，不会主动生成 m3u。服务启动后，只有满足下面任一条件才会跑聚合：

- 后台定时任务里 `live_source` 处于「使用中」，后端重启时调度器会按数据库里的 `next_run` 续跑；
  `next_run` 已过期时约 10 秒后补跑一次（`JOB_DELTA`），之后按 cron 执行；
- 你在后台点了「执行一次」。

`run.ps1` 默认给后端进程设置 `HTTP_PROXY=http://127.0.0.1:7897`；如果本机没开这个代理，
用 `.\run.ps1 -NoProxy` 启动。任务本身也会在代理失败后直连重试（`direct_fallback`）。

成功后检查：

```text
app/t4/files/m3u/live_merged.m3u          # 聚合结果
app/t4/files/json/live_merged_meta.json   # 每个源的条数、分组统计、失败原因
```

`live_merged_meta.json` 主要字段：

| 字段 | 说明 |
| --- | --- |
| `generated_at` / `updated_at` | 本次生成时间（`YYYY-MM-DD HH:MM:SS`） |
| `raw_count` | 各源解析出的原始条目总数 |
| `deduped_count` | 跨源去重后的条目数 |
| `final_count` | 最终写入 m3u 的条目数 |
| `removed_count` | 一共少了多少条（`raw_count - final_count`） |
| `dropped_by_dedupe` / `dropped_by_check` | 去重剔除数 / 测活剔除数 |
| `groups` | 每个分组的条目数 |
| `sources` | 每个源的条数与失败原因 |
| `logo_cache` / `epg_cache` | 台标、EPG 缓存统计 |
| `outputs` | 本次写出/依赖的产物路径（相对 `t4/files/`），含 `epg_url` |
| `errors` | 失败源汇总 |

默认**不会**覆盖仓库里已跟踪的 `t4/files/txt/mytv.txt`，避免每次跑任务都把生成物带进 git 变更。

### 3. 让播放端用上

先在后台「参数配置」改两项：

```text
vod_zb_use  = file
vod_zb_file = m3u/live_merged.m3u
```

`vod_zb_file` 是相对 `t4/files/` 的路径，生成配置时会拼成
`http://<你的地址>/files/m3u/live_merged.m3u`。

然后到 TVBox 的「配置地址」填：

```text
http://<服务器局域网IP>:5707/config/0?sub=<订阅码>   # 0 = T4，最常用
http://<服务器局域网IP>:5707/config/1?sub=<订阅码>   # 1 = T3
```

说明：

- `5707` 是 `app/configs/.env` 里的 `PORT`，不是前端的 `8080`。手机和服务器在同一局域网时，
  IP 填服务器的局域网地址（例如 `192.168.1.110`），不要填 `127.0.0.1`。
- `sub` 是后台「订阅管理」里的订阅码；初始化数据里默认是 `dzyyds`。
  如果库里没有任何订阅记录，可以不带 `?sub=`；有订阅记录但不带 `sub`，`/config/0` 会报「参数【sub】不正确」。
- 如果播放器支持单独填直播源，也可以直接用
  `http://<服务器局域网IP>:5707/files/m3u/live_merged.m3u`。
- 改完 `vod_zb_file` 后，TVBox 要重新拉一次配置（或清缓存/重启），否则它还会用旧的 `lives` 地址。

`/config/0` 返回完整 TVBox 配置 JSON，其中的 `lives` 字段就是上面那个 m3u 地址；
`/files/m3u/live_merged.m3u` 返回聚合后的直播列表本身。

如果你更想沿用旧的 `txt/mytv.txt` 路径，把 `live_sources.json` 里的
`output.mirror_local_txt` 改成 `true`。注意 `mytv.txt` 是仓库里已跟踪的文件，
每次跑任务都会产生 git 变更；同时旧的 `tv_spider` 任务也会写这个文件，二者只能留一个。

### 4. 注册定时任务

方式 A：后台「定时任务」新建一条：

| 字段 | 值 |
| --- | --- |
| 任务 ID | `live_source` |
| 任务名称 | 直播源聚合 |
| 函数名 | `tasks.live_source.main` |
| 参数 | `[]` |
| cron | `0 30 3 * * ?`（每天 03:30） |
| 状态 | 启动 |

方式 B：新库安装时，`app/db/init_data/job.csv` 已经预置了一条 `live_source`
记录（默认**暂停**），到后台把它启动即可。

> `job.csv` 只在**新库初始化**时导入。已有数据库不会自动多出这一条，需要按方式 A 手动新建。
> 建好后可以先点「执行一次」验证，再打开「使用中」；`active=True` 的任务在后端重启时会按 `next_run`
> 续跑，`next_run` 已过期则约 10 秒后补跑一次，之后才按 cron 执行。

> 旧的 `tv_spider` 任务（`tasks.tv_spider.main`，现在改成**每天 03:45 跑一次**）默认**不再写** `txt/mytv.txt`：
> 直播页读的是 `m3u/live_merged.m3u`。它的行为由 `t4/files/json/tv_spider.json` 控制：
> `write_mytv=false`（默认不动 mytv.txt）、`min_lines` 不达标或拉取失败时**保留旧文件**、
> `drop_auth_urls=true` 剔除带 `Authinfo/token` 的线路。真要恢复旧行为，把 `write_mytv` 改回 `true`。

## 四、源清单字段

`live_sources.json` 顶层字段：

| 字段 | 说明 |
| --- | --- |
| `output.m3u` | 聚合 m3u 的输出路径（相对 `t4/files/`） |
| `output.local_txt` | 兼容旧配置的镜像路径；配合 `mirror_local_txt` 使用 |
| `output.meta` | 统计信息输出路径 |
| `output.mirror_local_txt` | 是否额外写 `local_txt` 镜像；默认 `false` |
| `output.min_final_count` | 最终条数低于该值时的处理阈值；默认 100（语义见 `min_final_count_action`） |
| `output.min_final_count_action` | 条数不达标时的动作：`warn`（默认，告警但照写，旧文件留 `.bak`）/ `abort`（抛错不覆盖） |
| `epg` | 写进 `#EXTM3U x-tvg-url="..."` 的 EPG 地址；开启 `epg_cache` 后会改成本地地址 |
| `epg_cache` | XMLTV 本地缓存与 `/epg` 索引配置，见第六节 |
| `logo.backfill_from_sources` | 是否用已带台标的源给缺台标的条目补 logo |
| `logo.cache_local` | 是否把台标下载到 `t4/files/m3u/logo/` 并改写 m3u 里的地址 |
| `logo.url_rewrites` | 下载前的 URL 前缀替换，例如 `live.fanmingming.com` → GitHub raw |
| `request.timeout` / `connect_timeout` | 下载超时（读/连接，秒） |
| `request.retries` | 每个地址的重试次数 |
| `request.github_proxies` | GitHub raw 加速前缀列表，按顺序尝试；留空则直连。兼容旧字段 `github_proxy`（单个前缀） |
| `request.direct_fallback` | 系统代理失败后是否强制直连再试 |
| `check.enabled` | 是否测活；默认开启（深度测活，见下文「测活与死线剔除」） |
| `check.deep` | 是否做深度校验：拉播放列表 + 校验 `#EXTM3U` + 拉首个分片；`false` 则只看状态码 |
| `check.workers` / `check.timeout` / `check.connect_timeout` | 测活并发数、读超时、连接超时（秒） |
| `check.segment_bytes` | 深度校验时拉取首分片的字节数，默认 1（够判断是否可播且几乎不耗流量） |
| `check.keep_untestable` | `rtmp/rtp/udp` 等无法用 HTTP 测活的协议是否保留 |
| `check.keep_suspect` | 首次失败（未达判死阈值）的线路是否仍输出；默认 `true` |
| `check.host_sample` / `check.host_breaker` | 每个 host 先抽几条探测、抽样结果全是「整机不可达」时整批熔断（省时间；404/403 不熔断） |
| `check.probe_per_batch` / `check.batch_lcp_min` | 同一张票（host+mac+token 公共前缀）的线路合并成批次后抽几条探测 |
| `check.renew_by_redirect` | 是否尝试用 302 拿新 `Authinfo` 续期；默认 `false` |
| `health.*` | 台账与判死参数：`file`/`dead_report`/`dead_after_hard`/`dead_after_soft`/`cooldown_hours`/`history_days` |
| `dedupe.max_per_name` | 每个频道最多保留几个地址；默认 3（给播放端留换线备线） |
| `dedupe.dedupe_url` | 是否按 URL 再去重一次 |
| `group_order` | 输出时的分组顺序；未列出的分组排在最后 |
| `group_map` | 分组重命名，例如把 Tvlist 的 `WZYTV` 映射成 `央视` |

`epg_cache` 子字段：

| 字段 | 说明 |
| --- | --- |
| `enabled` | 是否启用本地 EPG 缓存 |
| `url` / `fallback_urls` | XMLTV 主地址与回退地址，默认 fanmingming 的 `e.xml` |
| `timeout` | 下载 XML 的超时；`e.xml` 有 8MB 左右，建议不低于 30 秒 |
| `max_age_hours` | 缓存有效期；有效期内直接复用，不再下载 |
| `keep_days` | 只保留「昨天起、未来 N 天」的节目，避免索引无限增大 |
| `trim_to_channels` | 只保留当前直播列表里能匹配到的频道；匹配不到时回退保留全部 |
| `xml_file` | 裁剪后的 XMLTV 路径，默认 `txt/e.xml` |
| `index_file` | `/epg` 使用的索引路径，默认 `json/epg_index.json` |
| `write_xml` | 是否额外写一份裁剪后的 XMLTV |
| `upstream_api` | 本地索引未命中时 302 回退的上游地址，默认仍是 `epg.mxdyeah.top` |

`logo` 子字段：

| 字段 | 说明 |
| --- | --- |
| `cache_local` | 是否启用台标本地缓存 |
| `dir` / `public_base_url` | 缓存目录（相对 `t4/files/`）和对外地址前缀；留空时用 `{{host}}` 在请求时渲染 |
| `timeout` / `workers` | 单张台标超时与并发数 |
| `max_bytes` | 单张台标大小上限，超过则放弃 |
| `cache_existing` | 已下载过的文件是否直接复用 |
| `rewrite_m3u` | 是否把 m3u 里的 `tvg-logo` 改成本地地址 |
| `url_rewrites` | 下载前的 URL 替换规则，按顺序匹配前缀 |

单个源字段：

| 字段 | 说明 |
| --- | --- |
| `name` | 源名称，日志/统计里用 |
| `url` | 源地址（m3u / m3u8 / txt 均可） |
| `fallback_urls` | 备用地址列表，主地址失败后依次尝试 |
| `enabled` | 是否启用 |
| `priority` | 优先级，数字越小越优先；去重时保留优先级高的 |
| `format` | `auto` / `m3u` / `txt`，默认自动识别 |
| `default_group` | 源里没有分组信息时使用的分组 |
| `timeout` | 单源超时覆盖 |
| `note` | 备注，仅给人看 |

## 五、常用操作

### 只保留 fanmingming，不要其他源

把 `tvlist-*`、`iptv-org-*` 的 `enabled` 改成 `false`，或直接删掉对应条目。

### 增加 Tvlist 的其他文件

从仓库 `m3u/` 目录挑文件，按下面格式加一条：

```json
{
  "name": "tvlist-hkmo",
  "url": "https://raw.githubusercontent.com/imDazui/Tvlist-awesome-m3u-m3u8/master/m3u/台湾香港澳门202506.m3u",
  "enabled": true,
  "priority": 30
}
```

仓库根分支是 `master`。文件名含中文/空格时，建议先做 URL 编码，或者直接在浏览器复制 raw 地址。

### 增加 iptv-org 的国家/地区

iptv-org 的播放列表有两种形态：

| 形态 | 示例 | 特点 |
| --- | --- | --- |
| 按国家（推荐） | `https://iptv-org.github.io/iptv/countries/cn.m3u` | 已过滤、带 `tvg-logo` 和英文分组，体积小 |
| 原始 streams | `https://raw.githubusercontent.com/iptv-org/iptv/master/streams/cn.m3u` | 条数更多，但**不带台标** |
| 全球主列表 | `https://iptv-org.github.io/iptv/index.m3u` | 2000+ 频道，带台标，但体积很大 |

新增一个国家/地区，只需要加一条：

```json
{
  "name": "iptv-org-jp",
  "url": "https://iptv-org.github.io/iptv/countries/jp.m3u",
  "fallback_urls": [
    "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/jp.m3u"
  ],
  "enabled": true,
  "priority": 34,
  "timeout": 30,
  "note": "iptv-org 日本区播放列表"
}
```

国家代码列表见仓库的 `PLAYLISTS.md`，也可以浏览 `https://iptv-org.github.io/iptv/` 下的
`countries/`、`categories/`、`languages/` 目录。

注意：

- `iptv-org.github.io` 在国内部分网络下可能需要 10～20 秒，所以 iptv-org 源默认把
  `timeout` 设成 30；如果经常超时，可以用 `fallback_urls` 回退到 raw（但会失去台标）。
- iptv-org 的频道名以英文为主，`tvg-id` 形如 `CCTV1.cn@SD`。聚合时会去掉 `.cn@SD`
  后缀再和 fanmingming 的 `CCTV1` 对齐，所以 **CCTV 等 tvg-id 能对上的频道会被去重**，
  并从 fanmingming 补上台标；但省级卫视因为「湖南卫视 / Hunan TV」这种中英文命名差异，
  可能会同时保留中英文两条，介意的话可以停用对应的 iptv-org 国家源。
- iptv-org 的分组是英文（`News`、`Sports`、`Movies`…），`live_sources.json` 里的
  `group_map` 已经把常见分组映射成中文；遇到新分组时在 `group_map` 里补一条即可。

### 启用 IPv6 / 广播

把 `fanmingming-ipv6` 或 `fanmingming-radio` 的 `enabled` 改成 `true`。
IPv6 源只有在播放端网络支持 IPv6 时才有意义。

### 打开测活

```json
{
  "check": {
    "enabled": true,
    "deep": true,
    "timeout": 8,
    "workers": 16,
    "keep_untestable": true
  }
}
```

> 测活会逐条发 HTTP 请求。390 条线路 + 深度校验 + 16 并发约 3 分钟，可以接受；
> 5000 条的大合集请配合 `host_breaker` 和 `dedupe.max_per_name=1`，或只给个别源打开。

### 测活与死线剔除（live_health）

老的测活只看 `status_code < 400`，这有两个问题：状态码 200 但内容是错误页的线路会漏过；
失败一次就永久剔除，网络抖一下就误杀。现在改成「三级校验 + 台账 + 软删除」。

**三级校验**（`check.deep=true`）

1. 拉播放列表，要求 HTTP 200；
2. body 里必须出现 `#EXTM3U` / `#EXTINF`（挡掉「200 的错误页」）；
3. 拉第一个分片（默认只取 1 字节）确认 200 且非空；是 master playlist 的话会先下钻一层。

**失败定性**

| kind | 含义 | 判死阈值 |
| --- | --- | --- |
| `ok` | 三级全过 | - |
| `auth_expired` | 票过期：带票失败，无票请求正常（主机还活着） | 1 次 |
| `source_gone` | 源下线：带票/乱票/无票结果一样 | `dead_after_hard`（默认 2 次） |
| `unreachable` | 超时 / 502 / SSL 等网络类失败 | `dead_after_soft`（默认 3 次） |
| `segment_failed` / `http_error` | 分片拉不到 / 其他 4xx | `dead_after_hard` |
| `untestable` | rtmp/udp 等，按 `keep_untestable` 处理 | - |

网络类阈值放宽到 3 次，就是为了避免「家里 Wi-Fi 抖一下，一晚上剔掉半个台」这种事故。

**状态机（软删除）**

```
ok --(失败 1 次)--> suspect（仍输出，播放端无感）
   --(再失败)--> dead（不输出，进入 cooldown_hours 冷却）
   --(冷却 24h 到)--> suspect（自动复测，好了就回 ok）
```

也就是「第一次失败不删、只记一笔」，连续失败才真删；删掉的还会自动复测。

> 复测发生在**每天的 `live_source` 重建**里：它每次都重新拉开上游的全部线路，冷却到期的会被重新测一遍，
> 好了就自动回到 `ok`。`live_check` 只复查 m3u 里现存的线路，所以别把它当成「把死台找回来」的任务。

**台账**

- 文件：`t4/files/json/live_health.json`（默认，已 `.gitignore`），按**归一化 URL**（剔除 auth 参数）记录
  `first_seen` / `last_ok` / `fail_count` / `consec_fail` / `state` / `cooldown_until` / `last_kind`；
- 死链清单：`t4/files/json/live_dead_report.json`，方便直接看「哪些台、为什么没了」；
- **保命规则**：台账读坏或缺失 → 整体降级为「全放行」，绝不会因为台账丢了把直播搞挂。

**同票折叠与 host 熔断**

- 像 `58.248.112.205` 那种「同一张会话票 + 每频道不同后缀」的源，按 host+mac+token 公共前缀折叠成一个批次，
  只抽 `probe_per_batch` 条探测；批次代表全灭时整批沿用结论（票过期/主机下线本来就是整批一起死）；
- host 熔断：某 host 抽样 `host_sample` 条**全是「整机不可达」**（超时 / 连接失败 / 5xx / SSL）就直接熔断，不再逐条等超时；
  `404`/`403`/`401` **不参与熔断**——那代表服务器还活着、只是这条路径没了，别的路径可能还能播，必须逐条判。
  > 实测 390 条里有 181 条集中在 3 个死 host 上，熔断后测活时间从几分钟降到几十秒；
  > 但一开始把 404 也算进熔断，误杀了 2 条能播的线路，改成只认「整机不可达」后恢复。
- 分片校验先用 `Range: bytes=0-N` 取 1 字节；个别 CDN（Akamai 系）对 `bytes=0-0` 会回 `206` + **空体**或 `416`，
  这时会自动去掉 `Range` 再取一次，避免把能播的线路判成分片失败。

**可选的 token 续期**（默认关）

把 `check.renew_by_redirect` 设为 `true` 后，失败的带票线路会去掉 `Authinfo` 重放一次，
如果服务端 302 且 `Location` 里带新票，就自动替换成新 URL 继续用。
注意：实测 `58.248.112.205:8006` 那批票是「源整台下线」而非过期，重放也拿不到新票，所以默认关闭。

**手动验证 / 单跑**

```bash
cd app
python -m tasks.live_health --stats                    # 看台账统计（存活/疑似/已死/host 分布）
python -m tasks.live_health --dry-run --limit 60        # 预演：1 次失败就算「会被剔除」，不写台账
python -m tasks.live_health --dry-run                  # 全量预演
python -m tasks.live_health --recheck --dry-run        # 预演：复查现有 m3u 会删掉哪些
python -m tasks.live_health --recheck                  # 真删：剔死链 + 回写 meta + 留 .bak
```

> 一定要在**部署机（手机）自己的网络**里验证。用电脑/境外网络跑，`502`、`超时` 都可能是代理造成的，
> 只有 `404` 可信。

**两个任务怎么分工**

| 任务 | 函数 | 建议 cron | 干什么 |
| --- | --- | --- | --- |
| `live_source` | `tasks.live_source.main` | `0 30 3 * * ?` | 重新拉上游 → 测活 → 去重 → 重建 m3u |
| `live_check` | `tasks.live_health.main` | `0 0 0/6 * * ?` | 不拉上游，只复查现有 m3u，按台账剔掉新死的线路 |

`live_check` 用迁移脚本注册（幂等，可重复跑）：

```bash
cd app
python db/migrate_live_health.py                 # 注册/更新，默认每 6 小时
python db/migrate_live_health.py --cron "0 0 0/3 * * ?"   # 例：每 3 小时复查一次
python db/migrate_live_health.py --disable       # 只暂停，不删除
```

> 为什么要拆开：重建要拉上游（慢、依赖源站），复查只需要测现有线路（快）。
> 上游挂了或者暂时不想重建时，可以单独把 `live_source` 停掉，`live_check` 继续守着现有 m3u。

### 台标怎么来的

- fanmingming 的 m3u 本身就带 `tvg-logo="https://live.fanmingming.com/tv/CCTV1.png"`；
- Tvlist 的 m3u 大多没有台标。聚合时 `logo.backfill_from_sources=true` 会用
  fanmingming 已解析出的「频道名/ tvg-id → logo」索引给同名频道补上；
- 补不到的同名频道不会强行拼 URL，避免出现大量 404 台标。

## 六、台标与 EPG 本地缓存

这一节解决两个国内网络下最常见的问题：台标打不开、EPG 接口太慢。

### 台标：下载到本地，失败保留原 URL

开启 `logo.cache_local` 后，聚合任务会：

1. 先按 `logo.url_rewrites` 改写地址。默认把 `live.fanmingming.com/tv/xxx.png`
   改成 `raw.githubusercontent.com/fanmingming/live/main/tv/xxx.png`，再走 `github_proxies`；
2. 用 `tvg-id`/URL 哈希生成文件名，下载到 `t4/files/m3u/logo/`；
3. 把 m3u 里的 `tvg-logo` 改写成 `{{host}}/files/m3u/logo/xxx.png`；
4. 下载失败的条目**保留原始 URL**，不会因为台标失败影响直播源本身。

实测（2026-10，国内直连）：

| 台标来源 | 结果 |
| --- | --- |
| `raw.githubusercontent.com/fanmingming/live/main/tv/*.png` | ✅ 200，约 0.5～2 秒 |
| `gh-proxy.com` + raw | ✅ 200，约 0.5 秒 |
| `www.tvchinese.net/uploads/tv/*.jpg` | ✅ 200（注意真实路径是 `/uploads/tv/`） |
| `i.imgur.com/*.png` | ❌ 连接超时；wsrv/weserv/gh-proxy 镜像均 404，无法救 |
| `upload.wikimedia.org/*.svg` | ❌ SSL/连接超时 |

因此一次完整聚合里通常只有一部分台标能本地化。`live_merged_meta.json` 的
`logo_cache` 会给出 `total / downloaded / reused / failed / rewritten`；失败的条目仍保留原 URL。

### EPG：缓存 XML + 按频道查询

TVBoxOS 把 `lives.epg` 当成**按频道查询的 JSON 接口**，会拿每个频道名去请求一次。
如果直接把 8MB 的 `e.xml` 填进去，播放端会为每个频道重复下载整份 XML，流量和等待都会爆炸。
所以本项目采用「本地索引 + `/epg` 接口」：

```text
fanmingming e.xml
      │ 每天下载一次（max_age_hours 内复用）
      ▼
t4/files/json/epg_index.json     # 频道 id → 节目列表，按频道名归一化建 keys
      │
      ▼
GET /epg?ch=CCTV1&date=2026-10-22
      │ 只返回该频道当天的节目
      ▼
TVBox LivePlayActivity 解析 epg_data
```

生成配置里的 `lives.epg` 已经改成：

```json
"epg": "{{host}}/epg?ch={name}&date={date}"
```

相关行为：

- 频道名会做归一化再查索引，`CCTV1`、`CCTV-1 综合`、`CCTV1.cn@SD` 都能命中同一个频道；
- 索引未命中（例如 iptv-org 独有的英文频道）时，`/epg` 会 302 到
  `epg_cache.upstream_api`，默认还是原来的 `https://epg.mxdyeah.top/api/diyp/?ch=...`，
  不会比改之前更差；
- `trim_to_channels=true` 时只保留当前直播列表能匹配到的频道；
- 响应带 `Cache-Control: public, max-age=600`，单次只有几 KB。

> 注意：`{{host}}` 不是聚合任务能知道的部署域名，而是在
> `/files/{group}/xxx.m3u` 和 `/config/{mode}` 请求时按当前 Host 替换。
> 所以局域网、公网、端口变化都不需要重新跑聚合任务。

### 手动验证

```shell
# 台标
curl -I http://127.0.0.1:5707/files/m3u/logo/CCTV1-xxxxxxxxxx.png

# 直播源（确认 tvg-logo / x-tvg-url 里的 {{host}} 已替换成实际地址）
curl http://127.0.0.1:5707/files/m3u/live_merged.m3u | head -3

# EPG（CCTV1 和 CCTV-1 综合 应该返回同一套节目）
curl 'http://127.0.0.1:5707/epg?ch=CCTV1&date=2026-10-22'
curl 'http://127.0.0.1:5707/epg?ch=CCTV-1%20%E7%BB%BC%E5%90%88&date=2026-10-22'
```

## 七、故障排查

| 现象 | 原因 / 处理 |
| --- | --- |
| 日志里 `live.fanmingming.com` 连接超时 | 该域名在部分网络不可达。任务会自动回退 `raw.githubusercontent.com`；若 GitHub 也不通，检查 `request.github_proxies`，例如加上 `https://ghproxy.net/`。 |
| 所有源都失败 | 先看 `live_merged_meta.json` 的 `errors`；再确认服务器能否访问 `raw.githubusercontent.com`，以及 `HTTP_PROXY/HTTPS_PROXY` 是不是指向了一个坏代理（本项目任务会在失败后强制直连重试）。 |
| 配置里直播是空的 | 确认 `vod_zb_use=file` 且 `vod_zb_file` 指向的文件真实存在（推荐 `m3u/live_merged.m3u`）；看 `/files/m3u/live_merged.m3u` 能否直接打开。 |
| 播放端频道重复 | 调大 `dedupe.max_per_name` 之前先确认不是多个源同名；默认 1 已经会按频道名去重。 |
| Tvlist 频道没有台标 | 正常。Tvlist 本身不带台标，只有能在 fanmingming 里找到同名/同 tvg-id 的频道才会补上。 |
| iptv-org 频道没有台标 | 如果走的是 `streams/*.m3u` 回退（`live_merged_meta.json` 里能看到实际使用的源），原始文件本来就没有台标；优先用 `countries/*.m3u`。 |
| iptv-org 拉取很慢 | `iptv-org.github.io` 在国内可能 10～20 秒才响应，源里已把 `timeout` 设为 30。仍超时就加大 `timeout`，或改用 raw + `github_proxies`（会失去台标）。 |
| 加速站也失效 | `github_proxies` 里的第三方站可能临时不可用。换成你自己的 GitHub 反代，或把 `iptv-org` 的 `enabled` 暂时关掉；任务会保留上一份可用的 m3u。 |
| iptv-org 分组还是英文 | 在 `group_map` 里补映射，例如 `"Kids": "少儿"`；多值分组如 `Animation;Kids` 会取第一个能映射的值。 |
| iptv-org 频道没有 EPG | 本地索引来自 fanmingming 的 `e.xml`，iptv-org 自己有一套 EPG（`iptv-org/epg`），默认没合并；未命中的频道会 302 到 `epg_cache.upstream_api`，可能仍为空。 |
| 台标显示不出来 | 先看 `live_merged_meta.json` 的 `logo_cache.failed`。`i.imgur.com`、`upload.wikimedia.org` 在国内基本不可达，任务会保留原 URL；能本地化的只有 fanmingming raw、tvchinese 等可用域名。 |
| `/epg` 返回 302 | 说明该频道不在 `epg_index.json` 里，正在回退上游。确认 `epg_cache.enabled=true` 且最近跑过聚合任务；再看索引的 `channel_count`。 |
| m3u 里还是 `{{host}}` | 说明是直接读文件，不是通过 `/files/m3u/xxx.m3u` 访问。用 HTTP 地址访问，或让播放端走 `/config` 生成的 `lives.url`。 |
| 任务跑完但没变化 | 检查定时的 `func_name` 是否为 `tasks.live_source.main`，以及任务是否处于「启动」状态；看后台任务日志的返回值。 |
| 页面能打开、但登录/所有接口一直转圈 | 后端「假死」：主进程已退出，但 APScheduler 进程池 fork 出的子进程还攥着监听 socket，端口继续 LISTEN 却没人 accept。`curl -m 5 -o /dev/null -w '%{http_code}\n' http://127.0.0.1:5707/docs` 不是 200 就是它。直接 `bash start_all.sh`（或 `_restart.sh`）重启；`pkill -f "python main.py"` 会把孤儿一起带走。 |
| 一轮复查/聚合把线路砍掉一大半 | 多半是本机网络被打满（并发探测）或两轮测活同时跑，把失败次数重复累加。已内置守卫：`json/.live_check.lock` 文件锁保证同时只有一轮在跑；`health.max_drop_ratio`（默认 0.5）超过就判定本机网络异常，`live_check` 回滚台账、`live_source` 抽样慢速复核后中止，都不覆盖已有 m3u。 |

### 7.1 后端「假死」是怎么来的（手机部署必读）

`app/common/sys_schedule.py` 默认用 `ProcessPoolExecutor` 跑定时任务。每次任务都会 `fork` 一个
整份应用的子进程（手机上约 100MB），而 **fork 会把 uvicorn 的监听 socket 一起继承过去**。一旦
主进程被系统回收，这些僵尸子进程还攥着 5707：端口继续 LISTEN、连接全堆在 backlog，但再也没有
人 accept —— 表现就是「静态页秒开、所有 API 超时、日志一行不写」。

两个缓解措施（都已在手机 `.env` 里生效）：

```ini
# 定时任务改用线程池：不 fork、不继承端口、不多占内存
SCHEDULER_EXECUTOR=thread
SCHEDULER_POOL_SIZE=4
```

- 想恢复旧的进程池行为，把 `SCHEDULER_EXECUTOR` 删掉或设为 `process` 即可（PC 端默认仍是进程池）；
- 另配了看门狗 `_watchdog.sh`：每分钟探一次 `/docs`，连续 3 次不通就重启后端；另外所有任务的下次执行时间都过期 15 分钟以上（调度器罢工）时也会重启。`start_all.sh` 会自动拉起它。

> 同类的另一个坑（会让人误以为「定时任务全坏了」）：在 APScheduler 的事件回调里直接 `remove_job`，本轮末尾它还要 `update_job` 那个已删的任务，抛 `JobLookupError` 会把整个调度循环打断 —— 之后网页和接口都正常，但所有定时任务永远不再执行、`next_run` 冻结在中断时刻。已改为延迟删除 + 事件回调兜异常。

### 7.2 测活的并发与守卫

| 参数 | 作用 |
| --- | --- |
| `check.workers` | 测活并发。手机上默认降到 8（原 16），避免把家用宽带上行打满造成大面积误判。 |
| `check.timeout` | 单条超时，手机上放宽到 10s。 |
| `health.max_drop_ratio` | 单轮剔除比例上限（默认 0.5）。超过就认为「本机网络异常」而不是「线路全死」。 |
| `json/.live_check.lock` | 文件锁，`live_source` 和 `live_check` 共用，保证同一时刻只有一轮测活。 |

## 八、为什么不把 Tvlist / iptv-org 全量导入

- `5000个直播源全部有效.m3u` 单文件就 1MB+，`iptv-org` 的 `index.m3u` 有 2000+ 频道，播放端解析和切换都会变慢；
- 这类汇总源里大量地址是临时 IP/端口，失效速度快，全量导入只会放大无效频道；
- 聚合任务的设计是「少量稳定主源 + 按需补充」，而不是做第二个 Tvlist / iptv-org 镜像。

如果你确实需要全量，建议：

1. 单独启用该源，并把 `priority` 设为很大（例如 100）；
2. 打开 `check.enabled` 先测活；
3. 把 `dedupe.max_per_name` 设为 1，避免同一个频道出现几十个地址；
4. 用 `group_map` 把杂乱分组收敛。

## 九、代码位置

| 文件 | 作用 |
| --- | --- |
| `app/t4/files/json/live_sources.json` | 直播源清单与聚合参数 |
| `app/tasks/live_source.py` | 下载、解析、去重、补台标、缓存台标/EPG、测活、输出 |
| `app/tasks/live_health.py` | 三级测活 + 台账 + 软删状态机 + 同票折叠 + host 熔断；`live_check` 任务本体 |
| `app/common/sys_schedule.py` | 定时任务调度器；`SCHEDULER_EXECUTOR=process/thread` 决定用进程池还是线程池 |
| `_watchdog.sh`（`~/hipy/`） | 后端探活看门狗：/docs 连续 3 次不通就重启后端，`start_all.sh` 自动拉起 |
| `app/tasks/tv_spider.py` | 旧 TV 源抓取；行为由 `t4/files/json/tv_spider.json` 控制（默认不写 mytv.txt） |
| `app/db/migrate_live_source.py` | 注册 `live_source` 定时任务（幂等） |
| `app/db/migrate_live_health.py` | 注册 `live_check` 定时任务（幂等） |
| `app/utils/live_epg.py` | 频道名归一化；任务建索引和 `/epg` 查索引共用同一套规则 |
| `app/t4/files/m3u/live_merged.m3u` | 聚合产物（运行时生成，已加入 `.gitignore`） |
| `app/t4/files/m3u/logo/` | 台标缓存（运行时生成，已加入 `.gitignore`） |
| `app/t4/files/json/live_health.json` | 线路健康台账（运行时生成，已加入 `.gitignore`） |
| `app/t4/files/json/live_dead_report.json` | 死链清单，含 kind/原因/失败次数（运行时生成） |
| `app/t4/files/json/tv_spider.json` | `tv_spider` 任务开关（可选，缺省用内置默认值） |
| `app/t4/files/json/epg_index.json` | `/epg` 使用的频道/节目索引（运行时生成，已加入 `.gitignore`） |
| `app/t4/files/txt/e.xml` | 裁剪后的 XMLTV（运行时生成，已加入 `.gitignore`） |
| `app/t4/files/txt/mytv.txt` | 兼容旧配置的镜像产物（仓库已跟踪，但默认不再写入） |
| `app/t4/files/txt/config.txt` | 生成配置里的 `lives` 字段模板 |
| `app/apps/web/views.py` | `/config/{mode}` 生成配置；`/files/{group}/{filename}` 提供静态文件并渲染 `{{host}}`；`/epg` 本地 EPG 接口 |

## 十、免责声明

直播源来自第三方公开仓库，本项目只做格式聚合与本地缓存，不存储、不转码、不保证任何频道的可用性与合法性。
请遵守当地法律法规，仅将相关内容用于学习研究。
