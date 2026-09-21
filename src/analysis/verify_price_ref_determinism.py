# -*- coding: utf-8 -*-
"""verify_price_ref_determinism.py —— 客单价校正复现性回归
=========================================================
锁三件事：
 1. 同一坐标 + 同一品牌多次调用，结果**逐字段完全一致**（含口径文案）；
 2. 缓存命中后 **0 次高德 API**（用 fetch_poi.API_CALL_COUNT 实测计数）；
 3. 同一坐标换品牌，共享同一份周边 POI 快照 → 也 0 次额外 API。

背景：修前同一输入两次运行的月流水差 2.3 倍。实测根因是高德
CUQPS_HAS_EXCEEDED_THE_LIMIT 被 `status != '1' → return []` 静默吞成
"这一带没有竞品"，且结果不落盘。

用法：C:\\Python314\\python.exe src/analysis/verify_price_ref_determinism.py
输出：同目录 verify_price_ref_determinism.txt
"""
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / '.pylibs'))

OUT = HERE / '_verify_price_ref.txt'
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


import engine.competitor_insight as ci
from data.fetch_poi import get_api_call_count, reset_api_call_count
from config import DATA_DIR

SITE = (121.5517, 29.8742)     # 宁波天一广场
SITE_NAME = '宁波天一广场'
CAT = '奶茶'
BRAND = '蜜雪冰城'
N = 5

p('=' * 64)
p(f'客单价校正复现性验证 —— {SITE_NAME} {SITE} / {CAT} / {BRAND}')
p(f'缓存文件：{DATA_DIR / "competitor_cache.json"}')
p('=' * 64)

# 从干净状态开始：清缓存，确保第一次是真实取数
ci.clear_cache()
p('\n=== T1 清缓存后首次取数（应为实时 + 消耗 API）===')
reset_api_call_count()
t0 = time.time()
r1 = ci.brand_price_reference(*SITE, CAT, BRAND)
n1 = get_api_call_count()
p(f'  首次：校正客单价={r1["校正客单价"]}  来源={r1["来源"]}  状态={r1["抓取状态"]}  '
  f'API 调用={n1}  用时={time.time() - t0:.1f}s')
check('首次成功取到价格', r1['抓取状态'] == 'ok' and r1['校正客单价'] is not None,
      str(r1['校正客单价']))
check('首次来源标为实时', r1['来源'] == '实时', str(r1['来源']))
check('首次确实消耗了 API', n1 >= 1, f'{n1} 次')

p(f'\n=== T2 同输入再调 {N} 次（应 0 次 API 且逐字段一致）===')
reset_api_call_count()
results = []
for i in range(N):
    results.append(ci.brand_price_reference(*SITE, CAT, BRAND))
n2 = get_api_call_count()
p(f'  {N} 次累计 API 调用 = {n2}')
check(f'缓存命中后 {N} 次调用 0 次 API', n2 == 0, f'{n2} 次')
check('缓存命中时来源标为缓存',
      all(r['来源'] == '缓存' for r in results),
      str({r['来源'] for r in results}))


def _sig(r):
    """把结果压成可比对的指纹（去掉会变化的 age 字段）"""
    return json.dumps({
        '校正客单价': r['校正客单价'], '校正倍数': r['校正倍数'],
        '口径': r['口径'], '证据': r['证据'], '抓取状态': r['抓取状态'],
        '取证时间': r['取证时间'],
    }, ensure_ascii=False, sort_keys=True)


sigs = {_sig(r) for r in [r1] + results}
p(f'  不同结果指纹数 = {len(sigs)}（应为 1）')
check('首次与后续结果逐字段完全一致', len(sigs) == 1,
      f'{len(sigs)} 种 / 校正客单价={sorted({str(r["校正客单价"]) for r in [r1] + results})}')
check('口径文案也完全一致（不是"数字对但说法漂")', len({r['口径'] for r in [r1] + results}) == 1,
      str(list({r['口径'] for r in [r1] + results})[0])[:60])

p('\n=== T3 同一坐标换品牌 → 复用同一份周边快照，0 次额外 API ===')
reset_api_call_count()
r_other = ci.brand_price_reference(*SITE, CAT, '古茗')
n3 = get_api_call_count()
p(f'  古茗：校正客单价={r_other["校正客单价"]}  来源={r_other["来源"]}  '
  f'API 调用={n3}')
check('换品牌不重复抓取周边（缓存按坐标+品类共享）', n3 == 0, f'{n3} 次')
check('换品牌仍能算出该品牌自己的价格',
      r_other['抓取状态'] in ('ok', 'underpowered', 'no_same_brand'),
      f"{r_other['抓取状态']} / {r_other['校正客单价']}")
check('不同品牌确实得到不同结果（不是把缓存值原样返回）',
      r_other['校正客单价'] != r1['校正客单价'] or r1['校正客单价'] is None,
      f'{r1["校正客单价"]} vs {r_other["校正客单价"]}')

p('\n=== T3b 自创品牌：定义上无同品牌参照，不该报成"没抓到" ===')
reset_api_call_count()
r_self = ci.brand_price_reference(*SITE, CAT, '自创品牌')
n_self = get_api_call_count()
p(f'  自创品牌：状态={r_self["抓取状态"]}  校正客单价={r_self["校正客单价"]}  '
  f'API 调用={n_self}')
check('自创品牌状态标为 self_brand', r_self['抓取状态'] == 'self_brand',
      str(r_self['抓取状态']))
check('自创品牌不误报成"附近没抓到"',
      '没抓到' not in (r_self['口径'] or '') and '口径定义' in (r_self['口径'] or ''),
      str(r_self['口径'])[:60])
