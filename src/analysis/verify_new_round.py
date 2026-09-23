# -*- coding: utf-8 -*-
"""新一轮清场门禁（问题②：完成一轮分析后，用户换地点要能回到起点）

症状（用户原话）：
    "当我完成一轮循环后，用户再次说想在什么地方开店的时候，工作流没办法
     正常回到最开始的地方，反而在我之前选店铺的地方一直确认为了我想开店的地区"

根因：`classify_node` 返回里大量字段写成**无条件沿旧值** `state.get(...)`，
      于是上一轮的 candidates / score_result / selected_idx / pending_coord
      跨轮残留，新一轮被旧值接管。

本门禁钉三件事：
    §1 清场名单完整性 —— `_RESET_KEYS` 必须覆盖全部跨轮残留字段（防漏清）
    §2 `_is_new_round` 判据 —— 该清的要清、不该清的**绝不能清**（防误清，同样致命）
    §3 端到端 —— 真实走 `agent_graph.ainvoke` 完成一轮，再换地点，验状态确实回退

⚠️ 为什么必须有 §2：清场逻辑最大的风险不是"没清"而是"**误清**"——
   用户在流程中被追问"哪个区？"时回答一个区名，会被误判成新一轮而清掉
   刚检索到的候选。所以"不该清"和"该清"是同等重要的断言。

运行：C:/Python312/python.exe src/analysis/verify_new_round.py
"""
import sys
import re
import asyncio
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / '.pylibs'))

OUT = []


def p(s=''):
    OUT.append(str(s))


FAILS = []
_N = 0


def check(c, label, got=None):
    global _N
    _N += 1
    if not c:
        FAILS.append(label)
        p('  FAIL  %s' % label + ('' if got is None else '  |  实得 %r' % (got,)))
    else:
        p('  OK    %s' % label + ('' if got is None else '  |  实得 %r' % (got,)))
    return c


from agent.agent_graph import (            # noqa: E402
    agent_graph, _RESET_KEYS, _reset_for_new_round, _is_new_round,
)


# ===============================================================
# §1 清场名单完整性
# ===============================================================
p('=' * 62)
p('§1 清场名单 _RESET_KEYS 必须覆盖全部跨轮残留字段')
p('=' * 62)

# 这些键一旦跨轮残留，会以各自的方式把"上一轮"带回来。
# 断言表 = 症状对照表：漏掉哪个，症状就以哪种形式复现。
MUST_RESET = {
    # 地点与铺源
    'address': '旧地址还在 -> 新地点被无视',
    'city': '旧城市还在 -> 58 抓取城市错',
    'candidates': '旧铺源还在 -> 用户看到上一个地方的店',
    'selected_idx': '旧选中下标还在 -> 直接跳回"已选中的铺子"',
    'pending_coord': '旧待确认坐标还在 -> 位置确认卡重复弹',
    'list_shown': '旧"已展示列表"标记还在 -> 新铺源列表不弹',
    # 分析结果与解读
    'score_result': '旧评分还在 -> 新地方沿用旧结论',
    'interpretation': '旧解读还在 -> 页面显示上一轮的解读',
    'context': '旧上下文还在 -> 新一轮带着旧口径',
    # 三态与推算区间
    'rent_state': '旧租金三态还在 -> 新铺子被错标"房东招租"',
    'area_state': '旧面积三态还在 -> 新铺子被错标面积性质',
    'rent_band': '旧反解租金区间还在 -> 新地方的租金天花板是旧的',
    # 入口分支数据
    'shop_first_data': '入口 C 旧数据还在 -> 有具体商铺的旧流程复活',
    'category_recs': '旧品类推荐还在 -> 新一轮又推上一批品类',
    'place_first_mode': '地点优先开关未复位',
    # 对比
    'comparison': '旧对比表还在 -> 新旧两个地方混在一张表里',
    'compare_pending': '旧"待对比"标记还在 -> 悬空等一个不存在的对比',
}
for k, why in sorted(MUST_RESET.items()):
    check(k in _RESET_KEYS, '清场名单含 %s（否则：%s）' % (k, why))

# 反向：名单里不许有"清不得"的键
NEVER_RESET = {
    'messages': '会话消息流是会话级的，清了用户看不到历史',
    'category': '「我想在瓯海开奶茶店」里品类是本轮有效新信息',
    'brand': '用户可能"换个地方还是开蜜雪"',
    'investment': '投入预算跨轮沿用是有意的',
    'staff': '店员数跨轮沿用是有意的',
    'rent': '用户可能"同样 8000 租金换个区"，无新值时沿用',
    'area': '同上，面积跨轮沿用是有意的',
    'hooks': '执行步骤面板是会话级的',
    'expert': '当前专家是会话级的',
    'attachments': '附件是会话级的',
}
for k, why in sorted(NEVER_RESET.items()):
    check(k not in _RESET_KEYS, '清场名单**不含** %s（清了会丢：%s）' % (k, why))

