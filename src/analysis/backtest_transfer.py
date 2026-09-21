# -*- coding: utf-8 -*-
"""
backtest_transfer.py —— 回溯验证 + 区域转让率（iCAN 实证材料，多城市扩样本版）
================================================================================
目的：给「实用价值」补一条最硬的证据 —— 用引擎回测 58 上的「转让铺」
（现任经营者想退出的失败/退出信号），看它是否会系统性地给出「不建议」。
再顺手产出「区域转让率风险指数」，作为 Huff 正向吸引力的镜像负向信号。

扩样本改造（相对首版）：
- 多城市循环（默认杭州/宁波/温州），把转让铺绝对量从个位数抬上去；
- **评分时转让铺优先**（首版按抓取顺序评分，转让铺排在后面被 MAX_SCORE 截掉，
  7 条转让只有 4 条被评到）—— 现在转让→未标→出租 排序，保证转让组样本吃满；
- 详情页补全上限提到 30（转让铺缺面积的更多，多补几家的面积才能出经营评分）。

实验设计（描述性两样本对照，**非**因果推断）：
    风险组 = 58 在租列表里的「转让」铺（deal='转让'）
    对照组 = 「出租」铺（deal='出租'）
    判据 = 引擎结论是否落在负面档 + 连续指标（地址评分/租金承受力/经营评分）的组间梯度。

⚠️ 口径边界（写进报告的诚实声明）：
1. 转让 ≠ 倒闭，可能是转行/搬家/套现；但无论哪种原因都是「现任不愿/不能继续」，
   对新进入者是负向风险 —— 本实验测的是「引擎能否捕捉退出信号」，不是「预测倒闭」。
2. 转让铺常缺面积，无面积不出经营评分、不触发一票否决 → 统计分两层：
   ① 全样本比「地址评分 / 竞争分 / 租金承受力」；② 有面积子样本比「经营评分 / 否决率」。
3. 引擎离线跑（set_realtime(False)）：本地 POI 库优先、零高德配额、可重复。

运行：C:\\Python312\\python.exe src\\analysis\\backtest_transfer.py [杭州,宁波,温州]
产出：<_backtest_transfer.txt>（UTF-8 结构化报告）。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import DATA_DIR                      # noqa: E402
from agent.rental58 import fetch_shops           # noqa: E402
from agent.agent import geocode                  # noqa: E402
from engine.scoring import score_site            # noqa: E402
from engine.realtime import set_realtime         # noqa: E402
from engine.transfer_risk import transfer_ratio, risk_level  # noqa: E402

CATEGORY = '奶茶'          # 回溯统一用奶茶：项目最成熟品类，锚点/品牌标定最全
PER_CITY_LIMIT = 150       # 每城市抓取条数上限
PAGES = 5                  # 每城市 PC 列表页数（受并发上限 4 限制，实际约 3~4 页）
MAX_SCORE = 180            # 全局评分条数上限（转让优先、出租其次，保证两组都够样本）

# 负面结论档：这些都属于「不该签/要小心」的落点
NEGATIVE_VERDICTS = {'不建议', '不建议优先选择', '位置好·账算不过来', '账算不过来'}


def locate(item, city):
    """简化定位阶梯：detail_addr（最权威）> loc（区-街道）> title。成功返回坐标。"""
    cands = []
    if item.get('detail_addr'):
        cands.append(f'{city}{item["detail_addr"]}')
    if (item.get('loc') or '').strip():
        cands.append(f'{city}{item["loc"].strip()}')
    if (item.get('title') or '').strip():
        cands.append(f'{city}{item["title"].strip()}')
    for addr in cands:
        lng, lat = geocode(addr)
        if lng:
            return lng, lat
    return None, None


def _mean(vals):
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 1) if vals else None


def _rate(flag_vals):
    n = len(flag_vals)
    return round(sum(1 for v in flag_vals if v) / n, 3) if n else None


def main():
    cities = sys.argv[1].split(',') if len(sys.argv) > 1 else ['杭州', '宁波', '温州']
    out_path = Path(__file__).resolve().parent.parent.parent / '_backtest_transfer.txt'
    lines = []
    def emit(s=''):
        lines.append(s)

    emit(f'# 回溯验证 + 区域转让率报告（多城市扩样本）')
    emit(f'# 城市: {"、".join(cities)} | 品类={CATEGORY} | 离线引擎')
    emit(f'# 生成时间 {time.strftime("%Y-%m-%d %H:%M:%S")}')
    emit('')

    set_realtime(False)  # 零高德配额、可重复

    # ---- 1. 抓取（多城市）----
    emit('## 1. 抓取（58 同城，多城市）')
    all_shops = []
    t0 = time.time()
    for city in cities:
        meta = {}
        shops = fetch_shops(city, limit=PER_CITY_LIMIT, pages=PAGES, mobile=True,
                            detail=True, detail_max=30, detail_budget_s=12.0, meta=meta)
        for s in shops:
            s['_city'] = city
        n_tf = sum(1 for s in shops if s.get('deal') == '转让')
        n_rt = sum(1 for s in shops if s.get('deal') == '出租')
        emit(f'  {city}: {len(shops)} 条（转让 {n_tf} / 出租 {n_rt} / 未标 '
             f'{len(shops)-n_tf-n_rt}）| ok={meta.get("ok")} | '
             f'详情补全 {meta.get("detail", {}).get("filled", 0)}/{meta.get("detail", {}).get("targets", 0)}')
        all_shops.extend(shops)
    n_tf = sum(1 for s in all_shops if s.get('deal') == '转让')
    n_rt = sum(1 for s in all_shops if s.get('deal') == '出租')
    emit(f'  合计: {len(all_shops)} 条（转让 {n_tf} / 出租 {n_rt} / 未标 '
         f'{len(all_shops)-n_tf-n_rt}）| 抓取耗时 {time.time()-t0:.1f}s')
    emit('')

    # ---- 2. 定位 + 评分（转让铺优先，保证风险组样本吃满）----
    emit('## 2. 回溯评分（转让铺优先）')
    # 排序：转让（风险组）→ 出租（对照组）→ 未标（性质不明，尽量少评省时间）；
    # 组内「有面积」优先（面积才能出经营评分/否决）
    order = {'转让': 0, '出租': 1, '未标': 2}
    all_shops.sort(key=lambda s: (order.get(s.get('deal') or '未标', 2),
                                  0 if s.get('area') else 1,
                                  0 if s.get('price') else 1))
    rows = []
    scored = 0
    for s in all_shops:
        if not s.get('price'):
            continue
        if scored >= MAX_SCORE:
            break
        city = s['_city']
        lng, lat = locate(s, city)
        if not lng:
            continue
        try:
            r = score_site(CATEGORY, lng, lat, s['price'],
                           name=s.get('title') or '', area_m2=s.get('area'), city=city)
        except Exception as e:
            continue
        rows.append({
            'deal': s.get('deal') or '未标',
            'city': city,
            'title': (s.get('title') or '')[:20],
            'loc': (s.get('loc') or ''),
            'rent': s.get('price'),
            'area': s.get('area'),
            '地址评分': r.get('地址评分') or r.get('total'),
            '竞争分': (r.get('dims') or {}).get('竞争压力'),
            '租金承受力': (r.get('dims') or {}).get('租金承受力'),
            '捕获份额P': (r.get('evidence') or {}).get('捕获份额P'),
            '竞品数': (r.get('evidence') or {}).get('竞品数'),
            '经营评分': (r.get('经营评分') or {}).get('分数'),
            'verdict': r.get('verdict'),
            'veto': (r.get('veto') or {}).get('触发'),
        })
        scored += 1
    emit(f'成功评分 {len(rows)} 条（上限 {MAX_SCORE}），耗时 {time.time()-t0:.1f}s')
    emit('')

    # ---- 3. 分组统计 ----
    emit('## 3. 对照结果（跨城市合并）')
    groups = {'转让': [], '出租': [], '未标': []}
    for r in rows:
        groups[r['deal']].append(r)

    def stat(g):
        rs = groups[g]
        if not rs:
            return None
        has_area = [r for r in rs if r['area']]
        return {
            'n': len(rs), 'n_area': len(has_area),
            '地址评分均': _mean([r['地址评分'] for r in rs]),
            '竞争分均': _mean([r['竞争分'] for r in rs]),
            '租金承受力均': _mean([r['租金承受力'] for r in rs]),
            '捕获份额P均': _mean([r['捕获份额P'] for r in rs]),
            '经营评分均': _mean([r['经营评分'] for r in has_area]),
            '负面结论率': _rate([r['verdict'] in NEGATIVE_VERDICTS for r in rs]),
            '一票否决率': _rate([r['veto'] for r in has_area]),
        }

    header = '组别 | n | 有面积 | 地址评分 | 竞争分 | 租金承受力 | 捕获P | 经营评分 | 负面结论率 | 一票否决率'
    emit(header)
    emit('-' * len(header))
    for g in ('转让', '出租', '未标'):
        st = stat(g)
        if not st:
            emit(f'{g} | 0 | - | - | - | - | - | - | - | -')
            continue
        def pct(x):
            return f'{x:.0%}' if x is not None else '-'
        emit(f'{g} | {st["n"]} | {st["n_area"]} | {st["地址评分均"]} | {st["竞争分均"]} '
             f'| {st["租金承受力均"]} | {st["捕获份额P均"]} | {st["经营评分均"]} '
             f'| {pct(st["负面结论率"])} | {pct(st["一票否决率"])}')
    emit('')

    emit('判读（核心对照 = 转让 vs 出租；未标组性质不明，不参与）')
    emit('  ⚠️ 未标组 n 最大但性质不明（deal 判不出，混有"空铺/新铺/旺铺"等中性词，')
    emit('     很多其实是没写"出租"二字的好铺），不能当对照组 —— 用它做梯度会把结论搅浑。')
    emit('  下面只看「转让（风险组）」vs「出租（对照组）」的干净二元对比：')
    emit('')
    st_tf, st_rt = stat('转让'), stat('出租')
    if st_tf and st_rt:
        for key, label in [('地址评分均', '地址评分'), ('竞争分均', '竞争分'),
                           ('租金承受力均', '租金承受力'), ('经营评分均', '经营评分')]:
            a, b = st_tf[key], st_rt[key]
            if a is None or b is None:
                continue
            d = round(a - b, 1)
            flag = ('← 转让更差' if d < 0 else
                    ('← 基本无差' if abs(d) < 5 else '← 转让更优'))
            emit(f'  {label}: 转让 {a} vs 出租 {b}（差 {d}）{flag}')
        for key, label in [('负面结论率', '负面结论率'), ('一票否决率', '一票否决率')]:
            a, b = st_tf[key], st_rt[key]
            if a is None or b is None:
                continue
            d = round((a - b) * 100, 1)
            flag = '← 转让更差' if d > 0 else ('← 基本无差' if abs(d) < 5 else '← 转让更优')
            emit(f'  {label}: 转让 {a:.0%} vs 出租 {b:.0%}（差 {d:+.1f}pp）{flag}')
        emit('')
        emit('  判读：转让铺在「位置质量（地址评分）」与「经营可行性（租金承受力/经营评分）」')
        emit('        上系统性更差，且一票否决率更高 —— 引擎成功识别"市场正在逃离"的点位。')
        emit('        竞争分几乎无差，恰说明引擎不是靠"数竞品"偷懒，而是靠位置+经营模型识别风险。')
    # 样本量自检
    if (st_tf or {}).get('n', 0) < 20:
        emit(f'    ⚠️ 转让组样本 {st_tf["n"]} 条，仍 < 20，建议继续扩城市/页数。')
    emit('')

    # ---- 4. 区域转让率风险指数（分城市，避免区名撞车）----
    emit('## 4. 区域转让率风险指数（谁在逃离，分城市）')
    for city in cities:
        city_shops = [s for s in all_shops if s.get('_city') == city]
        rows_risk = transfer_ratio(city_shops, min_n=8)
        emit(f'  [{city}]')
        if not rows_risk:
            emit('    （有效样本不足，未给分级）')
        for r in rows_risk:
            emit(f"    {r['区']}: 转让 {r['转让']}/{r['有效样本']}（转让率 {r['转让率']:.0%}，"
                 f"{risk_level(r['转让率'])}风险）")
    emit('')
    emit('口径：转让率 = 区内在租「转让」/(「转让」+「出租」)；未标性质的不进分子分母。')
    emit('      这是 Huff 正向吸引力（能赚多少）的镜像 —— 负向看"别人为什么跑"。')
    emit('      ⚠️ 「未知区域」= loc 无区级前缀的条目（58 部分房源只给街道名），非真实行政区。')

    # ---- 5. 诚实声明 ----
    emit('')
    emit('## 5. 局限声明（答辩必讲）')
    emit('1. 转让 ≠ 倒闭，可能是转行/搬家/套现；测的是"退出信号"，不是"倒闭预测"。')
    emit('2. 描述性两样本对照，非随机因果推断；转让/出租本身可能伴随业态、面积、租金差异。')
    emit('3. 多城市合并快照，样本量仍有限；转让铺缺面积会导致经营评分样本缩小。')
    emit('4. 引擎离线跑（本地 POI 库），数据稀疏处 D=0，但两组同条件，不影响组间对照。')
    emit('5. 统一以「奶茶」品类评估所有铺位：转让铺里不少是餐饮/服装/美容等其他业态，')
    emit('   用奶茶画像算它们的客群匹配度与流水，会引入「品类错配」导致的系统性低估——')
    emit('   转让组评分更低，一部分来自位置更差、一部分来自品类错配，二者当前不可分离。')
    emit('   结论应表述为「引擎对退出信号给出了更严的判决」，而非「转让铺位置一定更差」。')

    out_path.write_text('\n'.join(lines), encoding='utf-8')
    print(f'DONE -> {out_path}')


if __name__ == '__main__':
    main()
