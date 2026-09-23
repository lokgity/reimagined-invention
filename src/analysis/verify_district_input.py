# -*- coding: utf-8 -*-
"""
verify_district_input.py —— 区县/县级市地名识别门禁（问题①）
=============================================================
背景（策 2026-09-23 反馈）：
    「我直接输入县市级或者区名会显示我还没输入地区，比如瓯海区，
      我一定要输入温州瓯海区才能正确识别到我给的地区」

根因（三重，缺一条都还有症状）：
    ① `extract_city()` 只扫 11 个**地级市**名 → `extract_city('瓯海区')` = None
       → `_has_place_hint()` 判 False → 流程反问"想开在哪个区域"。
    ② `_clean_area()` 只剥**后缀**不剥**前缀** → 「我想在海宁开奶茶店」
       剥完剩 **「我想在海宁」**，被当地址送进 geocode（必然失败）。
    ③ `fetch_shops()` 里 `CITY_CODES.get(city, city)` 的默认值把**中文当域名**：
       `fetch_shops('海宁')` → `https://海宁.58.com/shangpu/`
       （2026-09-23 真机实测：4 路全部 0 条、耗时 21.4s 才失败）。

本套件钉住三件事（都是"改了会静默坏、且离线全绿"的那类）：
    §1 区县表完整性（90 个区县、无歧义、与 POI 库一致）
    §2 识别链（extract_city / city_of_district / extract_district / _has_place_hint）
       —— 含**外省不误判**这条反向断言
    §3 fetch_shops 的城市解析（中文绝不允许出现在域名里）
    §4 _clean_area 前缀剥离（且不许把有效地名剥空）

⚠️ 数据源纪律：区县表由 `data/zj_poi.db` 聚合而来，本套件会**回查该库**，
    确保表与库不脱节（库更新后表没重生 → 这里报错）。
"""
import os
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / '.pylibs'))
os.environ.setdefault('ZL_EXPERT_LLM_DISABLE', '1')

from agent.zj_districts import (  # noqa: E402
    DISTRICT_TO_CITY, DISTRICT_TO_CITY_SHORT, AMBIGUOUS_SHORT)
from agent.agent_graph import (  # noqa: E402
    extract_city, city_of_district, extract_district, _has_place_hint, _clean_area)
from agent.rental58 import CITY_CODES  # noqa: E402

fails = 0
n = 0


def ck(cond, label):
    global fails, n
    n += 1
    if cond:
        print('  OK   ' + label)
    else:
        fails += 1
        print('  FAIL ' + label)


CITY_ORDER = ['杭州', '宁波', '温州', '嘉兴', '湖州', '绍兴',
              '金华', '衢州', '舟山', '台州', '丽水']

print('=' * 64)
print('§1 区县表完整性（与 POI 库对齐）')
print('=' * 64)

db = ROOT / 'data' / 'zj_poi.db'
ck(db.exists(), f'POI 库存在（{db.name}）')
conn = sqlite3.connect(str(db))
rows = conn.execute(
    'SELECT city, adname, COUNT(*) FROM poi GROUP BY city, adname').fetchall()
conn.close()

from collections import defaultdict  # noqa: E402
by_city = defaultdict(dict)
for city, ad, cnt in rows:
    if ad and city:
        by_city[city.replace('市', '')][ad] = cnt

ck(len(DISTRICT_TO_CITY) == 90,
   f'区县表 90 条（实测 {len(DISTRICT_TO_CITY)}）')

# ⚠️ 两张表的**键本来就不同**（全称 '瓯海区' vs 短名 '瓯海'），
#    所以不能断言"键集合一致"（早先写错过一次）。真正要钉的是：
#    ① 条数相等（一一对应，没有谁多谁少）
#    ② 短名 = 全称剥掉后缀，且**值（地级市）必须相同**
ck(len(DISTRICT_TO_CITY) == len(DISTRICT_TO_CITY_SHORT),
   f'全称表与短名表条数相等（{len(DISTRICT_TO_CITY)} vs {len(DISTRICT_TO_CITY_SHORT)}）')

_mismatch = []
for full, city in DISTRICT_TO_CITY.items():
    short = full
    for suf in ('区', '县', '市'):
        if short.endswith(suf):
            short = short[:-len(suf)]
            break
    if DISTRICT_TO_CITY_SHORT.get(short) != city:
        _mismatch.append((full, short, city, DISTRICT_TO_CITY_SHORT.get(short)))
ck(not _mismatch,
   f'短名 = 全称去后缀 且 地级市一致（不符 {_mismatch[:5]}）')

# 与库逐条对齐 —— 库更新后表没重生，这里就红
missing, extra, wrong = [], [], []
for city, m in by_city.items():
    for ad in m:
        if ad not in DISTRICT_TO_CITY:
            missing.append(ad)
        elif DISTRICT_TO_CITY[ad] != city:
            wrong.append((ad, DISTRICT_TO_CITY[ad], city))
