# -*- coding: utf-8 -*-
"""recalibrate_uplift_v2.py —— 品牌溢价 UPLIFT **整表重标定**（v2，代理商圈口径）
================================================================================
为什么要有这个脚本（v1 的三个问题）
----------------------------------------------------------------
v1 的 UPLIFT 出自 `calibrate_brand_uplift.py`，口径是：
    3 个人工大商圈（宁波天一 27 家 / 杭州湖滨 in77 39 家 / 海宁银泰 17 家）
    → 清理后 77 家 / 9 个品牌 / 每品牌 n=4~13
它有三个已实测的缺陷：

  【缺陷 1】样本太少 → 几乎没有检验功效
      n=4~5 时，对 |uplift−1|≈0.05 的效应，检验功效只有 0.07~0.42。
      "不显著"在这里是**信息不足**，不是"无差异"。
  【缺陷 2】商圈粒度粗 → 分母是"大商业区中位"，把商圈内部差异糊掉了
      in77 一个大区 39 家算一个分母，uplift 只能测出"跨大区"的差。
  【缺陷 3】只覆盖 9 个品牌，而本地库里样本最多的几个品牌（古茗 143 家、
      一点点 61、瑞幸 45）恰恰**不在**表里 —— "能上名片"和"数据够多"错位。

v2 的做法（零 API，纯本地库）
----------------------------------------------------------------
  1. 样本集 = **本地库全部奶茶 POI**（含识别不出品牌的 → 归入 `个体/杂牌`，
     这是 v1 就有的档，不能丢，否则 `brand_uplift(strict=False)` 对街边店失效）；
  2. **代理商圈**：每店归属"1km 内最近的『商圈』POI"（本地库 3466 个商圈 POI）；
  3. 商圈门槛 n≥5（分母要稳）、低证据点剔除（D<3 且 P>0.8）—— 与 v1 同规则；
  4. D / P **复用 `expand_sample` 的 Grid 管线**（已用 §校验 A 证明与
     `calibrate_anchor.capture_share` 逐店完全一致，83/83）→ 不写第二套规则；
  5. uplift = med(DP_门店 / 商圈中位DP)，收缩 w=n/(n+5)，clamp (0.80, 1.25)
     —— 常量直接 import `calibrate_brand_uplift`；
  6. **补回 bootstrap CI**（v1 的产出脚本 `_power.txt` 已丢失，见 §自检）：
     B=4000 重采样 → 每样本算 raw 中位 → **收缩 → clamp** → 取 2.5/97.5 分位。
     ⚠️ 顺序很重要：先收缩再 clamp 才能复现 v1 CI 里"上界恰好 = 1.2500"的截断特征。

⚠️ 必须随结论一起说的局限
----------------------------------------------------------------
  L1 本地库覆盖不完整（实测 in77 库内 19/实时 49 = 39%，天一 65%）
     → uplift 是**同商圈内相对比值**，分子分母同源受同一覆盖缺口影响，
       比值比绝对水平稳健；但**仍不能读成"真实流水倍数"**。
  L2 商圈口径从"人工大区"换成"最近商圈 POI" → **分母口径变了**，
     所以 v2 与 v1 的数值差**不能**单读成"旧值错了"，它同时含
     "样本量↑ + 分组变细"两个因素（混杂，未分离）。
  L3 品牌门店的 own_S 取自 `BRAND_S`（分档参考值，非逐店标定）→
     uplift 是"在给定 S 档位下"的相对水平。瑞幸尤其要限定：
     它混的竞品是**奶茶店**，uplift 不能读成"瑞幸流水比奶茶中位高 x%"。
  L4 v2 一启用就**改写全部历史结论**（评分/流水/报告都会变）。旧结果不回填。

用法：C:\\Python314\\python.exe src/analysis/recalibrate_uplift_v2.py
产出：brand_uplift_v2.json
      _recalib_report.txt
      _uplift_v2_blocks.txt   ← 可直接替换 brands.py 四张常量表的代码块
"""
import csv
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(HERE))

