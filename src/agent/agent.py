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
import time
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

# ---------------------------------------------------------------
# 租金单价（元/㎡/天）识别 —— 2026-09-28 新增
# ---------------------------------------------------------------
# ⚠️ 为什么要单独一条：国内商铺挂牌**极常见**"3块一平一天"这种写法，
#    而它是**每天每平米**的单价，不是月租。RENT_PATTERN 会把它读成
#    "租金 3"（= 3 元/月），于是：
#      · 租金承受力被算成满分（月租 3 元 vs 真实 3×45×30 = 4050 元）
#      · 净利、一票否决、租金天花板全线失真 —— 而**界面看不出任何异常**
#    这与本项目已栽过的"单杯价当每单金额"（差 1.7 倍）是同一类量纲错，
#    倍数更大（这里能差 1000 倍以上）。
#
# 判据（两种语序都要认，中间只许夹**连接词**，绝不许夹数字/面积）：
#   ① 正序："3块一平一天" "2.5元/㎡/天" "租金 3 元/平方米/日"
#   ② 倒序："一平一天3块" "每天每平 3 元"
#
# ⚠️⚠️ 踩过的坑（2026-09-28，第一版就中招）：连接词写成 `[/每]?`
#    会导致跨词吞噬 —— "3块一平一天，45平" 被读成单价 = 45（把后面的面积
#    当成单价了，月租算成 60750，比真实值大 15 倍）。
#    所以中缀必须是**纯词**（每/一/一个/块/元），且 `\s*` 收紧为 `\s{0,2}`。
_RENT_UP_MID = r'(?:\s|每|一|一个|块|元|钱|/){0,4}'
_RENT_UP_AREA = r'(?:㎡|平米|平方米|平方米|平|方)'
_RENT_UP_TIME = r'(?:天|日|day)'
_RENT_UNIT_PRICE_PATTERN = re.compile(
    r'(\d+(?:\.\d+)?)\s*(?:元|块|钱)?' + _RENT_UP_MID +
    _RENT_UP_AREA + _RENT_UP_MID + _RENT_UP_TIME,
    re.IGNORECASE,
)
# 倒序式："一平一天 3 块" / "每天每平 3 元"
_RENT_UNIT_PRICE_PATTERN_REV = re.compile(
    _RENT_UP_AREA + _RENT_UP_MID + _RENT_UP_TIME + r'[^\d]{0,4}'
    r'(\d+(?:\.\d+)?)\s*(?:元|块|钱)?',
    re.IGNORECASE,
)
# 混序式："一天3块一平"（时间段在前，数字居中，面积在后）——数字后
# 只接面积、时间在数字之前，所以单独给一条"数字 + 面积"的尾巴式。
_RENT_UNIT_PRICE_PATTERN_MIX = re.compile(
    _RENT_UP_TIME + _RENT_UP_MID
    + r'(\d+(?:\.\d+)?)\s*(?:元|块|钱)?' + _RENT_UP_MID + _RENT_UP_AREA,
    re.IGNORECASE,
)
# 单价换算成月租时的天数基准：商铺按 30 天/月（行业惯例）
RENT_DAYS_PER_MONTH = 30


def extract_rent_unit_price(text: str, area=None):
    """识别"元/㎡/天"单价 → 返回 (元/㎡/天, 月租估算或 None)。

    ⚠️ 月租估算**必须有面积**才给：没面积就算不出月租，此时只返回单价，
    由调用方提示用户补面积 —— **不猜**（本项目的红线）。
    返回 (None, None) 表示没识别到单价写法。
    """
    t = text or ''
    m = _RENT_UNIT_PRICE_PATTERN.search(t)
    if not m:
        m = _RENT_UNIT_PRICE_PATTERN_REV.search(t)
    if not m:
        m = _RENT_UNIT_PRICE_PATTERN_MIX.search(t)
    if not m:
        return (None, None)
    try:
        unit = float(m.group(1))
    except Exception:
        return (None, None)
    # 量级闸：单价 0.1~200 元/㎡/天 之外的多半不是单价（商铺常见 1~30）
    if not (0.1 <= unit <= 200):
        return (None, None)
    if not area:
        return (unit, None)
    monthly = unit * float(area) * RENT_DAYS_PER_MONTH
    if not (200 <= monthly <= 2_000_000):
        return (unit, None)
    return (unit, int(round(monthly)))
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


