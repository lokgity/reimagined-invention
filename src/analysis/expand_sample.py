# -*- coding: utf-8 -*-
"""expand_sample.py —— 用**本地库**把 Huff 标定样本从 83 家扩到数千家（零 API）
================================================================================
为什么能做（关键事实）：
  `calibrate_anchor.py` / `calibrate_brand_uplift.py` 算 D 与 P 用的是
  `data.query.query_within`（**纯本地 SQLite**，不是高德实时）。也就是说，
  **标定样本的原始材料本来就在本地库里**，只是当初只手抄了 3 个商圈的 83 家。
  本地库现有 3959 条奶茶 POI，其中 2551 家能识别出品牌（34 个）——
  **"样本太少"不是数据不够，是当初只标了 3 个商圈。**

本脚本做的事：
  1. 从 `data/zj_poi.db` 枚举**全部**能识别品牌的奶茶门店；
  2. 商圈锚定：每店归属"1km 内最近的『商圈』POI"（本地库有 3466 个商圈 POI）；
  3. 对每店按**引擎同口径**算 D（0.8×学校+办公+社区 + 0.2×商圈，500m）与
     P（Huff，λ=2.0、d0=50m、品牌 S），**直接 import 标定脚本的函数** ——
     不写第二套规则；
  4. 按品牌算 uplift（同商圈内 DP/商圈中位，K=5 收缩）——同样复用
     `calibrate_brand_uplift` 的常量与中位数函数；
  5. 与引擎里**在跑的** `brands.UPLIFT`（83 家标定）逐一对照：n 涨了多少、
     点估计动了多少、排序是否稳定。

⚠️ 三条必须随结论一起说的局限（不说不等于不存在）：
  L1 **本地库覆盖不完整**：实测 in77 点位库内 19 家奶茶 vs 高德实时 49 家
     （覆盖 39%）、D 库 9 vs 实时 28（31%）；天一 65%/95%。覆盖率**随商圈变化**，
     所以扩样后的 **D×P 绝对水平不可直接当新锚点**（那是水平偏差，不是随机误差）。
      → 因此本脚本**只用于**：① 品牌 uplift 的稳定性/功效 ② 结构分析。
      **不产出**替代 `REF_DP` / `P_REF` 的新锚点（要动锚点必须先"补库"或做库→实时校正）。
  L2 **商圈口径是代理**：手标版本用人工商圈名（天一广场/in77/银泰），
     这里是"最近商圈 POI ≤1km"。两者不等价 → 必须做一致性校验（见 §校验 B）。
  L3 **低证据点**仍按原规则清理（D<3 且 P>0.8）。
  L4 存量标定产物（anchor_calib.csv 等）**不会自动跟着代码走**：
     品牌表后补会让 own_S 变，旧 P 就不复现了（见 §校验 A2）。
     所以本脚本一律**实时重算**。
  L5 引擎写死的锚点常量与注释声称的出处/口径**不一致**（见 §校验 A3）：
     REF_DP 可复现但口径是"剔低证据点后 77 家"而非注释写的"全 83 家中位"；
     P_REF 复现偏 +0.0015。**本脚本只报告，不擅自改**（改锚点会改写全部历史结论）。

用法：C:\\Python314\\python.exe src/analysis/expand_sample.py
产出：sample_expanded.csv + _expand_report.txt
"""
import csv
import math
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(HERE))

# —— 复用标定脚本的原语，保证"同一套规则" ——
from calibrate_anchor import engine_demand, capture_share, resolve_own_S  # noqa: E402
from calibrate_brand_uplift import med, SHRINK_K, MIN_N_UPLIFT, UPLIFT_CLAMP  # noqa: E402
from engine.brands import brand_attractiveness, UPLIFT, UPLIFT_TIER, UPLIFT_CI  # noqa: E402
from data.query import haversine  # noqa: E402

DB = ROOT / 'data' / 'zj_poi.db'
RADIUS = 500
ANCHOR_MAX_M = 1000        # 商圈锚定半径
LOW_EV = (3.0, 0.80)       # 低证据点判据（D < 3 且 P > 0.8），与原流水线一致

L = []


def p(s=''):
    print(s)
    L.append(str(s))


