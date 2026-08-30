# -*- coding: utf-8 -*-
"""
agent.py —— 选址 Agent 对话循环
=================================
架构:
- 意图解析 + 信息抽取: 规则 + LLM 混合（规则保证稳定，LLM 增强理解）
- 评分: 调用 engine.scoring（确定性、可离线）
- 解读: LLM 生成推理链（可解释性）

设计取舍（答辩导向）:
1. 评分必须确定性（同一输入同一结果），不能因为 LLM 抖动改变分数
2. 演示稳定 > 花哨：即使 LLM 调用失败，也有基于规则的兜底解读
3. 所有数据结论可追溯到评分引擎和本地数据库
"""
import re
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import get_profile, CATEGORY_PROFILES  # noqa: E402
from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL  # noqa: E402
from config import LLM_FALLBACK_API_KEY, LLM_FALLBACK_BASE_URL, LLM_FALLBACK_MODEL  # noqa: E402
from engine.scoring import score_site  # noqa: E402
from agent.prompts import build_interpret_prompt  # noqa: E402

CATEGORY_NAMES = list(CATEGORY_PROFILES.keys())

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
    r'(?:月租|租金|房租|预算)[^\d]{0,6}'
    r'(\d+(?:\.\d+)?)\s*(万|千|k|w|元)?'
    r'(?:(\d+)\s*(百)?)?',  # 支持 "1万5" "2千5" 这种口语
    re.IGNORECASE,
)


# ---------------------------------------------------------------
# 1. 信息抽取（规则层，保证稳定）
# ---------------------------------------------------------------
def extract_category(text: str):
    for cat, aliases in CATEGORY_ALIASES.items():
        for a in aliases:
            if a in text:
                return cat
    return None


def extract_rent(text: str):
    m = RENT_PATTERN.search(text)
    if not m:
        return None
    num = float(m.group(1))
    unit = (m.group(2) or '').lower()
    extra = m.group(3)  # "1万5" 里的 "5"
    if unit in ('千', 'k'):
        num *= 1000
    elif unit in ('万', 'w'):
        num *= 10000
    # 处理 "1万5" -> 15000, "2千5" -> 2500
    if extra:
        num += float(extra) * (1000 if unit in ('万', 'w') else 100)
    return int(num)


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
    lines = [
        f"【{r['name'] or '该地址'}】总分 {r['total']} —— {r['verdict']}",
    ]
    for dim, score in r['dims'].items():
        lines.append(f"  {dim}: {score}分")
    e = r['evidence']
    lines.append(f"  证据: 周边竞品 {e['竞品数']} 家，"
                 f"客群引力 {e['客群引力累计']}，"
                 f"最近通勤点 {e['最近通勤点(m)']}米，"
                 f"预估月流水 ¥{e['预估月流水']:,}，"
                 f"租金占流水 {e['租金占流水比']}")
    # 水电/盈利测算
    if r.get('utility'):
        u = r['utility']
        lines.append(f"  💡 水电测算({u['城市']}): 电价{u['电价(元/度)']}元/度 水价{u['水价(元/吨)']}元/吨，"
                     f"月水电合计 ¥{u['水电合计(元/月)']:,}")
    if r.get('profit'):
        p = r['profit']
        pb = f"{p['回本周期(月)']}个月" if p['回本周期(月)'] else '无法回本'
        lines.append(f"  💰 盈利测算: 前期投入 ¥{p['前期投入']:,}（{p['投入来源']}），"
                     f"月人工 ¥{p['月人工']:,}（{p['人数']}人×¥{p['人均月薪']:,}），"
                     f"月物料 ¥{p['月物料成本']:,}，月固定成本 ¥{p['月固定成本']:,}，"
                     f"月净利 ¥{p['月净利估算']:,}，回本周期 {pb}，{p['盈亏判断']}")
    if r['warnings']:
        for w in r['warnings']:
            lines.append(f"  {w}")
    lines.append("  ⚠️ 以上基于公开POI数据，不含真实人流量与成交租金，水电为参考标准，建议现场复核。")
    return '\n'.join(lines)


