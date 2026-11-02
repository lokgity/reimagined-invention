# -*- coding: utf-8 -*-
"""verify_output_numbers.py —— 数字溯源校验的**离线门禁**
================================================================================
2026-09-28 新增。对应专家评审 P0-3：「LLM 输出数字溯源校验」。

`src/agent/output_guard.py` 是**模块自检**（证明模块能用）；
本文件是**项目门禁**（证明它真的接进了引擎、且消费方没走偏）。

⚠️ 本项目第一高发错是「**验返回值 ≠ 验消费方**」：
门禁绿了不代表接线对。所以本文件除了测模块，还要断言：

  §5 接线：`interpret_node` 真的调了 `output_guard.audit`，
          且 `number_check` 写进了返回值；
  §6 schema：`AgentState` 声明了 `number_check`
          （LangGraph 的 StateGraph **只传 schema 内字段**，
          schema 外字段在 ainvoke 入口被静默丢弃 —— 这是本条最关键的断言）。

运行：C:\\Python314\\python.exe src\\analysis\\verify_output_numbers.py
"""
import io
import re
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / 'src'))

from agent import output_guard as og   # noqa: E402

PASS, FAIL = [], []


def chk(cond, label, detail=''):
    print(f'  {"PASS" if cond else "FAIL"}  {label}' + (f'  |  {detail}' if detail else ''))
    (PASS if cond else FAIL).append(label)


# ---------------------------------------------------------------
# 自检样例：一份"看起来正常"的引擎结果
# ---------------------------------------------------------------
_RES = {
    'total': 72, 'verdict': '谨慎推荐',
    'dims': {'客群匹配度': 84, '竞争压力': 61, '交通可达性': 79, '租金承受力': 55},
    'profit': {'月净利估算': 19950, '月租金': 8000, '净利率': 0.21,
               '回本周期(月)': 18, '前期投入': 180000, '月流水估算': 95000},
    'profit_bands': {
        '悲观': {'月净利估算': 8000, '回本周期(月)': 30},
        '中性': {'月净利估算': 19950, '回本周期(月)': 18},
        '乐观': {'月净利估算': 32000, '回本周期(月)': 11},
    },
    'rent_limits': {'盈亏平衡月租': 27950, '回本达标月租上限': 26000},
    'evidence': {'捕获份额P': 0.62, '竞品数': 11},
}

print('=' * 72)
print('§1 抽取器：三类数值都要抽到')
print('-' * 72)
_n = og.extract_numbers('月净利约 ¥19,950，回本 18 个月，净利率 21%，前期投入 18 万。')
chk(19950.0 in _n['money'], '金额 ¥19,950', str(_n['money']))
chk(180000.0 in _n['money'], '“18 万” → 180000（量级还原）', str(_n['money']))
chk(21.0 in _n['pct'], '百分比 21%', str(_n['pct']))
chk(18.0 in _n['months'], '月数 18 个月', str(_n['months']))

print('\n§2 噪声不误抽（抽取器误报是"只标记不改写"的前提）')
print('-' * 72)
_noise = og.extract_numbers('2026 年第三周，第 3 个建议，共 11 家竞品。')
chk(2026.0 not in _noise['money'], '年份 2026 不进 money', str(_noise['money']))

print('\n§3 溯源：忠实引用 → 全命中')
print('-' * 72)
_good = '月净利 ¥19,950，回本 18 个月，月租 ¥8,000，前期投入 ¥180,000，净利率 21%。'
_a = og.audit(_good, _RES)
chk(_a['numbers']['ok'], '忠实引用 → ok', f"ratio={_a['numbers']['ratio']}")
chk(_a['numbers']['untraced_n'] == 0, '无未溯源', str(_a['numbers']['untraced']))

print('\n§4 溯源：幻觉数字必须被抓（这条是模块存在的理由）')
print('-' * 72)
_bad = '月净利 ¥19,950，预计日销 300 杯，月流水可达 ¥270,000。'
_b = og.audit(_bad, _RES)
chk(not _b['numbers']['ok'], '编造的 ¥270,000 判为不 ok', f"ratio={_b['numbers']['ratio']}")
chk(any(u['value'] == 270000.0 for u in _b['numbers']['untraced']),
    '未溯源清单含 270000', str(_b['numbers']['untraced']))

print('\n§4b 三档利润块也要进参考系（否则"报两端"必然报红）')
print('-' * 72)
_band_txt = '悲观档月净利 ¥8,000、回本 30 个月；乐观档 ¥32,000、11 个月。'
_bd = og.audit(_band_txt, _RES)
chk(_bd['numbers']['untraced_n'] == 0,
    '三档两端均可溯源（profit_bands 已收）', str(_bd['numbers']['untraced']))

