# -*- coding: utf-8 -*-
"""
model_facts.py —— 「本模型的事实」唯一真源（实时读产物，零写死）
================================================================
问题（2026-09-18 欧文报）：模型审计师里写着「锚点用 83 家真实门店标定」，
而样本已经扩到几百上千家 —— 数字散落在 md / kb 语料 / 静态知识页 / 后端提示词
四处各写一份，改一处漏三处，且**没人知道哪个是当前值**。

本模块把「本模型的事实」全部收敛到一处：**运行时从真实产物读**。

谁在用（改这些地方的数字都必须走本模块，不许再写死）：
  · `experts/model_auditor.md` 的系统提示（由 registry 注入本模块的实时块）
  · `agent/knowledge.py` 「选址评分模型依据」等语料
  · `public/sidebar.js` 左侧知识页的系数卡（读 `public/sidebar.json.facts`）
  · `agent/agent_graph.py` 里带锚点数值的提示词

三条纪律（与项目红线同源）：

1. **不猜**：产物读不到就返回 `None` + 原因，**绝不回落到写死的旧值**。
   回落 = 悄悄拿过期数据冒充实时数据，比不显示更坏。
   （所以本模块里除"标签文字"外**不出现任何硬编码数值**。）

2. **不混口径**：这是最容易出错的地方 —— 锚点不是"一个样本量"，是**三个不同口径**：
   | 口径 | 规模 | 是否进引擎 |
   |---|---|---|
   | 锚点标定（REF_DP / P_REF） | **83 总 / 75 实际采用** | ✅ 引擎在用 |
   | 品牌溢价标定（UPLIFT） | **3563 锚定 / 1631 采用 / 34 品牌** | ✅ 引擎在用（v7/v8 产物） |
   | Huff 扩样探索 | **2298 锚定 / 796 可用** | ❌ 离线，**未接入锚点** |
   三者**必须分开呈现**。把它们合成一个"样本量"就是把口径搅了（红线 2）。

   ⚠️ 距离口径还有**第二层**之分（2026-09-20 步行路网改造时实测出来的）：
   `engine/realtime.get_surrounding` 是"**本地预抓取库优先，本地为空才实时兜底**"，
   而标定脚本大多强制 `REALTIME=0`（纯本地库）。两者只在**本地库无该类目覆盖**
   的门店上分歧 —— 实测 83 家里恰好 **3 家**（海宁银泰，P 全为 1.0）。
   所以模块里把两套口径**各自重算一遍并对拍**，而不是记一个写死的差值。

3. **带来源与时间**：每项给 `来源`（仓库内相对路径）与 `产出时间`（文件 mtime），
   让"这个数是什么时候生成的、能不能复跑"当场可核。
"""
import csv
import io
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # <repo>/site-selection-agent
_SRC = ROOT / 'src'
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

AN = _SRC / 'analysis'

# 产物所在的仓库内相对路径（只写路径，不写数值）
F_ANCHOR_PROD = 'src/analysis/brand_uplift.json'          # 锚点标定产物（83 家·人工商圈）
F_ENGINE_CSV = 'src/analysis/anchor_calib.csv'            # 引擎口径逐店 D/P（同脚本产出）
F_UPLIFT_PROD = 'src/analysis/brand_uplift_v3.json'       # 品牌溢价产物（v7·品牌盲残差）
F_UPLIFT_ROAD = 'src/analysis/brand_uplift_v3_road.json'  # 品牌溢价产物（v8·步行路网口径）
F_ANCHOR_CSV = 'src/analysis/anchor_calib.csv'            # 83 家逐店 D/P
F_SENS_CSV = 'src/analysis/result_sensitivity.csv'        # λ 敏感性（两两 Spearman）
F_EXPAND_CSV = 'src/analysis/sample_expanded.csv'         # Huff 扩样探索（离线）
F_SCORING = 'src/engine/scoring.py'
F_BRANDS = 'src/engine/brands.py'

# 低证据点判据（D < 3 且 P > 0.8）—— 与 calibrate_anchor / calibrate_anchor_by_brand
# 的 LOW_EVIDENCE_D / P_SUSPICIOUS 同源。这里重复一次是**读产物时的过滤规则**，
# 不是模型常数；改动必须与两个标定脚本同改。
LOW_EVIDENCE = (3.0, 0.80)


def _med(xs):
    xs = sorted(xs)
    n = len(xs)
    if n == 0:
        return None
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


# ---------------------------------------------------------------
# 读文件的小工具（读不到一律返回 None，由调用方决定怎么如实标"不可得"）
# ---------------------------------------------------------------
def _path(rel: str) -> Path:
    return ROOT / rel


def _stamp(rel: str) -> dict:
    """来源 + 产出时间（mtime）。文件不存在时产出时间为 None。"""
    p = _path(rel)
    out = {'来源': rel, '产出时间': None}
    try:
        if p.exists():
            out['产出时间'] = datetime.fromtimestamp(
                p.stat().st_mtime).strftime('%Y-%m-%d %H:%M')
    except OSError:
        pass
    return out


