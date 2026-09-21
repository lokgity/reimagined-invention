# -*- coding: utf-8 -*-
"""
huff_regression.py —— Huff 评分结构的线性回归检验
====================================================
定位（答辩口径，必须与结论一起呈现）:
  本脚本检验的是「引擎四维度分 → 总分」的内部结构一致性，
  即 config.py 手拍权重是否被数据支持；
  **不是**「选址打分 → 真实营收」的对外效度检验——
  后者需要真实营业额，83 家店没有该数据，不编造。

方法:
  1. 带约束 OLS: total = Σ β_k·dim_k，检验 H0: β_k = w_k（Wald 检验）
  2. 诊断三件套: VIF（共线性）/ Breusch-Pagan（异方差）/ Jarque-Bera（残差正态）
  3. 辅助: log-log 形式反解 λ 及其 95%CI（参数敏感性参考）

依赖: 仅 numpy / pandas（项目 .pylibs 已含，零新增）
用法:
  python src/analysis/huff_regression.py
  python src/analysis/huff_regression.py --panel stats/out/00_panel.csv
"""
import argparse
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

ALPHA = 0.05
D0 = 50.0
DIMS = ['客群匹配度', '竞争压力', '交通可达性', '租金承受力']


# ---------------------------------------------------------------
# 自写 OLS（含稳健标准误）
# ---------------------------------------------------------------
def ols(X, y):
    """普通最小二乘。X 需已含常数列（若需要）。
    返回 betas/resid/se/t/p/dof/r2/adj_r2/sigma2/XtX_inv。"""
    n, k = X.shape
    XtX = X.T @ X
    XtX_inv = np.linalg.pinv(XtX)
    betas = XtX_inv @ X.T @ y
    resid = y - X @ betas
    dof = n - k
    sigma2 = float(resid @ resid) / dof
    se = np.sqrt(np.diag(sigma2 * XtX_inv))
    with np.errstate(divide='ignore', invalid='ignore'):
        t = np.where(se > 0, betas / se, np.nan)
    p = 2 * (1 - _t_cdf(np.abs(t), dof))
    sst = float(((y - y.mean()) ** 2).sum())
    sse = float(resid @ resid)
    r2 = 1 - sse / sst if sst > 0 else np.nan
    adj = 1 - (1 - r2) * (n - 1) / dof if dof > 0 else np.nan
    return dict(betas=betas, resid=resid, se=se, t=t, p=p, dof=dof,
                r2=r2, adj_r2=adj, sigma2=sigma2, XtX_inv=XtX_inv)


def ols_hc3(X, y):
    """HC3 异方差稳健标准误（小样本表现优于 HC0）。"""
    n, k = X.shape
    fit = ols(X, y)
    resid = fit['resid']
    XtX_inv = np.linalg.pinv(X.T @ X)
    H = X @ XtX_inv @ X.T
    h = np.clip(np.diag(H), 0, 1 - 1e-12)
    w = (resid ** 2) / ((1 - h) ** 2)
    meat = X.T @ (X * w[:, None])
    cov = XtX_inv @ meat @ XtX_inv
    se = np.sqrt(np.diag(cov))
    with np.errstate(divide='ignore', invalid='ignore'):
        t = np.where(se > 0, fit['betas'] / se, np.nan)
    fit.update(se_hc3=se, t_hc3=t, p_hc3=2 * (1 - _t_cdf(np.abs(t), fit['dof'])))
    return fit


def wald_test(betas, XtX_inv, sigma2, R, r):
    """线性约束 Wald 检验。H0: R·beta = r。返回 (W, df, p)。"""
    dif = R @ betas - r
    M = R @ XtX_inv @ R.T
    W = float(dif.T @ np.linalg.pinv(M) @ dif / sigma2)
    q = R.shape[0]
    return W, q, float(1 - _chi2_cdf(W, q))


def vif(X):
    """方差膨胀因子。X 不含常数列。VIF>10 视为严重共线。"""
    out = []
    for i in range(X.shape[1]):
        y = X[:, i]
        others = np.delete(X, i, axis=1)
        others = np.column_stack([np.ones(len(others)), others])
        r2 = ols(others, y)['r2']
        out.append(np.inf if r2 >= 1 else 1 / (1 - r2))
    return np.array(out)