for ad in DISTRICT_TO_CITY:
    if ad not in {a for m in by_city.values() for a in m}:
        extra.append(ad)
ck(not missing, f'库里的区县表里都有（缺 {missing[:5]}）')
ck(not extra, f'表里的区县库里都有（多 {extra[:5]}）')
ck(not wrong, f'区县→地级市 映射与库一致（错 {wrong[:5]}）')

# 全部值必须是 11 个地级市之一（否则 CITY_CODES 查不到，又回退成域名）
bad_city = {v for v in DISTRICT_TO_CITY.values() if v not in CITY_ORDER}
ck(not bad_city, f'表里所有值都是合法地级市（越界 {bad_city}）')

# 每个值都能在 CITY_CODES 里查到码 —— 这是问题③的根，钉死
no_code = sorted({v for v in DISTRICT_TO_CITY.values() if v not in CITY_CODES})
ck(not no_code, f'表里所有值都能在 CITY_CODES 查到分站码（查不到 {no_code}）')

# 歧义短名不许混进识别表
ck(not (set(DISTRICT_TO_CITY_SHORT) & set(AMBIGUOUS_SHORT)),
   '歧义短名没有混进 DISTRICT_TO_CITY_SHORT')
ck(len(DISTRICT_TO_CITY_SHORT) == len(DISTRICT_TO_CITY),
   f'短名表 {len(DISTRICT_TO_CITY_SHORT)} 条（浙江 90 区县去掉后缀无重名）')

print()
print('=' * 64)
print('§2 识别链（extract_city / city_of_district / _has_place_hint）')
print('=' * 64)

# (输入, 期望地级市) —— 覆盖区/县级市/自治县/短名/带城市前缀
CASES = [
    ('瓯海区', '温州'), ('温州瓯海区', '温州'), ('瓯海', '温州'),
    ('海宁', '嘉兴'), ('海宁市', '嘉兴'), ('嘉兴海宁', '嘉兴'),
    ('鄞州', '宁波'), ('鄞州区', '宁波'), ('宁波鄞州区', '宁波'),
    ('义乌', '金华'), ('义乌市', '金华'),
    ('慈溪', '宁波'), ('余杭区', '杭州'), ('滨江', '杭州'),
    ('乐清', '温州'), ('诸暨', '绍兴'), ('龙港市', '温州'),
    ('景宁畲族自治县', '丽水'), ('桐庐县', '杭州'), ('建德市', '杭州'),
    # 地级市本身（行为不许变）
    ('杭州', '杭州'), ('温州', '温州'), ('丽水', '丽水'),
]
for text, want in CASES:
    got = extract_city(text)
    ck(got == want, f'extract_city({text!r}) == {want!r}（实测 {got!r}）')

# 全部 90 个区县，逐个验证反推
bad = []
for dist, city in DISTRICT_TO_CITY.items():
    if extract_city(dist) != city:
        bad.append((dist, city, extract_city(dist)))
    if city_of_district(dist) != city:
        bad.append(('city_of_district:' + dist, city, city_of_district(dist)))
ck(not bad, f'全部 90 个区县都能反推（错 {bad[:6]}）')

# 全部 90 个短名
bad_s = [s for s, c in DISTRICT_TO_CITY_SHORT.items() if city_of_district(s) != c]
ck(not bad_s, f'全部 90 个短名都能反推（错 {bad_s[:6]}）')

# 「我想在某区开店」这类整句
for text, want in [('我想在瓯海区开店', '温州'), ('我想在海宁开奶茶店', '嘉兴'),
                   ('我想在杭州滨江开店', '杭州'), ('帮我找义乌的铺子', '金华')]:
    ck(extract_city(text) == want,
       f'整句 extract_city({text!r}) == {want!r}（实测 {extract_city(text)!r}）')
    ck(_has_place_hint(text) is True,
       f'_has_place_hint({text!r}) 为 True —— 不再反问"想开在哪个区域"')

# ---- 反向断言：外省/非地名绝不能被认成浙江地名 ----
NEG = ['北京朝阳区', '上海浦东新区', '广州天河区', '深圳南山区',
       '奶茶店毛利率多少', '加盟费一般多少', '多少钱', '怎么办',
       '白堤路88号', '']
for text in NEG:
    ck(extract_city(text) is None,
       f'外省/非地名 extract_city({text!r}) 为 None（实测 {extract_city(text)!r}）')

for text in ['奶茶店毛利率多少', '加盟费多少', '怎么开店', '']:
    ck(_has_place_hint(text) is False,
       f'_has_place_hint({text!r}) 为 False（不被当成给了地点）')

print()
print('=' * 64)
print('§3 fetch_shops 城市解析：中文绝不许出现在域名里')
print('=' * 64)

import agent.rental58 as R  # noqa: E402

