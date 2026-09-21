# -*- coding: utf-8 -*-
"""
toolbox.py —— 专家可调用的**只读工具**（真 function calling 的落点）
=====================================================================
背景（`docs/七项改进方案-待审批.md` §6）：专家 frontmatter 里的
`tools` / `forbids` 曾经**运行时无人读** —— `call_llm()` 签名里根本没有
tools 参数，于是"白名单"只是一份设计期文档，没有任何"调用被拒"这回事。
本模块把那份白名单变成**真的执行边界**：

    toolbox.tool_schemas(expert_id)          -> OpenAI 风格 tools 列表（按该专家白名单）
    toolbox.run_tool(expert_id, name, args)  -> {'ok':bool, 'result':…, 'denied':bool, …}

三条硬约定（都是本项目的既有纪律）：
1. **只读**：这里只放"取数/查询"类工具，绝不写库、绝不改会话状态。
   理由：LLM 的自由调用必须无副作用，否则一次幻觉调用就能污染分析结果。
2. **白名单即边界**：不在 `tools` 里的工具一律拒绝（`denied=True`），
   并把拒绝原因**回给模型**而不是静默丢弃 —— 模型要能告诉用户"我这个角色
   不能做这件事"，这才是专家与裸 LLM 的**可验证差异**。
3. **失败不编造**：取不到就说取不到（`ok=False` + 明确原因），
   由模型转达；绝不用默认值冒充真实数据。
"""
import json
import sys
from pathlib import Path

try:
    from experts import registry
except ImportError:                      # 独立跑时的兜底
    _root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(_root))
    sys.path.insert(0, str(_root / '.pylibs'))
    from experts import registry


# ---------------------------------------------------------------
# 工具实现：全部只读、纯本地（geocode / analyze_competitors 走缓存，不新造数据）
# ---------------------------------------------------------------
def _kb_retrieve(query, top_k=3, tags=None):
    from agent.knowledge import build_context
    txt = build_context(str(query), top_k=int(top_k or 3), tags=tags)
    return {'查询': query, '知识库结果': txt or '（本地知识库无相关条目）'}


def _brand_store_metrics(brand):
    from engine.brands import brand_store_metrics
    m = brand_store_metrics(brand)
    if not m:
        return {'品牌': brand, '结果': '系统内暂无该品牌的公开披露数据'
                '（本表只收录招股书/年报口径、且每行都带证券代码）'}
    return {k: v for k, v in m.items() if v not in (None, '')}


def _brand_order_value(brand):
    from engine.brands import brand_order_value
    v = brand_order_value(brand)
    if not v:
        return {'品牌': brand, '结果': '无公开披露的每单金额，也没有可换算的单杯价'
                '（需带门店坐标走实时取数）'}
    return v


def _brand_attractiveness(name):
    from engine.brands import brand_attractiveness
    brand, s = brand_attractiveness(name)
    return {'输入': name, '归一品牌': brand or '（未识别，按个体/杂牌处理）',
            '品牌引力系数': s}


def _is_self_brand(name):
    from engine.brands import is_self_brand
    return {'输入': name, '是否自创/杂牌': bool(is_self_brand(name))}


def _brand_uplift(name):
    from engine.brands import brand_uplift
    # ⚠️ brand_uplift 返回的是**元组** (品牌名 or None, 系数)，不是裸 float。
    #    不拆元组的话，工具结果会变成 "('蜜雪冰城', 1.0018)"，模型只能靠猜读到 1.001
    #    —— 看起来对，但那是运气；元组一旦变长就会错读。这里显式拆开。
    brand, up = brand_uplift(name)
    if brand is None:
        return {'品牌': name, '结果': '识别不出连锁品牌（严格模式下不给溢价）'}
    return {'品牌': brand, '同商圈溢价系数': up,
            '口径': '9 品牌同商圈标定（UPLIFT）；系数 >1 为正溢价'}


def _brand_uplift_detail(name):
    from engine.brands import brand_uplift_detail
    d = brand_uplift_detail(name)
    return d or {'品牌': name, '结果': '无同商圈标定的品牌溢价明细'}


def _get_franchise_info(brand):
    from engine.brands import get_franchise_info
    v = get_franchise_info(brand)
    return v if v else {'品牌': brand, '结果': '系统内暂无该品牌的加盟信息'}


