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
# 浙江省 2024 年最低工资标准（元/月，参考值，以当地人社部门最新公布为准）
# 第一档 2490（杭州/宁波/温州市区等）；第二档 2260（其余地级市市区等）
MIN_WAGE = {
    '杭州': 2490, '宁波': 2490, '温州': 2490,
    '嘉兴': 2260, '湖州': 2260, '绍兴': 2260, '金华': 2260,
    '衢州': 2260, '舟山': 2260, '台州': 2260, '丽水': 2260,
    '默认': 2260,
}

# 各品类默认运营人数（用户不指定时使用）
DEFAULT_STAFF = {'奶茶': 2, '甜品': 2, '早餐': 2, '便利店': 1, '默认': 2}

# 物料/原料采购成本占月流水比例（按市面行情参考值）
# 餐饮类为食材成本占比，便利店为商品进销成本占比（COGS）
MATERIAL_RATIO = {'奶茶': 0.32, '甜品': 0.38, '早餐': 0.42, '便利店': 0.75, '默认': 0.40}

# 每月杂费/损耗/营销等（元）
MISC_MONTHLY = 1500


def get_min_wage(city: str) -> int:
    """按城市取最低工资标准（元/月）"""
    for key, wage in MIN_WAGE.items():
        if key in city or city in key:
            return wage
    return MIN_WAGE['默认']


def get_default_staff(category: str) -> int:
    return DEFAULT_STAFF.get(category, DEFAULT_STAFF['默认'])


def get_material_ratio(category: str) -> float:
    return MATERIAL_RATIO.get(category, MATERIAL_RATIO['默认'])


def estimate_profit(category, area_m2, city, monthly_rent, investment=None, staff=None,
                    price=None, daily_sales=None, sales_est=None):
    """综合盈利测算（含人工/物料/水电/租金/杂费 + 装修投入）:
    月流水  = 精细化估算(sales_est) 或 客单价×日单量×30
    月物料  = 月流水 × 品类物料占比
    月人工  = 人数 × 城市最低工资
    月水电  = 面积 × 单位强度 × 当地价
    月净利  = 月流水 - 租金 - 水电 - 人工 - 物料 - 杂费
    回本周期 = 前期投入 / 月净利
    """
    from config import get_profile
    prof = get_profile(category)
    price = price or prof['price']
    if sales_est is not None:
        monthly_sales = sales_est
        daily = round(sales_est / (price * 30)) if price else prof['daily_sales']
    else:
        daily = daily_sales or prof['daily_sales']
        monthly_sales = price * daily * 30

    material_ratio = get_material_ratio(category)
    staff = staff or get_default_staff(category)
    monthly_wage = get_min_wage(city)

    util = estimate_monthly_utility(category, area_m2, city)
    util_cost = util['水电合计(元/月)']
    labor_cost = staff * monthly_wage
    material_cost = monthly_sales * material_ratio
    misc_cost = MISC_MONTHLY

    fixed_cost = monthly_rent + util_cost + labor_cost + material_cost + misc_cost
    net_profit = monthly_sales - fixed_cost

    # 前期投入（用户给定；未给则按参考估算：装修4000/㎡ + 设备物料3万）
    if investment is None or investment <= 0:
        investment = int(area_m2 or 30) * 4000 + 30000
        invest_source = '参考估算'
    else:
        invest_source = '用户输入'

    payback = investment / net_profit if net_profit > 0 else None

    return {
        '品类': category,
        '客单价': price,
        '日单量参考': daily,
        '月流水估算': round(monthly_sales),
        '物料占比': material_ratio,
        '月物料成本': round(material_cost),
        '月人工': round(labor_cost),
        '人数': staff,
        '人均月薪': monthly_wage,
        '月租金': monthly_rent,
        '月水电': util_cost,
        '月杂费': misc_cost,
        '月固定成本': round(fixed_cost),
        '月净利估算': round(net_profit),
        '前期投入': round(investment),
        '投入来源': invest_source,
        '回本周期(月)': round(payback, 1) if payback else None,
        '盈亏判断': '可行' if net_profit > 0 else '亏损风险高',
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
    p = estimate_profit('奶茶', 30, '杭州', 8000, investment=120000, staff=2)
    for k, v in p.items():
        print(f'  {k}: {v}')
