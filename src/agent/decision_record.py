# -*- coding: utf-8 -*-
"""
decision_record.py —— 决策记录（证据包哈希）：让每一次结论都可复核、可追责
================================================================================
2026-09-28 新增（专家评审 P0/P1：「决策记录 … 可导出、可复核」）。

## 问题
现在一次分析留下的痕迹是「一段 LLM 写的话 + 一份结果 JSON」。
答辩/审计追问「这条结论是怎么来的」时，我们能给出的只有**当下**的代码与数据 ——
而代码会改、POI 库会更新、品牌表会换版（v7→v8 就换过）。
**同一个地址、同一个月租，两个月后重跑，得到的数字可能不同**，且没有任何记录
说明差异来自哪里。这不是"引擎有 bug"，而是**缺少可复核的凭据**。

## 做法：证据包 + 内容哈希（Merkle 式摘要）
把一次决策用到的**全部输入 + 全部口径**收进一个规范化 JSON（"证据包"），
再算一个 SHA-256（前 16 位当"决策指纹"）。证据包分四块：

    ┌ inputs      用户给的原始参数（品类/坐标/租金/面积/投入/人数）
    ├ engine      引擎身份（版本号 + 关键常量的值 —— λ / d0 / 锚点 / uplift 表版本）
    ├ evidence    引擎实际取到的证据（竞品数/捕获份额/需求池/POI 库版本）
    └ output      引擎产出（总分/四维/结论/三档/租金上限/一票否决）

**哈希的意义**：
  - 同输入 + 同口径 → **同指纹**（可复现性可被机器验证，不用信我们的话）；
  - 任一常量变更（比如 λ 从 2.0 改成别的）→ 指纹必变 ⇒ 旧结论**自动作废**，
    不会出现"用新引擎的号解释旧结论"这种事后追认。

## ⚠️ 三条口径约束（不许越界）
1. **只读不改**：本模块**不参与**评分，不产生任何新数字（符合"引擎产数"）。
   它只做摘要与哈希。
2. **哈希只覆盖"决策相关"字段**：LLM 解读文本**不进哈希** ——
   解读是文本产物，同一证据包换个温度就变了，进去等于让指纹随措辞漂移。
3. **JSON 必须规范化**：键排序 + 固定小数位 + 无空格，否则同一份证据包
   Python 的 dict 迭代序不同就出不同哈希（假指纹）。本模块用
   `sort_keys=True, separators=(',',':')` 并**递归取整**浮点。

## 用法
    from agent.decision_record import build_record, fingerprint, format_record
    rec = build_record(state, result)
    fp  = rec['指纹']                       # 16 位十六进制
    txt = format_record(rec)                # 可粘贴进报告/回复的文本

运行自检：C:\\Python312\\python.exe src\\agent\\decision_record.py
"""
import hashlib
import json
import sys
from pathlib import Path

# ⚠️ 直接 `python src/agent/decision_record.py` 跑自检时，`engine` / `config`
#    不在搜索路径里（脚本目录是 src/agent，不是 src）—— 必须先补 src。
#    少了这两行，engine_identity() 会静默走 except 分支记 None，
#    自检报 FAIL 但**生产环境反而是好的**，最容易把人带偏。
_SRC = Path(__file__).resolve().parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# 证据包 schema 版本：**加入/删除字段时必须 +1** ——
# 否则新旧两代的哈希会被误当"同一代"比对（v1 少个字段、v2 多个字段，
# 同一个地址会得出不同指纹，看起来像"数据变了"，实际只是我们改了摘要口径）。
RECORD_VERSION = 'v1'


