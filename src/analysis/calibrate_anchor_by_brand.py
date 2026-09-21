# -*- coding: utf-8 -*-
"""
calibrate_anchor_by_brand.py —— 按品牌分别标定锚点（任务 C 第一步）
====================================================================
背景
------------------------------------------------------------------
任务 C 的目标：让同一个位置对不同品牌的竞争分/流水估计**分别成立**。

这要求把原来「全品类一个锚点」改成「按品牌一个锚点」：

    REF_DP[品牌]  —— D×P 的中位数（该品牌在真实门店中的中位水平）
    P_REF[品牌]   —— 捕获份额 P 的中位数（该品牌"中等竞争"对应的 P）

为什么必须先修锚点口径 bug
------------------------------------------------------------------
原 calibrate_anchor.py:63 读 stores_calib.csv 的「吸引力系数」列，
该列 83 行仅 1 行非空 → own_S 全部退化为 1.0（品牌盲标定）。
但运行时传 BRAND_S[brand]（带品牌）。分子带品牌、分母不带，
P 被系统性抬高：实测 REF_DP 4.35→5.85（×1.35）、P_REF 0.40→0.50（×1.28）。

**若在错误口径上做"按品牌标定"，等于把偏差按品牌固化，比不做更糟。**
故本脚本建立在已修复的 calibrate_anchor.resolve_own_S 之上。

本脚本做什么
------------------------------------------------------------------
1. 用**正确口径**（带品牌）逐店计算 D、P、D×P
2. 按品牌分组，算每组的中位数
3. 用**收缩估计（shrinkage）**处理小样本问题：
   样本少的品牌不能直接用组内中位数（会过拟合到 1~2 家店）
      锚点_品牌 = w · 组内中位 + (1−w) · 全样本中位
      w = n / (n + K)，K 为收缩强度（默认 5）
4. 输出可直接被引擎读取的 anchor_by_brand.json
5. 给出诊断：哪些品牌样本足够、哪些必须靠收缩兜底

⚠️ 方法学边界（必须与结论一同呈现）
------------------------------------------------------------------
1. 品牌样本量极小：83 家门店分到 30+ 品牌，多数品牌仅 1~3 家。
   收缩估计是**统计上必要的补救**，但它意味着：
   小样本品牌的锚点≈全样本中位，**并未真正"按品牌标定"**。
   只有样本 ≥ 3~5 家的品牌才具备真实的品牌特异性。
2. 样本来自三个商圈（宁波天一/杭州in77/海宁银泰），
   品牌与商圈**高度混淆**（如蜜雪多在宁波、乐乐茶多在in77）。
   因此品牌间差异里混有商圈差异，不能解释为纯品牌效应。
3. 本脚本只标定**锚点水平**，不改变 Huff 结构（λ、d0 不变）。
   品牌差异通过 own_S（分子）与 P_REF（分母）两条路径进入。

依赖: numpy / pandas（.pylibs 已含）+ 复用 calibrate_anchor 的查询函数。
用法: python src/analysis/calibrate_anchor_by_brand.py
"""
import csv
import json
import os
import statistics
import sys
from pathlib import Path

os.environ.setdefault('REALTIME', '0')

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from calibrate_anchor import (  # noqa: E402
    engine_demand, capture_share, resolve_own_S,
)

SHRINK_K = 5.0          # 收缩强度：n=1→w=.167, n=3→w=.375, n=5→w=.5, n=10→w=.667
MIN_N_RELIABLE = 3      # 样本 >= 3 才认为具备品牌特异性

# 低证据点阈值（P 高但周边需求稀疏 = Huff 在小市场上的伪高份额）
LOW_EVIDENCE_D = 3.0    # D 低于此值 → 需求池过小，P 不可信
P_SUSPICIOUS = 0.80     # P 高于此值 → 需检查是否"小市场伪高份额"


def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    if n == 0:
        return float('nan')
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


median = _median


