# -*- coding: utf-8 -*-
"""
scoring.py —— 选址评分引擎（Huff 引力模型版）
================================================
通用框架 4 维度（0~100 分）:
  客群匹配度 / 竞争压力 / 交通可达性 / 租金承受力
总分 = Σ(维度分 × 品类权重)

模型升级（v2）:
- 客群匹配度: 从"POI 计数"升级为 Huff 引力累计（距离衰减 λ=2）
  P ∝ Σ (1 / (d + d0)^λ)，越近的客群 POI 权重越高
- 竞争压力:  从"数量 vs 基准"升级为竞品引力累计，竞品越近越密集扣分越狠
- 理论依据: Huff 引力模型(1963) / Reilly 零售引力法则(1931) / 中心地理论

明确局限（答辩必讲）:
- 基于公开 POI 数据，不含真实人流量/成交租金/营业额
- Huff 模型需要商店面积 S，用 POI 类型近似；λ 取文献常用值 2（估计值）
- 输出为"选址适宜度相对评分"，非营收预测
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import get_profile  # noqa: E402
from data.query import query_within, nearest_distance, haversine  # noqa: E402
from engine.realtime import get_surrounding  # noqa: E402


def query_pois(category, lng, lat, radius):
    """统一 POI 查询入口: 实时周边搜索优先, 本地库兜底。
    返回带 distance 字段的 POI 列表(供 Huff 引力计算)。"""
    pois = get_surrounding(category, lng, lat, radius)
    # 实时数据无 distance, 补算
    for p in pois:
        if not p.get('distance'):
            p['distance'] = round(haversine(lng, lat, p['lng'], p['lat']))
    return pois

# ---------------------------------------------------------------
# Huff 引力模型参数
# ---------------------------------------------------------------
LAMBDA = 2.0    # 距离衰减参数（Huff 文献常用值 λ=2，答辩中说明为估计）
D0 = 50.0       # 最小等效距离(米)：避免 d→0 时引力爆炸，也模拟店前 50m 的"到店距离"


def huff_gravity(pois, lam=LAMBDA, d0=D0):
    """Huff 引力累计: Σ (1/(d+d0))^λ。pois 需含 distance 字段"""
    g = 0.0
    for p in pois:
        d = p.get('distance', 0) or 0
        g += (1.0 / (d + d0)) ** lam
    return g


def _ref_gravity(n, radius):
    """参考引力：n 个 POI 均匀分布在 0.5*radius 处（作为 90 分基准配置）
    已用真实数据校准: 杭州湖滨银泰/宁波天一广场/温州五马街等核心商圈
    的加权引力约为 1e-04 ~ 1.7e-04，故将基准设为对应档位。"""
    if n <= 0 or radius <= 0:
        return 1e-9
    d_ref = 0.5 * radius
    return n * (1.0 / (d_ref + D0)) ** LAMBDA


# 客群匹配度归一化基准（真实数据校准）:
# 以"核心商圈级客群引力"= 90 分。杭州湖滨银泰实测 ~1.7e-04(未加权),
# 加权后约 1e-04。取 1.1e-04 作为 90 分基准（留出 100 分给超一线商圈）。
GUEST_GRAVITY_90 = 1.1e-4


# ---------------------------------------------------------------
# 1. 维度评分函数
# ---------------------------------------------------------------
def score_客群匹配度(profile, lng, lat):
    """Huff 引力版：目标客群 POI 距离衰减引力累计。
    设计: 取"最强单项客群引力"为主分（不同商圈结构各有强项，不要求四类齐全），
    其余类别做多样性加分。"""
    details = []
    per_label = []
    for tg in profile['target_pois']:
        label = tg['label']
        pois = query_pois(label, lng, lat, profile['radius'])
        g = huff_gravity(pois)
        per_label.append({'label': label, 'gravity': g, 'count': len(pois),
                          'weight': tg['weight'],
                          'samples': [p['name'] for p in pois[:5]]})
        details.append({
            'label': label, 'count': len(pois),
            'gravity': round(g, 6), 'weight': tg['weight'],
            'samples': [p['name'] for p in pois[:5]],
        })
    # 最强单项客群引力（该品类最核心的客群来源）
    g_max = max((x['gravity'] for x in per_label), default=0.0)
    # 多样性加分: 其他类别的加权贡献（主分之外最多 +20 分）
    g_other = sum(x['gravity'] * x['weight'] for x in per_label
                  if x['gravity'] < g_max * 0.5)
    # 归一化: 核心商圈级单项引力(约 1.2e-04) ≈ 80 分; 多样性加成封顶 20 分
    s_main = min(80.0, 80.0 * g_max / (1.2e-4))
    s_bonus = min(20.0, 20.0 * g_other / (6e-5))
    score = s_main + s_bonus
    total_g = sum(x['gravity'] * x['weight'] for x in per_label)
    return round(score), round(total_g, 6), details


def score_竞争压力(profile, lng, lat):
    """Huff 引力版：竞品引力累计 vs 参考配置（真实数据校准）"""
    pois = query_pois(profile['cn_name'], lng, lat, profile['radius'])
    n = len(pois)
    g = huff_gravity(pois)
    # 参考配置: comp_base 家竞品均匀分布在 0.5*radius 处（= 中等竞争强度，给 60 分左右）
    g_ref = _ref_gravity(profile['comp_base'], profile['radius'])
    ratio = g / g_ref if g_ref > 0 else 0.0
    if n == 0:
        # 无竞品: 可能蓝海也可能无人气, 给中性偏高分(75), 由 LLM 解读时提示两种可能
        s = 75.0
    elif ratio <= 0.5:
        s = 90 + 10 * (1 - ratio / 0.5)
    elif ratio <= 1.0:
        s = 90 - 30 * ((ratio - 0.5) / 0.5)
    elif ratio <= 1.5:
        s = 60 - 30 * ((ratio - 1.0) / 0.5)
    elif ratio <= 2.0:
        s = 30 - 30 * ((ratio - 1.5) / 0.5)
    else:
        s = 0.0
    return round(min(100, max(0, s))), n, [p['name'] for p in pois[:5]], round(ratio, 2)


def score_交通可达性(lng, lat):
    """最近地铁距离 + 公交站密度（保持简化，距离分段）"""
    metro_d = nearest_distance('通勤', lng, lat, max_km=10.0)
    pois = query_pois('通勤', lng, lat, 500)
    n_stops = len(pois)
    if metro_d is None:
        s = 20.0
    elif metro_d <= 300:
        s = 95.0
    elif metro_d <= 800:
        s = 80.0
    elif metro_d <= 1500:
        s = 55.0
    else:
        s = 35.0
    # 公交站密度加分（最多 +10）
    s += min(10.0, n_stops * 2.0)
    return round(min(100, s)), metro_d, n_stops


def score_租金承受力(profile, monthly_rent, est_monthly_sales):
    """月租 R vs 预估月流水 S，分段"""
    ratio = (monthly_rent or 0) / est_monthly_sales if est_monthly_sales else 1.0
    limit = profile['rent_ratio']
    if ratio <= limit * 0.6:
        s = 95.0
    elif ratio <= limit:
        s = 90 - 20 * ((ratio - limit * 0.6) / (limit * 0.4 + 1e-9))
    elif ratio <= limit * 1.67:
        s = 70 - 30 * ((ratio - limit) / (limit * 0.67 + 1e-9))
    else:
        s = max(0, 40 - 40 * ((ratio - limit * 1.67) / (limit * 1.67 + 1e-9)))
    return round(min(100, max(0, s))), ratio


def score_面积适配度(profile, area_m2):
    """面积适配度(0~100): 面积是否落在品类最佳区间。
    以 area_ideal 为满分点, 偏离越多分越低。"""
    if not area_m2:
        return None
    lo, hi = profile.get('area_range', (10, 100))
    ideal = profile.get('area_ideal', (lo + hi) / 2)
    if lo <= area_m2 <= hi:
        # 区间内: 越接近理想面积越高
        spread = max(hi - ideal, ideal - lo, 1)
        s = 100 - 30 * (abs(area_m2 - ideal) / spread)
    else:
        # 区间外: 越远越低
        if area_m2 < lo:
            s = 70 - 70 * ((lo - area_m2) / max(lo, 1))
        else:
            s = 70 - 70 * ((area_m2 - hi) / max(hi, 1))
    return round(min(100, max(0, s)))


def estimate_monthly_sales(profile, lng, lat, area_m2=None, city_level=1.0):
    """精细化月流水估算(偏保守):
    基准日单量 × 客群修正 × 竞争修正 × 面积修正 × 城市修正 × 保守系数
    避免固定日单量的粗糙估算。"""
    base_daily = profile['daily_sales']          # 基准日单量(理想状态下)
    price = profile['price']

    # 1) 客群修正: 客群引力 vs 参考(30个点半半径)
    s1, guest_g, _ = score_客群匹配度(profile, lng, lat)
    guest_factor = 0.6 + 0.6 * (s1 / 100.0)      # 0.6~1.2

    # 2) 竞争修正: 竞争压力大则打折
    s2, comp_n, _, _ = score_竞争压力(profile, lng, lat)
    comp_factor = 0.75 + 0.35 * (s2 / 100.0)       # 0.75~1.10

    # 3) 面积修正: 面积太小无法承载理想单量
    area_factor = 1.0
    if area_m2:
        lo, hi = profile.get('area_range', (10, 100))
        if area_m2 < lo:
            area_factor = max(0.4, area_m2 / lo)
        elif area_m2 > hi * 1.5:
            area_factor = 0.85  # 过大反而增加成本不增客流
        elif area_m2 > hi:
            area_factor = 0.92  # 略超区间, 小幅下调

    # 4) 城市修正: 杭州/宁波(核心城市) 1.0, 其他 0.85
    city_factor = city_level

    # 5) 保守系数: 开业前期客流爬坡, 取 0.75
    conservative = 0.75

    daily = base_daily * guest_factor * comp_factor * area_factor * city_factor * conservative
    monthly = daily * price * 30
    return {
        '基准日单量': base_daily,
        '客群修正': round(guest_factor, 2),
        '竞争修正': round(comp_factor, 2),
        '面积修正': round(area_factor, 2),
        '城市修正': round(city_factor, 2),
        '保守系数': conservative,
        '估算日单量': round(daily),
        '客单价': price,
        '月流水估算': round(monthly),
    }


# ---------------------------------------------------------------
# 2. 综合评分
# ---------------------------------------------------------------
# 浙江各市近似中心坐标（用于从经纬度粗判城市, 仅供水电价参考）
_CITY_CENTERS = {
    '杭州': (120.15, 30.28), '宁波': (121.55, 29.87), '温州': (120.70, 28.00),
    '嘉兴': (120.75, 30.75), '湖州': (120.10, 30.87), '绍兴': (120.58, 30.00),
    '金华': (119.65, 29.08), '衢州': (118.87, 28.94), '舟山': (122.20, 29.99),
    '台州': (121.42, 28.65), '丽水': (119.92, 28.45),
}


def _guess_city(lng, lat):
    """按经纬度粗判最近的浙江城市"""
    from data.query import haversine
    best, best_d = None, 1e18
    for city, (clng, clat) in _CITY_CENTERS.items():
        d = haversine(lng, lat, clng, clat)
        if d < best_d:
            best, best_d = city, d
    return best
def score_site(category, lng, lat, monthly_rent, name='', area_m2=None, city=None,
               budget=None, city_level=1.0, investment=None, staff=None):
    """对单个地址评分，返回完整结果 dict。
    area_m2: 商铺面积(㎡), 提供后启用面积适配度维度+水电盈利测算
    budget: 用户装修预算(元), 用于推断装修档次并修正吸引力
    investment: 用户前期投入成本(元)，用于装修档次 + 回本测算
    staff: 运营人数，未给则按品类默认（奶茶/甜品/早餐2人、便利店1人）
    city_level: 城市等级系数(杭州/宁波1.0, 其他0.85)
    """
    profile = get_profile(category)

    # 精细化营业额(先算, 供租金承受力使用)
    sales_est = estimate_monthly_sales(profile, lng, lat, area_m2, city_level)
    est_sales = sales_est['月流水估算']

    s1, guest_g, guest_details = score_客群匹配度(profile, lng, lat)

    # 装修精致度 -> 对目标客群吸引力的修正（±8分内，由前期投入推断）
    deco_budget = investment if investment else budget
    deco = evaluate_decoration(deco_budget, area_m2, category)
    deco_score = deco['档次分'] if deco else None
    attraction_bonus = (deco_score - 50) / 50 * 8 if deco_score is not None else 0.0
    if attraction_bonus:
        s1 = s1 + attraction_bonus

    s2, comp_n, comp_samples, comp_ratio = score_竞争压力(profile, lng, lat)
    s3, metro_d, n_stops = score_交通可达性(lng, lat)
    s4, rent_ratio = score_租金承受力(profile, monthly_rent, est_sales)
    s5 = score_面积适配度(profile, area_m2)  # 可能为 None

    if city is None:
        city = _guess_city(lng, lat)

    # 维度与权重: 面积已知时, 从客群/交通各拆5%给面积
    dims = {
        '客群匹配度': round(s1, 1),
        '竞争压力': s2,
        '交通可达性': s3,
        '租金承受力': s4,
    }
    weights = dict(profile['weights'])
    if s5 is not None:
        dims['面积适配度'] = s5
        # 重新分配权重: 面积占10%, 其余按原比例缩放
        rest = 0.90
        wsum = sum(weights.values())
        weights = {k: v / wsum * rest for k, v in weights.items()}
        weights['面积适配度'] = 0.10
    total = sum(dims[k] * weights[k] for k in dims)

    # 结论
    if total >= 75:
        verdict = '推荐'
    elif total >= 60:
        verdict = '谨慎推荐'
    elif total >= 45:
        verdict = '不建议优先选择'
    else:
        verdict = '不建议'

    # 主动质疑触发
    warnings = []
    if s2 < 30:
        warnings.append(f'⚠️ 竞争压力过低({s2}分)：周边 {comp_n} 家同类，引力累计超出参考 {comp_ratio} 倍，市场已饱和')
    if s1 < 40 and s2 < 40:
        warnings.append('⚠️ 客群匹配度与竞争压力双低，疑似品类-位置错配')
    if s4 < 40:
        warnings.append(f'⚠️ 租金承受力过低({s4}分)：月租占预估流水 {rent_ratio:.0%}，盈亏风险高')
    if s5 is not None and s5 < 40:
        warnings.append(f'⚠️ 面积适配度偏低({s5}分)：当前面积对{category}品类不理想，可能影响经营')
    if guest_g == 0:
        warnings.append('ℹ️ 目标客群 POI 数据稀疏，建议人工现场复核')

    # 水电成本 + 盈利测算（提供面积时）
    utility = None
    profit = None
    if area_m2:
        from engine.utilities import estimate_monthly_utility, estimate_profit
        utility = estimate_monthly_utility(category, area_m2, city)
        profit = estimate_profit(category, area_m2, city, monthly_rent or 0,
                                 investment=investment, staff=staff,
                                 sales_est=est_sales)

    return {
        'category': category,
        'name': name,
        'lng': lng,
        'lat': lat,
        'monthly_rent': monthly_rent,
        'area_m2': area_m2,
        'city': city,
        'investment': investment,
        'staff': staff,
        'attraction_bonus': round(attraction_bonus, 1),
        'dims': dims,
        'weights': weights,
        'total': round(total, 1),
        'verdict': verdict,
        'warnings': warnings,
        'evidence': {
            '客群引力累计': guest_g,
            '竞品数': comp_n,
            '竞品引力比': comp_ratio,
            '竞品样本': comp_samples,
            '最近通勤点(m)': metro_d,
            '500m内通勤点数': n_stops,
            '预估月流水': est_sales,
            '预估日单量': sales_est['估算日单量'],
            '流水明细': sales_est,
            '租金占流水比': f'{rent_ratio:.0%}',
        },
        'decoration': deco,
        'guest_details': guest_details,
        'profile_desc': profile['profile_desc'],
        'utility': utility,
        'profit': profit,
        'model': 'huff-v3',
    }


def evaluate_decoration(budget, area_m2, category):
    """根据装修预算评估装修档次(需求3):
    档次分 = 预算/面积 得到的单位面积装修投入(元/㎡) 映射到 0~100。
    - 经济型: <1000元/㎡
    - 标准型: 1000~2000元/㎡
    - 品质型: 2000~3500元/㎡
    - 高端型: >3500元/㎡
    返回 dict(档次, 档次分, 单位投入)
    """
    if not budget or not area_m2:
        return None
    per_m2 = budget / area_m2
    if per_m2 >= 3500:
        tier, score = '高端', 90
    elif per_m2 >= 2000:
        tier, score = '品质', 75
    elif per_m2 >= 1000:
        tier, score = '标准', 60
    else:
        tier, score = '经济', 40
    return {
        '装修预算': budget,
        '面积': area_m2,
        '单位投入(元/㎡)': round(per_m2),
        '档次': tier,
        '档次分': score,
        '说明': f'{tier}型装修，单位面积投入约{per_m2:.0f}元/㎡',
    }


def compare_sites(category, sites, monthly_rent):
    """对比多个候选地址: sites = [(name, lng, lat), ...]"""
    results = [score_site(category, lng, lat, monthly_rent, name) for name, lng, lat in sites]
    results.sort(key=lambda r: r['total'], reverse=True)
    return results


if __name__ == '__main__':
    print('评分引擎 v2 (Huff 引力模型) 加载成功。')
    print('  from engine.scoring import score_site')
    print('  r = score_site("奶茶", 120.1552, 30.2741, monthly_rent=8000)')