# ---------------------------------------------------------------
# 递归规范化（防浮点/键序制造假指纹）
# ---------------------------------------------------------------
def _norm(obj, ndigits=6):
    """递归规范化：浮点按 ndigits 取整、dict 键排序、list 保序。

    为什么必须做：`json.dumps({'a':0.1+0.2})` 与 `json.dumps({'a':0.3})`
    输出不同（0.30000000000000004 vs 0.3），但决策上完全等价。
    不规范化 → 同一逻辑输入偶尔得出不同指纹 → 用户以为"结论变了"。
    """
    if isinstance(obj, dict):
        return {str(k): _norm(v, ndigits) for k, v in sorted(obj.items(),
                                                            key=lambda kv: str(kv[0]))}
    if isinstance(obj, (list, tuple)):
        return [_norm(v, ndigits) for v in obj]
    if isinstance(obj, bool):
        return obj                      # bool 必须在 int 之前判（bool 是 int 子类）
    if isinstance(obj, (int, float)):
        try:
            f = round(float(obj), ndigits)
            # 整数化：12.0 与 12 应视为同一个值
            return int(f) if f == int(f) and abs(f) < 1e15 else f
        except Exception:
            return str(obj)
    if obj is None:
        return None
    return str(obj)


def canonical_json(payload: dict) -> str:
    """规范化的 JSON 字符串（键排序、无多余空格、浮点已取整）。"""
    return json.dumps(_norm(payload), ensure_ascii=False,
                      sort_keys=True, separators=(',', ':'))


def fingerprint(payload: dict, n=16) -> str:
    """证据包 → 决策指纹（SHA-256 前 n 位十六进制）。"""
    h = hashlib.sha256(canonical_json(payload).encode('utf-8')).hexdigest()
    return h[:n]


def short_hash(obj, n=12) -> str:
    """任意可序列化对象的短哈希（用于 POI 库版本、品牌表版本等的内联摘要）。"""
    try:
        s = canonical_json(obj) if isinstance(obj, (dict, list)) else str(obj)
    except Exception:
        s = repr(obj)
    return hashlib.sha256(s.encode('utf-8')).hexdigest()[:n]


# ---------------------------------------------------------------
# 引擎身份：把"当时的口径"钉进证据包
# ---------------------------------------------------------------
def engine_identity():
    """收集当前引擎的关键口径常量（**只读**，任何一项变了指纹就变）。

    设计取舍：这里**不 import 整个 engine 包**（那会拖慢每次分析），
    只 import 几个常量模块；取不到的项记 None 并**显式标出**
    （红线：不静默 —— 缺口径比给错口径更危险，因为缺了看不出来）。

    ⚠️ 常量来源以 `engine.scoring` / `engine.brands` 的**顶层定义为准**
    （那是引擎真正读的值），不读标定产物 `*.json` —— 产物是"上游"，
    引擎读的是"下游"，两者在扩样/切表后会分歧（本项目踩过）。
    """
    ident = {'record_version': RECORD_VERSION}
    # λ / d0 / REF_DP / P_REF：Huff 与锚点的核心常数（引擎在读的那份）
    try:
        from engine.scoring import LAMBDA, D0, REF_DP, P_REF, USE_BRAND_UPLIFT
        ident['lambda'] = LAMBDA
        ident['d0'] = D0
        ident['anchor'] = {'REF_DP': REF_DP, 'P_REF': P_REF}
        ident['use_brand_uplift'] = USE_BRAND_UPLIFT
    except Exception:
        ident['lambda'] = None
        ident['d0'] = None
        ident['anchor'] = None
        ident['use_brand_uplift'] = None
    # 品牌 uplift 表：**摘要哈希**而非整表 —— 表有 34 品牌 × 多项，
    # 整表进指纹会让证据包变得不可读；哈希同样能"表一变指纹就变"。
    try:
        from engine.brands import UPLIFT, UPLIFT_TIER, UPLIFT_CI
        ident['uplift_table_version'] = 'engine.brands.UPLIFT'
        ident['uplift_digest'] = short_hash(UPLIFT)
        ident['uplift_tier_digest'] = short_hash(UPLIFT_TIER)
        ident['uplift_n_brands'] = len(UPLIFT)
        ident['uplift_has_ci'] = bool(UPLIFT_CI)
    except Exception:
        ident['uplift_table_version'] = None
        ident['uplift_digest'] = None
    # 本地 POI 库的规模与指纹（数据变了指纹也变）
    # ⚠️ 库名是 zj_poi.db（浙江 4.4 万条），不是 poi.db —— 写错会静默记 None
    try:
        from config import DATA_DIR
        import sqlite3
        poi = None
        for nm in ('zj_poi.db', 'poi.db'):
            db = DATA_DIR / nm
            if not db.exists():
                continue
            n = None
            try:
                con = sqlite3.connect(str(db))
                cur = con.cursor()
                # 表名各版本不同，逐个试；试不到就只记文件 fingerprint
                for tbl in ('pois', 'poi', 'shops'):
                    try:
                        cur.execute(f'SELECT COUNT(*) FROM {tbl}')
                        n = cur.fetchone()[0]
                        break
                    except Exception:
                        continue
                con.close()
            except Exception:
                pass
            poi = {'file': nm, 'n': n, 'mtime': int(db.stat().st_mtime),
                   'size': db.stat().st_size}
            break
        ident['poi_db'] = poi
    except Exception:
        ident['poi_db'] = None
    # 步行路网距离库（v8 口径的底座）
    try:
        from config import DATA_DIR
        rd = DATA_DIR / 'road_distance.db'
        ident['road_distance_db'] = ({'mtime': int(rd.stat().st_mtime),
                                      'size': rd.stat().st_size}
                                     if rd.exists() else None)
    except Exception:
        ident['road_distance_db'] = None
    return ident