def _supported_brands():
    from engine.brands import supported_brands
    b = supported_brands()
    return {'支持品牌数': len(b), '品牌': b}


def _get_material_ratio(category, brand=None):
    """物料成本率。brand 可选（2026-09-18 加）—— 有品牌级覆盖时优先。

    为什么需要 brand 这个入参：瑞幸是咖啡连锁，物料率 36%（公司披露），
    与奶茶品类级 32% 不同。若专家只报"奶茶 32%"去答瑞幸的成本问题，
    会系统性低估成本、把回本周期说短 —— 那是**结论方向错**，不是精度问题。
    """
    from engine.utilities import get_material_ratio, BRAND_MATERIAL_RATIO
    r = get_material_ratio(str(category), brand=(str(brand) if brand else None))
    over = bool(brand) and str(brand) in BRAND_MATERIAL_RATIO
    return {'品类': category, '品牌': brand, '物料成本率': r,
            '口径': ('产品口径毛利 = 1 − 物料率 − 损耗率（外卖抽成不进毛利率）；'
                     + ('来源=品牌级覆盖（公司披露），**优先于品类级**' if over
                        else '来源=品类级参考值（无品牌级覆盖）'))}


def _get_delivery_ratio(category):
    from engine.utilities import get_delivery_ratio
    r = get_delivery_ratio(str(category))
    return {'品类': category, '外卖占流水比': r,
            '口径注意': '这是"外卖占流水比"，不是佣金率；抽成 = 占流水比 × 22%'}


def _estimate_monthly_utility(category, area_m2, city='宁波'):
    from engine.utilities import estimate_monthly_utility
    u = estimate_monthly_utility(str(category), float(area_m2), str(city))
    return u if isinstance(u, dict) else {'结果': u}


def _estimate_profit(category, area_m2, city, monthly_rent, staff=None):
    from engine.utilities import estimate_profit
    p = estimate_profit(str(category), float(area_m2), str(city),
                        float(monthly_rent),
                        staff=(int(staff) if staff else None))
    return p if isinstance(p, dict) else {'结果': p}


def _estimate_profit_bands(category, area_m2, city, monthly_rent):
    from engine.utilities import estimate_profit_bands
    b = estimate_profit_bands(str(category), float(area_m2), str(city),
                              float(monthly_rent))
    return b if isinstance(b, dict) else {'结果': b}


def _geocode(address):
    from engine.realtime import geocode
    r = geocode(str(address))
    if not r:
        return {'地址': address, '结果': '地理编码失败（地址无法解析为坐标）'}
    lng, lat = r
    return {'地址': address, '经度': lng, '纬度': lat}


def _analyze_competitors(lng, lat, category, radius=1000):
    from engine.competitor_insight import analyze_competitors
    return analyze_competitors(float(lng), float(lat), str(category),
                               radius=int(radius or 1000))


def _competitor_brief(lng, lat, category, brand=None, radius=1000):
    from engine.competitor_insight import competitor_brief
    return competitor_brief(float(lng), float(lat), str(category),
                            brand=brand, radius=int(radius or 1000))


def _fetch_shops_tool(city, area_filter=None, limit=12):
    """抓真实在租商铺（供"地点优先"场景下的品类反推顾问使用）。

    返回**统计 + 样本**而不是全量：模型不需要 60 条明细，
    它需要"这一带现在什么价位、有没有适合小店的小面积铺"。
    ⚠️ 取数失败与"真的没有"必须分开（`ok` 字段）——
    否则模型会把一次抓取失败说成"这个区没有在租铺子"。
    """
    from agent.rental58 import fetch_shops
    try:
        n = max(1, min(int(limit or 12), 30))
    except Exception:
        n = 12
    meta = {}
    rows = fetch_shops(str(city), limit=n, area_filter=(area_filter or None),
                       pages=1, meta=meta)
    if meta.get('ok') is False or not rows:
        return {'城市': city, '区域': area_filter, '取数成功': bool(meta.get('ok')),
                '条数': 0,
                '说明': (meta.get('reason') or '取数失败') if meta.get('ok') is False
                        else '本次抓取没有匹配到在租条目（可能是区域词过窄）'}
    prices = [r['price'] for r in rows if r.get('price')]
    areas = [r['area'] for r in rows if r.get('area')]
    return {
        '城市': city, '区域': area_filter, '取数成功': True, '条数': len(rows),
        '口径': f'{meta.get("source")}列表页挂牌信息（非成交价）；抓取时间 {meta.get("fetched_at")}',
        '字段缺失': {'缺租金': len(rows) - len(prices), '缺面积': len(rows) - len(areas)},
        '月租范围': [min(prices), max(prices)] if prices else None,
        '面积范围': [min(areas), max(areas)] if areas else None,
        '样本': [{'标题': (r.get('title') or '')[:26],
                  '位置': r.get('loc') or '',
                  '月租': r.get('price'), '面积': r.get('area')} for r in rows[:8]],
    }


