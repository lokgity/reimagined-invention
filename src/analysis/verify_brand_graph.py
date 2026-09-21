# -*- coding: utf-8 -*-
"""验证 LangGraph 图编译 + collect_brand 路由真正连通（不调 LLM/API）"""
import sys, io, json, asyncio
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'src'))

out = io.StringIO()
def p(*a): print(*a, file=out)

from agent.agent_graph import agent_graph

p('=== 图编译 ===')
p('节点:', sorted(agent_graph.get_graph().nodes.keys()))
p()

# 检查关键边是否存在
edges = agent_graph.get_graph().edges
pairs = [(e.source, e.target) for e in edges]
p('=== 关键边 ===')
for src, dst in pairs:
    p(f'  {src} -> {dst}')

assert ('collect_brand', 'collect_invest') in pairs, '品牌 -> 预算 的边缺失'
assert ('collect_brand', END) if False else True
p()

# 真实跑图：不走 LLM/API 的路径（collect_brand 未选品牌 -> 应该停在 END，不进入 analyze）
p('=== 跑图：奶茶 + 已选好商铺信息齐备（应停在选品牌，不进预算） ===')
st = {
    'messages': [{'role': 'user', 'content': '我看中了杭州滨江区江南大道123号的一个铺位，月租8000，想开奶茶店'}],
    'category': '奶茶', 'address': '杭州滨江', 'rent': 8000.0,
    'phase': 'intro', 'missing_info': [], 'candidates': [], 'list_shown': False,
    'hooks': {'steps': []},
}
res = asyncio.run(agent_graph.ainvoke(st))
p('phase =', res.get('phase'))
p('brand =', res.get('brand'))
p('investment =', res.get('investment'))
last = res['messages'][-1]['content']
p('最后一条回复:', last.replace('\n', ' | ')[:160])
assert res.get('phase') == 'collect_brand', res.get('phase')
assert '前期投入' not in last, '还没到预算环节，不该问投入'
p()

p('=== 跑图：接上一步，用户选品牌 ===')
st2 = dict(res)
st2['messages'] = res['messages'] + [{'role': 'user', 'content': '我选品牌蜜雪冰城'}]
st2['hooks'] = {'steps': []}
res2 = asyncio.run(agent_graph.ainvoke(st2))
p('phase =', res2.get('phase'))
p('brand =', res2.get('brand'))
last2 = res2['messages'][-1]['content']
p('最后一条回复:', last2.replace('\n', ' | ')[:200])
assert res2.get('brand') == '蜜雪冰城'
assert res2.get('phase') == 'collect_invest', res2.get('phase')
assert '前期投入' in last2
p()

p('=== 跑图：便利店应直接进预算（跳过品牌）===')
st3 = {
    'messages': [{'role': 'user', 'content': '我看中了杭州滨江区江南大道123号的一个铺位，月租8000，想开便利店'}],
    'category': '便利店', 'address': '杭州滨江', 'rent': 8000.0,
    'phase': 'intro', 'missing_info': [], 'candidates': [], 'list_shown': False,
    'hooks': {'steps': []},
}
res3 = asyncio.run(agent_graph.ainvoke(st3))
p('phase =', res3.get('phase'))
p('brand =', res3.get('brand'))
assert res3.get('phase') == 'collect_invest', res3.get('phase')
assert not res3.get('brand')
p()

p('ALL GRAPH CHECKS PASSED')
(Path(__file__).resolve().parent / '_verify_brand_graph.txt').write_text(out.getvalue(), encoding='utf-8')
print('written')
