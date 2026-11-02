# -*- coding: utf-8 -*-
"""业态判定（#11）—— LLM 只出「标签」，成本影响由**映射表**决定。

## 边界（策 2026-09-26 拍板：**允许影响数字**）

所以本模块会**改变净利**。既然改了数字，就用下面三条把它管住：

1. **LLM 只输出标签，不输出任何数字**
   （红线的原话是「引擎产数、LLM 产文」—— 这里 LLM 产的是**分类**，
   标签→查表→传引擎，钱仍由 `estimate_profit` 算）。
2. **判定结果落盘缓存**（`data/biz_type_cache.json`）：
   同一个铺位只判一次，之后复用 ⇒ 把"同一输入两次跑结果不同"压到最低。
   缓存可整体删除（下次遇到会重新判），所以错判不会永久固化。
3. **映射表是本模块唯一的数值来源，且**从 `SCENARIOS` 派生**，不另抄一份
   —— 否则"场地附加费率"会有两处表面（改一处漏一处，本项目第一高发错）。

## 为什么只覆盖「场地附加费率」一个参数

`场地附加费率` 正是"商场扣点/物业费/推广费"这一项，它是**业态的直接函数**；
而 `税负率` / `损耗率` / `人均日单量` 与业态无关（那是"情景"的语义）。
所以判定出业态后**只覆盖这一个费率**，不动其余假设 ——
否则"判出商场店"会连带改掉跟业态无关的三个参数，影响面失控。

⚠️ 判定不出（'未知' / LLM 挂了 / 缓存里是空）⇒ **不覆盖**，沿用用户选的情景档。
   绝不为了"看起来更聪明"而硬套一个业态。
"""
import hashlib
import json
import re

from engine.utilities import SCENARIOS, DEFAULT_SCENARIO

# ---------------------------------------------------------------
# 业态 → 场地附加费率。数值**全部从 SCENARIOS 派生**，一处都不另写。
# ---------------------------------------------------------------
_FEE = {
    'street': SCENARIOS['乐观']['场地附加费率'],   # 0.00
    'mid': SCENARIOS[DEFAULT_SCENARIO]['场地附加费率'],   # 0.06（中性）
    'mall': SCENARIOS['保守']['场地附加费率'],     # 0.15
}

# 可选标签 → (费率档, 为什么)。**标签集是封闭的**：
# LLM 只能在里面选，不许自由发挥 —— 自由发挥就没法映射到确定成本。
BIZ_TYPES = {
    '商场店':     ('mall', '购物中心/百货内铺位，普遍有销售扣点或物业+推广费'),
    '街边铺':     ('street', '临街独立铺，物业费与推广费自理（并入杂费）'),
    '社区底商':   ('mid', '小区底商，通常有物业费、无销售扣点'),
    '写字楼配套': ('mid', '写字楼/园区配套，物业费中等、无扣点'),
    # ⚠️ 2026-09-26 由「学校内档口」改成「档口摊位」：实测 58 的平台标签就是
    #    `档口摊位`（28 条），它是**泛指**的（美食城/园区/校内都有），
    #    原命名太窄，映射时会漏。
    '档口摊位':   ('mall', '档口/摊位，普遍按流水抽点（美食城/园区/校内均有）'),
}
VALID_TYPES = tuple(BIZ_TYPES)
UNKNOWN = '未知'

