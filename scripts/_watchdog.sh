#!/data/data/com.termux/files/usr/bin/bash
# 后端探活看门狗：/docs 连续 3 次不通 → 自动重启后端
#              调度器罢工（所有任务的下次执行时间都过期 15 分钟以上）→ 也重启
#              内存/线程超限（默认 RSS 1200MB 或 600 线程，连续 3 次）→ 也重启
# 用法: bash _watchdog.sh   (start_all.sh 会自动拉起)
export HOME=/data/data/com.termux/files/home
export PREFIX=/data/data/com.termux/files/usr
PY=$HOME/.pyenv/versions/3.12.8
export PATH=$PY/bin:$PREFIX/bin:$PREFIX/bin/applets:$PATH
export LD_LIBRARY_PATH=$PY/lib:$PREFIX/lib
export TMPDIR=$PREFIX/tmp
cd $HOME/hipy || exit 9

LOG=$HOME/hipy/watchdog.log
INTERVAL=${WATCHDOG_INTERVAL:-60}
URL=http://127.0.0.1:5707/docs
JOBS_URL=http://127.0.0.1:5707/api/v1/monitor/job/now
STALE_SEC=${WATCHDOG_STALE_SEC:-900}
RSS_LIMIT_MB=${WATCHDOG_RSS_MB:-1200}
THREAD_LIMIT=${WATCHDOG_THREADS:-600}
FAILS=0
HITS=0
log() { echo "[$(date '+%F %T')] $*" >>"$LOG"; }

# 资源守卫：后端 RSS 或线程数超限（连续 3 次采样）→ 返回 0。
# 目的是兜住代码里还没挖干净的泄漏（例如 drpy 源重复初始化漏线程），
# 宁可重启一次也不要被系统 LMK 整进程杀掉。
mem_guard() {
  pid=$(pgrep -f "python main.py" 2>/dev/null | head -1)
  [ -z "$pid" ] && return 1
  rss=$(awk '/^VmRSS/{print int($2/1024)}' /proc/$pid/status 2>/dev/null)
  thr=$(awk '/^Threads/{print $2}' /proc/$pid/status 2>/dev/null)
  [ -z "$rss" ] && return 1
  if [ "$rss" -gt "$RSS_LIMIT_MB" ] || { [ -n "$thr" ] && [ "$thr" -gt "$THREAD_LIMIT" ]; }; then
    HITS=$((HITS + 1))
    log "资源超限 pid=$pid rss=${rss}MB threads=${thr:-?} (连续 $HITS 次, 阈值 ${RSS_LIMIT_MB}MB / ${THREAD_LIMIT} 线程)"
    [ "$HITS" -ge 3 ] && return 0
  else
    [ "$HITS" -gt 0 ] && log "资源回落至正常 rss=${rss}MB threads=${thr:-?}"
    HITS=0
  fi
  return 1
}

# 调度器是否罢工：所有任务都有 next_run 且全部早于现在 STALE_SEC 秒
scheduler_stale() {
  body=$(curl -s -m 8 "$JOBS_URL" 2>/dev/null) || return 1
  total=$(printf '%s' "$body" | grep -o '"next_run":' | wc -l | tr -d ' ')
  [ -z "$total" ] && return 1
  [ "$total" -lt 1 ] && return 1
  stale=$(printf '%s' "$body" | grep -o '"next_run":"[^"]*"' | sed 's/.*"next_run":"//;s/"$//' | {
    cnt=0
    while IFS= read -r t; do
      [ -z "$t" ] && continue
      ts=$(date -d "$t" +%s 2>/dev/null) || continue
      now=$(date +%s)
      [ $((now - ts)) -gt "$STALE_SEC" ] && cnt=$((cnt + 1))
    done
    echo "$cnt"
  })
  [ -z "$stale" ] && return 1
  if [ "$stale" -ge "$total" ]; then
    log "调度器疑似罢工：$stale/$total 个任务的下次执行时间已过期 ${STALE_SEC}s 以上"
    return 0
  fi
  return 1
}

restart_backend() {
  log "重启后端 (原因: $1)"
  pkill -f "python main.py" 2>>"$LOG"
  sleep 3
  if pgrep -f "python main.py" >/dev/null; then
    log "普通 kill 无效, 尝试 -9"
    pkill -9 -f "python main.py" 2>>"$LOG"
    sleep 2
  fi
  if pgrep -f "python main.py" >/dev/null; then
    log "!! 杀不掉(跨 SELinux 域), 请在 Termux 里执行: bash $HOME/hipy/_restart.sh"
  else
    nohup bash start_backend.sh >> backend.log 2>&1 </dev/null &
    log "已重新拉起后端, 等待 25s 观察"
    sleep 25
    code=$(curl -s -o /dev/null -w '%{http_code}' -m 10 "$URL" 2>/dev/null)
    log "重启后探活 code=${code:-000}"
  fi
  FAILS=0
  HITS=0
  sleep 60
}

log "看门狗启动 (pid $$, 间隔 ${INTERVAL}s, 目标 $URL, 调度器过期阈值 ${STALE_SEC}s)"
while true; do
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 10 "$URL" 2>/dev/null)
  if [ "$code" = "200" ]; then
    [ "$FAILS" -gt 0 ] && log "后端已恢复 (code=$code)"
    FAILS=0
    if scheduler_stale; then
      restart_backend "调度器罢工"
      continue
    fi
    if mem_guard; then
      restart_backend "内存/线程超限"
      continue
    fi
  else
    FAILS=$((FAILS + 1))
    log "探活失败 code=${code:-000} (连续 $FAILS 次)"
    if [ "$FAILS" -ge 3 ]; then
      restart_backend "连续 3 次探活不通 code=${code:-000}"
    fi
  fi
  sleep "$INTERVAL"
done
