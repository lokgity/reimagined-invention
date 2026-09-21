# -*- coding: utf-8 -*-
"""
app_chainlit.py —— Chainlit + LangGraph 版浙江商铺选址 AI 顾问
================================================================
启动: chainlit run src/ui/app_chainlit.py --port 8502
架构: Chainlit (UI) + LangGraph (Agent) + Huff 引力模型 (评分)
优势: ChatGPT 风格对话界面，产品感强，工具调用可视化
"""
import sys
import os
import io
import re
import json
import math
import time
import base64
import asyncio
import requests
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PYLIBS = ROOT / '.pylibs'

# 图片库：优先系统全局 PIL（Python 3.12 下 .pylibs/PIL 是 cp314 构建，不可用）
_PIL_OK = False
try:
    from PIL import Image as PILImage, ImageDraw, ImageFont
    _PIL_OK = True
except Exception:
    PILImage = ImageDraw = ImageFont = None

sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(PYLIBS))
os.chdir(str(ROOT))

# 全局无 PIL（如 Python 3.14 只有 .pylibs 版本）时回落到 .pylibs
if not _PIL_OK:
    from PIL import Image as PILImage, ImageDraw, ImageFont  # noqa: F811

import chainlit as cl

from agent.agent_graph import run_agent, AgentState
from agent.conversation_store import (new_conversation, save_conversation,
                                      get_conversation, list_conversations,
                                      derive_title)
from engine.scoring import score_site, PAYBACK_LIMIT_MONTHS, query_pois
from engine import road_sim                      # 仿真看板（小人沿马路走）
from config import CATEGORY_PROFILES, get_profile, DATA_DIR
from data.query import query_within
from agent.llm import set_llm_model, MODEL_OPTIONS, DEFAULT_MODEL

# 公网访问闸门（演示模式开关 / 每 IP 限流 / 全局日预算）—— 纯逻辑在 ui/access_gate.py
from ui.access_gate import (gate_config, gate_summary, gate_ledger,
                            client_ip, is_private, demo_reject)

# 启动即打印闸门状态：开了什么、关了什么必须说出来（红线 4：不静默）
_GATE_CFG = gate_config()
print('[gate] ' + gate_summary(_GATE_CFG))


# ---------------------------------------------------------------
# 会话状态管理
# ---------------------------------------------------------------
def get_state() -> dict:
    """获取或创建当前用户的状态（含会话 id）"""
    state = cl.user_session.get('state')
    if state is None:
        state = {'messages': [], 'phase': 'intro', 'candidates': [], 'missing_info': [],
                 'investment': None, 'staff': None, 'comparison': None, 'compare_pending': False}
        cl.user_session.set('state', state)
    if cl.user_session.get('conv_id') is None:
        cl.user_session.set('conv_id', new_conversation('新会话'))
    return state


def _persist_conversation(state: dict):
    """把当前会话状态+标题保存到本地（历史会话保留，0 次 API）"""
    try:
        conv_id = cl.user_session.get('conv_id') or new_conversation('新会话')
        cl.user_session.set('conv_id', conv_id)
        # 附件正文最长 1.2 万字，原样落盘会让 conversations.json 迅速膨胀，
        # 所以只存"元信息 + 短预览"（会话内存里仍是全文，回答照常引用）。
        slim = dict(state)
        if slim.get('attachments'):
            slim['attachments'] = _attach_brief(slim['attachments'])
        save_conversation(conv_id, slim, title=derive_title(state))
    except Exception as e:
        print('[conv] persist error:', e)


# ---------------------------------------------------------------
# 左侧操作栏数据（写入 public/sidebar.json，前端 custom_js 读取渲染）
# ---------------------------------------------------------------
def _history_stats() -> int:
    from agent.analysis_store import list_analyses
    try:
        return len(list_analyses())
    except Exception:
        return 0


def _conv_mark(c: dict) -> str:
    return '分析' if (c.get('state') or {}).get('score_result') else '对话'


def _sim_index() -> list:
    """供左栏「仿真大屏」的**选择卡片页**：每次分析一行 + 有没有大屏快照。

    ⚠️ 为什么不能只靠 last_sim.json：那只有"最近一次"，用户没法挑。
    策 2026-09-21 15:33：「这个仿真大屏的功能我也需要和对比分析一样，
    先有卡片给我选择这个仿真大屏展示的是哪次分析的内容，然后再显示具体的内容」。
    这里**复用"对比分析"同一份 analyses.json**，保证两处的列表与排序一致
    （否则同一个铺子在两个入口里的顺序/编号不同，用户会懵）。
    """
    try:
        from agent.analysis_store import list_analyses, list_board_ids
        bids = list_board_ids()
        out = []
        for a in reversed(list_analyses()):          # 最近的排前面
            out.append({
                'id': a.get('id'), 'ts': a.get('ts', ''),
                'shop': a.get('shop', ''), 'category': a.get('category', ''),
                'total': a.get('total'), 'verdict': a.get('verdict', ''),
                'has_board': a.get('id') in bids,
            })
        return out
    except Exception as e:                                       # noqa: BLE001
        print('[sidebar] sim_index error:', e)
        return []


def _expert_payload() -> list:
    """专家列表 → 前端（输入框上方面板 + 左侧「专家系统」卡片页）共用一份数据。

    ⚠️ **不在前端写死 9 位专家**。写死就破坏了本项目"加专家 = 加 md 文件、不改代码"
    的约定（同样地，也不在这里维护"id → 人名"的映射表：人名住在各专家自己的 md 里，
    是单一真源）。
    """
    try:
        from experts import registry
        return [e.card() for e in registry.list_experts()]
    except Exception as e:
        print('[sidebar] experts error:', e)
        return []


async def refresh_sidebar():
    """把左侧操作栏数据写入 public/sidebar.json（纯本地，0 次 API）。
    hist 含每个会话的完整消息（messages），供前端点击历史项直接 fetch 渲染预览，
    不再往输入框注入 ##预览 指令（避免聊天区出现指令字样、且点开更稳定）。

    `experts` / `current_expert` 供前端画「专家选择面板」与「专家系统卡片页」；
    前端不写死专家清单（见 `_expert_payload`）。"""
    try:
        convs = list_conversations(30)
        hist = []
        for c in convs:
            sr = (c.get('state') or {}).get('score_result')
            msgs = []
            for m in ((c.get('state') or {}).get('messages') or []):
                txt = (m.get('content') or '').strip()
                if txt:
                    msgs.append({'role': m.get('role', 'assistant'), 'content': txt[:4000]})
            hist.append({
                'id': c['id'],
                'title': (c.get('title') or '会话')[:16],
                'ts': c.get('updated') or c.get('ts', ''),
                'mark': _conv_mark(c),
                'total': sr.get('total') if sr and sr.get('total') else None,
                'messages': msgs[-60:],
                'analysis': {
                    'shop': sr.get('name', ''),
                    'category': sr.get('category', ''),
                    'total': sr.get('total'),
                    # 经营评分（'能不能赚钱'）：结论以它为准，历史摘也要带上
                    'biz': (sr.get('经营评分') or {}).get('分数'),
                    'verdict': sr.get('verdict', ''),
                } if sr else None,
            })
        cur_state = cl.user_session.get('state') or {}
        data = {'analyses': _history_stats(), 'hist': hist,
                # ⚠️ 键名不能叫 analyses —— 上面那个已被"分析数(int)"占了。
                'sim_list': _sim_index(),
                'model': cl.user_session.get('llm_model') or DEFAULT_MODEL,
                'free_chat': bool(cl.user_session.get('free_chat')),
                'experts': _expert_payload(),
                'current_expert': cur_state.get('expert') or ''}
        (ROOT / 'public').mkdir(parents=True, exist_ok=True)
        (ROOT / 'public' / 'sidebar.json').write_text(
            json.dumps(data, ensure_ascii=False), encoding='utf-8')
    except Exception as e:
        print('[sidebar] error:', e)


# ---------------------------------------------------------------
# 模型选择持久化 + 历史会话独立页数据端点
# ---------------------------------------------------------------
MODEL_FILE = DATA_DIR / 'llm_model.txt'


def _load_model() -> str:
    try:
        v = MODEL_FILE.read_text(encoding='utf-8').strip()
        if v in MODEL_OPTIONS:
            return v
    except Exception:
        pass
    return DEFAULT_MODEL


def _save_model(name: str):
    try:
        MODEL_FILE.write_text(name, encoding='utf-8')
    except Exception:
        pass


async def process_set_model(name: str):
    """切换后续商铺分析使用的 LLM（##模型:<name>##）。"""
    if name not in MODEL_OPTIONS:
        await cl.Message(content=f'⚠️ 未知模型：{name}').send()
        return
    cl.user_session.set('llm_model', name)
    _save_model(name)
    set_llm_model(name)
    if MODEL_OPTIONS[name] is None:
        await cl.Message(content=f'已选择 **{name}**，但该模型尚未配置 API（mimo 暂未启用），'
                                 f'本次分析将回退到默认模型。').send()
    else:
        await cl.Message(content=f'✅ 已切换模型：**{name}**，后续商铺分析将使用该模型。').send()
    await refresh_sidebar()


async def process_free_chat_toggle(val: str):
    """需求4：手动切换「自由对话」模式（##自由对话:on|off##）。

    规则闸门（classify_node 里的咨询词判定）再准也有漏网，
    这是给用户的最后一道保险：打开后所有消息都不再触发选址流程。

    ⚠️ **本函数刻意不回消息**（2026-09-16 改）。
    开关是"界面状态"，不是"对话内容"——回一条「已开启自由对话」会白白占掉
    对话框一行，把用户真正想看的分析结论往下顶。现在改成：
    前端按钮点击时自己弹一个 3 秒浮层提示，后端只负责改状态 + 落盘。
    前端拿 `sidebar.json.free_chat` 做二次校验，所以"后端没收到"也能被发现
    （按钮会自己弹回去），不存在"静默失败"。"""
    from agent.agent_graph import set_free_chat_mode
    on = str(val or '').strip().lower() in ('on', '1', 'true', 'yes', '开', '开启')
    cl.user_session.set('free_chat', on)
    set_free_chat_mode(on)
    await refresh_sidebar()


async def process_export():
    """导出分析报告（重新生成当前会话最后一次分析的 PDF 附件，0 次额外 API）。"""
    state = get_state()
    sr = state.get('score_result')
    if not sr:
        await cl.Message(content='当前会话还没有已完成的分析可导出。先完成一次分析后再导出。').send()
        return
    interp = ''
    for m in reversed(state.get('messages', [])):
        if m.get('role') == 'assistant' and m.get('content'):
            interp = m['content']
            break
    try:
        # 复用落盘（同一会话的 PDF 不变）：导出不再重跑 Playwright
        pdf_bytes = await _analysis_pdf(sr, interp, cl.user_session.get('conv_id'))
        if not pdf_bytes:
            await cl.Message(content='导出失败：PDF 生成无输出。').send()
            return
        fname = f"址南针_分析报告_{str(sr.get('name', ''))[:12]}.pdf"
        await cl.Message(
            content='**导出分析报告**（PDF）：',
            elements=[cl.Pdf(name=fname, content=pdf_bytes, display='inline')],
        ).send()
    except Exception as e:
        print('[export] error:', e)
        await cl.Message(content=f'导出失败：{e}').send()


# ---------------------------------------------------------------
# §2 历史会话的「独立只读中间页」已在 2026-09-17 退休
# ---------------------------------------------------------------
# 原 `process_preview_conv()`（写 public/conv_page.json → 前端轮询 → 覆盖层只读页）
# 与同步备用版 `_conv_page_payload()` 一并删除。原因见下方 `process_open_conv`：
# 用户要的是"点一下就到、并且把聊天内容也恢复出来"，而中间页正好是这两件事的阻碍 ——
# 它逼用户点第二次，且进去之后只有右栏数据+PDF、对话内容全丢。
# 知识库页 / 专家卡片页仍然用同一个覆盖层容器（`openPage`），只是历史这条路径不再走它。


# ---------------------------------------------------------------
# 右侧"分析工作台"数据（写入 public/dashboard.json，前端 custom_js 读取渲染）
# ---------------------------------------------------------------
DASHBOARD_FILE = ROOT / 'public' / 'dashboard.json'
# 仿真看板快照（2026-09-21）：**单独一份文件，不受 clear_dashboard() 影响**。
# 为什么必须分开：dashboard.json 在开新会话 / 切历史会话时会被写成 {'kind':'clear'}，
# 而仿真看板原先只是右栏的一个 section，跟着一起没了 —— 用户开个新会话就再也点不到。
# 但"上一次跑出来的仿真"是**已经发生的取证结果**，不该因为开新会话被抹掉
# （红线 3：不改写历史）。所以它走独立文件、独立生命周期。
LAST_SIM_FILE = ROOT / 'public' / 'last_sim.json'
_DIM_WEIGHTS ={'客群匹配度': '35%', '竞争环境': '25%', '交通可达性': '25%', '租金承受力': '15%', '面积适配度': '10%'}
_DIM_LABELS = {'竞争压力': '竞争环境'}  # 分数高=竞争少=环境优，字面语义与分数方向一致


def _fmt_money(v):
    try:
        v = float(v)
    except Exception:
        return '-' if v is None else str(v)
    # 负号必须在货币符号前面：'¥-115,653' 会被读成"¥ 减 11 万"，'-¥115,653' 才是亏损
    return ('-' if v < 0 else '') + f'¥{abs(v):,.0f}'


def _fmt_num(v):
    """人类可读数值：去掉原始浮点尾巴（如 179.74647248686 -> 180、0.00011 -> 0.00011）。"""
    try:
        v = float(v)
    except Exception:
        return '-' if v is None else str(v)
    if abs(v) >= 100:
        return f'{v:.0f}'
    if abs(v) >= 1:
        return f'{v:.1f}'
    return f'{v:.4g}'


