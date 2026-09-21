# -*- coding: utf-8 -*-
"""
agent_graph.py —— LangGraph Agent 图定义
==========================================
把原有的手写状态机升级为 LangGraph 图节点：
- classify: 意图识别（规则提取，不调 LLM）
- collect_info: 信息收集
- collect_brand: 收集奶茶加盟品牌（仅奶茶; 位于预算环节之前）
- collect_invest: 收集前期投入/人数
- shop_first: 店铺优先——已有铺子但没想好做什么，收 地址/月租/面积
- reverse_match: 店铺优先——四品类并联测算，反推推荐开什么店
- search_rental: 候选搜索
- select_shop: 选择商铺
- analyze: 评分分析
- interpret: LLM 解读
- free_chat: 自由问答
- compare: 对比已分析商铺

两条入口，覆盖用户的两种真实起点：
  A. 品类优先：先想好开什么 → 找铺子 → 选品牌 → 预算 → 评分
  B. 店铺优先（需求3）：先有铺子 → 收地址/月租/面积 → 四品类反推 → 选方向
     → （选奶茶则衔接品牌卡片）→ 预算 → 评分

核心体验（针对用户反馈修正）：
1. 用户给出「品类 + 地区」→ 直接搜索并推荐候选商铺，**绝不反问租金**
   （租金由候选商铺自带；只有"已有具体铺子"才收集租金）
2. 奶茶品类在问预算之前先确认加盟品牌（品牌卡片形式，同候选商铺卡片），
   因为品牌决定 Huff 测算里的同商圈溢价系数 UPLIFT；其余品类跳过此步
3. 尽量少发 API 请求、每次量大：58 同城只抓一次、区域只 geocode 一次、
   无精确路名的候选直接用区域中心坐标（0 次额外调用）、评分优先本地库。
4. **自由对话不被流程劫持**（需求4）：命中品类词/城市名但在提问（如
   "奶茶店毛利率一般多少？"）不进入选址流程；另提供手动「自由对话」开关。
"""
import json
import os
import sys
import re
import asyncio
import time
import contextvars
from pathlib import Path
from typing import Dict, Any, Optional, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.state import AgentState
from agent.llm import call_llm, call_llm_sync, call_llm_with_tools
from agent.agent import (
    parse_request, geocode, extract_guest, extract_mode, extract_area,
    extract_address, _clean_area, _is_pure_district, _district_business_center,
    _in_zhejiang, KNOWN_AREA_COORDS, extract_brand,
    extract_rent, extract_category, extract_monthly_revenue,
    # 供 `_mask_revenue_rent` 复用：**不新写第二套**"什么算租金/流水"的规则
    RENT_PATTERN, REVENUE_PATTERN, DAILY_REVENUE_PATTERN,
)
from agent.rental58 import fetch_shops, CITY_CODES
from agent.knowledge import build_context as kb_context
from agent.knowledge import policy_links as kb_policy_links
from experts import registry as experts
from experts import toolbox as expert_toolbox
from engine.scoring import score_site
from engine.transfer_risk import summarize as transfer_risk_summary
from data.fetch_poi import search_poi
from data.query import haversine
from config import get_profile


# ---------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------
DEFAULT_EXPERT = 'site_advisor'


def _anchor_sample_text() -> str:
    """锚点样本量的**实时**文案（给用户可见提示用）。

    为什么要有这个函数（2026-09-18）：品类反推卡片的 note 里原来写死
    「锚点仅奶茶有 83 家真实门店标定」。样本量是会变的（手标 83 家 → 离线扩样
    近千家），写死就是**静默过期**。改成从 `agent/model_facts.py` 现取。

    ⚠️ 取不到时返回「真实门店」这种**不含数字**的说法，**绝不回落到写死的旧值**
    （回落 = 拿过期数据冒充实时，比不说更坏）。
    """
    try:
        from agent.model_facts import collect
        a = collect().get('锚点') or {}
        n = (a.get('逐店明细') or {}).get('家数')
        used = (a.get('标定产物') or {}).get('实际采用')
        if n and used and used != n:
            return f'{n} 家真实门店（实际采用 {used} 家）'
        if n:
            return f'{n} 家真实门店'
    except Exception:                                     # noqa: BLE001
        pass
    return '真实门店'


def _expert_kb_tags(expert_id):
    """取该专家的知识库分区标签；取不到就返回 None（= 不过滤）。

    这里**刻意不抛异常**：分区检索是锦上添花，配置错误应该在 registry 加载时
    大声失败（那时会抛 ExpertConfigError），不该在检索这一层把整轮对话打断。
    """
    try:
        return experts.get_expert(expert_id).kb_tags or None
    except Exception:
        return None


def _expert_id(state) -> str:
    """当前会话选中的专家 id；未选则回落默认（选址评估师 = 改造前的默认行为）。"""
    return (state or {}).get('expert') or DEFAULT_EXPERT


# ---------------------------------------------------------------
# 结构化证据包（§6：让"选专家"在主要路径上真的有差别）
# ---------------------------------------------------------------
# 背景：改造前 `free_chat` 只注入一行摘要
#   f"品类: X, 地址: Y, 总分: Z, 结论: W"
# 于是"选了某位专家"与"直接问大模型"在运行时几乎无差别（只差 kb 分区）。
# 本函数把会话里**已算出的结构化证据**整包给出：打分四维、经营评分、
# 三档情景、口径区间、租金临界点、一票否决、客单价口径、竞品洞察、门头照。
#
# 两条纪律：
# ① **省略即没有**：缺的字段直接不进包，不写"暂无"占位
#    —— 否则模型会把"暂无"读成"该项为 0"。
# ② **只给摘要不给全量字典**：三档情景每档 30+ 个成本键、口径区间两端各一套，
#    整包塞进去会把 prompt 撑大（§4 的同一个问题）。只保留决策相关字段。
_BIZ_KEYS = ('月流水估算', '月净利估算', '净利率', '回本周期(月)', '人数', '申报人数',
             '毛利率', '外卖抽成占流水比', '扣渠道后毛利率', '月租金', '月人工',
             '月物料成本', '月损耗', '月外卖抽成', '月场地附加费', '月税', '月水电',
             '月品牌费', '月成本合计', '前期投入', '盈亏判断')


def _slim_profit(p):
    if not isinstance(p, dict):
        return None
    out = {k: p.get(k) for k in _BIZ_KEYS if p.get(k) is not None}
    return out or None


def _slim_bands(b):
    if not isinstance(b, dict):
        return None
    out = {}
    for k, v in b.items():
        if k == '区间':
            out['区间'] = v
        elif isinstance(v, dict):
            s = _slim_profit(v)
            if s:
                out[k] = s
    return out or None


def build_evidence_pack(state) -> str:
    """把会话里已算出的结构化证据拼成 JSON 文本；无分析结果时返回空串。"""
    r = state.get('score_result') or {}
    if not r:
        return ''
    ev = {
        '品类': r.get('category'),
        '地址': r.get('name'),
        '城市': r.get('city'),
        '月租(元/月)': r.get('monthly_rent'),
        '面积(㎡)': r.get('area_m2'),
        '品牌': r.get('brand'),
        '地址评分': r.get('地址评分', r.get('total')),
        '地址评分结论': (r.get('veto') or {}).get('位置分结论'),
        '打分维度': r.get('dims'),
        '维度权重': r.get('weights'),
        '最终结论(以经营评分为准)': r.get('verdict'),
        '经营评分': r.get('经营评分'),
        '一票否决': r.get('veto'),
        '租金临界点': r.get('rent_limits'),
        '经营测算(中性档)': _slim_profit(r.get('profit')),
        '三档情景': _slim_bands(r.get('profit_bands')),
        '口径区间(价格弹性未标定)': ((r.get('口径区间') or {}).get('区间')
                                     if isinstance(r.get('口径区间'), dict) else None),
        '客单价校正': r.get('客单价校正'),
        '关键证据': r.get('evidence'),
        '竞品洞察': r.get('competitor_insight'),
        '门头照评估': r.get('storefront'),
        '引擎警告': r.get('warnings'),
    }
    ev = {k: v for k, v in ev.items() if v not in (None, '', {}, [])}
    return json.dumps(ev, ensure_ascii=False, default=str)


async def _expert_commentary(expert_id: str, user_msg: str,
                             temperature: float = 0.3,
                             timeout: float = 45.0) -> str:
    """让某位"此前从未进过 prompt"的专家，用他的人设解读**引擎已算好的结果**。

    为什么需要（§6）：`category_reverse` / `storefront_auditor` /
    `franchise_advisor` 三位专家声明的节点里**一次 LLM 都不调**
    （纯引擎 + 模板文案），于是他们的人设从未进过任何 prompt ——
    "选了也没区别"。这里各加一层 LLM 解读：**引擎结论仍是唯一事实来源**
    （prompt 明确禁止改数字），LLM 只负责换成该角色的口吻与行动建议。

    失败一律返回空串 → 调用方保持引擎模板文案（**严格增量**，不会让功能变差）。

    ⚠️ **输出长度是硬约束，不是风格偏好**（§4 实测）：
    首次上线时给的是"输出一份加盟前评估"，结果这一轮墙钟 **41.3s**
    （对比：整个分析轮的 LLM 解读 35s）—— 因为这些附加解读同样是
    跟着输出 token 数线性涨的。加盟品牌确认本该是"顺手确认一下"的一步，
    让用户为一段长文等 40 秒是**体验倒退**。故这里：
      · 在 system 尾部加一段"紧凑契约"（要点式、不重述输入数据）；
      · 预算从 90s 收到 45s（`ZL_EXPERT_LLM_TIMEOUT` 可覆盖）。
    实测收敛到 ~秒级，信息量不减（数字仍逐字来自引擎），只是不再铺陈。

    ⚠️ **离线开关**：设 `ZL_EXPERT_LLM_DISABLE=1` 即整体短路。
    `reverse_match_node` / `collect_brand_node` 是**离线回归套件直接调用**的节点
    （verify_flow_v2 / verify_brand_card / verify_flow_graph / verify_brand_graph），
    若这里无条件打外网，这四个"离线门禁"套件就会变成依赖网络与配额 ——
    那正是本项目一直在避免的事（flaky 组不许进离线门禁）。
    故：离线门禁在 `run_regression.py` 里统一置该变量；真实运行时它不存在。
    """
    if os.environ.get('ZL_EXPERT_LLM_DISABLE') == '1':
        return ''
    try:
        _budget = float(os.environ.get('ZL_EXPERT_LLM_TIMEOUT') or timeout)
    except Exception:
        _budget = timeout
    try:
        sys_msg = experts.compose_system_prompt(expert_id) + _BREVITY_TAIL
        txt = await call_llm(sys_msg, user_msg, temperature=temperature,
                             timeout=_budget, total_budget=_budget)
        return (txt or '').strip()
    except Exception:
        return ''


# 附加解读的紧凑契约：直接压的是**输出 token 数**，也就是这段的墙钟耗时。
# 明说"输入里的数据已经给用户看过"——否则模型会把 JSON 里的字段再抄一遍，
# 既占长度又零信息量。
_BREVITY_TAIL = (
    '\n\n【输出契约（硬要求，优先于你人设里的展开风格）】'
    '\n1. 总长 ≤ 200 字，要点式（短句 + 破折号），不分章节、不写大标题。'
    '\n2. 不要复述我给你的输入数据（那些字段我已有），只写**你的判断与行动项**。'
    '\n3. 数字必须逐字引用输入；输入里没有的，写"系统内暂无"，不要补。'
    '\n4. 直接给结论与下一步，不写"综上所述"这类铺垫。')


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
    # 3) 原文含门牌号 / 铺位特征 -> 有具体铺子
    #    ⚠️ 不能用 extract_address(text) 的结果来判：它只提取到"区域"级别，
    #       会把「杭州滨江春晓路 60 号」截断成「滨江」，门牌信息直接丢失
    #       （既有行为），导致用户报详细门牌仍被当成"在找铺子"。
    #    同时排除"帮我找/推荐"类搜索意图，避免
    #       「滨江路 100 号附近有哪些奶茶店」被误判成"已有具体商铺"。
    if not _wants_find(text) and not _wants_restart(text):
        if re.search(r'\d+\s*号', text) or any(
                k in text for k in ['大厦', '座', '铺位', '铺面', '门面', '楼层', '栋', '幢']):
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


# ---------------------------------------------------------------
# 自由对话模式（会话级手动开关，contextvar 隔离，不跨会话串扰）
# ---------------------------------------------------------------
# 规则闸门再准也有漏网，给用户一个"我不想被盘问，就想聊两句"的出口。
_FREE_CHAT_CTX = contextvars.ContextVar('free_chat_mode', default=False)


def set_free_chat_mode(on: bool):
    """打开/关闭「自由对话」。打开后 classify 直接短路到 chat，跳过所有流程判定。"""
    _FREE_CHAT_CTX.set(bool(on))


def is_free_chat_mode() -> bool:
    return bool(_FREE_CHAT_CTX.get())


# ---------------------------------------------------------------
# 需求 4：自由对话闸门（自动判断）
# ---------------------------------------------------------------
# 病根：classify_node 通用分支曾是
#         elif has_cat or has_addr or has_region or ...
#       —— 只要句子里出现品类词/城市名就直接进选址流程，
#       **完全不判断用户是不是在提问**。_looks_like_question() 虽然写了，
#       但只在 prev_phase 分支里被调用，主判定路径压根没用它。
#       实测翻车：「奶茶店毛利率一般多少？」命中「奶茶」→ no_shop
#                 → 反问"你想开在哪个区"，用户只想问个知识。
#
# 修法：主判定前插一道闸门 —— 命中"咨询词"且没有"启动词"就判 chat。
#
# 取舍原则：**闸门偏松进 chat**。
#   误判进 chat 代价小：free_chat 的 system prompt 已写了"涉及选址可温和引导
#     用户提供品类+区域"，大模型会把用户带回来；
#   误判进流程代价大：用户只想问个问题，却被连环盘问地址/租金，体验直接崩。
_CONSULT_KEYWORDS = [
    # 经营/成本/盈利
    '毛利率', '毛利', '净利', '净利润', '利润', '成本', '加盟费', '加盟条件',
    '营业额', '流水', '客单价', '单量', '翻台', '回本', '盈亏', '赚钱', '亏',
    # 资质/政策/流程
    '执照', '证件', '资质', '许可证', '备案', '政策', '补贴', '手续', '流程',
    '合同', '转让', '税务', '发票', '消防',
    # 开店实务
    '装修', '设备', '货源', '进货', '供应商', '工资', '人工', '招人', '培训',
    # 人力/排班（用户常用口语问法，原先漏掉会掉进选址流程）
    '几个人', '多少人', '人手', '忙得过来', '忙不过来', '排班', '几个员工',
    # 趋势/判断
    '趋势', '前景', '风险', '好不好做', '好做吗', '值得做', '饱和', '竞争激烈',
    '注意什么', '要注意', '踩坑', '经验',
]


def _wants_start_flow(text: str) -> bool:
    """用户是否明确要"开始选址/开始分析"。
    优先级高于咨询词：命中即走原有流程判定，不吃咨询闸门。
    例："我想开奶茶店" / "帮我找杭州滨江的铺子" / "这个铺子月租8000，分析一下"
    """
    if not text:
        return False
    for kw in ['想开', '要开', '准备开', '打算开', '计划开', '开一家', '开一个',
               '开个', '开间', '帮我找', '帮我查', '帮我推荐', '帮我看看', '推荐个',
               '推荐一下', '找铺', '找店', '找商铺', '找门面',
               '我有个铺', '我有个店', '有个铺子', '有个店铺', '有个店面',
               '有家铺', '有家店', '看中了', '看中', '找好了', '看好了', '选好',
               '分析一下', '帮我分析', '评估一下', '评估下', '算一下', '测算',
               '这家铺', '这个铺', '这个店', '这个位置', '这个地址',
               '月租', '租金是', '租金多少', '月租金',
               # 2026-09-17 入口 B：地点优先的意向词也要能穿透咨询闸门，
               # 否则「滨江这边怎么样，适合开店吗」会被"吗"字判成提问 → 掉进自由对话
               '适合开店', '能开店', '可以开店', '适不适合开店', '适合开什么',
               '适合做什么', '开什么店', '做什么好', '开什么好']:
        if kw in text:
            return True
    return False


def _is_consulting(text: str) -> bool:
    """咨询/提问意图（问知识、问成本、问政策），而不是要开店。
    注意：内部已处理启动词优先级 —— 有启动词就一定是 False。
    """
    if not text:
        return False
    if _wants_start_flow(text):
        return False
    if any(k in text for k in _CONSULT_KEYWORDS):
        return True
    return _looks_like_question(text)


def _wants_shop_first(text: str) -> bool:
    """需求 3：用户已有店铺、但还没想好做什么（"有铺子 + 无品类"）。
    与 _has_specific_shop 的区别：那个是"有铺子 + 有品类" → 仍走 have_shop，
    用户已经想好了，不该被反问品类。
    """
    if not text:
        return False
    # A. 有铺子措辞
    if _mentions_existing_shop(text):
        return True
    # B. 明确"不知道做什么"
    return any(k in text for k in [
        '不知道开什么', '不知道做什么', '不知道干', '做什么好', '干什么好',
        '开什么好', '开什么店', '适合做什么', '适合开什么', '做什么生意',
        '有什么建议', '推荐做什么', '帮我看看做什么', '做什么合适'])


# ---------------------------------------------------------------
# 入口 B（新增，2026-09-17）：地点优先 —— "我想在某个地方开店"
# ---------------------------------------------------------------
# 用户原话：「当用户说想在哪个地方开店的时候进入到推荐店铺的环节，然后再分析开什么店」。
#
# 改造前的实测真值表（三条全是真问题）：
#   "我想在杭州滨江开店"        → _wants_shop_first=False → no_shop → **被反问品类**
#   "滨江这边怎么样，适合开店吗" → _is_consulting=True    → **chat**（想开店被判成闲聊）
#   "杭州下沙适合开什么店"       → _wants_shop_first=True → shop_first → **追问月租/面积**
#                                （可他根本没铺子，答不出 → 死胡同）
#
# 与 shop_first 的分界线就一条：**手里到底有没有这个铺子**。
#   shop_first  = 有铺子，不知道做什么 → 直接四品类反推
#   place_first = 没铺子，只有地点     → 先推该地点的在租铺源，选中再反推
_SHOP_POSSESSION_WORDS = [
    '有个铺', '有个店', '有个店面', '有家铺', '有家店', '有间铺', '有间店',
    '有个门面', '有个门脸', '铺子租', '店面租', '店铺租', '租了铺', '租了店',
    '租下来', '签了租', '有商铺', '有个商铺', '自己的铺', '自己的店',
    '有铺子', '有店铺', '有店面', '手里有铺', '现在的铺',
]

# 开店意向词（"我想开个店"这类；不含品类）
_OPEN_INTENT = [
    '开店', '开一家', '开个店', '开家店', '开一间', '开个铺', '开个店',
    '想开个', '做个生意', '做生意', '做点生意',
    '适合开什么', '适合做什么', '能开什么', '可以开什么', '开什么好', '开什么店',
    '适合开店', '能开店', '可以开店', '能不能开店', '适不适合开店',
]

# 位置/方位提示词（用户在用口语指认某个地点，而不是在问知识）
_PLACE_HINTS = ['这边', '那边', '附近', '周围', '这一带', '那块', '这块', '这带',
                '地段', '商圈', '区域', '位置', '地点']

# 明显不是地名的词（`_clean_area` 剥壳后若只剩这些，说明没给出地点）
_NON_PLACE_WORDS = ['开店', '开一家', '开个店', '做什么', '开什么', '生意', '怎么',
                    '多少', '费用', '手续', '流程', '加盟', '什么']


def _mentions_existing_shop(text: str) -> bool:
    """用户是否明确说自己**手里已经有这个铺子**（区别于"想在某个地方开店"）。"""
    t = text or ''
    return bool(t) and any(k in t for k in _SHOP_POSSESSION_WORDS)


def _has_place_hint(text: str) -> bool:
    """句子里有没有"地点"。三级判定：城市名 → 方位词 → 区域名（剥壳后仍像个地名）。"""
    t = text or ''
    if extract_city(t):
        return True
    if any(k in t for k in _PLACE_HINTS):
        return True
    try:
        addr = _clean_area((parse_request(t) or {}).get('address') or '')
    except Exception:
        addr = ''
    if addr and 2 <= len(addr) <= 12 and not any(k in addr for k in _NON_PLACE_WORDS):
        return True
    return False


def _wants_place_first(text: str) -> bool:
    """「地点优先」入口：只说了想在哪里开店，**没有铺子**、也没想好品类。

    判定：有开店意向（或"帮我找铺子"这类搜索诉求）∧ ¬已有铺子 ∧ ¬品类（由调用方判）
          ∧ 有地点。"只说了想开店没给地点"也进本入口（进去会被问一句地点）。

    ⚠️ 2026-09-17 修正（用户诉求①）：原来这里把 `_wants_find`（"帮我找/推荐/哪里开"）
       排除在外，理由是"那属于 A 流程先问品类"。而这正是用户抱怨的那一步 ——
       「我想在杭州滨江开店」/「帮我找滨江的铺子」被反问"想开什么品类"，
       可**品类本该是他最后得出的结论**。
       现在不管有没有"找"字，只要**没品类**就先推铺源；
       A 流程（先品类）只在用户自己说了品类时才触发。
       `_wants_restart` 仍排除：它含"算了/别的/再看看"这类语气词，
       交给 prev_phase 分支判定更准（那里知道上一轮在干什么）。
    """
    t = text or ''
    if not t:
        return False
    if _mentions_existing_shop(t):            # 已有铺子 -> 那是 shop_first 的活
        return False
    if not (any(k in t for k in _OPEN_INTENT) or _wants_find(t)):
        return False
    if _has_place_hint(t):
        return True
    # 只说"想开店"、没给地点：也收进来，进去问一句地点（比掉进自由对话有用）
    return len(t) <= 20 and not _looks_like_question(t)



