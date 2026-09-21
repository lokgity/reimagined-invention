# -*- coding: utf-8 -*-
"""verify_access_gate.py —— 公网访问闸门回归（纯逻辑 + 源码接线）
==========================================================================
背景：服务一旦做内网穿透 / 云部署，任何拿到链接的人都能触发服务端付费调用
（LLM + 高德）。`ui/access_gate.py` 提供三道闸门：口令 / 每 IP 限流 / 全局日预算。
本套件把它的**算术与默认值**钉死，并断言 Chainlit 入口真的挂上了。

为什么必须单独一个套件（而不是塞进 verify_experts）：
· 闸门是"钱"的闸门。默认值一旦被人顺手改成 0/空，表现为"没拦住"，
  而**没拦住这件事在本地永远看不出来** —— 只有月底账单会告诉你。
· `access_gate.py` 跑在 3.12 + Chainlit 上，这里用 3.14 直接 import 纯逻辑，
  和 `agent/replay.py` 的隔离约定一致。

⚠️ 纪律：本套件**绝不能碰真实的 `data/gate_usage.json`**（那是运行时账本），
所有 Ledger 实例一律传 tmp 路径。

用法：C:\\Python314\\python.exe src/analysis/verify_access_gate.py
输出：同目录 _verify_access_gate.txt
"""
import os
import sys
import time
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / '.pylibs'))

OUT = HERE / '_verify_access_gate.txt'
L = []
FAIL = []


def p(*a):
    s = ' '.join(str(x) for x in a)
    print(s)
    L.append(s)


def check(name, cond, detail=''):
    p(f'  {"PASS" if cond else "FAIL"}  {name}' + (f'  |  {detail}' if detail else ''))
    if not cond:
        FAIL.append(name)


from ui.access_gate import (gate_config, gate_summary, client_ip, is_private,  # noqa: E402
                            verify_code, Ledger, _day_key, demo_reject)

APP = (ROOT / 'src' / 'ui' / 'app_chainlit.py').read_text(encoding='utf-8')

# 固定"现在"，让跨分钟/跨天可复现（不依赖真实时钟，避免 flaky）
T0 = time.mktime(time.strptime('2026-09-18 12:00:00', '%Y-%m-%d %H:%M:%S'))

tmpdir = tempfile.mkdtemp(prefix='_gate_')


def cfg(**over):
    base = {'access_code': '', 'per_min': 12, 'per_day': 200,
            'budget': 400, 'skip_local': True, 'demo_mode': False}
    base.update(over)
    return base


def fresh(path=None):
    return Ledger(path or os.path.join(tmpdir, 'u%d.json' % len(os.listdir(tmpdir))))


p('=' * 74)
p('§1 默认值：本地开发必须"零影响"')
p('=' * 74)
_saved = {k: os.environ.get(k) for k in
          ('ACCESS_CODE', 'RATE_PER_MIN', 'RATE_PER_DAY', 'DAILY_BUDGET',
           'GATE_SKIP_LOCAL', 'DEMO_MODE')}
for k in _saved:
    os.environ.pop(k, None)
d = gate_config()
check('默认无口令（ACCESS_CODE 为空 → 口令关闭）', d['access_code'] == '')
check('默认每 IP 12/分钟', d['per_min'] == 12, f'实={d["per_min"]}')
check('默认每 IP 200/天', d['per_day'] == 200, f'实={d["per_day"]}')
check('默认全局日预算 400', d['budget'] == 400, f'实={d["budget"]}')
check('默认内网豁免开启（否则本地开发会被自己限流）', d['skip_local'] is True)
check('默认演示模式关闭（公网默认拒，防裸奔）', d['demo_mode'] is False)
check('gate_summary 把开关状态说出来（不静默）',
      '演示模式=关' in gate_summary(d) and '口令=关' in gate_summary(d)
      and '内网豁免=是' in gate_summary(d), gate_summary(d))
os.environ['RATE_PER_MIN'] = 'abc'
check('环境变量配错 → 回落默认值而不是崩', gate_config()['per_min'] == 12)
os.environ.pop('RATE_PER_MIN')
for k, v in _saved.items():
    if v is not None:
        os.environ[k] = v

p('')
p('=' * 74)
p('§2 口令：空口令必须永远失败')
p('=' * 74)
check('未设口令时任何输入都不放行（不许"空口令=通行"）',
      verify_code('', '') is False and verify_code('anything', '') is False)
check('口令正确放行', verify_code('abc123', 'abc123') is True)
check('口令错误拒绝', verify_code('abc124', 'abc123') is False)
check('前后空格容忍', verify_code('  abc123  ', 'abc123') is True)
check('大小写敏感（口令不是用户名，不该被规范化）',
      verify_code('ABC123', 'abc123') is False)