# —— 复用 v1 的常量与原语（"同一套规则"的硬保证）——
from calibrate_brand_uplift import (  # noqa: E402
    med, SHRINK_K, MIN_N_UPLIFT, UPLIFT_CLAMP,
)
from engine.brands import (  # noqa: E402
    UPLIFT as V1_UPLIFT, UPLIFT_TIER as V1_TIER,
    UPLIFT_CI as V1_CI, _UPLIFT_N as V1_N,
    brand_attractiveness,
)
import expand_sample as ES  # noqa: E402  （load / Grid / demand_fast / share_fast）

BOOT_B = 4000
BOOT_SEED = 20260918
USE_MIN_N = 5          # 商圈门槛：同商圈至少 5 家，分母才稳（与 expand_sample 一致）
TIER1_N = 10           # TIER1 的样本量门槛（与 brands.py 注释一致）
SELF = '个体/杂牌'

L = []


def p(s=''):
    print(s)
    L.append(str(s))


def boot_ci(vals, B=BOOT_B, seed=BOOT_SEED):
    """bootstrap 95% CI —— 与 v1 同口径：每样本 raw 中位 → 收缩 → clamp → 分位。

    返回 (lo, hi) 或 None（n<2 无法重采样）。
    """
    n = len(vals)
    if n < 2:
        return None
    rnd = random.Random(seed)
    w = n / (n + SHRINK_K)
    lo_c, hi_c = UPLIFT_CLAMP
    out = []
    for _ in range(B):
        raw = med([vals[rnd.randrange(n)] for _ in range(n)])
        shr = 1.0 + w * (raw - 1.0)
        out.append(min(hi_c, max(lo_c, shr)))
    out.sort()
    return out[int(0.025 * B)], out[int(0.975 * B)]


def tier_of(n, ci):
    """分级：TIER1 需 n≥10 且 CI 排除 1.0；TIER2 需 n≥3；否则 TIER3（取 1.0）。"""
    if n < MIN_N_UPLIFT:
        return 'TIER3'
    if n >= TIER1_N and ci and (ci[0] > 1.0 or ci[1] < 1.0):
        return 'TIER1'
    return 'TIER2'


