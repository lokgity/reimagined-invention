# -*- coding: utf-8 -*-
"""验证：奶茶品牌选择卡片流程（Phase 2）
检查项：
  T1  奶茶 + 地区 → 只问品类/地区，不出现品牌问题（还在找商铺阶段）
  T2  选好商铺（有具体铺子）→ 先问品牌、后问预算（顺序）
  T3  品牌卡片负载结构（kind=brands，含自创品牌逃生项，TIER 标注；
      v7 口径下 TIER1 = 瑞幸/茶百道/乐乐茶，蜜雪已降 TIER2）
  T4  用户选品牌 → brand 入库 + phase=collect_invest + 文案含投入问题
  T5  非奶茶品类（便利店/早餐/甜品）跳过品牌环节
  T6  自创品牌选项可用
  T7  '我选品牌N' 序号式选择可用
"""
import sys, io, json, asyncio
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'src'))

out = io.StringIO()
def p(*a):
    print(*a, file=out)

from agent.agent_graph import (build_brand_payload, _parse_brand_choice,
                               collect_brand_node, collect_info_node,
                               select_shop_node, _needs_brand_step)

# ---------- T3: 负载结构 ----------
pl = build_brand_payload()
p('=== T3 品牌卡片负载 ===')
p('kind =', pl['kind'])
p('title =', pl['title'])
p('cards =', len(pl['cards']))
p('前 3 张:')
for c in pl['cards'][:3]:
    p('   ', c['i'], c['brand'], 'tier=', c['tier'], 'uplift=', c['uplift'],
      'ci=', c['ci'], 'n=', c['n'], 'invest_ref=', c['invest_ref'])
p('最后一张（逃生项）:')
last = pl['cards'][-1]
p('   ', last['i'], last['brand'], 'self_created=', last.get('self_created'),
  'uplift=', last['uplift'], 'tier=', last['tier'])
# 断言
assert pl['kind'] == 'brands'
assert last['brand'] == '自创品牌' and last.get('self_created') is True
# v7（2026-09-18 品牌盲残差口径）：蜜雪消双算后由 TIER1 降 TIER2（1.1903→1.0018），
# 不能再断言它 TIER1；改为钉死三个 TIER1 + 蜜雪仍在卡片里且量级正确。
# ⚠️ 2026-09-21 切 v8（步行路网）：TIER1 成员**换人**了 ——
#    v7 {乐乐茶, 瑞幸, 茶百道} → v8 **{奈雪, 春莱, 瑞幸}**（sorted 后 ['春莱','奈雪','瑞幸']）。
#    ⚠️ 奈雪(n=10)/春莱(n=11) 是被**抬进来**的：两者 CI 上界都恰好压在 clamp 天花板
#       1.2500（CI 被护栏截断，信息量有限）。这是"不加规则"的代价，已如实写在
#       brands.py 的 v8 注记里；要修应改 TIER1 判据（要求 CI 不被 clamp 截断），
#       属规则变更，需单独裁决 —— 门禁**不替这个决定**。
_t1 = sorted(c['brand'] for c in pl['cards'] if c['tier'] == 'TIER1')
assert _t1 == ['奈雪', '春莱', '瑞幸'], _t1   # sorted() 按 Unicode 码点：奈<春<瑞
_mx = next(c for c in pl['cards'] if c['brand'] == '蜜雪冰城')
assert _mx['tier'] == 'TIER2' and abs(_mx['uplift'] - 1.0000) < 5e-5, _mx
# 每张卡片都带 uplift/tier/i
for c in pl['cards']:
    assert 'i' in c and 'brand' in c and 'tier' in c, c

# ---------- 解析器 ----------
p('\n=== 解析器 ===')
cases = ['我选品牌蜜雪冰城', '我选品牌1', '品牌3', '蜜雪冰城', '蜜雪', 'coco',
         '自创品牌', '我不加盟，自己起名', '喜茶', '第2个品牌', '随便什么都行']
for t in cases:
    p(f'  {t!r:24} -> {_parse_brand_choice(t, allow_index_only=True)!r}')

# ---------- T2: 顺序（有具体铺子 → 先品牌）----------
p('\n=== T2 顺序：已有具体商铺（奶茶）===')
st = {
    'messages': [{'role': 'user', 'content': '我在杭州滨江有家铺子，月租8000，想开奶茶店'}],
    'category': '奶茶', 'address': '杭州滨江', 'rent': 8000.0, 'phase': 'have_shop',
}
r = asyncio.run(collect_info_node(st))
p('phase =', r.get('phase'), '（期望 collect_brand，而非 collect_invest）')
assert r.get('phase') == 'collect_brand', r.get('phase')
p('是否推送预算问题:', '前期投入' in str(r.get('messages', [{}])[-1].get('content', '')))

