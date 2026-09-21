# -*- coding: utf-8 -*-
"""road_uplift.py —— UPLIFT v7 的**步行路网口径**重标（v8）
==========================================================
为什么要有这个脚本
------------------------------------------------------------------
2026-09-20 引擎把距离口径从**直线（haversine）**换成**步行路网距离**
（高德步行规划，按铺位冻结在 `data/road_distance.db`），锚点 REF_DP / P_REF
已随之重标。而 UPLIFT 是在 `expand_sample` 的**直线口径**上标定的
（`share_fast` 用 `Grid.within` 的 haversine）⇒ 两处口径不一致（红线 2）。

本脚本把 UPLIFT v7 整条链**原样搬过来，只换距离口径**：

    ① 载入与商圈锚定      → 复用 `expand_sample.load()` / `ANCHOR_MAX_M`
    ② D / P / DP_blind    → 同式，但距离走**路网**（`data.road`，冻结库优先）
    ③ 收缩 / clamp / 分级 / bootstrap CI
                          → **逐字复用 `recalibrate_uplift_v3.calibrate`**
    ④ 产出                 → `brand_uplift_v3_road.json` + 对照报告

⚠️ 保证"同一套规则"的做法：**import 而不是抄**。
   clamp、SHRINK_K、MIN_N_UPLIFT、USE_MIN_N、TIER1_N、boot seed 全部来自
   `calibrate_brand_uplift` / `recalibrate_uplift_v3`，本脚本不重写任何一项。

⚠️ 距离口径的取证与留痕（红线 4）
   · 粗筛半径 = `radius × COARSE`（与引擎 `query_pois` 的 COARSE 同一个常量）
   · 路网库未命中的点**逐点回退直线并计数**；回退占比会写进报告与产物
   · 抓取断点续传：已入库的 pair 不再请求（可安全中断重跑）

用法
------------------------------------------------------------------
  # 干跑（只跑 N 个商圈的店，用来验证代码、不烧配额）
  python src/analysis/road_uplift.py --frac 0.005
  # 全量
  python src/analysis/road_uplift.py --frac 1.0
  # 只做对照（不算路网，纯本地、零 API）
  python src/analysis/road_uplift.py --mode straight
"""
import argparse
import json
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(HERE))

# —— 复用，绝不重写 ——
import expand_sample as ES                                             # noqa: E402
from calibrate_brand_uplift import (med, SHRINK_K, MIN_N_UPLIFT,       # noqa: E402
                                    UPLIFT_CLAMP)
from recalibrate_uplift_v3 import (calibrate, USE_MIN_N, SELF,         # noqa: E402
                                   BOOT_SEED, TIER1_N)
from engine.brands import brand_attractiveness                          # noqa: E402
from engine.scoring import _COARSE                                      # noqa: E402
from data import road                                                   # noqa: E402
from data.query import haversine                                        # noqa: E402

L = []


def p(s=''):
    print(s, flush=True)
    L.append(str(s))


# ---------------------------------------------------------------- 路网查询
FB = {'n': 0, 'demand': 0, 'share': 0}          # 直线回退计数（分用途记）


def fetch_store_walk(store, grids, tea_grid):
    """把**该店 5 个类目的粗筛候选合并成一批**去取步行距离。

    ⚠️ 为什么合并（这是本脚本能跑完的关键）：`/v3/distance` 的 origins 一次收
       100 个点。实测每店 5 类目合计候选**中位 56 / P90 152** —— 合并后**多数店
       1 次调用**就够了；若按类目各调一次，调用数直接 ×5（实测 110 次/22 店
       → 合并后约 22~30 次/22 店）。这是"取数成本"与"口径正确"两不误的做法。

    返回 (cand_by_cat, walk)：walk 为 {(qlng,qlat): meters}，只含真正取到的点。
    """
    cand = {}
    seen, orgs = set(), []
    for cat, g in list(grids.items()) + [('奶茶', tea_grid)]:
        lst = g.within(store['lng'], store['lat'], int(ES.RADIUS * _COARSE))
        cand[cat] = lst
        for _n, x, y, _d in lst:
            k = (road.q(x), road.q(y))
            if k not in seen:
                seen.add(k)
                orgs.append((x, y))
    walk = road.fetch_and_store((store['lng'], store['lat']), orgs)
    return cand, walk


def _road_points(cand_list, walk, lng, lat, radius, tag):
    """按**步行**距离精筛。取不到路网距离的点回退直线并计入 FB（红线 4：出声）。"""
    out = []
    for name, x, y, _ds in cand_list:
        k = (road.q(x), road.q(y))
        w = walk.get(k)
        if w is None:
            w = haversine(lng, lat, x, y)       # 取数失败 → 回退直线，留痕
            FB['n'] += 1
            FB[tag] += 1
        if w <= radius:
            out.append((name, x, y, w))
    return out


def road_demand(cand, walk, lng, lat):
    """D = 0.8×(学校+办公+社区) + 0.2×商圈，**步行 500m 口径**。"""
    n_a = sum(len(_road_points(cand[c], walk, lng, lat, ES.RADIUS, 'demand'))
              for c in ('学校', '办公', '社区'))
    n_b = len(_road_points(cand['商圈'], walk, lng, lat, ES.RADIUS, 'demand'))
    return 0.8 * n_a + 0.2 * n_b


