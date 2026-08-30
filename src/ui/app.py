# -*- coding: utf-8 -*-
"""
app.py —— 浙江商铺选址 AI 顾问（产品化升级版）
================================================
v2 升级点:
1. 产品化品牌（标题/图标/配色/页脚）
2. 首次访问引导页（讲清产品价值与用法）
3. 地图可视化（候选地址标点 + 周边 POI 分布）
4. 多地址对比视图（表格 + 雷达图 + 总分排序）
5. 深度需求追问（客群/堂食外卖/面积）
6. 评分结果导出（JSON，供海选材料）
"""
import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
import plotly.graph_objects as go
import pandas as pd

from config import CATEGORY_PROFILES  # noqa: E402
from agent.agent import SiteAgent, parse_request, geocode  # noqa: E402
from engine.scoring import score_site, compare_sites  # noqa: E402

st.set_page_config(
    page_title='浙里选址 · AI 商铺选址顾问',
    page_icon='🧭',
    layout='wide',
    initial_sidebar_state='expanded',
)

# ---------------------------------------------------------------
# 品牌样式
# ---------------------------------------------------------------
st.markdown("""
<style>
    .main .block-container {padding-top: 2rem;}
    .hero-title {
        font-size: 2.6rem; font-weight: 800;
        background: linear-gradient(120deg, #1e3a8a, #3b82f6);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        margin-bottom: 0.3rem;
    }
    .hero-sub {
        font-size: 1.05rem; color: #6b7280; margin-bottom: 1rem;
    }
    .score-card {
        background: linear-gradient(135deg, #eff6ff, #f8fafc);
        border-radius: 12px; padding: 1rem 1.2rem;
        border-left: 4px solid #3b82f6; margin-bottom: 0.5rem;
    }
    .verdict-rec {color: #059669; font-weight: 700;}
    .verdict-caut {color: #d97706; font-weight: 700;}
    .verdict-bad  {color: #dc2626; font-weight: 700;}
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------
# 会话状态
# ---------------------------------------------------------------
if 'agent' not in st.session_state:
    st.session_state.agent = SiteAgent()
if 'history' not in st.session_state:
    st.session_state.history = []
if 'first_visit' not in st.session_state:
    st.session_state.first_visit = True
    # 首次访问: 自动给出阶段一引导问题
    st.session_state.history.append({
        'role': 'bot',
        'text': ('👋 你好！我是你的选址顾问。先确认一下：'
                 '**你有具体看中的商铺了吗？**\n\n'
                 '- 有的话，告诉我商铺位置（如"杭州武林广场杭州大厦B座"）\n'
                 '- 还没有的话，告诉我你想开在哪个区域（如"杭州滨江"）'),
        'scores': None,
    })

# ---------------------------------------------------------------
# 顶部品牌区
# ---------------------------------------------------------------
st.markdown('<div class="hero-title">🧭 浙里选址</div>', unsafe_allow_html=True)
st.markdown('<div class="hero-sub">不是数据的搬运工，是决策的解释器 —— 基于 Huff 引力模型的商铺选址 AI 顾问</div>',
            unsafe_allow_html=True)

# 首次访问引导
if st.session_state.first_visit:
    with st.expander('🚀 首次使用？看这里（点我展开）', expanded=True):
        st.markdown("""
**我是谁**：一个面向个人创业者的**选址决策顾问**，帮你判断"这个铺子该不该开、为什么"。

**怎么用**：在下方输入框用一句人话说出你的想法，比如：
> "想在杭州武林广场开奶茶店，月租8000，主要做白领生意"

**我能做什么**：
- 🗺️ 实时抓取候选地址周边**真实数据**（竞品/学校/写字楼/商圈/社区/地铁）
- 🧮 基于 **Huff 引力模型** 从 4 个维度评分（客群匹配/竞争压力/交通可达/租金承受）
- 💡 用大模型生成**可解释的选址建议** + 风险警告
- ⚖️ 支持**多地址对比**（"A 和 B 比一下"）

**重要声明**：分析基于公开 POI 数据，不含真实人流量与成交租金，结论为选址适宜度参考。
""")
    st.session_state.first_visit = False

# ---------------------------------------------------------------
# 侧边栏
# ---------------------------------------------------------------
with st.sidebar:
    st.header('🎯 快速开始')
    st.caption('点一下自动填入（演示脚本）')
    demos = {
        '🥤 奶茶 · 武林广场30㎡ · 月租8k': '有，看中了杭州武林广场的一个铺子，想开奶茶店，面积30平方，月租8000',
        '🍰 甜品 · 宁波天一广场 · 房租1万5': '有，宁波天一广场附近有个铺子，开甜品店，面积25平，房租1万5',
        '🥟 早餐 · 杭州滨江长河路 · 预算6k': '有，杭州滨江区长河路看了一家，开早餐店，面积20平，月租6000',
        '🏪 便利店 · 温州人民路 · 月租1万': '有，温州鹿城区人民路有个铺子，开便利店，面积40平，月租1万',
    }
    for label, text in demos.items():
        if st.button(label, use_container_width=True):
            st.session_state.demo_text = text
    st.divider()

    st.markdown('#### 🧩 支持品类')
    for name, prof in CATEGORY_PROFILES.items():
        st.markdown(f"- **{name}**：{prof['profile_desc']}")
    st.divider()

    st.markdown('#### 🧮 评分维度')
    st.markdown("""
- 客群匹配度：周边目标客群 POI 引力
- 竞争压力：同品类竞品引力
- 交通可达性：地铁/公交距离与密度
- 租金承受力：月租 vs 预估月流水
""")
    st.divider()

    if st.button('🗑️ 清空对话', use_container_width=True):
        st.session_state.agent = SiteAgent()
        st.session_state.history = [{
            'role': 'bot',
            'text': ('👋 你好！我是你的选址顾问。先确认一下：'
                     '**你有具体看中的商铺了吗？**\n\n'
                     '- 有的话，告诉我商铺位置（如"杭州武林广场杭州大厦B座"）\n'
                     '- 还没有的话，告诉我你想开在哪个区域（如"杭州滨江"）'),
            'scores': None,
        }]
        st.session_state.first_visit = True
        st.rerun()

    st.caption('基于 Huff 引力模型（λ=2）· 高德开放数据 · 数据截至 2026-08')

# ---------------------------------------------------------------
# 评分渲染（总分对比 + 地图 + 明细）
# uid: 历史消息索引, 用于给动态元素生成唯一 key, 避免多轮对话元素ID冲突
# ---------------------------------------------------------------
def _render_scores(scores, uid=0):
    if len(scores) == 1:
        s = scores[0]
        c1, c2 = st.columns([1, 1])
        with c1:
            _score_card(s)
        with c2:
            _radar_chart(s, uid)
        _profit_summary(s, uid)   # 水电/盈利核心卖点, 直接展示
        _map_view(scores, uid)
        _detail_view(s, uid)
    else:
        # 多地址对比
        st.markdown('### ⚖️ 候选地址对比')
        _compare_table(scores, uid)
        c1, c2 = st.columns([1, 1])
        with c1:
            _bar_chart(scores, uid)
        with c2:
            _radar_overlay(scores, uid)
        _map_view(scores, uid)
        for i, s in enumerate(scores):
            _detail_view(s, f"{uid}_{i}")


def _score_card(s):
    vcls = {'推荐': 'verdict-rec', '谨慎推荐': 'verdict-caut'}.get(s['verdict'], 'verdict-bad')
    color = {'推荐': '#059669', '谨慎推荐': '#d97706'}.get(s['verdict'], '#dc2626')
    dim_str = ' · '.join(f"{k} {v}" for k, v in s['dims'].items())
    st.markdown(f"""
    <div class="score-card">
        <div style="font-size:1.1rem;font-weight:700;">{s['name']}</div>
        <div style="font-size:2.4rem;font-weight:800;color:{color};">{s['total']}<span style="font-size:1rem;">分</span></div>
        <div class="{vcls}">{s['verdict']}</div>
        <div style="font-size:0.85rem;color:#6b7280;margin-top:0.3rem;">
            {dim_str}
        </div>
    </div>
    """, unsafe_allow_html=True)


def _profit_summary(s, uid=0):
    """水电成本 + 盈利测算摘要（核心卖点, 直接展示不折叠）"""
    if not (s.get('utility') or s.get('profit')):
        st.info('📐 补充商铺面积（如"面积30平"），即可获得水电成本与盈利测算')
        return
    u, p = s.get('utility'), s.get('profit')
    # 用 label 区分多轮分析(不同商铺/不同次分析), 避免 st.metric 元素ID冲突
    tag = f"（{s['name'][:10]}）" if s.get('name') else ''
    with st.container(border=True):
        cols = st.columns(3)
        if u:
            with cols[0]:
                st.metric(f'月水电成本{tag}', f"¥{u['水电合计(元/月)']:,}/月",
                          help=f"电价{u['电价(元/度)']}元/度×{u['月用电(kWh)']}kWh + 水价{u['水价(元/吨)']}元/吨×{u['月用水(吨)']}吨")
        if p:
            with cols[1]:
                st.metric(f'月净利估算{tag}', f"¥{p['月净利估算']:,}",
                          help=f"月流水{p['月流水估算']:,}×毛利55% - 固定成本{p['月固定成本']:,}")
            with cols[2]:
                pb = f"{p['回本周期(月)']}月" if p['回本周期(月)'] else '难回本'
                st.metric(f'回本周期{tag}', pb, help=f"初始投入{p['初始投入参考']:,} / 月净利")
        st.caption(f"💧 当地参考标准（{u['城市'] if u else ''}）：商业电价 {u['电价(元/度)'] if u else '-'}元/度、商业水价 {u['水价(元/吨)'] if u else '-'}元/吨。以当地当月公告为准。")


def _radar_chart(s, uid=0):
    dims = list(s['dims'].keys())
    vals = [s['dims'][d] for d in dims] + [s['dims'][dims[0]]]
    labels = dims + [dims[0]]
    fig = go.Figure(go.Scatterpolar(r=vals, theta=labels, fill='toself',
                                    line_color='#3b82f6', fillcolor='rgba(59,130,246,0.25)'))
    fig.update_layout(
        polar=dict(radialaxis=dict(range=[0, 100], showticklabels=False)),
        height=300, margin=dict(t=30, b=10), showlegend=False,
        title=dict(text='四维度评估', font=dict(size=14)),
    )
    st.plotly_chart(fig, use_container_width=True, key=f'radar_{uid}')


def _bar_chart(scores, uid=0):
    fig = go.Figure()
    colors = [{'推荐': '#059669', '谨慎推荐': '#d97706'}.get(s['verdict'], '#dc2626') for s in scores]
    fig.add_bar(
        x=[s['name'] for s in scores],
        y=[s['total'] for s in scores],
        text=[f"{s['total']}分" for s in scores],
        textposition='outside',
        marker_color=colors,
    )
    fig.update_layout(
        title='总分对比', yaxis_range=[0, 100],
        height=300, margin=dict(t=40, b=20),
    )
    st.plotly_chart(fig, use_container_width=True, key=f'bar_{uid}')


def _radar_overlay(scores, uid=0):
    fig = go.Figure()
    palette = ['#3b82f6', '#f59e0b', '#10b981', '#ef4444']
    for i, s in enumerate(scores):
        dims = list(s['dims'].keys())
        vals = [s['dims'][d] for d in dims] + [s['dims'][dims[0]]]
        labels = dims + [dims[0]]
        fig.add_trace(go.Scatterpolar(
            r=vals, theta=labels, fill='toself',
            name=s['name'],
            line_color=palette[i % 4],
            fillcolor='rgba(0,0,0,0)',
        ))
    fig.update_layout(
        polar=dict(radialaxis=dict(range=[0, 100], showticklabels=False)),
        height=320, margin=dict(t=30, b=10),
        title=dict(text='四维度对比', font=dict(size=14)),
    )
    st.plotly_chart(fig, use_container_width=True, key=f'radar_overlay_{uid}')


def _compare_table(scores, uid=0):
    rows = []
    for s in scores:
        rows.append({
            '地址': s['name'],
            '总分': s['total'],
            '结论': s['verdict'],
            '客群': s['dims']['客群匹配度'],
            '竞争': s['dims']['竞争压力'],
            '交通': s['dims']['交通可达性'],
            '租金': s['dims']['租金承受力'],
            '竞品数': s['evidence']['竞品数'],
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True, key=f'tbl_{uid}')


def _map_view(scores, uid=0):
    try:
        import folium
        from streamlit_folium import st_folium

        # 中心 = 第一个地址
        c0 = scores[0]
        # 用高德瓦片(国内可访问), 避免 OpenStreetMap 在国内加载失败
        m = folium.Map(location=[c0['lat'], c0['lng']], zoom_start=15,
                       tiles=None)
        folium.TileLayer(
            tiles='https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}',
            attr='高德地图', name='高德', max_zoom=18, subdomains='1234',
        ).add_to(m)
        folium.TileLayer(
            tiles='https://webst0{s}.is.autonavi.com/appmaptile?style=6&x={x}&y={y}&z={z}',
            attr='高德卫星', name='卫星', max_zoom=18, subdomains='1234',
        ).add_to(m)
        folium.LayerControl(collapsed=True).add_to(m)
        palette = ['#3b82f6', '#f59e0b', '#10b981', '#ef4444']
        for i, s in enumerate(scores):
            folium.Marker(
                [s['lat'], s['lng']],
                popup=f"{s['name']}：{s['total']}分 · {s['verdict']}",
                tooltip=f"{s['name']} ({s['total']}分)",
                icon=folium.Icon(color='blue' if i == 0 else 'orange',
                                 icon='store', prefix='fa'),
            ).add_to(m)
        # 周边 POI 散点（用第一个地址的客群配套）
        try:
            from engine.realtime import get_surrounding
            for label in ['商圈', '办公', '学校', '社区', '通勤']:
                pois = get_surrounding(label, c0['lng'], c0['lat'], 500)
                for p in pois[:30]:
                    folium.CircleMarker(
                        [p['lat'], p['lng']], radius=2.5,
                        color={'商圈': '#f59e0b', '办公': '#3b82f6',
                               '学校': '#10b981', '社区': '#8b5cf6',
                               '通勤': '#64748b'}[label],
                        fill=True, fill_opacity=0.6,
                        popup=p.get('name', ''),
                    ).add_to(m)
        except Exception:
            pass
        st.markdown('### 🗺️ 位置与周边')
        st_folium(m, width='100%', height=380, key=f'map_{uid}')
    except Exception as e:
        st.caption(f'（地图组件暂不可用：{e}）')


def _detail_view(s, uid=0):
    with st.expander(f"🔍 {s['name']} 详细分析 —— {s['total']}分 · {s['verdict']}", key=f'exp_{uid}'):
        st.markdown('**关键证据：**')
        e = s['evidence']
        st.markdown(f"- 周边竞品：**{e['竞品数']} 家**（引力比 {e['竞品引力比']}）")
        st.markdown(f"- 客群引力累计：{e['客群引力累计']}")
        st.markdown(f"- 最近通勤点：{e['最近通勤点(m)']}m，500m 内 {e['500m内通勤点数']} 个")
        st.markdown(f"- 预估月流水：¥{e['预估月流水']:,}（日单量约 {e['预估日单量']}），租金占 {e['租金占流水比']}")
        # 精细化营业额明细
        if e.get('流水明细'):
            d = e['流水明细']
            st.markdown('**📈 营业额测算明细**（偏保守估算）')
            st.markdown(f"- 基准日单量 {d['基准日单量']} × 客群修正 {d['客群修正']} × 竞争修正 {d['竞争修正']} × 面积修正 {d['面积修正']} × 保守系数 {d['保守系数']}")
            st.markdown(f"- **估算日单量 ≈ {d['估算日单量']}**，客单价 ¥{d['客单价']}")
        # 装修档次
        if s.get('decoration'):
            deco = s['decoration']
            st.markdown(f"**🎨 装修档次评估**：{deco['档次']}型（单位投入 {deco['单位投入(元/㎡)']} 元/㎡，预算 ¥{deco['装修预算']:,}）")
        st.markdown('**客群明细：**')
        for g in s['guest_details']:
            samples = f"（如 {', '.join(g['samples'][:3])}）" if g['samples'] else ''
            st.markdown(f"- {g['label']}：{g['count']} 个 POI {samples}")
        # 水电/盈利测算
        if s.get('utility'):
            u = s['utility']
            st.markdown('**💡 水电成本测算**（当地参考标准）')
            st.markdown(f"- 商业电价：**{u['电价(元/度)']} 元/度**（{u['电价模式']}）｜商业水价：**{u['水价(元/吨)']} 元/吨**（{u['城市']}）")
            st.markdown(f"- 月用电 {u['月用电(kWh)']} kWh（电费 ¥{u['电费(元/月)']:,}）+ 月用水 {u['月用水(吨)']} 吨（水费 ¥{u['水费(元/月)']:,}）")
            st.markdown(f"- **月水电合计：¥{u['水电合计(元/月)']:,}**")
        if s.get('profit'):
            p = s['profit']
            st.markdown('**💰 盈利测算**')
            pb = f"{p['回本周期(月)']} 个月" if p['回本周期(月)'] else '难以回本'
            st.markdown(f"- 月流水估算 ¥{p['月流水估算']:,} ｜ 月固定成本 ¥{p['月固定成本']:,}（租金{p['月租金']:,} + 水电{s['utility']['水电合计(元/月)']:,} + 人工{p['月人工(2人)']:,} + 杂费{p['月杂费']:,}）")
            st.markdown(f"- **月净利估算 ¥{p['月净利估算']:,}** ｜ 回本周期 **{pb}** ｜ **{p['盈亏判断']}**")
        if s['warnings']:
            st.warning('\n'.join(s['warnings']))
        # 导出单条结果
        if st.button(f"📤 导出 {s['name']} 分析结果", key=f"expbtn_{uid}"):
            export_path = Path(__file__).resolve().parent.parent / 'exports'
            export_path.mkdir(exist_ok=True)
            fname = f"选址分析_{s['name']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(export_path / fname, 'w', encoding='utf-8') as f:
                json.dump(s, f, ensure_ascii=False, indent=1)
            st.success(f'已导出：{fname}')


# ---------------------------------------------------------------
# 对话历史展示（在评分函数定义之后调用）
# ---------------------------------------------------------------
for _uid, h in enumerate(st.session_state.history):
    if h['role'] == 'user':
        st.chat_message('user').write(h['text'])
    else:
        with st.chat_message('assistant'):
            if h.get('text'):
                st.write(h['text'])
            scores = h.get('scores')
            if scores:
                _render_scores(scores, uid=_uid)


# ---------------------------------------------------------------
# 输入区
# ---------------------------------------------------------------
user_input = st.chat_input('例如：想在杭州武林广场开奶茶店，月租8000，主要做白领生意')

if 'demo_text' in st.session_state and st.session_state.demo_text:
    user_input = st.session_state.demo_text
    st.session_state.demo_text = None

if user_input:
    st.session_state.history.append({'role': 'user', 'text': user_input})

    agent = st.session_state.agent
    # 阶段机驱动: 全部交给 agent.ask()（含引导/搜候选/选择/分析）
    reply_text = agent.ask(user_input)

    # 判断是否有评分结果（agent 完成分析时, addresses 和 category 齐备）
    results = []
    if (agent.state.get('category') and agent.state.get('addresses')
            and agent.state.get('phase') == 'analysis'):
        # 逐个地址评分（agent.ask 已返回文本, 这里渲染图表）
        for addr in agent.state['addresses']:
            lng, lat = geocode(addr)
            if lng is None and agent.state.get('pending_coord'):
                lng, lat = agent.state['pending_coord']
            if lng is None:
                continue
            try:
                r = score_site(agent.state['category'], lng, lat,
                               agent.state['rent'] or 8000, name=addr,
                               area_m2=agent.state.get('area'),
                               budget=agent.state.get('budget'))
                results.append(r)
            except Exception:
                continue

    st.session_state.history.append({'role': 'bot', 'text': reply_text, 'scores': results or None})

    st.rerun()