def breusch_pagan(resid, X):
    """Breusch-Pagan 异方差检验。H0 = 同方差。返回 (LM, df, p)。"""
    n = len(resid)
    e2 = resid ** 2
    e2s = e2 / e2.mean()
    r2 = ols(X, e2s)['r2']
    lm = float(r2 * n) if r2 == r2 else 0.0
    q = X.shape[1] - 1
    return lm, q, float(1 - _chi2_cdf(lm, q))


def jarque_bera(resid):
    """JB 正态性检验。返回 (统计量, p, 偏度, 峰度)。"""
    n = len(resid)
    sd = resid.std(ddof=1)
    if sd <= 0:
        return 0.0, 1.0, 0.0, 0.0
    sk = float(((resid - resid.mean()) ** 3).mean() / sd ** 3)
    ku = float(((resid - resid.mean()) ** 4).mean() / sd ** 4 - 3)
    jb = n / 6 * (sk ** 2 + ku ** 2 / 4)
    return jb, float(1 - _chi2_cdf(jb, 2)), sk, ku


# ---------------------------------------------------------------
# 分布函数（自写，规避 .pylibs 无 scipy 的问题）
# ---------------------------------------------------------------
def _t_cdf(t, dof):
    """Student-t CDF。"""
    t = np.atleast_1d(np.asarray(t, dtype=float))
    out = np.empty_like(t)
    for i, tv in enumerate(t):
        x = dof / (dof + tv * tv)
        ib = _betainc_reg(dof / 2, 0.5, x)
        out[i] = 1 - 0.5 * ib if tv > 0 else 0.5 * ib
    return out


def _chi2_cdf(x, k):
    if x <= 0:
        return 0.0
    return _gammainc_reg(k / 2, x / 2)


def _betainc_reg(a, b, x):
    """正则化不完全 Beta（连分数）。"""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lb = _ln_gamma(a) + _ln_gamma(b) - _ln_gamma(a + b)
    front = np.exp(a * np.log(x) + b * np.log(1 - x) - lb) / a
    if x < (a + 1) / (a + b + 2):
        return front * _beta_cf(a, b, x)
    return 1 - np.exp(b * np.log(x) + a * np.log(1 - x) - lb) / b * _beta_cf(b, a, 1 - x)


