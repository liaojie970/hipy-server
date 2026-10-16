1>安装Python3.8.19依赖
sudo apt update && sudo apt install -y make git curl g++ gcc wget build-essential zlib1g-dev libncurses5-dev libgdbm-dev libnss3-dev libssl-dev libreadline-dev libffi-dev libbz2-dev liblzma-dev sqlite3 libsqlite3-dev tk-dev uuid-dev libgdbm-compat-dev 
libffi-devel

2>下载Python-3.8.19的tar包: wget https://www.python.org/ftp/python/3.8.12/Python-3.8.12.tar.xz

3>解压: tar -xvJf Python-3.8.12.tar.xz

4>切换目录: cd Python-3.8.12

5>生成makefile文件: ./configure

6>编译: make -j6 

7> 强制安装(降级）make install (共存安装:make altinstall）

8>安装完成重启，验证python3 --version

如果编译过程有报错信息:To find the necessary bits, look in setup.py in detect_modules() for the module's name.
安装 Python 3.9 Failed to build these modules: _ctypes 

就重新安装以下依赖

安装libffi-devel

再次make




sudo apt update && sudo apt install -y  build-essential libssl-dev zlib1g-dev libpq-dev libbz2-dev libreadline-dev libsqlite3-dev  llvm libncurses5-dev libncursesw5-dev xz-utils tk-dev libffi-dev liblzma-dev python3-openssl python3-psycopg2 python3-dev default-jdk supervisor fonts-liberation libcurl3-gnutls libcurl3-nss libcurl4 libgbm1 libgtk-3-0 libgtk-4-1 libwayland-client0 libwayland-client0 libxkbcommon0 xdg-utils


设置pip源，可选

清华(近期清华源pip经常出错)
apt install python3-pip -y
python3 -m pip  install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
pip3 config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

阿里(首选阿里或者腾讯)


8> pip config set global.index-url https://mirrors.aliyun.com/pypi/simple && pip install --upgrade pip && pip install --upgrade setuptools
 
 

cat ~/.pip/pip.conf

[global]
index-url = https://mirrors.aliyun.com/pypi/simple/

# 检查pip源

pip3 config list


 pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple && pip install --upgrade pip && pip install --upgrade setuptools 
 

9>  pip install -r requirements.txt && pip install click pydantic virtualenv



10> playwright install chromium

11>apt install tmux






用pip3安装虚拟环境组件virtualenv

pip3 install virtualenv

为 hipy-server 项目单独创建 python3 虚拟环境。

python3 -m venv hipyenv

source /hipyenv/bin/activate && source /hipyenv/bin/activate 


退出环境变量的命令是deactivate



Exception in callback BaseSelectorEventLoop._accept_connection(<function sta... 0x75355c0790>, <socket.socke...1.100', 2699)>, None, <Server socke...00', 2699)>,)>, 100, None)                    handle: <Handle BaseSelectorEventLoop._accept_connection(<function sta... 0x75355c0790>, <socket.socke...1.100', 2699)>, None, <Server socke...00', 2699)>,)>, 100, None)>                         Traceback (most recent call last):                                 File "/usr/local/lib/python3.8/asyncio/events.py", line 81, in _run                                                                 self._context.run(self._callback, *self._args)                 File "/usr/local/lib/python3.8/asyncio/selector_events.py", line 164, in _accept_connection                                         conn, addr = sock.accept()
  File "/usr/local/lib/python3.8/socket.py", line 292, in accept     fd, addr = self._accept()                                    OSError: [Errno 22] Invalid argument



https://spacevision.blog.csdn.net/article/details/86518446?spm=1001.2101.3001.6650.6&utm_medium=distribute.wap_relevant.none-task-blog-2%7Edefault%7ECTRLIST%7ERate-6-86518446-blog-9004653.237%5Ev3%5Ewap_relevant_t0_download&depth_1-utm_source=distribute.wap_relevant.none-task-blog-2%7Edefault%7ECTRLIST%7ERate-6-86518446-blog-9004653.237%5Ev3%5Ewap_relevant_t0_download


https://blog.csdn.net/Jerry00713/article/details/127380845?spm=1001.2101.3001.6650.10&utm_medium=distribute.wap_relevant.none-task-blog-2%7Edefault%7EBlogCommendFromBaidu%7ERate-10-127380845-blog-9004653.237%5Ev3%5Ewap_relevant_t0_download&depth_1-utm_source=distribute.wap_relevant.none-task-blog-2%7Edefault%7EBlogCommendFromBaidu%7ERate-10-127380845-blog-9004653.237%5Ev3%5Ewap_relevant_t0_download









