"""端到端回归：复合意图拆分（AI 方向④ 收尾修的缺陷）

背景缺陷：用户一句话问两件事（"加盟蜜雪冰城大概要投多少钱？周边竞品口碑怎么样"），
整句命中竞品意图后被 competitor_node 独占，加盟费那一半没人回答。

修复：free_chat_node 把"专门节点之外的其余疑问"作为 extra_question 传给
competitor_node / negotiate_node，节点补真实参考数据（brands.py 加盟政策、知识库检索）
并要求 LLM 分两段作答、严禁编造。

本脚本跑真实链路（高德 API + 58 行情 + 火山方舟 LLM），断言：
  1. 复合问题被拆出 extra_question，且步骤里出现「复合意图拆分」
  2. 回复同时覆盖两段：加盟费数字（¥370,000 / ¥15,800 来自 brands.py 真实参考）+ 竞品口碑
  3. 单一竞品问题不受影响（extra 为空，无「复合意图拆分」步骤）

用法：cd src && python -m analysis.test_composite_intent

⚠️ 本脚本**构造性地不稳定**（2026-09-15 记录）：它的断言对象是 **LLM 的自由文本**
（回复里要出现"37 万""1.58 万""数据局限"等措辞），同一天两次运行可能一次 PASS 一次 FAIL
（实测：rc=0 / rc=1 都出现过），差异纯粹来自模型措辞而不是链路故障。
因此它**只进网络信息性组，不进离线门禁**（见 `run_regression.py`）。
若要做成稳定门禁，应改为断言"证据包被正确构造 + 模型收到了约束"，
而不是断言模型最终怎么措辞。
"""
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(errors='replace')

from agent.agent_graph import run_agent, _other_questions, _wants_competitor, _wants_negotiate  # noqa: E402

TURNS = [
    '有，看中了宁波天一广场的一个铺子，想开奶茶店，面积30平，月租12000',
    '装修预算20万，2个人运营，加盟蜜雪冰城',
    '加盟蜜雪冰城大概要投多少钱？周边竞品口碑怎么样',
]
COMPOSITE = '加盟费贵不贵？还有竞争对手多不多'
SINGLE = '周边竞品口碑怎么样'


def _route(text):
    """复刻 free_chat_node 的分流判定，返回 (节点名, extra_question)"""
    if _wants_negotiate(text):
        return 'negotiate', _other_questions(text, _wants_negotiate)
    if _wants_competitor(text):
        return 'competitor', _other_questions(text, _wants_competitor)
    return 'free_chat', ''


def check_routing():
    print('=' * 70)
    print('[1] 路由与拆分（纯本地判定，0 次 API）')
    print('=' * 70)
    ok = True
    for text, want_route, want_extra_nonempty in [
        (TURNS[2], 'competitor', True),
        (COMPOSITE, 'competitor', True),
        ('租金能砍到多少？周边竞品口碑怎么样', 'negotiate', True),
        (SINGLE, 'competitor', False),
        ('这附近同行的人均价格多少', 'competitor', False),
        ('宁波天一广场开奶茶店，帮我分析一下', 'free_chat', False),
    ]:
        route, extra = _route(text)
        good = route == want_route and bool(extra) == want_extra_nonempty
        ok &= good
        print(f'  {"PASS" if good else "FAIL"} {text}')
        print(f'       → {route} | extra={extra!r}')
    return ok


async def check_end_to_end():
    print()
    print('=' * 70)
    print('[2] 端到端真实链路（高德 + 58 + 豆包 LLM）')
    print('=' * 70)
    state = None
    for i, msg in enumerate(TURNS, 1):
        state = await run_agent(msg, state)
        reply = state['messages'][-1]['content']
        print(f'\n--- 轮{i} 用户：{msg}')
        for s in state.get('steps', [])[-8:]:
            print(f'    · [{s.get("kind")}] {s.get("name")}: '
                  f'{str(s.get("text") or s.get("output"))[:90]}')
        print(f'    phase={state.get("phase")} | brand={state.get("brand")} '
              f'| total={(state.get("score_result") or {}).get("total")}')
        if i < len(TURNS):
            state['steps'] = []
            print(f'    助手：{reply[:120]}…')

    final = state['messages'][-1]['content']
    steps = state.get('steps', [])
    print(f'\n--- 最终回复（{len(final)} 字）---')
    print(final)

    # ⚠️ 2026-09-15 修脆断言：LLM 常把 37 万写成 "¥370,000"（带千分位逗号）。
    #    原判据只认 '万' / '00,000' / '00000'，恰好漏掉 '370,000' 这种写法
    #    （它含 '70,000' 却不含 '00,000'），于是把"格式差异"误判成"模型没照做"。
    #    统一去掉逗号与空格后再匹配数字。
    def _norm(s):
        return s.replace(',', '').replace('，', '').replace(' ', '')

    fn = _norm(final)

    print('\n' + '=' * 70)
    print('[3] 断言')
    print('=' * 70)
    checks = [
        ('触发复合意图拆分',
         any('复合意图拆分' in str(s.get('name')) for s in steps)),
        ('回答里出现加盟费/前期投入数字（brands.py 真实参考 37 万）',
         ('370000' in fn or ('37' in final and '万' in final))),
        ('回答里出现年品牌费/管理费口径（15,800 或 1.58 万）',
         ('15800' in fn or '1.58' in final or '1.6万' in fn)),
        ('回答里出现竞品口碑真实数据（口碑/评分/人均/HHI 任一）',
         any(k in final for k in ['口碑', '评分', '人均', 'HHI', '连锁'])),
        ('声明了数据局限（点评登录墙 / 高德公开字段 / 未回填 任一）',
         any(k in final for k in ['登录墙', '公开字段', '未回填', '局限', '不可得'])),
        ('没有把团购字段当机会（未出现"团购活跃 0 家=空白"式误读）',
         # ⚠️ 脆断言修正（2026-09-16）：原判据只认"未回填"三字，而 LLM 写的是
         #    "高德平台**已不回填**团购、优惠、收藏数等字段" —— 语义正确却被判 FAIL
         #    （与 2026-09-15 千分位那次同类：对措辞做断言而非对语义）。
         #    现改为两段式：① 禁用"团购=空白机会"的具体误读句式；
         #    ② 一旦提到"团购"，必须同时声明该字段不可得（不锁定单一措辞）。
         (not any(p in _norm(final) for p in [
             '团购活跃0', '团购为0', '团购0家', '团购空白', '团购未被利用',
             '团购数据为0', '团购数0'])
          and ('团购' not in final
               or any(k in final for k in [
                   '未回填', '不回填', '不可用', '无有效', '未纳入', '无法获取',
                   '不提供', '未采集', '不返回', '不再提供', '未获取', '没回填',
                   '未披露', '无数据'])))),
    ]
    ok = True
    for name, passed in checks:
        ok &= bool(passed)
        print(f'  {"PASS" if passed else "FAIL"} {name}')
    return ok


if __name__ == '__main__':
    a = check_routing()
    b = asyncio.run(check_end_to_end())
    print()
    print('=' * 70)
    print(f'总结：路由拆分 {"PASS" if a else "FAIL"} | 端到端 {"PASS" if b else "FAIL"}')
    print('=' * 70)
    sys.exit(0 if (a and b) else 1)
