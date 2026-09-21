# -*- coding: utf-8 -*-
"""verify_degrade_fallback.py —— 降级策略故障注入回归
======================================================
背景：四能力审计（docs/四能力实现度审计.md）发现「降级策略设计完整、
但**只有代码审计、无运行时验证**」——"主链全挂会不会真的走兜底"从没被执行过。
本脚本用 monkeypatch 把每一层逐一打断，断言降级行为真的发生。

零真实 API、零网络，全部可离线复现。

覆盖：
 T1  降级链：每个 provider 都被尝试；全挂必抛且错误逐一点名
 T2  火山方舟 provider 必须带 thinking disabled（防"8 分钟挂起"回归）+ 链序
 T3  总预算：超预算即跳过后续 provider，且单次 timeout 被 remain 收紧
 T4  降级回调：切换 provider 前通知上层（否则 UI 只会干转圈）
 T5  rule_based_interpret：兜底文案必须自带全部关键结论（确定性）
 T6  interpret_node：LLM 全挂 → 自动转规则解读 + 明写原因
 T7  negotiate_node：58 抓取失败 + LLM 失败 → 承受力上限这条硬证据不能丢
 T8  free_chat_node：LLM 挂 → 离线回复模板（有/无上下文两条分支）
 T9  VLM 时限不变式 + 两条调用路径共用常量（防"手动上传又漏包裹"）

用法：C:\\Python314\\python.exe src/analysis/verify_degrade_fallback.py
输出：同目录 _verify_degrade_fallback.txt
"""
import asyncio
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / '.pylibs'))

OUT = HERE / '_verify_degrade_fallback.txt'
L = []
FAIL = []


def p(*a):
    s = ' '.join(str(x) for x in a)
    print(s)
    L.append(s)


def check(name, cond, detail=''):
    p(f'  {"PASS" if cond else "FAIL"}  {name}' + (f'  |  {detail}' if detail else ''))
    if not cond:
        FAIL.append(name)


import agent.llm as llm


# ---------------------------------------------------------------
# 一份真实形状的 score_result 样例（数值取自蜜雪@天一广场 ¥11.4 口径实测）
# rule_based_interpret / 各节点均基于它做故障注入，避免联网。
#
# ⚠️ 下面是**冻结快照**（取自 2026-09-16 口径的案例 F，品牌 uplift v1：蜜雪 1.1343），
#    仅用于喂渲染路径，**不参与数值断言**。2026-09-18 品牌 uplift 整表重标定到 v6 后，
#    真机同铺位的值是 流水 104,467 / 月净利 12,688 / 免租月净利 24,688 / 回本 11.0 月
#    （见 test_veto.py 案例 F）。**不要为了"对齐实机"来改这里的数字** —— 它会牵动
#    本文件多处断言型快照；真要同步，先确认本文件没有任何断言读这些数。
# ---------------------------------------------------------------
def sample_result():
    return {
        'name': '宁波天一广场', 'category': '奶茶', 'city': '宁波',
        'total': 87.0, 'verdict': '推荐',
        'monthly_rent': 12000, 'area_m2': 30,
        'dims': {'客群引力': 40.4, '竞争格局': 18.2, '交通便利': 17.0, '租金压力': 11.4},
        'evidence': {
            '竞品数': 12, '捕获份额P': 0.181, '客群引力累计': 89190,
            '最近通勤点(m)': 120, '预估月流水': 99552, '租金占流水比': '12.1%',
            '客单价': 11.4, '客单价来源': '品牌级每单金额(公开/换算)',
        },
        '客单价校正': {
            '校正客单价': 11.4, '校正倍数': 1.4, '品类画像客单价': 16,
            '口径': '已用公开披露的每单平均金额 ¥11.4（招股书）覆盖品类画像假设 ¥16',
        },
        'utility': {'城市': '宁波', '电价(元/度)': 0.95, '水价(元/吨)': 4.8,
                    '水电合计(元/月)': 1600},
        'profit': {'前期投入': 200000, '投入来源': '用户申报', '月人工': 9000,
                   '人数': 2, '人均月薪': 4500, '月物料成本': 29866,
                   '月成本合计': 40168, '月固定成本': 40168, '月净利估算': 10265,
                   '回本周期(月)': 12.6, '盈亏判断': '盈利'},
        'profit_bands': {
            '乐观': {'月净利估算': 18000, '净利率': 0.13, '人数': 2, '回本周期(月)': 8.0},
            '中性': {'月净利估算': 10265, '净利率': 0.10, '人数': 2, '回本周期(月)': 12.6},
            '保守': {'月净利估算': 3000, '净利率': 0.03, '人数': 2, '回本周期(月)': 30.0},
            '区间': {'结论': '三档同向（都盈利）', '口径': '假设区间，非调研数据'},
        },
        '口径区间': {
            '档位': [
                {'口径': '单量刚性', '月流水': 99552, '月净利': 10265, '回本周期(月)': 12.6},
                {'口径': '营业额刚性', '月流水': 139722, '月净利': 30069, '回本周期(月)': 5.6},
            ],
            '区间': {'结论': '结论稳健', '口径': '两端都不否决，价格弹性不影响能否签的判断'},
        },
        'veto': {'触发': False, '位置分结论': '推荐'},
        'rent_limits': {'盈亏平衡月租': 22000, '回本达标月租上限': 19450, '免租月净利': 22265},
        'warnings': ['⚠️ 示例警告：租金占流水 12.1%，处于品类阈值内'],
    }


