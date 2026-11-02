# -*- coding: utf-8 -*-
"""verify_output_numbers.py —— LLM 输出数字溯源校验（“引擎产数、LLM 产文”的机器断言）
================================================================================
2026-09-28 新增。对应专家评审 P0-3：「LLM 输出数字溯源校验 … 让'产文不产数'
成为可证明的不变式」。

## 这个模块解决什么

本项目的核心纪律是「**引擎产数、LLM 产文**」—— 所有金额/百分比/月数都必须来自
评分引擎（`score_site` / `estimate_profit` / `solve_rent_limits`），LLM 只负责
把它们说成人话。但在这之前，这条纪律**只是一句承诺**：
没有任何机制阻止 LLM 在解读里写出一个没出现过的数字（幻觉数字）。

本模块给它一个**机器断言**：
  1. 从 LLM 输出里抽出所有金额 / 百分比 / 月数；
  2. 逐一匹配本次决策记录里的引擎数值（允许取整误差）；
  3. 匹配不上的 → 挂"未溯源"标记（**不改写、不拦截**，见下）；
  4. 同时检查结论标签不与引擎最终结论矛盾（引擎已否决、话术不得劝签）。

## ⚠️ 为什么只标记、不自动改写（设计决策，别改成硬拦）

自动改写 LLM 输出里"对不上"的数字，风险比收益大：
  - 抽取器会误报（"第一"里的"一"、"3 个建议"里的"3"、"2026 年"），
    硬改会把**正确的话改错**；
  - 部分数字是**允许的新表述**（"翻一倍""多花两成"这类相对说法）。
所以本模块的输出是**诊断信息**：
  - 挂进 `result['number_check']`，供报告/审计读取；
  - 命中比例超阈值时，在「执行过程」面板**出声**（不静默）。
真正的硬拦只在一种情形：**结论标签与引擎矛盾**（引擎否决、话术劝签）——
那种情况下话术会直接误导用户签字，必须拦。

## 沿用本项目的口径约定
- 数值比对一律用**相对容差**（默认 1%），因为引擎与话术的取整方式不同
  （专家评审点名的 `¥73,614 vs 73,615`、`12,951 vs 12,960` 就是这么来的）。
- 「允许取整」的判据：|a-b| / max(|b|, 1) <= tol，或四舍五入到同一位后相等。

运行自检：C:\\Python314\\python.exe src\\analysis\\verify_output_numbers.py
"""
import re

# ---------------------------------------------------------------
# 抽取
# ---------------------------------------------------------------
# 金额：¥1234 / 1234元 / 1.2万元 / 12,345 / 3.5万
_MONEY = re.compile(
    r'(?:¥|￥)?\s*(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(万|千|k|w)?\s*(?:元|块|人民币)?',
    re.IGNORECASE,
)
# 百分比：12% / 12.5% / 百分之十二
_PCT = re.compile(r'(\d+(?:\.\d+)?)\s*%')
# 月数：回本 24 个月 / 24 月 / 24个月
_MONTHS = re.compile(r'(\d+(?:\.\d+)?)\s*(?:个月|月)')

# 明显不是"引擎数值"的噪声（年份、序数、纯计数词前后缀）
_NOISE_PREFIX = ('第', '星期', '周', '点', '号', '年', '月', '日', '时', '分', '秒')
# 单位量级：用于把 "1.2万" 还原成 12000
_SCALE = {'万': 10000, 'w': 10000, '千': 1000, 'k': 1000}


def _to_float(num_s, unit=None):
    try:
        v = float(str(num_s).replace(',', ''))
    except Exception:
        return None
    if unit:
        v *= _SCALE.get(str(unit).lower(), 1)
    return v