# ---------------------------------------------------------------
# 3. LLM 解读（增强可解释性；主用小米 mimo，失败降级到 DeepSeek，最终降级到规则解读）
# ---------------------------------------------------------------
def _call_llm(api_key, base_url, model, system_msg, user_msg, temperature=0.3, timeout=30):
    """通用 LLM 调用函数"""
    import urllib.request
    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': system_msg},
            {'role': 'user', 'content': user_msg},
        ],
        'temperature': temperature,
    }
    req = urllib.request.Request(
        f'{base_url.rstrip("/")}/chat/completions',
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json',
                 'Authorization': f'Bearer {api_key}'},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    return data['choices'][0]['message']['content']


def llm_interpret(result: dict) -> str:
    """LLM 解读评分结果，支持三级降级：小米 mimo -> DeepSeek -> 规则解读"""
    if not LLM_API_KEY:
        return rule_based_interpret(result)

    system_msg = (
        '你是一位资深商铺选址顾问，服务对象是缺乏商业分析能力的个人创业者。'
        '你的分析基于 Huff 引力模型（零售引力理论）的评分引擎输出。'
        '要求：'
        '1. 用口语化、有说服力的方式向创业者解释选址结论，先给结论再给理由；'
        '2. 必须引用引擎返回的数据证据（竞品引力比、客群引力、通勤距离、租金占比等），'
        '   可以通俗解释"引力"概念（如"离地铁口越近、周边匹配客群越密集，得分越高"）；'
        '3. 若引擎提供了水电成本和盈利测算（utility/profit 字段），必须解读：'
        '   - 月水电成本是否合理，占流水比例'
        '   - 月净利估算、回本周期是否可接受'
        '   - 结合租金给出盈亏风险的实话实说判断；'
        '4. 如实转达所有风险警告，帮用户避坑；'
        '5. 最后必须附局限声明：基于公开POI数据，不含真实人流量与成交租金，'
        '   水电价格为参考标准，建议现场复核；'
        '6. 严禁编造引擎数据之外的任何数字。'
    )
    user_msg = build_interpret_prompt(json.dumps(result, ensure_ascii=False))

    # 主用: 小米 mimo
    try:
        return _call_llm(LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, system_msg, user_msg)
    except Exception as e1:
        pass  # 主用失败，尝试备用

    # 备用: DeepSeek
    if LLM_FALLBACK_API_KEY:
        try:
            return _call_llm(LLM_FALLBACK_API_KEY, LLM_FALLBACK_BASE_URL, LLM_FALLBACK_MODEL, system_msg, user_msg)
        except Exception as e2:
            pass  # 备用也失败，降级到规则解读

    # 最终兜底: 规则解读
    return rule_based_interpret(result)


# ---------------------------------------------------------------
# 4. 对话主流程
# ---------------------------------------------------------------
# 客群定位 / 堂食外卖 / 面积 的口语词提取
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


def extract_budget(text: str):
    """提取装修预算(元): 需含"装修/装潢/预算"等词, 避免误匹配月租"""
    if not any(k in text for k in ['装修', '装潢', '预算', '投入', '装修款']):
        return None
    # 优先"XX万装修/装修预算XX万/预算XX万"
    m = re.search(r'(?:装修|装潢|预算|投入)[^\d]{0,6}(\d+(?:\.\d+)?)\s*(万|w|千|k)?', text)
    if not m:
        # 反向: "XX万装修"
        m = re.search(r'(\d+(?:\.\d+)?)\s*(万|w)\s*(?:装修|装潢)', text)
    if not m:
        return None
    num = float(m.group(1))
    unit = (m.group(2) or '').lower()
    if unit in ('万', 'w'):
        num *= 10000
    elif unit in ('千', 'k'):
        num *= 1000
    else:
        num *= 10000  # 裸数字视为万(装修预算量级)
    return int(num)


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
        '想去开', '想开', '去看看', '去看看铺子', '开个', '开一家',
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


