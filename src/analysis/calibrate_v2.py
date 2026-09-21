# -*- coding: utf-8 -*-
"""
calibrate_v2.py —— 需求加权的 Huff λ 标定（完整版模型）
==========================================================
v1 教训: 只用捕获份额 P_j 与月售做相关，得到负相关——因为
销量 = 需求规模 D × 份额 P，商圈中心需求极大但份额被摊薄。

v2 模型: 预期销量_j = D_j × P_j(λ)
  D_j: 周边需求 POI 加权规模（fetch_demand.py 产出）
  P_j(λ) = (S_j/d0^λ) / (S_j/d0^λ + Σ_{k≠j} S_k/(d_jk+d0)^λ)

对 λ 网格搜索 Spearman(预期销量, 外卖月售)。

用法:
  python src/analysis/calibrate_v2.py stores_calib.csv --brands brands.csv
"""
import argparse
import csv
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from calibrate_lambda import (haversine, spearman, load_stores,  # noqa: E402
                              load_brands, assign_attractiveness)


def load_demand(path):
    d = {}
    with open(path, encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f):
            d[r['名称']] = float(r['需求D'])
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('stores')
    ap.add_argument('--brands', default=None)
    ap.add_argument('--demand', default=str(HERE / 'demand.csv'))
    ap.add_argument('--lam-min', type=float, default=1.0)
    ap.add_argument('--lam-max', type=float, default=3.0)
    ap.add_argument('--step', type=float, default=0.1)
    ap.add_argument('--d0', type=float, default=50.0)
    ap.add_argument('-o', '--out', default='calibration_v2_result.csv')
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(errors='replace')
    except Exception:
        pass

    stores = load_stores(args.stores)
    brand_table = load_brands(args.brands) if args.brands else {}
    S, _ = assign_attractiveness(stores, brand_table)
    demand_map = load_demand(args.demand)

    missing = [s['name'] for s in stores if s['name'] not in demand_map]
    if missing:
        print(f'⚠️ {len(missing)} 家缺需求数据，已剔除: {missing[:5]}...')
    idx = [i for i, s in enumerate(stores) if s['name'] in demand_map]
    stores = [stores[i] for i in idx]
    S = [S[i] for i in idx]
    D = [demand_map[s['name']] for s in stores]
    sales = [s['sales'] for s in stores]
    print(f'样本 {len(stores)} 家（需求数据齐全）')

    # D 与月售本身的相关性（需求项单独的含金量）
    print(f'需求D vs 月售 Spearman = {spearman(D, sales):.3f}')

    n = len(stores)
    grid, rows = args.lam_min, []
    while grid <= args.lam_max + 1e-9:
        lam = round(grid, 2)
        pred = []
        for j in range(n):
            own = S[j] / (args.d0 ** lam)
            comp = 0.0
            for k in range(n):
                if k == j:
                    continue
                dd = haversine(stores[j]['lng'], stores[j]['lat'],
                               stores[k]['lng'], stores[k]['lat'])
                comp += S[k] / ((dd + args.d0) ** lam)
            p = own / (own + comp) if (own + comp) > 0 else 0.0
            pred.append(D[j] * p)
        sp = spearman(pred, sales)
        rows.append({'lambda': lam, 'spearman_DxP': sp})
        grid += args.step

    best = max(rows, key=lambda r: r['spearman_DxP'])
    print(f"\n{'λ':>5} {'Spearman(D×P)':>14}")
    for r in rows:
        mark = ' *最优' if r is best else ''
        print(f"{r['lambda']:>5.1f} {r['spearman_DxP']:>14.3f}{mark}")
    print(f'\n===== 最优 λ = {best["lambda"]}（Spearman = {best["spearman_DxP"]:.3f}）=====')

    with open(args.out, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['lambda', 'spearman_DxP'])
        w.writeheader()
        w.writerows(rows)
    print(f'结果已保存: {args.out}')


if __name__ == '__main__':
    main()