check('自创品牌不必为此打高德接口（省配额）', n_self == 0, f'{n_self} 次')

p('\n=== T4 缓存文件可读且含取证时间 ===')
cf = DATA_DIR / 'competitor_cache.json'
check('缓存写盘无错误', ci.CACHE_SAVE_ERROR is None, str(ci.CACHE_SAVE_ERROR))
check('缓存文件已落盘', cf.exists(), str(cf))
try:
    data = json.loads(cf.read_text(encoding='utf-8'))
    check('缓存是合法 JSON', isinstance(data, dict), f'{len(data)} 条')
    k = ci._cache_key(*SITE, CAT, 1000, 25)
    ent = data.get(k)
    check('键含坐标+品类+半径，可精确定位', ent is not None, k)
    check('缓存记录带取证时间与成功标记',
          bool(ent) and bool(ent.get('fetched_at')) and ent.get('ok') is True,
          str(ent.get('fetched_at')) if ent else 'None')
    check('缓存里存的是原始 POI 快照（可同时服务多个品牌）',
          bool(ent) and isinstance(ent.get('pois'), list) and len(ent['pois']) > 0,
          f'{len(ent["pois"]) if ent else 0} 家门店')
except Exception as e:
    check('缓存文件可解析', False, f'{type(e).__name__}: {e}')

p('\n=== T5 端到端：同一输入两次 score_site，流水必须相同 ===')
from engine.scoring import score_site

sigs_sales = []
for i in range(2):
    r = score_site(CAT, *SITE, 12000, SITE_NAME, 30, city='宁波', city_level=1.0,
                   investment=200000, staff=3, brand=BRAND)
    pc = r.get('客单价校正') or {}
    sigs_sales.append((r['total'], r['evidence']['预估月流水'],
                       (r.get('profit') or {}).get('月净利估算'),
                       (r.get('profit') or {}).get('回本周期(月)')))
    p(f'  第{i+1}次：总分={r["total"]}  月流水={r["evidence"]["预估月流水"]}  '
      f'月净利={(r.get("profit") or {}).get("月净利估算")}  '
      f'回本={(r.get("profit") or {}).get("回本周期(月)")}  '
      f'客单价校正状态={pc.get("抓取状态")}  来源={pc.get("数据来源")}')
check('两次 score_site 完全一致（流水/净利/回本/总分）',
      sigs_sales[0] == sigs_sales[1],
      f'{sigs_sales[0]} vs {sigs_sales[1]}')
check('两次都没有出现"校正值在 ¥X 与 None 之间跳变"',
      all(s[1] == sigs_sales[0][1] for s in sigs_sales),
      str([s[1] for s in sigs_sales]))

p('\n=== T6 取数失败也要确定（同一会话内不跳变）===')
NO_PUB = '一点点'   # 真实连锁、但无公开披露的单店每单金额 → 失败时只能退画像
real = ci.fetch_around_raw
try:
    ci.clear_cache()
    # 直接替换抓取层：模拟限流。fetch_competitor_pois_ex 在调用时按模块全局
    # 查找 fetch_around_raw，所以这个替换会生效。
    ci.fetch_around_raw = lambda *a, **k: (
        [], {'ok': False, 'info': 'CUQPS_HAS_EXCEEDED_THE_LIMIT',
             'infocode': '10021', 'quota': False, 'err': None,
             'tries': 3, 'count': None})
    # T6a 无公开数据的品牌 → fetch_failed（沿用品类画像，且绝不说"附近没有"）
    a1 = ci.brand_price_reference(*SITE, CAT, NO_PUB)
    a2 = ci.brand_price_reference(*SITE, CAT, NO_PUB)
    p(f'  [{NO_PUB}] 失败态两次：状态={a1["抓取状态"]}/{a2["抓取状态"]}  '
      f'口径一致={a1["口径"] == a2["口径"]}')
    check('取数失败且无公开数据 → 状态标记 fetch_failed',
          a1['抓取状态'] == 'fetch_failed', a1['抓取状态'])
    check('取数失败在同一会话内结果稳定', a1['口径'] == a2['口径'] and
          a1['校正客单价'] == a2['校正客单价'])
    check('失败态不写"周边 0 家里没抓到"这种假结论',
          '0 家同类门店' not in a1['口径'], a1['口径'][:50])
    # T6b 有公开数据的品牌（蜜雪）→ public_only：取数失败也不降级、仍给每单金额
    b1 = ci.brand_price_reference(*SITE, CAT, BRAND)
    b2 = ci.brand_price_reference(*SITE, CAT, BRAND)
    p(f'  [{BRAND}] 失败态两次：状态={b1["抓取状态"]}/{b2["抓取状态"]}  '
      f'校正客单价={b1["校正客单价"]}  口径来源={b1["口径来源"]}')
    check('取数失败但有公开数据 → 状态标记 public_only',
          b1['抓取状态'] == 'public_only', b1['抓取状态'])
    check('有公开数据时取数失败仍给出每单金额（不降级、不退画像）',
          b1['校正客单价'] == 11.4 and b1['口径来源'] == 'public_report',
          f"{b1['校正客单价']} / {b1['口径来源']}")
    check('public_only 在同一会话内结果稳定',
          b1['口径'] == b2['口径'] and b1['校正客单价'] == b2['校正客单价'])
finally:
    ci.fetch_around_raw = real
    ci.clear_cache()

p('\n' + '=' * 64)
if FAIL:
    p(f'共 {len(FAIL)} 项 FAIL：' + ' / '.join(FAIL))
else:
    p('全部 PASS')
p('=' * 64)

OUT.write_text('\n'.join(L), encoding='utf-8')
sys.exit(1 if FAIL else 0)