def write_dashboard(payload: dict):
    try:
        (ROOT / 'public').mkdir(parents=True, exist_ok=True)
        payload['ts'] = time.strftime('%H:%M:%S')
        DASHBOARD_FILE.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    except Exception as e:
        print('[dashboard] error:', e)


def clear_dashboard():
    # ⚠️ 只清 dashboard.json，**绝不碰 last_sim.json**。
    # 仿真看板快照是历史取证结果，开新会话不该抹掉它（见 LAST_SIM_FILE 注释）。
    write_dashboard({'kind': 'clear'})


def _log_caliber():
    """启动时把**口径版本**打到日志里。

    为什么要这行：2026-09-21 排查时发现 8502 上跑的是个 7 小时前启动的旧实例，
    加载的还是 v7 的 UPLIFT 表 —— 而所有门禁、文档都已经切到 v8 了。
    服务不重启就不生效（Chainlit 不热重载），但**日志里看不出跑的是哪一套**，
    只能靠查进程创建时间反推。加这一行，以后一眼就能确认。
    """
    try:
        from engine.brands import UPLIFT, UPLIFT_TIER, _UPLIFT_N
        t1 = sorted(b for b, t in UPLIFT_TIER.items() if t == 'TIER1')
        print('[口径] UPLIFT 瑞幸=%s(n=%s) 蜜雪=%s(n=%s) 古茗=%s | TIER1=%s | 品牌数=%d'
              % (UPLIFT.get('瑞幸'), _UPLIFT_N.get('瑞幸'),
                 UPLIFT.get('蜜雪冰城'), _UPLIFT_N.get('蜜雪冰城'),
                 UPLIFT.get('古茗'), '、'.join(t1) or '无', len(UPLIFT)), flush=True)
        print('[口径] v8 步行路网基准：瑞幸 1.3271(n=42) / 蜜雪 1.0(n=154) / '
              '古茗 0.997(n=200) / TIER1=奈雪、春莱、瑞幸', flush=True)
    except Exception as e:                                       # noqa: BLE001
        print('[口径] 读取失败：%r' % (e,), flush=True)


_log_caliber()


def write_last_sim(sim: dict, result: dict, map_b64: str = '', board: dict = None):
    """把仿真大屏快照单独落盘，供左栏「仿真看板」按钮在新会话里也能打开。

    ⚠️ 红线 4（外部数据带来源）：快照必须自带 **来源会话 id + 取证时间 +
    铺位经纬度/半径**。否则用户在新会话里看到一块没有出处的动图，
    无法判断它是不是这一轮、这一个铺子的结果。
    ⚠️ 落盘条件：`board`（自绘大屏场景）或 `sim`（旧的底图叠加）**任一**为 ok。
    2026-09-21 起主场景是 `board`；`sim` 保留是为了不打断右栏那块旧渲染。
    """
    _bok = isinstance(board, dict) and board.get('ok')
    if not _bok and not (isinstance(sim, dict) and sim.get('ok')):
        return
    try:
        sid = ''
        try:
            sid = cl.user_session.get('id') or ''
        except Exception:
            sid = ''
        _meta = ((board or {}).get('meta') if _bok else (sim or {}).get('meta')) or {}
        payload = {
            'kind': 'sim_board',
            '来源会话': sid or '未知（服务端未取到 session id）',
            '取证时间': time.strftime('%Y-%m-%d %H:%M:%S'),
            # ⚠️ analysis_id 让这份快照能和"对比分析"同一份分析列表**对上号**，
            #    从而支持"先挑哪一次、再看大屏"（策 2026-09-21 15:33）。
            #    它由 analysis_store.add_analysis() 回写进 result（见那里的注释）。
            'analysis_id': result.get('analysis_id', ''),
            '铺位': result.get('name', ''),
            '品类': result.get('category', ''),
            '品牌': result.get('brand', ''),
            '地址评分': result.get('total'),
            '结论': result.get('verdict', ''),
            'lng': result.get('lng'),
            'lat': result.get('lat'),
            '半径m': _meta.get('半径m'),
            'map_b64': map_b64 or '',
            'board': board or {},
            'sim': sim or {},
        }
        (ROOT / 'public').mkdir(parents=True, exist_ok=True)
        # 「最近一次」快照（左栏按钮的默认页）—— 与下面按 id 存的那份是同一内容
        LAST_SIM_FILE.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        # 按 analysis_id 再存一份，供"挑哪一次"的卡片页使用
        try:
            from agent.analysis_store import save_board
            if not save_board(result.get('analysis_id'), payload):
                print('[sim_board] 未按 id 落盘（result 里没有 analysis_id）')
        except Exception as e:                                   # noqa: BLE001
            print('[sim_board] save error:', e)
    except Exception as e:                                       # noqa: BLE001
        print('[last_sim] error:', e)


def _last_assistant_msg(state: dict) -> str:
    for m in reversed(state.get('messages', [])):
        if m.get('role') == 'assistant' and m.get('content'):
            return str(m['content'])
    return ''


def maybe_push_input_form(state: dict):
    """当 agent 正在等待用户输入结构化经营参数时，把录入表单数据写入工作台。
    仅在明确等待投入/人数或缺失信息时覆盖工作台（0 次 API）。"""
    try:
        # 品牌选择阶段：工作台必须留给品牌卡片，不被投入表单覆盖
        if state.get('phase') == 'collect_brand' and not state.get('brand'):
            return
        last = _last_assistant_msg(state)
        if not last:
            return
        fields = []
        mode = ''
        hint = ''
        if ('最后确认一下' in last) or ('请回复前期投入成本' in last):
            mode = 'invest'
            hint = '请确认经营参数，我将据此完成盈利测算与四维评分'
            # 诉求④：表单里带上所选品牌的加盟费，并在前端做第一道"低于加盟费"的软提示
            # （后端 collect_invest_node 还有第二道，两层都只提示不硬拦）。
            jf = None
            brand = state.get('brand') or ''
            if brand:
                try:
                    from engine.brands import get_join_fee
                    jf = get_join_fee(brand)
                except Exception:
                    jf = None
            # ⚠️ note 会原样进 HTML（不走 markdown 渲染），所以**不能带 `**`**，
            #    否则星号会直接显示出来（卡片 label 踩过同一个坑）。
            inv_note = '含加盟费/保证金/设备/装修/首批物料，不含房租押金'
            inv_floor = None
            inv_floor_txt = ''
            # ⚠️ **必须按 status 三态分派，不能按 `if jf.get('fee'):` 分派。**
            #    2026-09-18 修：瑞幸 fee=0（"明确不收"是事实）在旧写法里是 falsy，
            #    会掉进 elif 分支、在表单上写「瑞幸 暂无公开加盟费口径」——
            #    这句是假话，而且正是本轮在 `agent_graph.py` 修掉的那句。
            #    同一件事的两个表面（聊天提示 / 表单提示）必须一起改。
            if jf and jf.get('status') == 'none':
                # 明确不收：不设下限（设了会误拦），但要说"明确不收"而不是"查不到"，
                # 并给出品牌实际的收费方式（毛利阶梯分成），否则用户以为零成本。
                inv_note += (f'　｜　{brand} 明确不收加盟费，此项不做下限校验'
                             f'（品牌方按门店月毛利阶梯分成，需另行核算）')
            elif jf and jf.get('fee'):
                inv_floor = int(jf['fee'])
                inv_floor_txt = jf.get('text') or ''
                # ⚠️ `jf['text']` **本身就以"加盟费"开头**，这里不能再写一遍
                #    —— 否则界面会念成"蜜雪冰城 加盟费 加盟费 ¥11,000"（实机抓到过）。
                inv_note += (f'　｜　{brand}：{inv_floor_txt}，'
                             f'投入不得低于此数（低于需确认）')
            elif brand:
                inv_note += f'　｜　{brand} 暂无公开加盟费口径，不做下限校验'
            fields = [
                {'key': 'investment', 'label': '前期投入成本', 'unit': '万元',
                 'placeholder': '如 12', 'default': '',
                 'note': inv_note, 'floor': inv_floor, 'floorText': inv_floor_txt,
                 'floorBrand': brand},
                {'key': 'staff', 'label': '运营人数', 'unit': '人', 'placeholder': '默认按品类', 'default': ''},
            ]
        elif state.get('missing_info'):
            mode = 'missing'
            hint = '补充以下信息，我就能继续为你选址或分析'
            for item in state['missing_info']:
                if '品类' in item:
                    fields.append({'key': 'category', 'label': '想开什么品类', 'unit': '',
                                   'placeholder': '奶茶 / 甜品 / 早餐 / 便利店', 'default': ''})
                elif ('区域' in item) or ('位置' in item) or ('地址' in item):
                    fields.append({'key': 'address', 'label': '位置 / 区域', 'unit': '',
                                   'placeholder': '如 杭州滨江', 'default': ''})
                elif '租金' in item:
                    fields.append({'key': 'rent', 'label': '月租金', 'unit': '元/月',
                                   'placeholder': '如 8000', 'default': ''})
                elif '面积' in item:
                    fields.append({'key': 'area', 'label': '面积', 'unit': '㎡',
                                   'placeholder': '如 30', 'default': ''})
        if fields:
            write_dashboard({
                'kind': 'input', 'mode': mode, 'hint': hint,
                'fields': fields, 'flow': state.get('phase', ''),
                'category': state.get('category', ''),
            })
    except Exception as e:
        print('[input-form] error:', e)


