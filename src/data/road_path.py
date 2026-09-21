# -*- coding: utf-8 -*-
"""road_path.py —— 步行**路径几何**的冻结库（供仿真看板「小人沿马路走」用）
================================================================================
为什么需要它
------------------------------------------------------------------
`data/road.py` 只冻结了**距离**（标量），画不出"沿马路走"的轨迹。
`/v3/direction/walking` 能返回**真实道路折线**（分 step，带 street 名），
实测：天一广场 → 都市仁和中心 直走 437m、**步行路网 622m / 6 段 / 55 个折点**，
且该接口的 `distance` 与 `road_distance.db` 里的值**逐位一致（622.0）** —— 同族接口、口径自洽。

设计（与 `road.py` 完全同源的三条纪律）
------------------------------------------------------------------
1. **冻结**：抓一次落 `data/road_path.db`，之后**只读本地**（0 次 API、可复现、可离线）。
2. **不猜**：取不到（>5km 的 `OVER_DIRECTION_RANGE`、限流、配额）→ **明确抛错**，
   由调用方降级并留痕，**绝不返回空折线冒充"这条路是直的"**。
3. **带来源**：每条路径记 `fetched_at`，便于回答"这条轨迹什么时候抓的"。

⚠️ 步行路径是**有向**的（单行道、过街天桥等），所以键按 (origin → destination) 存，
   不做无向归一（这一点与 `road.py` 的距离不同，那边路网距离近似对称）。
"""
import json
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / 'data' / 'road_path.db'

WALK_MAX_M = 5000          # 与 road.py 同：高德步行规划仅支持 5km 内
BATCH_SLEEP = 0.25
_CALLS = {'n': 0, 'fail': 0}


def q(v):
    """坐标量化到 1e-5°（≈1.1m）—— 与 road_distance.db 同精度。"""
    return round(float(v) + 0.0, 5)


def _conn():
    c = sqlite3.connect(str(DB_PATH))
    c.execute('''CREATE TABLE IF NOT EXISTS path(
                     olng REAL, olat REAL, dlng REAL, dlat REAL,
                     meters REAL, seconds REAL, points TEXT, fetched_at TEXT,
                     PRIMARY KEY(olng, olat, dlng, dlat))''')
    return c


def stats():
    c = _conn()
    n = c.execute('SELECT COUNT(*) FROM path').fetchone()[0]
    c.close()
    return n


def calls():
    return dict(_CALLS)


def lookup(origin, dest):
    """查冻结库；未命中返回 None。origin/dest 均为 (lng, lat)。"""
    c = _conn()
    row = c.execute(
        'SELECT meters, seconds, points FROM path '
        'WHERE olng=? AND olat=? AND dlng=? AND dlat=?',
        (q(origin[0]), q(origin[1]), q(dest[0]), q(dest[1]))).fetchone()
    c.close()
    if not row:
        return None
    return {'meters': row[0], 'seconds': row[1], 'points': json.loads(row[2])}


def lookup_many(dest, origins):
    """批量查库。返回 {(qlng, qlat): 路径 dict}，只含命中的。"""
    out = {}
    for o in origins:
        got = lookup(o, dest)
        if got is not None:
            out[(q(o[0]), q(o[1]))] = got
    return out


def _fetch_walk_path(origin, dest):
    """调一次 `/v3/direction/walking`，返回步行的**真实道路折线**。

    ⚠️ `status != '1'` **明确抛错**（不返回空折线）—— 与 `road._fetch_walk` 同源纪律：
       本项目 P12 那条「限流被静默吞成空结果」的教训。
    """
    from data.fetch_poi import amap_url, http_get
    params = {
        'origin': '%.6f,%.6f' % (q(origin[0]), q(origin[1])),
        'destination': '%.6f,%.6f' % (q(dest[0]), q(dest[1])),
    }
    d = http_get(amap_url('/v3/direction/walking', params), timeout=15, retries=2)
    if d.get('status') != '1':
        raise RuntimeError('高德步行路径接口 status=%s info=%s'
                           % (d.get('status'), d.get('info')))
    paths = ((d.get('route') or {}).get('paths')) or []
    if not paths:
        raise RuntimeError('步行路径返回空（可能超出 5km 射程）')
    p0 = paths[0]
    pts, streets = [], []
    for s in (p0.get('steps') or []):
        for xy in (s.get('polyline') or '').split(';'):
            xy = xy.strip()
            if not xy:
                continue
            a, b = xy.split(',')
            pts.append([q(a), q(b)])
        ins = (s.get('instruction') or '').strip()
        if ins:
            streets.append(ins)
    if len(pts) < 2:
        raise RuntimeError('步行路径折点不足（%d 个）' % len(pts))
    # 去重相邻重复点（高德折线在 step 接缝处会重复首点）
    dedup = [pts[0]]
    for p in pts[1:]:
        if p != dedup[-1]:
            dedup.append(p)
    return {'meters': float(p0.get('distance') or 0),
            'seconds': float(p0.get('duration') or 0),
            'points': dedup, 'instructions': streets}


def fetch_and_store(dest, origins, sleep=BATCH_SLEEP, max_new=None):
    """批量抓取并落盘（断点续传：已命中的不再请求）。

    返回 {(qlng, qlat): 路径 dict}，**只含真正取到**的；取不到的**不出现**
    （调用方负责降级留痕）。
    """
    hit = lookup_many(dest, origins)
    todo = [o for o in origins if (q(o[0]), q(o[1])) not in hit]
    if max_new is not None:
        todo = todo[:max_new]
    now = time.strftime('%Y-%m-%d %H:%M:%S')
    c = _conn()
    n_new = 0
    for o in todo:
        try:
            r = _fetch_walk_path(o, dest)
            _CALLS['n'] += 1
        except Exception:
            _CALLS['fail'] += 1
            continue                       # 该点降级：不进库，也不返回
        points = r['points']
        c.execute('INSERT OR REPLACE INTO path VALUES(?,?,?,?,?,?,?,?)',
                  (q(o[0]), q(o[1]), q(dest[0]), q(dest[1]),
                   r['meters'], r['seconds'],
                   json.dumps(points, separators=(',', ':')),
                   now + '｜' + ' / '.join(r.get('instructions') or [])[:200]))
        n_new += 1
        if sleep:
            time.sleep(sleep)
    c.commit()
    c.close()
    if n_new:
        hit = lookup_many(dest, origins)
    return hit


if __name__ == '__main__':
    import io as _io
    import sys as _sys
    _sys.stdout = _io.TextIOWrapper(_sys.stdout.buffer, encoding='utf-8')
    print('road_path.db 现有路径：', stats())
    print('调用计数：', calls())