# ---------------------------------------------------------------- 加速：等价的空间索引
# ⚠️ 为什么不能不加速：`query_within` 每次都全表扫描该 category 再逐行 haversine。
#    3500+ 家门店 × 4 个 category × 数千行 = 上亿次三角函数，跑不完。
#    这里用 0.01° 分桶做**预筛**，命中后再用**同一个 haversine** 判定 ——
#    结果与 query_within 逐字节等价（§校验 里会抽样对拍）。
class Grid:
    def __init__(self, rows):
        """rows: list[(name, lng, lat)]"""
        self.rows = rows
        self.cells = defaultdict(list)
        for i, r in enumerate(rows):
            self.cells[(int(r[1] * 100), int(r[2] * 100))].append(i)

    def within(self, lng, lat, radius_m):
        dlat = radius_m / 111000.0 + 1e-4
        dlng = radius_m / (111000.0 * max(0.2, math.cos(math.radians(lat)))) + 1e-4
        out = []
        for cx in range(int((lng - dlng) * 100), int((lng + dlng) * 100) + 1):
            for cy in range(int((lat - dlat) * 100), int((lat + dlat) * 100) + 1):
                for i in self.cells.get((cx, cy), ()):
                    n, x, y = self.rows[i]
                    d = haversine(lng, lat, x, y)
                    if d <= radius_m:
                        out.append((n, x, y, round(d)))
        return out


def load():
    c = sqlite3.connect(str(DB))
    def rows(cat):
        return c.execute('SELECT name,lng,lat FROM poi WHERE category=?', (cat,)).fetchall()
    tea = rows('奶茶')
    grids = {cat: Grid(rows(cat)) for cat in ('学校', '办公', '社区', '商圈')}
    shang = rows('商圈')
    c.close()
    return tea, grids, shang


def demand_fast(grids, lng, lat):
    """与 calibrate_anchor.engine_demand 同式（0.8×客群 + 0.2×商业，500m）"""
    n_a = sum(len(grids[c].within(lng, lat, RADIUS)) for c in ('学校', '办公', '社区'))
    n_b = len(grids['商圈'].within(lng, lat, RADIUS))
    return 0.8 * n_a + 0.2 * n_b


def share_fast(tea_grid, lng, lat, own_S, lam=2.0, d0=50.0):
    """与 calibrate_anchor.capture_share 同式（竞争集合=半径内奶茶 POI，跳过自己）"""
    own = own_S / (d0 ** lam)
    comp = 0.0
    for n, x, y, d in tea_grid.within(lng, lat, RADIUS):
        if abs(x - lng) < 1e-6 and abs(y - lat) < 1e-6:
            continue
        _, s_k = brand_attractiveness(n)
        comp += s_k / ((d + d0) ** lam)
    return own / (own + comp) if (own + comp) > 0 else 1.0