def _wants_diagnose(text: str) -> bool:
    """专家层 P1-2：用户**店已经开起来了**且报了经营数字 → 走经营诊断，不走选址。

    ⚠️ 必须在 `_wants_shop_first` **之前**判定："我有个店，月流水8万" 同时命中
       shop_first 的"有个店"；若顺序反了，已开店用户会被反问"想做哪个品类"。
    三个互斥起点（README §4.3）：有品类+有铺位→评估师；**无品类**+有铺位→品类反推；
    **已开店+有真实流水**→经营测算。本函数就是第三个起点的判定。
    """
    t = text or ''
    if not t:
        return False
    has_open = any(k in t for k in [
        '已经开了', '已开店', '开起来了', '开了个店', '开了家店', '开了半年',
        '开了三个月', '开业了', '在营业', '已经在营业', '店已经开', '店开了',
        '我店', '我这店', '现有的店', '存量店', '已经在做', '店在营业',
        # 以下与 _wants_shop_first 重叠（"我有个店/有个铺"）→ 靠 has_revenue 区分：
        # 没报流水 = 还没想好做什么（shop_first）；报了流水 = 已经在营业（diagnose）。
        '有个店', '有家店', '有个铺', '有个店面', '有个门面', '有间店', '有间铺'])
    has_revenue = any(k in t for k in [
        '月流水', '流水', '营业额', '月营收', '营收', '月销售', '销售额', '月营业额',
        '日流水', '日营业额', '月均流水'])
    return has_open and has_revenue


# 已上传经营数据附件后，用户"分析/诊断"类措辞（本身不含"已开店+流水"）也要能触发诊断。
_ANALYZE_HINT = ('分析', '诊断', '拆解', '拆一拆', '算一算', '算算', '算一下',
                 '帮我看看', '看看问题', '看看哪里', '帮我看下')


def _wants_analyze_attached(state, user_msg) -> bool:
    """已上传经营数据附件 + 用户只说"分析/诊断"这类词 → 触发已开店诊断。

    2026-09-18 修（用户实测报 bug）：上传《店铺经营月报》PDF 后，下一句只说
    "开始分析"，这句话没有 `_wants_diagnose` 要的"已开店 + 流水"措辞 → 诊断不被触发，
    专家反过来追问"月流水多少"，而数据明明在附件里。这里补一条：
    **有附件 + 分析意图 + 无选址信号** → 进 diagnose，让 diagnose_node 自己去
    附件正文抽字段，抽不到才追问。
    "无选址信号"由调用方保证（有地址/品类/具体铺子的仍走选址，不被这里抢走）。
    """
    if not (state.get('attachments') or []):
        return False
    t = (user_msg or '').strip()
    if not t:
        return False
    return any(k in t for k in _ANALYZE_HINT)


def _extract_full_address(text: str) -> Optional[str]:
    """需求 3：从原文里抽取**含门牌的完整地址**。

    为什么需要它：`parse_request()` / `extract_address()` 只提取到"区域"级别，
    会把「杭州滨江江陵路 88 号」压成「滨江」。而门牌号直接决定定位精度
    （区域中心点 vs 铺位本身），店铺优先分支必须拿到完整地址。
    """
    if not text:
        return None
    # 1) 优先：路/街/道/巷/弄 + 门牌号（前缀文字会被 {2,10} 一起吃掉）
    m = re.search(
        r'([\u4e00-\u9fa5]{2,10}(?:路|街|道|巷|弄|大道|大街)\s*\d+\s*号'
        r'(?:[\u4e00-\u9fa5]{0,10}?(?:大厦|大楼|广场|中心|商城|商铺|铺位|店))?)',
        text)
    if not m:
        # 2) 退路：任意「…数字+号」片段
        m = re.search(r'([\u4e00-\u9fa5\d]{2,24}\d+\s*号)', text)
    if not m:
        return None
    s = m.group(1).strip()
    # 去掉口语化的开头噪音（"我在…"、"铺子在…"）
    for kw in ['我在', '我有个', '有一个', '有个', '铺子在', '店在', '地址是', '位置是', '就是', '在']:
        if s.startswith(kw):
            s = s[len(kw):]
            break
    return s.strip() or None


def _awaiting_answer(state) -> bool:
    """上一轮 assistant 是否正在向用户提问（在等用户回答收集问题）"""
    for m in reversed(state.get('messages', [])):
        if m.get('role') == 'assistant':
            c = m.get('content', '')
            return ('？' in c) or ('?' in c) or ('还需要告诉我' in c) or ('回复' in c)
    return False


def _parse_brand_choice(text: str, allow_index_only: bool = False):
    """从文本解析用户选择的奶茶品牌。
    支持三种写法：
      1) 品牌名/关键词（"蜜雪冰城""蜜雪""coco"）→ 返回品牌名
      2) 卡片序号（"我选品牌3" / "品牌3"）→ 返回品牌名（需 allow_index_only 或带"品牌"前缀）
      3) 自创/不加盟（"自创品牌""不加盟""个体"）→ 返回 '自创品牌'
    解析不出返回 None。"""
    if not text:
        return None
    from engine.brands import BRAND_KEYWORDS
    # 明确的自创/个体诉求
    if any(k in text for k in ['自创', '自己创', '自己的牌', '自家牌', '不加盟', '个体', '杂牌']):
        return '自创品牌'
    # 品牌名/关键词优先于序号（"蜜雪冰城"里没有数字，但"我选品牌3"要走序号）
    for b, kws in BRAND_KEYWORDS.items():
        for kw in kws:
            if kw and kw in text:
                return b
    # 英文别名大小写不敏感兜底（用户常打小写 "coco"/"linlee"/"vq"）
    low = text.lower()
    for b, kws in BRAND_KEYWORDS.items():
        for kw in kws:
            if kw and kw.isascii() and kw.lower() in low:
                return b
    # 卡片序号："我选品牌3" / "品牌 3" / "第3个品牌"
    m = (re.search(r'品牌\s*(?:第)?\s*(\d+)', text)
         or re.search(r'第\s*(\d+)\s*个?\s*品牌', text))
    if m:
        n = int(m.group(1))
        cards = build_brand_payload()['cards']
        if 1 <= n <= len(cards):
            return cards[n - 1]['brand']
    # 纯序号（仅当明确在选品牌环节且文本就是裸序号/选N时才认，避免污染候选商铺选择）
    if allow_index_only:
        m = (re.search(r'选(?:第)?\s*(\d+)', text)
             or re.fullmatch(r'[（(]?(\d+)\s*号?[）)]?', text.strip()))
        if m:
            n = int(m.group(1))
            cards = build_brand_payload()['cards']
            if 1 <= n <= len(cards):
                return cards[n - 1]['brand']
    return None


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


# ---------------------------------------------------------------
# 「月流水 8.6 万」里的数字是**收入**，不是投入 —— 掩码保护
# ---------------------------------------------------------------
# 实测（2026-09-17）：`_parse_investment('月流水 8.6 万', strict=True)` 返回
# **86000**。原因是它的第 2 条规则「带单位 → 是投入」会把句子里**任何** "X万"
# 当成前期投入。于是已开店诊断里，用户只要报了流水而没提"前期投入"四个字，
# 投入就被悄悄读成月流水 → 摊销 86000/36≈2389 元/月混进月成本 → 净利与回本全错。
#
# 触发场景不是构造出来的：经营报表 / 一句话报数里
# "月流水 ×万、月租 ×万、前期投入 ×万" 三个万位数字并排出现是常态。
#
# 修法：先把**已被租金/流水抽取器认领**的片段挖成等长空格，再解析投入。
# 掩码复用 `agent.py` 里同一套 RENT_PATTERN / REVENUE_PATTERN /
# DAILY_REVENUE_PATTERN —— 绝不另写第二份"什么算流水"的定义（两份必然漂移）。
_MASK_PATTERNS = (REVENUE_PATTERN, DAILY_REVENUE_PATTERN)


def _mask_revenue_rent(text: str) -> str:
    """把已被"月租/月流水"认领的片段替换成**等长空格**（保持下标不变）。

    保持等长是为了不破坏下游按 `m.start()` 取的上下文（如"预算"触发词的
    前文判据 `text[:m.start()][-6:]`）。

    ⚠️ 租金这一支**刻意跳过「预算」**（`RENT_PATTERN` 的四个触发词之一）：
    「预算」在两个抽取器里是**两义**的 —— `extract_rent` 只在"不像投入"
    时才把它当租金，而"装修预算 20 万"里它恰恰就是投入。
    掩码若连它一起挖掉，投入就被挖没了（实测：`预算 12 万` → 投入读成 None）。
    所以这里只掩**无歧义**的 月租 / 租金 / 房租，`预算` 留给
    `_parse_investment` 与 `extract_rent` 各自按上下文判。
    """
    s = text or ''
    out, last = [], 0
    for m in RENT_PATTERN.finditer(s):
        if m.group(1) == '预算':
            continue
        out.append(s[last:m.start()])
        out.append(' ' * len(m.group(0)))
        last = m.end()
    out.append(s[last:])
    s = ''.join(out)
    for pat in _MASK_PATTERNS:
        s = pat.sub(lambda mm: ' ' * len(mm.group(0)), s)
    return s


# 前期投入的**命名口径**（strict 模式）。刻意不含裸的「成本」：
# 实测（2026-09-17）strict 下 `月成本 6.2 万`、`月流水 8.6 万`、`月租 1.2 万`
# 都会被读成前期投入，于是摊销 = 投入/36 混进月成本，净利与回本全错。
# strict 的语义是"用户有没有**明说**自己投了多少"，所以必须被写明；
# collect_invest 环节（strict=False）用户正在直接回答投入，才放宽。
_INVEST_NAMED = ('前期投入', '投入成本', '总投资', '开店投入', '投入资金',
                 '投资', '投入', '预算', '资金', '准备', '投')
# 非 strict 的宽松表：多认一个「成本」（用户可能就回一句"成本大概 20 万"）
_INVEST_LOOSE = _INVEST_NAMED + ('成本',)


def _parse_investment(text: str, strict=False) -> Optional[float]:
    """解析前期投入成本（元）。
    strict=True: 必须**写明**投入口径词（前期投入/投入/预算/资金…）才识别，
                避免把"月租8000""月流水8.6万""月成本6.2万"误当投入。
    strict=False: 允许裸数字（collect_invest 环节用户在直接回答投入）。

    ⚠️ 解析前先过 `_mask_revenue_rent`：收入与租金里的 "X万" **一律不算投入**
    （见该函数上方的事故记录）。掩码只挖掉"月租/月流水"这类**已带口径词**的
    片段，所以 collect_invest 里裸答的「12万」不受影响。
    """
    if not text:
        return None
    s = _mask_revenue_rent(text).strip()
    # 1) 明确前缀: 前期投入/投入成本/总投资/投资/投入/预算/成本/资金
    _trig = '|'.join(_INVEST_NAMED if strict else _INVEST_LOOSE)
    m = re.search(rf'(?:{_trig})[:：]?\s*(\d+(?:\.\d+)?)\s*(万元|万|w|w元|千|k|k元|元)?', s)
    if m:
        v = float(m.group(1))
        unit = m.group(2) or ''
        if unit and ('万' in unit or 'w' in unit.lower()):
            v *= 10000
        elif unit and ('千' in unit or 'k' in unit.lower()):
            v *= 1000
        return round(v)
    # 2) 带单位但**没有**口径词: "10万" "80k"
    #    ⚠️ 只在非 strict 模式下采信。strict 下"有万就算投入"会把
    #       `月流水 8.6 万` / `月成本 6.2 万` 一起读成前期投入（实测过），
    #       所以宁可不认（缺了会被追问），也不能认错（认错会静默算歪净利）。
    if not strict:
        m = re.search(r'(\d+(?:\.\d+)?)\s*(万元|万|w|千|k)\b', s)
        if m:
            v = float(m.group(1))
            unit = m.group(2)
            if '万' in unit or 'w' in unit.lower():
                v *= 10000
            elif '千' in unit or 'k' in unit.lower():
                v *= 1000
            return round(v)
        # 3) 裸数字（collect_invest 环节的直接回答）
        m = re.search(r'(\d{4,7})', s)
        if m:
            return int(m.group(1))
    return None


def _parse_price(text: str) -> Optional[float]:
    """解析「每单金额」（元）。

    口径（2026-09-15 定稿，见项目记忆）：客单价 = **每单金额**，
    不是单杯价（高德 `biz_ext.cost` 才是单杯价）。所以这里只认
    「每单金额 / 客单价 / 单均 / 每单 / 单笔」，**不认裸的"价格"**
    —— 免得把"单杯价 12 元"当成每单金额。
    """
    m = re.search(r'(?:每单金额|客单价|单均|每单|单笔金额|单笔)[^\d]{0,4}'
                  r'(\d+(?:\.\d+)?)\s*(?:元)?', text or '')
    if not m:
        return None
    v = float(m.group(1))
    return v if v > 0 else None


def _parse_daily_orders(text: str) -> Optional[int]:
    """解析「日单量」（单/天）。支持 "日单量 190 单" / "每天卖 190 杯"。

    ⚠️ 与 `DAILY_REVENUE_PATTERN`（日**流水**）是两回事：那个是金额×30 折月，
    这个是**单量**，必须配「每单金额」才能折月，由 `diagnose_node` 负责配对。
    """
    m = re.search(r'(?:日单量|日均单量|每日单量|每天|单量)[^\d]{0,6}?'
                  r'(\d+(?:\.\d+)?)\s*(?:单|杯|笔)', text or '')
    if not m:
        return None
    v = int(float(m.group(1)))
    return v if v > 0 else None


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


def ask_investment_message(category: str, brand: str = '') -> str:
    """询问前期投入 + 人数的提示文案。

    口径（2026-09-17 定稿，用户诉求④）：**含加盟费/保证金/设备/装修/首批物料，
    不含房租押金**。改造前这里写的是"含装修+设备+首批物料+转让等"——**没提加盟费**，
    而加盟费恰恰是加盟店投入里最硬的一项，用户按这句话填就会把它漏掉
    （实测漏掉蜜雪 1.1 万会让回本周期低估约 8%）。
    房租押金单列：它既不进月成本合计也不参与摊销，混进来会把净利算低。

    选了加盟品牌时，**把该品牌加盟费一并提示**出来，并说明它只是"最低兜底"、
    不是经营门槛 —— 蜜雪加盟费 1.1 万/年 vs 官方总投资 37 万起，差 30 多倍，
    不说清用户会以为 1.1 万就能开店。
    """
    from engine.utilities import get_default_staff
    default_staff = get_default_staff(category or '默认')
    lines = ['💰 最后确认一下，好把回本周期算准：',
             f'1️⃣ **前期投入成本**大概多少？'
             f'（**含加盟费/保证金/设备/装修/首批物料**，**不含房租押金**；'
             f'直接回复如「**12万**」或「**120000**」）']
    # 加盟品牌的加盟费门槛提示（诉求④）
    # 2026-09-18 三态改造：新增「明确不收加盟费」（如瑞幸）—— 旧代码 `if jf['fee']`
    # 会把 0 当成"没查到"，对瑞幸显示"暂无公开加盟费口径"，那是**假话**。
    if brand:
        try:
            from engine.brands import get_join_fee
            jf = get_join_fee(brand)
        except Exception:
            jf = None
        _notes = (jf or {}).get('cost_notes') or []
        if jf and jf.get('status') == 'none':
            lines.append(f'　　📌 你选的 **{brand}**：{jf["text"]}'
                         f'　→ 前期投入按下方的**总投入门槛**来报。')
            if jf.get('src'):
                lines.append(f'　　　口径来源：{jf["src"]}（公开参考，以品牌方最新政策为准）')
        elif jf and jf.get('fee'):
            lines.append(f'　　📌 你选的 **{brand}** 加盟费：{jf["text"]}'
                         f'　→ 前期投入**不能低于这个数**（低于我会先跟你确认）。')
            if jf.get('src'):
                lines.append(f'　　　口径来源：{jf["src"]}（公开参考，以品牌方最新政策为准）')
        elif jf:
            lines.append(f'　　📌 **{brand}** 暂无公开加盟费口径，'
                         f'这项不做下限校验（不编数据）。')
        # 品牌特有的"必须说出口"的成本/资质提示（不静默：不说 = 给了一份偏乐观的结论）
        for _n in _notes:
            lines.append(f'　　⚠️ {_n}')
    lines += [
        f'2️⃣ 运营**人数**：{category or "该品类"}默认按 **{default_staff} 人**算'
        f'（奶茶/甜品/早餐2人、便利店1人），需要调整就一起说，如「**12万 3人**」。',
        '（回复「你定」则由我按投入自动估算装修档次）',
    ]
    return '\n'.join(lines)


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
# 品牌选择卡片（奶茶品类，进入预算环节之前）
# ---------------------------------------------------------------
# 设计依据（见 docs/Huff线性回归完善方案.md 第三部分）：
#   · 品牌只有奶茶品类进入引擎（UPLIFT 同商圈溢价），其余品类恒为 1.0
#   · UPLIFT 分三级可信度 TIER1/TIER2/TIER3，卡片必须如实标注，
#     不能把 TIER2 的"参考值"当成和蜜雪同等的确定结论
#   · 品牌不提供选址服务的品牌才是本产品的目标用户，但不在此处做筛选
#     （用户可能已决定品牌，此处只负责如实告知与收集）
# ⚠️ 2026-09-18（UPLIFT v6 整表重标定）后已标定品牌 **9 → 27 个**，
#    旧的"总数 14 张"逻辑会算出 room = 14 − 27 = 0 → 无标定品牌**一张都进不来**
#    （甜啦啦/书亦烧仙草/茶颜悦色/7分甜… 共 14 个只能靠打字）。
#    这违背本函数的设计意图（无标定品牌本来就要留位子），故改为：
#      · **已标定品牌全在**（它们才是有数据支撑的、本产品的差异化价值）
#      · **无标定品牌固定保底若干席**，按品牌势能降序取
BRAND_UNLABELED_SHOW = 6        # 无标定品牌展示数（保底席位，不因已标定变多而被挤掉）


def _brand_cards() -> List[Dict]:
    """构造品牌候选卡片数据（本地表，0 次 API）。

    排序策略（重要，决定用户第一眼看到什么）：
      1. 有同商圈溢价标定的品牌（TIER1/TIER2）排在前面
         —— 这些品牌我们能给出真实数据支撑，是本产品的差异化价值所在
      2. 组内按 BRAND_S（品牌势能）降序
      3. 无标定的品牌（TIER3）垫后，并明确标注"暂无标定"
    不能按 BRAND_S 单纯降序：那样无标定的长尾品牌会混在头部，
    用户选了也拿不到任何品牌差异，等于卡片白给。
    """
    from engine.brands import (BRAND_S, UPLIFT, UPLIFT_TIER, UPLIFT_CI,
                               FRANCHISE_INFO, _UPLIFT_N)
    items = []
    for b, s in BRAND_S.items():
        tier = UPLIFT_TIER.get(b, 'TIER3')
        up = UPLIFT.get(b)
        ci = UPLIFT_CI.get(b)
        fi = FRANCHISE_INFO.get(b) or {}
        items.append({
            'brand': b,
            's': s,
            'uplift': round(up, 4) if up is not None else None,
            'tier': tier,
            'ci': [round(ci[0], 3), round(ci[1], 3)] if ci else None,
            'n': _UPLIFT_N.get(b),
            'invest_ref': fi.get('invest_ref'),
            'yearly_fee': fi.get('yearly_fee'),
        })
    # 已标定优先（0/1 键），再按品牌势能降序
    items.sort(key=lambda x: (0 if x['uplift'] is not None else 1, -(x['s'] or 0)))
    return items


def build_brand_payload() -> Dict[str, Any]:
    """kind='brands' 的工作台负载：已标定品牌 + 保底的无标定品牌 + 自创/杂牌逃生项。

    **已标定品牌全在**（v6 后为 27 个，它们才有数据支撑）；
    无标定品牌取前 BRAND_UNLABELED_SHOW 个（按品牌势能降序）——这是保底席位，
    不能因为"已标定变多了"就把无标定组整个挤掉（用户想做的品牌常常没标定）。
    """
    from engine.brands import (UPLIFT, UPLIFT_TIER, UPLIFT_CI, _UPLIFT_N)
    all_items = _brand_cards()
    calibrated = [c for c in all_items if c['uplift'] is not None]
    others = [c for c in all_items if c['uplift'] is None]
    others_show = others[:BRAND_UNLABELED_SHOW]
    cards = calibrated + others_show
    for i, c in enumerate(cards, 1):
        c['i'] = i
    # 逃生项：自创品牌 / 不加盟（UPLIFT 按"个体/杂牌"计）
    # ⚠️ tier/ci/n 必须**从表里取**，不能写死 —— 写死会在重标定后变成过期的假话
    #    （v6 后「个体/杂牌」已从 TIER2/n=7 变为 TIER1/n=557）。
    nxt = len(cards) + 1
    cards.append({
        'i': nxt, 'brand': '自创品牌', 's': 1.0,
        'uplift': round(UPLIFT.get('个体/杂牌', 1.0), 4),
        'tier': UPLIFT_TIER.get('个体/杂牌', 'TIER3'),
        'ci': (list(UPLIFT_CI['个体/杂牌']) if '个体/杂牌' in UPLIFT_CI else None),
        'n': _UPLIFT_N.get('个体/杂牌'),
        'invest_ref': None, 'yearly_fee': None,
        'self_created': True,
    })
    hidden = max(0, len(others) - len(others_show))
    hint = ('点卡片选择品牌（决定品牌引力与同商圈溢价系数）。'
            '带「已标定」的品牌由真实门店标定（口径是**同商圈内的相对水平**，'
            '不是流水倍数）；「—」表示暂无标定，会按中性 ×1.00 测算。')
    if hidden:
        hint += f'另有 {hidden} 个长尾品牌未列出，直接打字告诉我名字也行。'
    return {
        'kind': 'brands',
        'title': '你想加盟哪个奶茶品牌？',
        'hint': hint,
        'cards': cards,
        'category': '奶茶',
    }


