# -*- coding: utf-8 -*-
"""
common.py —— 多维度分析的公共层：数据装配 + 自写统计量
========================================================
只用 numpy/pandas/scipy/sklearn（项目已有），不引入 statsmodels 等运行时新依赖。

KMO、Bartlett 球形检验、Cronbach's α、熵权法、CRITIC 全部按原始文献公式自写。
选择自写而不是装包的两个原因：
  1. 这些量都是闭式解，几十行就能实现，且能逐项打印中间量供核验；
  2. statsmodels 没有原生 KMO/Bartlett，装了也仍要自写。

数据口径（重要）：
  本模块装配的是 83 家已开业奶茶门店的**上游实测变量**，不是评分引擎的 6 个维度分。
  原因是租金承受力/面积适配度/门头形象三个维度需要月租、面积、照片作为输入，
  而这 83 家店的这三项都不可得；编造输入去凑维度分等于伪造数据。

  所有位置变量都在 REALTIME=0（纯本地库）下用引擎自己的 query_within 重算，
  不发任何高德 API。这样做而不是直接读 demand.csv / anchor_calib.csv，是因为
  那两份 CSV 与引擎运行时不同源：
    · demand.csv 的 A/B 分量走高德 API 关键词搜索，引擎 estimate_demand 走本地库品类；
      同一家店两个口径能差 5%（奈雪 29.2 vs 27.8）。
    · anchor_calib.csv 的 P 是 own_S=1.0 算的（stores_calib 的吸引力系数列整列为空），
      而运行时 capture_share 收到的是 BRAND_S[brand]。
  两套口径都保留为对照列，便于量化分歧，但分析主体用引擎本地库口径。
"""
import math
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

# 必须在 import engine 之前设置，否则 realtime 模块已按默认值初始化
os.environ.setdefault('REALTIME', '0')

