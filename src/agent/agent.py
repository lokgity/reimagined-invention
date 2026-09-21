# -*- coding: utf-8 -*-
"""
agent.py —— 选址领域逻辑层（无状态纯函数）
=================================
职责（被 agent_graph.py 复用，Chainlit 是唯一入口）:
- 口语信息抽取: 品类/租金/地址/客群/堂食外卖/面积/品牌（规则层，保证稳定）
- 规则兜底解读: LLM 不可用时也能输出合格结论（rule_based_interpret）
- 地理编码: 高德 API 优先 + 本地 POI 库兜底 + 浙江范围校验 + 磁盘缓存

设计取舍（答辩导向）:
1. 评分必须确定性（同一输入同一结果），不能因为 LLM 抖动改变分数
2. 演示稳定 > 花哨：即使 LLM 调用失败，也有基于规则的兜底解读
3. 所有数据结论可追溯到评分引擎和本地数据库

对话编排（阶段流转/节点路由/LLM 调用）在 agent_graph.py，不在本文件。
"""
import re
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 常用口语词 -> 品类
CATEGORY_ALIASES = {
    '奶茶': ['奶茶', '茶饮', '奶茶店', '新茶饮'],
    '甜品': ['甜品', '蛋糕', '烘焙', '糖水', '面包'],
    '早餐': ['早餐', '早点', '包子', '煎饼', '肠粉', '豆浆', '早饭'],
    '便利店': ['便利店', '超市', '小卖部'],
}
# 地址识别: 城市 + 区/县 + 具体地点(路/街/号/大厦/广场等), 贪婪匹配完整地址
# 贪婪 + 明确结尾词, 避免截断成"杭州滨江"
ADDR_PATTERN = re.compile(
    r'(杭州|宁波|温州|嘉兴|湖州|绍兴|金华|衢州|舟山|台州|丽水)'
    r'([\u4e00-\u9fa5A-Za-z0-9]{1,30}?)'
    r'(?:区|县|市)?'
    r'([\u4e00-\u9fa5A-Za-z0-9]{1,40})'
    r'(?=，|。|,|\.|$|的|开|月租|租金|房租|预算|面积|平方|平米)'
)
# 无城市前缀的纯地点（"下沙""文三路"），交给 geocode 解析 + 浙江范围校验
LOCALITY_PATTERN = re.compile(
    r'(下沙|文三路|文二路|延安路|湖滨|武林|滨江|钱江新城|未来科技城|'
    r'五马街|老外滩|天一广场|万达广场|银泰|万象城|大悦城|南湖|东钱湖)'
)
RENT_PATTERN = re.compile(
    r'(月租|租金|房租|预算)[^\d]{0,6}'
    r'(\d+(?:\.\d+)?)\s*(万|千|k|w|元)?'
    r'(?:(\d+)\s*(百)?)?',  # 支持 "1万5" "2千5" 这种口语
    re.IGNORECASE,
)
# "预算"有歧义：既可能是月租，也可能是装修/前期投入。上文出现这些词就不是月租
_BUDGET_NOT_RENT = ('装修', '装潢', '投入', '加盟', '转让', '设备', '建店', '改造', '前期')
# 本工具面向 10~100㎡ 小铺，月租到不了 5 万量级；"预算"超过这个数一律当投入
_RENT_PLAUSIBLE_MAX = 50000


# ---------------------------------------------------------------
# 1. 信息抽取（规则层，保证稳定）
# ---------------------------------------------------------------
def extract_category(text: str):
    for cat, aliases in CATEGORY_ALIASES.items():
        for a in aliases:
            if a in text:
                return cat
    return None


