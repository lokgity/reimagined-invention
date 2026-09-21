# -*- coding: utf-8 -*-
"""road_sim.py —— 「仿真数据看板」的数据构造（小人沿马路走）
================================================================================
它回答的问题是：**这个铺位的客流，是从哪几条路走过来的、要走多远？**

和别的"客流热力图"不同，这里的小人**沿真实道路折线移动**，不画直线：

  · 选点口径 = 引擎**同一条** `scoring.query_pois`（步行路网 ≤ 分析半径）
    ⇒ 看板上出现的 POI，和真正进 Huff 分母/分子的是**同一批**（不另起一套）
  · 轨迹几何 = `data.road_path` 冻结的 `/v3/direction/walking` 折线
    ⇒ 可离线复现，且距离与 `road_distance.db` 同族接口、逐位一致（实测 622.0 = 622.0）
  · 直线 vs 路网**两个数都给出**，并在画面上标注 —— 让"绕路"看得见

⚠️ 本节只做**可视化**：不参与 D/P 计算，不改任何结论。
   它存在的意义是"把已经生效的路网口径**画出来**"，而不是再算一遍模型。
"""
import math
import re


# ---------------------------------------------------------------- 投影
def deg2num(lat, lng, zoom):
    """WGS84 → 瓦片浮点坐标（与 app_chainlit._deg2num 同式，刻意保持一致）。"""
    n = 2.0 ** zoom
    x = (lng + 180.0) / 360.0 * n
    y = (1.0 - math.log(math.tan(math.radians(lat)) +
                        1.0 / math.cos(math.radians(lat))) / math.pi) / 2.0 * n
    return x, y


def map_geometry(lat, lng, radius, grid=3, tile=256,
                 min_zoom=13, max_zoom=17, width_frac=0.30):
    """地图图的几何参数 —— **唯一真源**，`_build_shop_map_png` 与仿真看板都调它。

    返回 dict(zoom, x0, y0, img_w, tile, mpd)。
    历史上两处各算一遍是"同一件事几个表面"的典型，这里收敛成一处。
    """
    img_w = tile * grid
    mpd0 = 156543.03392 * math.cos(math.radians(lat))
    target_mpd = radius / (width_frac * img_w) if radius else 3.0
    zoom = int(round(math.log2(mpd0 / target_mpd)))
    zoom = max(min_zoom, min(max_zoom, zoom))
    xf, yf = deg2num(lat, lng, zoom)
    return dict(zoom=zoom, x0=int(xf) - 1, y0=int(yf) - 1,
                img_w=img_w, tile=tile, mpd=target_mpd)


def project(lng, lat, geo):
    """经纬度 → 地图图内像素坐标（前端直接用这个，不在 JS 里重算投影）。"""
    fx, fy = deg2num(lat, lng, geo['zoom'])
    return [round((fx - geo['x0']) * geo['tile'], 1),
            round((fy - geo['y0']) * geo['tile'], 1)]


# ---------------------------------------------------------------- 选点
def _target_labels(profile):
    out = []
    for t in (profile or {}).get('target_pois', []):
        lab = (t.get('label') or '').strip()
        if lab and lab not in out:
            out.append(lab)
    return out


def pick_targets(category, lng, lat, radius, limit=10, labels=None):
    """按**步行路网距离**升序取最近的客群 POI。

    ⚠️ 走 `scoring.query_pois`（引擎口径），**不是** `query_within`（直线）。
       这是本模块与旧地图实现的根差别：旧实现直接用直线选点画点，
       于是"地图上的点"与"进模型算的点"不是同一批（口径不一致）。
    """
    from engine.scoring import query_pois
    from data.query import haversine
    got = []
    seen = set()
    for lab in (labels or []):
        try:
            pois = query_pois(lab, lng, lat, radius)
        except Exception:
            pois = []
        for p in pois:
            k = (round(p['lng'], 5), round(p['lat'], 5))
            if k in seen:
                continue
            seen.add(k)
            got.append({
                'name': (p.get('name') or '')[:20],
                'cat': lab,
                'road_m': int(p.get('distance') or 0),
                'straight_m': int(round(haversine(lng, lat, p['lng'], p['lat']))),
                'lng': p['lng'], 'lat': p['lat'],
                '口径': p.get('距离口径', '步行路网'),
            })
    got.sort(key=lambda x: x['road_m'])
    return got[:limit]


