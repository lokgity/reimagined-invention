# -*- coding: utf-8 -*-
"""
utilities.py —— 浙江省水电标准数据与成本测算
==============================================
基于公开政策数据（2026年浙江新版工商业分时电价 + 各市非居民水价），
提供:
- 各地市商业电价（分时 + 一口价）
- 各地市商业水价（含污水处理费）
- 按面积/品类估算月水电成本
- 盈利测算（日均流水需求、回本周期参考）

数据说明（答辩必讲）:
- 电价为2026年7月浙江新版工商业分时电价政策框架下的参考值，
  具体单价以国网浙江省电力公司当月《代理工商业用户购电价格公告》为准
- 水价为各市非居民用水参考价，以当地供水公司公告为准
- 用途: 商铺经营成本估算的参考，非精确账单

数据来源:
- 浙江省能源局 2026-07 新版工商业分时电价政策
- 国网浙江省电力公司代理购电价格公告
- 各市发改/供水公司非居民用水价格
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ---------------------------------------------------------------
# 1. 浙江工商业电价（2026年新版分时电价，参考值）
# ---------------------------------------------------------------
# 单位: 元/千瓦时。尖峰/高峰/平/谷/深谷为政策浮动比例下的一般工商业参考价
# 政策要点(2026-07-01 起):
#   - 8:00-11:00 平时段; 16:00-23:00 高峰(夏冬季含18:00-22:00尖峰)
#   - 午间低谷延长至3小时; 节假日9:00-15:00深谷(电价2折)
#   - 一般工商业用户可选"一口价"(不执行分时), 12个月内不变
ELECTRICITY = {
    # 参考均价（一般工商业, 含基本电费摊分, 元/千瓦时）
    '参考均价': 0.85,   # 一般工商业综合参考价
    '一口价': 0.95,     # 不执行分时的一口价参考（略高于均价）
    '分时': {
        '尖峰': 1.35,   # 夏冬季 18:00-22:00
        '高峰': 1.10,   # 16:00-18:00, 22:00-23:00
        '平段': 0.85,   # 8:00-11:00, 13:00-16:00(冬) 等
        '低谷': 0.45,   # 午间低谷(11:00-14:00) + 23:00-8:00
        '深谷': 0.17,   # 节假日 9:00-15:00（约2折）
    },
}

# ---------------------------------------------------------------
# 2. 各市商业水价（非居民用水, 含污水处理费, 元/吨）
# ---------------------------------------------------------------
# 参考值: 水费(3.0-4.0) + 污水处理费(1.5-1.7) ≈ 4.5-5.7 元/吨
WATER = {
    '杭州': 5.20,   # 非居民用水约3.5 + 污水1.7
    '宁波': 5.00,
    '温州': 4.80,
    '嘉兴': 4.70,
    '湖州': 4.70,
    '绍兴': 4.80,
    '金华': 4.60,
    '衢州': 4.50,
    '舟山': 5.10,
    '台州': 4.80,
    '丽水': 4.50,
    '默认': 4.80,
}


def get_water_price(city: str) -> float:
    """按城市取商业水价(元/吨), 未匹配取默认"""
    for key, price in WATER.items():
        if key in city or city in key:
            return price
    return WATER['默认']


def get_electricity_price(mode='一口价'):
    """取电价参考(元/千瓦时)。mode: 一口价/分时均价/尖峰/高峰/平段/低谷/深谷"""
    if mode == '一口价':
        return ELECTRICITY['一口价']
    if mode == '分时均价':
        return ELECTRICITY['参考均价']
    return ELECTRICITY['分时'].get(mode, ELECTRICITY['一口价'])


# ---------------------------------------------------------------
# 3. 月度水电成本估算
# ---------------------------------------------------------------
# 各品类单位面积月用电/用水强度（参考值, 元/㎡·月 或 吨/㎡·月）
# 来源: 行业经验参考量级
CATEGORY_UTILITY_INTENSITY = {
    '奶茶': {'用电': 45, '用水': 1.2},    # 冷饮设备+制冰机 耗电耗水
    '甜品': {'用电': 55, '用水': 0.8},    # 烘焙设备
    '早餐': {'用电': 50, '用水': 1.5},    # 蒸煮设备
    '便利店': {'用电': 35, '用水': 0.4},  # 冷柜为主
    '默认': {'用电': 40, '用水': 0.8},
}


def estimate_monthly_utility(category, area_m2, city, elec_mode='一口价'):
    """估算月水电成本: (电费, 水费, 合计)
    area_m2: 商铺面积(平方米)
    电费 = 面积 × 单位面积月用电量(kWh) × 电价
    水费 = 面积 × 单位面积月用水量(吨) × 水价
    """
    intensity = CATEGORY_UTILITY_INTENSITY.get(category, CATEGORY_UTILITY_INTENSITY['默认'])
    elec_price = get_electricity_price(elec_mode)
    water_price = get_water_price(city)

    monthly_kwh = max(area_m2, 10) * intensity['用电']
    monthly_ton = max(area_m2, 10) * intensity['用水']

    elec_cost = monthly_kwh * elec_price
    water_cost = monthly_ton * water_price
    return {
        '城市': city,
        '面积': area_m2,
        '品类': category,
        '电价(元/度)': elec_price,
        '月用电(kWh)': round(monthly_kwh),
        '电费(元/月)': round(elec_cost),
        '水价(元/吨)': water_price,
        '月用水(吨)': round(monthly_ton, 1),
        '水费(元/月)': round(water_cost),
        '水电合计(元/月)': round(elec_cost + water_cost),
        '电价模式': elec_mode,
    }


# ---------------------------------------------------------------
# 4. 盈利测算
# ---------------------------------------------------------------
# 浙江省 2024 年最低工资标准（元/月）——仅作法律底线参考，
# 实际用工成本见下方 MARKET_WAGE（2026-09-14 修正: 此前按最低工资算
# 人工，严重低估真实成本）
MIN_WAGE = {
    '杭州': 2490, '宁波': 2490, '温州': 2490,
    '嘉兴': 2260, '湖州': 2260, '绍兴': 2260, '金华': 2260,
    '衢州': 2260, '舟山': 2260, '台州': 2260, '丽水': 2260,
    '默认': 2260,
}

# 市场实际月薪（元/月/人，餐饮零售店员口径，2026 年浙江招聘行情参考：
# 智联/BOSS 直聘茶饮店员月薪区间 4000-5500，取城市中位偏保守值）
MARKET_WAGE = {
    '杭州': 4800, '宁波': 4500, '温州': 4300,
    '嘉兴': 4200, '湖州': 4100, '绍兴': 4200, '金华': 4100,
    '衢州': 3900, '舟山': 4200, '台州': 4100, '丽水': 3900,
    '默认': 4200,
}

# 雇主承担的社保+公积金负担（占工资比例，浙江企业五险雇主部分约 26-30%）
SOCIAL_RATE = 0.28

# 外卖占月流水比例（茶饮类外卖占比高；便利店很低）
DELIVERY_RATIO = {'奶茶': 0.35, '甜品': 0.30, '早餐': 0.25, '便利店': 0.10, '默认': 0.30}

# 外卖平台综合抽成（佣金+配送服务费，美团/饿了么 2026 年行情 20-25%）
COMMISSION_RATE = 0.22

# 前期投入（装修+设备+转让费）摊销月数：按常见 3 年租约摊销
AMORTIZE_MONTHS = 36

# 各品类默认运营人数（用户不指定时使用）
DEFAULT_STAFF = {'奶茶': 2, '甜品': 2, '早餐': 2, '便利店': 1, '默认': 2}

# 物料/原料采购成本占月流水比例（按市面行情参考值）
# 餐饮类为食材成本占比，便利店为商品进销成本占比（COGS）
MATERIAL_RATIO = {'奶茶': 0.32, '甜品': 0.38, '早餐': 0.42, '便利店': 0.75, '默认': 0.40}

# 每月固定杂项（元）：证照摊销/办公耗材/小额维修/宽带等不随流水走的开销。
# 2026-09-14 由 2500 下调至 1200 —— 原先这里塞了"平台推广通/物料损耗"，
# 但三档情景已把场地附加费(含物业费/推广费)与损耗率拆成按流水计费的显式项，
# 再按 2500 收就是同一笔钱算两遍。
MISC_MONTHLY = 1200


def get_min_wage(city: str) -> int:
    """按城市取最低工资标准（元/月）——法律底线参考"""
    for key, wage in MIN_WAGE.items():
        if key in city or city in key:
            return wage
    return MIN_WAGE['默认']


def get_market_wage(city: str) -> int:
    """按城市取市场实际月薪（元/月/人，不含雇主社保）"""
    for key, wage in MARKET_WAGE.items():
        if key in city or city in key:
            return wage
    return MARKET_WAGE['默认']


def get_delivery_ratio(category: str) -> float:
    """外卖占月流水比例"""
    return DELIVERY_RATIO.get(category, DELIVERY_RATIO['默认'])


def get_default_staff(category: str) -> int:
    return DEFAULT_STAFF.get(category, DEFAULT_STAFF['默认'])


# 品牌级物料率覆盖（2026-09-18 新增，起因：瑞幸入表）
# ⚠️ 品类级 `MATERIAL_RATIO['奶茶'] = 0.32` 是**奶茶口径**。瑞幸是咖啡连锁，
#   物料结构不同（咖啡豆/奶浆/包材占比更高），直接套 32% 会**系统性低估成本**，
#   而低估成本 → 回本周期偏短 → 结论方向偏乐观，属"不能沉默"的那类误差。
# 来源（B 级：公司披露）：瑞幸 2025Q3 业绩会 CFO 披露「原材料成本占总净营收的
#   比例从 2024 年同期 39% 降至 36%」；券商测算整体毛利率 63.8%/直营 66.1% 互相印证
#   → 取 36%（= 1 − 毛利率）。
# ⚠️ 口径提醒：36% 是**占总净营收**（公司口径：自营+联营合并），与品类级 32%
#   的「占月流水」不是逐字同口径；但两者同向、量级可直接使用。这是
#   "**公司披露值 + 我方换算判断**"，不是逐店实测，报告里要如实这么讲。
BRAND_MATERIAL_RATIO = {'瑞幸': 0.36}


def get_material_ratio(category: str, brand: str = None) -> float:
    """物料成本率。**品牌级覆盖优先于品类级**（2026-09-18）。

    brand 为空 / 未收录 → 退回品类级 `MATERIAL_RATIO`，与旧行为完全一致
    （向后兼容：不传 brand 的调用点结果不变）。
    """
    if brand and brand in BRAND_MATERIAL_RATIO:
        return BRAND_MATERIAL_RATIO[brand]
    return MATERIAL_RATIO.get(category, MATERIAL_RATIO['默认'])


# ---------------------------------------------------------------
# 5. 三档情景假设（2026-09-14 新增）
# ---------------------------------------------------------------
# ⚠️ 下面是**假设区间，不是实测数据**——答辩必须这么讲，不能包装成调研结果。
#
# 起因：单点测算给天一广场 30㎡ 蜜雪冰城算出 41% 净利率、2.6 个月回本，
# 而真实奶茶店净利率通常在 10~20%、回本 12~24 个月，乐观了一个量级。
# 漏掉的四项：①商场扣点/物业费/推广费（天一广场是购物中心，mall 铺位普遍
# "保底租金 or 流水扣点取高"）②税 ③物料损耗 ④人工不跟单量（369 单/天只算 2 人）。
#
# 为什么不直接补数字：用户是在校生，拿不到品牌授权与真实账目，这四个数没有
# 可引用出处，而项目铁律是"不许编造数据"。所以走与 λ 完全相同的口径——
# 不给伪精确单点，给三档区间 + 结论稳健性，把不确定性摊开给评委看。
#
# 三个费率都以**月流水**为基数（购物中心扣点、增值税、损耗都是按流水走的）。
SCENARIOS = {
    '乐观': {
        '场地附加费率': 0.00,   # 街边铺/无商场扣点，物业费推广费自理在杂费里
        '税负率': 0.005,        # 小规模纳税人优惠档
        '损耗率': 0.01,         # 熟手备料、SKU 少
        '人均日单量': 200,      # 熟手 + 高峰有兼职帮手
    },
    '中性': {
        '场地附加费率': 0.06,   # 有物业费/推广费，或低扣点商场
        '税负率': 0.02,
        '损耗率': 0.03,
        '人均日单量': 140,
    },
    '保守': {
        '场地附加费率': 0.15,   # 购物中心扣点模式（餐饮常见量级）
        '税负率': 0.04,
        '损耗率': 0.05,         # 新手备料、报废高
        '人均日单量': 100,      # 无兼职、纯新手
    },
}
DEFAULT_SCENARIO = '中性'
SCENARIO_ORDER = ['乐观', '中性', '保守']


def get_scenario(name=None) -> dict:
    """取情景假设；未指定或名字不认识都退回中性档（不许静默用乐观档糊弄）。"""
    return SCENARIOS.get(name or DEFAULT_SCENARIO, SCENARIOS[DEFAULT_SCENARIO])


def derive_staff(daily_orders, per_capita) -> int:
    """按单量推导可行人数（向上取整）。

    这是结构性修正而非新数据：原模型 DEFAULT_STAFF 把人数写死（奶茶/甜品/早餐 2、
    便利店 1），与单量完全脱钩——便利店画像自己写着"24h 属性强"却只给 1 人，
    早餐 400 单/天也只给 2 人。人数必须跟单量走，否则净利是幻想出来的。
    """
    if not daily_orders or not per_capita:
        return 1
    return max(1, math.ceil(daily_orders / per_capita))


def estimate_profit(category, area_m2, city, monthly_rent, investment=None, staff=None,
                    price=None, daily_sales=None, sales_est=None, brand=None, scenario=None):
    """综合盈利测算（2026-09-14 三档情景版）:
    月流水  = 精细化估算(sales_est) 或 客单价×日单量×30
    月物料  = 月流水 × 品类物料占比
    月人工  = 人数 × 市场实际月薪 × (1+雇主社保28%)
    人数    = max(用户指定, ceil(日单量 / 情景人均日单量))   ← 结构性修正
    外卖抽成 = 月流水 × 外卖占比 × 平台综合抽成22%
    场地附加 = 月流水 × 情景场地附加费率（商场扣点/物业费/推广费）  ← 新增
    税      = 月流水 × 情景税负率                                ← 新增
    损耗    = 月流水 × 情景损耗率                                ← 新增
    月摊销  = 前期投入 / 36个月(3年租约)
    月品牌费 = 加盟品牌年品牌费 / 12（仅加盟）
    月水电  = 面积 × 单位强度 × 当地价
    毛利率  = (月流水 - 月物料 - 月损耗) / 月流水      ← 2026-09-15 新增，产品口径
    月净利  = 月流水 - 上述全部
    回本周期 = 前期投入 / (月净利 + 月摊销)   （摊销为非现金成本，加回）

    毛利率口径（2026-09-15 定稿）：**产品口径**，即只扣物料与损耗，
    **不含外卖抽成**——平台佣金是渠道/销售费用（性质同租金、人工），不是产品成本，
    这也是餐饮会计的惯例口径（毛利率 = 营业额 − 食材成本）。
    但奶茶外卖占流水 35%×抽成 22% = 7.7%，只看毛利率会误导，故并列给出
    `外卖抽成占流水比` 与 `扣渠道后毛利率`（= 毛利率 − 该占比）。
    详见 docs/经营测算口径与已开店诊断.md。
    ⚠️ 勿与既有 key `外卖抽成率`（= 平台佣金率 22%，**不是**占流水比）混用。

    scenario: 乐观/中性/保守，默认中性。⚠️ 三档费率是**假设区间不是实测数据**。
    brand: 加盟品牌名；未自报投入时前期投入用品牌加盟政策参考值
    """
    from config import get_profile
    from engine.brands import get_franchise_info
    prof = get_profile(category)
    sc = get_scenario(scenario)
    price = price or prof['price']
    if sales_est is not None:
        monthly_sales = sales_est
        daily = round(sales_est / (price * 30)) if price else prof['daily_sales']
    else:
        daily = daily_sales or prof['daily_sales']
        monthly_sales = price * daily * 30

    material_ratio = get_material_ratio(category, brand=brand)
    market_wage = get_market_wage(city)
    delivery_ratio = get_delivery_ratio(category)

    # 人数取"用户指定"与"产能下限"的较大值：369 单/天不可能 2 个人做完，
    # 按用户报的 2 人算成本，等于把一部分人工藏起来当净利。
    needed = derive_staff(daily, sc['人均日单量'])
    declared = staff or get_default_staff(category)
    staff_used = max(declared, needed)
    origin = '用户指定' if staff else '品类默认'
    if declared >= needed:
        staff_source = origin
    else:
        staff_source = (f'{origin} {declared} 人低于产能下限，已按 {needed} 人计'
                        f'（日单量 {daily} ÷ 人均 {sc["人均日单量"]} 单/天）')

    util = estimate_monthly_utility(category, area_m2, city)
    util_cost = util['水电合计(元/月)']
    labor_cost = staff_used * market_wage * (1 + SOCIAL_RATE)
    material_cost = monthly_sales * material_ratio
    delivery_cost = monthly_sales * delivery_ratio * COMMISSION_RATE
    venue_cost = monthly_sales * sc['场地附加费率']
    tax_cost = monthly_sales * sc['税负率']
    waste_cost = monthly_sales * sc['损耗率']
    misc_cost = MISC_MONTHLY

    # ---- 毛利率（2026-09-15 新增）----
    # 产品毛利口径：只扣物料与损耗。外卖抽成归渠道/销售费用，不进 COGS（理由见 docstring）。
    # 三个口径并列输出，让"平台吃掉多少"看得见，而不是藏进毛利率里。
    cogs = material_cost + waste_cost
    gross_margin = (monthly_sales - cogs) / monthly_sales if monthly_sales else None
    delivery_over_sales = delivery_ratio * COMMISSION_RATE
    gross_margin_channel = (gross_margin - delivery_over_sales
                            if gross_margin is not None else None)

    # 品牌加盟政策（2026 公开渠道参考量级）
    franchise = get_franchise_info(brand)
    brand_fee_monthly = franchise['yearly_fee'] / 12 if franchise else 0.0

    # 前期投入优先级: 用户输入 > 品牌加盟参考 > 通用估算(装修4000/㎡+设备3万)
    if investment is not None and investment > 0:
        invest_source = '用户输入'
    elif franchise:
        investment = franchise['invest_ref']
        invest_source = f'品牌加盟参考({brand})'
    else:
        investment = int(area_m2 or 30) * 4000 + 30000
        invest_source = '参考估算'
    amortize = investment / AMORTIZE_MONTHS

    # ⚠️ 命名修正（2026-09-15）：这里累加的是**全部成本**（含物料/外卖抽成/场地/税/
    #    损耗等变动项），旧变量名 fixed_cost、旧输出键 '月固定成本' 都是**误名**——
    #    真正的固定成本（租金+人工+水电+摊销+品牌费+杂费）只有它的一半左右
    #    （宁波 30㎡ 蜜雪：真固定 ¥37,777 vs 此值 ¥78,336）。用户可见处一律用
    #    '月成本合计'；'月固定成本' 仅作已废弃别名保留，避免旧 JSON 读取失败。
    total_cost = (monthly_rent + util_cost + labor_cost + material_cost + delivery_cost
                  + venue_cost + tax_cost + waste_cost
                  + amortize + brand_fee_monthly + misc_cost)
    net_profit = monthly_sales - total_cost

    # 回本: 摊销是非现金成本, 现金口径回本速度 = 投入/(净利+摊销)
    cash_monthly = net_profit + amortize
    payback = investment / cash_monthly if cash_monthly > 0 else None

    return {
        '品类': category,
        '情景': scenario or DEFAULT_SCENARIO,
        '假设': sc,
        '假设口径': '假设区间，非实测数据',
        '客单价': price,
        '日单量参考': daily,
        '月流水估算': round(monthly_sales),
        '物料占比': material_ratio,
        '月物料成本': round(material_cost),
        '月人工': round(labor_cost),
        '人数': staff_used,
        '申报人数': declared,
        '可行人数': needed,
        '人数口径': staff_source,
        '人均月薪': market_wage,
        '社保负担率': SOCIAL_RATE,
        '外卖占比': delivery_ratio,
        '外卖抽成率': COMMISSION_RATE,
        '月外卖抽成': round(delivery_cost),
        '场地附加费率': sc['场地附加费率'],
        '月场地附加费': round(venue_cost),
        '税负率': sc['税负率'],
        '月税': round(tax_cost),
        '损耗率': sc['损耗率'],
        '月损耗': round(waste_cost),
        '毛利率': round(gross_margin, 4) if gross_margin is not None else None,
        '毛利率口径': '产品口径（流水 − 物料 − 损耗）；不含外卖抽成/人工/租金',
        '外卖抽成占流水比': round(delivery_over_sales, 4),
        '扣渠道后毛利率': (round(gross_margin_channel, 4)
                      if gross_margin_channel is not None else None),
        '月租金': monthly_rent,
        '月水电': util_cost,
        '月杂费': misc_cost,
        '月摊销': round(amortize),
        '摊销月数': AMORTIZE_MONTHS,
        '品牌': brand,
        '月品牌费': round(brand_fee_monthly),
        '月成本合计': round(total_cost),
        '月固定成本': round(total_cost),   # ⚠️ 已废弃别名：值是**总成本**不是固定成本，
        #   仅为兼容历史 analyses.json 保留；新代码请用 '月成本合计'。
        '月净利估算': round(net_profit),
        '净利率': round(net_profit / monthly_sales, 4) if monthly_sales else None,
        '前期投入': round(investment),
        '投入来源': invest_source,
        '回本周期(月)': round(payback, 1) if payback else None,
        '盈亏判断': '可行' if net_profit > 0 else '亏损风险高',
    }


def estimate_profit_bands(category, area_m2, city, monthly_rent, **kw):
    """三档情景并列测算 + 区间摘要。

    为什么要并列：单点数字会被读成预测。给区间才能回答评委那句
    "你这个净利率怎么算的"——答案是"取决于商场扣点和产能假设，我们摊开给你看"。
    """
    kw.pop('scenario', None)
    bands = {n: estimate_profit(category, area_m2, city, monthly_rent, scenario=n, **kw)
             for n in SCENARIO_ORDER}

    nets = {n: bands[n]['月净利估算'] for n in SCENARIO_ORDER}
    margins = {n: bands[n]['净利率'] for n in SCENARIO_ORDER}
    pbs = {n: bands[n]['回本周期(月)'] for n in SCENARIO_ORDER}
    pb_vals = [v for v in pbs.values() if v]

    all_win = all(v > 0 for v in nets.values())
    all_lose = all(v <= 0 for v in nets.values())
    if all_win:
        concl = '三档均盈利——结论对假设不敏感'
    elif all_lose:
        concl = '三档均亏损——结论对假设不敏感'
    else:
        concl = ('情景敏感：乐观档盈利、保守档亏损，实际结果取决于'
                 '商场扣点与产能假设，不能只看单一数字')

    return {
        **bands,
        '区间': {
            '净利区间(元/月)': (nets['保守'], nets['乐观']),
            '净利率区间': (margins['保守'], margins['乐观']),
            '回本区间(月)': (max(pb_vals), min(pb_vals)) if pb_vals else None,
            '回本区间说明': ('保守档最慢、乐观档最快' if pb_vals
                          else '至少一档亏损，回本周期不存在'),
            '三档均盈利': all_win,
            '三档均亏损': all_lose,
            '结论': concl,
            '口径': '假设区间，非实测数据（场地附加费/税/损耗/人均产能四项无可引用出处）',
        },
    }


if __name__ == '__main__':
    print('=== 水电标准模块自检 ===')
    for city in ['杭州', '宁波', '温州', '嘉兴']:
        print(f'{city} 商业水价: {get_water_price(city)} 元/吨')
    print()
    for cat in ['奶茶', '甜品', '早餐', '便利店']:
        u = estimate_monthly_utility(cat, 30, '杭州')
        print(f"{cat} 30㎡ 杭州: 电费{u['电费(元/月)']} 水费{u['水费(元/月)']} 合计{u['水电合计(元/月)']}元/月")
    print()
    print('=== 产能下限对默认人数的修正（结构性 bug）===')
    for cat in ['奶茶', '甜品', '早餐', '便利店']:
        p = estimate_profit(cat, 30, '宁波', 8000)
        print(f"  {cat}: 默认{p['申报人数']}人 → 中性档实需{p['人数']}人"
              f"（{p['日单量参考']}单/天 ÷ {p['假设']['人均日单量']}）")
    print()
    print('=== 三档情景自检（奶茶 30㎡ 宁波 月租8000 投入12万 蜜雪冰城）===')
    bands = estimate_profit_bands('奶茶', 30, '宁波', 8000, investment=120000,
                                  staff=2, brand='蜜雪冰城')
    for n in SCENARIO_ORDER:
        b = bands[n]
        print(f"  [{n}] 人数{b['人数']} 月流水{b['月流水估算']:,} "
              f"月净利{b['月净利估算']:,} 净利率{(b['净利率'] or 0):.1%} "
              f"回本{b['回本周期(月)']}个月")
    for k, v in bands['区间'].items():
        print(f'  区间·{k}: {v}')
