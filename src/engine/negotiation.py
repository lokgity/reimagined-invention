# -*- coding: utf-8 -*-
"""
negotiation.py —— 租金谈判助手（AI 含量模块 ①）
==================================================
思路: 谈判的本质是信息差。房东知道同商圈行情，租客不知道。
本模块用两条独立的线把信息差抹平:
1. rent_benchmark: 58 同城同区在租挂牌的**参考带**(P25~P75 元/㎡/月) + 完整样本标题
2. negotiation_brief: 参考带定位 + 承受力上限 + 结构化谈判筹码
3. 话术由 LLM 在 agent 层生成（本模块只产数据证据，遵守"引擎产数、LLM 产文"分工）

2026-09-17 增补 `band_from_samples()`：同一套口径，但输入是**调用方手上已经抓到的样本**，
用于给"只有面积没有租金"的候选铺源补一个**标注为推算**的租金区间（不额外抓一次，见其 docstring）。

⚠️ 目标价只来自承受力，不来自行情（2026-09-14 修正）:
58 的 area_filter 只对列表标题做关键词过滤，粒度到**行政区**不到商圈，且不分
楼层与业态。实测宁波海曙的最低 5 个样本是社区底商兼仓库、大学食堂档口、可办公
可娱乐场地、夜宵街招商、宿舍楼边档口急转——P25 是拿食堂档口算出来的。旧版据此
反推出"建议目标价 1239 元/月"，而用户自报单价是它的 5.6 倍，LLM 于是自信地教用户
对房东说"我诚心租，先给你出 1239 元/月"。所以行情侧降级为参考带 + 披露样本，
真正能当目标价的只有 scoring.solve_rent_limits 反解出的承受力上限。

局限（答辩口径）: 挂牌价 ≠ 成交价；参考带不可复现到个位数（58 列表每次返回
15~30 条不等）；承受力上限依赖流水估算，而流水估算本身带 0.6 保守爬坡系数。
"""
import statistics
import sys
# ⚠️ 必须**模块级**导入：`rent_benchmark` 原先只在函数内 `from datetime import datetime`，
# 于是 2026-09-17 给 `band_from_samples` 加"抓取时间"时踩了 NameError，
# 而调用方 `_fill_field_states` 把异常兜住 → 参考带静默变成 None →
# 候选的"推算租金"全部静默退化成"不可得"。**没有任何报错，只是少了一整块能力**。
# 这类"兜底吞掉真错误"的路径，只有回归套件能发现（verify_place_first §5/§6）。
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent.rental58 import fetch_shops  # noqa: E402


# 标题里出现这些词，基本可以判定不是"购物中心/沿街零售铺"同类业态。
# ⚠️ 只用于**披露**不用于剔除：关键词过滤是新的未经验证启发式，静默丢样本
# 比留着混杂样本更危险（用户看不到自己少了什么）。
NON_RETAIL_HINTS = ['食堂', '档口', '仓库', '仓储', '办公', '写字楼', '厂房', '摊位',
                    '车位', '宿舍', '住宅', '公寓', '整栋', '整层', '楼上', '地下',
                    '冷库', '场地', '车间', '农庄', '养殖']


def rent_benchmark(city, district=None, limit=30):
    """抓同区在租商铺挂牌，返回**参考带**（不是可锚定的目标价）。

    ⚠️ 为什么不给中位价当目标价（2026-09-14 修正）：
    area_filter 只对 58 列表标题做关键词过滤，粒度到**行政区**不到商圈，且完全
    不分楼层与业态。实测宁波海曙 30㎡ 档：最低 5 个样本分别是社区底商兼仓库
    (27.3)、大学食堂档口(30.0)、可办公可娱乐场地(39.2)、奥莱旁夜宵街招商(45.0)、
    宿舍楼边食堂档口急转(50.0)——无一是购物中心零售铺，P25 是拿食堂档口算出来的。
    拿它去锚天一广场的铺子，会把用户推到"我诚心租，给你 1239 元/月"这种荒谬报价上。
    所以这里只输出参考带 + 完整样本标题，可比性交给 LLM 与用户判断。

    district: 区域关键词(如'海曙''滨江')。返回 dict；抓取失败或样本不足返回 None。
    """
    shops = fetch_shops(city, limit=limit, area_filter=district)
    scope = f'{city}{district or ""}'
    if not shops and district:
        shops = fetch_shops(city, limit=limit)  # 区域过滤无结果则放宽到全城
        scope = f'{city}（全城，"{district}"无命中）'
    bench = band_from_samples(shops, scope=scope)
    if bench is None:
        return None
    bench['抓取时间'] = datetime.now().strftime('%Y-%m-%d %H:%M')
    return bench


