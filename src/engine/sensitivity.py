# -*- coding: utf-8 -*-
"""敏感性阶梯（#10）—— 把引擎算好的结论排成可拖动的情景。

⚠️ **核心纪律（不能破）**：所有数字都由**既有引擎**算出
   （`store_diagnosis.diagnose_existing_store`），本模块
   **不新造口径、不在前端复刻公式、不在这里算钱**。
   它只做一件事：**把同一个引擎在若干档输入下各跑一遍，排成阶梯**。

   为什么必须这样：拖动出来的净利若与静态分析的净利对不上，用户看到的
   就是**两套账**——这种"改了但没改对"是本项目第一高发错。
   宁可多跑几次引擎（实测单次 ~94ms），也不许出现第二个算法。

为什么是**单因素扫描**而不是三维网格：
   三维 7×7×7 = 343 次引擎调用（~32 秒），没人等得起；
   而敏感性分析的标准做法本来就是**一次只看一个变量**，读起来也更清楚
   （"租金每降 800，月净利多 XXX"）。所以：**一次只变一个，其余保持基准**。

⚠️ 刻意**不自造"结论档"**（如"稳/勉强/亏"）：那是新口径。
   本模块只回引擎给的原始数字，是否"能签"由引擎既有的
   `月净利 ≤ 0 → 一票否决` 规则判（前端据此高亮），不另立标准。
"""

# 档数：7 档 = 基准 + 上下各 3 档。再多前端滑块会挤，再少看不出趋势。
STEPS = 7
# 扫描跨度：基准 ±40%。取 ±40% 是因为租金谈到 ±40% 已是现实中的极限区间
# （再往外就不是"敏感性分析"而是"另一个铺子"了）。
SPAN = 0.4
# 外卖占比也用 ±40% **相对基准**扫，而不是"绝对值 0~70%"：
# 外卖占比是**品类的结构性特征**（奶茶 35%、便利店 10%），跨品类横着扫没有意义；
# 相对基准扫才回答"如果我的外卖比品类常态高/低 40%，净利怎么变"。
TAKEOUT_SPAN = 0.4
# 取整粒度：租金到百元（实盘报价就是百元级），日单量到单。
RENT_ROUND = 100


def _ladder_values(center, span=SPAN, n=STEPS, round_to=1, floor=None):
    """以 center 为中心，等距铺 n 档。返回**升序**的整数列表。

    floor：下限（如月租不能为负、日单量必须 ≥1）。
    """
    if center is None:
        return []
    try:
        c = float(center)
    except (TypeError, ValueError):
        return []
    if c <= 0:
        return []
    lo, hi = c * (1 - span), c * (1 + span)
    vals = []
    for i in range(n):
        v = lo + (hi - lo) * i / (n - 1)
        # ⚠️ 只有**整数粒度**（租金到百、日单量到 1）才能 `int()`。
        #    小数粒度（外卖占比到 0.01）用 int 会把 0.35 截成 **0**，整个阶梯塌掉
        #    —— 2026-09-26 加"外卖占比"维度时踩到（`int(round(0.35/0.01)*0.01)` = `int(0.35)` = 0）。
        v = round(v / round_to) * round_to
        v = int(v) if round_to >= 1 else round(v, 6)
        if floor is not None:
            v = max(v, floor)
        vals.append(v)
    # 去重（round 之后可能出现相等的相邻档）+ 保序
    out = []
    for v in vals:
        if not out or v != out[-1]:
            out.append(v)
    return out


