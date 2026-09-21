# -*- coding: utf-8 -*-
"""B 线回归：盈利一票否决是否贯通 引擎→看板→PDF→兜底解读→谈判助手，
且门头照不能把否决洗白。

用法: python src/analysis/test_veto.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.scoring import score_site, apply_storefront, PAYBACK_LIMIT_MONTHS  # noqa: E402
from agent.agent import rule_based_interpret, geocode  # noqa: E402
from engine.negotiation import negotiation_brief  # noqa: E402

FAIL = []

# 坐标必须走真实 geocode：硬编码差 500m 就会让客群匹配度从 86 掉到 30，测的不是同一个铺子
ADDR = '宁波天一广场'
BRAND = '蜜雪冰城'   # 与真实演示链路同口径：品牌系数进 Huff 吸引力，漏传会让竞争压力 97→63
LNG, LAT = geocode(ADDR)

# 客单价校正固定注入。测试不能让 score_site 自己去实时抓——同品牌样本数一变，
# 月流水跟着变，下面所有断言的期望值全漂，测的就不是否决逻辑而是高德数据。
#
# ⚠️ 口径是**每单金额**（元/单），不是高德 biz_ext.cost。高德 cost 在茶饮类目
#    实测 ≈ **单杯价**（蜜雪 ¥7 ↔ 招股书单杯 ¥6.72），拿它当"每单"乘进去等于
#    假设"一单一杯"，会系统性低估约 1.7 倍（蜜雪 11.4÷6.72 = 1.70 杯/单）。
#    所以这里注的是**公开披露的每单平均零售额 ¥11.4**（蜜雪招股书），单杯价
#    ¥7 只作对照。详见 docs/品牌级公开数据与客单价口径修正.md。
#
# ⚠️ 模型里日单量不随客单价联动（见 scoring.estimate_monthly_sales 注释），
#    因此这里的注入只锁"每单金额口径贯通"，**不构成对蜜雪真实流水的估计**。
PRICE_REF = {
    '校正客单价': 11.4, '单杯价': 7.0, '校正倍数': 1.4,
    '口径来源': 'public_report',
    '口径': ('已用**公开披露**的蜜雪冰城每单平均金额 ¥11.4（招股书·聆讯后资料集）覆盖'
             '品类画像假设 ¥16；高德实测同品牌单杯价 ¥7 与公开单杯价 ¥6.72 相差 4%，互为印证'),
    '证据': {'品牌': BRAND, '样本数': 2, '同品牌人均中位': 7.0,
             '同品牌人均区间': (7.0, 7.0), '全品类人均中位': 17.0,
             '门店': ['蜜雪冰城(天一广场店)', '蜜雪冰城(东鼓道店)']},
}


def check(name, cond, detail=''):
    print(('  PASS  ' if cond else '  FAIL  ') + name + (f'  | {detail}' if detail else ''))
    if not cond:
        FAIL.append(name)


def main():
    print('=== 案例 A：租金严重超载（应触发一票否决）===')
    print(f'  坐标（geocode 实取）: {LNG}, {LAT}')
    r = score_site('奶茶', LNG, LAT, 200000, ADDR, 30, investment=200000, staff=2,
                   brand=BRAND, price_ref=PRICE_REF)
    veto = r.get('veto') or {}
    rl = r.get('rent_limits') or {}
    p = r.get('profit') or {}
    print(f"  total={r['total']}  verdict={r['verdict']}  位置分结论={veto.get('位置分结论')}")
    print(f"  月净利={p.get('月净利估算')}  回本={p.get('回本周期(月)')}")
    print(f"  rent_limits={rl}")

    check('否决触发', veto.get('触发') is True, str(veto.get('原因')))
    check('综合结论被改写', r['verdict'] in ('位置好·账算不过来', '账算不过来'), r['verdict'])
    check('位置分结论独立保留', veto.get('位置分结论') in ('推荐', '谨慎推荐', '不建议优先选择', '不建议'),
          str(veto.get('位置分结论')))
    check('警告里出现红线', any('一票否决' in w for w in r['warnings']))
    check('警告里给出谈判目标价', any('必须压到' in w for w in r['warnings']))
    check('盈亏平衡月租已反解', isinstance(rl.get('盈亏平衡月租'), int), str(rl.get('盈亏平衡月租')))

    print()
    print('=== 案例 B：门头照不能洗白否决 ===')
    perfect_vlm = {'是否门头实景': True, '招牌文字': '蜜雪冰城', '识别品牌': '蜜雪冰城',
                   '装修档次': 5, '门头可见度': 5, '卫生观感': 5,
                   '观察描述': '门头崭新、招牌醒目、店前整洁',
                   '经营建议': '保持现状', '_model': 'test'}
    r2 = apply_storefront(dict(r), perfect_vlm)
    print(f"  照片前 total={r['total']} → 照片后 total={r2['total']}  verdict={r2['verdict']}")
    check('照片抬高了总分', r2['total'] > r['total'], f"{r['total']} → {r2['total']}")
    check('否决未被洗白', (r2.get('veto') or {}).get('触发') is True)
    check('照片后结论仍是否决措辞', r2['verdict'] in ('位置好·账算不过来', '账算不过来'), r2['verdict'])

    print()
    print('=== 案例 C：兜底解读口径 ===')
    txt = rule_based_interpret(r)
    print('  --- rule_based_interpret 前 6 行 ---')
    for ln in txt.split('\n')[:6]:
        print('   ', ln)
    check('兜底首行是双轴', '位置分' in txt.split('\n')[0] and '综合结论' in txt.split('\n')[0])
    check('兜底含否决原因', '🚫' in txt.split('\n')[0])
    check('兜底含租金临界点', '租金临界点' in txt and '盈亏平衡月租' in txt)

    print()
    print('=== 案例 D：谈判助手——行情降级为参考带，天花板只来自承受力 ===')
    b = negotiation_brief('宁波', '天一广场', 200000, 30, district='海曙', affordability=rl)
    bench = b.get('行情分布') or {}
    print(f"  参考带={b.get('行情参考带')}  样本={bench.get('样本数') or 0}  "
          f"疑似非同类={bench.get('疑似非同类业态样本数')}  "
          f"天花板={b.get('可承受月租上限')}  口径={b.get('上限口径')}")
    print(f"  价格位置: {b.get('价格位置')}")
    for s in (bench.get('最低5样本') or []):
        print(f"    低端样本 {s['单价']:.0f}元/㎡ {s['面积']:.0f}㎡ 「{s['标题']}」")
    for c in b['筹码']:
        if any(k in c for k in ('承受力', '盈亏平衡', '红线', '冲突', '天花板', '差额')):
            print('   筹码:', c[:120])
    check('承受力进了证据包', b.get('承受力') == rl)
    check('行情侧不再反推目标价（旧版 1239 元/月的来源）',
          '目标价' not in b, f"残留键={[k for k in b if '目标价' in k]}")
    check('天花板只来自承受力上限',
          b.get('可承受月租上限') in (None, rl.get('盈亏平衡月租'), rl.get('回本达标月租上限')),
          f"{b.get('可承受月租上限')} / 口径={b.get('上限口径')}")
    check('天花板不高于盈亏平衡线',
          b.get('可承受月租上限') is None or b['可承受月租上限'] <= rl['盈亏平衡月租'],
          f"{b.get('可承受月租上限')} vs {rl.get('盈亏平衡月租')}")
    # 天花板是"最多能付"，不是"先出这个价"。旧措辞会教用户一开口就报底线。
    import re
    open_bid = [c for c in b['筹码'] if re.search(r'先出\s*[\d,]+', c)]
    check('筹码没有把天花板当开价报数字', not open_bid,
          (open_bid[0][:100] if open_bid else '无'))
    check('筹码明确天花板不是开价', any('天花板' in c and '不是"先出这个价"' in c
                                    for c in b['筹码']))
    check('报价超天花板时给出差额锚', any('缺口' in c for c in b['筹码']),
          next((c for c in b['筹码'] if '缺口' in c), '无')[:100])
    check('筹码含承受力上限', any('承受力上限' in c for c in b['筹码']))
    check('筹码含报价超线红线', any('已超盈亏平衡线' in c for c in b['筹码']))
    if bench:
        check('筹码强制转达可比性声明',
              any('可比性声明' in c and '不到商圈' in c for c in b['筹码']))
        check('筹码披露样本标题供 LLM 自判可比性',
              any('样本标题' in c for c in b['筹码']))
        check('报价远超上沿时归因于业态不同类而非"贵了N倍"',
              '不是同类铺子' in (b.get('价格位置') or ''), b.get('价格位置'))

    # 无承受力数据时绝不能退回行情价——这正是旧版荒谬目标价的产生路径
    b0 = negotiation_brief('宁波', '天一广场', 12000, 30, district='海曙')
    print(f"  [无承受力] 天花板={b0.get('可承受月租上限')}  口径={b0.get('上限口径')}")
    check('无承受力数据时不给天花板', b0.get('可承受月租上限') is None,
          str(b0.get('可承受月租上限')))
    check('无承受力数据时说明原因', '缺承受力数据' in (b0.get('上限口径') or ''),
          b0.get('上限口径'))

    print()
    print('=== 案例 E：PDF 章节（只验 HTML 生成，不出真 PDF）===')
    import ui.report_pdf as rp
    src = None
    # build_analysis_pdf 直接出字节，这里改为断言其内部拼装逻辑：用 monkeypatch 截获 html_doc
    captured = {}

    class FakePage:
        def set_content(self, html, wait_until=None):
            captured['html'] = html

        def pdf(self, **kw):
            return b'%PDF-fake'

    class FakeBrowser:
        def new_page(self):
            return FakePage()

        def close(self):
            pass

    class FakeChromium:
        def launch(self, **kw):
            return FakeBrowser()

    class FakePw:
        chromium = FakeChromium()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    try:
        import playwright.sync_api as sp
        sp.sync_playwright = lambda: FakePw()
        src = rp.build_analysis_pdf(r, interpretation='测试解读')
    except Exception as e:
        print(f'  (PDF 生成跳过: {e})')
    if captured.get('html'):
        h = captured['html']
        check('PDF 用红色否决横幅', 'score veto' in h)
        check('PDF 双轴陈述', '位置分：' in h and '综合结论：' in h)
        check('PDF 有租金临界点章节', '租金临界点' in h and '盈亏平衡月租' in h)
        check('PDF 有免租压力测试', '免租压力测试' in h)
        check('PDF 有三档情景区间章节', '三档情景区间' in h)
        check('PDF 盈利表标注中性档', '月净利估算（中性档）' in h)
        check('PDF 列出三项新增成本', all(k in h for k in ('月场地附加费', '月税', '月损耗')))
        check('PDF 页脚声明假设非实测数据', '假设区间，非实测数据' in h)
    else:
        print('  (未截获 HTML，跳过 PDF 断言)')

    print()
    print('=== 案例 F：客单价按「每单金额」校正后，天一广场 ¥12000 由否决翻为可行 ===')
    r3 = score_site('奶茶', LNG, LAT, 12000, ADDR, 30, investment=200000, staff=2,
                    brand=BRAND, price_ref=PRICE_REF)
    v3 = r3.get('veto') or {}
    rl3 = r3.get('rent_limits') or {}
    p3 = r3.get('profit') or {}
    print(f"  [月租 12000] total={r3['total']}  verdict={r3['verdict']}  否决={v3.get('触发')}  "
          f"月净利={p3.get('月净利估算')}  盈亏平衡月租={rl3.get('盈亏平衡月租')}")
    print(f"  dims={r3['dims']}")

    # 这条断言锁的是"客单价校正 + 口径"本身：按品类画像 ¥16 算，这个铺子更宽松；
    # 按品牌级每单金额 ¥11.4 算，流水下调 29%、月净利降到 ¥10,265（v6 uplift 后为 ¥12,688）。
    # 谁哪天把校正退回画像值、或把口径改回"单杯价当每单"，这两条就会红。
    pc3 = r3.get('客单价校正') or {}
    check('客单价按品牌级每单金额校正', pc3.get('校正客单价') == 11.4, str(pc3.get('校正客单价')))
    check('校正倍数与口径可追溯', pc3.get('校正倍数') == 1.4 and '蜜雪冰城' in (pc3.get('口径') or ''),
          str(pc3.get('口径'))[:60])
    check('单杯价与每单金额分开记录（防口径混用）',
          pc3.get('单杯价') == 7.0 and pc3.get('每单金额口径来源') == 'public_report',
          f"单杯价={pc3.get('单杯价')} 来源={pc3.get('每单金额口径来源')}")
    check('流水按校正后每单金额算', p3.get('客单价') == 11.4, str(p3.get('客单价')))
    check('证据里标了客单价来源', r3['evidence'].get('客单价来源') == '品牌级每单金额(公开/换算)',
          str(r3['evidence'].get('客单价来源')))
    check('校正出声（警告里有客单价）', any('客单价已按品牌级每单金额校正' in w for w in r3['warnings']))
    # 【本次修复的核心结论】**必须**与旧口径区分开：旧口径把高德单杯价 ¥7 当每单金额，
    # 低估流水约 1.7 倍，于是这个铺位在 ¥12000 被误判为"账算不过来"。
    # 改成每单金额 ¥11.4 后，月净利转正、结论翻为"推荐"。这条断言就是防回退的锚。
    check('修复后 ¥12000 不再误判否决（旧口径的错判锚）', v3.get('触发') is False, str(v3.get('原因')))
    # 【2026-09-16 口径变更】结论改为**以经营评分为准**（用户诉求是"能不能赚钱"）：
    #   同一份数据 地址评分 85.8（→"推荐"）× 经营评分（→各自的档位）⇒ 最终结论取经营档。
    #   旧断言断的正是"地址分说了算"的旧语义。
    #
    # 【2026-09-18 二次口径变更 v7：uplift 换成"品牌盲残差"，消双算】
    #   本案例结论由 v6 的"推荐"**回落**为"谨慎推荐"（与 v1 同档）。
    #   这不是回退 —— 恰恰是修掉了 v6 的**虚高**：v6 里蜜雪的 +19.0% 有 99%
    #   来自 own_S 的重复计入，而 own_S 已经通过 P 进过一次流水
    #   （scoring.py:701 进 P → 331 又乘 uplift）。零 API 证据见
    #   analysis/recalibrate_uplift_v3.py §2：Spearman(own_S, uplift) +0.6719 → +0.1531。
    #
    #   三口径对照（探针 _v7_probe.py，只改 UPLIFT['蜜雪冰城'] 一个数，其余全不动）：
    #     uplift   日单量参考  测算人数  净利率   回本    经营评分  结论        免租净利
    #     1.1343   291        3/2       10.31%  12.6月   70       谨慎推荐    ¥22,265
    #     1.1903   305        3/2       12.15%  11.0月   76       推荐        ¥24,688
    #     1.0018   257        2/2       11.71%  12.6月   74       谨慎推荐    ¥22,292
    #   ---- 距离口径换 **步行路网** 后（v8，2026-09-20）----
    #     v8        —          —         —       —       66       谨慎推荐    ¥20,425
    #   ⚠️ 上表前四行是**直线距离**口径的历史快照，不要拿它跟 v8 直接比量级；
    #      v8 这一行变化的原因见下面「经营评分」哨兵处的注释。
    #   ⚠️ 注意最后一行**不是笔误**：v7 流水比 v1 低 11.7%，但日单量 257 落到
    #      2 人产能（人均 140 单/天 × 2 = 280）之内 ⇒ 测算人数从 3 降到 2，
    #      少扣一个人工 ⇒ 净利反而略高于 v1。**净利不是流水的单调函数**，
    #      因为人工有一个"台阶"（见 docs/口径区间-价格弹性未标定.md）。
    #   ⚠️ 语义锚（上面那条"¥12000 未触发否决"）第三次未变，变的只有量级。
    #   ⚠️ 本节对 uplift 敏感这一性质没变；再动 uplift，下面三行还要整体重新标定。
    #   断言按"口径哨兵"定位（锁当前口径的快照），语义锚是上面那条，别把两者混为一谈。
    check('结论哨兵：本案例在 v7 口径下为「谨慎推荐」（v6 为"推荐"，v1 同为本档）',
          r3['verdict'] == '谨慎推荐', r3['verdict'])
    _b3 = r3.get('经营评分') or {}
    # 口径哨兵（映射见 scoring._score_one_profit / _lin_score）：
    #   v7（直线距离）：净利率 11.71% → 58.6 分；回本 12.6 月 → 97.5 分 ⇒ 0.6×58.6+0.4×97.5 ≈ 74.2 → **74**
    #   **v8（步行路网，2026-09-20）⇒ 66**
    #   ⚠️ 本哨兵**对距离口径敏感**：换步行路网后该点位 D×P 变化 → 流水/回本变 → 评分跟着变
    #      （同一批改动里"免租月净利"也从 ¥22,292 变到 ¥20,425，两行互为印证）。
    #      谁动了**距离口径**、成本结构、品牌系数或映射阈值，这行都会红。
    check('经营评分=66（净利率60% + 回本40% 的映射哨兵，**v8 步行路网口径**；v7 直线口径为 74）',
          _b3.get('分数') == 66, str(_b3.get('分数')))
    check('经营评分带三档区间', isinstance(_b3.get('区间'), list)
          and len(_b3['区间']) == 2 and _b3['区间'][0] <= _b3['区间'][1], str(_b3.get('区间')))
    check('经营评分口径写明权重与封顶', '60%' in (_b3.get('口径') or '')
          and '封顶' in (_b3.get('口径') or ''), (_b3.get('口径') or '')[:70])
    check('地址评分仍独立保留（双轴）', v3.get('位置分结论') == '推荐', str(v3.get('位置分结论')))
    check('两条租金临界点不再恒等',
          rl3.get('回本达标月租上限') is not None
          and rl3['回本达标月租上限'] < rl3['盈亏平衡月租'],
          f"{rl3.get('回本达标月租上限')} < {rl3.get('盈亏平衡月租')}")

    # 否决逻辑的**分界行为**：月租落在回本上限以内必须放行，超出必须否决。
    #
    # ⚠️ 这里刻意**不硬编码**具体月租。历史上此处写死 6000 元，那是"客单价按品类
    #    画像 ¥16"旧口径下的数；口径改成品牌级每单金额 ¥11.4 后回本上限变成
    #    ¥19,450，写死的数字就失效了（v6 uplift 后进一步变成 ¥21,900，v7 消双算后
    #    又回到 ¥19,450——**每换一次口径这个数就会动一次**，正好是"不该写死"的最好证明）。
    #    写死数字还有个更坏的毛病：把阈值挪到刚好能过的地方就能变绿，而不是暴露问题。
    #    所以改为从本引擎自己解出的临界点构造分界线**两侧**。
    #
    # ⚠️ 必须知情：base_daily=250 是**跨品牌混合**门店的中位日单量，换成品牌级
    #    每单金额后单量没有同步上调——低价品牌单量通常更高，因此这里的流水仍偏保守
    #    （见 docs/口径区间-价格弹性未标定.md）。故本节测的是"分界点两侧行为相反"，
    #    **不是**断言某个真实铺位盈亏。
    cap3 = rl3.get('回本达标月租上限')
    check('回本上限可解（下面两条断言依赖它）', isinstance(cap3, int) and cap3 > 0, str(cap3))
    cap3 = cap3 if isinstance(cap3, int) and cap3 > 0 else 0
    RENT_OK = max(50, cap3 - 50)      # 分界线内侧
    RENT_BAD = cap3 + 500             # 分界线外侧
    r4 = score_site('奶茶', LNG, LAT, RENT_OK, ADDR, 30, investment=200000, staff=2,
                    brand=BRAND, price_ref=PRICE_REF)
    v4 = r4.get('veto') or {}
    rl4 = r4.get('rent_limits') or {}
    pr4 = r4.get('profit') or {}
    print(f"  [月租 {RENT_OK:>5} 内侧] verdict={r4['verdict']}  否决={v4.get('触发')}  "
          f"月净利={pr4.get('月净利估算')}  回本={pr4.get('回本周期(月)')}月  "
          f"(盈亏平衡={rl4.get('盈亏平衡月租')}, 回本上限={rl4.get('回本达标月租上限')})")
    check(f'月租 {RENT_OK}（回本上限内）不触发否决', v4.get('触发') is False, str(v4.get('原因')))
    # 未否决时结论 = 经营结论（以经营评分为准）。这条租位净利率仅 2.9%、回本 23.8 个月，
    # 经营评分低 → "不建议"，正是新口径想表达的东西：位置不差，但这租金赚不到钱。
    check('未否决时结论=经营结论（以经营评分为准，不被地址分改写）',
          r4['verdict'] == (r4.get('经营评分') or {}).get('结论'),
          f"{r4['verdict']} vs {(r4.get('经营评分') or {}).get('结论')}")
    check('未触发时也给出安全垫数据', isinstance(rl4.get('盈亏平衡月租'), int))
    check('内侧铺子回本周期确实落在红线内（验语义，不只验触发位）',
          pr4.get('回本周期(月)') is not None and pr4['回本周期(月)'] <= PAYBACK_LIMIT_MONTHS,
          str(pr4.get('回本周期(月)')))
    b4 = negotiation_brief('宁波', '天一广场', RENT_OK, 30, district='海曙', affordability=rl4)
    check('可行铺子筹码是安全垫而非红线', any('承受力校验' in c for c in b4['筹码']),
          ' / '.join(b4['筹码'])[:80])

    # 分界线外侧必须否决——原测试只验了内侧，于是"把阈值挪到刚好能过"这个漏洞
    # 没有任何断言挡着（这正是它当初能悄悄失效的原因）。
    r4b = score_site('奶茶', LNG, LAT, RENT_BAD, ADDR, 30, investment=200000, staff=2,
                     brand=BRAND, price_ref=PRICE_REF)
    v4b = r4b.get('veto') or {}
    print(f"  [月租 {RENT_BAD:>5} 外侧] verdict={r4b['verdict']}  否决={v4b.get('触发')}")
    check(f'月租 {RENT_BAD}（超回本上限）必须触发否决', v4b.get('触发') is True,
          str(v4b.get('原因')))

    # 口径哨兵：锁住当前口径下的关键中间量。它不是"业务结论"，而是防漂移的快照——
    # 谁改了流水/成本结构，这行会红，提醒回来复核上面所有阈值类断言是否还成立。
    # ⚠️ 该值**随品牌 uplift 走**，且**不是流水的单调函数**（人工有台阶）：
    #     v1（蜜雪 1.1343）→ ¥22,265；v6（1.1903）→ ¥24,688；v7（1.0018）→ ¥22,292；
    #     v8 半程（2026-09-20，**只换距离口径**、uplift 还是 v7 的）→ ¥20,425；
    #     **v8 完整（2026-09-21，距离 + uplift 表都切到路网口径）→ ¥20,351**。
    #   ⚠️ 两跳要分开看，别混：
    #     · 22,292 → 20,425 是**距离口径**换的（该点位 D×P 随之变化），不是 uplift 变了；
    #     · 20,425 → 20,351 是 **UPLIFT 表切 v8** 换的（蜜雪 1.0018 → 1.0000，−0.18%，
    #       落在免租净利上约 −74 元）。量级很小，正说明大样本品牌在两个口径下都稳。
    #     v7 < v6 是流水下降；v7 > v1 是因为日单量落到 2 人产能内、少扣一个人工。
    #     改 uplift 就必须回来重标定这里与上面两条（三口径对照见本节顶部注释）。
    check('口径哨兵：免租月净利仍为 ¥20,351（**v8 完整口径：路网距离 + v8 UPLIFT**；'
          'v8 半程仅换距离为 ¥20,425、v7 直线口径为 ¥22,292、v6 为 ¥24,688、v1 为 ¥22,265）',
          rl3.get('免租月净利') == 20351, str(rl3.get('免租月净利')))
    # 差额锚只在"报价超承受力上限"时才出现。¥12000 修好口径后已可行（走的是安全垫分支，
    # 见上文 RENT_OK），所以这里改用外侧租金构造被否决场景，才能验到差额锚。
    b3 = negotiation_brief('宁波', '天一广场', RENT_BAD, 30, district='海曙', affordability=rl3)
    check('被否决铺子的筹码给出差额锚', any('谈判真正的锚是差额' in c for c in b3['筹码']))

    print()
    print('=== 案例 G：三档情景区间贯通 引擎→看板→兜底解读 ===')
    bands = r3.get('profit_bands') or {}
    iv = bands.get('区间') or {}
    for n in ('乐观', '中性', '保守'):
        b = bands.get(n) or {}
        print(f"  [{n}] 人数{b.get('人数')} 净利{b.get('月净利估算'):,} "
              f"净利率{(b.get('净利率') or 0):.1%} 回本{b.get('回本周期(月)')}月 "
              f"场地费{b.get('月场地附加费'):,} 税{b.get('月税'):,} 损耗{b.get('月损耗'):,}")
    print(f"  区间结论: {iv.get('结论')}")
    check('三档齐全', all(n in bands for n in ('乐观', '中性', '保守')))
    check('保守档净利低于乐观档',
          bands['保守']['月净利估算'] < bands['乐观']['月净利估算'],
          f"{bands['保守']['月净利估算']} < {bands['乐观']['月净利估算']}")
    # 中性档必须与单点 profit 完全一致，否则说明两条链路用了不同算法，区间就没有意义
    check('中性档与单点 profit 同口径',
          bands['中性']['月净利估算'] == p3['月净利估算'],
          f"{bands['中性']['月净利估算']} vs {p3['月净利估算']}")
    check('区间带非实测数据声明', '非实测数据' in (iv.get('口径') or ''))
    check('人数随情景按产能下限变化', bands['保守']['人数'] >= bands['乐观']['人数'],
          f"{bands['乐观']['人数']}→{bands['保守']['人数']}")
    # 产能警告的触发条件是"测算人数 > 申报人数"（scoring.py:863）。
    # ⚠️ v7 口径下本节案例（申报 2 人）中性档日单量 257，已落在 2 人产能
    #    （人均 140 单/天 ×2 = 280）之内 ⇒ 这条不变式在本案例上**自然测不到**了。
    #    不能把断言改成"不触发"——那等于把它废掉。改用**显式申报 1 人**的输入
    #    触发它，这样这条断言不再依赖 uplift 的数值，以后 uplift 再动也不会红。
    r1p = score_site('奶茶', LNG, LAT, 12000, ADDR, 30, investment=200000, staff=1,
                     brand=BRAND, price_ref=PRICE_REF)
    check('产能不可行警告已触发（申报人数低于测算下限时必须明说）',
          any('产能不可行' in w for w in r1p['warnings']),
          next((w for w in r1p['warnings'] if '产能不可行' in w), '无'))

    from ui.app_chainlit import build_analysis_dashboard
    dash = build_analysis_dashboard(r3)
    sr = dash.get('scenario_rows') or []
    pr = dict(dash.get('profit_rows') or [])
    print(f"  看板 scenario_rows {len(sr)} 行；profit_rows {len(pr)} 行")
    check('看板有三档区间行', len(sr) >= 5, f'{len(sr)} 行')
    check('看板补了三项新增成本', all(k in pr for k in ('月场地附加费', '月税', '月损耗')))
    check('看板补了净利率行', '净利率' in pr)
    check('看板卡片标注中性档', any('中性档' in c['label'] for c in dash['cards']),
          ' / '.join(c['label'] for c in dash['cards']))

    txt3 = rule_based_interpret(r3)
    check('兜底解读含三档区间', '三档情景区间' in txt3)
    check('兜底解读含非实测数据声明', '非实测数据' in txt3)

    print()
    print('=== 案例 H：每单金额校正的分支（公开/换算/失败）+ 校验参照组切换（monkeypatch，零 API）===')
    import engine.competitor_insight as ci

    def _pois(*specs):
        """specs: (门店名, 品牌, 人均)"""
        return [{'name': n, 'brand': b, 'cost': c, 'rating': 4.0, 'distance': 200,
                 'S': 1.0, 'opentime': '', 'groupbuy': 0, 'discount': 0, 'favorite': 0,
                 'photos': 0, 'tags': [], 'keytag': ''} for n, b, c in specs]

    def _ok(*specs):
        """取数成功的桩：返回 (pois, meta)。品牌价格校正是从 _ex 版本取数的。"""
        return (_pois(*specs),
                {'ok': True, 'cached': False, 'age': 0.0, 'info': 'OK',
                 'infocode': '10000', 'quota': False, 'tries': 1,
                 'fetched_at': '2026-09-15 10:00'})

    real_fetch = ci.fetch_competitor_pois_ex
    real_brand = ci.fetch_brand_pois
    # 默认把"A 级品牌定向搜索"打成**空结果**：本节 ②③④⑥ 测的是**周边采样**分支，
    # 若让定向补采真去打高德，既不确定、又会把 no_same_brand/underpowered 两个分支
    # 悄悄改成 ok。A 级本身单独在 ⑤b~⑤d 里测（也全部 monkeypatch，零 API）。
    _EMPTY_BRAND = lambda *a, **k: (                                       # noqa: E731
        [], {'ok': True, 'info': 'OK', 'infocode': '10000', 'quota': False,
             'tries': 1, 'count': 0, 'cached': False, 'fetched_at': '2026-09-15 10:00'})
    ci.fetch_brand_pois = _EMPTY_BRAND
    # ⚠️ 本案例把「有公开披露数据」和「无公开披露数据」两条路径分开测：
    #    蜜雪冰城有招股书每单金额 → 走 public_report 分支（**与取数成败无关**，
    #    接口挂了照样能校正）；一点点无公开数据 → 才走"高德单杯价 × 每单杯数"换算。
    #    历史版本把两者混在蜜雪一个品牌上测，加了公开数据后断言会失真。
    NO_PUB = '一点点'   # 真实连锁品牌、但无公开披露的单店每单金额
    try:
        # ① 未指定品牌 → 不校正
        ci.fetch_competitor_pois_ex = lambda *a, **k: _ok(('某奶茶', None, 17))
        x = ci.brand_price_reference(LNG, LAT, '奶茶', None)
        check('无品牌时不校正', x['校正客单价'] is None and '非加盟场景' in x['口径'], x['口径'])

        # ①b【有公开数据】蜜雪冰城：直接用公开每单金额，不看高德单杯价
        ci.fetch_competitor_pois_ex = lambda *a, **k: _ok(('蜜雪A', '蜜雪冰城', 7),
                                                          ('蜜雪B', '蜜雪冰城', 7))
        x = ci.brand_price_reference(LNG, LAT, '奶茶', '蜜雪冰城')
        check('有公开数据的品牌按每单金额校正', x['校正客单价'] == 11.4, str(x['校正客单价']))
        check('公开数据分支标记 public_report/ok',
              x['口径来源'] == 'public_report' and x['抓取状态'] == 'ok',
              f"{x['口径来源']} / {x['抓取状态']}")
        check('公开单杯价与高德实测互印证', '互为印证' in x['口径'], x['口径'][:80])

        # ②【无 A/B/C 三级数据】同品牌 0 家（高德没收录）+ 无披露 + 无第三方参考
        #   → 不校正，但要说清"没抓到"≠"没必要"。
        #   ⚠️ 自 2026-09-16 起 NO_PUB='一点点' 有了 **C 级**第三方参考（窄门 ¥15.05），
        #   若不禁用 C 级，这一支会被 C 级兜底接管、断言失真。故此处显式屏蔽 C 级，
        #   专门测"三级全无"的最坏路径；C 级本身在 ⑤e 里单独测。
        _real_ind_2 = ci.industry_price_reference
        ci.industry_price_reference = lambda *a, **k: None
        ci.fetch_competitor_pois_ex = lambda *a, **k: _ok(('古茗一号', '古茗', 15), ('古茗二号', '古茗', 15))
        x = ci.brand_price_reference(LNG, LAT, '奶茶', NO_PUB)
        check('三级数据全无时不校正且说明原因',
              x['校正客单价'] is None and x['证据'] is None and '没抓到' in x['口径'], x['口径'][:50])
        check('取数成功但 A/B/C 全无该品牌 → 状态标记 no_same_brand',
              x['抓取状态'] == 'no_same_brand' and x['来源'] == '实时',
              f"{x['抓取状态']} / {x['来源']}")
        check('no_same_brand 口径点明"也无第三方行业参考数据"',
              '也无第三方行业参考数据' in x['口径'], x['口径'][-40:])
        ci.industry_price_reference = _real_ind_2

        # ③ 同品牌仅 1 家 → 不校正（含除法分支，此前无任何测试覆盖）
        ci.fetch_competitor_pois_ex = lambda *a, **k: _ok((f'{NO_PUB}孤店', NO_PUB, 7),
                                                          ('奈雪', '奈雪的茶', 24))
        x = ci.brand_price_reference(LNG, LAT, '奶茶', NO_PUB)
        check('同品牌 1 家时不用噪声覆盖假设', x['校正客单价'] is None, str(x['校正客单价']))
        check('同品牌 1 家时仍把单杯价报出来并点明它≠每单金额',
              x['证据'] and x['证据']['同品牌人均中位'] == 7.0 and '1.7 倍' in x['口径'],
              x['口径'][:90])

        # ④ 同品牌 ≥2 家 → 单杯价 × 每单杯数 换算（中位 8 × 1.7 = 13.6）
        ci.fetch_competitor_pois_ex = lambda *a, **k: _ok((f'{NO_PUB}A', NO_PUB, 7),
                                                          (f'{NO_PUB}B', NO_PUB, 9),
                                                          ('奈雪', '奈雪的茶', 24))
        x = ci.brand_price_reference(LNG, LAT, '奶茶', NO_PUB)
        check('同品牌 ≥2 家时单杯价×每单杯数换算', x['校正客单价'] == 13.6, str(x['校正客单价']))
        check('校正倍数=画像÷换算每单', x['校正倍数'] == 1.18, str(x['校正倍数']))
        check('换算分支标记 amap_converted 且披露高估风险',
              x['口径来源'] == 'amap_converted' and '高估风险' in x['口径'], x['口径'][:80])
        check('正常校正时带出取数溯源', x['来源'] == '实时' and bool(x['取证时间']),
              f"{x['来源']} / {x['取证时间']}")

        # ④b 【本次修复的核心】取数失败（限流/配额）绝不能写成"附近没有该品牌"。
        # 旧实现把 status!=1 一律 return []，于是限流被写成
        # "周边 0 家同类门店里没抓到「一点点」…（高德未收录）"——一句假话。
        ci.fetch_competitor_pois_ex = lambda *a, **k: (
            [], {'ok': False, 'cached': False, 'age': 0.0,
                 'info': 'CUQPS_HAS_EXCEEDED_THE_LIMIT', 'infocode': '10021',
                 'quota': False, 'err': None, 'tries': 3,
                 'fetched_at': '2026-09-15 10:00'})
        x = ci.brand_price_reference(LNG, LAT, '奶茶', NO_PUB)
        check('限流时状态标记 fetch_failed', x['抓取状态'] == 'fetch_failed', str(x['抓取状态']))
        check('限流时不写"周边 0 家里没抓到"这种假结论',
              '0 家同类门店' not in x['口径'] and f'没抓到「{NO_PUB}」的人均' not in x['口径'],
              x['口径'][:70])
        check('限流时明确说不是"附近没有该品牌"',
              '不是"附近没有该品牌"' in x['口径'] and '限流' in x['口径'], x['口径'][:90])
        check('限流时说明已退避重试', '退避重试 3 次' in x['口径'], x['口径'][:80])
        check('限流时不给出校正值', x['校正客单价'] is None and x['证据'] is None,
              str(x['校正客单价']))

        # ④c 日配额耗尽 → 与瞬时限流区分（重试无意义，别让用户以为"高德没数据"）
        ci.fetch_competitor_pois_ex = lambda *a, **k: (
            [], {'ok': False, 'cached': False, 'age': 0.0,
                 'info': 'DAILY_QUERY_OVER_LIMIT', 'infocode': '10003',
                 'quota': True, 'err': None, 'tries': 1,
                 'fetched_at': '2026-09-15 10:00'})
        x = ci.brand_price_reference(LNG, LAT, '奶茶', NO_PUB)
        check('日配额耗尽时明确说是配额问题',
              '日调用配额已用尽' in x['口径'] and x['抓取状态'] == 'fetch_failed', x['口径'][:60])

        # ④d score_site 遇到取数失败（且无公开数据）时必须出声，不能沉默沿用品类画像
        r6 = score_site('奶茶', LNG, LAT, 12000, ADDR, 30, investment=200000, staff=2,
                        brand=NO_PUB,
                        price_ref=ci.brand_price_reference(LNG, LAT, '奶茶', NO_PUB))
        check('取数失败时 score_site 出声警告',
              any('未校正，且不是因为没有该品牌' in w for w in r6['warnings']),
              next((w for w in r6['warnings'] if '客单价' in w), '无')[:60])
        check('取数失败时流水仍按画像算（未静默改动）',
              r6['profit']['客单价'] == 16, str(r6['profit']['客单价']))
        check('取数溯源写进 evidence',
              (r6.get('客单价校正') or {}).get('抓取状态') == 'fetch_failed',
              str((r6.get('客单价校正') or {}).get('抓取状态')))

        # ④e 【公开数据的价值】取数同样失败，但品牌有公开每单金额 → 不降级、仍校正
        r6b = score_site('奶茶', LNG, LAT, 12000, ADDR, 30, investment=200000, staff=2,
                         brand='蜜雪冰城',
                         price_ref=ci.brand_price_reference(LNG, LAT, '奶茶', '蜜雪冰城'))
        check('取数失败但有公开数据 → 状态 public_only',
              (r6b.get('客单价校正') or {}).get('抓取状态') == 'public_only',
              str((r6b.get('客单价校正') or {}).get('抓取状态')))
        check('取数失败但有公开数据 → 仍按 ¥11.4 校正（不再退画像）',
              r6b['profit']['客单价'] == 11.4, str(r6b['profit']['客单价']))
        check('取数失败但有公开数据 → 口径说明"不受本次取数失败影响"',
              '不受本次取数失败影响' in (r6b.get('客单价校正') or {}).get('口径', ''),
              str((r6b.get('客单价校正') or {}).get('口径'))[:70])
        check('取数失败但有公开数据 → 校正仍出声且标"公开披露每单金额"',
              any('已按品牌级每单金额校正' in w and '公开披露每单金额' in w
                  for w in r6b['warnings']),
              next((w for w in r6b['warnings'] if '客单价' in w), '无')[:70])

        # ⑤ 校验参照组：给品牌 → 同品牌；不给 → 全品类。两者结论必须相反。
        # 样本按真实分布构造（天一广场实测：全品类中位 ¥17、蜜雪冰城 2 家均 ¥7），
        # 若随手只放 3 家店，全品类中位会等于同品牌中位，两个参照组算出同一个数，
        # 这条测试就退化成恒真、什么也没验证。
        pois = _pois(('蜜雪A', '蜜雪冰城', 7), ('蜜雪B', '蜜雪冰城', 7),
                     ('古茗', '古茗', 15), ('喜茶', '喜茶', 15), ('春莱', '春莱', 16),
                     ('一点点', '一点点', 17), ('LINLEE', 'LINLEE', 18),
                     ('茶百道', '茶百道', 19), ('茉莉奶白', '茉莉奶白', 19),
                     ('茉酸奶', '茉酸奶', 22), ('奈雪', '奈雪的茶', 24))
        a_brand = ci.analyze_competitors(pois, '奶茶', '蜜雪冰城')
        a_all = ci.analyze_competitors(pois, '奶茶', None)
        cb, ca = a_brand['客单价现实校验'], a_all['客单价现实校验']
        print(f"  同品牌参照组: {cb['参照组']} → {cb['判断']}（¥{cb['真实人均中位']}）")
        print(f"  全品类参照组: {ca['参照组']} → {ca['判断']}（¥{ca['真实人均中位']}）")
        check('给品牌时参照组是同品牌', '同品牌' in cb['参照组'], cb['参照组'])
        check('同品牌参照组判偏乐观', cb['判断'] == '偏乐观', cb['判断'])
        check('全品类参照组判基本吻合（即旧版的错误结论）', ca['判断'] == '基本吻合', ca['判断'])
        check('两个参照组结论相反——证明参照组选错会得出反向结论',
              cb['判断'] != ca['判断'], f"{cb['判断']} vs {ca['判断']}")

        # ⑥ score_site 在 n=1 时必须出"未校正但存疑"警告，不能沉默回退。
        # 必须重新打补丁到 n=1 的样本，否则用的是 ④ 残留的 ≥2 家数据。
        ci.fetch_competitor_pois_ex = lambda *a, **k: _ok((f'{NO_PUB}孤店', NO_PUB, 7),
                                                          ('奈雪', '奈雪的茶', 24))
        r5 = score_site('奶茶', LNG, LAT, 12000, ADDR, 30, investment=200000, staff=2,
                        brand=NO_PUB,
                        price_ref=ci.brand_price_reference(LNG, LAT, '奶茶', NO_PUB))
        check('n=1 时 score_site 出声警告未校正',
              any('客单价未校正但存疑' in w for w in r5['warnings']),
              next((w for w in r5['warnings'] if '客单价' in w), '无')[:60])
        check('n=1 时流水仍按画像算（未静默改动）',
              r5['profit']['客单价'] == 16, str(r5['profit']['客单价']))

        # ⑤b【A 级补采】周边 1km 采样里没抓到该品牌（这是 CoCo 在天一广场的真实处境：
        #     25 家里根本没有 CoCo）→ 自动改用**品牌定向搜索**补齐 → 正常换算。
        ci.fetch_competitor_pois_ex = lambda *a, **k: _ok(('古茗一号', '古茗', 15),
                                                          ('奈雪', '奈雪的茶', 24))
        ci.fetch_brand_pois = lambda *a, **k: (
            _pois((f'{NO_PUB}定向A', NO_PUB, 8), (f'{NO_PUB}定向B', NO_PUB, 10)),
            {'ok': True, 'info': 'OK', 'infocode': '10000', 'quota': False,
             'tries': 1, 'count': 2, 'cached': False, 'fetched_at': '2026-09-16 12:00'})
        x = ci.brand_price_reference(LNG, LAT, '奶茶', NO_PUB)
        check('A 级补采：周边无该品牌时用定向搜索补齐并正常换算',
              x['校正客单价'] == 15.3, f"{x['校正客单价']}（[8,10] 中位 9 × 1.7 = 15.3）")
        check('A 级补采标记 amap_targeted 与来源',
              x['口径来源'] == 'amap_targeted' and '定向补采' in (x['来源'] or ''),
              f"{x['口径来源']} / {x['来源']}")
        check('A 级补采在口径里写清补了几家', '补采 2 家' in x['口径'], x['口径'][:100])

        # ⑤c【A 级补采 n=1】仍然"显示但不生效"
        ci.fetch_brand_pois = lambda *a, **k: (
            _pois((f'{NO_PUB}独苗', NO_PUB, 9)),
            {'ok': True, 'info': 'OK', 'infocode': '10000', 'quota': False,
             'tries': 1, 'count': 1, 'cached': False, 'fetched_at': '2026-09-16 12:00'})
        x = ci.brand_price_reference(LNG, LAT, '奶茶', NO_PUB)
        check('A 级补采仍不足 2 家时只显示不生效',
              x['校正客单价'] is None and x['证据'] and x['证据']['同品牌人均中位'] == 9.0
              and x['抓取状态'] == 'underpowered',
              f"{x['校正客单价']} / {x['抓取状态']}")

        # ⑤d【A 级补采失败】定向搜索失败要如实写明，不能吞成"没有该品牌"
        ci.fetch_brand_pois = lambda *a, **k: (
            [], {'ok': False, 'info': 'CUQPS_HAS_EXCEEDED_THE_LIMIT', 'infocode': '10021',
                 'quota': False, 'err': None, 'tries': 3, 'cached': False,
                 'fetched_at': '2026-09-16 12:00'})
        x = ci.brand_price_reference(LNG, LAT, '奶茶', NO_PUB)
        check('A 级补采失败时如实写明原因（不吞成"没有该品牌"）',
              '品牌定向搜索也未取到' in x['口径'] and 'CUQPS' in x['口径'],
              x['口径'][:100])

        # ⑤e【C 级兜底】A 级（含定向补采）与 B 级都拿不到 → 退第三方行业参考。
        #     NO_PUB='一点点' 无公开披露，但 C 级表里有（窄门 ¥15.05/杯）。
        #  e-1：定向搜索**成功但确实没有该品牌** → 纯 C 级兜底 → 生效并分级标注
        ci.fetch_brand_pois = lambda *a, **k: (
            [], {'ok': True, 'info': 'OK', 'infocode': '10000', 'quota': False,
                 'tries': 1, 'count': 0, 'cached': False,
                 'fetched_at': '2026-09-16 12:00'})
        x = ci.brand_price_reference(LNG, LAT, '奶茶', NO_PUB)
        _exp = round(15.05 * ci.UNIT_PER_ORDER, 2)
        check('C 级兜底：A/B 均无时用第三方行业参考换算并生效',
              x['校正客单价'] is not None and abs(x['校正客单价'] - _exp) < 0.02
              and x['单杯价'] == 15.05,
              f"{x['校正客单价']}（期望 ≈{_exp} = 15.05×{ci.UNIT_PER_ORDER}）")
        check('C 级分级隔离：口径来源单列 industry_estimate、抓取状态 industry_ref',
              x['口径来源'] == 'industry_estimate' and x['抓取状态'] == 'industry_ref',
              f"{x['口径来源']} / {x['抓取状态']}")
        check('C 级必须写明"行业参考，非披露非实测"',
              '行业参考' in x['口径'] and '非我实测' in x['口径']
              and '不与 A/B 级披露值混用' in x['口径'],
              x['口径'][-90:])
        check('C 级不与 A/B 级口径混用（来源≠public_report/amap_*）',
              x['口径来源'] not in ('public_report', 'amap_targeted', 'amap_converted')
              and not x.get('证据'),
              str(x['口径来源']))

        #  e-2：A 级是**瞬时限流**（可重试）而 C 级可用 → C 级生效但不得抹平限流事实
        ci.fetch_brand_pois = lambda *a, **k: (
            [], {'ok': False, 'info': 'CUQPS_HAS_EXCEEDED_THE_LIMIT', 'infocode': '10021',
                 'quota': False, 'err': None, 'tries': 3, 'cached': False,
                 'fetched_at': '2026-09-16 12:00'})
        x = ci.brand_price_reference(LNG, LAT, '奶茶', NO_PUB)
        check('C 级兜底不抹平"瞬时限流"事实（提示可重试）',
              x['校正客单价'] is not None and '瞬时限流' in x['口径']
              and '重试' in x['口径'],
              x['口径'][:120])

        #  e-3：C 级也没有 → 如实回落 no_same_brand（并说明三级都没有）
        _real_ind = ci.industry_price_reference
        ci.industry_price_reference = lambda *a, **k: None
        x = ci.brand_price_reference(LNG, LAT, '奶茶', NO_PUB)
        check('三级都取不到时回落 no_same_brand 且口径写明"C 级也无"',
              x['校正客单价'] is None and x['抓取状态'] == 'no_same_brand'
              and '也无第三方行业参考数据' in x['口径'],
              f"{x['校正客单价']} / {x['抓取状态']}")
        ci.industry_price_reference = _real_ind

        #  e-4：C 级在"underpowered(n=1)"里只作**交叉核对**，不参与换算
        ci.fetch_brand_pois = lambda *a, **k: (
            _pois((f'{NO_PUB}独苗', NO_PUB, 9)),
            {'ok': True, 'info': 'OK', 'infocode': '10000', 'quota': False,
             'tries': 1, 'count': 1, 'cached': False, 'fetched_at': '2026-09-16 12:00'})
        x = ci.brand_price_reference(LNG, LAT, '奶茶', NO_PUB)
        check('n=1 时 C 级只作交叉核对、不生效',
              x['校正客单价'] is None and x['抓取状态'] == 'underpowered'
              and '另有第三方行业参考' in x['口径'],
              x['口径'][-90:])
    finally:
        ci.fetch_competitor_pois_ex = real_fetch
        ci.fetch_brand_pois = real_brand

    print()
    print('=== 案例 I：经营评分（"能不能赚钱"）的边界口径 + 展示层改名 ===')
    from ui.app_chainlit import build_analysis_dashboard

    # ① 一票否决 → 分数封顶 ≤59（不允许"位置好 + 经营高分"自相矛盾）
    bizA = r.get('经营评分') or {}
    print(f"  [否决铺] 地址评分={r['total']} 经营评分={bizA.get('分数')} "
          f"封顶={bizA.get('一票否决封顶')} 结论={bizA.get('结论')} 区间={bizA.get('区间')}")
    check('否决时经营评分封顶 ≤59', bizA.get('分数') is not None and bizA['分数'] <= 59,
          str(bizA.get('分数')))
    check('否决标记写入经营评分', bizA.get('一票否决封顶') is True)
    check('否决时经营结论不是"推荐/谨慎推荐"', bizA.get('结论') in ('不建议优先选择', '不建议'),
          str(bizA.get('结论')))

    # ② 未提供月租 → **不出分**（不猜），并说明原因；结论退回地址评分
    rnr = score_site('奶茶', LNG, LAT, None, ADDR, 30, investment=200000, staff=2,
                     brand=BRAND, price_ref=PRICE_REF)
    bnr = rnr.get('经营评分') or {}
    print(f"  [无月租] 分数={bnr.get('分数')} 原因={bnr.get('不可得原因')} 结论={rnr['verdict']}")
    check('无月租时经营评分不出分', bnr.get('分数') is None, str(bnr.get('分数')))
    check('无月租时说明原因（不猜）', '缺月租' in (bnr.get('不可得原因') or ''),
          bnr.get('不可得原因'))
    check('无月租时结论退回地址评分结论',
          rnr['verdict'] == (rnr.get('veto') or {}).get('地址结论'),
          f"{rnr['verdict']} vs {(rnr.get('veto') or {}).get('地址结论')}")

    # ③ 未提供面积 → 无经营测算 → 同样不出分
    rna = score_site('奶茶', LNG, LAT, 12000, ADDR, None, investment=200000, staff=2,
                     brand=BRAND, price_ref=PRICE_REF)
    bna = rna.get('经营评分') or {}
    check('无面积时经营评分不出分', bna.get('分数') is None, str(bna.get('分数')))

    # ④ 展示层：「综合评分」→「地址评分」，并新增「经营评分」卡；结论卡注明口径
    dA = build_analysis_dashboard(r3)
    labels = [c['label'] for c in dA['cards']]
    check('看板有「地址评分」卡（原综合评分改名）', any('地址评分' in l for l in labels), ' / '.join(labels))
    check('看板有「经营评分」卡', any('经营评分' in l for l in labels), ' / '.join(labels))
    check('看板结论卡注明以经营评分为准', any('以经营评分为准' in l for l in labels), ' / '.join(labels))
    check('看板 evidence 带经营评分口径',
          any('经营评分' in str(x[0]) for x in (dA.get('evidence_rows') or [])),
          ' / '.join(str(x[0]) for x in (dA.get('evidence_rows') or [])))
    check('看板暴露 biz 字段供历史摘要用',
          dA.get('biz') == (r3.get('经营评分') or {}).get('分数'), str(dA.get('biz')))

    print()
    print('=' * 60)
    if FAIL:
        print(f'共 {len(FAIL)} 项 FAIL: ' + ' / '.join(FAIL))
        sys.exit(1)
    print('全部 PASS')


if __name__ == '__main__':
    main()