================================================================
【MI 9 SE 裸跑 Termux 部署完成记录】  2026-10-10
================================================================
设备: MI 9 SE (adb 序列号 299b92f) / arm64-v8a / Android 11 / 未 root
WiFi IP: 192.168.1.113   (PC: 192.168.1.110)

访问地址:
  前端  http://192.168.1.113:8080
  后端文档 http://192.168.1.113:5707/docs
  默认账号 admin / 123456    (已重置, 另 hjdhnx/hjdhnx)

一、Python 环境
  - 方案: Termux 裸跑 + pyenv 源码编译 Python 3.12.8 (匹配 PC 技术栈)
  - pyenv 2.8.9  =>  $HOME/.pyenv
  - 版本目录: $HOME/.pyenv/versions/3.12.8  (shared libpython3.12.so)
  - 编译关键点(踩坑记录):
    1) 必须用默认 clang, 不要传 --target=aarch64-linux-android30
       (传了会导致 TLS 段 p_align=4, Android 链接器拒绝执行)
    2) 大量 ac_cv_func_*=no 关闭 bionic 未声明的 API
       (sem_clockwait/getpwent/setpwent/shm_open/shm_unlink/getlogin_r 等)
    3) Makefile 里 LN 改成 `ln -sf` (Android 禁止硬链接)
    4) Makefile 里 BLDSHARED 追加 $(BLDLIBRARY)
       => 让每个扩展模块(.so)显式 NEEDED libpython3.12
       (CPython 3.12 用 Makefile 规则 + BLDSHARED 链接内置扩展, 不链接 libpython,
        导致 dlopen 模块时找不到 PyExc_* 符号)
    5) Modules/_multiprocessing/multiprocessing.c 去掉 `&& !defined(__ANDROID__)`
       => 恢复 sem_unlink, 否则 multiprocessing 无法导入(Pillow 构建需要)
  - 运行环境变量: LD_LIBRARY_PATH=$HOME/.pyenv/versions/3.12.8/lib:$PREFIX/lib

二、已安装 Python 依赖 (pip, 清华镜像 pypi.tuna.tsinghua.edu.cn)
  fastapi 0.86.0 / starlette 0.20.4 / pydantic 1.10.18 / SQLAlchemy 1.4.43
  uvicorn 0.19.0 / redis 4.3.4 (+async-timeout) / python-jose 3.3.0 / passlib 1.7.4
  python-multipart / cachetools 5.3.2 / APScheduler 3.10.4 / httpx 0.28.1
  PyMySQL / openpyxl 3.1.5 / user_agents / cloudscraper / jsonpath / pyquery
  prometheus-client / lxml 6.1.3 / ujson 6.0.0 / quickjs 1.19.4 / pycryptodome 3.19.0
  psutil 7.2.2 / captcha 0.5 / Pillow 12.3.0 / python-dateutil / tzdata
  bcrypt 3.2.0 (C 扩展, 避开 4.x 的 Rust 依赖) + cffi
  * 跳过: numpy / pandas / jpype1 / playwright / selenium / gunicorn / msgpack
  * aioredis 已卸载(与 py3.12 不兼容, 代码走 redis.asyncio 分支)

三、数据库
  - SQLite: $HOME/hipy/app/db/hipy.db (3.8MB, 已含种子数据: 4用户/44菜单/485规则)
  - 无需运行 initial_data.py (它顶层 import numpy/pandas, 且库已有数据)
  - 已重置密码: admin=123456, hjdhnx=hjdhnx