HERE = Path(__file__).resolve().parent
ANALYSIS = HERE.parent
SRC = ANALYSIS.parent          # data.query / engine.* 都在 src/ 下
for _p in (str(SRC), str(ANALYSIS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# 机械派生变量：由其他变量线性/乘积算出，与成分同放进因子分析会产生人为结构。
#   需求D   = 0.8*A_客群POI + 0.2*B_商业POI   (scoring.estimate_demand)
#   D×P     = 需求D * 捕获份额P
DERIVED = ['需求D', 'D×P_brand', 'D×P_blind']

# 进入因子分析的变量集：原始实测/模型构造量，剔除机械派生。
# 外卖月售保留为描述性变量，但它作为"经营结果代理"已被证伪
# （三个商圈 Spearman 全部不显著，p=0.10~0.75），不参与任何效度结论。
PCA_VARS = ['A_客群POI', 'B_商业POI', 'P_brand', '品牌系数S', '本地竞争密度', '外卖月售']

# 客观赋权的"位置质量"指标集：只放方向明确为正向、且非手拍参数的量。
#   本地竞争密度 方向存疑（扎堆既是客流也是饱和）→ 不进赋权，单独报告
#   品牌系数S 是手工设定参数、不是测量值 → 不进赋权
WEIGHT_VARS = ['A_客群POI', 'B_商业POI', 'P_brand']

# 需求公式 D = W_A*A + W_B*B 里的手拍权重（scoring.estimate_demand / fetch_demand.py）
DEMAND_W = {'A_客群POI': 0.8, 'B_商业POI': 0.2}

DENSITY_RADIUS_M = 500
DEMAND_RADIUS_M = 500


def haversine_m(lng1, lat1, lng2, lat2):
    """两点大圆距离（米）。"""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def load_panel(recompute=True):
    """装配 83 家门店的多维面板。零高德 API 调用（REALTIME=0 走本地 SQLite 库）。

    recompute=True 时用引擎的 query_within / capture_share 重算全部位置变量；
    False 时只读已落盘的 panel_recomputed.csv（供无本地库的环境复用）。
    """
    st = pd.read_csv(ANALYSIS / 'stores_calib.csv', encoding='utf-8-sig')
    dm = pd.read_csv(ANALYSIS / 'demand.csv', encoding='utf-8-sig')
    br = pd.read_csv(ANALYSIS / 'brands.csv', encoding='utf-8-sig')

    df = st.merge(dm.rename(columns={'客群POI数': 'A_客群POI_API口径',
                                     '商业POI数': 'B_商业POI_API口径',
                                     '需求D': '需求D_API口径'}),
                  on='名称', how='inner')
    df = df.merge(br.rename(columns={'系数': '品牌系数S'}), on='品牌', how='left')
    # 未进 brands.csv 的品牌会静默退化成 S=1.0，必须显式标记而不是装作有数据
    df['S已覆盖'] = df['品牌系数S'].notna()
    df['品牌系数S'] = df['品牌系数S'].fillna(1.0)

    if recompute:
        from data.query import query_within
        from engine.brands import brand_attractiveness

        LAMBDA, D0 = 2.0, 50.0

        def _capture(lng, lat, own_S):
            """与 scoring.capture_share 同式，但固定走本地库以保证离线可复现。"""
            own = own_S / (D0 ** LAMBDA)
            comp = 0.0
            for p in query_within('奶茶', lng, lat, DEMAND_RADIUS_M):
                if abs(p['lng'] - lng) < 1e-6 and abs(p['lat'] - lat) < 1e-6:
                    continue
                _, s_k = brand_attractiveness(p['name'])
                comp += s_k / ((p['distance'] + D0) ** LAMBDA)
            return own / (own + comp) if (own + comp) > 0 else 1.0

        A, B, Pb, PS = [], [], [], []
        for _, r in df.iterrows():
            lng, lat = r['经度'], r['纬度']
            n_a = sum(len(query_within(c, lng, lat, DEMAND_RADIUS_M))
                      for c in ('学校', '办公', '社区'))
            n_b = len(query_within('商圈', lng, lat, DEMAND_RADIUS_M))
            A.append(n_a); B.append(n_b)
            Pb.append(_capture(lng, lat, 1.0))
            PS.append(_capture(lng, lat, r['品牌系数S']))
        df['A_客群POI'] = A
        df['B_商业POI'] = B
        df['P_blind'] = Pb
        df['P_brand'] = PS
    else:
        rc = pd.read_csv(HERE / 'panel_recomputed.csv', encoding='utf-8-sig')
        rc = rc.rename(columns={'D': '需求D'})
        df = df.merge(rc[['名称', '需求D', 'P_blind', 'P_brand']], on='名称', how='left')
        df['A_客群POI'] = np.nan
        df['B_商业POI'] = np.nan

    df['需求D'] = (DEMAND_W['A_客群POI'] * df['A_客群POI']
                   + DEMAND_W['B_商业POI'] * df['B_商业POI'])
    df['D×P_blind'] = df['需求D'] * df['P_blind']
    df['D×P_brand'] = df['需求D'] * df['P_brand']

    # 本地竞争密度 / 最近同类距离：纯用样本内坐标离线算。
    # ⚠️ 这是"抽样密度"不是"普查密度"——83 家是抽样而非全量门店，
    #    真实密度被系统性低估，只能做样本内相对比较，不能当绝对值引用。
    lng = df['经度'].to_numpy()
    lat = df['纬度'].to_numpy()
    dens, nearest = [], []
    for i in range(len(df)):
        d = np.array([haversine_m(lng[i], lat[i], lng[j], lat[j])
                      for j in range(len(df)) if j != i])
        dens.append(int((d <= DENSITY_RADIUS_M).sum()))
        nearest.append(float(d.min()) if d.size else np.nan)
    df['本地竞争密度'] = dens
    df['最近同类距离m'] = nearest

    return df



# ---------------------------------------------------------------- 因子分析前置

def kmo(corr):
    """Kaiser-Meyer-Olkin 取样适切性量数。

    返回 (总 KMO, 各变量 MSA 的 Series)。判读：>0.9 极好 / 0.8 良好 /
    0.7 中等 / 0.6 勉强 / <0.6 不适合做因子分析。
    """
    idx = corr.index if hasattr(corr, 'index') else range(len(corr))
    corr = np.asarray(corr, dtype=float)
    p = corr.shape[0]
    inv = np.linalg.pinv(corr)
    # 偏相关：由相关矩阵的逆得到，q_ij = -inv_ij / sqrt(inv_ii * inv_jj)
    d = np.sqrt(np.diag(inv))
    partial = -inv / np.outer(d, d)
    np.fill_diagonal(partial, 0.0)

    r2 = corr ** 2
    np.fill_diagonal(r2, 0.0)
    q2 = partial ** 2

    total = r2.sum() / (r2.sum() + q2.sum())
    msa = pd.Series(
        [r2[i].sum() / (r2[i].sum() + q2[i].sum()) if (r2[i].sum() + q2[i].sum()) > 0
         else np.nan for i in range(p)],
        index=pd.Index(list(idx)),
    )
    return float(total), msa


def bartlett_sphericity(df):
    """Bartlett 球形检验：H0 = 相关矩阵是单位阵（变量互不相关，不适合因子分析）。

    χ² = -(n - 1 - (2p+5)/6) · ln|R|，自由度 p(p-1)/2。
    """
    X = df.to_numpy(dtype=float)
    n, p = X.shape
    corr = np.corrcoef(X, rowvar=False)
    sign, logdet = np.linalg.slogdet(corr)
    if sign <= 0:
        raise ValueError('相关矩阵行列式非正，无法做 Bartlett 检验（存在完全共线？）')
    chi2 = -(n - 1 - (2 * p + 5) / 6) * logdet
    dof = p * (p - 1) / 2
    pval = float(stats.chi2.sf(chi2, dof))
    return float(chi2), int(dof), pval


def cronbach_alpha(df):
    """Cronbach's α 内部一致性信度。α = k/(k-1) · (1 - Σσ²ᵢ / σ²_total)。

    只对"同一构念的平行指标"有意义。本项目里只有客群POI数/商业POI数
    同测"周边需求"这一个构念，所以只在这一对上算。
    """
    X = df.to_numpy(dtype=float)
    k = X.shape[1]
    if k < 2:
        return np.nan
    var_items = X.var(axis=0, ddof=1)
    var_total = X.sum(axis=1).var(ddof=1)
    if var_total == 0:
        return np.nan
    return float(k / (k - 1) * (1 - var_items.sum() / var_total))


# ---------------------------------------------------------------- 客观赋权

def _minmax_positive(X):
    """正向化 min-max 归一到 [0,1]。熵权法与 CRITIC 都要求指标同向。"""
    lo, hi = X.min(axis=0), X.max(axis=0)
    span = np.where(hi - lo == 0, 1.0, hi - lo)
    return (X - lo) / span


def entropy_weight(df):
    """熵权法。指标离散度越大（熵越小）→ 提供的信息越多 → 权重越大。

    e_j = -1/ln(n) · Σᵢ p_ij·ln(p_ij)，p_ij 为第 j 项指标下第 i 个样本的比重；
    g_j = 1 - e_j；w_j = g_j / Σg_j。
    """
    X = _minmax_positive(df.to_numpy(dtype=float))
    n = X.shape[0]
    # 比重法要求正值，min-max 后最小值为 0 会让 ln 爆掉，平移一个极小量
    Xs = X + 1e-12
    P = Xs / Xs.sum(axis=0, keepdims=True)
    e = -(P * np.log(P)).sum(axis=0) / math.log(n)
    g = 1 - e
    if g.sum() == 0:
        return pd.Series(np.nan, index=df.columns), pd.DataFrame({'熵e': e, '差异系数g': g})
    w = g / g.sum()
    detail = pd.DataFrame({'熵e': e, '差异系数g': g, '权重w': w}, index=df.columns)
    return pd.Series(w, index=df.columns), detail


def critic_weight(df):
    """CRITIC 法（Diakoulaki 1995）。同时考虑指标自身的波动性和指标间的冲突性。

    C_j = σ_j · Σ_k (1 - r_jk)；w_j = C_j / ΣC_j。
    σ_j 大 = 该指标区分度高；r_jk 小 = 与其他指标信息不重叠。
    """
    X = _minmax_positive(df.to_numpy(dtype=float))
    sd = X.std(axis=0, ddof=1)
    R = np.corrcoef(X, rowvar=False)
    if R.ndim == 0:
        R = np.array([[1.0]])
    conflict = (1 - R).sum(axis=1)
    C = sd * conflict
    if C.sum() == 0:
        return pd.Series(np.nan, index=df.columns), pd.DataFrame({'σ': sd, '冲突性': conflict})
    w = C / C.sum()
    detail = pd.DataFrame({'标准差σ': sd, '冲突性Σ(1-r)': conflict,
                           '信息量C': C, '权重w': w}, index=df.columns)
    return pd.Series(w, index=df.columns), detail


# ---------------------------------------------------------------- 输出辅助

def fmt_p(p):
    """p 值统一格式：小于 0.001 报 <0.001，避免显示 0.0000 造成"绝对显著"的错觉。"""
    if p is None or (isinstance(p, float) and math.isnan(p)):
        return 'NA'
    return '<0.001' if p < 0.001 else f'{p:.4f}'


def sig_mark(p):
    if p is None or (isinstance(p, float) and math.isnan(p)):
        return ''
    return '***' if p < 0.001 else '**' if p < 0.01 else '*' if p < 0.05 else 'ns'


def rule(title='', width=78):
    print()
    print('=' * width)
    if title:
        print(title)
        print('=' * width)
