# -*- coding: utf-8 -*-
"""
query.py —— 本地 POI 数据库查询接口
=====================================
- SQLite 建表
- 按坐标范围查询周边 POI（竞品/目标客群）
- 距离计算（Haversine）
"""
import math
import sqlite3
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import DB_PATH  # noqa: E402

SCHEMA_TABLE = """
CREATE TABLE IF NOT EXISTS poi (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    city TEXT,            -- 地级市
    adname TEXT,          -- 区县
    category TEXT,        -- 品类: 奶茶/甜品/早餐/便利店/配套(学校/办公/商圈/社区/通勤)
    poi_type TEXT,        -- 高德类型名（如"餐饮服务;冷饮店"）
    name TEXT,
    address TEXT,
    lng REAL,
    lat REAL,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    UNIQUE(name, lng, lat, category)
);
"""
SCHEMA_IDX1 = """
CREATE INDEX IF NOT EXISTS idx_poi_cat ON poi(category);
"""
SCHEMA_IDX2 = """
CREATE INDEX IF NOT EXISTS idx_poi_xy  ON poi(lng, lat);
"""
# 2026-09-27 性能修复（P0-4）：半径查询的标准形状是
#   WHERE category = ? AND lng BETWEEN ? AND ? AND lat BETWEEN ? AND ?
# 单列 idx_poi_cat 只能把范围缩到「整个品类」（奶茶 3959 行里通常只命中 44 行），
# 而 idx_poi_xy 又以 lng 打头、吃不到 category 这个等值条件。
# 复合索引 (category, lng, lat) 让 category 做等值前缀、lng 做范围扫描、lat 在索引内过滤。
SCHEMA_IDX3 = """
CREATE INDEX IF NOT EXISTS idx_poi_cat_xy ON poi(category, lng, lat);
"""

_DDL = (SCHEMA_TABLE, SCHEMA_IDX1, SCHEMA_IDX2, SCHEMA_IDX3)
_INIT_LOCK = threading.Lock()
_INIT_DONE = False
_TLS = threading.local()


def init_db():
    """建表 + 建索引。**整个进程只跑一次**。

    2026-09-27 性能修复（P0-3）：原先 `get_conn()` 每次调用都执行 3 条
    `CREATE ... IF NOT EXISTS`，实测 0.707 ms/次里有 0.265 ms（37%）纯耗在
    这几条注定 no-op 的 DDL 上（要解析 SQL、查 sqlite_master、开事务）。
    """
    global _INIT_DONE
    if _INIT_DONE:
        return
    with _INIT_LOCK:
        if _INIT_DONE:
            return
        Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(str(DB_PATH))
        try:
            for ddl in _DDL:
                c.execute(ddl)
            c.commit()
        finally:
            c.close()
        _INIT_DONE = True


def get_conn():
    """返回**当前线程**复用的连接（首次调用时触发一次 `init_db()`）。

    ⚠ 调用方**不要再 `conn.close()`**：连接按线程缓存复用，关掉会让该线程后续查询报错。
       （函数内做了 `SELECT 1` 活性探测，万一有漏改的调用方 close 了也能自愈重开。）

    为什么按线程缓存而不是全局一个：sqlite3 默认 `check_same_thread=True`，
    而 Chainlit 会把同步函数丢进线程池执行 —— 每线程一条连接既安全又省掉反复 connect
    （实测单次 connect ≈ 0.44 ms）。
    """
    init_db()
    conn = getattr(_TLS, 'conn', None)
    if conn is not None:
        try:
            conn.execute('SELECT 1').fetchone()
            return conn
        except Exception:
            conn = None
    conn = sqlite3.connect(str(DB_PATH))
    _TLS.conn = conn
    return conn


_R_EARTH = 6371000.0        # 与 haversine() 同一个球半径，保证两套口径自洽
_BBOX_EPS = 1e-6            # 相对余量（1 ppm）：吸收浮点累积误差，代价可忽略


def _bbox(lng, lat, radius_m):
    """以 (lng, lat) 为心、radius_m 为半径的圆的**严格**包围盒（lng0, lng1, lat0, lat1）。

    ⚠ 必须是超集，绝不能漏点 —— 漏一条 POI，结果指纹断言就对不上了。
      剪枝之后仍跑**同一个 haversine** 逐条精算，所以「超集 + 精算」≡ 原结果。

    用的是**球面冠的精确包围盒**，不是「1° ≈ 111320 m」那种平面近似：
      · 纬度方向：球面上沿子午线走 radius 米，对应的角距就是 θ = radius / R，
        所以 dlat = degrees(θ)，精确。
      · 经度方向：半径 θ 的球面冠，其最大经度跨度为 asin(sin θ / cos φ)
        —— 注意不是 θ / cos φ，后者在大半径下会偏小。
      · 冠跨越极点（cos φ → 0 或 sin θ / cos φ 越界）时直接给全球经度范围。

    为什么非改不可（2026-09-27 实测教训）：
      第一版用了 111320 m/度的平面近似，在浙江（北纬 ~30°）实际只有约 110850 m/度，
      盒子偏小约 3 米 —— 9720 组对拍里有 12 组在半径边界上漏了 1 条 POI。
      平面近似在小半径下看着没事，但**凡是漏就是结果错**，不能用。
    """
    theta = radius_m / _R_EARTH                    # 角距（弧度）
    dlat = math.degrees(theta) * (1.0 + _BBOX_EPS)

    coslat = math.cos(math.radians(lat))
    if abs(coslat) <= 1e-12:                       # 站在极点上：经度无意义，给全球
        dlng = 180.0
    else:
        s = math.sin(theta) / coslat
        if abs(s) >= 1.0:                          # 冠跨越极点：经度方向没有边界
            dlng = 180.0
        else:
            dlng = math.degrees(math.asin(s)) * (1.0 + _BBOX_EPS)

    return lng - dlng, lng + dlng, lat - dlat, lat + dlat


