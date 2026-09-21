# -*- coding: utf-8 -*-
"""闭环验证：品牌卡片选的品牌 → 真的影响评分输出（UPLIFT 生效）"""
import sys, io, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'src'))

out = io.StringIO()
def p(*a): print(*a, file=out)

from agent.agent_graph import build_brand_payload, _parse_brand_choice
from engine.scoring import score_site

# 固定坐标（避免 geocode 波动）：杭州湖滨in77 附近
LNG, LAT = 120.1693, 30.2537

# 让客单价固定，隔离出"品牌"这一个变量（沿用之前发现的 price_ref 非确定性对策）
PRICE_REF = {'校正客单价': 16.0, '样本数': 30, '说明': '冻结用于对照实验'}

p('=== 闭环：同一铺位、不同品牌 → 溢价系数应体现在流水上 ===')
p(f'坐标 ({LNG}, {LAT})，月租 ¥12000，面积 30㎡，客单价冻结 ¥{PRICE_REF["校正客单价"]}')
p()

pl = build_brand_payload()
picks = ['蜜雪冰城', '喜茶', '自创品牌', '古茗']
rows = []
for b in picks:
    r = score_site('奶茶', LNG, LAT, 12000, '杭州湖滨in77',
                   area_m2=30, investment=300000, staff=2,
                   brand=b, price_ref=PRICE_REF)
    ev = r.get('evidence') or {}
    det = ev.get('流水明细') or {}
    dims = r.get('dims') or {}
    rows.append({
        'brand': b,
        'total': r.get('total'),
        'comp': dims.get('竞争压力'),
        'rev': ev.get('预估月流水'),
        'factor': det.get('品牌溢价系数'),
        'tier': det.get('品牌溢价等级'),
        'n': det.get('品牌标定样本量'),
    })

p(f"{'品牌':<10} {'总分':>4} {'竞争压力':>6} {'月流水':>12} {'溢价系数':>8} {'等级':>6} {'n':>4}")
for x in rows:
    rev = f"{x['rev']:,.0f}" if isinstance(x['rev'], (int, float)) else '-'
    p(f"{x['brand']:<10} {str(x['total']):>4} {str(x['comp']):>6} {rev:>12} "
      f"{str(x['factor']):>8} {str(x['tier']):>6} {str(x['n']):>4}")

# 断言 1: 品牌确实进入引擎（蜜雪系数 **1.0000** —— v8 步行路网口径）
#   ⚠️ 变更史：v1 是 1.1343，v6 是 1.1903（TIER1）。v7 把"不同品牌的 uplift 差异"
#      归因清楚了 —— 蜜雪那 +19% 有 99% 是 own_S 的重复计入，故回落到 1.0018。
#      v8（2026-09-21 切表）只换距离口径（直线 → 步行路网），蜜雪进一步落到
#      **1.0000**、样本 173 → **154**（路网口径下更多门店落进 D<3 的低证据点）。
mx = [x for x in rows if x['brand'] == '蜜雪冰城'][0]
assert mx['factor'] == 1.0000, mx
assert mx['tier'] == 'TIER2' and mx['n'] == 154, mx
p()
p('✔ 蜜雪冰城 → 溢价系数 1.0000 / TIER2 / n=154（品牌确实进入引擎；v8 路网口径）')

# 断言 2: 竞争压力**随品牌引力 own_S 单调不降**
#   （设计与 `score_竞争压力` 的 docstring 一致：「品牌力强的候选(own_S大)在同等竞品
#     密度下份额更高、得分更高 —— 这正是加盟商关心的核心输出」。）
#
#   ⚠️ 本条 2026-09-20 重写，原因必须记下来，别再改回去：
#      旧断言写的是「竞争压力**与品牌无关**」，与实现和 docstring **相反**。
#      它当年能通过，纯粹是因为分公式 `s = 60 × P / P_REF` 里有个 `min(100, …)` 封顶：
#      旧锚点 P_REF=0.5012 下，四个品牌算出来是 114.08 / 116.83 / 117.09 / 117.40，
#      **全部被封顶成 100**，`len(set(...)) == 1` 因此成立 —— 差异是被封顶抹平的，
#      不是不存在。
#      换成步行路网口径、P_REF 重标为 0.6024 之后，`60×P/P_REF` 整体降到 94.92~97.67，
#      封顶不再覆盖，差异就露出来了（旧断言随即报红）。
#      ⇒ 新断言按**设计意图**表达，且对封顶稳健（封顶时全 100，仍满足"单调不降"）。
_ORDER = ['自创品牌', '喜茶', '古茗', '蜜雪冰城']          # own_S = 1.0 / 2.0 / 2.2 / 2.5
comps = {x['brand']: x['comp'] for x in rows}
_s_seq = [comps[b] for b in _ORDER]
assert _s_seq == sorted(_s_seq), ('竞争压力应随 own_S 单调不降', comps)
p(f'✔ 竞争压力随品牌引力单调不降（own_S 1.0→2.5）：{_s_seq}，符合设计')
if len(set(comps.values())) == 1:
    p(f'  （本次四品牌同分 {_s_seq[0]} —— 说明该点位被封顶或截断覆盖，非"与品牌无关"）')

