# -*- coding: utf-8 -*-
"""
access_gate.py —— 公网访问闸门（演示模式开关 / 每 IP 限流 / 全局日预算）
=====================================================================
为什么需要这个模块
------------------
`start_agent.bat` 里 Chainlit 已经是 `--host 0.0.0.0 --port 8502`，也就是**对局域网全开**。
本地跑的时候没人看得见；可一旦做内网穿透或云部署，任何人拿到链接都能触发服务端的
付费调用：LLM（火山方舟豆包）和高德 API。而 key 是明文放在 `.env` 里的，服务本身
**没有登录、没有限流** —— 爬虫顺手一刷，一天配额就没了。

三道闸门（2026-09-22：口令下线，改为"演示模式开关"）
----------------------------------------------------
1. **演示开关** `DEMO_MODE`               —— **默认关**。关闭时公网来源一律拒绝，
                                            只有本机/内网能用；作者在部署平台设
                                            `DEMO_MODE=1` 才对外开放（公网仍走限流+预算）。
2. **限流**   `RATE_PER_MIN` / `RATE_PER_DAY`（按 IP）—— 挡单点狂刷。
3. **预算**   `DAILY_BUDGET`              —— 全局兜底。当天用超后，不再调用任何付费 API。

默认值对**本地开发零影响**：
· `DEMO_MODE` 默认为关 → 公网全拒，但内网豁免不受影响；
· `GATE_SKIP_LOCAL` 默认 1 → 127.0.0.1 / 192.168.* / 10.* 等内网来源全部豁免。

⚠️ 三条如实说明（别把它当防盗门）
--------------------------------
· **X-Forwarded-For 可以伪造**。穿透/反代会在该头里追加真实 IP，但客户端自己也能塞假值，
  所以限流**只防"顺手刷"，防不住刻意伪造 IP 的人**。要真防，得在上游（穿透服务端或
  Nginx）做限流，或者开 Chainlit 自带的 `CHAINLIT_AUTH_SECRET` 登录。
· **计数存在本机 `data/gate_usage.json`，进程重启不清零**（按天滚动），但它是单机的：
  多台机器各算各的。
· **预算封顶是"拒答"，不是"降级"**。超了就是明确告诉用户今天不能再跑，
  不静默给你一份掺沙子的结果（红线 1：宁少不掺沙）。

为什么单独一个文件
------------------
和 `agent/replay.py` 同理：这里跑的是 Python 3.12 + Chainlit，而离线回归在 3.14。
算术埋进 `app_chainlit.py` 就永远测不到。
"""
import os
import json
import time
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATE_FILE = ROOT / 'data' / 'gate_usage.json'


# ---------------------------------------------------------------
# 配置
# ---------------------------------------------------------------
def _env_int(name, default, lo=0, hi=10 ** 9):
    """读整数环境变量；没配/配错 → 用默认值（不静默失败，见 gate_summary 会打印出来）。"""
    raw = os.getenv(name, '')
    try:
        v = int(str(raw).strip())
    except Exception:
        return default
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


def gate_config() -> dict:
    """每次调用都重新读环境变量 —— 测试要 monkeypatch，缓存了就改不动。"""
    return {
        'access_code': (os.getenv('ACCESS_CODE') or '').strip(),
        'per_min': _env_int('RATE_PER_MIN', 12),
        'per_day': _env_int('RATE_PER_DAY', 200),
        'budget': _env_int('DAILY_BUDGET', 400),
        'skip_local': os.getenv('GATE_SKIP_LOCAL', '1').strip().lower()
                      not in ('0', 'false', 'no', 'off'),
        'demo_mode': os.getenv('DEMO_MODE', '0').strip().lower()
                     in ('1', 'true', 'yes', 'on'),
    }


def gate_summary(cfg: dict) -> str:
    """启动日志用的一行话。开了什么、关了什么必须说出来（红线 4：不静默）。"""
    return ('演示模式=%s，口令=%s，每IP %d/分钟·%d/天，全局日预算=%s，内网豁免=%s'
            % ('开' if cfg['demo_mode'] else '关',
               '开' if cfg['access_code'] else '关',
               cfg['per_min'], cfg['per_day'],
               str(cfg['budget']) if cfg['budget'] > 0 else '不限',
               '是' if cfg['skip_local'] else '否'))


