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
import json
import math
import time
import base64
import asyncio
import requests
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
from engine.scoring import score_site
from config import CATEGORY_PROFILES, get_profile, DATA_DIR
from data.query import query_within
from agent.llm import set_llm_model, MODEL_OPTIONS, DEFAULT_MODEL


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
        save_conversation(conv_id, state, title=derive_title(state))
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


async def refresh_sidebar():
    """把左侧操作栏数据写入 public/sidebar.json（纯本地，0 次 API）。
    hist 含每个会话的完整消息（messages），供前端点击历史项直接 fetch 渲染预览，
    不再往输入框注入 ##预览 指令（避免聊天区出现指令字样、且点开更稳定）。"""
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
                    'verdict': sr.get('verdict', ''),
                } if sr else None,
            })
        data = {'analyses': _history_stats(), 'hist': hist,
                'model': cl.user_session.get('llm_model') or DEFAULT_MODEL}
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
        from report_pdf import build_analysis_pdf
        pdf_bytes = await asyncio.to_thread(build_analysis_pdf, sr, interp)
        if not pdf_bytes:
            await cl.Message(content='导出失败：PDF 生成无输出。').send()
            return
        fname = f"浙里选址_分析报告_{str(sr.get('name', ''))[:12]}.pdf"
        await cl.Message(
            content='**导出分析报告**（PDF）：',
            elements=[cl.Pdf(name=fname, content=pdf_bytes, display='inline')],
        ).send()
    except Exception as e:
        print('[export] error:', e)
        await cl.Message(content=f'导出失败：{e}').send()