def _json(rel: str):
    try:
        return json.loads(_path(rel).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return None


def _rows(rel: str, encoding='utf-8-sig'):
    """读 CSV → list[dict]。带 BOM 的产物用 utf-8-sig 才不会把首列名读坏。"""
    try:
        with io.open(_path(rel), encoding=encoding, newline='') as fh:
            return list(csv.DictReader(fh))
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def _engine_consts():
    """引擎里正在生效的常量。**这是唯一可称为'当前值'的来源。**"""
    from engine.scoring import LAMBDA, D0, REF_DP, P_REF, USE_BRAND_UPLIFT
    from engine.brands import UPLIFT, UPLIFT_TIER
    return dict(LAMBDA=LAMBDA, D0=D0, REF_DP=REF_DP, P_REF=P_REF,
                USE_BRAND_UPLIFT=USE_BRAND_UPLIFT,
                UPLIFT=UPLIFT, UPLIFT_TIER=UPLIFT_TIER)


# ---------------------------------------------------------------
# 各口径的事实
# ---------------------------------------------------------------
def _anchor_recount(rel):
    """从逐店 D/P 明细**当场重算**锚点（引擎口径：本地库优先 + 本地空则实时兜底）。

    为什么要重算而不是只读产物：产物 `brand_uplift.json` 由
    `calibrate_anchor_by_brand.py` 产出，它强制 `REALTIME=0`（纯本地库口径）；
    而引擎跑的是"本地库优先、本地为空才实时兜底"。两者在**本地库无覆盖**的
    门店上会分歧 ⇒ 必须按**引擎口径**再算一遍来对拍，不能拿产物当引擎值。
    """
    rows = _rows(rel)
    if rows is None:
        return None
    lo_d, hi_p = LOW_EVIDENCE
    tot, keep = 0, []
    for r in rows:
        nm = (r.get('名称') or '').strip()
        if not nm or nm.startswith(('REF_DP', 'P_REF')):
            continue                       # 末尾 3 行汇总行
        try:
            d = float((r.get('D') or '').strip())
            p = float((r.get('P') or '').strip())
        except (TypeError, ValueError):
            continue
        tot += 1
        if not (d < lo_d and p > hi_p):
            keep.append((d, p))
    if not keep:
        return None
    # ⚠️ 踩过的坑：这里必须写 `for _d, _p in keep` 并在表达式里用 `_p`。
    #    若写成 `[d * p for d, _p in keep]`，`p` **不在推导式作用域内** →
    #    会静默取到外层 for 循环遗留的 `p`（= 最后一行的 P 值），
    #    于是 D×P 退化成 D×常数，中位数照样是"一个看起来合理的数"（实测 8.0）。
    #    同类错误在 dict 字面量里尤其隐蔽 —— 不会报错，只会给出错值。
    return {
        '总样本': tot,
        '采用': len(keep),
        '剔除低证据点': tot - len(keep),
        'REF_DP': round(_med([_d * _p for _d, _p in keep]), 4),
        'P_REF': round(_med([_p for _d, _p in keep if 0 < _p < 1]), 4),
        '来源': _stamp(rel),
    }


def anchor() -> dict:
    """① 锚点标定口径（REF_DP / P_REF）—— 引擎在用。

    「采用家数」按**引擎口径**当场重算（见 `_anchor_recount`）：v8 实测 83 总 /
    75 采用；标定产物（纯本地库口径）记的是 72。**两者口径不同，并列呈现、
    不许互相替换**（红线 2）。
    """
    out = {}
    eng = _anchor_recount(F_ENGINE_CSV)
    if eng:
        out['引擎口径重算'] = eng
        out['口径'] = (f"剔除低证据点（D<{LOW_EVIDENCE[0]:g} 且 P>{LOW_EVIDENCE[1]:g}）"
                       f"后取中位：总样本 {eng['总样本']} 家 → 采用 {eng['采用']} 家")
        out['重算来源'] = eng['来源']
    else:
        out['引擎口径重算'] = None
    try:
        c = _engine_consts()
        out['引擎在用'] = {'REF_DP': c['REF_DP'].get('奶茶'),
                          'P_REF': c['P_REF'].get('奶茶')}
    except Exception as e:                                # noqa: BLE001
        out['引擎在用'] = None
        out['引擎常量读取失败'] = repr(e)
    out['常量来源'] = _stamp(F_SCORING)

    prod = _json(F_ANCHOR_PROD)
    if prod:
        g = prod.get('global_') or {}
        out['标定产物'] = {
            'REF_DP': g.get('REF_DP'), 'P_REF': g.get('P_REF'),
            'P_REF_unadj': g.get('P_REF_unadj'),
            '总样本': g.get('n_total'), '实际采用': g.get('n_used'),
        }
        out['产物来源'] = _stamp(F_ANCHOR_PROD)
        out['商圈中位D×P'] = prod.get('district_median_DP')
    else:
        out['标定产物'] = None

    rows = _rows(F_ANCHOR_CSV)
    if rows is not None:
        # ⚠️ 这个 CSV 末尾有 3 行"汇总行"（列为 名称,值），列数不齐 →
        #    直接按 `商圈` 列非空过滤会把它们当成门店（实测：家数 83 被读成 86）。
        #    判据 = `D×P` 列必须能解析成浮点数（汇总行没有这一列）。
        stores = []
        for r in rows:
            name = (r.get('名称') or '').strip()
            dist = (r.get('商圈') or '').strip()
            if not dist or name.startswith('REF_DP') or name.startswith('P_REF'):
                continue
            try:
                float((r.get('D×P') or '').strip())
            except ValueError:
                continue                       # 汇总行/坏行
            stores.append(r)
        dists = []
        for r in stores:
            d = r['商圈']
            if d not in dists:
                dists.append(d)
        out['逐店明细'] = {'家数': len(stores), '商圈数': len(dists), '商圈': dists}
        out['明细来源'] = _stamp(F_ANCHOR_CSV)

    # ---- 对拍（live，不写死差值）：引擎常量 vs 引擎口径重算 vs 标定产物 ----
    cmp = {}
    eu = out.get('引擎在用') or {}
    if eng and eu.get('REF_DP') is not None:
        cmp['REF_DP(常量−重算)'] = round(eu['REF_DP'] - eng['REF_DP'], 4)
    if eng and eu.get('P_REF') is not None and eng.get('P_REF') is not None:
        cmp['P_REF(常量−重算)'] = round(eu['P_REF'] - eng['P_REF'], 4)
    pr = out.get('标定产物') or {}
    if eng and pr.get('实际采用') is not None:
        cmp['采用家数(产物−引擎口径重算)'] = pr['实际采用'] - eng['采用']
    if eng and pr.get('REF_DP') is not None:
        cmp['REF_DP(产物−重算)'] = round(pr['REF_DP'] - eng['REF_DP'], 4)
    if cmp:
        out['对拍'] = cmp
    # 口径差异的**原因**（结构性事实，不是数值）：只在两套口径家数真的不同时才说
    if eng and pr.get('实际采用') is not None and pr['实际采用'] != eng['采用']:
        out['口径差异说明'] = (
            f"标定产物（纯本地库 REALTIME=0）采用 {pr['实际采用']} 家，"
            f"引擎口径（本地库优先+实时兜底）采用 {eng['采用']} 家。"
            "差异只出现在**本地库无该类目覆盖**的门店上（实测 3 家海宁银泰店，"
            "其 P 全为 1.0，即周边无竞品）。REF_DP 两侧差异 ≤0.01%。"
            "⇒ 引擎常量按引擎口径取，标定产物按标定链口径记，**不可互换**。")
    return out


def lam() -> dict:
    """② λ 敏感性 —— 样本量同上（83 家），数值从敏感性表实时读。"""
    out = {}
    try:
        c = _engine_consts()
        out['值'] = c['LAMBDA']
        out['最小等效距离m'] = c['D0']
    except Exception as e:                                # noqa: BLE001
        out['值'] = None
        out['失败'] = repr(e)
    cs = _rows(F_SENS_CSV)
    if cs:
        # ⚠️ 这个 CSV 里**叠了两张表**（第二张表头是「对比λ(vs 2.0),Top10重合,Bottom10重合」，
        #    值形如 1.0,0.8,0.8）。DictReader 只认第一个表头 → 第二张表会被读成
        #    "Spearman = 0.8"并污染 min（实测：最低相关从 0.937 被读成 0.8）。
        #    判据 = 严格按第一张表读，遇到解析不出浮点数的首列就停。
        pairs, seen_lam = [], []
        for r in cs:
            try:
                a, b, s = (float(r['λ1']), float(r['λ2']),
                           float(r['Spearman排名相关']))
            except (KeyError, TypeError, ValueError):
                break                          # 第二张表（或空行）→ 收工
            pairs.append((a, b, s))
            for v in (a, b):
                if v not in seen_lam:
                    seen_lam.append(v)
        if pairs:
            lo, hi = min(seen_lam), max(seen_lam)
            out['λ取值'] = sorted(seen_lam)
            out['全区间'] = f'λ∈[{lo:.1f}, {hi:.1f}]'
            out['全区间最低相关'] = min(s for _a, _b, s in pairs)
            band = [(a, b, s) for a, b, s in pairs
                    if 1.5 <= a <= 2.5 and 1.5 <= b <= 2.5]
            out['文献区间'] = 'λ∈[1.5, 2.5]'
            out['文献区间最低相关'] = min((s for _a, _b, s in band), default=None)
            out['敏感性来源'] = _stamp(F_SENS_CSV)
    return out


def uplift() -> dict:
    """③ 品牌溢价口径 —— 引擎在用，但**样本集与锚点不同**（扩样后）。

    ⚠️ 这里有两个产物，**引擎的表用的是 v7（直线口径）**：
      · `brand_uplift_v3.json`      —— v7，**引擎在用的就是它**；
      · `brand_uplift_v3_road.json` —— v8 步行路网口径，**已备好但未采用**。

    为什么 v8 没采用（2026-09-20 实测，必须讲清，否则下一个人会以为漏了）：
      换成路网口径后，**3 个 TIER1 品牌（奈雪/春莱/瑞幸）的点估计掉出了自己的 CI**
      —— 因为 TIER1 免 clamp（点估计可到 1.33/1.36/1.52），而 CI 仍按带 clamp 的
      口径算（上界被钉在 1.25）。项目自己有一条不变式「**点估计必须落在 CI 内**」
      （`verify_place_first` 在断言它），v8 产物当场把它判红。
      ⇒ 要采用 v8 必须先裁决 **CI 是否也随 TIER1 免 clamp**（规则变更，需单独决定）。
    """
    out = {}
    # 引擎表的来源：brands.py 的四张常量表当前抄自哪一份产物
    out['产物候选'] = {
        'v7_直线（引擎在用）': F_UPLIFT_PROD,
        'v8_步行路网（备好未采用）': F_UPLIFT_ROAD,
    }
    prod = _json(F_UPLIFT_PROD)          # 引擎的表来自 v7 —— 这里**不**改成 v8
    used = F_UPLIFT_PROD
    if prod:
        pr = prod.get('params') or {}
        dist = prod.get('distance') or 'haversine（直线）'
        out['被引用产物'] = used
        out['引擎表口径'] = f'{prod.get("version")} · {dist}'
        out['口径'] = (f"品牌盲残差（{prod.get('version')}）：自己 own_S 置 1.0、"
                       f"竞品保持真实，得到与 own_S 正交的残差 → 消掉"
                       f"\"经 P 计一次、再乘一次\"的双算。距离口径：{dist}")
        out['clamp分层'] = bool(pr.get('clamp_tier1_exempt'))
        cov = prod.get('coverage') or {}
        if cov:
            out['取数覆盖'] = cov
    # 备好的 v8 产物：只报"已备好 + 差多少 + 为什么没用"
    road = _json(F_UPLIFT_ROAD)
    if road:
        rb = road.get('brands') or {}
        vb = (prod or {}).get('brands') or {}
        diffs = []
        for b, rv in rb.items():
            vv = vb.get(b)
            if not vv or not vv.get('uplift') or not rv.get('uplift'):
                continue
            diffs.append((b, vv['uplift'], rv['uplift'],
                          abs(rv['uplift'] - vv['uplift']) / vv['uplift'] * 100))
        diffs.sort(key=lambda t: -t[3])
        t1r = sorted(b for b, v in rb.items() if v.get('tier') == 'TIER1')
        out['v8_备好未采用'] = {
            '样本': (road.get('sample') or {}).get('n_used'),
            '取数': road.get('coverage') or {},
            'TIER1': t1r,
            '最大差异品牌': [{'品牌': b, 'v7': round(v, 4), 'v8': round(r, 4),
                          '差%': round(d, 2)} for b, v, r, d in diffs[:5]],
            '中位差%': round(_med([d for *_x, d in diffs]) or 0, 2),
            '为什么没采用': ('v8 下奈雪/春莱/瑞幸的点估计**掉出自己的 CI**'
                         '（TIER1 免 clamp 但 CI 仍带 clamp，上界钉在 1.25）——'
                         '违反项目不变式「点估计落在 CI 内」，'
                         '需先裁决"CI 是否也随 TIER1 免 clamp"再采用。'),
        }
    try:
        c = _engine_consts()
        up, tier = c['UPLIFT'], c['UPLIFT_TIER']
        out['品牌数'] = len(up)
        t1 = sorted(b for b, t in tier.items() if t == 'TIER1')
        out['TIER1'] = t1
        out['TIER1数'] = len(t1)
        out['启用中'] = bool(c['USE_BRAND_UPLIFT'])
        # 常用示例（含样本量）：知识页/语料要举例子时**从这里取**，别手抄
        try:
            from engine.brands import _UPLIFT_N
        except Exception:                                 # noqa: BLE001
            _UPLIFT_N = {}
        out['示例'] = {b: {'uplift': up.get(b), 'n': _UPLIFT_N.get(b)}
                     for b in ('瑞幸', '喜茶', '茶百道', '蜜雪冰城', '古茗')
                     if b in up}
    except Exception as e:                                # noqa: BLE001
        out['品牌数'] = None
        out['失败'] = repr(e)
    out['表来源'] = _stamp(F_BRANDS)

    if prod:
        s = prod.get('sample') or {}
        out['样本'] = {'奶茶POI': s.get('n_poi'), '锚定商圈': s.get('n_anchored'),
                      '采用': s.get('n_used'), '商圈数': s.get('n_districts')}
        out['样本来源'] = _stamp(used)
    else:
        out['样本'] = None
    return out


def expansion() -> dict:
    """④ Huff 扩样**探索**口径 —— 离线产物，**未接入锚点**（必须显式说明原因）。"""
    out = {'接入引擎锚点': False}
    rows = _rows(F_EXPAND_CSV)
    if rows is None:
        out['失败'] = '扩样产物读不到'
        return out
    n_all = len(rows)
    n_used = sum(1 for r in rows if (r.get('采用') or '').strip() == 'Y')
    n_low = sum(1 for r in rows if (r.get('低证据点') or '').strip())
    brands, dists = set(), set()
    for r in rows:
        if (r.get('品牌') or '').strip():
            brands.add(r['品牌'].strip())
        if (r.get('商圈') or '').strip():
            dists.add(r['商圈'].strip())
    out.update({
        '锚定商圈': n_all, '可用': n_used, '低证据点': n_low,
        '品牌数': len(brands), '商圈数': len(dists),
        '来源': _stamp(F_EXPAND_CSV),
    })
    base = None
    prod = _json(F_UPLIFT_PROD)
    if prod:
        base = (prod.get('sample') or {}).get('n_poi')
    if base and n_used:
        out['相对锚点样本倍数'] = round(n_used / 83, 1)
    out['为什么不接入'] = ('本地库覆盖不完整、且随商圈变化（实测 in77 点位库内 19 家'
                        ' vs 高德实时 49 家 = 39%），是**水平偏差不是随机误差** → '
                        '扩样后的 D×P 绝对水平不能直接当新锚点；要动锚点必须先"补库"'
                        '或做"库→实时"校正。')
    out['说明'] = ('本块与"品牌溢价"是**两套不同的样本口径**（本块 2298 锚定基于'
                 '扩样脚本自己的商圈索引），**不可直接与品牌溢价块的 1508/3563 比大小**'
                 '（1508 = v8 步行路网口径采用家数；v7 直线口径下为 1631）。')
    return out


def variance() -> dict:
    """⑤ 方差分解（那个"品牌不可辨识"的证据）—— 来自 83 家标定产物。"""
    prod = _json(F_ANCHOR_PROD)
    out = {}
    if prod:
        ab = prod.get('anchor_by_brand') or {}
        out['为什么不按品牌标定'] = ab.get('reason')
        out['来源'] = _stamp(F_ANCHOR_PROD)
    return out


def thresholds() -> dict:
    """⑥ 阈值类常量（回本上限、评分区间、竞争分截断）。

    ⚠️ `竞争分截断P` 是**推导量**（`100×P_REF/60`），不是写死的常数 ——
    P_REF 一动它就跟着动，所以必须当场算。
    v8（步行路网口径，P_REF=0.6024）下该阈值为 **1.0040 > 1** ⇒ 由于 P ≤ 1，
    **`min(100, …)` 封顶永不触发**（P=1 时竞争分只有 99.60）。这一条很重要：
    v7 及更早的 P_REF=0.5012 阈值为 0.8353，封顶会**抹平品牌间差异**，
    曾让"竞争压力与品牌无关"那条断言**靠封顶假绿**（见 verify_brand_closedloop）。
    """
    out = {}
    try:
        c = _engine_consts()
        p_ref = c['P_REF'].get('奶茶')
        if p_ref:
            out['竞争分截断P'] = round(100.0 * p_ref / 60.0, 4)
            out['截断含义'] = ('竞争分 s = 60×P/P_REF 封顶 100 ⇒ P 超过该值时'
                            '品牌在竞争维度**不可区分**（差异只体现在流水上）')
    except Exception as e:                                # noqa: BLE001
        out['失败'] = repr(e)
    try:
        from engine.scoring import (PAYBACK_LIMIT_MONTHS, BUSINESS_SCORE_WEIGHTS,
                                    BUSINESS_SCORE_BOUNDS)
        from engine.utilities import AMORTIZE_MONTHS
        lo, hi = BUSINESS_SCORE_BOUNDS['回本周期']      # (36.0, 12.0)，方向相反
        out['回本上限月'] = PAYBACK_LIMIT_MONTHS
        out['回本评分零分月'] = lo
        out['回本评分满分月'] = hi
        out['月摊销月数'] = AMORTIZE_MONTHS
        out['经营评分权重'] = dict(BUSINESS_SCORE_WEIGHTS)
        out['两个"36"不是一回事'] = ('回本评分零分线 36 个月 vs 摊销 36 个月：'
                              '回本 = 投入/(月净利+月摊销)，两者含义不同，不可互换')
    except Exception as e:                                # noqa: BLE001
        out['阈值失败'] = repr(e)
    out['来源'] = _stamp(F_SCORING)
    return out


def benchmarks() -> dict:
    """⑦ 品牌级经营基准（招股书/年报口径）—— 实时读公开数据表。

    `推算日单量` = 单店日均出杯量 ÷ 每单杯数（当场算，不写死）。
    `每单金额来源` 保留「披露 / 推导」两态：本系统不许把推导值说成披露值。
    """
    F = 'src/engine/brand_store_metrics.csv'
    rows = _rows(F)
    if rows is None:
        return {'失败': '品牌经营基准表读不到', '来源': F}

    def _f(r, k):
        try:
            return float((r.get(k) or '').strip())
        except ValueError:
            return None

    out = {'来源': _stamp(F), '品牌': {}}
    for r in rows:
        b = (r.get('品牌') or '').strip()
        if not b:
            continue
        gmv, cups = _f(r, '单店日均GMV元'), _f(r, '单店日均出杯量')
        per_order, per_order_cups = _f(r, '每单平均金额元'), _f(r, '每单杯数')
        # 推算日单量优先用 GMV ÷ 每单金额（自洽性最好：蜜雪 4184.4/11.4 = 367.0，
        # 与招股书口径对得上）；缺了才退回 出杯量 ÷ 每单杯数。
        orders, how = None, None
        if gmv and per_order:
            orders, how = round(gmv / per_order), '日均GMV÷每单金额'
        elif cups and per_order_cups:
            orders, how = round(cups / per_order_cups), '日均出杯量÷每单杯数'
        out['品牌'][b] = {
            '期间': (r.get('期间') or '').strip() or None,
            '单杯均价元': _f(r, '单杯均价元'),
            '每单金额元': per_order,
            '日均GMV元': gmv,
            '日均出杯量': cups,
            '每单杯数': per_order_cups,
            '推算日单量': orders,
            '推算方式': how,
            '每单金额来源': (r.get('每单金额来源') or '').strip() or None,
            '数据来源': (r.get('数据来源') or '').strip() or None,
        }
    return out


def audit_findings() -> dict:
    """⑧ 历史审计结论 —— **显式标注"非实时"**。

    为什么单独拎出来：这几条是**一次性回归**的结论（已证伪/已否定），
    仓库里**没有可复跑的产物**（仅存在于注释与 docs）。所以**不能假装实时**：
    给出结论 + 出处文件，让读者自己去核。改口径时这几条**必须人工复核**。
    """
    return {
        '标注': '以下为历史审计结论，**非实时**（无可复跑产物）；'
                '若相关口径改动，必须人工复核本节',
        '条目': [
            {'项': '外卖月售作为经营代理',
             '结论': '已证伪并停用 —— P_brand ↔ 外卖月售 = −0.229（p=0.037），方向与预期相反',
             '出处': 'src/engine/scoring.py（ELASTICITY_CALIPERS 上方注释）、docs/四能力实现度审计.md'},
            {'项': '按品牌分别标定锚点',
             '结论': '已否定 —— 品牌与商圈高度混淆（同品牌跨商圈 D×P 可差数倍），'
                     '"品牌锚点"实为"商圈锚点"',
             '出处': 'src/analysis/brand_uplift.json::anchor_by_brand、'
                     'src/analysis/anchor_calib.csv'},
            {'项': '客单价把"单杯价"当"每单金额"',
             '结论': '已修（单位错误）—— 高德 biz_ext.cost 是单杯价；'
                     '同一品牌两个数可差 1.4~1.7 倍',
             '出处': 'docs/品牌级公开数据与客单价口径修正.md'},
        ],
    }


def collect() -> dict:
    """汇总全部事实。任一块失败只影响该块（返回 None + 失败原因），不炸整体。"""
    facts = {'生成时间': datetime.now().strftime('%Y-%m-%d %H:%M')}
    for name, fn in (('锚点', anchor), ('λ敏感性', lam), ('品牌溢价', uplift),
                     ('扩样探索', expansion), ('方差分解', variance),
                     ('阈值', thresholds), ('品牌经营基准', benchmarks),
                     ('历史审计结论', audit_findings)):
        try:
            facts[name] = fn()
        except Exception as e:                            # noqa: BLE001
            facts[name] = {'失败': repr(e)}
    return facts


# ---------------------------------------------------------------
# 渲染给 LLM 的实时块（专家 prompt 用）
# ---------------------------------------------------------------
BLOCKS = ('锚点', 'λ敏感性', '品牌溢价', '扩样探索', '方差分解',
          '阈值', '品牌经营基准', '历史审计结论')


def render_for_prompt(facts: dict = None, blocks=None) -> str:
    """把事实渲染成一段**可直接引用的**紧凑文本。

    `blocks` 给定时只渲染指定的那几块（专家可以只要"锚点"不要"扩样探索"）。

    刻意写成"引用即用"的口吻并标注生成时间：LLM 看到实时块就不该再凭记忆写数。
    不出现任何写死数值 —— 全部来自 facts。
    """
    f = facts or collect()
    if blocks:
        want = {b for b in blocks if b in BLOCKS}
        f = {k: v for k, v in f.items() if k == '生成时间' or k in want}
    L = []
    L.append(f'【本模型实时事实 · 自动生成于 {f.get("生成时间")}】')
    L.append('以下数值由引擎常量与标定产物**当场读出**。引用模型证据时'
             '**必须用本块的数**，不要凭记忆写，也不要把不同口径的数字混在一句话里。')

    a = f.get('锚点') or {}
    e = f.get('扩样探索') or {}
    if a.get('引擎在用'):
        L.append('')
        L.append('① 锚点（流水/竞争分，引擎在用）')
        L.append(f"   · REF_DP = {a['引擎在用'].get('REF_DP')}，"
                 f"P_REF = {a['引擎在用'].get('P_REF')}")
        # 样本量主数字 = 扩样可用数（策 2026-09-18 拍板：对外样本量显示 796），
        # 但 83 手标 / 77 采用 才是引擎当前**真正生效**的锚点标定样本，
        # 二者口径不同，必须并列讲清，不能只报 796 而丢掉"引擎用的是 83 家"这个真相。
        n_main = (e.get('可用')) if (e and e.get('可用')) else None
        n_hand = (a.get('逐店明细') or {}).get('家数')
        n_used_eng = (a.get('引擎口径重算') or {}).get('采用')
        if n_main:
            L.append(f"   · 标定样本量：{n_main} 家（离线扩样探索的可用样本）")
        if n_used_eng:
            d = a.get('逐店明细') or {}
            L.append(f"   · 引擎当前生效锚点：{n_used_eng} 家真实门店（总样本 "
                     f"{n_hand} 家 / {d.get('商圈数')} 个商圈："
                     f"{'、'.join(d.get('商圈') or [])}）")
        if a.get('引擎口径重算'):
            r = a['引擎口径重算']
            L.append(f"   · 锚点口径（当场按引擎口径重算）：{a.get('口径')}"
                     f" → REF_DP {r.get('REF_DP')} / P_REF {r.get('P_REF')}")
        if a.get('标定产物'):
            g = a['标定产物']
            L.append(f"   · 标定产物**另一口径**（纯本地库 REALTIME=0）："
                     f"{g.get('实际采用')} 家采用 / 总样本 {g.get('总样本')} 家"
                     f" → REF_DP {g.get('REF_DP')} / P_REF {g.get('P_REF')}"
                     f" / P_REF_unadj {g.get('P_REF_unadj')}")
        if n_main and e.get('为什么不接入'):
            L.append(f"   · ⚠️ {n_main} 家是扩样样本，**未接入引擎锚点**：{e.get('为什么不接入')}")
        if a.get('对拍'):
            L.append(f"   · 对拍（引擎常量 − 同口径重算）：{a['对拍']}")
        if a.get('口径差异说明'):
            L.append(f"   · ⚠️ 口径差异：{a['口径差异说明']}")

    l = f.get('λ敏感性') or {}
    if l.get('值') is not None:
        L.append('')
        L.append(f"② 距离衰减 λ = {l['值']}，最小等效距离 d0 = {l.get('最小等效距离m')} m"
                 f"（声明式设定 + 敏感性检验，非逐店拟合）")
        if l.get('全区间最低相关') is not None:
            # 样本量取①的逐店家数（不写死）——敏感性表本身不带样本量，同一批门店。
            n_lam = (a.get('逐店明细') or {}).get('家数')
            who = f'{n_lam} 家门店' if n_lam else '标定样本门店'
            L.append(f"   · 敏感性（同①的 {who}）："
                     f"{l.get('全区间')} 内排名两两 Spearman 最低 "
                     f"{l['全区间最低相关']}；{l.get('文献区间')} 内最低 "
                     f"{l.get('文献区间最低相关')} ⇒ 结论不依赖 λ 精确取值")

    u = f.get('品牌溢价') or {}
    if u.get('品牌数'):
        L.append('')
        L.append(f"③ 品牌溢价 UPLIFT（引擎在用）")
        L.append(f"   · 已标定 {u['品牌数']} 个品牌；TIER1 {u.get('TIER1数')} 个："
                 f"{'、'.join(u.get('TIER1') or [])}")
        s = u.get('样本') or {}
        if s.get('采用'):
            L.append(f"   · **样本口径与①不同**：{s.get('采用')} 家（奶茶 POI "
                     f"{s.get('奶茶POI')} 条 → 锚定 {s.get('锚定商圈')} → 采用 "
                     f"{s.get('采用')}）、{s.get('商圈数')} 个商圈"
                     f"、引擎表口径 {u.get('引擎表口径')}")
        cov = u.get('取数覆盖') or {}
        if cov:
            L.append(f"   · 取数覆盖：API {cov.get('api_calls')} 次 / 失败 "
                     f"{cov.get('api_fail')}；**直线回退 {cov.get('straight_fallback')} 点**"
                     f"（非 0 即混口径）；冻结路网对 {cov.get('road_pairs')}")
        L.append(f"   · 方法：{u.get('口径')}")
        r8 = u.get('v8_备好未采用') or {}
        if r8:
            L.append(f"   · ⚠️ **已有 v8 步行路网口径产物（{r8.get('样本')} 家采用），"
                     f"但未采用**：{r8.get('为什么没采用')}")
            L.append(f"     v8 的 TIER1 是 {'、'.join(r8.get('TIER1') or [])}；"
                     f"与 v7 的差中位 {r8.get('中位差%')}%，最大差异品牌 "
                     f"{'、'.join(str(d['品牌']) + '(v7 ' + str(d['v7']) + '→v8 ' + str(d['v8']) + ')' for d in (r8.get('最大差异品牌') or [])[:3])}。"
                     f"要采用需先裁决 CI 口径。")

    e = f.get('扩样探索') or {}
    if e.get('可用'):
        L.append('')
        L.append('④ Huff 扩样探索（离线产物，**未接入锚点**）')
        L.append(f"   · 锚定商圈 {e.get('锚定商圈')} 家 → 可用 {e.get('可用')} 家"
                 f"（{e.get('品牌数')} 个品牌、{e.get('商圈数')} 个商圈）"
                 f"，相对手标锚点样本约 ×{e.get('相对锚点样本倍数')}")
        L.append(f"   · 为何没接入：{e.get('为什么不接入')}")
        L.append(f"   · 口径提醒：{e.get('说明')}")

    v = f.get('方差分解') or {}
    if v.get('为什么不按品牌标定'):
        L.append('')
        L.append(f"⑤ 不按品牌标定锚点的证据：{v['为什么不按品牌标定']}")

    t = f.get('阈值') or {}
    if t.get('竞争分截断P') is not None:
        L.append('')
        L.append('⑥ 阈值（引擎常量 / 推导量）')
        L.append(f"   · 竞争分截断：P > {t['竞争分截断P']} 一律 100 分"
                 f"（= 100×P_REF/60，P_REF 变则跟着变）——{t.get('截断含义')}")
        if t.get('回本上限月') is not None:
            w = t.get('经营评分权重') or {}
            L.append(f"   · 一票否决：月净利 ≤0 或回本 > {t['回本上限月']} 个月 "
                     f"→ 经营评分封顶（不允许出现「位置好 + 经营评分高」）")
            L.append(f"   · 经营评分 = 净利率 ×{w.get('净利率')} + 回本周期 ×{w.get('回本周期')}"
                     f"（回本 ≤{t.get('回本评分满分月')} 月满分、"
                     f"≥{t.get('回本评分零分月')} 月零分）")
            L.append(f"   · ⚠️ {t.get('两个\"36\"不是一回事')}")

    b = f.get('品牌经营基准') or {}
    if b.get('品牌'):
        L.append('')
        L.append('⑦ 品牌级经营基准（招股书/年报口径，来自品牌公开数据表）')
        for name in ('蜜雪冰城', '瑞幸', '茶百道', '沪上阿姨'):
            d = b['品牌'].get(name)
            if not d:
                continue
            # 缺的字段直接省略，不写 "None 元" 占位（免得模型读成 0）
            seg = []
            if d.get('单杯均价元') is not None:
                seg.append(f"单杯均价 {d['单杯均价元']} 元")
            if d.get('每单金额元') is not None:
                seg.append(f"每单金额 {d['每单金额元']} 元"
                           f"（{d.get('每单金额来源') or '来源未标'}）")
            if d.get('推算日单量') is not None:
                seg.append(f"推算日单量 {d['推算日单量']} 单"
                           f"（{d.get('推算方式')}）")
            if seg:
                L.append(f"   · {name}（{d.get('期间')}）：" + '、'.join(seg))
        L.append('   · ⚠️ 「披露 / 推导」两态不许混说：推导值不能讲成公司披露值')

    au = f.get('历史审计结论') or {}
    if au.get('条目'):
        L.append('')
        L.append(f"⑧ {au.get('标注')}")
        for it in au['条目']:
            L.append(f"   · {it['项']} → {it['结论']}（出处：{it['出处']}）")

    return '\n'.join(L)


_UI_CACHE = {'t': 0.0, 'v': None}
UI_TTL = 60.0            # 侧栏轮询频繁（秒级），给 UI 侧一个短缓存；prompt 侧不缓存。


def render_for_ui(use_cache: bool = True) -> dict:
    """给前端（sidebar.json.facts）用的精简结构：只有要展示的数字与口径。

    ⚠️ 前端**不许**自己再存一份"当前锚点值" —— 那份值只住在这里。
    带 60 秒短缓存：`sidebar.json` 是秒级轮询写的，而扩样表有几千行，
    每次轮询都重读一遍纯属浪费（1 分钟内数字不可能变）。
    """
    if use_cache:
        now = time.time()
        if _UI_CACHE['v'] is not None and now - _UI_CACHE['t'] < UI_TTL:
            return _UI_CACHE['v']
    f = collect()
    a, u, e = f.get('锚点') or {}, f.get('品牌溢价') or {}, f.get('扩样探索') or {}
    t = f.get('阈值') or {}
    out = {
        '生成时间': f.get('生成时间'),
        '锚点': {
            'REF_DP': (a.get('引擎在用') or {}).get('REF_DP'),
            'P_REF': (a.get('引擎在用') or {}).get('P_REF'),
            '标定样本量': e.get('可用'),
            '总样本': (a.get('逐店明细') or {}).get('家数'),
            '实际采用': (a.get('标定产物') or {}).get('实际采用'),
            '商圈数': (a.get('逐店明细') or {}).get('商圈数'),
            '口径': a.get('口径'),
        },
        '阈值': {
            '竞争分截断P': t.get('竞争分截断P'),
            '回本上限月': t.get('回本上限月'),
            '回本评分零分月': t.get('回本评分零分月'),
            '回本评分满分月': t.get('回本评分满分月'),
            '摊销月数': t.get('月摊销月数'),
        },
        '品牌溢价': {
            '品牌数': u.get('品牌数'), 'TIER1数': u.get('TIER1数'),
            'TIER1': u.get('TIER1'), '采用': (u.get('样本') or {}).get('采用'),
        },
        '扩样探索': {
            '锚定': e.get('锚定商圈'), '可用': e.get('可用'),
            '接入引擎锚点': e.get('接入引擎锚点'),
        },
    }
    if use_cache:
        _UI_CACHE['t'], _UI_CACHE['v'] = time.time(), out
    return out


if __name__ == '__main__':
    import io as _io
    sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    print('=' * 68)
    print(render_for_prompt())
    print('=' * 68)
    print(json.dumps(collect(), ensure_ascii=False, indent=2))
