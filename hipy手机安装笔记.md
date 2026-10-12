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
  - 启动: redis-server --port 6379 --requirepass 123456 --daemonize yes --dir $HOME --logfile $HOME/redis.log --save ""

五、代码补丁(相对原仓库)
  - 新增 app/utils/safe_eval.py (替代 numpy.safe_eval)
  - apps/monitor/views/views_job.py, common/task_apscheduler.py 改用 safe_eval
  - apps/permission/views.py: pandas 改惰性 import
  - utils/server_info.py: psutil 读取 /proc/stat|/proc/net/dev 被 SELinux 拒绝, 全部 try/except 容错
  - configs/.env: SQLALCHEMY_ENGINE=sqlite, DEFAULT_SNIFFER=hipy-sniffer,
    API_DOMAIN=http://192.168.1.113:5707, WEB_DOMAIN=http://192.168.1.113:8080,
    SERVER_PROXY=, REDIS_PASSWORD=123456

六、前端
  - PC 用 nvm node16 构建: npm run build:prod  => dashboard/dist (7.5MB)
  - .env.production.local 内嵌:
      VUE_APP_BASE_API='http://192.168.1.113:5707/api/v1/'
  - 手机端用 `python -m http.server 8080 --directory $HOME/hipy/dist --bind 0.0.0.0` 提供

七、目录/脚本(手机 $HOME/hipy)
  app/            后端代码
  dist/           前端静态文件
  start_backend.sh   启动后端(:5707)
  start_frontend.sh  启动前端(:8080)
  start_all.sh       一键启动 redis+后端+前端
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