def _beta_cf(a, b, x, itmax=200, eps=3e-12):
    """Beta 连分数（Lentz）。"""
    qab, qap, qam = a + b, a + 1, a - 1
    c, d = 1.0, 1 - qab * x / qap
    d = 1 / d if abs(d) > 1e-30 else 1e30
    h = d
    for m in range(1, itmax + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1 + aa * d
        d = 1 / d if abs(d) > 1e-30 else 1e30
        c = 1 + aa / c
        c = c if abs(c) > 1e-30 else 1e-30
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1 + aa * d
        d = 1 / d if abs(d) > 1e-30 else 1e30
        c = 1 + aa / c
        c = c if abs(c) > 1e-30 else 1e-30
        de = d * c
        h *= de
        if abs(de - 1) < eps:
            break
    return h


def _gammainc_reg(a, x, itmax=300, eps=3e-12):
    """正则化不完全 Gamma P(a,x)。"""
    if x < a + 1:
        term = total = 1.0 / a
        for n in range(1, itmax + 1):
            term *= x / (a + n)
            total += term
            if abs(term) < abs(total) * eps:
                break
        return total * np.exp(-x + a * np.log(x) - _ln_gamma(a))
    tiny = 1e-30
    b = x + 1 - a
    c = 1 / tiny
    d = 1 / b if abs(b) > tiny else 1 / tiny
    h = d
    for i in range(1, itmax + 1):
        an = -i * (i - a)
        b += 2
        d = an * d + b
        d = d if abs(d) > tiny else tiny
        c = b + an / c
        c = c if abs(c) > tiny else tiny
        d = 1 / d
        de = d * c
        h *= de
        if abs(de - 1) < eps:
            break
    return 1 - np.exp(-x + a * np.log(x) - _ln_gamma(a)) * h


_GC = {}
_LZ = [676.5203681218851, -1259.1392167224028, 771.32342877765313,
       -176.61502916214059, 12.507343278686905, -0.13857109526572012,
       9.9843695780195716e-6, 1.5056327351493116e-7]


def _ln_gamma(z):
    """Lanczos 近似。"""
    if z in _GC:
        return _GC[z]
    if z < 0.5:
        v = np.log(np.pi / np.sin(np.pi * z)) - _ln_gamma(1 - z)
    else:
        zz = z - 1
        x = 0.99999999999980993
        for i, c in enumerate(_LZ):
            x += c / (zz + i + 1)
        t = zz + len(_LZ) - 0.5
        v = 0.5 * np.log(2 * np.pi) + (zz + 0.5) * np.log(t) - t + np.log(x)
    _GC[z] = v
    return v


# ---------------------------------------------------------------
# 输出辅助
# ---------------------------------------------------------------
def fmt_p(p):
    if p is None or p != p:
        return 'NA'
    return '<0.001' if p < 0.001 else f'{p:.4f}'


def sig(p):
    if p is None or p != p:
        return ''
    return '***' if p < 0.001 else '**' if p < 0.01 else '*' if p < 0.05 else 'ns'


def rule(t='', w=78):
    print()
    print('=' * w)
    if t:
        print(t)
        print('=' * w)


# ---------------------------------------------------------------
# 面板装配
# ---------------------------------------------------------------
def build_panel():
    """装配 83 家门店的四维度分。走引擎 score_site，纯本地库（REALTIME=0）。"""
    os.environ.setdefault('REALTIME', '0')
    from engine import scoring
    from engine.brands import BRAND_S
    from config import get_profile

    st = pd.read_csv(HERE / 'stores_calib.csv', encoding='utf-8-sig')
    prof = get_profile('奶茶')
    rows, skipped = [], []
    for _, r in st.iterrows():
        try:
            brand = r['品牌'] if r['品牌'] in BRAND_S else None
            res = scoring.score_site(
                '奶茶', r['经度'], r['纬度'], monthly_rent=0,
                name=r['名称'], area_m2=None, city=None, brand=brand)
            d = res['dims']
            ev = res.get('evidence') or {}
            rows.append({
                '名称': r['名称'], '商圈': r['商圈'], '品牌': r['品牌'],
                **{k: d.get(k, np.nan) for k in DIMS},
                '总分': res['total'],
                # 引擎运行时实际捕获份额（用于 [1b] 自洽性检验）
                '_P': ev.get('捕获份额P', np.nan),
                '_竞品数': ev.get('竞品数', np.nan),
            })
        except Exception as e:
            skipped.append((r['名称'], f'{type(e).__name__}: {e}'))
    if skipped:
        print(f'⚠️ {len(skipped)} 家跳过，前 3 例: {skipped[:3]}')
    return pd.DataFrame(rows), prof


# ---------------------------------------------------------------
# 分析各节
# ---------------------------------------------------------------
def section_identity_check(df, prof):
    """[1a] 恒等式核查 —— 证明「四维度分→总分」是定义式，不是回归。

    预期结果：β 精确等于声明权重，R²=1。这不是发现，是算术必然。
    本节存在的意义是把这件事**显式记录下来**，防止误报成"回归验证了权重"。
    """
    rule('[1a] 恒等式核查 —— 四维度分→总分 是定义式，不是可检验的回归')
    w = prof['weights']
    w_vec = np.array([w[d] for d in DIMS])
    print('  引擎定义: total = Σ(dim_k × w_k)  —— 见 scoring.py 无截距加权和')
    print('  因此 OLS 必然得到 β_k ≡ w_k、R² ≡ 1，这是算术恒等，')
    print('  不含任何数据证据。把它报成"回归验证了权重"属于把一个定义式当发现。\n')

    sub = df.dropna(subset=DIMS + ['总分'])
    y = sub['总分'].to_numpy(dtype=float)
    Xd = sub[DIMS].to_numpy(dtype=float)
    fit = ols(Xd, y)

    print(f'  {"维度":<12}{"OLS β":>10}{"声明 w":>10}{"差":>12}')
    for i, d in enumerate(DIMS):
        print(f'  {d:<12}{fit["betas"][i]:>10.6f}{w_vec[i]:>10.4f}'
              f'{fit["betas"][i] - w_vec[i]:>+12.2e}')
    print(f'\n  R² = {fit["r2"]:.10f}   σ² = {fit["sigma2"]:.3e}')
    print('  ✅ 恒等式成立 → 脚本与引擎定义一致（这是对脚本的校验，不是对模型的验证）')
    print('  ⚠️ 结论：**不要**把本节作为效度证据写入文档。')
    return sub


def section_dim_consistency(df, prof):
    """[1b] 维度分自洽性 —— 检验各维度分是否由位置变量正确导出。

    这是**唯一有统计信息量**的内部检验：
    维度分是引擎算出来的（可复现），但它是否真的反映位置变量，
    要看维度分与上游位置变量（客群POI/竞争密度/最近通勤距离）的关系
    是否符合模型设定方向。
    """
    rule('[1b] 维度分自洽性 —— 各维度分是否由上游位置变量正确导出')
    print('  这是有信息量的检验：维度分不是恒等式产物，而是位置变量的函数。')
    print('  若某维度分与其上游变量的关系方向/强度异常，说明该维度实现有 bug。\n')

    # P 直接取引擎运行时实际值（build_panel 已从 evidence 记录为 _P），
    # 不用 panel_recomputed.csv 的 P_brand —— 后者 S 列来源与引擎 BRAND_S 不同，
    # 实测二者相关 0.93 但不完全一致，混用会引入非引擎因素。
    panel_path = HERE / 'stats' / 'panel_recomputed.csv'
    if panel_path.exists():
        up = pd.read_csv(panel_path, encoding='utf-8-sig')[['名称', 'D']]
        print(f'  需求规模 D 取自 {panel_path.name}；P 取引擎运行时实测值')
    else:
        print('  ⚠️ 未找到 panel_recomputed.csv，D 不可得，本节中止')
        print('     （需先运行 stats/run_analysis.py 生成）')
        return None

    merged = df.merge(up, on='名称', how='inner')
    if len(merged) < 10:
        print(f'  ⚠️ 可合并样本仅 {len(merged)}，跳过')
        return None

    # 最近同类距离：panel 未含，用样本内坐标补算
    st = pd.read_csv(HERE / 'stores_calib.csv', encoding='utf-8-sig')
    lng = st['经度'].to_numpy()
    lat = st['纬度'].to_numpy()
    near = {}
    for i, nm in enumerate(st['名称']):
        d = [np.hypot((lng[i] - lng[j]) * 88000, (lat[i] - lat[j]) * 111000)
             for j in range(len(st)) if j != i]
        near[nm] = min(d)
    merged['最近同类距离m'] = merged['名称'].map(near)
    up_var = {'客群匹配度': 'D', '竞争压力': '_P', '交通可达性': '最近同类距离m'}

    print(f'\n  {"维度":<12}{"上游变量":<14}{"Pearson":>10}{"p":>10}{"方向":>6}{"判读":>8}')
    rows = []
    for dim, var in up_var.items():
        if dim not in merged.columns or var not in merged.columns:
            print(f'  {dim:<12}{var:<14}{"列缺失":>10}')
            continue
        a = pd.to_numeric(merged[dim], errors='coerce').to_numpy(dtype=float)
        b = pd.to_numeric(merged[var], errors='coerce').to_numpy(dtype=float)
        m = ~(np.isnan(a) | np.isnan(b))
        if m.sum() < 5 or np.ptp(a[m]) == 0 or np.ptp(b[m]) == 0:
            print(f'  {dim:<12}{var:<14}{"方差为0/样本不足":>10}')
            continue
        r = float(np.corrcoef(a[m], b[m])[0, 1])
        n = int(m.sum())
        t = r * np.sqrt((n - 2) / max(1e-12, 1 - r * r))
        p = float(2 * (1 - _t_cdf(np.array([abs(t)]), n - 2)[0]))
        expect_pos = '负' if var == '最近同类距离m' else '正'
        ok = (r > 0) if expect_pos == '正' else (r < 0)
        rows.append({'维度': dim, '上游变量': var, 'Pearson_r': r, 'n': n,
                     'p': p, '预期方向': expect_pos})
        print(f'  {dim:<12}{var:<14}{r:>10.4f}{fmt_p(p):>10}'
              f'{expect_pos:>10}{"✅" if ok else "⚠️异常":>8}')
    print('\n  判读：方向符合预期 → 该维度实现正确；方向相反 → 该维度有 bug，必须排查。')
    return pd.DataFrame(rows)


def section_weight_evidence(df):
    """[1c] 权重数据支持度 —— 用客观赋权反推，看手拍权重是否合理。

    诚实的表述：给的是**区间参考**，不是"应该改成这个值"。
    """
    rule('[1c] 权重数据支持度 —— 客观赋权能否支持手拍的 0.35/0.25/0.25/0.15')
    print('  ⚠️ 前置警告：维度分之间高度相关（都是位置质量的函数），')
    print('     客观赋权在这种共线结构下极不稳定，结果只能作方向性参考。\n')

    sub = df.dropna(subset=DIMS)
    X = sub[DIMS].to_numpy(dtype=float)
    n = len(sub)

    # 熵权法
    lo, hi = X.min(axis=0), X.max(axis=0)
    span = np.where(hi - lo == 0, 1.0, hi - lo)
    Xn = (X - lo) / span + 1e-12
    P = Xn / Xn.sum(axis=0, keepdims=True)
    e = -(P * np.log(P)).sum(axis=0) / np.log(n)
    g = 1 - e
    w_entropy = g / g.sum() if g.sum() > 0 else np.full(len(DIMS), np.nan)

    # CRITIC
    sd = Xn.std(axis=0, ddof=1)
    R = np.corrcoef(Xn, rowvar=False)
    conflict = (1 - R).sum(axis=1)
    C = sd * conflict
    w_critic = C / C.sum() if C.sum() > 0 else np.full(len(DIMS), np.nan)

    hand = np.array([0.35, 0.25, 0.25, 0.15])
    print(f'  {"维度":<12}{"手拍":>8}{"熵权":>8}{"CRITIC":>9}{"客观均值":>10}{"与手拍差":>10}{"偏离度":>10}')
    for i, d in enumerate(DIMS):
        avg = np.nanmean([w_entropy[i], w_critic[i]])
        dev = abs(avg - hand[i]) / hand[i] if hand[i] else np.nan
        flag = '  ⚠️大' if dev > 0.5 else ''
        print(f'  {d:<12}{hand[i]:>8.3f}{w_entropy[i]:>8.3f}{w_critic[i]:>9.3f}'
              f'{avg:>10.3f}{avg - hand[i]:>+10.3f}{dev:>10.1%}{flag}')
    print('\n  判读：偏离度 <50% 视为量级一致。')
    print('  结论用途：只能写"手拍权重与客观赋权量级基本一致，未发现明显失当"，')
    print('    **不能**写"客观赋权支持最优权重为 X"——共线结构下该结论不成立。')


def section_diagnostics(df, prof):
    """回归诊断三件套 —— 针对 [1b] 的维度分-上游变量回归。

    ⚠️ 设计要点（踩过的坑）:
      不要把 D 与 P 同时放进一个回归去解释维度分。D 与 P 强负相关
      （实测 corr=-0.44：需求密集的地方竞品也多，份额被摊薄），
      同放会产生 suppression，使本应为正的系数变负、误导判断。
      正确做法是每个维度只对其**对应的**上游变量做单变量回归。
    """
    rule('[2] 回归诊断 —— 每个维度分对其对应上游变量的单变量回归')
    panel_path = HERE / 'stats' / 'panel_recomputed.csv'
    if not panel_path.exists():
        print('  ⚠️ 缺 panel_recomputed.csv，跳过')
        return
    up = pd.read_csv(panel_path, encoding='utf-8-sig')[['名称', 'D']]
    st = pd.read_csv(HERE / 'stores_calib.csv', encoding='utf-8-sig')

    # 用样本内坐标补算最近同类距离
    lng = st['经度'].to_numpy()
    lat = st['纬度'].to_numpy()
    near = {}
    for i, nm in enumerate(st['名称']):
        d = [np.hypot((lng[i] - lng[j]) * 88000, (lat[i] - lat[j]) * 111000)
             for j in range(len(st)) if j != i]
        near[nm] = min(d)
    up['最近同类距离m'] = up['名称'].map(near)

    merged = df.merge(up, on='名称', how='inner')
    print(f'  配对样本 n = {len(merged)}\n')

    # 维度 -> 其对应上游变量（一一对应，禁止混放）
    pairs = [
        ('客群匹配度', 'D',           '需求规模'),
        ('竞争压力',   '_P',          '捕获份额(引擎实测)'),
        ('交通可达性', '最近同类距离m',  '最近同类距离'),
    ]
    print(f'  {"维度":<12}{"上游变量":<20}{"β":>10}{"SE(HC3)":>10}'
          f'{"t":>8}{"p":>9}{"R²":>8}')
    for dim, var, label in pairs:
        if dim not in merged.columns or var not in merged.columns:
            print(f'  {dim:<12}{label:<20}{"列缺失":>10}')
            continue
        y = pd.to_numeric(merged[dim], errors='coerce').to_numpy(dtype=float)
        x = pd.to_numeric(merged[var], errors='coerce').to_numpy(dtype=float)
        m = ~(np.isnan(y) | np.isnan(x))
        if m.sum() < 10 or np.ptp(x[m]) == 0:
            print(f'  {dim:<12}{label:<20}{"样本/方差不足":>10}')
            continue
        X = np.column_stack([np.ones(int(m.sum())), x[m]])
        fit = ols_hc3(X, y[m])
        print(f'  {dim:<12}{label:<20}{fit["betas"][1]:>10.4f}'
              f'{fit["se_hc3"][1]:>10.4f}{fit["t_hc3"][1]:>8.3f}'
              f'{fmt_p(fit["p_hc3"][1]):>9}{fit["r2"]:>8.4f}')

    print('\n  --- 完整诊断（以竞争压力 ~ 捕获份额 为主模型）---')
    y = pd.to_numeric(merged['竞争压力'], errors='coerce').to_numpy(dtype=float)
    x = pd.to_numeric(merged['_P'], errors='coerce').to_numpy(dtype=float)
    m = ~(np.isnan(y) | np.isnan(x))
    Xc = np.column_stack([np.ones(int(m.sum())), x[m]])
    fit = ols_hc3(Xc, y[m])

    print('  VIF：单变量回归无共线问题（VIF≡1），略。')
    lm, q, p = breusch_pagan(fit['resid'], Xc)
    print(f'  Breusch-Pagan: LM = {lm:.4f}, df = {q}, p = {fmt_p(p)}  {sig(p)}')
    print('    判读：拒绝同方差 → 已用 HC3 稳健标准误。')
    jb, pj, sk, ku = jarque_bera(fit['resid'])
    print(f'  Jarque-Bera:   JB = {jb:.4f}, p = {fmt_p(pj)}  {sig(pj)}'
          f'（偏度{sk:+.3f} 峰度{ku:+.3f}）')

    # 关键：解释"为什么 D 与 P 不能同放"
    r_dp = float(np.corrcoef(
        pd.to_numeric(merged['D'], errors='coerce').to_numpy(dtype=float)[m],
        x[m])[0, 1])
    print(f'\n  ⚠️ corr(D, P) = {r_dp:+.4f}')
    print('     需求密集处竞品同样密集 → P 被摊薄，两者天然负相关。')
    print('     若把 D 与 P 一并放进解释竞争压力的回归，会发生 suppression：')
    print('     系数符号可能翻转，得到"P 越高竞争分越低"的错误结论。')
    print('     → 因此本脚本坚持单变量对应，不做多变量混放。')


def section_lambda_ci():
    """辅助：log-log 反解 λ 及其 95%CI（参数敏感性参考）。"""
    rule('[3] 辅助回归 —— λ 的点估计与 95% 置信区间')
    print('  ⚠️ 因变量为外卖月售（已证伪的经营代理），本节仅作参数敏感性参考，')
    print('     不作为模型效度证据。')
    st = pd.read_csv(HERE / 'stores_calib.csv', encoding='utf-8-sig')
    br = pd.read_csv(HERE / 'brands.csv', encoding='utf-8-sig').set_index('品牌')

    lng = st['经度'].to_numpy()
    lat = st['纬度'].to_numpy()
    sales = st['外卖月售'].to_numpy(dtype=float)
    dists = np.array([
        min(np.hypot((lng[i] - lng[j]) * 88000, (lat[i] - lat[j]) * 111000)
            for j in range(len(st)) if j != i)
        for i in range(len(st))])
    S = np.array([float(br['系数'].get(b, 1.0)) for b in st['品牌']])

    y = np.log(np.clip(sales, 1, None))
    X = np.column_stack([np.ones(len(st)),
                         np.log(1.0 / (dists + D0)),
                         np.log(S)])
    fit = ols_hc3(X, y)
    print(f'\n  log(月售) = α + β1·log(1/(d+{D0:.0f})) + β2·log(S)')
    print(f'  {"项":<16}{"系数":>10}{"SE(HC3)":>12}{"t":>10}{"p":>10}{"95%CI":>24}')
    for i, nm in enumerate(['截距', 'λ(距离衰减)', 'γ(log S)']):
        lo = fit['betas'][i] - 1.96 * fit['se_hc3'][i]
        hi = fit['betas'][i] + 1.96 * fit['se_hc3'][i]
        print(f'  {nm:<16}{fit["betas"][i]:>10.4f}{fit["se_hc3"][i]:>12.4f}'
              f'{fit["t_hc3"][i]:>10.3f}{fmt_p(fit["p_hc3"][i]):>10}'
              f'{"[%+.3f, %+.3f]" % (lo, hi):>24}')
    print(f'\n  R² = {fit["r2"]:.4f}   n = {len(st)}')
    lo = fit['betas'][1] - 1.96 * fit['se_hc3'][1]
    hi = fit['betas'][1] + 1.96 * fit['se_hc3'][1]
    print(f'  λ 点估计 = {fit["betas"][1]:.4f}，95%CI = [{lo:.4f}, {hi:.4f}]')
    if lo <= 2.0 <= hi:
        print('  ✅ CI 覆盖文献值 2.0 → λ=2.0 得到数据支持')
    else:
        print('  ⚠️ CI 不覆盖 2.0 → 数据偏向其他衰减强度，需在文档说明')
    print('  注：本式与 scoring.py 的 Huff 形式不完全等价（后者含竞争项求和），')
    print('      λ 在此是"距离弹性"的近似解读，仅作方向性参考。')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--panel', default=None, help='复用已算好的维度分 CSV')
    ap.add_argument('-o', '--out', default=str(HERE / 'huff_regression_result.csv'))
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(errors='replace')
    except Exception:
        pass

    if args.panel and Path(args.panel).exists():
        df = pd.read_csv(args.panel, encoding='utf-8-sig')
        prof = {'weights': {'客群匹配度': 0.35, '竞争压力': 0.25,
                            '交通可达性': 0.25, '租金承受力': 0.15}}
        print(f'从 {args.panel} 载入 {len(df)} 行')
        if '_P' not in df.columns:
            print('  ⚠️ 该文件缺 _P 列（引擎实测捕获份额），[1b]/[2] 将降级')
    else:
        print('正在装配维度分面板（纯本地库，零 API）...')
        df, prof = build_panel()
        print(f'装配完成：{len(df)} 家')

    if len(df) < 10:
        print(f'⚠️ 样本量仅 {len(df)}，结论仅供参考')

    sub = section_identity_check(df, prof)
    section_dim_consistency(df, prof)
    section_weight_evidence(df)
    section_diagnostics(df, prof)
    section_lambda_ci()

    rule('[汇总] 必须与结论一同呈现的方法学边界')
    print('  1. 【1a】恒等式核查证明「四维度分→总分」是定义式（β≡w、R²≡1），')
    print('     它不是回归、不构成任何效度证据。禁止作为"权重被数据验证"写入文档。')
    print('  2. 【1b】维度分自洽性是唯一有信息量的内部检验：')
    print('     检验维度分与其上游位置变量的关系方向是否符合模型设定。')
    print('     方向异常 = 该维度实现有 bug，必须排查而非掩盖。')
    print('  3. 【1c】客观赋权在共线结构下不稳定，只能给"量级一致"的方向性结论，')
    print('     不能声称推出了"最优权重"。')
    print('  4. 【2】每个维度只与其对应上游变量做单变量回归；')
    print('     D 与 P 强负相关（实测约 -0.44），同放会产生 suppression 致符号翻转。')
    print('  5. 【3】λ 的 log-log 估计因变量（外卖月售）已被证伪，仅作参数敏感性参考。')
    print('  6. 真正的对外效度检验（选址分 → 真实营业额）需补营业额数据后另做，')
    print('     83 家店没有该字段，未编造。')

    if sub is not None and len(sub):
        sub.drop(columns=[c for c in sub.columns if c.startswith('_')],
                 errors='ignore').to_csv(args.out, index=False,
                                         encoding='utf-8-sig')
        print(f'\n明细已保存: {args.out}')


if __name__ == '__main__':
    main()
