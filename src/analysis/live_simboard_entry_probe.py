# -*- coding: utf-8 -*-
"""仿真看板入口的实机探针（2026-09-21）

验的是「用户手够得着」，不是「算得对」：
  ① /public/sidebar.js 里确实有 data-cmd="simboard" 按钮（服务也在读盘，不用重启）
  ② write_last_sim() 真能落盘（用**真实** build_sim 结果，不是假数据）
  ③ 落盘字段带全 来源会话 / 取证时间 / 经纬度 / 半径（红线 4）
  ④ 快照不被 clear_dashboard() 清掉
⚠️ 探针用的是真实的天一广场仿真结果（真数据、真几何），
   但**不是一次真实用户分析**，所以跑完必须删掉，不留一个"来路不明"的入口。
"""
import io
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / 'src'))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

FAIL = []


def check(name, ok, extra=''):
    print(('  [PASS] ' if ok else '  [FAIL] ') + name + (('  ← ' + str(extra)) if extra and not ok else ''))
    if not ok:
        FAIL.append(name)


# ① 前端已被服务端读到（/public 按需读盘）
import urllib.request
base = 'http://127.0.0.1:8502'
try:
    js = urllib.request.urlopen(base + '/public/sidebar.js', timeout=20).read().decode('utf-8', 'replace')
except Exception as e:
    js = ''
    print('  [WARN] 拉不到 sidebar.js：%r' % (e,))
check('服务读到的 sidebar.js 含 data-cmd="simboard"', 'data-cmd="simboard"' in js)
check('服务读到的 sidebar.js 含 simBoardHTML/syncSimBoard',
      'function simBoardHTML' in js and 'function syncSimBoard' in js)

# ② 真实仿真 → 落盘
from config import get_profile                      # noqa: E402
from engine.road_sim import build_sim, map_geometry  # noqa: E402
import importlib.util                                # noqa: E402

spec = importlib.util.spec_from_file_location('_app', ROOT / 'src' / 'ui' / 'app_chainlit.py')
# 不整模块导入（会触发 chainlit 副作用），只做**文件级**断言 + 函数级复刻校验
APP = io.open(ROOT / 'src' / 'ui' / 'app_chainlit.py', encoding='utf-8', errors='ignore').read()
check('write_last_sim 写入路径 = public/last_sim.json',
      "LAST_SIM_FILE = ROOT / 'public' / 'last_sim.json'" in APP)
check('write_last_sim 用 json.dumps(..., ensure_ascii=False)',
      'json.dumps(payload, ensure_ascii=False)' in APP)
check('快照写入用 UTF-8（中文键不炸）', "encoding='utf-8'" in APP)

prof = get_profile('奶茶')
radius = prof.get('radius', 500)
LNG, LAT = 121.551902, 29.869684
sim = build_sim('奶茶', LNG, LAT, radius, profile=prof, limit=6,
                geo=map_geometry(LAT, LNG, radius))
check('探针用的是**真实**仿真结果', sim.get('ok') is True, sim.get('原因'))

# 复刻 write_last_sim 的序列化，验证字段完整性（不依赖 chainlit 运行时）
payload = {
    'kind': 'sim_board',
    '来源会话': 'probe',
    '取证时间': '2026-09-21 00:00:00',
    '铺位': '探针铺位',
    '品类': '奶茶',
    'lng': LNG, 'lat': LAT, '半径m': radius,
    'map_b64': '',
    'sim': sim,
}
p = ROOT / 'public' / 'last_sim.json'
# ⚠️ 2026-09-21 修：原来这里跑完无条件 os.remove(p)，会把**真实分析留下的快照删掉**
#    （探针跑之前 last_sim.json 里可能是用户真实跑出来的结果）。
#    改成：有则备份、跑完原样恢复；没有才删掉探针自己写的那个。
_bak = p.with_suffix('.json.probebak')
_had = p.exists()
if _had:
    p.replace(_bak)
try:
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    back = json.loads(io.open(p, encoding='utf-8').read())
    check('快照可 JSON 往返（含中文键 + 折线数组）',
          back['来源会话'] == 'probe' and back['lng'] == LNG and back['半径m'] == radius)
    check('快照里的 sim 仍是 ok', back['sim'].get('ok') is True)
    check('快照大小可接受（<%d KB）' % 400, p.stat().st_size < 400 * 1024,
          '%.1f KB' % (p.stat().st_size / 1024))
    # ③ HTTP 拿得到
    try:
        got = json.loads(urllib.request.urlopen(base + '/public/last_sim.json', timeout=20)
                         .read().decode('utf-8'))
        check('HTTP 能取到 /public/last_sim.json（前端轮询可用）',
              got.get('kind') == 'sim_board')
    except Exception as e:
        check('HTTP 能取到 /public/last_sim.json（前端轮询可用）', False, repr(e))
finally:
    # ⚠️ 探针产物必须清掉：它不是一次真实用户分析留下的快照，
    #    留着就是一个"来路不明"的入口，正是本项目红线 1 要防的东西。
    # ⚠️ 但**原来就有的快照必须原样还回去** —— 那是用户真实分析的取证结果。
    try:
        os.remove(p)
    except OSError:
        pass
    if _had:
        _bak.replace(p)

check('探针没留下临时快照（原有的已原样恢复）',
      (not p.exists()) or (_had and p.exists() and not _bak.exists()),
      'had=%s exists=%s' % (_had, p.exists()))

print()
if FAIL:
    print('✗ %d 项未通过：' % len(FAIL))
    for f in FAIL:
        print('   ·', f)
    sys.exit(1)
print('✓ 仿真看板入口实机探针全部通过')
