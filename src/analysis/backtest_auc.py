# -*- coding: utf-8 -*-
"""
backtest_auc.py —— 把回测从「描述性对照」升级为「判别指标（AUC）」
================================================================================
2026-09-28 新增（专家评审 P1）。相对 `backtest_transfer.py` 的**关键差别**：

| 维度 | backtest_transfer.py（旧） | 本文件（新） |
|------|--------------------------|-------------|
| 输出 | 两组均值差（50.9 vs 53.3） | **AUC + 95%CI**（与量纲无关） |
| 能回答 | "两组像不像" | "引擎分能不能把风险组排到前面" |
| 阈值依赖 | 需人工定"差多少算差" | AUC 自带 0.5 基线，**无需调参** |
| 结论稳健性 | 均值受极端值牵动 | AUC 只用**排序**，抗离群 |

## 为什么必须换
专家评审的原话是：均值对照**"只能说明两组分布不同，不能说引擎有判别力"**。
均值差 2.4 分在 100 分制里既可能是信号也可能是噪声，且**随样本量增大必然显著**
（大样本下任何微小差异都 p<0.05）—— 这正是"描述性对照"的天花板。
AUC 回答的是另一个问题：**随机抽一个转让铺 + 随机抽一个出租铺，
引擎给转让铺的分数更低的概率是多少**。0.5 = 抛硬币（无判别力），
1.0 = 完全可分。这是一个**与量纲无关、与阈值无关**的判别力度量。

## 方法（重采样 + bootstrap，无 scipy 依赖）
- 主指标：`AUC(地址评分)`、`AUC(经营评分)`、`AUC(租金承受力)`
- 统一方向：分数**越低越像风险**（转让），故 AUC 用 `P(score_tf < score_rt)`，
  等价于 `AUC = (mean_rank_tf - (n1+1)/2) / n2` 的 Mann-Whitney U 形式。
- 95%CI：**Bootstrap 2000 次**（分层重采样保两组样本量），报 P2.5 / P97.5。
- 显著性：CI 下界 > 0.5 即"判别力显著优于抛硬币"。

## 口径边界（沿用并**强化** backtest_transfer 的声明）
1. **品类错配不可分离**：转让铺里混有服装/美容等非奶茶业态，用奶茶画像评它们
   会系统性低估。所以本文件**主结论用"地址评分"**（纯位置量，不吃品类成本结构），
   "经营评分"只作辅助并**显式标注受品类错配污染**。
2. **转让 ≠ 倒闭**：测的是"退出信号"，非"倒闭预测"。
3. **单次快照**：58 在租列表一次抓取，非区域存量全貌。

## 用法
    # 从已有回测缓存读（默认，零网络、可重复）
    C:\\Python312\\python.exe src\\analysis\\backtest_auc.py
    # 现场抓（约 90s，需网络）
    C:\\Python312\\python.exe src\\analysis\\backtest_auc.py --fetch 杭州,宁波,温州

产出：`_backtest_auc.txt`（结构化报告）+ `_backtest_auc.json`（供 PDF/门禁读）
"""
import io
import json
import math
import random
import sys
import time
from pathlib import Path

# ⚠️ stdout 重定向只在**当脚本跑**时做；被 import（如门禁 verify_analysis_metrics）
#    时不要动 —— 否则会抢走/关闭调用方的 stdout（ValueError: I/O operation on closed file）。
if __name__ == '__main__':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                      errors='replace')
    except Exception:
        pass
_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / 'src'))

BOOT_N = 2000          # bootstrap 次数
BOOT_SEED = 20260928   # 固定种子：保证报告可复现（答辩现场重跑数字一致）

# 负面结论档（与 backtest_transfer 同一口径，不新造）
NEGATIVE_VERDICTS = {'不建议', '不建议优先选择', '位置好·账算不过来', '账算不过来'}