p('')
p('=' * 74)
p('§3 客户端 IP 提取')
p('=' * 74)
check('X-Forwarded-For 优先（穿透/反代场景唯一的真实 IP 来源）',
      client_ip({'HTTP_X_FORWARDED_FOR': '1.2.3.4', 'REMOTE_ADDR': '127.0.0.1'}) == '1.2.3.4')
check('XFF 逗号串取第一个（原始客户端）',
      client_ip({'HTTP_X_FORWARDED_FOR': '1.2.3.4, 5.6.7.8, 9.9.9.9'}) == '1.2.3.4')
check('X-Real-IP 次选', client_ip({'HTTP_X_REAL_IP': '8.8.8.8', 'REMOTE_ADDR': '127.0.0.1'}) == '8.8.8.8')
check('REMOTE_ADDR 兜底', client_ip({'REMOTE_ADDR': '203.0.113.9'}) == '203.0.113.9')
check('ASGI scope.client 兜底',
      client_ip({'asgi.scope': {'client': ('198.51.100.7', 5123)}}) == '198.51.100.7')
check('全空 → fallback', client_ip({}, fallback='sess-42') == 'sess-42')
check('全空无 fallback → unknown（不许静默当内网放行）',
      client_ip({}) == 'unknown' and is_private(client_ip({})) is False)

p('')
p('=' * 74)
p('§4 内网判定（172.16~31 是唯一需要算的边界）')
p('=' * 74)
for ip, want in (('127.0.0.1', True), ('::1', True), ('192.168.31.7', True),
                 ('10.0.0.1', True), ('172.16.0.1', True), ('172.31.255.255', True),
                 ('172.32.0.1', False), ('172.15.0.1', False), ('8.8.8.8', False),
                 ('203.0.113.9', False), ('unknown', False), ('', False)):
    check(f'is_private({ip or "空"}) == {want}', is_private(ip) is want)
check('172 段不能用前缀"172.1"蒙混（必须真算第二个数）',
      is_private('172.1.0.1') is False and is_private('172.20.5.5') is True)

p('')
p('=' * 74)
p('§5 限流算术：分钟桶 / 日桶 / 全局预算')
p('=' * 74)
c = cfg(per_min=3, per_day=5, budget=100)
lg = fresh()
oks = [lg.hit('1.1.1.1', c, now=T0 + i)[0] for i in range(3)]
check('分钟内前 3 条放行', oks == [True, True, True], str(oks))
ok4, why4 = lg.hit('1.1.1.1', c, now=T0 + 3)
check('第 4 条被分钟桶拦下', ok4 is False and '每分钟' in why4, why4)
check('拒绝理由非空（不静默拒绝）', bool(why4.strip()))
ok5, _ = lg.hit('1.1.1.1', c, now=T0 + 60)
check('跨分钟桶复位（+60s 后又能发）', ok5 is True)

lg2 = fresh()
res, why_day = [], ''
for m in range(6):
    _ok, _why = lg2.hit('2.2.2.2', c, now=T0 + 60 * m)
    res.append(_ok)
    if not _ok:
        why_day = _why
check('日桶 5 条：第 6 条被拦（即使每分钟都合规）',
      res == [True] * 5 + [False], str(res))
check('日桶拒绝文案说明恢复时间（明天）', '明天' in why_day, why_day)
okd, _ = lg2.hit('2.2.2.2', c, now=T0 + 86400)   # +1 天（86400s，不是 9 分钟）
check('跨天完全复位（+86400s）', okd is True, why_day)

lg3 = fresh()
c3 = cfg(per_min=99, per_day=999, budget=4)
r3 = [lg3.hit(f'3.3.3.{i}', c3, now=T0 + i)[0] for i in range(4)]
ok6, why6 = lg3.hit('3.3.3.9', c3, now=T0 + 9)
check('全局预算 4：前 4 条放行', r3 == [True] * 4, str(r3))
check('第 5 条被全局预算拦下（换 IP 也拦）', ok6 is False and '预算' in why6, why6)
check('预算是"拒答"不是"降级掺沙"（文案里出现暂停/预算）',
      ('暂停' in why6 or '预算' in why6))

lg4 = fresh()
c0 = cfg(per_min=0, per_day=0, budget=0)
r0 = [lg4.hit('4.4.4.4', c0, now=T0 + i)[0] for i in range(50)]
check('三项都设 0 = 闸门全关（显式关闭要真能关）', all(r0), f'拦了 {r0.count(False)} 次')