# ---------------------------------------------------------------
# 58 平台标签 → 本项目的 5 类（**平台标签优先，LLM 兜底**）
# ---------------------------------------------------------------
# ⚠️ 为什么改成"平台优先"（2026-09-26 评估后定的）：
#    实测 LLM 判定 vs 58 标签的一致率只有 **45%**（97 条抽样），
#    其中 6 条把非商场判成「商场店」（被"大厦/MALL/广场"诱导）——
#    那是**最贵的错**（场地附加费率 0 → 15%，直接改净利）。
#    而 58 卡片**自带业态标签、覆盖率 99%** ⇒ 用它更稳、零 LLM、完全可复现。
#    LLM 只在**没有平台标签**时兜底（如用户手输地址"杭州湖滨银泰in77"）。
#
# ⚠️ 这层映射是**人工判断**（不是数据），写在明处：
#    `商业街店铺`/`商业街`/`沿街商铺` 都归「街边铺」—— 都是沿街零售铺；
#    `底商` 归「社区底商」；`购物中心` 归「商场店」。
PLATFORM_MAP = {
    '临街门面': '街边铺',
    '商业街店铺': '街边铺',
    '商业街': '街边铺',
    '沿街商铺': '街边铺',
    '写字楼配套': '写字楼配套',
    '社区底商': '社区底商',
    '底商': '社区底商',
    '档口摊位': '档口摊位',
    '购物中心': '商场店',
}


def fee_for(biz_type):
    """业态 -> 场地附加费率。判不出/不认识 -> None（**不覆盖**，沿用情景档）。"""
    hit = BIZ_TYPES.get(biz_type or '')
    return _FEE[hit[0]] if hit else None


def why_for(biz_type):
    """业态 -> 一句话依据（给结果里出声用）。判不出返回 ''。"""
    hit = BIZ_TYPES.get(biz_type or '')
    return hit[1] if hit else ''


# ---------------------------------------------------------------
# 判定（LLM 只出标签）+ 落盘缓存
# ---------------------------------------------------------------
_CACHE = None
_CACHE_PATH = None
_CACHE_CAP = 800          # 只保留最近 N 条，防无限增长


def _norm_key(text):
    """铺位文本 -> 缓存键。

    ⚠️ 先**规范化**再哈希：58 的标题会带空格/全角标点/零宽字符，
       同一铺位在不同轮次里字符串可能差一个空格 —— 直接拿原文当键会
       每次都 miss、每次都重新判（缓存等于没做，可复现性也没了）。
    """
    t = str(text or '')
    t = re.sub(r'[\s\u200b-\u200f\ufeff]+', '', t)
    t = re.sub(r'[，。、；：（）()\[\]【】!！?？·—\-_/|]', '', t)
    return hashlib.sha1(t.encode('utf-8')).hexdigest()[:16]


def _cache():
    global _CACHE, _CACHE_PATH
    if _CACHE is None:
        from config import DATA_DIR
        _CACHE_PATH = DATA_DIR / 'biz_type_cache.json'
        try:
            _CACHE = json.loads(_CACHE_PATH.read_text(encoding='utf-8'))
        except Exception:
            _CACHE = {}
    return _CACHE


def _save():
    try:
        if _CACHE_PATH is not None and _CACHE is not None:
            items = list(_CACHE.items())[-_CACHE_CAP:]
            _CACHE_PATH.write_text(json.dumps(dict(items), ensure_ascii=False),
                                   encoding='utf-8')
    except Exception:
        pass


PROMPT = (
    '你是商铺业态分类器。**只输出一个标签**，不要标点、不要解释、不要任何其它字。\n'
    '可选标签（必须原样选一个）：' + '、'.join(VALID_TYPES) + '\n'
    f'若信息不足以判断，就输出：{UNKNOWN}\n\n'
    '判据提示：出现"购物中心/商场/百货/XX广场内/楼层铺位"→ 商场店；'
    '"临街/沿街/门面/街边"→ 街边铺；"小区/社区/底商/XX苑"→ 社区底商；'
    '"写字楼/园区/办公配套"→ 写字楼配套；"食堂/档口/校内"→ 学校内档口。'
)


