# -*- coding: utf-8 -*-
"""
transfer_risk.py —— 区域转让率风险指数（Huff 正向吸引力的镜像负向信号）
=====================================================================
商业直觉：所有选址工具都在数「有多少人、多少竞品」（正向吸引力），
几乎没人数「有多少店在逃跑」。58 同城的「转让」标的是现任租户想退出，
是市场用脚投票的负向信号 —— 一个区域转让铺越多，说明退出者越多，
该区域对后来者的实际风险越高。

把转让占比聚合到**区级**，得到：
    转让率 = 区域内转让铺数 / (区域内转让铺 + 出租铺数)
这个比例与 Huff 模型的 D×P（能赚多少）形成**镜像**：
    Huff 正向看「能赚多少」，转让率负向看「别人为什么跑」。

数据来源：rental58.fetch_shops 返回的条目已带 `deal` 三态
（'转让' / '出租' / ''，判不出不标），`loc` 形如「滨江-四桥南」，
区级 = loc.split('-')[0]。

⚠️ 口径边界（答辩必讲）：
1. 转让 ≠ 倒闭 —— 也可能是老板转行/搬家/套现离场，不能直接等同「失败」；
   但无论哪种原因，转让都是「现任经营者不愿/不能继续」的退出信号，
   对一个**新进入者**而言是负向风险，这是本指数的含义，不是「倒闭率」。
2. 样本来自 58 在租列表的一次抓取（快照），不代表该区域存量全貌；
   样本量过小时（<min_n）不给出分级，避免用个位数样本制造假精度。
3. 判不出性质的条目（deal=''）不进分子也不进分母，单独计数。
"""

# 风险分级阈值（经验值，随样本积累可调）：
#   转让率 ≥ 0.50 → 高（每两家在租铺里至少一家在转店）
#   0.30 ~ 0.50   → 中
#   < 0.30        → 低
RISK_HIGH = 0.50
RISK_MID = 0.30


def area_of(loc):
    """从 58 的 loc（如「滨江-四桥南」）取区级名。取不到返回 ''。"""
    loc = (loc or '').strip()
    if not loc:
        return ''
    # loc 常是「区-街道」两级，区在前；没有 '-' 时整段当区名
    return loc.split('-')[0].strip()


def transfer_ratio(shops, min_n=5):
    """按区聚合，算每个区的转让率。

    shops: rental58.fetch_shops 返回的条目列表（每项含 deal / loc）。
    min_n : 区级有效样本（转让+出租）低于此数不输出，避免个位数样本假精度。

    返回 list[dict]，按转让率降序：
        {'区': str, '转让': int, '出租': int, '未标': int,
         '有效样本': int, '转让率': float|None}
    """
    agg = {}
    for s in shops:
        area = area_of(s.get('loc'))
        if not area:
            area = '未知区域'
        d = s.get('deal') or ''
        bucket = agg.setdefault(area, {'转让': 0, '出租': 0, '未标': 0})
        if d == '转让':
            bucket['转让'] += 1
        elif d == '出租':
            bucket['出租'] += 1
        else:
            bucket['未标'] += 1

    out = []
    for area, b in agg.items():
        n = b['转让'] + b['出租']
        if n < min_n:
            continue
        out.append({
            '区': area,
            '转让': b['转让'],
            '出租': b['出租'],
            '未标': b['未标'],
            '有效样本': n,
            '转让率': round(b['转让'] / n, 3) if n else None,
        })
    out.sort(key=lambda x: (x['转让率'] is None, -(x['转让率'] or 0)))
    return out


def risk_level(ratio):
    """转让率 → 风险等级。None（样本不足）也返回 None。"""
    if ratio is None:
        return None
    if ratio >= RISK_HIGH:
        return '高'
    if ratio >= RISK_MID:
        return '中'
    return '低'


def summarize(shops, min_n=5):
    """产出一段可直接放回复/报告的文字摘要。"""
    rows = transfer_ratio(shops, min_n=min_n)
    if not rows:
        return '（区域内有效样本不足，暂不给出转让率分级）'
    lines = []
    for r in rows:
        lvl = risk_level(r['转让率'])
        tag = {'高': '⚠️', '中': '', '低': ''}.get(lvl, '')
        lines.append(
            f"{tag}{r['区']}：{r['转让']}/{r['有效样本']} 家在转让（转让率 "
            f"{r['转让率']:.0%}，{lvl}风险）")
    return '；'.join(lines)


if __name__ == '__main__':
    # 演示：伪造一批条目验证聚合与分级逻辑（纯逻辑，无网络）
    demo = [
        {'loc': '滨江-四桥南', 'deal': '转让'},
        {'loc': '滨江-西兴', 'deal': '转让'},
        {'loc': '滨江-长河', 'deal': '出租'},
        {'loc': '滨江-长河', 'deal': '出租'},
        {'loc': '滨江-长河', 'deal': '出租'},
        {'loc': '西湖-文三路', 'deal': '出租'},
        {'loc': '西湖-文三路', 'deal': '出租'},
        {'loc': '西湖-黄龙', 'deal': ''},
        {'loc': '西湖-黄龙', 'deal': '出租'},
    ]
    for r in transfer_ratio(demo, min_n=3):
        print(f"{r['区']} 转让率 {r['转让率']:.0%} -> {risk_level(r['转让率'])}")
