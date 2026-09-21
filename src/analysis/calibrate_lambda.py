# -*- coding: utf-8 -*-
"""
calibrate_lambda.py —— Huff 模型距离衰减系数 λ 代理标定脚本
================================================================
方法（答辩口径）:
  拿不到品牌方真实流水，用公开可见的"外卖月售单量"作为经营表现代理变量。
  对每个候选 λ，计算各门店的 Huff 捕获份额 P_j：

      P_j = (S_j / d0^λ) / ( S_j/d0^λ + Σ_{k≠j} S_k / (d_jk + d0)^λ )

  含义：把门店 j 所在位置视为一个需求点，该店对自身点位的捕获份额——
  竞品越近、吸引力越强，分走的份额越多。

  然后计算 P_j 与外卖月售的 Spearman 秩相关（对量纲偏误稳健），
  取相关系数最高的 λ 作为标定值。

输入 CSV（utf-8-sig，列名固定）:
  名称,经度,纬度,外卖月售,品牌(可选),吸引力系数(可选)

  - 外卖月售: 美团+饿了么月售之和（手动抄录即可）
  - 吸引力系数: 品牌引力 S_j。不给则用 brands.csv 品牌系数表；
    两者都没有则 S=1（退化为纯距离竞争，可作基线对照）

品牌系数表 brands.csv（可选）:
  品牌,系数
  蜜雪冰城,2.5
  古茗,2.0
  ...

用法:
  python src/analysis/calibrate_lambda.py stores.csv
  python src/analysis/calibrate_lambda.py stores.csv --brands brands.csv
  python src/analysis/calibrate_lambda.py stores.csv --lam-min 1.0 --lam-max 3.0 --step 0.1 --d0 50

输出:
  - 控制台：λ 网格 × 相关系数表 + 最优 λ
  - calibration_result.csv：完整网格结果
  - 若装有 matplotlib：calibration_curve.png 相关性曲线
"""
import argparse
import csv
import math
import sys
from pathlib import Path


# ---------------------------------------------------------------
# 基础工具（自包含，不依赖项目其他模块，方便单独运行）
# ---------------------------------------------------------------
def haversine(lng1, lat1, lng2, lat2):
    """两点球面距离（米）"""
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _rank(values):
    """秩次（并列取平均秩）"""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def pearson(x, y):
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(x, y))
    vx = sum((a - mx) ** 2 for a in x)
    vy = sum((b - my) ** 2 for b in y)
    if vx <= 0 or vy <= 0:
        return 0.0
    return cov / math.sqrt(vx * vy)


def spearman(x, y):
    """Spearman 秩相关 = 秩次上的 Pearson"""
    return pearson(_rank(x), _rank(y))