# ---------------------------------------------------------------
# 工具目录：name -> {desc, params(JSON Schema), fn}
# 只登记"可脱离完整选址上下文、纯本地即可跑"的工具。
# 其余 VOCAB 里的名字（score_site / solve_rent_limits / negotiation_brief …）
# 需要坐标、租金、整份评分等上下文，本层**不臆造默认值**，调用时如实回复
# "需要会话上下文"，由节点把已算好的证据直接给模型。
# ---------------------------------------------------------------
def _schema(name, description, properties, required):
    return {'type': 'function', 'function': {
        'name': name, 'description': description,
        'parameters': {'type': 'object', 'properties': properties,
                       'required': required}}}


TOOLS = {
    'kb_retrieve': {
        'fn': _kb_retrieve,
        'schema': _schema(
            'kb_retrieve', '检索系统内置的选址/经营/政策知识库（本地 TF-IDF，0 次外部 API）。'
            '本角色只能检索自己分区内的语料。',
            {'query': {'type': 'string', 'description': '检索问题或关键词'},
             'top_k': {'type': 'integer', 'description': '返回条数，默认 3'}},
            ['query'])},
    'brand_store_metrics': {
        'fn': _brand_store_metrics,
        'schema': _schema('brand_store_metrics',
                          '取品牌级公开披露经营数据（招股书/年报口径：单店日均GMV、'
                          '每单平均金额、单杯均价、每单杯数）。',
                          {'brand': {'type': 'string'}}, ['brand'])},
    'brand_order_value': {
        'fn': _brand_order_value,
        'schema': _schema('brand_order_value',
                          '取品牌级「每单金额」（元/单）：优先公开披露值，'
                          '否则单杯价×每单杯数换算。',
                          {'brand': {'type': 'string'}}, ['brand'])},
    'brand_attractiveness': {
        'fn': _brand_attractiveness,
        'schema': _schema('brand_attractiveness',
                          '把店名/品牌名归一为登记品牌，并返回品牌引力系数 S。',
                          {'name': {'type': 'string'}}, ['name'])},
    'is_self_brand': {
        'fn': _is_self_brand,
        'schema': _schema('is_self_brand',
                          '判断是否为自创品牌/个体经营（没有同品牌连锁门店可作参照）。',
                          {'name': {'type': 'string'}}, ['name'])},
    'brand_uplift': {
        'fn': _brand_uplift,
        'schema': _schema('brand_uplift',
                          '取该品牌在同商圈口径下的溢价系数（UPLIFT，9 品牌标定）。',
                          {'name': {'type': 'string'}}, ['name'])},
    'brand_uplift_detail': {
        'fn': _brand_uplift_detail,
        'schema': _schema('brand_uplift_detail',
                          '取品牌溢价的明细：TIER 分级、样本量、置信区间。',
                          {'name': {'type': 'string'}}, ['name'])},
    'get_franchise_info': {
        'fn': _get_franchise_info,
        'schema': _schema('get_franchise_info',
                          '取加盟信息（前期投入构成、年品牌费口径）。',
                          {'brand': {'type': 'string'}}, ['brand'])},
    'supported_brands': {
        'fn': _supported_brands,
        'schema': _schema('supported_brands', '列出系统内已登记的品牌。', {}, [])},
    'get_material_ratio': {
        'fn': _get_material_ratio,
        'schema': _schema('get_material_ratio',
                          '取物料成本率。传 brand 可拿到品牌级覆盖值（如瑞幸咖啡 36%，'
                          '与奶茶品类级 32% 不同）——问某个**具体品牌**的成本时必须传 brand。',
                          {'category': {'type': 'string'},
                           'brand': {'type': 'string',
                                     'description': '品牌名（可选）；不传则用品类级参考值'}},
                          ['category'])},
    'get_delivery_ratio': {
        'fn': _get_delivery_ratio,
        'schema': _schema('get_delivery_ratio', '取品类的外卖占流水比。',
                          {'category': {'type': 'string'}}, ['category'])},
    'estimate_monthly_utility': {
        'fn': _estimate_monthly_utility,
        'schema': _schema('estimate_monthly_utility',
                          '按品类/面积/城市估算月水电成本。',
                          {'category': {'type': 'string'},
                           'area_m2': {'type': 'number'},
                           'city': {'type': 'string'}},
                          ['category', 'area_m2'])},
    # 2026-09-17 新增（入口 B「地点优先」）：
    # 品类反推顾问现在**真的能去找铺子**了 —— 用户只给地点时，它得先有铺源。
    # 这是一个"能验证的差异"（§6 壁垒）：专家可以真的拉回一批在租铺（含租金/面积），
    # 而不是只能说"我没权限"。取数纪律：返回里带 meta（取数失败 ≠ 真的没有）。
    'fetch_shops': {
        'fn': _fetch_shops_tool,
        'schema': _schema('fetch_shops',
                          '抓取某城市/区域的**真实在租商铺**（58同城列表页，含月租与面积）。'
                          'areas_filter 用区域或街道关键词（如"滨江""鄞州"）。'
                          '返回条目数、字段缺失统计与样本；'
                          '⚠️ 返回的是挂牌信息（非成交价），且平台每次返回条数会变。',
                          {'city': {'type': 'string', 'description': '城市名，如"杭州"'},
                           'area_filter': {'type': 'string', 'description': '区域/街道关键词，可省略'},
                           'limit': {'type': 'integer', 'description': '条数上限，默认 12，最多 30'}},
                          ['city'])},
    'estimate_profit': {
        'fn': _estimate_profit,
        'schema': _schema('estimate_profit',
                          '按品类/面积/城市/月租估算月度盈亏（中性档）。'
                          '返回月流水、成本拆解、月净利、回本周期、三种毛利口径。',
                          {'category': {'type': 'string'}, 'area_m2': {'type': 'number'},
                           'city': {'type': 'string'}, 'monthly_rent': {'type': 'number'},
                           'staff': {'type': 'integer'}},
                          ['category', 'area_m2', 'city', 'monthly_rent'])},
    'estimate_profit_bands': {
        'fn': _estimate_profit_bands,
        'schema': _schema('estimate_profit_bands',
                          '同上，但并列乐观/中性/保守三档情景（不要只报一档）。',
                          {'category': {'type': 'string'}, 'area_m2': {'type': 'number'},
                           'city': {'type': 'string'}, 'monthly_rent': {'type': 'number'}},
                          ['category', 'area_m2', 'city', 'monthly_rent'])},
    'geocode': {
        'fn': _geocode,
        'schema': _schema('geocode', '把中文地址解析为经纬度（带缓存）。',
                          {'address': {'type': 'string'}}, ['address'])},
    'analyze_competitors': {
        'fn': _analyze_competitors,
        'schema': _schema('analyze_competitors',
                          '分析某坐标周边的竞品结构（口碑分/人均价格带/连锁占比/HHI）。',
                          {'lng': {'type': 'number'}, 'lat': {'type': 'number'},
                           'category': {'type': 'string'},
                           'radius': {'type': 'integer', 'description': '米，默认 1000'}},
                          ['lng', 'lat', 'category'])},
    'competitor_brief': {
        'fn': _competitor_brief,
        'schema': _schema('competitor_brief',
                          '取竞品简报（含指定品牌的参照组价格校验）。',
                          {'lng': {'type': 'number'}, 'lat': {'type': 'number'},
                           'category': {'type': 'string'},
                           'brand': {'type': 'string'},
                           'radius': {'type': 'integer'}},
                          ['lng', 'lat', 'category'])},
}