def _build_comparison(current, history):
    """生成当前商铺与之前分析商铺的对比文本"""
    lines = ['📊 **与之前分析的商铺对比：**', '']
    # 表头
    lines.append('| 商铺 | 总分 | 客群 | 竞争 | 交通 | 租金 | 结论 |')
    lines.append('|---|---|---|---|---|---|---|')
    for h in history:
        d = h['dims']
        lines.append(f"| {h['name'][:12]} | {h['total']} | {d['客群匹配度']} | "
                     f"{d['竞争压力']} | {d['交通可达性']} | {d['租金承受力']} | {h['verdict']} |")
    d = current['dims']
    lines.append(f"| **{current['name'][:12]}** | **{current['total']}** | {d['客群匹配度']} | "
                 f"{d['竞争压力']} | {d['交通可达性']} | {d['租金承受力']} | **{current['verdict']}** |")
    # 结论建议
    best = min(history, key=lambda h: -h['total'])
    if current['total'] > best['total']:
        lines.append(f"\n✅ 当前商铺 **{current['total']}分** 高于之前最好的 "
                     f"「{best['name'][:10]}」({best['total']}分)，可作为优先考虑。")
    else:
        lines.append(f"\nℹ️ 当前商铺 **{current['total']}分**，之前「{best['name'][:10]}」"
                     f"({best['total']}分) 评分更高，可对比权衡。")
    return '\n'.join(lines)