四、Redis
  - Termux 包: redis 8.10.2
  - 启动: redis-server --port 6379 --requirepass 123456 --daemonize yes --dir $HOME --logfile $HOME/redis.log --save "" --appendonly no --ignore-warnings ARM64-COW-BUG
  - 坑(2026-10-16): ARM64 内核 COW 缺陷会让 Redis 在后台保存时主动退出
    (日志 ~/redis.log 出现 "ARM64-COW-BUG" / "Redis will now exit to prevent data corruption")。
    Redis 一挂 => 登录/验证码/字典/系统参数等依赖缓存的接口全部 500(前端表现: 能打开登录页但登录报内部错误),
    后端日志: redis.exceptions.ConnectionError: Error 111 connecting to 127.0.0.1:6379。
    修复: 启动参数加 --ignore-warnings ARM64-COW-BUG (并 --save "" --appendonly no 避免 fork)。
  - 缓存后端抽象(2026-10-16 新增, 可选内存缓存, 不再强依赖 Redis):
    * app/db/cache_base.py   统一接口 BaseCache(签名对齐 redis.asyncio: get/setex/scan/info...)
    * app/db/cache_redis.py  RedisCache(默认)
    * app/db/cache_memory.py MemoryCache(单进程内存: 惰性+后台清理, 超上限按最早过期淘汰)
    * app/db/cache.py        工厂 registerCache(): 按 settings.CACHE_BACKEND 选择后端;
                             CACHE_BACKEND=redis 且连接失败时, 若 CACHE_FALLBACK_TO_MEMORY=true 自动降级为内存
    * configs/.env 新增:
        CACHE_BACKEND=memory            # 手机改为内存缓存, 不再需要 redis
        CACHE_FALLBACK_TO_MEMORY=true
        MEMORY_CACHE_MAX_ENTRIES=10000
        MEMORY_CACHE_SWEEP_INTERVAL=60
    内存缓存注意点:
      - 仅单进程有效(手机为单 worker, 无影响); 重启后端会清空缓存 => 需重新登录
      - 多 worker / 定时任务子进程不共享缓存
      - 后台监控页(/monitor/cache)仍可用, 但 Redis 版本/命令统计为合成值
    start_all.sh 会读取 CACHE_BACKEND: memory 时跳过 redis 启动(保留 Redis 便于随时切回)

五、代码补丁(相对原仓库)
  - 新增 app/utils/safe_eval.py (替代 numpy.safe_eval)
  - apps/monitor/views/views_job.py, common/task_apscheduler.py 改用 safe_eval
  - apps/permission/views.py: pandas 改惰性 import
  - utils/server_info.py: psutil 读取 /proc/stat|/proc/net/dev 被 SELinux 拒绝, 全部 try/except 容错
  - configs/.env: SQLALCHEMY_ENGINE=sqlite, DEFAULT_SNIFFER=hipy-sniffer,
    API_DOMAIN=http://127.0.0.1:5707 (设为本机 => 跟随访问来源, 实现 IP 无关),
    WEB_DOMAIN=http://192.168.1.113:8080 (仅邮件链接用), SERVER_PROXY=, REDIS_PASSWORD=123456
  - common/sys_schedule.py: APScheduler 的 ProcessPoolExecutor(10) -> (3),
    手机端省内存(启动进程数由 10 降到 3)
  - 新增缓存层: app/db/cache_base.py / cache_memory.py / cache_redis.py,
    改造 app/db/cache.py 为工厂(保留 registerRedis 别名);
    common/deps.py 新增 get_cache(get_redis 保留为等价别名), core/server.py 改调用 registerCache

六、前端 (IP 无关化后)
  - PC 用 nvm node16 构建: npm run build:prod  => dashboard/dist (7.5MB)
  - .env.production.local 改为相对路径:
      VUE_APP_BASE_API='/api/v1/'
      VUE_APP_MEDIA_BASE='/media/'
  - 源码里 12 处 `new URL(process.env.VUE_APP_BASE_API).origin` 全部替换为
      window.location.origin  (否则相对路径会让 new URL() 抛 TypeError)
  - 手机端由自写 spa_server.py 提供: 静态文件 + SPA 回退 + 反向代理
      python $HOME/hipy/spa_server.py $HOME/hipy/dist 8080
      代理前缀: /api /media /files /config /parse /ysp /web /docs /redoc
      /openapi.json /version /database_update /rules_refresh /sniffer
      /baidu /hotsugg /get_ip_location /blank /blog /doc -> 127.0.0.1:5707
      保留原始 Host 头, 让后端 request.base_url 反映前端来源地址
      注意: /static/ 后端也挂了, 但必须留给前端本地提供, 不可代理

七、目录/脚本(手机 $HOME/hipy)
  app/            后端代码
  dist/           前端静态文件
  spa_server.py   静态服务器 + 反向代理(SPA 回退)
  start_backend.sh   启动后端(:5707)
  start_frontend.sh  启动前端(:8080)
  start_all.sh       一键启动(按 CACHE_BACKEND 决定是否启动 redis)+后端+前端
  stop_all.sh        一键停止
  backend.log / frontend.log / $HOME/redis.log  日志

