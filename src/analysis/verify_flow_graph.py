# -*- coding: utf-8 -*-
"""LangGraph 图级端到端验证（需求 3 / 4）
真实走 agent_graph.ainvoke，验证路由表、节点衔接与状态传递
（前面的 verify_flow_v2.py 是直接调节点，不覆盖图边）。

运行：C:/Python314/python.exe src/analysis/verify_flow_graph.py
"""
import sys
import asyncio
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'src'))

OUT = []


def p(s=''):
    OUT.append(str(s))


from agent.agent_graph import agent_graph, set_free_chat_mode  # noqa: E402

FAILS = []


def check(c, label):
    if not c:
        FAILS.append(label)
    return c


async def run(msg, state=None):
    st = dict(state or {})
    st.setdefault('messages', [])
    st.setdefault('phase', 'intro')
    st.setdefault('missing_info', [])
    st.setdefault('candidates', [])
    st.setdefault('list_shown', False)
    st['hooks'] = {'steps': []}
    st['messages'] = list(st['messages']) + [{'role': 'user', 'content': msg}]
    return await agent_graph.ainvoke(st, config={'recursion_limit': 12})


def last_assistant(st):
    for m in reversed(st.get('messages') or []):
        if m.get('role') == 'assistant' and m.get('content'):
            return m['content']
    return ''


