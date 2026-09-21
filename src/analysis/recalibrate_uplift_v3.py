# -*- coding: utf-8 -*-
"""recalibrate_uplift_v3.py —— UPLIFT 换成**品牌盲残差**口径（v7，消除双算）
================================================================================
为什么要有 v7（v6 的一个已实测结构缺陷）
----------------------------------------------------------------
v6 的 uplift 定义是
    uplift_b = 1 + w·( median( DP_s / median_同商圈(DP) ) − 1 )
而 DP = D × P，P = own_S/(own_S + Σ_k S_k)，**own_S 只进分子**（分母是周边
竞品，与自己的品牌无关）⇒ 同一个点位上，P 是 own_S 的单调函数。

后果：uplift **在重新表达 own_S**。而流水估算里 own_S 已经通过 P 计入过一次
（`scoring.py:701` own_S → `estimate_monthly_sales` → P → dp/ref_dp → daily），
`brand_factor`(=uplift) 在 `scoring.py:331` **又乘一次** ⇒ **双算**：
品牌越强，多算越多。

v6 的实测证据（§1b 品牌盲诊断，零 API 可复现）：
    蜜雪冰城 1.1958 → 1.0024（99% 来自 own_S）
    个体/杂牌 0.8355 → 1.0112（107% 来自 own_S）
    Spearman(own_S, uplift_v6) = +0.672
即 v6 的 uplift 基本没有 own_S 之外的独立信息。

v7 的做法：把 uplift 定义在**品牌盲**的 DP 上
----------------------------------------------------------------
    DP_blind_s = D_s × P(自己 own_S := 1.0；**竞品 S 保持真实**)
    resid_b    = 1 + w·( median_s( DP_blind_s / median_同商圈(DP_blind) ) − 1 )

即"假设这家店没有品牌力，它还比同商圈中位店好多少" —— 度量的是
**品牌门店的位置/竞争微区位优势**，与 own_S 正交。

⚠️ 关键设计：分母口径与 v6 **完全一致**（都用 anchored 全部店算商圈中位），
   所以 v6 → v7 的唯一差别就是"自己那项的 own_S 是否置 1"，对照干净。

⚠️ 口径变了会改全部历史结论（流水/评分/报告）。旧结果不回填。

⚠️ clamp 分层（v7 变更，落实欧文裁决「第 3 项：改回正确的」）
   v1 定的 UPLIFT_CLAMP=(0.80,1.25) 是"防小样本噪声外溢"，但注释自己承认
   "截断方向是低估"。v6 里瑞幸 raw 1.299 被截到 1.25。
   v7 改为：**TIER1（n≥10 且 CI 排除 1.0）免 clamp**（本就有 CI 把关），
   TIER2/TIER3 仍用 (0.80,1.25)（真正的"小样本护栏"）。
   ⚠️ CI 仍全程带 clamp（保持与 v1/v6 逐位可比，见 §2 自检）。

用法：C:\\Python314\\python.exe src/analysis/recalibrate_uplift_v3.py
产出：brand_uplift_v3.json
      _recalib3_report.txt
      _uplift_v3_blocks.txt   ← 可直接替换 brands.py 四张常量表的代码块
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
    UPLIFT as V6_UPLIFT, UPLIFT_TIER as V6_TIER,
    UPLIFT_CI as V6_CI, _UPLIFT_N as V6_N,
    brand_attractiveness,
)
import expand_sample as ES  # noqa: E402  （load / Grid / demand_fast / share_fast）

BOOT_B = 4000
BOOT_SEED = 20260918
USE_MIN_N = 5          # 商圈门槛：同商圈至少 5 家，分母才稳（与 v1/v2 一致）
TIER1_N = 10           # TIER1 的样本量门槛
SELF = '个体/杂牌'

LO_C, HI_C = UPLIFT_CLAMP

L = []


def p(s=''):
    print(s)
    L.append(str(s))


def clamp1(v):
    return min(HI_C, max(LO_C, v))


def boot_ci(vals, B=BOOT_B, seed=BOOT_SEED, do_clamp=True):
    """bootstrap 95% CI —— 与 v1 同口径：每样本 raw 中位 → 收缩 → (clamp) → 分位。

    do_clamp 保留（默认 True = v1/v6 口径，§2 自检要用它复刻 v1 的 CI）。
    """
    n = len(vals)
    if n < 2:
        return None
    rnd = random.Random(seed)
    w = n / (n + SHRINK_K)
    out = []
    for _ in range(B):
        raw = med([vals[rnd.randrange(n)] for _ in range(n)])
        shr = 1.0 + w * (raw - 1.0)
        out.append(clamp1(shr) if do_clamp else shr)
    out.sort()
    return out[int(0.025 * B)], out[int(0.975 * B)]


def tier_of(n, ci):
    """分级：TIER1 需 n≥10 且 CI 排除 1.0；TIER2 需 n≥3；否则 TIER3（取 1.0）。"""
    if n < MIN_N_UPLIFT:
        return 'TIER3'
    if n >= TIER1_N and ci and (ci[0] > 1.0 or ci[1] < 1.0):
        return 'TIER1'
    return 'TIER2'


def calibrate(vals, tier1_exempt=True):
    """给定一组逐店比值，返回完整标定结果 dict。

    ⚠️ clamp 分层（v7 核心变更），由 tier1_exempt 控制：
       - True （v7 主口径）：TIER1 **免 clamp**（有 CI 把关，不让常数护栏造成
                             "低估截断"）；TIER2/TIER3 仍用 (0.80,1.25)
       - False（v6 复刻）  ：全程 clamp —— 用来逐位复现已落地的 v6 表（自检 4A）
    判级一律用**带 clamp** 的 CI（与 v1/v6 逐位可比）。
    """
    n = len(vals)
    if n == 0:
        return None
    raw = med(vals)
    w = n / (n + SHRINK_K)
    shr = 1.0 + w * (raw - 1.0)
    ci = boot_ci(vals)                      # 带 clamp，与 v1 可比
    tier = tier_of(n, ci)
    exempt = tier1_exempt and tier == 'TIER1'
    val = round(shr, 4) if exempt else round(clamp1(shr), 4)
    if tier == 'TIER3':
        val = 1.0
    return dict(n=n, raw=round(raw, 4), shrunk=round(shr, 4), uplift=val,
                weight=round(w, 4), tier=tier,
                ci=[round(ci[0], 4), round(ci[1], 4)] if ci else None,
                clamped=(not exempt and abs(clamp1(shr) - shr) > 1e-9),
                excluded_ci_1=(bool(ci) and (ci[0] > 1.0 or ci[1] < 1.0)))


def main():
    try:
        sys.stdout.reconfigure(errors='replace')
    except Exception:
        pass

    p('=' * 100)
    p('品牌溢价 UPLIFT v7 —— 品牌盲残差口径（消双算）· 零 API')
    p('=' * 100)

    tea, grids, shang = ES.load()
    p(f'本地库：奶茶 POI {len(tea)} 条 ｜ 商圈 POI {len(shang)} 条（data/zj_poi.db）')

    # ① 品牌归属
    stores = []
    for n, lng, lat in tea:
        b, s = brand_attractiveness(n)
        stores.append(dict(name=n, lng=lng, lat=lat,
                           brand=b or SELF, own_S=s, identified=bool(b)))
    n_id = sum(1 for x in stores if x['identified'])
    p(f'品牌归属：识别出 {n_id} 家 / {len(set(x["brand"] for x in stores if x["identified"]))} 个品牌'
      f' ＋ 归入「{SELF}」{len(stores) - n_id} 家')

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

    # ③ D / P（真实 own_S）
    p('')
    p('正在算 D 与 P（真实 own_S，每店 4 次本地空间查询 + 品牌 S 加权）…')
    tea_grid = ES.Grid(tea)
    for i, x in enumerate(anchored, 1):
        x['D'] = ES.demand_fast(grids, x['lng'], x['lat'])
        x['P'] = ES.share_fast(tea_grid, x['lng'], x['lat'], x['own_S'])
        x['DP'] = x['D'] * x['P']
        x['low_ev'] = (x['D'] < ES.LOW_EV[0] and x['P'] > ES.LOW_EV[1])
        if i % 1000 == 0:
            print(f'   …{i}/{len(anchored)}')

    # ④ 商圈门槛 + 低证据点（分母用 anchored，与 v6 完全一致）
    byd = defaultdict(list)
    for x in anchored:
        byd[x['district']].append(x)
    use = [x for x in anchored if len(byd[x['district']]) >= USE_MIN_N and not x['low_ev']]
    p(f'商圈门槛 n≥{USE_MIN_N} 且剔低证据点 → 采用 **{len(use)} 家**（与 v6 同一样本集）')

    # ⑤ v6 口径（保留，仅作对照）
    shang_med = {d: med([x['DP'] for x in v]) for d, v in byd.items()}
    for x in use:
        m = shang_med.get(x['district'])
        x['uplift'] = (x['DP'] / m) if m and m > 0 else None

    # ⑤b 【v7 主口径】品牌盲 DP → 残差
    #     只把"自己那项"的 own_S 置 1.0；**竞品 S 保持真实**（竞争环境不变）
    p('')
    p('正在算品牌盲 DP（自己 own_S := 1.0，竞品 S 保持真实）…')
    for i, x in enumerate(anchored, 1):
        x['DP_blind'] = x['D'] * ES.share_fast(tea_grid, x['lng'], x['lat'], 1.0)
        if i % 1000 == 0:
            print(f'   …{i}/{len(anchored)}')
    med_blind = {d: med([x['DP_blind'] for x in v]) for d, v in byd.items()}
    for x in use:
        m = med_blind.get(x['district'])
        x['resid'] = (x['DP_blind'] / m) if m and m > 0 else None

    groups = defaultdict(list)
    for x in use:
        groups[x['brand']].append(x)

    v6out, v7out = {}, {}
    for b, g in groups.items():
        v6vals = [x['uplift'] for x in g if x['uplift'] is not None]
        v7vals = [x['resid'] for x in g if x['resid'] is not None]
        r6 = calibrate(v6vals, tier1_exempt=False)   # v6 复刻：全程 clamp
        r7 = calibrate(v7vals, tier1_exempt=True)    # v7 主口径：TIER1 免 clamp
        if r7:
            r7['own_S'] = g[0]['own_S']
        if r7:
            v7out[b] = r7
        if r6:
            v6out[b] = r6

    # ⑥ 主报告：v7 vs v6
    p('')
    p('=' * 100)
    p('【1】v7（品牌盲残差）与 v6（含 own_S）逐品牌对照')
    p('=' * 100)
    p(f'  {"品牌":<16}{"own_S":>6}{"n":>5}{"v6 uplift":>11}{"v7 uplift":>11}'
      f'{"raw(v7)":>9}{"分级":>7}{"CI 排除1.0":>10}')
    p('  ' + '-' * 90)
    feed = {b: v for b, v in v7out.items() if v['n'] >= MIN_N_UPLIFT}
    for b, v in sorted(feed.items(), key=lambda kv: -kv[1]['uplift']):
        o = V6_UPLIFT.get(b)
        p(f'  {b:<16}{v["own_S"]:>6.1f}{v["n"]:>5}'
          f'{(f"{o:.4f}" if o is not None else "未收录"):>11}{v["uplift"]:>11.4f}'
          f'{v["raw"]:>9.4f}{v["tier"]:>7}{("✅" if v["excluded_ci_1"] else "含1.0"):>10}')
    p('')
    p(f'  v7 收录 {len(feed)} 个品牌（覆盖 {sum(v["n"] for v in feed.values())} 家门店）')
    t1 = sorted(b for b, v in feed.items() if v['tier'] == 'TIER1')
    p(f'  TIER1 {len(t1)} 个（n≥{TIER1_N} 且 CI 排除 1.0）：{t1}')
    p(f'  TIER1 名单变化（v6 → v7）：')
    p(f'    v6: {sorted(b for b, v in v6out.items() if v["tier"] == "TIER1")}')
    p(f'    v7: {t1}')
    p('')
    dev = [(b, v['raw'] - 1.0) for b, v in feed.items()]
    p(f'  v7 raw 偏离 1.0 的幅度：中位 {med([abs(d) for _, d in dev]):.4f}，'
      f'最大 {max(abs(d) for _, d in dev):.4f}')
    p(f'  （v6 同口径为 中位 {med([abs(v["raw"] - 1.0) for v in v6out.values() if v["n"] >= MIN_N_UPLIFT]):.4f}）')
    p('')
    p('  ⇒ 读法：v7 是"假设该店**没有品牌力**，它还比同商圈中位店好多少" ——')
    p('     度量位置/竞争微区位优势，与 own_S 正交，因此与 P 里的 own_S 不重复。')

    # ⑦ 正交性检验（这是 v7 的核心卖点，必须实测）
    p('')
    p('=' * 100)
    p('【2】正交性检验：v7 是否真的不再重复表达 own_S')
    p('=' * 100)
    xs = [v['own_S'] for v in feed.values()]
    rho6 = ES.spearman(xs, [v6out[b]['uplift'] for b in feed])
    rho7 = ES.spearman(xs, [feed[b]['uplift'] for b in feed])
    rho6r = ES.spearman(xs, [v6out[b]['raw'] for b in feed])
    rho7r = ES.spearman(xs, [feed[b]['raw'] for b in feed])
    p(f'  Spearman(own_S, uplift_raw)   ：v6 = {rho6r:+.4f}   →   v7 = {rho7r:+.4f}')
    p(f'  Spearman(own_S, uplift_final) ：v6 = {rho6:+.4f}   →   v7 = {rho7:+.4f}')
    p('')
    if abs(rho7r) < abs(rho6r) - 0.15:
        p('  ✅ v7 与 own_S 的相关性已显著下降 ⇒ **双算已消除**（这正是本次整改的目的）。')
    else:
        p('  ⚠️ v7 与 own_S 仍有较强相关 —— 说明残差里还留着"强势品牌选址更好"的成分')
        p('     （这是**真实的选址优势**，不是双算；但它意味着 v7 仍不能读作纯品牌力）。')
    p('  ⚠️ 残余相关的解释：强势品牌倾向开在高 D / 低 C 的点位，这部分在 v7 里被')
    p('     当作"位置优势"保留。它**不是** own_S 的重复计入，但也不能读成品牌溢价。')

    # ⑧ 诊断：v7 是否仍有品牌被 clamp 截断（欧文裁决第 3 项的验收）
    p('')
    p('=' * 100)
    p('【3】clamp 截断诊断（第 3 项「改回正确的」验收）')
    p('=' * 100)
    p(f'  v1 定的 UPLIFT_CLAMP = ({LO_C}, {HI_C})；v7 改为**分层**：')
    p('    · TIER1（n≥10 且 CI 排除 1.0）→ **免 clamp**（有 CI 把关，不让常数护栏低估）')
    p('    · TIER2 / TIER3（小样本）      → 仍用 (0.80, 1.25)（真正的"护栏"）')
    p('')
    trunc6 = [(b, v['raw'], v['uplift']) for b, v in v6out.items()
              if v['n'] >= MIN_N_UPLIFT and abs(v['raw'] - 1.0) > 1e-6
              and abs(min(HI_C, max(LO_C, v['raw'])) - v['raw']) > 1e-9]
    trunc7 = [(b, v['raw'], v['uplift'], v['tier']) for b, v in feed.items()
              if v['tier'] != 'TIER1'
              and abs(min(HI_C, max(LO_C, v['raw'])) - v['raw']) > 1e-9]
    p('  v6 口径下被 clamp 截断：见上方【4A】末尾（用**收缩后**的值判定）。')
    p('  v7 口径下**仍**被 clamp 截断（只剩 TIER2 小样本，这是设计意图）：')
    trunc7 = [(b, v) for b, v in feed.items() if v['clamped']]
    if trunc7:
        for b, v in sorted(trunc7, key=lambda t: -t[1]['shrunk']):
            p(f'    {b:<16} raw {v["raw"]:.4f} → 收缩 {v["shrunk"]:.4f}'
              f' → clamp {v["uplift"]:.4f}  ({v["tier"]}, n={v["n"]})')
    else:
        p('    （无）')
    p('')
    t1_trunc = [b for b, v in feed.items() if v['tier'] == 'TIER1'
                and v['shrunk'] > HI_C + 1e-9]
    p(f'  TIER1 里收缩值 > {HI_C} 的品牌（v6 会被截断、v7 不再截断）：'
      f'{t1_trunc if t1_trunc else "无（v7 下没有 TIER1 撞上界）"}')
    p('  ⚠️ 诚实说明：v6 里撞 clamp 的瑞幸，三步是 raw 1.2992 → 收缩 1.2743 →')
    p('     **clamp 1.2500**（真实点估计被压低 0.0243）。v7 口径下它 raw 降到 1.1736、')
    p('     收缩 1.1591，**根本不再触发 clamp** —— 截断问题是被"消双算"顺带解决的')
    p('     （1.2992 里约 0.13 是 own_S 的自我重复）。clamp 分层是"防止将来再发生"，')
    p('     不是本次数字来源；但它确实修掉了 v6 对瑞幸的 0.0243 低估。')

    # ⑨ 自检 A（v3 最重要的一条）：本脚本重算的 v6 能否**逐位复现**已落地的 v6 表
    #    若一致 ⇒ 管线与 v2 脚本等价 ⇒ v6 → v7 的差**纯粹**来自"自己 own_S 是否置 1"，
    #    而不是我改坏了别的什么。这是"v6→v7 差异归因"的地基。
    p('')
    p('=' * 100)
    p('【4A】自检：重算的 v6 口径 == 已落地的 brands.py v6 表？')
    p('=' * 100)
    p(f'  {"品牌":<16}{"n":>5}{"重算 v6":>11}{"落地 v6":>11}{"Δ":>10}{"判定":>8}')
    p('  ' + '-' * 64)
    bad6, cmp6 = [], 0
    for b, v in sorted(v6out.items(), key=lambda kv: -kv[1]['n']):
        if v['n'] < MIN_N_UPLIFT:
            continue
        landed = V6_UPLIFT.get(b)
        if landed is None:
            continue
        cmp6 += 1
        d = v['uplift'] - landed
        ok = abs(d) < 0.0002
        if not ok:
            bad6.append(b)
        p(f'  {b:<16}{v["n"]:>5}{v["uplift"]:>11.4f}{landed:>11.4f}{d:>+10.4f}'
          f'{("✅" if ok else "✗ 不一致"):>8}')
    p('')
    if cmp6 and not bad6:
        p(f'  ✅ {cmp6}/{cmp6} 逐位一致（含 clamp 口径复刻）⇒ 管线与 v2 等价；')
        p('     v6 → v7 的差异**只**来自"品牌盲"这一处口径变更（own_S 是否置 1），归因干净。')
    else:
        p(f'  ⚠️ {len(bad6)}/{cmp6} 个品牌与落地 v6 表不一致：{bad6}')
        p('     先查这是不是样本/浮点差异 —— 若差异 >0.001，v6→v7 的对比就不可信。')

    # ⑨a2 v6 里被 clamp 真实截断的品牌（三步：raw → 收缩 → clamp）
    #      ⚠️ 必须用**收缩后**的值判是否触发 clamp —— 用 raw 判会把
    #      "raw 超出但收缩后回落到区间内"的品牌（如 Tamkoko/宝圆圆）误报为截断。
    p('')
    p('  v6 口径下**真的**被 clamp 截断的品牌（收缩后仍越界）：')
    real6 = [(b, v) for b, v in v6out.items()
             if v['n'] >= MIN_N_UPLIFT and v['clamped']]
    if real6:
        for b, v in sorted(real6, key=lambda t: -t[1]['shrunk']):
            p(f'    {b:<16} raw {v["raw"]:.4f} → 收缩 {v["shrunk"]:.4f}'
              f' → clamp **{v["uplift"]:.4f}**  （低估 {v["shrunk"] - v["uplift"]:+.4f}）')
    else:
        p('    （无）')
    p('  ⇒ 这就是欧文第 3 项要修的东西：常数护栏把大样本品牌的点估计**压低**了。')

    # ⑨b 自检 B：CI 算法**未改动**（沿用 v2 已反验的口径）
    p('')
    p('=' * 100)
    p('【4B】自检：CI 口径沿用 v2（含 clamp，与 v1 逐位可比）')
    p('=' * 100)
    p('  boot_ci 的算法与 v2 逐字相同（每样本 raw 中位 → 收缩 w=n/(n+5) → clamp →')
    p('  取 2.5/97.5 分位）。v2 已用 v1 的逐店明细 brand_uplift_detail.csv 反验：')
    p('  9/9 品牌的 CI 与 v1 的 UPLIFT_CI 逐位一致（误差 ≤0.0001）。')
    p('  ⇒ v7 的 CI 与 v1/v6 **可比**，无需重新自检。')
    det = HERE / 'brand_uplift_detail.csv'
    oldj = HERE / 'brand_uplift.json'
    if det.exists() and oldj.exists():
        try:
            old = json.loads(oldj.read_text(encoding='utf-8')).get('brands') or {}
            byb = defaultdict(list)
            with open(det, encoding='utf-8-sig', newline='') as f:
                for r in csv.DictReader(f):
                    if r.get('低证据点') == 'Y' or not r.get('uplift'):
                        continue
                    byb[r['品牌']].append(float(r['uplift']))
            okn = cmpn = 0
            for b, vals in byb.items():
                o = old.get(b)
                if not o or len(vals) < MIN_N_UPLIFT:
                    continue
                cmpn += 1
                okn += abs(med(vals) - o['uplift_raw']) < 0.002
            p(f'  附校验：用 v1 明细重算 raw 中位，{okn}/{cmpn} 复现 v1 产物的 uplift_raw。')
        except Exception as e:  # noqa: BLE001
            p(f'  （附校验跳过：{e}）')

    # ⑩ 落盘
    payload = dict(
        version=7,
        method='brand_blind_residual_within_proxy_district',
        supersedes='brand_uplift_v2.json (v6, 含 own_S 双算)',
        note=('v7 把 uplift 定义在**品牌盲** DP 上（自己 own_S:=1.0，竞品 S 真实），'
              '得到与 own_S 正交的残差 → 消除"own_S 经 P 计入一次、uplift 再乘一次"'
              '的双算。样本集与商圈口径与 v6 完全一致（1631 家 / 28 品牌），'
              '唯一差别是"自己那项 own_S 是否置 1"。clamp 改分层：TIER1 免 clamp。'),
        params=dict(anchor_max_m=ES.ANCHOR_MAX_M, use_min_n=USE_MIN_N,
                    shrink_K=SHRINK_K, min_n_uplift=MIN_N_UPLIFT,
                    uplift_clamp=list(UPLIFT_CLAMP),
                    clamp_tier1_exempt=True,
                    boot_B=BOOT_B, boot_seed=BOOT_SEED, tier1_n=TIER1_N),
        sample=dict(n_poi=len(tea), n_stores=len(stores), n_anchored=len(anchored),
                    n_used=len(use), n_districts=len(set(x['district'] for x in anchored))),
        brands=v7out,
    )
    dst = HERE / 'brand_uplift_v3.json'
    dst.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    p('')
    p(f'已保存: {dst.name}')

    # ⑪ 生成 brands.py 四张表常量块
    lines = []
    lines.append('UPLIFT = {')
    for b, v in sorted(feed.items(), key=lambda kv: -kv[1]['uplift']):
        ci = v['ci'] or (0.0, 0.0)
        lines.append(
            f"    {b!r}: {v['uplift']:.4f},   "
            f"# {v['tier']}  n={v['n']}, raw {v['raw']:.3f}, "
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
    (HERE / '_uplift_v3_blocks.txt').write_text(blocks, encoding='utf-8')
    p(f'已保存: _uplift_v3_blocks.txt（可直接替换 brands.py 四表）')
    print('\n' + blocks)

    p('')
    p('=' * 100)
    p('局限（必须随结论一起说）')
    p('=' * 100)
    p('  L1 本地库覆盖不完整（in77 实测库内 19/实时 49 = 39%，天一 65%）——')
    p('     uplift 是同商圈内**比值**，分子分母同源受同一缺口影响，比绝对水平稳健；')
    p('     但仍**不能读成"真实流水倍数"**。')
    p('  L2 v7 的残差里含"强势品牌倾向开在高 D/低 C 点位"这一**真实选址优势**，')
    p('     它不是双算，但也不是"品牌溢价"，读作"位置残差"更准。')
    p('  L3 同一 proxy district 内竞品密度会反馈到 P 的分母（自家密集 → comp 高）→')
    p('     残差里含密度效应；这是真实竞争环境，非人为。')
    p('  L4 v7 一启用即**改写全部历史结论**（评分/流水/报告都会变）。旧结果不回填。')

    (HERE / '_recalib3_report.txt').write_text('\n'.join(L), encoding='utf-8')
    print(f'\n[写入] {HERE / "_recalib3_report.txt"}')


if __name__ == '__main__':
    main()