def extract_rent(text: str, area=None):
    """提取月租(元)。

    坑（2026-09-14 实测踩到）："装修预算20万"曾被当成月租 20 万，覆盖掉用户先前给的
    月租 12000，把租金承受力打成 0 分、盈利测算与结论全错。所以"预算"这个触发词必须
    过闸：上文指向装修/投入就不算月租，金额超出小铺月租量级也不算。
    明确的"月租/租金/房租"无条件采信（用户改口重报租金要能生效）。

    ⚠️ 2026-09-28 新增：**单价写法优先**。"3块一平一天""2.5元/㎡/天"这类是
    **每㎡每天**的单价，绝不能被 RENT_PATTERN 读成"月租 3 元"。有面积时直接换成月租；
    没面积时返回 None（不猜），由上层提示补面积。
    """
    up, monthly = extract_rent_unit_price(text, area=area)
    if up is not None:
        # 识别到单价写法：这一条**压过**裸数字读法
        if monthly is not None:
            return int(monthly)
        return None      # 有单价但缺面积 -> 不猜，交给上层追问

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
    """提取地址。优先"城市+地点"；否则匹配知名区域名（下沙/文三路等）。

    ⚠️ 2026-09-25：**这里不做清洗**。清洗的唯一表面是 `_clean_area`（agent_graph 三处调用它）。
       本函数曾短暂挂过一个自己的清洗函数 `_clean_addr`，实测与 `_clean_area` 高度重叠
       （切动作短语/切品类词那两步它早就做了），属于"同一件事两处表面"。
       唯一真增量是「去助词『的』」，已合并进 `_clean_area`，此处恢复原样。
    """
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
    "杭州滨江的奶茶店"->"杭州滨江")。

    ⚠️ 2026-09-23 补**前缀**剥离（问题①）：
        改造前只剥后缀，于是「我想在海宁开奶茶店」剥完尾巴后剩
        **「我想在海宁」**，被当成地址传下去 → `geocode('我想在海宁')`
        必然失败、`area_filter='我想在海宁'` 在 58 一条都匹配不上。
        真机实测（策 2026-09-23）：`_clean_area('我想在海宁开奶茶店')`
        = '我想在海宁'；`'我想在杭州滨江开店'` = '我想在杭州滨江'
        —— 后者说明这个缺口在改造前**一直存在**，只是当时区县名识别不出，
        『我想在杭州滨江』靠 extract_city 拿到城市、地址串错也被掩盖了。
    """
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
    # 前缀：口语开场白（"我想在"/"帮我找"/"打算在"…），按长度降序只剥一次。
    # ⚠️ 剥完必须校验剩下的是不是"像地名"，否则：
    #      「想开一家奶茶店」→「一家奶茶店」→（再剥后缀）→ 空/单字，
    #      「找铺子」→「找」→ 单字 —— 这种**纯意向句**本来就没有地名，
    #      剥出来的单字反而比原文更误导（geocode('找') 会查出莫名其妙的结果）。
    #    所以要求剩余长度 ≥ 2 且**至少含一个字面像地名的字符**才接受；
    #    否则退回原文（让下游按"没给地点"处理，别拿噪声当地址）。
    prefixes = [
        '我打算在', '我准备在', '我想要在', '我计划在', '我想去在',
        '帮我查一下', '帮我找一下', '帮我看看', '帮我找', '帮我查',
        '打算在', '准备在', '计划在', '想去在', '想在', '要去在', '要去',
        '我想在', '我要在', '我想去', '我要去', '我想', '我要',
        '看一下', '查一下', '找一下', '请问', '麻烦',
    ]
    for prefix in prefixes:
        if t.startswith(prefix):
            cand = t[len(prefix):]
            if len(cand) >= 2:
                t = cand
            break
    # 前缀剥完可能又露出尾巴残留（"我想在海宁开店" -> "海宁开店" -> 需再剥一次）
    for suffix in suffixes:
        if t.endswith(suffix):
            t = t[: -len(suffix)]
    # ⚠️ 2026-09-25 补：助词「的」与方位词会长在**中间**，而上面的后缀剥离
    #    `if ...: t = ...; break` **只切一个就停** —— 切掉句尾的"奶茶店"之后，
    #    前面的"附近"和夹在中间的"的"都不会再动。
    #    实测后果（真机）：`geocode('宁波海曙区的火车站附近')` =
    #    (121.550485, 29.873705)，而干净的 `'宁波海曙区火车站'` =
    #    (121.519325, 29.866124) —— **偏约 3 公里**，跨了好几个商圈，
    #    且该点已在海曙区东侧边缘、可能出了区界。
    #    修法：助词全局去（中文地名基本不含「的」，安全）；
    #          方位词循环剥（它们可能连着出现，如"附近一带"）。
    t = t.replace('的', '')
    while True:
        _cut = False
        for w in ('附近', '周边', '旁边', '一带', '周围', '区域', '那块', '这边'):
            if t.endswith(w) and len(t) > len(w) + 1:
                t = t[: -len(w)]
                _cut = True
        if not _cut:
            break
            break
    for junk in ['的', '开', '找', '租', '在', '里']:
        while t.endswith(junk) and len(t) > 2:
            t = t[: -len(junk)]
    # 最终守门：剥完如果只剩 1 个字，或原文里有地名而剥完没了，一律退回原文。
    # （"想开一家奶茶店" → "想" 这种宁可给原文，也不要给一个假地名）
    if len(t) < 2:
        return area
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
    """从地址中提取浙江省城市名作为高德 city 参数（防止同名异地误解析）。

    ⚠️ 2026-09-25 补**区级约束**：地址里只写区县、不写市名时（用户口语常见），
       高德会串到外省同名区 —— 真机实测：
         `'西湖区'` 无 city 提示 → **南昌市西湖区** adcode 360103、坐标 (115.877, 28.657)（跨省！）
         `'西湖区'` 带 city='杭州' → 杭州市西湖区 adcode 330106、坐标 (120.130, 30.259) ✓
       所以这里先扫 11 个地级市（**行为不变**），扫不到再用 `zj_districts` 的区县表
       反推地级市 —— 这样 `'西湖区'` 也能拿到 '杭州' 这个提示。

    ⚠️ 与 `extract_city` 的分工（别重复）：那个给业务层用、返回裸市名；
       这个只服务高德参数，所以额外保留了 '义乌/余杭/临安' 这几个高德友好别名。
    """
    for c in ['杭州', '宁波', '温州', '嘉兴', '湖州', '绍兴',
              '金华', '衢州', '舟山', '台州', '丽水', '义乌', '余杭', '临安']:
        if c in addr:
            return c
    try:
        from agent.zj_districts import DISTRICT_TO_CITY, DISTRICT_TO_CITY_SHORT
        for d in sorted(DISTRICT_TO_CITY, key=len, reverse=True):
            if d in addr:
                return DISTRICT_TO_CITY[d]
        for s in sorted(DISTRICT_TO_CITY_SHORT, key=len, reverse=True):
            if s in addr:
                return DISTRICT_TO_CITY_SHORT[s]
    except Exception:
        pass
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

# 定位记录的字段表：缓存与返回值共用同一套形状，避免"多一处表面"
_GEO_FIELDS = ('lng', 'lat', 'district', 'adcode', 'level', 'src')


def _blank_record():
    return {'lng': None, 'lat': None, 'district': None,
            'adcode': None, 'level': None, 'src': ''}


def _normalize_cache_value(v):
    """缓存值兼容层。

    ⚠️ 2026-09-25：缓存从 `[lng, lat]` / `null` 升级为**完整定位记录 dict**
       （为了把高德响应里的 district / adcode 留下来做区县校验）。
       旧缓存**必须还能读** —— 否则升级后整份缓存失效，白白重烧一遍高德配额。
    """
    if isinstance(v, dict):
        rec = _blank_record()
        for k in _GEO_FIELDS:
            if v.get(k) is not None:
                rec[k] = v[k]
        return rec
    if isinstance(v, (list, tuple)) and len(v) == 2 and v[0] is not None:
        rec = _blank_record()
        rec['lng'], rec['lat'], rec['src'] = v[0], v[1], 'legacy'
        return rec
    return _blank_record()


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


def geocode_record(addr: str, enrich_district: bool = False) -> dict:
    """地址 -> **完整定位记录**（定位的**唯一实现**；`geocode()` 是它的薄包装）。

    返回 {'lng','lat','district','adcode','level','src'}：
      src='amap'        高德地理编码 —— 唯一带 district/adcode 的来源，区县校验的权威依据
      src='centroid'    本地 POI 商业质心（纯区名，刻意避开区政府）；district/adcode 仍取自
                        同一次高德响应的 geocodes[0]，**不是**从地址串反推的
      src='known'       本地知名区域修正表（下沙/钱塘/未来科技城/滨江）
      src='local'       本地 POI 模糊匹配
      src='legacy'      旧缓存（2026-09-25 之前写入，只有坐标、没有区县）
      src='legacy+…'    旧缓存补过区县（**坐标仍是旧值**，只填了 district/adcode；
                        后缀是补到区县的路径，如 legacy+amap / legacy+known）
      src=''            定位失败（lng/lat 为 None）

    ⚠️ `district` / `adcode` **只来自高德**，绝不从地址串反推后填进来 ——
       填了就变成"自己跟自己比对"，冲突检测会永远通过（**假绿**）。
       高德没给就是 None，调用方据此**跳过**校验（不猜）。

    enrich_district：命中"**本该有区县、却没记下来**"的缓存记录时补一次
       （`src ∈ {legacy, known, local}` 且 district 为空）。补的时候**坐标保持旧值**。
       ⚠️ 条件必须按"有没有区县"判、**不能只认 `src=='legacy'`**：
          本次开发实测踩到 —— 修正表路径（`known`）写入的记录也没有区县，
          只认 legacy 会让它们永远补不上，冲突检测对这些地址**静默失效**。
       ⚠️ 为什么必须冻结坐标：坐标一漂移，所有候选的距离/排序/占比全变，
          同一输入两次跑结果不同 —— 违反项目"确定性"红线。
       ⚠️ 为什么默认关：这是**额外的高德调用**。批量场景（backtest 几百个地址）
          若默认开，会成倍烧配额。只有真正要做区县校验的调用方（search_rental_node，
          每个会话一个目标地址）才显式打开。
    """
    cache = _geocode_cache()
    if addr in cache:
        rec = _normalize_cache_value(cache[addr])
        if (enrich_district and not rec['district']
                and rec['src'] in ('legacy', 'known', 'local')):
            try:
                _m = _geocode_record_inner(addr)
            except Exception:
                _m = {}
            if _m.get('district') or _m.get('adcode'):
                rec['district'] = _m.get('district')
                rec['adcode'] = _m.get('adcode')
                rec['level'] = _m.get('level')
                # 坐标未动，只补了区县身份；后缀标明区县是从哪条路径补到的（amap/known）
                rec['src'] = 'legacy+' + (_m.get('src') or 'amap')
            cache[addr] = dict(rec)
            _save_geocode_cache()
        return rec
    rec = _geocode_record_inner(addr)
    cache[addr] = dict(rec)
    _save_geocode_cache()
    return rec


def geocode(addr: str):
    """地址转坐标（带持久化缓存：命中则 0 次 API）。优先高德地理编码 API（精确到路/号），
    纯区名时用本地数据库商业质心（避免解析到区政府），知名区域坐标表仅作为最后兜底。

    ⚠️ 薄包装：定位的**唯一实现**是 `geocode_record()`，别在这里复制逻辑。
       需要 district/adcode（区县校验、地标冲突检测）的调用方直接用 `geocode_record()`。
    """
    rec = geocode_record(addr)
    return (rec['lng'], rec['lat']) if rec['lng'] is not None else (None, None)


def _amap_geocode(address, city):
    """高德地理编码 —— 调用它的**唯一入口**（带并发限流重试）。返回 `geocodes[0]` 或 `{}`。

    ⚠️ 为什么必须有重试（2026-09-26 真机踩到）：
       高德有**并发 QPS 限制** —— 实测连打 4 次，第 4 次返回
       `status=0, info='CUQPS_HAS_EXCEEDED_THE_LIMIT'`。
       而候选定位是**循环里连续调用**（每条候选 1~3 次 geocode），
       一旦被限流，`geocode` 就返回 `(None, None)`，候选**静默回落成"区域级"定位** ——
       实测：清了 34 条缓存后，15 条候选**全部**变成 `addr_level='area'`、坐标全等于目标点。
       这种回归在界面上看不出来（卡片只标"区域级·无门牌"），所以必须在这里兜住。

    ⚠️ 抽成唯一入口而不是各处自己 `http_get`：本项目第一高发错就是
       "同一件事几处表面" —— 限流这件事要么全兜住，要么等于没兜。
    """
    for _ in range(3):
        try:
            from data.fetch_poi import amap_url, http_get
            d = http_get(amap_url('/v3/geocode/geo',
                                  {'address': address, 'city': city or ''}), timeout=10)
            if d.get('status') == '1':
                return (d.get('geocodes') or [{}])[0]
            _info = str(d.get('info') or '')
            if 'CUQPS' in _info or 'LIMIT' in _info:
                time.sleep(0.5)      # 被限流：短退避再试
                continue
            return {}                # 其它失败（查无此地址等）重试无意义
        except Exception:
            time.sleep(0.3)
    return {}


def _known_district(area_key):
    """`KNOWN_AREA_COORDS` 的键若是**区县名**，返回规范全称（'滨江' → '滨江区'）；否则 None。

    ⚠️ 为什么需要它（2026-09-25）：方案零会**抢在高德之前**返回修正坐标，
       于是 `'杭州西湖区滨江宝龙城'` 这类地址拿不到高德给区县，
       地标/区县冲突检测就被**静默跳过**（真机踩到）。
       而这张表的点本来就是按区选的（'滨江' 取的就是滨江区商圈坐标），
       所以"这一点落在哪个区"是**表里已有的信息**，如实记下不算猜 ——
       冲突检测要的正是"我把点落在哪个区" vs "用户说的哪个区"。
       '下沙' / '未来科技城' 不是区名（分属钱塘区/余杭区）⇒ 返回 None，不硬套。
    """
    try:
        from agent.zj_districts import DISTRICT_KEYS, district_key, district_full
        if district_key(area_key) in DISTRICT_KEYS:
            return district_full(area_key)
    except Exception:
        pass
    return None


# 品类/动作短语：出现在「剥完剩下的」里就说明那不是地名，是没洗干净的意向句。
# 只收**多字**词 —— 单字「店」「铺」会误伤真实地标（"XX大酒店"），所以不收。
_LANDMARK_STOPWORDS = (
    '奶茶店', '甜品店', '早餐店', '便利店', '茶饮店', '商铺', '店铺', '铺子', '店面', '门面',
    '出租', '转让', '招租', '转租', '附近', '周边', '一带', '周围',
    '开店', '开一家', '开一间', '开个', '做生意', '小生意', '想去开',
)


def _landmark_of(addr):
    """从「城市+区县+地标」里剥出**地标**；剥完什么都不剩（只剩城市/区县）返回 None。
    ⚠️ 为什么需要它（2026-09-26，策实机验收提出）：
       `'宁波海曙区火车站'` 直接丢给高德，返回的 `level='区县'` ——
       高德**只认到行政级别，没定位到"火车站"**。而下游把区中心当成了目标点，
       于是用户要的"火车站附近"变成"海曙区中心附近"，实测**偏 1.8 公里**。

    实测对照：
      `geocode('宁波海曙区火车站')` → (121.5193, 29.8661)   ← 海曙区商业质心
      `geocode('宁波火车站')`       → (121.5370, 29.8621)   ← 真·公交地铁站点 ✓

    ⚠️ 剥不出地标**必须返回 None**，让调用方原样回落老路径 ——
       `'海曙区'` / `'宁波'` / `'杭州滨江'` 都不该被这里改写行为。

    ⚠️ 2026-09-26 加严（第一版太松，实测踩到）：第一版只要求"剥完还剩 ≥2 字"，
       于是**一整句描述**也算命中 —— 缓存 600 条里有 **590 条**被误判为"含地标"
       （如 `'宁波龙湖天街大型汉庭酒店 大型K T V，消费人群多'`：剥掉'宁波'后剩一长串）。
       这会让长句地址也去触发一次地标定位，可能定到完全无关的地方。
       现在要求：**必须真的剥掉城市名、且真的剥掉一个区县名**，
       剥出来的还得**像个地名**（长度 2~12、不含空白/标点）。
       `'下沙'`/`'文三路'`/`'宁波龙湖天街…'` 这类一律返回 None。
    """
    t = (addr or '').strip()
    if not t:
        return None
    # 必须先能剥掉城市名 —— 否则这串不是「城市+区县+地标」形态
    c = _city_hint(t)
    if not (c and t.startswith(c)):
        return None
    t = t[len(c):]
    # 剥区县名（全称优先，再短名）—— **必须真的剥掉一个**
    _stripped = False
    try:
        from agent.zj_districts import DISTRICT_TO_CITY, DISTRICT_TO_CITY_SHORT
        for d in sorted(DISTRICT_TO_CITY, key=len, reverse=True):
            if t.startswith(d):
                t = t[len(d):]
                _stripped = True
                break
        if not _stripped:
            for s in sorted(DISTRICT_TO_CITY_SHORT, key=len, reverse=True):
                if t.startswith(s):
                    t = t[len(s):]
                    _stripped = True
                    break
    except Exception:
        pass
    if not _stripped:
        return None          # 没剥到区县 ⇒ 不是「区 + 地标」形态
    t = t.strip().lstrip('的')      # 历史缓存里有「宁波海曙区**的**火车站」这种带助词的串
    # 剥出来的得**像一个地名**，不能是一整句
    if not (2 <= len(t) <= 12):
        return None
    if re.search(r'[\s,，。、;；:：()（）\[\]【】!！?？/|·]', t):
        return None
    # 也不能是没洗干净的**意向句**（'的火车站附近开一家奶茶店' 剥完正好 12 字，
    # 长度拦不住）。含品类/动作短语的一律不当地标 —— 否则会白花一次地标定位。
    if any(w in t for w in _LANDMARK_STOPWORDS):
        return None
    return t


def _landmark_coord(landmark, city_hint):
    """地标定位（'火车站' + '宁波' → 坐标）。返回记录 dict 或 None。

    两级，都**只在真能定位到比"行政级别"更具体**时才采信：
      ① 高德查「城市+地标」—— 最准（实测 '宁波火车站' → level='公交地铁站点'，
         误差 ≈ 0）。⚠️ 高德有**并发 QPS 限流**（实测连打 4 次第 4 次返回
         `CUQPS_HAS_EXCEEDED_THE_LIMIT`），所以失败要能兜。
      ② 本地 POI 库：`name` 含地标的 POI 求质心 —— 零 API、不受限流。
         实测 '火车站' 在宁波库有 8 条，质心离真站点约 0.9 公里（比现状 1.8 公里好一半）。
         要求样本 ≥ 3 条，否则单条噪声不当证据。

    ⚠️ 高德那一步**必须再查一次 level**：如果它也只给 '省/市/区县'，
       说明换了个写法仍然没定位到地标 —— 这种结果与现状等价，**不该采信**（白花一次调用）。
    """
    if not landmark or len(landmark) < 2:
        return None
    # ① 高德
    if city_hint:
        try:
            g = _amap_geocode(f'{city_hint}{landmark}', city_hint)
            if g:
                loc = (g.get('location') or '').split(',')
                _lv = g.get('level') or ''
                if len(loc) == 2 and _lv not in ('省', '市', '区县', ''):
                    lng, lat = float(loc[0]), float(loc[1])
                    if _in_zhejiang(lng, lat):
                        return {'lng': lng, 'lat': lat, 'district': g.get('district'),
                                'adcode': g.get('adcode'), 'level': _lv, 'src': 'landmark'}
        except Exception:
            pass
    # ② 本地 POI 质心兜底
    if city_hint:
        try:
            from data.query import get_conn
            _cn = city_hint if city_hint.endswith('市') else f'{city_hint}市'
            conn = get_conn()
            row = conn.execute(
                'SELECT AVG(lng), AVG(lat), COUNT(*) FROM poi WHERE city = ? AND name LIKE ?',
                (_cn, f'%{landmark}%')).fetchone()
            # 不再 close()：连接由 data.query.get_conn() 按线程缓存复用（2026-09-27 P0-3）
            if row and row[0] and (row[2] or 0) >= 3 and _in_zhejiang(row[0], row[1]):
                return {'lng': row[0], 'lat': row[1], 'district': None,
                        'adcode': None, 'level': 'poi-avg', 'src': 'landmark_local'}
        except Exception:
            pass
    return None


def _geocode_record_inner(addr: str) -> dict:
    rec = _blank_record()
    city_hint = _city_hint(addr)
    # 方案零: 地址命中知名区域(下沙/钱塘/未来科技城/滨江)且无具体路号 -> 用修正坐标
    # (高德对"下沙大学城"等常解析偏差, 修正表更准)
    if not any(k in addr for k in ['路', '街', '号', '大道', '广场', '大厦', '中心', '小区', '公寓']):
        for area, (alng, alat) in KNOWN_AREA_COORDS.items():
            if area in addr:
                rec.update({'lng': alng, 'lat': alat, 'src': 'known'})
                # 键本身是区名就直接用（'滨江'→滨江区）；不是（'下沙'）就看同一串里
                # 有没有**别的区名键**（'杭州钱塘区下沙' 同时含 '钱塘'）。坐标不动，只补区县。
                rec['district'] = _known_district(area)
                if not rec['district']:
                    for _k in KNOWN_AREA_COORDS:
                        if _k != area and _k in addr and _known_district(_k):
                            rec['district'] = _known_district(_k)
                            break
                return rec
    # 方案一: 高德地理编码 API（带城市提示 + 范围校验）—— 精确地址首选
    # ⚠️ 走 `_amap_geocode`（唯一入口，带并发限流重试）—— 直接 http_get 会漏掉 QPS 限流，
    #    候选定位在循环里连续调用时会大面积失败、静默回落成"区域级"。
    try:
        _g0 = _amap_geocode(addr, city_hint)
        if _g0:
            for g in [_g0]:
                loc = g.get('location', '').split(',')
                if len(loc) != 2:
                    continue
                lng, lat = float(loc[0]), float(loc[1])
                if not _in_zhejiang(lng, lat):
                    continue
                # 高德的区县身份 —— 顺手留下（同一次响应的字段，不额外花配额）
                _d, _a, _lv = g.get('district'), g.get('adcode'), g.get('level')
                # ★ 2026-09-26（策实机验收提出）：高德只认到**行政级别**时
                #   （`level ∈ {省, 市, 区县}`），说明它**没有定位到地名本身** ——
                #   实测 `'宁波海曙区火车站'` 只返回 level='区县'。
                #   这时若直接用区中心，用户要的"火车站附近"就变成"海曙区中心附近"
                #   （实测偏 **1.8 公里**，1 公里内 0 条候选）。
                #   把地标拆出来单独定一次；**定不到就原样往下走**，既有行为一字不变。
                if _lv in ('省', '市', '区县'):
                    _lm = _landmark_of(addr)
                    if _lm:
                        _hit = _landmark_coord(_lm, city_hint)
                        if _hit:
                            rec.update(_hit)
                            return rec
                # 纯区名(短、无路/街/号) -> 用商业质心替代区政府
                if _is_pure_district(addr):
                    c = _district_business_center(addr)
                    if c:
                        rec.update({'lng': c[0], 'lat': c[1], 'district': _d,
                                    'adcode': _a, 'level': _lv, 'src': 'centroid'})
                        return rec
                rec.update({'lng': lng, 'lat': lat, 'district': _d,
                            'adcode': _a, 'level': _lv, 'src': 'amap'})
                return rec
    except Exception:
        pass  # 网络/配额问题则回落到本地库
    # 方案二: 纯区名兜底 -> 商业质心
    if _is_pure_district(addr):
        c = _district_business_center(addr)
        if c:
            rec.update({'lng': c[0], 'lat': c[1], 'src': 'centroid'})
            return rec
    # 方案三: 仅当地址是"纯区名"时用知名区域坐标
    if len(addr) <= 6 and not any(k in addr for k in ['路', '街', '号', '大道', '广场', '大厦', '中心']):
        for area, (alng, alat) in KNOWN_AREA_COORDS.items():
            if addr.endswith(area) or addr == area:
                rec.update({'lng': alng, 'lat': alat, 'src': 'known'})
                rec['district'] = _known_district(area)
                return rec
    # 方案四: 本地数据库模糊匹配（只匹配浙江坐标）
    from data.query import get_conn
    conn = get_conn()
    cur = conn.execute(
        'SELECT lng, lat FROM poi WHERE name LIKE ? OR address LIKE ? LIMIT 1',
        (f'%{addr}%', f'%{addr}%'),
    )
    row = cur.fetchone()
    # 不再 close()：连接由 data.query.get_conn() 按线程缓存复用（2026-09-27 P0-3）
    if row:
        lng, lat = row[0], row[1]
        if _in_zhejiang(lng, lat):
            rec.update({'lng': lng, 'lat': lat, 'src': 'local'})
            return rec
    return rec


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
        # 不再 close()：连接由 data.query.get_conn() 按线程缓存复用（2026-09-27 P0-3）
        if row and row[0] and row[1]:
            lng, lat = float(row[0]), float(row[1])
            if _in_zhejiang(lng, lat):
                return lng, lat
    except Exception:
        pass
    return None


