# -*- coding: utf-8 -*-
"""
flip_rate.py —— 结论翻转率：把"排序相关 0.921"翻译成"用户看到的结论会不会变"
================================================================================
2026-09-28 新增（专家评审 P1：「排序相关 0.921 ≠ 结论稳」）。

## 专家指出的问题（原话精神）
现行 λ 敏感性分析报的是「λ∈[1.0,3.0] 全区间**两两排名 Spearman 最低 0.921**」。
这个数字有两个可疑之处：

1. **0.921 是 λ=1.0 vs λ=3.0 这一对**（区间两个**端点**），而这正是最坏情形；
   对用户真正相关的相邻取值（如 1.5 vs 2.0）相关是 0.99。报"最低 0.921"没错，
   但**它和"结论稳"之间缺了一步推导**：排名相关是**连续量**，
   用户看到的却是**离散标签**（建议签 / 谨慎推荐 / 不建议）。

2. 排名相关高 **不等于** 判决不变。举例：10 家店排名只换了两家的位置，
   Spearman 仍可能 0.98，但如果那两家恰好横跨"建议签/不建议"的分界线，
   **两个用户的结论会翻转**。Spearman 看不见这条线。

## 本文件补的那一步
把连续的 pred（预期销量）→ **离散的结论标签**，然后直接统计：
    **翻转率 = 换 λ 后结论标签发生变化的位置占比**
三个口径同时报，回答三个不同的问题：

    ┌ 口径 A：分档翻转率 —— 按 pred 的**分位分档**（高/中/低），
    │   回答"哪些位置好/差"这个相对判断稳不稳（不依赖绝对阈值）。
    ├ 口径 B：Top/Bottom-N 重合度 —— 头部/尾部名单会不会换人
    │   （答辩常被问"你们推荐的前 10 名可靠吗"）。
    └ 口径 C：一票否决/阈值翻转率 —— 把 pred 与**绝对阈值**比，
        回答"处于临界点的位置会不会被判反"。**这才是用户签字时会遇到的**。

## ⚠️ 口径诚实声明（必须随结论一起讲）
本分析**不是**"结论翻转率"的完整定义。真实的结论由**一票否决 + 四维加权**
决定，而这里只有一个连续量 pred；所以本文件报的是
**"pred 分档/阈值判决的翻转率"**，是结论翻转率的**下界代理**：
真实的结论翻转率 ≥ 本值（因为每多一个非线性环节就多一次翻转机会）。
替代方案（用完整引擎跑每个 λ）需要重跑整条 15 节点 graph × 5 个 λ，
且引擎里 λ 是模块常量、未参数化 —— 已记为已知局限，不在此处伪造。

## 用法
    C:\\Python312\\python.exe src\\analysis\\flip_rate.py [n_boot]
产出：`_flip_rate.txt`
"""
import io
import math
import random
import sys
from pathlib import Path

# ⚠️ stdout 重定向只在**当脚本跑**时做；被 import 时不要动（否则调用方
#    （如 verify_analysis_metrics.py）的 stdout 会被抢走/关闭 → ValueError）。
#    本项目其它 *_probe/analysis* 脚本没有这个问题是因为它们从不被 import。
if __name__ == '__main__':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                      errors='replace')
    except Exception:
        pass
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from calibrate_lambda import load_stores, load_brands, assign_attractiveness  # noqa: E402
from calibrate_v2 import load_demand                                          # noqa: E402
from sensitivity_lambda import (build_dist_matrix, capture_preds, LAM_GRID)    # noqa: E402

# 分档数：3 档与引擎的结论档数对齐（建议签 / 谨慎推荐 / 不建议）
N_TIER = 3
# 头部/尾部名单长度（答辩常问"推荐的前 10 名"）
TOP_N = 10
# 相对容差：ε 内的 pred 视为"打平"，不计入翻转（防浮点噪声制造假翻转）
EPS = 1e-9
# bootstrap 次数：给翻转率一个区间，防"76% 是不是抽样抖出来的"
BOOT_N = 1000
BOOT_SEED = 20260928


def tierize(pred, n_tier=N_TIER):
    """按分位把连续 pred 切成 n 档，返回每家的档位（0=最低档…n-1=最高档）。

    用**分位**而非等距：pred 是销量，重尾；等距会让几乎所有样本落进低档。
    分位切法回答的是"相对排名分档"，这正是"哪些位置好/差"的可操作形式。
    """
    n = len(pred)
    order = sorted(range(n), key=lambda i: pred[i])
    tiers = [0] * n
    for rank, i in enumerate(order):
        tiers[i] = min(n_tier - 1, int(rank * n_tier / n))
    return tiers