def road_share(cand, walk, lng, lat, own_S, lam=2.0, d0=50.0):
    """Huff 捕获份额，竞争者权重用**步行距离**（跳过自己）。"""
    own = own_S / (d0 ** lam)
    comp = 0.0
    for name, x, y, d in _road_points(cand['奶茶'], walk, lng, lat,
                                      ES.RADIUS, 'share'):
        if abs(x - lng) < 1e-6 and abs(y - lat) < 1e-6:
            continue
        _, s_k = brand_attractiveness(name)
        comp += s_k / ((d + d0) ** lam)
    return own / (own + comp) if (own + comp) > 0 else 1.0


def straight_demand(grids, lng, lat):
    return ES.demand_fast(grids, lng, lat)


def straight_share(tea_grid, lng, lat, own_S):
    return ES.share_fast(tea_grid, lng, lat, own_S)


# ---------------------------------------------------------------- 主流程
def run(mode, frac, seed, out_name):
    p('=' * 100)
    p('UPLIFT v7 —— 步行路网口径重标（v8）')
    p('=' * 100)
    p(f'模式 {mode} ｜ 商圈抽样 frac={frac} seed={seed}')
    p(f'粗筛系数 _COARSE={_COARSE}（radius×{_COARSE} 直线预筛，与引擎同源）')

    tea, grids, shang = ES.load()
    p(f'本地库：奶茶 POI {len(tea)} 条 ｜ 商圈 POI {len(shang)} 条')

    stores = []
    for n, lng, lat in tea:
        b, s = brand_attractiveness(n)
        stores.append(dict(name=n, lng=lng, lat=lat, brand=b or SELF,
                           own_S=s, identified=bool(b)))
    n_id = sum(1 for x in stores if x['identified'])
    p(f'品牌归属：识别 {n_id} 家 / {len(set(x["brand"] for x in stores if x["identified"]))} 品牌'
      f' ＋「{SELF}」{len(stores) - n_id} 家')

    sg = ES.Grid(shang)
    for x in stores:
        best, bd = None, 1e9
        for n, sx, sy, d in sg.within(x['lng'], x['lat'], ES.ANCHOR_MAX_M):
            if d < bd:
                bd, best = d, n
        x['district'] = best
    anchored = [x for x in stores if x['district']]
    p(f'锚定到 ≤{ES.ANCHOR_MAX_M}m 内商圈 POI：{len(anchored)} 家 '
      f'（{len(set(x["district"] for x in anchored))} 个代理商圈）')

    if frac < 1.0:
        dists = sorted(set(x['district'] for x in anchored))
        rnd = random.Random(seed)
        keep = set(rnd.sample(dists, max(1, int(round(len(dists) * frac)))))
        anchored = [x for x in anchored if x['district'] in keep]
        p(f'★ 抽样：保留 {len(keep)} 个商圈 → 门店 {len(anchored)} 家')

    tea_grid = ES.Grid(tea)

    # ---------- D / P / DP_blind（每店 1 批路网取数，两阶段共用）----------
    t0 = time.time()
    n_calls0 = road.calls()['n']
    for i, x in enumerate(anchored, 1):
        if mode == 'straight':
            x['D'] = straight_demand(grids, x['lng'], x['lat'])
            x['P'] = straight_share(tea_grid, x['lng'], x['lat'], x['own_S'])
            pb = straight_share(tea_grid, x['lng'], x['lat'], 1.0)
        else:
            cand, walk = fetch_store_walk(x, grids, tea_grid)
            x['D'] = road_demand(cand, walk, x['lng'], x['lat'])
            x['P'] = road_share(cand, walk, x['lng'], x['lat'], x['own_S'])
            pb = road_share(cand, walk, x['lng'], x['lat'], 1.0)
        x['DP'] = x['D'] * x['P']
        x['DP_blind'] = x['D'] * pb
        x['low_ev'] = (x['D'] < ES.LOW_EV[0] and x['P'] > ES.LOW_EV[1])
        if i % 200 == 0 or i == len(anchored):
            p(f'   D/P/DP_blind … {i}/{len(anchored)}  {time.time() - t0:.0f}s '
              f'｜API 调用 {road.calls()["n"]}（本段 {road.calls()["n"] - n_calls0}）'
              f' 失败 {road.calls()["fail"]} 回退 {FB["n"]}')
    p(f'   D/P/DP_blind 完成，用时 {time.time() - t0:.0f}s'
      f'，API {road.calls()["n"] - n_calls0} 次')

    byd = defaultdict(list)
    for x in anchored:
        byd[x['district']].append(x)
    use = [x for x in anchored
           if len(byd[x['district']]) >= USE_MIN_N and not x['low_ev']]
    p(f'商圈门槛 n≥{USE_MIN_N} 且剔低证据点 → 采用 {len(use)} 家')

    # ---------- ⑤b 品牌盲残差 ----------
    med_blind = {d: med([x['DP_blind'] for x in v]) for d, v in byd.items()}
    for x in use:
        m = med_blind.get(x['district'])
        x['resid'] = (x['DP_blind'] / m) if m and m > 0 else None

    groups = defaultdict(list)
    for x in use:
        groups[x['brand']].append(x)
    out = {}
    for b, g in groups.items():
        vals = [x['resid'] for x in g if x['resid'] is not None]
        r = calibrate(vals)
        if r:
            r['own_S'] = g[0]['own_S']
            out[b] = r
    feed = {b: v for b, v in out.items() if v['tier'] != 'TIER3'}
    p(f'标定品牌 {len(out)} 个（进引擎 {len(feed)}）')

    # ---------- 落盘 ----------
    payload = dict(
        version=8,
        method='brand_blind_residual_within_proxy_district',
        distance='walking_road_network (amap /v3/distance type=3, frozen in data/road_distance.db)',
        supersedes=('brand_uplift_v3.json (v7, haversine)'
                    if mode != 'straight' else None),
        note=('v8 = v7 的规则**逐字不变**（品牌盲残差 / K=5 收缩 / TIER1 免 clamp / '
              '同 proxy district 中位），**只把距离口径从直线换成步行路网**。'),
        params=dict(anchor_max_m=ES.ANCHOR_MAX_M, use_min_n=USE_MIN_N,
                    shrink_K=SHRINK_K, min_n_uplift=MIN_N_UPLIFT,
                    uplift_clamp=list(UPLIFT_CLAMP), clamp_tier1_exempt=True,
                    boot_seed=BOOT_SEED, tier1_n=TIER1_N,
                    coarse_factor=_COARSE, radius_m=ES.RADIUS),
        sample=dict(n_poi=len(tea), n_stores=len(stores),
                    n_anchored=len(anchored), n_used=len(use),
                    n_districts=len(set(x['district'] for x in anchored)),
                    frac=frac, seed=seed, mode=mode),
        coverage=dict(api_calls=road.calls()['n'], api_fail=road.calls()['fail'],
                      straight_fallback=FB['n'], fallback_demand=FB['demand'],
                      fallback_share=FB['share'],
                      road_pairs=int(road.stats()),
                      note=('straight_fallback = 路网库未命中而回退直线的**点数**；'
                            '非 0 时该产物为混口径，不得直接采用')),
        brands=out,
    )
    dst = HERE / out_name
    dst.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    p(f'已保存 {dst.name}')

    rep = HERE / '_road_uplift_report.txt'
    rep.write_text('\n'.join(L), encoding='utf-8')
    p(f'已保存 {rep.name}')
    return payload


