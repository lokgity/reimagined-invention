# -*- coding: utf-8 -*-
"""store_diagnosis.py —— 已开店经营诊断（2026-09-15 新增，填「零入口」缺口）
=============================================================================
背景：全项目此前**没有任何"存量店"入口**——`score_site` 是选址前的**预估**
（用 Huff 引力模型估流水），而已经开起来的店**知道自己真实流水**。
它需要的不是"估"，是"拆"：成本结构是否合理、毛利率多少、
流水还能跌多久才亏、跟同品牌公开水平比差在哪。

与选址测算的根本区别（也是它在专家体系里的"唯一性"）：

| | 选址测算 score_site | 本模块 diagnose_existing_store |
|---|---|---|
| 流水 | **模型估**（Huff，含未标定的弹性假设） | **用户自报**，不估 |
| 位置 | 待定，需算位置分 | 已定，只做经营拆解 |
| 回答 | 能不能开、租金上限多少 | 现在哪里不对、还有多少缓冲 |

设计原则（与项目"不编数据"铁律一致）：
1. **不估流水**：`monthly_revenue` 由用户自报；本模块只做拆解与对标，不产生新假设。
   所以选址侧那个"价格—单量弹性未标定"的不确定性，在这里**根本不存在**。
2. **口径可追溯**：毛利率用**产品口径**（只扣物料与损耗，外卖抽成单列为渠道费用），
   理由见 `utilities.estimate_profit` 的 docstring 与
   `docs/经营测算口径与已开店诊断.md`。
3. **对标只用公开数据**：品牌基准来自 `brand_store_metrics.csv`
   （招股书/年报口径）。**没有公开数据的品牌不给基准**，不编。
4. **安全边际用引擎自己的模型解**，不引入外部经验阈值——这样它和
   `scoring.solve_rent_limits` 能互相校验（见 verify_store_diagnosis.py 的自洽断言）。

用法：
    from engine.store_diagnosis import diagnose_existing_store
    r = diagnose_existing_store('奶茶', 80000, 12000, area_m2=30, city='宁波',
                                staff=2, brand='蜜雪冰城')
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.utilities import (estimate_profit, get_material_ratio,
                              get_delivery_ratio, COMMISSION_RATE)

# 毛利率口径标识（写进输出，便于上游/前端原样转达，避免二次解释走样）
GROSS_MARGIN_CALIBER = '产品口径（流水 − 物料 − 损耗）；不含外卖抽成/人工/租金'


def _to_float(v):
    """把可能带单位/区间/空值的公开数据字段转成 float；转不了返回 None。

    例：奈雪的「单店日均GMV元」是 '6800~8900' 这种区间字符串——
    不能猜一个中位数当基准（那是编数据），所以直接判为不可用。
    """
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(',', '')
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def brand_benchmark(brand, category=None):
    """取品牌的**公开单店经营基准**（元/月），识别不出或无收录 → None。

    只做一件事：把 brand_store_metrics.csv 里的「单店日均 GMV」× 30 换成年月基准。
    数据来自招股书/年报，期间见返回值的「期间」字段——**披露期不同口径不同**，
    上游转达时必须带出期间，不能当成"当前水平"。

    返回 dict(品牌, 基准月流水, 日均GMV, 期间, 门店数, 来源, 口径) 或 None。
    """
    from engine.brands import brand_store_metrics
    m = brand_store_metrics(brand)
    if not m:
        return None
    gmv = _to_float(m.get('单店日均GMV元'))
    if not gmv:
        return None
    row = {
        '品牌': m.get('品牌') or brand,
        '日均GMV': gmv,
        '基准月流水': round(gmv * 30),
        '期间': m.get('期间') or '—',
        '门店数': m.get('门店数'),
        '来源': m.get('数据来源') or '公开披露',
        '口径': '品牌级单店日均 GMV × 30；**含堂食+外卖的全渠道零售额**',
        '注意': ('披露期与当前可能不同，且是**品牌平均**而非同商圈同面积可比店，'
                 '只能判断量级，不能当业绩考核线'),
    }
    return row


def diagnose_existing_store(category, monthly_revenue=None, monthly_rent=0,
                            area_m2=30, city='宁波', staff=None, investment=None,
                            brand=None, scenario='中性', price=None,
                            daily_orders=None):
    """已开店经营诊断：拆成本、算毛利、算安全边际、跟品牌公开基准对标。

    参数
    ----
    monthly_revenue : 用户自报的**实际月流水**（元）。必填其一：
                      也可给 daily_orders，则按 `daily_orders × price × 30` 折月。
    monthly_rent    : 实际月租金（元）
    area_m2 / city  : 实际面积 / 城市（决定水电与人工行情）
    staff           : 实际用工人数；不填按品类默认
    investment      : 已投入的前期资金（元）；不填按品牌政策或通用估算（影响摊销）
    brand           : 加盟品牌名；有公开数据时用于对标
    price           : 每单金额（元）；不填用品类画像
    daily_orders    : 实际日单量（当 monthly_revenue 缺失时用它折算）
    scenario        : 成本假设档（乐观/中性/保守），默认中性

    返回
    ----
    dict：成本拆解 / 毛利率（三种口径）/ 净利 / 安全边际 / 租金余量 / 品牌对标 / 诊断文本

    异常
    ----
    流水与日单量都拿不到、或流水 ≤ 0 → ValueError（不静默返回空壳，
    否则上层会把它当成"诊断完成"）。
    """
    if monthly_revenue is None:
        if daily_orders and price:
            monthly_revenue = daily_orders * price * 30
        else:
            raise ValueError('需要 monthly_revenue（实际月流水），'
                             '或同时给出 daily_orders 与 price')
    try:
        monthly_revenue = float(monthly_revenue)
    except (TypeError, ValueError):
        raise ValueError(f'月流水不是数字：{monthly_revenue!r}')
    if monthly_revenue <= 0:
        raise ValueError(f'月流水必须为正：{monthly_revenue!r}')

    prof = estimate_profit(category, area_m2, city, monthly_rent,
                           investment=investment, staff=staff,
                           sales_est=monthly_revenue, brand=brand,
                           price=price, scenario=scenario)

    # ---- 变动成本率 v：跟着流水一起变的那部分（物料/损耗/外卖抽成/场地附加/税）----
    v = (prof['物料占比'] + prof['损耗率']
         + prof['外卖占比'] * prof['外卖抽成率']
         + prof['场地附加费率'] + prof['税负率'])
    # ---- 固定成本 F：不随流水变的部分（租金/人工/水电/摊销/品牌费/杂费）----
    f_fixed = (prof['月租金'] + prof['月人工'] + prof['月水电']
               + prof['月摊销'] + prof['月品牌费'] + prof['月杂费'])

    bep_sales = None
    margin_amt = margin_rate = None
    bep_rent = None
    if v < 1:
        bep_sales = f_fixed / (1 - v)
        margin_amt = monthly_revenue - bep_sales
        margin_rate = margin_amt / monthly_revenue
        # 令净利 = 0 解出租金上限：流水×(1−v) 减去「除租金外的固定成本」
        bep_rent = monthly_revenue * (1 - v) - (f_fixed - prof['月租金'])

    # ---- 与 scoring 的租金临界点互相校验（同一模型，理应一致到二分取整精度）----
    rent_limits = None
    try:
        from engine.scoring import solve_rent_limits
        rent_limits = solve_rent_limits(category, area_m2, city, prof['前期投入'],
                                        prof['人数'], monthly_revenue, brand, price=price)
    except Exception:  # 纯本地二分，理论上不会抛；真抛了不能连带拖垮诊断
        rent_limits = None

    bench = brand_benchmark(brand) if brand else None
    compare = None
    if bench:
        ratio = monthly_revenue / bench['基准月流水']
        compare = {
            '基准月流水': bench['基准月流水'],
            '你/基准': round(ratio, 3),
            '期间': bench['期间'],
            '来源': bench['来源'],
            '口径': bench['口径'],
            '注意': bench['注意'],
        }

    diag = _diagnose_texts(prof, monthly_revenue, margin_rate, bep_sales,
                          bep_rent, monthly_rent, compare)

    return {
        '品类': category,
        '品牌': brand,
        '情景': prof['情景'],
        '输入': {
            '实际月流水': monthly_revenue,
            '实际月租金': monthly_rent,
            '面积': area_m2,
            '城市': city,
            '人数': prof['人数'],
            '人数口径': prof['人数口径'],
        },
        '成本拆解': {
            '月物料': prof['月物料成本'],
            '月损耗': prof['月损耗'],
            '月外卖抽成': prof['月外卖抽成'],
            '月人工': prof['月人工'],
            '月水电': prof['月水电'],
            '月租金': prof['月租金'],
            '月场地附加费': prof['月场地附加费'],
            '月税': prof['月税'],
            '月摊销': prof['月摊销'],
            '月品牌费': prof['月品牌费'],
            '月杂费': prof['月杂费'],
            # ⚠️ 同名不同义：utilities 的 '月固定成本'（已废弃别名）值是**总成本**，
            #    这里是真的固定成本（不含物料/损耗/外卖抽成/场地/税）。两者并列输出。
            '月固定成本': round(f_fixed),
            '月成本合计': prof['月成本合计'],
        },
        '变动成本率': round(v, 4),
        # 三种毛利口径并列——只看一个会误导（见模块 docstring）
        '毛利率': prof['毛利率'],
        '毛利率口径': GROSS_MARGIN_CALIBER,
        '外卖抽成占流水比': prof['外卖抽成占流水比'],
        '扣渠道后毛利率': prof['扣渠道后毛利率'],
        '净利率': prof['净利率'],
        '月净利': prof['月净利估算'],
        '盈亏平衡月流水': round(bep_sales) if bep_sales is not None else None,
        '安全边际额': round(margin_amt) if margin_amt is not None else None,
        '安全边际率': round(margin_rate, 4) if margin_rate is not None else None,
        '安全边际说明': ('流水跌到该比例以内仍不亏损；为负说明当前已在亏损'
                     if margin_rate is not None else '变动成本率 ≥ 100%，卖得越多亏得越多'),
        '盈亏平衡月租': round(bep_rent) if bep_rent is not None else None,
        '租金余量': round(bep_rent - monthly_rent) if bep_rent is not None else None,
        '租金临界点(引擎二分)': rent_limits,
        '品牌对标': compare,
        '品牌基准明细': bench,
        # 品牌特有的成本提示（2026-09-18 新增，起因：瑞幸按月毛利阶梯分成且
        # 物料率 36% ≠ 奶茶 32%）。**必须随结论一起出去** —— 不说就等于
        # 静默给了一份偏乐观的测算。
        '品牌成本提示': _brand_cost_notes(brand),
        '诊断': diag,
        '局限': _brand_cost_notes(brand) + [
            '成本率（物料占比/外卖占比/场地附加/税/损耗）是**假设区间不是实测**，'
            '与选址侧共用同一套假设；用户若有真实账目，应把这些率替换为实测值。',
            '品牌基数是**品牌平均**且披露期不同，只判断量级，不是业绩考核线。',
            '不含开业初期的爬坡期差异，也不含一次性损失（如装修返工）。',
        ],
    }


def _brand_cost_notes(brand):
    """该品牌特有的、**必须随结论一起说出口**的成本/资质提示。

    2026-09-18 新增。起因：瑞幸的「门店月毛利阶梯分成」是品牌方成本，
    但本项目未建模（它是变动成本，塞进 yearly_fee 会算错），
    而它的物料率 36% 也与奶茶品类级 32% 不同 —— 这两件事不说出来，
    就等于静默地把一份偏乐观的测算当成结论交付。
    任何异常都吞掉返回 []：宁可不提示，也不能让诊断整体崩掉。
    """
    if not brand:
        return []
    try:
        from engine.brands import get_franchise_info
        return list((get_franchise_info(brand) or {}).get('cost_notes') or [])
    except Exception:
        return []


def _diagnose_texts(prof, revenue, margin_rate, bep_sales, bep_rent, rent, compare):
    """把数字翻成几条**有依据**的诊断，不产营销玄学。"""
    out = []

    gm = prof['毛利率']
    if gm is not None:
        out.append(f'毛利率 {gm:.1%}（产品口径：扣物料与损耗）；'
                   f'外卖抽成再吃掉流水的 {prof["外卖抽成占流水比"]:.1%}，'
                   f'扣渠道后 {prof["扣渠道后毛利率"]:.1%}')

    if margin_rate is not None:
        if margin_rate < 0:
            out.append(f'**当前是亏损的**：流水 {revenue:,.0f} 元低于盈亏平衡的 '
                       f'{bep_sales:,.0f} 元，缺口 {bep_sales - revenue:,.0f} 元/月')
        elif margin_rate < 0.10:
            out.append(f'安全边际仅 {margin_rate:.1%}——流水再跌 '
                       f'{abs(bep_sales - revenue):,.0f} 元就转到亏损，缓冲很薄')
        elif margin_rate < 0.25:
            out.append(f'安全边际 {margin_rate:.1%}，属正常偏紧')
        else:
            out.append(f'安全边际 {margin_rate:.1%}，抗波动能力较强')

    if bep_rent is not None and rent:
        gap = bep_rent - rent
        if gap < 0:
            out.append(f'租金已越过临界：实际 {rent:,.0f} 元 > 可承受 '
                       f'{bep_rent:,.0f} 元，超 {abs(gap):,.0f} 元/月——'
                       f'首要动作是谈租或谈分担，而不是投推广')
        else:
            out.append(f'租金余量 {gap:,.0f} 元/月（实际 {rent:,.0f} / 可承受 '
                       f'{bep_rent:,.0f}）')

    if compare:
        r = compare['你/基准']
        if r < 0.7:
            out.append(f'月流水只有该品牌公开单店基准的 {r:.0%}'
                       f'（基准 ¥{compare["基准月流水"]:,}/月，{compare["期间"]}）——'
                       f'差距明显，优先排查位置客流与出杯效率，而不是先加推广预算')
        elif r < 1.0:
            out.append(f'月流水约为该品牌公开基准的 {r:.0%}，处于基准下方')
        else:
            out.append(f'月流水达到/超过该品牌公开基准的 {r:.0%}——'
                       f'经营面本身没问题，瓶颈更可能在成本结构或租金')

    if not out:
        out.append('数据不足，未能形成诊断')
    return out


if __name__ == '__main__':
    r = diagnose_existing_store('奶茶', 80000, 12000, area_m2=30, city='宁波',
                                staff=2, brand='蜜雪冰城')
    print('=== 已开店诊断自检（奶茶 月流水 8 万 月租 1.2 万 30㎡ 宁波 2 人 蜜雪）===')
    print(f'毛利率 {r["毛利率"]:.1%}→扣渠道后 {r["扣渠道后毛利率"]:.1%}；'
          f'净利率 {r["净利率"]:.1%}')
    print(f'盈亏平衡月流水 ¥{r["盈亏平衡月流水"]:,}；安全边际率 {r["安全边际率"]:.1%}')
    print(f'盈亏平衡月租 ¥{r["盈亏平衡月租"]:,}；租金余量 ¥{r["租金余量"]:,}')
    for t in r['诊断']:
        print('  -', t)