# ---------------------------------------------------------------- 主构造
def build_sim(category, lng, lat, radius, profile=None, limit=10,
              geo=None, want_paths=True):
    """构造仿真看板数据（纯本地；仅在路径库缺该对时联网抓一次并冻结）。"""
    labels = _target_labels(profile) or ['学校', '办公', '社区', '商圈']
    targets = pick_targets(category, lng, lat, radius, limit=limit, labels=labels)
    if not targets:
        return {'ok': False, '原因': '分析半径内没有可用客群 POI（本地库覆盖不足）'}

    geo = geo or map_geometry(lat, lng, radius)
    path_stat = {'请求': 0, '取到': 0, '降级': 0, 'API调用': 0}
    if want_paths:
        from data import road_path
        dest = (lng, lat)
        orgs = [(t['lng'], t['lat']) for t in targets]
        path_stat['请求'] = len(orgs)
        before = road_path.calls()['n']
        paths = road_path.fetch_and_store(dest, orgs)
        path_stat['API调用'] = road_path.calls()['n'] - before
        path_stat['失败'] = road_path.calls()['fail']
        for t in targets:
            k = (road_path.q(t['lng']), road_path.q(t['lat']))
            rp = paths.get(k)
            if rp:
                t['path_px'] = [project(x, y, geo) for x, y in rp['points']]
                t['seconds'] = int(rp.get('seconds') or 0)
                t['instructions'] = rp.get('instructions') or []
                path_stat['取到'] += 1
            else:
                # 取不到 → 不留假轨迹，如实置空并计数（红线 1/4）
                t['path_px'] = []
                t['seconds'] = None
                t['降级原因'] = '路径库未命中且接口取数失败（>5km / 限流 / 配额）'
                path_stat['降级'] += 1
    else:
        for t in targets:
            t['path_px'] = []
            path_stat['降级'] = len(targets)

    store_px = project(lng, lat, geo)
    for t in targets:
        t['ratio'] = round(t['road_m'] / t['straight_m'], 2) if t['straight_m'] else None

    return {
        'ok': True,
        'geo': geo,
        'store_px': store_px,
        'targets': targets,
        'meta': {
            '半径m': radius,
            '选点口径': '步行路网距离（scoring.query_pois，与模型同一批点）',
            '轨迹口径': '高德步行规划 /v3/direction/walking 折线（冻结于 road_path.db）',
            '路径统计': path_stat,
            '步行速度_ms': 1.2,
            '说明': ('小人沿**真实道路折线**从客群走向本铺；轨迹只用于可视化，'
                     '不参与 D/P 计算。'),
        },
    }


# ================================================================
# 仿真大屏（**自绘场景**，2026-09-21 重做）
# ================================================================
# 策原话（09-20 10:17 / 09-21 10:16 两次强调）：
#   「做成一个**一直动态的数据大屏**，用**小人的多少来代表客流量的大小**，
#     然后**根据边上有多少家竞品来分流**让小人一直走动」
#   「你要根据这个热力图的地图**自己实时生成新的地图**，简化不必要的建筑，
#     只留下开店的店铺、竞品店铺、还有人流量的来源（小区/学校/商城/写字楼），
#     然后小人从这里出来后沿着马路走到各个店铺里，要求**一直是动态的**」
#
# ⇒ 所以**不再用高德底图**。底图里全是建筑和路名，小人贴在上面根本看不清谁去哪；
#   大屏只画**关系**：马路骨架 + 三类节点 + 持续走动的小人。
#
# 口径**全部来自引擎**，不另起一套（这是本模块存在的纪律）：
#   · 来源类别与客流权重 = `profile['target_pois'][].weight`
#     —— 就是引擎算需求池 D 用的那套权重（奶茶：学校 .35 / 办公 .25 / 商圈 .20 / 社区 .20）
#   · 来源点位 = `scoring.query_pois`（步行路网 ≤ 半径，与 D/P 同一批点）
#   · 竞品店铺 = `scoring.query_pois(同品类)` —— **与 Huff 分母是同一批**
#   · 轨迹 = `data.road_path` 冻结的高德步行折线
#   · 分流 = Huff 引力 `g_j = S_j / (d_j + d0)^λ`（λ=2.0 / d0=50m，与 `scoring` 同常量）
#
# ⚠️ 本函数**只做可视化**：不参与 D/P 计算、不改任何结论。
#    分流是"来源 → 各店"的引力分配，引擎的 P 是"本铺 → 各竞品"的捕获份额，
#    两者**不是同一个量**，画面上必须分开标注，不许混着讲。