def _one(category, *, rent, revenue, area_m2, city, investment, staff,
         brand, scenario, takeout=None):
    """跑一档，从引擎结果里抽几个数字。取不到就给 None（**不猜**）。

    ⚠️ 传的是**月流水**而不是"日单量 × 客单价"：
       客单价可能被品牌级校正（`price_ref`）改过，画像里的 price 未必等于
       分析时实际用的那个 ⇒ 用乘法换算会让**基准档与静态分析对不上**。
       改成"流水进、日单量只作显示"后，基准档必然逐位复原。
    """
    from engine.store_diagnosis import diagnose_existing_store
    r = diagnose_existing_store(
        category, monthly_revenue=revenue, monthly_rent=rent,
        area_m2=area_m2, city=city, staff=staff, investment=investment,
        brand=brand, scenario=scenario, takeout_ratio=takeout)
    # 「租金天花板」= 引擎二分反解出来的临界租金。它是一个 dict，含**两个口径**：
    #   '盈亏平衡月租'    —— 正好吃平（净利 = 0）的租金
    #   '回本达标月租上限' —— 还能在回本期限内回本的租金上限（**这才是"能签多少"**）
    # ⚠️ 两个都必须留着，不许只留一个：前者是"不能越过"的线，后者是"建议压到这里"。
    #    只留盈亏平衡的话，用户会把"吃平"当成"可以签" —— 那是两种结论。
    _rl = r.get('租金临界点(引擎二分)') or {}
    _in = r.get('输入') or {}
    return {
        # ⚠️ 不在这里塞 `值` —— 三个维度（租金/日单量/外卖占比）的值语义不同，
        #    由 `sensitivity_ladder` 显式写，避免"这个 0.35 到底是钱还是比例"的混乱。
        '月净利': r.get('月净利'),
        # ⚠️ 天花板由**流水与成本结构**决定，与"当前报的月租"无关 ——
        #    所以拖【租金】时它不变（变的是净利），拖【日单量】时它才跟着变。
        '盈亏平衡月租': _rl.get('盈亏平衡月租'),
        '回本达标月租上限': _rl.get('回本达标月租上限'),
        '净利率': r.get('净利率'),
        '安全边际额': r.get('安全边际额'),
        # 用工人数与口径 —— 只用于检测"隐性台阶"（见 `_kink_note`），不是给用户看的指标
        '人数': _in.get('人数'),
        '人数口径': _in.get('人数口径'),
    }


def _kink_note(prev, cur):
    """相邻两档之间若有「隐性台阶」就说明原因；没有返回 ''。

    ⚠️ 为什么必须标出来（2026-09-26 实测）：
       日单量 250 → 283 时，引擎把用工人数从 **2 人升到 3 人**（人均 140 单/天），
       月人工 +5760 元，于是**净利率反而从 0.2734 掉到 0.2566**。
       不标的话，用户看到"单量涨了、利润没跟上"会以为系统算错了 ——
       而**产能台阶恰恰是敏感性分析最该暴露的东西**
       （250 单时觉得"再多做 33 单能多赚"，其实会被第三个人的人工吃掉）。

    ⚠️ 判据只用**引擎自己给的 `人数`**，不猜、不用斜率阈值 ——
       斜率阈值会在平坦段误报。
    """
    a, b = prev.get('人数'), cur.get('人数')
    if a and b and a != b:
        # ⚠️ 不再给 `人数口径` 套括号 —— 它自己就带括号（'…（日单量 283 ÷ 人均 140 单/天）'），
        #    套一层会变成双层括号，卡片上很难读。
        _why = cur.get('人数口径') or ''
        return (f'用人从 {a} 人升到 {b} 人' + (f' —— {_why}' if _why else '')
                + '。人工是**台阶式成本**，这一档的增量会被它吃掉一部分')
    return ''