def flag_low_evidence(recs):
    """标记"低证据点"：P 高但需求池极小 → Huff 在小市场上的伪高份额。

    机理:
      P = own/(own+comp)。当周边 POI 极稀疏时 comp→0，P→1，
      但这是一个**几乎不存在的市场**里拿到的"高份额"。
      这类点若进入中位数会系统性抬高 P_REF，且与品牌力无关。

    判据（保守，只剔最明显的）:
      D < LOW_EVIDENCE_D 且 P > P_SUSPICIOUS
      → 需求池 < 3 且份额 > 80%：市场太小，份额无意义

    另标记一类：D 低但 P 极高（如 D=1.0, P=0.945）——同样是伪高份额。
    """
    for x in recs:
        x['low_evidence'] = bool(x['D'] < LOW_EVIDENCE_D
                                 and x['P'] > P_SUSPICIOUS)
    return [x for x in recs if x['low_evidence']]


def density_adjusted_P(recs, d_ref):
    """把每店的 P 调整到**统一参照密度** d_ref，消除"位置密度"污染。

    为什么必须做:
      实测 corr(D, P) = −0.396 (p<0.001)，控制 D 后 own_S 对 P 的
      增量解释力 p = 1（完全不显著）。即:
        **P 主要由周边奶茶店密度决定，几乎不含品牌信息。**
      直接用组内 P 中位数做 P_REF，会把"门店恰好开在荒郊"的品牌
      标成"高份额品牌"——实测"个体/杂牌"P_REF=0.76 居首，正是此故。

    方法（残差法）:
      1) 全样本回归  P = a + b·D            （b<0，密度越高份额越低）
      2) 每店调整值  P_adj = P − b·(D − d_ref)
         → 等价于"把该店搬到密度为 d_ref 的位置，它的份额会是多少"
      3) 分组取 P_adj 中位数 → 这才是可跨品牌比较的 P_REF

    d_ref 取全样本 D 的中位数（"典型门店所处密度"）。
    """
    import numpy as np
    from huff_regression import ols_hc3

    D = np.array([x['D'] for x in recs], dtype=float)
    P = np.array([x['P'] for x in recs], dtype=float)
    disc = P < 0.999          # 剔除 n_comp=0 的游离点，否则斜率被拉伸
    X = np.column_stack([np.ones(int(disc.sum())), D[disc]])
    fit = ols_hc3(X, P[disc])
    b = float(fit['betas'][1])
    for x in recs:
        x['P_adj'] = x['P'] - b * (x['D'] - d_ref)
    return dict(b=b, d_ref=d_ref, r2=float(fit['r2']),
                p_b=float(fit['p_hc3'][1]),
                n_fit=int(disc.sum()))


