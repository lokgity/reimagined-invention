# -*- coding: utf-8 -*-
"""verify_store_diagnosis.py —— 已开店经营诊断回归（填「零入口」缺口的验收）
==========================================================================
锁七件事（全部本地、0 次 API，可离线复现）：

 1. **口径**：毛利率是**产品口径**（只扣物料+损耗），且与「外卖抽成占流水比」
    **分开**给出——这是 2026-09-15 定的口径，混在一起会误导（详见
    `docs/经营测算口径与已开店诊断.md`）。
 2. **不新增假设**：诊断输出的每一项成本，必须与 `estimate_profit(sales_est=流水)`
    **逐项相同**。诊断只做拆解、不换成本模型——否则它和选址侧会给出两套数。
 3. **安全边际自洽**：盈亏平衡月流水 = 固定成本/(1−变动成本率)；把流水设到该点，
    月净利必须≈0。这条是"内部一致"的硬检验，比断言某个具体数字有用。
 4. **与引擎二分互相校验**：自解的「盈亏平衡月租」在中性档下必须与
    `scoring.solve_rent_limits` 的二分结果吻合（同一模型的两条独立算法）。
 5. **对标只用公开数据**：有公开数据的品牌给基准；**没有的不编**——
    茶百道（未披露单店 GMV）、奈雪（区间字符串）、喜茶（未收录）都必须是 None。
 6. **异常输入必须抛**：无流水、流水≤0、非数字，一律 ValueError，
    不能静默返回空壳（上层会误判为"诊断完成"）。
 7. **不估流水**：月流水由用户自报，诊断**不产生** `月流水估算` 字段，
    且成本项按自报值算而不是模型估值——这是它与 `score_site` 的分界线。
 8. **命名陷阱哨兵**：`utilities` 的 `月固定成本` 键，值是**总成本**（误名；
   已降为兼容别名，规范键为 `月成本合计`）。断言两者不被混用、且总成本=流水−净利。

用法：C:\\Python314\\python.exe src/analysis/verify_store_diagnosis.py
输出：同目录 _verify_store_diagnosis.txt
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / '.pylibs'))

OUT = HERE / '_verify_store_diagnosis.txt'
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


from engine.store_diagnosis import (diagnose_existing_store, brand_benchmark,
                                    GROSS_MARGIN_CALIBER)
from engine.utilities import estimate_profit, COMMISSION_RATE

# 统一的基准场景：奶茶 / 30㎡ / 宁波 / 2 人 / 月租 12000 / 蜜雪冰城
CAT, AREA, CITY, RENT, STAFF, BRAND = '奶茶', 30, '宁波', 12000, 2, '蜜雪冰城'
REV = 80000


def _run(rev=REV, **kw):
    args = dict(monthly_rent=RENT, area_m2=AREA, city=CITY, staff=STAFF, brand=BRAND)
    args.update(kw)
    return diagnose_existing_store(CAT, rev, **args)


def main():
    p('=== verify_store_diagnosis —— 已开店经营诊断回归 ===')
    p(f'基准场景：{CAT} / {AREA}㎡ / {CITY} / {STAFF} 人 / 月租 {RENT} / {BRAND} / '
      f'自报月流水 {REV:,}')
    p('')

    r = _run()

    # ---- T1 口径 ----
    p('=== T1 毛利口径（产品口径 vs 扣渠道，必须分开且可复算）===')
    gm, rev = r['毛利率'], r['输入']['实际月流水']
    back = 1 - (r['成本拆解']['月物料'] + r['成本拆解']['月损耗']) / rev
    check('毛利率 == 1 −(物料+损耗)/流水（产品口径可复算）',
          abs(gm - back) < 1.5e-3, f'{gm:.4f} vs {back:.4f}')
    check('扣渠道后毛利率 == 毛利率 − 外卖抽成占流水比',
          abs(r['扣渠道后毛利率'] - (gm - r['外卖抽成占流水比'])) < 1e-9,
          f"{r['扣渠道后毛利率']} vs {gm - r['外卖抽成占流水比']:.4f}")
    expected_over = round(0.35 * COMMISSION_RATE, 4)   # 奶茶外卖占比 35% × 佣金 22%
    check('外卖抽成占流水比 == 外卖占比×佣金率', r['外卖抽成占流水比'] == expected_over,
          f"{r['外卖抽成占流水比']} vs {expected_over}")
    check('口径文本写明"不含外卖抽成"', '不含外卖抽成' in GROSS_MARGIN_CALIBER,
          GROSS_MARGIN_CALIBER)
    check('输出带口径标识', r['毛利率口径'] == GROSS_MARGIN_CALIBER)
    # 毛利率与流水规模无关（是率不是额）——换一个流水应完全相同
    r_other = _run(rev=200000)
    check('毛利率是率、不随流水规模变化', r_other['毛利率'] == gm,
          f"{gm} vs {r_other['毛利率']}")
    p('')

    # ---- T2 不新增假设：与 estimate_profit 逐项相同 ----
    p('=== T2 诊断不换成本模型（与 estimate_profit 逐项一致）===')
    prof = estimate_profit(CAT, AREA, CITY, RENT, staff=STAFF,
                           sales_est=REV, brand=BRAND)
    pairs = [('月物料', '月物料成本'), ('月损耗', '月损耗'), ('月外卖抽成', '月外卖抽成'),
             ('月人工', '月人工'), ('月水电', '月水电'), ('月租金', '月租金'),
             ('月场地附加费', '月场地附加费'), ('月税', '月税'), ('月摊销', '月摊销'),
             ('月品牌费', '月品牌费'), ('月杂费', '月杂费')]
    diffs = [(a, r['成本拆解'][a], prof[b]) for a, b in pairs
             if r['成本拆解'][a] != prof[b]]
    check('11 项成本逐项相同', not diffs, str(diffs[:3]))
    # ⚠️ 这里锁一个真实的命名陷阱（2026-09-15 发现）：
    #    utilities 的 `月固定成本` 键**值是总成本**（含物料/外卖抽成/场地/税/损耗），
    #    比真固定成本高出一倍多（宁波 30㎡ 蜜雪：真固定 ¥37,777 vs 总成本 ¥78,336）。
    #    已把规范键改为 `月成本合计`、旧键降为兼容别名；诊断里两个都给。
    #    下面既验正确性，也验两者不被当成同一个数。
    true_fixed = sum(prof[k] for k in ['月租金', '月人工', '月水电', '月摊销',
                                       '月品牌费', '月杂费'])
    check('诊断的月固定成本 == 真固定成本（不含变动项，≤3 元取整差）',
          abs(r['成本拆解']['月固定成本'] - true_fixed) <= 3,
          f"{r['成本拆解']['月固定成本']} vs {true_fixed}")
    parts = ['月物料', '月损耗', '月外卖抽成', '月人工', '月水电', '月租金',
             '月场地附加费', '月税', '月摊销', '月品牌费', '月杂费']
    check('月成本合计 == 11 项分项之和（≤3 元取整差）',
          abs(r['成本拆解']['月成本合计'] - sum(r['成本拆解'][k] for k in parts)) <= 3,
          f"{r['成本拆解']['月成本合计']} vs {sum(r['成本拆解'][k] for k in parts)}")
    check('月成本合计 == 流水 − 净利（总成本口径自证）',
          abs(r['成本拆解']['月成本合计'] - (REV - prof['月净利估算'])) <= 2,
          f"{r['成本拆解']['月成本合计']} vs {REV - prof['月净利估算']}")
    check('总成本严格大于固定成本（防"两个键当成一个数"回归）',
          r['成本拆解']['月成本合计'] > r['成本拆解']['月固定成本'] * 1.3,
          f"{r['成本拆解']['月成本合计']} vs {r['成本拆解']['月固定成本']}")
    check('月净利与 estimate_profit 相同', r['月净利'] == prof['月净利估算'],
          f"{r['月净利']} vs {prof['月净利估算']}")
    p('')

    # ---- T3 安全边际自洽 ----
    p('=== T3 安全边际自洽（内部一致性，不依赖外部经验阈值）===')
    bep, f_fixed = r['盈亏平衡月流水'], r['成本拆解']['月固定成本']
    v = r['变动成本率']
    check('盈亏平衡月流水 == 固定成本/(1−变动成本率)',
          abs(bep - f_fixed / (1 - v)) <= 2, f'{bep} vs {f_fixed / (1 - v):.1f}')
    check('安全边际额 == 实际流水 − 盈亏平衡流水',
          abs(r['安全边际额'] - (rev - bep)) <= 2, f"{r['安全边际额']} vs {rev - bep}")
    check('安全边际率 == 安全边际额/流水',
          abs(r['安全边际率'] - (rev - bep) / rev) < 1e-3,
          f"{r['安全边际率']} vs {(rev - bep) / rev:.4f}")
    # 把流水正好设在盈亏平衡点上 → 月净利应≈0
    r_at = _run(rev=bep)
    check('流水置于盈亏平衡点时月净利≈0（±2%流水）',
          r_at['月净利'] is not None and abs(r_at['月净利']) < 0.02 * bep,
          f"净利 {r_at['月净利']} @ 流水 {bep}")
    check('低于盈亏平衡点时安全边际率为负', _run(rev=int(bep * 0.8))['安全边际率'] < 0,
          str(_run(rev=int(bep * 0.8))['安全边际率']))
    p('')

    # ---- T4 与引擎二分互相校验 ----
    p('=== T4 自解租金临界点 vs scoring 二分（同一模型的两条独立算法）===')
    rl = r['租金临界点(引擎二分)']
    check('solve_rent_limits 被成功调用（不是被 except 静默吞掉）', rl is not None, str(rl))
    if rl:
        d = abs(r['盈亏平衡月租'] - rl['盈亏平衡月租'])
        p(f'  自解 ¥{r["盈亏平衡月租"]:,}　二分 ¥{rl["盈亏平衡月租"]:,}　差 ¥{d:,}')
        check('中性档下两个盈亏平衡月租吻合（≤2%）',
              d <= max(200, 0.02 * rl['盈亏平衡月租']),
              f'差 {d}')
    check('租金余量 == 盈亏平衡月租 − 实际月租',
          r['租金余量'] == r['盈亏平衡月租'] - RENT,
          f"{r['租金余量']} vs {r['盈亏平衡月租'] - RENT}")
    p('')

    # ---- T5 对标只用公开数据，没有就不编 ----
    p('=== T5 品牌对标（只认公开披露，无数据不编）===')
    bench = brand_benchmark(BRAND)
    check('蜜雪冰城有公开基准', bench is not None, str(bench and bench['基准月流水']))
    check('蜜雪基准月流水 == 日均GMV×30（哨兵：改 CSV 需同步改此处）',
          bench and bench['基准月流水'] == round(4184.4 * 30),
          str(bench and bench['基准月流水']))
    check('基准带出披露期间与来源（口径可追溯）',
          bench and bench['期间'] and bench['来源'],
          f"{bench and bench['期间']} / {bench and bench['来源']}")
    check('对标比值 == 流水/基准', r['品牌对标']['你/基准'] == round(REV / bench['基准月流水'], 3),
          str(r['品牌对标']['你/基准']))
    for name, why in [('茶百道', 'CSV 未披露单店 GMV'), ('奈雪的茶', 'GMV 是区间字符串'),
                      ('喜茶', 'CSV 未收录')]:
        check(f'{name} 无可用基准 → None（{why}）', brand_benchmark(name) is None,
              str(brand_benchmark(name)))
    r_nb = diagnose_existing_store(CAT, REV, monthly_rent=RENT, area_m2=AREA,
                                   city=CITY, staff=STAFF)   # 不传 brand
    check('不传 brand → 不做对标', r_nb['品牌对标'] is None and r_nb['品牌基准明细'] is None)
    p('')

    # ---- T6 异常输入必须抛 ----
    p('=== T6 异常输入（不静默返回空壳）===')
    for label, kwargs, rev in [
        ('两者都不给', dict(daily_orders=None), None),
        ('流水为 0', {}, 0),
        ('流水为负', {}, -5000),
        ('流水非数字', {}, 'abc'),
    ]:
        try:
            diagnose_existing_store(CAT, rev, monthly_rent=RENT, area_m2=AREA,
                                    city=CITY, **kwargs)
            check(f'{label} → ValueError', False, '未抛异常')
        except ValueError as e:
            check(f'{label} → ValueError', True, str(e)[:40])
        except Exception as e:                                     # noqa: BLE001
            check(f'{label} → ValueError', False, f'抛了 {type(e).__name__}')
    p('')

    # ---- T7 日单量折算 + 不估流水 ----
    p('=== T7 日单量折算 & 诊断不产生"估流水"字段 ===')
    r_do = diagnose_existing_store(CAT, None, monthly_rent=RENT, area_m2=AREA,
                                   city=CITY, staff=STAFF, daily_orders=250, price=16)
    check('daily_orders×price×30 折算月流水', r_do['输入']['实际月流水'] == 250 * 16 * 30,
          str(r_do['输入']['实际月流水']))
    try:
        diagnose_existing_store(CAT, None, monthly_rent=RENT, area_m2=AREA,
                                city=CITY, daily_orders=250)
        check('只给日单量不给每单金额 → ValueError', False, '未抛异常')
    except ValueError:
        check('只给日单量不给每单金额 → ValueError', True)
    check('输出不含"月流水估算"字段（流水自报、不估）',
          '月流水估算' not in r and '月流水估算' not in r['成本拆解'], '')
    check('成本按自报流水算（月物料 = 流水×物料占比，非模型估值）',
          abs(r['成本拆解']['月物料'] - REV * prof['物料占比']) <= 1.5,
          f"{r['成本拆解']['月物料']} vs {REV * prof['物料占比']:.1f}")
    p('')

    # ---- T8 诊断文本随情形改变 ----
    p('=== T8 诊断文本（有依据，不产营销玄学）===')
    hi = _run(rev=200000)                 # 高流水：应提到超过品牌基准
    check('高流水 → 提到达到/超过品牌基准',
          any('基准' in t for t in hi['诊断']), str(hi['诊断'][:1])[:70])
    check('亏损情形 → 明说"当前是亏损的"',
          any('当前是亏损的' in t for t in _run(rev=30000)['诊断']),
          str(_run(rev=30000)['诊断'])[:80])
    check('诊断条数 ≥2 且无空条', len(r['诊断']) >= 2 and all(t for t in r['诊断']),
          str(len(r['诊断'])))
    check('局限声明与结论同出', any('假设区间' in x for x in r['局限']), str(len(r['局限'])))
    p('')

    # ---- T9 确定性 ----
    p('=== T9 确定性（同输入两次逐位相同）===')
    a, b = _run(), _run()
    check('两次调用结果完全相同', a == b)
    p('')

    p('=' * 60)
    if FAIL:
        p(f'FAILED = {len(FAIL)}')
        for f in FAIL:
            p(f'  x {f}')
    else:
        p('全部 PASS')
    OUT.write_text('\n'.join(L), encoding='utf-8')
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
