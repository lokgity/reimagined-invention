# -*- coding: utf-8 -*-
"""真实应用路径冒烟：competitor_brief（带 fetch_meta，ok=True）
—— 这是刚发现的 NameError 隐患的唯一触发路径，必须有覆盖。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / '.pylibs'))

L = []
FAIL = []


def p(*a):
    s = ' '.join(str(x) for x in a)
    L.append(s)


def check(name, cond, detail=''):
    L.append(f'  {"PASS" if cond else "FAIL"}  {name}' + (f'  |  {detail}' if detail else ''))
    if not cond:
        FAIL.append(name)


from engine.competitor_insight import competitor_brief, analyze_competitors
from data.fetch_poi import reset_api_call_count, get_api_call_count

p('=== S1 competitor_brief 真实路径（ok=True，会走 _provenance 的实时分支）===')
reset_api_call_count()
a, txt = competitor_brief(121.5517, 29.8742, '奶茶', brand='蜜雪冰城')
p(f'  API 调用={get_api_call_count()}  返回 insight={"有" if a else "无"}')
check('competitor_brief 不抛异常且返回 insight', a is not None, 'None')
check('数据来源标为缓存（上一步复现性验证已写入缓存）',
      (a or {}).get('数据来源') in ('缓存', '实时'), str((a or {}).get('数据来源')))
check('取证时间不为空', bool((a or {}).get('取证时间')), str((a or {}).get('取证时间')))
check('数据局限里带上了取证说明',
      '取证时间' in ((a or {}).get('数据局限') or ''),
      str((a or {}).get('数据局限'))[:70])
p(f'  \\n--- 摘要前 6 行 ---')
for line in (txt or '').split('\n')[:6]:
    p('    ' + line)

p('\n=== S2 命中缓存 → 不再消耗 API ===')
reset_api_call_count()
a2, _ = competitor_brief(121.5517, 29.8742, '奶茶', brand='蜜雪冰城')
check('二次 competitor_brief 0 次 API', get_api_call_count() == 0,
      f'{get_api_call_count()} 次')
check('二次样本数一致', (a or {}).get('样本数') == (a2 or {}).get('样本数'),
      f'{(a or {}).get("样本数")} vs {(a2 or {}).get("样本数")}')

p('\n=== S3 直接喂 POI（无 fetch_meta）不应谎称"取数失败" ===')
pois = [{'name': '蜜雪A', 'brand': '蜜雪冰城', 'cost': 7, 'rating': 4.0, 'distance': 200,
         'S': 1.0, 'opentime': '', 'groupbuy': 0, 'discount': 0, 'favorite': 0,
         'photos': 0, 'tags': [], 'keytag': ''} for _ in range(2)]
x = analyze_competitors(pois, '奶茶', '蜜雪冰城')
check('无 fetch_meta 时标为"未标注"', x.get('数据来源') == '未标注', str(x.get('数据来源')))
check('无 fetch_meta 时不说"未取到数据"',
      '未取到数据' not in (x.get('数据局限') or ''), str(x.get('数据局限'))[:60])

p('\n=== S4 取数失败路径的文案（competitor_brief）===')
import engine.competitor_insight as ci
real = ci.fetch_around_raw
try:
    ci.fetch_around_raw = lambda *a, **k: (
        [], {'ok': False, 'info': 'CUQPS_HAS_EXCEEDED_THE_LIMIT', 'infocode': '10021',
             'quota': False, 'err': None, 'tries': 3, 'count': None})
    ci.clear_cache()
    a3, t3 = competitor_brief(121.5517, 29.8742, '奶茶', brand='蜜雪冰城')
    p(f'  insight={a3}  摘要={t3[:90]}')
    check('取数失败时 insight 为 None', a3 is None)
    check('取数失败时摘要说清是限流而非"没有竞品"',
          ('限流' in t3) and ('不代表该商圈没有竞品' in t3), t3[:80])
    ci.fetch_around_raw = lambda *a, **k: (
        [], {'ok': False, 'info': 'DAILY_QUERY_OVER_LIMIT', 'infocode': '10003',
             'quota': True, 'err': None, 'tries': 1, 'count': None})
    ci.clear_cache()
    a4, t4 = competitor_brief(121.5517, 29.8742, '奶茶')
    check('日配额时摘要标为"今日配额已用尽"', '今日配额已用尽' in t4, t4[:70])
finally:
    ci.fetch_around_raw = real
    ci.clear_cache()

p('\n' + '=' * 60)
p(('共 %d 项 FAIL：' % len(FAIL)) + ' / '.join(FAIL) if FAIL else '全部 PASS')
p('=' * 60)

(Path(__file__).resolve().parent / '_verify_brief_smoke.txt').write_text('\n'.join(L), encoding='utf-8')
sys.exit(1 if FAIL else 0)
