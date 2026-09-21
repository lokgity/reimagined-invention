# -*- coding: utf-8 -*-
"""replay.py —— §2 历史会话回放的**纯逻辑**部分
================================================
为什么单独一个模块：这段逻辑（"最近 N 条 + 查看更早"的批次边界）是最容易
静默出错的地方 —— 差一位就会**重复回放**或**漏掉一条**，而两种错都不会抛异常。
放在 `app_chainlit.py` 里就注定测不到：那个文件的运行环境是 **Python 3.12 +
Chainlit**（项目纪律：Chainlit 必须在 3.12 启动），而离线回归门禁跑在
**Python 3.14**（引擎/分析用的解释器）—— 3.14 下 import chainlit 直接崩。

所以：纯算术留在这里（3.14 可导入、可断言），
`app_chainlit.py` 只负责"把 text 渲染成消息"这件必须依赖 Chainlit 的事。
"""

REPLAY_TAIL = 8      # 一次回放多少条（最近 N 条；更早的走「查看更早」入口）


def replayable(messages) -> list:
    """从会话消息里挑出**可回放**的：有正文的 user/assistant，保持时间正序。

    过滤空正文不是为了省事：历史里确实会留下 content 为空的消息
    （流式被打断、或某些节点只写 role），回放它们会在聊天区留下空白气泡，
    用户会以为"记录丢了"。
    """
    out = []
    for m in messages or []:
        c = str((m or {}).get('content') or '').strip()
        if c:
            out.append({'role': (m or {}).get('role') or 'assistant', 'content': c})
    return out


def clamp_shown(total: int, shown) -> int:
    """把"已显示条数"夹到 [0, total]。

    为什么要夹：`shown` 存在 user_session 里，而会话内容可能在两次点击之间变了
    （比如后端换了会话、或会话被精简）。脏值直接进算术会算出 start>end
    或负区间 → 报错或静默不发。
    """
    try:
        s = int(shown or 0)
    except Exception:
        s = 0
    return max(0, min(s, int(total or 0)))


def replay_slice(total: int, shown, tail: int = REPLAY_TAIL):
    """算出**本轮该补发**的区间 `(start, end)`（左闭右开，时间正序）。

    语义：已经显示了尾部 `shown` 条，现在再往前补 `tail` 条。
      total=20, shown=8  → (4, 12)     补发第 5~12 条
      total=20, shown=16 → (0, 4)      补发第 1~4 条（到顶）
      total=20, shown=20 → (0, 0)      没有更早的了（空区间，调用方应提示而非发消息）
      total=5,  shown=8  → (0, 0)      shown 被夹到 5，同样为空区间

    ⚠️ **不重不漏的判据**（回归里就是这么断言的）：
      把各轮的 (start, end) 依次拼起来，必须恰好覆盖 [0, total) **一次**，
      相邻两轮必须满足 `本轮 end == 上轮 start`（严丝合缝，不留缝也不重叠）。
    """
    total = max(0, int(total or 0))
    shown = clamp_shown(total, shown)
    tail = max(1, int(tail or 1))
    end = total - shown
    start = max(0, end - tail)
    return start, end


def next_shown(total: int, shown, start: int, end: int) -> int:
    """本轮发完后，"已显示"变成多少（= 已显示 + 本轮实际发出的条数）。"""
    return clamp_shown(total, clamp_shown(total, shown) + max(0, end - start))