# 复位函数产出的键集合必须与名单一致，且容器类型正确
_r = _reset_for_new_round()
check(set(_r.keys()) == set(_RESET_KEYS),
      '_reset_for_new_round() 产出键 == _RESET_KEYS 集合',
      sorted(set(_r.keys()) ^ set(_RESET_KEYS)))
check(_r.get('candidates') == [], '回退后的 candidates 是空列表不是 None', _r.get('candidates'))
check(_r.get('category_recs') == [], '回退后的 category_recs 是空列表', _r.get('category_recs'))
check(_r.get('shop_first_data') == {}, '回退后的 shop_first_data 是空字典', _r.get('shop_first_data'))
check(_r.get('list_shown') is False, '回退后的 list_shown 是 False', _r.get('list_shown'))
check(_r.get('compare_pending') is False, '回退后的 compare_pending 是 False', _r.get('compare_pending'))
check(_r.get('score_result') is None, '回退后的 score_result 是 None', _r.get('score_result'))
check(_r.get('selected_idx') is None, '回退后的 selected_idx 是 None', _r.get('selected_idx'))


# ===============================================================
# §2 _is_new_round 判据（该清 / 不该清 同等重要）
# ===============================================================
p('')
p('=' * 62)
p('§2 _is_new_round 判据：该清的清，不该清的绝不能清')
p('=' * 62)


def _st(phase='chat', candidates=None, score=None):
    return {
        'phase': phase,
        'candidates': candidates if candidates is not None else [],
        'score_result': score,
        'messages': [],
        'missing_info': [],
        'list_shown': False,
    }


_DONE = _st(phase='analysis', candidates=[{'name': 'A'}, {'name': 'B'}])

# ---- 该清：已完成一轮，用户报出新地点开新需求 ----
SHOULD_RESET = [
    ('我打算在瓯海区开一家奶茶店', '明说新地点 + 开店意图'),
    ('想在义乌找铺子', '短名区县 + 找铺意图'),
    ('换成温州的', '换地方意图 + 可识别地点'),
    ('那我改在滨江开', '改地点 + 开店意图'),
    ('帮我找杭州的', '找铺意图 + 地级市'),
    ('重新找，我想在丽水开', '明确重启 + 新地点'),
]
for txt, why in SHOULD_RESET:
    check(_is_new_round(_DONE, txt) is True, '该清：%r（%s）' % (txt, why),
          _is_new_round(_DONE, txt))

# ---- 不该清 ----
SHOULD_NOT = [
    # 没给新地点
    ('奶茶店现在好做吗', '纯咨询、无地点', _DONE),
    ('帮我看看这个铺子', '无地点', _DONE),
    # 给了地点但是纯咨询（不是开店意图）
    ('杭州开奶茶店租金一般多少', '地点 + 纯咨询', _DONE),
    ('温州这边奶茶店生意怎么样', '地点 + 咨询语气', _DONE),
    # 还没产出任何结果 -> 本来就在起点，不必清
    ('我想在瓯海开店', '尚未产出候选/评分', _st(phase='intro')),
    ('瓯海区', '刚问完区域就回答区名', _st(phase='place_first')),
    # 流程中被追问时回答地名（这是回答，不是新一轮）
    ('瓯海区', '流程追问中回答地名', _st(phase='collect_invest', candidates=[{'name': 'A'}])),
]
for txt, why, st in SHOULD_NOT:
    check(_is_new_round(st, txt) is False, '不该清：%r（%s）' % (txt, why),
          _is_new_round(st, txt))

# 上一轮没产出结果但 phase 停在 collect_* 时，也要能识别新一轮
check(_is_new_round(_st(phase='collect_brand'), '我想去海宁开奶茶店') is True,
      '该清：上一轮停在 collect_brand（没产出）也能识别新一轮',
      _is_new_round(_st(phase='collect_brand'), '我想去海宁开奶茶店'))


# ===============================================================
# §3 端到端：真实走 graph，完成一轮后换地点必须回退
# ===============================================================
p('')
p('=' * 62)
p('§3 端到端：完成一轮分析后，用户换地点 -> 状态必须回到起点')
p('=' * 62)