def build_analysis_dashboard(result: dict, map_b64: str = '') -> dict:
    """把一次分析结果构造成右侧工作台数据（纯本地）"""
    p = result.get('profit') or {}
    u = result.get('utility') or {}
    e = result.get('evidence') or {}
    dims = result.get('dims') or {}
    dims = {_DIM_LABELS.get(k, k): v for k, v in dims.items()}  # 展示名（竞争压力→竞争环境）
    verdict = result.get('verdict') or ''
    total = result.get('total')
    payback = p.get('回本周期(月)')
    np_ = p.get('月净利估算')

    def tone_for(v, good_th=80, mid_th=60):
        try:
            v = float(v)
            if v >= good_th:
                return 'good'
            if v >= mid_th:
                return 'mid'
            return 'bad'
        except Exception:
            return 'mid'

    veto = result.get('veto') or {}
    rl = result.get('rent_limits') or {}
    be_rent = rl.get('盈亏平衡月租')
    cap_rent = rl.get('回本达标月租上限')
    rent_now = p.get('月租金') or result.get('monthly_rent') or 0

    def signed_money(v):
        """带正负号的金额；正号是为了让"安全垫 +¥72,350"和"-¥115,650"在同一列里能直接比。"""
        try:
            float(v)
        except Exception:
            return '-'
        return ('+' if float(v) >= 0 else '') + _fmt_money(v)

    # 经营评分（2026-09-16 新增）："这个租金下能不能赚钱"。结论以它为准，
    # 地址评分降为维度指标。无月租/无面积时**不出分**，把原因写在卡上（不猜）。
    #
    # ⚠️ 三种"没有分"必须分开说（实机在历史会话上踩到，2026-09-17）：
    #   ① 字段在、有分数        → 直接显示；
    #   ② 字段在、分数为 None   → 显示 `不可得原因`（真的算不出：无月租/无面积/无前期投入）；
    #   ③ **字段压根不存在**    → 说明这条结果生成于**旧版本引擎**（本功能上线前存盘的）。
    #      改前 ② ③ 都落到 "不出分"，于是历史会话卡片上写着"不出分"，
    #      看着像"这个铺子算不出来"，其实是"这份分析早于该功能"—— 两种含义完全不同，
    #      混成一句就是在误导用户（也可能被答辩时当成 bug）。
    if '经营评分' not in result:
        biz = {}
        biz_missing = True
    else:
        biz = result.get('经营评分') or {}
        biz_missing = False
    biz_score = biz.get('分数')
    biz_band = biz.get('区间')
    if biz_missing:
        _biz_val, _biz_unit, _biz_tone = '旧版本结果，请重新分析', '', 'mid'
        _biz_label = '经营评分（本结果未含）'
    elif biz_score is not None:
        _biz_val, _biz_unit = str(biz_score), '分'
        _biz_tone = tone_for(biz_score or 0)
        _biz_label = '经营评分' + ('（一票否决封顶）' if biz.get('一票否决封顶') else '')
    else:
        _biz_val, _biz_unit, _biz_tone = (biz.get('不可得原因') or '不出分'), '', 'bad'
        _biz_label = '经营评分（不出分）'

    cards = [
        # 原「综合评分」改名「地址评分」：它衡量的是**这个位置本身好不好**，
        # 结构上不含成本与利润（profit 在 total 定稿之后才算）。
        {'label': '地址评分', 'value': str(total) if total is not None else '-',
         'unit': '分', 'tone': tone_for(total or 0)},
        {'label': _biz_label, 'value': _biz_val, 'unit': _biz_unit, 'tone': _biz_tone},
        {'label': '经营评分区间(三档)',
         'value': (f'{biz_band[0]} ~ {biz_band[1]}' if biz_band else '-'),
         'unit': '', 'tone': 'mid'},
        # 卡片 label 走的是纯文本渲染（不解析 markdown），所以这里**不能**写 `**加粗**`
        # —— 实机截图里会原样显示成「（**旧版本，仅地址**）」。用方括号代替强调。
        {'label': ('选址结论［旧版本·仅地址］' if biz_missing
                   else '选址结论（以经营评分为准）'),
         'value': verdict, 'unit': '',
         # 一票否决时结论已被改写（"位置好·账算不过来"），必须压成 bad：
         # 否则位置分 90+ 会让评分卡显示绿色，用户只扫一眼颜色就以为能签
         'tone': 'bad' if veto.get('触发') else
                 ('good' if verdict == '推荐' else ('mid' if verdict == '谨慎推荐' else 'bad'))},
        {'label': '月净利(中性档)', 'value': _fmt_money(np_), 'unit': '/月',
         'tone': 'good' if (np_ or 0) > 0 else 'bad'},
        {'label': '回本(中性档)', 'value': str(payback) if payback else '难回本',
         'unit': '个月' if payback else '', 'tone': 'good' if payback else 'bad'},
        {'label': '前期投入', 'value': _fmt_money(p.get('前期投入')), 'unit': '',
         'tone': 'mid'},
        {'label': '周边竞品', 'value': str(e.get('竞品数', '-')), 'unit': '家', 'tone': 'mid'},
    ]
    if be_rent:
        cushion = be_rent - rent_now
        cards.append({'label': '盈亏平衡月租', 'value': _fmt_money(be_rent), 'unit': '/月',
                      'tone': 'good' if cushion >= 0 else 'bad'})
        cards.append({'label': '租金安全垫', 'value': signed_money(cushion), 'unit': '/月',
                      'tone': 'good' if cushion > 0 else 'bad'})

    # 口径区间（价格-单量弹性未知）：必须紧跟月净利/回本两张卡片，因为那两张的
    # 单点值只对应区间的一端（"单量刚性"端），不是中点，也不是真值。
    calipers = result.get('口径区间') or {}
    civ = calipers.get('区间') or {}
    if civ:
        _nlo, _nhi = civ.get('月净利区间(元/月)') or (None, None)
        cards.append({'label': '月净利区间(弹性两端)',
                      'value': f'{_fmt_money(_nlo)} ~ {_fmt_money(_nhi)}', 'unit': '/月',
                      # 悲观端为正才算 good：只给区间不给态度，用户会挑自己爱看的那端
                      'tone': 'good' if (_nlo or 0) > 0 else 'bad'})
        # 四档（2026-09-20）：布尔"结论稳健"保留作兼容，展示优先用"稳健档"。
        # 档位是**确定性等级、不是概率**，也不表示生意好坏。
        _tier = civ.get('稳健档')
        if not _tier:                       # 兼容旧记录（只存了布尔）
            _tier = '稳健' if civ.get('结论稳健') else '不稳健'
        cards.append({'label': '口径稳健性', 'value': _tier, 'unit': '',
                      'tone': {'稳健': 'good', '比较稳健': 'mid',
                               '比较不稳健': 'mid', '不稳健': 'bad'}.get(_tier, 'mid')})

    w_raw = result.get('weights') or {}
    w_by_label = {_DIM_LABELS.get(k, k): v for k, v in w_raw.items()}
    dim_rows = [{'name': k, 'value': v,
                 'weight': (f'{w_by_label[k] * 100:.0f}%' if isinstance(w_by_label.get(k), (int, float))
                            else _DIM_WEIGHTS.get(k, '-'))}
                for k, v in dims.items()]

    profit_rows = []
    if p:
        profit_rows = [
            ('预估月流水', _fmt_money(p.get('月流水估算'))),
            ('月物料成本', f"{_fmt_money(p.get('月物料成本'))}（占流水 {p.get('物料占比', 0):.0%}）"),
            ('月人工', f"{_fmt_money(p.get('月人工'))}（{p.get('人数', '-')}人×¥{p.get('人均月薪', 0):,.0f}市场工资，含社保 {p.get('社保负担率', 0):.0%}）"),
            ('月外卖抽成', f"{_fmt_money(p.get('月外卖抽成'))}（外卖占流水 {p.get('外卖占比', 0):.0%}×抽成 {p.get('外卖抽成率', 0):.0%}）"),
            ('月场地附加费', f"{_fmt_money(p.get('月场地附加费'))}（商场扣点/物业费/推广费，占流水 {p.get('场地附加费率', 0):.0%}）"),
            ('月税', f"{_fmt_money(p.get('月税'))}（占流水 {p.get('税负率', 0):.1%}）"),
            ('月损耗', f"{_fmt_money(p.get('月损耗'))}（物料报废，占流水 {p.get('损耗率', 0):.0%}）"),
            ('月租金', _fmt_money(p.get('月租金'))),
            ('月水电', _fmt_money(p.get('月水电'))),
            ('月杂费', _fmt_money(p.get('月杂费'))),
            ('月摊销', f"{_fmt_money(p.get('月摊销'))}（投入按 {p.get('摊销月数', '-')} 个月摊）"),
        ]
        if p.get('月品牌费'):
            profit_rows.append(('月品牌费', f"{_fmt_money(p.get('月品牌费'))}（{p.get('品牌', '')}）"))
        if p.get('人数') != p.get('申报人数'):
            profit_rows.append(('人数口径', str(p.get('人数口径') or '-')))
        profit_rows += [
            ('月成本合计', _fmt_money(p.get('月成本合计'))),
            ('前期投入', f"{_fmt_money(p.get('前期投入'))}（{p.get('投入来源', '')}）"),
            ('装修档次', (result.get('decoration') or {}).get('档次', '-')),
            ('月净利估算', _fmt_money(p.get('月净利估算'))),
            ('净利率', f"{(p.get('净利率') or 0):.1%}"),
            ('回本周期', f"{p.get('回本周期(月)')} 个月" if payback else '难以回本'),
            ('盈亏判断', p.get('盈亏判断', '-')),
        ]

    # 三档情景区间：上面的明细是中性档单点，单点会被读成预测。
    # 摊开三档才能回答"你这个净利率怎么算的"——取决于商场扣点和产能假设。
    bands = result.get('profit_bands') or {}
    scenario_rows = []
    if bands.get('区间'):
        for n in ('乐观', '中性', '保守'):
            b = bands.get(n) or {}
            bpb = b.get('回本周期(月)')
            scenario_rows.append((
                n,
                f"净利 {_fmt_money(b.get('月净利估算'))}／净利率 {(b.get('净利率') or 0):.1%}"
                f"／{b.get('人数', '-')} 人"
                f"／回本 {str(bpb) + ' 个月' if bpb else '难以回本'}"))
        sc_txt = ' · '.join(
            f"{n} {bands[n]['假设']['场地附加费率']:.0%}/{bands[n]['假设']['税负率']:.1%}"
            f"/{bands[n]['假设']['损耗率']:.0%}/{bands[n]['假设']['人均日单量']}单"
            for n in ('乐观', '中性', '保守') if bands.get(n))
        scenario_rows.append(('情景假设', f"{sc_txt}（场地附加/税/损耗/人均日单量）"))
        scenario_rows.append(('区间结论', str(bands['区间'].get('结论') or '-')))
        scenario_rows.append(('口径', str(bands['区间'].get('口径') or '-')))

    # 口径区间明细：与三档情景**正交**——三档变的是成本假设（扣点/税/损耗/产能），
    # 这一档变的是需求假设（日单量跟不跟客单价动）。两者可能给出不同方向的结论，
    # 必须并列而不是合并，否则用户会以为是同一个不确定性。
    caliper_rows = []
    if civ:
        for _t in (calipers.get('档位') or []):
            _tpb = _t.get('回本周期(月)')
            caliper_rows.append((
                str(_t.get('口径', '-')),
                f"月流水 {_fmt_money(_t.get('月流水'))}／净利 {_fmt_money(_t.get('月净利'))}"
                f"／{_t.get('日单量参考', '-')} 单/天·{_t.get('人数', '-')} 人"
                f"／回本 {str(_tpb) + ' 个月' if _tpb else '难以回本'}"
                f"（{_t.get('角色', '')}）"))
        caliper_rows.append(('区间结论', str(civ.get('结论') or '-')))
        caliper_rows.append(('口径声明', str(civ.get('口径') or '-')))

    utility_rows = []
    if u:
        utility_rows = [
            ('商业电价', f"{u.get('电价(元/度)')} 元/度"),
            ('商业水价', f"{u.get('水价(元/吨)')} 元/吨"),
            ('月用电', f"{u.get('月用电(kWh)')} kWh（¥{u.get('电费(元/月)', 0):,.0f}）"),
            ('月用水', f"{u.get('月用水(吨)')} 吨（¥{u.get('水费(元/月)', 0):,.0f}）"),
            ('月水电合计', f"¥{u.get('水电合计(元/月)', 0):,.0f}"),
        ]

    evidence_rows = []
    if e:
        evidence_rows = [
            ('周边竞品', f"{e.get('竞品数', 0)} 家（捕获份额 {round(e.get('捕获份额P', 0) * 100, 1) if e.get('捕获份额P') is not None else '-'}%）"),
            ('客群引力累计', _fmt_num(e.get('客群引力累计', '-'))),
            ('最近通勤点', f"{_fmt_num(e.get('最近通勤点(m)', '-'))}m，500m 内 {e.get('500m内通勤点数', 0)} 个"),
            ('预估月流水', f"¥{e.get('预估月流水', 0):,.0f}，租金占 {e.get('租金占流水比', '-')}"),
        ]
        _pc = result.get('客单价校正') or {}
        if e.get('客单价') is not None:
            _ratio = _pc.get('校正倍数')
            evidence_rows.append((
                '客单价',
                f"¥{e['客单价']:g}（{e.get('客单价来源', '-')}）"
                + (f"；画像 ¥{_pc.get('品类画像客单价')}，相差 {_ratio} 倍" if _ratio else '')))
        if _pc.get('口径'):
            evidence_rows.append(('客单价校正口径', _pc['口径']))

    # 租金临界点（纯本地二分反解，0 次 API）：这是"最多能付"的天花板，不是开价
    if rl:
        if be_rent:
            evidence_rows.append(('盈亏平衡月租',
                                  f"{_fmt_money(be_rent)}（当前 {_fmt_money(rent_now)}，"
                                  f"安全垫 {signed_money(be_rent - rent_now)}）"))
        else:
            evidence_rows.append(('盈亏平衡月租', '不存在——免租也亏损，问题不在租金'))
        if cap_rent:
            _gap = f'，比不亏线再低 {_fmt_money(be_rent - cap_rent)}' if be_rent and cap_rent < be_rent else ''
            evidence_rows.append((f'{PAYBACK_LIMIT_MONTHS} 个月回本月租上限',
                                  f'{_fmt_money(cap_rent)}{_gap}'))
        free_np = rl.get('免租月净利')
        if free_np is not None:
            evidence_rows.append(('免租情形（压力测试）',
                                  f"月净利 {_fmt_money(free_np)}，回本 {rl.get('免租回本周期(月)') or '难回本'} 个月"))
    # 双轴结论：地址评分判定 vs 经营判定，否决触发时必须同时展示，否则用户只看到"不能签"却不知道位置其实好
    if veto.get('触发'):
        evidence_rows.append(('地址评分单独判定', f"{veto.get('位置分结论', '-')}（未计盈利）"))
        evidence_rows.append(('盈利一票否决', str(veto.get('原因') or '-')))

    # 经营评分：结论以它为准，就必须让用户看见它是怎么来的（口径 + 三档分数）
    if biz_missing:
        evidence_rows.append(('经营评分',
                              '本结果生成于旧版本引擎（未含该字段），显示的是"仅地址"口径；'
                              '想知道"这个租金下能不能赚钱"，请对同一地址重新分析一次'))
    elif biz:
        if biz_score is not None:
            _tiers = biz.get('三档') or {}
            _tt = '／'.join(f'{n} {_tiers[n]}' for n in ('乐观', '中性', '保守') if n in _tiers) or '-'
            evidence_rows.append(('经营评分（净利率60%+回本40%）',
                                  f"中性档 {biz_score} 分（三档 {_tt}）；结论：{biz.get('结论') or '-'}"))
            evidence_rows.append(('经营评分口径', str(biz.get('口径') or '-')))
        else:
            evidence_rows.append(('经营评分', f"不出分：{biz.get('不可得原因') or '数据不足'}"))

    # 竞品口碑画像（高德公开字段）
    ci = result.get('competitor_insight') or {}
    if ci:
        rat = ci.get('口碑分') or {}
        cost = ci.get('客单价带') or {}
        chk = ci.get('客单价现实校验') or {}
        if rat:
            evidence_rows.append(('竞品口碑分', f"均 {rat.get('均值', '-')} / 中位 {rat.get('中位', '-')}"
                                            f"（{ci.get('有口碑分样本', 0)} 家有分）"))
        if cost:
            evidence_rows.append(('竞品人均价格带', f"P25 ¥{cost.get('P25', '-')} / 中位 ¥{cost.get('中位', '-')}"
                                              f" / P75 ¥{cost.get('P75', '-')}"))
        evidence_rows.append(('连锁占比 / 集中度', f"{(ci.get('连锁占比') or 0):.0%} ／ HHI {ci.get('品牌集中度HHI', '-')}"))
        if chk:
            evidence_rows.append(('客单价假设校验', f"{chk.get('判断', '-')}（假设 ¥{chk.get('假设客单价', '-')}"
                                             f" vs 真实 ¥{chk.get('真实人均中位', '-')}）"))
        # 取数溯源：让用户知道这份口碑画像是"哪来的、什么时候取的"，
        # 从而自己判断要不要复核（缓存/取数失败都要能看出来）
        if ci.get('数据来源') or ci.get('取证时间'):
            evidence_rows.append(('竞品数据来源',
                                  f"{ci.get('数据来源') or '-'}"
                                  f"（取证 {ci.get('取证时间') or '-'}）"))
        elif ci.get('抓取状态') == 'fetch_failed':
            evidence_rows.append(('竞品数据来源', '⚠️ 本次未取到（不代表周边无竞品）'))

    # 门头照视觉分析
    sf = result.get('storefront') or {}
    if sf:
        evidence_rows.append(('门头形象（照片）', f"{sf.get('形象分', '-')} 分（装修 {sf.get('装修档次', '-')}/5、"
                                            f"门头 {sf.get('门头可见度', '-')}/5、卫生 {sf.get('卫生观感', '-')}/5）"))
        if sf.get('招牌文字'):
            evidence_rows.append(('照片招牌识别', str(sf.get('招牌文字'))))

    # ---------------------------------------------------------------
    # 仿真数据看板（2026-09-20 新增）：小人沿**真实道路折线**走
    #   · 选点走 `scoring.query_pois`（步行路网口径，与 D/P 同一批点）
    #   · 轨迹走 `data.road_path`（高德步行规划折线，冻结在 road_path.db）
    #   · 只做可视化，**不参与 D/P 计算、不改任何结论**
    #   · 取不到轨迹的点**不留假轨迹**，如实置空并计数（红线 1/4）
    # ⚠️ 任何异常都不能拖垮整张工作台 —— 仿真块降级为 {'ok': False, '原因': ...}
    sim = {'ok': False, '原因': '未计算'}
    try:
        _lng, _lat = result.get('lng'), result.get('lat')
        if _lng is not None and _lat is not None:
            _prof = {}
            try:
                _prof = get_profile(result.get('category', ''))
            except Exception:
                _prof = {}
            _radius = _prof.get('radius', 500) or 500
            sim = road_sim.build_sim(
                result.get('category', ''), _lng, _lat, _radius,
                profile=_prof, limit=10,
                geo=road_sim.map_geometry(_lat, _lng, _radius))
    except Exception as _e:                                   # noqa: BLE001
        sim = {'ok': False, '原因': f'仿真块构造失败：{_e!r}'}

    return {
        'kind': 'analysis',
        'shop': result.get('name', ''),
        'category': result.get('category', ''),
        'total': total,
        # 地址评分 = 原「综合评分」，展示层已改名；total 键保持不变以兼容历史 JSON
        'biz': biz_score,
        'verdict': verdict,
        'veto': veto,
        'rent_limits': rl,
        'cards': cards,
        'dims': dims,
        'dim_rows': dim_rows,
        'profit_rows': profit_rows,
        'scenario_rows': scenario_rows,
        'caliper_rows': caliper_rows,
        'utility_rows': utility_rows,
        'evidence_rows': evidence_rows,
        'warnings': result.get('warnings', []),
        'map_b64': map_b64,
        'sim': sim,
    }


