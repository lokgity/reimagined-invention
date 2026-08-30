# -*- coding: utf-8 -*-
"""
agent_graph.py —— LangGraph Agent 图定义
==========================================
把原有的手写状态机升级为 LangGraph 图节点：
- classify: 意图识别（规则提取，不调 LLM）
- collect_info: 信息收集
- search_rental: 候选搜索
- select_shop: 选择商铺
- analyze: 评分分析
- interpret: LLM 解读
- free_chat: 自由问答

核心体验（针对用户反馈修正）：
1. 用户给出「品类 + 地区」→ 直接搜索并推荐候选商铺，**绝不反问租金**
   （租金由候选商铺自带；只有"已有具体铺子"才收集租金）
2. 尽量少发 API 请求、每次量大：58 同城只抓一次、区域只 geocode 一次、
   无精确路名的候选直接用区域中心坐标（0 次额外调用）、评分优先本地库。
"""
import json
import sys
import re
import asyncio
import time
from pathlib import Path
from typing import Dict, Any, Optional, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.state import AgentState
from agent.llm import call_llm, call_llm_sync
from agent.agent import (
    parse_request, geocode, extract_guest, extract_mode, extract_area,
    extract_address, _clean_area, _is_pure_district, _district_business_center,
    _in_zhejiang, KNOWN_AREA_COORDS
)
from agent.rental58 import fetch_shops, CITY_CODES
from engine.scoring import score_site
from data.fetch_poi import search_poi
from data.query import haversine
from config import get_profile


# ---------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------
async def _emit(state: AgentState, kind: str, name: str, text: str = '',
                input_: str = '', output: str = ''):
    """记录执行过程事件（thinking/tool），并实时推送给前端（若有 on_event 钩子）。
    事件同时写入 hooks['steps']（随状态跨节点共享，无需每个节点显式返回）。"""
    ev = {'kind': kind, 'name': name, 'text': text,
          'input': input_, 'output': output}
    hooks = state.get('hooks') or {}
    hooks.setdefault('steps', []).append(ev)
    on_event = hooks.get('on_event')
    if on_event:
        try:
            await on_event(ev)
        except Exception:
            pass


def extract_city(addr: str) -> Optional[str]:
    """从地址中提取城市名"""
    if not addr:
        return None
    for c in ['杭州', '宁波', '温州', '嘉兴', '湖州', '绍兴',
              '金华', '衢州', '舟山', '台州', '丽水']:
        if c in addr:
            return c
    return None


def extract_district(addr: str) -> Optional[str]:
    """从地址中提取区名"""
    if not addr:
        return None
    for c in ['杭州', '宁波', '温州', '嘉兴', '湖州', '绍兴',
              '金华', '衢州', '舟山', '台州', '丽水']:
        if addr.startswith(c):
            addr = addr[len(c):]
            break
    m = re.search(r'([\u4e00-\u9fa5]+(?:区|县))', addr)
    return m.group(1) if m else None


def _has_specific_shop(text: str) -> bool:
    """判断用户是否提到了一个"具体看中的商铺"（而非找区域推荐）。
    规则优先级: 明确否定 > 明确"有铺子"措辞 > 地址含具体铺位特征。
    """
    # 1) 明确否定 -> 找商铺
    for kw in ['还没有', '没有', '还没', '没看中', '不确定', '没找到', '没选', '没看']:
        if kw in text:
            return False
    # 2) 明确"有具体铺子"
    for kw in ['看中了', '看中', '找到了', '找好了', '看好了', '有意向', '目标商铺',
               '具体商铺', '看了一家', '有一个', '有具体', '有看', '选好', '已选',
               '有个铺子', '有个店铺', '有个店面', '有个铺位', '附近有个', '看中了一']:
        if kw in text:
            return True
    # 3) 地址含"号/大厦/座/铺位/门面/楼层/栋"等具体铺位特征 -> 有具体铺子
    addr = extract_address(text) or ''
    if any(k in addr for k in ['号', '大厦', '座', '铺位', '铺面', '门面', '楼层', '栋', '幢']):
        return True
    return False


def _wants_find(text: str) -> bool:
    """是否有明确的"找/推荐商铺"诉求（用于初次阶段判定）"""
    for kw in ['帮我找', '帮我查', '推荐', '帮我看看', '帮我找找', '帮我搜',
               '帮我推荐', '找商铺', '找店', '找铺', '有什么店', '有哪些店',
               '哪家店', '哪里开', '哪个位置']:
        if kw in text:
            return True
    return False


def _wants_restart(text: str) -> bool:
    """是否明确要"换/重新找"（用于已有具体商铺时放弃当前分析）"""
    for kw in ['换一个', '换家', '重新找', '再推荐', '再找', '换到', '换个',
               '帮我找', '帮我查', '帮我推荐', '其他区域', '别的', '算了',
               '重新推荐', '再看看']:
        if kw in text:
            return True
    return False


def _parse_choice(text: str):
    """解析用户从候选列表选择的序号（如"选1""1号""就选2""2"）。
    返回 1-based 序号；非选择意图返回 None。"""
    if not text:
        return None
    # "选1" / "选第2个" / "就选3"
    m = re.search(r'选(?:第)?\s*(\d+)', text)
    if m:
        return int(m.group(1))
    # 整个消息就是序号: "1" / "1号" / "（2）"
    m = re.fullmatch(r'[（(]?(\d+)\s*号?[）)]?', text.strip())
    if m:
        return int(m.group(1))
    # "第3个" / "3号吧"
    m = re.search(r'第\s*(\d+)\s*个|(\d+)\s*号吧|(\d+)\s*号\s*吧', text)
    if m:
        return int(m.group(1) or m.group(2) or m.group(3))
    return None


def _last_user_msg(state) -> str:
    """取最后一轮用户消息文本（节点在追加过 assistant 消息后仍能取到）"""
    for m in reversed(state.get('messages', [])):
        if m.get('role') == 'user':
            return m.get('content', '')
    return ''


