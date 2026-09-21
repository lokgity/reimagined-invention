# -*- coding: utf-8 -*-
"""
run_analysis.py —— 线一：评分体系上游变量的多维度分析
========================================================
纯离线（REALTIME=0 走本地 SQLite 库），零高德 API 调用。
只用 numpy/pandas/scipy/sklearn，KMO/Bartlett/α/熵权/CRITIC 按文献公式自写。

产出：控制台 SPSS 风格报表 + out/ 下的 CSV（供文档直接引用）。

范围声明：本分析的对象是**位置变量**，不是评分引擎的 6 个维度分。
租金承受力/面积适配度/门头形象三维需要月租/面积/照片，83 家店都没有，
编造输入去凑维度分等于伪造数据，所以不做。
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.decomposition import FactorAnalysis
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (PCA_VARS, WEIGHT_VARS, DEMAND_W, cronbach_alpha, critic_weight,
                    entropy_weight, fmt_p, kmo, bartlett_sphericity, load_panel, rule,
                    sig_mark, HERE)

OUT = HERE / 'out'
OUT.mkdir(exist_ok=True)

ALPHA = 0.05


def section_descriptive(df):
    rule('[1] 描述统计（SPSS「描述」风格）')
    vars_all = PCA_VARS + ['需求D', 'P_blind', 'D×P_brand', '最近同类距离m']
    rows = []
    for v in vars_all:
        x = df[v].dropna().to_numpy(dtype=float)
        n = len(x)
        sd = x.std(ddof=1)
        rows.append({
            '变量': v, 'N': n, '均值': x.mean(), '标准差': sd,
            '标准误': sd / np.sqrt(n), '中位数': np.median(x),
            '最小': x.min(), 'P25': np.percentile(x, 25),
            'P75': np.percentile(x, 75), '最大': x.max(),
            'IQR': np.percentile(x, 75) - np.percentile(x, 25),
            '偏度': stats.skew(x, bias=False), '峰度': stats.kurtosis(x, bias=False),
            '变异系数CV': sd / x.mean() if x.mean() else np.nan,
        })
    t = pd.DataFrame(rows).set_index('变量')
    print(t.round(4).to_string())
    print('\n判读：偏度绝对值 >1 或峰度绝对值 >2 视为明显偏离正态；'
          'CV 反映离散度，用于后面 CRITIC 的对比强度项。')
    t.round(6).to_csv(OUT / '01_descriptive.csv', encoding='utf-8-sig')
    return t


def section_normality(df):
    rule('[2] 正态性检验（决定后续用参数还是非参数方法）')
    rows = []
    for v in PCA_VARS:
        x = df[v].dropna().to_numpy(dtype=float)
        sw = stats.shapiro(x)
        jb = stats.jarque_bera(x)
        k2 = stats.normaltest(x)
        rows.append({
            '变量': v, 'N': len(x),
            'ShapiroWilk_W': sw.statistic, 'SW_p': sw.pvalue,
            'JarqueBera_JB': jb.statistic, 'JB_p': jb.pvalue,
            "D'Agostino_K2": k2.statistic, 'K2_p': k2.pvalue,
            '三检验一致拒绝正态': bool(sw.pvalue < ALPHA and jb.pvalue < ALPHA
                                     and k2.pvalue < ALPHA),
        })
    t = pd.DataFrame(rows).set_index('变量')
    show = t.copy()
    for c in ['SW_p', 'JB_p', 'K2_p']:
        show[c] = show[c].map(fmt_p)
    print(show.round(4).to_string())
    n_rej = int(t['三检验一致拒绝正态'].sum())
    print(f'\n判读：{n_rej}/{len(t)} 个变量在三种检验下一致拒绝正态（α={ALPHA}）。')
    print('      → 组间差异检验默认走非参数（Kruskal-Wallis + Mann-Whitney 事后），'
          '同时并列报告 ANOVA 结果作稳健性对照。')
    t.round(6).to_csv(OUT / '02_normality.csv', encoding='utf-8-sig')
    return t


def section_correlation(df):
    rule('[3] 相关矩阵（Pearson + Spearman，带 p 值与 95%CI）')
    X = df[PCA_VARS]
    n = len(X)
    rows = []
    for i, a in enumerate(PCA_VARS):
        for b in PCA_VARS[i + 1:]:
            pr = stats.pearsonr(X[a], X[b])
            sp = stats.spearmanr(X[a], X[b])
            # Fisher z 变换求 Pearson r 的 95%CI
            z = np.arctanh(pr.statistic)
            se = 1 / np.sqrt(n - 3)
            lo, hi = np.tanh(z - 1.96 * se), np.tanh(z + 1.96 * se)
            rows.append({
                '变量1': a, '变量2': b,
                'Pearson_r': pr.statistic, 'Pearson_p': pr.pvalue,
                'r_95CI下限': lo, 'r_95CI上限': hi,
                'CI含0': bool(lo <= 0 <= hi),
                'Spearman_rho': sp.statistic, 'Spearman_p': sp.pvalue,
                '显著性': sig_mark(min(pr.pvalue, sp.pvalue)),
            })
    t = pd.DataFrame(rows)
    show = t.copy()
    for c in ['Pearson_p', 'Spearman_p']:
        show[c] = show[c].map(fmt_p)
    print(show[['变量1', '变量2', 'Pearson_r', 'Pearson_p', 'r_95CI下限', 'r_95CI上限',
                'CI含0', 'Spearman_rho', 'Spearman_p', '显著性']].round(4).to_string(index=False))
    n_sig = int((~t['CI含0']).sum())
    print(f'\n判读：{n_sig}/{len(t)} 对变量的 Pearson 95%CI 不含 0（即在 0.05 水平显著）。')
    print('      CI 含 0 的相关系数不能当"存在关联"引用，只能当"未检测到关联"。')
    t.round(6).to_csv(OUT / '03_correlation.csv', index=False, encoding='utf-8-sig')

    print('\n--- 相关矩阵（下三角 Pearson r / 上三角 Spearman rho）---')
    M = pd.DataFrame(np.nan, index=PCA_VARS, columns=PCA_VARS, dtype=object)
    for i, a in enumerate(PCA_VARS):
        for j, b in enumerate(PCA_VARS):
            if i == j:
                M.iloc[i, j] = '1'
            elif j < i:
                M.iloc[i, j] = f'{stats.pearsonr(X[a], X[b]).statistic:+.3f}'
            else:
                M.iloc[i, j] = f'{stats.spearmanr(X[a], X[b]).statistic:+.3f}'
    print(M.to_string())
    return t


def section_kmo_bartlett(df):
    rule('[4] KMO 取样适切性 + Bartlett 球形检验（因子分析前置门槛）')
    X = df[PCA_VARS]
    corr = X.corr().to_numpy()
    corr_df = X.corr()
    k, msa = kmo(corr_df)
    chi2, dof, p = bartlett_sphericity(X)

    print(f'  KMO 总量数           = {k:.4f}')
    grade = ('极好(>0.9)' if k > 0.9 else '良好(0.8~0.9)' if k > 0.8 else
             '中等(0.7~0.8)' if k > 0.7 else '勉强(0.6~0.7)' if k > 0.6 else
             '不适合(<0.6)')
    print(f'  判读                 = {grade}')
    print('\n  各变量 MSA（单项取样适切性，<0.5 的变量应考虑剔除）:')
    for v, m in msa.items():
        flag = '  ⚠️ 偏低' if m < 0.5 else ''
        print(f'    {v:<14} {m:.4f}{flag}')
    print(f'\n  Bartlett 球形检验    χ²({dof}) = {chi2:.3f}, p = {fmt_p(p)}')
    verdict = ('拒绝 H0（相关矩阵非单位阵），适合做因子分析' if p < ALPHA
               else '未能拒绝 H0，变量间几乎不相关，因子分析无意义')
    print(f'  判读                 = {verdict}')
    pd.DataFrame({'变量': msa.index, 'MSA': msa.values}).round(6).to_csv(
        OUT / '04_kmo_msa.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame([{'KMO': k, 'Bartlett_chi2': chi2, 'df': dof, 'p': p}]
                 ).round(6).to_csv(OUT / '04_kmo_bartlett.csv', index=False, encoding='utf-8-sig')
    return k, p


def section_alpha(df):
    rule('[5] Cronbach\'s α 内部一致性信度')
    ab = df[['A_客群POI', 'B_商业POI']]
    a_ab = cronbach_alpha(ab)
    print(f"  ① 需求构念（A_客群POI + B_商业POI，k=2）  α = {a_ab:.4f}")
    print('     这两个指标同为"周边需求规模"的平行测量，是唯一有资格算 α 的组合。')
    grade = '可接受(≥0.7)' if a_ab >= 0.7 else '偏低(0.6~0.7)' if a_ab >= 0.6 else '差(<0.6)'
    print(f'     判读：{grade}')
    r = stats.pearsonr(ab['A_客群POI'], ab['B_商业POI'])
    print(f'     两者 Pearson r = {r.statistic:+.4f}, p = {fmt_p(r.pvalue)}')

    print('\n  ② 全变量集（6 个变量）—— ⚠️ 仅作反例展示，不应引用')
    a_all = cronbach_alpha(df[PCA_VARS])
    print(f'     α = {a_all:.4f}')
    print('     为什么不能引用：α 的前提是各题为**同一构念的平行指标**。')
    print('     客群POI数/商业POI数/捕获份额P/品牌系数S/竞争密度/外卖月售分属需求、')
    print('     竞争、品牌、结果四类不同构念，硬算出的 α 无解释意义，')
    print('     把它当"信度达标"报出去属于伪严谨。')
    pd.DataFrame([{'组合': '需求构念(A+B)', 'k': 2, 'alpha': a_ab},
                  {'组合': '全变量集(反例)', 'k': len(PCA_VARS), 'alpha': a_all}]
                 ).round(6).to_csv(OUT / '05_cronbach_alpha.csv', index=False, encoding='utf-8-sig')
    return a_ab


def section_pca(df):
    rule('[6] 主成分分析 / 因子结构')
    X = df[PCA_VARS].to_numpy(dtype=float)
    n, p = X.shape
    Z = StandardScaler().fit_transform(X)
    corr = np.corrcoef(Z, rowvar=False)
    eigval, eigvec = np.linalg.eigh(corr)
    order = np.argsort(eigval)[::-1]
    eigval, eigvec = eigval[order], eigvec[:, order]

    print(f'  样本 N={n}，变量 p={p}，N/p = {n / p:.1f}'
          f'（{"≥10 达标" if n / p >= 10 else "<10 偏小，载荷稳定性存疑"}）')
    keep = int((eigval > 1).sum())
    print('\n  --- 特征值与方差贡献（碎石图数据）---')
    print(f'  {"成分":<6}{"特征值":>10}{"方差%":>10}{"累计%":>10}{"判据":>16}')
    cum = 0.0
    rows = []
    for i in range(p):
        pct = eigval[i] / p * 100
        cum += pct
        rows.append({'成分': i + 1, '特征值': eigval[i], '方差贡献%': pct,
                     '累计贡献%': cum, 'Kaiser保留': bool(eigval[i] > 1)})
        print(f'  PC{i + 1:<4}{eigval[i]:>10.4f}{pct:>10.2f}{cum:>10.2f}'
              f'{"Kaiser>1" if eigval[i] > 1 else "-":>16}')
    print(f'\n  Kaiser 判据（特征值>1）保留 {keep} 个成分，'
          f'累计解释 {sum(r["方差贡献%"] for r in rows[:keep]):.2f}%')

    print('\n  --- 成分载荷矩阵（未旋转，基于相关矩阵的特征向量×√特征值）---')
    load = eigvec * np.sqrt(eigval)
    L = pd.DataFrame(load[:, :max(keep, 2)], index=PCA_VARS,
                     columns=[f'PC{i + 1}' for i in range(max(keep, 2))])
    print(L.round(4).to_string())
    print('\n  各变量在哪个成分上载荷最高（|载荷|>0.4 视为主要归属）:')
    for v in PCA_VARS:
        row = L.loc[v]
        top = row.abs().idxmax()
        print(f'    {v:<14} → {top}  载荷 {row[top]:+.4f}'
              + ('' if abs(row[top]) > 0.4 else '  ⚠️ 无显著归属'))
    commun = (L ** 2).sum(axis=1)
    print('\n  公因子方差（communality，<0.5 表示该变量信息大部分未被提取）:')
    for v in PCA_VARS:
        print(f'    {v:<14} {commun[v]:.4f}' + ('  ⚠️ 偏低' if commun[v] < 0.5 else ''))

    print('\n  --- 主轴因子法（FactorAnalysis，含噪声方差分解）交叉验证 ---')
    fa = FactorAnalysis(n_components=max(keep, 2), rotation='varimax', random_state=0)
    fa.fit(Z)
    FA = pd.DataFrame(fa.components_.T, index=PCA_VARS,
                      columns=[f'F{i + 1}' for i in range(fa.n_components)])
    print(FA.round(4).to_string())
    print(f'\n  各变量唯一性(uniqueness): '
          f'{dict(zip(PCA_VARS, np.round(fa.noise_variance_, 4)))}')

    pd.DataFrame(rows).round(6).to_csv(OUT / '06_pca_eigen.csv', index=False, encoding='utf-8-sig')
    L.round(6).to_csv(OUT / '06_pca_loadings.csv', encoding='utf-8-sig')
    FA.round(6).to_csv(OUT / '06_fa_loadings_varimax.csv', encoding='utf-8-sig')
    return keep, L


def section_weighting(df):
    rule('[7] 客观赋权：熵权法 + CRITIC，对照手拍权重')

    print('  --- 7.1 位置质量指标集（3 指标，方向均为正向）---')
    print(f'  纳入: {WEIGHT_VARS}')
    print('  排除 本地竞争密度：方向存疑（扎堆既是客流也是饱和），熵权法要求指标同向')
    print('  排除 品牌系数S：手工设定参数、不是测量值，拿它给自己赋权是循环论证')
    Xw = df[WEIGHT_VARS]
    we, de = entropy_weight(Xw)
    wc, dc = critic_weight(Xw)
    cmp = pd.DataFrame({'熵权法': we, 'CRITIC': wc})
    cmp['两者均值'] = cmp.mean(axis=1)
    print('\n  熵权法中间量:')
    print(de.round(6).to_string())
    print('\n  CRITIC 中间量:')
    print(dc.round(6).to_string())
    print('\n  客观权重汇总:')
    print(cmp.round(4).to_string())
    cmp.round(6).to_csv(OUT / '07_objective_weights.csv', encoding='utf-8-sig')

    print('\n  --- 7.2 直接检验需求公式里手拍的 0.8 / 0.2 ---')
    print(f'  scoring.estimate_demand:  D = {DEMAND_W["A_客群POI"]}·A_客群POI '
          f'+ {DEMAND_W["B_商业POI"]}·B_商业POI')
    ab = df[['A_客群POI', 'B_商业POI']]
    we2, de2 = entropy_weight(ab)
    wc2, dc2 = critic_weight(ab)
    t2 = pd.DataFrame({'熵权法': we2, 'CRITIC': wc2,
                       '手拍权重': pd.Series(DEMAND_W)})
    t2['客观均值'] = t2[['熵权法', 'CRITIC']].mean(axis=1)
    t2['与手拍差值'] = t2['客观均值'] - t2['手拍权重']
    print(t2.round(4).to_string())
    print('\n  熵权法中间量（2 指标）:')
    print(de2.round(6).to_string())
    print('\n  CRITIC 中间量（2 指标）:')
    print(dc2.round(6).to_string())
    print('\n  ⚠️ 方法学警示：只有 2 个指标时，两种客观赋权都极不稳定——')
    print('     熵权法退化为"谁更离散谁权重大"，CRITIC 的冲突项只剩 (1-r) 一项。')
    print('     这个结果只能作为"0.8/0.2 缺乏数据支持"的证据，')
    print('     不能直接拿客观值去替换引擎参数。')
    t2.round(6).to_csv(OUT / '07_demand_weight_check.csv', encoding='utf-8-sig')
    return cmp, t2


def section_group_diff(df):
    rule('[8] 组间差异检验：三个商圈之间')
    groups = sorted(df['商圈'].unique())
    print(f'  分组: {[(g, int((df["商圈"] == g).sum())) for g in groups]}')
    print('  ⚠️ 组样本量不均衡（39/27/17），最小组 n=17，事后检验功效有限')

    rows = []
    for v in PCA_VARS + ['需求D', 'P_blind']:
        samples = [df.loc[df['商圈'] == g, v].dropna().to_numpy(dtype=float) for g in groups]
        lev = stats.levene(*samples, center='median')
        norm_all = all(stats.shapiro(s).pvalue >= ALPHA for s in samples if len(s) >= 3)
        if norm_all and lev.pvalue >= ALPHA:
            stat, p, method = stats.f_oneway(*samples)
            method = 'ANOVA'
            dof = f'F({len(groups) - 1},{len(df) - len(groups)})'
        else:
            stat, p = stats.kruskal(*samples)
            method = 'Kruskal-Wallis'
            dof = f'H({len(groups) - 1})'
        rows.append({'变量': v, 'Levene_p': lev.pvalue, '方差齐': lev.pvalue >= ALPHA,
                     '正态': norm_all, '采用方法': method, '统计量': stat,
                     '自由度': dof, 'p': p, '显著': sig_mark(p)})
        print(f'\n  [{v}]  Levene p={fmt_p(lev.pvalue)}（方差{"齐" if lev.pvalue >= ALPHA else "不齐"}）'
              f'  正态={"是" if norm_all else "否"} → 用 {method}')
        print(f'      {dof} = {stat:.4f}, p = {fmt_p(p)}  {sig_mark(p)}')
        print(f'      分组中位数: ' + '  '.join(
            f'{g}={np.median(s):.3f}' for g, s in zip(groups, samples)))
        if p < ALPHA:
            print('      事后两两比较（Mann-Whitney U + Bonferroni 校正，α\'=0.05/3=0.0167）:')
            for i in range(len(groups)):
                for j in range(i + 1, len(groups)):
                    u = stats.mannwhitneyu(samples[i], samples[j], alternative='two-sided')
                    padj = min(1.0, u.pvalue * 3)
                    print(f'        {groups[i]} vs {groups[j]}: U={u.statistic:.1f}, '
                          f'p_raw={fmt_p(u.pvalue)}, p_bonf={fmt_p(padj)} '
                          f'{sig_mark(padj)}')
    t = pd.DataFrame(rows)
    t.round(6).to_csv(OUT / '08_group_diff_商圈.csv', index=False, encoding='utf-8-sig')
    return t


def section_brand_tier(df):
    rule('[9] 品牌档次差异检验')
    print('  品牌档次用 brands.csv 的吸引力系数 S 分层（S 是手工设定，此处当分类型自变量用）')
    tiers = pd.cut(df['品牌系数S'], bins=[0.99, 1.0, 1.5, 2.0, 2.6],
                   labels=['个体/杂牌(S=1.0)', '弱势品牌(1.0~1.5)',
                           '中势品牌(1.5~2.0)', '强势品牌(>2.0)'])
    df = df.assign(品牌档次=tiers)
    print('\n  档次分布:')
    print(df['品牌档次'].value_counts().reindex(tiers.cat.categories).to_string())

    rows = []
    for v in ['外卖月售', 'P_brand', 'P_blind', '本地竞争密度', '需求D']:
        gs = [g for _, g in df.groupby('品牌档次', observed=True) if len(g) >= 3]
        if len(gs) < 2:
            print(f'\n  [{v}] 有效组数不足 2，跳过')
            continue
        samples = [g[v].dropna().to_numpy(dtype=float) for g in gs]
        labels = [str(g['品牌档次'].iloc[0]) for g in gs]
        stat, p = stats.kruskal(*samples)
        rows.append({'变量': v, '统计量': stat, 'df': len(gs) - 1, 'p': p, '显著': sig_mark(p)})
        print(f'\n  [{v}]  Kruskal-Wallis H({len(gs) - 1}) = {stat:.4f}, p = {fmt_p(p)} {sig_mark(p)}')
        print('      分组中位数: ' + '  '.join(f'{l}={np.median(s):.1f}'
                                             for l, s in zip(labels, samples)))
        if p < ALPHA:
            print('      事后（Bonferroni）:')
            k = len(gs) * (len(gs) - 1) // 2
            for i in range(len(gs)):
                for j in range(i + 1, len(gs)):
                    u = stats.mannwhitneyu(samples[i], samples[j], alternative='two-sided')
                    padj = min(1.0, u.pvalue * k)
                    print(f'        {labels[i]} vs {labels[j]}: p_bonf={fmt_p(padj)} {sig_mark(padj)}')
    print('\n  ⚠️ 关键警示：S 是手工设定的品牌系数，外卖月售是已被证伪的结果代理。')
    print('     本节只能说明"手工设定的品牌档次与外卖月售之间是否存在系统性关联"，')
    print('     无论显著与否都**不能**当作品牌吸引力 S 的效度证据。')
    print('     ① P_brand 按 S 分层检验属**机械循环**：P_brand 的分子里就含 own_S，')
    print('        档次间必然有差异，p=0.0120 不是发现，是恒等式的重述。')
    print('     ② 外卖月售的档次中位数**非单调**（个体1950 < 弱势2900 ≈ 中势3000')
    print('        > 强势2750），事后仅"个体 vs 中势"一对显著，缺少剂量-反应关系，')
    print('        不能读成"品牌越强卖得越多"。')
    pd.DataFrame(rows).round(6).to_csv(OUT / '09_brand_tier.csv', index=False, encoding='utf-8-sig')
    return pd.DataFrame(rows)


def section_data_quality(df):
    rule('[0] 数据完整性与口径核查')
    print(f'  样本量 N = {len(df)}，商圈数 = {df["商圈"].nunique()}，品牌数 = {df["品牌"].nunique()}')
    print(f'  品牌系数 S 未被 brands.csv 覆盖（静默退化为 1.0）: '
          f'{int((~df["S已覆盖"]).sum())} 家')
    print(f'    涉及品牌: {sorted(df.loc[~df["S已覆盖"], "品牌"].unique())}')
    print(f'    ⚠️ 其中"个体/杂牌"退化为 1.0 是正确语义；'
          f'柠季/贡茶是**连锁品牌却按个体户计分**，属于数据缺口')
    print(f'\n  机械派生变量（不进因子分析，否则产生人为结构）:')
    print('    需求D = 0.8·A_客群POI + 0.2·B_商业POI')
    print('    D×P   = 需求D · 捕获份额P')
    print(f'\n  高德API口径 vs 引擎本地库口径 的 D 分歧（demand.csv 与引擎不同源）:')
    rel = ((df['需求D'] - df['需求D_API口径']).abs() / df['需求D_API口径'])
    print(f'    完全相同: {int((df["需求D"] == df["需求D_API口径"]).sum())}/{len(df)} 家')
    print(f'    相对差 中位 {rel.median():.1%}  均值 {rel.mean():.1%}  最大 {rel.max():.1%}')
    print('    → 结论：demand.csv 不能用于描述引擎行为，本分析已全部改用本地库重算值')
    print(f'\n  P 的两套口径（锚点 bug 的证据，详见 check_anchor_consistency.py）:')
    print(f'    品牌盲 P_blind 中位 {df["P_blind"].median():.4f}  ← 现用 P_REF=0.40 来源')
    print(f'    带品牌 P_brand 中位 {df["P_brand"].median():.4f}  ← 运行时实际口径')
    print(f'    放大倍数 {df["P_brand"].median() / df["P_blind"].median():.4f}')

    s = df['外卖月售'].astype(float)
    n_dist = s.nunique()
    n_100 = int((s % 100 == 0).sum())
    top = s.value_counts()
    tie_rate = 1 - n_dist / len(s)
    print(f'\n  ⚠️ 外卖月售 测量粒度核查（该列是人工抄录的平台展示值，形如"月售2000+"）:')
    print(f'    不同取值数 = {n_dist}（N={len(s)}），并列率 = {tie_rate:.1%}')
    print(f'    能被 100 整除 = {n_100}/{len(s)}')
    print(f'    最高频取值: ' + ', '.join(f'{int(v)}×{int(c)}' for v, c in top.head(5).items()))
    print('    → 本质是**粗粒度有序分类**，不是连续变量。')
    print('    → [3] 中"S~外卖月售 Pearson 不显著 / Spearman 显著"的分歧，')
    print('      主因是大量并列秩 + 2 个 20000 极端值，不是单纯的偏态。')
    print('    → 后续凡以该列为因变量的检验（含 [9]）一律降级为方向性证据。')


def main():
    df = load_panel()
    df.to_csv(OUT / '00_panel.csv', index=False, encoding='utf-8-sig')
    section_data_quality(df)
    section_descriptive(df)
    section_normality(df)
    section_correlation(df)
    k, p_bt = section_kmo_bartlett(df)
    section_alpha(df)
    keep, L = section_pca(df)
    section_weighting(df)
    section_group_diff(df)
    section_brand_tier(df)

    rule('[汇总] 本次分析的方法学边界（写文档时必须一并声明）')
    print('  1. 分析对象是位置变量，不是评分引擎的 6 个维度分——租金承受力/面积适配度/')
    print('     门头形象三维缺月租、面积、照片输入，83 家店均不可得，未编造。')
    print('  2. 外卖月售作为经营结果代理已不成立（相关全部不显著）；且其测量粒度本身')
    print('     不合格——83 家中 82 家能被 100 整除、仅 27 个不同取值，是粗粒度有序')
    print('     分类而非连续变量。凡以它为因变量的检验只能当方向性证据。')
    print('  3. 本地竞争密度是"抽样密度"非"普查密度"，83 家为抽样，真实密度被低估。')
    print('  4. 品牌系数 S 是手工设定参数，凡以 S 为自变量的检验都不构成对 S 的效度验证。')
    print('  5. 2 指标客观赋权（0.8/0.2 检验）稳定性差，只作方向性证据。')
    print('  6. 三个商圈组样本量不均衡（39/27/17），最小组 n=17，事后检验功效有限。')
    print('  7. ★ KMO = 0.3685 < 0.5（不可接受线），且 6 个变量中 5 个的 MSA < 0.5。')
    print('     Bartlett 虽显著拒绝单位阵，但这是"有相关结构、共享方差却不足以支撑')
    print('     潜因子模型"的典型矛盾组合。因此**不能**用因子分析/PCA 的结果去论证')
    print('     "6 个维度应该合成一个总分"，PCA 在本项目中只能当描述性降维使用。')
    print(f'\n  全部表格已输出到 {OUT}')


if __name__ == '__main__':
    main()