# ---------------------------------------------------------------
# 证据包构建
# ---------------------------------------------------------------
def _pick(d, *keys):
    """从 dict 里挑键（缺的记 None，不跳过 —— 缺项也是证据的一部分）。"""
    d = d or {}
    return {k: d.get(k) for k in keys}


def build_record(state, result):
    """把一次决策的全部痕迹收成证据包（**只读**，不改 state / result）。

    返回 dict，含四块 + '指纹'。可用 `canonical_json` 落盘。
    """
    state = state or {}
    result = result or {}
    ev = result.get('evidence') or {}
    # ⚠️ 与"锚点已补到 796"口径一致：真实池容量若引擎侧有，原样记；
    #     引擎侧没有就记 None（**不编 796** —— 摘要里编数字比不记更坏）。
    rec = {
        'record_version': RECORD_VERSION,
        # ① 用户输入：全靠抽取，任一项错结论必错 → 必须进指纹
        'inputs': {
            'category': state.get('category'),
            'address': state.get('address'),
            'lng': result.get('lng') if result.get('lng') is not None else state.get('lng'),
            'lat': result.get('lat') if result.get('lat') is not None else state.get('lat'),
            'rent': state.get('rent'),
            'rent_state': state.get('rent_state'),
            'rent_band': list(state.get('rent_band') or []) or None,
            'area': state.get('area'),
            'area_state': state.get('area_state'),
            'brand': state.get('brand'),
            'investment': state.get('investment'),
            'staff': state.get('staff'),
        },
        # ② 引擎身份：口径常量（λ/d0/锚点/uplift 表版本/POI 库mtime）
        'engine': engine_identity(),
        # ③ 证据：引擎实际取到的事实
        'evidence': {
            'competitors': ev.get('竞品数'),
            'capture_share': ev.get('捕获份额P'),
            'demand_pool': ev.get('需求池') or ev.get('D'),
            'est_month_sales': ev.get('预估月流水'),
            'brand_coeff': ev.get('品牌引力') or ev.get('own_S'),
            'poi_source': ev.get('来源') or ev.get('数据来源'),
        },
        # ④ 产出：结论本体
        'output': {
            'total': result.get('total'),
            'verdict': result.get('verdict'),
            'dims': result.get('dims'),
            'bands': {
                '悲观': _pick((result.get('profit_bands') or {}).get('悲观'),
                              '月净利估算', '回本周期(月)'),
                '中性': _pick((result.get('profit_bands') or {}).get('中性'),
                              '月净利估算', '回本周期(月)'),
                '乐观': _pick((result.get('profit_bands') or {}).get('乐观'),
                              '月净利估算', '回本周期(月)'),
            },
            'rent_limits': result.get('rent_limits'),
            'veto': _pick(result.get('veto'), '触发', '原因'),
            'operating_score': (result.get('经营评分') or {}).get('分数'),
        },
    }
    # ⑤ 数字溯源校验结果（若本次分析跑了 output_guard）
    nc = state.get('number_check') or result.get('number_check')
    if nc:
        rec['output']['number_check'] = {
            'checked': (nc.get('numbers') or {}).get('checked'),
            'ratio': (nc.get('numbers') or {}).get('ratio'),
            'ok': nc.get('ok'),
        }
    rec['指纹'] = fingerprint({k: v for k, v in rec.items() if k != '指纹'})
    return rec