八、常用 adb 自动化命令(PC)
  MSYS_NO_PATHCONV=1 adb -s 299b92f shell "run-as com.termux /data/data/com.termux/files/usr/bin/bash -c \"echo <B64> | /data/data/com.termux/files/usr/bin/base64 -d | bash\""
  (包装脚本: /j/tmp/term.sh '命令')
================================================================

----------------------------------------------------------------
【密码约定补充/更正】 2026-10-10
----------------------------------------------------------------
前端 src/store/modules/user.js 登录时发送的是 md5(明文密码):
    password: md5(password)
后端 curd_user.create 存储 hashed_password = bcrypt(收到的password)
=> 数据库中实际存的是  bcrypt( md5(明文) )
所以手动重置密码时必须:
    from passlib.context import CryptContext
    import hashlib
    c = CryptContext(schemes=["bcrypt"])
    h = c.hash(hashlib.md5(b"新密码").hexdigest())
    # 写入 t_users.hashed_password
直接写 bcrypt(明文) 会导致前端登录一直“密码错误”。

可用账号(已重置):
    admin  / 123456
    user   / 123456   (原库即为此)
    hjdhnx / hjdhnx
----------------------------------------------------------------


================================================================
【SSH 远程登录配置记录】  2026-10-10
================================================================
目标: 在 Windows PC 上用 SSH 管理手机 Termux

一、必须先记住的两个坑
  - Termux 的 sshd 端口是 8022, 不是 22
  - 用户名是 Termux 的 uid (命令 whoami 的输出), 本机为 u0_a212,
    不是 root, 也不是 termux
  - Android 不提供可解析的 .local 主机名(mDNS), 实测:
      adb shell getprop net.hostname  -> MI9SE-AdadeMI9SE
      ping MI9SE-AdadeMI9SE.local     -> 解析失败
      adb -s 299b92f mdns services    -> 空
    结论: 只能靠 IP 定位手机

二、实际执行的动作(可复现)
  1) 确认 openssh 已装:
       dpkg -l | grep openssh        -> openssh 10.6p1-1
  2) 启动 sshd (默认监听 8022):
       sshd
  3) PC 生成专用密钥(不动原有 id_rsa):
       ssh-keygen -t ed25519 -f "J:/Develop/Users/LJ/.ssh/id_ed25519_hipy" -N "" -C hipy-phone
  4) 把公钥写入手机(通过 adb):
       adb push id_ed25519_hipy.pub /data/local/tmp/hipy_key.pub
       # 手机内:
       mkdir -p ~/.ssh && chmod 700 ~/.ssh
       cat /data/local/tmp/hipy_key.pub >> ~/.ssh/authorized_keys
       chmod 600 ~/.ssh/authorized_keys
  5) PC 上写别名 %USERPROFILE%\.ssh\config :
       Host hipy
           HostName 192.168.1.113
           Port 8022
           User u0_a212
           IdentityFile J:/Develop/Users/LJ/.ssh/id_ed25519_hipy
           ServerAliveInterval 30
  6) 把 sshd 加入手机 ~/hipy/start_all.sh (重启后随服务一起启动)
  7) 验证:
       ssh hipy  ->  whoami = u0_a212 ; uname -m = aarch64  ✅

三、换 WiFi 后 IP 会变 => "ssh hipy" 会失效
  原因: config 里 HostName 写死了 192.168.1.113。
  解决方案(按推荐排序):
   A. USB 直连(最稳, 与 IP 无关):
        adb forward tcp:8022 tcp:8022
        ssh -p 8022 u0_a212@127.0.0.1
   B. 查新 IP 后改 config:
        手机(Termux): ip -4 addr show wlan0
        PC: 修改 %USERPROFILE%\.ssh\config 里 hipy 的 HostName
   C. 路由器里给手机做 DHCP 保留(绑定固定 IP) —— 只对该网络有效
   D. 自动定位脚本: %USERPROFILE%\.ssh\ssh-hipy.ps1
        逻辑: ① 若 adb 在线 -> 用 adb 取 wlan0 的 IP (USB 路径)
              ② 否则 -> 扫描各活动网段的 8022 端口, 自动找到手机
        用法: .\ssh-hipy.ps1                 # 自动找并登录
              .\ssh-hipy.ps1 -FindOnly       # 只打印手机当前 IP
              .\ssh-hipy.ps1 -Command "whoami"
              .\ssh-hipy.ps1 -UpdateConfig   # 找到后写回 config 别名
        实测: 局域网扫描约 2 秒命中 192.168.1.113
        注意: PowerShell 5.1 读取脚本需 "UTF-8 with BOM",
              否则中文被当 GBK 解析会报语法错(字符串未终止)

