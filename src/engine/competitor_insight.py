# -*- coding: utf-8 -*-
"""
competitor_insight.py —— 竞品口碑与价格带挖掘（AI 方向④，诚实降级版）
=====================================================================
原始设想是爬大众点评评论做情感分析，实测点评全站强制登录墙（PC 扫码 +
移动短信验证），不可爬。降级为高德开放平台 POI 的**平台公开字段**：

真实可得：biz_ext.rating（口碑分）、biz_ext.cost（人均消费）、
          opentime2（营业时间）、groupbuy_num/discount_num（团购/优惠活跃度）、
          favorite_num（收藏数）、tag（招牌产品词）、photos（实拍图数量）
真实不可得：评论文本、评论数、销量 → 本模块**不做情感分析**，只做
            口碑分分布 / 价格带 / 品牌集中度 / 营业强度 / 招牌热词 的结构化挖掘，
            并把它当成对模型假设的**现实校验**（客单价假设 vs 真实人均）。

每次调用消耗 1 次高德 API（周边搜索 extensions=all）。

--------------------------------------------------------------------------
v2 修正（2026-09-15）：接口失败 ≠ 没有数据，以及结果冻结
--------------------------------------------------------------------------
背景：同一坐标、同一品牌连续评分，`校正客单价` 会在 ¥7 与 None 之间跳变，
导致同一输入两次运行的月流水差 2.3 倍——报告不可复现。

实测根因（不是数据源抖动）：
  个人 key 连续调 /v3/place/around，第 5 次起返回
      status=0  infocode=10021  info=CUQPS_HAS_EXCEEDED_THE_LIMIT
  间隔 2s 后立刻恢复；成功时 count / POI 列表 / 同品牌样本数**完全稳定**
  （天一广场恒 3 家蜜雪、湖滨 in77 恒 5 家）。
  即：数据源是确定的，非确定性 100% 来自高德 QPS 限流。

原实现三个缺陷：
  1. `if data.get('status') != '1': return []` —— 限流被静默当成"空结果"，
     与"这一带真的没有同类店"不可区分；
  2. 下游据此写出**假结论**：「周边 0 家同类门店里没抓到「蜜雪冰城」的
     人均（高德未收录）」——实际是限流，用户会误以为附近没有该品牌；
  3. 结果不落盘，每次评分重打 API，抖动直接进流水。

修法：
  · `_fetch_around_raw` 带出 status/infocode，瞬时限流（10021/10020/10004）
    走退避重试；日配额耗尽（10003/10019）明确区分，重试无意义；
  · `fetch_competitor_pois` 加**持久化冻结缓存**（data/competitor_cache.json），
    成功结果 30 天、失败结果 180s，写盘用原子替换；命中即 0 次 API 且值恒定；
  · `brand_price_reference` 口径按"取数失败 / 取数成功但无该品牌 / 正常校正"
    三分支输出，失败时明确写"这不代表附近没有该品牌"，并在 API 失败时用
    本地预抓取库交叉验证该品牌是否存在（本地库无人均字段，只能证存在性）。
"""
import json
import os
import sys
import time
import statistics
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import get_profile
from data.fetch_poi import amap_url, http_get
from engine.brands import (brand_attractiveness, is_self_brand, brand_order_value,
                          industry_price_reference,
                          UNIT_PER_ORDER, UNIT_PER_ORDER_BAND)

# 数据局限声明（必须随结果一起给到 LLM 与用户，防止把降级数据吹成评论挖掘）
DATA_LIMIT = ('竞品数据来自高德开放平台公开字段（口碑分/人均/营业时间/团购数/招牌标签），'
              '评论文本与销量不可得，因此本模块不做评论情感分析；'
              '样本仅覆盖高德已收录门店，新开/未收录门店不在内。')


def _pct(vals, q):
    """线性插值分位数（不依赖 numpy）"""
    if not vals:
        return None
    s = sorted(vals)
    if len(s) == 1:
        return round(s[0], 1)
    pos = (len(s) - 1) * q
    lo, hi = int(pos), min(int(pos) + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (pos - lo), 1)


# ---- 高德 infocode 分类：决定"重试有没有意义" ----
# 10021/10020/10004 是单位时间并发/QPS 超限，实测 2s 后就恢复 → 退避重试有效；
# 10003/10019 是**日配额**耗尽，当天重试一万次也没用 → 必须明确告诉用户是哪种，
# 否则用户会误以为"高德没这个数据"而放弃核实。
RETRYABLE_INFOCODES = {'10021', '10020', '10004'}
QUOTA_INFOCODES = {'10003', '10019'}
BACKOFF_SECONDS = (0.4, 0.9, 1.8)     # 总退避 < 3.2s，评分路径上可接受

CACHE_TTL_OK = 30 * 24 * 3600   # 人均消费变化以月/季计，30 天内冻结完全够用
CACHE_TTL_FAIL = 180            # 失败只冻结 3 分钟：够让一次会话内数字不跳，
                                # 又能在限流解除后自愈，不会把一次抖动固化很久
CACHE_MAX_ENTRIES = 400         # 约 400 个「点位×品类」，防缓存文件无限增长

_CACHE_MEM = None
_CACHE_PATH = None
CACHE_SAVE_ERROR = None     # 最近一次写盘失败原因（None = 正常），供诊断用


def _ensure_path():
    """保证 _CACHE_PATH 已就绪（与 _CACHE_MEM 是否为空解耦）。

    曾经的坑：路径初始化绑在 `if _CACHE_MEM is None` 里，于是 clear_cache()
    先把 _CACHE_MEM 置成 {}，后续 _cache() 不再进入初始化分支 → _CACHE_PATH
    永远 None → _save_cache() 静默早退 → 缓存一次都没落盘，而且没有任何报错。
    """
    global _CACHE_PATH
    if _CACHE_PATH is None:
        from config import DATA_DIR
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH = DATA_DIR / 'competitor_cache.json'
    return _CACHE_PATH


def _cache():
    global _CACHE_MEM
    path = _ensure_path()
    if _CACHE_MEM is None:
        try:
            _CACHE_MEM = json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            _CACHE_MEM = {}
    return _CACHE_MEM