def build_analysis_dashboard_with_sim(result: dict, map_b64: str = '') -> dict:
    """build_analysis_dashboard 的包装：顺手把仿真块落一份快照。

    为什么单独抽一层而不是直接改 build_analysis_dashboard：
    后者是纯函数（result, map_b64 → payload），门禁 verify_road_sim 会直接调它做对拍；
    落盘是副作用，留在包装层，纯函数保持可测。
    """
    payload = build_analysis_dashboard(result, map_b64)
    board = None
    try:
        # 自绘大屏场景（2026-09-21 重做）：人流来源 → 沿马路 → 本铺/竞品店铺。
        # ⚠️ 放在**包装层**而不是纯函数里：build_board 会读路径库、必要时联网抓折线，
        #    而 build_analysis_dashboard 是纯函数，门禁 verify_road_sim 会直接调它做对拍
        #    —— 不能让它带上网络副作用。
        _cat = result.get('category', '')
        try:
            _prof = get_profile(_cat)
        except Exception:
            _prof = {}
        _radius = _prof.get('radius', 500) or 500
        if result.get('lng') is not None and result.get('lat') is not None:
            board = road_sim.build_board(
                _cat, result.get('lng'), result.get('lat'), _radius,
                profile=_prof, brand=result.get('brand') or '',
                own_s=result.get('own_brand_S'))
    except Exception as e:                                       # noqa: BLE001
        print('[sim_board] 构造失败：%r' % (e,))
        board = {'ok': False, '原因': '大屏场景构造失败：%r' % (e,)}
    try:
        write_last_sim(payload.get('sim'), result, map_b64, board=board)
    except Exception as e:                                       # noqa: BLE001
        print('[last_sim] wrap error:', e)
    return payload


# ---------------------------------------------------------------
# 专家层：切换入口 + 回执
# ---------------------------------------------------------------
# 设计前提（写在这里免得被"优化"掉）：**专家不是独立会话**。
# 9 位专家读的是同一份 AgentState（category / brand / score_result / rent / area…），
# 切换专家只换"视角"，不换数据。做成独立会话 → score_result 丢失 →
# 谈判的"承受力上限"、竞品的"参照组"、解读的"证据引用"全部失效。
#
# 三个入口共用同一条通道 `##专家:<id>##`（前端已把这条指令加入"静默白名单"，
# 所以切换全程不产生对话气泡）：
#   ① 输入框上方的专家面板（一级：当前专家；二级：展开 9 行）
#   ② 左侧「专家系统」卡片页（3×3，点卡片即切）
#   ③ `/expert <序号|id>`（手动输入，**保留文字回执**——用户打了字就该有回应）
def _set_expert(state: dict, expert_id: str):
    """写入选中的专家并持久化（历史会话也记住选了谁）。"""
    state['expert'] = expert_id
    cl.user_session.set('state', state)
    try:
        _persist_conversation(state)
    except Exception:
        pass


async def _announce_expert(expert_id: str):
    """切换后的回执：说清"我是谁 / 怎么问 / 数据不会丢"。

    只在 `/expert` 手动输入时调用。UI 面板/卡片页走静默通道，
    由前端弹 3 秒浮层代替（见 `process_free_chat_toggle` 的说明）。
    """
    try:
        from experts import registry
        ex = registry.get_expert(expert_id)
    except Exception as e:
        await cl.Message(content=f'⚠️ 切换失败：{e}').send()
        return
    await cl.Message(
        content=(f'已切换到 **{ex.name} · {ex.alias}** —— {ex.one_liner}\n\n'
                 f'可以这样问：*「{ex.start_sentence}」*\n\n'
                 f'（前面的分析结果不会丢：所有专家读的是同一份会话数据，'
                 f'我只换了看问题的角度。）'),
        author='址南针').send()


async def process_set_expert(arg: str, silent: bool = False):
    """`/expert` 空参 → 列出可选；`/expert 4` 或 `/expert rent_negotiator` → 切换。

    `silent=True`（来自 UI 面板 / 卡片页的 `##专家:id##`）时**不回文字消息**，
    让前端浮层去反馈 —— 这是需求「按按钮时对话框不要有任何输出」的一部分。
    """
    try:
        from experts import registry
    except Exception as e:
        if not silent:
            await cl.Message(content=f'⚠️ 专家层不可用：{e}').send()
        return
    arg = (arg or '').strip()
    state = get_state()
    items = registry.list_experts()

    if not arg:
        if silent:      # 静默通道不带参数 = 无意义，直接忽略，不冒泡
            return
        lines = ['**可用专家**（切换：`/expert 序号` 或 `/expert 专家id`）', '']
        for i, e in enumerate(items, 1):
            mark = '　←当前' if e.id == state.get('expert') else ''
            lines.append(f'`{i}` **{e.name} · {e.alias}** `{e.id}` — '
                         f'{e.one_liner}{mark}')
        lines.append('')
        lines.append('不选专家时走默认顾问（按第一句话自动判断）。')
        await cl.Message(content='\n'.join(lines)).send()
        return

    ex = None
    if arg.isdigit() and 1 <= int(arg) <= len(items):
        ex = items[int(arg) - 1]
    else:
        # 两种顺序都认：2026-09-18 起展示口径改为「定位 · 拟人名」，
        # 但用户仍可能照旧写法输入「沈砚舟·选址评估师」，不能因此切不过去。
        ex = next((e for e in items
                   if arg in (e.id, e.name, e.alias,
                              f'{e.name}·{e.alias}', f'{e.alias}·{e.name}',
                              f'{e.name} · {e.alias}', f'{e.alias} · {e.name}')), None)
    if ex is None:
        if silent:
            return
        await cl.Message(content=f'没找到专家「{arg}」。输入 `/expert` 看全部可选。').send()
        return

    _set_expert(state, ex.id)
    if not silent:
        await _announce_expert(ex.id)
    await refresh_sidebar()


# ---------------------------------------------------------------
# 欢迎消息
# ---------------------------------------------------------------
# ⚠️ 首屏**刻意只留一条消息**。历史教训：首页曾同时铺 6 条 bullet + 5 条示例
# + 一整块「想找谁聊？」九宫格，近 40 行、三处在讲同一件事（门头照 ↔ 门头审核员、
# 砍价 ↔ 租金谈判教练 完全重复）。现在改成"3 句总览"，具体能力由点击展示：
#   · 输入框上方「专家」面板（随时展开，9 行，点行即切）
#   · 左侧「专家系统」卡片页（3×3 卡片，含人名与详细解释）


# ---------------------------------------------------------------
# 公网访问闸门（演示模式开关 / 每 IP 限流 / 全局日预算）
# ---------------------------------------------------------------
# ⚠️ 为什么要这个：`start_agent.bat` 里是 `--host 0.0.0.0`，一旦做内网穿透或云部署，
# 任何拿到链接的人都能触发服务端的付费调用（LLM + 高德），而服务本身没有登录也没有限流。
# 纯逻辑在 `ui/access_gate.py`（有独立离线回归），这里只负责"挂到 Chainlit 的入口上"。
# 默认 **对本地零影响**：内网来源一律豁免；公网默认拒绝，只有作者开 DEMO_MODE=1 才开放。
def _current_ip() -> str:
    """取当前连接的客户端 IP；拿不到就退回 session id（至少能防单会话狂刷）。"""
    try:
        from chainlit.context import context
        env = getattr(context.session, 'environ', None) or {}
    except Exception:
        env = {}
    try:
        sid = cl.user_session.get('id') or ''
    except Exception:
        sid = ''
    return client_ip(env, fallback=sid)


def _gate_on() -> bool:
    """该来源是否需要过闸门（内网来源 + GATE_SKIP_LOCAL 默认豁免）。"""
    cfg = gate_config()
    if cfg['skip_local'] and is_private(_current_ip()):
        return False
    return True


async def _ensure_access() -> bool:
    """入口闸（on_chat_start）：内网直接放行；公网必须开启演示模式（DEMO_MODE=1）。

    未开演示模式 → 直接结束会话（欢迎语都不发，避免"能看不能用"的困惑）。
    """
    if not _gate_on():
        return True
    reason = demo_reject(_current_ip(), gate_config())
    if reason:
        await cl.Message(content=reason).send()
        return False
    return True


async def _gate_guard(text: str) -> bool:
    """on_message 入口。返回 False = 已回话、**不进业务、0 次付费 API**。

    顺序：演示模式开关（公网默认拒）→ 控制指令豁免 → 限流/预算记账。
    """
    cfg = gate_config()
    if not _gate_on():
        return True
    # 第 0 道：演示模式未开 → 公网一律拒绝（直接挡，不计数）
    reason = demo_reject(_current_ip(), cfg)
    if reason:
        await cl.Message(content=reason).send()
        return False
    # 控制指令（##新对话## / /expert 等）纯本地，不计额度
    if (text or '').strip().startswith(('##', '/')):
        return True
    # 排障用：穿透后必须确认拿到的是不是**真实访客 IP**。若穿透服务不传
    # X-Forwarded-For，所有访客会被算成同一个 IP → 每 IP 限流会误伤全部评委。
    # 开 `GATE_DEBUG=1`，用手机流量（关 WiFi）访问一次，看控制台打印值。
    if os.getenv('GATE_DEBUG'):
        print('[gate] ip=', _current_ip())
    # 第 1、2 道：每 IP 限流 + 全局日预算
    ok, reason = gate_ledger().hit(_current_ip(), cfg)
    if not ok:
        await cl.Message(content=reason).send()
        return False
    return True


@cl.on_chat_start
async def on_chat_start():
    # 公网闸门：演示模式未开就直接结束（欢迎语都不发，避免"能看不能用"的困惑）
    if not await _ensure_access():
        return
    # 恢复上次选择的模型（会话级 + 持久化），供本次会话的 LLM 调用
    mdl = _load_model()
    cl.user_session.set('llm_model', mdl)
    set_llm_model(mdl)

    welcome = """# 早上好，BOSS

##### ——您的AI商铺选址分析师

我能覆盖开店全流程的 **9 个环节**——从选品类、找铺子、谈租金、办证照，到开业后复盘盈亏。

**直接说你的情况就行**，我会按第一句话判断该找谁；也可以点**输入框上方**的「专家」指定一位，
或在左栏「专家系统」里看完整名单。

选址知识（Huff 模型、蹲点方法、加盟避坑、租约条款等）我内置了知识库，问到就会引用。
每次执行过程的**内部思考与工具调用记录**会实时展开显示在对话中，全程可见。"""

    # 全新会话：不残留上一会话的工作台（刷新/恢复会话已有 conv_id，不清空）
    if not cl.user_session.get('conv_id'):
        clear_dashboard()
    await cl.Message(content=welcome).send()
    await refresh_sidebar()


# ---------------------------------------------------------------
# 快捷指令 / 左侧操作栏命令（前端 custom_js 按钮发送的控制指令）
# ---------------------------------------------------------------
async def process_new_chat():
    """新建对话：原会话已自动保存，重置为全新会话并重发欢迎。"""
    fresh = {'messages': [], 'phase': 'intro', 'candidates': [], 'missing_info': [],
             'investment': None, 'staff': None, 'comparison': None, 'compare_pending': False}
    cl.user_session.set('state', fresh)
    cl.user_session.set('conv_id', new_conversation('新会话'))
    clear_dashboard()  # 右侧工作台清空
    await cl.Message(content='**已新建对话**，原会话已自动保存到左侧「历史会话」，随时可以打开继续。').send()
    await refresh_sidebar()


