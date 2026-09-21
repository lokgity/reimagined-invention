# -*- coding: utf-8 -*-
"""
sensitivity_lambda.py —— λ 敏感性（稳健性）分析
==================================================
目的: 证明 λ 取文献值 2.0 不是"拍脑袋"——在文献常用区间 [1.5, 2.5]
（扩展到 [1.0, 3.0]）内, 模型输出的门店相对排序高度稳定,
因此评分结论不依赖于 λ 的精确取值。

方法:
1. 对每个 λ ∈ 网格, 计算 83 家真实门店的预期销量 pred_j = D_j × P_j(λ)
2. 两两 λ 之间计算 pred 排名的 Spearman 相关系数
3. 检查 λ=2.0 与相邻取值的 Top-10 / Bottom-10 门店重合度

判据（答辩口径）:
- 两两 Spearman ≥ 0.9 → 排序对 λ 不敏感, 结论稳健
- Top/Bottom 门店重合度 ≥ 80% → "哪些位置好/差"的结论稳定

用法:
  python src/analysis/sensitivity_lambda.py stores_calib.csv
"""
import csv
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))      # src（v8：要 import data.road）
from calibrate_lambda import (haversine, spearman, load_stores,  # noqa: E402
                              load_brands, assign_attractiveness)
from calibrate_v2 import load_demand  # noqa: E402

LAM_GRID = [1.0, 1.5, 2.0, 2.5, 3.0]
D0 = 50.0
WALK_MAX_M = 5000     # 高德步行规划（type=3）的射程上限，超出必然取不到值


def build_dist_matrix(stores):
    """预取门店两两之间的**步行路网距离**（冻结库优先，0 次重复请求）。

    口径说明（必须随结论一起讲）：
      · 高德步行规划只支持 **5km 内**，超出的对必然取不到值。被截断的都是
        **跨商圈对**（宁波↔杭州 ≈150km、10km 量级），在 λ=2、d0=50m 下的
        Huff 权重 ≤ 1/(10050)² ≈ 1e-8，相对近邻（~1e-4）小 4 个数量级
        ⇒ 数值上惰性；**但截断对数如实打印，不静默**（红线 4）。
      · 路网库未命中的对**逐点回退直线并计数**；回退数 > 0 时本产物为混口径，
        报告里会显著标出（与锚点标定的护栏②同源）。

    返回 (mat, stats)：mat 键为 (min(j,k), max(j,k))。
    """
    from data import road
    n = len(stores)
    mat, cut, miss = {}, 0, 0
    for j in range(n):
        orgs = []
        for k in range(n):
            if k == j:
                continue
            dl = haversine(stores[j]['lng'], stores[j]['lat'],
                           stores[k]['lng'], stores[k]['lat'])
            if dl > WALK_MAX_M:
                continue                     # 超射程，下面统一计数
            orgs.append((stores[k]['lng'], stores[k]['lat']))
        walk = road.fetch_and_store((stores[j]['lng'], stores[j]['lat']), orgs)
        for k in range(n):
            if k == j:
                continue
            key = (min(j, k), max(j, k))
            dl = haversine(stores[j]['lng'], stores[j]['lat'],
                           stores[k]['lng'], stores[k]['lat'])
            if dl > WALK_MAX_M:
                cut += 1
                continue
            if key in mat:
                continue
            w = walk.get((road.q(stores[k]['lng']), road.q(stores[k]['lat'])))
            if w is None:
                miss += 1
                w = dl
            mat[key] = w
    st = {'对数': len(mat), '截断(>5km)': cut, '回退直线': miss,
          'API调用': road.calls()['n'], 'API失败': road.calls()['fail'],
          '冻结库累计': road.stats()}
    print(f'  [距离口径] 步行路网矩阵：取到 {st["对数"]} 对 ｜ '
          f'截断(>5km，权重≤1e-8) {st["截断(>5km)"]} 对 ｜ '
          f'回退直线 {st["回退直线"]} 对 ｜ API {st["API调用"]} 次')
    if st['回退直线']:
        print('  ★ 有回退 —— 混口径，结论需注明')
    return mat, st


def capture_preds(stores, S, D, lam, mat, d0=D0):
    """pred_j = D_j × (S_j/d0^λ) / (S_j/d0^λ + Σ_{k≠j} S_k/(d_jk+d0)^λ)

    `mat` 为 build_dist_matrix 的产物（**步行路网**距离）。
    跨 5km 对不在 mat 中 → 权重 0（其量级 ≤1e-8，已在 build 里计数）。
    """
    n = len(stores)
    pred = []
    for j in range(n):
        own = S[j] / (d0 ** lam)
        comp = 0.0
        for k in range(n):
            if k == j:
                continue
            dd = mat.get((min(j, k), max(j, k)))
            if dd is None:
                continue
            comp += S[k] / ((dd + d0) ** lam)
        p = own / (own + comp) if (own + comp) > 0 else 0.0
        pred.append(D[j] * p)
    return pred