def _apply_unit(num_s, unit, extra=None) -> float:
    """把「数字 + 单位 + 口语尾数」换算成元。

    处理三种写法：① 普通单位（万/千/k/w）；② 口语连读 "1万5"（=15000）、
    "2千5"（=2500）—— 尾数按主单位进位（万级 +千、千级 +百）；
    ③ 无单位时按元。`extract_rent` 与 `extract_monthly_revenue` 共用，
    避免两处换算漂移（同一个"1万5"在租金和流水上必须解释成同一个数）。
    """
    num = float(num_s)
    unit = (unit or '').lower()
    if unit in ('千', 'k'):
        num *= 1000
    elif unit in ('万', 'w'):
        num *= 10000
    if extra:
        num += float(extra) * (1000 if unit in ('万', 'w') else 100)
    return num


def extract_rent(text: str):
    """提取月租(元)。

    坑（2026-09-14 实测踩到）："装修预算20万"曾被当成月租 20 万，覆盖掉用户先前给的
    月租 12000，把租金承受力打成 0 分、盈利测算与结论全错。所以"预算"这个触发词必须
    过闸：上文指向装修/投入就不算月租，金额超出小铺月租量级也不算。
    明确的"月租/租金/房租"无条件采信（用户改口重报租金要能生效）。
    """
    for m in RENT_PATTERN.finditer(text or ''):
        trigger = m.group(1)
        num = _apply_unit(m.group(2), m.group(3), m.group(4))

        if trigger == '预算':
            before = (text or '')[:m.start()][-6:]
            if any(k in before for k in _BUDGET_NOT_RENT):
                continue        # 装修预算/前期投入预算 → 不是月租
            if num > _RENT_PLAUSIBLE_MAX:
                continue        # "预算20万" 这种量级只能是投入
        return int(num)
    return None


# 月流水/营业额（已开店诊断用）：与月租是两码事，量级通常更大，且可能按"日"报。
# 用词与 RENT_PATTERN 不重叠（租金/房租/预算），所以两个抽取器互不干扰。
REVENUE_PATTERN = re.compile(
    r'(月流水|月营业额|月营收|月均流水|月销售|月销额|销售额|营业额|营收|流水|月收入)'
    r'[^\d]{0,6}(\d+(?:\.\d+)?)\s*(万|千|k|w|元)?'
    r'(?:(\d+)\s*(百)?)?',
    re.IGNORECASE,
)
# "日流水 3000" / "日营业额 1.2万" —— 命中后 ×30 折月。必须先于上面的通用式判断，
# 否则"日流水3000"里的"流水"会被 REVENUE_PATTERN 当成月流水直接采信（差 30 倍）。
DAILY_REVENUE_PATTERN = re.compile(
    r'(?:日均|日|平均每天|一天)[^\d]{0,4}'
    r'(?:流水|营业额|营收|销售额|卖)\s*(\d+(?:\.\d+)?)\s*(万|千|k|w|元)?',
    re.IGNORECASE,
)


def extract_monthly_revenue(text: str):
    """提取**月流水**（元）——已开店诊断的必需输入。

    三种报法都支持：① 月流水/月营业额/营收（直采）；② "日流水 3000"（×30 折月）；
    ③ "1万5" 这种口语连读（复用 `_apply_unit`，与月租同一套释义）。
    提取不到返回 None（**绝不猜**：诊断要求真数，宁可追问）。
    """
    t = text or ''
    md = DAILY_REVENUE_PATTERN.search(t)
    if md:
        return int(_apply_unit(md.group(1), md.group(2)) * 30)
    mm = REVENUE_PATTERN.search(t)
    if mm:
        return int(_apply_unit(mm.group(2), mm.group(3), mm.group(4)))
    return None


def extract_address(text: str):
    """提取地址。优先"城市+地点"；否则匹配知名区域名（下沙/文三路等）。"""
    m = ADDR_PATTERN.search(text)
    if m and len(m.group(0)) >= 3:
        return m.group(0)
    m2 = LOCALITY_PATTERN.search(text)
    if m2:
        return m2.group(0)
    return None


def parse_request(text: str) -> dict:
    return {
        'category': extract_category(text),
        'rent': extract_rent(text),
        'address': extract_address(text),
    }