HOST_CASES = [
    ('海宁', 'jx.58.com'), ('嘉兴海宁', 'jx.58.com'),
    ('瓯海区', 'wz.58.com'), ('温州瓯海区', 'wz.58.com'),
    ('鄞州', 'nb.58.com'), ('义乌', 'jh.58.com'),
    ('龙港市', 'wz.58.com'), ('景宁畲族自治县', 'ls.58.com'),
    ('杭州滨江', 'hz.58.com'), ('杭州', 'hz.58.com'),
]
for city, want_host in HOST_CASES:
    captured = {}
    orig = R._fetch_async

    def fake(urls, timeout, limit, total_timeout=12.0, _cap=captured):
        _cap['urls'] = list(urls)
        return ({u: [] for u in urls}, [])

    R._fetch_async = fake
    meta = {}
    try:
        R.fetch_shops(city, limit=1, timeout=1, area_filter=None, pages=3,
                      mobile=True, budget_s=25.0, meta=meta, detail=False)
    finally:
        R._fetch_async = orig
    urls = captured.get('urls') or []
    hosts = {u.split('/')[2] for u in urls}
    # ⚠️ 合法域名只有两种：
    #   ① 城市分站 `{code}.58.com`（PC 列表，只抓首页）
    #   ② 移动端 `m.58.com`（**所有城市共用**，城市码在路径里：`m.58.com/{code}/…`）
    #   移动端不是"另一个城市的域名"，早先误把它当异常 —— 断言要按这个事实写。
    code = want_host.split('.')[0]
    allowed = {want_host, 'm.58.com'}
    ck(hosts <= allowed,
       f'fetch_shops({city!r}) 只打 {sorted(allowed)}（实测 {sorted(hosts)}）')
    ck(want_host in hosts,
       f'fetch_shops({city!r}) 用对了城市分站 {want_host}')
    # 移动端路径里必须是这个城市的码（不许拼成别的城市 / 中文）
    m_urls = [u for u in urls if u.startswith('https://m.58.com/')]
    ck(all(u.split('/')[3] == code for u in m_urls),
       f'fetch_shops({city!r}) 移动端路径用的是 {code}（实测 '
       f'{[u.split("/")[3] for u in m_urls]}）')
    ck(not any(re.search(r'[\u4e00-\u9fa5]', h) for h in hosts),
       f'fetch_shops({city!r}) 域名里无中文')


# 无法反推的城市：必须**明确报错并快速返回**，不许白等 20 秒
meta = {}
t0 = __import__('time').monotonic()
res = R.fetch_shops('北京', limit=1, timeout=1, area_filter=None, pages=3,
                    mobile=True, budget_s=25.0, meta=meta, detail=False)
dt = __import__('time').monotonic() - t0
ck(res == [], 'fetch_shops(外省) 返回空列表')
ck(meta.get('ok') is False, 'fetch_shops(外省) meta[ok]=False（区分"取数失败"与"真的没有"）')
ck(dt < 2.0, f'fetch_shops(外省) 快速失败（实测 {dt:.2f}s < 2s，不再白等 20s）')
ck('地级市' in (meta.get('reason') or '') or '区县' in (meta.get('reason') or ''),
   f'报错文案说清原因（实测 {meta.get("reason")!r}）')

print()
print('=' * 64)
print('§4 _clean_area 前缀剥离（且不许把有效地名剥空）')
print('=' * 64)

CLEAN_CASES = [
    ('我想在海宁开奶茶店', '海宁'),
    ('我想在瓯海区开店', '瓯海区'),
    ('我想在杭州滨江开店', '杭州滨江'),
    ('帮我找义乌的铺子', '义乌'),
    ('宁波鄞州区的商铺', '宁波鄞州区'),
    ('打算在慈溪开一家店', '慈溪'),
    ('杭州滨江的奶茶店', '杭州滨江'),
]
for src, want in CLEAN_CASES:
    got = _clean_area(src)
    ck(got == want, f'_clean_area({src!r}) == {want!r}（实测 {got!r}）')

# 反向：剥完不能为空、不能把地名本体吃掉
for src in ['我想开店', '开店', '想开一家奶茶店', '找铺子']:
    got = _clean_area(src)
    ck(len(got) >= 2 or got == src,
       f'_clean_area({src!r}) 没有剥成空串（实测 {got!r}）')

# 剥完的结果里如果再含区县名，必须仍能反推（保证链路端到端不断）
for src in ['我想在海宁开奶茶店', '我想在瓯海区开店', '帮我找义乌的铺子']:
    cleaned = _clean_area(src)
    ck(extract_city(cleaned) is not None,
       f'_clean_area({src!r})={cleaned!r} 仍可反推出城市')

print()
print('=' * 64)
print(f'FAILED = {fails}  /  共 {n} 项')
# ⚠️ 结尾行必须是 `FAILED = N`：run_regression.py 的失败计数正则里
#    `共\s*(\d+)\s*项\s*FAIL` 会把**总项数**当失败数（本套件有「共 N 项 FAIL M」
#    两段数字，该正则捕获的是 N）。统一成 FAILED = N 才无歧义。
print('=' * 64)

sys.exit(1 if fails else 0)