def sample_state(with_result=True, with_context=True, last_user='你好'):
    st = {
        'messages': [{'role': 'user', 'content': last_user}],
        'hooks': {'steps': []},
        'phase': 'chat',
    }
    if with_result:
        st['score_result'] = sample_result()
    if with_context:
        st['context'] = '品类: 奶茶, 地址: 宁波天一广场, 总分: 87.0, 结论: 推荐'
    return st


# ===============================================================
# T1 降级链：每个 provider 都被尝试；全挂必抛且错误逐一点名
# ===============================================================
def t1():
    p('=== T1 降级链：逐个尝试、全挂必抛且点名 ===')
    orig_pl, orig_call = llm._provider_list, llm._call_llm
    tried = []
    llm._provider_list = lambda: [
        ('k', 'u', 'm1', 'prov-A', None),
        ('k', 'u', 'm2', 'prov-B', None),
        ('k', 'u', 'm3', 'prov-C', None),
    ]

    def boom(key, url, model, sysmsg, usermsg, temperature=0.3, timeout=120, extra=None):
        tried.append((model, timeout))
        raise Exception(f'{model} 模拟 500')

    llm._call_llm = boom
    try:
        # 同步版
        err = None
        try:
            llm.call_llm_sync('s', 'u', total_budget=180)
        except Exception as e:
            err = str(e)
        check('同步版全挂必抛', err is not None and '所有 LLM 调用失败' in err, (err or '')[:60])
        check('同步版三个 provider 都被试过', len(tried) == 3, str(len(tried)))
        check('错误里逐一点名 A/B/C',
              all(n in (err or '') for n in ('prov-A', 'prov-B', 'prov-C')), (err or '')[:90])

        # 异步版
        tried.clear()
        aerr = None
        try:
            asyncio.run(llm.call_llm('s', 'u', total_budget=180))
        except Exception as e:
            aerr = str(e)
        check('异步版全挂必抛', aerr is not None and '所有 LLM 调用失败' in aerr, (aerr or '')[:60])
        check('异步版三个 provider 都被试过', len(tried) == 3, str(len(tried)))
    finally:
        llm._provider_list, llm._call_llm = orig_pl, orig_call
    p('')