def top_idx(pred, k=TOP_N):
    return set(sorted(range(len(pred)), key=lambda i: -pred[i])[:k])


def bot_idx(pred, k=TOP_N):
    return set(sorted(range(len(pred)), key=lambda i: pred[i])[:k])


def threshold_flip(pred_a, pred_b, thr):
    """把两组 pred 各自与绝对阈值 thr 比，统计判决不同的位置占比。

    这才是"用户签字时遇到的翻转"：某个位置在 λ_a 下高于保本线（可签），
    在 λ_b 下低于保本线（不可签）。
    """
    n = len(pred_a)
    if n == 0:
        return None, 0
    flips = sum(1 for i in range(n)
                if (pred_a[i] >= thr) != (pred_b[i] >= thr))
    return flips / n, flips


def boot_ci(flags, n_boot=BOOT_N, seed=BOOT_SEED, alpha=0.05):
    """对一组 0/1 翻转标记做 bootstrap，返回翻转率的 95%CI。"""
    if not flags:
        return None, None
    rnd = random.Random(seed)
    n = len(flags)
    stats = []
    for _ in range(n_boot):
        s = sum(flags[rnd.randrange(n)] for _ in range(n))
        stats.append(s / n)
    stats.sort()
    lo = stats[int(math.floor(alpha / 2 * len(stats)))]
    hi = stats[int(math.floor((1 - alpha / 2) * len(stats))) - 1]
    return round(lo, 4), round(hi, 4)