def _save_cache():
    """原子写：先写 .tmp 再 os.replace，避免进程被中断时留下半个 JSON。

    ⚠️ 写失败必须出声。本模块最初的 bug 就是"静默吞掉失败"（限流的空结果被
    当成"没有竞品"），缓存写失败如果也静默吞，下次运行读不到缓存 → 又开始抖，
    用户完全无从排查。所以这里失败打 stderr 并记录到 CACHE_SAVE_ERROR。
    """
    global CACHE_SAVE_ERROR
    try:
        path = _ensure_path()
        if _CACHE_MEM is None:
            return
        items = sorted(_CACHE_MEM.items(), key=lambda kv: kv[1].get('t', 0))
        items = items[-CACHE_MAX_ENTRIES:]
        tmp = path.with_name(path.name + '.tmp')
        tmp.write_text(json.dumps(dict(items), ensure_ascii=False), encoding='utf-8')
        os.replace(tmp, path)
        CACHE_SAVE_ERROR = None
    except Exception as e:
        CACHE_SAVE_ERROR = f'{type(e).__name__}: {e}'
        try:
            print(f'[competitor_insight] 竞品缓存写盘失败（不影响本次评分，'
                  f'但下次运行会重新取数）：{CACHE_SAVE_ERROR}', file=sys.stderr)
        except Exception:
            pass


def clear_cache():
    """清空持久化竞品缓存（调试 / 强制刷新用）。"""
    global _CACHE_MEM
    _ensure_path()
    _CACHE_MEM = {}
    _save_cache()


def _num_or_none(v):
    try:
        f = float(v)
        return f if f > 0 else None
    except Exception:
        return None


def _parse_pois(raw_pois, limit):
    out = []
    for p in (raw_pois or [])[:limit]:
        be = p.get('biz_ext') or {}
        brand, s_coef = brand_attractiveness(p.get('name') or '')
        tags = [t for t in str(p.get('tag') or '').split(',') if t]
        out.append({
            'name': p.get('name') or '',
            'brand': brand,
            'S': s_coef,
            'distance': _num_or_none(p.get('distance')),
            'rating': _num_or_none(be.get('rating')),
            'cost': _num_or_none(be.get('cost')),
            'opentime': be.get('opentime2') or be.get('open_time') or '',
            'groupbuy': int(_num_or_none(p.get('groupbuy_num')) or 0),
            'discount': int(_num_or_none(p.get('discount_num')) or 0),
            'favorite': int(_num_or_none(p.get('favorite_num')) or 0),
            'photos': len(p.get('photos') or []),
            'tags': tags[:8],
            'keytag': p.get('keytag') or '',
        })
    return out


def fetch_around_raw(lng, lat, category, radius=1000, limit=25):
    """原始抓取，**带出失败原因**。返回 (pois, meta)。

    meta = {'ok': bool, 'info', 'infocode', 'err', 'tries', 'count', 'quota'}
      ok=False 时 pois 恒为 []，但 meta 说清是"限流/配额/网络"中的哪一种，
      下游必须据此改口径，不能再说"周边 0 家同类门店"。
    """
    profile = get_profile(category)
    kw = (profile.get('poi_keywords') or [category])[0]
    params = {
        'location': f'{lng},{lat}', 'keywords': kw, 'radius': str(radius),
        'offset': str(min(limit, 25)), 'page': '1', 'extensions': 'all',
    }
    url = amap_url('/v3/place/around', params)
    last = {'ok': False, 'info': None, 'infocode': None,
            'err': None, 'count': None, 'quota': False}
    tries = 0
    for attempt in range(len(BACKOFF_SECONDS)):
        tries += 1
        try:
            # retries=2：网络层抖动重试交给 http_get，但别用默认的 4 次
            # （其退避是 2+4+6+8=20s，评分路径上太久）
            data = http_get(url, timeout=20, retries=2)
        except Exception as e:
            last = {'ok': False, 'info': None, 'infocode': None,
                    'err': f'{type(e).__name__}: {e}', 'count': None, 'quota': False}
            time.sleep(BACKOFF_SECONDS[attempt])
            continue
        if str(data.get('status')) == '1':
            last = {'ok': True, 'info': 'OK', 'infocode': '10000', 'err': None,
                    'count': int(data.get('count') or 0), 'quota': False, 'tries': tries}
            return _parse_pois(data.get('pois'), limit), last
        code = str(data.get('infocode') or '')
        last = {'ok': False, 'info': str(data.get('info') or ''), 'infocode': code,
                'err': None, 'count': None,
                'quota': code in QUOTA_INFOCODES, 'tries': tries}
        if code not in RETRYABLE_INFOCODES:
            break            # 日配额 / key 无效 / 参数错误：重试无意义，立即上报
        time.sleep(BACKOFF_SECONDS[attempt])
    last['tries'] = tries
    return [], last


def _cache_key(lng, lat, category, radius, limit):
    return f'{round(lng, 4)},{round(lat, 4)}|{category}|{int(radius)}|{int(limit)}'


def fetch_competitor_pois_ex(lng, lat, category, radius=1000, limit=25, use_cache=True):
    """带状态的抓取。返回 (pois, meta)，meta 额外含 cached / age / fetched_at。

    缓存键含坐标与半径，保证**同一输入永远同一条缓存**；命中即 0 次 API，
    且返回的 POI 列表逐字节相同 → 下游一切指标（人均中位、价格带、HHI）
    随之恒定，报告可复现。
    """
    if not use_cache:
        pois, meta = fetch_around_raw(lng, lat, category, radius, limit)
        return pois, dict(meta, cached=False, age=0.0,
                          fetched_at=datetime.now().strftime('%Y-%m-%d %H:%M'))

    key = _cache_key(lng, lat, category, radius, limit)
    cache = _cache()
    ent = cache.get(key)
    if ent:
        age = time.time() - float(ent.get('t') or 0)
        ttl = CACHE_TTL_OK if ent.get('ok') else CACHE_TTL_FAIL
        if age < ttl:
            return (ent.get('pois') or []), dict(
                ent.get('meta') or {}, cached=True, age=round(age, 1),
                fetched_at=ent.get('fetched_at'))

    pois, meta = fetch_around_raw(lng, lat, category, radius, limit)
    fetched_at = datetime.now().strftime('%Y-%m-%d %H:%M')
    cache[key] = {'t': time.time(), 'ok': bool(meta.get('ok')),
                  'pois': pois, 'meta': meta, 'fetched_at': fetched_at}
    _save_cache()
    return pois, dict(meta, cached=False, age=0.0, fetched_at=fetched_at)