print('\n§4c 取整容忍：¥73,614 vs 引擎 73,615')
print('-' * 72)
_r2 = dict(_RES, profit=dict(_RES['profit'], 月成本合计=73615))
_a2 = og.audit('各项成本相加 ¥73,614。', _r2)
chk(_a2['numbers']['traced'] >= 1, '1‰ 级取整差视为一致',
    f"ratio={_a2['numbers']['ratio']}")

print('\n§4d 结论一致性：唯一硬拦项')
print('-' * 72)
_v1 = og.audit('综合结论：谨慎推荐，回本 18 个月。', _RES)
chk(_v1['verdict']['ok'], '负面结论 + 有警示 → 一致', str(_v1['verdict']))
_r3 = dict(_RES, verdict='不建议')
_v2 = og.audit('这个位置很划算，可以放心签！', _r3)
chk(not _v2['verdict']['ok'], '引擎“不建议”却劝签 → 判矛盾',
    _v2['verdict']['reason'][:50])
_v3 = og.audit('这个位置很划算，可以放心签！', dict(_RES, verdict='推荐'))
chk(_v3['verdict']['ok'], '引擎“推荐” + 劝签 → 不误报', str(_v3['verdict']))

print('\n§4e extra_refs：用户输入是**合法**数值，不该被误判为幻觉')
print('-' * 72)
# 实测踩过：只给 result 时，话术报"前期投入"会被判幻觉 —— 因为它是**用户输入**，
# 引擎只是照读，不一定进 result。必须把 state 一起当参考源。
# ⚠️ 这里必须挑一个 result 里**确实没有**的数（_RES.profit 里有 前期投入=180000，
#    用它测不出问题 —— 自检第一版就是这么假绿的）。
_txt = '月净利 ¥19,950，装修预算 ¥320,000。（隔壁说能赚 ¥500,000）'
_r4 = dict(_RES)          # profit 里不含 320000
_a_no = og.audit(_txt, _r4)
_a_yes = og.audit(_txt, _r4, extra_refs={'decoration_budget': 320000})
chk(any(u['value'] == 320000.0 for u in _a_no['numbers']['untraced']),
    '不给 extra_refs 时 320000 被判未溯源（复现踩过的坑）',
    str([u['value'] for u in _a_no['numbers']['untraced']]))
chk(not any(u['value'] == 320000.0 for u in _a_yes['numbers']['untraced']),
    '给 extra_refs 后 320000 可溯源',
    str([u['value'] for u in _a_yes['numbers']['untraced']]))
chk(any(u['value'] == 500000.0 for u in _a_yes['numbers']['untraced']),
    '真幻觉 ¥500,000 仍被抓（extra_refs 不放松底线）',
    str([u['value'] for u in _a_yes['numbers']['untraced']]))
chk(_a_yes['numbers']['ratio'] > _a_no['numbers']['ratio'],
    'ratio 因 extra_refs 上升', f"{_a_no['numbers']['ratio']} → {_a_yes['numbers']['ratio']}")

print('\n§5 接线：interpret_node 必须真调 audit，且写回 number_check')
print('-' * 72)
_graph_src = (_ROOT / 'src' / 'agent' / 'agent_graph.py').read_text(encoding='utf-8')
chk('output_guard' in _graph_src and 'audit(' in _graph_src,
    'interpret_node 引用了 output_guard.audit',
    'grep output_guard / audit(')
chk('extra_refs=state' in _graph_src,
    'audit 调用带 extra_refs=state（用户输入算合法参考源）',
    'grep extra_refs=state')
# 顺序断言：先算出 _nc 再 return（用"出现位置先后"表达不变式，不用字面复述）
_i_audit = _graph_src.find('output_guard.audit(')
_i_ret = _graph_src.find("'number_check': _nc", _i_audit)
chk(_i_audit != -1 and _i_ret != -1 and _i_ret > _i_audit,
    'number_check 在 audit 之后写回返回值',
    f'audit@{_i_audit} → return@{_i_ret}')

print('\n§6 schema：AgentState 必须声明 number_check（漏了就被静默丢弃）')
print('-' * 72)
from agent.state import AgentState  # noqa: E402
chk('number_check' in AgentState.__annotations__,
    'AgentState 声明 number_check', str(list(AgentState.__annotations__)[-4:]))

print('\n§7 消费方顺序：插桩不能盖过引擎结果')
print('-' * 72)
# 不变式用"顺序"表达：审计插在「参数回显」之后、「return」之前，
# 即审计看的是已经拼好的完整解读（而不是半成品）
_i_echo = _graph_src.find('本次测算实际用的参数')
chk(_i_echo != -1 and _i_audit > _i_echo,
    '审计在参数回显之后（审的是完整解读）', f'echo@{_i_echo} → audit@{_i_audit}')

print('\n' + '=' * 72)
print(f'结论：{"全部通过" if not FAIL else str(len(FAIL)) + " 项 FAIL"}'
      f'（PASS {len(PASS)}）')
print('=' * 72)
for x in FAIL:
    print(f'  FAIL  {x}')
sys.exit(1 if FAIL else 0)