class SiteAgent:
    """有状态的选址顾问。分阶段引导：
    phase='intro'    -> 问有无意向商铺
    phase='have_shop'-> 有商铺: 收集面积/租金, 进入分析
    phase='no_shop'  -> 无商铺: 找区域, 搜出租商铺候选, 用户选择
    phase='analysis' -> 分析完成/持续对话
    """

    def __init__(self):
        self.state = {
            'phase': 'intro',
            'category': None, 'rent': None, 'addresses': [],
            'guest': None, 'mode': None, 'area': None,
            'shop_candidates': [],   # 无商铺分支的候选列表
            'awaiting_choice': False,  # 等待用户从候选里选择
            'analyzed_history': [],  # 已分析结果列表(用于前后对比)
        }

    def ask(self, user_text: str) -> str:
        text = (user_text or '').strip()

        # ---- 用户想换/再看其他商铺(任意阶段) -> 回到推荐环节 ----
        if self.state['phase'] != 'intro' and self._wants_more_shops(text):
            return self._re_recommend(text)

        # ---- 阶段1: 引导 ----
        if self.state['phase'] == 'intro':
            return self._phase_intro(text)

        # ---- 无商铺: 等待从候选中选择（优先于 no_shop, 因为选择时 phase 仍是 no_shop）----
        if self.state['awaiting_choice']:
            return self._handle_choice(text)

        # ---- 无商铺: 用户给区域 -> 搜出租候选 ----
        if self.state['phase'] == 'no_shop':
            return self._handle_no_shop_area(text)

        # ---- 常规信息收集(有商铺/后续追问) ----
        return self._collect_info(text)

    # -----------------------------------------------------------
    def _wants_more_shops(self, text):
        """判断用户是否想继续看其他商铺(而非分析新地址)"""
        # 若用户给了新地址/新品类, 视为新分析, 不是换商铺
        if parse_request(text).get('address'):
            return False
        if parse_request(text).get('category'):
            # 有品类但无地址: 可能是补信息, 不拦截
            if '换' not in text and '再推荐' not in text and '别的' not in text:
                return False
        for kw in ['换一个', '换家', '再推荐', '再找', '其他的', '别的', '还有其他',
                   '还有吗', '再来', '重新推荐', '另选', '换别']:
            if kw in text:
                return True
        # "再看看"仅在无新地址时算换商铺
        if '再看看' in text and not parse_request(text).get('address'):
            return True
        return False

    def _re_recommend(self, text):
        """回到推荐环节: 若之前有候选列表, 重新展示; 否则重新问区域"""
        # 保留历史分析用于后续对比
        self.state['phase'] = 'no_shop'
        self.state['awaiting_choice'] = False
        # 用户是否给了新区域(如"换到滨江区看看")
        new_area = extract_address(text) or (
            re.search(r'(杭州|宁波|温州|嘉兴|湖州|绍兴|金华|衢州|舟山|台州|丽水)[\u4e00-\u9fa5]{0,10}', text))
        # 如果还有旧候选且用户没给新区域, 直接重新展示旧候选
        if self.state.get('shop_candidates') and not new_area:
            cands = self.state['shop_candidates']
            self.state['awaiting_choice'] = True
            lines = ['好的，为你重新展示候选商铺：', '']
            for i, c in enumerate(cands, 1):
                info = []
                if c.get('area'):
                    info.append(f"{c['area']}㎡")
                if c.get('price'):
                    info.append(f"{c['price']:.0f}元/月")
                extra = f"（{'，'.join(info)}）" if info else ''
                show_addr = c.get('real_addr') or c.get('address') or ''
                lines.append(f"**{i}. {c['name']}**  {extra}")
                lines.append(f"    🧭 {show_addr}")
                lines.append('')
            lines.append('回复序号选择；或告诉我其他区域（如"滨江区"）。')
            return '\n'.join(lines)
        # 用户给了新区域或没有旧候选: 重新搜索
        return self._handle_no_shop_area(text)

    # -----------------------------------------------------------
    def _phase_intro(self, text):
        """阶段1: 判断有无意向商铺"""
        has_shop = self._detect_has_shop(text)
        if has_shop is None:
            return ('👋 你好！我是你的选址顾问。先确认一下：'
                    '**你有具体看中的商铺了吗？**\n\n'
                    '- 有的话，告诉我商铺位置（如"杭州武林广场杭州大厦B座"）\n'
                    '- 还没有的话，告诉我你想开在哪个区域（如"杭州滨江"）')
        if has_shop:
            self.state['phase'] = 'have_shop'
            # 用户可能已带位置/面积/租金
            return self._collect_info(text)
        else:
            self.state['phase'] = 'no_shop'
            # 用户可能已带区域(如"帮我找杭州滨江的"), 直接搜; 否则追问区域
            return self._handle_no_shop_area(text)

    def _detect_has_shop(self, text):
        """判断用户是否有具体商铺: 有/没有/不确定(返回None继续追问)"""
        t = text
        # 先排除否定词（"还没有""没有""没看中"）
        for kw in ['还没有', '没有', '还没', '没看中', '不确定', '没找到']:
            if kw in t:
                return False
        # 明确"有"的表述（排除"有没有"这种疑问）
        for kw in ['有没有', '有吗', '有没']:
            if kw in t:
                return None
        for kw in ['看中了', '看中', '找到了', '找好了', '看好了', '有意向', '目标商铺',
                   '具体商铺', '看了一家', '有一个', '有具体', '有看']:
            if kw in t:
                return True
        # 明确的"找/推荐"请求
        for kw in ['帮我找', '帮我查', '推荐', '帮我看看', '帮我找找', '帮我搜']:
            if kw in t:
                return False
        # "想在XX附近/想在XX开/XX附近有没有" 这类=想找区域, 没有具体商铺
        for kw in ['附近', '周边', '一带', '区域', '地段', '哪里', '在哪', '哪些地方']:
            if kw in t:
                return False
        # 若只提到"区域/地标 + 品类"(无具体铺位), 视为找区域/找商铺, 不问租金
        # (如"想在杭州龙翔桥地铁站附近开奶茶店""开奶茶店杭州滨江")
        info = parse_request(t)
        if info.get('category') or info.get('address'):
            # 有具体商铺特征的（大厦X座/号铺/铺位/门店/店面/楼层）才算"有"
            addr = info.get('address') or ''
            for kw in ['座', '号', '铺位', '门店', '店面', '层']:
                if kw in addr:
                    return True
            return False
        return None

    # -----------------------------------------------------------
    def _collect_info(self, text):
        """收集品类/地址/租金/面积等, 齐全则分析。
        若用户输入不含任何可提取的信息(且已有分析上下文), 视为自由提问,
        交给 LLM 以顾问身份回答。"""
        info = parse_request(text)
        got_new = False
        if info['category']:
            self.state['category'] = info['category']
            got_new = True
        if info['rent']:
            self.state['rent'] = info['rent']
            got_new = True
        if info['address']:
            self.state['addresses'].append(info['address'])
            # 用户给了新地址: 清除旧的候选坐标(避免回落错位置)
            self.state['pending_coord'] = None
            got_new = True
        if extract_guest(text):
            self.state['guest'] = extract_guest(text)
            got_new = True
        if extract_mode(text):
            self.state['mode'] = extract_mode(text)
            got_new = True
        if extract_area(text):
            self.state['area'] = extract_area(text)
            got_new = True
        if extract_budget(text):
            self.state['budget'] = extract_budget(text)
            got_new = True

        # 已有分析上下文 + 用户没给新信息 -> 自由问答
        if not got_new and self.state.get('addresses') and self.state.get('category'):
            return self._free_chat(text)

        missing = []
        if not self.state['category']:
            missing.append('品类（奶茶/甜品/早餐/便利店）')
        if not self.state['addresses']:
            missing.append('商铺位置或地址')
        # 地址来自候选(pending_coord)时, 租金缺失不阻塞, 用默认继续
        from_candidate = bool(self.state.get('pending_coord'))
        if self.state['rent'] is None and not from_candidate:
            missing.append('月租金')
        if missing:
            return f'还需要你告诉我：{"、".join(missing[:2])}（一次说全更省事~）'
        self.state['phase'] = 'analysis'
        result = self.analyze()
        # 面积已知但没给装修预算 -> 提示(不阻塞)
        if self.state.get('area') and not self.state.get('budget'):
            result += ('\n\n💡 补充**装修预算**（如"装修预算10万"），'
                       '可评估装修档次对店铺吸引力的影响。')
        return result

    # -----------------------------------------------------------
    def _free_chat(self, text):
        """自由问答: 用户问改进建议/客流/运营等, 用 LLM 结合分析上下文回答
        支持三级降级: 小米 mimo -> DeepSeek -> 规则解读"""
        # 重新跑一次当前地址的评分, 作为上下文
        context = []
        for addr in self.state['addresses']:
            lng, lat = geocode(addr)
            if lng is None and self.state.get('pending_coord'):
                lng, lat = self.state['pending_coord']
            if lng is None:
                continue
            try:
                r = score_site(self.state['category'], lng, lat,
                               self.state['rent'] or 8000, name=addr,
                               area_m2=self.state.get('area'))
                context.append(json.dumps(r, ensure_ascii=False))
            except Exception:
                continue
        if not context:
            return self.analyze()
        # 用 LLM 回答（三级降级）
        sys_prompt = (
            '你是"浙里选址"的选址顾问。用户已经完成了一个商铺的选址分析，'
            '现在问你关于该商铺的改进建议、周边客流、运营策略等问题。'
            '以下是该商铺的评分数据（JSON）：\n' + '\n'.join(context) + '\n\n'
            '请结合这些数据，用口语化、专业、有建设性的方式回答用户的问题。'
            '涉及数据时必须引用上面 JSON 里的真实数值，不要编造。'
            '如果问题与选址无关（如闲聊），正常友好回答即可。'
        )
        # 主用: 小米 mimo
        try:
            return _call_llm(LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, sys_prompt, text, temperature=0.5, timeout=40)
        except Exception:
            pass
        # 备用: DeepSeek
        if LLM_FALLBACK_API_KEY:
            try:
                return _call_llm(LLM_FALLBACK_API_KEY, LLM_FALLBACK_BASE_URL, LLM_FALLBACK_MODEL, sys_prompt, text, temperature=0.5, timeout=40)
            except Exception:
                pass
        # 兜底: 规则解读
        return rule_based_interpret(context[0] if context else {})

    # -----------------------------------------------------------
    def _search_rental_shops(self, area, limit=8):
        """搜索指定区域候选商铺（混合方案）:
        1. 优先 58 同城真实出租数据（名称/面积/租金, Playwright抓取）
        2. 不足时用高德"商铺出租/商圈"POI 补足
        只保留浙江省范围内候选。"""
        from data.query import haversine
        candidates = []
        seen = set()
        target_lng, target_lat = geocode(area)
        if target_lng is None:
            return []

        def _add_candidate(name, address, lng, lat, source, area=None, price=None, precise=None,
                           real_addr=None):
            key = (name, round(lng, 4), round(lat, 4))
            if key in seen:
                return
            seen.add(key)
            candidates.append({
                'name': name, 'address': address,
                'lng': lng, 'lat': lat, 'source': source,
                'area': area, 'price': price, 'precise': precise,
                'real_addr': real_addr,
            })

        # 第1轮: 58同城真实出租数据（只抓一次; 精确 geocode 设预算, 省配额）
        try:
            from agent.rental58 import fetch_shops, CITY_CODES
            city = next((c for c in CITY_CODES if c in area), None)
            if city:
                # 区域过滤词: 去掉城市名(如"杭州滨江"→"滨江"; "杭州下沙"→"下沙")
                area_filter = area
                for c in CITY_CODES:
                    if area_filter.startswith(c):
                        area_filter = area_filter[len(c):]
                        break
                shops = fetch_shops(city, limit=limit, area_filter=area_filter or None)
                precise_budget = 4  # 精确 geocode 预算(次), 超出回落区域中心
                for s in shops:
                    # 58条目无坐标: 优先从 loc 提取"XX路XX号"定位(预算内),
                    # 否则直接回落区域中心(0 次额外 API)
                    lng, lat, precise = None, None, False
                    loc_text = (s.get('loc') or '').replace(' ', '')
                    m_addr = re.search(r'([\u4e00-\u9fa5]{1,10}(?:路|街|道|巷|弄|大道)[\u4e00-\u9fa5A-Za-z0-9]*\d*号?)', loc_text)
                    if m_addr and precise_budget > 0:
                        lng, lat = geocode(f'{city}{m_addr.group(1)}')
                        if lng:
                            precise_budget -= 1
                            precise = True
                    if lng is None and precise_budget > 0:
                        loc_parts = loc_text.split('-')
                        if len(loc_parts) >= 2:
                            street = loc_parts[-1]
                            if street and street not in ('空置中', '经营中') and '宁波' not in street:
                                lng, lat = geocode(f'{city}{street}')
                                if lng:
                                    precise_budget -= 1
                    if lng is None:
                        lng, lat = target_lng, target_lat  # 0次API: 回落区域中心
                    if not _in_zhejiang(lng, lat):
                        continue
                    if haversine(target_lng, target_lat, lng, lat) > 30000:
                        continue
                    real_addr = m_addr.group(1) if m_addr else None
                    _add_candidate(s['title'], s['loc'] or area, lng, lat,
                                   '58同城(在租商铺)', area=s['area'], price=s['price'],
                                   precise=precise, real_addr=real_addr)
                    if len(candidates) >= limit:
                        return candidates
        except Exception:
            pass

        # 第2轮: 高德"商铺出租" POI 兜底（候选太少时, 只搜 1 词 × 1 页）
        if len(candidates) < 3:
            from data.fetch_poi import search_poi
            for kw in ['商铺出租']:
                try:
                    rows, _ = search_poi(kw, area, max_pages=1)
                except Exception:
                    continue
                for r in rows:
                    lng, lat = r['lng'], r['lat']
                    if not _in_zhejiang(lng, lat):
                        continue
                    if haversine(target_lng, target_lat, lng, lat) > 30000:
                        continue
                    _add_candidate(r['name'], r['address'], lng, lat,
                                   '高德POI(商铺出租/招商信息)')
                    if len(candidates) >= limit:
                        return candidates

        # 第3轮: 商圈/商业楼宇 POI 兜底（仍不足且候选<3 时, 只搜 1 词 × 1 页）
        if len(candidates) < 3:
            from data.fetch_poi import search_poi
            for kw in ['购物中心']:
                try:
                    rows, _ = search_poi(kw, area, max_pages=1)
                except Exception:
                    continue
                for r in rows:
                    lng, lat = r['lng'], r['lat']
                    if not _in_zhejiang(lng, lat):
                        continue
                    if haversine(target_lng, target_lat, lng, lat) > 5000:
                        continue
                    _add_candidate(r['name'], r['address'], lng, lat,
                                   '高德POI(商圈/商业楼宇)')
                    if len(candidates) >= limit:
                        return candidates
        return candidates

    def _handle_no_shop_area(self, text):
        """无商铺分支: 解析区域, 搜索候选"""
        # 区域: 城市+区/地名
        area = extract_address(text)
        if area is None:
            # 尝试匹配"区域"词
            m = re.search(r'(杭州|宁波|温州|嘉兴|湖州|绍兴|金华|衢州|舟山|台州|丽水)[\u4e00-\u9fa5]{0,10}', text)
            area = m.group(0) if m else None
        if area is None:
            return '请告诉我具体区域，比如"杭州滨江区"或"宁波鄞州区"'
        # 清洗区域: 去掉"的商铺/商铺/附近/周边/一带"等后缀
        area = _clean_area(area)
        candidates = self._search_rental_shops(area)
        if not candidates:
            return (f'在「{area}」暂未搜到高德收录的商铺出租/招商信息。'
                    '建议换个区域，或告诉我具体商铺位置直接分析。')
        self.state['shop_candidates'] = candidates
        self.state['awaiting_choice'] = True
        lines = [f'在「{area}」为你找到以下候选商铺（实时抓取）：', '']
        for i, c in enumerate(candidates, 1):
            tag = '在租' if '58' in c['source'] else ('出租信息' if '出租' in c['source'] else '商圈位置')
            info = []
            if c.get('area'):
                info.append(f"{c['area']}㎡")
            if c.get('price'):
                info.append(f"{c['price']:.0f}元/月")
            extra = f"（{'，'.join(info)}）" if info else ''
            # 真实地址优先(地图定位的), 否则用平台文本
            show_addr = c.get('real_addr') or c.get('address') or area
            lines.append(f"**{i}. {c['name']}**  {tag}{extra}")
            lines.append(f"    🧭 地址：{show_addr}")
            if not c.get('real_addr'):
                lines.append(f"    ℹ️ 平台描述：{c.get('address', '')[:50]}")
            lines.append('')  # 每条候选之间空行, 避免挤在一起
        lines.append('回复序号（如"选1"）选择想分析的商铺；也可以告诉我其他位置。')
        return '\n'.join(lines)

    def _handle_choice(self, text):
        """处理用户从候选列表中的选择"""
        m = re.search(r'选\s*(\d+)|(\d+)\s*号?', text)
        if m:
            idx = int(m.group(1) or m.group(2)) - 1
            cands = self.state['shop_candidates']
            if 0 <= idx < len(cands):
                c = cands[idx]
                self.state['addresses'].append(c['name'])
                self.state['pending_coord'] = (c['lng'], c['lat'])
                self.state['awaiting_choice'] = False
                self.state['phase'] = 'have_shop'
                # 58 候选自带面积/租金, 直接填入
                filled = []
                if c.get('area'):
                    self.state['area'] = c['area']
                    filled.append(f"面积{c['area']}㎡")
                if c.get('price'):
                    self.state['rent'] = c['price']
                    filled.append(f"租金{c['price']:.0f}元/月")
                else:
                    # 平台无标价: 清掉旧租金, 分析时用默认, 避免沿用上一个铺子的租金
                    self.state['rent'] = None
                msg = f'已选：「{c["name"]}」（{c["address"]}）。'
                if filled:
                    msg += f'\n已按平台信息填入：{"、".join(filled)}（可在对话中修正）。'
                if c.get('precise') is False:
                    msg += ('\n⚠️ 该商铺仅有区域级定位（平台未提供精确坐标），'
                            '**分析将基于所在区域进行**。若知道具体门牌/路名，'
                            '可补充（如"滨江区长河路128号"）以获得精确分析。')
                msg += ('\n你的**品类**是？（如"奶茶"）'
                        '\n也可一并告诉我：**装修预算**（如"装修预算10万"）')
                return msg
            return '序号无效，请重新选择（如"选1"）。'
        # 用户可能直接给了新信息（如品类/租金）
        return self._collect_info(text)

    def analyze(self) -> str:
        cat = self.state['category']
        rent = self.state['rent'] or 8000  # 未给预算时用默认，并注明
        area = self.state['area']
        outputs = []
        new_results = []
        for addr in self.state['addresses']:
            lng, lat = geocode(addr)
            # 无商铺分支选中的: 用已存坐标
            if lng is None and self.state.get('pending_coord'):
                lng, lat = self.state['pending_coord']
            if lng is None:
                outputs.append(f'「{addr}」暂无法定位到坐标，请确认地址格式（如"杭州市西湖区文三路"）。')
                continue
            result = score_site(cat, lng, lat, rent, name=addr, area_m2=area,
                                budget=self.state.get('budget'))
            new_results.append(result)
            # 与历史分析对比(如有)
            if self.state['analyzed_history']:
                outputs.append(_build_comparison(result, self.state['analyzed_history']))
            outputs.append(llm_interpret(result))
        # 保存本次分析到历史(用于后续对比, 同名去重)
        for r in new_results:
            exist = any(h['name'] == r['name'] and h['lng'] == r['lng']
                        for h in self.state['analyzed_history'])
            if not exist:
                self.state['analyzed_history'].append({
                    'name': r['name'], 'total': r['total'], 'verdict': r['verdict'],
                    'dims': r['dims'], 'lng': r['lng'], 'lat': r['lat'],
                    'area_m2': r.get('area_m2'), 'evidence': r['evidence'],
                })
        if rent is None and self.state['rent'] is None:
            outputs.append('（注：你未提供月租金，暂按默认 ¥8000 测算，可在对话中补充）')
        if area is None:
            outputs.append('（注：你未提供商铺面积，暂未测算水电成本与盈利，可补充面积获得完整测算）')
        self.state['phase'] = 'analysis'
        return '\n\n'.join(outputs)


# ---------------------------------------------------------------
# 5. 地理编码（高德 API 优先 + 本地库兜底 + 浙江范围校验）
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


def demo():
    """命令行演示"""
    agent = SiteAgent()
    print('=== 浙江商铺选址顾问（演示模式）===')
    print('提示：说清"品类+地址+预算"，如：想在杭州西湖区文三路开奶茶店，月租8000')
    print('输入 q 退出\n')
    while True:
        try:
            text = input('你: ').strip()
        except (EOFError, KeyboardInterrupt):
            break
        if text.lower() in ('q', 'quit', 'exit'):
            break
        print('顾问:', agent.ask(text), '\n')


if __name__ == '__main__':
    demo()