def fetch_competitor_pois(lng, lat, category, radius=1000, limit=25):
    """抓取周边同类竞品的口碑字段（缓存命中时 0 次 API）。返回 list[dict]。

    保持旧签名以兼容既有调用方与测试（测试会整体替换本函数，从而绕过缓存）。
    需要区分"取数失败"与"真的没有门店"的调用方请改用
    `fetch_competitor_pois_ex`，它把失败原因带出来。
    """
    return fetch_competitor_pois_ex(lng, lat, category, radius, limit)[0]


# n<2 时"中位数"就是那一家店的单个数，拿它覆盖全局假设是用噪声换伪精度
MIN_SAME_BRAND_SAMPLES = 2

# ---------------------------------------------------------------
# A 级数据源：品牌定向搜索（/v3/place/text）
# ---------------------------------------------------------------
# 为什么需要（2026-09-16）：周边搜索 /v3/place/around 固定只取半径 1km 内
# **最近 25 家**。热门商圈里品牌扎堆，目标品牌可能根本不在 top25 采样内
# —— 实测宁波天一广场 25 家里**没有 CoCo**（状态 no_same_brand）、
# 鄞州万达只抓到 1 家（低于 MIN_SAME_BRAND_SAMPLES）。
# 定向搜索直接按品牌名查 + 距离排序，能拿到该品牌在候选点周边的真实门店
# 单杯价。它是**唯一既真实、又可实时、又不引入编造**的补法。
BRAND_SEARCH_RADIUS = 5000


def fetch_brand_pois(brand, lng=None, lat=None, radius=BRAND_SEARCH_RADIUS,
                     limit=25, use_cache=True):
    """按品牌名定向搜索该品牌门店（/v3/place/text）。

    返回 (pois, meta)：pois 为 `_parse_pois` 结构（brand 字段**强制**为传入 brand），
    meta 与 `fetch_around_raw` 同构（ok/info/infocode/quota/tries/cached/fetched_at）。
    """
    if not brand:
        return [], {'ok': False, 'info': '未指定品牌', 'infocode': None,
                    'err': None, 'count': None, 'quota': False, 'tries': 0}
    radius = int(radius)
    _loc = (f'{round(lng, 3)},{round(lat, 3)}'
            if (lng is not None and lat is not None) else '-')
    key = f'brand|{brand}|{_loc}|{radius}|{int(limit)}'
    if use_cache:
        ent = _cache().get(key)
        if ent:
            age = time.time() - float(ent.get('t') or 0)
            ttl = CACHE_TTL_OK if ent.get('ok') else CACHE_TTL_FAIL
            if age < ttl:
                return (ent.get('pois') or []), dict(
                    ent.get('meta') or {}, cached=True, age=round(age, 1),
                    fetched_at=ent.get('fetched_at'))

    params = {'keywords': brand, 'offset': str(min(limit, 25)), 'page': '1',
              'extensions': 'all', 'sortrule': 'distance'}
    if lng is not None and lat is not None:
        params['location'] = f'{lng},{lat}'
        params['radius'] = str(radius)
    url = amap_url('/v3/place/text', params)

    last = {'ok': False, 'info': None, 'infocode': None, 'err': None,
            'count': None, 'quota': False}
    tries, pois = 0, []
    for attempt in range(len(BACKOFF_SECONDS)):
        tries += 1
        try:
            # retries=2：与 fetch_around_raw 同口径，别用默认 4（退避 20s，评分路径上太久）
            data = http_get(url, timeout=20, retries=2)
        except Exception as e:
            last = {'ok': False, 'info': None, 'infocode': None,
                    'err': f'{type(e).__name__}: {e}', 'count': None, 'quota': False}
            time.sleep(BACKOFF_SECONDS[attempt])
            continue
        if str(data.get('status')) == '1':
            pois = _parse_pois(data.get('pois'), limit)
            # 定向搜索的语义就是"找这个品牌" → brand 强制归一，避免因店名写法差异
            # （如「都可」）被 brand_attractiveness 认成别的品牌或认不出。
            for p in pois:
                p['brand'] = brand
            last = {'ok': True, 'info': 'OK', 'infocode': '10000', 'err': None,
                    'count': int(data.get('count') or 0), 'quota': False, 'tries': tries}
            break
        code = str(data.get('infocode') or '')
        last = {'ok': False, 'info': str(data.get('info') or ''), 'infocode': code,
                'err': None, 'count': None, 'quota': code in QUOTA_INFOCODES,
                'tries': tries}
        if code not in RETRYABLE_INFOCODES:
            break            # 日配额 / key 无效 / 参数错误：重试无意义
        time.sleep(BACKOFF_SECONDS[attempt])
    last['tries'] = tries

    fetched_at = datetime.now().strftime('%Y-%m-%d %H:%M')
    if use_cache:
        _cache()[key] = {'t': time.time(), 'ok': bool(last.get('ok')), 'pois': pois,
                         'meta': last, 'fetched_at': fetched_at}
        _save_cache()
    return pois, dict(last, cached=False, age=0.0, fetched_at=fetched_at)


def same_brand_price(pois, brand):
    """同品牌门店的高德 biz_ext.cost（**口径 = 单杯价**，纯函数，不发 API）。

    ⚠️ 键名沿用了历史字段「同品牌人均中位」，但实测口径是**单杯价**：
    蜜雪 ¥7 ↔ 招股书单杯 ¥6.72、霸王茶姬 ¥20 ↔ 招股书单杯 ¥20.48。
    高德官方定义写的是「人均消费」，而茶饮场景里顾客多是一人一杯，
    所以"人均"≈"单杯价"。**它不是每单金额**——一单平均约 1.7 杯
    （蜜雪 11.4÷6.72 = 1.70、沪上阿姨 25÷14 = 1.79）。
    要拿它算流水，必须先乘每单杯数（见 brand_price_reference）。

    为什么必须按品牌分组：同品类内部价差可达 3~4 倍（实测
    蜜雪冰城 ¥7、CoCo ¥12、一点点/沪上阿姨/茶百道 ¥14~16、古茗 ¥15、
    霸王茶姬 ¥15~20、喜茶/奈雪 ¥22~24），全品类中位对任何单个品牌都不是
    可比对象。原校验拿品类画像 ¥16 跟全品类中位比、判"基本吻合"，
    而跟同品牌 ¥7 比则差 2.3 倍——参照组错了，结论正好反了。
    """
    if not brand:
        return None
    same = [p['cost'] for p in pois if p.get('brand') == brand and p.get('cost')]
    if not same:
        return None
    all_costs = [p['cost'] for p in pois if p.get('cost')]
    return {
        '品牌': brand,
        '样本数': len(same),
        '同品牌人均中位': _pct(same, 0.5),
        '同品牌人均区间': (min(same), max(same)),
        '全品类人均中位': _pct(all_costs, 0.5) if all_costs else None,
        '门店': [p['name'] for p in pois if p.get('brand') == brand and p.get('cost')][:6],
    }


