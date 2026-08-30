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
    
    # 候选商铺（无商铺分支）
    candidates: List[Dict]        # 58/高德候选列表
    selected_idx: Optional[int]   # 用户选择的候选索引
    pending_coord: Optional[Tuple[float, float]]  # 选中商铺的坐标 (lng, lat)
    list_shown: Optional[bool]    # 候选列表是否已展示（避免重复渲染/重复消息）
    
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

    # 执行过程（实时步骤/思考/工具记录，供前端可折叠面板展示）
    steps: Optional[List[Dict]]   # 步骤日志 [{kind: think|tool, name, text/input/output}]
    hooks: Optional[Dict]         # 事件钩子 {on_event: async callable, steps: list}