# ---------------------------------------------------------------
# §2 历史会话：一步到位 + 回放（2026-09-17）
# ---------------------------------------------------------------
REPORT_DIR = ROOT / 'data' / 'reports'
# 回放的**纯逻辑**（REPLAY_TAIL / 批次边界 / 可回放筛选）住在 `agent/replay.py`：
# 这里跑的是 3.12 + Chainlit，而离线回归在 3.14 —— 放进本文件就永远测不到那段算术。
from agent.replay import (REPLAY_TAIL, replayable as _replayable,
                          replay_slice as _replay_slice,
                          next_shown as _next_shown)   # noqa: E402


async def _replay_emit(m: dict):
    """把一条历史记录作为**真消息**重发到聊天区。

    ⚠️ 三个必须知情的点（都验证过，不是想当然）：
    1. **Chainlit 2.11 没有 `cl.UserMessage` 类**（`hasattr(cl,'UserMessage')` 为
       False、`chainlit.utils` 的注册表里没有这个名字）。用户气泡的正路是
       `cl.Message(content=..., type='user_message')` —— type 接受
       `'user_message' | 'assistant_message' | 'system_message'`。
       这是方案 A（后端重发）在本版本上的**唯一**可行实现。
    2. **只渲染、不进 graph**：所以不会触碰 `state['messages']`。
       若走图/写状态，同一次打开重放一次就翻倍累积，历史会越开越长。
    3. 用 `author='AI'` 标助手侧，与实时的助手气泡一致。
    """
    if m['role'] == 'user':
        await cl.Message(content=m['content'], type='user_message').send()
    else:
        await cl.Message(content=m['content'], author='AI').send()


def _conv_msgs(conv: dict) -> list:
    """取该会话可回放的消息（纯逻辑在 agent/replay.py::replayable）。"""
    return _replayable((conv.get('state') or {}).get('messages'))


async def _replay_batch(conv: dict, msgs: list, start: int, end: int,
                        first: bool, total: int):
    """回放 msgs[start:end]，并在前面加一条批次说明。
    说明是必需的：Chainlit 只能**追加**消息，无法把更早的记录插到上方，
    所以"更早"这一批在视觉上排在下方。不写清楚用户会读成顺序错乱。

    `start/end` 由 `agent/replay.py::replay_slice` 算出（那段算术有独立回归，
    保证多轮拼接"不重不漏"），这里只管渲染。"""
    conv_id = conv['id']
    n = end - start
    _title = conv.get('title', '会话')[:16]
    _ts = conv.get('updated') or conv.get('ts', '')
    if first:
        head = (f'── 已切换到历史会话「{_title}」（{_ts}）──\n'
                f'以下回放**最近 {n} 条**记录；此后的对话将记录在该会话中。')
    else:
        head = f'── 更早的记录（第 {n} 条，时间上**早于**上方内容）──'
    await cl.Message(content=head).send()
    for m in msgs[start:end]:
        await _replay_emit(m)
    remain = start
    if remain > 0:
        # 按钮上的 `shown` 只是点击那一刻的快照；真正的进度以 user_session 为准
        # （见 on_load_earlier 的注释），这里带上是为了连点时的自洽。
        await cl.Message(
            content=f'（该会话共 {total} 条，上方已显示 {total - remain} 条，'
                    f'还有更早的 {remain} 条未显示）',
            actions=[cl.Action(
                name='load_earlier',
                payload={'conv_id': conv_id, 'shown': total - remain},
                label=f'查看更早的 {min(remain, REPLAY_TAIL)} 条',
                description='补发更早的记录（会追加在下方，并标注时间关系）')],
        ).send()
    else:
        await cl.Message(content=f'（已显示该会话全部 {total} 条记录）').send()


async def process_open_conv(conv_id: str):
    """打开历史会话：**一步到位**切状态 + 回放聊天内容（不再有只读中间页）。

    改造要点（§2）：
    · 去中间页：前端 `openHistory` 现在直接发 `##打开:<id>##`，本函数即唯一入口；
      原先的「独立只读页」（`process_preview_conv` / `public/conv_page.json`）已退休。
    · 回放：把最近 `REPLAY_TAIL` 条作为**真消息**重发（见 `_replay_emit` 的三条说明）；
      更早的走消息上的「查看更早」按钮（`load_earlier` action）。
    · 右侧工作台重渲 + PDF 复用落盘（`data/reports/<conv_id>.pdf`），
      不再每次打开都重跑 Playwright。
    """
    conv = get_conversation(conv_id)
    if not conv:
        await cl.Message(content='⚠️ 该会话不存在或已被清理。').send()
        return
    state = conv.get('state') or {'messages': [], 'phase': 'intro', 'candidates': []}
    cl.user_session.set('state', state)
    cl.user_session.set('conv_id', conv_id)
    set_llm_model(cl.user_session.get('llm_model') or DEFAULT_MODEL)

    # 有分析结果则重渲右侧工作台（指标卡片/雷达图/热力图）+ 复用落盘 PDF
    sr = state.get('score_result')
    if sr:
        interp = ''
        for m in reversed(state.get('messages', [])):
            if m.get('role') == 'assistant' and m.get('content'):
                interp = m['content']
                break
        await render_analysis_dashboard(sr, interpretation=interp, conv_id=conv_id)

    msgs = _conv_msgs(conv)
    total = len(msgs)
    if total:
        start, end = _replay_slice(total, 0)          # 第一次打开：显示最近 N 条
        cl.user_session.set('replay', {'conv_id': conv_id,
                                       'shown': _next_shown(total, 0, start, end)})
        await _replay_batch(conv, msgs, start, end, first=True, total=total)
    else:
        await cl.Message(content=f'✅ 已切换到历史会话「{conv.get("title", "")}」'
                                 f'（{conv.get("updated") or conv.get("ts", "")}）。'
                                 f'该会话没有对话记录，此后的对话将记录在这里。').send()
    await refresh_sidebar()


@cl.action_callback('load_earlier')
async def on_load_earlier(action):
    """「查看更早」：按批次往前补发历史记录。

    `shown` 以 **user_session 里记的进度**为准、而不是 payload 里的数字 ——
    用户可能连点两次，按钮上的 payload 是点击那一刻的快照，照它走会重复补发。
    同一会话换过（`rp['conv_id'] != conv_id`）时进度作废，从"最尾部"重新起算。
    """
    payload = action.payload or {}
    conv_id = payload.get('conv_id') or cl.user_session.get('conv_id')
    conv = get_conversation(conv_id) if conv_id else None
    if not conv:
        await cl.Message(content='⚠️ 该会话不存在或已被清理。').send()
        return
    msgs = _conv_msgs(conv)
    total = len(msgs)
    rp = cl.user_session.get('replay') or {}
    shown = min(total, REPLAY_TAIL) if rp.get('conv_id') != conv_id \
        else (rp.get('shown') or 0)
    start, end = _replay_slice(total, shown)
    if start >= end:
        await cl.Message(content='（没有更早的记录可显示了）').send()
        return
    cl.user_session.set('replay', {'conv_id': conv_id,
                                   'shown': _next_shown(total, shown, start, end)})
    await _replay_batch(conv, msgs, start, end, first=False, total=total)


async def process_delete_conv(conv_id: str):
    """删除一个历史会话（可单独选择删除）。"""
    from agent.conversation_store import delete_conversation
    ok = delete_conversation(conv_id)
    if not ok:
        await cl.Message(content='⚠️ 该会话不存在或已被删除。').send()
        return
    # 若删的是当前会话，重置到全新会话
    if cl.user_session.get('conv_id') == conv_id:
        fresh = {'messages': [], 'phase': 'intro', 'candidates': [], 'missing_info': [],
                 'investment': None, 'staff': None, 'comparison': None, 'compare_pending': False}
        cl.user_session.set('state', fresh)
        cl.user_session.set('conv_id', new_conversation('新会话'))
    await cl.Message(content='**已删除**该历史会话。').send()
    await refresh_sidebar()


# ---------------------------------------------------------------
# 消息处理
# ---------------------------------------------------------------
def _read_element_bytes(el) -> bytes:
    """读取 Chainlit 图片元素字节（优先 content, 回落本地 path）"""
    try:
        content = getattr(el, 'content', None)
        if content:
            return content
        p = getattr(el, 'path', None)
        if p and Path(p).exists():
            return Path(p).read_bytes()
    except Exception:
        pass
    return b''


# ---------------------------------------------------------------
# 非图片附件：抽取正文（2026-09-16 新增）
# ---------------------------------------------------------------
# 为什么必须补这一段：`.chainlit/config.toml` 的 accept 白名单是
# `["image/*", "application/pdf"]` —— 用户**能选中并上传 PDF**，但 on_message
# 过去只挑 `cl.Image`，PDF 落进 `process_message(message.content)` 后**附件内容
# 根本没被读**，用户也收不到任何提示：消息发出去像被无视了。
# 这是"静默失败"，比报错更糟，所以要么真读，要么明说读不了。
#
# 读得到字节这件事有依据：Chainlit 把上传文件转元素时给的是**本地磁盘路径**
# （chainlit/emitter.py: `{"path": str(file["path"]), "type": infer_type_from_mime(mime)}`），
# `_read_element_bytes` 的 path 回落分支正好接住 —— 图片那条路就是靠它工作的。
ATTACH_MAX_CHARS = 12000     # 注入 prompt 的正文上限（超出截断，并如实声明）
ATTACH_PREVIEW = 360         # 回执里展示的预览字数
PREVIEW_LINE_MAX = 30        # 预览里"短行"的宽度上限（超过视为整句，单独成行）
ATTACH_KEEP = 3              # 会话内保留的最近附件数（更多的丢掉，防 prompt 无限膨胀）
PDF_MAX_PAGES = 40           # 只抽前 N 页：config 允许单文件 500MB，不设闸会把内存吃光


def _norm_attach_text(t: str) -> str:
    """压缩空白。PDF/Word 抽取结果常带零散空格与全角空格，直接注入会浪费大量 token。

    ⚠️ 这里**不做"合并短行"**。上一版按"两个连续短行拼一行"合并，遇到
    「标签 / 数值 / 单位」三行一组的版式（《店铺经营月报》正是这种）会**错位**：
    `元` 被和下一个标签粘成一行（`元 月租金`），本来对齐的字段全打乱。
    碎行的根子在**抽取层**，已在 `_pdf_page_text` 里按坐标重建视觉行根治，
    归一化只负责压空白这一件事。
    """
    t = re.sub(r'[ \t\u00a0\u3000]+', ' ', t or '')
    t = re.sub(r'\n\s*\n\s*\n+', '\n\n', t)
    return t.strip()


def _pdf_page_text(pg) -> str:
    """把一页 PDF 重建成"视觉行"（标签与数值回到同一行）。

    ⚠️ 为什么不用 `pg.get_text('text')`：它会把**同一视觉行上、横向间隔较大的
    几段**拆成多行。实测《店铺经营月报》：`月流水` / `120000` / `元` 三个词的
    y 坐标**完全相同**（233.3），却被拆成三行 —— 展示上就是"几个字换一行"，
    读起来一片空隙。这不是排版碎，是抽取把一行读成了三行。
    做法：取 word 级坐标 → 按垂直重叠聚成行 → 行内按 x 排序拼回去。
    `get_text('text')` 里凡是真在同一行的，这里都还原；行间距足够大仍分行。

    局限（如实说明）：分栏排版（学术论文双栏）同高度处左右栏会被并到一行。
    本项目面向商业文档（经营月报 / 合同 / 方案 / 清单），几乎不会遇到；
    真遇到只是多几个空格，字段抽取不受影响（正则按"标签…数值"邻接匹配）。
    """
    words = pg.get_text('words') or []
    if not words:
        return pg.get_text('text') or ''      # 无文本层（扫描件）时原样回落
    rows = []
    for w in sorted(words, key=lambda w: ((w[1] + w[3]) / 2.0, w[0])):
        y0, y1 = w[1], w[3]
        target = None
        for r in rows:                        # 与已有行垂直重叠 → 同一行
            ov = min(y1, r['y1']) - max(y0, r['y0'])
            if ov > 0 and ov >= 0.5 * min(y1 - y0, r['y1'] - r['y0']):
                target = r
                break
        if target is None:
            rows.append({'y0': y0, 'y1': y1, 'ws': [w]})
        else:
            target['ws'].append(w)
            target['y0'] = min(target['y0'], y0)
            target['y1'] = max(target['y1'], y1)
    rows.sort(key=lambda r: r['y0'])
    out = []
    for r in rows:
        buf, prev_x1 = [], None
        for w in sorted(r['ws'], key=lambda w: w[0]):
            if prev_x1 is not None and w[0] - prev_x1 > 1.5:
                buf.append(' ')               # 词间留一个空格；贴合字符不加
            buf.append(w[4])
            prev_x1 = w[2]
        line = ''.join(buf).strip()
        if line:
            out.append(line)
    return '\n'.join(out)


def _extract_pdf(data: bytes):
    """返回 (text, meta, err)。meta 带 pages_total / pages_read。

    ⚠️ 依赖装在**服务端解释器**上（本机是 C:\\Python312），不是 `.pylibs`：
    `.pylibs` 里的轮子是 cp314 构建，3.12 根本 import 不了 —— 这一条踩过，
    表现为"功能写了但一跑就说缺库"。装法：
        C:\\Python312\\python.exe -m pip install pymupdf
    （PyMuPDF ≥1.24 起 `fitz` 别名已标记废弃，推荐 `import pymupdf`，
      所以这里两个名字都试，兼容新旧版本。）
    """
    try:
        import pymupdf as fitz            # 新名（1.24+ 推荐）
    except Exception:
        try:
            import fitz                   # 旧名兜底
        except Exception as e:
            return '', {}, f'缺少 PDF 解析库（PyMuPDF）：{e}'
    try:
        doc = fitz.open(stream=data, filetype='pdf')
    except Exception as e:
        return '', {}, f'PDF 打开失败（文件可能损坏或被加密）：{e}'
    try:
        total = doc.page_count
        n = min(total, PDF_MAX_PAGES)
        parts = []
        for i in range(n):
            try:
                parts.append(_pdf_page_text(doc.load_page(i)))
            except Exception:
                parts.append('')
        return '\n'.join(parts), {'pages_total': total, 'pages_read': n}, ''
    finally:
        try:
            doc.close()
        except Exception:
            pass


