# -*- coding: utf-8 -*-
"""
road.py —— 步行路网距离：本地冻结库优先，未命中才调高德
=========================================================
口径：高德 `/v3/distance` 的 **type=3 步行规划距离**（仅支持 5km 内）。
     分析半径 300~800m 远在射程内。
     不用 type=1 驾车距离 —— 那是「车能走的路」，不是「人能走的路」；
     驾车还会受单行道影响，实测同一对点驾车 823m / 步行 433m（示例见探针）。

⚠️ 为什么必须**冻结成本地库**，而不是每次实时调：
   高德的路线规划**会考虑路况**，同一对坐标在不同时间可能返回不同距离。
   而本项目红线是「同一组输入必得同一组输出」（17 项结果指纹断言）。
   一次性抓下来冻结，之后所有计算读本地 ⇒ 可复现 ✓ 离线 ✓ 配额只花一次 ✓。
   这与 `zj_poi.db`（本地预抓取 POI 库）、高德瓦片缓存是**同一个哲学**。

⚠️ 失败必须留痕，不许静默回退：
   取数失败时 `road_distances_to()` 返回的 dict 里**不包含**该点（而不是塞一个直线距离），
   调用方（`scoring.dist()`）再决定回退，并把「本次口径=直线（路网取数失败）」写进结果。
   这条对应 `口径区间-价格弹性未标定.md` §四条修法里「取数失败必须声明」。
"""
import json
import math
import os
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DB_PATH = Path(__file__).resolve().parents[2] / 'data' / 'road_distance.db'

# 高德 distance 接口单次 origins 上限（公交仅 20；步行/驾车 100）
MAX_ORIGINS = 100
# 步行规划硬上限 5km
WALK_MAX_M = 5000
# ⚠️ 距离测量接口的 QPS 限得很紧（实测 0.12s 间隔即撞 CUQPS_HAS_EXCEEDED_THE_LIMIT）。
#    批次间隔取 0.6s（≈1.7 QPS）；撞限流时另有退避重试兜底。
BATCH_SLEEP = 0.6
QPS_BACKOFF = (1.5, 3.0, 5.0)
# 坐标量化：5 位小数 ≈ 1.1m，足够稳定命中，也不会因浮点尾差造成缓存穿透
_Q = 5

_CALLS = {'n': 0, 'fail': 0, 'qps_retry': 0}


def q(v):
    return round(float(v), _Q)


def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(DB_PATH))
    c.execute('''CREATE TABLE IF NOT EXISTS road (
        olng REAL, olat REAL, dlng REAL, dlat REAL,
        meters REAL, seconds REAL, source TEXT, fetched_at TEXT,
        PRIMARY KEY (olng, olat, dlng, dlat))''')
    c.commit()
    return c


def stats():
    c = _conn()
    n = c.execute('SELECT COUNT(*) FROM road').fetchone()[0]
    c.close()
    return n


def _pair_key(a, b):
    """无向对的规范化键（路网距离近似对称，取字典序小的在前，省一半抓取）。"""
    (la, aa), (lb, ab) = (q(a[0]), q(a[1])), (q(b[0]), q(b[1]))
    return (la, aa, lb, ab) if (la, aa) <= (lb, ab) else (lb, ab, la, aa)


def lookup(a, b):
    """查冻结库；未命中返回 None。a, b 均为 (lng, lat)。"""
    k = _pair_key(a, b)
    c = _conn()
    row = c.execute('SELECT meters FROM road WHERE olng=? AND olat=? AND dlng=? AND dlat=?',
                    k).fetchone()
    c.close()
    return row[0] if row else None


def lookup_many(dest, origins):
    """批量查冻结库。返回 {(qlng, qlat): meters}，只含命中的。"""
    out = {}
    if not origins:
        return out
    keys = {}
    for o in origins:
        keys[_pair_key(o, dest)] = (q(o[0]), q(o[1]))
    c = _conn()
    hit = {}
    for k in keys:
        row = c.execute('SELECT meters FROM road WHERE olng=? AND olat=? AND dlng=? AND dlat=?',
                        k).fetchone()
        if row:
            hit[k] = row[0]
    c.close()
    for k, oq in keys.items():
        if k in hit:
            out[oq] = hit[k]
    return out