async def main():
    g = agent_graph.get_graph().nodes
    p('图节点数：%d' % len(g))
    p('节点：' + '、'.join(sorted(g.keys())))
    for n in ('shop_first', 'reverse_match', 'collect_brand', 'collect_invest', 'free_chat'):
        check(n in g, f'图中缺少节点 {n}')
    edges = {(e.source, e.target) for e in agent_graph.get_graph().edges}
    for e in [('shop_first', 'reverse_match'), ('reverse_match', '__end__')]:
        check(e in edges, f'缺少边 {e[0]} -> {e[1]}')
    p('shop_first / reverse_match 相关边：'
      + '、'.join(f'{a}->{b}' for a, b in sorted(edges) if a in ('shop_first', 'reverse_match')))
    p()

    # ---------- T1：有铺子但没想好做什么 ----------
    p('=' * 70)
    p('T1  输入「我有个铺子但不知道开什么」（整图）')
    p('=' * 70)
    try:
        s1 = await run('我有个铺子但不知道开什么')
        p(f'  phase = {s1.get("phase")}')
        p(f'  missing = {s1.get("missing_info")}')
        msg = last_assistant(s1)
        p('  回复：')
        for ln in msg.splitlines():
            if ln.strip():
                p('    | ' + ln)
        check(s1.get('phase') == 'shop_first', f'T1 phase 应为 shop_first，得到 {s1.get("phase")}')
        check('月租金' in msg and '面积' in msg and '地址' in msg, 'T1 追问未点出三项')
        check(set(s1.get('missing_info') or []) == {'地址', '月租金', '面积'},
              f'T1 missing 应为三项，得到 {s1.get("missing_info")}')
    except Exception as e:
        check(False, f'T1 抛异常：{type(e).__name__}: {e}')
        p(f'  [ERROR] {type(e).__name__}: {e}')
    p()

    # ---------- T2：补齐三件套 -> 四品类反推 ----------
    p('=' * 70)
    p('T2  接上轮，输入「杭州滨江江陵路 88 号，月租 9000，面积 45 平米」')
    p('=' * 70)
    s2 = None
    try:
        s2 = await run('杭州滨江江陵路 88 号，月租 9000，面积 45 平米', s1)
        p(f'  phase = {s2.get("phase")}')
        p(f'  address = {s2.get("address")!r}  rent = {s2.get("rent")}  area = {s2.get("area")}')
        p(f'  pending_coord = {s2.get("pending_coord")}')
        recs = s2.get('category_recs') or []
        p(f'  category_recs = {len(recs)} 条')
        for c in recs:
            net = c.get('monthly_net')
            p(f'    {c.get("i")}. {c.get("category"):<5} 净利 '
              + (f'¥{net:,.0f}' if net is not None else 'n/a')
              + f'  标签={c.get("label")}')
        p('  回复：')
        for ln in last_assistant(s2).splitlines():
            if ln.strip():
                p('    | ' + ln)
        check(s2.get('phase') == 'reverse_match',
              f'T2 phase 应为 reverse_match，得到 {s2.get("phase")}')
        check(len(recs) == 4, f'T2 应产出 4 个品类，得到 {len(recs)}')
        check(bool(s2.get('pending_coord')), 'T2 未完成定位')
    except Exception as e:
        check(False, f'T2 抛异常：{type(e).__name__}: {e}')
        p(f'  [ERROR] {type(e).__name__}: {e}')
    p()

    # ---------- T3 / T4：反推后选方向 ----------
    if s2 and s2.get('phase') == 'reverse_match':
        p('=' * 70)
        p('T3  接上轮，点「我选奶茶」-> 应衔接到品牌选择（奶茶专属环节）')
        p('=' * 70)
        try:
            s3 = await run('我选奶茶', s2)
            p(f'  phase = {s3.get("phase")}  category = {s3.get("category")!r}  brand = {s3.get("brand")}')
            check(s3.get('phase') == 'collect_brand',
                  f'T3 奶茶应进 collect_brand，得到 {s3.get("phase")}')
            check(s3.get('category') == '奶茶', f'T3 品类应为奶茶，得到 {s3.get("category")}')
        except Exception as e:
            check(False, f'T3 抛异常：{type(e).__name__}: {e}')
            p(f'  [ERROR] {type(e).__name__}: {e}')
        p()

        p('=' * 70)
        p('T4  接上轮，点「我选甜品」-> 非奶茶应跳过品牌，直接进预算')
        p('=' * 70)
        try:
            s4 = await run('我选甜品', s2)
            p(f'  phase = {s4.get("phase")}  category = {s4.get("category")!r}')
            check(s4.get('phase') == 'collect_invest',
                  f'T4 甜品应进 collect_invest，得到 {s4.get("phase")}')
            check(s4.get('category') == '甜品', f'T4 品类应为甜品，得到 {s4.get("category")}')
        except Exception as e:
            check(False, f'T4 抛异常：{type(e).__name__}: {e}')
            p(f'  [ERROR] {type(e).__name__}: {e}')
        p()

    # ---------- T5：自由对话开关（图级） ----------
    p('=' * 70)
    p('T5  开启「自由对话」后，整图必须直接进 free_chat')
    p('=' * 70)
    set_free_chat_mode(True)
    try:
        s5 = await run('我想开奶茶店，帮我找杭州滨江的铺子')
        p(f'  phase = {s5.get("phase")}')
        check(s5.get('phase') == 'chat', f'T5 phase 应为 chat，得到 {s5.get("phase")}')
    except Exception as e:
        check(False, f'T5 抛异常：{type(e).__name__}: {e}')
        p(f'  [ERROR] {type(e).__name__}: {e}')
    finally:
        set_free_chat_mode(False)
    p()

    # ---------- 汇总 ----------
    p('=' * 70)
    if FAILS:
        p(f'❌ 失败 {len(FAILS)} 项：')
        for f in FAILS:
            p('   - ' + f)
    else:
        p('✅ 图级验证全部通过')
    p('=' * 70)

    (Path(__file__).resolve().parent / '_verify_flow_graph.txt').write_text(
        '\n'.join(OUT), encoding='utf-8')
    print('done, fails =', len(FAILS))


if __name__ == '__main__':
    asyncio.run(main())
    # ⚠️ 2026-09-15 补：原先失败也只打印、不设退出码 → 批量回归把它当"通过"。
    sys.exit(1 if FAILS else 0)