def classify(text, use_cache=True):
    """铺位文本 -> 业态标签（或 '未知'）。**判不出永远返回 '未知'，不猜。**

    返回 (标签, 来源)；来源 ∈ {'缓存', 'LLM', '跳过'}。
    """
    key = _norm_key(text)
    c = _cache()
    if use_cache and key in c:
        # ⚠️ 缓存里**连「原始认定方式」一起存**（2026-09-26 实机探针 §20 抓到）：
        #    原来只存标签，命中时来源写成「缓存」—— 用户看到
        #    「业态判定（社区底商·缓存）」**分不出这条是平台标的还是 LLM 判的**，
        #    而这两者可信度差很远（平台标签 99% 覆盖且零 LLM；LLM 一致率只有 45%）。
        #    新格式 {'t': 标签, 's': 原始来源}；旧格式（纯字符串）**读时兼容**。
        _v = c[key]
        if isinstance(_v, dict):
            return _v.get('t', UNKNOWN), '缓存（原判定：%s）' % (_v.get('s') or '?')
        # 旧格式（只有标签、没记来源）：那时的缓存**只可能来自 LLM 路径** ——
        # 平台标签是 2026-09-26 才接进来的，且平台路径**根本不写缓存**（纯映射、零成本）。
        # ⇒ 如实标成「缓存（LLM 判定）」，而不是含糊的「缓存」：
        #   用户要能分辨这笔费率是平台标的还是 LLM 判的。
        return _v, '缓存（LLM 判定）'
    if not str(text or '').strip():
        return UNKNOWN, '跳过'
    lab = UNKNOWN
    src = 'LLM'
    try:
        # ⚠️ 预算是**故意收紧**的：业态判定是**增值功能**，判不出只是"不覆盖情景档"，
        #    主链路照常跑。所以宁可快速失败，也不让分析界面为了它多等十几秒
        #    （门禁套件每次都会走分析节点，budget 放大会让 20 套门禁整体变慢）。
        from agent.llm import call_llm_sync
        # temperature=0：分类任务要的是稳定，不是发挥
        out = call_llm_sync(PROMPT, str(text)[:600], temperature=0.0,
                            timeout=12, total_budget=16)
        # ⚠️ 中文引号写成 \u 转义，不用字面量 —— 上一版写成字面量时被 Python
        #    当成"相邻字符串隐式拼接"才侥幸跑通，读代码的人会以为是 ASCII 引号。
        s = re.sub(r'[\s，。、；：\u201c\u201d\u2018\u2019（）()]+', '',
                   str(out or ''))
        for t in VALID_TYPES:
            if t in s:            # 只认白名单里的标签；LLM 多说几个字也能捞出来
                lab = t
                break
    except Exception:
        lab = UNKNOWN
        src = '跳过'
    if use_cache:
        # 连认定方式一起存（见上面缓存读取处的注释）
        c[key] = {'t': lab, 's': src}
        _save()
    return lab, src        # ⚠️ 返回 src 而不是硬编码 'LLM' —— 否则异常时'跳过'会被谎报成'LLM'


def from_platform(platform_biz):
    """58 平台标签 -> 本项目业态；映射不到返回 None（**不硬套**）。"""
    return PLATFORM_MAP.get(str(platform_biz or '').strip())


def resolve(text, platform_biz=None, use_cache=True):
    """铺位 -> 可直接喂给引擎的一整包。**平台标签优先，LLM 兜底**；都拿不到就 None。

    返回
    ----
    {'业态': 标签, '场地附加费率': 0.15 或 None, '依据': '…', '判定来源': '…'}
    判不出时 `场地附加费率` 为 None ⇒ 引擎**不覆盖**，沿用用户选的情景档。

    ⚠️ 优先用平台标签（理由见 `PLATFORM_MAP` 上面的注释：LLM 一致率只有 45%）。
    ⚠️ 平台标签映射不到本项目类时**继续走 LLM**，不当成"判不出" —— 那是两种情形。
    """
    mine = from_platform(platform_biz)
    if mine:
        return {'业态': mine, '场地附加费率': fee_for(mine), '依据': why_for(mine),
                '判定来源': f'平台标注（58「{str(platform_biz).strip()}」）'}
    lab, src = classify(text, use_cache=use_cache)
    return {'业态': lab, '场地附加费率': fee_for(lab),
            '依据': why_for(lab), '判定来源': src}