def _extract_docx(data: bytes):
    try:
        from docx import Document
        d = Document(io.BytesIO(data))
        parts = [p.text for p in d.paragraphs]
        for tb in d.tables:                # 表格里的原文也要，合同/清单常靠表格装内容
            for row in tb.rows:
                parts.append(' | '.join(c.text for c in row.cells))
        return '\n'.join(parts), {}, ''
    except Exception as e:
        return '', {}, f'Word 解析失败：{e}'


def _extract_attachment(el):
    """按 mime 分流抽取。返回 (kind, name, text, meta, err)。"""
    name = getattr(el, 'name', '') or '附件'
    mime = str(getattr(el, 'mime', '') or '')
    data = _read_element_bytes(el)
    if not data:
        return 'unknown', name, '', {}, '读不到文件内容（附件可能已过期，请重新上传）'

    if mime == 'application/pdf' or isinstance(el, cl.Pdf):
        t, meta, err = _extract_pdf(data)
        return 'pdf', name, _norm_attach_text(t), meta, err

    if mime.startswith('text/') or isinstance(el, cl.Text):
        for enc in ('utf-8', 'utf-8-sig', 'gb18030'):
            try:
                return 'text', name, _norm_attach_text(data.decode(enc)), {}, ''
            except UnicodeDecodeError:
                continue
        return 'text', name, '', {}, '文本编码无法识别（既不是 UTF-8 也不是 GB18030）'

    if (mime.endswith('wordprocessingml.document')
            or name.lower().endswith('.docx')):
        t, meta, err = _extract_docx(data)
        return 'docx', name, _norm_attach_text(t), meta, err

    return 'unsupported', name, '', {}, f'暂不支持读取该类型（{mime or "未知类型"}）'


def _attach_brief(atts) -> list:
    """给持久化用：剥掉正文，只留元信息 + 短预览（避免 conversations.json 被撑大）。"""
    out = []
    for a in atts or []:
        b = dict(a)
        if b.get('text'):
            b['text'] = b['text'][:160]
            b['text_truncated'] = True
        out.append(b)
    return out


def _compact_preview(text: str, limit: int) -> str:
    """把预览压成"少换行"的紧凑块（治"几个字一行、满屏空白"）。

    ⚠️ 为什么非压不可：Chainlit 2.11.1 的 markdown 渲染**给 `p` 挂了
    `whitespace-pre-wrap`**（前端 bundle 原文：
    `p(s){...className:"leading-7 [&:not(:first-child)]:mt-4 whitespace-pre-wrap break-words"...}`）,
    于是每一个换行都是**真实换行**，每段还额外吃 16px 上边距。一份"一个词一行"
    的 PDF 直接铺进去，就是"几个字一行 + 一堆空隙"。这属于渲染层的既定行为，
    改不了它，只能让送进去的文本自己紧凑。

    做法：连续的短行（≤ PREVIEW_LINE_MAX 字）用 ` ｜ ` 连成一行 —— 浏览器
    自然折行铺满宽度，不再产生人为空隙；长行（整句/段落）保持独立成行，
    不破坏原文结构。空行当段落分隔。
    """
    out, buf = [], []

    def flush():
        if buf:
            out.append(' ｜ '.join(buf))
            buf.clear()

    for raw in (text or '').split('\n'):
        line = raw.strip()
        if not line:
            flush()                      # 空行 = 段落边界，收束缓冲
            continue
        if len(line) <= PREVIEW_LINE_MAX:
            buf.append(line)
        else:
            flush()
            out.append(line)
    flush()
    s = '\n'.join(out)
    return s[:limit] + ('…' if len(s) > limit else '')


async def process_attachment(el, caption: str = ''):
    """非图片附件：抽取正文 → 回执 → 挂到会话，供后续问答引用。"""
    state = get_state()
    kind, name, text, meta, err = _extract_attachment(el)

    lines = [f'📄 **已收到附件**：{name}']
    ok = False
    if err:
        lines.append(f'⚠️ {err}')
        # 关键：不把它当"已读取"。否则后续回答会凭空引用一份没读到的文件。
        lines.append('（未把这份文件登记为已读内容，避免模型凭空引用它。）')
    elif not text:
        lines.append('⚠️ 抽取到的正文为**空** —— 这份 PDF 很可能是**扫描件/图片型 PDF**，'
                     '没有文本层。要读它得走 OCR，本系统目前不做 OCR，'
                     '所以不会假装已经读到了内容。')
    else:
        ok = True
        pages = meta.get('pages_total')
        if pages:
            head = f'已抽取 **{meta.get("pages_read")}/{pages}** 页、共 **{len(text)}** 字'
        else:
            head = f'已抽取正文 **{len(text)}** 字'
        if len(text) > ATTACH_MAX_CHARS:
            head += f'（超出单次引用上限，本次只带前 {ATTACH_MAX_CHARS} 字，其余不注入）'
        lines.append(head)
        lines.append('')
        lines.append('正文开头预览：')
        lines.append('> ' + _compact_preview(text, ATTACH_PREVIEW).replace('\n', '\n> '))
        lines.append('')
        lines.append('已挂到本次会话 —— 你可以**直接就它的内容提问**，'
                     '后续回答会引用这份正文（不会编造里面没有的内容）。')

        atts = state.setdefault('attachments', [])
        atts.insert(0, {
            'name': name, 'kind': kind, 'chars': len(text),
            'pages': meta.get('pages_total'),
            'text': text[:ATTACH_MAX_CHARS],
        })
        del atts[ATTACH_KEEP:]

    state.setdefault('messages', []).append(
        {'role': 'user', 'content': caption or f'（上传了附件：{name}）'})
    state.setdefault('messages', []).append(
        {'role': 'assistant', 'content': '\n'.join(lines)})
    cl.user_session.set('state', state)
    _persist_conversation(state)
    await cl.Message(content='\n'.join(lines)).send()

    # 附件是"材料"不是"问题"：带了问题就继续走正常流程回答它
    if ok and caption:
        await process_message(caption)
    elif ok:
        await refresh_sidebar()


async def process_storefront_image(el, caption: str = '', mode: str = 'site'):
    """AI 方向③：门头照 VLM 分析。
    分工: 豆包视觉模型只输出"看得见的证据"(招牌/装修/门头/卫生),
          引擎按 10% 权重把形象分并入总分; 经营测算(流水/成本/回本)不受照片影响。

    `mode`：
      - 'site'（默认）：选址语境。识别到品牌会回写会话品牌、有评分则并入评分。
      - 'chat'：自由对话语境。**只解读照片**，不改任何会话状态、不并入选址评分。
        起因：过去无论开没开自由对话，传图都会被拉进"门头照 → 选址报告"的流程，
        在闲聊语境里返回一份评分报告很违和。"""
    chat_mode = (mode == 'chat')
    state = get_state()
    set_llm_model(cl.user_session.get('llm_model') or DEFAULT_MODEL)

    data = _read_element_bytes(el)
    if not data:
        await cl.Message(content='⚠️ 图片读取失败，请重新上传（支持 jpg/png）。').send()
        return

    mime = getattr(el, 'mime', '') or 'image/jpeg'
    result = state.get('score_result') or {}
    ctx_bits = []
    if state.get('category'):
        ctx_bits.append(f"计划品类：{state['category']}")
    if state.get('brand'):
        ctx_bits.append(f"品牌：{state['brand']}")
    if result.get('name'):
        ctx_bits.append(f"商铺：{result['name']}")
    if caption:
        ctx_bits.append(f"用户备注：{caption}")
    context = '；'.join(ctx_bits)

    step = cl.Step(name='门头照分析（豆包视觉模型）', type='tool', icon='camera')
    await step.send()

    from agent.vision import (analyze_storefront, render_storefront_report,
                              VLM_PER_MODEL_TIMEOUT, VLM_TOTAL_BUDGET)
    # ⚠️ 总超时包裹（2026-09-15 补齐）：analyze_storefront 内部按
    #    (主模型, 备模型) 顺序各试一次，单次默认 90s → 最坏 2×90 = 180s，
    #    期间界面只有转圈、零反馈，用户会以为程序挂了。
    #    自动看铺路径早有 75s 的 wait_for 包裹（见 agent_graph.py 门头照自动分析），
    #    而用户手动上传这条路一直漏着，两条路径行为不一致。此处统一引用
    #    vision.VLM_* 常量，行为与自动看铺对齐。
    #    超时按降级处理：只这一张照片失败，不影响已有评分与选址结论。
    try:
        vlm = await asyncio.wait_for(
            asyncio.to_thread(analyze_storefront, data, mime, context,
                              VLM_PER_MODEL_TIMEOUT),
            timeout=VLM_TOTAL_BUDGET)
    except asyncio.TimeoutError:
        step.output = f'超时（>{VLM_TOTAL_BUDGET}s）'
        await step.update()
        await cl.Message(content=(f'⚠️ 门头照分析超时（超过 {VLM_TOTAL_BUDGET}s）。'
                                  '视觉模型此刻响应较慢，可稍后重传；'
                                  '照片只影响"形象分"这一项，不影响选址结论，'
                                  '不传也可以继续。')).send()
        return
    except Exception as e:
        step.output = f'失败：{e}'
        await step.update()
        await cl.Message(content=f'⚠️ 门头照分析失败：{e}\n'
                                 '（提示：图片最小边需 ≥14px，建议上传清晰的门头正面照）').send()
        return

    step.output = (f"招牌：{vlm.get('招牌文字') or '未识别'}；"
                   f"装修 {vlm['装修档次']}/5；门头可见度 {vlm['门头可见度']}/5；"
                   f"卫生 {vlm['卫生观感']}/5")
    await step.update()

    reply = [render_storefront_report(vlm)]
    if chat_mode:
        reply.append('\n（自由对话模式：以上仅为**照片解读**，'
                     '不并入选址评分，也不改写会话里的品类/品牌/评分。）')

    # ---- §6：storefront_auditor 的人设第一次真正进场 ----
    # 改造前门头照两条路径都是「VLM + 模板渲染」，一次 LLM 都不调 →
    # 这位专家的人设不生效（"选了也没区别"）。这里把 **VLM 的结构化结果**
    # 交给它自己的 persona 解读：分数仍来自 VLM（prompt 禁止改数字），
    # LLM 只负责按"门头审核员"的口吻给判断与**照片层面的**改进建议。
    # 失败/超时一律不追加 —— 模板报告照常给出（严格增量）。
    try:
        from agent.agent_graph import _expert_commentary
        _sf_note = await asyncio.wait_for(
            _expert_commentary('storefront_auditor', (
                '以下是视觉模型对用户上传照片的结构化识别结果'
                '（数字来自视觉模型，逐字引用，**禁止改动、禁止新增任何数字**；'
                '字段缺失就说"这次没看出来"，不要补）：\n'
                f'{json.dumps({k: v for k, v in vlm.items() if v not in (None, "", [], {})}, ensure_ascii=False, default=str)}\n\n'
                f'背景：{context or "未提供"}\n\n'
                '请按你的角色输出：是否为门头实景 → 招牌文字/识别品牌 → '
                '装修档次·门头可见度·卫生观感三项 1-5 分 → 形象分及其对总分的影响'
                '（固定 10% 权重）→ 照片层面的改进建议 → 【只反映拍摄时刻】声明。')),
            timeout=60)
        if _sf_note:
            reply.append('\n' + _sf_note)
    except Exception:
        pass

    # 照片识别到连锁品牌且用户尚未指定 → 回写会话品牌（后续分析计入品牌引力 S）
    # 自由对话模式下**不做**这个回写：闲聊时随手拍一张别家的门头，
    # 不该把人家品牌写进你的选址会话。
    if not chat_mode and vlm.get('识别品牌') and not state.get('brand'):
        try:
            from engine.brands import BRAND_S
            b = vlm['识别品牌']
            if b in BRAND_S:
                state['brand'] = b
                reply.append(f'\n🏷️ 照片识别到连锁品牌 **{b}**（品牌引力 S={BRAND_S[b]}），已记入本次会话。'
                             '若你确实打算加盟该品牌，说一声"按这个品牌重新分析"，'
                             '我会把品牌力计入 Huff 捕获份额，投入测算也改用该品牌的加盟政策口径。')
        except Exception:
            pass

    # 已有评分结果 → 把照片证据并入"门头形象"维度并重算总分
    # 自由对话模式下不并入：否则用户闲聊时传张图就会**悄悄改掉已有评分**。
    if result and not chat_mode:
        try:
            from engine.scoring import apply_storefront
            before = result.get('total')
            result = apply_storefront(result, vlm)
            state['score_result'] = result
            sf = result.get('storefront') or {}
            if sf:
                reply.append(f'\n📊 **照片证据已并入评分**：新增维度「门头形象(照片)」= '
                             f'{sf.get("形象分")} 分（权重 10%），'
                             f'总分 {before} → **{result.get("total")}**（{result.get("verdict")}）。'
                             '经营测算（流水/成本/回本）未受照片影响。')
                new_warns = [w for w in (result.get('warnings') or [])
                             if '门头形象' in w or '照片' in w]
                for w in new_warns:
                    reply.append(w)
        except Exception as e:
            reply.append(f'\n（照片已分析，但并入评分失败：{e}）')

    state.setdefault('messages', []).append(
        {'role': 'assistant', 'content': '\n'.join(reply)})
    cl.user_session.set('state', state)
    _persist_conversation(state)

    await cl.Message(content='\n'.join(reply)).send()

    # 刷新右侧工作台（雷达图/得分表会多出一个维度）；不重复推送 PDF
    if result and result.get('storefront'):
        try:
            map_b64 = ''
            if result.get('lng') is not None and result.get('lat') is not None:
                png = await asyncio.to_thread(_build_shop_map_png, result)
                if png:
                    map_b64 = 'data:image/png;base64,' + base64.b64encode(png).decode('ascii')
            write_dashboard(build_analysis_dashboard_with_sim(result, map_b64))
        except Exception as e:
            print('[storefront-dash] error:', e)

    await refresh_sidebar()