def brand_ask_message() -> str:
    """询问品牌时的对话区文案（卡片在右侧工作台）"""
    return ('🧋 奶茶店的品牌不同，**吸客能力和同商圈内的流水水平差别不小**，'
            '所以要先确认一下你想做哪个牌子的加盟。\n'
            '请到**右侧工作台**点卡片选择（品牌溢价按真实门店标定，卡片上标注了可信度）；'
            '如果打算**自创品牌 / 不加盟**，选最后一张卡片即可。\n'
            '（也可以直接打字告诉我，如「蜜雪冰城」）')


# ---------------------------------------------------------------
# 节点 1：意图识别（规则提取，不调 LLM，0 次 API 请求）
# ---------------------------------------------------------------
async def classify_node(state: AgentState) -> Dict[str, Any]:
    """用规则判断用户意图，提取结构化信息。
    阶段语义：
    - intro        : 初始/闲聊，尚无任何信息
    - no_shop      : 找商铺（收集品类+地区 -> 搜索推荐），**不问租金**
    - have_shop    : 已有具体商铺（收集品类/地址/租金 -> 分析）
    - select_shop  : 等待用户从候选列表选择
    - collect_brand: 奶茶品类，等待选择加盟品牌（先于预算环节）
    - collect_invest: 等待前期投入/人数
    - shop_first   : 已有店铺但还没想好做什么，收集 地址/月租/面积
    - reverse_match: 四品类并联测算，反推推荐开什么店（奶茶再衔接品牌卡片）
    - analysis     : 信息齐备，进入评分
    - chat         : 自由问答（含用户手动开启的「自由对话」模式）
    """
    user_msg = state['messages'][-1]['content']

    # 需求 4：用户手动开启「自由对话」→ 直接短路，跳过所有选址流程判定
    if is_free_chat_mode():
        await _emit(state, 'think', '意图识别', '「自由对话」已开启 → 跳过选址流程判定，直接与大模型对话')
        return {'messages': state['messages'], 'phase': 'chat', 'missing_info': []}

    info = parse_request(user_msg)
    guest = extract_guest(user_msg)
    mode = extract_mode(user_msg)
    area = extract_area(user_msg)
    brand = extract_brand(user_msg)
    # 已开店诊断：月流水（用户自报）。与 rent 同理，抽不到就保留旧值。
    revenue = extract_monthly_revenue(user_msg)

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
        # 需求4：这里只认"明确的知识咨询"才转 chat，**不看 _looks_like_question**。
        # 因为用户在本环节常会边回答边追问（"大概20万吧，这个投入够吗？"），
        # 若整句带问号就转 chat，会丢掉他正在报的投入数字，流程卡住。
        if not _wants_start_flow(user_msg) and any(k in user_msg for k in _CONSULT_KEYWORDS):
            phase = 'chat'                          # 纯咨询 -> 自由对话
        elif has_specific or has_cat or has_addr or has_region or _wants_find(user_msg) or _wants_restart(user_msg):
            phase = 'have_shop' if has_specific else 'no_shop'   # 用户改主意/换需求
        else:
            phase = 'collect_invest'                # 正在答投入/人数
    # 2.55) 专家层 P1-2：正在做已开店诊断（收集 品类/月流水/月租）
    #       报数就继续留在 diagnose；纯提问（且没带流水数字）才转自由对话。
    elif prev_phase == 'diagnose':
        if _is_consulting(user_msg) and revenue is None:
            phase = 'chat'
        else:
            phase = 'diagnose'
    # 2.6) 需求 3：正在收集店铺三件套（地址 / 月租 / 面积）
    #      ⚠️ 必须保持 shop_first，交给 collect_shop_first_node 判"还缺什么"。
    #         否则会被下面的通用分支按品类词/地区词改写成 no_shop，
    #         图会走到 collect_info 而非 collect_shop_first，流程直接掉出去。
    elif prev_phase == 'shop_first':
        if _is_consulting(user_msg):
            phase = 'chat'
        else:
            phase = 'shop_first'
    # 2.65) 入口 B（新增）：正在收集"想在哪个地方开店"的地点
    #       用户在回答地点 -> 留在 place_first 交给节点处理（齐了就发候选检索）。
    elif prev_phase == 'place_first':
        if _is_consulting(user_msg):
            phase = 'chat'
        else:
            phase = 'place_first'
    # 2.7) 正在选择品牌（奶茶）
    elif prev_phase == 'collect_brand':
        # 需求4：问品牌加盟费/毛利/口碑等 -> 先回答，不要顺手把品牌定下来
        # （"蜜雪冰城加盟费多少？"会被 _parse_brand_choice 命中"蜜雪"而直接定品牌，
        #   用户的疑问被吞掉，体验很差）
        if not _wants_start_flow(user_msg) and any(k in user_msg for k in _CONSULT_KEYWORDS):
            phase = 'chat'
        elif _parse_brand_choice(user_msg) is not None or brand:
            phase = 'collect_brand'                 # 已给出品牌 -> 交给节点处理
        elif has_specific:
            phase = 'have_shop'                     # 改为分析具体商铺
        elif has_cat or has_addr or _wants_find(user_msg) or _wants_restart(user_msg):
            phase = 'no_shop'                       # 换品类/区域重新找
        elif _looks_like_question(user_msg):
            phase = 'chat'
        else:
            phase = 'collect_brand'                 # 继续等选品牌
    # 2.8) 需求 3：刚看完四品类推荐，用户选定方向 -> 直接分析他那个铺子
    #      复用已收集的地址/租金/面积，不再重复追问（奶茶会自然衔接品牌卡片）。
    elif prev_phase == 'reverse_match':
        if has_cat:
            phase = 'have_shop'                     # 选定品类 -> 分析这个铺位
        elif _wants_shop_first(user_msg) or _wants_restart(user_msg):
            phase = 'shop_first'                    # 换铺子 / 重新给信息
        elif _is_consulting(user_msg):
            phase = 'chat'
        else:
            phase = 'reverse_match'                 # 继续等选择
    # 2.85) 专家层 P1-2：已开店 + 报了经营数字 → 经营诊断（第三个互斥起点）。
    #       必须在 _wants_shop_first 之前（"我有个店，月流水8万"会同时命中它）。
    #       2026-09-18 扩展：有经营数据附件 + 只说"分析/诊断"（无选址信号）也进 diagnose，
    #       否则用户上传报表后说"开始分析"，专家会反问"月流水多少"而数据明明在附件里。
    elif (_wants_diagnose(user_msg)
          or (_wants_analyze_attached(state, user_msg)
              and not has_specific and not has_cat and not has_addr)):
        phase = 'diagnose'
    # 2.9) 入口 B（新增）：地点优先 —— 只有地点、没铺子、没想好品类。
    #      ⚠️ 必须排在通用分流之前（否则 has_addr 会把它推去 no_shop 反问品类）。
    #      ⚠️ 但**咨询闸门必须保留**：这是 2026-09-17 被 verify_flow_v2 抓到的一次真回退 ——
    #         我最初把这行放在闸门之前且不加 `_is_consulting`，
    #         于是「杭州开店租金什么水平？」（纯问行情）被判成"想开店" → place_first，
    #         用户会被塞一张候选铺源列表，而他问的只是行情。
    #         所以 `_wants_start_flow` 里补了「适合开店/能开店/开什么店」等意向词：
    #         它们让「滨江这边怎么样，适合开店吗」穿透闸门（修"吗"字误判），
    #         而「租金什么水平」不在其中 → 仍被闸门拦下 → chat。两者靠这几个词分开。
    #      与 2.9b 的 shop_first 分界只有一条：**手里到底有没有这个铺子**。
    elif _wants_place_first(user_msg) and not has_cat and not _is_consulting(user_msg):
        phase = 'place_first'
    # 2.9b) 需求 3：店铺优先分支 —— **有铺子**，但还没想好做什么
    #      必须在通用分流之前判定，否则会被 has_specific / has_cat 抢走。
    #      `not has_cat` 保证"有铺子 + 已想好品类"仍走 have_shop（用户已经想好了，
    #      不该被反问品类）。
    elif _wants_shop_first(user_msg) and not has_cat:
        phase = 'shop_first'
    # 3) 通用：触发了业务关键词 -> 按"有具体商铺/找商铺"分流
    elif has_specific:
        phase = 'have_shop'
    elif has_cat or has_addr or has_region or _wants_find(user_msg) or _wants_restart(user_msg):
        # 需求4：咨询闸门 —— 命中品类/地区词但实际在提问 -> 自由对话
        # 例："奶茶店毛利率一般多少？"、"便利店要办什么执照？"、"杭州开店租金什么水平？"
        if _is_consulting(user_msg):
            phase = 'chat'
        else:
            phase = 'no_shop'
    # 4) 没有触发任何关键词 -> 自动进入自由对话
    #    例外：正在收集品类/地区/租金，且用户在回答上一轮的问题（如"嗯""随便"）时保持追问
    elif prev_phase in ('no_shop', 'have_shop') and _awaiting_answer(state) and not _is_consulting(user_msg):
        phase = prev_phase
    else:
        phase = 'chat'

    # 清洗地址尾部（"杭州滨江的奶茶店" -> "杭州滨江"）
    # ⚠️ 需求3 例外：店铺优先阶段**保留含门牌的完整地址**。
    #    parse_request / _clean_area 都只到"区域"级，会把
    #    「杭州滨江江陵路 88 号」压成「滨江」→ geocode 只能拿区域中心点，
    #    实测测算精度差一大截。所以这里从原文重抽一次。
    addr = info.get('address') or state.get('address')
    if phase == 'shop_first':
        addr = _extract_full_address(user_msg) or addr
    elif addr:
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
        'brand': brand or state.get('brand'),
        'monthly_revenue': revenue if revenue is not None else state.get('monthly_revenue'),
        'phase': phase,
        'missing_info': [],
        'candidates': state.get('candidates', []),
        'pending_coord': state.get('pending_coord'),
        'selected_idx': state.get('selected_idx'),
        'list_shown': state.get('list_shown', False),
        'comparison': state.get('comparison'),
        'compare_pending': state.get('compare_pending', False),
        'shop_first_data': state.get('shop_first_data') or {},
        'category_recs': state.get('category_recs') or [],
        # 入口 B：地点优先开关。进入时置位，**用户一旦说出品类就收回**
        # （"我想在滨江开店" → True；之后"那我开奶茶吧" → has_cat → False，
        #   流程交回 A：按品类分析，而不是再反推四品类）
        'place_first_mode': (not has_cat) and (
            bool(state.get('place_first_mode')) or phase == 'place_first'),
        'rent_state': state.get('rent_state'),
        'area_state': state.get('area_state'),
        'rent_band': state.get('rent_band'),
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

    # 选品牌阶段：不在此追问（由 collect_brand 节点负责）
    if phase == 'collect_brand':
        return {'phase': 'collect_brand'}

    # 找商铺分支：**只收集地点，绝不问品类**（2026-09-17 用户诉求①）
    if phase in ('intro', 'no_shop'):
        if not state.get('address'):
            reply = ('好的，帮你找合适的商铺！只差一个信息：**想开在哪个区域？**'
                     '（如"杭州滨江""宁波鄞州"）\n'
                     '（先不用告诉我开什么 —— 我把这一带的在租铺源拉出来，'
                     '你挑中一家之后，我按奶茶/甜品/早餐/便利店各算一遍，'
                     '再告诉你这里开什么最赚。）')
            return {
                'messages': state['messages'] + [{'role': 'assistant', 'content': reply}],
                'missing_info': ['想开在哪个区域？（如"杭州滨江""宁波鄞州"）'],
                'phase': 'no_shop',
            }
        # 地点齐了 -> 直接搜候选。
        # ⚠️ 这里原来是 `if not category: missing.append('想开什么品类？')` ——
        #    用户诉求①抱怨的就是这一步："品类不该由我在前期自己选，那应该是你最后得出的结论"。
        #    现在改成：**没品类也照搜铺源**，并把 place_first_mode 置位，
        #    选中一家后直接进四品类反推。用户自己说了品类才走 A 流程。
        return {'phase': 'search_rental', 'missing_info': [],
                'place_first_mode': not state.get('category')}

    # "已有具体商铺"分支：问 地址 / 月租金（**同样不问品类**）
    # 用户直接用数字回答租金（如"8000""8000元"）时自动补上
    last_msg = _last_user_msg(state)
    rent_ans = None
    if state.get('rent') is None and state.get('category') and state.get('address'):
        m = re.fullmatch(r'\s*(\d{3,7})\s*(元|/月|每月|块)?\s*', last_msg)
        if m:
            rent_ans = int(m.group(1))

    missing = []
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

    rent_val = state.get('rent') if state.get('rent') is not None else rent_ans

    # 铺子有了但**没想好品类** -> 直接四品类反推（走 shop_first 的定位 + 反推链路）。
    # 改造前这里会追问"品类（奶茶/甜品/早餐/便利店）"，等于让用户在做选择题，
    # 而四品类反推存在的意义就是替他回答这个问题。
    if not state.get('category'):
        return {
            'phase': 'shop_first',
            'missing_info': [],
            'rent': rent_val,
            'shop_first_data': {'address': state.get('address'), 'rent': rent_val,
                                'area': state.get('area')},
        }

    # 已有具体商铺，信息齐备 -> 奶茶品类先问品牌，其余直接问前期投入/人数
    if _needs_brand_step(state):
        return {
            'phase': 'collect_brand',
            'missing_info': [],
            'rent': rent_val,
            'messages': state['messages'] + [{
                'role': 'assistant',
                'content': brand_ask_message(),
            }],
        }
    return {
        'phase': 'collect_invest',
        'missing_info': [],
        'rent': rent_val,
        'messages': state['messages'] + [{
            'role': 'assistant',
            'content': ask_investment_message(state.get('category', '')),
        }],
    }


# ---------------------------------------------------------------
# 节点 2.4：询问加盟品牌（仅奶茶品类; 放在预算环节之前）
# ---------------------------------------------------------------
def _needs_brand_step(state) -> bool:
    """是否需要先问品牌：奶茶品类 + 尚未确定品牌。"""
    if (state.get('category') or '') != '奶茶':
        return False
    return not state.get('brand')


async def collect_brand_node(state: AgentState) -> Dict[str, Any]:
    """奶茶品类：先确认加盟品牌（决定 UPLIFT 同商圈溢价系数），再进入预算环节。
    - 解析出品牌 -> 写入 brand，转入 collect_invest
    - 未解析出  -> 提示（品牌卡片由 UI 的 brands 块渲染），保持本轮结束等用户选
    """
    user_msg = _last_user_msg(state)
    brand = _parse_brand_choice(user_msg, allow_index_only=True)

    # 还没选 -> 只提示，卡片在右侧工作台
    if not brand:
        reply = ('请先选择加盟品牌（上面的候选卡片在**右侧工作台**）。'
                 '如果想自创品牌/不加盟，选最后一张卡片，或直接回复「自创品牌」。')
        return {
            'messages': state['messages'] + [{'role': 'assistant', 'content': reply}],
            'phase': 'collect_brand',
            'list_shown': True,
        }

    # 已选品牌 -> 记录并进入预算环节
    if brand == '自创品牌':
        detail = '自创品牌 / 不加盟（按"个体/杂牌"标定）'
    else:
        from engine.brands import UPLIFT, UPLIFT_TIER, UPLIFT_CI, _UPLIFT_N
        up = UPLIFT.get(brand)
        tier = UPLIFT_TIER.get(brand, 'TIER3')
        n = _UPLIFT_N.get(brand)
        ci = UPLIFT_CI.get(brand)
        if up is None:
            detail = f'{brand}（暂无同商圈溢价标定，按 1.0 中性处理）'
        else:
            tag = {'TIER1': '可信', 'TIER2': '参考值', 'TIER3': '样本不足'}.get(tier, tier)
            ci_txt = f'，区间 {ci[0]:.2f}~{ci[1]:.2f}' if ci else ''
            detail = (f'{brand}（同商圈溢价 ×{up:.3f}，{tag}'
                      f'{f"，n={n}" if n else ""}{ci_txt}）')

    await _emit(state, 'think', '确认加盟品牌',
                f'用户选择品牌「{brand}」→ {detail}\n'
                f'品牌将进入流水测算的溢价系数（竞争分不受品牌影响）')

    # ---- §6：franchise_advisor 的人设第一次真正进场 ----
    # 改造前 `collect_brand_node` 不调 LLM，唯一出加盟数字的路径用的是
    # **competitor_analyst 的人设**（人设错位）。这里把品牌结构数据交给
    # 加盟顾问自己的 persona 解读；数据取自 brands.py，LLM 只组织话术。
    _franchise_note = ''
    if brand != '自创品牌':
        _st = _Stage(state)
        _st.start('加盟顾问解读(LLM)')
        try:
            from engine.brands import (get_franchise_info, brand_store_metrics,
                                       brand_order_value, industry_price_reference)
            _facts = {'品牌': brand}
            _facts.update({k: v for k, v in (get_franchise_info(brand) or {}).items()})
            _m = brand_store_metrics(brand)
            if _m:
                _facts['公开经营数据'] = {k: v for k, v in _m.items() if v not in (None, '')}
            _ov = brand_order_value(brand)
            if _ov:
                _facts['每单金额'] = _ov
            _ind = industry_price_reference(brand)
            if _ind:
                _facts['第三方行业参考'] = _ind
            _franchise_note = await _expert_commentary('franchise_advisor', (
                f'用户已选定加盟品牌「{brand}」。系统内该品牌的结构化数据如下'
                f'（数字来自 brands.py，逐字引用，**禁止编造任何数字**；'
                f'没有的字段就是"系统内暂无"，如实说）：\n'
                f'{json.dumps(_facts, ensure_ascii=False, default=str)}\n\n'
                f'按你的角色，用要点式给出**加盟前必须知道的三件事**：'
                f'①前期投入口径（含哪些、不含哪些）②同商圈溢价系数及其可信度'
                f'③一条最容易踩的坑。数字全部取自上面的数据。'))
        except Exception:
            _franchise_note = ''
        finally:
            # finally：异常路径也要收账，否则这段耗时在 stage_ms 里凭空消失，
            # 恰恰把"最慢的那次"漏掉（§4 第 0 步的前提是账本完整）。
            _st.stop('加盟顾问解读(LLM)')
        if _franchise_note:
            await _emit(state, 'tool', '加盟顾问解读',
                        input_='品牌结构数据 → franchise_advisor 人设',
                        output=f'解读完成，{len(_franchise_note)} 字')
            await _st.emit_summary(state, '⏱ 阶段耗时（品牌确认轮）')

    return {
        'messages': state['messages'] + [{
            'role': 'assistant',
            'content': (f'✅ 已记录品牌：{detail}\n\n'
                        + (_franchise_note + '\n\n' if _franchise_note else '')
                        + ask_investment_message(state.get('category', ''))),
        }],
        'brand': brand,
        'in_franchise_note': _franchise_note,
        'phase': 'collect_invest',
    }


# ---------------------------------------------------------------
# 需求 3：店铺优先分支（先有铺子 -> 反推开什么店）
# ---------------------------------------------------------------
# 用户场景：铺子已经租下来了（或看好了），但还没想好做什么生意。
# 与 have_shop 的区别：have_shop 是"有铺子 + 已想好品类"，用户已经决定了，
# 不该被反问品类；本分支是"有铺子 + 没品类"。
REVERSE_CATEGORIES = ['奶茶', '甜品', '便利店', '早餐']

# ⚠️ 推荐度阈值是**人工设定**，没有外部权威依据，属经验值（文档已声明）。
REC_PAYBACK_FIRST = 24.0   # 首选：净利第 1 且回本 ≤ 24 个月
REC_PAYBACK_OK = 36.0      # 可选：回本 ≤ 36 个月


def shop_first_ask_message(missing: List[str]) -> str:
    """店铺优先分支的追问文案：缺什么问什么，一次问全。"""
    lines = [
        '好，我来帮你判断**这个位置更适合开什么店**。',
        '',
        '还需要你告诉我：',
    ]
    for m in missing:
        lines.append(f'- **{m}**')
    lines += [
        '',
        '一次说全就行，例如：',
        '「杭州滨江江陵路 88 号，月租 9000，面积 45 平米」',
        '',
        '（如果铺子还没定，告诉我想要的城市和区域，我帮你找在租铺位）',
    ]
    return '\n'.join(lines)


def _rec_label(rank: int, net, payback) -> str:
    """推荐度标签。阈值见 REC_PAYBACK_*，属人工经验值。"""
    if net is None or net <= 0:
        return '谨慎'
    if payback is None:
        return '可选' if rank == 1 else '谨慎'
    if rank == 1 and payback <= REC_PAYBACK_FIRST:
        return '首选'
    if payback <= REC_PAYBACK_OK:
        return '可选'
    return '谨慎'


def _rec_reason(rec: Dict[str, Any]) -> str:
    """从客群配套明细里生成一行适配理由（周边有什么）。"""
    parts = []
    for g in (rec.get('guest_details') or [])[:3]:
        cnt = g.get('count') or 0
        label = g.get('label') or ''
        if cnt > 0 and label:
            parts.append(f'{cnt} 个{label}')
    return ('周边 ' + '、'.join(parts)) if parts else ''


