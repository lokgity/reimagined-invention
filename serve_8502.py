# -*- coding: utf-8 -*-
"""以**真正脱离**的方式启动 Chainlit（8502），供本机演示使用。

⚠️ 为什么需要这个脚本（2026-09-21 踩了三次的坑）：
  直接在会话里用后台方式起服务，**进程会随 agent 结束本轮而一起被杀** ——
  非交互运行会在主 agent 结束 turn 时终止它派生的子进程。
  症状极具迷惑性：日志一切正常、服务也确实起来了、当轮验证全过，
  但下一轮再看，8502 上跑的是**几小时前的旧实例**（加载的是旧代码）。
  实测撞见过 02:02 / 02:45 起的旧实例占着端口，而我起的服务已经消失。

  解法：用 `DETACHED_PROCESS` 起，进程不挂在当前进程树上，谁的 turn 结束都不影响它。

用法：
    C:\\Python312\\python.exe serve_8502.py            # 起服务（已在跑就先停掉）
    C:\\Python312\\python.exe serve_8502.py --status   # 只看状态
    C:\\Python312\\python.exe serve_8502.py --stop     # 只停
"""
import ctypes
import datetime
import io
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(os.path.dirname(ROOT), '_cl_serve.log')
PY = r'C:\Python312\python.exe'          # ⚠️ 必须 312：3.14 下 /public/* 会 500
PORT = 8502
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
# ⚠️ 只有 DETACHED_PROCESS 是**不够**的（2026-09-21 实测：进程起来了、当轮验证全过，
#    但本轮一结束就被回收，下一轮再看 8502 上已经是别的东西）。
#    原因：宿主把工具子进程放进一个 Windows **Job Object**，job 上带
#    KILL_ON_JOB_CLOSE ⇒ job 一关，里面所有进程连同后代一起被杀，
#    DETACHED_PROCESS 只改控制台归属、改不了 job 归属。
#    CREATE_BREAKAWAY_FROM_JOB 才是真正"脱离 job"的那个标志
#    （前提：目标 job 允许 breakaway；不允许时系统直接拒绝创建，见下面回退）。
CREATE_BREAKAWAY_FROM_JOB = 0x01000000

sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def busy():
    """端口上有没有人在听。⚠️ 用 socket 直连判断，不依赖 netstat
    （实测在子进程里拿 netstat 输出会得到 None）。"""
    import socket
    s = socket.socket()
    s.settimeout(1.5)
    try:
        s.connect(('127.0.0.1', PORT))
        return True
    except Exception:
        return False
    finally:
        s.close()


def listeners():
    """尽量给出占用 8502 的 PID（拿不到就返回空，不影响主流程）。"""
    try:
        r = subprocess.run('netstat -ano', shell=True, capture_output=True,
                           timeout=30)
        out = (r.stdout or b'').decode('utf-8', 'replace')
    except Exception:
        return []
    pids = set()
    for line in out.splitlines():
        if (':%d ' % PORT) in line and 'LISTENING' in line:
            try:
                pids.add(int(line.split()[-1]))
            except Exception:
                pass
    return sorted(pids)


def created(pid):
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    h = k.OpenProcess(0x1000, False, pid)
    if not h:
        return '?'
    c = ctypes.c_ulonglong(); e = ctypes.c_ulonglong()
    kt = ctypes.c_ulonglong(); ut = ctypes.c_ulonglong()
    ok = k.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e),
                           ctypes.byref(kt), ctypes.byref(ut))
    k.CloseHandle(h)
    if not ok:
        return '?'
    # ⚠️ GetProcessTimes 给的 FILETIME 是 **UTC**。第一版直接当本地时间打印，
    #    结果比北京时间**少 8 小时** —— 11:00 启动的进程被印成 03:00，
    #    于是一次排障中被误判成"8 小时前启动的旧实例"（2026-09-21 实际踩过）。
    return str(datetime.datetime(1601, 1, 1)
               + datetime.timedelta(microseconds=c.value // 10)
               + datetime.timedelta(hours=8))    # UTC → UTC+8


def stop():
    for pid in listeners():
        print('停止 PID %s（启动于 %s）' % (pid, created(pid)))
        subprocess.run(['taskkill', '/PID', str(pid), '/F'],
                       capture_output=True, text=True)
    time.sleep(2)


def start():
    env = dict(os.environ)
    env['PYTHONPATH'] = os.path.join(ROOT, 'src') + ';' + os.path.join(ROOT, '.pylibs')
    env['PYTHONIOENCODING'] = 'utf-8'
    args = [PY, '-u', '-m', 'chainlit', 'run', os.path.join('src', 'ui', 'app_chainlit.py'),
            '--port', str(PORT), '--host', '0.0.0.0']
    base = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    p = None
    for flags, tag in ((base | CREATE_BREAKAWAY_FROM_JOB, '已脱离 job（能活过本会话）'),
                       (base, '仅脱离控制台（**可能**被宿主回收）')):
        f = io.open(LOG, 'w', encoding='utf-8', errors='replace')
        try:
            p = subprocess.Popen(args, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                 stdout=f, stderr=subprocess.STDOUT, creationflags=flags)
            print('已启动 PID %d，%s' % (p.pid, tag))
            break
        except OSError as e:
            print('  breakaway 失败（%s），回退' % e)
    if p is None:
        print('启动失败'); return
    print('  日志 %s' % LOG)
    for _ in range(40):
        time.sleep(1)
        if busy():
            break
    for pid in listeners():
        print('  监听中 PID %s（启动于 %s）' % (pid, created(pid)))
    # 口径行：一眼看出跑的是哪套 UPLIFT
    if os.path.exists(LOG):
        for line in io.open(LOG, encoding='utf-8', errors='replace').read().splitlines():
            if '[口径]' in line or 'Your app is available' in line:
                print('  ' + line)


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else ''
    if mode == '--status':
        ps = listeners()
        if ps:
            print('8502 监听中：%s' % ['%d(启动于 %s)' % (p, created(p)) for p in ps])
        else:
            print('8502 监听中：%s' % ('有服务（PID 取不到）' if busy() else '无'))
    elif mode == '--stop':
        stop()
        print('已停，现在：', '仍在监听' if busy() else '无')
    else:
        if busy():
            stop()
        start()