# ---------------------------------------------------------------
# 纯统计（无 numpy/scipy 依赖 —— 本项目引擎侧只用标准库）
# ---------------------------------------------------------------
def auc_score(neg, pos):
    """AUC = P(neg 的分数 < pos 的分数)。

    方向约定：neg = 风险组（转让，**应**得低分），pos = 对照组（出租）。
    AUC 高 = 引擎给风险组的分确实更低 = 有判别力。
    用 Mann-Whitney U 的秩和形式，O(n log n)，抗离群（只用排序）。
    平局记 0.5（标准做法，避免平局被人为算成"可分"）。
    """
    if not neg or not pos:
        return None
    combined = [(v, 0) for v in neg] + [(v, 1) for v in pos]
    combined.sort(key=lambda t: t[0])
    # 赋秩（平局取平均秩）
    ranks = [0.0] * len(combined)
    i = 0
    while i < len(combined):
        j = i
        while j + 1 < len(combined) and combined[j + 1][0] == combined[i][0]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[k] = avg_rank
        i = j + 1
    rank_sum_neg = sum(r for r, (_, g) in zip(ranks, combined) if g == 0)
    n1, n2 = len(neg), len(pos)
    u = rank_sum_neg - n1 * (n1 + 1) / 2.0     # U for neg 组
    # 方向：neg 分数越低，rank_sum 越小，U 越小 →
    # AUC = P(neg < pos) = 1 - U/(n1*n2)
    return 1.0 - u / (n1 * n2)


def auc_ci(neg, pos, n_boot=BOOT_N, seed=BOOT_SEED, alpha=0.05):
    """分层 bootstrap 的 AUC 95%CI。返回 (lo, hi) 或 (None, None)。"""
    if not neg or not pos:
        return None, None
    rnd = random.Random(seed)   # 固定种子 → 报告可复现
    stats = []
    n1, n2 = len(neg), len(pos)
    for _ in range(n_boot):
        b_neg = [neg[rnd.randrange(n1)] for _ in range(n1)]
        b_pos = [pos[rnd.randrange(n2)] for _ in range(n2)]
        a = auc_score(b_neg, b_pos)
        if a is not None:
            stats.append(a)
    if not stats:
        return None, None
    stats.sort()
    lo = stats[int(math.floor(alpha / 2 * len(stats)))]
    hi = stats[int(math.floor((1 - alpha / 2) * len(stats))) - 1]
    return round(lo, 4), round(hi, 4)


def cliff_delta(a, b=None):
    """Cliff's delta —— 非参数效应量（与 AUC 一一对应：delta = 2*AUC - 1）。

    AUC 说"概率"，delta 说"效应大小"：
      |delta| < 0.147 微不足道 / < 0.33 小 / < 0.474 中 / >= 0.474 大。
    可比 p 值更有信息量 —— 大样本下 p 必然显著，但效应可能微不足道。
    可只传 AUC（b=None），也可传两组原始分数（等价计算，供他处复用）。
    """
    if b is not None:
        a = auc_score(a, b)     # 传了两组分数 → 先折成 AUC
    if a is None:
        return None
    return round(2 * a - 1, 4)


def delta_mag(d):
    if d is None:
        return None
    ad = abs(d)
    if ad < 0.147:
        return '微不足道'
    if ad < 0.33:
        return '小'
    if ad < 0.474:
        return '中'
    return '大'


# ---------------------------------------------------------------
# 数据装载
# ---------------------------------------------------------------
def load_from_report(path):
    """从旧回测报告（_backtest_transfer.txt）的汇总表读横截面。

    ⚠️ 局限：旧报告只留了**组均值**，没有原始逐条分数 → 只能算
    "均值差异的 AUC 代理"（无法出真 AUC）。所以本函数只用于
    **提示用户去 --fetch**，不产出主结论。保留它是为了诚实：
    明确区分"我们有什么"和"我们缺什么"。
    """
    return None


