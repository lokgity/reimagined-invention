# -*- coding: utf-8 -*-
"""
analysis_store.py —— 分析结果持久化（供跨会话"全方位对比"）
================================================================
- 每次评分分析完成后把结果存到本地 JSON（data/analyses.json）
- 对比功能读取该文件，可对比不同对话/不同商铺的分析
- 纯本地读写，0 次 API 请求
"""
import json
import time
import uuid
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent.parent / 'data'
ANALYSES_FILE = DATA_DIR / 'analyses.json'
MAX_ANALYSES = 50


def _load() -> list:
    try:
        with open(ANALYSES_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(data: list) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(ANALYSES_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def add_analysis(result: dict, rent=None, area=None, investment=None, staff=None,
                 utility=None, profit=None, interpretation='', city=None) -> dict | None:
    """保存一次评分分析结果，返回条目 dict；失败返回 None。
    utility/profit/interpretation 供对比表格、图表与 PDF 导出使用。"""
    try:
        dims = result.get('dims', {})
        evidence = result.get('evidence', {})
        p = profit if profit is not None else result.get('profit', {}) or {}
        u = utility if utility is not None else result.get('utility', {}) or {}
        entry = {
            'id': uuid.uuid4().hex[:8],
            'ts': time.strftime('%m-%d %H:%M'),
            'shop': result.get('name', ''),
            'category': result.get('category', ''),
            'city': city,
            'total': result.get('total'),
            'verdict': result.get('verdict', ''),
            'dims': dims,
            'lng': result.get('lng'),
            'lat': result.get('lat'),
            'rent': rent,
            'area': area,
            'comp_count': evidence.get('竞品数'),
            'month_sales': evidence.get('预估月流水'),
            'investment': investment if investment is not None else result.get('investment'),
            'staff': staff if staff is not None else result.get('staff'),
            'payback': p.get('回本周期(月)'),
            'net_profit': p.get('月净利估算'),
            'decoration': (result.get('decoration') or {}).get('档次'),
            'utility': u,
            'profit': p,
            'interpretation': interpretation,
        }
        data = _load()
        data.append(entry)
        if len(data) > MAX_ANALYSES:
            data = data[-MAX_ANALYSES:]
        _save(data)
        return entry
    except Exception:
        return None


def list_analyses() -> list:
    """返回已保存的所有分析（按时间正序）。"""
    return _load()


def delete_analysis(analysis_id: str) -> bool:
    """删除指定 id 的分析；成功返回 True，找不到返回 False。"""
    try:
        data = _load()
        new = [d for d in data if d.get('id') != analysis_id]
        if len(new) == len(data):
            return False
        _save(new)
        return True
    except Exception:
        return False


def clear_analyses() -> None:
    _save([])