# ---------- T4: 选品牌 → 入库 + 进入预算 ----------
p('\n=== T4 选品牌后 ===')
st2 = dict(st)
st2['messages'] = st2['messages'] + [{'role': 'user', 'content': '我选品牌蜜雪冰城'}]
st2['phase'] = 'collect_brand'
r2 = asyncio.run(collect_brand_node(st2))
p('brand =', r2.get('brand'))
p('phase =', r2.get('phase'))
content = r2['messages'][-1]['content']
p('文案片段 =', content.replace('\n', ' | ')[:150])
assert r2.get('brand') == '蜜雪冰城', r2.get('brand')
assert r2.get('phase') == 'collect_invest', r2.get('phase')
assert '前期投入' in content, '必须接着问预算'

# 未选品牌 → 停在 collect_brand
st2b = dict(st); st2b['messages'] = st2b['messages'] + [{'role': 'user', 'content': '嗯'}]
st2b['phase'] = 'collect_brand'
r2b = asyncio.run(collect_brand_node(st2b))
p('未选品牌时 phase =', r2b.get('phase'), '| brand =', r2b.get('brand'))
assert r2b.get('phase') == 'collect_brand'

# ---------- T7: 序号式 ----------
st3 = dict(st); st3['messages'] = st3['messages'] + [{'role': 'user', 'content': '我选品牌2'}]
st3['phase'] = 'collect_brand'
r3 = asyncio.run(collect_brand_node(st3))
p('\n=== T7 序号式 "我选品牌2" -> ', r3.get('brand'))
assert r3.get('brand') == pl['cards'][1]['brand']
p('品牌2 应为:', pl['cards'][1]['brand'])

# ---------- T6: 自创品牌 ----------
st4 = dict(st); st4['messages'] = st4['messages'] + [{'role': 'user', 'content': '自创品牌'}]
st4['phase'] = 'collect_brand'
r4 = asyncio.run(collect_brand_node(st4))
p('\n=== T6 自创品牌 ->', r4.get('brand'), '| phase =', r4.get('phase'))
assert r4.get('brand') == '自创品牌'

# ---------- T5: 非奶茶跳过 ----------
p('\n=== T5 非奶茶品类是否跳过品牌环节 ===')
for cat in ['便利店', '早餐', '甜品', '奶茶']:
    s = {'category': cat, 'address': '杭州滨江', 'rent': 8000.0, 'phase': 'have_shop',
         'messages': [{'role': 'user', 'content': f'杭州滨江的{cat}店'}]}
    need = _needs_brand_step(s)
    rr = asyncio.run(collect_info_node(s))
    p(f'  {cat:5} needs_brand={need!s:5} -> phase={rr.get("phase")}')
    if cat == '奶茶':
        assert need is True and rr.get('phase') == 'collect_brand'
    else:
        assert need is False and rr.get('phase') == 'collect_invest', (cat, rr.get('phase'))

# 已有品牌则不再问
s5 = {'category': '奶茶', 'address': '杭州滨江', 'rent': 8000.0, 'brand': '古茗',
      'phase': 'have_shop', 'messages': [{'role': 'user', 'content': '杭州滨江奶茶店'}]}
rr5 = asyncio.run(collect_info_node(s5))
p('  已定品牌 -> needs_brand=', _needs_brand_step(s5), 'phase=', rr5.get('phase'))
assert _needs_brand_step(s5) is False and rr5.get('phase') == 'collect_invest'

# ---------- T1: 卖场阶段不该问品牌 ----------
p('\n=== T1 找商铺阶段（无具体铺子）不问品牌 ===')
s6 = {'category': '奶茶', 'address': '杭州滨江', 'phase': 'no_shop',
      'messages': [{'role': 'user', 'content': '杭州滨江开奶茶店'}]}
rr6 = asyncio.run(collect_info_node(s6))
p('phase =', rr6.get('phase'), '（期望 search_rental）')
assert rr6.get('phase') == 'search_rental'

# ---------- select_shop_node 也走品牌优先 ----------
p('\n=== T2b select_shop 选中候选后 -> 先问品牌 ===')
s7 = {
    'messages': [{'role': 'user', 'content': '选1'}],
    'category': '奶茶', 'address': '杭州滨江', 'phase': 'select_shop',
    'candidates': [{'name': '滨江宝龙城奶茶铺', 'address': '杭州滨江宝龙城', 'lng': 120.2,
                    'lat': 30.2, 'source': '58', 'area': 30, 'price': 9000, 'precise': True}],
}
rr7 = asyncio.run(select_shop_node(s7))
p('phase =', rr7.get('phase'), '| brand =', rr7.get('brand'))
c7 = rr7['messages'][-1]['content']
p('文案末尾 =', c7[-90:].replace('\n', ' | '))
assert rr7.get('phase') == 'collect_brand'
assert '品牌' in c7

# 非奶茶选中候选 -> 直接预算
s8 = dict(s7); s8['category'] = '便利店'
rr8 = asyncio.run(select_shop_node(s8))
p('非奶茶 phase =', rr8.get('phase'))
assert rr8.get('phase') == 'collect_invest'

p('\n' + '=' * 46)
p('ALL CHECKS PASSED')

(Path(__file__).resolve().parent / '_verify_brand_card.txt').write_text(out.getvalue(), encoding='utf-8')
print('written')
