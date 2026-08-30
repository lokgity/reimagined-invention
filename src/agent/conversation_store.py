# -*- coding: utf-8 -*-
"""
conversation_store.py —— 会话记录持久化（自定义"历史会话"界面）
==================================================================
- 每次对话（含状态与消息）保存到本地 data/conversations.json
- 新建对话后，历史会话仍在，可在左侧/顶部面板打开继续
- 纯本地读写，0 次 API 请求
"""
import json
import time
import uuid
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent.parent / 'data'
CONV_FILE = DATA_DIR / 'conversations.json'
MAX_CONVERSATIONS = 30


def _load() -> list:
    try:
        with open(CONV_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(data: list) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONV_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def new_conversation(title: str = '新会话') -> str:
    """创建并保存一个新会话，返回其 id。"""
    conv = {
        'id': uuid.uuid4().hex[:8],
        'ts': time.strftime('%m-%d %H:%M'),
        'title': title,
        'state': {'messages': [], 'phase': 'intro', 'candidates': [],
                  'missing_info': []},
    }
    data = _load()
    data.insert(0, conv)
    if len(data) > MAX_CONVERSATIONS:
        data = data[:MAX_CONVERSATIONS]
    _save(data)
    return conv['id']


def save_conversation(conv_id: str, state: dict, title: str = None) -> None:
    """更新指定会话的状态（含消息）；不存在则新建（含状态）。"""
    data = _load()
    for c in data:
        if c['id'] == conv_id:
            c['state'] = state
            if title:
                c['title'] = title
            c['updated'] = time.strftime('%m-%d %H:%M')
            _save(data)
            return
    # 不存在（如数据被清空）：直接新建带状态的会话
    conv = {
        'id': conv_id,
        'ts': time.strftime('%m-%d %H:%M'),
        'title': title or '新会话',
        'state': state,
        'updated': time.strftime('%m-%d %H:%M'),
    }
    data.insert(0, conv)
    if len(data) > MAX_CONVERSATIONS:
        data = data[:MAX_CONVERSATIONS]
    _save(data)


def get_conversation(conv_id: str) -> dict | None:
    for c in _load():
        if c['id'] == conv_id:
            return c
    return None


def delete_conversation(conv_id: str) -> bool:
    """删除指定会话（返回是否删除成功）。"""
    data = _load()
    new = [c for c in data if c['id'] != conv_id]
    if len(new) == len(data):
        return False
    _save(new)
    return True


def list_conversations(limit: int = 30) -> list:
    """返回会话列表（新的在前）。"""
    return _load()[:limit]


def derive_title(state: dict) -> str:
    """从状态生成会话标题：有分析 -> 品类+店铺+分；否则取首条用户消息。"""
    sr = state.get('score_result')
    if sr and sr.get('name'):
        cat = sr.get('category', '')
        total = sr.get('total', '')
        name = (sr.get('name') or '')[:12]
        return f'{cat} · {name} · {total}分'
    for m in state.get('messages', []):
        if m.get('role') == 'user':
            t = (m.get('content') or '').strip().replace('\n', ' ')
            return t[:16]
    return '新会话'


def reset_conversations() -> None:
    _save([])