# 断言 3: 同一点位上，品牌间流水差异 = own_S 效应 × uplift 效应（两者都在）
#   v7 实测：喜茶 142,494 > 蜜雪 137,574 > 自创 131,210
#   ⚠️ 这条断言改过三次，别照着旧版"修回去"：
#      v1  uplift 蜜雪 1.1343 > 自创 1.0599 > 喜茶 0.9470
#      v6  uplift 蜜雪 1.1903 > 喜茶 1.1880 > 自创 0.8370（流水同序）
#      v7  uplift 喜茶 1.0477 > 自创 1.0111 > 蜜雪 1.0018
#      v8  uplift 喜茶 1.0399 > 蜜雪 1.0000 = 自创 1.0000（后两者并列）
#   ⚠️ **注意流水顺序并不等于 uplift 顺序**：v7 下自创的 uplift（1.0111）高于
#      蜜雪（1.0018），流水却最低 —— 因为蜜雪 own_S=2.5 仍通过捕获份额 P 起作用。
#      所以这里断的是**实际看到的顺序**，不假装它等于 uplift 的顺序。
def rev_of(b):
    return [x for x in rows if x['brand'] == b][0]['rev']
p()
p('流水相对关系:')
hi, zi, xi = rev_of('蜜雪冰城'), rev_of('自创品牌'), rev_of('喜茶')
p(f'  喜茶 {xi:,.0f} / 蜜雪 {hi:,.0f} / 自创 {zi:,.0f}')
assert xi > hi > zi, (xi, hi, zi)
p('✔ 喜茶 > 蜜雪 > 自创（own_S 2.0/2.5/1.0 × uplift 1.0399/1.0000/1.0000 的合成结果；'
  'v8 下蜜雪与自创的 uplift 已并列 1.0000，流水顺序仍由 own_S 拉开）')

# 断言 4: 古茗**已收录**（v1 时是"无标定"）→ v8 系数 0.9970
#   ⚠️ 变更史：v1 的古茗没有标定样本，这条断言原本是"系数必须是 1.0"；
#      v6 整表重标定后古茗 n=218 → 收录（1.0724/TIER1）；
#      v7 消双算后回落到 0.9899/TIER2（CI 含 1.0）；
#      v8（路网口径）升到 0.9970/TIER2、**n 218 → 200** ——
#      "收录"这件事没变，变的只是它偏离 1.0 的量级。
gm = [x for x in rows if x['brand'] == '古茗'][0]
assert gm['factor'] == 0.9970, gm
assert gm['tier'] == 'TIER2' and gm['n'] == 200, gm
p()
p(f"✔ 古茗已收录 → 系数 {gm['factor']} / TIER2 / n=200（v8 路网口径）")

# 断言 5: 非奶茶品类不受影响
r2 = score_site('便利店', LNG, LAT, 12000, '杭州湖滨in77',
                area_m2=30, investment=300000, staff=1,
                brand='蜜雪冰城', price_ref=PRICE_REF)
d2 = (r2.get('evidence') or {}).get('流水明细') or {}
p(f"✔ 便利店 + 蜜雪品牌 → 系数 {d2.get('品牌溢价系数')}（非奶茶不进 UPLIFT）")
assert d2.get('品牌溢价系数') in (1.0, None)

p()
p('ALL CLOSED-LOOP CHECKS PASSED')
(Path(__file__).resolve().parent / '_verify_brand_closedloop.txt').write_text(out.getvalue(), encoding='utf-8')
print('written')