# 需要完整会话上下文的工具：如实拒绝，不臆造默认参数。
_CONTEXT_ONLY = {
    'score_site': '完整评分需坐标 + 品类 + 月租 + 面积，请在分析流程里触发；'
                  '本工具不在对话中重算，避免与已展示的结果不一致',
    'elasticity_band': '口径区间已随评分结果一并给出，无需重算',
    'solve_rent_limits': '租金临界点已在评分结果里给出，无需重算',
    'compare_sites': '跨店对比请在「对比」入口查看已保存的分析',
    'apply_storefront': '形象分已并入评分结果，不单独调用',
    'reverse_match': '四品类反推在「店铺优先」流程里触发',
    'analyze_storefront': '门头照只能由用户在会话中上传，工具无法凭空取图',
    'diagnose_existing_store': '已开店诊断需要你自报的月流水/月租，请在诊断流程里填',
    'brand_benchmark': '品牌基准对标随经营诊断一并给出',
    'negotiation_brief': '谈判筹码随租金谈判一并给出（需要承受力上限）',
    'rent_benchmark': '行情参考带随租金谈判一并给出',
    'brand_price_reference': '客单价校正需要门店坐标，随评分流程一并完成',
    'list_analyses': '历史分析请在左侧历史入口查看',
    'add_analysis': '保存分析由系统在解读完成后自动完成',
    'rule_based_interpret': '规则解读是 LLM 不可用时的兜底，不供模型主动调用',
}