# ---------------------------------------------------------------
# 2. 兜底解读（LLM 不可用时也能输出合格结论）
# ---------------------------------------------------------------
def rule_based_interpret(result: dict) -> str:
    r = result
    veto = r.get('veto') or {}
    rl = r.get('rent_limits') or {}
    head = f"【{r['name'] or '该地址'}】总分 {r['total']} —— {r['verdict']}"
    if veto.get('触发'):
        head = (f"【{r['name'] or '该地址'}】位置分 {r['total']}（{veto.get('位置分结论')}）"
                f" —— 综合结论：{r['verdict']}｜🚫 {veto.get('原因')}")
    lines = [head]
    for dim, score in r['dims'].items():
        lines.append(f"  {dim}: {score}分")
    e = r['evidence']
    lines.append(f"  证据: 周边竞品 {e['竞品数']} 家，"
                 f"真Huff捕获份额 {e['捕获份额P']:.1%}，"
                 f"客群引力 {e['客群引力累计']}，"
                 f"最近通勤点 {e['最近通勤点(m)']}米，"
                 f"预估月流水 ¥{e['预估月流水']:,}，"
                 f"租金占流水 {e['租金占流水比']}")
    if e.get('客单价'):
        pc = r.get('客单价校正') or {}
        _x = f"  💲 客单价 ¥{e['客单价']:g}（{e.get('客单价来源', '-')}）"
        if pc.get('校正倍数'):
            _x += f"，品类画像 ¥{pc.get('品类画像客单价')}，相差 {pc['校正倍数']} 倍"
        lines.append(_x)
        if pc.get('口径'):
            lines.append(f"     ↳ {pc['口径']}")
    # 水电/盈利测算
    if r.get('utility'):
        u = r['utility']
        lines.append(f"  💡 水电测算({u['城市']}): 电价{u['电价(元/度)']}元/度 水价{u['水价(元/吨)']}元/吨，"
                     f"月水电合计 ¥{u['水电合计(元/月)']:,}")
    if r.get('profit'):
        p = r['profit']
        pb = f"{p['回本周期(月)']}个月" if p['回本周期(月)'] else '无法回本'
        lines.append(f"  💰 盈利测算（中性档）: 前期投入 ¥{p['前期投入']:,}（{p['投入来源']}），"
                     f"月人工 ¥{p['月人工']:,}（{p['人数']}人×¥{p['人均月薪']:,}），"
                     f"月物料 ¥{p['月物料成本']:,}，月成本合计 ¥{p['月成本合计']:,}，"
                     f"月净利 {p['月净利估算']:,} 元，回本周期 {pb}，{p['盈亏判断']}")
        # 单点数字会被当成预测。三档并列才能回答"你这个净利率怎么算的"——
        # 答案是"取决于商场扣点和产能假设"，把不确定性摊开而不是藏起来。
        bands = r.get('profit_bands')
        if bands:
            seg = []
            for n in ('乐观', '中性', '保守'):
                b = bands[n]
                bpb = f"{b['回本周期(月)']}个月" if b['回本周期(月)'] else '无法回本'
                seg.append(f"{n} 净利 {b['月净利估算']:,} 元"
                           f"（净利率 {(b['净利率'] or 0):.0%}、{b['人数']}人、回本 {bpb}）")
            lines.append('  📊 三档情景区间: ' + ' ｜ '.join(seg))
            lines.append(f"     ↳ {bands['区间']['结论']}。{bands['区间']['口径']}")
        # 口径区间：与三档情景**正交**（那三档变成本假设，这一档变需求假设）。
        # LLM 不可用时这条就是用户唯一能看到的说明，更不能省——否则上面那串
        # 中性档数字会被原样当成承诺。
        _cal = r.get('口径区间') or {}
        _civ = _cal.get('区间') or {}
        if _civ:
            seg = []
            for _t in (_cal.get('档位') or []):
                _tpb = f"{_t['回本周期(月)']}个月" if _t.get('回本周期(月)') else '难以回本'
                seg.append(f"{_t['口径']} 流水 ¥{_t['月流水']:,}、净利 ¥{_t['月净利']:,} 元、"
                           f"回本 {_tpb}")
            lines.append('  🎯 口径区间（价格-单量弹性未标定）: ' + ' ｜ '.join(seg))
            lines.append(f"     ↳ {_civ.get('结论')}。{_civ.get('口径')}")
    # 租金临界点：这是唯一能直接拿去谈判的数字，兜底文案也不能省
    if rl:
        be = rl.get('盈亏平衡月租')
        cap = rl.get('回本达标月租上限')
        rent_now = r.get('monthly_rent') or 0
        if be is None:
            be_txt = '不存在——免租也亏损，问题在客流/成本结构，谈租金救不回来'
        elif be >= rent_now:
            be_txt = f'¥{be:,}（当前 ¥{rent_now:,}，安全垫 ¥{be - rent_now:,}）'
        else:
            be_txt = f'¥{be:,}（当前 ¥{rent_now:,}，已超出 ¥{rent_now - be:,}）'
        from engine.scoring import PAYBACK_LIMIT_MONTHS
        cap_txt = (f'；{PAYBACK_LIMIT_MONTHS}个月回本上限 ¥{cap:,}'
                   + (f'（比不亏线再低 ¥{be - cap:,}）' if be and cap < be else '') if cap else '')
        lines.append(f"  🎯 租金临界点: 盈亏平衡月租 {be_txt}{cap_txt}"
                     f"；免租压力测试 月净利 {rl.get('免租月净利'):,} 元")
    if r['warnings']:
        for w in r['warnings']:
            lines.append(f"  {w}")
    lines.append("  ⚠️ 以上基于公开POI数据，不含真实人流量与成交租金，水电为参考标准，建议现场复核。")
    return '\n'.join(lines)


