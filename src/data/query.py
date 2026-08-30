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


def get_conn():
    Path(DB_PATH).parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(SCHEMA_TABLE)
    conn.execute(SCHEMA_IDX1)
    conn.execute(SCHEMA_IDX2)
    return conn


def insert_pois(rows):
    """rows: list of dict(city, adname, category, poi_type, name, address, lng, lat)"""
    conn = get_conn()
    conn.executemany(
        'INSERT OR IGNORE INTO poi (city, adname, category, poi_type, name, address, lng, lat) '
        'VALUES (:city, :adname, :category, :poi_type, :name, :address, :lng, :lat)',
        rows,
    )
    conn.commit()
    conn.close()
    return len(rows)


def count_by_category():
    conn = get_conn()
    cur = conn.execute('SELECT category, COUNT(*) FROM poi GROUP BY category ORDER BY COUNT(*) DESC')
    result = cur.fetchall()
    conn.close()
    return result


def haversine(lng1, lat1, lng2, lat2):
    """两点球面距离（米）"""
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def query_within(category, lng, lat, radius_m):
    """返回参考半径内指定 category 的 POI 列表（含距离）"""
    conn = get_conn()
    cur = conn.execute(
        'SELECT name, lng, lat, poi_type, adname FROM poi WHERE category = ?', (category,)
    )
    rows = cur.fetchall()
    conn.close()
    result = []
    for name, lng2, lat2, poi_type, adname in rows:
        d = haversine(lng, lat, lng2, lat2)
        if d <= radius_m:
            result.append({'name': name, 'lng': lng2, 'lat': lat2, 'poi_type': poi_type,
                           'adname': adname, 'distance': round(d)})
    return result


def nearest_distance(category, lng, lat, max_km=10.0):
    """到指定 category 最近 POI 的距离（米）；无则返回 None"""
    conn = get_conn()
    cur = conn.execute('SELECT lng, lat FROM poi WHERE category = ?', (category,))
    rows = cur.fetchall()
    conn.close()
    best = None
    for lng2, lat2 in rows:
        d = haversine(lng, lat, lng2, lat2)
        if d <= max_km * 1000 and (best is None or d < best):
            best = d
    return best


def stats():
    conn = get_conn()
    cur = conn.execute('SELECT COUNT(*), COUNT(DISTINCT city) FROM poi')
    total, cities = cur.fetchone()
    conn.close()
    return total, cities


if __name__ == '__main__':
    total, cities = stats()
    print(f'本地数据库: {total} 条 POI, 覆盖 {cities} 个城市')
    print('按品类分布:')
    for cat, cnt in count_by_category():
        print(f'  {cat}: {cnt}')