四、网页 IP 无关化 (2026-10-12 已实施完成)
  问题: 前端打包时 VUE_APP_BASE_API 固化为 http://192.168.1.113:5707/api/v1/,
        后端 .env 的 API_DOMAIN 也是该 IP => 换网络后网页加载不出数据。
  解决:
    1) 前端改用相对路径 /api/v1/ 与 /media/ (需同步替换 12 处
       new URL(VUE_APP_BASE_API).origin -> window.location.origin)
    2) spa_server.py 增加反向代理: 命中后端路径前缀时转发到 127.0.0.1:5707,
       并保留原始 Host 头
    3) 后端 .env API_DOMAIN 设为 http://127.0.0.1:5707
  关键发现: apps/web/views.py:224 与 apps/vod/views/views_rules.py:97 判断
    内网 IP 的正则带 ^...$ 锚点, 而 request.base_url 形如
    "http://ip:port/" (结尾有斜杠), 永远匹配不上 => 条件恒真 => 一直用
    API_DOMAIN。因此必须把 API_DOMAIN 设成 127.0.0.1 (命中 `'127.0.0.1' not in`
    分支走 else), 才会回退到 request.base_url (即访问来源地址)。
  验证: 经 8080 代理取 /config/0?sub=dzyyds, 生成的源地址为
        http://192.168.1.113:8080 ; 直连 5707 则为 ...:5707 (均跟随来源)。
  4) 邮件链接的 WEB_DOMAIN 也做了同样处理 (utils/web.py 新增 getWebHost):
     若 WEB_DOMAIN 是内网地址/localhost 则改用 request.base_url;
     若是公网域名则沿用配置值。apps/user/views.py 的 submitRegister /
     submitForgetPassword 改用 getWebHost(request) 生成邮件里的注册/找回链接。
  => 至此 IP 无关化覆盖: 网页接口、tvbox 配置、邮件链接。
================================================================