# ---------------------------------------------------------------
# 客户端 IP
# ---------------------------------------------------------------
def client_ip(environ: dict, fallback: str = '') -> str:
    """从 WSGI/ASGI environ 里取客户端 IP。

    取值顺序：`X-Forwarded-For` → `X-Real-IP` → `REMOTE_ADDR` → ASGI `client`
    → `fallback` → `unknown`。穿透/BEHIND 反代时只有前两个头才带得进真实 IP。
    """
    env = environ or {}
    for key in ('HTTP_X_FORWARDED_FOR', 'HTTP_X_REAL_IP', 'HTTP_X_CLIENT_IP'):
        val = (env.get(key) or '').strip()
        if val:
            # XFF 可能是 "1.2.3.4, 5.6.7.8"：第一个是原始客户端
            return val.split(',')[0].strip()
    val = (env.get('REMOTE_ADDR') or '').strip()
    if val:
        return val
    scope = env.get('asgi.scope') or {}
    client = scope.get('client') if isinstance(scope, dict) else None
    if client:
        try:
            return str(client[0])
        except Exception:
            pass
    return (fallback or '').strip() or 'unknown'


def is_private(ip: str) -> bool:
    """是否内网地址（127.* / 10.* / 192.168.* / 172.16-31.* / ::1）。"""
    ip = (ip or '').strip()
    if not ip or ip == 'unknown':
        return False
    if ip.startswith('::1') or ip.startswith('127.') or ip.startswith('::ffff:127.'):
        return True
    if ip.startswith('10.') or ip.startswith('192.168.'):
        return True
    if ip.startswith('172.'):
        try:
            second = int(ip.split('.')[1])
        except Exception:
            return False
        return 16 <= second <= 31
    # 链路本地 / 唯一本地（IPv6）
    if ip.lower().startswith('fe80:') or ip.lower().startswith('fd'):
        return True
    return False


# ---------------------------------------------------------------
# 计数账本
# ---------------------------------------------------------------
def _day_key(now: float) -> str:
    return time.strftime('%Y-%m-%d', time.localtime(now))