def allowed_tools(expert_id: str) -> set:
    """该专家**实际可调用**的工具集 = tools − forbids（forbids 优先级更高）。"""
    ex = registry.get_expert(expert_id)
    return set(ex.tools or []) - set(ex.forbids or [])


def tool_schemas(expert_id: str) -> list:
    """按白名单过滤出 OpenAI 风格 tools 列表。未实现的工具**不暴露**。"""
    allow = allowed_tools(expert_id)
    return [TOOLS[n]['schema'] for n in sorted(allow) if n in TOOLS]


def run_tool(expert_id: str, name: str, args) -> dict:
    """执行一次工具调用，返回可 JSON 序列化的结果。

    - 不在白名单 / 被 forbids 命中 → {'ok': False, 'denied': True, ...}
      （**拒绝要回给模型**，不是静默丢弃 —— 这是专家能力的可验证边界）
    - 在 VOCAB 但属于"需要上下文"的工具 → ok=False，说明为什么不在对话里重算
    - 未登记 → ok=False
    """
    ex = registry.get_expert(expert_id)
    allow = allowed_tools(expert_id)
    try:
        a = json.loads(args) if isinstance(args, str) else (args or {})
    except Exception:
        return {'ok': False, 'denied': False, 'error': f'参数不是合法 JSON：{args!r}'}
    if not isinstance(a, dict):
        return {'ok': False, 'denied': False, 'error': '参数必须是 JSON 对象'}

    if name not in allow:
        why = ('该能力被明确禁止' if name in (ex.forbids or [])
               else '不在你的工具白名单内')
        return {'ok': False, 'denied': True,
                'error': f'调用被拒：「{name}」{why}。'
                         f'你现在的角色是 {ex.name}（{ex.alias}），'
                         f'可用的工具只有：{"、".join(sorted(allow)) or "无"}。'
                         f'请说明这不在你的职责范围，不要编造该能力的结果。'}

    if name in _CONTEXT_ONLY:
        return {'ok': False, 'denied': False,
                'error': f'「{name}」{_CONTEXT_ONLY[name]}。'
                         f'请直接引用会话中已给出的证据。'}

    if name not in TOOLS:
        return {'ok': False, 'denied': False,
                'error': f'「{name}」尚未在本系统中实现'}

    kw = dict(a)
    if name == 'kb_retrieve':
        # 分区检索：把专家声明的 kb_tags 作为默认过滤，与节点内的 RAG 行为一致
        kw.setdefault('tags', ex.kb_tags or None)
    try:
        return {'ok': True, 'result': TOOLS[name]['fn'](**kw)}
    except TypeError as e:
        return {'ok': False, 'denied': False,
                'error': f'参数不匹配：{e}。请按 schema 重填参数。'}
    except Exception as e:
        return {'ok': False, 'denied': False,
                'error': f'执行失败（{type(e).__name__}: {e}）'}


if __name__ == '__main__':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    for e in registry.list_experts():
        allow = allowed_tools(e.id)
        runnable = sorted(n for n in allow if n in TOOLS)
        print(f'{e.alias}·{e.name:<10} 声明 {len(allow)} 个，'
              f'可执行 {len(runnable)} 个 → {runnable}')