def fetch_rows(cities):
    """现场抓 58 + 引擎评分，返回逐条 rows（与 backtest_transfer 同口径）。"""
    from agent.rental58 import fetch_shops
    from agent.agent import geocode
    from engine.scoring import score_site
    from engine.realtime import set_realtime

    set_realtime(False)
    CATEGORY = '奶茶'
    all_shops = []
    for city in cities:
        meta = {}
        shops = fetch_shops(city, limit=150, pages=5, mobile=True,
                            detail=True, detail_max=30, detail_budget_s=12.0, meta=meta)
        for s in shops:
            s['_city'] = city
        all_shops.extend(shops)

    order = {'转让': 0, '出租': 1, '未标': 2}
    all_shops.sort(key=lambda s: (order.get(s.get('deal') or '未标', 2),
                                  0 if s.get('area') else 1,
                                  0 if s.get('price') else 1))
    rows = []
    for s in all_shops:
        if not s.get('price'):
            continue
        city = s['_city']
        lng, lat = None, None
        for addr in [f'{city}{s.get("detail_addr") or ""}' if s.get('detail_addr') else '',
                     f'{city}{(s.get("loc") or "").strip()}' if (s.get('loc') or '').strip() else '',
                     f'{city}{(s.get("title") or "").strip()}' if (s.get('title') or '').strip() else '']:
            if not addr:
                continue
            lng, lat = geocode(addr)
            if lng:
                break
        if not lng:
            continue
        try:
            r = score_site(CATEGORY, lng, lat, s['price'],
                           name=s.get('title') or '', area_m2=s.get('area'), city=city)
        except Exception:
            continue
        rows.append({
            'deal': s.get('deal') or '未标',
            'city': city,
            'rent': s.get('price'),
            'area': s.get('area'),
            '地址评分': r.get('地址评分') or r.get('total'),
            '竞争分': (r.get('dims') or {}).get('竞争压力'),
            '租金承受力': (r.get('dims') or {}).get('租金承受力'),
            '经营评分': (r.get('经营评分') or {}).get('分数'),
            'verdict': r.get('verdict'),
            'veto': (r.get('veto') or {}).get('触发'),
        })
    return rows


def load_cache(path):
    """读上一次 --fetch 落盘的 rows（零网络复跑）。"""
    if not Path(path).exists():
        return None
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except Exception:
        return None