def build_category_rec_payload(recs: List[Dict]) -> Dict[str, Any]:
    """kind='category-rec' 的工作台负载。"""
    cards = []
    for r in recs or []:
        cards.append({
            'i': r.get('i'),
            'category': r.get('category'),
            'label': r.get('label', ''),
            'total': r.get('total'),
            'net': r.get('monthly_net'),
            'sales': r.get('monthly_sales'),
            'payback': r.get('payback'),
            'invest': r.get('invest'),
            'rent_share': r.get('rent_share'),
            'reason': _rec_reason(r),
            'error': r.get('error'),
        })
    return {
        'kind': 'category-rec',
        'title': '这个位置更适合开什么？',
        'hint': '按预估月净利排序。点卡片选一个方向，我立刻按你的铺子出具详细分析。',
        'cards': cards,
        'note': ('排序依据是预估月净利（绝对量纲，跨品类可比）。'
                 f'竞争分基于各品类独立口径——锚点仅奶茶有 {_anchor_sample_text()}标定，'
                 '其余品类沿用默认口径——**跨品类不可比**，仅供单品类内参考。'),
    }


def place_first_ask_message(missing: List[str]) -> str:
    """入口 B 的追问文案：只问地点，并说清"不用先想品类"。"""
    tips = {
        '地点': '想开在哪个地方？（如「杭州滨江」「宁波鄞州万达附近」「下沙大学城」）',
    }
    lines = ['还差：' + '、'.join(missing) + '。', '']
    lines += [f'· {tips[m]}' for m in missing if m in tips]
    lines += [
        '',
        '**不用先说做什么** —— 我先把这一带在租的铺子拉出来（带租金和面积），',
        '你挑中一家，我再按奶茶/甜品/早餐/便利店四个品类各算一遍，看这里开什么最赚。',
    ]
    return '\n'.join(lines)


async def collect_place_node(state: AgentState) -> Dict[str, Any]:
    """入口 B（2026-09-17）：地点优先 —— 只收「地点」，然后直接去搜在租铺源。

    ⚠️ 与 `collect_shop_first_node` 的关键差异：**不问租金和面积**。
    用户还没铺子，问了他也答不出来（这正是改造前的死胡同：实测
    「杭州下沙适合开什么店」被 shop_first 追问"月租多少"，流程卡死）。
    这里改成：地点 → 候选铺源（自带租金/面积）→ 选中 → 四品类反推。
    """
    addr = _clean_area(state.get('address') or '')
    category = state.get('category')
    if not addr:
        await _emit(state, 'think', '地点优先·信息收集', '还缺地点 → 追问一句（不问品类）')
        return {
            'messages': state['messages'] + [
                {'role': 'assistant', 'content': place_first_ask_message(['地点'])}],
            'phase': 'place_first',
            'missing_info': ['地点'],
            'candidates': [],
            'list_shown': False,
            'place_first_mode': True,
        }
    if category:
        # 用户顺口给了品类 -> 说明他已经想好了，交回 A 流程按品类找铺/分析，
        # 不再做四品类反推（反推的前提是"还没想好"）
        await _emit(state, 'think', '地点优先·转按品类处理',
                    f'用户已给出品类【{category}】→ 不再反推，按该品类找铺')
        return {'address': addr, 'phase': 'search_rental',
                'place_first_mode': False, 'missing_info': []}
    await _emit(state, 'tool', '地点优先·在租铺源检索',
                input_=f'地点「{addr}」（不带品类）',
                output='去 58 抓这一带的在租铺源：不看品类，先把铺子（含租金/面积）拉出来…')
    return {
        'address': addr,
        'phase': 'search_rental',
        'place_first_mode': True,
        'missing_info': [],
        'list_shown': False,
    }


async def collect_shop_first_node(state: AgentState) -> Dict[str, Any]:
    """需求 3：收集 地址 / 月租金 / 面积（缺什么问什么，一次问全）。
    三者齐备 -> geocode 定位 -> 转 reverse_match 做四品类测算。
    """
    prev = dict(state.get('shop_first_data') or {})
    address = state.get('address') or prev.get('address')
    rent = state.get('rent') if state.get('rent') is not None else prev.get('rent')
    area = state.get('area') if state.get('area') is not None else prev.get('area')

    missing = []
    if not address:
        missing.append('地址')
    if rent is None:
        missing.append('月租金')
    if area is None:
        missing.append('面积')

    d = {'address': address, 'rent': rent, 'area': area}

    if missing:
        await _emit(state, 'think', '店铺优先·信息收集',
                    f'已收到：{address or "—"} / 租金 {rent if rent is not None else "—"}'
                    f" / 面积 {area if area is not None else '—'}\n"
                    f'仍缺：{"、".join(missing)} → 继续追问')
        return {
            'messages': state['messages'] + [
                {'role': 'assistant', 'content': shop_first_ask_message(missing)}],
            'shop_first_data': d,
            'phase': 'shop_first',
            'missing_info': missing,
            'candidates': [],          # 清掉可能的旧候选，避免误渲染
            'list_shown': False,
        }

    # 三件套齐备 -> 定位一次
    # ⚠️ 优先用**原始地址**geocode，再退回 _clean_area 的清洗结果：
    #    _clean_area('杭州滨江江陵路 88 号') 会截断成 '滨江'，
    #    拿到的是区域中心点而不是铺位本身，精度差一大截。
    #    （_clean_area 本是为「杭州滨江的奶茶店」这类"区域+品类"输入设计的）
    clean_addr = _clean_area(address)
    candidates_addr = list(dict.fromkeys(
        [str(address).strip(), str(clean_addr).strip()]))
    await _emit(state, 'tool', '店铺优先·地址定位',
                input_=f'geocode「{candidates_addr[0]}」', output='定位中…')
    coord, used_addr = None, address
    for cand_addr in candidates_addr:
        if not cand_addr:
            continue
        try:
            coord = await asyncio.to_thread(geocode, cand_addr)
        except Exception:
            coord = None
        if coord and coord[0] is not None:
            used_addr = cand_addr
            break

    if not coord or coord[0] is None:
        msg = (f'「{address}」这个地址我没能定位到坐标。\n'
               '麻烦换个更明确的写法，比如「杭州市滨江区江陵路 88 号」'
               '或「宁波天一广场附近」。')
        return {
            'messages': state['messages'] + [{'role': 'assistant', 'content': msg}],
            'shop_first_data': d,
            'phase': 'shop_first',
            'missing_info': ['地址'],
        }

    lng, lat = coord
    d.update({'address': used_addr, 'lng': lng, 'lat': lat})
    await _emit(state, 'tool', '店铺优先·地址定位',
                input_=f'geocode「{used_addr}」',
                output=(f'定位成功 ({lng:.5f}, {lat:.5f}) —— '
                        f'后续需求池 D、竞争捕获 P 全部基于这个坐标计算'))

    return {
        'shop_first_data': d,
        'address': used_addr,
        'rent': rent,
        'area': area,
        'pending_coord': (lng, lat),
        'city': extract_city(used_addr) or extract_city(address) or state.get('city'),
        'phase': 'reverse_match',
        'missing_info': [],
        'candidates': [],
        'list_shown': False,
    }


def diagnose_ask_message(missing: List[str]) -> str:
    """已开店诊断的追问文案：只问缺的，并说清"要真数、不替你估"。"""
    tips = {
        '品类': '开的是什么店（奶茶 / 甜品 / 早餐 / 便利店）？',
        '月流水': '月流水（营业额）大概多少？只记得日单量的话，报「日单量 × 客单价」也行。',
        '月租金': '月租多少？这是你这店最大的一块固定支出，没有它算不出安全边际。',
    }
    lines = ['要诊断得先有真数 —— 还差：' + '、'.join(missing) + '。', '']
    lines += [f'· {tips[m]}' for m in missing if m in tips]
    lines += ['', '（流水是你店里的**实际数字**，我只做拆解，不替你估。）']
    return '\n'.join(lines)


async def diagnose_node(state: AgentState) -> Dict[str, Any]:
    """专家层 P1-2：已开店经营诊断（第三个互斥起点，见 README §4.3）。

    与 `analyze` / `reverse_match` 的根本区别 ——
      选址节点：**模型估**流水（Huff，含未标定的价格弹性假设）
      本节点：**用户自报**流水，模型不估（见 engine/store_diagnosis.py）
    ⇒ 这里不跑 Huff、不产选址分、不回答"能不能开"，只回答"现在哪里不对、还能跌多久"。
    也因此，选址侧那个"价格—单量弹性未标定"的不确定性在这里**根本不存在** ——
    流水是事实不是推断，本结论的不确定性远小于选址结论。

    人设固定用 `store_diagnosis_advisor`（与 negotiate/competitor 节点同款做法：
    节点职责本身就对应某位专家，不取决于用户是否手动选了他）。
    """
    user_msg = _last_user_msg(state)
    # ---- 解析源 = 用户这句话 + 上传附件正文（2026-09-17）----
    # 诉求：桌面上那份《店铺经营月报》填完**直接上传**给本专家，不该再把同样的数字手打一遍。
    # 改前只有 `free_chat_node`（专家问答）把附件正文拼进 system_msg，诊断节点只读
    # `user_msg` → 上传一张填好的报表会被当成"什么都没说"，然后反复追问流水，用户会以为
    # 系统读不了文件。这里把附件正文并进**规则抽取**的解析源（不是并进 LLM 上下文），
    # 于是报表里的 `月流水：…` / `月租金：…` 等口径词能直接被 `extract_*` 命中。
    # ⚠️ 无附件时 `_parse_src is user_msg`，逐字与改前一致 → 离线套件基准不变。
    _parse_src = user_msg
    _atts = state.get('attachments') or []
    if _atts:
        _attach_texts = [(a.get('text') or '').strip() for a in _atts[:2]]
        _attach_texts = [t for t in _attach_texts if t]
        if _attach_texts:
            _parse_src = user_msg + '\n' + '\n'.join(_attach_texts)
            await _emit(state, 'tool', '报表正文并入解析',
                        input_=f'附件：{_atts[0].get("name") or "附件"}',
                        output=(f'已把 {len(_attach_texts)} 份附件正文（合计 '
                                f'{sum(len(t) for t in _attach_texts)} 字）并入字段抽取源'))
    category = state.get('category') or extract_category(_parse_src)
    brand = state.get('brand') or extract_brand(_parse_src)
    # 报了已知品牌就不必再追问"开什么店"—— 品牌表（BRAND_KEYWORDS / brands.csv）
    # 收录的全是茶饮品牌，从品牌反推品类是查表不是编造。
    if not category and brand and brand != '自创品牌':
        category = '奶茶'
    revenue = state.get('monthly_revenue')
    if revenue is None:
        revenue = extract_monthly_revenue(_parse_src)
    # 「记不清月流水，只记得日单量 + 每单金额」→ 在这里折月。
    # persona 一直承诺"给单量和客单价我也能折算"、引擎 `diagnose_existing_store`
    # 也支持 `daily_orders × price × 30`，但**节点从来没把这两个参数接进来**，
    # 于是那句承诺是空话（用户照做只会被反复追问月流水）。
    # 折完只把结果递给引擎、**不传 price**：传 price 会把客单价口径从
    # 品类画像改成用户自报，那是口径变动（项目纪律：改口径要连提示词一起改），
    # 不在本次范围内。
    daily_orders = _parse_daily_orders(_parse_src)
    price = _parse_price(_parse_src)
    folded_from_orders = False
    if revenue is None and daily_orders and price:
        revenue = int(round(daily_orders * price * 30))
        folded_from_orders = True
    rent = state.get('rent')
    if rent is None:
        rent = extract_rent(_parse_src)
    area = state.get('area') or extract_area(_parse_src)
    city = state.get('city') or extract_city(_parse_src)
    # 人数与前期投入（2026-09-17 补齐）：改前这里只读 `state`，而 `state['staff']` /
    # `state['investment']` 只在 A 路径的 `collect_invest` 环节才写入 —— 走「已开店」
    # 这条路时它们**永远是 None**，于是引擎一路吃默认值（默认人数、`面积×4000+3万` 的
    # 估算投入），用户在报表里填的员工数和前期投入被静默丢掉：回本周期 = 投入/月净利，
    # 投入被换成估算值，回本那个数就整条不可信。
    # strict=True 的理由见 `_parse_investment` docstring：报表里写的是「前期投入：24 万」
    # 这种**带命名口径**的写法，必须写明才认，宁可不认也不能把"月流水 8.6 万"认成投入。
    staff = state.get('staff')
    if staff is None:
        staff = _parse_staff(_parse_src)
    investment = state.get('investment')
    if investment is None:
        investment = _parse_investment(_parse_src, strict=True)

    missing = []
    if not category:
        missing.append('品类')
    if revenue is None:
        missing.append('月流水')
    if rent is None:
        missing.append('月租金')

    carry = {'category': category, 'monthly_revenue': revenue, 'rent': rent,
             'area': area, 'brand': brand, 'city': city,
             # 早期版本这里不带 staff/investment：引擎吃到的是默认值，但 state 里仍为 None
             # → 下一轮追问/追问后的复算会在"用户已填"与"引擎用默认值"之间来回漂。
             # 抽出什么就回写什么，口径单一。
             'staff': staff, 'investment': investment}

    if missing:
        await _emit(state, 'think', '已开店诊断·信息收集',
                    f'已收到：{category or "—"} / '
                    f'月流水 {f"¥{revenue:,.0f}" if revenue is not None else "—"} / '
                    f'月租 {f"¥{rent:,.0f}" if rent is not None else "—"}\n'
                    f'仍缺：{"、".join(missing)} → 继续追问')
        return {
            'messages': state['messages'] + [
                {'role': 'assistant', 'content': diagnose_ask_message(missing)}],
            **carry,
            'phase': 'diagnose',
            'missing_info': missing,
            'candidates': [],      # 清掉可能的旧候选，避免误渲染
            'list_shown': False,
        }

    from engine.store_diagnosis import diagnose_existing_store
    _rev_src = (f'（按日单量 {daily_orders} × 每单 ¥{price:g} × 30 折算）'
                if folded_from_orders else '（用户自报）')
    await _emit(state, 'tool', '已开店诊断·成本拆解',
                input_=f'{category}｜月流水 ¥{revenue:,.0f}{_rev_src}｜'
                       f'月租 ¥{rent:,.0f}｜'
                       f'{area if area is not None else "默认"}㎡',
                output='拆成本 / 三种毛利口径 / 解安全边际 / 对标品牌公开基准…')
    try:
        diag = await asyncio.to_thread(
            diagnose_existing_store, category, revenue, rent,
            area_m2=area if area is not None else 30,
            city=city or '宁波',
            staff=staff,
            investment=investment,
            # '自创品牌' 不是可对标品牌 → 传 None，引擎便不产基准（错过就错过，不编）
            brand=brand if brand and brand != '自创品牌' else None,
        )
    except ValueError as e:
        msg = (f'这个数我不能用：{e}\n'
               '麻烦核对一下**月流水** —— 它是诊断的输入，得是正数。'
               '（如果你给的是日流水，写「日流水 3000」我会按 ×30 折月。）')
        return {'messages': state['messages'] + [{'role': 'assistant', 'content': msg}],
                **carry, 'phase': 'diagnose', 'missing_info': ['月流水']}

    # ---- RAG：按经营测算专家的分区检索（营销与运营 / 成本与政策）----
    kb_q = f'{category} 已开店 毛利率 外卖 成本 {brand or ""}'
    kb_txt = kb_context(kb_q, top_k=3,
                        tags=_expert_kb_tags('store_diagnosis_advisor'))
    system_msg = experts.compose_system_prompt('store_diagnosis_advisor', kb_text=kb_txt)
    llm_user = ('以下是引擎对这家**已开店**店铺的经营诊断数据。'
                '注意：月流水是用户自报的事实，不是模型预估。\n'
                + json.dumps(diag, ensure_ascii=False)
                + '\n\n请按你的输出契约向店主输出经营诊断。')

    await _emit(state, 'think', '生成经营诊断',
                '成本拆解完成，调用 LLM 生成口语化经营诊断（含营销调整建议）…')
    try:
        text = await call_llm(system_msg, llm_user, temperature=0.3, timeout=120)
        note = '火山方舟·豆包'
    except Exception as e:
        from agent.agent import rule_based_diagnosis
        text = (rule_based_diagnosis(diag)
                + f'\n\n[提示: LLM 暂不可用，已用引擎自带诊断文本。原因：{e}]')
        note = '规则诊断（LLM 暂不可用）'

    await _emit(state, 'tool', f'LLM 经营诊断（{note}）',
                input_='诊断数据 → 成本 / 毛利 / 安全边际 / 品牌对标的口语化解释',
                output=f'诊断完成，{len(text)} 字')

    context = (f"已开店诊断: {category} 月流水 ¥{revenue:,.0f} 月租 ¥{rent:,.0f} "
               f"毛利率 {diag.get('毛利率')} 净利率 {diag.get('净利率')} "
               f"安全边际率 {diag.get('安全边际率')}")

    return {
        'messages': state['messages'] + [{'role': 'assistant', 'content': text}],
        **carry,
        'store_diagnosis': diag,
        'interpretation': text,
        'context': context,
        'phase': 'chat',
        'missing_info': [],
    }


async def reverse_match_node(state: AgentState) -> Dict[str, Any]:
    """需求 3：四品类并联测算，反推这个铺位更适合开什么店。

    ⚠️ 排序口径只用「预估月净利」（绝对量纲，跨品类可比）。
       竞争分 / 总分**不可跨品类比较**：
         - P_REF 锚点只有奶茶被真实门店标定过（家数与口径见 `agent/model_facts.py`
           的实时块，**不要在这里写死数字**），
           甜品/便利店/早餐在 REF_DP/P_REF 里都取 '默认' 口径（= 奶茶的值），
           这是无依据的借用；
         - 四个品类的 POI 关键词不同 → 竞品基数不同 → P=A/(A+B) 绝对值不可比。
       所以竞争分照算、照展示，但**不参与排序**，并在卡片上明示。
    """
    d = state.get('shop_first_data') or {}
    address = d.get('address') or state.get('address') or ''
    rent = d.get('rent') if d.get('rent') is not None else state.get('rent')
    area = d.get('area') if d.get('area') is not None else state.get('area')
    lng = d.get('lng')
    lat = d.get('lat')
    if lng is None or lat is None:
        pc = state.get('pending_coord')
        if pc:
            lng, lat = pc

    if lng is None or lat is None or rent is None:
        reply = '抱歉，铺位信息不完整，麻烦重新说一次地址、月租金和面积。'
        return {
            'messages': state['messages'] + [{'role': 'assistant', 'content': reply}],
            'phase': 'shop_first',
        }

    # 租金口径（2026-09-17）：实测 / 推算 / 不可得，三者结论措辞必须不同。
    # 推算值**允许**参与排序（用户确认的口径），但必须在结论里显著标注，
    # 因为它会让净利/回本这些对租金敏感的数字带上系统性偏差。
    rent_state = state.get('rent_state') or 'measured'
    area_state = state.get('area_state') or 'measured'

    city = extract_city(address) or state.get('city')
    await _emit(state, 'tool', '四品类并联测算',
                input_=f'{address}（{ "、".join(REVERSE_CATEGORIES) }）月租 ¥{rent:,.0f}',
                output='本地 POI 库（浙江 4.4 万条）优先、高德实时补全，'
                       '逐品类跑 Huff 引力模型算 D×P…')

    recs = []
    for cat in REVERSE_CATEGORIES:
        try:
            r = await asyncio.to_thread(
                score_site, cat, lng, lat, rent, address, area,
                city=city, city_level=1.0,
            )
        except Exception as e:
            recs.append({'category': cat, 'error': f'{type(e).__name__}: {e}'})
            continue
        prof = r.get('profit') or {}
        ev = r.get('evidence') or {}
        recs.append({
            'category': cat,
            'total': r.get('total'),
            'verdict': r.get('verdict'),
            'dims': r.get('dims') or {},
            'monthly_sales': ev.get('预估月流水'),
            'monthly_net': prof.get('月净利估算'),
            'net_margin': prof.get('净利率'),
            'payback': prof.get('回本周期(月)'),
            'invest': prof.get('前期投入'),
            'rent_share': ev.get('租金占流水比'),
            'guest_details': r.get('guest_details') or [],
        })

    ok = [r for r in recs if r.get('monthly_net') is not None]
    ok.sort(key=lambda x: -(x.get('monthly_net') or 0))
    for i, r in enumerate(ok, 1):
        r['rank'] = i
        r['label'] = _rec_label(i, r.get('monthly_net'), r.get('payback'))
    errs = [r for r in recs if r.get('monthly_net') is None]
    ordered = ok + errs
    for i, r in enumerate(ordered, 1):
        r['i'] = i

    top = ordered[0] if ordered else None
    if top and top.get('monthly_net') is not None:
        net = top['monthly_net']
        pb = top.get('payback')
        pb_txt = f'、回本约 {pb:.0f} 个月' if isinstance(pb, (int, float)) else ''
        chat_msg = (
            f'我把「{address}」按 4 个品类各算了一遍（月租 ¥{rent:,.0f}、面积 {area}㎡）。\n\n'
            f'净利最高的方向是 **{top["category"]}**：'
            f'预估月净利 ¥{net:,.0f}{pb_txt}。\n\n'
            '完整对比在**右侧工作台**，点卡片选一个方向，我立刻按你的铺子出具详细分析。'
        )
    else:
        chat_msg = (
            f'「{address}」四个品类都跑了，但都没能算出可用的净利（可能是地址过偏或数据不足）。\n'
            '可以把铺位地址说得更具体一些，我再算一次。'
        )

    # 口径声明：推算值必须显著标注（用户确认口径）——
    # 排序允许用推算租金，但**不能让用户以为这是实测**。
    _dia = []
    if rent_state == 'derived':
        band = state.get('rent_band') or (None, None)
        band_txt = f'（同区参考带 ¥{band[0]:,}~{band[1]:,}/月）' if band and band[0] else ''
        _dia.append(f'⚠️ **本次月租 ¥{rent:,.0f} 是推算值**{band_txt}，'
                    '不是这套铺子的实际挂牌价。推算口径来自同区在租挂牌参考带'
                    '（P25~P75 元/㎡/月，粒度到行政区不到商圈）——'
                    '**排序结论可用，但金额本身有系统性偏差，回本周期尤其敏感**。'
                    '报一个实际月租我可以换成实测口径重算。')
    if area_state == 'derived':
        _dia.append(f'⚠️ 面积 {area}㎡ 同样是推算值（非实测）。')
    if _dia:
        chat_msg = chat_msg + '\n\n' + '\n'.join(_dia)

    await _emit(state, 'tool', '四品类测算完成',
                output='四品类月净利预估：' + ' / '.join(
                    f"{r['category']} "
                    + (f"¥{r['monthly_net']:,.0f}" if r.get('monthly_net') is not None else 'n/a')
                    for r in ordered))

    # ---- §6：category_reverse 的人设第一次真正进场 ----
    # 改造前这位专家的 persona 从未进过任何 prompt（节点纯引擎 + 模板文案），
    # 于是"选品类反推师"与"不选"完全一样。这里把引擎排序结果交给它解读：
    # 事实（四个数字）来自引擎，口吻与行动建议来自它的人设。
    _rows = [{'品类': r.get('category'), '月流水': r.get('monthly_sales'),
              '月净利': r.get('monthly_net'), '净利率': r.get('net_margin'),
              '回本(月)': r.get('payback'), '租金占流水比': r.get('rent_share'),
              '地址评分': r.get('total'),
              '竞争分': (r.get('dims') or {}).get('竞争压力'),
              '结论': r.get('verdict'), '推荐标签': r.get('label')}
             for r in ordered]
    # 数据口径必须原样交给专家：租金是推算值时，解读里必须带出来，
    # 不能让"净利最高是奶茶"读起来像实测结论。
    _rent_caliber = ('实测（平台挂牌价）' if rent_state == 'measured'
                     else '**推算**（同区挂牌参考带 P25~P75 元/㎡/月，非该铺实际报价）')
    _area_caliber = '实测' if area_state == 'measured' else '**推算**'
    _comment = await _expert_commentary('category_reverse', (
        f'引擎对同一个铺位（{address}，月租 ¥{rent:,.0f}［口径：{_rent_caliber}］，'
        f'面积 {area}㎡［口径：{_area_caliber}］，'
        f'城市 {city or "未定"}）按 4 个品类**并联测算**，真实结果如下'
        f'（数字来自引擎，逐字引用，禁止改动、禁止新增任何数字）：\n'
        f'{json.dumps(_rows, ensure_ascii=False, default=str)}\n\n'
        f'请按你的角色输出「这个铺位更适合开什么」的解读：按【预估月净利】降序讲；'
        f'每项给月流水/月净利/净利率/回本/租金占比；'
        f'明示竞争分与总分**跨品类不可比、不参与排序**；'
        f'声明推荐度阈值是人为经验值；'
        + ('**必须在结论里显式声明月租/面积为推算值，回本周期对租金敏感、偏差会被放大**；'
           if rent_state != 'measured' or area_state != 'measured' else '')
        + f'最后给出选中一个品类后的下一步。'))
    if _comment:
        chat_msg = chat_msg + '\n\n' + _comment
        await _emit(state, 'tool', '品类反推师解读',
                    input_='4 品类测算表 → category_reverse 人设',
                    output=f'解读完成，{len(_comment)} 字')

    return {
        'messages': state['messages'] + [{'role': 'assistant', 'content': chat_msg}],
        'category_recs': ordered,
        'phase': 'reverse_match',
    }