五、内容库「儿童专用配置」复制按钮修复 (2026-10-12)
  现象: http://<手机IP>:8080/curated/media 中「儿童专用配置」弹窗里
        「配置地址」的「复制」按钮点了没反应(剪贴板没写入)。
  原因: src/views/curated/media/index.vue 的 copyKidUrl() 用了
        navigator.clipboard.writeText(); 而该异步剪贴板 API 只在
        「安全上下文」(HTTPS / localhost / 127.0.0.1) 才存在。
        局域网 http://192.168.1.113:8080 属非安全上下文 =>
        navigator.clipboard 为 undefined => 走 else 分支只弹提示、不复制。
        (开发时用 http://localhost:8080 所以是好的, 搬上手机才暴露。)
  说明: 不是本次 IP 无关化改动引入的 —— 旧包(10-10)与新包(10-12)里该函数
        编译结果完全一致, 从页面诞生(提交 5719a8b)起就是这样。
  修复: 改用项目内置的 vue-clipboard2 (main.js 已 Vue.use(VueClipboard)),
        即 this.$copyText(url) —— 内部走 document.execCommand('copy'),
        在 http 下也能复制。与 vod/rules/edit.vue 等页面写法统一。
  重建: node16 构建曾 OOM(Fatal process out of memory: Zone),
        需 NODE_OPTIONS=--max-old-space-size=6144 再 npm run build:prod。
  产物: 新主包 app.da8d47bb.js, curated chunk-6120d593.3da73da8.js;
        全 dist 已无 navigator.clipboard、无绝对 IP。
  部署: 新 dist 覆盖 $HOME/hipy/dist (旧版备份 dist.bak_<ts>), 无需重启 spa_server。
================================================================

六、TVBox 播放 B站(精选库)失败修复 (2026-10-12)
  现象: 用手机配置 http://192.168.1.113:8080/config/0?sub=qinzi01 在 TVBox 里,
        列表/详情能出来, 但点开 B站视频播放不了(无地址/黑屏);
        换成电脑配置 http://192.168.1.110:5707/config/0?sub=qinzi01 就正常。
  排查(不靠猜, 直接对比):
    1) 两份 /config/0?sub=qinzi01 结构完全一致, 只有 host 不同 =>
       排除配置/端口问题。
    2) 直接打源接口对比:
       - ac=list   : PC5707 / 手机8080 / 手机5707 均 200, 21495 字节, 完全一致;
       - ac=detail : 三者均 200, 4842 字节, 完全一致;
       - play=...  : PC5707 => 200, 991 字节(真实 bilivideo.com 地址);
                     手机8080 / 手机5707 => 200, 82 字节(url 为空)。
       => 失败在「手机后端自身」, 8080 反向代理只是如实返回; 与端口/代理无关。
    3) 手机后端日志: `[亲子精选] 解析播放失败: string index out of range`
       —— 正是 bilibili.py 的 _get_mixin_key() 对 <64 字符串索引越界。
    4) 顺着看: _get_mixin_key 入参 = img_key + sub_key(各 32 位),
       来自 api.bilibili.com/x/web-interface/nav 的 wbi_img; 取不到才越界。
  根因: 精选库站点(哔哩哔哩)的 config 里存了 proxy = "127.0.0.1:7897"
        (电脑上的 Clash/V2Ray 本机代理)。
        - 电脑: 127.0.0.1:7897 有 Clash 在听 => B站请求走代理 => 正常;
        - 手机: 127.0.0.1:7897 是手机自己的回环, 无人监听 =>
                连接立即被拒 => nav 拿不到 wbi_img => 索引越界 => 播放地址为空。
        (失败仅 0.09s, 是 loopback 拒绝, 不是超时。)
        网络本身没问题: 手机直连 api.bilibili.com 返回 200 且有 wbi_img。
  修复: apps/curated/providers/base.py 的 setup_session_proxy 增加回退:
        若代理是回环地址(127.0.0.1/localhost/::1)且端口无人监听, 自动改直连,
        避免把 A 机器的代理配置同步到 B 机器后无法播放。
        - 电脑: 7897 在听 => 判定存活 => 仍走代理, 行为不变;
        - 手机: 7897 无人 => 自动直连 => B站解析恢复正常。
        实现: 新增 _is_dead_loopback_proxy(), 用 socket.connect_ex 探测(0.5s)。
  验证: play 请求三者均 200 / 991 字节(真实 bilivideo.com 地址 + Referer)。
  部署: 覆盖 $HOME/hipy/app/apps/curated/providers/base.py 后重启后端
        (pkill -f "python main.py"; setsid bash start_backend.sh)。前端无需改。
  备注: 站点配置里的 proxy 不必手动改; 想显式直连可把 proxy 填 none/direct。

  配套(前端, 2026-10-12): 「站点管理 → 修改站点」的「网络代理」由纯文本框改为开关:
        - 开关关闭(默认) => 保存 proxy='none', 强制直连;
        - 开关开启 => 显示「代理地址」输入框, 必填, 保存该地址。
        打开旧记录时按已有 proxy 自动还原开关状态(none/direct 视为关闭)。
        列表「代理」列显示: 直连 / 具体地址 / 跟随系统(空值)。
        文件: src/views/curated/providers/index.vue
              (isDirectProxy / collectConfig / handleUpdate / 表单 / 列表列)。
        坑(Vue2 响应式): useProxy 是后加到 form.config 上的新属性, Vue2 侦测不到,
              导致开关点击无反应(新增/修改弹窗都中招, 因为两者共用同一个弹窗)。
              修复: 新增 emptyConfig() 预置 {useProxy:false,cookie:'',qn:undefined,
              proxy:''}; 打开记录时先合并成完整对象再赋给 form(而非事后追加属性)。
        新包: app.34bb9bfd.js, chunk-5b586bce.6d02154c.js(含 使用代理/强制直连 文案)。
  部署(前端): 新 dist 覆盖 $HOME/hipy/dist (旧版备份 dist.bak_<ts>), spa_server 无需重启。
  设计说明: 代理是「本机环境相关」设置, 不应随配置跨机同步。开关默认直连 +
        后端回环代理自动回退, 双保险, 避免再次出现「电脑代理带到手机」。
  注: 「新增站点」与「修改站点」是同一个 el-dialog(共享模板), 开关两处均生效。
================================================================