# ---------------------------------------------------------------
# 文本渲染（粘贴进报告/回复）
# ---------------------------------------------------------------
def format_record(rec, brief=False):
    """把证据包渲染成可读文本。brief=True 只出三行（回复用）。"""
    if not rec:
        return ''
    fp = rec.get('指纹', '')
    inp = rec.get('inputs') or {}
    eng = rec.get('engine') or {}
    out = rec.get('output') or {}
    if brief:
        return (f'决策指纹 `{fp}`（录入 {inp.get("category") or "-"}｜'
                f'月租 {inp.get("rent") or "-"}｜λ={eng.get("lambda")} '
                f'｜uplift {eng.get("uplift_table_version")}）')
    L = []
    L.append(f'**决策记录 · 指纹 `{fp}`**（记录格式 {rec.get("record_version")}）')
    L.append('')
    L.append('| 块 | 内容 |')
    L.append('|---|---|')
    L.append(f'| 输入 | 品类 `{inp.get("category")}` ｜ 月租 `{inp.get("rent")}`'
             f'（{inp.get("rent_state") or "-"}）｜ 面积 `{inp.get("area")}`'
             f'（{inp.get("area_state") or "-"}）｜ 投入 `{inp.get("investment")}`'
             f'｜ 人数 `{inp.get("staff")}` ｜ 品牌 `{inp.get("brand")}` |')
    L.append(f'| 引擎口径 | λ=`{eng.get("lambda")}` ｜ d0=`{eng.get("d0")}`'
             f' ｜ uplift 表=`{eng.get("uplift_table_version")}`'
             f' ｜ 锚点 `{eng.get("anchor")}` ｜ POI库 `{eng.get("poi_db")}` |')
    ev = rec.get('evidence') or {}
    L.append(f'| 证据 | 竞品 `{ev.get("competitors")}` ｜ 捕获份额 `{ev.get("capture_share")}`'
             f' ｜ 需求池 `{ev.get("demand_pool")}` ｜ 品牌系数 `{ev.get("brand_coeff")}` |')
    L.append(f'| 产出 | 总分 `{out.get("total")}` ｜ 结论 `{out.get("verdict")}`'
             f' ｜ 经营评分 `{out.get("operating_score")}` ｜ 一票否决 `{(out.get("veto") or {}).get("触发")}` |')
    L.append('')
    L.append('> 同一输入 + 同一口径 ⇒ 同一指纹（可复现性可机器验证）。'
             '任一常量（λ/uplift 表/POI 库）变更 ⇒ 指纹必变，旧结论自动作废，'
             '不存在"用新引擎解释旧结论"。')
    return '\n'.join(L)