def compare(payload):
    """与在跑的 v7（brand_uplift_v3.json）逐品牌对照。"""
    v7 = json.loads((HERE / 'brand_uplift_v3.json').read_text(encoding='utf-8-sig'))
    a, b = v7.get('brands') or {}, payload.get('brands') or {}
    p('')
    p('=' * 100)
    p('对照：v7（直线口径） vs v8（步行路网口径）')
    p('=' * 100)
    p('%-16s %8s %8s %9s %7s %7s' % ('品牌', 'v7', 'v8', 'Δ%', 'n7', 'n8'))
    rows = []
    for brand in sorted(set(a) | set(b)):
        x, y = a.get(brand), b.get(brand)
        if not x or not y:
            continue
        v7u, v8u = x.get('uplift'), y.get('uplift')
        if v7u in (None, 0) or v8u is None:
            continue
        d = (v8u - v7u) / v7u * 100
        rows.append((abs(d), brand, v7u, v8u, d, x.get('n'), y.get('n'),
                     x.get('tier'), y.get('tier')))
    for _, brand, v7u, v8u, d, n7, n8, t7, t8 in sorted(rows, reverse=True):
        flag = ' ★同一档' if t7 == t8 and t7 != 'TIER3' else ''
        print('%-16s %8.4f %8.4f %+8.2f%% %6d %6d  %s→%s%s'
              % (brand, v7u, v8u, d, n7, n8, t7, t8, flag))
    if rows:
        ds = sorted(r[0] for r in rows)
        print()
        print('共 %d 个品牌可比 ｜ |Δ| 中位 %.2f%% ｜ P90 %.2f%% ｜ 最大 %.2f%%'
              % (len(rows), ds[len(ds) // 2], ds[int(len(ds) * 0.9)], ds[-1]))
        tier_moved = [r[1] for r in rows if r[7] != r[8]]
        print('分级发生变化的品牌：', tier_moved or '无')
        biased = [r[1] for r in rows if r[3] != r[2] and (
            (r[4] > 0) == (r[2] > 1.0)) and abs(r[4]) > 3]
        print('系统性偏向（同向且 >3%%）的品牌：', biased or '无')
    return rows


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', default='road', choices=('road', 'straight'))
    ap.add_argument('--frac', type=float, default=1.0)
    ap.add_argument('--seed', type=int, default=20260920)
    ap.add_argument('--out', default='brand_uplift_v3_road.json')
    ap.add_argument('--compare', action='store_true')
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    pl = run(a.mode, a.frac, a.seed, a.out)
    if a.compare:
        compare(pl)