def _local_brand_presence(lng, lat, category, brand, radius):
    """本地预抓取库(zj_poi.db)里该品牌在 radius 内有多少家门店。

    仅用于**存在性**交叉验证：本地库是 place/text 抓的，没有 biz_ext，
    因此**不含人均消费字段**，不能用来算价格校正。
    它的价值在于：当高德实时接口因限流失败时，能回答
    "这一带到底有没有该品牌"，而不是让用户以为"限流 = 附近没有这家店"。
    """
    try:
        from data.query import query_within
        rows = query_within(category, lng, lat, radius)
    except Exception:
        return None
    hits = []
    for r in rows:
        b, _ = brand_attractiveness(r.get('name') or '')
        if b == brand:
            hits.append({'name': r.get('name'), 'distance': r.get('distance')})
    hits.sort(key=lambda x: x['distance'] if x['distance'] is not None else 9e9)
    return {'门店数': len(hits), '样本': hits[:6]}


def brand_price_reference(lng, lat, category, brand, radius=1000, use_cache=True):
    """加盟场景下校正客单价 —— 口径是**每单金额**，不是高德给的人均/单杯价。

    ⚠️ 口径修正（2026-09-15）
    高德 biz_ext.cost 的官方定义是「人均消费」，但茶饮类目实测 ≈ **单杯价**：
        蜜雪冰城  高德 ¥7  ↔ 招股书单杯 ¥6.72
        霸王茶姬  高德 ¥20 ↔ 招股书单杯 ¥20.48
        沪上阿姨  高德 ¥14 ↔ 其价格带 7~22 的中位
    而本引擎的 daily_sales 明确是**日订单量**（订单数），公式为
        月流水 = 日订单量 × 每单金额
    拿「单杯价」直接当「每单金额」乘进去，等于隐含假设"一单一杯"，
    会系统性低估约 1.7 倍（蜜雪 11.4÷6.72 = 1.70 杯/单、沪上阿姨 25÷14 = 1.79 杯/单）。

    每单金额的来源优先级：
      ① 公开披露的「每单平均零售额」（招股书/年报，最可靠、可溯源）
         —— 与高德取数成败**无关**，接口挂了照样能用
      ② 高德实测同品牌「单杯价」× 每单杯数（brands.UNIT_PER_ORDER=1.7，粗估）
      ③ 都没有 → None，沿用品类画像

    返回 dict:
      校正客单价 : 每单金额(元/单) 或 None
      单杯价     : 高德实测同品牌单杯价中位（或公开单杯价）
      口径来源   : public_report / amap_targeted / amap_converted
                   / industry_estimate / none
      校正倍数   : 品类画像 ÷ 每单金额（>1 表示画像偏高）
      抓取状态   : not_requested / self_brand / fetch_failed / public_only
                   / no_same_brand / underpowered / industry_ref / ok

    A 级补采（2026-09-16 新增）：周边 1km 采样里同品牌不足
    `MIN_SAME_BRAND_SAMPLES` 家时，自动改用**品牌定向搜索**（`fetch_brand_pois`，
    5km + 距离排序）补齐样本，解决"品牌不在 top25 采样内"的问题。补采成功时
    `口径来源='amap_targeted'`、`来源='实时+定向补采'`。

    来源分级（用户拍板：分级标注、不与披露值混用）：
      B 级 public_report     —— 招股书/年报披露的每单平均金额（最可靠，可溯源）
      A 级 amap_targeted     —— 高德品牌定向搜索实测单杯价 × 每单杯数
      A 级 amap_converted    —— 高德周边采样实测同品牌单杯价 × 每单杯数
      C 级 industry_estimate —— 第三方行业「人均消费」榜（窄门餐眼），仅数量级参照。
        **A/B 都拿不到时才启用**，文案强制标注"行业参考，非披露非实测"。

    校正客单价为 None 的几种原因**互不相同**，口径必须分别说清——
    混在一起会让用户把"我没问成接口"读成"这附近没有这家店"。
    """
    prof_price = get_profile(category).get('price')
    if not brand:
        return {'校正客单价': None, '单杯价': None, '校正倍数': None, '证据': None,
                '口径': '非加盟场景（未指定品牌），沿用品类画像客单价',
                '口径来源': 'none', '来源': None, '取证时间': None, '抓取状态': 'not_requested'}

    # 自创品牌 / 不加盟：**定义上**就没有同品牌连锁门店可作参照，
    # 不是"附近没抓到"，也不需要为此打一次高德接口。直接说清口径。
    if is_self_brand(brand):
        return {'校正客单价': None, '单杯价': None, '校正倍数': None, '证据': None,
                '来源': None, '取证时间': None, '抓取状态': 'self_brand', '口径来源': 'none',
                '口径': (f'自创品牌/个体经营没有同品牌连锁门店可作价格参照，'
                         f'沿用品类画像客单价 ¥{prof_price}'
                         f'（这是口径定义，不是取数失败，也不是"附近没有门店"）')}

    # ① 公开数据先拿到手：它与高德取数成败无关，接口限流也照样能用
    pub = brand_order_value(brand)

    pois, meta = fetch_competitor_pois_ex(lng, lat, category,
                                          radius=radius, limit=25,
                                          use_cache=use_cache)
    src = ('缓存' if meta.get('cached') else '实时') if meta.get('ok') else None
    fetched_at = meta.get('fetched_at')
    base = {'来源': src, '取证时间': fetched_at}

    # ② 取数失败：有公开数据仍可用；没有则如实说明（绝不能写成"周边 0 家门店"）
    if not meta.get('ok'):
        info = meta.get('info') or meta.get('err') or '未知原因'
        code = meta.get('infocode')
        if meta.get('quota'):
            why = (f'高德**日调用配额已用尽**（{info}），今天是取不到数据了')
        elif code in RETRYABLE_INFOCODES:
            why = (f'高德接口**限流**（{info}，已退避重试 {meta.get("tries", "?")} 次仍失败），'
                   f'这是瞬时问题')
        else:
            why = f'高德接口未返回可用数据（{info}）'
        if pub:
            ov = pub['每单金额']
            ratio = round(prof_price / ov, 2) if (prof_price and ov) else None
            return dict(base, **{
                '校正客单价': ov, '单杯价': pub.get('单杯价'), '校正倍数': ratio,
                '证据': None, '抓取状态': 'public_only', '口径来源': 'public_report',
                '口径': (f'{why}，本次没能取到同品牌实时单杯价；但该品牌有**公开披露**的'
                         f'每单平均金额 ¥{ov:g}（{pub["来源"]}），'
                         f'本次直接按该值覆盖品类画像 ¥{prof_price}，不受本次取数失败影响。'
                         f'注意这不是"附近没有该品牌"。'),
            })
        local = _local_brand_presence(lng, lat, category, brand, radius)
        cross = ''
        if local:
            if local['门店数']:
                _names = '、'.join(str(s['name']) for s in local['样本'][:3])
                cross = (f'本地预抓取库显示该品牌在周边 {radius}m 内**有 '
                         f'{local["门店数"]} 家**门店（{_names}…），'
                         f'说明该品牌在当地确实存在，只是本次没能取到价格。'
                         f'建议按当地实际定价自行核实后再签约。')
            else:
                cross = (f'本地预抓取库也未在 {radius}m 内找到该品牌门店，'
                         f'但这同样不能替代实时数据，仅供参考。')
        return dict(base, **{
            '校正客单价': None, '单杯价': None, '校正倍数': None, '证据': None,
            '抓取状态': 'fetch_failed', '口径来源': 'none',
            '口径': (f'{why}——**这不是"附近没有该品牌"**。本次沿用品类画像假设 ¥{prof_price}，'
                     f'**该流水未按品牌真实定价校正，请勿据此签约**。{cross}'),
        })

    # ③ 取数成功：拿到同品牌单杯价（口径是"单杯"，不是"每单"）
    ev = same_brand_price(pois, brand)
    cup = ev['同品牌人均中位'] if ev else None

    # ③-a 有公开每单金额 → 直接用它（最可靠），单杯价降为对照
    if pub:
        ov = pub['每单金额']
        ratio = round(prof_price / ov, 2) if (prof_price and ov) else None
        if not ratio or 0.95 <= ratio <= 1.05:
            cmp_txt = '与品类画像基本一致'
        elif ratio > 1:
            cmp_txt = f'品类画像每单偏高 {ratio} 倍'
        else:
            cmp_txt = f'品类画像每单偏低 {round(1 / ratio, 2)} 倍'
        cross = ''
        if cup and pub.get('单杯价'):
            gap = abs(cup - pub['单杯价']) / pub['单杯价']
            cross = (f'；高德实测同品牌单杯价 ¥{cup:g}，与公开单杯价 '
                     f'¥{pub["单杯价"]:g} 相差 {gap:.0%}，互为印证')
        elif cup:
            cross = f'；高德实测同品牌单杯价 ¥{cup:g}'
        return dict(base, **{
            '校正客单价': ov, '单杯价': cup or pub.get('单杯价'), '校正倍数': ratio,
            '证据': ev, '抓取状态': 'ok', '口径来源': 'public_report',
            '口径': (f'已用**公开披露**的每单平均金额 ¥{ov:g}（{pub["来源"]}）'
                     f'覆盖品类画像假设 ¥{prof_price}（{cmp_txt}）{cross}'),
        })

    # ③-b【A 级补采】周边 1km 采样里同品牌不足 → 用**品牌定向搜索**补齐。
    #   实测宁波天一广场 25 家里没有 CoCo —— /place/around 固定只取最近 25 家，
    #   品牌扎堆时目标品牌可能压根不在采样内。定向搜索按品牌名查（5km + 距离排序），
    #   能拿到该品牌在候选点周边的真实单杯价：可实时、可溯源、不编造。
    same_costs = [p['cost'] for p in pois if p.get('brand') == brand and p.get('cost')]
    n_here = len(same_costs)
    tpois, tmeta, tgt_costs = [], {}, []
    if n_here < MIN_SAME_BRAND_SAMPLES:
        tpois, tmeta = fetch_brand_pois(brand, lng, lat)
        tgt_costs = [p['cost'] for p in tpois if p.get('cost')]
        if tgt_costs:
            same_costs = same_costs + tgt_costs
            here_note = (f'，周边 1km 只覆盖 {n_here} 家、已用**品牌定向搜索**'
                         f'（5km）补采 {len(tgt_costs)} 家')
            base['来源'] = '实时+定向补采'
        elif not tmeta.get('ok'):
            here_note = (f'；品牌定向搜索也未取到（'
                         f'{tmeta.get("info") or tmeta.get("err") or "未知原因"}）')
        else:
            here_note = '；品牌定向搜索在 5km 内也没有该品牌门店'
    else:
        here_note = ''

    if not same_costs:
        # ③-c【C 级兜底】A 级（高德实测/定向搜索）与 B 级（公开披露）都拿不到时，
        #   退到**第三方行业参考价**（窄门餐眼「人均消费」榜，2024-02-20 口径）。
        #   与 A/B 级**分级隔离**：口径来源单列 industry_estimate，文案必须写明
        #   "行业参考，非披露非实测"，禁止与披露值混用（用户拍板的分级口径）。
        ind = industry_price_reference(brand)
        if ind and ind.get('单杯价参考'):
            icup = ind['单杯价参考']
            iov = round(icup * UNIT_PER_ORDER, 2)
            iratio = round(prof_price / iov, 2) if (prof_price and iov) else None
            if not iratio or 0.95 <= iratio <= 1.05:
                icmp = '与品类画像基本一致'
            elif iratio > 1:
                icmp = f'品类画像每单偏高 {iratio} 倍'
            else:
                icmp = f'品类画像每单偏低 {round(1 / iratio, 2)} 倍'
            # A 级若是**取数失败**（而非"真的没有"）→ 提醒可重试；不能让瞬时限流
            # 被 C 级兜底"抹平"，否则用户会以为这就是该品牌在该商圈的定论。
            _retry = ''
            if tmeta and not tmeta.get('ok'):
                if tmeta.get('quota'):
                    _retry = ('（注意：A 级品牌定向搜索今天是**配额耗尽**，改日可重试以取到实测值）')
                elif tmeta.get('infocode') in RETRYABLE_INFOCODES:
                    _retry = ('（注意：A 级品牌定向搜索本次是**瞬时限流**，稍后重试即可取到实测值）')
                else:
                    _retry = '（注意：A 级品牌定向搜索本次未取到，可稍后重试）'
            return dict(base, **{
                '校正客单价': iov, '单杯价': icup, '校正倍数': iratio, '证据': None,
                '抓取状态': 'industry_ref', '口径来源': 'industry_estimate',
                '口径': (f'周边 {len(pois)} 家同类门店里没抓到「{brand}」的单杯价'
                         f'（高德未收录该品牌门店，或其 biz_ext.cost 为空）{here_note}，'
                         f'且该品牌无公开披露的每单金额。'
                         f'现退用**第三方行业参考**：{ind["来源"]}'
                         f'（{ind.get("数据截止") or "—"}）显示该品牌人均消费约 '
                         f'¥{icup:g}，按 {ind["口径"]} 视作**单杯价**，'
                         f'× 每单 {UNIT_PER_ORDER} 杯 ≈ ¥{iov:g}/单 覆盖品类画像 '
                         f'¥{prof_price}（{icmp}）{_retry}。'
                         f'⚠️ **这是行业参考，既非品牌披露也非我实测**，'
                         f'只作数量级参照、不与 A/B 级披露值混用，签约前请自行核实。'),
            })
        return dict(base, **{
            '校正客单价': None, '单杯价': None, '校正倍数': None, '证据': None,
            '抓取状态': 'no_same_brand', '口径来源': 'none',
            '口径': (f'周边 {len(pois)} 家同类门店里没抓到「{brand}」的单杯价'
                     f'（高德未收录该品牌门店，或其 biz_ext.cost 为空）{here_note}，'
                     f'且该品牌无公开披露的每单金额，也无第三方行业参考数据，'
                     f'沿用品类画像假设 ¥{prof_price}'),
        })

    cup = _pct(same_costs, 0.5)
    ev = {'品牌': brand, '样本数': len(same_costs),
          '同品牌人均中位': cup,
          '同品牌人均区间': (min(same_costs), max(same_costs)),
          '全品类人均中位': _pct([p['cost'] for p in pois if p.get('cost')], 0.5),
          '门店': ([p['name'] for p in pois if p.get('brand') == brand and p.get('cost')]
                   + [p['name'] for p in tpois if p.get('cost')])[:6]}

    if ev['样本数'] < MIN_SAME_BRAND_SAMPLES:
        # n=1：**显示但不生效**（用户拍板的取舍）—— 把"高德实测 ¥X"摆出来让人
        # 自己去核实，但不参与换算：单点进流水等于用噪声换伪精度。
        # 若还有 C 级第三方行业参考，一并列出供交叉核对（同样不生效）。
        _ind = industry_price_reference(brand)
        _ind_note = ''
        if _ind and _ind.get('单杯价参考'):
            _ind_note = (f'；另有第三方行业参考（{_ind["来源"]}，'
                         f'{_ind.get("数据截止") or "—"}）人均约 ¥{_ind["单杯价参考"]:g}，'
                         f'可一并核实（同为单杯口径）')
        return dict(base, **{
            '校正客单价': None, '单杯价': cup, '校正倍数': None, '证据': ev,
            '抓取状态': 'underpowered', '口径来源': 'none',
            '口径': (f'同品牌只有 {ev["样本数"]} 家能取到单杯价（{ev["门店"][0]} '
                     f'¥{cup:g}）{here_note}，不足 {MIN_SAME_BRAND_SAMPLES} 家、'
                     f'不构成换算依据，沿用品类画像假设 ¥{prof_price}；'
                     f'但这个值值得你自己去核实——注意它是**单杯价**，'
                     f'每单金额通常约为它的 {UNIT_PER_ORDER} 倍（一单不止一杯）'
                     f'{_ind_note}'),
        })
    ov = round(cup * UNIT_PER_ORDER, 2)
    ratio = round(prof_price / ov, 2) if (prof_price and ov) else None
    if not ratio or 0.95 <= ratio <= 1.05:
        cmp_txt = '与品类画像基本一致'
    elif ratio > 1:
        cmp_txt = f'品类画像每单偏高 {ratio} 倍'
    else:
        cmp_txt = f'品类画像每单偏低 {round(1 / ratio, 2)} 倍'
    return dict(base, **{
        '校正客单价': ov, '单杯价': cup, '校正倍数': ratio, '证据': ev,
        '抓取状态': 'ok',
        # amap_targeted = 样本主要来自品牌定向搜索（A 级）；amap_converted = 周边采样
        '口径来源': ('amap_targeted' if tgt_costs else 'amap_converted'),
        '口径': (f'该品牌无公开披露的每单金额；已用高德实测同品牌单杯价 ¥{cup:g}'
                 f'（{ev["样本数"]} 家门店中位{here_note}）× 每单 {UNIT_PER_ORDER} 杯 '
                 f'≈ ¥{ov:g}/单 覆盖品类画像 ¥{prof_price}（{cmp_txt}）。'
                 f'⚠️ 每单杯数由蜜雪 1.70、沪上阿姨 1.79 两点估计，'
                 f'高端品牌实际可能接近 1 杯/单，此处存在高估风险；'
                 f'样本：{"、".join(ev["门店"])}'),
    })