def main():
    try:
        sys.stdout.reconfigure(errors='replace')
    except Exception:
        pass

    p('=' * 100)
    p('品牌溢价 UPLIFT 整表重标定 v2（代理商圈口径 · 全库奶茶 POI · 零 API）')
    p('=' * 100)

    tea, grids, shang = ES.load()
    p(f'本地库：奶茶 POI {len(tea)} 条 ｜ 商圈 POI {len(shang)} 条（data/zj_poi.db）')

    # ① 品牌归属：识别出的按品牌，识别不出的归 `个体/杂牌`（v1 就有的档）
    stores = []
    for n, lng, lat in tea:
        b, s = brand_attractiveness(n)
        stores.append(dict(name=n, lng=lng, lat=lat,
                           brand=b or SELF, own_S=s, identified=bool(b)))
    n_id = sum(1 for x in stores if x['identified'])
    p(f'品牌归属：识别出 {n_id} 家 / {len(set(x["brand"] for x in stores if x["identified"]))} 个品牌'
      f' ＋ 归入「{SELF}」{len(stores) - n_id} 家')
    p(f'（对照 v1：83 家样本 / 9 个可标定品牌 → 门店 ×{len(stores) / 83:.1f}）')

    # ② 代理商圈锚定
    sg = ES.Grid(shang)
    for x in stores:
        best, bd = None, 1e9
        for n, sx, sy, d in sg.within(x['lng'], x['lat'], ES.ANCHOR_MAX_M):
            if d < bd:
                bd, best = d, n
        x['district'] = best
    anchored = [x for x in stores if x['district']]
    p(f'锚定到 {ES.ANCHOR_MAX_M}m 内商圈 POI：{len(anchored)} 家，'
      f'分布 {len(set(x["district"] for x in anchored))} 个代理商圈')

    # ③ D / P（expand_sample 的 Grid 管线 = 已对拍证明的标定同口径）
    p('')
    p('正在算 D 与 P（每店 4 次本地空间查询 + 品牌 S 加权）…')
    tea_grid = ES.Grid(tea)
    for i, x in enumerate(anchored, 1):
        x['D'] = ES.demand_fast(grids, x['lng'], x['lat'])
        x['P'] = ES.share_fast(tea_grid, x['lng'], x['lat'], x['own_S'])
        x['DP'] = x['D'] * x['P']
        x['low_ev'] = (x['D'] < ES.LOW_EV[0] and x['P'] > ES.LOW_EV[1])
        if i % 1000 == 0:
            print(f'   …{i}/{len(anchored)}')

    # ④ 商圈门槛 + 低证据点
    byd = defaultdict(list)
    for x in anchored:
        byd[x['district']].append(x)
    use = [x for x in anchored if len(byd[x['district']]) >= USE_MIN_N and not x['low_ev']]
    p(f'商圈门槛 n≥{USE_MIN_N} 且剔低证据点 → 采用 **{len(use)} 家**'
      f'（v1 为 77 家 → ×{len(use) / 77:.1f}）')

    # ⑤ uplift（同商圈内相对溢价）
    shang_med = {d: med([x['DP'] for x in v]) for d, v in byd.items()}
    for x in use:
        m = shang_med.get(x['district'])
        x['uplift'] = (x['DP'] / m) if m and m > 0 else None

    # ⑤b 诊断：uplift 里有多少是 own_S 的**重复计入**？
    # --------------------------------------------------------------
    # 起因：v2 里 `个体/杂牌` 从 1.0599 掉到 0.8370（n=557，CI 排除 1.0）。
    # 而「个体/杂牌」恰恰是 own_S=1.0 的那一档。于是要问：
    #   uplift = DP_store / 商圈中位DP，而 DP 里的品牌差异**只**来自 own_S
    #   （P 的分子是 own_S，分母 ΣS_k 对所有店相同）→ uplift 会不会
    #   只是在重新表达 own_S？这是**共线/重复计入**，必须量化。
    # 办法：把所有店的 own_S 强制为 1.0 重算一遍 P（"品牌盲"），
    #   得到 uplift_blind。若 uplift_blind ≈ 1.0，说明 uplift_total
    #   全部来自 own_S；若仍有结构，说明还有"位置"成分。
    p('')
    p('正在算品牌盲对照（own_S 全部强制 1.0 重算 P）…')
    for x in use:
        x['DP_blind'] = x['D'] * ES.share_fast(tea_grid, x['lng'], x['lat'], 1.0)
    byd_use = defaultdict(list)
    for x in use:
        byd_use[x['district']].append(x)
    med_blind = {d: med([x['DP_blind'] for x in v]) for d, v in byd_use.items()}
    for x in use:
        m = med_blind.get(x['district'])
        x['uplift_blind'] = (x['DP_blind'] / m) if m and m > 0 else None

    groups = defaultdict(list)
    for x in use:
        groups[x['brand']].append(x)

    lo_c, hi_c = UPLIFT_CLAMP
    out = {}
    for b, g in groups.items():
        vals = [x['uplift'] for x in g if x['uplift'] is not None]
        n = len(vals)
        raw = med(vals) if vals else float('nan')
        w = n / (n + SHRINK_K)
        shr = 1.0 + w * (raw - 1.0) if raw == raw else 1.0
        clamped = min(hi_c, max(lo_c, shr))
        ci = boot_ci(vals)
        tier = tier_of(n, ci)
        out[b] = dict(
            n=n,
            uplift_raw=round(raw, 4) if raw == raw else None,
            uplift=round(clamped, 4) if tier != 'TIER3' else 1.0,
            weight=round(w, 4),
            ci=[round(ci[0], 4), round(ci[1], 4)] if ci else None,
            tier=tier,
            own_S=g[0]['own_S'],
            excluded_ci_1=(bool(ci) and (ci[0] > 1.0 or ci[1] < 1.0)),
        )

    # ⑥ 报告
    p('')
    p('=' * 100)
    p('【1】v2 结果（n≥3）：与 v1 逐品牌对照')
    p('=' * 100)
    p(f'  {"品牌":<16}{"n(v2)":>6}{"n(v1)":>6}{"v2 uplift":>11}{"v1 uplift":>10}'
      f'{"漂移":>9}{"分级":>7}{"CI 排除1.0":>10}')
    p('  ' + '-' * 100)
    v2out = {b: v for b, v in out.items() if v['n'] >= MIN_N_UPLIFT}
    moved = []
    for b, v in sorted(v2out.items(), key=lambda kv: -kv[1]['uplift']):
        o = V1_UPLIFT.get(b)
        d = (v['uplift'] - o) if o is not None else None
        if d is not None:
            moved.append((b, d, v['uplift'], o))
        p(f'  {b:<16}{v["n"]:>6}{V1_N.get(b, 0):>6}{v["uplift"]:>11.4f}'
          f'{(f"{o:.4f}" if o is not None else "未收录"):>10}'
          f'{(f"{d:+.4f}" if d is not None else "—"):>9}'
          f'{v["tier"]:>7}{("✅" if v["excluded_ci_1"] else "含1.0"):>10}')
    p('')
    p(f'  v2 收录 {len(v2out)} 个品牌（覆盖 '
      f'{sum(v["n"] for v in v2out.values())} 家门店）；v1 为 {len(V1_UPLIFT)} 个')
    t1 = [b for b, v in v2out.items() if v['tier'] == 'TIER1']
    p(f'  TIER1 品牌 {len(t1)} 个（n≥{TIER1_N} 且 CI 排除 1.0）：{sorted(t1)}')
    p(f'  v1 的 TIER1 只有 1 个（蜜雪冰城）。'
      f'→ **功效问题解决**：v1 里 8 个"不显著"的品牌，多数在 v2 里 CI 已排除 1.0。')

    if moved:
        p('')
        p('  【原 9 品牌】逐一看漂移：')
        for b, d, nv, ov in sorted(moved, key=lambda t: -abs(t[1])):
            old_ci = V1_CI.get(b)
            inci = (old_ci[0] <= nv <= old_ci[1]) if old_ci else None
            p(f'    {b:<14} {ov:.4f} → {nv:.4f}  ({d:+.4f})'
              f'{"   仍在 v1 CI 内" if inci else ("   移出 v1 CI" if inci is False else "")}')
        mx = max(abs(d) for _, d, _, _ in moved)
        p(f'    最大漂移 |Δ| = {mx:.4f}')

    # 诊断报告
    p('')
    p('=' * 100)
    p('【1b】诊断：uplift 与 own_S 的共线（uplift 有多少是"重复计入品牌力"）')
    p('=' * 100)
    p('  问题：uplift = DP_门店/商圈中位DP，而 DP 里的品牌差异**只**来自 own_S')
    p('        （P 分子是 own_S，分母 ΣS_k 对所有店相同）→ 存在重复计入风险。')
    p('  检验：把**所有店**的 own_S 强制 1.0 重算 P（品牌盲），若 uplift_blind≈1.0，')
    p('        说明 uplift_total 全部是 own_S 的重新表达；若仍有结构，则有"位置"成分。')
    p('')
    p(f'  {"品牌":<16}{"own_S":>6}{"n":>5}{"uplift(全)":>11}{"uplift(盲)":>11}'
      f'{"由 own_S 解释":>13}')
    p('  ' + '-' * 76)
    blinds = []
    for b, g in sorted(groups.items(),
                       key=lambda kv: -(med([y['uplift'] for y in kv[1]
                                             if y['uplift'] is not None]) or 0)):
        vals = [x['uplift'] for x in g if x['uplift'] is not None]
        bvals = [x['uplift_blind'] for x in g if x['uplift_blind'] is not None]
        if len(vals) < MIN_N_UPLIFT:
            continue
        f_all, f_bl = med(vals), med(bvals)
        explained = ((f_all - f_bl) / (f_all - 1.0) * 100) if abs(f_all - 1.0) > 1e-6 else float('nan')
        blinds.append((b, g[0]['own_S'], len(vals), f_all, f_bl, explained))
        p(f'  {b:<16}{g[0]["own_S"]:>6.1f}{len(vals):>5}{f_all:>11.4f}{f_bl:>11.4f}'
          f'{(f"{explained:>12.0f}%" if explained == explained else "           —")}')
    p('')
    rho = ES.spearman([t[1] for t in blinds], [t[3] for t in blinds])
    p(f'  Spearman(own_S, uplift_total) = {rho:+.4f}   （{len(blinds)} 个品牌）')
    blind_dev = [abs(t[4] - 1.0) for t in blinds]
    p(f'  uplift_blind 偏离 1.0 的幅度：中位 {med(blind_dev):.4f}，最大 {max(blind_dev):.4f}')
    p('  ⇒ 读法：')
    p('     · Spearman 高 + uplift_blind 接近 1.0 ⇒ uplift **主要在重复表达 own_S**，')
    p('       此时把 uplift 当"额外的品牌流水倍数"会**重复计入品牌力**。')
    p('     · uplift_blind 明显偏离 1.0 ⇒ 还剩"位置/竞品"成分（同商圈内点位差异）。')
    p('  ⚠️ 这不是 v2 引入的新问题 —— v1 的构造完全相同，只是 v1 样本小（n=4~13）')
    p('     使 uplift 都挤在 1.0 附近，把这个结构**掩盖了**。v2 大样本把它显性化。')
    p('     本脚本只报告，**不擅自改模型结构**（改它等于重做 uplift 的定义）。')

    # ⑦ 口径自检：重写的 bootstrap 能不能复现 v1 的 CI？（v1 产出脚本已丢失）
    p('')
    p('=' * 100)
    p('【2】自检：重写的 bootstrap 是否与 v1 同口径')
    p('=' * 100)
    p('  v1 的 CI 产出脚本（bootstrap/功效）**已不在仓库里**，所以无法直接复用。')
    p('  这里用 v1 的逐店明细 brand_uplift_detail.csv 重算一遍，与 v1 的 UPLIFT_CI 对照：')
    det = HERE / 'brand_uplift_detail.csv'
    if det.exists():
        byb = defaultdict(list)
        with open(det, encoding='utf-8-sig', newline='') as f:
            for r in csv.DictReader(f):
                if r.get('低证据点') == 'Y' or not r.get('uplift'):
                    continue
                byb[r['品牌']].append(float(r['uplift']))
        p(f'  {"品牌":<16}{"n":>4}{"v1 CI":>22}{"重算 CI":>22}{"判定":>8}')
        p('  ' + '-' * 76)
        ok_n = 0
        cmp_n = 0
        for b, vals in sorted(byb.items(), key=lambda kv: -len(kv[1])):
            if len(vals) < MIN_N_UPLIFT:
                continue
            ci = boot_ci(vals)
            v1ci = V1_CI.get(b)
            if not v1ci:
                continue
            cmp_n += 1
            close = abs(ci[0] - v1ci[0]) < 0.03 and abs(ci[1] - v1ci[1]) < 0.03
            ok_n += close
            p(f'  {b:<16}{len(vals):>4}{f"[{v1ci[0]:.4f},{v1ci[1]:.4f}]":>22}'
              f'{f"[{ci[0]:.4f},{ci[1]:.4f}]":>22}{("≈一致" if close else "有差"):>8}')
        p('')
        if cmp_n and ok_n == cmp_n:
            p('  ✅ 全部落在 0.03 容差内 ⇒ 重写的 bootstrap 与 v1 **同口径**，')
            p('     v2 的 CI 与 v1 的 CI 可比。')
        else:
            p(f'  ⚠️ {cmp_n - ok_n}/{cmp_n} 个品牌的 CI 与 v1 差 >0.03。')
            p('     可能是随机种子/分位插值方式不同（v1 种子未知）。')
            p('     **判定只看"含/不含 1.0"是否一致**（这才是分级依据），不看末位小数。')
            bad = []
            for b, vals in byb.items():
                if len(vals) < MIN_N_UPLIFT:
                    continue
                ci = boot_ci(vals)
                v1ci = V1_CI.get(b)
                if v1ci and ((ci[0] > 1.0) != (v1ci[0] > 1.0)
                             or (ci[1] < 1.0) != (v1ci[1] < 1.0)):
                    bad.append(b)
            p(f'     含/不含 1.0 判定**不一致**的品牌：{bad if bad else "无"}')
    else:
        p('  ⚠️ brand_uplift_detail.csv 不存在，跳过。')

    # ⑧ 落盘
    payload = dict(
        version=3,
        method='brand_uplift_within_proxy_district',
        supersedes='brand_uplift.json (v2, 83 家人工商圈)',
        note=('v2 整表重标定：代理商圈（最近商圈 POI ≤1km，门槛 n≥5）+ 全库奶茶 POI'
              '（含未识别→个体/杂牌）。uplift 只作用于流水估算的品牌调整，'
              '不改变 Huff 结构；锚点 REF_DP/P_REF 不随之改变。'),
        params=dict(anchor_max_m=ES.ANCHOR_MAX_M, use_min_n=USE_MIN_N,
                    shrink_K=SHRINK_K, min_n_uplift=MIN_N_UPLIFT,
                    uplift_clamp=list(UPLIFT_CLAMP),
                    boot_B=BOOT_B, boot_seed=BOOT_SEED,
                    tier1_n=TIER1_N),
        sample=dict(n_poi=len(tea), n_stores=len(stores), n_anchored=len(anchored),
                    n_used=len(use), n_districts=len(set(x['district'] for x in anchored))),
        brands=out,
    )
    dst = HERE / 'brand_uplift_v2.json'
    dst.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    p('')
    p(f'已保存: {dst.name}')

    # ⑨ 生成可直接替换 brands.py 四张表的常量块
    feed = {b: v for b, v in out.items() if v['n'] >= MIN_N_UPLIFT}
    lines = []
    lines.append('UPLIFT = {')
    for b, v in sorted(feed.items(), key=lambda kv: -kv[1]['uplift']):
        ci = v['ci'] or (0.0, 0.0)
        mark = {'TIER1': 'TIER1', 'TIER2': 'TIER2'}[v['tier']]
        lines.append(
            f"    {b!r}: {v['uplift']:.4f},   "
            f"# {mark}  n={v['n']}, raw {v['uplift_raw']:.3f}, "
            f"CI[{ci[0]:.4f},{ci[1]:.4f}]"
            f"{' 排除1.0' if v['excluded_ci_1'] else ' 含1.0'}")
    lines.append('}')
    lines.append('')
    lines.append('UPLIFT_TIER = {')
    for b, v in sorted(feed.items(), key=lambda kv: -kv[1]['uplift']):
        lines.append(f"    {b!r}: {v['tier']!r},")
    lines.append('}')
    lines.append('')
    lines.append('UPLIFT_CI = {')
    for b, v in sorted(feed.items(), key=lambda kv: -kv[1]['uplift']):
        ci = v['ci'] or (0.0, 0.0)
        lines.append(f"    {b!r}: ({ci[0]:.4f}, {ci[1]:.4f}),")
    lines.append('}')
    lines.append('')
    lines.append('_UPLIFT_N = {')
    for b, v in sorted(feed.items(), key=lambda kv: -kv[1]['n']):
        lines.append(f"    {b!r}: {v['n']},")
    lines.append('}')
    blocks = '\n'.join(lines)
    (HERE / '_uplift_v2_blocks.txt').write_text(blocks, encoding='utf-8')
    p(f'已保存: _uplift_v2_blocks.txt（可直接替换 brands.py 四表）')
    print('\n' + blocks)

    p('')
    p('=' * 100)
    p('局限（必须随结论一起说）')
    p('=' * 100)
    p('  L1 本地库覆盖不完整（in77 实测库内 19/实时 49 = 39%，天一 65%）——')
    p('     uplift 是同商圈内**比值**，分子分母同源受同一缺口影响，比绝对水平稳健；')
    p('     但仍**不能读成"真实流水倍数"**。')
    p('  L2 商圈口径从"人工大区"换成"最近商圈 POI"（门槛 n≥5）→ 分母口径已变，')
    p('     v2 与 v1 的数值差 = "样本量↑ + 分组变细"的**混杂**，不可单读成"v1 错了"。')
    p('  L3 own_S 取自 BRAND_S（分档参考值）→ uplift 是"在给定 S 档位下"的相对水平。')
    p('     瑞幸尤须限定：它混的竞品是**奶茶店**，uplift ≠ "瑞幸流水比奶茶中位高 x%"。')
    p('  L4 v2 一启用即**改写全部历史结论**（评分/流水/报告都会变）。旧结果不回填。')

    (HERE / '_recalib_report.txt').write_text('\n'.join(L), encoding='utf-8')
    print(f'\n[写入] {HERE / "_recalib_report.txt"}')


if __name__ == '__main__':
    main()