# ---------------------------------------------------------------
# 节点 2.5：收集前期投入（选好商铺后 -> 问投入+人数 -> 再分析）
# ---------------------------------------------------------------
# 加盟费下限（2026-09-17，用户诉求④确认口径：**下限取单列加盟费，显示后放行**）
# ⚠️ 为什么是"放行"而不是"拦截"：加盟费只是品牌授权费，真实开店投入还含
#    保证金/设备/装修/首批物料，用户完全可能报出一个低于加盟费的数（比如
#    他打算用二手设备、或者把加盟费算在别处）。硬拦会把他的真实情况挡在门外，
#    所以我们**提示 + 要求显式确认**，确认了照算 —— 不撒谎，也不挡死。
_CONFIRM_WORDS = ['确认', '确定', '就按', '就这样', '按这个', '继续', '没问题',
                  '明白', '知道了', '懂了', '接受', '是的', '没错']


def _join_fee_floor(brand: str):
    """取该品牌的加盟费下限（元）与给用户看的说明。无下限 -> (None, '')。

    ⚠️ "无下限"有**两个来源，必须分清**（2026-09-18）：
      · status='unknown' —— 查不到公开口径 ⇒ 不知道下限，不编，故不校验；
      · status='none'    —— **明确不收加盟费**（瑞幸）⇒ 下限**本就不适用**。
    两者返回值相同（都是无下限），但**理由完全相反**。这里刻意不区分，
    因为对"要不要拦住用户"而言结论一致。
    ⚠️ 但**给用户看的那句话**（`collect_invest_node` / 投入表单 note）**必须区分**：
    对瑞幸说"暂无公开口径"是假话 —— 那句文案在别处，不要顺手拿这里的返回值去拼。
    """
    if not brand:
        return None, ''
    try:
        from engine.brands import get_join_fee
        jf = get_join_fee(brand)
    except Exception:
        return None, ''
    if not jf or not jf.get('fee'):
        return None, ''
    return int(jf['fee']), jf.get('text') or ''


def _is_floor_confirm(text: str) -> bool:
    """用户是否在**明确确认**"就按我报的投入算"（低于加盟费时的放行条件）。

    ⚠️ 长度上限 20 字不是随手写的：不限长就会把
    「确认，但我想问下这个租金合理吗，周边还有没有别的选择」这种
    **顺口带个"确认"的长句**也当成放行，校验等于形同虚设。
    """
    t = (text or '').strip()
    if not t or len(t) > 20:
        return False
    return any(k in t for k in _CONFIRM_WORDS)


async def collect_invest_node(state: AgentState) -> Dict[str, Any]:
    """选好铺子后，询问前期投入成本与运营人数。
    投入已给出 -> 人数默认(奶茶/甜品/早餐2人、便利店1人) -> 进入分析。
    回复"你定/默认" -> 按面积兜底估算投入后进入分析。
    投入低于所选品牌的加盟费 -> **提示并要求显式确认**，确认后照算（不硬拦）。"""
    from engine.utilities import get_default_staff
    category = state.get('category', '')
    invest = state.get('investment')
    staff = state.get('staff')
    last = _last_user_msg(state)

    # 兜底：奶茶品类若还没定品牌，先回到选品牌（不在预算后面追问，顺序必须在前）
    if _needs_brand_step(state):
        return {'phase': 'collect_brand'}

    # 投入未给出：继续收集（本轮先提示/引导）
    if invest is None:
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

    # ---- 加盟费下限软校验（诉求④：显示后放行）----
    floor, floor_txt = _join_fee_floor(state.get('brand'))
    if floor and invest < floor and not _is_floor_confirm(last):
        await _emit(state, 'think', '前期投入·加盟费下限',
                    f'{state.get("brand")} 加盟费 ¥{floor:,} '
                    f'> 用户报的投入 ¥{invest:,.0f} → 提示并等确认（不硬拦）')
        return {
            'investment': invest,
            'staff': staff,
            'phase': 'collect_invest',
            'messages': state['messages'] + [{
                'role': 'assistant',
                'content': (
                    f'⚠️ 你填的前期投入 **¥{invest:,.0f}** 低于 **{state.get("brand")}** 的加盟费：\n'
                    f'　　{floor_txt}\n\n'
                    f'**加盟费是单独一项，不含保证金/设备/装修/首批物料** ——'
                    f'这两个数差这么多，通常是漏了某一块（或是打算用二手设备/接手转店）。\n\n'
                    f'· 如果确实按这个数算（用二手设备、或加盟费你另有安排）→ 回复「**确认**」，我照算；\n'
                    f'· 如果要修正 → 直接回一个新数字，如「**35万**」。\n'
                    f'（我不会偷偷帮你改数，也不会因为这个拦着不让你算。）'),
            }],
        }

    # 投入已给出 -> 人数默认 -> 进入分析
    staff = staff or get_default_staff(category)
    invest_txt = f"{invest:,}"
    floor_note = ''
    if floor:
        floor_note = (f'（{state.get("brand")} 加盟费 ¥{floor:,} 已含在该投入内）'
                      if invest >= floor else '（低于加盟费，已确认按此口径）')
    return {
        'staff': staff,
        'phase': 'analysis',
        'messages': state['messages'] + [{
            'role': 'assistant',
            'content': f'💰 收到：前期投入 **{invest_txt} 元**，运营按 **{staff} 人**测算'
                       f'（{category}默认{get_default_staff(category)}人）。{floor_note}正在为您分析…',
        }],
    }


# ---------------------------------------------------------------
# 节点 3：候选搜索（找商铺分支，尽量少 API 请求）
# ---------------------------------------------------------------
# ---------------------------------------------------------------
# 节点 3：候选搜索（找商铺分支，尽量少 API 请求）
# ---------------------------------------------------------------
# 2026-09-17 扩量：候选数量常量集中在这里，A 流程（先定品类）与
# 入口 B（地点优先）**共用**这套上限 —— 用户要求"两处都要增加可选店铺数量"，
# 而这两条路走的是同一个节点，所以只改这一处。
CAND_TOTAL = 15            # 最终展示的候选数（用户确认：抓 60 / 展示 15）
# 候选池上限：58 抓到的条目都先收进来，再交给 `_rank_candidates` 挑最好的 15 个。
# ⚠️ 这个池必须 ≥ CAND_TOTAL，否则"排序"就退化成"按抓取顺序取前 N 个"
#    —— 用户点的前几家可能恰好是缺面积/缺租金的。改造前这里写死 12，
#    是因为剩下的缺口由高德/本地库兜底补齐；那两级兜底已在 2026-09-17 删除
#    （用户诉求②：兜底 POI 不是房源），所以池子必须自己开够。
CAND_POOL = 40
RENTAL58_LIMIT = 60        # 58 抓取条数上限（用户确认：抓 60）
RENTAL58_PAGES = 3         # 58 PC 列表翻页数
RENTAL58_MOBILE = True     # 并入移动端（另一套条目集合）
# 详情页补全：只对"缺面积/缺定位线索"的条目再开一次详情页取参数区。
# 这是需求④"有些店铺只有区域定位而且没有面积和租金"的直接落地；
# 代价是 +4~7s（逐条一次导航），所以条数与时间都给了硬上限，超了就放弃补全。
RENTAL58_DETAIL = True
RENTAL58_DETAIL_MAX = 12
RENTAL58_DETAIL_BUDGET = 7.0
PRECISE_BUDGET = 10        # 精确 geocode 预算（次，省高德配额）


def _cand_completeness(c) -> float:
    """候选的字段完整度（用于排序，不用于过滤）。"""
    s = 0.0
    if c.get('area'):
        s += 1.0
    if c.get('price'):
        s += 1.0
    if c.get('precise'):
        s += 1.0
    if c.get('img'):
        s += 0.5
    return s


def _rank_candidates(cands, target_lng, target_lat):
    """按「字段完整度 → 距区域中心」排序后截断到 `CAND_TOTAL`。

    ⚠️ 为什么不是简单截断前 15 个：扩容后 58 返回的条目里混着"只有区域定位、
    没有面积租金"的（实测缺面积 ~10%，兜底条目则是全缺）。若按抓取顺序截断，
    用户点前几个就可能全是算不了的铺子，扩容反而更差。
    所以先按"能算出多少"排，**缺字段的不丢弃、只排后面**（仍可点，卡片如实标注）。
    """
    for c in cands:
        try:
            c['_dist'] = (haversine(target_lng, target_lat, c['lng'], c['lat'])
                          if target_lng is not None else 0)
        except Exception:
            c['_dist'] = 0
    cands.sort(key=lambda c: (-_cand_completeness(c), c.get('_dist') or 0))
    kept = cands[:CAND_TOTAL]
    for i, c in enumerate(kept, 1):
        c['i'] = i
        c.pop('_dist', None)
    return kept


def _fill_field_states(cands, shops, scope_label, category=None):
    """给每个候选标注「租金/面积」的**数据可信度三态**，缺的按层级补。

    三态（用户确认的口径：缺租金一律不出经营评分）：
      measured    = 平台实测（58 列表）
      derived     = 推算（同区挂牌参考带 / 品类标准面积）→ 可参与排序，但必须显著标注
      unavailable = 不可得 → **不出经营评分**，禁止静默用默认 ¥8000

    ⚠️ 推算用的参考带来自**同一次抓取的样本**（`band_from_samples`），
    不再额外抓一次 58：既省时间，也保证"参照样本"与"候选列表"是同一时间点的同一批条目。
    """
    need_rent = any(c.get('price') in (None, 0) for c in cands)
    need_area = any(not c.get('area') for c in cands)
    bench = None
    if (need_rent or need_area) and shops:
        try:
            from engine.negotiation import band_from_samples
            bench = band_from_samples(shops, scope=scope_label)
        except Exception:
            bench = None
    prof = {}
    if category:
        try:
            prof = get_profile(category) or {}
        except Exception:
            prof = {}
    for c in cands:
        # ---- 面积 ----
        if c.get('area'):
            c['area_state'] = 'measured'
            c['area_source'] = '58列表' if '58' in str(c.get('source')) else '平台实测'
        else:
            a = prof.get('area_ideal')
            if a:
                c['area'] = a
                c['area_state'] = 'derived'
                c['area_source'] = f'{category}品类标准面积'
            elif bench:
                c['area'] = int(bench['中位面积'])
                c['area_state'] = 'derived'
                c['area_source'] = f'同区样本中位面积(n={bench["样本数"]})'
            else:
                c['area_state'] = 'unavailable'
                c['area_source'] = None
        # ---- 租金 ----
        if c.get('price'):
            c['rent_state'] = 'measured'
            c['rent_source'] = '58列表' if '58' in str(c.get('source')) else '平台实测'
        elif bench and c.get('area'):
            lo, hi = bench['参考带']
            c['price'] = int(round(bench['中位单价'] * c['area']))
            c['rent_band'] = (int(round(lo * c['area'])), int(round(hi * c['area'])))
            c['rent_state'] = 'derived'
            c['rent_source'] = f'同区挂牌参考带推算(P25~P75, n={bench["样本数"]})'
        else:
            c['rent_state'] = 'unavailable'
            c['rent_source'] = None
        c['evidence_at'] = (bench or {}).get('抓取时间') or ''
        # 定位精度分级（2026-09-17 诉求②）：四级如实标，**不假装精确**。
        # 卡片据此显示"门牌级/楼宇级/街区级/区域级"，区域级额外提示"无门牌"。
        c['addr_level'] = c.get('addr_level') or ('door' if c.get('precise') else 'area')
        c['geo_state'] = 'precise' if c['addr_level'] in ('door', 'building') else 'area_level'
    return cands


def cand_state_brief(cands) -> str:
    """一句话说清本批候选的数据可信度构成（给用户看）。"""
    m = sum(1 for c in cands if c.get('rent_state') == 'measured' and c.get('area_state') == 'measured')
    d = sum(1 for c in cands if c.get('rent_state') == 'derived' or c.get('area_state') == 'derived')
    u = sum(1 for c in cands if c.get('rent_state') == 'unavailable' or c.get('area_state') == 'unavailable')
    parts = [f'{m} 家租金+面积均为实测']
    if d:
        parts.append(f'{d} 家含推算值（已标注）')
    if u:
        parts.append(f'{u} 家缺租金或面积（不出经营评分）')
    return '；'.join(parts)


def area_filter_of(area: str, city: str = '') -> str:
    """候选检索用的区域过滤词（去掉城市前缀）。与 search_rental 内部保持一致。"""
    a = area or ''
    for c in CITY_CODES:
        if a.startswith(c):
            return a[len(c):]
    return a