def _pct(v, digits=1):
    """百分比格式化；None 返回 '—'（毛利率/净利率在变动成本率≥100% 时为 None）。"""
    return f'{v:.{digits}%}' if isinstance(v, (int, float)) else '—'


def rule_based_diagnosis(r: dict) -> str:
    """已开店诊断的**规则兜底文案**（LLM 不可用时用）。

    与 `rule_based_interpret` 的分工：那个解读"选址预估"，这个只排版"已开店拆解"。
    结论本身由引擎 `store_diagnosis.diagnose_existing_store` 给出（`诊断` 字段是
    有依据的判断），本函数**不新增任何判断**，只把数字与结论摆清楚、并原样带上局限。
    """
    inp = r.get('输入') or {}
    cost = r.get('成本拆解') or {}
    brand = r.get('品牌') or '自创/未指定品牌'
    lines = [f"【已开店诊断】{r.get('品类') or '—'} · {brand}"
             + (f"（{r.get('情景')}档）" if r.get('情景') else '')]

    lines.append(f"  📥 实际月流水 ¥{inp.get('实际月流水', 0):,.0f}　"
                 f"月租金 ¥{inp.get('实际月租金', 0):,.0f}　"
                 f"{inp.get('面积', '—')}㎡　{inp.get('人数', '—')}人")

    # 三种毛利口径并列 —— 只给一个必然误导（口径定义见 store_diagnosis.py）
    lines.append(f"  💰 毛利率 {_pct(r.get('毛利率'))}（产品口径：扣物料与损耗）"
                 f"｜外卖抽成占流水 {_pct(r.get('外卖抽成占流水比'))}"
                 f"｜扣渠道后 {_pct(r.get('扣渠道后毛利率'))}"
                 f"｜净利率 {_pct(r.get('净利率'))}")
    lines.append(f"     ↳ {r.get('毛利率口径') or ''}")

    _money = [(k, v) for k, v in cost.items() if isinstance(v, (int, float))]
    if _money:
        lines.append('  📋 成本拆解：' + '　'.join(f'{k} ¥{v:,.0f}' for k, v in _money))

    if r.get('盈亏平衡月流水') is not None:
        lines.append(f"  🎯 盈亏平衡月流水 ¥{r['盈亏平衡月流水']:,}"
                     f"（安全边际 {_pct(r.get('安全边际率'))}，"
                     f"即还能跌 ¥{r.get('安全边际额', 0):,}/月）")
    if r.get('租金余量') is not None:
        lines.append(f"  🏠 盈亏平衡月租 ¥{r['盈亏平衡月租']:,}"
                     f"；租金余量 ¥{r['租金余量']:,}/月")

    bench = r.get('品牌对标')
    if bench:
        lines.append(f"  📊 品牌公开基准 {bench.get('你/基准')}×"
                     f"（基准 ¥{bench.get('基准月流水', 0):,}/月，"
                     f"期间 {bench.get('期间')}，{bench.get('来源')}）")

    for t in (r.get('诊断') or []):
        lines.append(f"  · {t}")
    for w in (r.get('局限') or []):
        lines.append(f"  ⚠️ {w}")
    return '\n'.join(lines)


