# -*- coding: utf-8 -*-
"""校准产物：按品牌锚点的**可辨识性判定** + 收缩后的最终锚点
================================================================
本脚本把两个诊断结论固化为可被引擎读取的产物：

诊断 I  —— P 由竞品密度驱动，不是品牌力指标
    回归 P = a + b·D  →  b = −0.00665 (p=7.1e-4)
    加入 own_S 后 own_S 系数 p≈1（完全不显著）
    反事实：个体/杂牌 own_S 1.0→2.5，P 中位 0.7639→0.8882
            蜜雪 own_S 2.5→1.0，P 中位 0.6352→0.4106
    而实际观测 个体/杂牌(0.7639) > 蜜雪(0.6430)，即品牌力只有一半的一方
    P 反而更高 → P 高不是品牌力，是"位置对手弱"

诊断 II —— D×P 的方差由商圈主导，品牌效应微弱
    R²(仅商圈 2 参数) = 0.6946
    R²(仅品牌 9 参数) = 0.0795
    ΔR²(商圈之上再加品牌) = 0.041
    同品牌跨商圈极差：蜜雪 4.58x、沪上阿姨 4.61x、CoCo 4.02x

由此得到本脚本的**核心设计决定**：
--------------------------------------------------------------
【决定 1】P_REF **不**按品牌标定 —— 因为不可辨识
    若强行按品牌给 P_REF，等于把"该品牌门店恰好开在哪"写进参数。
    改用**统一 P_REF**（全样本中位），品牌差异只通过 own_S 进入分母竞争项。

【决定 2】REF_DP 也**不**按品牌标定 —— 因为品牌 R² 仅 0.0795
    且品牌与商圈混淆严重。按品牌标定的 REF_DP 实质是"商圈锚点"，
    换城市即失效，对用户（新商圈找铺）是有害的。
    保留统一 REF_DP。

【决定 3】真正按品牌进入引擎的是 **own_S（已有）** 与
    **品牌流量弹性系数 brand_uplift**（本脚本新增，见下）。

【决定 4】引擎需要新增**自适应半径 / 商圈类型识别**，
    因为商圈效应（R²=0.69）远大于品牌效应（R²=0.08）。
    这才是"同一地址对不同品牌分别成立"的正确解法：
    → 不是给品牌不同锚点，而是让评分为**具体商圈**校准。

brand_uplift 的构造（这是 C 真正可落地的部分）
--------------------------------------------------------------
商圈效应占主导，但**同商圈内**品牌间的 D×P 中位数差异仍可提取。
方法：对每个品牌，计算其门店 D×P 相对于**同商圈中位**的比值（品牌相对溢价）：

    uplift_b = median over stores of ( DP_store / DP_median(该店商圈) )

再收缩到 1.0：
    uplift_b_shrunk = 1 + w·(uplift_b − 1),  w = n/(n+K)

这个量是**商圈内比较**得出的，自动消除了商圈混淆，
是当前样本下唯一可辨识的品牌效应度量。
"""
import csv
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

os.environ.setdefault('REALTIME', '0')
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

SHRINK_K = 5.0
MIN_N_UPLIFT = 3          # uplift 需要 n>=3 才可信（比锚点更严格，因是比值）
UPLIFT_CLAMP = (0.80, 1.25)   # 收缩后的合理区间，防止小样本噪声外溢