def insert_pois(rows):
    """rows: list of dict(city, adname, category, poi_type, name, address, lng, lat)"""
    conn = get_conn()
    conn.executemany(
        'INSERT OR IGNORE INTO poi (city, adname, category, poi_type, name, address, lng, lat) '
        'VALUES (:city, :adname, :category, :poi_type, :name, :address, :lng, :lat)',
        rows,
    )
    conn.commit()
    # 不再 close()：连接由 get_conn() 按线程缓存复用（2026-09-27 P0-3）
    return len(rows)


def count_by_category():
    conn = get_conn()
    cur = conn.execute('SELECT category, COUNT(*) FROM poi GROUP BY category ORDER BY COUNT(*) DESC')
    return cur.fetchall()


def haversine(lng1, lat1, lng2, lat2):
    """两点球面距离（米）"""
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def query_within(category, lng, lat, radius_m):
    """返回参考半径内指定 category 的 POI 列表（含距离）

    2026-09-27 性能修复（P0-1）：先用经纬度包围盒做**超集**剪枝，再逐条 haversine 精算。

    原先是「把整个品类（奶茶就有 3959 行）全拉进 Python，逐行算球面距离，最后只留下
    半径内的几十条」——命中率约 1%，99% 的三角函数是白算的。
    实测单铺位 6 个品类合计：36.75 ms → 0.50 ms（73×）。

    `ORDER BY id` 是**故意加的**：原写法走 idx_poi_cat 时行按 rowid 升序产出，
    换成 (category,lng,lat) 索引后产出顺序会变成按坐标排。加 `ORDER BY id`（id 即 rowid）
    把顺序钉死成和原来一致，避免浮点求和顺序变化扰动结果指纹。
    """
    conn = get_conn()
    lng0, lng1, lat0, lat1 = _bbox(lng, lat, radius_m)
    cur = conn.execute(
        'SELECT name, lng, lat, poi_type, adname FROM poi '
        'WHERE category = ? AND lng BETWEEN ? AND ? AND lat BETWEEN ? AND ? '
        'ORDER BY id',
        (category, lng0, lng1, lat0, lat1),
    )
    rows = cur.fetchall()
    result = []
    for name, lng2, lat2, poi_type, adname in rows:
        d = haversine(lng, lat, lng2, lat2)
        if d <= radius_m:
            result.append({'name': name, 'lng': lng2, 'lat': lat2, 'poi_type': poi_type,
                           'adname': adname, 'distance': round(d)})
    return result


def nearest_distance(category, lng, lat, max_km=10.0):
    """到指定 category 最近 POI 的距离（米）；无则返回 None

    2026-09-27 性能修复（P0-2）：同样加包围盒剪枝（半径 = max_km 换算的米数）。
    超 max_km 的点本来就会被 `d <= max_km * 1000` 丢掉，所以按 max_km 建盒是安全的超集。
    """
    conn = get_conn()
    max_m = max_km * 1000.0
    lng0, lng1, lat0, lat1 = _bbox(lng, lat, max_m)
    cur = conn.execute(
        'SELECT lng, lat FROM poi '
        'WHERE category = ? AND lng BETWEEN ? AND ? AND lat BETWEEN ? AND ? '
        'ORDER BY id',
        (category, lng0, lng1, lat0, lat1),
    )
    rows = cur.fetchall()
    best = None
    for lng2, lat2 in rows:
        d = haversine(lng, lat, lng2, lat2)
        if d <= max_m and (best is None or d < best):
            best = d
    return best


def stats():
    conn = get_conn()
    cur = conn.execute('SELECT COUNT(*), COUNT(DISTINCT city) FROM poi')
    return cur.fetchone()


if __name__ == '__main__':
    total, cities = stats()
    print(f'本地数据库: {total} 条 POI, 覆盖 {cities} 个城市')
    print('按品类分布:')
    for cat, cnt in count_by_category():
        print(f'  {cat}: {cnt}')