# ---------------------------------------------------------------
# 3. 口语信息抽取（客群定位 / 堂食外卖 / 面积 / 品牌）
# ---------------------------------------------------------------
GUEST_ALIASES = {
    '学生': ['学生', '大学生', '校园', '学校客群'],
    '白领': ['白领', '上班族', '写字楼客群', '办公'],
    '社区': ['社区', '居民', '家庭', '小区客群'],
    '商圈': ['商圈', '逛街', '游客', '商场'],
}
MODE_ALIASES = {
    '堂食': ['堂食', '坐店', '店内'],
    '外卖': ['外卖', '外带', '带走'],
}


def extract_guest(text: str):
    for label, aliases in GUEST_ALIASES.items():
        if any(a in text for a in aliases):
            return label
    return None


def extract_mode(text: str):
    for label, aliases in MODE_ALIASES.items():
        if any(a in text for a in aliases):
            return label
    return None


def extract_area(text: str):
    m = re.search(r'(面积|平方|平米|㎡|m²|方)[^\d]{0,4}(\d+)', text)
    if m:
        return int(m.group(2))
    return None


def extract_brand(text: str):
    """从用户文本识别加盟品牌（复用引擎品牌关键词表）。
    返回品牌名 / '自创品牌' / None。"""
    from engine.brands import BRAND_KEYWORDS
    if any(k in text for k in ['自创', '自己创', '自己的牌', '自家牌', '不加盟', '个体', '杂牌']):
        return '自创品牌'
    for brand, kws in BRAND_KEYWORDS.items():
        for kw in kws:
            if kw in text:
                return brand
    return None


def _clean_area(area):
    """清洗区域字符串: 去掉"的商铺/的奶茶店/附近/周边/一带"等后缀,
    只保留"城市+区/县"(如"宁波鄞州区的商铺"->"宁波鄞州区"、
    "杭州滨江的奶茶店"->"杭州滨江")。"""
    t = (area or '').strip()
    # 按长度降序优先匹配长后缀, 避免"的店"先吃掉"的奶茶店"的一部分
    suffixes = [
        '的一个铺子', '的一个店面', '的奶茶店', '的甜品店', '的早餐店', '的便利店',
        '的商铺', '的店铺', '的铺子', '的店面', '的店面出租',
        '奶茶店', '甜品店', '早餐店', '便利店', '茶饮店',
        '商铺', '店铺', '铺子', '店面', '门面',
        '附近', '周边', '一带', '地段', '区域',
        # 2026-09-17：口语里的"开店意向"尾巴也要剥掉。
        # 否则「我想在滨江开店」抽出的地址是「滨江开店」，进了 search_rental
        # 会被当成 area_filter='滨江开店' → 58 一条都匹配不上（实测踩到）。
        '做点小生意', '做点生意', '做生意',
        '开一家店', '开一个店', '开个店', '开家店', '开一间店', '开一家', '开一间',
        '想去开', '想开', '去看看', '去看看铺子', '开个', '开店',
    ]
    for suffix in suffixes:
        if t.endswith(suffix):
            t = t[: -len(suffix)]
            break
    # 尾巴上残留的介词/动词(如"滨江开""滨江的")继续剥掉
    for junk in ['的', '开', '找', '租', '在', '里']:
        while t.endswith(junk) and len(t) > 2:
            t = t[: -len(junk)]
    return t or area