def sensitivity_ladder(category, monthly_rent, monthly_revenue, price=None,
                       area_m2=30, city='宁波', investment=None, staff=None,
                       brand=None, scenario='中性', steps=STEPS,
                       takeout_base=None):
    """生成「租金 / 日单量」两条敏感性阶梯，外加一个基准点。

    monthly_revenue : 选中铺子的**基准月流水** —— 必须与静态分析用的是同一个值
                      （取自 `result['profit']['输入']['实际月流水']`），
                      这样基准档才可能与静态分析**逐位一致**。
    price           : **只用于把流水换算成日单量显示**（滑块刻度上给用户看"每天多少单"），
                      **不参与任何计算** —— 计算一律用流水。
                      若客单价被品牌级校正改过，画像默认值会偏；用流水进、日单量只作显示，
                      基准档就不会因为换算而漂移。

    返回
    ----
    {
      '基准':   {'月租':…, '日单量':…, '月净利':…, '盈亏平衡月租':…,
                 '回本达标月租上限':…, '净利率':…, '安全边际额':…},
      '租金':   [{'值':4800,'月净利':…,'盈亏平衡月租':…,
                  '回本达标月租上限':…,'净利率':…,'安全边际额':…,'台阶':''}, …],
      '日单量': [{'值':…, …}, …],
      '口径':   '单因素扫描：一次只变一个变量，其余保持基准；数字全部来自引擎 …',
    }
    流水缺失/非正 → 返回 None（**不猜、不编**，上层不渲染滑块即可）。
    """
    try:
        revenue = float(monthly_revenue)
    except (TypeError, ValueError):
        return None
    if revenue <= 0:
        return None
    if price is None:
        try:
            from config import get_profile
            price = get_profile(category).get('price')
        except Exception:
            price = None
    try:
        price = float(price)
    except (TypeError, ValueError):
        price = 0.0
    if price <= 0:
        price = 16.0            # 画像都拿不到时的兜底（只影响显示刻度，不影响钱）
    # 显示用基准日单量 —— 只进滑块刻度与文案，不进计算
    base_orders = revenue / (price * 30)

    # 外卖占比基准：引擎的**品类默认**（用户没在滑块上改过时就是它）
    if takeout_base is None:
        try:
            from engine.utilities import get_delivery_ratio
            takeout_base = get_delivery_ratio(category)
        except Exception:
            takeout_base = 0.30

    kw = dict(area_m2=area_m2, city=city, investment=investment,
              staff=staff, brand=brand, scenario=scenario)
    base = _one(category, rent=monthly_rent, revenue=revenue, **kw)
    base['月租'] = monthly_rent
    base['日单量'] = round(base_orders)
    base['外卖占比'] = round(float(takeout_base), 4)

    rent_rungs = []
    for v in _ladder_values(monthly_rent, n=steps, round_to=RENT_ROUND, floor=0):
        r = _one(category, rent=v, revenue=revenue, **kw)
        r['值'] = v
        # 台阶挂在**跳变到的那一档**上，前端拖到该档时提示
        r['台阶'] = _kink_note(rent_rungs[-1], r) if rent_rungs else ''
        rent_rungs.append(r)

    order_rungs = []
    for v in _ladder_values(base_orders, n=steps, round_to=1, floor=1):
        # 日单量档 -> 流水：这一步只是**显示口径的换算**，钱仍由引擎算
        r = _one(category, rent=monthly_rent, revenue=v * price * 30, **kw)
        r['值'] = v
        r['台阶'] = _kink_note(order_rungs[-1], r) if order_rungs else ''
        order_rungs.append(r)

    # 外卖占比阶梯（#10 第二版 2026-09-26）：绝对值档（比例），不是金额。
    # 它是**成本侧**的杠杆：外卖抽成 = 流水 × 外卖占比 × 抽成率(22%)。
    takeout_rungs = []
    for v in _ladder_values(float(takeout_base), n=steps, round_to=0.01,
                            floor=0.0, span=TAKEOUT_SPAN):
        r = _one(category, rent=monthly_rent, revenue=revenue, takeout=v, **kw)
        r['值'] = round(v * 100)      # 前端直接显示成百分数的分子（如 35 = 35%）
        r['台阶'] = _kink_note(takeout_rungs[-1], r) if takeout_rungs else ''
        takeout_rungs.append(r)

    return {
        '基准': base,
        '租金': rent_rungs,
        '日单量': order_rungs,
        '外卖占比': takeout_rungs,
        # 换算口径必须写出来 —— 否则用户不知道滑块的"日单量"是拿哪个客单价折的
        '日单量换算价': round(price, 2),
        '口径': (f'单因素扫描：一次只变一个变量，其余保持基准（{scenario}档）；'
                 f'每档都是把**同一个引擎**跑一遍的结果，不是另一套算法；'
                 f'扫描跨度基准 ±{SPAN:.0%}，{len(rent_rungs)} 档。'
                 f'「日单量」按客单价 ¥{price:.0f} 折自月流水，**只用于显示刻度**，'
                 f'计算全程用流水，所以基准档与静态分析逐位一致。'),
    }