async def search_rental_node(state: AgentState) -> Dict[str, Any]:
    """搜索区域真实在租商铺（58同城多页并发抓取；**不再有兜底点位**）。

    2026-09-17 扩量改造：
    - 58 抓取 10 → 60 条，翻 3 页并**并入移动端**（实测是另一套条目集合）
    - 候选池 40 → 按「字段完整度 → 距离」排序截断到 15（CAND_TOTAL）
    - 每个候选带「租金/面积」三态标注（实测/推算/不可得）+ 房源性质（出租/转让）
      + 定位层级（门牌/楼宇/街区/区域）

    2026-09-17 第二轮（用户诉求②）：**删除高德 POI 与本地库两级兜底**。
    这两级返回的是"在营店铺/商圈点位"而不是"在租房源"，没有租金也没有面积，
    凑数只会让用户点进"算不了"的条目。真房源不足 15 家时如实说明不足。

    API 优化（保持）：
    - 区域中心只 geocode 一次；无精确路名的候选直接回落区域中心（0 次额外调用）
    - 精确 geocode 预算上限（PRECISE_BUDGET 次），省高德配额
    """
    area = _clean_area(state.get('address') or '')
    category = state.get('category', '')
    city = extract_city(area)
    place_mode = bool(state.get('place_first_mode'))

    # §4 第 0 步：这一段改造前**没有埋点**，而它恰好是"第一次问地址"那一轮的
    # 全部耗时（实测 8.4s：geocode + 58 抓取 + 逐个候选精确 geocode）。
    # 没账本就没法判断该不该优化它，所以补上。
    _st = _Stage(state)

    candidates = []
    seen = set()

    # 区域中心坐标：只 geocode 一次（1 次高德调用）
    target_lng, target_lat = (None, None)
    if area:
        _st.start('地址定位(geocode)')
        target_lng, target_lat = geocode(area)
        _st.stop('地址定位(geocode)')
        await _emit(state, 'tool', '地址定位',
                    input_=f'定位「{area}」',
                    output=f'坐标 ({target_lng:.5f}, {target_lat:.5f})（优先本地库，0~1 次高德调用）'
                    if target_lng else f'「{area}」定位失败')

    def add_cand(name, address, lng, lat, source, area_m2=None, price=None, precise=False,
                 img=None, deal='', addr_level='area'):
        key = (name, round(lng, 4), round(lat, 4))
        if key in seen:
            return
        seen.add(key)
        candidates.append({
            'name': name, 'address': address,
            'lng': lng, 'lat': lat, 'source': source,
            'area': area_m2, 'price': price, 'precise': precise,
            'img': img,
            # 房源性质：'出租'（房东招租）/ '转让'（别人转店）/ ''（判不出）
            'deal': deal,
            # 定位层级：door / building / street / area —— 卡片按级显示
            'addr_level': addr_level,
        })

    shops, fetch_meta = [], {}
    area_filter = area_filter_of(area, city)
    # 第 1 轮：58 同城真实在租商铺（多页并发；硬时限兜底，避免用户无限等待）
    _st.start('58抓取+候选定位')
    if city and target_lng:
        precise_budget = PRECISE_BUDGET  # 精确坐标 geocode 预算（次）；标题含大厦/广场名可辅助精确定位
        t0 = time.monotonic()
        search_timeout = False
        try:
            try:
                shops = await asyncio.wait_for(
                    asyncio.to_thread(fetch_shops, city, RENTAL58_LIMIT, 25,
                                      area_filter or None, RENTAL58_PAGES,
                                      RENTAL58_MOBILE, 12.0, fetch_meta,
                                      detail=RENTAL58_DETAIL,
                                      detail_max=RENTAL58_DETAIL_MAX,
                                      detail_budget_s=RENTAL58_DETAIL_BUDGET),
                    timeout=40,
                )
            except asyncio.TimeoutError:
                shops = []
                search_timeout = True
            # ⚠️ 先按"信息量"排一遍再烧 geocode 预算：
            #    扩容到 60 条后，预算只够定位 10 个，
            #    不排序就会把预算花在前几条恰好没地标名的条目上。
            shops = sorted(
                shops,
                key=lambda s: (0 if s.get('area') else 1,
                               0 if (s.get('title') or '') else 1))
            for s in shops:
                if time.monotonic() - t0 > 45:
                    search_timeout = True
                    break
                if len(candidates) >= CAND_POOL:
                    break
                lng, lat, precise = None, None, False
                # 定位层级（2026-09-17）：用户诉求②明确问"有些又是区域级定位 没有具体的地址"，
                # 所以要如实记下**这一条最终是按哪一级定位的**，并在卡片上分级显示。
                # 四级：门牌 > 楼宇 > 街区 > 区域。区域级必须显式标"无门牌"，
                # 不能让它看起来跟门牌级一样精确。
                lvl = 'area'
                title_text = (s.get('title') or '').replace(' ', '')
                loc_text = (s.get('loc') or '').replace(' ', '')
                # 0) 详情页给的详细地址优先（2026-09-17 新增）—— 这是阶梯里最权威的一条：
                #    列表页只有"滨江-四桥南"这种区域级位置，详情页才有门牌号。
                #    成功即直接用，省下后面 3 次试探。
                if s.get('detail_addr') and precise_budget > 0:
                    lng, lat = geocode(f'{city}{s["detail_addr"]}')
                    if lng:
                        precise_budget -= 1
                        precise = True
                        lvl = 'door'
                # 1) loc/标题里的"XX路XX号"等完整地址（1 次 geocode）
                if lng is None:
                    m_addr = re.search(
                        r'([\u4e00-\u9fa5]{1,10}(?:路|街|道|巷|弄|大道)[\u4e00-\u9fa5A-Za-z0-9]*\d*号?)',
                        loc_text + title_text,
                    )
                    if m_addr and precise_budget > 0:
                        lng, lat = geocode(f'{city}{m_addr.group(1)}')
                        if lng:
                            precise_budget -= 1
                            precise = True
                            # 带门牌号才算 door，只有路名算 street
                            lvl = 'door' if re.search(r'\d+\s*号', m_addr.group(1)) else 'street'
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
                            lvl = 'building'
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
                                lvl = 'street'
                # 4) 其余回落区域中心（0 次额外 API）
                if lng is None:
                    lng, lat = target_lng, target_lat
                    lvl = 'area'
                if not _in_zhejiang(lng, lat):
                    continue
                if haversine(target_lng, target_lat, lng, lat) > 30000:
                    continue
                # 地址展示：标题 + 位置合并（标题通常含楼宇名，比 loc 更具体）
                show_addr = f'{title_text}（{loc_text}）' if loc_text and title_text else (title_text or loc_text or area)
                add_cand(s['title'], show_addr, lng, lat, '58同城(在租)',
                         area_m2=s.get('area'), price=s.get('price'), precise=precise,
                         img=s.get('img'), deal=s.get('deal') or '', addr_level=lvl)
        except Exception:
            pass
        # 取数失败 vs 真的没有：meta 里 ok=False 才算失败，两者文案必须不同
        if search_timeout:
            fetch_txt = '58 抓取超时，改用其他来源兜底'
        elif fetch_meta.get('ok') is False:
            fetch_txt = f'58 取数失败（{fetch_meta.get("reason") or "反爬/网络"}），改用其他来源兜底'
        else:
            pages = len(fetch_meta.get('pages') or [])
            fetch_txt = (f'抓取到 {len(shops)} 条在租商铺（{pages} 个页面并发，'
                         f'原始卡片 {fetch_meta.get("raw", 0)} 张，耗时 {fetch_meta.get("elapsed_s")}s）')
            _dm = fetch_meta.get('detail') or {}
            if _dm:
                if _dm.get('targets'):
                    fetch_txt += (f'；详情页补全 {_dm.get("filled", 0)}/{_dm.get("targets")} 条'
                                  f'（只为"缺面积/缺定位线索"的条目多抓一次，'
                                  f'{_dm.get("elapsed_s")}s）')
                elif _dm.get('reason'):
                    fetch_txt += f'；详情页补全跳过（{_dm["reason"]}）'
        await _emit(state, 'tool', '58同城·实时在租抓取',
                    input_=f'{city}「{area_filter or "全区"}」'
                           + ('（不带品类）' if place_mode else f'品类近似检索'),
                    output=fetch_txt)

    # ---- 兜底路径已删除（2026-09-17，用户诉求②）----
    # 改造前这里有**两级兜底**，正是用户看到"把正在开店的奶茶店地址给我"的根因：
    #   ① 高德 POI 兜底：kw = f'{category}出租' → 品类=奶茶时关键词就是"奶茶出租"，
    #      返回的是**在营奶茶店**（POI 是"店铺"不是"房源"），只有名字+区域级地址；
    #   ② 本地库兜底：query_within('商圈','办公') → 是**商圈/写字楼点位**，
    #      既不是房源也没有任何租金面积。
    # 两级都缺租金与面积 → 进去必然"算不出经营评分"，靠"全缺也算候选"来凑数量，
    # 等于用噪声填满列表。用户决策：**一律不进候选，接受候选数可能不足 15**。
    # 真房源不足时如实说不足（下面的文案分三种情况），不用不相干的点位充数。
    _st.stop('58抓取+候选定位')

    # ---- 补全 + 排序 + 三态标注（2026-09-17 新增） ----
    _st.start('字段补全+排序')
    scope_label = f'{city or ""}{area_filter}'
    candidates = _fill_field_states(candidates, shops, scope_label, category or None)
    candidates = _rank_candidates(candidates, target_lng, target_lat)
    _st.stop('字段补全+排序')

    if candidates:
        state_brief = cand_state_brief(candidates)
        # 房源性质构成（诉求③：转让铺算进来，但要能一眼分辨）
        mix = ''
        n_tf = sum(1 for c in candidates if c.get('deal') == '转让')
        n_rt = sum(1 for c in candidates if c.get('deal') == '出租')
        # ⚠️ 第三态必须**说出来**：判不出的如果只字不提，用户会以为
        #    "房东招租 + 转让" 就是全部，而卡片上那些没打性质标签的
        #    会被当成"房东招租"读（实机就出现过 15 家里只报 3+1 的情况）。
        n_un = len(candidates) - n_tf - n_rt
        if n_tf or n_rt:
            bits = []
            if n_rt:
                bits.append(f'{n_rt} 家房东招租')
            if n_tf:
                bits.append(f'{n_tf} 家**转让**（别人在转店，谈判对象是现任租户）')
            if n_un:
                bits.append(f'{n_un} 家标题没写明性质（**不猜**，卡片不打性质标签）')
            mix = '房源性质：' + '、'.join(bits) + '。\n'
        # 定位层级构成（诉求②：区域级定位要说明白）
        n_area = sum(1 for c in candidates if c.get('addr_level') == 'area')
        geo = (f'其中 {n_area} 家只有**区域级**定位（平台没给门牌/楼宇，卡片已标"区域级"，'
               f'不假装精确）。\n' if n_area else '')
        # 区域转让风险（谁在逃离）：用这批抓到的房源算区级转让率，
        # 作为 Huff 正向吸引力（能赚多少）的镜像负向信号。
        # 严格增量：算不出来（异常/样本不足）就空串，绝不影响候选主链路。
        risk = ''
        try:
            _risk_txt = transfer_risk_summary(shops, min_n=5)
        except Exception:
            _risk_txt = ''
        if _risk_txt:
            risk = f'区域转让风险（谁在逃离）：{_risk_txt}。\n'
        shortage = (f'⚠️ 该区域真实在租房源就这么多，**不足 15 家**不是抓取失败 —— '
                    f'已把 58 的 PC 3 页 + 移动端都翻过。\n'
                    if len(candidates) < CAND_TOTAL else '')
        if place_mode:
            reply = (f'在「{area}」共找到 **{len(candidates)}** 个在租商铺（58同城实时抓取）。\n'
                     f'{shortage}{mix}{geo}{risk}'
                     f'数据可信度：{state_brief}。\n'
                     '已按「租金/面积是否齐全」排序，从头看就行。\n\n'
                     '选中一家后，我按奶茶/甜品/早餐/便利店四个品类各算一遍，'
                     '告诉你这里开什么最赚 —— 从右侧卡片选（或回复"选1"）：')
        else:
            reply = (f'在「{area}」为你找到 **{len(candidates)}** 个候选商铺（58同城实时抓取）。\n'
                     f'{shortage}{mix}{geo}{risk}'
                     f'数据可信度：{state_brief}。\n'
                     '已按「租金/面积是否齐全」排序，点右侧卡片选择（也可回复"选1"）：')
    else:
        if fetch_meta.get('ok') is False:
            reply = (f'在「{area}」**取数失败**（58 抓取异常，不是"没有铺子"）：'
                     f'{fetch_meta.get("reason") or "反爬/网络"}。\n'
                     '可以稍后再试，或换个区域。')
        else:
            reply = (f'在「{area}」确实没有搜到在租商铺（58 已翻 3 页 + 移动端，'
                     f'不是抓取失败）。\n'
                     '这不是"系统没数据"，是**这一带此刻真的没有挂牌** ——'
                     '换个区域，或者说个更宽的片区名（如"杭州滨江"而不是"滨江某条小路"）。')

    # 只在真有耗时记录时才发这条：本地库兜底/序号无效这类亚毫秒轮次发汇总
    # 只会往「执行过程」里塞噪声（§4 第 0 步要的是分布，不是刷屏）。
    if _st.ms:
        await _st.emit_summary(state, '⏱ 阶段耗时（候选检索轮）')

    return {
        'messages': state['messages'] + [{'role': 'assistant', 'content': reply}],
        'candidates': candidates,
        'phase': 'select_shop' if candidates else ('place_first' if place_mode else 'no_shop'),
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
                f'，面积：{c.get("area", "-")}㎡{c.get("area_state", "")}'
                f'，月租：{c.get("price", "-")}{c.get("rent_state", "")}')

    # 用户本轮自己报了租金则优先，否则用候选自带的（可能是推算值）
    info = parse_request(user_msg)
    user_rent = info.get('rent')

    # ---- 租金/面积三态（2026-09-17）----
    # 改造前的行为是 `rent = state.get('rent') or 8000`：缺租金就**静默按 ¥8000 测算**，
    # 还告诉用户"暂按默认 8000 测算"。这是最危险的一种错 —— 8000 不是数据，
    # 是编的，而它会一路传进净利、回本、经营评分，最后变成一个看起来很确定的结论。
    # 现在改成三态：实测 / 推算（显著标注）/ 不可得（**不出经营评分**）。
    rent_state = 'measured' if user_rent is not None else (c.get('rent_state') or 'unavailable')
    area_state = c.get('area_state') or ('measured' if c.get('area') else 'unavailable')
    rent_val = user_rent if user_rent is not None else c.get('price')
    area_val = c.get('area') or state.get('area')

    filled = []
    if area_val:
        filled.append(f"面积 {area_val}㎡"
                      + {'derived': '（推算）', 'unavailable': '（未标）'}.get(area_state, ''))
    if rent_val:
        filled.append(f"租金 ¥{rent_val:,.0f}/月" + ('（推算）' if rent_state == 'derived' else ''))

    msg = f'已选：「{c["name"]}」（{c["address"]}）。'
    if filled:
        msg += f'\n已填入：{"、".join(filled)}。'
    if rent_state == 'derived':
        band = c.get('rent_band') or (None, None)
        band_txt = f'（同区参考带 ¥{band[0]:,}~{band[1]:,}/月）' if band[0] else ''
        msg += (f'\n⚠️ 该铺平台未标租金，上面是**推算值**{band_txt}，'
                f'依据：{c.get("rent_source") or "同区挂牌参考带"}。'
                '推算值会参与四品类排序，但结论里会注明口径；'
                '你报一个实际月租，我就换成实测口径重算。')
    elif rent_state == 'unavailable':
        msg += ('\n⚠️ 该铺**租金不可得**（平台未标，同区样本也不足以推算）。'
                '没有月租就算不出净利与回本 —— **本次不出经营评分**，只给地址维度参考。'
                '报一个实际月租（或你的预算）我再算一遍。')
    if area_state == 'derived':
        msg += f'\n⚠️ 面积也是**推算值**（{c.get("area_source")}），有实测面积请告诉我。'
    elif area_state == 'unavailable':
        msg += '\n⚠️ 该铺**面积不可得**，没有面积算不出产能与流水 —— 同样不出经营评分。'
    if c.get('addr_level') in (None, 'area', 'street') or c.get('precise') is False:
        msg += ('\n⚠️ 该商铺仅有区域级定位（平台未提供门牌/楼宇，卡片标"区域级·无门牌"），'
                '分析将基于所在区域进行；若知道具体门牌/路名，可补充以获得精确分析。')

    if state.get('place_first_mode'):
        # 入口 B：地点优先选中的铺子 —— 用户**还没想好品类** -> 直接四品类反推。
        # 若他在选的时候顺手说了品类，classify 会把 place_first_mode 收回，
        # 走下面的品牌/预算分支（用户已经想好了，不该再反问品类）。
        next_phase = 'reverse_match'
        msg += ('\n\n这家你还没想好做什么？我按 **奶茶 / 甜品 / 早餐 / 便利店** 各算一遍，'
                '看这里开什么最赚。\n（已经想好了就直接说品类，比如"就开奶茶"。）')
    else:
        # 奶茶品类且未定品牌 -> 先问品牌（在预算之前）；否则直接问预算
        next_phase = 'collect_brand' if _needs_brand_step(state) else 'collect_invest'
        msg += '\n\n' + (brand_ask_message() if next_phase == 'collect_brand'
                         else ask_investment_message(state.get('category', ''),
                                                     state.get('brand') or ''))

    return {
        'messages': state['messages'] + [{'role': 'assistant', 'content': msg}],
        'address': _clean_area(c['name']),
        'pending_coord': (c['lng'], c['lat']),
        'selected_idx': idx,
        'area': area_val,
        'rent': rent_val,
        'rent_state': rent_state,
        'area_state': area_state,
        'rent_band': c.get('rent_band'),
        'phase': next_phase,
        'list_shown': True,
    }


# ---------------------------------------------------------------
# 节点 5：评分分析
# ---------------------------------------------------------------
# ---------------------------------------------------------------
# §4 第 0 步：阶段计时器（先测量，再优化）
# ---------------------------------------------------------------
class _Stage:
    """极轻量的阶段耗时记录器（§4 第 0 步）。

    **为什么必须先有它**：改造前全项目没有任何阶段计时，方案里那份"耗时排序"
    全是按代码常数推断的。凭推断优化，很可能把力气花在占比 3% 的那一环上，
    而真正的大头（VLM 最坏 75s / PDF 首启 / 瓦片串行）被忽略。
    所以先装表、跑几次真实分析、拿到分布，再决定动哪里。

    结果写进 `hooks['stage_ms']`（跨节点共享，因为 hooks 是同一个 dict），
    并由各节点汇总成一条 `⏱ 阶段耗时` 事件 —— 前端「执行过程」面板直接可见，
    不需要另开日志。同名阶段重复计次会累加（如四个品类的测算）。
    """

    def __init__(self, state):
        hooks = state.get('hooks')
        if hooks is None:
            hooks = state['hooks'] = {}
        self.ms = hooks.setdefault('stage_ms', {})
        self._t = {}

    def start(self, name):
        self._t[name] = time.perf_counter()
        return self

    def stop(self, name):
        t0 = self._t.pop(name, None)
        if t0 is not None:
            self.ms[name] = self.ms.get(name, 0) + round((time.perf_counter() - t0) * 1000)
        return self.ms.get(name, 0)

    def summary(self, top: int = 8):
        """按耗时降序，只列最贵的 top 项（全列会让事件很长且噪声大）。"""
        rows = sorted(self.ms.items(), key=lambda x: -x[1])[:top]
        return '、'.join(f'{k} {v}ms' for k, v in rows) or '（无记录）'

    async def emit_summary(self, state, name='⏱ 阶段耗时'):
        await _emit(state, 'tool', name, output=self.summary())


async def _vlm_probe(state, img_url: str, cat: str, addr: str, st=None):
    """门头照视觉分析（§4：与竞品挖掘**并发**，不再是串行 await）。

    ⚠️ 这里**不改 `result`** —— 只把 VLM 结果交回去，由 analyze_node 在并发结束后
    统一 `apply_storefront()`。理由见 analyze_node 里的合并注释（副本覆盖问题）。
    失败一律返回 None（门头照是加分项，不能拖垮主流程）。
    `st`：共享的 `_Stage` 计时器；并发时各分支用**各自的阶段名**，互不覆盖。
    """
    if st is not None:
        st.start('门头照VLM')
    try:
        from agent.vision import (analyze_storefront_url,
                                  VLM_PER_MODEL_TIMEOUT, VLM_TOTAL_BUDGET)
        await _emit(state, 'tool', '门头照视觉分析（自动看铺）',
                    input_=f'58 在租实拍图 → 视觉模型\n{img_url[:80]}',
                    output='识别招牌/装修/门头/卫生中…')
        return await asyncio.wait_for(
            asyncio.to_thread(analyze_storefront_url, img_url,
                              f'计划品类：{cat}；商铺：{addr}',
                              VLM_PER_MODEL_TIMEOUT),
            timeout=VLM_TOTAL_BUDGET)
    except Exception as e:
        await _emit(state, 'tool', '门头照视觉分析（自动看铺）',
                    input_=img_url[:80], output=f'跳过（{e}）')
        return None
    finally:
        if st is not None:
            st.stop('门头照VLM')


async def _competitor_probe(state, lng, lat, cat, brand, st=None):
    """竞品口碑与价格带挖掘（§4：与 VLM **并发**）。

    返回 `(insight, brief_txt, err)`：
      · 成功取到 → `(insight, brief_txt, None)`；
      · 调用抛异常 → `(None, str(e), str(e))` —— 与"取数成功但真的没有同类店"
        **必须分开**（`err is None` 时 `insight is None` 才表示"真的没有"）。
        这正是项目纪律里的"取数失败 ≠ 真的没有"，合并两者会让用户以为
        这个商圈没竞品，从而低估竞争。
    同样不改 `result`。
    """
    if st is not None:
        st.start('竞品挖掘')
    try:
        from engine.competitor_insight import competitor_brief
        await _emit(state, 'tool', '竞品口碑挖掘',
                    input_='周边 1000m 同类门店口碑分/人均/营业时间/招牌标签（高德公开字段）',
                    output='抓取中…')
        insight, brief_txt = await asyncio.to_thread(
            competitor_brief, lng, lat, cat, 1000, 25, brand)
        return insight, brief_txt, None
    except Exception as e:
        await _emit(state, 'tool', '竞品口碑挖掘',
                    input_='高德周边搜索', output=f'跳过（{e}）')
        return None, str(e), str(e)
    finally:
        if st is not None:
            st.stop('竞品挖掘')


async def analyze_node(state: AgentState) -> Dict[str, Any]:
    """调用评分引擎，生成评分结果（评分优先本地库，0 次实时 API）。

    ⚠️ 2026-09-17 变更：**去掉 `rent = state.get('rent') or 8000`**。
    旧写法在缺租金时静默按 ¥8000 测算，而 8000 不是数据、是编的 ——
    它会一路传进净利/回本/经营评分，最后给出一个看起来很确定的错误结论。
    现在：租金或面积不可得时**不进评分**，直接返回"补一个数就能算"的引导。
    """
    cat = state['category']
    addr = state['address'] or ''
    rent = state.get('rent')
    area = state.get('area')
    rent_state = state.get('rent_state') or ('measured' if rent else 'unavailable')
    area_state = state.get('area_state') or ('measured' if area else 'unavailable')

    # 租金/面积不可得 -> 不出分（与"无月租/无面积不出经营评分"的既有口径一致）
    if not rent or not area:
        lack = []
        if not rent:
            lack.append('月租金')
        if not area:
            lack.append('面积')
        reply = (f'缺{ "、".join(lack) }，算不出来 —— **缺一个数就少一整块结论**，'
                 f'而且我不会替你猜（月租直接决定净利与回本，猜出来的是假结论）。\n\n'
                 f'· 月租：这套铺子一个月多少钱？（或你的租金预算）\n'
                 f'· 面积：多少平？\n\n'
                 f'补上就立刻出分析。')
        return {
            'messages': state['messages'] + [{'role': 'assistant', 'content': reply}],
            'phase': 'have_shop',
        }

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

    st = _Stage(state)

    st.start('评分引擎')
    result = await asyncio.to_thread(
        score_site, cat, lng, lat, rent, addr, area,
        investment=state.get('investment'), staff=state.get('staff'),
        brand=state.get('brand')
    )
    st.stop('评分引擎')

    await _emit(state, 'tool', '选址评分引擎',
                input_=f'品类「{cat}」坐标 ({lng:.5f}, {lat:.5f}) 月租 ¥{rent:,.0f}'
                       f'（Huff 引力模型，本地 POI 库优先，0 次实时 API）',
                output=(f'总分 {result.get("total")} → {result.get("verdict")}；'
                        f'维度：' + '、'.join(f'{k}={v}' for k, v in (result.get("dims") or {}).items())))

    # ---- §4 提速：AI 看铺（VLM）与竞品口碑挖掘**互不依赖** → 并发取数 ----
    # 改前是两个串行 await：VLM（单模型 60s、预算 75s）走完才轮到竞品（缓存未命中
    # 0.5~3s），白等 min(两者)。两者本来就都"失败不影响主流程"，并发不放大风险。
    #
    # ⚠️ **并发只负责"取数"，合并仍然串行**：
    #    两个分支都要改 `result` —— VLM 经 `apply_storefront()` 返回一个**新副本**，
    #    竞品往 `result['competitor_insight']` 写字段。若在并发里各改各的，
    #    先返回的那份副本会把另一分支后写进去的字段**整块覆盖掉**；
    #    而且丢字段不抛异常，只会"静默少一块数据"，极难发现。
    #    所以两边都只返回结果、不改 `result`，合并放在 await 之后按顺序做。
    img_url = None
    cands = state.get('candidates') or []
    idx = state.get('selected_idx')
    if isinstance(idx, int) and 0 <= idx < len(cands):
        img_url = cands[idx].get('img')

    _vlm_task = (asyncio.create_task(_vlm_probe(state, img_url, cat, addr, st))
                 if img_url else None)
    _cmp_task = asyncio.create_task(
        _competitor_probe(state, lng, lat, cat, result.get('brand'), st))

    # 两个 task 在 create_task 时就已经并发跑起来了；这里只是**按固定顺序收结果**
    # （顺序固定 → `hooks['steps']` 里的事件次序确定，离线回归才好断言）。
    st.start('看铺‖竞品(并发段)')
    if _vlm_task:
        vlm = await _vlm_task
    else:
        vlm = None
    insight, brief_txt, cmp_err = await _cmp_task
    st.stop('看铺‖竞品(并发段)')

    # ① 门头形象并入评分（权重 10%；非门头实景不给假分、不计入总分）
    if vlm is not None:
        try:
            from engine.scoring import apply_storefront
            before = result.get('total')
            result = apply_storefront(result, vlm)
            sf = result.get('storefront') or {}
            if sf:
                await _emit(state, 'tool', '门头形象并入评分',
                            input_=(f'招牌：{vlm.get("招牌文字") or "未识别"}；'
                                    f'装修 {vlm["装修档次"]}/5、门头 {vlm["门头可见度"]}/5、'
                                    f'卫生 {vlm["卫生观感"]}/5'),
                            output=(f'形象分 {sf["形象分"]}（权重 10%），'
                                    f'总分 {before} → {result.get("total")}'))
            else:
                await _emit(state, 'tool', '门头照视觉分析（自动看铺）',
                            input_=img_url[:80],
                            output='图片非门头实景（品牌 logo/宣传图/室内局部），不给假分、不计入总分')
        except Exception as e:
            await _emit(state, 'tool', '门头照视觉分析（自动看铺）',
                        input_=img_url[:80], output=f'跳过（{e}）')

    # ② 竞品口碑并入（`cmp_err` 与"真的没有同类店"必须分开，见 _competitor_probe）
    if cmp_err is not None:
        pass          # 调用异常：_competitor_probe 里已 emit「跳过（原因）」
    elif insight:
        # 明细不进 prompt（体积大且对解读无用），只留结构化统计
        result['competitor_insight'] = {k: v for k, v in insight.items() if k != '明细'}
        check = insight.get('客单价现实校验') or {}
        if check and check.get('判断') != '基本吻合':
            result.setdefault('warnings', []).append(
                f'⚠️ 客单价假设{check["判断"]}：{check["说明"]}')
        r = insight.get('口碑分') or {}
        c = insight.get('客单价带') or {}
        await _emit(state, 'tool', '竞品口碑挖掘',
                    input_=f'{insight["样本数"]} 家同类竞品（连锁占比 {insight["连锁占比"]:.0%}）',
                    output=(f'口碑均分 {r.get("均值") or "-"}，人均中位 ¥{c.get("中位") or "-"}'
                            f'（P25 ¥{c.get("P25") or "-"} / P75 ¥{c.get("P75") or "-"}），'
                            f'HHI {insight.get("品牌集中度HHI")}；'
                            f'客单价假设校验：{check.get("判断") or "无数据"}'))
    else:
        # brief_txt 此时携带的是**具体失败原因**（限流 / 日配额 / 真的没有同类店），
        # 三者含义完全不同，不能合并成一句"无数据返回"——那会让用户以为
        # "这个商圈没竞品"，从而低估竞争。
        reason = (brief_txt or '').strip() or '原因未知'
        _limited = ('限流' in reason) or ('配额' in reason)
        await _emit(state, 'tool', '竞品口碑挖掘',
                    input_='高德周边搜索',
                    output=('⚠️ 取数失败（已如实标注，未编造数据）'
                            if _limited else '周边确实无同类门店返回（未编造数据）'))
        result.setdefault('warnings', []).append(
            ('⚠️ 竞品口碑数据未获取到：' if _limited else 'ℹ️ 竞品口碑数据为空：') + reason)

    st.ms['分析总计'] = st.ms.get('评分引擎', 0) + st.ms.get('看铺‖竞品(并发段)', 0)
    await st.emit_summary(state)

    # 数据口径随结果一起带出去：前端卡片与 PDF 要按它打标
    # （实测/推算/不可得必须视觉可分，不许把推算结果展示成实测）
    result['rent_state'] = rent_state
    result['area_state'] = area_state
    if state.get('rent_band'):
        result['rent_band'] = list(state['rent_band'])

    return {
        'score_result': result,
        'context': json.dumps(result, ensure_ascii=False),
        'phase': 'interpret',
        'rent_state': rent_state,
        'area_state': area_state,
    }