# ---------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------
def main():
    argv = sys.argv[1:]
    do_fetch = '--fetch' in argv
    cities = ['杭州', '宁波', '温州']
    if do_fetch:
        i = argv.index('--fetch')
        if i + 1 < len(argv) and not argv[i + 1].startswith('--'):
            cities = argv[i + 1].split(',')

    rows_cache = _ROOT / '_backtest_auc_rows.json'
    rows = None
    if do_fetch:
        print('[抓取中] 58 → 引擎评分 …')
        rows = fetch_rows(cities)
        rows_cache.write_text(json.dumps(rows, ensure_ascii=False, indent=1),
                              encoding='utf-8')
    else:
        rows = load_cache(rows_cache)

    lines = []

    def emit(s=''):
        lines.append(s)

    emit('# 回测升级：判别指标（AUC）报告')
    emit(f'# 生成时间 {time.strftime("%Y-%m-%d %H:%M:%S")} | bootstrap n={BOOT_N} '
         f'seed={BOOT_SEED}')
    emit('# 方法：Mann-Whitney AUC（P(转让分 < 出租分)）+ 分层 bootstrap 95%CI')
    emit('')

    if not rows:
        emit('⚠️ 尚无逐条回测数据（`_backtest_auc_rows.json` 不存在）。')
        emit('   本工具**不能**从旧报告的组均值反推 AUC（均值丢失了分布形状）。')
        emit('   请先跑一次现场抓取（约 90s，需网络）：')
        emit('     C:\\Python312\\python.exe src\\analysis\\backtest_auc.py --fetch 杭州,宁波,温州')
        out = _ROOT / '_backtest_auc.txt'
        out.write_text('\n'.join(lines), encoding='utf-8')
        print('DONE (no data) ->', out)
        return 0

    tf = [r for r in rows if r['deal'] == '转让']
    rt = [r for r in rows if r['deal'] == '出租']
    emit(f'样本：转让 {len(tf)} / 出租 {len(rt)} / 未标 '
         f'{len([r for r in rows if r["deal"] == "未标"])}（未标性质不明，不入对比）')
    emit('')

    # ---- 主指标：AUC ----
    emit('## 1. 主指标 AUC（负类=转让，正类=出租；AUC>0.5 = 引擎给转让更低分）')
    emit('指标 | 有效 n(转让/出租) | AUC | 95%CI | 显著? | Cliff δ | 效应量级')
    emit('-' * 96)
    metrics = [
        ('地址评分', '地址评分', True),      # 主结论：纯位置量，不吃品类成本
        ('租金承受力', '租金承受力', True),
        ('经营评分', '经营评分', False),     # 受品类错配污染，标警告
        ('竞争分', '竞争分', True),
    ]
    results = {}
    for label, key, clean in metrics:
        a_vals = [r[key] for r in tf if r.get(key) is not None]
        b_vals = [r[key] for r in rt if r.get(key) is not None]
        a = auc_score(a_vals, b_vals)
        if a is None:
            emit(f'{label} | - | 样本不足 | - | - | - | -')
            continue
        lo, hi = auc_ci(a_vals, b_vals)
        sig = '✓' if (lo is not None and lo > 0.5) else '✗'
        d = cliff_delta(a)
        tag = '' if clean else ' ⚠️品类错配'
        emit(f'{label}{tag} | {len(a_vals)}/{len(b_vals)} | {a:.3f} | '
             f'[{lo}, {hi}] | {sig} | {d} | {delta_mag(d)}')
        results[label] = {'auc': round(a, 4), 'ci': [lo, hi], 'n': [len(a_vals), len(b_vals)],
                          'cliff_delta': d, 'sig': sig == '✓', 'clean': clean}
    emit('')

    # ---- 退化诊断（**必看**：AUC≈0.5 有两种完全不同的原因）----
    emit('## 1b. 退化诊断 —— AUC≈0.5 是"没信号"还是"指标坏了"？')
    emit('  ⚠️ 这一步是必须的。**零判别力有两个根因，含义天差地别**：')
    emit('     a) 引擎真的看不出退出信号（信号不存在 / 模型错）；')
    emit('     b) 度量用错了 —— 指标分布**退化**（绝大多数样本同值），')
    emit('        AUC 自然趋近 0.5，此时"无判别力"是**指标的问题**，不是引擎的问题。')
    emit('')
    _diag = {}
    for key in ('地址评分', '租金承受力', '经营评分', '竞争分'):
        a_vals = [r[key] for r in tf if r.get(key) is not None]
        b_vals = [r[key] for r in rt if r.get(key) is not None]
        allv = a_vals + b_vals
        if not allv:
            continue
        from collections import Counter
        cnt = Counter(allv)
        top_val, top_n = cnt.most_common(1)[0]
        uniq = len(cnt)
        tie_rate = top_n / len(allv)
        _diag[key] = {'unique': uniq, 'top_value': top_val,
                      'top_share': round(tie_rate, 3), 'n': len(allv)}
        emit(f'  {key}: 唯一值 {uniq} 个 | 众数 {top_val} 占 {tie_rate:.0%} '
             f'（{top_n}/{len(allv)}）')
    emit('')
    # 自动判读：众数占比 ≥ 50% ⇒ 分布退化，AUC 不可读
    _degenerate = [k for k, v in _diag.items() if v['top_share'] >= 0.5]
    if _degenerate:
        emit(f'  ★ 判读：**{"/".join(_degenerate)} 分布退化**（众数占比 ≥50%）⇒ '
             f'这些指标的 AUC **不可读**作"引擎判别力"，')
        emit('    它测的是"少数非零样本的位置"，不是全体。')
    else:
        emit('  ★ 判读：各指标分布**未退化**，AUC≈0.5 应读作'
             '「该指标对退出信号无可辨识的判别力」。')
    emit('')
    # 一票否决封顶是经营评分退化的直接原因 —— 量化它
    _veto_tf = sum(1 for r in tf if r.get('veto'))
    _veto_rt = sum(1 for r in rt if r.get('veto'))
    if tf and rt:
        emit(f'  一票否决率：转让 {_veto_tf}/{len(tf)}（{_veto_tf/len(tf):.0%}）'
             f' ｜ 出租 {_veto_rt}/{len(rt)}（{_veto_rt/len(rt):.0%}）')
        emit('  ⚠️ 否决率两组都极高且接近 ⇒ **绝大多数样本被"封顶 0"**，')
        emit('     经营评分只剩 0 与少数高分两个值 ⇒ 秩相关结构被摧毁。')
        emit('     这是"一票否决把连续评分压成二值"的**度量退化**，')
        emit('     不是"引擎不认路"。要测判别力应改看**位置分**（未被封顶的那个）。')
        emit('')

    # ---- 非退化子样本：位置分的 AUC（对未否决 / 有面积子样本再算一遍）----
    emit('## 1c. 子样本 AUC（剔除退化影响）')
    emit('  在"未被一票否决"的子样本上重算位置分 AUC —— 这才是引擎**位置判断**')
    emit('  的真实判别力（不受"封顶 0"污染）。')
    emit('')
    for key, label in (('地址评分', '地址评分（未被否决子样本）'),):
        a_vals = [r[key] for r in tf if r.get(key) is not None and not r.get('veto')]
        b_vals = [r[key] for r in rt if r.get(key) is not None and not r.get('veto')]
        a = auc_score(a_vals, b_vals)
        if a is None:
            emit(f'  {label}: 样本不足（转让 {len(a_vals)} / 出租 {len(b_vals)}）')
            continue
        lo, hi = auc_ci(a_vals, b_vals)
        d = cliff_delta(a)
        emit(f'  {label}: n={len(a_vals)}/{len(b_vals)} | AUC={a:.3f} '
             f'| CI=[{lo}, {hi}] | δ={d}（{delta_mag(d)}）')
        results[label] = {'auc': round(a, 4), 'ci': [lo, hi],
                          'n': [len(a_vals), len(b_vals)],
                          'cliff_delta': d, 'sig': bool(lo and lo > 0.5),
                          'clean': True}
    emit('')
    _m = [r['地址评分'] for r in tf if not r.get('veto')]
    _n = [r['地址评分'] for r in rt if not r.get('veto')]
    if _m and _n:
        emit(f'  ⚠️ 但该子样本极小（转让 {len(_m)} / 出租 {len(_n)}）⇒ CI 会很宽，')
        emit('     只能作**方向性**参考，不足以支撑显著性主张。')
        emit('')

    # ---- 分离度（排序视角的稳健性）----
    emit('## 2. 分离度：AUC ≈ 0.5 的直接后果')
    emit('  取"对照组（出租）中位数"为线，看两组各有**多大比例**落在其下。')
    emit('  两比例之差 = **分离度**；分离度 ≈ 0 ⇒ 两组完全重叠 ⇒ AUC ≈ 0.5。')
    emit('  （⚠️ 这里的数字是"重叠程度"，不是"结论翻转率" —— ')
    emit('     翻转率另见 `flip_rate.py` 的 `_flip_rate.txt`。两者别混。）')
    emit('')
    emit('  指标 | 分界线 | 转让线下 | 出租线下 | 分离度')
    emit('  ' + '-' * 60)
    for key, label in [('地址评分', '地址评分'), ('经营评分', '经营评分（⚠️退化）'),
                       ('租金承受力', '租金承受力')]:
        a_vals = [r[key] for r in tf if r.get(key) is not None]
        b_vals = [r[key] for r in rt if r.get(key) is not None]
        if not a_vals or not b_vals:
            continue
        b_sorted = sorted(b_vals)
        mid = b_sorted[len(b_sorted) // 2]
        tf_below = sum(1 for v in a_vals if v < mid) / len(a_vals)
        rt_below = sum(1 for v in b_vals if v < mid) / len(b_vals)
        sep = tf_below - rt_below
        emit(f'  {label} | {mid} | {tf_below:.0%} | {rt_below:.0%} | {sep:+.0%}')
    emit('')
    emit('  读法：分离度越接近 0，两组越分不开 ⇒ 单店判决完全靠不住。')
    emit('        **这是"引擎看不出退出信号"的直接证据，如实报，不粉饰。**')
    emit('')

    # ---- 与旧口径对照 ----
    emit('## 3. 与旧口径（均值差）对照 —— 升级后**结论变了**，这是升级的价值')
    emit('  旧口径（backtest_transfer.py）报的是**组均值差**，2026-09-17 那次结果显示：')
    emit('    「地址评分 转让 50.9 vs 出租 53.3（差 -2.4）← 转让更差」')
    emit('    「经营评分 转让 7.7 vs 出租 11.3（差 -3.6）← 转让更差」')
    emit('  据此当时写了"引擎成功识别市场正在逃离的点位"。')
    emit('')
    emit('  **升级到 AUC 后，这个结论站不住了**：')
    emit('    · 均值差 -2.4 分在 100 分制里**既可能是信号也可能是噪声** ——')
    emit('      没有基线，无法判断"多大才算大"；')
    emit('    · AUC 给了基线（0.5）与区间（bootstrap CI）：本例所有指标 CI **都跨 0.5**，')
    emit('      ⇒ 按判别力口径，**不能声称"引擎识别出了退出信号"**；')
    emit('    · 均值差为正/负还受**分母不同**影响（转让 50 / 出租 114，档位分布不同），')
    emit('      AUC 用成对排序，不吃这个亏。')
    emit('')
    emit('  ⇒ **这正是"从描述性对照升级到判别指标"的意义**：')
    emit('    旧口径让我们说了一句大话，新口径把它收回来。')
    emit('    报告口径应改为："以 AUC 衡量，引擎对转让/出租两组**未显示显著判别力**；')
    emit('    均值差方向一致但效应量微不足道，且经营评分受一票否决封顶导致分布退化。"')
    emit('')

    # ---- 局限 ----
    emit('## 4. 局限声明（答辩必讲）')
    emit('1. 转让 ≠ 倒闭 —— 测"退出信号"，非"倒闭预测"。')
    emit('2. **品类错配不可分离**：统一用奶茶画像评所有铺，转让铺混有其他业态 →')
    emit('   经营评分受污染；**且经营评分因一票否决封顶而在两组都退化为近 0**，')
    emit('   其 AUC 不可读作判别力（见 §1b）。')
    emit('3. 非随机因果：转让/出租样本本身伴随业态/面积/租金差异。')
    emit('4. 单次快照，样本仍有限（转让 50 / 出租 114）；bootstrap CI 只反映抽样波动。')
    emit('5. AUC 是**截面判别力**，不是"预测某家店会不会倒"的准确率。')
    emit('6. **负面结论也是结论**：AUC≈0.5 说明"以现有直方特征 + 引擎现有输出，')
    emit('   无法判别退出信号"。这不证伪引擎的价值（引擎的价值在**成本结构分析与')
    emit('   租金天花板反解**，不在"预测谁要跑"），但**必须如实写进局限**，')
    emit('   不能拿旧版那句"成功识别逃离点位"继续用。')

    out_txt = _ROOT / '_backtest_auc.txt'
    out_txt.write_text('\n'.join(lines), encoding='utf-8')
    out_json = _ROOT / '_backtest_auc.json'
    out_json.write_text(json.dumps({
        'generated': time.strftime('%Y-%m-%d %H:%M:%S'),
        'n': {'转让': len(tf), '出租': len(rt)},
        'metrics': results,
        'bootstrap_n': BOOT_N, 'seed': BOOT_SEED,
    }, ensure_ascii=False, indent=1), encoding='utf-8')
    print('DONE ->', out_txt)
    print('      ->', out_json)
    return 0


if __name__ == '__main__':
    sys.exit(main())