def _looks_like_question(text: str) -> bool:
    """是否像提问/闲聊（用于"无关键词时进入自由对话"的判断）"""
    if not text:
        return False
    if any(c in text for c in ['？', '?', '吗', '呢', '哈', '嗨', 'hi', 'hello', '在吗']):
        return True
    for kw in ['怎么', '什么', '为什么', '如何', '哪个', '多少', '怎样', '怎么办',
               '啥', '聊聊', '介绍', '你好', '谢谢', '帮忙', '随便聊聊', '有什么']:
        if kw in text:
            return True
    return False


def _awaiting_answer(state) -> bool:
    """上一轮 assistant 是否正在向用户提问（在等用户回答收集问题）"""
    for m in reversed(state.get('messages', [])):
        if m.get('role') == 'assistant':
            c = m.get('content', '')
            return ('？' in c) or ('?' in c) or ('还需要告诉我' in c) or ('回复' in c)
    return False


def _wants_compare(text: str) -> bool:
    """是否要对比两个已分析商铺"""
    if not text:
        return False
    for kw in ['对比', '比较两个', '对比一下', '对比分析', '两个分析', '哪个更好']:
        if kw in text:
            return True
    return False


def _parse_compare_pair(text: str):
    """解析对比选择的多个序号（如"对比 1 和 3""1,2,4""1 3"）。
    返回 1-based 序号列表（2-4 个）；无法解析返回 None。"""
    if not text:
        return None
    # 空格/和/与/vs/、/,/，分隔的多个数字（只取数字 token，忽略前后文字）
    nums = re.findall(r'\d+', text)
    if len(nums) >= 2:
        vals = [int(n) for n in nums[:4]]
        # 去重且保序
        seen, out = set(), []
        for v in vals:
            if v not in seen:
                seen.add(v); out.append(v)
        if len(out) >= 2:
            return out
    return None


def _parse_investment(text: str, strict=False) -> Optional[float]:
    """解析前期投入成本（元）。
    strict=True: 只有明确带"投入/预算/成本/万/千/k"等标志才识别，
                避免把"月租8000"误当投入。
    strict=False: 允许裸数字（collect_invest 环节用户在直接回答投入）。
    """
    if not text:
        return None
    s = text.strip()
    # 1) 明确前缀: 前期投入/投入成本/总投资/投资/预算/成本/资金
    m = re.search(r'(?:前期投入|投入成本|总投资|投入|预算|成本|资金|准备)[:：]?\s*(\d+(?:\.\d+)?)\s*(万元|万|w|w元|千|k|k元|元)?', s)
    if m:
        v = float(m.group(1))
        unit = m.group(2) or ''
        if unit and ('万' in unit or 'w' in unit.lower()):
            v *= 10000
        elif unit and ('千' in unit or 'k' in unit.lower()):
            v *= 1000
        return round(v)
    # 2) 带单位: "10万" "12万元" "80k"
    m = re.search(r'(\d+(?:\.\d+)?)\s*(万元|万|w|千|k)\b', s)
    if m:
        v = float(m.group(1))
        unit = m.group(2)
        if '万' in unit or 'w' in unit.lower():
            v *= 10000
        elif '千' in unit or 'k' in unit.lower():
            v *= 1000
        return round(v)
    # 3) 非严格模式: 裸数字（collect_invest 环节的直接回答）
    if not strict:
        m = re.search(r'(\d{4,7})', s)
        if m:
            return int(m.group(1))
    return None