# ===============================================================
# T2 火山方舟 provider 必须关思考（防"8 分钟挂起"回归）+ 链序
# ===============================================================
def t2():
    p('=== T2 火山方舟 provider 必须 thinking disabled + 链序 ===')
    snap = (llm.LLM_ARK_API_KEY, llm.LLM_API_KEY, llm.LLM_FALLBACK_API_KEY)
    llm.LLM_ARK_API_KEY = 'ark-key'
    llm.LLM_API_KEY = 'mimo-key'
    llm.LLM_FALLBACK_API_KEY = 'ds-key'
    try:
        llm.set_llm_model('DeepSeek-V4-Flash')
        provs = llm._provider_list()
        names = [x[3] for x in provs]
        p(f'  链序：{names}')
        check('链序 = 已选 → 豆包pro → 豆包turbo → mimo → DeepSeek',
              names == ['已选·DeepSeek-V4-Flash',
                        f'火山方舟·{llm.LLM_ARK_MODEL}',
                        f'火山方舟·{llm.LLM_ARK_MODEL_FALLBACK}',
                        f'小米mimo·{llm.LLM_MODEL}',
                        f'DeepSeek·{llm.LLM_FALLBACK_MODEL}'],
              str(names))
        # 火山方舟(volces.com)的 provider 必须显式关思考——否则默认深度思考
        # 会输出极长、远超超时（实测界面卡 8 分钟不返回）。
        bad = []
        for key, url, model, name, extra in provs:
            if 'volces.com' in (url or ''):
                ok = (extra or {}).get('thinking', {}).get('type') == 'disabled' \
                    and (extra or {}).get('max_tokens')
                if not ok:
                    bad.append(name)
        check('所有火山方舟 provider 均 thinking disabled + 限制 max_tokens',
              not bad, str(bad))
        llm.set_llm_model(None)
    finally:
        (llm.LLM_ARK_API_KEY, llm.LLM_API_KEY, llm.LLM_FALLBACK_API_KEY) = snap
    p('')


# ===============================================================
# T3 总预算：超预算即跳过，且单次 timeout 被 remain 收紧
# ===============================================================
def t3():
    p('=== T3 总预算（假时钟，确定性）===')
    orig_pl, orig_call, orig_time = llm._provider_list, llm._call_llm, llm.time

    class FakeTime:
        def __init__(self):
            self.t = 0.0

        def time(self):
            return self.t

    ft = FakeTime()
    llm.time = ft
    tried = []
    llm._provider_list = lambda: [(('k', 'u', f'm{i}', f'P{i}', None)) for i in range(4)]

    def slow(key, url, model, sysmsg, usermsg, temperature=0.3, timeout=120, extra=None):
        tried.append((model, timeout))
        ft.t += 100.0          # 模拟每个 provider 各耗 100s
        raise Exception('慢且失败')

    llm._call_llm = slow
    try:
        err = None
        try:
            llm.call_llm_sync('s', 'u', timeout=120, total_budget=180)
        except Exception as e:
            err = str(e)
        # 预算 180：第1次 remain=180→call；第2次 remain=80→call；第3次 remain=-20→skip；第4次 skip
        check('只尝试了未超预算的前 2 个 provider', len(tried) == 2, str(tried))
        check('单次 timeout 被 remain 收紧（120 → 80）',
              [t for _, t in tried] == [120, 80], str(tried))
        check('被跳过的 provider 明确写"已达总超时预算"',
              err is not None and err.count('跳过（已达总超时预算 180s）') == 2, (err or '')[:120])
    finally:
        llm._provider_list, llm._call_llm, llm.time = orig_pl, orig_call, orig_time
    p('')


# ===============================================================
# T4 降级回调：切换 provider 前必须通知
# ===============================================================
def t4():
    p('=== T4 降级回调（UI 靠它避免干转圈）===')
    orig_pl, orig_call = llm._provider_list, llm._call_llm
    llm._provider_list = lambda: [('k', 'u', 'm1', '首个模型', None),
                                 ('k', 'u', 'm2', '备用模型', None)]
    msgs = []

    def boom(*a, **k):
        raise Exception('boom')

    llm._call_llm = boom
    llm.set_retry_callback(msgs.append)
    try:
        try:
            llm.call_llm_sync('s', 'u')
        except Exception:
            pass
        check('切换前触发回调 1 次', len(msgs) == 1, str(len(msgs)))
        check('回调文案含备用模型名', len(msgs) == 1 and '备用模型' in msgs[0], str(msgs[:1]))
        check('回调文案含剩余预算', len(msgs) == 1 and '剩余预算' in msgs[0], str(msgs[:1]))

        # 回调自身抛异常不能带崩主流程（_notify_retry 内 try/except）
        parts = []

        def bad_cb(m):
            parts.append(m)
            raise ValueError('回调自己炸了')

        msgs2 = []
        llm.set_retry_callback(bad_cb)
        try:
            llm.call_llm_sync('s', 'u')
        except Exception as e:
            pass
        check('回调抛异常不影响降级流程', len(parts) == 1, str(len(parts)))
    finally:
        llm._provider_list, llm._call_llm = orig_pl, orig_call
        llm.set_retry_callback(None)
    p('')