# ---------------------------------------------------------------
# 节点 6：LLM 解读（1 次 LLM 调用）
# ---------------------------------------------------------------
async def interpret_node(state: AgentState) -> Dict[str, Any]:
    """用 LLM 解读评分结果（一次调用；失败降级规则解读）。"""
    result = state.get('score_result')
    if not result:
        return {'phase': 'chat'}

    # ---- RAG: 选址知识库检索，注入解读 prompt（纯本地 TF-IDF，0 次 API）----
    # ⚠️ 人设固定用 site_advisor（§6 修"人设错位"）：解读**一份选址评分**本就该是
    #    选址评估师的工作。改造前按"当前选中的专家"取人设，于是用户选了"模型审计师"
    #    就会用审计师的人设 + 模型边界的 kb 分区去解读选址评分 —— 那不是"专家被
    #    拒绝"，而是**用错了人**。这里固定，且 kb 分区随之固定在选址口径上。
    _INTERP_EXPERT = DEFAULT_EXPERT
    st = _Stage(state)          # §4 第 0 步：与 analyze_node 共用同一本账（hooks 跨节点共享）
    st.start('RAG检索')
    kb_query = f"{result.get('category') or ''} {result.get('name') or ''} 选址"
    kb_txt = kb_context(kb_query, top_k=3, tags=_expert_kb_tags(_INTERP_EXPERT))
    st.stop('RAG检索')

    # ---- 专家层：公共铁律（唯一一份）+ 选址评估师 persona（增量）----
    # 原来那 9 条定制约束已按「通用 / 专属」拆开：
    #   通用纪律（不许编数字、必须报口径、三档报两端、口径区间与三档分开讲、
    #   veto 优先、附局限）→ `_common.md`，唯一一份，9 位专家共用；
    #   字段级指引（profit.人数、storefront、competitor_insight、口径区间…）
    #   → `site_advisor.md` 的增量职责。
    # 想改铁律只改 `_common.md` 一个文件 —— 4 个节点各抄一份的旧做法必然改漏。
    system_msg = experts.compose_system_prompt(
        _INTERP_EXPERT, kb_text=kb_txt)

    if kb_txt:
        _tags = _expert_kb_tags(_INTERP_EXPERT)
        await _emit(state, 'tool', '知识库检索（RAG）',
                    input_=kb_query[:40],
                    output=f'命中 {kb_txt.count(chr(10)) + 1} 条选址知识'
                           f'（分区：{"/".join(_tags) if _tags else "全库"}）')

    # ---- §4 提速：prompt 只用"决策相关字段"，不再整份 json.dumps(result) ----
    # 旧写法把 profit（30+ 成本键）+ profit_bands（3 档 × 30+ 键）三套几乎相同的
    # 成本字典整份塞进去，直接抬高首 token 延迟；而竞品那块反而是特意裁剪过的。
    # 这里只给：中性档摘要 + 三档摘要（含月净利/回本两端，解读要报的正是它们）
    # + 口径区间（原样，本来就小）。所有断言要的数字（三档两端、净利、回本）都保留。
    _view = dict(result)
    if result.get('profit') is not None:
        _view['profit'] = _slim_profit(result['profit'])
    if result.get('profit_bands') is not None:
        _view['profit_bands'] = _slim_bands(result['profit_bands'])
    user_msg = (f'评分引擎返回了以下真实数据：\n{json.dumps(_view, ensure_ascii=False)}\n\n'
                f'请基于以上数据，向用户输出选址建议。')

    await _emit(state, 'think', '生成解读',
                f'评分完成（总分 {result.get("total")}），调用 LLM 生成口语化选址解读…')

    try:
        st.start('LLM解读')
        interpretation = await call_llm(system_msg, user_msg, temperature=0.3, timeout=120)
        llm_note = '火山方舟·豆包'
    except Exception as e:
        from agent.agent import rule_based_interpret
        interpretation = rule_based_interpret(result)
        interpretation += f'\n\n[提示: LLM解读暂不可用，已用规则解读。原因：{e}。\n请检查 LLM API 账户余额/Key（可在 .env 配置 LLM_API_KEY / LLM_FALLBACK_API_KEY）。]'
        llm_note = '规则解读（LLM 暂不可用）'
    finally:
        # 走的是 finally 而不是 try 尾部：降级到规则解读时这一步同样耗了时间
        # （等完整个 provider 链才放弃），漏记会把"最慢的一次"正好藏起来。
        st.stop('LLM解读')

    await _emit(state, 'tool', f'LLM 解读（{llm_note}）',
                input_=f'评分数据 → 口语化选址建议（含证据引用与风险）',
                output=f'解读完成，{len(interpretation)} 字' + ('（火山方舟·doubao-seed-2.1-pro）' if llm_note.startswith('火山') else ''))
    await st.emit_summary(state, '⏱ 阶段耗时（全流程）')

    # 保存分析结果到本地（供"对比"功能跨对话使用；纯本地，0 次 API）
    try:
        from agent.analysis_store import add_analysis
        add_analysis(result, rent=state.get('rent'), area=state.get('area'),
                     investment=state.get('investment'), staff=state.get('staff'),
                     utility=result.get('utility'), profit=result.get('profit'),
                     interpretation=interpretation, city=state.get('city'))
    except Exception:
        pass

    # 租金口径声明（2026-09-17）：
    # 改造前这里是"未提供月租金，按默认 ¥8000 测算" —— 但 analyze_node 现在
    # 缺租金就直接不出分，所以那种情形已经走不到这里。留下的两条分支改成
    # **推算值必须显式声明**，不能让用户把推算读成实测。
    if state.get('rent_state') == 'derived':
        _band = state.get('rent_band') or (None, None)
        _band_txt = f'（同区参考带 ¥{_band[0]:,}~{_band[1]:,}/月）' if _band[0] else ''
        interpretation += (f'\n\n（注：本次月租 ¥{state.get("rent"):,.0f} 是**推算值**{_band_txt}，'
                           '来源是同区在租挂牌参考带 P25~P75 元/㎡/月（粒度到行政区、'
                           '未剔除楼层业态）。金额本身有系统性偏差，**回本周期对它尤其敏感**；'
                           '报一个实际月租我可以换实测口径重算。）')
    if state.get('area_state') == 'derived':
        interpretation += (f'\n\n（注：面积 {state.get("area")}㎡ 也是**推算值**'
                           '（平台未标、按品类标准面积/同区样本中位面积补），有实测面积请告知。）')

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
def _wants_negotiate(text: str) -> bool:
    """识别租金谈判意图：谈价/砍价/还价/压价/租金能不能少 等"""
    t = text or ''
    has_price_word = any(k in t for k in ['租金', '房租', '价格', '报价'])
    has_talk_word = any(k in t for k in ['谈', '砍', '还价', '压价', '便宜', '少点', '优惠', '议价'])
    return has_price_word and has_talk_word


def _wants_competitor(text: str) -> bool:
    """识别竞品口碑/竞争格局意图：周边竞品怎么样、对手口碑、竞争激不激烈 等"""
    t = text or ''
    has_comp_word = any(k in t for k in ['竞品', '竞争', '对手', '同行', '别家', '其他店'])
    has_info_word = any(k in t for k in ['口碑', '评价', '评分', '怎么样', '如何', '激不激烈',
                                         '价格', '人均', '卖多少', '生意', '多不多', '多吗',
                                         '几家', '密集', '饱和', '扎堆', '格局'])
    return has_comp_word and has_info_word


_CLAUSE_SPLIT = re.compile(r'[？?！!。；;，,\n\r]+')
_QUESTION_HINTS = ('多少', '几', '什么', '怎么', '哪', '吗', '贵', '便宜', '要不要', '能不能',
                   '投', '钱', '费', '需要', '如何', '咋', '行不行')


def _other_questions(text: str, matched) -> str:
    """复合意图拆分：把用户一句话按标点切成子句，剔除已被专门节点接住的部分（matched 判定），
    返回剩下的疑问子句（'；'拼接）；没有则返回空串。

    背景：用户常一句话问两件事（"加盟蜜雪冰城要投多少钱？周边竞品口碑怎么样"），
    整句命中某个专门节点后被它独占，另一半问题就没人答了。拆开后：专门节点照常取数，
    其余疑问作为附加问题一并交给 LLM 回答。竞品节点与谈判节点共用这套逻辑。"""
    clauses = [c.strip() for c in _CLAUSE_SPLIT.split(text or '') if c.strip()]
    if len(clauses) < 2:
        return ''
    kept = [c for c in clauses if matched(c)]
    if not kept:
        return ''
    other = [c for c in clauses if c not in kept and any(k in c for k in _QUESTION_HINTS)]
    return '；'.join(other)


async def free_chat_node(state: AgentState) -> Dict[str, Any]:
    """用户追问改进建议/客流/运营等；未分析商铺时也能自由聊天"""
    user_msg = state['messages'][-1]['content']
    context = state.get('context', '')

    # ---- 租金谈判意图 + 已有分析结果 → 谈判助手（真实行情数据 + LLM 话术）----
    # 复合问题（"租金能砍到多少？周边竞品口碑怎么样"）把另一半疑问一起带上，不让它被吞掉
    if _wants_negotiate(user_msg) and state.get('score_result'):
        return await negotiate_node(state,
                                    extra_question=_other_questions(user_msg, _wants_negotiate))

    # ---- 竞品口碑意图 → 竞品洞察（高德真实口碑分/价格带 + LLM 解读）----
    if _wants_competitor(user_msg):
        return await competitor_node(state,
                                     extra_question=_other_questions(user_msg, _wants_competitor))

    _sel = state.get('expert')

    # ★ 自由对话（用户手动开关）**优先级最高：无视已选专家**（2026-09-17 用户诉求）。
    # 起因：打开自由对话后问「今天天气怎么样」「这部剧好看吗」，回答仍被已选专家接管
    #   —— 人设是"经营测算专家"、知识库只检索该专家的分区、还挂上该专家的工具白名单。
    #   用户要的是"一个能随便聊的通用助手"，不是"一位专家在闲聊"。
    # 处置：自由对话下把 `_sel` 当作未选 → 走"未选专家"的通用路径
    #   （全库检索 / 不开工具 / 通用人设），并追加一段通用助手人设（见下方 `if _free:`）。
    # 边界：**只在本节点生效**。选址/诊断/谈判等业务节点的人设不受影响 ——
    #   那些节点的职责本身就对应某位专家，与"用户选了谁"无关。
    _free = is_free_chat_mode()
    if _free:
        _sel = None

    # §6：结构化证据包（有分析结果时才有内容；没有则为空串，逐字走回旧路径）
    _pack = build_evidence_pack(state)

    # ---- RAG: 按用户问题检索知识库（纯本地，0 次 API）----
    # 选了专家 → 按该专家的分区检索；未选（含自由对话）→ 全库
    kb_txt = kb_context(user_msg, top_k=3, tags=_expert_kb_tags(_sel))

    _KB_TAIL = (f"\n\n【选址知识库检索结果（系统内置知识库，与问题相关时可引用，"
                f"引用时说明来自系统知识库；不相关则忽略）】\n{kb_txt}")

    if _free:
        # 【自由对话】通用助手人设（2026-09-17）。三条要点，缺一条就会退回老毛病：
        #   ①「问什么答什么」—— 否则模型仍按选址顾问收口，把天气问题带回开店；
        #   ②「没有实时能力要**先说明**」—— 否则它会编一个"今天杭州 26 度"；
        #   ③「只有用户主动问选址才切专业口径」—— 别硬聊，也别把专业能力丢掉。
        _was = state.get('expert')
        system_msg = (
            '你现在的模式是【自由对话】（用户手动打开的通用助手模式，'
            '优先级高于任何"专家视角"）。\n'
            '1. 用户问什么就答什么 —— 天气、影视剧、生活常识、闲聊、写文案、'
            '解释概念都正常回答；不要把这些话题拉回选址，'
            '也不要因为"不在我的职责范围"就拒答或只答一半。\n'
            '2. 你没有联网与实时数据能力：涉及实时信息（今天的天气、最新剧集、'
            '当前价格、新闻）时，**必须先说明这一点**，再用你已有的知识做一般性回答；'
            '**不许**编造具体数值，也不许说"我帮你查了一下"。\n'
            '3. 用户主动问到选址 / 开店 / 经营时，照常用专业口径回答；'
            '想跑完整的选址分析流程，可以提示他关掉「自由对话」再开始。\n'
            '4. 数字纪律不变：证据包里没有的数据就是没有，不许用常识填。')
        if _pack:
            system_msg += (f'\n\n【当前会话已有的选址分析证据包（真实数据）】\n{_pack}\n'
                           '**仅当用户问到该商铺时**才引用；引用须与上述数值逐字一致。')
        elif context:
            system_msg += (f'\n\n【当前会话已完成的选址分析摘要】{context}\n'
                           '同上：仅当用户问到该商铺时才引用。')
        if kb_txt:
            system_msg += _KB_TAIL
        if _was:
            await _emit(state, 'think', '自由对话·优先级',
                        f'本次已选专家「{_was}」**不生效** —— 自由对话下'
                        f'人设 / 知识分区 / 工具白名单全部让位，按通用助手回答')
    elif _sel:
        # 用户显式选了专家 → 换成该专家的人设与铁律（专家层 P0 的核心行为）。
        # **未选时不走这条分支**，默认行为逐字不变 —— 回归因此有明确基准。
        system_msg = experts.compose_system_prompt(_sel, kb_text=kb_txt)
        if _pack:
            # §6：结构化证据包（替代原来的一行摘要）。这一段是"专家 vs 裸 LLM"
            # 在主要路径上的**实质差异来源** —— 裸 LLM 拿不到四维分/三档/临界点。
            system_msg += (f'\n\n【当前会话已完成的结构化证据包（真实数据）】\n{_pack}\n'
                           '引用时必须与上述数值逐字一致，不得改动、不得四舍五入成大约值；'
                           '证据包里没有的数据就是「系统里没有」，请直说，不要用常识补。')
        elif context:
            system_msg += (f'\n\n【当前会话已完成的选址分析摘要】{context}\n'
                           '结合它回答用户的问题。')
    elif _pack:
        system_msg = (
            f'你是"址南针"的选址顾问。用户已经完成了一个商铺的选址分析。\n'
            f'以下是该商铺的**结构化证据包**（真实数据）：\n{_pack}\n\n'
            f'请结合数据，用口语化、专业、有建设性的方式回答用户的问题。'
            f'涉及数据时必须引用真实数值，不要编造。')
        if kb_txt:
            system_msg += _KB_TAIL
    elif context:
        system_msg = f"""你是"址南针"的选址顾问。用户已经完成了一个商铺的选址分析。
以下是该商铺的评分摘要：{context}

请结合数据，用口语化、专业、有建设性的方式回答用户的问题。
涉及数据时必须引用真实数值，不要编造。"""
        if kb_txt:
            system_msg += _KB_TAIL
    else:
        system_msg = """你是"址南针"的选址顾问，专门帮个人创业者评估商铺选址。
用户目前还没有分析具体商铺。
请友好回答：如果是闲聊或一般问题，就正常聊天；如果涉及选址，
可以温和引导用户提供「想开什么品类 + 想开在哪个区域」，或具体商铺地址来开始分析。"""
        if kb_txt:
            system_msg += _KB_TAIL

    if kb_txt:
        await _emit(state, 'tool', '知识库检索（RAG）',
                    input_=f'问题：{user_msg[:40]}',
                    output=('已注入相关知识条目'
                            + (f'（{_sel} 分区）' if _sel else '')))

    # ---- 用户上传的附件正文（PDF / 文本 / Word，由 UI 层抽取后挂到 state）----
    # 放在 system_msg 三个分支**都拼完之后**统一追加，这样无论走"选了专家 / 有分析摘要 /
    # 纯闲聊"哪条路，附件的正文都能被看到，不用改三处。
    # 无附件时 state 里没有这个键（`or []`）→ 行为与从前逐字一致，回归有明确基准。
    # ⚠️ 不要把附件正文塞进 state['context']：context 非空是"已完成选址分析"的**标志**
    #    （见上面的 elif context 分支），塞进去会让模型谎称做过分析。
    _atts = state.get('attachments') or []
    if _atts:
        _blocks = []
        for _a in _atts[:2]:
            _t = (_a.get('text') or '').strip()
            if _t:
                _blocks.append(f'《{_a.get("name") or "附件"}》：\n{_t}')
        if _blocks:
            _head = _atts[0].get('name') or '附件'
            system_msg += ('\n\n【用户上传的附件正文（请以此为准回答；'
                           '文件里没有的内容不要编造，也不要引用未列出的页码）】\n'
                           + '\n\n'.join(_blocks))
            await _emit(state, 'tool', '附件正文注入',
                        input_=f'附件：{_head}',
                        output=(f'已把 {len(_blocks)} 份附件正文（合计 '
                                f'{sum(len(b) for b in _blocks)} 字）注入对话上下文'))

    # ---- 真 function calling（§6）：只对"显式选了专家"的会话开放 ----
    # 工具白名单来自该专家 frontmatter 的 `tools` − `forbids`；模型只能看到白名单
    # 内的工具，越过白名单会被 `run_tool` 明确拒绝并把拒绝原因回灌给模型。
    # 未选专家时**不开工具**：默认路径逐字不变，回归有明确基准。
    _tools = expert_toolbox.tool_schemas(_sel) if _sel else []
    _trace = []
    try:
        if _tools:
            reply, _trace = await call_llm_with_tools(
                system_msg, user_msg, tools=_tools,
                tool_runner=lambda n, a: expert_toolbox.run_tool(_sel, n, a),
                max_rounds=3, temperature=0.5, timeout=120)
            llm_note = '火山方舟·豆包（含工具调用）'
        else:
            reply = await call_llm(system_msg, user_msg, temperature=0.5, timeout=120)
            llm_note = '火山方舟·豆包'
    except Exception as e:
        if context or _pack:
            reply = (f'（当前 AI 服务暂不可用：{e}）\n'
                     '你可以继续问，或让我分析其他地址。')
        else:
            reply = ('😊 我是址南针——你的 AI 商铺选址顾问！\n'
                     '告诉我**想开在哪个区域**（如"帮我找杭州滨江的商铺"）就行 ——'
                     '我先把你这一带的在租铺源拉出来，你挑中一家，我再算这里开什么最赚。\n'
                     '已经想好品类也可以直接说（如"滨江开个奶茶店"）；'
                     '或者直接给我具体商铺地址，我做 4 维度分析。\n'
                     '（注：当前 AI 联网服务暂不可用，恢复后即可自由聊天）')
        llm_note = '离线回复（LLM 暂不可用）'

    # 把真实发生的工具调用写进「执行过程」面板：这是"专家 vs 裸 LLM"的
    # **可核查证据** —— 用户能看到这位专家到底调了什么、有没有被拒。
    if _trace:
        _used = [t['tool'] for t in _trace if t.get('ok') and t.get('tool') != '(降级)']
        _deny = [t for t in _trace if t.get('denied')]
        await _emit(state, 'tool', f'工具调用（{_sel}）',
                    input_=f'白名单 {len(_tools)} 个工具',
                    output=(f'实际调用：{"、".join(_used) if _used else "无"}'
                            + (f'；被拒：{"、".join(t["tool"] for t in _deny)}' if _deny else '')
                            + ('；' + _trace[-1]['note'] if _trace[-1].get('note') else '')))

    await _emit(state, 'tool', f'LLM 自由对话（{llm_note}）',
                input_=f'用户追问：{user_msg[:40]}',
                output=(f'回答完成，{len(reply)} 字'
                        + ('；参考链接（原文出处）已随回答附上，可点击核验'
                           if _sel == 'startup_policy_advisor' else '')))

    # ---- 创业政策顾问：确定性追加「参考链接」块（2026-09-18）----
    # 政策顾问的职责之一就是"逐条给出处、让用户能点进原文"。但 LLM 未必把链接
    # 抄进回答（会漏、会改写 URL）。所以这里**不依赖 LLM**，直接从本次检索命中
    # 的政策语料里抽出带 url 的原文链接，去重后拼成可点击的 markdown 列表追加。
    # 无 url 的条目（如实标"未找到稳定链接"的）不在其列 —— 不给不存在的链接。
    if _sel == 'startup_policy_advisor':
        _plinks = kb_policy_links(user_msg, top_k=3, tags=_expert_kb_tags(_sel))
        if _plinks:
            _block = ['\n\n---\n**参考链接（原文出处）**']
            for _t, _u in _plinks:
                _block.append(f'- [{_t}]({_u})')
            reply += '\n'.join(_block)
        else:
            reply += ('\n\n---\n⚠️ 本次命中的政策条目暂无可稳定引用的原文链接，'
                      '建议按上文给出的法规文号/关键词在官方政务网检索最新原文。')

    return {
        'messages': state['messages'] + [{'role': 'assistant', 'content': reply}],
        'phase': 'chat',
        'compare_pending': False,
    }


