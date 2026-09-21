# -*- coding: utf-8 -*-
"""
state.py —— LangGraph 状态定义（TypedDict 版）
==============================================
LangGraph 的 StateGraph 要求状态是 TypedDict，不是 dataclass。
"""
from typing import TypedDict, Optional, List, Dict, Any, Tuple


class AgentState(TypedDict, total=False):
    """选址 Agent 的全局状态（LangGraph 兼容）"""
    
    # 对话历史
    messages: List[Dict[str, str]]

    # 已上传附件（PDF/文本/Word 抽取的正文），供诊断节点/自由对话引用。
    # ⚠️ 必须声明在 schema 里：LangGraph 的 StateGraph 只传递 TypedDict 里声明的字段，
    #   schema 外字段（如 attachments）会在 ainvoke 时被静默丢弃 —— 这正是 2026-09-18
    #   「上传 PDF 后诊断读不到附件、专家反问月流水」的根因。UI 层挂、节点读的都是同一个键。
    attachments: Optional[List[Dict]]
    
    # 用户输入（解析后的结构化信息）
    category: Optional[str]       # 品类：奶茶/甜品/早餐/便利店
    address: Optional[str]        # 具体地址
    rent: Optional[float]         # 月租金
    area: Optional[int]           # 面积（㎡）
    guest: Optional[str]          # 客群定位（学生/白领/社区）
    mode: Optional[str]           # 堂食/外卖
    city: Optional[str]           # 城市
    investment: Optional[float]   # 前期投入成本（元，含装修+设备+首批物料等）
    staff: Optional[int]          # 运营人数（默认：奶茶/甜品/早餐2人、便利店1人）
    brand: Optional[str]          # 加盟品牌名（如"蜜雪冰城"）或"自创品牌"
    
    # 候选商铺（无商铺分支）
    candidates: List[Dict]        # 58/高德候选列表
    selected_idx: Optional[int]   # 用户选择的候选索引
    pending_coord: Optional[Tuple[float, float]]  # 选中商铺的坐标 (lng, lat)
    list_shown: Optional[bool]    # 候选列表是否已展示（避免重复渲染/重复消息）

    # 店铺优先分支（需求3）：已有店铺但没想好做什么
    shop_first_data: Optional[Dict]   # {'address','rent','area','lng','lat'}
    category_recs: Optional[List[Dict]]  # 四品类测算结果（按预估月净利降序）

    # 地点优先分支（入口 B，2026-09-17）：**没有铺子**、只说了想在哪里开店。
    # 与 shop_first 的唯一分界：手里有没有这个铺子。
    # True 时：候选检索 → 选中店铺 → 直接进 reverse_match（四品类反推），
    # 而不是像 A 流程那样去问品类/品牌/预算。
    place_first_mode: Optional[bool]

    # 租金/面积的数据可信度三态（2026-09-17）：
    #   measured    = 平台实测
    #   derived     = 由同区参考带/品类标准面积**推算**
    #   unavailable = 不可得（此时**不出经营评分**，禁止静默用默认 ¥8000）
    rent_state: Optional[str]
    area_state: Optional[str]
    rent_band: Optional[Tuple[float, float]]  # 推算时的区间（元/月），点估计不给

    # 已开店经营诊断（专家层 P1-2，节点 diagnose）
    # ⚠️ 与 score_result 的根本区别：这里的流水是**用户自报的事实**，不是模型预估。
    monthly_revenue: Optional[float]  # 用户自报的实际月流水（元）
    store_diagnosis: Optional[Dict]   # diagnose_existing_store 的返回（成本拆解/毛利口径/安全边际/对标）
    
    # 分析结果
    score_result: Optional[Dict]  # 评分结果
    interpretation: Optional[str] # LLM 解读文本
    
    # 流程控制
    phase: str                    # 当前阶段：intro/have_shop/no_shop/select_shop/analysis/chat
    missing_info: List[str]       # 缺失信息列表
    
    # 上下文（自由问答时用）
    context: Optional[str]        # 当前分析的评分数据 JSON
    
    # 跨会话对比（对比功能）
    comparison: Optional[Dict]    # 两次分析对比数据 {a: {...}, b: {...}}
    compare_pending: Optional[bool]  # 是否在等用户选择两个对比序号
    compare_list: Optional[List[Dict]]  # 供前端渲染"勾选对比"卡片的分析列表（含 shop/category/total/verdict/ts/dims）

    # 专家视角（专家层 P0）：当前选中的专家 id（见 src/experts/registry.py）；
    # 空 = 默认态（找铺向导 / 自动路由）
    expert: Optional[str]

    # 执行过程（实时步骤/思考/工具记录，供前端可折叠面板展示）
    steps: Optional[List[Dict]]   # 步骤日志 [{kind: think|tool, name, text/input/output}]
    hooks: Optional[Dict]         # 事件钩子 {on_event: async callable, steps: list}