def band_from_samples(shops, scope='', min_samples=3):
    """从**已抓到的样本**算挂牌参考带（**不重新抓取**）。

    为什么需要这个函数（2026-09-17 加）：
    候选铺源列表里有一部分条目**只有面积没有租金**（58 列表页缺租金实测 0%，
    但经高德/本地库兜底的条目完全没有租金字段）。要给这类条目补一个**标注为推算**
    的租金，就得有一条"这一带大致什么量级"的参考带。

    为什么不能用 `rent_benchmark()`：它会**再跑一次 Playwright 抓取**。
    在候选检索那一轮里，我们手上已经有同一批样本了 —— 再抓一次既慢，
    又会让"参照样本"和"候选列表"来自两个不同时间点的不同批次，
    可比性反而更差。所以这里复用同一次快照。

    ⚠️ 口径与 `rent_benchmark` **完全一致**（同一份 `可比性声明`）：
    挂牌价 ≠ 成交价；粒度到行政区不到商圈；未筛除楼层/业态。
    **推算结果只能当区间，不能当目标价，也不能用于回本周期这类对租金敏感的结论。**
    """
    units = []
    for s in shops or []:
        price, area = s.get('price'), s.get('area')
        if price and area and area >= 5:
            title = s.get('title', '') or ''
            units.append({'单价': price / area, '月租': price, '面积': area,
                          '位置': s.get('loc', ''), '标题': title[:40],
                          '疑似非同类': [w for w in NON_RETAIL_HINTS if w in title]})
    if len(units) < min_samples:
        return None
    units.sort(key=lambda u: u['单价'])
    prices = [u['单价'] for u in units]
    n = len(prices)
    areas = sorted(u['面积'] for u in units)
    mixed = [u for u in units if u['疑似非同类']]
    hits = sorted({w for u in mixed for w in u['疑似非同类']})
    hits_txt = f'（命中：{"、".join(hits)}）' if hits else ''
    return {
        '口径': f'{scope} 在租挂牌参考带（非商圈、非成交价、未筛除业态）',
        '范围': scope,
        '样本数': n,
        '参考带': (round(prices[n // 4], 1), round(prices[3 * n // 4], 1)),
        'P25单价': round(prices[n // 4], 1),
        'P75单价': round(prices[3 * n // 4], 1),
        '中位单价': round(statistics.median(prices), 1),
        '中位面积': round(statistics.median(areas), 0),
        '最低单价': round(prices[0], 1),
        '最高单价': round(prices[-1], 1),
        '疑似非同类业态样本数': len(mixed),
        '疑似非同类占比': round(len(mixed) / n, 2),
        '命中关键词': hits,
        '最低5样本': units[:5],
        '最高5样本': units[-5:],
        '样本': units[:5],          # 兼容旧字段名
        # ⚠️ 取证时间必须有：候选列表里的"推算租金"就是拿这份参考带算出来的，
        #    没有时间戳，用户看到的是一个无从追溯的金额。
        #    这是回归套件 verify_place_first §5「每个候选都带取证时间」逼出来的 ——
        #    `rent_benchmark` 一直有这行，`band_from_samples` 是后来加的，漏了。
        '抓取时间': datetime.now().strftime('%Y-%m-%d %H:%M'),
        '可比性声明': (
            f'本次样本粒度是「{scope}」，不到商圈，且未剔除楼层/业态差异'
            f'{"（地址里没抽到区名，实际是全城口径，比行政区更粗）" if not scope else ""}；'
            f'{n} 个样本中 {len(mixed)} 个标题含食堂档口/仓库/办公/楼上等非同类业态关键词'
            f'{hits_txt}。绝对价位不可直接套用到具体铺子，只能作为"这一带大致什么量级"的参考带。'
            '另：本数据为实时抓取，58 列表每次返回条数会变，'
            '参考带不可复现到个位数，请勿把它当成可反复引用的行情指标。'),
    }


def negotiation_brief(city, address, rent, area_m2, district=None, affordability=None):
    """生成谈判证据包（纯数据，话术由 LLM 生成）。
    rent: 房东报价(元/月)；area_m2: 面积。两者缺一则无法定位价格位置。
    affordability: scoring.solve_rent_limits 的输出（盈亏平衡月租等）。
      两条线分工明确：58 参考带回答"这个区大致什么量级"（背景，口径粗）；
      承受力上限回答"你最多能付多少"（天花板，可当硬约束）。
      **两者都不是"你该先出多少"**——参考带不可比所以不能反推开价，
      天花板是你自己的底线所以更不能一开口就报出去。"""
    bench = rent_benchmark(city, district)
    brief = {'城市': city, '地址': address, '报价': rent, '面积': area_m2,
             '行情分布': bench, '行情参考带': None, '行情口径声明': None,
             '价格位置': None, '可承受月租上限': None, '上限口径': None,
             '筹码': [], '承受力': affordability}

    band = None
    if bench:
        band = bench['参考带']
        brief['行情参考带'] = f'{band[0]}~{band[1]} 元/㎡/月'
        brief['行情口径声明'] = bench['可比性声明']
        brief['价格位置'] = f'同区在租挂牌参考带 {band[0]}~{band[1]} 元/㎡/月（{bench["样本数"]} 个样本）'
    if band and rent and area_m2:
        lo, hi = band
        user_unit = rent / area_m2
        brief['用户单价'] = round(user_unit, 1)
        if user_unit > hi:
            brief['价格位置'] = (
                f'报价 {user_unit:.0f} 元/㎡/月，高于同区参考带 {lo}~{hi} 的上沿。'
                f'⚠️ 但倍数差更可能说明两者不是同类铺子（参考带含食堂档口/仓库/楼上等），'
                f'不能直接读成"贵了 {user_unit / hi:.1f} 倍"')
        elif user_unit < lo:
            brief['价格位置'] = (f'报价 {user_unit:.0f} 元/㎡/月，低于同区参考带 {lo}~{hi} 的下沿，'
                               f'价格本身有竞争力（参考带口径粗，此结论仅供方向参考）')
        else:
            brief['价格位置'] = (f'报价 {user_unit:.0f} 元/㎡/月，落在同区参考带 {lo}~{hi} 内'
                               f'（参考带口径粗，落在带内不等于价格合理）')

    # 承受力上限：唯一按本铺流水与成本结构算出来的数。
    # ⚠️ 它是"最多能付多少"，不是"该先出多少"——旧版叫"建议目标价"，
    # 筹码跟着写成"先出 60,400 元/月"，等于教用户一开口就把天花板报给房东。
    from engine.scoring import PAYBACK_LIMIT_MONTHS
    be = (affordability or {}).get('盈亏平衡月租')
    cap = (affordability or {}).get('回本达标月租上限')
    if be is None and affordability:
        brief['可承受月租上限'] = None
        brief['上限口径'] = '免租也亏损，谈判救不了'
    elif be:
        brief['可承受月租上限'] = cap or be
        brief['上限口径'] = ('按本铺流水与成本结构反解，非市场行情'
                             + (f'；取 {PAYBACK_LIMIT_MONTHS} 个月回本上限，'
                                f'比只求不亏的 {be:,} 元更严' if cap and cap < be else '；取盈亏平衡线'))
    else:
        brief['可承受月租上限'] = None
        brief['上限口径'] = ('缺承受力数据（未做评分测算），只能给同区参考带；'
                          '参考带到区不到商圈、业态混杂，不可直接当目标价')

    # 结构化筹码（规则引擎产出，LLM 负责组织成话术）
    chips = brief['筹码']
    if bench:
        chips.append(f'同区在租挂牌 {bench["样本数"]} 个样本，参考带 '
                     f'{band[0]}~{band[1]} 元/㎡/月——⚠️ 只能当"这个区大致什么量级"的背景，'
                     f'不能当报价依据：{bench["疑似非同类业态样本数"]} 个样本标题含'
                     f'食堂档口/仓库/办公等非同类业态关键词')
        chips.append('⚠️ 行情可比性声明（必须原样转达用户，不许省略）: ' + bench['可比性声明'])
        chips.append('参考带样本标题（判断可比性用，请自己看一眼这些是不是同类铺子）: '
                     + ' ｜ '.join(f"{s['单价']:.0f}元/㎡·{s['面积']:.0f}㎡·{s['标题']}"
                                  for s in bench['最低5样本'])
                     + ' ‖ 高端: '
                     + ' ｜ '.join(f"{s['单价']:.0f}元/㎡·{s['面积']:.0f}㎡·{s['标题']}"
                                  for s in bench['最高5样本']))
    ceiling = brief['可承受月租上限']
    if ceiling:
        chips.append(f'🚪 你的天花板: 月租最高只能到 {ceiling:,} 元（{brief["上限口径"]}）。'
                     f'⚠️ 这是"最多能付"不是"先出这个价"，开价必须留出余地，'
                     f'别一开口就把天花板报给房东')
        if rent and rent > ceiling:
            chips.append(f'谈判真正的锚是差额: 房东要 {rent:,.0f}，你最多只能付 {ceiling:,}，'
                         f'中间 {rent - ceiling:,.0f} 元/月的缺口必须让他降，'
                         f'降不下来就是谈不成，不是你出价不够诚意')

    if affordability:
        if be is None:
            free_np = affordability.get('免租月净利')
            chips.append(f'⛔ 承受力红线: 这个铺即便免租也只有月净利 ¥{free_np:,}——亏损不在租金，'
                         f'在客流或成本结构，谈价救不回来，建议换铺或重做客流测算')
        else:
            chips.append(f'承受力上限: 只要求不亏，月租不能超过 {be:,} 元'
                         + (f'；还要求 {PAYBACK_LIMIT_MONTHS} 个月内回本，则上限收紧到 {cap:,} 元'
                            f'（比"不亏线"再低 {be - cap:,} 元/月）' if cap and cap < be else '')
                         + '（按你的流水与成本结构反解，非市场行情）')
            if band and rent and area_m2 and be / max(area_m2, 1) < band[0]:
                chips.append(f'⚠️ 承受力与行情量级冲突: 你的盈亏平衡线折合 '
                             f'{be / max(area_m2, 1):.0f} 元/㎡/月，低于同区参考带下沿 {band[0]}——'
                             f'说明按这个区的行情租就是亏的，要么压到平衡线以下，要么放弃')
            if rent and rent > be:
                chips.append(f'🚫 当前报价 {rent:,.0f} 元 已超盈亏平衡线 {rent - be:,.0f} 元，照签即亏；'
                             f'这是你跟房东摊牌最硬的一句话')
            elif rent:
                chips.append(f'✅ 承受力校验: 当前报价 {rent:,.0f} 元 在盈亏平衡线 {be:,} 元 以内，'
                             f'安全垫 {be - rent:,.0f} 元/月，能扛得住租金上涨')

    chips += [
        '要 15-30 天免租装修期（行业惯例，房东接受度高）',
        '承诺签约 3 年换取首年租金 5-8% 折扣',
        '租金年递增条款压到 3% 以内（餐饮租约常见坑是 5-8% 递增）',
        '明确物业费/水电过户/广告位使用费由谁承担',
        '争取"同等条件优先续租权"写进合同',
    ]
    return brief


if __name__ == '__main__':
    import json
    b = negotiation_brief('宁波', '海曙区天一广场', 12000, 30, district='海曙')
    print(json.dumps(b, ensure_ascii=False, indent=2, default=str))