def extract_numbers(text: str):
    """抽出文本里的金额 / 百分比 / 月数三类数值。

    返回 dict：
      money   = [float, ...]      （已按万/千还原成元）
      pct     = [float, ...]      （百分数的数值，如 12.5 表示 12.5%）
      months  = [float, ...]
      raw     = [str, ...]        （命中的原始片段，供报告展示）
    """
    t = text or ''
    money, pct, months, raw = [], [], [], []

    for m in _MONEY.finditer(t):
        # 过滤序数/日期类噪声：命中前一个字符是"第/年月日"等就跳过
        pre = t[max(0, m.start() - 1):m.start()]
        if pre and pre in _NOISE_PREFIX:
            continue
        has_ctx = bool(m.group(2)) or ('元' in m.group(0)) or ('¥' in m.group(0)) \
            or ('￥' in m.group(0)) or (',' in (m.group(1) or ''))
        # 纯裸数字（无单位、无千分位、非小数）多半是计数，不进 money
        if not has_ctx and '.' not in (m.group(1) or ''):
            continue
        v = _to_float(m.group(1), m.group(2))
        if v is None:
            continue
        # 金额量级闸：本项目的金额都在 10 ~ 1e8 之间
        if not (1 <= v <= 1e8):
            continue
        money.append(v)
        raw.append(m.group(0).strip())

    for m in _PCT.finditer(t):
        v = _to_float(m.group(1))
        if v is not None and 0 <= v <= 1000:
            pct.append(v)
            raw.append(m.group(0).strip())

    for m in _MONTHS.finditer(t):
        v = _to_float(m.group(1))
        if v is not None and 0 < v <= 600:
            months.append(v)
            raw.append(m.group(0).strip())

    return {'money': money, 'pct': pct, 'months': months, 'raw': raw}


# ---------------------------------------------------------------
# 决策记录 → 参考数值集合
# ---------------------------------------------------------------
def collect_reference_values(result: dict):
    """把引擎结果里所有**允许被话术引用**的数值收成一个集合。

    范围与 `_BIZ_KEYS` 一致（引擎产出的键），外加四维评分、总分、口径区间、
    租金上限、一票否决阈值。**只收引擎给的数** —— 这就是"参考系"。
    """
    vals = set()
    pct_vals = set()

    def _add(v):
        try:
            v = float(v)
        except Exception:
            return
        if 1 <= v <= 1e8:
            vals.add(round(v, 4))

    r = result or {}
    # 利润块（含三档）—— 先归一成"dict 列表"再遍历，避免星号解包与
    # 条件表达式混用（那种写法在 Python 里是语法错误）
    _profit_srcs = [r.get('profit')]
    _bands = r.get('profit_bands')
    if isinstance(_bands, dict):
        _profit_srcs.extend(list(_bands.values()))
    elif isinstance(_bands, (list, tuple)):
        _profit_srcs.extend(list(_bands))
    for src in _profit_srcs:
        if not isinstance(src, dict):
            continue
        for k, v in src.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                if k in ('净利率', '毛利率', '外卖抽成占流水比', '扣渠道后毛利率'):
                    pct_vals.add(round(float(v) * 100, 4))
                    pct_vals.add(round(float(v), 4))
                _add(v)
    # 四维 + 总分
    for v in (r.get('dims') or {}).values():
        _add(v)
    _add(r.get('total'))
    # 租金上限 / 承受力
    for k, v in (r.get('rent_limits') or {}).items():
        if isinstance(v, (int, float)):
            _add(v)
        elif isinstance(v, dict):
            for vv in v.values():
                if isinstance(vv, (int, float)):
                    _add(vv)
    # 证据块里的数
    for v in (r.get('evidence') or {}).values():
        if isinstance(v, (int, float)):
            _add(v)
    # 一票否决相关
    vet = r.get('veto') or {}
    for v in vet.values():
        if isinstance(v, (int, float)):
            _add(v)
    # 口径区间
    band = r.get('elasticity_band') or r.get('口径区间') or {}
    if isinstance(band, dict):
        for v in band.values():
            if isinstance(v, (int, float)):
                _add(v)
            elif isinstance(v, (list, tuple)):
                for vv in v:
                    _add(vv)
    # 投资 / 租金 / 面积（用户输入，引擎也吃这些）
    for k in ('investment', 'monthly_rent', 'rent', 'area', 'staff'):
        _add(result.get(k))
    return vals, pct_vals


def _near(a, b, tol=0.01):
    """相对容差比对（默认 1%），覆盖引擎与话术取整方式的差异。"""
    if a is None or b is None:
        return False
    try:
        a, b = float(a), float(b)
    except Exception:
        return False
    if abs(a - b) <= 1e-9:
        return True
    return abs(a - b) <= tol * max(abs(b), 1.0)