def _parse_staff(text: str) -> Optional[int]:
    """解析运营人数（如"2人""3个人""两个"）。"""
    if not text:
        return None
    m = re.search(r'(\d+)\s*(?:人|名|个员工|个人)', text)
    if m:
        return int(m.group(1))
    m = re.search(r'([一二两三四五六七八九十])\s*个?人', text)
    if m:
        cn = {'一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5,
              '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}
        return cn.get(m.group(1))
    return None


def _default_investment(area=None) -> int:
    """前期投入兜底估算：装修 4000/㎡ + 设备物料 3 万"""
    return int(area or 30) * 4000 + 30000


def ask_investment_message(category: str) -> str:
    """询问前期投入 + 人数的提示文案"""
    from engine.utilities import get_default_staff
    default_staff = get_default_staff(category or '默认')
    return (f'💰 最后确认一下，好把回本周期算准：\n'
            f'1️⃣ **前期投入成本**大概多少？（含装修+设备+首批物料+转让等，'
            f'直接回复如「**12万**」或「**120000**」）\n'
            f'2️⃣ 运营**人数**：{category or "该品类"}默认按 **{default_staff} 人**算'
            f'（奶茶/甜品/早餐2人、便利店1人），需要调整就一起说，如「**12万 3人**」。\n'
            f'（回复「你定」则由我按投入自动估算装修档次）')


def format_candidates(candidates: List[Dict]) -> str:
    """格式化候选列表"""
    lines = ['为你找到以下候选位置：', '']
    for i, c in enumerate(candidates, 1):
        info = []
        if c.get('area'):
            info.append(f"{c['area']}㎡")
        if c.get('price'):
            info.append(f"{c['price']:.0f}元/月")
        extra = f"（{'，'.join(info)}）" if info else ''
        lines.append(f"**{i}. {c['name']}**{extra}")
        lines.append(f"    🧭 {c['address']}")
    lines.append('')
    lines.append('回复序号选择；或告诉我其他区域。')
    return '\n'.join(lines)


# ---------------------------------------------------------------
# 节点 1：意图识别（规则提取，不调 LLM，0 次 API 请求）
# ---------------------------------------------------------------
async def classify_node(state: AgentState) -> Dict[str, Any]:
    """用规则判断用户意图，提取结构化信息。
    阶段语义：
    - intro     : 初始/闲聊，尚无任何信息
    - no_shop   : 找商铺（收集品类+地区 -> 搜索推荐），**不问租金**
    - have_shop : 已有具体商铺（收集品类/地址/租金 -> 分析）
    - select_shop: 等待用户从候选列表选择
    - analysis  : 信息齐备，进入评分
    - chat      : 自由问答
    """
    user_msg = state['messages'][-1]['content']
    info = parse_request(user_msg)
    guest = extract_guest(user_msg)
    mode = extract_mode(user_msg)
    area = extract_area(user_msg)

    prev_phase = state.get('phase', 'intro')
    has_specific = _has_specific_shop(user_msg)
    has_cat = bool(info.get('category'))
    has_addr = bool(info.get('address'))
    has_region = has_addr or bool(extract_city(user_msg))
    choice = _parse_choice(user_msg)
    # 前期投入 / 人数（strict: 非 collect_invest 环节只认明确"投入/万"标志，防误把租金当投入）
    invest = _parse_investment(user_msg, strict=(prev_phase != 'collect_invest'))
    staff_parsed = _parse_staff(user_msg)
    # 是否触发"业务关键词"：具体商铺/品类/地区/找/换/选序号
    has_keyword = (has_specific or has_cat or has_addr or has_region
                   or _wants_find(user_msg) or _wants_restart(user_msg)
                   or choice is not None)

    # ---- 阶段决策 ----
    # 0) 对比两个已分析商铺
    if _wants_compare(user_msg):
        phase = 'compare'
    # 1) 正在对比流程中
    elif prev_phase == 'compare':
        if _parse_compare_pair(user_msg):
            phase = 'compare'                       # 正在选两个序号
        elif has_specific:
            phase = 'have_shop'
        elif has_cat or has_addr or has_region or _wants_find(user_msg) or _wants_restart(user_msg):
            phase = 'no_shop'                       # 离开对比，重新找
        elif _looks_like_question(user_msg):
            phase = 'chat'                          # 对比中闲聊/提问
        else:
            phase = 'compare'                       # 继续等对比选择
    # 2) 正在候选列表中选择
    elif prev_phase == 'select_shop':
        if choice is not None:
            phase = 'select_shop'                   # 已选序号 -> 分析
        elif has_specific:
            phase = 'have_shop'                     # 改为分析具体商铺
        elif has_cat or has_addr or _wants_find(user_msg) or _wants_restart(user_msg):
            phase = 'no_shop'                       # 换品类/区域重新找
        elif _looks_like_question(user_msg):
            phase = 'chat'                          # 选候选时突然提问 -> 自由对话
        else:
            phase = 'select_shop'                   # 继续等待选择
    # 2.5) 正在收集前期投入/人数
    elif prev_phase == 'collect_invest':
        if has_specific or has_cat or has_addr or has_region or _wants_find(user_msg) or _wants_restart(user_msg):
            phase = 'have_shop' if has_specific else 'no_shop'   # 用户改主意/换需求
        else:
            phase = 'collect_invest'                # 正在答投入/人数
    # 3) 通用：触发了业务关键词 -> 按"有具体商铺/找商铺"分流
    elif has_specific:
        phase = 'have_shop'
    elif has_cat or has_addr or has_region or _wants_find(user_msg) or _wants_restart(user_msg):
        phase = 'no_shop'
    # 4) 没有触发任何关键词 -> 自动进入自由对话
    #    例外：正在收集品类/地区/租金，且用户在回答上一轮的问题（如"嗯""随便"）时保持追问
    elif prev_phase in ('no_shop', 'have_shop') and _awaiting_answer(state) and not _looks_like_question(user_msg):
        phase = prev_phase
    else:
        phase = 'chat'

    # 清洗地址尾部（"杭州滨江的奶茶店" -> "杭州滨江"）
    addr = info.get('address') or state.get('address')
    if addr:
        addr = _clean_area(addr)

    # 执行过程：意图识别思考
    cat_txt = info.get('category') or state.get('category') or '？'
    addr_txt = addr or '？'
    has_spec_txt = '已有具体商铺' if has_specific else '正在找商铺'
    await _emit(state, 'think', '意图识别',
                f'用户输入「{user_msg[:40]}{"…" if len(user_msg) > 40 else ""}」\n'
                f'→ 识别结果：品类【{cat_txt}】、区域【{addr_txt}】、{has_spec_txt}\n'
                f'→ 本轮流程方向：{phase}')

    return {
        'messages': state['messages'],
        'category': info.get('category') or state.get('category'),
        'address': addr or state.get('address'),
        'rent': info.get('rent') if info.get('rent') is not None else state.get('rent'),
        'area': area or state.get('area'),
        'guest': guest or state.get('guest'),
        'mode': mode or state.get('mode'),
        'investment': invest if invest is not None else state.get('investment'),
        'staff': staff_parsed if staff_parsed is not None else state.get('staff'),
        'phase': phase,
        'missing_info': [],
        'candidates': state.get('candidates', []),
        'pending_coord': state.get('pending_coord'),
        'selected_idx': state.get('selected_idx'),
        'list_shown': state.get('list_shown', False),
        'comparison': state.get('comparison'),
        'compare_pending': state.get('compare_pending', False),
    }


# ---------------------------------------------------------------
# 节点 2：信息收集
# ---------------------------------------------------------------
async def collect_info_node(state: AgentState) -> Dict[str, Any]:
    """收集缺失信息。
    - no_shop/intro 分支: 只问品类 + 地区，**绝不问租金**（租金由候选自带）
    - have_shop 分支: 问品类/地址/租金（已有具体铺子才需要租金）
    """
    phase = state.get('phase', 'no_shop')

    # 选择候选阶段：不追问，等用户选
    if phase == 'select_shop':
        return {'phase': 'select_shop'}

    # 找商铺分支：只收集品类 + 地区
    if phase in ('intro', 'no_shop'):
        missing = []
        if not state.get('category'):
            missing.append('想开什么品类？（奶茶/甜品/早餐/便利店）')
        if not state.get('address'):
            missing.append('想开在哪个区域？（如"杭州滨江""宁波鄞州"）')

        if missing:
            reply = '好的，帮你找合适的商铺！还需要告诉我：' + '、'.join(missing[:2])
            return {
                'messages': state['messages'] + [{'role': 'assistant', 'content': reply}],
                'missing_info': missing,
                'phase': 'no_shop',
            }
        # 品类 + 地区都有了 -> 搜索候选
        return {'phase': 'search_rental', 'missing_info': []}

    # "已有具体商铺"分支：问品类、地址、租金
    # 用户直接用数字回答租金（如"8000""8000元"）时自动补上
    last_msg = _last_user_msg(state)
    rent_ans = None
    if state.get('rent') is None and state.get('category') and state.get('address'):
        m = re.fullmatch(r'\s*(\d{3,7})\s*(元|/月|每月|块)?\s*', last_msg)
        if m:
            rent_ans = int(m.group(1))

    missing = []
    if not state.get('category'):
        missing.append('品类（奶茶/甜品/早餐/便利店）')
    if not state.get('address'):
        missing.append('商铺位置或地址')
    if state.get('rent') is None and rent_ans is None:
        missing.append('月租金')

    if missing:
        reply = '还需要你告诉我：' + '、'.join(missing[:2]) + '（一次说全更省事~）'
        return {
            'messages': state['messages'] + [{'role': 'assistant', 'content': reply}],
            'missing_info': missing,
            'phase': 'have_shop',
        }

    # 已有具体商铺，信息齐备 -> 先问前期投入/人数（再进入分析）
    return {
        'phase': 'collect_invest',
        'missing_info': [],
        'rent': state.get('rent') if state.get('rent') is not None else rent_ans,
        'messages': state['messages'] + [{
            'role': 'assistant',
            'content': ask_investment_message(state.get('category', '')),
        }],
    }


# ---------------------------------------------------------------
# 节点 2.5：收集前期投入（选好商铺后 -> 问投入+人数 -> 再分析）
# ---------------------------------------------------------------
async def collect_invest_node(state: AgentState) -> Dict[str, Any]:
    """选好铺子后，询问前期投入成本与运营人数。
    投入已给出 -> 人数默认(奶茶/甜品/早餐2人、便利店1人) -> 进入分析。
    回复"你定/默认" -> 按面积兜底估算投入后进入分析。"""
    from engine.utilities import get_default_staff
    category = state.get('category', '')
    invest = state.get('investment')
    staff = state.get('staff')

    # 投入未给出：继续收集（本轮先提示/引导）
    if invest is None:
        last = _last_user_msg(state)
        if any(k in last for k in ['你定', '你算', '默认', '随便', '你看着办', '听你的']):
            invest = _default_investment(state.get('area'))
            staff = staff or get_default_staff(category)
            return {
                'investment': invest,
                'staff': staff,
                'phase': 'analysis',
                'messages': state['messages'] + [{
                    'role': 'assistant',
                    'content': f'好的，按参考帮您估算：前期投入约 **{invest:,}** 元'
                               f'（装修{int(state.get("area") or 30)*4000:,} + 设备物料 3 万），'
                               f'运营按 {staff} 人。正在为您分析…',
                }],
            }
        # 用户还没回答 -> 提示（避免重复整段说明）
        reply = ('请回复前期投入成本，如「**12万**」或「**120000**」；'
                 '需要调人数就一起说，如「**12万 3人**」；回复「你定」由我估算。')
        return {
            'messages': state['messages'] + [{'role': 'assistant', 'content': reply}],
            'phase': 'collect_invest',
        }

    # 投入已给出 -> 人数默认 -> 进入分析
    staff = staff or get_default_staff(category)
    invest_txt = f"{invest:,}"
    return {
        'staff': staff,
        'phase': 'analysis',
        'messages': state['messages'] + [{
            'role': 'assistant',
            'content': f'💰 收到：前期投入 **{invest_txt} 元**，运营按 **{staff} 人**测算'
                       f'（{category}默认{get_default_staff(category)}人）。正在为您分析…',
        }],
    }


# ---------------------------------------------------------------
# 节点 3：候选搜索（找商铺分支，尽量少 API 请求）
# ---------------------------------------------------------------
async def search_rental_node(state: AgentState) -> Dict[str, Any]:
    """搜索区域真实在租商铺（58同城一次抓取 + 高德兜底）。
    API 优化：
    - 58 同城只抓一次（limit=8，量大）
    - 区域中心只 geocode 一次；无精确路名的候选直接回落区域中心（0 次额外调用）
    - 精确 geocode 设预算上限（默认 4 次），省配额
    - 高德兜底只在候选 < 3 时用 1 次搜索
    """
    area = _clean_area(state.get('address') or '')
    category = state.get('category', '')
    city = extract_city(area)

    candidates = []
    seen = set()

    # 区域中心坐标：只 geocode 一次（1 次高德调用）
    target_lng, target_lat = (None, None)
    if area:
        target_lng, target_lat = geocode(area)
        await _emit(state, 'tool', '地址定位',
                    input_=f'定位「{area}」',
                    output=f'坐标 ({target_lng:.5f}, {target_lat:.5f})（优先本地库，0~1 次高德调用）'
                    if target_lng else f'「{area}」定位失败')

    def add_cand(name, address, lng, lat, source, area_m2=None, price=None, precise=False):
        key = (name, round(lng, 4), round(lat, 4))
        if key in seen:
            return
        seen.add(key)
        candidates.append({
            'name': name, 'address': address,
            'lng': lng, 'lat': lat, 'source': source,
            'area': area_m2, 'price': price, 'precise': precise,
        })

    # 第 1 轮：58 同城真实在租商铺（只抓一次；硬时限兜底，避免用户无限等待）
    if city and target_lng:
        area_filter = area
        for c in CITY_CODES:
            if area_filter.startswith(c):
                area_filter = area_filter[len(c):]
                break
        precise_budget = 8  # 精确坐标 geocode 预算（次）；标题含大厦/广场名可辅助精确定位
        t0 = time.monotonic()
        search_timeout = False
        try:
            try:
                shops = await asyncio.wait_for(
                    asyncio.to_thread(fetch_shops, city, 10, 30, area_filter or None),
                    timeout=35,
                )
            except asyncio.TimeoutError:
                shops = []
                search_timeout = True
            for s in shops:
                if time.monotonic() - t0 > 45:
                    search_timeout = True
                    break
                lng, lat, precise = None, None, False
                title_text = (s.get('title') or '').replace(' ', '')
                loc_text = (s.get('loc') or '').replace(' ', '')
                # 1) loc/标题里的"XX路XX号"等完整地址（1 次 geocode）
                m_addr = re.search(
                    r'([\u4e00-\u9fa5]{1,10}(?:路|街|道|巷|弄|大道)[\u4e00-\u9fa5A-Za-z0-9]*\d*号?)',
                    loc_text + title_text,
                )
                if m_addr and precise_budget > 0:
                    lng, lat = geocode(f'{city}{m_addr.group(1)}')
                    if lng:
                        precise_budget -= 1
                        precise = True
                # 2) 标题含"XX大厦/广场/中心/城/街"等地标名（1 次 geocode，定位到具体楼宇）
                if lng is None and precise_budget > 0:
                    m_landmark = re.search(
                        r'([\u4e00-\u9fa5A-Za-z0-9]{2,15}(?:大厦|广场|中心|城|街|里|坊|座|馆|园|苑|庭|府|汇))',
                        title_text,
                    )
                    if m_landmark:
                        lng, lat = geocode(f'{city}{m_landmark.group(1)}')
                        if lng:
                            precise_budget -= 1
                            precise = True
                # 3) 街道名（如"明楼""四桥南"）
                if lng is None and precise_budget > 0:
                    loc_parts = loc_text.split('-')
                    if len(loc_parts) >= 2:
                        street = loc_parts[-1]
                        if street and street not in ('空置中', '经营中') and city not in street:
                            lng, lat = geocode(f'{city}{street}')
                            if lng:
                                precise_budget -= 1
                                precise = True
                # 4) 其余回落区域中心（0 次额外 API）
                if lng is None:
                    lng, lat = target_lng, target_lat
                if not _in_zhejiang(lng, lat):
                    continue
                if haversine(target_lng, target_lat, lng, lat) > 30000:
                    continue
                # 地址展示：标题 + 位置合并（标题通常含楼宇名，比 loc 更具体）
                show_addr = f'{title_text}（{loc_text}）' if loc_text and title_text else (title_text or loc_text or area)
                add_cand(s['title'], show_addr, lng, lat, '58同城(在租)',
                         area_m2=s.get('area'), price=s.get('price'), precise=precise)
                if len(candidates) >= 6:
                    break
        except Exception:
            pass
        await _emit(state, 'tool', '58同城·实时在租抓取',
                    input_=f'{city}「{area_filter or "全区"}」品类近似检索',
                    output=(f'58 抓取超时（>30s），改用本地数据兜底'
                            if search_timeout else
                            f'抓取到 {len(shops)} 条在租商铺（无实时坐标则回落区域中心，省调用）'))
    if len(candidates) < 3 and target_lng:
        kw = f'{category}出租' if category else '商铺出租'
        try:
            rows, _ = await asyncio.to_thread(search_poi, kw, city or area, 2)
            for r in rows:
                if not _in_zhejiang(r['lng'], r['lat']):
                    continue
                add_cand(r['name'], r['address'], r['lng'], r['lat'], '高德POI(出租信息)')
                if len(candidates) >= 4:
                    break
        except Exception:
            pass
        await _emit(state, 'tool', '高德·POI 兜底搜索',
                    input_=f'关键词「{kw}」范围「{city or area}」',
                    output=f'候选 <3，兜底补齐 {len(rows)} 条' if rows else '高德配额超限/无结果，继续本地兜底')

    # 第 3 轮：本地数据库兜底（0 次 API；58/高德都失败/配额超限时也保证有候选可分析）
    used_fallback = False
    if len(candidates) < 3 and target_lng:
        try:
            from data.query import query_within
            seen_names = set()
            fb_count = 0
            for cat in ('商圈', '办公'):
                for poi in query_within(cat, target_lng, target_lat, 9000):
                    if poi['name'] in seen_names:
                        continue
                    seen_names.add(poi['name'])
                    if not _in_zhejiang(poi['lng'], poi['lat']):
                        continue
                    add_cand(poi['name'], poi.get('adname') or area,
                             poi['lng'], poi['lat'], '本地数据库(兜底)')
                    used_fallback = True
                    fb_count += 1
                    if len(candidates) >= 4:
                        break
                if len(candidates) >= 4:
                    break
        except Exception:
            fb_count = 0
            pass
        await _emit(state, 'tool', '本地数据库·兜底点位',
                    input_=f'范围「{area}」周边 9km 商圈/办公 POI',
                    output=f'58/高德未足额，从本地 4.4 万 POI 兜底 {fb_count} 个点位（0 次 API）'
                    if fb_count else '本地库也未取到候选')

    if candidates:
        src_hint = '（含本地库兜底点位，非实时在租）' if used_fallback else '（实时抓取）'
        reply = f'在「{area}」为你找到 **{len(candidates)}** 个候选商铺{src_hint}，回复序号（如"选1"）选择想分析的铺子：'
    else:
        reply = f'在「{area}」暂未搜到{category or "相关"}商铺，换个区域试试？'

    return {
        'messages': state['messages'] + [{'role': 'assistant', 'content': reply}],
        'candidates': candidates,
        'phase': 'select_shop' if candidates else 'no_shop',
        'list_shown': True,
    }


# ---------------------------------------------------------------
# 节点 4：选择商铺
# ---------------------------------------------------------------
async def select_shop_node(state: AgentState) -> Dict[str, Any]:
    """处理用户选择的候选商铺；未选择时给出简短提示（不重复整张列表）。"""
    user_msg = _last_user_msg(state)
    choice = _parse_choice(user_msg)
    candidates = state.get('candidates', [])

    # 没有选择序号
    if choice is None:
        if not candidates:
            return {
                'messages': state['messages'] + [{
                    'role': 'assistant',
                    'content': '暂无可选商铺，换个区域或告诉我其他想法吧。',
                }],
                'phase': 'no_shop',
            }
        # 等待选择：简短提示（候选列表由 UI 的 candidates 块渲染，避免重复）
        return {
            'messages': state['messages'] + [{
                'role': 'assistant',
                'content': '请回复上面的序号（如"选1"）选择想分析的铺子；也可以告诉我其他区域。',
            }],
            'phase': 'select_shop',
        }

    # 有选择序号：解析并进入分析
    idx = choice - 1
    if idx < 0 or idx >= len(candidates):
        return {
            'messages': state['messages'] + [{'role': 'assistant', 'content': '序号无效，请重新选择（如"选1"）。'}],
            'phase': 'select_shop',
        }

    c = candidates[idx]
    await _emit(state, 'think', '选择商铺',
                f'用户选择第 {choice} 号 → 「{c["name"]}」\n'
                f'坐标：({c["lng"]:.5f}, {c["lat"]:.5f})，来源：{c.get("source", "")}'
                f'，面积：{c.get("area", "-")}㎡，月租：{c.get("price", "-")}')
    filled = []
    if c.get('area'):
        filled.append(f"面积{c['area']}㎡")
    if c.get('price'):
        filled.append(f"租金{c['price']:.0f}元/月")

    # 用户本轮自己报了租金则优先，否则用平台租金，再否则留空（分析时按默认 8000）
    info = parse_request(user_msg)
    user_rent = info.get('rent')

    msg = f'已选：「{c["name"]}」（{c["address"]}）。'
    if filled:
        msg += f'\n已按平台信息填入：{"、".join(filled)}（可在对话中修正）。'
    if user_rent is None and not c.get('price'):
        msg += '\n（该铺未标注租金，暂按默认 ¥8000 测算，可补充实际月租修正）'
    if c.get('precise') is False:
        msg += ('\n⚠️ 该商铺仅有区域级定位（平台未提供精确坐标），分析将基于所在区域进行；'
                '若知道具体门牌/路名，可补充以获得精确分析。')
    msg += '\n\n' + ask_investment_message(state.get('category', ''))

    return {
        'messages': state['messages'] + [{'role': 'assistant', 'content': msg}],
        'address': _clean_area(c['name']),
        'pending_coord': (c['lng'], c['lat']),
        'selected_idx': idx,
        'area': c.get('area') or state.get('area'),
        'rent': user_rent if user_rent is not None else c.get('price'),
        'phase': 'collect_invest',
        'list_shown': True,
    }


# ---------------------------------------------------------------
# 节点 5：评分分析
# ---------------------------------------------------------------
async def analyze_node(state: AgentState) -> Dict[str, Any]:
    """调用评分引擎，生成评分结果（评分优先本地库，0 次实时 API）。"""
    cat = state['category']
    addr = state['address'] or ''
    rent = state.get('rent') or 8000
    area = state.get('area')

    addr = _clean_area(addr)

    # 候选商铺直接复用已定位坐标（0 次额外 geocode）；否则 geocode 一次
    if state.get('pending_coord'):
        lng, lat = state['pending_coord']
    else:
        lng, lat = geocode(addr)

    if lng is None:
        reply = f'「{addr}」无法定位坐标，请确认地址格式（如"杭州市西湖区文三路"）。'
        return {
            'messages': state['messages'] + [{'role': 'assistant', 'content': reply}],
            'phase': 'chat',
        }

    result = await asyncio.to_thread(
        score_site, cat, lng, lat, rent, addr, area,
        investment=state.get('investment'), staff=state.get('staff')
    )

    await _emit(state, 'tool', '选址评分引擎',
                input_=f'品类「{cat}」坐标 ({lng:.5f}, {lat:.5f}) 月租 ¥{rent:,.0f}'
                       f'（Huff 引力模型，本地 POI 库优先，0 次实时 API）',
                output=(f'总分 {result.get("total")} → {result.get("verdict")}；'
                        f'维度：' + '、'.join(f'{k}={v}' for k, v in (result.get("dims") or {}).items())))

    return {
        'score_result': result,
        'context': json.dumps(result, ensure_ascii=False),
        'phase': 'interpret',
    }


# ---------------------------------------------------------------
# 节点 6：LLM 解读（1 次 LLM 调用）
# ---------------------------------------------------------------
async def interpret_node(state: AgentState) -> Dict[str, Any]:
    """用 LLM 解读评分结果（一次调用；失败降级规则解读）。"""
    result = state.get('score_result')
    if not result:
        return {'phase': 'chat'}

    system_msg = """你是一位资深商铺选址顾问，服务对象是缺乏商业分析能力的个人创业者。
你的分析基于 Huff 引力模型（零售引力理论）的评分引擎输出。
要求：
1. 用口语化、有说服力的方式向创业者解释选址结论，先给结论再给理由；
2. 必须引用引擎返回的数据证据（竞品引力比、客群引力、通勤距离、租金占比等）；
3. 若引擎提供了水电成本和盈利测算（utility/profit 字段），必须解读；
4. 如实转达所有风险警告，帮用户避坑；
5. 最后必须附局限声明：基于公开POI数据，不含真实人流量与成交租金，水电为参考标准，建议现场复核；
6. 严禁编造引擎数据之外的任何数字。"""

    user_msg = f"评分引擎返回了以下真实数据：\n{json.dumps(result, ensure_ascii=False)}\n\n请基于以上数据，向用户输出选址建议。"

    await _emit(state, 'think', '生成解读',
                f'评分完成（总分 {result.get("total")}），调用 LLM 生成口语化选址解读…')

    try:
        interpretation = await call_llm(system_msg, user_msg, temperature=0.3, timeout=120)
        llm_note = '火山方舟·豆包'
    except Exception as e:
        from agent.agent import rule_based_interpret
        interpretation = rule_based_interpret(result)
        interpretation += f'\n\n[提示: LLM解读暂不可用，已用规则解读。原因：{e}。\n请检查 LLM API 账户余额/Key（可在 .env 配置 LLM_API_KEY / LLM_FALLBACK_API_KEY）。]'
        llm_note = '规则解读（LLM 暂不可用）'

    await _emit(state, 'tool', f'LLM 解读（{llm_note}）',
                input_=f'评分数据 → 口语化选址建议（含证据引用与风险）',
                output=f'解读完成，{len(interpretation)} 字' + ('（火山方舟·doubao-seed-2.1-pro）' if llm_note.startswith('火山') else ''))

    # 保存分析结果到本地（供"对比"功能跨对话使用；纯本地，0 次 API）
    try:
        from agent.analysis_store import add_analysis
        add_analysis(result, rent=state.get('rent'), area=state.get('area'),
                     investment=state.get('investment'), staff=state.get('staff'),
                     utility=result.get('utility'), profit=result.get('profit'),
                     interpretation=interpretation, city=state.get('city'))
    except Exception:
        pass

    # 未提供租金时补充默认说明
    if state.get('rent') is None:
        interpretation += '\n\n（注：未提供月租金，按默认 ¥8000 测算；可告诉我实际月租，修正后再帮你看）'

    summary = f"品类: {result.get('category')}, 地址: {result.get('name')}, 总分: {result.get('total')}, 结论: {result.get('verdict')}"

    return {
        'interpretation': interpretation,
        'messages': state['messages'] + [{'role': 'assistant', 'content': interpretation}],
        'phase': 'chat',
        'context': summary,
    }


# ---------------------------------------------------------------
# 节点 7：自由问答（1 次 LLM 调用）
# ---------------------------------------------------------------
async def free_chat_node(state: AgentState) -> Dict[str, Any]:
    """用户追问改进建议/客流/运营等；未分析商铺时也能自由聊天"""
    user_msg = state['messages'][-1]['content']
    context = state.get('context', '')

    if context:
        system_msg = f"""你是"浙里选址"的选址顾问。用户已经完成了一个商铺的选址分析。
以下是该商铺的评分摘要：{context}

请结合数据，用口语化、专业、有建设性的方式回答用户的问题。
涉及数据时必须引用真实数值，不要编造。"""
    else:
        system_msg = """你是"浙里选址"的选址顾问，专门帮个人创业者评估商铺选址。
用户目前还没有分析具体商铺。
请友好回答：如果是闲聊或一般问题，就正常聊天；如果涉及选址，
可以温和引导用户提供「想开什么品类 + 想开在哪个区域」，或具体商铺地址来开始分析。"""

    try:
        reply = await call_llm(system_msg, user_msg, temperature=0.5, timeout=120)
        llm_note = '火山方舟·豆包'
    except Exception as e:
        if context:
            reply = (f'（当前 AI 服务暂不可用：{e}）\n'
                     '你可以继续问，或让我分析其他地址。')
        else:
            reply = ('😊 我是浙里选址——你的 AI 商铺选址顾问！\n'
                     '告诉我「想开什么品类 + 想开在哪个区域」（如"帮我找杭州滨江的奶茶店"），'
                     '我帮你找在租商铺并评分；或告诉我具体商铺地址，我做 4 维度分析。\n'
                     '（注：当前 AI 联网服务暂不可用，恢复后即可自由聊天）')
        llm_note = '离线回复（LLM 暂不可用）'

    await _emit(state, 'tool', f'LLM 自由对话（{llm_note}）',
                input_=f'用户追问：{user_msg[:40]}',
                output=f'回答完成，{len(reply)} 字')

    return {
        'messages': state['messages'] + [{'role': 'assistant', 'content': reply}],
        'phase': 'chat',
        'compare_pending': False,
    }


# ---------------------------------------------------------------
# 节点 8：对比两个已分析商铺（跨对话；纯本地数据，0 次 API）
# ---------------------------------------------------------------
async def compare_node(state: AgentState) -> Dict[str, Any]:
    """列出所有已保存的分析（右侧工作台卡片勾选）→ 用户勾选 2-4 个序号 → 生成对比数据。
    对比数据由 UI 渲染（多列表格 + 多雷达图）。"""
    from agent.analysis_store import list_analyses
    user_msg = _last_user_msg(state)
    analyses = list_analyses()

    await _emit(state, 'think', '对比分析',
                f'已保存 {len(analyses)} 个分析；用户输入「{user_msg[:30]}」'
                f'{"→ 解析到多序号" if _parse_compare_pair(user_msg) else "→ 展示分析卡片列表"}')

    if len(analyses) < 2:
        reply = (f'目前只有 {len(analyses)} 个已完成的分析，至少需要 2 个才能对比。\n'
                 '先完成 2 个商铺的分析（可以新建对话分别分析）再回来对比。')
        return {
            'messages': state['messages'] + [{'role': 'assistant', 'content': reply}],
            'phase': 'chat',
            'comparison': None,
            'compare_pending': False,
            'compare_list': [],
        }

    pair = _parse_compare_pair(user_msg)
    if pair is not None and len(pair) >= 2:
        idxs = [p - 1 for p in pair]
        valid = [i for i in idxs if 0 <= i < len(analyses)]
        if len(valid) >= 2:
            chosen = [analyses[i] for i in valid[:4]]
            names = '、'.join(f"{p}. {a.get('shop', '?')}" for p, a in zip([i + 1 for i in valid[:4]], chosen))
            reply = f'📊 已为你对比 **{names}**。下面是全方位对比：'
            return {
                'messages': state['messages'] + [{'role': 'assistant', 'content': reply}],
                'comparison': {'items': chosen},
                'phase': 'chat',
                'compare_pending': False,
                'compare_list': [],
            }
        reply = '序号无效，请在右侧工作台勾选 2-4 个已分析商铺后再点「开始对比」。'
        return {
            'messages': state['messages'] + [{'role': 'assistant', 'content': reply}],
            'phase': 'compare',
            'comparison': None,
            'compare_pending': True,
            'compare_list': [{'i': k + 1, 'id': a.get('id', ''), 'shop': a.get('shop', '?'), 'category': a.get('category', ''),
                              'total': a.get('total'), 'verdict': a.get('verdict', ''),
                              'ts': a.get('ts', ''), 'dims': a.get('dims', {})}
                             for k, a in enumerate(analyses)],
        }

    # 未给序号 -> 把分析列表推给右侧工作台（卡片勾选）
    return {
        'messages': state['messages'] + [{'role': 'assistant',
                                          'content': f'📊 已找到 **{len(analyses)}** 个已完成的分析，请到**右侧工作台**勾选 2-4 个后点「开始对比」。'}],
        'phase': 'compare',
        'comparison': None,
        'compare_pending': True,
        'compare_list': [{'i': k + 1, 'id': a.get('id', ''), 'shop': a.get('shop', '?'), 'category': a.get('category', ''),
                          'total': a.get('total'), 'verdict': a.get('verdict', ''),
                          'ts': a.get('ts', ''), 'dims': a.get('dims', {})}
                         for k, a in enumerate(analyses)],
    }


# ---------------------------------------------------------------
# LangGraph 图定义
# ---------------------------------------------------------------
from langgraph.graph import StateGraph, START, END


def build_agent_graph():
    """构建 LangGraph 图"""
    workflow = StateGraph(AgentState)

    # 添加节点
    workflow.add_node('classify', classify_node)
    workflow.add_node('collect_info', collect_info_node)
    workflow.add_node('collect_invest', collect_invest_node)
    workflow.add_node('search_rental', search_rental_node)
    workflow.add_node('select_shop', select_shop_node)
    workflow.add_node('analyze', analyze_node)
    workflow.add_node('interpret', interpret_node)
    workflow.add_node('free_chat', free_chat_node)
    workflow.add_node('compare', compare_node)

    # 起始边
    workflow.add_edge(START, 'classify')

    # 意图识别后分流
    workflow.add_conditional_edges(
        'classify',
        lambda state: state.get('phase', 'collect_info'),
        {
            'intro': 'collect_info',       # 初始，进入找商铺信息收集
            'no_shop': 'collect_info',     # 找商铺：收集品类+地区（不问租金）
            'have_shop': 'collect_info',   # 有具体商铺：收集品类/地址/租金
            'select_shop': 'select_shop',  # 等待选择候选
            'collect_invest': 'collect_invest',  # 收集前期投入/人数
            'analysis': 'analyze',         # 直接分析
            'chat': 'free_chat',           # 自由问答
            'compare': 'compare',          # 对比两个已分析商铺
        }
    )

    # 信息收集后：搜索候选 / 分析 / 结束（等用户补充）
    workflow.add_conditional_edges(
        'collect_info',
        lambda state: state.get('phase', 'end'),
        {
            'search_rental': 'search_rental',
            'analysis': 'analyze',
            'collect_invest': END,  # 等用户回答投入，结束本轮
            'select_shop': END,   # 等用户选候选，结束本轮
            'no_shop': END,       # 等用户补品类/地区，结束本轮
            'have_shop': END,     # 等用户补品类/地址/租金，结束本轮
            'intro': END,         # 初始等待，结束本轮
            'end': END,
        }
    )

    # 前期投入收集后：齐备 -> 分析；未齐备 -> 等用户回答
    workflow.add_conditional_edges(
        'collect_invest',
        lambda state: 'analysis' if state.get('phase') == 'analysis' else 'end',
        {'analysis': 'analyze', 'end': END},
    )

    # 候选搜索后：有候选 -> 选择商铺；无候选 -> 结束本轮（等用户换区域，避免空转）
    workflow.add_conditional_edges(
        'search_rental',
        lambda state: 'select_shop' if state.get('candidates') else 'end',
        {'select_shop': 'select_shop', 'end': END},
    )

    # 选择商铺后 -> 收集信息（选中的走 collect_invest/analysis 分支，未选等待）
    workflow.add_edge('select_shop', 'collect_info')

    # 评分分析后 -> LLM 解读
    workflow.add_edge('analyze', 'interpret')

    # LLM 解读后 -> 结束
    workflow.add_edge('interpret', END)

    # 自由问答后 -> 结束
    workflow.add_edge('free_chat', END)

    # 对比后 -> 结束（对比数据由 UI 渲染）
    workflow.add_edge('compare', END)

    return workflow.compile()


# 编译图
agent_graph = build_agent_graph()


async def run_agent(user_msg: str, state: AgentState = None, hooks: dict = None) -> AgentState:
    """运行 Agent 图。hooks 可传 {'on_event': async callable} 实时推送执行过程事件。"""
    if state is None:
        state = AgentState(messages=[], phase='intro', candidates=[], missing_info=[],
                           comparison=None, compare_pending=False,
                           investment=None, staff=None)

    if 'messages' not in state:
        state['messages'] = []
    state['messages'].append({'role': 'user', 'content': user_msg})

    # 执行过程事件钩子（thinking/tool 实时推送 + 步骤日志）
    hooks = hooks or {}
    hooks.setdefault('steps', [])
    state['hooks'] = hooks
    state['steps'] = hooks['steps']

    # recursion_limit: 正常一轮 2~5 个节点; 上限 12 防止逻辑缺陷导致死循环刷爆外部 API
    result = await agent_graph.ainvoke(state, config={'recursion_limit': 12})

    result['steps'] = hooks['steps']
    # hooks 含回调函数，不可 JSON 序列化（历史会话存储需要），从结果中剥离
    result.pop('hooks', None)
    return result