def _night_open(opentime: str) -> bool:
    """营业时间是否覆盖到 22:00 之后（夜宵/晚间客流能力）"""
    import re
    hours = re.findall(r'(\d{1,2}):(\d{2})', opentime or '')
    if len(hours) < 2:
        return False
    try:
        end_h = int(hours[-1][0])
        end_m = int(hours[-1][1])
    except Exception:
        return False
    # 跨零点（如 22:00-02:00）时最后一个时间会小于开店时间，视为夜间营业
    if end_h < 8:
        return True
    return (end_h * 60 + end_m) >= 22 * 60


def analyze_competitors(pois, category, brand=None, fetch_meta=None):
    """把竞品口碑字段聚合成结构化洞察 + 对模型假设的现实校验。
    brand: 加盟场景传入，客单价校验的参照组会优先用同品牌门店（见 same_brand_price）。
    fetch_meta: fetch_competitor_pois_ex 的 meta，用于标注数据来源与取证时间；
                空 pois + fetch_meta['ok']=False 时说明是取数失败，不是"没有竞品"。
    """
    profile = get_profile(category)
    assumed_price = profile.get('price')

    ratings = [p['rating'] for p in pois if p.get('rating')]
    costs = [p['cost'] for p in pois if p.get('cost')]
    brands = [p['brand'] for p in pois if p.get('brand')]
    dists = [p['distance'] for p in pois if p.get('distance') is not None]

    # 招牌产品热词（高德 tag 字段，反映真实在售爆品结构）
    hot = {}
    for p in pois:
        for t in p['tags']:
            t = t.strip()
            if 2 <= len(t) <= 12 and '首创' not in t:
                hot[t] = hot.get(t, 0) + 1
    hot_words = sorted(hot.items(), key=lambda kv: -kv[1])[:10]

    # 品牌集中度
    brand_cnt = {}
    for b in brands:
        brand_cnt[b] = brand_cnt.get(b, 0) + 1
    top_brands = sorted(brand_cnt.items(), key=lambda kv: -kv[1])[:5]
    chain_ratio = round(len(brands) / len(pois), 2) if pois else 0.0
    hhi = None
    if pois and brand_cnt:
        shares = [c / len(pois) for c in brand_cnt.values()]
        hhi = round(sum(s * s for s in shares) * 10000)   # 赫芬达尔指数(0~10000)

    cost_median = _pct(costs, 0.5)
    same = same_brand_price(pois, brand) if brand else None

    # 参照组优先级：同品牌 > 全品类。加盟场景下"我这个品牌在这卖多少钱"才是
    # 可比对象；全品类中位把 ¥7 的蜜雪和 ¥24 的奈雪混在一起，对谁都不准。
    ref_median, ref_group = None, None
    if same and same['样本数'] >= MIN_SAME_BRAND_SAMPLES:
        ref_median = same['同品牌人均中位']
        ref_group = f'同品牌（{brand}，{same["样本数"]} 家门店高德真实人均）'
    elif cost_median:
        ref_median = cost_median
        ref_group = '全品类' + (f'（同品牌仅 {same["样本数"]} 家有人均，不足 '
                              f'{MIN_SAME_BRAND_SAMPLES} 家，参照组偏粗）' if same else
                              '（未指定品牌）')

    price_check = None
    if ref_median and assumed_price:
        gap = (assumed_price - ref_median) / ref_median
        # ⚠️ 口径警示（2026-09-15 补）：参照组来自高德 biz_ext.cost（= 人均消费，
        #    茶饮类目实测 ≈ **单杯价**），而 assumed_price 是引擎的**每单金额**。
        #    两者量纲不同（一杯 ≠ 一单），倍数只能表方向、不能当精确偏差。
        #    不把这句写进"说明"，用户就会把"高出 129%"当成精确结论——
        #    详见 docs/品牌级公开数据与客单价口径修正.md。
        _caliber = ('（⚠️ 口径提示：参照组是高德"人均消费/单杯价"口径，'
                    '模型假设是"每单金额"口径——一杯 ≠ 一单，'
                    '这个倍数只表方向，不能当精确偏差；要精确比价需按该品牌每单杯数折算）')
        if gap > 0.15:
            tone = '偏乐观'
            note = (f'模型假设客单价 ¥{assumed_price}/单，但{ref_group}仅 ¥{ref_median}'
                    f'（高出 {gap:.0%}）——流水估算可能偏高，签约前请按当地实际定价复核{_caliber}')
        elif gap < -0.15:
            tone = '偏保守'
            note = (f'模型假设客单价 ¥{assumed_price}/单，{ref_group} ¥{ref_median}'
                    f'（低 {abs(gap):.0%}）——当地价格带更高，流水估算可能偏保守{_caliber}')
        else:
            tone = '基本吻合'
            note = (f'模型假设客单价 ¥{assumed_price}/单，{ref_group} ¥{ref_median}，'
                    f'偏差 {gap:+.0%} 在可接受范围{_caliber}')
        price_check = {'假设客单价': assumed_price, '真实人均中位': ref_median,
                       '参照组': ref_group, '同品牌证据': same,
                       '全品类人均中位': cost_median,
                       '假设客单价口径': '每单金额',
                       '参照组口径': '高德人均消费（茶饮类目实测≈单杯价）',
                       '偏差': round(gap, 3), '判断': tone, '说明': note}

    # 团购/优惠/收藏字段实测常年全 0（高德已不再回填），全 0 时视为"字段不可用"，
    # 不能当成"没人做团购"的机会点——那会误导用户
    def _field_or_none(key):
        vals = [p[key] for p in pois]
        if not vals or max(vals) == 0:
            return None
        return sum(1 for v in vals if v > 0)

    groupbuy_active = _field_or_none('groupbuy')
    discount_active = _field_or_none('discount')

    # 取数溯源（必须在 result 字面量之前算好——在字面量内部引用 result 会 NameError，
    # 而且因为条件表达式是惰性的，这个错只在 fetch_meta.ok=True 时才炸，
    # 也就是只在真实应用路径上炸、单元测试反而看不出来）
    if fetch_meta and fetch_meta.get('ok'):
        _src = '缓存' if fetch_meta.get('cached') else '实时'
        _st = 'ok'
        _provenance = (f'本次数据为{_src}，取证时间 {fetch_meta.get("fetched_at") or "—"}；'
                       f'结果已按坐标+品类冻结缓存，同一输入复算结果一致。')
    elif fetch_meta:
        _src, _st = '取数失败', 'fetch_failed'
        _provenance = '本次**未取到数据**，样本 0 不代表该商圈没有竞品。'
    else:
        _src, _st = '未标注', 'unlabeled'
        _provenance = '本次调用未携带取数溯源信息（多为直接传入 POI 的测试调用）。'

    result = {
        '品类': category,
        '样本数': len(pois),
        '数据来源': _src,
        '取证时间': (fetch_meta or {}).get('fetched_at'),
        '抓取状态': _st,
        '有口碑分样本': len(ratings),
        '有客单价样本': len(costs),
        '口碑分': {
            '均值': round(statistics.mean(ratings), 2) if ratings else None,
            '中位': _pct(ratings, 0.5),
            '最低': min(ratings) if ratings else None,
            '最高': max(ratings) if ratings else None,
        } if ratings else {},
        '客单价带': {
            'P25': _pct(costs, 0.25), '中位': cost_median, 'P75': _pct(costs, 0.75),
            '最低': min(costs) if costs else None, '最高': max(costs) if costs else None,
        } if costs else {},
        '连锁占比': chain_ratio,
        '品牌集中度HHI': hhi,
        '头部品牌': [{'品牌': b, '门店数': c} for b, c in top_brands],
        '团购活跃门店数': groupbuy_active,
        '优惠活跃门店数': discount_active,
        '夜间营业门店数': sum(1 for p in pois if _night_open(p['opentime'])),
        '平均距离(m)': round(statistics.mean(dists)) if dists else None,
        '招牌热词': [{'词': w, '出现门店数': c} for w, c in hot_words],
        '客单价现实校验': price_check,
        '明细': pois[:15],
        '数据局限': DATA_LIMIT + ('团购/优惠/收藏数字段高德已不回填（全为 0），不纳入判断；'
                                 if groupbuy_active is None else '') + _provenance,
    }

    # 结论性洞察（规则化，供 LLM 引用，不让 LLM 自己编）
    insights = []
    if fetch_meta is not None and not fetch_meta.get('ok'):
        insights.append('本次**未能取到**周边竞品数据（'
                        + (fetch_meta.get('info') or fetch_meta.get('err') or '未知原因')
                        + '），以下所有"样本 0"结论都不成立，请勿据此判断该商圈没有竞品。')
    if ratings:
        avg = statistics.mean(ratings)
        if avg >= 4.3:
            insights.append(f'周边同类口碑普遍偏高（均分 {avg:.2f}），说明这个商圈的客群对品质敏感，'
                            '低价低质打法容易被比下去')
        elif avg < 3.8:
            insights.append(f'周边同类口碑偏弱（均分 {avg:.2f}），存在用产品与服务拉开差距的机会')
        else:
            insights.append(f'周边同类口碑中等（均分 {avg:.2f}），拼的是位置与效率，不是差异化')
    if hhi is not None:
        if hhi >= 2500:
            insights.append(f'品牌集中度高（HHI {hhi}），头部品牌垄断客流，新进入者要么加盟头部、要么错位竞争')
        elif hhi <= 1000:
            insights.append(f'品牌格局分散（HHI {hhi}），没有绝对头部，自创品牌仍有生存空间')
    if pois:
        night = sum(1 for p in pois if _night_open(p['opentime']))
        if night / len(pois) >= 0.5:
            insights.append(f'{night}/{len(pois)} 家竞品营业到 22 点后，晚间客流是真实存在的，'
                            '你的营业时间不能太短')
        if groupbuy_active is not None and groupbuy_active / len(pois) >= 0.4:
            insights.append(f'{groupbuy_active}/{len(pois)} 家竞品在做团购，价格战已经开打，'
                            '纯靠正价卖的日子不好过，要把团购成本算进流水预期')
    if price_check:
        insights.append(f'客单价假设校验（{price_check["判断"]}）：{price_check["说明"]}')
    result['洞察'] = insights
    return result