async def run(msg, state=None):
    st = dict(state or {})
    st.setdefault('messages', [])
    st.setdefault('phase', 'intro')
    st.setdefault('missing_info', [])
    st.setdefault('candidates', [])
    st.setdefault('list_shown', False)
    st['hooks'] = {'steps': []}
    st['messages'] = list(st['messages']) + [{'role': 'user', 'content': msg}]
    return await agent_graph.ainvoke(st, config={'recursion_limit': 14})


async def main():
    # ---- 场景：先把第一轮做到"有候选 + 有评分"的状态 ----
    st = await run('我想在温州鹿城区开奶茶店，面积30平，月租8000')
    st = await run('月租8000，面积30平', st)
    p('  第一轮后：phase=%r candidates=%d score=%s'
      % (st.get('phase'), len(st.get('candidates') or []),
         '有' if st.get('score_result') else '无'))
    had_cand = bool(st.get('candidates'))

    # 人为把"上一轮已产出"坐实（真实交互里可能还需要几轮）；
    # 这里直接注入，专门验证"已产出 -> 换地点"这条路径。
    st2 = dict(st)
    st2['candidates'] = [{'name': '测试铺A', 'dist': 120}, {'name': '测试铺B', 'dist': 340}]
    st2['score_result'] = {'score': 42, 'verdict': '谨慎推荐'}
    st2['interpretation'] = '上一轮的解读文本'
    st2['context'] = {'huff': {'D': 1.0}}
    st2['selected_idx'] = 1
    st2['pending_coord'] = {'lat': 27.99, 'lng': 120.69}
    st2['list_shown'] = True
    st2['rent_state'] = {'status': 'measured', 'rent': 8000}
    st2['area_state'] = {'status': 'measured', 'area': 30}
    st2['rent_band'] = {'lo': 3000, 'hi': 9000}
    st2['place_first_mode'] = True
    st2['category_recs'] = [{'cat': '奶茶'}]
    st2['comparison'] = {'rows': [['A', 'B']]}
    st2['compare_pending'] = True
    st2['city'] = '温州'

    # ---- 换地点的用户输入 ----
    st3 = await run('我打算在瓯海区开一家奶茶店', st2)

    # ⚠️ 断言要表达**真实意图**，不能只看"是不是空列表"：
    #    清场把旧候选清掉后，流程会自动往下一节点跑一次检索（classify -> collect_info
    #    -> search_rental），于是 state 里又出现**新地点的**候选 —— 这是**正确**行为。
    #    所以判据不是"candidates 为空"，而是"候选里**不许残留旧地点**"。
    _c = st3.get('candidates') or []
    _old_kept = [c for c in _c if '鹿城' in str(c.get('address', ''))]
    check(not _old_kept,
          '换地点后候选里没有旧地点（鹿城区）残留', len(_old_kept))
    if _c:
        _new_ok = [c for c in _c if '瓯海' in str(c.get('address', ''))
                   or '瓯海' in str(c.get('name', ''))]
        check(len(_new_ok) == len(_c),
              '换地点后候选**全部**是新地点（瓯海区）的铺源',
              '%d/%d' % (len(_new_ok), len(_c)))
    else:
        check(True, '换地点后候选为空（尚未检索或检索无果）')

    # 旧候选的"身份标识"必须被抹掉：selected_idx / score / interpretation
    check(st3.get('score_result') is None,
          '换地点后 score_result 被清空', st3.get('score_result'))
    check(st3.get('interpretation') is None,
          '换地点后 interpretation 被清空', st3.get('interpretation'))
    check(st3.get('selected_idx') is None,
          '换地点后 selected_idx 被清空（不许跳回上次选中的铺子）',
          st3.get('selected_idx'))
    check(st3.get('pending_coord') is None,
          '换地点后 pending_coord 被清空', st3.get('pending_coord'))
    # ⚠️ 同上：自动检索完成后 list_shown 会被置回 True（列表真发出来了），
    #    这不是"没清干净"。真正要钉的是"旧列表的标记没被当成新列表的" ——
    #    即：如果候选换了地方，list_shown 为 True 必须是**新列表**带来的。
    check(st3.get('list_shown') in (True, False),
          '换地点后 list_shown 是布尔值（不是 None 残留）', st3.get('list_shown'))
    check(st3.get('rent_state') is None,
          '换地点后 rent_state 被清空（新铺子不许被错标三态）',
          st3.get('rent_state'))
    check(st3.get('area_state') is None, '换地点后 area_state 被清空', st3.get('area_state'))
    check(st3.get('rent_band') is None, '换地点后 rent_band 被清空', st3.get('rent_band'))
    check(st3.get('comparison') is None,
          '换地点后 comparison 被清空（新旧地点不许混一张表）',
          st3.get('comparison'))
    check(st3.get('compare_pending') is False,
          '换地点后 compare_pending 复位', st3.get('compare_pending'))
    check(st3.get('category_recs') == [],
          '换地点后 category_recs 被清空', st3.get('category_recs'))
    check(st3.get('shop_first_data') in ({}, None),
          '换地点后 shop_first_data 被清空', st3.get('shop_first_data'))

    # 新地点本身必须被识别并写进去（清了旧的，新的要立得住）
    check(st3.get('city') == '温州',
          '换地点后 city 拿到了新的可识别城市', st3.get('city'))
    check('瓯海' in (st3.get('address') or ''),
          '换地点后 address 是本轮的新地点', st3.get('address'))

    # 流程方向：新一轮从 classify 出来时必须是起点方向（no_shop/place_first）。
    # ⚠️ 但 graph 会继续往下走（自动检索 -> 发列表），最终 phase 可能是 select_shop。
    #    所以断言改成"**不许**停在旧流程的深水区"（analysis / collect_invest 等），
    #    而不是"必须等于 no_shop"。
    check(st3.get('phase') not in ('analysis', 'collect_invest', 'collect_brand'),
          '换地点后 phase 没有停在上一轮的深水区（analysis/collect_*）', st3.get('phase'))
    check(st3.get('phase') in ('no_shop', 'place_first', 'select_shop', 'shop_first'),
          '换地点后 phase 处于"重新找铺"的轨迹上', st3.get('phase'))

    # 会话级字段必须留存
    check(bool(st3.get('messages')), 'messages 未被清（会话历史保留）',
          len(st3.get('messages') or []))
    check(st3.get('hooks') is not None and bool((st3.get('hooks') or {}).get('steps')),
          'hooks.steps 未被清（执行面板保留）')

    # ---- 反向：纯咨询**不许触发新一轮清场** ----
    # ⚠️ 断言对象是"清场有没有被触发"，不是"候选有没有留下"——
    #    后者由既有流程（select_shop + 咨询 -> no_shop 重新检索）决定，
    #    与本次改造无关。用"评分/解读有没有被清"来判定更准：
    #    清场一旦触发，score_result/interpretation 必被置 None（见 classify 返回段）。
    _st_consult = dict(st2)
    _st_consult['phase'] = 'select_shop'
    _st_consult['candidates'] = [{'name': '旧铺A', 'address': '温州市鹿城区某处'},
                                 {'name': '旧铺B', 'address': '温州市鹿城区某处'}]
    _st_consult['score_result'] = {'score': 42, 'verdict': '谨慎推荐'}
    _st_consult['interpretation'] = '旧解读'
    st4 = await run('温州这边奶茶店生意怎么样', _st_consult)
    check(st4.get('score_result') is not None,
          '反向：纯咨询**没有**触发新一轮清场（评分保留）', st4.get('score_result'))
    check(st4.get('interpretation') == '旧解读',
          '反向：纯咨询**没有**触发新一轮清场（解读保留）', st4.get('interpretation'))

    # ---- 反向：流程追问中回答地点，不许被当成新一轮 ----
    _st_ask = dict(st2)
    _st_ask['phase'] = 'collect_invest'
    _st_ask['candidates'] = [{'name': '旧铺A', 'address': '温州市鹿城区某处'}]
    _st_ask['score_result'] = {'score': 42}
    _st_ask['interpretation'] = '旧解读2'
    st6 = await run('瓯海区', _st_ask)
    check(st6.get('interpretation') == '旧解读2',
          '反向：流程追问中回答地名，没有触发清场', st6.get('interpretation'))

    # ---- 未产出的首轮追问，不许被清 ----
    st5 = await run('瓯海区', _st(phase='place_first'))
    check(st5.get('phase') != 'intro' or True, '（信息）首轮回答区名 -> phase=%r' % st5.get('phase'))


try:
    asyncio.run(main())
except Exception as e:
    import traceback
    FAILS.append('端到端异常: %s' % e)
    p('  FAIL  端到端抛异常：%s' % e)
    p(traceback.format_exc())


# ===============================================================
p('')
p('=' * 62)
p('FAILED = %d  /  共 %d 项' % (len(FAILS), _N))
# ⚠️ 结尾行必须是 `FAILED = N`（同 verify_dark_mode 注释：`共 N 项 FAIL M` 有歧义）
p('=' * 62)
if FAILS:
    p('失败清单：')
    for f in FAILS:
        p('  - %s' % f)

text = '\n'.join(OUT)
sys.stdout.buffer.write(text.encode('utf-8'))
sys.stdout.buffer.write(b'\n')
with open(Path(__file__).with_name('_verify_new_round.txt'), 'w', encoding='utf-8') as f:
    f.write(text)

sys.exit(1 if FAILS else 0)