def check_numbers(text: str, result: dict, tol=0.01, extra_refs=None):
    """把 LLM 输出里的数值与引擎参考系比对。

    `extra_refs`：额外的合法数值来源（如 `state` 里的用户输入 —— investment /
    staff / rent / area 这些**用户给的**数，引擎可能原样回显也可能不入 result）。
    不给的话，话术里报"前期投入 18 万"会被误判为幻觉（实测踩过）。

    返回 dict：
      checked   = 检查了多少个数
      traced    = 能溯源的个数
      untraced  = [{'kind','value','raw'}, ...]   未溯源的
      ratio     = traced / checked （0~1；checked=0 时记 1.0）
      ok        = ratio >= 0.8（经验阈值；低于则值得出声）
    """
    nums = extract_numbers(text)
    vals, pct_vals = collect_reference_values(result)
    # 合并额外参考源（只收标量；dict/list 递归收标量，与主参考系同口径）
    if extra_refs:
        def _harvest(o, depth=0):
            if depth > 4:
                return
            if isinstance(o, bool) or o is None:
                return
            if isinstance(o, (int, float)):
                v = float(o)
                if 1 <= v <= 1e8:
                    vals.add(round(v, 4))
            elif isinstance(o, dict):
                for vv in o.values():
                    _harvest(vv, depth + 1)
            elif isinstance(o, (list, tuple)):
                for vv in o:
                    _harvest(vv, depth + 1)
        if isinstance(extra_refs, dict):
            _harvest(extra_refs)
        elif isinstance(extra_refs, (list, tuple)):
            _harvest(dict(enumerate(extra_refs)))

    traced, untraced = 0, []
    checked = 0

    for kind, arr, ref in (('money', nums['money'], vals),
                           ('pct', nums['pct'], pct_vals),
                           ('months', nums['months'], vals)):
        for v in arr:
            checked += 1
            hit = any(_near(v, rv, tol) for rv in ref)
            if hit:
                traced += 1
            else:
                untraced.append({'kind': kind, 'value': v})

    ratio = 1.0 if checked == 0 else traced / checked
    return {
        'checked': checked,
        'traced': traced,
        'untraced': untraced[:12],       # 只留前 12 条，防报告爆炸
        'untraced_n': len(untraced),
        'ratio': round(ratio, 4),
        'ok': ratio >= 0.8,              # 阈值：与门禁同一把尺子
    }


# ---------------------------------------------------------------
# 结论标签一致性（唯一需要"硬拦"的情形）
# ---------------------------------------------------------------
# 引擎的负面结论词（与 scorer 的 verdict 口径一致）
_NEGATIVE_VERDICTS = ('不建议', '谨慎推荐', '不可签', '谨慎', '否决')
# 话术里的"劝签"词：引擎已否决却出现这些 → 矛盾
_PRO_SIGN = ('可以放心签', '放心签', '建议签', '赶紧签', '很划算可以签',
             '闭眼入', '稳赚', '保底赚', '一定赚')
# 话术里的"警示"词：与负面结论一致
_ALERT = ('不建议', '谨慎', '有风险', '不推荐', '再考虑', '别急着签',
          '不建议签', '算不过来', '亏损', '撑不住')


def check_verdict_consistency(text: str, result: dict):
    """检查话术结论标签是否与引擎最终结论矛盾。

    只判最危险的一种：**引擎已给负面结论，话术却在劝签** ——
    那会让用户押上积蓄去签一个模型明确否掉的位置。
    返回 {'ok': bool, 'reason': str}
    """
    verdict = str((result or {}).get('verdict') or '')
    veto = (result or {}).get('veto') or {}
    engine_negative = any(k in verdict for k in _NEGATIVE_VERDICTS) or bool(veto.get('触发'))

    t = text or ''
    pro = [w for w in _PRO_SIGN if w in t]
    alert = [w for w in _ALERT if w in t]

    if engine_negative and pro and not alert:
        return {'ok': False,
                'reason': f'引擎结论「{verdict}」为负面，话术却出现劝签词 {pro} 且无任何风险提示'}
    return {'ok': True, 'reason': ''}