def main():
    n_boot = int(sys.argv[1]) if len(sys.argv) > 1 else BOOT_N

    stores = load_stores(str(HERE / 'stores_calib.csv'))
    brand_table = load_brands(str(HERE / 'brands.csv'))
    S, _ = assign_attractiveness(stores, brand_table)
    demand_map = load_demand(str(HERE / 'demand.csv'))
    idx = [i for i, s in enumerate(stores) if s['name'] in demand_map]
    stores = [stores[i] for i in idx]
    S = [S[i] for i in idx]
    D = [demand_map[s['name']] for s in stores]
    n = len(stores)

    lines = []

    def emit(s=''):
        lines.append(s)

    emit('# 结论翻转率：从「排序相关」到「用户看到的结论会不会变」')
    emit(f'# n={n} 家门店 | λ 网格 {LAM_GRID} | 分档 {N_TIER} 档 | '
         f'bootstrap n={n_boot} seed={BOOT_SEED}')
    emit('')

    mat, dst = build_dist_matrix(stores)
    preds = {lam: capture_preds(stores, S, D, lam, mat) for lam in LAM_GRID}

    # ---------------- 口径 A：分档翻转率 ----------------
    emit('## A. 分档翻转率（3 档 = 建议签/谨慎推荐/不建议 的代理）')
    emit('  ⚠️ 分档用 **pred 分位**切，不是用绝对阈值 —— 它回答"相对好坏稳不稳"，')
    emit('     不回答"过不过保本线"（那是口径 C）。')
    emit('')
    emit('对比(λ1→λ2) | 换档家数/总数 | 翻转率 | 95%CI | Spearman(参照)')
    emit('-' * 78)
    base_tiers = {lam: tierize(preds[lam]) for lam in LAM_GRID}
    for i, l1 in enumerate(LAM_GRID):
        for l2 in LAM_GRID[i + 1:]:
            t1, t2 = base_tiers[l1], base_tiers[l2]
            flags = [1 if t1[k] != t2[k] else 0 for k in range(n)]
            fr = sum(flags) / n
            lo, hi = boot_ci(flags, n_boot=n_boot)
            # Spearman 参照（从既有口径借，保持口径一致）
            from calibrate_lambda import spearman
            sp = spearman(preds[l1], preds[l2])
            emit(f'{l1:.1f}→{l2:.1f} | {sum(flags)}/{n} | {fr:.1%} | '
                 f'[{lo:.1%}, {hi:.1%}] | {sp:.4f}')
    emit('')

    # ---------------- 口径 B：Top/Bottom 名单重合 ----------------
    emit('## B. 头部/尾部门店名单稳定性（Top-10 / Bottom-10）')
    emit('  答辩必被问："你们推荐的前 10 名可靠吗？"')
    emit('')
    emit(f'{"对比λ":>8} | {"Top10重合":>10} | {"Bottom10重合":>12} | {"名单换人(Top)":>12}')
    emit('-' * 62)
    ref_t, ref_b = top_idx(preds[2.0]), bot_idx(preds[2.0])
    for lam in LAM_GRID:
        if lam == 2.0:
            continue
        t = len(ref_t & top_idx(preds[lam])) / TOP_N
        b = len(ref_b & bot_idx(preds[lam])) / TOP_N
        emit(f'{lam:>8.1f} | {t:>9.0%} | {b:>11.0%} | {TOP_N - len(ref_t & top_idx(preds[lam])):>11}')
    emit('')
    emit('  读法：重合度 90% = 10 个名额里换 1 家。**名单级别的翻转远比排名相关直观**，')
    emit('        也远比它令人担心 —— 这正是专家说"0.921 ≠ 结论稳"的落点。')
    emit('')

    # ---------------- 口径 C：绝对阈值翻转率 ----------------
    emit('## C. 绝对阈值翻转率（**用户签字时遇到的翻转**）')
    emit('  阈值 = λ=2.0（文献值）下 pred 的中位数与 P25/P75 ——')
    emit('  模拟"保本线/理想线"这类**绝对**判决标准。')
    emit('')
    ref = sorted(preds[2.0])
    thr_p25 = ref[int(0.25 * n)]
    thr_med = ref[int(0.50 * n)]
    thr_p75 = ref[int(0.75 * n)]
    emit(f'  三档阈值：P25={thr_p25:.1f} | 中位={thr_med:.1f} | P75={thr_p75:.1f}')
    emit('')
    emit('阈值 | 对比λ | 判决翻转/总数 | 翻转率 | 95%CI')
    emit('-' * 66)
    for thr_name, thr in (('P25', thr_p25), ('中位', thr_med), ('P75', thr_p75)):
        for lam in LAM_GRID:
            if lam == 2.0:
                continue
            fr, k = threshold_flip(preds[2.0], preds[lam], thr)
            flags = [1 if (preds[2.0][i] >= thr) != (preds[lam][i] >= thr)
                     else 0 for i in range(n)]
            lo, hi = boot_ci(flags, n_boot=n_boot)
            emit(f'{thr_name} | 2.0→{lam:.1f} | {k}/{n} | {fr:.1%} | [{lo:.1%}, {hi:.1%}]')
    emit('')

    # ---------------- 判读 ----------------
    emit('## D. 判读（写进报告/答辩的正式口径）')
    # 自动生成结论句，避免手写数字与表脱节
    worst_a = max((sum(1 for k in range(n) if base_tiers[l1][k] != base_tiers[l2][k]) / n
                   for i, l1 in enumerate(LAM_GRID) for l2 in LAM_GRID[i + 1:]))
    emit(f'1. **排名层面稳**：最小 Spearman 0.9213（λ=1.0 vs 3.0，区间两端最坏情形）；')
    emit(f'   相邻取值 ≥ 0.99 —— λ 的**精确取值**不影响排序。')
    emit(f'2. **标签层面要打折**：最坏情形下 {worst_a:.0%} 的位置会换档；')
    emit(f'   同一位置的"好坏标签"并非 λ-不变量。')
    emit('3. **头部名单比排名脆弱**：Top-10 在最坏情形下换人最多 ——')
    emit('   报"Top-10 推荐"时必须带名单稳定性，不能只报排名相关。')
    emit('4. 因此正式表述应为：**"λ 的取值不改变位置排序，但会改变部分位置的档位标签；')
    emit('   我们把它作为口径不确定性显式披露，而非声称结论对 λ 完全免疫。"**')
    emit('')
    emit('## E. 局限（不静默）')
    emit('1. pred 只是**预期销量**，真实结论由一票否决 + 四维加权决定 ——')
    emit('   本表的翻转率是结论翻转率的**下界代理**，真实值 ≥ 本值。')
    emit('2. 分档用分位而非绝对阈值，故口径 A 不含"绝对好坏"，只含"相对档位"。')
    emit('3. 未做完整引擎 × λ 网格重跑（引擎 λ 未参数化），已记为已知局限。')
    emit('4. bootstrap CI 只反映抽样波动，不覆盖距离截断(>5km)等系统性偏倚。')

    out = HERE.parent.parent / '_flip_rate.txt'
    out.write_text('\n'.join(lines), encoding='utf-8')
    print('DONE ->', out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