# 来源类别 → 画面样式（颜色 + 图标名由前端映射）
SOURCE_STYLE = {
    '学校': {'color': '#f59e0b', 'icon': '🎓', 'short': '学校'},
    '办公': {'color': '#10b981', 'icon': '🏢', 'short': '写字楼'},
    '商圈': {'color': '#ef4444', 'icon': '🛍', 'short': '商场'},
    '社区': {'color': '#8b5cf6', 'icon': '🏘', 'short': '小区'},
    '通勤': {'color': '#06b6d4', 'icon': '🚇', 'short': '通勤'},
}


def _brand_of(name):
    """店名 → (识别出的品牌名, 引力 S)。识别不出返回 (None, 1.0)。"""
    try:
        from engine.brands import brand_attractiveness
        return brand_attractiveness(name or '')
    except Exception:
        return None, 1.0


def _shop_s(df):
    """取引力 S：优先显式传出，否则按品牌名识别，最后退化 1.0。"""
    s = df.get('S')
    if s:
        return float(s)
    return float(_brand_of(df.get('name'))[1] or 1.0)


def build_board(category, lng, lat, radius, profile=None, own_s=None, brand=None,
                max_sources=8, max_rivals=6, total_figures=150, want_paths=True):
    """构造**自绘**仿真大屏场景：人流来源 →（沿马路）→ 本铺 / 竞品店铺。

    返回（不是 build_sim 的那个结构，前端另有渲染器）：
      geo / store / sources / rivals / roads / flows / meta
    """
    from engine.scoring import LAMBDA, D0, query_pois
    from data.query import haversine
    from data import road_path

    geo = map_geometry(lat, lng, radius)
    store_px = project(lng, lat, geo)

    # ---- ① 店铺集合：本铺 + 最近的若干竞品（同一批 query_pois，与 Huff 分母一致）
    shops = [{
        'kind': 'store', 'name': (brand or '本铺')[:20], 'brand': brand or '',
        'lng': lng, 'lat': lat, 'px': store_px, 'road_m': 0,
        'S': float(own_s) if own_s else _shop_s({'name': brand or ''}),
    }]
    rival_stat = {'候选': 0, '采用': 0}
    try:
        cand = query_pois(category, lng, lat, radius)
    except Exception:
        cand = []
    rival_stat['候选'] = len(cand)
    for p in sorted(cand, key=lambda x: x.get('distance') or 0):
        if len(shops) - 1 >= max_rivals:
            break
        _bn, _ = _brand_of(p.get('name') or '')
        shops.append({
            'kind': 'rival', 'name': (p.get('name') or '')[:20],
            # 品牌名**识别出来**再上屏：POI 没有「品牌」字段，直接用 name 会是
            # "茶百道(杭州湖滨银泰in77店)" 这种整串，牌子上根本放不下（2026-09-21 实测被截成"茶百道(杭州…"）
            # 识别不出（如"东方墨兰"不在品牌表）→ 退回**括号前的店名**，比整串可用
            'brand': _bn or re.split(r'[（(]', p.get('name') or '')[0][:8],
            'lng': p['lng'], 'lat': p['lat'], 'px': project(p['lng'], p['lat'], geo),
            'road_m': int(p.get('distance') or 0), 'S': _shop_s(p),
        })
    rival_stat['采用'] = len(shops) - 1

    # ---- ② 人流来源：按 profile 的类别**分别**取最近的，保留类别权重
    tps = [t for t in ((profile or {}).get('target_pois') or []) if t.get('label')]
    cats = [(t['label'], float(t.get('weight') or 0)) for t in tps]
    wsum = sum(w for _, w in cats) or 1.0
    # 每类至少取 2 个：奶茶 4 类 ⇒ 8//4=2。只取 1 个时画面只剩 2~4 个来源牌，
    # 看不出"人流是从好几个地方来的"（2026-09-21 实测武林广场只出 2 个）。
    per_cat = max(2, max_sources // max(1, len(cats))) if cats else 0

    sources = []
    seen = set()
    src_stat = {'类别数': len(cats), '每类取': per_cat, '候选': 0, '采用': 0}
    for lab, w in cats:
        try:
            pois = query_pois(lab, lng, lat, radius)
        except Exception:
            pois = []
        src_stat['候选'] += len(pois)
        got = 0
        for p in sorted(pois, key=lambda x: x.get('distance') or 0):
            if got >= per_cat:
                break
            k = (round(p['lng'], 5), round(p['lat'], 5))
            if k in seen:
                continue
            seen.add(k)
            st = SOURCE_STYLE.get(lab, {'color': '#3b82f6', 'icon': '📍', 'short': lab})
            sources.append({
                'cat': lab, 'short': st['short'], 'color': st['color'],
                'name': (p.get('name') or '')[:20],
                'lng': p['lng'], 'lat': p['lat'], 'px': project(p['lng'], p['lat'], geo),
                'w': w, 'to_store_m': int(p.get('distance') or 0),
                'straight_m': int(round(haversine(lng, lat, p['lng'], p['lat']))),
            })
            got += 1
    src_stat['采用'] = len(sources)

    # ---- ③ 每条 来源→店 的真实步行折线
    path_stat = {'请求': 0, '取到': 0, '降级': 0, 'API调用': 0}
    held = {}
    if want_paths and sources:
        before = road_path.calls()['n']
        for j, shop in enumerate(shops):
            orgs = [(s['lng'], s['lat']) for s in sources]
            path_stat['请求'] += len(orgs)
            got = road_path.fetch_and_store((shop['lng'], shop['lat']), orgs)
            held[j] = got
        path_stat['API调用'] = road_path.calls()['n'] - before
        path_stat['失败'] = road_path.calls()['fail']
        # 真正拿到折线的条数（命中冻结库 + 本轮新抓的都算）
        path_stat['取到'] = sum(len(m or {}) for m in held.values())
        path_stat['降级'] = max(0, path_stat['请求'] - path_stat['取到'])

    def _pts(j, s):
        """取 来源 s → 店 j 的像素折线；取不到返回 None（**不留假轨迹**，红线 1）。"""
        if not want_paths:
            return None
        rp = (held.get(j) or {}).get((road_path.q(s['lng']), road_path.q(s['lat'])))
        if not rp:
            return None
        return [project(x, y, geo) for x, y in rp['points']], int(rp.get('meters') or 0)

    # ---- ④ 分流：Huff 引力（与引擎同 λ / d0）
    flows = []
    for si, s in enumerate(sources):
        g, meta_j = [], []
        for j, shop in enumerate(shops):
            r = _pts(j, s) if want_paths else None
            if r:
                pts, road_m = r
            else:
                # 降级：用直线距离代入引力（画面上**不画线**，只用于分流权重）
                pts, road_m = None, int(round(haversine(s['lng'], s['lat'],
                                                        shop['lng'], shop['lat'])))
            gj = shop['S'] / ((road_m + D0) ** LAMBDA)
            g.append(gj)
            meta_j.append((pts, road_m))
        tot = sum(g) or 1.0
        for j, (pts, road_m) in enumerate(meta_j):
            share = g[j] / tot
            flows.append({
                'si': si, 'si_kind': 'store' if j == 0 else 'rival', 'si_idx': j,
                'share': round(share, 4), 'road_m': road_m,
                'pts': pts, '直线回退': pts is None,
            })

    # ---- ⑤ 小人数：先按**类别权重**分总量，再在类别内按到达本铺的引力归一
    fig_by_src = [0.0] * len(sources)
    if sources:
        for lab, w in cats:
            idx = [i for i, s in enumerate(sources) if s['cat'] == lab]
            if not idx:
                continue
            pool = total_figures * w / wsum
            gg = [shops[0]['S'] / ((sources[i]['to_store_m'] + D0) ** LAMBDA) for i in idx]
            tg = sum(gg) or 1.0
            for k, i in enumerate(idx):
                fig_by_src[i] = pool * (gg[k] / tg)

    # ---- ⑤b 「到本铺比例」：**必须按来源客流权重加权**，不能把各来源的份额相加
    #   ⚠️ 2026-09-21 策发现 HUD 显示 >100%：原实现是 `Σ share`，
    #      而 share 是**每个来源内部**归一化的份额（每个来源 Σshare = 1）——
    #      4 个来源各 30% 一加就是 120%。分母口径对不上，属于算错。
    #      正确口径：Σ(来源客流权重 × 该来源到本铺份额) / Σ(来源客流权重)。
    #   ⚠️ 必须在**裁剪之前**算：裁剪只决定画哪些线，不能影响统计数字。
    _ss = {f['si']: f['share'] for f in flows if f['si_kind'] == 'store'}
    _tf = sum(fig_by_src) or 1.0
    to_store = sum(fig_by_src[i] * _ss.get(i, 0.0) for i in range(len(sources))) / _tf

    # ⚠️ 每个来源**只保留引力最强的 3 个去向**（且强制保留到本铺的那条）；
    #    **另外兜底：每个店铺至少要有一条路连过去**。
    #    不裁的话 8 来源 × 7 店 = 56 条线，画面上糊成一团，反而看不出分流
    #    （2026-09-21 实测 42 条流向时第一版就这样）。
    #    ⚠️ 但只裁不补会出另一种毛病：某家竞品在**所有来源的 top3 里都没排上**，
    #       于是画面上它孤零零挂着、一条路都没有 —— 策当场就发现了
    #       （"有些店铺怎么没有道路可以通过去，小人也没走过去"）。
    by_src = {}
    for f in flows:
        by_src.setdefault(f['si'], []).append(f)
    keep = set()
    for si, fs in by_src.items():
        fs.sort(key=lambda x: -x['share'])
        for f in fs[:3]:
            keep.add(id(f))
        for f in fs:
            if f['si_kind'] == 'store':          # 到本铺的那条一定要在
                keep.add(id(f))
    # 兜底：逐店铺检查，谁一条都没留下，就把**权重最大**的那条补上
    _by_shop = {}
    for f in flows:
        _by_shop.setdefault((f['si_kind'], f['si_idx']), []).append(f)
    for k, fs in _by_shop.items():
        if not any(id(f) in keep for f in fs):
            best = max(fs, key=lambda f: fig_by_src[f['si']] * f['share'])
            keep.add(id(best))
    flows = [f for f in flows if id(f) in keep]

    for f in flows:
        n = fig_by_src[f['si']] * f['share']
        # 少于半个小人的流向**不画**（画 0.3 个人只会糊成一团），但权重如实留在数据里
        f['figures'] = int(round(n)) if n >= 0.5 else 0
    flows = [f for f in flows if f['figures'] > 0 and f['pts']]

    # ---- ⑥ 马路骨架：flows 折线去重（同一条路走的人多 → 前面线更粗，前端按次数算）
    def _key(pts):
        return '|'.join('%d,%d' % (p[0], p[1]) for p in pts)

    roads, rk = [], {}
    for f in flows:
        k = _key(f['pts'])
        if k in rk:
            rk[k] += 1
            continue
        rk[k] = 1
        roads.append({'pts': f['pts'], 'count': 1})
    for r in roads:
        r['count'] = rk[_key(r['pts'])]

    return {
        'ok': bool(sources),
        'geo': geo,
        'store': shops[0],
        'sources': sources,
        'rivals': shops[1:],
        'roads': roads,
        'flows': flows,
        'meta': {
            '半径m': radius,
            # 半径在图上的像素长度。⚠️ 必须用**真实** mpd（zoom 取整后的），
            # 不能用 map_geometry 返回的 target_mpd（那是取整前的目标值，会差一档）。
            '半径像素': round(radius / (156543.03392 * math.cos(math.radians(lat))
                                      / (2.0 ** geo['zoom'])), 1),
            '来源类别': [{'label': l, 'weight': w, 'short': SOURCE_STYLE.get(l, {}).get('short', l)}
                         for l, w in cats],
            '来源统计': src_stat,
            '竞品统计': rival_stat,
            '路径统计': path_stat,
            '小人总数': sum(f['figures'] for f in flows),
            # 「到本铺比例」按来源客流权重加权（不是 Σshare，见 ⑤b）
            '到本铺比例': round(to_store, 4),
            '客流权重口径': ('来源类别权重取自 profile.target_pois[].weight'
                             '（引擎算需求池 D 用的同一套）；小人数 = 类别权重 × 类别内引力归一'),
            '分流口径': ('Huff 引力 g_j = S_j/(d_j+d0)^λ，S_j 为品牌引力、d_j 为**步行路网**距离，'
                         'λ=2.0 / d0=50m 与引擎同常量。**这是"来源→各店"的引力分配，'
                         '不是引擎的捕获份额 P**，只用于可视化。'),
            '轨迹口径': '高德步行规划 /v3/direction/walking 折线（冻结于 road_path.db）',
            '说明': ('自绘示意图：只画马路骨架 + 人流来源 + 本铺 + 竞品店铺，'
                     '不叠真实底图。小人从来源出发、沿真实道路折线走进店里，循环不止。'
                     '⚠️ 只做可视化，不参与 D/P 计算。'),
            '原因': '分析半径内没有可用客群 POI（本地库覆盖不足）' if not sources else '',
        },
    }