# ===============================================================
# T5 rule_based_interpret：兜底文案自带全部关键结论
# ===============================================================
def t5():
    p('=== T5 规则兜底解读的完整性（确定性）===')
    from agent.agent import rule_based_interpret
    r = sample_result()
    txt = rule_based_interpret(r)
    need = {
        '结论(verdict)': r['verdict'],
        '总分': '总分 87.0',
        '维度': '客群引力',
        '证据-捕获份额': '捕获份额 18.1%',
        '客单价口径': '客单价 ¥11.4',
        '三档情景': '📊 三档情景区间',
        '口径区间': '🎯 口径区间',
        '租金临界点': '🎯 租金临界点',
        '盈亏平衡月租': '¥22,000',
        '回本上限': '¥19,450',
        '警告转达': '示例警告',
        '局限声明': '建议现场复核',
    }
    for label, s in need.items():
        check(f'兜底含{label}', s in txt, '' if s in txt else f'缺「{s}」')
    check('兜底确定性（两次逐字相同）', rule_based_interpret(r) == txt)

    # veto 触发时，兜底必须把"不能签"提到最前
    r2 = sample_result()
    r2['verdict'] = '位置好·账算不过来'
    r2['veto'] = {'触发': True, '位置分结论': '推荐', '原因': '月租 ¥12000 超回本上限'}
    t2txt = rule_based_interpret(r2)
    check('veto 触发时兜底抬头写"综合结论"',
          '综合结论' in t2txt.split('\n')[0] and '账算不过来' in t2txt.split('\n')[0],
          t2txt.split('\n')[0])
    p('')


# ===============================================================
# T6 interpret_node：LLM 全挂 → 规则解读
# ===============================================================
def t6():
    p('=== T6 interpret_node 故障注入：LLM 全挂 ===')
    import agent.agent_graph as ag
    orig = ag.call_llm

    async def boom(*a, **k):
        raise Exception('模拟所有 provider 全挂')

    ag.call_llm = boom
    try:
        st = sample_state()
        out = asyncio.run(ag.interpret_node(st))
        interp = out.get('interpretation') or ''
        from agent.agent import rule_based_interpret
        rule_head = rule_based_interpret(sample_result()).split('\n')[0]
        check('解读以规则文案开头', interp.startswith(rule_head), interp[:60])
        check('明写已降级为规则解读', '已用规则解读' in interp and '规则解读' in interp)
        check('附带失败原因', '模拟所有 provider 全挂' in interp)
        steps = (st.get('hooks') or {}).get('steps') or []
        names = [s.get('name', '') for s in steps]
        check('执行过程面板标了"规则解读（LLM 暂不可用）"',
              any('规则解读' in n for n in names), str(names))
    finally:
        ag.call_llm = orig
    p('')


# ===============================================================
# T7 negotiate_node：58 失败 + LLM 失败 → 硬证据不能丢
# ===============================================================
def t7():
    p('=== T7 negotiate_node 故障注入：58 抓取失败 + LLM 全挂 ===')
    import agent.agent_graph as ag
    import engine.negotiation as ng

    orig_llm, orig_brief = ag.call_llm, ng.negotiation_brief

    async def boom(*a, **k):
        raise Exception('LLM 全挂')

    def fake_brief(city, addr, rent, area, district, afford, *a, **k):
        # 行情分布=None 模拟 58 抓取失败；承受力上限仍在（必须活下来）
        return {'行情分布': None, '可承受月租上限': 19450, '上限口径': '回本达标月租上限',
                '行情参考带': '-', '价格位置': '未知',
                '筹码': ['免租装修期谈到 30 天', '3 年约换 5-8% 折扣', '用差额 ¥7,450 去锚，不报目标价']}

    ag.call_llm = boom
    ng.negotiation_brief = fake_brief
    try:
        st = sample_state()
        out = asyncio.run(ag.negotiate_node(st))
        reply = out['messages'][-1]['content']
        check('明写 AI 话术不可用', 'AI 话术暂不可用' in reply, reply[:60])
        check('承受力上限这条硬证据仍在（抓不到行情时最不能丢）',
              '19,450' in reply, reply[:200])
        check('筹码逐条输出', all(c in reply for c in
                                 ['免租装修期', '3 年约换', '差额 ¥7,450']), reply[-200:])
        check('明确提示未抓到行情', '未能抓到同区挂牌' in reply, reply[:120])
    finally:
        ag.call_llm, ng.negotiation_brief = orig_llm, orig_brief
    p('')