def audit(text: str, result: dict, tol=0.01, extra_refs=None):
    """综合审计：数字溯源 + 结论一致性。给调用方一个入口。"""
    nc = check_numbers(text, result, tol=tol, extra_refs=extra_refs)
    vc = check_verdict_consistency(text, result)
    return {'numbers': nc, 'verdict': vc,
            'ok': nc['ok'] and vc['ok']}


# ---------------------------------------------------------------
# 自检
# ---------------------------------------------------------------
if __name__ == '__main__':
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    _res = {
        'total': 72, 'verdict': '谨慎推荐',
        'dims': {'客群匹配度': 84, '竞争压力': 61, '交通可达性': 79, '租金承受力': 55},
        'profit': {'月净利估算': 19950, '月租金': 8000, '净利率': 0.21,
                   '回本周期(月)': 18, '前期投入': 180000, '月流水估算': 95000},
        'rent_limits': {'盈亏平衡月租': 27950, '回本达标月租上限': 26000},
        'evidence': {'捕获份额P': 0.62, '竞品数': 11},
    }

    L, F = [], []

    def chk(c, label, detail=''):
        print(f'  {"PASS" if c else "FAIL"}  {label}' + (f'  |  {detail}' if detail else ''))
        if not c:
            F.append(label)

    print('=' * 70)
    print('[1] 抽取器')
    print('-' * 70)
    n = extract_numbers('月净利约 ¥19,950，回本 18 个月，净利率 21%，前期投入 18 万。')
    chk(19950.0 in n['money'], '抽到 ¥19,950', f"{n['money']}")
    chk(180000.0 in n['money'], '抽到 18 万 → 180000', f"{n['money']}")
    chk(21.0 in n['pct'], '抽到 21%', f"{n['pct']}")
    chk(18.0 in n['months'], '抽到 18 个月', f"{n['months']}")

    print('\n[2] 溯源：全部命中')
    print('-' * 70)
    good = '月净利 ¥19,950，回本 18 个月，月租 ¥8,000，前期投入 ¥180,000，净利率 21%。'
    a = audit(good, _res)
    chk(a['numbers']['ok'], '忠实引用引擎数字 → ok', f"ratio={a['numbers']['ratio']}")
    chk(a['numbers']['untraced_n'] == 0, '无未溯源数字', f"{a['numbers']['untraced']}")

    print('\n[3] 溯源：幻觉数字被抓')
    print('-' * 70)
    bad = '月净利 ¥19,950，预计日销 300 杯，月流水可达 ¥270,000。'
    b = audit(bad, _res)
    chk(not b['numbers']['ok'], '编造的 ¥270,000 被抓', f"untraced={b['numbers']['untraced']}")
    chk(any(u['value'] == 270000.0 for u in b['numbers']['untraced']),
        '未溯源清单含 270000', f"{b['numbers']['untraced']}")

    print('\n[4] 取整容忍（专家点名的 73,614 vs 73,615）')
    print('-' * 70)
    r2 = dict(_res)
    r2['profit'] = dict(_res['profit'], 月成本合计=73615)
    a2 = audit('各项成本相加 ¥73,614。', r2)
    chk(a2['numbers']['traced'] >= 1, '¥73,614 与引擎 73615 视为一致', f"ratio={a2['numbers']['ratio']}")

    print('\n[5] 结论一致性（唯一硬拦项）')
    print('-' * 70)
    v1 = audit('综合结论：谨慎推荐，回本 18 个月。', _res)
    chk(v1['verdict']['ok'], '负面结论 + 有警示 → 一致', f"{v1['verdict']}")
    r3 = dict(_res, verdict='不建议')
    v2 = audit('这个位置很划算，可以放心签！', r3)
    chk(not v2['verdict']['ok'], '引擎"不建议"却劝签 → 抓矛盾', f"{v2['verdict']['reason'][:40]}")

    print('\n' + '=' * 70)
    print(f'结论：{"全部通过" if not F else str(len(F)) + " 项 FAIL"}')
    print('=' * 70)
    for x in F:
        print(f'  FAIL  {x}')
    sys.exit(1 if F else 0)