# ---------------------------------------------------------------
# 自检
# ---------------------------------------------------------------
if __name__ == '__main__':
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    F = []

    def chk(c, label, detail=''):
        print(f'  {"PASS" if c else "FAIL"}  {label}' + (f'  |  {detail}' if detail else ''))
        if not c:
            F.append(label)

    _state = {'category': '奶茶', 'address': '滨江-四桥南', 'rent': 8000.0,
              'rent_state': 'measured', 'area': 45.0, 'area_state': 'measured',
              'brand': '古茗', 'investment': 180000, 'staff': 3}
    _result = {'lng': 120.1, 'lat': 30.2, 'total': 72, 'verdict': '谨慎推荐',
               'dims': {'客群匹配度': 84, '竞争压力': 61},
               'evidence': {'竞品数': 11, '捕获份额P': 0.62, '预估月流水': 95000},
               'profit_bands': {'悲观': {'月净利估算': 8000, '回本周期(月)': 30},
                                '中性': {'月净利估算': 19950, '回本周期(月)': 18},
                                '乐观': {'月净利估算': 32000, '回本周期(月)': 11}},
               'rent_limits': {'盈亏平衡月租': 27950},
               'veto': {'触发': False}}

    print('=' * 70)
    print('§1 指纹稳定性：同输入 → 同指纹')
    print('-' * 70)
    r1 = build_record(_state, _result)
    r2 = build_record(dict(_state), dict(_result))
    chk(r1['指纹'] == r2['指纹'], '两次构建同指纹', r1['指纹'])

    print('\n§2 指纹稳定性：浮点等价（8000 vs 8000.0 vs 0.1+0.2 的坑）')
    print('-' * 70)
    s3 = dict(_state, rent=8000)
    r3 = build_record(s3, _result)
    chk(r3['指纹'] == r1['指纹'], 'rent 8000(int) == 8000.0(float)', r3['指纹'])
    _fp_a = fingerprint({'x': 0.1 + 0.2})
    _fp_b = fingerprint({'x': 0.3})
    chk(_fp_a == _fp_b, '0.1+0.2 与 0.3 同指纹（递归取整生效）', _fp_a)

    print('\n§3 敏感性：改关键口径 → 指纹必变')
    print('-' * 70)
    s4 = dict(_state, rent=9000)
    chk(build_record(s4, _result)['指纹'] != r1['指纹'], '改租金 → 指纹变')
    s5 = dict(_state, brand='蜜雪冰城')
    chk(build_record(s5, _result)['指纹'] != r1['指纹'], '改品牌 → 指纹变')
    _res2 = dict(_result, verdict='不建议')
    chk(build_record(_state, _res2)['指纹'] != r1['指纹'], '改结论 → 指纹变')

    print('\n§4 LLM 解读文本**不进**指纹（否则措辞一变指纹就漂）')
    print('-' * 70)
    s6 = dict(_state, interpretation='完全不同的另一段解读文字')
    chk(build_record(s6, _result)['指纹'] == r1['指纹'],
        'interpretation 不在指纹覆盖范围', build_record(s6, _result)['指纹'])

    print('\n§5 引擎身份块：λ/d0/锚点要能取到')
    print('-' * 70)
    eng = r1.get('engine') or {}
    chk(eng.get('lambda') is not None, 'λ 取到', str(eng.get('lambda')))
    chk(eng.get('anchor') is not None, '锚点取到', str(eng.get('anchor')))
    chk(eng.get('uplift_table_version') is not None,
        'uplift 表版本取到', str(eng.get('uplift_table_version')))

    print('\n§6 只读：build_record 不许改 state / result')
    print('-' * 70)
    _s_before = json.dumps(_state, sort_keys=True)
    _r_before = json.dumps(_result, sort_keys=True)
    build_record(_state, _result)
    chk(json.dumps(_state, sort_keys=True) == _s_before, 'state 未被修改')
    chk(json.dumps(_result, sort_keys=True) == _r_before, 'result 未被修改')

    print('\n§7 文本渲染')
    print('-' * 70)
    _txt = format_record(r1)
    chk(r1['指纹'] in _txt, '完整渲染含指纹')
    chk(r1['指纹'] in format_record(r1, brief=True), 'brief 渲染含指纹')

    print('\n' + '=' * 70)
    print(f'结论：{"全部通过" if not F else str(len(F)) + " 项 FAIL"}')
    print('=' * 70)
    for x in F:
        print(f'  FAIL  {x}')
    sys.exit(1 if F else 0)