# ===============================================================
# T8 free_chat_node：LLM 挂 → 离线模板（两分支）
# ===============================================================
def t8():
    p('=== T8 free_chat_node 故障注入：离线回复模板 ===')
    import agent.agent_graph as ag
    orig = ag.call_llm

    async def boom(*a, **k):
        raise Exception('LLM 全挂')

    ag.call_llm = boom
    try:
        # 分支 A：无上下文（首次闲聊）
        st = sample_state(with_result=False, with_context=False)
        out = asyncio.run(ag.free_chat_node(st))
        a = out['messages'][-1]['content']
        check('无上下文 → 引导式离线模板',
              '址南针' in a and '暂不可用' in a, a[:50])

        # 分支 B：有上下文（已做过分析）
        st2 = sample_state(with_context=True)
        out2 = asyncio.run(ag.free_chat_node(st2))
        b = out2['messages'][-1]['content']
        check('有上下文 → 说明服务暂不可用且可继续问',
              '暂不可用' in b, b[:50])
        check('降级时仍返回合法 state（phase=chat）', out2.get('phase') == 'chat', str(out2.get('phase')))
    finally:
        ag.call_llm = orig
    p('')


# ===============================================================
# T9 VLM 时限不变式 + 两条路径共用常量
# ===============================================================
def t9():
    p('=== T9 VLM 时限不变式 + 两条调用路径一致性 ===')
    import agent.vision as vis
    check('VLM_PER_MODEL_TIMEOUT == 60', vis.VLM_PER_MODEL_TIMEOUT == 60,
          str(vis.VLM_PER_MODEL_TIMEOUT))
    check('VLM_TOTAL_BUDGET == 75', vis.VLM_TOTAL_BUDGET == 75, str(vis.VLM_TOTAL_BUDGET))
    check('不变式：2×单模型超时 > 总预算（否则包裹形同虚设）',
          vis.VLM_PER_MODEL_TIMEOUT * 2 > vis.VLM_TOTAL_BUDGET,
          f'{vis.VLM_PER_MODEL_TIMEOUT}×2 vs {vis.VLM_TOTAL_BUDGET}')

    # 结构守卫：两条路径都必须引用 VLM_TOTAL_BUDGET（防"手动上传又漏包裹"回归）
    ui_src = (ROOT / 'src' / 'ui' / 'app_chainlit.py').read_text(encoding='utf-8')
    gp_src = (ROOT / 'src' / 'agent' / 'agent_graph.py').read_text(encoding='utf-8')
    check('UI 手动上传路径引用 VLM_TOTAL_BUDGET', 'VLM_TOTAL_BUDGET' in ui_src)
    check('自动看铺路径引用 VLM_TOTAL_BUDGET', 'VLM_TOTAL_BUDGET' in gp_src)
    check('UI 手动上传路径确有 wait_for 包裹', 'asyncio.wait_for' in ui_src)
    check('UI 手动上传路径有超时分支', 'except asyncio.TimeoutError' in ui_src)

    # 无 KEY 时必须抛（调用方靠它降级，而不是返回假数据）
    orig = vis.LLM_ARK_API_KEY
    vis.LLM_ARK_API_KEY = ''
    try:
        raised = False
        try:
            vis.analyze_storefront(b'\x00' * 10, 'image/jpeg')
        except Exception as e:
            raised = 'API KEY' in str(e)
        check('未配置 KEY 时抛异常（供调用方降级，不返回假数据）', raised)
    finally:
        vis.LLM_ARK_API_KEY = orig
    p('')


def main():
    p('=== verify_degrade_fallback —— 降级策略故障注入回归 ===')
    p('零真实 API / 零网络；用 monkeypatch 逐层打断主链，验证兜底真的发生。')
    p('')
    for fn in (t1, t2, t3, t4, t5, t6, t7, t8, t9):
        fn()
    p('=' * 60)
    if FAIL:
        p(f'FAILED = {len(FAIL)}')
        for f in FAIL:
            p(f'  x {f}')
    else:
        p('全部 PASS')
    OUT.write_text('\n'.join(L), encoding='utf-8')
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