@cl.on_message
async def on_message(message: cl.Message):
    """附件分流：图片 → 门头照 VLM；PDF/文本/Word → 抽取正文；都没有 → 普通消息。

    ⚠️ 过去这里只挑 `cl.Image`，**非图片附件被静默丢弃**（config 白名单里
    却明确允许 application/pdf）。分流后每一条路径都有明确回执，不再有"发了像没发"。
    """
    caption = (message.content or '').strip()
    # 公网闸门：演示模式未开 / 限流超限 → 已回话，直接返回（**0 次付费 API**）
    if not await _gate_guard(caption):
        return
    try:
        els = list(message.elements or [])
    except Exception:
        els = []
    images = [el for el in els
              if isinstance(el, cl.Image)
              or str(getattr(el, 'mime', '')).startswith('image/')]
    docs = [el for el in els if el not in images]

    if images:
        if len(images) > 1:
            # 视觉分析按张计费、也更容易看混，一次只分析第一张 —— 但要**说出来**，
            # 不能让用户以为 5 张都看了（沉默丢弃正是这次要消灭的行为）。
            _rest = '、'.join((getattr(e, 'name', '') or '未命名') for e in images[1:4])
            await cl.Message(content=(
                f'⚠️ 一次收到 **{len(images)}** 张图，本次**只分析第 1 张**'
                f'（`{getattr(images[0], "name", "") or "未命名"}`）；'
                f'其余已忽略（{_rest}{"…" if len(images) > 4 else ""}）。'
                '要逐张分析请分次上传。')).send()
        await process_storefront_image(
            images[0], caption,
            mode='chat' if cl.user_session.get('free_chat') else 'site')
        return

    if docs:
        if len(docs) > 1:
            await cl.Message(content=(
                f'⚠️ 一次收到 {len(docs)} 个文件，本次只处理第 1 个；'
                '其余请分次上传。')).send()
        await process_attachment(docs[0], caption)
        return

    await process_message(message.content)


async def process_message(text: str):
    text = (text or '').strip()
    # 左侧操作栏控制指令（不进入业务状态机）
    if text.startswith('##新对话##'):
        await process_new_chat()
        return
    if text.startswith('##打开:'):
        await process_open_conv(text[len('##打开:'):].rstrip('#'))
        return
    if text.startswith('##预览:'):
        # 兼容保留：老前端/书签可能还在发 ##预览:<id>##。§2 已取消中间只读页，
        # 两者现在指向同一个动作（一步到位 + 回放）。
        await process_open_conv(text[len('##预览:'):].rstrip('#'))
        return
    if text.startswith('##删除:'):
        await process_delete_conv(text[len('##删除:'):].rstrip('#'))
        return
    if text.startswith('##删除分析:'):
        # 删除对比功能里的单个历史分析（纯本地，0 次 API）
        try:
            from agent.analysis_store import delete_analysis
            aid = text[len('##删除分析:'):].rstrip('#')
            if delete_analysis(aid):
                await cl.Message(content='已删除该条分析记录。', author='assistant').send()
            else:
                await cl.Message(content='未找到要删除的分析记录。', author='assistant').send()
        except Exception:
            await cl.Message(content='删除分析失败，请重试。', author='assistant').send()
        await refresh_sidebar()
        return
    if text.startswith('/expert') or text.startswith('##专家:'):
        # `##专家:` 是 UI 面板/卡片页发的**静默通道**：不回文字消息（前端出浮层）。
        # `/expert` 是用户手打的，保留文字回执。
        _silent = text.startswith('##专家:')
        _arg = (text.split(':', 1)[1] if _silent else text[len('/expert'):])
        # ⚠️ `##专家:xxx##` 的尾巴要削掉：`split(':',1)[1]` 得到的是 `xxx##`，
        # 不 rstrip 的话 id 永远匹配不上（这条通道此前没有前端调用者，属于潜伏 bug）。
        await process_set_expert(_arg.strip().rstrip('#').strip(), silent=_silent)
        return
    if text.startswith('##模型:'):
        await process_set_model(text[len('##模型:'):].rstrip('#'))
        return
    if text.startswith('##自由对话:'):
        await process_free_chat_toggle(text[len('##自由对话:'):].rstrip('#'))
        return
    if text.startswith('##导出##'):
        await process_export()
        return

    state = get_state()
    # 每次业务消息都应用当前会话选择的模型
    set_llm_model(cl.user_session.get('llm_model') or DEFAULT_MODEL)
    # 需求4：恢复本会话的「自由对话」开关
    # （contextvar 不跨消息保持，需在每次业务消息前重设一次）
    try:
        from agent.agent_graph import set_free_chat_mode
        set_free_chat_mode(bool(cl.user_session.get('free_chat')))
    except Exception:
        pass

    # 执行过程实时推送：agent 内部思考 + 工具调用记录（执行中默认展开，实时可见）
    parent = None

    async def on_event(ev):
        nonlocal parent
        try:
            if parent is None:
                parent = cl.Step(name='本次执行过程', type='run', default_open=True, icon='bot')
                await parent.send()
            if ev.get('kind') == 'think':
                st = cl.Step(name=ev.get('name', '思考'), type='run',
                             parent_id=parent.id, default_open=True, show_input=False, icon='brain')
                st.output = ev.get('text', '')
            else:
                st = cl.Step(name=ev.get('name', '工具'), type='tool',
                             parent_id=parent.id, default_open=True, show_input=False, icon='wrench')
                inp = ev.get('input', '')
                out = ev.get('output', '')
                st.output = (f"输入：{inp}\n输出：{out}") if inp else out
            await st.send()
        except Exception:
            pass

    # 调用 LangGraph Agent（实时回传思考/工具事件）
    result = await run_agent(text, state, hooks={'on_event': on_event})

    # 更新状态
    cl.user_session.set('state', result)

    # 保存会话（历史保留）并刷新左侧操作栏数据
    _persist_conversation(result)

    # 渲染回复
    await render_response(result)

    # 若 agent 正等待结构化输入（投入/人数/缺失信息）→ 推录入表单到工作台
    maybe_push_input_form(result)

    # 会话状态更新后再刷新一次（含新增分析）
    await refresh_sidebar()


async def render_response(state: dict):
    """根据状态渲染不同类型的回复"""
    
    # 1. 文本回复（所有阶段都有）
    messages = state.get('messages', [])
    if messages:
        last_msg = messages[-1]
        if last_msg.get('role') == 'assistant' and last_msg.get('content'):
            await cl.Message(content=last_msg['content']).send()
    
    # 2. 候选列表（找区域分支 / 入口B 地点优先分支）
    candidates = state.get('candidates', [])
    if candidates and not state.get('score_result'):
        # 候选商铺 → 右侧工作台卡片（可点击选择）；聊天区只留简短引导
        try:
            cards = []
            for i, c in enumerate(candidates, 1):
                # 数据可信度三态随卡片一起下发（2026-09-17）：
                # 前端必须能区分「实测 / 推算 / 不可得」，不许把推算展示成实测。
                cards.append({
                    'i': i,
                    'name': c.get('name', f'候选 {i}'),
                    'area': c.get('area'),
                    'price': round(float(c.get('price'))) if c.get('price') else None,
                    'precise': c.get('precise', True),
                    'in_rent': '58' in str(c.get('source', '')),
                    'addr': c.get('address', ''),
                    'rent_state': c.get('rent_state') or 'unavailable',
                    'area_state': c.get('area_state') or 'unavailable',
                    'rent_band': c.get('rent_band'),
                    'rent_source': c.get('rent_source'),
                    'area_source': c.get('area_source'),
                    'source': c.get('source'),
                    # 房源性质（2026-09-17 诉求③）：'出租' = 房东招租 / '转让' = 别人转店。
                    # 用户确认转让铺**要算**，但必须一眼分清 —— 两者谈判对象、
                    # 能否议价、要不要承接二手设备完全不同。
                    'deal': c.get('deal') or '',
                    # 定位层级（2026-09-17 诉求②）：door/building/street/area。
                    # 区域级必须在卡片上写明"无门牌"，不能看起来跟门牌级一样精确。
                    'addr_level': c.get('addr_level') or ('door' if c.get('precise') else 'area'),
                })
            write_dashboard({
                'kind': 'candidates',
                'title': f'找到 {len(cards)} 家候选商铺',
                'cards': cards,
                'hint': ('点击卡片即可开始分析这家'
                         + ('（选中后自动按四品类反推）' if state.get('place_first_mode')
                            else '')),
            })
        except Exception as e:
            print('[candidates-dash] error:', e)
        # 聊天区保留简短引导（完整候选信息在右侧卡片）
        await cl.Message(content=f"**📋 已为您找到 {len(candidates)} 家候选商铺**，请到**右侧工作台**点击卡片选择（点击即开始分析）。").send()
        # 候选选择阶段：工作台保留已有内容（不强制清空，避免用户丢失刚建立的分析上下文）
        # 无已有分析时才回占位，避免残留旧表单/旧分析混淆。
        try:
            if DASHBOARD_FILE.exists():
                dash = json.loads(DASHBOARD_FILE.read_text(encoding='utf-8'))
            else:
                dash = {}
            if not dash.get('cards') and not dash.get('dims'):
                clear_dashboard()
        except Exception:
            clear_dashboard()

    # 2.4) 需求3：店铺优先 —— 四品类推荐卡片（已有店铺 → 反推开什么店）
    if (state.get('phase') == 'reverse_match'
            and state.get('category_recs') and not state.get('score_result')):
        try:
            from agent.agent_graph import build_category_rec_payload
            write_dashboard(build_category_rec_payload(state['category_recs']))
        except Exception as e:
            print('[category-rec-dash] error:', e)

    # 2.5) 奶茶品牌选择卡片（进入预算环节之前）
    if state.get('phase') == 'collect_brand' and not state.get('score_result'):
        try:
            from agent.agent_graph import build_brand_payload
            write_dashboard(build_brand_payload())
        except Exception as e:
            print('[brands-dash] error:', e)
    
    # 3. 评分可视化（分析完成后 → 右侧工作台；文本仍在中间对话框）
    score_result = state.get('score_result')
    if score_result:
        # 取该轮 LLM 解读（最后一条 assistant 消息）用于 PDF 报告
        interp = ''
        if messages:
            for m in reversed(messages):
                if m.get('role') == 'assistant' and m.get('content'):
                    interp = m['content']
                    break
        # 带 conv_id → PDF 落盘缓存，历史会话再打开时直接复用（§2 第三步 / §4 提速）
        await render_analysis_dashboard(score_result, interpretation=interp,
                                        conv_id=cl.user_session.get('conv_id'))

    # 4. 对比列表（右侧工作台卡片勾选 2-4 个 → 点开始对比）
    compare_list = state.get('compare_list')
    if compare_list:
        try:
            write_dashboard({
                'kind': 'compare-pick',
                'title': f'选择要对比的分析（可勾选 2-4 个）',
                'items': compare_list,
                'hint': '勾选 2-4 个历史分析，点「开始对比」生成对比报告',
            })
        except Exception as e:
            print('[compare-pick] error:', e)
        state['compare_list'] = None
        cl.user_session.set('state', state)

    # 5. 对比结果（跨对话对比多个分析）
    comparison = state.get('comparison')
    if comparison:
        await render_comparison(comparison)
        state['comparison'] = None
        cl.user_session.set('state', state)


async def _analysis_pdf(result: dict, interpretation: str, conv_id: str = None):
    """取分析 PDF 字节：**优先复用落盘**（`data/reports/<conv_id>.pdf`）。

    §4 提速点 + §2 第三步：历史会话每次打开都会重跑一遍
    Playwright/Chromium（1~5s，首启更久），但同一个会话的分析结果**不会变**
    （流水/评分都由冻结的输入决定）→ 生成一次、之后直接读盘。
    落盘用"先写临时文件再 os.replace"的原子写：
    半截文件一旦被后续打开复用，用户拿到的是坏 PDF，而且很难复现。
    """
    if conv_id:
        p = REPORT_DIR / f'{conv_id}.pdf'
        try:
            if p.exists() and p.stat().st_size > 800:   # <800B 必然是坏文件
                return p.read_bytes()
        except Exception:
            pass
    from report_pdf import build_analysis_pdf
    data = await asyncio.to_thread(build_analysis_pdf, result, interpretation)
    if data and conv_id:
        try:
            REPORT_DIR.mkdir(parents=True, exist_ok=True)
            tmp = REPORT_DIR / f'.{conv_id}.pdf.tmp'
            tmp.write_bytes(data)
            os.replace(tmp, REPORT_DIR / f'{conv_id}.pdf')
        except Exception as e:
            print('[pdf] cache write error:', e)
    return data