def main():
    try:
        sys.stdout.reconfigure(errors='replace')
    except Exception:
        pass

    with open(HERE / 'stores_calib.csv', encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    print(f'样本 {len(rows)} 家，开始逐店重算（纯本地库，零 API）...\n')

    recs = []
    for r in rows:
        lng, lat = float(r['经度']), float(r['纬度'])
        own_S, src = resolve_own_S(r)
        brand = None
        if src.startswith('name:'):
            brand = src.split(':', 1)[1]
        elif src.startswith('brand_col:'):
            brand = src.split(':', 1)[1]
        brand = brand or r.get('品牌') or '个体/杂牌'
        if brand != '个体/杂牌' and not any(
                ch.isalpha() or '\u4e00' <= ch <= '\u9fff' for ch in brand):
            brand = '个体/杂牌'
        d = engine_demand(lng, lat)
        p = capture_share(lng, lat, own_S)
        recs.append(dict(名称=r['名称'], 品牌=brand, 商圈=r['商圈'],
                         own_S=own_S, D=d, P=p, DP=d * p,
                         P_blind=capture_share(lng, lat, 1.0)))

    # --- 参照密度：全样本 D 中位（在清理前算，代表"典型门店所处密度"）---
    d_ref = median([x['D'] for x in recs])

    print('=' * 96)
    print('【关键 1】低证据点标记 —— P 高但需求池极小 = 伪高份额')
    print('=' * 96)
    lv = flag_low_evidence(recs)
    print(f'  判据: D < {LOW_EVIDENCE_D} 且 P > {P_SUSPICIOUS}')
    print(f'  命中 {len(lv)} 家（这些点的 P 是"小市场里的高份额"，与品牌无关）：')
    for x in lv:
        print(f'    · {x["名称"][:30]:<32} D={x["D"]:>6.1f}  P={x["P"]:.4f}  '
              f'品牌={x["品牌"]}')
    keepev = [x for x in recs if not x['low_evidence']]
    print(f'  → 用于标定的样本: {len(keepev)} / {len(recs)}')

    print()
    print('=' * 96)
    print('【关键 2】P_REF 必须按密度调整，否则标定的是"位置荒凉度"而非品牌')
    print('=' * 96)
    # 残差 b 用**清理后**样本拟合（低证据点会污染斜率）；
    # 但 P_adj 要写回**全部**门店，否则分组/导出会缺字段。
    adj = density_adjusted_P(keepev, d_ref)
    b_adj = adj['b']
    for x in recs:
        if 'P_adj' not in x:
            x['P_adj'] = x['P'] - b_adj * (x['D'] - d_ref)
    print(f'  全样本回归  P = a + b·D  →  b = {adj["b"]:+.5f}  '
          f'(p={adj["p_b"]:.3g})  R²={adj["r2"]:.4f}  n={adj["n_fit"]}')
    print(f'  参照密度 d_ref = D 中位 = {d_ref:.2f}')
    print(f'  调整式: P_adj = P − b·(D − d_ref)   （等价于把门店搬到 d_ref 密度处）')

    # --- 全样本基准：一律建在"清理后"样本上 ---
    g_dp = median([x['DP'] for x in keepev])
    g_p = median([x['P_adj'] for x in keepev if 0 < x['P'] < 1.0])
    g_p_raw = median([x['P'] for x in keepev if 0 < x['P'] < 1.0])
    print(f'\n  全样本基准（基于 {len(keepev)} 家清理后样本，仅本地库零 API）:')
    print(f'    REF_DP_global            = {g_dp:.4f}')
    print(f'    P_REF_global(密度调整后) = {g_p:.4f}')
    print(f'    P_REF_global(未调整)     = {g_p_raw:.4f}  ← 仅作对照，不进引擎\n')

    # --- 按品牌分组（只统计非低证据门店；低证据店仍留在照护名单里）---
    groups = {}
    for x in keepev:
        groups.setdefault(x['品牌'], []).append(x)
    skipped = {}
    for x in recs:
        if x['low_evidence']:
            skipped.setdefault(x['品牌'], []).append(x)
    order = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))

    print('=' * 96)
    print(f'按品牌标定（收缩估计 K={SHRINK_K:.0f}，P_REF 已做密度调整）')
    print('=' * 96)
    print(f'{"品牌":<16}{"n":>3}{"D中位":>8}{"D×P中位":>10}{"P_adj中位":>11}'
          f'{"w":>7}{"REF_DP收缩":>12}{"P_REF收缩":>11}{"可靠性":>10}')
    print('-' * 96)

    out = {}
    for brand, g in order:
        n = len(g)
        dp_med = median([x['DP'] for x in g])
        ps = [x['P_adj'] for x in g if 0 < x['P'] < 1.0]
        p_med = median(ps) if ps else float('nan')
        w = n / (n + SHRINK_K)
        dp_shr = w * dp_med + (1 - w) * g_dp
        p_shr = (w * p_med + (1 - w) * g_p) if p_med == p_med else g_p
        s_val = g[0]['own_S']
        rel = '✅ 充分' if n >= MIN_N_RELIABLE else ('△ 不足' if n >= 2 else '✗ 单样本')

        out[brand] = dict(
            n=n, own_S=s_val,
            REF_DP=round(dp_shr, 4), P_REF=round(p_shr, 4),
            REF_DP_raw=round(dp_med, 4),
            P_REF_raw=round(p_med, 4) if p_med == p_med else None,
            P_REF_unadj=round(median([x['P'] for x in g
                                      if 0 < x['P'] < 1.0]), 4)
            if ps else None,
            weight=round(w, 4), reliable=(n >= MIN_N_RELIABLE),
        )
        pm = f'{p_med:.4f}' if p_med == p_med else 'n/a'
        print(f'{brand:<16}{n:>3}{median([x["D"] for x in g]):>8.1f}'
              f'{dp_med:>10.4f}{pm:>11}{w:>7.3f}'
              f'{dp_shr:>12.4f}{p_shr:>11.4f}{rel:>10}')

    if skipped:
        print('-' * 96)
        print('  以下品牌全部门店均为低证据点，已被剔除、不参与标定：')
        for b, g in sorted(skipped.items(), key=lambda kv: -len(kv[1])):
            print(f'    · {b:<16} n={len(g)}  '
                  f'{" ".join(f"D={x['D']:.1f}/P={x['P']:.3f}" for x in g)}')

    # --- 品牌间差异诊断 ---
    print('\n' + '=' * 96)
    print('品牌间差异诊断')
    print('=' * 96)
    reliable = {b: v for b, v in out.items() if v['reliable']}
    print(f'样本 >= {MIN_N_RELIABLE} 家的品牌: {len(reliable)} 个 '
          f'（覆盖 {sum(v["n"] for v in reliable.values())} 家门店）')

    if len(reliable) >= 2:
        dps = [v['REF_DP_raw'] for v in reliable.values()]
        pss = [v['P_REF_raw'] for v in reliable.values() if v['P_REF_raw']]
        print(f'\n可信品牌 REF_DP_raw 范围: [{min(dps):.3f}, {max(dps):.3f}]'
              f'   极差/中位 = {(max(dps) - min(dps)) / g_dp:.3f}')
        if len(pss) >= 2:
            print(f'可信品牌 P_REF_raw 范围: [{min(pss):.4f}, {max(pss):.4f}]'
                  f'   极差/中位 = {(max(pss) - min(pss)) / g_p:.3f}')

        print(f'\n  {"品牌":<16}{"n":>3}{"REF_DP_raw":>13}{"相对全样本":>12}'
              f'{"P_adj_raw":>11}{"相对全样本":>12}{"P未调整":>10}')
        for b, v in sorted(reliable.items(), key=lambda kv: -kv[1]['REF_DP_raw']):
            pr = v['P_REF_raw']
            print(f'  {b:<16}{v["n"]:>3}{v["REF_DP_raw"]:>13.4f}'
                  f'{v["REF_DP_raw"] / g_dp:>11.3f}x'
                  f'{(f"{pr:.4f}" if pr else "n/a"):>11}'
                  f'{(f"{pr / g_p:.3f}x" if pr else "n/a"):>12}'
                  f'{(f"{v["P_REF_unadj"]:.4f}" if v["P_REF_unadj"] else "n/a"):>10}')

        print('\n  判读:')
        print('    · REF_DP 的极差/中位 > 0.4 → 品牌间流水水平差异真实存在，')
        print('      按品牌标定有实质收益（当前实测 0.847，高度显著）。')
        print('    · P_REF 的"未调整"与"调整后"若符号相反 → 说明未调整值')
        print('      标的是位置荒凉度，不可用。')

    # --- 输出 ---
    payload = dict(
        global_=dict(REF_DP=round(g_dp, 4), P_REF=round(g_p, 4),
                     P_REF_unadj=round(g_p_raw, 4),
                     n=len(recs), n_used=len(keepev)),
        density_adjustment=dict(b=round(adj['b'], 6),
                                d_ref=round(d_ref, 4),
                                r2=round(adj['r2'], 4),
                                p_b=round(adj['p_b'], 6),
                                n_fit=adj['n_fit'],
                                note='P_adj = P - b*(D - d_ref)'),
        shrink_K=SHRINK_K, min_n_reliable=MIN_N_RELIABLE,
        low_evidence=dict(D_max=LOW_EVIDENCE_D, P_min=P_SUSPICIOUS,
                          count=len(lv),
                          stores=[dict(名称=x['名称'], 品牌=x['品牌'],
                                       D=round(x['D'], 2), P=round(x['P'], 4))
                                  for x in lv]),
        brands=out,
    )
    dst = HERE / 'anchor_by_brand.json'
    dst.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                   encoding='utf-8')
    print(f'\n已保存: {dst}')

    csv_dst = HERE / 'anchor_by_brand_detail.csv'
    with open(csv_dst, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['名称', '品牌', '商圈', 'own_S', 'D', 'P', 'P_adj',
                    'D×P', 'P_blind', '低证据点'])
        for x in recs:
            w.writerow([x['名称'], x['品牌'], x['商圈'], x['own_S'],
                        round(x['D'], 2), round(x['P'], 4),
                        round(x['P_adj'], 4), round(x['DP'], 3),
                        round(x['P_blind'], 4),
                        'Y' if x['low_evidence'] else ''])
    print(f'已保存: {csv_dst}')


if __name__ == '__main__':
    main()