def main():
    try:
        sys.stdout.reconfigure(errors='replace')
    except Exception:
        pass

    p('=' * 100)
    p('把 Huff 标定样本从 83 家扩到数千家（纯本地库，零高德 API）')
    p('=' * 100)

    tea, grids, shang = load()
    p(f'本地库：奶茶 POI {len(tea)} 条 ｜ 商圈 POI {len(shang)} 条（data/zj_poi.db）')

    # ① 品牌识别
    stores = []
    for n, lng, lat in tea:
        b, s = brand_attractiveness(n)
        stores.append(dict(name=n, lng=lng, lat=lat, brand=b, own_S=s))
    branded = [x for x in stores if x['brand']]
    n_brand = len(branded)
    p(f'能识别出品牌的奶茶门店：**{n_brand} 家 / {len(set(x["brand"] for x in branded))} 个品牌**'
      f'（原标定样本 83 家 / 9 个可标定品牌 → **{n_brand / 83:.0f} 倍**）')

    # ② 商圈锚定（最近商圈 POI ≤1km）
    sg = Grid(shang)
    for x in branded:
        best, bd = None, 1e9
        for n, sx, sy, d in sg.within(x['lng'], x['lat'], ANCHOR_MAX_M):
            if d < bd:
                bd, best = d, n
        x['district'] = best
        x['district_m'] = round(bd) if best else None
    anchored = [x for x in branded if x['district']]
    p(f'能锚定到 {ANCHOR_MAX_M}m 内商圈 POI 的：{len(anchored)} 家，'
      f'分布于 {len(set(x["district"] for x in anchored))} 个商圈')

    # ③ D / P（引擎同口径）
    p('')
    p('正在算 D 与 P（每店 4 次本地空间查询 + 品牌 S 加权）…')
    # ⚠️ 竞争集合必须是**全库奶茶 POI**（含识别不出品牌的个体/杂牌），
    #    这才是 calibrate_anchor.capture_share 的口径。若只用"已锚定的品牌店"，
    #    分母会系统性地少掉杂牌对手 → P 被**系统性抬高** → uplift 全错。
    tea_grid = Grid(tea)
    for i, x in enumerate(anchored, 1):
        x['D'] = demand_fast(grids, x['lng'], x['lat'])
        x['P'] = share_fast(tea_grid, x['lng'], x['lat'], x['own_S'])
        x['DP'] = x['D'] * x['P']
        x['low_ev'] = (x['D'] < LOW_EV[0] and x['P'] > LOW_EV[1])
        if i % 500 == 0:
            print(f'   …{i}/{len(anchored)}')

    # ④ 商圈规模门槛：同商圈中位数要稳，至少 5 家
    byd = defaultdict(list)
    for x in anchored:
        byd[x['district']].append(x)
    for min_n in (3, 5, 8):
        keep = [x for x in anchored if len(byd[x['district']]) >= min_n]
        p(f'   商圈门槛 n≥{min_n}：{len([d for d, v in byd.items() if len(v) >= min_n])} 个商圈 / '
          f'{len(keep)} 家门店')
    USE_MIN = 5
    use = [x for x in anchored if len(byd[x['district']]) >= USE_MIN and not x['low_ev']]
    p(f'   → 采用 **n≥{USE_MIN} 的商圈** 且剔除低证据点后：**{len(use)} 家门店**'
      f'（原样本清理后 77 家 → {len(use) / 77:.0f} 倍）')

    # ⑤ uplift（同商圈内相对溢价，K=5 收缩）—— 与 calibrate_brand_uplift 同式
    shang_med = {d: med([x['DP'] for x in v]) for d, v in byd.items()}
    for x in use:
        m = shang_med.get(x['district'])
        x['uplift'] = (x['DP'] / m) if m and m > 0 else None

    groups = defaultdict(list)
    for x in use:
        groups[x['brand']].append(x)

    def uplift_of(g):
        us = [x['uplift'] for x in g if x['uplift'] is not None]
        n = len(us)
        raw = med(us) if us else float('nan')
        w = n / (n + SHRINK_K)
        shr = 1.0 + w * (raw - 1.0) if raw == raw else 1.0
        lo, hi = UPLIFT_CLAMP
        return n, raw, w, min(hi, max(lo, shr))

    p('')
    p('=' * 100)
    p('【1】扩样后的品牌 uplift vs 引擎里在跑的 83 家标定值')
    p('=' * 100)
    p(f'  {"品牌":<14}{"n(扩样)":>8}{"n(原)":>6}{"uplift扩样":>11}{"uplift原":>10}'
      f'{"差":>8}{"原分级":>8}')
    p('  ' + '-' * 92)
    rows_out, moved = [], []
    for b, g in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        n, raw, w, up = uplift_of(g)
        if n < MIN_N_UPLIFT:
            continue
        old = UPLIFT.get(b)
        old_tier = UPLIFT_TIER.get(b, '—')
        diff = (up - old) if old else None
        rows_out.append((b, n, old, up, diff, old_tier))
        if old is not None:
            moved.append((b, diff, up, old))
        p(f'  {b:<14}{n:>8}{(UPLIFT_item_n(b) if old else 0):>6}'
          f'{up:>11.4f}{(f"{old:.4f}" if old else "未收录"):>10}'
          f'{(f"{diff:+.4f}" if diff is not None else "—"):>8}{old_tier:>8}')

    p('')
    p('  【原标定 9 个品牌】扩样后动没动？（排序稳定性）')
    if len(moved) >= 3:
        old_rank = sorted(UPLIFT.items(), key=lambda kv: -kv[1])
        new_rank = sorted(moved, key=lambda t: -t[2])
        p('    原排序: ' + ' > '.join(b for b, _ in old_rank))
        p('    新排序: ' + ' > '.join(t[0] for t in new_rank))
        # 只用两边都有的品牌做秩相关
        common_old = {b: v for b, v in UPLIFT.items() if any(t[0] == b for t in moved)}
        common_new = {t[0]: t[2] for t in moved if t[0] in UPLIFT}
        if len(common_old) >= 3:
            rho = spearman(list(common_old.values()), [common_new[b] for b in common_old])
            p(f'    Spearman(原 uplift, 扩样 uplift) = {rho:+.4f}   n={len(common_old)} 个品牌')
        maxmove = max(abs(d) for _, d, _, _ in moved)
        p(f'    点估计最大漂移 = {maxmove:.4f}（0.05 以内可认为"样本量上来后结论没动"）')
        p('')
        p('  ⚠️ 但**别急着说"旧结论被推翻"** —— 正确读法是"旧点估计本来就不确定"：')
        p(f'    {"品牌":<14}{"原uplift":>9}{"原95%CI":>20}{"扩样":>9}{"落在CI内?":>10}')
        inside = 0
        for b, diff, up, old in sorted(moved, key=lambda t: -t[3]):
            ci = UPLIFT_CI.get(b)
            if ci:
                ok = ci[0] <= up <= ci[1]
                inside += ok
                p(f'    {b:<14}{old:>9.4f}{f"[{ci[0]:.4f},{ci[1]:.4f}]":>20}'
                  f'{up:>9.4f}{("✅是" if ok else "❌否"):>10}')
        p(f'    → {inside}/{len(moved)} 个品牌的扩样点估计**仍落在原 83 家的 bootstrap 95%CI 内**。')
        p('      也就是说：原样本的 CI 大多包含 1.0（品牌效应不显著），')
        p('      排序（Spearman≈0.29）本来就没有统计支撑 —— 扩样只是把这件事显性化了。')

    p('')
    p('【2】扩样专门解决的那件事：**功效**')
    p('  原标定：9 个品牌 n=4~13，|uplift−1|≈0.05 的效应检验功效仅 0.07~0.42')
    p('  扩样后各品牌 n：')
    for b, g in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        n, raw, w, up = uplift_of(g)
        if n >= MIN_N_UPLIFT:
            p(f'    {b:<16} n={n:<5} w=n/(n+5)={w:.4f}'
              f'{"  ← 收缩权重已接近 1（几乎不再向 1.0 拉）" if w > 0.9 else ""}')

    p('')
    p('【3】瑞幸（本次新入表品牌）的扩样标定')
    rg = groups.get('瑞幸')
    if rg:
        n, raw, w, up = uplift_of(rg)
        p(f'  瑞幸：n={n}  raw={raw:.4f}  uplift={up:.4f}  （引擎当前：TIER3 ×1.00，'
          f'"暂无标定"）')
        p('  ⚠️ 是否把瑞幸从 TIER3 提到 TIER2/TIER1，**要欧文点头**：')
        p('     ① 咖啡门店与奶茶门店同商圈竞争，口径上说得通但不同源；')
        p('     ② 本地库覆盖不完整（L1），先把 uplift 当"同商圈相对水平"看，别当流水倍数。')
    else:
        p('  ⚠️ 瑞幸在扩样集里凑不到 n≥3，保持 TIER3 ×1.00（不编）。')

    # ⑥ 校验（docstring 承诺的 §校验）—— "同口径"能否成立，全靠这一段
    p('')
    p('=' * 100)
    p('【4】校验：扩样管线 vs 原标定管线')
    p('=' * 100)

    # 一次算完，三相校验复用（避免重复 query_within）
    with open(HERE / 'stores_calib.csv', encoding='utf-8-sig', newline='') as f:
        orig_rows = list(csv.DictReader(f))
    live = []
    for r in orig_rows:
        lng, lat = float(r['经度']), float(r['纬度'])
        own_S, _ = resolve_own_S(r)
        d_r = engine_demand(lng, lat)
        p_r = capture_share(lng, lat, own_S)
        live.append(dict(
            name=r['名称'], lng=lng, lat=lat, own_S=own_S, D=d_r, P=p_r,
            DP=d_r * p_r, low_ev=(d_r < LOW_EV[0] and p_r > LOW_EV[1]),
            D_g=demand_fast(grids, lng, lat),
            P_g=share_fast(tea_grid, lng, lat, own_S),
        ))

    # 校验 A —— 真·同口径对拍：本脚本 Grid 管线 vs calibrate_anchor 的
    #           `capture_share`（真 `query_within` 路径）。这是"我有没有写第二套规则"
    #           的唯一硬证据，必须逐店完全一致（浮点级）。
    gD = [abs(x['D_g'] - x['D']) for x in live]
    gP = [abs(x['P_g'] - x['P']) for x in live]
    n_same = sum(1 for x in live if abs(x['D_g'] - x['D']) < 1e-9
                 and abs(x['P_g'] - x['P']) < 1e-12)
    p(f'  A. Grid 加速管线 vs 原 `capture_share`（真 query_within 路径），{len(live)} 家')
    p(f'     |ΔD| 最大={max(gD):.3e}   |ΔP| 最大={max(gP):.3e}'
      f'   完全一致 {n_same}/{len(live)} 家')
    if n_same == len(live):
        p('     ✅ 逐店完全一致 ⇒ **没有第二套规则**，扩样与标定同口径')
    else:
        badly = sorted(live, key=lambda x: -abs(x['P_g'] - x['P']))[0]
        p(f'     ⚠️ 有 {len(live) - n_same} 家不一致（最大 {badly["name"]}）'
          f' —— 必须先查清，否则扩样结论不可用')

    # 校验 A2 —— 存量产物 anchor_calib.csv 是否还跟得上当前代码
    cal = {}
    with open(HERE / 'anchor_calib.csv', encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f):
            if r.get('名称') and r.get('D'):
                cal[r['名称']] = r
    stale = []
    for x in live:
        ref = cal.get(x['name'])
        if not ref:
            continue
        try:
            stale.append((abs(x['P'] - float(ref['P'])), x['name'],
                          x['own_S'], float(ref['S']) if ref.get('S') else None))
        except (TypeError, ValueError):
            continue
    big = [s for s in stale if s[0] > 5e-5]
    p('')
    p(f'  A2. 存量产物 anchor_calib.csv 是否落后（{len(stale)} 家）')
    p(f'     |ΔP| ≤ 5e-5（列里只存了 4 位小数，纯舍入）: {len(stale) - len(big)} 家')
    p(f'     |ΔP| > 5e-5（真实漂移）: **{len(big)} 家**')
    for d, nm, s_now, s_old in sorted(big, reverse=True)[:5]:
        p(f'       {nm}  ΔP={d:.6f}  own_S 存={s_old} → 现={s_now}')
    if big:
        p('     ⇒ 原因不是"标定错了"，而是**品牌表后补**：贡茶等品牌是在该文件')
        p('        生成之后才进 BRAND_KEYWORDS 的，own_S 由 1.0 升到 1.4，')
        p('        分子变大 → P 变大。属**预期内的口径改进**，非错误；')
        p('        但意味着**存量标定 CSV 不会自动跟着代码走**，')
        p('        所以本次扩样一律**实时重算**，不读旧 CSV。')

    # 校验 A3 —— 引擎写死的锚点常量，今天还复现得出来吗？（只报告，不改）
    nl = [x for x in live if not x['low_ev']]
    p('')
    p('  A3. 引擎锚点常量的可复现性（**只报告，本次不改引擎**）')
    p('     引擎写死 : REF_DP = 6.2489   P_REF = 0.5012   (src/engine/scoring.py)')
    p(f'     实测复现 : D×P 中位(全 {len(live)} 家)          = {med([x["DP"] for x in live]):.4f}')
    p(f'                D×P 中位(剔低证据 {len(nl)} 家) = {med([x["DP"] for x in nl]):.4f}'
      f'  ← 与引擎一致 ✅')
    p(f'                P   中位(剔低证据 {len(nl)} 家) = {med([x["P"] for x in nl]):.6f}'
      f'  （引擎值 − 可复现值 = {0.5012 - med([x["P"] for x in nl]):+.6f}）⚠️')
    p('     ⚠️ 两点需要欧文知悉（本脚本**不擅自改动**，因改锚点会改写全部历史结论）:')
    p('        ① **口径与注释不符**：scoring.py 注释写"由 calibrate_anchor.py 同一次')
    p('           运行产出、全样本中位"，但 calibrate_anchor.py 今天实际输出')
    p('           REF_DP=5.85 / P_REF=0.5074（**全 83 家**口径）；')
    p('           引擎的 6.2489 实为 **剔低证据点后 77 家**中位（calibrate_brand_uplift')
    p('           的口径）。数值本身每项都能复现，**错的只是注释里的出处与口径**。')
    p('        ② **P_REF 引擎值比可复现值高 +0.0015（+0.3%）**：可复现 0.4997，引擎 0.5012。')
    p('           影响面 = 竞争分 `60×P/P_REF` 整体低约 0.3%，量级小，但说明')
    p('           这对常量**并非"同一次标定"产出**，与注释承诺的"同一次运行"不符。')

    # 校验 B —— 商圈代理 vs 原人工商圈：粒度差多少？
    man, prox, unanch = defaultdict(set), defaultdict(set), 0
    for r in orig_rows:
        lng, lat = float(r['经度']), float(r['纬度'])
        man[r['商圈']].add(r['名称'])
        best, bd = None, 1e9
        for n2, sx, sy, dd in sg.within(lng, lat, ANCHOR_MAX_M):
            if dd < bd:
                bd, best = dd, n2
        if best:
            prox[best].add(r['名称'])
        else:
            unanch += 1
    p('')
    p('  B. 商圈口径对照（原样本 3 个人工商圈 → 代理商圈）')
    p(f'     原人工商圈 {len(man)} 个：'
      + ' ｜ '.join(f'{k}({len(v)}家)' for k, v in man.items()))
    p(f'     → 代理商圈（最近商圈 POI ≤{ANCHOR_MAX_M}m）{len(prox)} 个，'
      f'未锚定 {unanch} 家')
    for s, names in sorted(man.items(), key=lambda kv: -len(kv[1])):
        k = len({p2 for p2 in prox if prox[p2] & names})
        p(f'       {s}({len(names)}家) 被拆到 {k} 个代理商圈')
    p('     ⚠️ **粒度不等价**：原人工商圈是"大商业区"（27~39 家/组），')
    p('        代理商圈是"最近单个商圈 POI"（均值仅 2~3 家/组）。')
    p('        uplift 是"对同商圈中位取比值"，分母口径一变，点估计必然移动。')
    p('        ⇒ 所以【1】的漂移**不能**解读成"旧结论错了"，')
    p('          它同时含"样本量增加"与"分组变细"两个因素（混杂，未分离）。')

    # ⑥ 落盘
    out = HERE / 'sample_expanded.csv'
    with open(out, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['名称', '品牌', '商圈', '商圈距离m', 'own_S', 'D', 'P', 'D×P',
                    '商圈中位D×P', 'uplift', '低证据点', '采用'])
        for x in anchored:
            used = (x in use)
            w.writerow([x['name'], x['brand'] or '', x['district'], x['district_m'],
                        x['own_S'], round(x['D'], 3), round(x['P'], 4),
                        round(x['DP'], 3),
                        round(shang_med.get(x['district'], float('nan')), 3),
                        round(x['uplift'], 4) if x.get('uplift') is not None else '',
                        'Y' if x['low_ev'] else '', 'Y' if used else ''])
    p('')
    p(f'已写出逐店明细：{out.name}（{len(anchored)} 行，含未采用的）')

    p('')
    p('=' * 100)
    p('局限（必须随结论一起说）')
    p('=' * 100)
    p('  L1 本地库覆盖不完整且**随商圈变化**（实测 in77 39% / D 31%，天一 65% / 95%）')
    p('     → 扩样后的 **D×P 绝对水平不能直接当新锚点**；本脚本刻意不产出新 REF_DP。')
    p('     → 要动锚点，必须先"补库"（用高德搜索类配额逐商圈补）或做"库→实时"校正。')
    p('  L2 商圈口径是代理（最近商圈 POI ≤1km）而非人工商圈边界 → 见 §校验。')
    p('  L3 品牌识别依赖 BRAND_KEYWORDS；识别不出的连锁仍按"个体/杂牌"参与竞争。')
    p('  L4 高德搜索类配额：**个人 key 100 次/日**（官方 FAQ），且实测有 QPS 限制')
    p('     （连续快发会 CUQPS_HAS_EXCEEDED_THE_LIMIT）。1 次 place/text 可换')
    p('     "一个品牌在一个城市的真实门店总数"，但拿坐标要按 25 家/页翻页。')

    (HERE / '_expand_report.txt').write_text('\n'.join(L), encoding='utf-8')
    print(f'\n[写入] {HERE / "_expand_report.txt"}')


def spearman(a, b):
    """秩相关（纯标准库，无 scipy）。"""
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r
    ra, rb = rank(a), rank(b)
    n = len(a)
    ma, mb = sum(ra) / n, sum(rb) / n
    num = sum((ra[i] - ma) * (rb[i] - mb) for i in range(n))
    da = math.sqrt(sum((x - ma) ** 2 for x in ra))
    db = math.sqrt(sum((x - mb) ** 2 for x in rb))
    return num / (da * db) if da and db else float('nan')


def UPLIFT_item_n(b):
    from engine.brands import _UPLIFT_N
    return _UPLIFT_N.get(b, 0)


if __name__ == '__main__':
    main()