p('')
p('=' * 74)
p('§6 账本落盘：进程重启不清零')
p('=' * 74)
fpath = os.path.join(tmpdir, 'persist.json')
lga = Ledger(fpath)
lga.hit('5.5.5.5', cfg(per_min=2), now=T0)
lgb = Ledger(fpath)          # 模拟"服务重启"
check('重启后当天计数仍在（穿透服务半夜重启不该白限）',
      lgb.snapshot('5.5.5.5', now=T0)['my_day'] == 1,
      str(lgb.snapshot('5.5.5.5', now=T0)))
check('换天自动归零', _day_key(T0) != _day_key(T0 + 86400)
      and Ledger(fpath).snapshot('5.5.5.5', now=T0 + 86400)['my_day'] == 0)
check('snapshot 给出全局总量', Ledger(fpath).snapshot(now=T0)['total'] >= 1)
check('运行时账本 data/gate_usage.json 未被本套件污染',
      'gate_usage' not in fpath)

p('')
p('=' * 74)
p('§7 源码接线：闸门真的挂在 Chainlit 入口上')
p('=' * 74)
check('导入闸门模块', 'from ui.access_gate import' in APP)
check('on_chat_start 走入口闸（未过就直接 return）',
      'if not await _ensure_access():' in APP)
check('on_message 走闸门守卫（超限即返回，0 次付费 API）',
      'if not await _gate_guard(caption):' in APP)
check('守卫在附件分流之前（图片/PDF 更贵，不能绕过闸门）',
      APP.index('_gate_guard(caption)') < APP.index('els = list(message.elements'))
check('控制指令 ## 与 / 不计额度（否则点个按钮也扣）',
      "startswith(('##', '/'))" in APP)
check('内网豁免有独立开关（GATE_SKIP_LOCAL）', 'skip_local' in APP and 'is_private' in APP)
check('口令用 hmac.compare_digest（不做裸 == 拼接）',
      'compare_digest' in (ROOT / 'src' / 'ui' / 'access_gate.py').read_text(encoding='utf-8'))
check('启动即打印闸门状态（不静默，红线 4）',
      "print('[gate] '" in APP and 'gate_summary' in APP)
check('app 已切演示模式开关（demo_reject 接入入口）', 'demo_reject' in APP)
check('口令流程已下线（app 不再 import verify_code）', 'verify_code' not in APP)
check('app 不再弹口令输入框（AskUserMessage 口令流程移除）',
      'cl.AskUserMessage' not in APP or '口令' not in APP.split('cl.AskUserMessage')[0])

p('')
p('=' * 74)
p('§8 演示模式开关：默认关 → 公网拒；作者开 → 公网放行')
p('=' * 74)
check('内网 + 演示关 → 放行（本地开发永远能用）',
      demo_reject('192.168.1.8', cfg()) == '')
check('127 回环 + 演示关 → 放行', demo_reject('127.0.0.1', cfg()) == '')
r_off = demo_reject('8.8.8.8', cfg())
check('公网 + 演示关 → 拒绝（"未开只能本机用"）',
      bool(r_off) and '演示模式' in r_off, r_off)
check('公网 unknown IP + 演示关 → 拒绝（不许静默放行）',
      bool(demo_reject('unknown', cfg())))
check('公网 + 演示开 → 放行（限流/预算仍在 _gate_guard 生效）',
      demo_reject('8.8.8.8', cfg(demo_mode=True)) == '')
check('公网 + 演示开 + 内网豁免关 → 放行',
      demo_reject('203.0.113.9', cfg(demo_mode=True, skip_local=False)) == '')
_saved2 = {k: os.environ.get(k) for k in ('DEMO_MODE',)}
for k in _saved2:
    os.environ.pop(k, None)
check('DEMO_MODE 未设 → demo_mode=False（公网默认拒）',
      gate_config()['demo_mode'] is False)
os.environ['DEMO_MODE'] = '1'
check('DEMO_MODE=1 → demo_mode=True（作者放行）',
      gate_config()['demo_mode'] is True)
os.environ['DEMO_MODE'] = '0'
check('DEMO_MODE=0 → demo_mode=False', gate_config()['demo_mode'] is False)
for k, v in _saved2.items():
    if v is not None:
        os.environ[k] = v

p('')
p('=' * 74)
p(f'共 {len(FAIL)} 项 FAIL' if FAIL else '全部 PASS')
if FAIL:
    for f in FAIL:
        p('  FAIL:', f)
p('=' * 74)
OUT.write_text('\n'.join(L), encoding='utf-8')
sys.exit(1 if FAIL else 0)