def competitor_brief(lng, lat, category, radius=1000, limit=25, brand=None):
    """一步到位：抓取 + 分析。返回 (分析 dict, 可注入 prompt 的文字摘要)。
    brand: 加盟场景传入，客单价校验的参照组会优先用同品牌门店而非全品类。
    """
    pois, meta = fetch_competitor_pois_ex(lng, lat, category, radius, limit)
    if not pois:
        # 取数失败与"周边真没有同类店"必须分开说——前者不能推出后者
        if not meta.get('ok'):
            info = meta.get('info') or meta.get('err') or '未知原因'
            tag = '今日配额已用尽' if meta.get('quota') else '接口限流/不可用'
            return None, (f'未能获取周边竞品口碑数据（{tag}：{info}）。'
                          f'**这不代表该商圈没有竞品**，而是本次没取到数。'
                          f'请不要编造口碑分或人均消费，也不要断言"该区域竞争小"。')
        return None, (f'高德接口返回成功，但周边 {radius}m 内确实没有搜索到同类门店'
                      f'（关键词：{get_profile(category)["poi_keywords"][0]}）。'
                      f'这可能是真实的空白市场，也可能是高德未收录，'
                      f'建议实地走访核实后再下结论。')
    a = analyze_competitors(pois, category, brand, fetch_meta=meta)
    lines = [f'周边 {radius}m 内同类竞品口碑画像（样本 {a["样本数"]} 家，高德公开字段，'
             f'{a.get("数据来源")}取证 {a.get("取证时间") or "—"}）：']
    if a['口碑分']:
        r = a['口碑分']
        lines.append(f'- 口碑分：均 {r["均值"]}、中位 {r["中位"]}、区间 {r["最低"]}~{r["最高"]}'
                     f'（{a["有口碑分样本"]} 家有分）')
    if a['客单价带']:
        c = a['客单价带']
        lines.append(f'- 人均价格带：P25 ¥{c["P25"]} / 中位 ¥{c["中位"]} / P75 ¥{c["P75"]}'
                     f'（{a["有客单价样本"]} 家有价）')
    lines.append(f'- 连锁占比 {a["连锁占比"]:.0%}，品牌集中度 HHI {a["品牌集中度HHI"]}，'
                 f'头部品牌：' + ('、'.join(f'{b["品牌"]}({b["门店数"]}家)' for b in a['头部品牌'][:3]) or '无明显连锁'))
    gb = a['团购活跃门店数']
    gb_txt = f'团购活跃 {gb} 家 / ' if gb is not None else '团购字段不可用（高德未回填） / '
    lines.append(f'- {gb_txt}夜间营业 {a["夜间营业门店数"]} 家 / '
                 f'平均距离 {a["平均距离(m)"]}m')
    if a['招牌热词']:
        lines.append('- 招牌热销词：' + '、'.join(w['词'] for w in a['招牌热词'][:8]))
    if a.get('客单价现实校验'):
        chk = a['客单价现实校验']
        # 口径必须随数字一起给出：参照组是高德"人均/单杯价"，假设是"每单金额"，
        # 一杯 ≠ 一单。证据包里不写，LLM 就可能把百分比当成精确偏差转述给用户。
        lines.append(f'- 客单价现实校验：{chk["判断"]}（假设 ¥{chk["假设客单价"]}/单 vs '
                     f'参照组高德人均 ¥{chk["真实人均中位"]}（单杯价口径），'
                     f'偏差 {chk["偏差"]:+.0%}——口径不同，仅表方向）')
    for ins in a['洞察']:
        lines.append(f'- 洞察：{ins}')
    lines.append(f'- 数据局限：{a["数据局限"]}')
    return a, '\n'.join(lines)


if __name__ == '__main__':
    sys.stdout.reconfigure(errors='replace')
    import json
    # 宁波天一广场附近奶茶竞品
    a, txt = competitor_brief(121.5517, 29.8742, '奶茶', radius=1000, limit=25)
    print(txt)
    if a:
        print('\n客单价现实校验:', json.dumps(a['客单价现实校验'], ensure_ascii=False))
        print('明细前3:', json.dumps(a['明细'][:3], ensure_ascii=False)[:400])