async def negotiate_node(state: AgentState, extra_question: str = '') -> Dict[str, Any]:
    """租金谈判助手：同商圈 58 真实挂牌分布 + 结构化筹码 + LLM 话术。
    分工: 引擎产数据证据(negotiation.py)，LLM 只负责组织话术，严禁编数字。

    extra_question：用户复合提问中"谈判之外的另一半"（如"周边竞品口碑怎么样"），
    带上后要求 LLM 两段都答，不许吞问题。"""
    r = state['score_result']
    city = r.get('city') or ''
    addr = r.get('name') or state.get('address') or ''
    rent = r.get('monthly_rent')
    area = r.get('area_m2')
    district = extract_district(addr)

    await _emit(state, 'tool', '租金谈判助手',
                input_=f'抓 {city}{district or ""} 在租商铺行情（58同城）',
                output='分布统计中…')

    from engine.negotiation import negotiation_brief
    afford = r.get('rent_limits') or {}
    brief = await asyncio.to_thread(negotiation_brief, city, addr, rent, area, district, afford)

    bench = brief.get('行情分布')
    afford_txt = ''
    if afford:
        from engine.scoring import PAYBACK_LIMIT_MONTHS
        be = afford.get('盈亏平衡月租')
        cap = afford.get('回本达标月租上限')
        afford_txt = ('\n你的承受力上限（按本铺流水与成本结构反解，非市场行情）: '
                      + (f'不亏的月租上限 {be:,} 元' if be else '免租也亏损——租金不是矛盾所在')
                      + (f'；{PAYBACK_LIMIT_MONTHS} 个月内回本的月租上限 {cap:,} 元'
                         f'（比"只求不亏"更严，差额 {be - cap:,} 元/月）' if cap and be and cap < be
                         else (f'；{PAYBACK_LIMIT_MONTHS} 个月内回本的月租上限 {cap:,} 元' if cap else ''))
                      + f'\n可承受月租上限（天花板）: {brief.get("可承受月租上限") or "给不出"} 元/月'
                        f'（口径：{brief.get("上限口径") or "-"}）'
                        f'\n⚠️ 天花板 ≠ 开价：这是"最多能付"，不是"先出这个价"')

    if bench:
        data_txt = (
            f'同区在租挂牌参考带（范围 {bench["范围"]}，{bench["样本数"]} 个样本，'
            f'抓取于 {bench["抓取时间"]}）: {brief.get("行情参考带") or "-"}'
            f'（P25 {bench["P25单价"]} ~ P75 {bench["P75单价"]}，中位 {bench["中位单价"]}）。\n'
            f'⚠️ 可比性声明（必须原样转达用户，不许省略或改写）: {bench["可比性声明"]}\n'
            f'报价位置: {brief.get("价格位置") or "未知"}'
            f'{afford_txt}\n'
            f'谈判筹码: ' + '；'.join(brief['筹码'])
        )
        sample_txt = '参考带低端样本（注意看标题是不是同类铺子）: ' + '；'.join(
            f"{s['位置']}{s['面积']:.0f}㎡{s['月租']:.0f}元（{s['单价']:.0f}元/㎡）「{s['标题']}」"
            for s in bench.get('最低5样本') or [])
    else:
        data_txt = ('本次未能抓到同区挂牌数据（网络/反爬），'
                    '请基于通用餐饮租约谈判经验给建议，不要编造行情数字。'
                    + (afford_txt or ''))
        sample_txt = ''

    # ---- 专家层：公共铁律 + 租金谈判教练 persona ----
    # 原 6 条定制要求已进 `rent_negotiator.md`（天花板≠开价、差额锚、
    # 可比性声明原样转达、承受力与行情冲突直说…），通用纪律进 `_common.md`。
    kb_query = '租金谈判 租约条款 免租期' + (f' {extra_question}' if extra_question else '')
    kb_txt = kb_context(kb_query, top_k=2, tags=_expert_kb_tags('rent_negotiator'))
    system_msg = experts.compose_system_prompt('rent_negotiator', kb_text=kb_txt)


    if extra_question:
        system_msg += (f'\n\n【附加问题】用户除了谈租金，还问了：{extra_question}\n'
                       '7. 回答分两段：先给租金谈判结论与话术，再回答上面的附加问题；'
                       '附加问题只能引用证据包/知识库里已有的数据，'
                       '数据不足就直说"这部分需要再抓一次周边竞品数据，你可以单独问我'
                       '『周边竞品口碑怎么样』"，严禁凭印象编造。')
        await _emit(state, 'think', '复合意图拆分',
                    f'识别到两个问题：租金谈判 + 「{extra_question[:40]}」')

    raw_q = _last_user_msg(state)
    user_msg = (f'用户原话: {raw_q}\n'
                f'商铺: {addr}（{city}），报价 {rent} 元/月，面积 {area}㎡。\n{data_txt}\n{sample_txt}')

    try:
        reply = await call_llm(system_msg, user_msg, temperature=0.5, timeout=120)
    except Exception as e:
        # 降级: 无 LLM 时直接输出结构化筹码（data_txt 无条件输出——抓不到行情时
        # 承受力上限是唯一还剩的硬证据，恰恰最不能丢）
        lines = [f'（AI 话术暂不可用：{e}，以下为数据证据与谈判要点）', f'📊 {data_txt}']
        lines += [f'• {c}' for c in brief['筹码']]
        reply = '\n'.join(lines)

    await _emit(state, 'tool', '租金谈判助手',
                input_=f'{city}{district or ""} {rent}元/月 {area}㎡',
                output=(f'{bench["范围"] if bench else "未抓到"} 挂牌 {bench["样本数"] if bench else 0} 个'
                        f'（参考带 {brief.get("行情参考带") or "-"}，'
                        f'疑似非同类业态 {bench.get("疑似非同类业态样本数", 0) if bench else 0} 个）；'
                        f'天花板 {brief.get("可承受月租上限") or "给不出"} 元/月'
                        f'（{brief.get("上限口径") or "-"}），'
                        f'盈亏平衡月租 {afford.get("盈亏平衡月租") or "-"} 元'))

    return {
        'messages': state['messages'] + [{'role': 'assistant', 'content': reply}],
        'phase': 'chat',
        'compare_pending': False,
    }


# ---------------------------------------------------------------
# 节点 9：竞品口碑洞察（AI 方向④，1 次高德 API + 1 次 LLM）
# ---------------------------------------------------------------
async def competitor_node(state: AgentState, extra_question: str = '') -> Dict[str, Any]:
    """竞品口碑与价格带挖掘：高德公开字段（口碑分/人均/营业时间/招牌标签/团购）
    + 规则化洞察 + LLM 解读。
    诚实边界：大众点评评论文本有登录墙、不可得，本节点**不做评论情感分析**，
    只用平台公开字段，并在回答中明示数据局限。

    extra_question：用户复合提问中"竞品之外的另一半"（如"加盟蜜雪冰城要投多少钱"）。
    带上后本节点会补品牌加盟政策真实参考 + 知识库检索，要求 LLM 两段都答，不许吞问题。"""
    user_msg = _last_user_msg(state)
    r = state.get('score_result') or {}
    cat = state.get('category') or r.get('category')
    lng, lat = r.get('lng'), r.get('lat')
    addr = r.get('name') or state.get('address') or ''

    if (lng is None or lat is None) and addr:
        lng, lat = await asyncio.to_thread(geocode, addr)

    if lng is None or lat is None or not cat:
        reply = ('想帮你挖周边竞品口碑，得先有**位置**和**品类**。\n'
                 '告诉我商铺地址，或先做一次分析，比如：'
                 '"宁波天一广场开奶茶店，周边竞品口碑怎么样"。')
        return {
            'messages': state['messages'] + [{'role': 'assistant', 'content': reply}],
            'phase': 'chat', 'compare_pending': False,
        }

    await _emit(state, 'tool', '竞品口碑挖掘',
                input_=(f'{addr or f"({lng:.4f}, {lat:.4f})"} 周边 1000m · {cat}'
                        '（高德公开字段：口碑分/人均/营业时间/招牌标签/团购）'),
                output='抓取中…')

    from engine.competitor_insight import competitor_brief
    insight, brief_txt = await asyncio.to_thread(
        competitor_brief, lng, lat, cat, 1000, 25,
        r.get('brand') or state.get('brand'))

    if not insight:
        await _emit(state, 'tool', '竞品口碑挖掘',
                    input_='高德周边搜索', output='无数据返回')
        reply = ('这次没抓到周边竞品的口碑数据（高德接口无返回或配额受限）。'
                 '我不会编口碑分给你——可以稍后再试，或换个地址/品类。')
        return {
            'messages': state['messages'] + [{'role': 'assistant', 'content': reply}],
            'phase': 'chat', 'compare_pending': False,
        }

    # ---- 专家层：公共铁律 + 竞品分析师 persona ----
    kb_txt = kb_context('竞品 竞争格局 品牌集中度 定价', top_k=2,
                        tags=_expert_kb_tags('competitor_analyst'))
    system_msg = experts.compose_system_prompt('competitor_analyst', kb_text=kb_txt)


    # ---- 复合问题：竞品之外的另一半疑问（如加盟费），补真实参考数据后要求一并回答 ----
    if extra_question:
        from engine.brands import get_franchise_info, supported_brands
        asked_brand = next((b for b in supported_brands() if b in extra_question), None) \
            or state.get('brand')
        info = get_franchise_info(asked_brand) if asked_brand else None
        extra_kb = kb_context(extra_question, top_k=2)

        lines = [f'用户除了竞品，还问了：{extra_question}']
        if info:
            lines.append(f'系统内该品牌（{asked_brand}）加盟政策参考：'
                         f'前期投入约 ¥{info["invest_ref"]:,}（含加盟费/保证金/设备/装修，不含房租押金），'
                         f'年品牌费约 ¥{info["yearly_fee"]:,}（加盟费摊年+管理费，计入月成本合计）。')
        elif asked_brand:
            lines.append(f'系统内暂无 {asked_brand} 的加盟政策参考数据。')
        else:
            lines.append('系统内未识别到具体品牌，无法给出加盟费数字。')
        if isinstance(r.get('profit'), dict) and isinstance(r['profit'].get('前期投入'), (int, float)):
            pf = r['profit']
            lines.append(f'本次已分析商铺的测算口径：前期投入 ¥{pf["前期投入"]:,.0f}，'
                         f'月品牌费 ¥{pf.get("月品牌费") or 0:,.0f}。')

        system_msg += ('\n\n【附加问题与真实参考】\n' + '\n'.join(lines)
                       + '\n7. 回答分两段：先答上面的附加问题，再答竞品格局；'
                         '加盟费/投入只能引用"附加问题与真实参考"里给出的数字，'
                         '没有数据就直说"系统里没有该品牌的公开加盟政策数据，建议直接向品牌方索取招商手册"，'
                         '严禁凭印象编造加盟费。')
        if extra_kb:
            system_msg += f'\n\n【选址知识库·附加问题相关（可参考）】\n{extra_kb}'
        await _emit(state, 'think', '复合意图拆分',
                    f'识别到两个问题：竞品口碑 + 「{extra_question[:40]}」'
                    f'{"（品牌：" + str(asked_brand) + "）" if asked_brand else ""}')

    llm_input = f'用户问题：{user_msg}\n\n{brief_txt}'
    try:
        reply = await call_llm(system_msg, llm_input, temperature=0.4, timeout=120)
        note = '火山方舟·豆包'
    except Exception as e:
        reply = f'（AI 解读暂不可用：{e}，以下是原始数据与规则化洞察）\n\n{brief_txt}'
        note = '原始数据（LLM 暂不可用）'

    rat = insight.get('口碑分') or {}
    cost = insight.get('客单价带') or {}
    await _emit(state, 'tool', f'竞品口碑解读（{note}）',
                input_=f'{insight["样本数"]} 家竞品样本',
                output=(f'口碑均分 {rat.get("均值") or "-"}，人均中位 ¥{cost.get("中位") or "-"}，'
                        f'连锁占比 {insight["连锁占比"]:.0%}，HHI {insight.get("品牌集中度HHI")}；'
                        f'回答 {len(reply)} 字'))

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
    workflow.add_node('collect_brand', collect_brand_node)
    workflow.add_node('collect_invest', collect_invest_node)
    workflow.add_node('search_rental', search_rental_node)
    workflow.add_node('select_shop', select_shop_node)
    workflow.add_node('analyze', analyze_node)
    workflow.add_node('interpret', interpret_node)
    workflow.add_node('free_chat', free_chat_node)
    workflow.add_node('compare', compare_node)
    workflow.add_node('shop_first', collect_shop_first_node)      # 需求3：收 地址/月租/面积
    workflow.add_node('place_first', collect_place_node)          # 入口B：只收地点 -> 搜铺源
    workflow.add_node('reverse_match', reverse_match_node)        # 需求3：四品类反推
    workflow.add_node('diagnose', diagnose_node)                  # 专家层 P1-2：已开店经营诊断

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
            'collect_brand': 'collect_brand',    # 收集奶茶加盟品牌（先于预算）
            'collect_invest': 'collect_invest',  # 收集前期投入/人数
            'analysis': 'analyze',         # 直接分析
            'chat': 'free_chat',           # 自由问答
            'compare': 'compare',          # 对比两个已分析商铺
            'shop_first': 'shop_first',    # 需求3：有铺子但没想好做什么 -> 收三件套
            'place_first': 'place_first',  # 入口B：没铺子只有地点 -> 收地点 -> 搜铺源
            'reverse_match': 'reverse_match',  # 需求3：四品类反推测算
            'diagnose': 'diagnose',        # 专家层 P1-2：已开店 + 有真实流水 -> 经营诊断
        }
    )

    # 信息收集后：搜索候选 / 分析 / 结束（等用户补充）
    workflow.add_conditional_edges(
        'collect_info',
        lambda state: state.get('phase', 'end'),
        {
            'search_rental': 'search_rental',
            'analysis': 'analyze',
            # 2026-09-17 诉求①：有铺子但**没品类**时，collect_info 不再追问品类，
            # 而是转 shop_first（定位 -> 四品类反推）。这条边就是为它加的。
            'shop_first': 'shop_first',
            'collect_brand': END,   # 等用户选品牌，结束本轮
            'collect_invest': END,  # 等用户回答投入，结束本轮
            'select_shop': END,   # 等用户选候选，结束本轮
            'no_shop': END,       # 等用户补地点，结束本轮
            'have_shop': END,     # 等用户补地址/租金，结束本轮
            'intro': END,         # 初始等待，结束本轮
            'end': END,
        }
    )

    # 品牌收集后：齐备 -> 收集投入；未齐备 -> 等用户选（结束本轮）
    workflow.add_conditional_edges(
        'collect_brand',
        lambda state: state.get('phase'),
        {'collect_invest': 'collect_invest', 'end': END, 'collect_brand': END},
    )

    # 前期投入收集后：齐备 -> 分析；未齐备 -> 等用户回答
    workflow.add_conditional_edges(
        'collect_invest',
        lambda state: 'analysis' if state.get('phase') == 'analysis' else 'end',
        {'analysis': 'analyze', 'end': END},
    )

    # 需求3：店铺优先信息收集后：三件套齐备 -> 四品类测算；未齐备 -> 等用户补充
    workflow.add_conditional_edges(
        'shop_first',
        lambda state: state.get('phase'),
        {'reverse_match': 'reverse_match', 'shop_first': END, 'end': END},
    )

    # 入口B（新增）：地点优先。收到地点 -> 去搜在租铺源；还没给 -> 等用户补充
    workflow.add_conditional_edges(
        'place_first',
        lambda state: 'search_rental' if state.get('phase') == 'search_rental' else 'end',
        {'search_rental': 'search_rental', 'end': END},
    )

    # 需求3：四品类测算后 -> 等用户选方向（结束本轮）；信息不足则回收集
    workflow.add_conditional_edges(
        'reverse_match',
        lambda state: 'shop_first' if state.get('phase') == 'shop_first' else 'end',
        {'shop_first': 'shop_first', 'end': END},
    )

    # 专家层 P1-2：已开店诊断 —— 信息缺则追问、齐则出诊断，两种情况都结束本轮
    workflow.add_edge('diagnose', END)

    # 候选搜索后：**直接结束本轮**，等用户选。
    # ⚠️ 2026-09-17 改：原来是 `search_rental -> select_shop`，于是同一轮里
    #    select_shop_node 会再追加一句"请回复上面的序号…"，把 search_rental
    #    刚写好的候选摘要（含**数据可信度**说明）顶掉 —— UI 只显示最后一条消息，
    #    用户看不到"12 家里 8 家是实测、3 家是推算"。本轮不需要 select_shop 做任何事，
    #    下一轮用户给出序号时 classify 会按 prev_phase='select_shop' 再进该节点。
    workflow.add_edge('search_rental', END)

    # 选择商铺后 -> 收集信息（选中的走 collect_invest/analysis 分支，未选等待）
    # 入口B 例外：地点优先选中的铺子**没想好品类** -> 直接进四品类反推，
    # 不能再走 collect_info（它会去问品类，与"用户还没想好"矛盾）。
    workflow.add_conditional_edges(
        'select_shop',
        lambda state: 'reverse_match' if state.get('phase') == 'reverse_match'
        else 'collect_info',
        {'reverse_match': 'reverse_match', 'collect_info': 'collect_info'},
    )

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
    # ⚠️ 必须是 `is None` 判断，不能写 `hooks = hooks or {}` —— 后者会把调用方传进来的
    # **空 dict** 当成"没传"而换成一个新 dict，于是调用方**永远收不到**
    # steps / stage_ms（空 dict 是 falsy）。这个坑在 §4 第 0 步暴露：
    # 想拿真实阶段分布就得 `run_agent(msg, state, hooks)` 跨轮复用同一本账，
    # 而传入的空 dict 被静默丢弃 → 量出来的永远是"最后一轮"的那点数据。
    if hooks is None:
        hooks = {}
    hooks.setdefault('steps', [])
    state['hooks'] = hooks
    state['steps'] = hooks['steps']

    # LLM 降级提示：降级链切换 provider 时，往「执行过程」里写一行，
    # 避免用户看到界面干转却不知道程序正在换模型重试（实测曾卡 8 分钟）。
    try:
        from agent.llm import set_retry_callback
        set_retry_callback(lambda msg: hooks['steps'].append({
            'kind': 'tool', 'name': 'LLM 降级重试', 'text': msg, 'input': '', 'output': ''}))
    except Exception:
        pass

    # recursion_limit: 正常一轮 2~5 个节点; 上限 12 防止逻辑缺陷导致死循环刷爆外部 API
    result = await agent_graph.ainvoke(state, config={'recursion_limit': 12})

    result['steps'] = hooks['steps']
    # §4 第 0 步收尾：把阶段耗时**留一份可序列化的副本**在结果里。
    # 为什么必须留：`hooks` 含回调函数、必须剥离（历史会话要存盘），于是
    # 跑完一轮后 `state['hooks']` 就没了 —— 想事后分析分布只能翻 UI 事件文本，
    # 无法回归、无法比较两次优化前后的差异。stage_ms 本身是 {str: int}，
    # 序列化零成本，留在结果里就能被脚本读、被历史会话带着走。
    result['stage_ms'] = dict(hooks.get('stage_ms') or {})
    # hooks 含回调函数，不可 JSON 序列化（历史会话存储需要），从结果中剥离
    result.pop('hooks', None)
    return result