async def process_preview_conv(conv_id: str):
    """历史会话独立页：把某会话的只读记录写入 public/conv_page.json，前端轮询渲染。"""
    conv = get_conversation(conv_id)
    if not conv:
        await cl.Message(content='⚠️ 该会话不存在或已被清理。').send()
        return
    msgs = []
    for m in (conv.get('state') or {}).get('messages', []):
        c = (m.get('content') or '').strip()
        if not c:
            continue
        msgs.append({'role': m.get('role', 'assistant'), 'content': c[:4000]})
    sr = (conv.get('state') or {}).get('score_result') or {}
    payload = {
        'id': conv_id,
        'title': conv.get('title', '会话')[:16],
        'ts': conv.get('updated') or conv.get('ts', ''),
        'messages': msgs[-60:],  # 每页最多展示最近 60 条
        'analysis': {
            'shop': sr.get('name', ''),
            'category': sr.get('category', ''),
            'total': sr.get('total'),
            'verdict': sr.get('verdict', ''),
        } if sr else None,
    }
    try:
        (ROOT / 'public').mkdir(parents=True, exist_ok=True)
        (ROOT / 'public' / 'conv_page.json').write_text(
            json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    except Exception as e:
        print('[conv_page] error:', e)


def _conv_page_payload(conv: dict) -> dict:
    """（备用）同步版本 —— 生成独立页载荷。"""
    msgs = []
    for m in (conv.get('state') or {}).get('messages', []):
        c = (m.get('content') or '').strip()
        if not c:
            continue
        msgs.append({'role': m.get('role', 'assistant'), 'content': c[:4000]})
    sr = (conv.get('state') or {}).get('score_result') or {}
    return {
        'id': conv.get('id', ''),
        'title': conv.get('title', '会话')[:16],
        'ts': conv.get('updated') or conv.get('ts', ''),
        'messages': msgs[-60:],
        'analysis': {
            'shop': sr.get('name', ''),
            'category': sr.get('category', ''),
            'total': sr.get('total'),
            'verdict': sr.get('verdict', ''),
        } if sr else None,
    }


# ---------------------------------------------------------------
# 右侧"分析工作台"数据（写入 public/dashboard.json，前端 custom_js 读取渲染）
# ---------------------------------------------------------------
DASHBOARD_FILE = ROOT / 'public' / 'dashboard.json'
_DIM_WEIGHTS = {'客群匹配度': '35%', '竞争环境': '25%', '交通可达性': '25%', '租金承受力': '15%', '面积适配度': '10%'}
_DIM_LABELS = {'竞争压力': '竞争环境'}  # 分数高=竞争少=环境优，字面语义与分数方向一致


def _fmt_money(v):
    try:
        return f'¥{float(v):,.0f}'
    except Exception:
        return '-' if v is None else str(v)


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
    write_dashboard({'kind': 'clear'})


def _last_assistant_msg(state: dict) -> str:
    for m in reversed(state.get('messages', [])):
        if m.get('role') == 'assistant' and m.get('content'):
            return str(m['content'])
    return ''


def maybe_push_input_form(state: dict):
    """当 agent 正在等待用户输入结构化经营参数时，把录入表单数据写入工作台。
    仅在明确等待投入/人数或缺失信息时覆盖工作台（0 次 API）。"""
    try:
        last = _last_assistant_msg(state)
        if not last:
            return
        fields = []
        mode = ''
        hint = ''
        if ('最后确认一下' in last) or ('请回复前期投入成本' in last):
            mode = 'invest'
            hint = '请确认经营参数，我将据此完成盈利测算与四维评分'
            fields = [
                {'key': 'investment', 'label': '前期投入成本', 'unit': '万元', 'placeholder': '如 12', 'default': ''},
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

    cards = [
        {'label': '综合评分', 'value': str(total) if total is not None else '-',
         'unit': '分', 'tone': tone_for(total or 0)},
        {'label': '选址结论', 'value': verdict, 'unit': '',
         'tone': 'good' if verdict == '推荐' else ('mid' if verdict == '谨慎推荐' else 'bad')},
        {'label': '月净利估算', 'value': _fmt_money(np_), 'unit': '/月',
         'tone': 'good' if (np_ or 0) > 0 else 'bad'},
        {'label': '回本周期', 'value': str(payback) if payback else '难回本',
         'unit': '个月' if payback else '', 'tone': 'good' if payback else 'bad'},
        {'label': '前期投入', 'value': _fmt_money(p.get('前期投入')), 'unit': '',
         'tone': 'mid'},
        {'label': '周边竞品', 'value': str(e.get('竞品数', '-')), 'unit': '家', 'tone': 'mid'},
    ]

    dim_rows = [{'name': k, 'value': v, 'weight': _DIM_WEIGHTS.get(k, '-')}
                for k, v in dims.items()]

    profit_rows = []
    if p:
        profit_rows = [
            ('预估月流水', _fmt_money(p.get('月流水估算'))),
            ('月物料成本', f"{_fmt_money(p.get('月物料成本'))}（占流水 {p.get('物料占比', 0):.0%}）"),
            ('月人工', f"{_fmt_money(p.get('月人工'))}（{p.get('人数', '-')}人×¥{p.get('人均月薪', 0):,.0f}最低工资）"),
            ('月租金', _fmt_money(p.get('月租金'))),
            ('月水电', _fmt_money(p.get('月水电'))),
            ('月杂费', _fmt_money(p.get('月杂费'))),
            ('月固定成本', _fmt_money(p.get('月固定成本'))),
            ('前期投入', f"{_fmt_money(p.get('前期投入'))}（{p.get('投入来源', '')}）"),
            ('装修档次', (result.get('decoration') or {}).get('档次', '-')),
            ('月净利估算', _fmt_money(p.get('月净利估算'))),
            ('回本周期', f"{p.get('回本周期(月)')} 个月" if payback else '难以回本'),
            ('盈亏判断', p.get('盈亏判断', '-')),
        ]

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
            ('周边竞品', f"{e.get('竞品数', 0)} 家（引力比 {e.get('竞品引力比', '-')}）"),
            ('客群引力累计', _fmt_num(e.get('客群引力累计', '-'))),
            ('最近通勤点', f"{_fmt_num(e.get('最近通勤点(m)', '-'))}m，500m 内 {e.get('500m内通勤点数', 0)} 个"),
            ('预估月流水', f"¥{e.get('预估月流水', 0):,.0f}，租金占 {e.get('租金占流水比', '-')}"),
        ]

    return {
        'kind': 'analysis',
        'shop': result.get('name', ''),
        'category': result.get('category', ''),
        'total': total,
        'verdict': verdict,
        'cards': cards,
        'dims': dims,
        'dim_rows': dim_rows,
        'profit_rows': profit_rows,
        'utility_rows': utility_rows,
        'evidence_rows': evidence_rows,
        'warnings': result.get('warnings', []),
        'map_b64': map_b64,
    }


# ---------------------------------------------------------------
# 欢迎消息
# ---------------------------------------------------------------
@cl.on_chat_start
async def on_chat_start():
    # 恢复上次选择的模型（会话级 + 持久化），供本次会话的 LLM 调用
    mdl = _load_model()
    cl.user_session.set('llm_model', mdl)
    set_llm_model(mdl)

    welcome = """# 早上好，BOSS

##### ——您的AI商铺选址分析师

**我能帮你做什么：**
- 告诉我「想开什么 + 开在哪里」，我直接帮你找合适的在租商铺并评分推荐
- 或你已看中某个铺子，告诉我地址，我帮你做维度评分（客群/竞争/交通/租金）
- 结合当地水电标准与人工/物料/装修成本的盈利测算，告诉你"该不该开、回本要多久"

**直接说就行，比如：**
- "帮我找杭州滨江的奶茶店"
- "我想在宁波鄞州开早餐店"
- "看中了杭州滨江区长河路128号的一个铺子，开奶茶店，月租8000"

每次执行过程的**内部思考与工具调用记录**会实时展开显示在对话中，全程可见。"""

    # 全新会话：不残留上一会话的工作台（刷新/恢复会话已有 conv_id，不清空）
    if not cl.user_session.get('conv_id'):
        clear_dashboard()
    await cl.Message(content=welcome).send()
    await refresh_sidebar()


# ---------------------------------------------------------------
# 快捷指令
# ---------------------------------------------------------------
# 左侧操作栏命令处理（前端 custom_js 按钮发送的控制指令）
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


async def process_open_conv(conv_id: str):
    """打开历史会话（继续对话）：把状态切到该会话，不向当前页面回放消息。
    历史会话的完整记录由前端在「独立页面」中只读展示（GET /api/conv/<id>）。"""
    conv = get_conversation(conv_id)
    if not conv:
        await cl.Message(content='⚠️ 该会话不存在或已被清理。').send()
        return
    state = conv.get('state') or {'messages': [], 'phase': 'intro', 'candidates': []}
    cl.user_session.set('state', state)
    cl.user_session.set('conv_id', conv_id)
    set_llm_model(cl.user_session.get('llm_model') or DEFAULT_MODEL)

    # 有分析结果则重渲右侧工作台（指标卡片/雷达图/热力图）
    sr = state.get('score_result')
    if sr:
        interp = ''
        for m in reversed(state.get('messages', [])):
            if m.get('role') == 'assistant' and m.get('content'):
                interp = m['content']
                break
        await render_analysis_dashboard(sr, interpretation=interp)

    await cl.Message(content=f'✅ 已切换到历史会话「{conv.get("title", "")}」'
                             f'（{conv.get("updated") or conv.get("ts", "")}）。'
                             f'此后的对话将记录在该会话中。').send()
    await refresh_sidebar()


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
@cl.on_message
async def on_message(message: cl.Message):
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
        await process_preview_conv(text[len('##预览:'):].rstrip('#'))
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
    if text.startswith('##模型:'):
        await process_set_model(text[len('##模型:'):].rstrip('#'))
        return
    if text.startswith('##导出##'):
        await process_export()
        return

    state = get_state()
    # 每次业务消息都应用当前会话选择的模型
    set_llm_model(cl.user_session.get('llm_model') or DEFAULT_MODEL)

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
    
    # 2. 候选列表（找区域分支）
    candidates = state.get('candidates', [])
    if candidates and not state.get('score_result'):
        # 候选商铺 → 右侧工作台卡片（可点击选择）；聊天区只留简短引导
        try:
            cards = []
            for i, c in enumerate(candidates, 1):
                cards.append({
                    'i': i,
                    'name': c.get('name', f'候选 {i}'),
                    'area': c.get('area'),
                    'price': round(float(c.get('price'))) if c.get('price') else None,
                    'precise': c.get('precise', True),
                    'in_rent': '58' in str(c.get('source', '')),
                    'addr': c.get('address', ''),
                })
            write_dashboard({
                'kind': 'candidates',
                'title': f'找到 {len(cards)} 家候选商铺',
                'cards': cards,
                'hint': '点击卡片即可开始分析这家',
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
        await render_analysis_dashboard(score_result, interpretation=interp)

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


async def render_analysis_dashboard(result: dict, interpretation: str = ''):
    """分析输出 → 右侧工作台（指标卡片/热力图/得分表格/雷达图由前端渲染）；
    中间对话框保留 AI 解读文本 + PDF 附件。纯本地，0 次 API。"""
    # 1) 生成周边地图（放大版）→ base64（作为右侧"热力图/地图"）
    map_b64 = ''
    if result.get('lng') is not None and result.get('lat') is not None:
        try:
            png = await asyncio.to_thread(_build_shop_map_png, result)
            if png:
                map_b64 = 'data:image/png;base64,' + base64.b64encode(png).decode('ascii')
        except Exception as e:
            print('[map] error:', e)

    # 2) 写入右侧工作台数据（纯本地）
    try:
        write_dashboard(build_analysis_dashboard(result, map_b64))
    except Exception as e:
        print('[dashboard] error:', e)

    # 3) 导出 PDF 报告（仍附在中间对话框，可下载）
    try:
        from report_pdf import build_analysis_pdf
        pdf_bytes = await asyncio.to_thread(build_analysis_pdf, result, interpretation)
        if pdf_bytes:
            fname = f"浙里选址_分析报告_{result.get('name', '')[:12]}.pdf"
            await cl.Message(
                content="**分析完成**：AI 解读见上方；指标卡片 / 得分表格 / 雷达图 / 周边热力图已生成到**右侧工作台**。\n\n分析报告附件：",
                elements=[cl.Pdf(name=fname, content=pdf_bytes, display='inline')],
            ).send()
    except Exception as e:
        print('[pdf] error:', e)


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
    p = TILE_CACHE / str(z) / str(x) / f'{y}.png'
    if p.exists():
        return p
    for src in _TILE_SOURCES:
        try:
            url = src.replace('{z}', str(z)).replace('{x}', str(x)).replace('{y}', str(y))
            url = url.replace('{s}', str((x + y) % 4 + 1))  # 高德子域轮换
            r = requests.get(url, headers=_TILE_UA, timeout=8)
            if r.status_code == 200 and len(r.content) > 800:
                p.parent.mkdir(parents=True, exist_ok=True)
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
    img_w = 256 * GRID
    # 依据分析半径自适应缩放，让半径圈约占图片宽度 30%（放大、更清晰）
    mpd = 156543.03392 * math.cos(math.radians(lat))  # 米/像素 at zoom 0
    target_mpd = radius / (0.30 * img_w) if radius else 3.0
    zoom = int(round(math.log2(mpd / target_mpd)))
    zoom = max(13, min(17, zoom))

    xf, yf = _deg2num(lat, lng, zoom)
    x0, y0 = int(xf), int(yf)

    im = PILImage.new('RGB', (img_w, img_w), (240, 240, 240))
    ok = 0
    for gx in range(GRID):
        for gy in range(GRID):
            t = _fetch_tile(zoom, x0 - 1 + gx, y0 - 1 + gy)
            if t:
                try:
                    tile = PILImage.open(t).convert('RGB')
                    im.paste(tile, (gx * 256, gy * 256))
                    ok += 1
                except Exception:
                    pass

    draw = ImageDraw.Draw(im, 'RGBA')

    def _to_px(lo, la):
        f_x, f_y = _deg2num(la, lo, zoom)
        return (f_x - (x0 - 1)) * 256, (f_y - (y0 - 1)) * 256

    cx, cy = _to_px(lng, lat)
    r_px = radius / target_mpd

    # 分析半径圈
    if ok:
        draw.ellipse([cx - r_px, cy - r_px, cx + r_px, cy + r_px],
                     outline=(59, 130, 246, 200), width=3)

    # 竞品（同品类，本地库 0 API）
    try:
        comps = query_within(category, lng, lat, radius)[:18] if category else []
    except Exception:
        comps = []
    for c in comps:
        x, y = _to_px(c['lng'], c['lat'])
        draw.ellipse([x - 5, y - 5, x + 5, y + 5], fill=(239, 68, 68, 215))

    # 目标客群 POI（学校/办公/商圈/社区/通勤，本地库 0 API）
    targets = []
    if category:
        try:
            for t in profile.get('target_pois', []):
                label = t.get('label', '')
                if label:
                    targets.extend(query_within(label, lng, lat, radius))
        except Exception:
            pass
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
    metrics = ['预估月流水', '月净利估算', '前期投入', '月人工', '月物料成本', '月水电', '月固定成本']
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