# ---------------------------------------------------------------
# 4. 地理编码（高德 API 优先 + 本地库兜底 + 浙江范围校验）
# ---------------------------------------------------------------
# 浙江省边界近似范围（用于校验解析结果是否落在浙江）
ZJ_BOUNDS = {'lng': (118.0, 123.5), 'lat': (27.0, 31.5)}


def _in_zhejiang(lng, lat):
    return (ZJ_BOUNDS['lng'][0] <= lng <= ZJ_BOUNDS['lng'][1]
            and ZJ_BOUNDS['lat'][0] <= lat <= ZJ_BOUNDS['lat'][1])


def _city_hint(addr):
    """从地址中提取浙江省城市名作为高德 city 参数（防止同名异地误解析）"""
    for c in ['杭州', '宁波', '温州', '嘉兴', '湖州', '绍兴',
              '金华', '衢州', '舟山', '台州', '丽水', '义乌', '余杭', '临安']:
        if c in addr:
            return c
    return None


# 知名区域名 -> 准确坐标（修正高德地理编码的歧义解析）
# 下沙: 高德把"下沙"解析到杭州别处(120.11,30.13)，实际大学城在钱塘区(120.35,30.32)
KNOWN_AREA_COORDS = {
    '下沙': (120.353, 30.321),
    '钱塘': (120.353, 30.321),
    '未来科技城': (120.010, 30.280),
    '滨江': (120.213, 30.210),
}


_GEOCODE_CACHE = None
_GEOCODE_CACHE_PATH = None


def _geocode_cache():
    """持久化 geocode 缓存（data/geocode_cache.json），避免重复地址反复调高德。"""
    global _GEOCODE_CACHE, _GEOCODE_CACHE_PATH
    if _GEOCODE_CACHE is None:
        from config import DATA_DIR
        _GEOCODE_CACHE_PATH = DATA_DIR / 'geocode_cache.json'
        try:
            _GEOCODE_CACHE = json.loads(_GEOCODE_CACHE_PATH.read_text(encoding='utf-8'))
        except Exception:
            _GEOCODE_CACHE = {}
    return _GEOCODE_CACHE


def _save_geocode_cache():
    try:
        if _GEOCODE_CACHE_PATH is not None and _GEOCODE_CACHE is not None:
            # 只保留最近 600 条，防止无限增长
            items = list(_GEOCODE_CACHE.items())[-600:]
            _GEOCODE_CACHE_PATH.write_text(
                json.dumps(dict(items), ensure_ascii=False), encoding='utf-8')
    except Exception:
        pass


def geocode(addr: str):
    """地址转坐标（带持久化缓存：命中则 0 次 API）。优先高德地理编码 API（精确到路/号），
    纯区名时用本地数据库商业质心（避免解析到区政府），知名区域坐标表仅作为最后兜底。"""
    cache = _geocode_cache()
    if addr in cache:
        v = cache[addr]
        return (v[0], v[1]) if v else (None, None)
    result = _geocode_inner(addr)
    cache[addr] = ([result[0], result[1]] if result[0] is not None else None)
    _save_geocode_cache()
    return result