def _fetch_walk(dest, origins):
    """调一次高德步行距离：N 个 origins → 1 个 destination。返回 {(qlng,qlat): meters}。

    ⚠️ 遇 status != '1' **明确抛错**（不返回空 dict 冒充"没有结果"）——
       这正是本项目 P12 那条「限流被静默吞成空结果」事故的教训。
    """
    from data.fetch_poi import amap_url, http_get
    orgs = origins[:MAX_ORIGINS]
    params = {
        'origins': '|'.join('%.6f,%.6f' % (q(o[0]), q(o[1])) for o in orgs),
        'destination': '%.6f,%.6f' % (q(dest[0]), q(dest[1])),
        'type': '3',                      # 3 = 步行规划距离
    }
    d = None
    for _wait in (0,) + QPS_BACKOFF:           # 首次 + 最多 3 次退避重试
        if _wait:
            _CALLS['qps_retry'] += 1
            time.sleep(_wait)
        _CALLS['n'] += 1
        d = http_get(amap_url('/v3/distance', params), timeout=15, retries=2)
        if d.get('status') == '1':
            break
        _info = str(d.get('info') or '')
        if 'CUQPS' not in _info:               # 不是限流（如配额耗尽）→ 不重试
            break
    if d.get('status') != '1':
        # ⚠️ 明确抛出，**不返回空 dict 冒充"这些点没有距离"** —— 这正是本项目
        #    P12 那条「限流被静默吞成空结果」事故的教训。调用方据此逐点回退直线,
        #    并把回退占比写进结果（红线 4：取数失败必须出声）。
        _CALLS['fail'] += 1
        raise RuntimeError('高德距离接口返回 status=%s info=%s（配额或限流）'
                           % (d.get('status'), d.get('info')))
    out = {}
    for r in (d.get('results') or []):
        try:
            oi = int(r.get('origin_id')) - 1
            meters = float(r.get('distance'))
        except (TypeError, ValueError):
            continue
        if oi < 0 or oi >= len(orgs):
            continue
        seconds = None
        try:
            seconds = float(r.get('duration'))
        except (TypeError, ValueError):
            pass
        # 高德对不可达/超 5km 的点会返回 0 或空，按"未取到"处理，不塞假值
        if meters <= 0:
            continue
        out[(q(orgs[oi][0]), q(orgs[oi][1]))] = meters
    return out


def fetch_and_store(dest, origins, sleep=BATCH_SLEEP):
    """批量抓取并落盘（断点续传：已命中的不再请求）。返回 {(qlng,qlat): meters}。

    返回**只含真正取到**的点；取不到的**不出现**在返回值里（调用方负责降级留痕）。

    ⚠️ 某一批重试后仍失败（配额耗尽 / 限流）→ **停止继续抓、保留已抓到的部分**，
       不让整个分析崩掉（失败可见但不阻断）。未抓到的点由 `scoring.query_pois`
       逐点回退直线，并计入 `DIST_STATS['fallback']`。
    """
    dest = (q(dest[0]), q(dest[1]))
    hit = lookup_many(dest, origins)
    todo = [o for o in origins if (q(o[0]), q(o[1])) not in hit]
    now = time.strftime('%Y-%m-%d %H:%M:%S')
    c = _conn()
    for i in range(0, len(todo), MAX_ORIGINS):
        batch = todo[i:i + MAX_ORIGINS]
        try:
            got = _fetch_walk(dest, batch)
        except Exception as e:
            print('    [road] 取数失败，停止本铺位抓取：%s' % e)
            break
        for (oq, m) in got.items():
            k = _pair_key((oq[0], oq[1]), dest)
            c.execute('INSERT OR REPLACE INTO road VALUES (?,?,?,?,?,?,?,?)',
                      (k[0], k[1], k[2], k[3], m, None, 'amap-type3-walk', now))
            hit[oq] = m
        c.commit()
        if sleep:
            time.sleep(sleep)
    c.close()
    return hit


def calls():
    return dict(_CALLS)