class Ledger:
    """按天滚动的计数账本：每 IP 的分钟桶、每 IP 的当天总量、全局当天总量。

    落盘到 `data/gate_usage.json`（**按天滚动，进程重启不清零** —— 穿透服务要是
    半夜被重启一次就白限了）。写盘失败不影响主流程（限流不该把服务搞挂）。
    """

    def __init__(self, path=None):
        self._lock = threading.Lock()
        self.path = Path(path) if path else Path(os.getenv('GATE_STATE_FILE')
                                                 or DEFAULT_STATE_FILE)
        self.data = {'day': '', 'minute': {}, 'per_ip': {}, 'total': 0}
        self._load()

    # -- 持久化 --------------------------------------------------
    def _load(self):
        try:
            if self.path.exists():
                raw = json.loads(self.path.read_text(encoding='utf-8'))
                if isinstance(raw, dict):
                    self.data = {
                        'day': str(raw.get('day') or ''),
                        'minute': dict(raw.get('minute') or {}),
                        'per_ip': dict(raw.get('per_ip') or {}),
                        'total': int(raw.get('total') or 0),
                    }
        except Exception as e:
            print('[gate] load error:', e)

    def _save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix('.json.tmp')
            tmp.write_text(json.dumps(self.data, ensure_ascii=False), encoding='utf-8')
            tmp.replace(self.path)
        except Exception as e:
            print('[gate] save error:', e)

    # -- 核心 ----------------------------------------------------
    def _rollover(self, now: float):
        """跨天 / 跨分钟桶时复位（调用方须持锁）。"""
        day = _day_key(now)
        if self.data['day'] != day:
            self.data = {'day': day, 'minute': {}, 'per_ip': {}, 'total': 0}
        mkey = str(int(now // 60))
        minute = self.data['minute']
        for ip in list(minute.keys()):
            if not (isinstance(minute[ip], list) and minute[ip] and minute[ip][0] == mkey):
                minute.pop(ip, None)

    def check(self, ip: str, cfg: dict, now: float = None) -> tuple:
        """只判断不记账。返回 `(是否放行, 拒绝理由)`。"""
        now = time.time() if now is None else now
        ip = (ip or '').strip() or 'unknown'
        with self._lock:
            self._rollover(now)
            mkey = str(int(now // 60))
            slot = self.data['minute'].get(ip)
            n_min = int(slot[1]) if isinstance(slot, list) and len(slot) > 1 else 0
            n_day = int(self.data['per_ip'].get(ip, 0))
            total = int(self.data['total'])
        if cfg['per_min'] > 0 and n_min >= cfg['per_min']:
            return False, (f'⏳ 你这条线路**每分钟最多 {cfg["per_min"]} 条**对话，'
                           f'稍等一分钟就能继续。')
        if cfg['per_day'] > 0 and n_day >= cfg['per_day']:
            return False, (f'⏳ 你这条线路今天已用完 {cfg["per_day"]} 条额度，'
                           f'明天（北京时间 0 点）自动恢复。')
        if cfg['budget'] > 0 and total >= cfg['budget']:
            return False, ('🔒 演示服务今天的**全局调用预算已用完**，为避免计费超额已暂停响应。'
                           '明天自动恢复，或联系服务提供方。')
        return True, ''

    def record(self, ip: str, now: float = None):
        """放行后记账（调用方须先 `check` 通过）。"""
        now = time.time() if now is None else now
        ip = (ip or '').strip() or 'unknown'
        with self._lock:
            self._rollover(now)
            mkey = str(int(now // 60))
            slot = self.data['minute'].get(ip)
            if isinstance(slot, list) and len(slot) > 1 and slot[0] == mkey:
                slot[1] = int(slot[1]) + 1
            else:
                self.data['minute'][ip] = [mkey, 1]
            self.data['per_ip'][ip] = int(self.data['per_ip'].get(ip, 0)) + 1
            self.data['total'] = int(self.data['total']) + 1
            self._save()

    def hit(self, ip: str, cfg: dict, now: float = None) -> tuple:
        """`check` + `record` 一步到位。"""
        ok, reason = self.check(ip, cfg, now)
        if ok:
            self.record(ip, now)
        return ok, reason

    # -- 观察（给 /gate 状态查看 / 调试用） ----------------------
    def snapshot(self, ip: str = '', now: float = None) -> dict:
        now = time.time() if now is None else now
        with self._lock:
            self._rollover(now)
            mkey = str(int(now // 60))
            slot = self.data['minute'].get((ip or '').strip() or 'unknown')
            n_min = int(slot[1]) if isinstance(slot, list) and len(slot) > 1 else 0
            return {'day': self.data['day'],
                    'my_minute': n_min,
                    'my_day': int(self.data['per_ip'].get((ip or '').strip() or 'unknown', 0)),
                    'total': int(self.data['total'])}


_ledger = None


def gate_ledger() -> Ledger:
    """进程内单例（多线程共享一把锁，计数才准）。"""
    global _ledger
    if _ledger is None:
        _ledger = Ledger()
    return _ledger


# ---------------------------------------------------------------
# 口令
# ---------------------------------------------------------------
def verify_code(guess: str, code: str) -> bool:
    """口令比对。没设口令时**永远失败**（不允许"空口令 = 放行"这种漏洞）。"""
    if not code:
        return False
    try:
        import hmac
        return hmac.compare_digest(str(guess or '').strip(), str(code))
    except Exception:
        return str(guess or '').strip() == str(code)


# ---------------------------------------------------------------
# 演示模式开关（2026-09-22 起替代口令：作者无法把口令发给评委）
# ---------------------------------------------------------------
def demo_reject(ip: str, cfg: dict) -> str:
    """公网开关（先于限流/预算）：放行返回 ``''``，拒绝返回原因文案。

    - **内网来源**（127.* / 10.* / 192.168.* 等，且 `skip_local`）→ 永远放行，
      本机开发零影响；
    - **公网来源**：只有作者显式开启演示模式（`DEMO_MODE=1`）才放行；
    - 公网且未开演示模式 → 拒绝并明确告知"仅限本机访问"（不静默）。
    """
    if cfg.get('skip_local') and is_private(ip):
        return ''
    if cfg.get('demo_mode'):
        return ''
    return ('🔒 演示模式未开启：当前服务仅限本机（作者）访问。'
            '服务方在本机开启演示模式后，公网才能使用。')