# ---------------------------------------------------------------
# 数据读取
# ---------------------------------------------------------------
def load_stores(path):
    stores = []
    with open(path, encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            name = (row.get('名称') or '').strip()
            if not name or name.startswith('#'):
                continue
            s = {
                'name': name,
                'lng': float(row['经度']),
                'lat': float(row['纬度']),
                'sales': float(row['外卖月售']),
                'brand': (row.get('品牌') or '').strip(),
                's_override': (row.get('吸引力系数') or '').strip(),
            }
            stores.append(s)
    return stores


def load_brands(path):
    table = {}
    with open(path, encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            b = (row.get('品牌') or '').strip()
            if b and not b.startswith('#'):
                table[b] = float(row['系数'])
    return table


def assign_attractiveness(stores, brand_table):
    """确定每家店的 S_j。优先级: 手填吸引力系数 > 品牌系数表 > 1.0。
    返回 (S 列表, 是否使用了品牌信息)"""
    S, used_brand = [], False
    for s in stores:
        if s['s_override']:
            S.append(float(s['s_override']))
            used_brand = True
        elif s['brand'] and s['brand'] in brand_table:
            S.append(brand_table[s['brand']])
            used_brand = True
        else:
            S.append(1.0)
    return S, used_brand


# ---------------------------------------------------------------
# Huff 捕获份额
# ---------------------------------------------------------------
def capture_shares(stores, S, lam, d0):
    """对每个 λ，返回各店捕获份额列表"""
    n = len(stores)
    shares = []
    for j in range(n):
        own = S[j] / (d0 ** lam)
        comp = 0.0
        for k in range(n):
            if k == j:
                continue
            d = haversine(stores[j]['lng'], stores[j]['lat'],
                          stores[k]['lng'], stores[k]['lat'])
            comp += S[k] / ((d + d0) ** lam)
        shares.append(own / (own + comp) if (own + comp) > 0 else 0.0)
    return shares


# ---------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description='Huff λ 代理标定')
    ap.add_argument('stores', help='门店 CSV（名称,经度,纬度,外卖月售,品牌,吸引力系数）')
    ap.add_argument('--brands', help='品牌系数表 CSV（品牌,系数）', default=None)
    ap.add_argument('--lam-min', type=float, default=1.0)
    ap.add_argument('--lam-max', type=float, default=3.0)
    ap.add_argument('--step', type=float, default=0.1)
    ap.add_argument('--d0', type=float, default=50.0, help='最小等效距离(米)')
    ap.add_argument('-o', '--out', default='calibration_result.csv')
    args = ap.parse_args()

    # Windows GBK 控制台兼容：特殊符号打印不崩溃
    try:
        sys.stdout.reconfigure(errors='replace')
    except Exception:
        pass

    stores = load_stores(args.stores)
    if len(stores) < 10:
        print(f'⚠️ 样本量 {len(stores)} 太小，建议 ≥ 30 家再下结论（本次结果仅供参考）')
    print(f'读取门店 {len(stores)} 家，d0={args.d0}m')

    brand_table = load_brands(args.brands) if args.brands else {}
    S, used_brand = assign_attractiveness(stores, brand_table)
    print(f'品牌引力: {"已启用（品牌表/手填系数）" if used_brand else "未启用（S=1 基线）"}')

    sales = [s['sales'] for s in stores]

    # λ 网格扫描：启用品牌 vs S=1 基线 两组对照
    grid = []
    lam = args.lam_min
    while lam <= args.lam_max + 1e-9:
        grid.append(round(lam, 2))
        lam += args.step

    rows = []
    for lam in grid:
        p_brand = capture_shares(stores, S, lam, args.d0)
        sp_b = spearman(p_brand, sales)
        pe_b = pearson([math.log(max(p, 1e-9)) for p in p_brand],
                       [math.log(max(v, 1e-9)) for v in sales])
        p_flat = capture_shares(stores, [1.0] * len(stores), lam, args.d0)
        sp_f = spearman(p_flat, sales)
        rows.append({'lambda': lam, 'spearman_品牌引力': sp_b,
                     'pearson_log_品牌引力': pe_b, 'spearman_纯距离基线': sp_f})

    # 输出
    best = max(rows, key=lambda r: r['spearman_品牌引力'])
    best_f = max(rows, key=lambda r: r['spearman_纯距离基线'])
    print(f"\n{'λ':>5} {'Spearman(品牌)':>14} {'Pearson-log(品牌)':>17} {'Spearman(基线)':>14}")
    for r in rows:
        mark = ' ◀ 最优' if r is best else ''
        print(f"{r['lambda']:>5.1f} {r['spearman_品牌引力']:>14.3f} "
              f"{r['pearson_log_品牌引力']:>17.3f} {r['spearman_纯距离基线']:>14.3f}{mark}")

    print('\n===== 结论 =====')
    print(f"最优 λ = {best['lambda']}（Spearman = {best['spearman_品牌引力']:.3f}）")
    print(f"纯距离基线最优 λ = {best_f['lambda']}（Spearman = {best_f['spearman_纯距离基线']:.3f}）")
    delta = best['spearman_品牌引力'] - best_f['spearman_纯距离基线']
    if used_brand:
        print(f"品牌引力带来的相关性提升: {delta:+.3f}"
              f"（{'正向，品牌项有效' if delta > 0.02 else '不显著，考虑检查品牌系数来源'}）")
    if best['spearman_品牌引力'] < 0.3:
        print('⚠️ 最优相关性仍偏弱(<0.3)：外卖月售受运营水平噪音影响大，'
              '建议改用稳健性声明（λ 取文献值 2，展示 λ∈[1.5,2.5] 结论稳定）')

    out = Path(args.out)
    with open(out, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f'\n网格结果已保存: {out.resolve()}')

    # 可选：画相关性曲线
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei']
        plt.rcParams['axes.unicode_minus'] = False
        xs = [r['lambda'] for r in rows]
        plt.figure(figsize=(8, 4.5))
        plt.plot(xs, [r['spearman_品牌引力'] for r in rows], 'o-', label='品牌引力模型')
        plt.plot(xs, [r['spearman_纯距离基线'] for r in rows], 's--', label='纯距离基线(S=1)')
        plt.axvline(best['lambda'], color='gray', ls=':', alpha=0.6)
        plt.xlabel('λ（距离衰减系数）')
        plt.ylabel('Spearman 秩相关（捕获份额 vs 外卖月售）')
        plt.title(f'λ 代理标定（n={len(stores)}）最优 λ={best["lambda"]}')
        plt.legend()
        plt.tight_layout()
        png = out.with_suffix('.png')
        plt.savefig(png, dpi=150)
        print(f'相关性曲线已保存: {png.resolve()}')
    except ImportError:
        print('(未安装 matplotlib，跳过曲线图；pip install matplotlib 后可自动生成)')


if __name__ == '__main__':
    main()