def _geocode_inner(addr: str):
    city_hint = _city_hint(addr)
    # 方案零: 地址命中知名区域(下沙/钱塘/未来科技城/滨江)且无具体路号 -> 用修正坐标
    # (高德对"下沙大学城"等常解析偏差, 修正表更准)
    if not any(k in addr for k in ['路', '街', '号', '大道', '广场', '大厦', '中心', '小区', '公寓']):
        for area, (alng, alat) in KNOWN_AREA_COORDS.items():
            if area in addr:
                return alng, alat
    # 方案一: 高德地理编码 API（带城市提示 + 范围校验）—— 精确地址首选
    try:
        from data.fetch_poi import amap_url, http_get
        params = {'address': addr, 'city': city_hint or ''}
        data = http_get(amap_url('/v3/geocode/geo', params), timeout=10)
        if data.get('status') == '1':
            geos = data.get('geocodes') or []
            for g in geos:
                loc = g.get('location', '').split(',')
                if len(loc) != 2:
                    continue
                lng, lat = float(loc[0]), float(loc[1])
                if not _in_zhejiang(lng, lat):
                    continue
                # 纯区名(短、无路/街/号) -> 用商业质心替代区政府
                if _is_pure_district(addr):
                    c = _district_business_center(addr)
                    if c:
                        return c
                return lng, lat
    except Exception:
        pass  # 网络/配额问题则回落到本地库
    # 方案二: 纯区名兜底 -> 商业质心
    if _is_pure_district(addr):
        c = _district_business_center(addr)
        if c:
            return c
    # 方案三: 仅当地址是"纯区名"时用知名区域坐标
    if len(addr) <= 6 and not any(k in addr for k in ['路', '街', '号', '大道', '广场', '大厦', '中心']):
        for area, (alng, alat) in KNOWN_AREA_COORDS.items():
            if addr.endswith(area) or addr == area:
                return alng, alat
    # 方案四: 本地数据库模糊匹配（只匹配浙江坐标）
    from data.query import get_conn
    conn = get_conn()
    cur = conn.execute(
        'SELECT lng, lat FROM poi WHERE name LIKE ? OR address LIKE ? LIMIT 1',
        (f'%{addr}%', f'%{addr}%'),
    )
    row = cur.fetchone()
    conn.close()
    if row:
        lng, lat = row[0], row[1]
        if _in_zhejiang(lng, lat):
            return lng, lat
    return None, None


def _is_pure_district(addr):
    """判断是否纯区名/街道名(短、无具体路号)。
    会忽略"的一个铺子/的铺子"等后缀。"""
    t = addr
    for suffix in ['的一个铺子', '的铺子', '的商铺', '铺子', '商铺', '的一个店面', '店面']:
        if t.endswith(suffix):
            t = t[: -len(suffix)]
            break
    if len(t) > 8:
        return False
    if any(k in t for k in ['路', '街', '号', '大道', '广场', '大厦', '中心', '小区', '公寓', '村', '园']):
        return False
    return True


def _district_business_center(addr):
    """从本地数据库查该区(区名)的商业质心: 商圈+办公 POI 平均位置。
    用于纯区名定位, 避免解析到区政府。"""
    try:
        from data.query import get_conn
        conn = get_conn()
        # 提取区名: 去掉城市名, 保留"XX区/XX县"部分(如"宁波鄞州区"->"鄞州区")
        dist = addr
        for suffix in ['的一个铺子', '的铺子', '的商铺', '铺子', '商铺', '的一个店面', '店面']:
            if dist.endswith(suffix):
                dist = dist[: -len(suffix)]
                break
        for city in ['杭州', '宁波', '温州', '嘉兴', '湖州', '绍兴', '金华', '衢州', '舟山', '台州', '丽水']:
            if dist.startswith(city):
                dist = dist[len(city):]
                break
        # 保留到区/县名(如"鄞州区"->"鄞州区"; 无区名则原样)
        for sep in ['区', '县']:
            idx = dist.find(sep)
            if idx >= 0:
                dist = dist[:idx + 1]
                break
        if not dist:
            return None
        cur = conn.execute('''
            SELECT AVG(lng), AVG(lat) FROM poi
            WHERE adname LIKE ? AND category IN ('商圈', '办公')
        ''', (f'%{dist}%',))
        row = cur.fetchone()
        conn.close()
        if row and row[0] and row[1]:
            lng, lat = float(row[0]), float(row[1])
            if _in_zhejiang(lng, lat):
                return lng, lat
    except Exception:
        pass
    return None