def main():
    try:
        sys.stdout.reconfigure(errors='replace')
    except Exception:
        pass

    stores = load_stores(str(HERE / 'stores_calib.csv'))
    brand_table = load_brands(str(HERE / 'brands.csv'))
    S, _ = assign_attractiveness(stores, brand_table)
    demand_map = load_demand(str(HERE / 'demand.csv'))

    idx = [i for i, s in enumerate(stores) if s['name'] in demand_map]
    stores = [stores[i] for i in idx]
    S = [S[i] for i in idx]
    D = [demand_map[s['name']] for s in stores]
    n = len(stores)
    print(f'样本: {n} 家真实门店（三商圈合并）\n')

    # 0) 距离矩阵（步行路网，冻结库优先）
    print(f'\n=== 距离口径：步行路网（v8）===')
    mat, dst = build_dist_matrix(stores)

    # 1) 各 λ 下的预测值
    preds = {lam: capture_preds(stores, S, D, lam, mat) for lam in LAM_GRID}

    # 2) 两两 λ 排名相关矩阵
    print('=== λ 两两排名 Spearman 相关矩阵 ===')
    header = 'λ\\λ   ' + ''.join(f'{l2:>7.1f}' for l2 in LAM_GRID)
    print(header)
    matrix = []
    for l1 in LAM_GRID:
        row = []
        for l2 in LAM_GRID:
            r = spearman(preds[l1], preds[l2])
            row.append(r)
        matrix.append(row)
        print(f'{l1:>4.1f}  ' + ''.join(f'{r:>7.3f}' for r in row))

    # 非对角线最小值 = 最坏情形下的排名稳定性
    off_diag = [matrix[i][j] for i in range(len(LAM_GRID))
                for j in range(len(LAM_GRID)) if i != j]
    print(f'\n非对角线最小 Spearman = {min(off_diag):.3f}（越接近1越稳健）')

    # 3) λ=2.0 vs 其他取值的 Top/Bottom-10 重合度
    def top_idx(pred, k=10):
        return set(sorted(range(n), key=lambda i: -pred[i])[:k])

    def bot_idx(pred, k=10):
        return set(sorted(range(n), key=lambda i: pred[i])[:k])

    ref = preds[2.0]
    print('\n=== 以 λ=2.0（文献值）为基准的头部/尾部门店稳定性 ===')
    print(f'{"对比λ":>6} {"Top10重合":>10} {"Bottom10重合":>12}')
    overlap_rows = []
    for lam in LAM_GRID:
        if lam == 2.0:
            continue
        t_overlap = len(top_idx(ref) & top_idx(preds[lam])) / 10
        b_overlap = len(bot_idx(ref) & bot_idx(preds[lam])) / 10
        print(f'{lam:>6.1f} {t_overlap:>9.0%} {b_overlap:>11.0%}')
        overlap_rows.append({'对比λ': lam, 'Top10重合': t_overlap,
                             'Bottom10重合': b_overlap})

    # 4) 写出结果
    out = HERE / 'result_sensitivity.csv'
    with open(out, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['λ1', 'λ2', 'Spearman排名相关'])
        for i, l1 in enumerate(LAM_GRID):
            for j, l2 in enumerate(LAM_GRID):
                w.writerow([l1, l2, round(matrix[i][j], 4)])
        w.writerow([])
        w.writerow(['对比λ(vs 2.0)', 'Top10重合', 'Bottom10重合'])
        for r in overlap_rows:
            w.writerow([r['对比λ'], r['Top10重合'], r['Bottom10重合']])
        # 第三块：口径留痕（解析方读到第二块表头即停，不影响既有解析）
        w.writerow([])
        w.writerow(['口径', '值'])
        w.writerow(['距离口径', '步行路网（高德 type=3，冻结于 data/road_distance.db）'])
        w.writerow(['取到对数', dst['对数']])
        w.writerow(['截断(>5km)', dst['截断(>5km)']])
        w.writerow(['回退直线', dst['回退直线']])
        w.writerow(['API调用', dst['API调用']])
    print(f'\n结果已保存: {out.name}')

    # 5) 结论判读
    print('\n=== 判读 ===')
    if min(off_diag) >= 0.9:
        print(f'λ∈[1.0,3.0] 全区间两两排名相关最低 {min(off_diag):.3f} ≥ 0.9')
        print('→ 门店相对排序对 λ 取值不敏感，λ=2.0 文献值可用，结论稳健。')
    else:
        print(f'λ 敏感性偏高（最低相关 {min(off_diag):.3f}），需缩小文献区间或补充实证。')


if __name__ == '__main__':
    main()
