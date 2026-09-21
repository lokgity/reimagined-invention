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
        # ⚠️ 把 id **回写进 result**。
        #    为什么：仿真大屏的快照是**在 UI 层**生成的（那里才有 map_b64 / 品牌 / own_S），
        #    而 id 只有这里（store 层）知道。原本 add_analysis 的返回值在调用处被丢掉了，
        #    UI 层拿不到 id，就只能"存最近一次"—— 那正是大屏没法像对比分析一样
        #    让用户挑"看哪一次"的根因（策 2026-09-21 15:33 提出）。
        #    回写到 result 是**零成本、零新依赖**的传递方式（result 是调用方传进来的同一对象）。
        result['analysis_id'] = entry['id']
        return entry
    except Exception:
        return None


def list_analyses() -> list:
    """返回已保存的所有分析（按时间正序）。"""
    return _load()


# ---------------------------------------------------------------
# 仿真大屏快照（每次分析一份）
# ---------------------------------------------------------------
# 存到 **public/ 下**，因为前端要用 fetch('/public/sim_boards/<id>.json') 直接取；
# data/ 目录不在 Chainlit 的静态服务根里，前端拿不到。
BOARDS_DIR = DATA_DIR.parent / 'public' / 'sim_boards'


def save_board(analysis_id: str, payload: dict) -> bool:
    """把某次分析的仿真大屏快照落盘。analysis_id 为空则**不存**
    （没有 id 的快照对不上列表，存了也没法被选中）。"""
    if not analysis_id:
        return False
    try:
        BOARDS_DIR.mkdir(parents=True, exist_ok=True)
        with open(BOARDS_DIR / ('%s.json' % analysis_id), 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False)
        return True
    except Exception:
        return False


def load_board(analysis_id: str):
    try:
        with open(BOARDS_DIR / ('%s.json' % analysis_id), 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def list_board_ids() -> set:
    """已有哪些分析有大屏快照（供列表页给卡片标"可看/不可看"）。"""
    try:
        return set(p.stem for p in BOARDS_DIR.glob('*.json'))
    except Exception:
        return set()


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
