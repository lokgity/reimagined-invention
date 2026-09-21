# -*- coding: utf-8 -*-
"""verify_elasticity_band.py —— 价格—单量弹性「口径区间」回归
=============================================================
锁五件事：
 1. **不适用时不出现**：未指定品牌 / 未做校正 / 校正价恰等于画像价 → 口径区间为 None，
    不许为了显得"考虑了不确定性"而摆一个两端同值的假区间；
 2. **结构自洽**：「单量刚性」档必须与主口径逐位相同（同一套参数），
    「营业额刚性」档的日单量必须按 price_cat/price_eff 反推；
 3. **方向随价格档翻转**：低价品牌（蜜雪 ¥11.4 < 画像 ¥16）营业额刚性端更高；
    高价品牌（喜茶 ¥24 > 画像 ¥16）单量刚性端更高；
 4. **稳健性判定正确**：扫租金找到"一端否决一端放行"的窗口，
    该处必须报 结论稳健=False 且在 warnings 里出现"结论不稳健"；
 5. **看板只在该出现时出现**：有区间才出卡片/表格行。

背景：83 家标定样本的日单量基准 250 单/天是**混合品牌**中位（蜜雪仅占 17%），
隐含绑定 ¥16 那一档定价；客单价校正却是品牌级的。只换单价不换单量，等于隐含
假设需求量对价格完全无弹性。真实弹性在 (−1, 0) 之间，且现有样本无法标定它
（无营业数据，外卖月售作为经营代理已被证伪），故并列两个建模极端而非编系数。

用法：C:\\Python314\\python.exe src/analysis/verify_elasticity_band.py
输出：同目录 _verify_elasticity_band.txt
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / '.pylibs'))

OUT = HERE / '_verify_elasticity_band.txt'
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


from engine.scoring import score_site, elasticity_band  # noqa: E402

SITE = (121.5503, 29.8735)      # 宁波天一广场
SITE_NAME = '宁波天一广场'
CAT = '奶茶'
PRICE_CAT = 16                   # config 里奶茶画像价
AMORT = 200000


def frozen_ref(price, n=3):
    """冻结的 price_ref，避免测试依赖实时高德（口径区间只关心 price 这个数本身）。"""
    return {'校正客单价': price, '校正倍数': round(PRICE_CAT / price, 2),
            '口径': f'测试冻结：同品牌 {n} 家均 ¥{price:g}',
            '抓取状态': 'ok', '来源': '测试', '取证时间': '2026-09-15T00:00:00',
            '证据': {'样本数': n, '同品牌人均中位': price,
                     '门店': [f'测试门店{i}' for i in range(1, n + 1)]}}


def run(brand, price, rent=12000, area=30, staff=2):
    return score_site(CAT, *SITE, rent, name=SITE_NAME, area_m2=area, city='宁波',
                      city_level=1.0, investment=AMORT, staff=staff, brand=brand,
                      price_ref=frozen_ref(price) if price else
                      {'校正客单价': None, '抓取状态': 'no_same_brand', '口径': '冻结·未校正'})


p('口径区间回归 —— %s %s / %s' % (SITE_NAME, SITE, CAT))
p()

# ---------------------------------------------------------------
p('=== T1 不适用时必须返回 None（不许造假区间）===')
r_nobrand = score_site(CAT, *SITE, 12000, name=SITE_NAME, area_m2=30, city='宁波',
                       city_level=1.0, investment=AMORT, staff=2, brand=None)
check('未指定品牌 → 无口径区间', r_nobrand.get('口径区间') is None,
      str(r_nobrand.get('口径区间')))

r_nocorr = run('古茗', None)
check('指定品牌但未做校正 → 无口径区间', r_nocorr.get('口径区间') is None,
      str(r_nocorr.get('口径区间')))

r_same = run('古茗', 16.0)
check('校正价恰等于画像价 → 无口径区间（两端同值，摆出来是假不确定性）',
      r_same.get('口径区间') is None, str(r_same.get('口径区间')))
check('未校正时不产生"口径不确定"警告',
      not any('盈利口径不确定' in w for w in r_nocorr['warnings']), '')

# ---------------------------------------------------------------
p()
p('=== T2 结构自洽（低价品牌 蜜雪冰城 ¥11.4/单）===')
r = run('蜜雪冰城', 11.4)
cb = r.get('口径区间') or {}
civ = cb.get('区间') or {}
tiers = {t['口径']: t for t in (cb.get('档位') or [])}
det = r['evidence']['流水明细']
daily = det['未取整日单量']
check('日单量键存在且取整后等于展示值',
      round(daily) == det['估算日单量'], f'{daily} → {det["估算日单量"]}')
check('两个档位齐全', set(tiers) == {'单量刚性', '营业额刚性'}, str(sorted(tiers)))
check('单量刚性档月流水 = 未取整日单量 × 校正价 × 30',
      tiers['单量刚性']['月流水'] == round(daily * 11.4 * 30),
      f"{tiers['单量刚性']['月流水']} vs {round(daily * 11.4 * 30)}")
check('单量刚性档月净利与主口径**逐位相同**（同一套参数，不能有两套算法）',
      tiers['单量刚性']['月净利'] == r['profit']['月净利估算'],
      f"{tiers['单量刚性']['月净利']} vs {r['profit']['月净利估算']}")
check('单量刚性档日单量与主口径相同（弹性 0 = 单量不跟价格动）',
      tiers['单量刚性']['日单量参考'] == r['profit']['日单量参考'],
      f"{tiers['单量刚性']['日单量参考']} vs {r['profit']['日单量参考']}")
check('营业额刚性档月流水 = 未取整日单量 × 画像价 × 30',
      tiers['营业额刚性']['月流水'] == round(daily * PRICE_CAT * 30),
      f"{tiers['营业额刚性']['月流水']} vs {round(daily * PRICE_CAT * 30)}")
check('营业额刚性档日单量按 price_cat/price_eff 反推（不是白捡流水）',
      tiers['营业额刚性']['日单量参考'] == round(daily * PRICE_CAT / 11.4),
      f"{tiers['营业额刚性']['日单量参考']} vs {round(daily * PRICE_CAT / 11.4)}")
check('营业额刚性档人数 ≥ 单量刚性档人数（单量涨了人工必须跟着涨）',
      tiers['营业额刚性']['人数'] >= tiers['单量刚性']['人数'],
      f"{tiers['营业额刚性']['人数']} vs {tiers['单量刚性']['人数']}")
_pv = civ.get('月流水区间(元/月)') or (None, None)
_nv = civ.get('月净利区间(元/月)') or (None, None)
check('流水区间为 (min, max) 且覆盖两档',
      _pv == (min(t['月流水'] for t in tiers.values()),
              max(t['月流水'] for t in tiers.values())), str(_pv))
check('净利区间为 (min, max) 且覆盖两档',
      _nv == (min(t['月净利'] for t in tiers.values()),
              max(t['月净利'] for t in tiers.values())), str(_nv))
_pb = civ.get('回本区间(月)')
check('回本区间按 (最慢, 最快) 排（与 profit_bands 同约定）',
      _pb is None or _pb[0] >= _pb[1], str(_pb))
check('区间声明里写明了"单侧"和上界外推的局限',
      '单侧' in str(civ.get('口径')) and '面积承载' in str(civ.get('口径')),
      str(civ.get('口径'))[:70])

# ---------------------------------------------------------------
p()
p('=== T3 方向随价格档翻转 ===')
check('低价品牌：营业额刚性端 > 单量刚性端（低价换高频，流水被抬高）',
      tiers['营业额刚性']['月流水'] > tiers['单量刚性']['月流水'],
      f"{tiers['单量刚性']['月流水']} < {tiers['营业额刚性']['月流水']}")

r_hi = run('喜茶', 24.0)
cb_hi = r_hi.get('口径区间') or {}
th = {t['口径']: t for t in (cb_hi.get('档位') or [])}
check('高价品牌：单量刚性端 > 营业额刚性端（高价低量，流水被压低）',
      th['单量刚性']['月流水'] > th['营业额刚性']['月流水'],
      f"{th['单量刚性']['月流水']} > {th['营业额刚性']['月流水']}")
check('高价品牌营业额刚性端月流水 = 日单量 × 画像价 × 30',
      th['营业额刚性']['月流水'] == round(r_hi['evidence']['流水明细']['未取整日单量']
                                          * PRICE_CAT * 30),
      f"{th['营业额刚性']['月流水']} vs "
      f"{round(r_hi['evidence']['流水明细']['未取整日单量'] * PRICE_CAT * 30)}")

# ---------------------------------------------------------------
p()
p('=== T4 稳健性判定（扫租金，三种状态自适应取代表点）===')
_STATES = {}


def _state(rent):
    b = (run('蜜雪冰城', 11.4, rent=rent).get('口径区间') or {}).get('区间', {})
    concl = str(b.get('结论'))
    if b.get('结论稳健') is False:
        return 'unstable'
    if '都不触发' in concl:
        return 'both_pass'
    if '都触发' in concl:
        return 'both_veto'
    return '?'


_scanned = []
for _r in range(1000, 400001, 2000):
    st = _state(_r)
    _scanned.append((_r, st))
    if st != 'unstable' and st not in _STATES:
        _STATES[st] = _r
    if len(_STATES) >= 2 and any(s == 'unstable' for _, s in _scanned):
        break
_unstable_rents = [r for r, s in _scanned if s == 'unstable']
p(f'  代表点: {_STATES}；不稳定点 {len(_unstable_rents)} 个'
  f'（{_unstable_rents[0] if _unstable_rents else "-"} ~ '
  f'{_unstable_rents[-1] if _unstable_rents else "-"}）')

_r_bp = _STATES.get('both_pass')
check('存在"两端都放行"的租金', _r_bp is not None, str(_r_bp))
if _r_bp:
    _c = (run('蜜雪冰城', 11.4, rent=_r_bp).get('口径区间') or {}).get('区间', {})
    check('两端都放行 → 稳健=True', _c.get('结论稳健') is True, str(_c.get('结论')))
    check('两端都放行 → 措辞为"不敏感"', '不敏感' in str(_c.get('结论')),
          str(_c.get('结论')))

_r_bv = _STATES.get('both_veto')
check('存在"两端都否决"的租金', _r_bv is not None, str(_r_bv))
if _r_bv:
    _c = (run('蜜雪冰城', 11.4, rent=_r_bv).get('口径区间') or {}).get('区间', {})
    check('两端都否决 → 稳健=True（不敏感也是结论）',
          _c.get('结论稳健') is True, str(_c.get('结论')))
    check('两端都否决 → 措辞为"都触发一票否决"',
          '都触发一票否决' in str(_c.get('结论')), str(_c.get('结论')))

check('存在"结论不稳健"的租金窗口', len(_unstable_rents) > 0,
      f'{len(_unstable_rents)} 点')
if _unstable_rents:
    _fr = _unstable_rents[0]
    rf = run('蜜雪冰城', 11.4, rent=_fr)
    _bf = (rf.get('口径区间') or {}).get('区间', {})
    _t = {t['口径']: t for t in rf['口径区间']['档位']}
    check('不稳健时警告里出现"结论不稳健"',
          any('结论不稳健' in w for w in rf['warnings']),
          next((w for w in rf['warnings'] if '不稳健' in w), '无')[:80])
    _vt0 = (_t['单量刚性']['月净利'] <= 0
            or (_t['单量刚性']['回本周期(月)'] or 1e9) > 24)
    _vt1 = (_t['营业额刚性']['月净利'] <= 0
            or (_t['营业额刚性']['回本周期(月)'] or 1e9) > 24)
    check('不稳健时两端的否决判定确实相反', _vt0 != _vt1,
          f"月租 {_fr}: 单量刚性 净利 {_t['单量刚性']['月净利']}／回本 "
          f"{_t['单量刚性']['回本周期(月)']}；营业额刚性 净利 "
          f"{_t['营业额刚性']['月净利']}／回本 {_t['营业额刚性']['回本周期(月)']}")

# ---------------------------------------------------------------
p()
p('=== T4b 四档稳健性（2026-09-20 新增）===')
# 档位是**确定性等级，不是概率**。两条分界是人为约定，这里把它们钉住，
# 防止以后有人调了阈值却没同步界面文案。
_TIERS4 = {'稳健', '比较稳健', '比较不稳健', '不稳健'}
_tier_seen, _tier_bad, _b_last = set(), [], {}
for _r in range(6000, 46001, 2000):
    _b = (run('蜜雪冰城', 11.4, rent=_r).get('口径区间') or {}).get('区间', {})
    _b_last = _b
    _tt, _ss = _b.get('稳健档'), _b.get('结论稳健')
    _tier_seen.add(_tt)
    if (_ss is True) != (_tt in ('稳健', '比较稳健')):
        _tier_bad.append((_r, _tt, _ss))
check('稳健档取值都落在四档之内', _tier_seen <= _TIERS4,
      str(sorted(str(x) for x in _tier_seen)))
check('布尔「结论稳健」与四档自洽：True ⇔ 稳健/比较稳健',
      not _tier_bad, str(_tier_bad[:3]))
check('四档不是死代码：单一口径扫描至少取到 3 个不同档位',
      len(_tier_seen) >= 3, str(sorted(str(x) for x in _tier_seen)))
check('区间里带「稳健档约定」字段（界面须能如实标注为人为约定）',
      bool(_b_last.get('稳健档约定')), str(list(_b_last.keys()))[:100])
for _r in _STATES.values():
    _bt = (run('蜜雪冰城', 11.4, rent=_r).get('口径区间') or {}).get('区间', {}).get('稳健档')
    check(f'两端同向（月租 {_r}）→ 档位 ∈ {{稳健, 比较稳健}}',
          _bt in ('稳健', '比较稳健'), str(_bt))
if _unstable_rents:
    _bt = (run('蜜雪冰城', 11.4, rent=_unstable_rents[0]).get('口径区间')
           or {}).get('区间', {}).get('稳健档')
    check('两端相反 → 档位 ∈ {比较不稳健, 不稳健}',
          _bt in ('比较不稳健', '不稳健'), str(_bt))
# 最高档「不稳健」必须可达：口径错误场景（¥7 当每单）两端净利率差 19.4pp > 12pp
_b7 = (run('蜜雪冰城', 7.0, rent=12000).get('口径区间') or {}).get('区间', {})
check('口径错误场景命中「不稳健」（最高档不是死代码）',
      _b7.get('稳健档') == '不稳健', f"档位={_b7.get('稳健档')}")
check('「不稳健」措辞仍是「结论不稳健」（旧断言口径未被改动）',
      '结论不稳健' in str(_b7.get('结论')), str(_b7.get('结论'))[:60])

# ---------------------------------------------------------------
p()
p('=== T5 与三档情景正交（互不干扰）===')
bands = r.get('profit_bands') or {}
check('三档情景仍然存在', bool(bands.get('区间')), str(list(bands.keys()))[:60])
for n in ('乐观', '中性', '保守'):
    b = bands.get(n) or {}
    if b:
        check(f'{n}档月流水 = 单量刚性档月流水（三档只变成本，不变需求）',
              b['月流水估算'] == tiers['单量刚性']['月流水'],
              f"{b['月流水估算']} vs {tiers['单量刚性']['月流水']}")
check('口径区间与三档情景是并列的两个字段，未被合并',
      '区间' in cb and '区间' in bands and cb['区间'] is not bands['区间'], '')

# ---------------------------------------------------------------
p()
p('=== T6 看板：该出现时出现、不该出现时不出 ===')
sys.path.insert(0, str(ROOT / 'src' / 'ui'))
import app_chainlit as A  # noqa: E402

d = A.build_analysis_dashboard(r)
labels = [c.get('label') for c in (d.get('cards') or [])]
check('看板卡片含"月净利区间(弹性两端)"', '月净利区间(弹性两端)' in labels, str(labels))
check('看板卡片含"口径稳健性"', '口径稳健性' in labels, str(labels))
check('看板表格行非空', bool(d.get('caliper_rows')), f"{len(d.get('caliper_rows') or [])} 行")
check('表格行含区间结论与口径声明',
      {x[0] for x in (d.get('caliper_rows') or [])} >= {'区间结论', '口径声明'},
      str([x[0] for x in (d.get('caliper_rows') or [])]))
_pn = next((c for c in d['cards'] if c['label'] == '月净利区间(弹性两端)'), {})
check('区间卡片悲观端为负时压成 bad（不给假乐观）',
      ('bad' if _nv[0] <= 0 else 'good') == _pn.get('tone'),
      f"{_nv} → {_pn.get('tone')}")

d0 = A.build_analysis_dashboard(r_nocorr)
labels0 = [c.get('label') for c in (d0.get('cards') or [])]
check('未校正时不出现区间卡片（不制造假不确定性）',
      '月净利区间(弹性两端)' not in labels0 and '口径稳健性' not in labels0, str(labels0))
check('未校正时 caliper_rows 为空', not d0.get('caliper_rows'), str(d0.get('caliper_rows')))

# ---------------------------------------------------------------
p()
if FAIL:
    p(f'❌ 共 {len(FAIL)} 项 FAIL：' + '；'.join(FAIL))
else:
    p('✅ 全部 PASS')
OUT.write_text('\n'.join(L), encoding='utf-8')
sys.exit(1 if FAIL else 0)