def med(xs):
    xs = sorted(x for x in xs if x is not None)
    n = len(xs)
    if n == 0:
        return float('nan')
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def main():
    try:
        sys.stdout.reconfigure(errors='replace')
    except Exception:
        pass

    # 读入已产出的逐店明细（含 D/P/P_adj，无需重算 Huff，零 API）
    recs = []
    with open(HERE / 'anchor_by_brand_detail.csv', encoding='utf-8-sig',
              newline='') as f:
        for r in csv.DictReader(f):
            recs.append(dict(名称=r['名称'], 品牌=r['品牌'], 商圈=r['商圈'],
                             own_S=float(r['own_S']), D=float(r['D']),
                             P=float(r['P']), P_adj=float(r['P_adj']),
                             DP=float(r['D×P']),
                             low_ev=(r['低证据点'] == 'Y')))

    use = [x for x in recs if not x['low_ev']]
    print('=' * 100)
    print('按品牌锚点 —— 可辨识性判定与最终产物')
    print('=' * 100)
    print(f'样本 {len(recs)} 家，清理后 {len(use)} 家（剔除低证据点）\n')

    # ---------- 1. 商圈内品牌相对溢价（uplift）----------
    byshang = defaultdict(list)
    for x in use:
        byshang[x['商圈']].append(x['DP'])
    shang_med = {s: med(v) for s, v in byshang.items()}

    print('=' * 100)
    print('【1】品牌相对溢价 uplift = DP_门店 / DP_同商圈中位')
    print('=' * 100)
    print('  理由: 商圈效应占 D×P 方差 69.5%，品牌仅 8.0%；')
    print('        只有"同商圈内"的比较才剔除了混淆，是可辨识的品牌信号。\n')

    for x in use:
        m = shang_med.get(x['商圈'])
        x['uplift'] = (x['DP'] / m) if m and m > 0 else None

    groups = defaultdict(list)
    for x in use:
        groups[x['品牌']].append(x)

    print(f'  {"品牌":<16}{"n":>3}{"uplift原始":>12}{"w":>7}'
          f'{"uplift收缩":>12}{"是否进引擎":>11}')
    print('  ' + '-' * 96)

    uplift_out = {}
    for b, g in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        us = [x['uplift'] for x in g if x['uplift'] is not None]
        raw = med(us) if us else float('nan')
        n = len(us)
        w = n / (n + SHRINK_K)
        shr = 1.0 + w * (raw - 1.0) if raw == raw else 1.0
        lo, hi = UPLIFT_CLAMP
        clamped = min(hi, max(lo, shr))
        ok = n >= MIN_N_UPLIFT
        uplift_out[b] = dict(
            n=n, uplift_raw=round(raw, 4) if raw == raw else None,
            uplift=round(clamped, 4), weight=round(w, 4), reliable=ok,
            own_S=g[0]['own_S'],
        )
        flag = '✅ 进引擎' if ok else '— 回落到 1.0'
        print(f'  {b:<16}{n:>3}'
              f'{(f"{raw:.4f}" if raw == raw else "n/a"):>12}'
              f'{w:>7.3f}{clamped:>12.4f}{flag:>11}')

    rel = {b: v for b, v in uplift_out.items() if v['reliable']}
    print(f'\n  n≥{MIN_N_UPLIFT} 的品牌 {len(rel)} 个，覆盖 '
          f'{sum(v["n"] for v in rel.values())} 家门店')
    if len(rel) >= 2:
        vals = [v['uplift'] for v in rel.values()]
        print(f'  uplift 范围 [{min(vals):.4f}, {max(vals):.4f}]  '
              f'（1.0 = 同商圈中位水平）')
        print('\n  排序（同商圈内相对强弱）:')
        for b, v in sorted(rel.items(), key=lambda kv: -kv[1]['uplift']):
            bar = '█' * max(1, int(abs(v['uplift'] - 1.0) * 200))
            print(f'    {b:<16} {v["uplift"]:.4f}  {bar}')

    # ---------- 2. 为什么不按品牌标定锚点 ----------
    print()
    print('=' * 100)
    print('【2】判定：锚点不按品牌标定（附证据）')
    print('=' * 100)
    print('  P_REF 不按品牌:')
    print('    回归 P = a + b·D + c·own_S  →  c 的 p ≈ 1（own_S 无增量解释力）')
    print('    反事实: 个体/杂牌 own_S 1.0→2.5, P 中位 0.7639→0.8882')
    print('            蜜雪冰城 own_S 2.5→1.0, P 中位 0.6352→0.4106')
    print('    观测事实: 个体/杂牌 P(0.7639) > 蜜雪 P(0.6430)，')
    print('              但两者品牌力相差 2.5 倍 → P 高来自"对手弱"而非品牌')
    print('  REF_DP 不按品牌:')
    print('    R²(仅商圈,2参数)=0.6946  vs  R²(仅品牌,9参数)=0.0795')
    print('    同品牌跨商圈极差: 蜜雪 4.58x / 沪上阿姨 4.61x / CoCo 4.02x')
    print('    → 品牌锚点实质是商圈锚点，换城市即失效')
    print('  结论: 统一锚点 + 品牌通过 own_S/uplift 进入，')
    print('        商圈差异通过"自适应半径/商圈识别"解决（另一任务）。')

    # ---------- 3. 产出 ----------
    g_dp = med([x['DP'] for x in use])
    g_p = med([x['P_adj'] for x in use if 0 < x['P'] < 1.0])
    g_p_raw = med([x['P'] for x in use if 0 < x['P'] < 1.0])

    payload = dict(
        version=2,
        method='brand_uplift_within_district',
        note=('锚点不按品牌标定（不可辨识）；品牌通过 own_S 与 '
              'uplift（同商圈内相对溢价）进入引擎。'
              'uplift 只作用于流水估算的品牌调整，不改变 Huff 结构。'),
        global_=dict(REF_DP=round(g_dp, 4), P_REF=round(g_p, 4),
                     P_REF_unadj=round(g_p_raw, 4),
                     n_total=len(recs), n_used=len(use)),
        district_median_DP={s: round(v, 4) for s, v in shang_med.items()},
        shrink_K=SHRINK_K, min_n_uplift=MIN_N_UPLIFT,
        uplift_clamp=list(UPLIFT_CLAMP),
        anchor_by_brand=dict(
            REF_DP=False,
            P_REF=False,
            reason='identifiability_failure: district R2=0.6946 >> brand R2=0.0795',
        ),
        brands=uplift_out,
    )

    dst = HERE / 'brand_uplift.json'
    dst.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                   encoding='utf-8')
    print(f'\n已保存: {dst}')

    csv_dst = HERE / 'brand_uplift_detail.csv'
    with open(csv_dst, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['名称', '品牌', '商圈', 'own_S', 'D', 'P', 'D×P',
                    '商圈中位D×P', 'uplift', '低证据点'])
        for x in recs:
            w.writerow([x['名称'], x['品牌'], x['商圈'], x['own_S'],
                        round(x['D'], 2), round(x['P'], 4),
                        round(x['DP'], 3),
                        round(shang_med.get(x['商圈'], float('nan')), 3),
                        round(x['uplift'], 4) if x.get('uplift') else '',
                        'Y' if x['low_ev'] else ''])
    print(f'已保存: {csv_dst}')


if __name__ == '__main__':
    main()