async def render_analysis_dashboard(result: dict, interpretation: str = '',
                                    conv_id: str = None):
    """分析输出 → 右侧工作台（指标卡片/热力图/得分表格/雷达图由前端渲染）；
    中间对话框保留 AI 解读文本 + PDF 附件。纯本地，0 次 API。

    `conv_id`：传入则 PDF 走落盘复用（历史会话再次打开时不重跑 Playwright）。
    """
    # §4 提速：地图与 PDF **互不依赖**（一个拼瓦片、一个跑 Playwright），改前是串行。
    # 并发只负责"生产"两样东西，**发送消息仍然按固定顺序**（地图先进工作台、
    # PDF 消息在后），否则对话区顺序会随调度抖。
    _t0 = time.perf_counter()
    _map_task = None
    _pdf_task = None
    if result.get('lng') is not None and result.get('lat') is not None:
        _map_task = asyncio.create_task(
            asyncio.to_thread(_build_shop_map_png, result))
    _pdf_task = asyncio.create_task(_analysis_pdf(result, interpretation, conv_id))

    # 1) 周边地图（放大版）→ base64（作为右侧"热力图/地图"）
    map_b64 = ''
    if _map_task is not None:
        try:
            png = await _map_task
            if png:
                map_b64 = 'data:image/png;base64,' + base64.b64encode(png).decode('ascii')
        except Exception as e:
            print('[map] error:', e)
    _t_map = time.perf_counter()

    # 2) 写入右侧工作台数据（纯本地）
    try:
        write_dashboard(build_analysis_dashboard_with_sim(result, map_b64))
    except Exception as e:
        print('[dashboard] error:', e)

    # 3) 导出 PDF 报告（仍附在中间对话框，可下载）
    try:
        pdf_bytes = await _pdf_task
        if pdf_bytes:
            fname = f"址南针_分析报告_{result.get('name', '')[:12]}.pdf"
            await cl.Message(
                content="**分析完成**：AI 解读见上方；指标卡片 / 得分表格 / 雷达图 / 周边热力图已生成到**右侧工作台**。\n\n分析报告附件：",
                elements=[cl.Pdf(name=fname, content=pdf_bytes, display='inline')],
            ).send()
    except Exception as e:
        print('[pdf] error:', e)
    _t_end = time.perf_counter()
    # §4 第 0 步：这条不在图里（是 UI 侧收尾），所以直接落控制台，
    # 不往 hooks['stage_ms'] 里塞 —— 那本账是"分析阶段"的，混进渲染会误导归因。
    print(f'[timing] 工作台渲染 地图/面板 {( _t_map - _t0)*1000:.0f}ms · '
          f'PDF(含并发等待) {(_t_end - _t_map)*1000:.0f}ms · '
          f'合计 {(_t_end - _t0)*1000:.0f}ms')


# ---------------------------------------------------------------
# 商铺周边地图（OSM 免费瓦片 + 本地 POI 标注；0 次高德 API）
# ---------------------------------------------------------------
TILE_CACHE = ROOT / 'data' / 'tiles'
# 瓦片源（按顺序尝试；均为免费、无需 key、不计高德配额）：
# 1) 高德网页地图瓦片（国内可达、中文标注）
# 2) OpenStreetMap 瓦片（国外可达）
_TILE_SOURCES = [
    'https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}',
    'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
]
_TILE_UA = {'User-Agent': 'ZheLiXuanDian/1.0 (local selection demo)'}


def _deg2num(lat, lng, zoom):
    n = 2.0 ** zoom
    xtile = (lng + 180.0) / 360.0 * n
    lat_rad = math.radians(lat)
    ytile = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
    return xtile, ytile


def _fetch_tile(z, x, y):
    """取一张瓦片（本地缓存优先）。**并发安全**：9 张瓦片现在是并发拉的（§4），
    各自写各自的缓存文件；只有 `mkdir(parents=True, exist_ok=True)` 这一句
    在 Windows 上存在"两个线程同时建同一层目录"的窄竞争（会偶发 FileExistsError），
    所以把它单独包起来 —— 目录已存在时直接继续读/写，不影响任何一张瓦片。"""
    p = TILE_CACHE / str(z) / str(x) / f'{y}.png'
    if p.exists():
        return p
    for src in _TILE_SOURCES:
        try:
            url = src.replace('{z}', str(z)).replace('{x}', str(x)).replace('{y}', str(y))
            url = url.replace('{s}', str((x + y) % 4 + 1))  # 高德子域轮换
            r = requests.get(url, headers=_TILE_UA, timeout=8)
            if r.status_code == 200 and len(r.content) > 800:
                try:
                    p.parent.mkdir(parents=True, exist_ok=True)
                except FileExistsError:
                    pass
                p.write_bytes(r.content)
                return p
        except Exception:
            continue
    return None


def _build_shop_map_png(result):
    lng, lat = result['lng'], result['lat']
    category = result.get('category', '')
    try:
        profile = get_profile(category)
        radius = profile.get('radius', 500)
    except Exception:
        profile, radius = {}, 500

    GRID = 3
    # ⚠️ 几何参数收敛到 `engine.road_sim.map_geometry` **一处**（2026-09-20）：
    #    原先这里自己算 zoom/x0/y0，仿真看板另算一遍 → 两边一旦漂移，
    #    小人的轨迹就会错位到地图外面。现在同一个函数、同一组参数。
    geo = road_sim.map_geometry(lat, lng, radius, grid=GRID)
    img_w = geo['img_w']
    zoom, x0, y0 = geo['zoom'], geo['x0'], geo['y0']
    target_mpd = geo['mpd']

    im = PILImage.new('RGB', (img_w, img_w), (240, 240, 240))
    ok = 0
    # §4 提速：9 张瓦片**并发拉取**。改前是 `for gx: for gy:` 串行 await 网络，
    # 单张 timeout 8s、失败还要依次试 2 个源 → 新位置首次最坏 9×(8+8)=144s，
    # 是整条链上最不可控的一段（缓存命中时 ~0.1s，所以只有首访难受）。
    # ⚠️ 线程池只用来"取字节"；`im.paste()` 仍回到本线程串行做 ——
    #    对同一个 PIL 对象的并发写不是线程安全的，而 `_fetch_tile` 各写各的
    #    缓存文件、互不重叠，因此是安全的并发边界。
    _cells = [(gx, gy) for gx in range(GRID) for gy in range(GRID)]
    with ThreadPoolExecutor(max_workers=len(_cells)) as _ex:
        _tiles = list(_ex.map(
            lambda c: _fetch_tile(zoom, x0 + c[0], y0 + c[1]), _cells))
    for (gx, gy), t in zip(_cells, _tiles):
        if t:
            try:
                tile = PILImage.open(t).convert('RGB')
                im.paste(tile, (gx * 256, gy * 256))
                ok += 1
            except Exception:
                pass

    draw = ImageDraw.Draw(im, 'RGBA')

    def _to_px(lo, la):
        px = road_sim.project(lo, la, geo)
        return px[0], px[1]

    cx, cy = _to_px(lng, lat)
    r_px = radius / target_mpd

    # 分析半径圈
    if ok:
        draw.ellipse([cx - r_px, cy - r_px, cx + r_px, cy + r_px],
                     outline=(59, 130, 246, 200), width=3)

    # ⚠️ 选点口径 = **引擎的步行路网距离**（`scoring.query_pois`），2026-09-20 改。
    #    改前这里用 `query_within`（直线）选点画点 → 「地图上的点」与
    #    「真正进 Huff 分子/分母的点」不是同一批（口径不一致，红线 2）。
    #    现在地图与模型同源：地图画出来的每一个点，都确实参与了 D 与 P。
    def _road_pois(label, cap):
        try:
            got = query_pois(label, lng, lat, radius)
        except Exception:
            return []
        got.sort(key=lambda p: p.get('distance') or 0)
        return got[:cap]

    comps = _road_pois(category, 18) if category else []
    for c in comps:
        x, y = _to_px(c['lng'], c['lat'])
        draw.ellipse([x - 5, y - 5, x + 5, y + 5], fill=(239, 68, 68, 215))

    # 目标客群 POI（学校/办公/商圈/社区/通勤；步行路网口径，同一入口）
    targets = []
    if category:
        for t in profile.get('target_pois', []):
            label = t.get('label', '')
            if label:
                targets.extend(_road_pois(label, 40))
    seen = set()
    t_list = []
    for t in targets:
        k = (round(t['lng'], 4), round(t['lat'], 4))
        if k in seen:
            continue
        seen.add(k)
        t_list.append(t)
        if len(t_list) >= 40:
            break
    for t in t_list:
        x, y = _to_px(t['lng'], t['lat'])
        draw.ellipse([x - 4, y - 4, x + 4, y + 4], fill=(37, 99, 235, 215))

    # 本铺标记（红色大点）
    draw.ellipse([cx - 9, cy - 9, cx + 9, cy + 9], fill=(220, 38, 38, 255),
                 outline=(255, 255, 255, 255), width=3)

    # 图例
    try:
        font = ImageFont.truetype('msyh.ttc', 17)
    except Exception:
        font = ImageFont.load_default()
    y = 12
    for text, color in [('● 本铺', (220, 38, 38)), ('● 竞品', (239, 68, 68)),
                        ('● 客群', (37, 99, 235))]:
        draw.text((14, y), text, fill=color + (255,), font=font)
        y += 25
    if not ok:
        draw.text((12, y), '网络瓦片不可用，以下为周边POI示意', fill=(0, 0, 0, 210), font=font)

    buf = io.BytesIO()
    im.save(buf, format='PNG')
    return buf.getvalue()


async def render_shop_map(result):
    """（已并入右侧工作台）周边地图由 render_analysis_dashboard 生成 base64 渲染。"""
    return


# ---------------------------------------------------------------
# 跨对话"全方位对比"渲染（多列表格 + 多雷达图；0 次 API）
# ---------------------------------------------------------------
async def render_comparison(cmp):
    """对比结果 → 右侧工作台（多列表格 + 多雷达 + 多系列柱状图）；对话框只留一句指引。0 次 API。"""
    items = cmp.get('items') or []
    if not items and cmp.get('a'):
        items = [cmp['a'], cmp['b']]  # 兼容旧的 {a,b} 结构
    if not items:
        return
    items = items[:4]
    n = len(items)

    def cell(v):
        return '-' if v is None else v

    def _fmt_int(v):
        try:
            return f'{int(v):,}'
        except Exception:
            return v

    def _gv(item, m):
        """取某店某经营指标数值：优先 profit 字典，其次条目顶层字段，最后 utility 兜底。"""
        p = item.get('profit') or {}
        u = item.get('utility') or {}
        # 顶层字段映射（analysis_store 存的扁平字段）
        top = {'预估月流水': 'month_sales', '月净利估算': 'net_profit',
               '前期投入': 'investment', '回本周期(月)': 'payback', '人数': 'staff'}
        # utility 兜底（月水电等）
        u_map = {'月水电': '水电合计(元/月)'}
        v = p.get(m)
        if v is None and m in top:
            v = item.get(top[m])
        if v is None and m in u_map:
            v = u.get(u_map[m])
        try:
            return float(v)
        except Exception:
            return None

    # 各 item 的维度（展示名统一）
    dim_lists = []
    for it in items:
        d = {_DIM_LABELS.get(k, k): v for k, v in (it.get('dims') or {}).items()}
        dim_lists.append(d)
    all_dims = list(dict.fromkeys(k for d in dim_lists for k in d))

    # 对比表格：每行一项指标，每列一个店
    table = []
    table.append(['总分'] + [f"{cell(it.get('total'))}（{it.get('verdict', '')}）" for it in items])
    for d in all_dims:
        table.append([d] + [cell(dl.get(d)) for dl in dim_lists])
    table.append(['面积'] + [f"{cell(it.get('area'))}㎡" for it in items])
    table.append(['月租'] + [f"¥{cell(_fmt_int(it.get('rent')))}" for it in items])
    table.append(['前期投入'] + [f"¥{cell(_fmt_int((it.get('profit') or {}).get('前期投入', it.get('investment'))))}" for it in items])
    table.append(['运营人数'] + [f"{cell((it.get('profit') or {}).get('人数', it.get('staff')))}人" for it in items])
    table.append(['预估月流水'] + [f"¥{cell(_fmt_int((it.get('profit') or {}).get('月流水估算', it.get('month_sales'))))}" for it in items])
    table.append(['月净利估算'] + [f"¥{cell(_fmt_int((it.get('profit') or {}).get('月净利估算', it.get('net_profit'))))}" for it in items])
    table.append(['回本周期'] + [f"{cell((it.get('profit') or {}).get('回本周期(月)', it.get('payback')))}月" for it in items])
    table.append(['盈亏判断'] + [cell((it.get('profit') or {}).get('盈亏判断')) for it in items])
    table.append(['周边竞品'] + [f"{cell(it.get('comp_count'))}家" for it in items])

    # 图表数据：每维度每店一值；指标每店一值
    dims_chart = {d: [dl.get(d) for dl in dim_lists] for d in all_dims}
    dims_chart['总分'] = [it.get('total') or 0 for it in items]
    metrics = ['预估月流水', '月净利估算', '前期投入', '月人工', '月物料成本', '月水电', '月成本合计']
    metrics_chart = {m: [_gv(it, m) for it in items] for m in metrics}

    payload = {
        'kind': 'compare',
        'shop': f"对比 {n} 个分析",
        'category': '｜'.join(f"{it.get('shop', '?')}（{it.get('category', '')}）" for it in items),
        'compare': {
            'names': [it.get('shop', f'#{i + 1}') for i, it in enumerate(items)],
            'table': table,
            'dims': dims_chart,
            'metrics': metrics_chart,
        },
    }
    write_dashboard(payload)

    await cl.Message(
        content="**对比完成**：" + " vs ".join(f"`{it.get('shop', '?')}`" for it in items) +
                "\n对比表格、多雷达图与柱状图已生成到**右侧工作台**。"
    ).send()
