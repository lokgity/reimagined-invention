# -*- coding: utf-8 -*-
"""
scoring.py —— 选址评分引擎（真 Huff 引力模型 v4）
====================================================
通用框架 4 维度（0~100 分）:
  客群匹配度 / 竞争压力 / 交通可达性 / 租金承受力
总分 = Σ(维度分 × 品类权重)

模型演进:
- v2: 距离衰减计数器（Σ1/(d+d0)^λ），无捕获份额概念
- v4: 真 Huff 模型 —— 引入品牌引力 S 与捕获份额 P
  · 竞争维度: P = (S_自/d0^λ) / (S_自/d0^λ + Σ_k S_k/(d_k+d0)^λ)
    S_k 由品牌系数表查得（brands.py，窄门餐眼门店量级分档），
    同商场内实证：品牌系数 vs 月售 Spearman=0.414
  · 流水估算: 日单量 = 基准日单量 × (D×P)/REF_DP × 面积/城市/保守系数
    D = 周边客群 POI 加权规模；REF_DP 由 83 家真实门店的 D×P 中位数锚定
    （⚠️ **实际采用的是"剔除低证据点后 77 家"** 的中位 —— 见下表口径注记）
  · λ = 2.0 取 Huff(1963) 文献常用值，83 家真实门店敏感性检验:
    λ∈[1.5,2.5] 门店排名两两 Spearman ≥ 0.981，结论不依赖 λ 精确取值
- v5: 锚点口径修正 + 品牌同商圈溢价
  · 修正标定时 own_S 退化为 1.0 的 bug（83 行仅 1 行有系数列）:
    REF_DP 4.35→6.2489, P_REF 0.40→0.5012
    ⚠️ 早期文档里写 0.5232 是**另一个量**（calibrate_brand_uplift 的"密度调整后"值），
       不能拿来当运行时锚点（口径错配）；引擎用的一直是 0.5012。
  · 新增品牌溢价 UPLIFT（同商圈内校准），仅作用于流水估算
  · **锚点不按品牌分别标定** —— 实测商圈解释 D×P 方差 69.5%、
    品牌仅 8.0%，按品牌标定不可辨识（见 REF_DP 上方注释）
- v6（2026-09-18）: UPLIFT 整表重标定 —— 样本从"3 个人工大商圈 / 77 家 / 9 品牌"
  换成"代理商圈 + 全库奶茶 POI"共 1631 家 / 28 品牌
- v7（2026-09-18，当前）: UPLIFT 换成**品牌盲残差**口径，消掉与品牌引力的双算
  · 旧口径直接比 D×P，而 D×P 的品牌差异**只**来自 own_S ⇒ 与 P 里的 own_S 重复计入
  · 新口径用"自己 S 置 1.0 重算"的 D×P 比同商圈中位 ⇒ 与 own_S 正交
    （Spearman(own_S, uplift) +0.6719 → +0.1531；蜜雪 1.1903→1.0018、个体/杂牌 0.8370→1.0111）
  · clamp 改为分层：TIER1 免 clamp（v6 曾把瑞幸的真实收缩值 1.2743 截到 1.2500）
  ⚠️ 详细归因与实测见 brands.py 的 UPLIFT 注释块 + analysis/recalibrate_uplift_v3.py
- 循环论证修复: 流水不再由客群/竞争评分反推，而是由 D×P 模型结构直接产出

明确局限（答辩必讲）:
- 基于公开 POI 数据，不含真实人流量/成交租金/营业额
- λ 为文献值+稳健性检验，非逐店标定；S 为分档参考值
- 品牌表当前覆盖奶茶品类，其他品类自动退化为 S=1 的纯距离 Huff
- 品牌溢价样本 1631 家门店 / 28 个品牌（代理商圈口径，n=3~557，2026-09 两次口径变更）
- ⚠️ 品牌溢价**曾经**与品牌引力 S 同源（v6 直接比 D×P ⇒ 重复计入品牌力 ⇒ 双算，
  蜜雪虚高 +19.0%）；v7 已改成"品牌盲残差"把它消掉。但它度量的只是
  **位置/竞争微区位残差**，仍然不能当作品牌力的独立证据，也不能读成"流水就会高这么多"
- 输出为"选址适宜度相对评分"，非营收预测
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import get_profile  # noqa: E402
from data.query import query_within, nearest_distance, haversine  # noqa: E402
from engine.realtime import get_surrounding  # noqa: E402
from engine.brands import (brand_attractiveness, BRAND_S,  # noqa: E402
                           brand_uplift, brand_uplift_detail,
                           UPLIFT, UPLIFT_TIER, DISTRICT_MEDIAN_DP)
from engine.utilities import DEFAULT_SCENARIO  # noqa: E402


# ---------------- 距离口径：步行路网距离（2026-09-20 起） ----------------
# 口径来源：高德 `/v3/distance` 的 **type=3 步行规划距离**，一次性抓取后**冻结**在
#           `data/road_distance.db`（见 `src/data/road.py` 的模块说明）。
# 为什么不用直线距离：人能走的是路，不是直线。实测同一商圈内 73 个点，
#   「步行/直线」= 最低 0.66 / 中位 1.26 / 最高 2.09 —— 差异不是常系数，逐对儿不同，
#   所以**不能用一个"绕行系数"近似**（那属于编数据，撞红线 1）。
# ⚠️ 也**不用 type=1 驾车距离**：那是车能走的路（受单行道影响，实测同一点驾车 823m
#   而步行 433m）。
# ⚠️ 取数失败**逐点回退直线并留痕**（`距离口径` 字段 + DIST_STATS），不静默（红线 4）。

# 粗筛安全边际：实测最高绕行 2.09，取 2.5 留边际。
# ⚠️ 这个系数**不影响结论** —— 它只决定"向高德要哪些点"；最终入选与否由
#    「步行距离 ≤ radius」这一步决定。系数据实测定，不是模型参数。
_COARSE = 2.5

DIST_STATS = {'walk': 0, 'fallback': 0}


def dist_report():
    """本次进程内的距离口径统计（供看板/报告如实披露）。"""
    n = DIST_STATS['walk'] + DIST_STATS['fallback']
    return {
        '口径': '步行路网距离（高德 type=3 步行规划，冻结本地库）',
        '步行': DIST_STATS['walk'],
        '直线回退': DIST_STATS['fallback'],
        '直线回退占比': (round(DIST_STATS['fallback'] / n, 4) if n else 0.0),
    }


def query_pois(category, lng, lat, radius):
    """统一 POI 查询入口。**`distance` 口径 = 步行路网距离。**

    三段式：
      ① 粗筛 —— 按 `radius × 2.5` 的**直线**半径取候选（宽，保证不漏；
         实测存在"步行走大楼入口"导致 步行 < 直线 的点，如 0.66 倍）；
      ② 取数 —— 要这些点到本铺位的步行距离（冻结库优先，命中即 0 次 API）；
      ③ 精筛 —— 只保留 **步行距离 ≤ radius** 的点。
    半径的语义因此统一为「**步行路网半径**」。
    """
    cand = get_surrounding(category, lng, lat, int(radius * _COARSE))
    if not cand:
        return []
    from data import road as _road
    walk = _road.fetch_and_store((lng, lat), [(p['lng'], p['lat']) for p in cand])
    out = []
    for p in cand:
        k = (_road.q(p['lng']), _road.q(p['lat']))
        w = walk.get(k)
        if w is not None:
            if w > radius:                 # 步行超半径 → 不入选
                continue
            p['distance'] = int(round(w))
            p['距离口径'] = '步行路网'
            DIST_STATS['walk'] += 1
        else:                              # 取数失败 → 回退直线，留痕
            d = haversine(lng, lat, p['lng'], p['lat'])
            if d > radius:
                continue
            p['distance'] = int(round(d))
            p['距离口径'] = '直线(路网取数失败)'
            DIST_STATS['fallback'] += 1
        out.append(p)
    return out

# ---------------------------------------------------------------
# Huff 引力模型参数
# ---------------------------------------------------------------
LAMBDA = 2.0    # 距离衰减参数（Huff 文献常用值 λ=2，答辩中说明为估计）
D0 = 50.0       # 最小等效距离(米)：避免 d→0 时引力爆炸，也模拟店前 50m 的"到店距离"


def huff_gravity(pois, lam=LAMBDA, d0=D0):
    """Huff 引力累计: Σ (1/(d+d0))^λ。pois 需含 distance 字段"""
    g = 0.0
    for p in pois:
        d = p.get('distance', 0) or 0
        g += (1.0 / (d + d0)) ** lam
    return g


# 客群匹配度归一化基准（真实数据校准）:
# 以"核心商圈级客群引力"= 90 分。杭州湖滨银泰实测 ~1.7e-04(未加权),
# 加权后约 1e-04。取 1.1e-04 作为 90 分基准（留出 100 分给超一线商圈）。
GUEST_GRAVITY_90 = 1.1e-4


# ---------------------------------------------------------------
# 真 Huff 捕获份额（v4 核心）
# ---------------------------------------------------------------
# 流水锚点常量: 83 家真实门店（宁波天一/杭州in77/海宁银泰）用本引擎
# 相同查询路径实测的 D×P 中位数（见 analysis/calibrate_anchor.py）。
# 含义: 一家中位水平门店的日单量 ≈ 品类基准日单量(profile['daily_sales'])
#
# ⚠️ 口径注记（2026-09-18 落实裁决第 4 项"注释与代码对齐"，**不改数值**）：
#   ① "83 家"是**总样本**；本值实际是**剔除低证据点后 77 家**的中位。
#      （低证据点判据 D<3 且 P>0.8，与标定脚本一致；标定产物 brand_uplift.json
#        的 global_ 里同时记着 n_total=83 与 n_used=77。）
#   ② P_REF=0.5012 有约 **+0.0015（+0.3%）复现不出来**：同口径下用本地库重算
#      可得 0.499702（见 analysis/expand_sample.py 的对拍段）。差额无实质影响，
#      但**如实记下来**，不要让下一个人以为它能逐位复现。
#   ③ 早期文档里的 0.5232 是 calibrate_brand_uplift 的"密度调整后"值，
#      与这里未做密度调整的口径不匹配，不能混用（见 §4.1 口径注记）。
#
# ⚠️ 口径修订 2026-09-15（锚点 bug 修复）
#   原 calibrate_anchor.py:63 读 stores_calib.csv 的「吸引力系数」列，
#   该列 83 行仅 1 行非空 → 标定时 own_S 退化为 1.0（品牌盲）。
#   但运行时传 BRAND_S[brand]（带品牌）：分子带品牌、分母不带，
#   导致 P 被系统性抬高，锚点也用错口径。修正后（71/83 按品牌解析）:
#       REF_DP  4.35  → 6.2489 (×1.4365)
#       P_REF   0.40  → 0.5012 (×1.2530)
#   影响: 竞争分整体下降、流水估算更保守（蜜雪案例 96→75 分）。
#   注意: 这两个值由 calibrate_anchor.py **同一次运行**产出，
#         口径必须一致（同为"品牌一致 + 全样本中位 + 未做密度调整"）。
#         不要单独替换其中一个。
#   副作用（已知且可接受）: P_REF 上调使 K=60/P_REF 从 150 降到 119.7，
#         截断阈值 P* 从 0.6667 升到 0.8353 → 被 100 分截断的门店
#         反而从 25 家减少到 8 家（截断问题**改善**）。
#
# ⚠️ 为什么锚点不按品牌标定（可辨识性检验）
#   实测 D×P 的方差分解（83 家门店，3 商圈）:
#       R²(仅商圈哑变量, 2 参数) = 0.6946
#       R²(仅品牌哑变量, 9 参数) = 0.0795
#       ΔR²(商圈之上再加品牌)    = 0.041
#       同品牌跨商圈 D×P 极差: 蜜雪 4.58x / 沪上阿姨 4.61x / CoCo 4.02x
#   → 品牌样本量极小（30+ 品牌分 83 店）且与商圈高度混淆，
#     "品牌锚点"实质是"商圈锚点"，换城市即失效。
#   → 又: P 本身由竞品密度驱动（corr(D,P)=−0.396, p<0.001；
#     控制 D 后 own_S 对 P 的增量解释力 p≈1）。
#     反事实: 个体/杂牌 own_S 1.0→2.5 时 P 中位 0.7639→0.8882，
#             蜜雪 own_S 2.5→1.0 时 P 中位 0.6352→0.4106；
#     而实测个体/杂牌 P(0.7639) 已高于蜜雪(0.6430) → P 高来自
#     "位置对手弱"而非品牌力。故按品牌标 P_REF 会把偏差固化。
#   → 因此锚点保持统一。品牌差异**只通过 own_S 进入**（它的实证方向成立），
#     UPLIFT 只承载 own_S 之外的**位置/竞争微区位残差**（v7 起；v6 及以前它
#     还在重复表达 own_S，等于把品牌力算两遍，见 brands.py 的 UPLIFT 注释块）。
#
# 注意: 仅奶茶品类做过真实数据锚定；其他品类沿用该量级（近似），
#       需扩充样本后逐品类标定（答辩局限说明）
# ===================== 距离口径与锚点：v8 步行路网（2026-09-20） =====================
# 距离口径从**直线距离（haversine）**换成 **步行路网距离**（高德 type=3 步行规划，
# 一次性抓取后冻结在 data/road_distance.db）。理由：人能走的是路，不是直线。
# 实测同一商圈 73 个点「步行/直线」= 最低 0.66 / 中位 1.26 / 最高 2.09 ——
# **逐对儿不同，不能用常系数近似**（那是编数据）。
#
# 锚点随之重标（口径：剔除低证据点「D<3 且 P>0.8」后取中位，与 v5 同规则）：
#   REF_DP  6.2489 → **4.8200**（×0.7714）  样本 83 家 → 保留 75 家
#   P_REF   0.5012 → **0.6024**（×1.2015）  保留集内 0<P<1 的 70 家
# ⇒ REF_DP 与 D×P **同向下降约 23%**，尺度互相抵消 —— 这正是
#   「流水 = 基准 × (D×P)/REF_DP」里锚点该起的作用：**吸收整体尺度、让相对排序说话**。
# ⚠️ 口径注记：v5 之前 REF_DP 为 4.35（own_S 退化 bug），v5 修正后 6.2489；
#    本条是**再次重标**，口径已写清，旧值不再引用。
# ⚠️ 现行 P_REF 0.5012 的「77 家」与标定脚本输出的家数（70/75/78，随过滤规则而变）
#    不完全对得上 —— 来源脚本已不可考。本次统一采用「D<3 且 P>0.8」过滤后重算，
#    规则写在上面。若日后要改过滤规则，**必须同时改 REF_DP 与 P_REF 并重录门禁**。
REF_DP = {'奶茶': 4.82, '默认': 4.82}

# 竞争评分锚点: 捕获份额 P 多少算"中等竞争"(60 分)。
# 奶茶 = 83 家中**剔低证据点后 77 家**的捕获份额中位数（品牌口径修正后，未做密度调整）。
#   ⚠️ 同样是"83 总样本 / 77 实际采用"的口径，别写成"83 家的中位数"。
#   ⚠️ 与 REF_DP **必须来自同一次标定**、同口径，不能单独替换其中一个（见上方注记）。
# 其他品类沿用，需扩充样本后逐品类标定。
P_REF = {'奶茶': 0.6024, '默认': 0.6024}

# 品牌溢价是否作用于流水估算（v5 开关，便于 A/B 对照与回滚）
# ⚠️ v7（2026-09-18）后 uplift 只承载"位置残差"（与 own_S 正交），量级收敛到 ±5% 附近
#    （v6 的 ±19~25% 基本来自品牌引力的重复计入）。关掉它 ≈ 回退到"只有 own_S"，
#    对结论的影响比 v6 时小得多 —— 这本身就是双算被消掉的旁证。
USE_BRAND_UPLIFT = True


def capture_share(profile, lng, lat, own_S=1.0, lam=LAMBDA, d0=D0):
    """真 Huff 捕获份额: P = (S_自/d0^λ) / (S_自/d0^λ + Σ_k S_k/(d_k+d0)^λ)
    own_S: 候选门店自身品牌引力（个体杂牌=1.0, 加盟商传品牌系数）
    竞品 S_k 由店名经品牌系数表识别, 识别不出按 1.0。
    返回 (P, 竞品数, 竞品样本名列表)。"""
    pois = query_pois(profile['cn_name'], lng, lat, profile['radius'])
    own = own_S / (d0 ** lam)
    comp = 0.0
    for p in pois:
        _, s_k = brand_attractiveness(p['name'])
        comp += s_k / ((p.get('distance', 0) + d0) ** lam)
    p_share = own / (own + comp) if (own + comp) > 0 else 1.0
    return p_share, len(pois), [p['name'] for p in pois[:5]]


def estimate_demand(lng, lat, radius):
    """需求规模 D = 0.8×(学校+办公+社区 POI 数) + 0.2×(商圈 POI 数)
    与标定脚本 fetch_demand/calibrate_anchor 的定义一致。"""
    n_a = (len(query_pois('学校', lng, lat, radius))
           + len(query_pois('办公', lng, lat, radius))
           + len(query_pois('社区', lng, lat, radius)))
    n_b = len(query_pois('商圈', lng, lat, radius))
    return 0.8 * n_a + 0.2 * n_b


# ---------------------------------------------------------------
# 1. 维度评分函数
# ---------------------------------------------------------------
def score_客群匹配度(profile, lng, lat):
    """Huff 引力版：目标客群 POI 距离衰减引力累计。
    设计: 取"最强单项客群引力"为主分（不同商圈结构各有强项，不要求四类齐全），
    其余类别做多样性加分。"""
    details = []
    per_label = []
    for tg in profile['target_pois']:
        label = tg['label']
        pois = query_pois(label, lng, lat, profile['radius'])
        g = huff_gravity(pois)
        per_label.append({'label': label, 'gravity': g, 'count': len(pois),
                          'weight': tg['weight'],
                          'samples': [p['name'] for p in pois[:5]]})
        details.append({
            'label': label, 'count': len(pois),
            'gravity': round(g, 6), 'weight': tg['weight'],
            'samples': [p['name'] for p in pois[:5]],
        })
    # 最强单项客群引力（该品类最核心的客群来源）
    g_max = max((x['gravity'] for x in per_label), default=0.0)
    # 多样性加分: 其他类别的加权贡献（主分之外最多 +20 分）
    g_other = sum(x['gravity'] * x['weight'] for x in per_label
                  if x['gravity'] < g_max * 0.5)
    # 归一化: 核心商圈级单项引力(约 1.2e-04) ≈ 80 分; 多样性加成封顶 20 分
    s_main = min(80.0, 80.0 * g_max / (1.2e-4))
    s_bonus = min(20.0, 20.0 * g_other / (6e-5))
    score = s_main + s_bonus
    total_g = sum(x['gravity'] * x['weight'] for x in per_label)
    return round(score), round(total_g, 6), details


def score_竞争压力(profile, lng, lat, own_S=1.0):
    """真 Huff 捕获份额版：候选店能抢到的需求份额 P 决定竞争分。
    P = (S_自/d0^λ) / (S_自/d0^λ + Σ_k S_k/(d_k+d0)^λ)
    评分映射: 实测锚点 P_REF = **0.6024**（83 家中剔低证据点后 **75 家**的捕获份额中位数；
    **步行路网距离口径**）= 中等竞争 60 分, s = 60 × P/P_REF 封顶 100。
    ⚠️ 本维度**随品牌引力 own_S 单调不降** —— 这是设计意图（见模块头与 REF_DP 注释）。
       换口径前 P_REF 较小（0.5012），60×P/P_REF 常被 min(100) 封顶、差异被掩盖；
       重标到 0.6024 后封顶不再普遍生效，差异才显出来。
    ⚠️ 早期文档里出现过 0.5232，那是 calibrate_brand_uplift 的**密度调整后**值，
       与这里未做密度调整的口径不匹配，**不能**拿它当运行时锚点。
    注: 不用理论值 1/(comp_base+1)=0.11, 因真实竞品分布在 100~500m,
    距离衰减后有效份额远高于"等距均分"假设（实测 P 中位 0.52）。
    品牌力强的候选(own_S大)在同等竞品密度下份额更高、得分更高——
    这正是加盟商关心的核心输出。
    返回 (分数, 竞品数, 竞品样本, 捕获份额P)。"""
    P, n, samples = capture_share(profile, lng, lat, own_S)
    if n == 0:
        # 无竞品: 可能蓝海也可能无人气, 给中性偏高分(75), 由 LLM 解读时提示两种可能
        return 75, n, samples, round(P, 4)
    p_ref = P_REF.get(profile['cn_name'], P_REF['默认'])
    s = 60.0 * P / p_ref
    return round(min(100, max(0, s))), n, samples, round(P, 4)


def _nearest_road_stop(lng, lat, topk=30):
    """**步行**最近通勤 POI 的距离（米）。

    ⚠️ 必须"直线取候选 + 步行精算"两步：全库通勤 POI 有 3 千余条，
       逐条算步行距离要 30+ 次 API 调用。直线最近 30 个候选已足够安全
       （步行与直线在**同一商圈内**高度同秩，实测秩相关高；而 30 个候选的余量
        远超最高绕行倍数 2.09 所能造成的重排）。
    """
    from data import road as _road
    from data.query import get_conn
    conn = get_conn()
    rows = conn.execute("SELECT lng, lat FROM poi WHERE category='通勤'").fetchall()
    conn.close()
    if not rows:
        return None
    cand = sorted(rows, key=lambda r: haversine(lng, lat, r[0], r[1]))[:topk]
    walk = _road.fetch_and_store((lng, lat), [(r[0], r[1]) for r in cand])
    vals = [walk.get((_road.q(r[0]), _road.q(r[1]))) for r in cand]
    vals = [v for v in vals if v]
    return min(vals) if vals else None


def score_交通可达性(lng, lat):
    """最近通勤站点的**步行**距离 + 公交站密度（距离分段）。

    分段阈值（300/800/1500m）按**步行**理解：300m≈4 分钟、800m≈11 分钟、
    1500m≈20 分钟 —— 换成步行口径后这三档的语义比原来用直线距离时更贴切。
    """
    metro_d = _nearest_road_stop(lng, lat)
    pois = query_pois('通勤', lng, lat, 500)
    n_stops = len(pois)
    if metro_d is None:
        s = 20.0
    elif metro_d <= 300:
        s = 95.0
    elif metro_d <= 800:
        s = 80.0
    elif metro_d <= 1500:
        s = 55.0
    else:
        s = 35.0
    # 公交站密度加分（最多 +10）
    s += min(10.0, n_stops * 2.0)
    return round(min(100, s)), metro_d, n_stops


def score_租金承受力(profile, monthly_rent, est_monthly_sales):
    """月租 R vs 预估月流水 S，分段"""
    ratio = (monthly_rent or 0) / est_monthly_sales if est_monthly_sales else 1.0
    limit = profile['rent_ratio']
    if ratio <= limit * 0.6:
        s = 95.0
    elif ratio <= limit:
        s = 90 - 20 * ((ratio - limit * 0.6) / (limit * 0.4 + 1e-9))
    elif ratio <= limit * 1.67:
        s = 70 - 30 * ((ratio - limit) / (limit * 0.67 + 1e-9))
    else:
        s = max(0, 40 - 40 * ((ratio - limit * 1.67) / (limit * 1.67 + 1e-9)))
    return round(min(100, max(0, s))), ratio


def score_面积适配度(profile, area_m2):
    """面积适配度(0~100): 面积是否落在品类最佳区间。
    以 area_ideal 为满分点, 偏离越多分越低。"""
    if not area_m2:
        return None
    lo, hi = profile.get('area_range', (10, 100))
    ideal = profile.get('area_ideal', (lo + hi) / 2)
    if lo <= area_m2 <= hi:
        # 区间内: 越接近理想面积越高
        spread = max(hi - ideal, ideal - lo, 1)
        s = 100 - 30 * (abs(area_m2 - ideal) / spread)
    else:
        # 区间外: 越远越低
        if area_m2 < lo:
            s = 70 - 70 * ((lo - area_m2) / max(lo, 1))
        else:
            s = 70 - 70 * ((area_m2 - hi) / max(hi, 1))
    return round(min(100, max(0, s)))


def estimate_monthly_sales(profile, lng, lat, area_m2=None, city_level=1.0, own_S=1.0,
                           price_override=None, brand=None):
    """D×P 结构模型月流水估算（v5，破除循环论证 + 品牌同商圈校准）:
    日单量 = 基准日单量 × (D×P)/REF_DP × 面积修正 × 城市修正 × 品牌溢价 × 保守系数
      D: 周边客群 POI 加权规模（需求池大小）
      P: 真 Huff 捕获份额（能从竞品中抢到多少）
      REF_DP: 83 家真实门店 D×P 中位数锚点 → 中位门店=基准日单量
      brand: 品牌名，用于取同商圈内的品牌溢价 UPLIFT（v7 起是"位置残差"，默认 1.0）
    与 v2 的本质区别: 流水由模型结构直接产出，不再从客群/竞争评分反推。

    price_override: 加盟场景下的**每单金额**（元/单），由 brand_price_reference 给出。
      ⚠️ 它不是高德的"人均/单杯价"——高德 biz_ext.cost 在茶饮类目实测 ≈ 单杯价
      （蜜雪 ¥7 ↔ 招股书单杯 ¥6.72、霸王茶姬 ¥20 ↔ 招股书单杯 ¥20.48），
      而本函数的 daily 是**日订单量**，两者口径不同，直接代入会低估约 1.7 倍
      （一单平均约 1.7 杯）。换算已在 brand_price_reference 内完成：
      优先用公开披露的每单平均零售额，其次用高德单杯价 × 每单杯数。
    """
    base_daily = profile['daily_sales']          # 基准日单量(中位门店参考)
    price = price_override or profile['price']
    price_source = ('品牌级每单金额(公开/换算)' if price_override else '品类画像假设')
    ref_dp = REF_DP.get(profile['cn_name'], REF_DP['默认'])

    # 1) 需求规模 D 与捕获份额 P（模型结构产出，非评分）
    D = estimate_demand(lng, lat, profile['radius'])
    P, comp_n, _ = capture_share(profile, lng, lat, own_S)
    dp = D * P
    data_sparse = (D == 0)

    # 1b) 品牌相对溢价（同商圈内校准；仅奶茶品类有真实标定）
    #     strict=True: brand 是用户输入的**候选品牌**，识别不出就保持中性，
    #     不要把错别字/未知品牌猜成"个体杂牌"而误加 5.99% 溢价。
    brand_name, brand_factor = (None, 1.0)
    brand_tier, brand_ci, brand_n = 'TIER3', None, None
    if brand and USE_BRAND_UPLIFT and profile['cn_name'] == '奶茶':
        det = brand_uplift_detail(brand, strict=True)
        brand_name = det['brand']
        brand_factor = det['uplift'] if brand_name else 1.0
        brand_tier = det['tier']
        brand_ci = det['ci']
        brand_n = det['n']

    # 2) 面积修正: 面积太小无法承载理想单量
    area_factor = 1.0
    if area_m2:
        lo, hi = profile.get('area_range', (10, 100))
        if area_m2 < lo:
            area_factor = max(0.4, area_m2 / lo)
        elif area_m2 > hi * 1.5:
            area_factor = 0.85  # 过大反而增加成本不增客流
        elif area_m2 > hi:
            area_factor = 0.92  # 略超区间, 小幅下调

    # 3) 城市修正: 杭州/宁波(核心城市) 1.0, 其他 0.85
    city_factor = city_level

    # 4) 保守系数: 开业前 3-6 个月爬坡期客流通常仅成熟店 6-7 成,
    #    取 0.6 偏保守（2026-09-14 由 0.75 下调，避免回本周期过于画饼）
    conservative = 0.6

    if data_sparse:
        # 客群 POI 数据稀疏: 无法估计需求池, 按基准 3 折保守处理
        daily = base_daily * 0.3 * conservative
    else:
        daily = (base_daily * (dp / ref_dp) * area_factor * city_factor
                 * brand_factor * conservative)
    monthly = daily * price * 30
    # 「营业额刚性」口径：假设品牌不改变营业额（即该店的日均营业额与品类画像
    # 同价档的门店一致）。这是与上面「单量刚性」并列的另一个建模极端，
    # 由 elasticity_band() 组装成区间，用于回答"换客单价到底该怎么改流水"。
    # 只算一个数字没有任何风险——两个极端都摆出来才算把不确定性摊开。
    monthly_rev_rigid = daily * profile['price'] * 30
    return {
        '基准日单量': base_daily,
        '需求规模D': round(D, 1),
        '捕获份额P': round(P, 4),
        'D×P': round(dp, 2),
        '锚点REF_DP': ref_dp,
        '自身品牌S': own_S,
        '品牌': brand_name,
        '品牌溢价系数': round(brand_factor, 4),
        '品牌溢价等级': brand_tier,
        '品牌溢价区间': (list(brand_ci) if brand_ci else None),
        '品牌标定样本量': brand_n,
        '面积修正': round(area_factor, 2),
        '城市修正': round(city_factor, 2),
        '保守系数': conservative,
        '估算日单量': round(daily),
        # 未取整日单量：口径区间要用它乘出另一端流水，取整会引入二次误差
        '未取整日单量': round(daily, 3),
        '客单价': price,
        '客单价来源': price_source,
        '品类画像客单价': profile['price'],
        '月流水估算': round(monthly),
        '营业额刚性月流水': round(monthly_rev_rigid),
        '数据稀疏': data_sparse,
    }


# ---------------------------------------------------------------
# 2. 综合评分
# ---------------------------------------------------------------
# 浙江各市近似中心坐标（用于从经纬度粗判城市, 仅供水电价参考）
_CITY_CENTERS = {
    '杭州': (120.15, 30.28), '宁波': (121.55, 29.87), '温州': (120.70, 28.00),
    '嘉兴': (120.75, 30.75), '湖州': (120.10, 30.87), '绍兴': (120.58, 30.00),
    '金华': (119.65, 29.08), '衢州': (118.87, 28.94), '舟山': (122.20, 29.99),
    '台州': (121.42, 28.65), '丽水': (119.92, 28.45),
}


def _guess_city(lng, lat):
    """按经纬度粗判最近的浙江城市"""
    from data.query import haversine
    best, best_d = None, 1e18
    for city, (clng, clat) in _CITY_CENTERS.items():
        d = haversine(lng, lat, clng, clat)
        if d < best_d:
            best, best_d = city, d
    return best


# ---------------------------------------------------------------
# 结论判定：位置分 × 盈利硬约束（非补偿性一票否决）
# ---------------------------------------------------------------
# 回本红线：3 年租约里前 2 年收回投入才算达标，最后一年才是真正赚到的。
# ⚠️ 此值不可等于 utilities.AMORTIZE_MONTHS(36)。回本 = 投入/(月净利+月摊销)，
# 而月摊销 = 投入/摊销月数，两者相等时"回本=摊销月数"与"净利=0"是同一个方程，
# 盈亏平衡月租与回本达标月租上限会恒等（实测三种投入水平下全部相等），
# 第二个临界点携带的信息量为零，还会让谈判筹码把同一个数字说两遍当成两个条件。
PAYBACK_LIMIT_MONTHS = 24


def _money(v) -> str:
    """带货币符号的金额。负号必须在 ¥ 前面：'¥-115,653' 会被读成'¥ 减 11 万'。"""
    try:
        f = float(v)
    except Exception:
        return '-' if v is None else str(v)
    return ('-' if f < 0 else '') + f'¥{abs(f):,.0f}'


def _verdict(total: float, veto_reason: str = None) -> str:
    """四级位置结论 + 盈利一票否决。

    为什么是一票否决，而不是提高"租金承受力"权重：加权是**补偿性**的，位置分够高
    就能把 0 分补回来（这正是"总分 80.9 判推荐、月净利却是负的"的成因）；而"这个
    租金下亏钱"是**非补偿性**硬约束——位置再好也不能签。所以盈利不过关时直接改写
    结论，且只覆盖原本为正的结论（推荐/谨慎推荐），原本就为负的保持不动。
    """
    # 阈值统一在 _verdict_from_score 里（地址评分与经营评分共用一套措辞）。
    base = _verdict_from_score(total) or '不建议'
    if veto_reason and base in ('推荐', '谨慎推荐'):
        return '位置好·账算不过来' if base == '推荐' else '账算不过来'
    return base


def _bisect_rent(f, cap=1_000_000.0):
    """f(租金) 单调递减，求 f(rent)=0 的根，取整到 50 元。
    f(0) <= 0 说明白送租金也达不到目标 → 返回 None（调用方据此区分"降租能救"与"救不了"）。"""
    if f(0.0) <= 0:
        return None
    lo, hi = 0.0, 1000.0
    while f(hi) > 0:
        lo, hi = hi, hi * 2
        if hi > cap:
            return None
    while hi - lo > 50:
        mid = (lo + hi) / 2
        if f(mid) > 0:
            lo = mid
        else:
            hi = mid
    return int(round(lo / 50) * 50)


def solve_rent_limits(category, area_m2, city, investment, staff, sales_est, brand,
                      price=None) -> dict:
    """反解两个租金临界点（纯本地二分，0 次 API）：
      盈亏平衡月租    : 月净利 = 0
      回本达标月租上限 : 回本周期 = PAYBACK_LIMIT_MONTHS
    顺带给出"免租"情形，用来区分"租金谈下来就能救"和"这铺子根本救不了"。
    estimate_profit 对租金单调递减，二分即可收敛。
    price: 校正后的客单价，必须与 sales_est 同口径传入，否则临界点按品类画像
      反解、流水按品牌级每单金额算，两条线对不上。
    """
    from engine.utilities import estimate_profit

    def prof(rent):
        return estimate_profit(category, area_m2, city, rent, investment=investment,
                               staff=staff, sales_est=sales_est, brand=brand, price=price)

    def payback_margin(rent):
        pb = prof(rent).get('回本周期(月)')
        return -1e9 if not pb else PAYBACK_LIMIT_MONTHS - pb

    free = prof(0)
    return {
        '盈亏平衡月租': _bisect_rent(lambda r: prof(r)['月净利估算']),
        '回本达标月租上限': _bisect_rent(payback_margin),
        '免租月净利': free['月净利估算'],
        '免租回本周期(月)': free.get('回本周期(月)'),
    }


# ---------------------------------------------------------------
# 2.5 价格—单量弹性：把"换了客单价之后流水该怎么变"这个未标定的自由度摊开
# ---------------------------------------------------------------
# 背景（2026-09-15 发现）：日单量基准 250 单/天是**混合品牌**标定的中位数
# （83 家里蜜雪只占 14 家/16.9%，其余是 20 多个品牌各 1~6 家），隐含绑定 ¥16 那一档定价；
# 而客单价校正是**品牌级**的（蜜雪实测 ¥7）。只换单价、不换单量，等于隐含假设
# "需求量对价格完全无弹性"——这会把低价品牌的流水压到很低、把高价品牌抬得很高。
#
# 真实弹性在 (−1, 0) 之间：蜜雪客单价只有画像的 0.44，但单量绝不可能只有一半，
# 也未必高到"营业额完全不变"。现有数据**无法标定**这个弹性——
# stores_calib.csv 只有坐标/外卖月售/品牌/商圈，没有任何营业数据；
# 而外卖月售作为经营代理已被证伪（P_brand ↔ 外卖月售 = −0.229，方向相反）。
#
# 所以并列两个建模极端，把真值夹在中间，而不是编一个弹性系数出来。
ELASTICITY_CALIPERS = (
    ('单量刚性', 0.0,
     '假设品牌不改变日单量：客单价低就按低单价卖同样杯数（流水随单价线性变）'),
    ('营业额刚性', -1.0,
     '假设品牌不改变营业额：客单价低就必须卖出更多杯（流水不随单价变）'),
)


def elasticity_band(category, area_m2, city, monthly_rent, investment, staff, brand,
                    sales_est, price_eff):
    """价格弹性未知时的两端口径区间。**这不是置信区间**，是两个建模极端。

    返回 None 表示不适用（无面积、或未做客单价校正——此时两端退化为同一个数，
    摆出来只会制造"我们考虑了不确定性"的假象）。
    """
    if not area_m2 or not price_eff:
        return None
    from engine.utilities import estimate_profit

    daily = sales_est.get('未取整日单量')
    price_cat = sales_est.get('品类画像客单价')
    if not daily or not price_cat:
        return None
    # 校正价恰好等于画像价 → 两端同值，没有弹性问题可言
    if abs(float(price_eff) - float(price_cat)) < 1e-9:
        return None

    tiers = []
    for name, elast, note in ELASTICITY_CALIPERS:
        # 端点流水一律取 estimate_monthly_sales 已经算好并取整的那两个值，
        # 不要在这里重算——否则主路径用取整值、区间用未取整值，
        # 同一个"单量刚性"档会算出相差几元的两个净利，两个数字就"对不上账"了。
        _known = (sales_est.get('月流水估算') if elast == 0.0
                  else sales_est.get('营业额刚性月流水'))
        sales = (_known if _known is not None
                 else daily * (price_eff if elast == 0.0 else price_cat) * 30)
        # sales 与 price 必须同口径传入：estimate_profit 会反推日单量
        # （daily = sales/(price×30)），于是"营业额刚性"档下低价品牌自动得到
        # 更高的单量与更多的人力成本，而不是白捡一份流水。
        p = estimate_profit(category, area_m2, city, monthly_rent,
                            investment=investment, staff=staff,
                            sales_est=sales, brand=brand, price=price_eff)
        tiers.append({
            '口径': name, '价格弹性假设': elast, '说明': note,
            '角色': ('本报告单点数字即此端' if elast == 0.0
                     else '区间另一端（建模极端，非预测情景）'),
            '月流水': round(sales),
            '日单量参考': p['日单量参考'],
            '人数': p['人数'],
            '月净利': p['月净利估算'],
            '净利率': p['净利率'],
            '回本周期(月)': p.get('回本周期(月)'),
        })

    sales_v = [t['月流水'] for t in tiers]
    nets = [t['月净利'] for t in tiers]
    margins = [t['净利率'] for t in tiers if t['净利率'] is not None]
    pb_vals = [t['回本周期(月)'] for t in tiers if t['回本周期(月)']]

    def _veto(t):
        pb = t['回本周期(月)']
        return t['月净利'] <= 0 or (pb is not None and pb > PAYBACK_LIMIT_MONTHS)

    flags = [_veto(t) for t in tiers]
    stable = len(set(flags)) == 1

    # ---------------- 稳健性档位（四档，2026-09-20） ----------------
    # ⚠️ 两条分界都是**人为约定，不是数据推导**，界面与文档里必须如实标注：
    #   ① 「贴近临界」= 回本周期落在否决线 ±25% 以内（即 18 ~ 30 个月）；
    #   ② 两端相反时「差异有限」= 两端净利率之差 ≤ 5 个百分点。
    # 为什么要分档：真实的确定性是连续的，而"稳健/不稳健"把
    #   「两端都离生死线很远」与「两端都刚好压线」混成了同一档，
    #   把「差一点就翻」与「差出天际」也混成了同一档。
    # 命名规则：**结论稳健（布尔）** 仍保留 —— true ⇔ 档位 ∈ {稳健, 比较稳健}。
    #   即布尔回答"两端同不同向"，档位回答"同向的话余量厚不厚 / 反向的话差得多不多"。
    _TIER_NEAR = 0.25           # 贴近临界带（否决线 ±25%）
    _TIER_MARGIN_SPREAD = 0.12  # 两端相反时"差异有限"的上限（净利率 12pp）
    # ⚠️ 12pp 取自**实测断点**，不是拍的：两端流水本身相差约 40%，只要结论方向
    #   相反，两端净利率之差天然就有 ~10pp 起步。实测扫描（天一广场 30㎡ 蜜雪，
    #   21 个租金档）：
    #     5pp  → 稳健12 / 比较稳健2 / 比较不稳健0 / 不稳健7   ← 中间档取不到
    #     15pp → 稳健12 / 比较稳健2 / 比较不稳健7 / 不稳健0   ← 最高档取不到
    #     12pp → 稳健12 / 比较稳健2 / 比较不稳健7 / 不稳健0（本扫描，客单价固定）
    #            ＋ 口径错误场景（¥7 当每单，19.4pp）命中 不稳健
    #   即：**单一口径下最高到"比较不稳健"，"不稳健"留给口径错误或极端品牌**
    #   —— 这与结论打架但两边都在同一量级的真实语感一致。
    _pbs = [(t['回本周期(月)'] if t['回本周期(月)'] is not None else float('inf'))
            for t in tiers]
    _mg = [t['净利率'] for t in tiers if t['净利率'] is not None]
    if stable:
        if not flags[0]:        # 两端都不触发否决 ⇒ 看离生死线还剩多少余量
            tier = ('稳健' if max(_pbs) <= PAYBACK_LIMIT_MONTHS * (1 - _TIER_NEAR)
                    else '比较稳健')
        else:                   # 两端都触发否决 ⇒ 看"最接近放行"的那端离线多远
            tier = ('稳健' if min(_pbs) >= PAYBACK_LIMIT_MONTHS * (1 + _TIER_NEAR)
                    else '比较稳健')
    else:                       # 两端相反 ⇒ 看这两端打得有多厉害
        tier = ('比较不稳健'
                if (len(_mg) == 2 and abs(_mg[0] - _mg[1]) <= _TIER_MARGIN_SPREAD)
                else '不稳健')

    if stable:
        # ⚠️ 两个方向的措辞必须题头就写明（"都不触发" / "都触发"）——
        #    离线门禁 verify_elasticity_band.py 的 _state() 靠这两个短语区分
        #    both_pass / both_veto；中间档若把它们冲掉，扫描会退化成 '?' 而
        #    提前中断，"两端都否决"的代表点就再也取不到（2026-09-20 踩过）。
        _dir = ('两端口径都不触发一票否决' if not flags[0]
                else '两端口径都触发一票否决')
        concl = _dir + '——结论对价格弹性假设不敏感'
        if tier == '比较稳健':
            concl = (_dir + '，但有一端贴近 24 个月回本线、余量偏薄 —— '
                     '价格弹性假设换一种合理取法，结论可能翻转')
    elif tier == '比较不稳健':
        concl = ('⚠️ 结论比较不稳健：两端口径方向相反，但两端净利率之差在 12 个百分点以内，'
                 '此时应看真实日单量落在哪一侧')
    else:
        concl = ('⚠️ 结论不稳健：两端口径对"这个租金能不能签"给出**相反**答案，'
                 '取决于该品牌在该商圈的真实日单量，而现有样本无法标定它')

    return {
        '区间': {
            '月流水区间(元/月)': (min(sales_v), max(sales_v)),
            '月净利区间(元/月)': (min(nets), max(nets)),
            '净利率区间': ((min(margins), max(margins)) if margins else None),
            '回本区间(月)': ((max(pb_vals), min(pb_vals)) if pb_vals else None),
            '结论': concl,
            '结论稳健': stable,
            '稳健档': tier,
            '稳健档约定': ('四档是**确定性等级，不是概率**：只说明这个结论有多确定，'
                       '不表示生意好坏（"稳健"既可能是确定能签，也可能是确定不能签）。'
                       '两条分界为人为约定 —— 「贴近临界」= 回本周期落在 24 个月否决线 '
                       '±25% 内（18~30 个月）；两端相反时「差异有限」= 两端净利率之差 '
                       '≤ 12 个百分点。分界可调，含义不变。'),
            '口径': ('两端为建模极端、非置信区间：真值取决于需求量-价格弹性，'
                     '该弹性未被标定（标定样本无营业数据可用）。'
                     '注意区间是**单侧**的——报告里的各单点数字取自"单量刚性"端；'
                     '"营业额刚性"端在低价品牌上会外推出超出面积承载能力的日单量与'
                     '用工人数（如 30㎡ 推出 9 人），该端是用来夹住上界的，不是预测'),
        },
        '档位': tiers,
    }


# ---------------------------------------------------------------
# 2.6 经营评分（"这个租金下开起来到底赚不赚钱"的单一分数 + 三档区间）
# ---------------------------------------------------------------
# 与「地址评分」（原 `total`，2026-09-16 起在展示层改称「地址评分」）的分工：
#   · 地址评分 = 四(五)维**加权和**，衡量"这个位置本身好不好"，**不含成本与利润**
#     —— 结构上就不可能含：`total` 在 profit 之前定稿（见 score_site 里
#     `total = sum(...)` 与 `profit = estimate_profit(...)` 的先后顺序），
#     租金也只以「租金 ÷ **流水**」的分段进入，比的是租金与营业额、不是租金与利润。
#   · 经营评分 = 净利率(60%) + 回本周期(40%)，按**中性档**映射，
#     衡量"这个租金下能不能赚钱"。结论以它为准（地址评分降为维度指标）。
#
# 为什么不只给一个数字：三档净利、口径区间（价格弹性）、一票否决都是**真实的
# 不确定性**，用一个 0~100 把它们盖住等于制造新的假精确。所以主分用中性档，
# **同时并列乐观/保守两档分数**——与项目既有的「三档情景」「口径区间」口径纪律一致。
BUSINESS_SCORE_WEIGHTS = {'净利率': 0.60, '回本周期': 0.40}
BUSINESS_SCORE_BOUNDS = {
    # (零分阈值, 满分阈值)：净利率 ≤0 得 0、≥20% 得 100
    '净利率': (0.0, 0.20),
    # 回本周期 ≥36 个月得 0、≤12 个月得 100（注意 lo>hi，方向相反）
    '回本周期': (36.0, 12.0),
}
BUSINESS_SCORE_CAP_ON_VETO = 59   # 一票否决时封顶：不允许出现"位置好 + 经营评分 80"


def _lin_score(v, lo, hi):
    """线性映射：v=lo → 0 分，v=hi → 100 分，两端截断。v 为 None → 0 分。
    hi<lo 时方向自动反转（回本周期就是这种）。"""
    if v is None:
        return 0.0
    if hi == lo:
        return 100.0 if float(v) >= hi else 0.0
    s = (float(v) - lo) / (hi - lo) * 100.0
    return max(0.0, min(100.0, s))


def _verdict_from_score(score):
    """分数 → 四级结论词。与 _verdict 共用同一套阈值，保证两个轴措辞一致。"""
    if score is None:
        return None
    if score >= 75:
        return '推荐'
    if score >= 60:
        return '谨慎推荐'
    if score >= 45:
        return '不建议优先选择'
    return '不建议'


def _score_one_profit(p):
    """单个情景（一档）→ 0~100 经营评分。"""
    w = BUSINESS_SCORE_WEIGHTS
    b = BUSINESS_SCORE_BOUNDS
    m = _lin_score(p.get('净利率'), *b['净利率'])
    pb = _lin_score(p.get('回本周期(月)'), *b['回本周期'])
    return w['净利率'] * m + w['回本周期'] * pb


def business_score(profit, bands=None, veto_triggered=False, has_rent=True):
    """经营评分：净利率 60% + 回本周期 40%（按中性档），并列三档分数。

    返回 dict（**不可得时也必须给口径，不能静默返回空**）：
      分数/结论/三档/区间/一票否决封顶/权重/映射/口径/不可得原因
    """
    weights_txt = f"净利率 {BUSINESS_SCORE_WEIGHTS['净利率']:.0%}（≥20% 满分、≤0 零分）" \
                  f"＋ 回本周期 {BUSINESS_SCORE_WEIGHTS['回本周期']:.0%}（≤12 月满分、≥36 月零分）"
    base = {
        '分数': None, '结论': None, '三档': None, '区间': None,
        '一票否决封顶': bool(veto_triggered), '权重': dict(BUSINESS_SCORE_WEIGHTS),
        '映射': {'净利率': {'零分': 0.0, '满分': 0.20},
                 '回本周期(月)': {'零分': 36, '满分': 12}},
        '口径': f'{weights_txt}，按中性档；一票否决时封顶 {BUSINESS_SCORE_CAP_ON_VETO} 分',
        '不可得原因': None,
    }
    if not profit:
        return dict(base, 不可得原因='缺经营测算（未提供商铺面积，无法算成本利润）')
    # 没填月租 → 不猜，不出分。硬按默认租金算出的"经营评分"是编出来的。
    if not has_rent:
        return dict(base, 不可得原因='缺月租，无法判断能不能赚钱——请补充月租后再看经营评分')
    if not profit.get('前期投入'):
        return dict(base, 不可得原因='缺前期投入，无法算回本周期')

    main = _score_one_profit(profit)
    tiers = {}
    if bands:
        for n in ('乐观', '中性', '保守'):
            b = bands.get(n)
            if b:
                tiers[n] = round(_score_one_profit(b))
    main_r = round(main)
    if veto_triggered:
        main_r = min(main_r, BUSINESS_SCORE_CAP_ON_VETO)
    if tiers:
        lo, hi = min(tiers.values()), max(tiers.values())
    else:
        lo = hi = main_r
    out = dict(base)
    out.update({
        '分数': main_r,
        '结论': _verdict_from_score(main_r),
        '三档': tiers or None,
        '区间': [lo, hi],
    })
    if veto_triggered:
        out['口径'] = (f"{weights_txt}，按中性档。⚠️ 一票否决已触发"
                       f"（月净利≤0 或回本 >{PAYBACK_LIMIT_MONTHS} 个月），"
                       f"分数封顶 {BUSINESS_SCORE_CAP_ON_VETO}——位置再好也不能签，"
                       f"不出现「位置好 + 经营高分」的自相矛盾展示")
    return out


def score_site(category, lng, lat, monthly_rent, name='', area_m2=None, city=None,
               city_level=1.0, investment=None, staff=None, brand=None, price_ref=None):
    """对单个地址评分，返回完整结果 dict。
    area_m2: 商铺面积(㎡), 提供后启用面积适配度维度+水电盈利测算+盈利一票否决
    investment: 用户前期投入成本(元)，用于装修档次 + 回本测算
    staff: 运营人数，未给则按品类默认（奶茶/甜品/早餐2人、便利店1人）
    city_level: 城市等级系数(杭州/宁波1.0, 其他0.85)
    brand: 候选门店品牌名(B2B 加盟商场景, 如 '蜜雪冰城')，
           传入后按品牌引力系数 S 参与捕获份额竞争；个体户默认 None(→S=1.0)
    price_ref: competitor_insight.brand_price_reference 的输出，用于以**品牌级
           每单金额**校正客单价（口径见该函数：高德 cost 是单杯价、不是每单）。
           未注入且 brand 非空时本函数自己发 1 次高德 API；
           调用方若已抓过周边竞品，请注入以省配额。
    """
    profile = get_profile(category)
    own_S = BRAND_S.get(brand, 1.0) if brand else 1.0

    # 客单价校正：加盟场景下品类画像的假设客单价对具体品牌不成立
    # （同品类内部价差实测达 3~4 倍），必须用品牌级真实**每单金额**覆盖。
    if brand and price_ref is None:
        from engine.competitor_insight import brand_price_reference
        price_ref = brand_price_reference(lng, lat, category, brand)
    price_ref = price_ref or {}
    corrected_price = price_ref.get('校正客单价')

    # D×P 结构模型流水(先算, 供租金承受力使用)
    sales_est = estimate_monthly_sales(profile, lng, lat, area_m2, city_level, own_S,
                                       price_override=corrected_price, brand=brand)
    est_sales = sales_est['月流水估算']

    s1, guest_g, guest_details = score_客群匹配度(profile, lng, lat)

    # 装修精致度 -> 对目标客群吸引力的修正（±8分内，由前期投入推断）
    deco = evaluate_decoration(investment, area_m2, category)
    deco_score = deco['档次分'] if deco else None
    attraction_bonus = (deco_score - 50) / 50 * 8 if deco_score is not None else 0.0
    if attraction_bonus:
        s1 = s1 + attraction_bonus

    s2, comp_n, comp_samples, capture_p = score_竞争压力(profile, lng, lat, own_S)
    s3, metro_d, n_stops = score_交通可达性(lng, lat)
    s4, rent_ratio = score_租金承受力(profile, monthly_rent, est_sales)
    s5 = score_面积适配度(profile, area_m2)  # 可能为 None

    if city is None:
        city = _guess_city(lng, lat)

    # 维度与权重: 面积已知时, 从客群/交通各拆5%给面积
    dims = {
        '客群匹配度': round(s1, 1),
        '竞争压力': s2,
        '交通可达性': s3,
        '租金承受力': s4,
    }
    weights = dict(profile['weights'])
    if s5 is not None:
        dims['面积适配度'] = s5
        # 重新分配权重: 面积占10%, 其余按原比例缩放
        rest = 0.90
        wsum = sum(weights.values())
        weights = {k: v / wsum * rest for k, v in weights.items()}
        weights['面积适配度'] = 0.10
    total = sum(dims[k] * weights[k] for k in dims)

    # 主动质疑触发
    warnings = []
    if s2 < 30:
        warnings.append(f'⚠️ 竞争压力过低({s2}分)：周边 {comp_n} 家同类，'
                        f'真 Huff 捕获份额仅 {capture_p:.1%}，市场已饱和')
    if s1 < 40 and s2 < 40:
        warnings.append('⚠️ 客群匹配度与竞争压力双低，疑似品类-位置错配')
    if s4 < 40:
        warnings.append(f'⚠️ 租金承受力过低({s4}分)：月租占预估流水 {rent_ratio:.0%}，盈亏风险高')
    if s5 is not None and s5 < 40:
        warnings.append(f'⚠️ 面积适配度偏低({s5}分)：当前面积对{category}品类不理想，可能影响经营')
    if guest_g == 0:
        warnings.append('ℹ️ 目标客群 POI 数据稀疏，建议人工现场复核')

    # 客单价校正必须出声：流水是后面所有测算（承受力、一票否决、三档区间）的地基，
    # 悄悄换个客单价等于悄悄换了结论，用户有权知道自己看到的是哪个口径。
    # 四种状态对应四种**互不相同**的说法，尤其 fetch_failed 不能说成"附近没有该品牌"。
    _ratio = price_ref.get('校正倍数')
    _state = price_ref.get('抓取状态')
    _src = price_ref.get('来源') or ''
    _when = price_ref.get('取证时间') or ''
    _trace = ('（' + '，'.join(x for x in [
        (f'{_src}取数' if _src else ''), (_when or '')] if x) + '）') if (_src or _when) else ''
    if corrected_price:
        _n = (price_ref.get('证据') or {}).get('样本数', '?')
        _prov = price_ref.get('口径来源')
        # _ratio 是"画像 ÷ 真实"，流水变化幅度是 1-1/_ratio；直接拿 _ratio-1
        # 会算出"下调 129%"这种不可能的数（降幅不能超过 100%）。
        if _ratio and _ratio > 1:
            _delta = f'，流水因此下调 {1 - 1 / _ratio:.0%}'
        elif _ratio and _ratio < 1:
            _delta = f'，流水因此上调 {1 / _ratio - 1:.0%}'
        else:
            _delta = ''
        if _prov == 'public_report':
            _src_txt = '公开披露每单金额'
        elif _prov == 'industry_estimate':
            _src_txt = '第三方行业参考单杯价×每单杯数'
        elif _prov == 'amap_targeted':
            _src_txt = f'高德**品牌定向搜索** {_n} 家「{brand}」单杯价×每单杯数'
        else:
            _src_txt = f'高德 {_n} 家「{brand}」单杯价×每单杯数'
        # C 级（行业参考）不是披露也不是实测，出声时必须比 A/B 级更重的措辞，
        # 免得用户把"第三方人均榜"读成"实测/披露"。
        _warn = ('⚠️ 客单价已按**第三方行业参考**校正（非披露非实测，仅数量级参照）：'
                 if _prov == 'industry_estimate'
                 else 'ℹ️ 客单价已按品牌级每单金额校正：')
        _tail = ('；这是 C 级兜底口径（A 级实测与 B 级披露均未取到），'
                 '与披露值不可混用，签约前请务必自行核实'
                 if _prov == 'industry_estimate' else '')
        warnings.append(
            f'{_warn}¥{profile["price"]}/单（品类画像）→ '
            f'¥{corrected_price:g}/单（{_src_txt}）{_delta}{_trace}{_tail}')
    elif brand and _state == 'fetch_failed':
        warnings.append(
            f'⚠️ 客单价**未校正，且不是因为没有该品牌**：本次没能取到高德竞品数据'
            f'（{price_ref.get("口径", "")[:80]}）。本报告流水按品类画像 '
            f'¥{profile["price"]}/单 测算，若「{brand}」在当地实际每单金额与之差异大，'
            f'流水与回本结论会随之偏移，签约前务必自行核实。')
    elif brand and price_ref.get('证据'):
        _ev = price_ref['证据']
        _cupv = _ev['同品牌人均中位']
        warnings.append(
            f'⚠️ 客单价未校正但存疑：周边只抓到 {_ev["样本数"]} 家「{brand}」能取到单杯价'
            f'（¥{_cupv}），不足 2 家不构成换算依据，本次仍按品类画像 '
            f'¥{profile["price"]}/单 测算。注意 ¥{_cupv} 是**单杯价**、不是每单金额'
            f'（一单通常不止一杯）；若该品牌真实每单金额与画像差异大，'
            f'盈亏结论可能反转，签约前务必自己核实')
    elif brand and _state == 'self_brand':
        warnings.append(
            f'ℹ️ 客单价按品类画像 ¥{profile["price"]}/单 测算：自创品牌没有同品牌连锁'
            f'门店可作价格参照（这是口径定义，不是没查到数据）。'
            f'品牌引力仍按"个体/杂牌"档计入竞争测算。')
    elif brand and _state == 'no_same_brand':
        # 取数成功、但该品牌确实没出现在周边样本里（A/B/C 三级均未取到价）——
        # 这才可以说"附近没抓到"。
        warnings.append(
            f'ℹ️ 未做客单价校正：高德周边 1km 内没抓到「{brand}」门店的单杯价，'
            f'且该品牌既无公开披露的每单金额、也无第三方行业参考数据'
            f'（可能尚未进入这个商圈），'
            f'本次按品类画像 ¥{profile["price"]}/单 测算{_trace}')

    # 水电成本 + 盈利测算（提供面积时）
    # 口径：单点 profit 与 solve_rent_limits/一票否决统一走**中性档**情景假设；
    # profit_bands 另外并列三档，供 UI/PDF/LLM 展示区间而不是伪精确单点。
    utility = None
    profit = None
    profit_bands = None
    rent_limits = None
    if area_m2:
        from engine.utilities import (estimate_monthly_utility, estimate_profit,
                                      estimate_profit_bands)
        utility = estimate_monthly_utility(category, area_m2, city)
        profit = estimate_profit(category, area_m2, city, monthly_rent or 0,
                                 investment=investment, staff=staff,
                                 sales_est=est_sales, brand=brand, price=corrected_price)
        profit_bands = estimate_profit_bands(category, area_m2, city, monthly_rent or 0,
                                             investment=investment, staff=staff,
                                             sales_est=est_sales, brand=brand,
                                             price=corrected_price)
        rent_limits = solve_rent_limits(category, area_m2, city, investment, staff,
                                        est_sales, brand, price=corrected_price)

    # 价格—单量弹性区间：只在"客单价被品牌校正"时才有意义（未校正时两端同值）。
    # 放在结论层而不是塞进 estimate_monthly_sales，是因为它要并列跑两套完整成本
    # 测算——人数随单量变化，属于结论而不是流水本身。
    caliper_band = None
    if corrected_price:
        caliper_band = elasticity_band(category, area_m2, city, monthly_rent or 0,
                                       investment, staff, brand, sales_est, corrected_price)

    # 产能可行性：人数被产能下限上调时必须明说。否则用户看到"2 个人、月净利 X"
    # 会以为自己 2 个人真能干出来，而测算其实是按 3~4 个人扣的人工。
    if profit and profit['人数'] > profit['申报人数']:
        who = '你报的' if staff else '品类默认的'
        warnings.append(
            f'⚠️ 产能不可行：{who} {profit["申报人数"]} 人做不完预估 '
            f'{profit["日单量参考"]} 单/天（中性档人均 '
            f'{profit["假设"]["人均日单量"]} 单/天），测算已按 {profit["人数"]} 人计人工；'
            f'坚持 {profit["申报人数"]} 人则这个流水量本身做不到')

    # 口径区间必须出声。上面所有"月净利/回本"都建立在"客单价变了、但日单量照旧"
    # 这一条未经标定的假设上；不给区间，用户会把中性档单点当成承诺。
    if caliper_band:
        _civ = caliper_band['区间']
        _plo, _phi = _civ['月流水区间(元/月)']
        _nlo, _nhi = _civ['月净利区间(元/月)']
        _pbv = _civ['回本区间(月)']
        _pb_txt = f'{_pbv[0]}~{_pbv[1]} 个月' if _pbv else '至少一端难以回本'
        warnings.append(
            f'⚠️ 盈利口径不确定（模型限制，不是数据错）：客单价用了品牌级每单金额 '
            f'¥{corrected_price:g}，但日单量基准 {sales_est["基准日单量"]} 单/天是从 '
            f'83 家**混合品牌**门店标定的（蜜雪只占 17%），并没有随客单价联动。'
            f'把弹性两端都摆出来：月流水 {_money(_plo)}~{_money(_phi)}，'
            f'月净利 {_money(_nlo)}~{_money(_nhi)}，回本 {_pb_txt}。'
            f'⚠️ 区间是**单侧**的：报告里的每个单点数字都取自"单量刚性"端，'
            f'换"营业额刚性"假设后才会到另一端，真值不会跑出区间之外的说法不成立。')
        if not _civ['结论稳健']:
            warnings.append(
                f'🚫 结论不稳健：换成另一个同样合理的假设（品牌不改变营业额），'
                f'"这个租金能不能签"的答案就反过来了。要定论必须先拿到该品牌在该商圈的'
                f'真实日单量——签约前请向品牌方或已开业的同类门店核实单量，'
                f'不要只依据本报告的单一数字。')

    # 盈利一票否决（非补偿性硬约束，理由见 _verdict 注释）
    veto_reason = None
    if profit:
        payback = profit.get('回本周期(月)')
        net = profit['月净利估算']
        if net <= 0:
            veto_reason = f'月净利 {_money(net)}（亏损）'
        elif not payback or payback > PAYBACK_LIMIT_MONTHS:
            veto_reason = (f'{PAYBACK_LIMIT_MONTHS} 个月（3 年租约的前两年）内回不了本'
                           f'（回本 {payback} 个月，月净利仅 {_money(net)}）' if payback
                           else f'月净利仅 {_money(net)}，投入收不回')

    if veto_reason:
        rent_now = monthly_rent or 0
        net = profit['月净利估算']
        be = rent_limits.get('盈亏平衡月租')
        cap = rent_limits.get('回本达标月租上限')
        # 净利为负 → 目标是先做到不亏（盈亏平衡点）；净利为正但回本超期 → 目标是压进回本红线
        target, label = (be, '盈亏平衡点') if net <= 0 else (cap, f'{PAYBACK_LIMIT_MONTHS} 个月回本上限')

        if net <= 0 and be is None:
            warnings.append(
                f'🚫 一票否决：月租 {_money(rent_now)} 下{veto_reason}，'
                f'且即便免租也只有 {_money(rent_limits["免租月净利"])}——问题不在租金，'
                f'在客流或成本结构，谈租金救不回来')
        elif target is not None and rent_now > target:
            warnings.append(
                f'🚫 一票否决：月租 {_money(rent_now)} 下{veto_reason}。'
                f'位置分 {round(total, 1)} 再高也不能签——要成立，月租必须压到 '
                f'{_money(target)} 以下（{label}，已含 0.6 保守爬坡系数）')
            if net <= 0 and cap is not None and be is not None and cap < be:
                warnings.append(
                    f'ℹ️ 若还要求 {PAYBACK_LIMIT_MONTHS} 个月内回本，月租上限进一步收紧到 '
                    f'{_money(cap)}（比盈亏平衡线低 {_money(be - cap)}）。'
                    f'这是"最多能付"的天花板、不是开价，实际报价还要再留出余地')
        else:
            warnings.append(f'🚫 一票否决：{veto_reason}')

    # ---- 经营评分 + 结论以经营评分为准（2026-09-16 口径变更）----
    # 双轴：地址评分（这个位置好不好）× 经营评分（这个租金下赚不赚钱）。
    # 最终结论以**经营评分**为准（用户的真实诉求是"能不能赚钱"）；地址评分降为
    # 维度指标，仍在找铺/谈判阶段有用。一票否决时否决优先（非补偿性硬约束）。
    biz = business_score(profit, profit_bands, veto_triggered=bool(veto_reason),
                         has_rent=bool(monthly_rent))
    address_verdict = _verdict(total)
    if veto_reason:
        verdict = _verdict(total, veto_reason)
    else:
        verdict = biz.get('结论') or address_verdict

    return {
        'category': category,
        'name': name,
        'lng': lng,
        'lat': lat,
        'monthly_rent': monthly_rent,
        'area_m2': area_m2,
        'city': city,
        'investment': investment,
        'staff': staff,
        'brand': brand,
        'own_brand_S': own_S,
        'attraction_bonus': round(attraction_bonus, 1),
        'dims': dims,
        'weights': weights,
        'total': round(total, 1),
        # ⚠️ `total` 键**不改名**（改了会破坏历史 analyses.json / conversations.json 的兼容性）；
        #    展示层一律称「地址评分」，并额外给一个同值的 '地址评分' 键方便新代码直读。
        '地址评分': round(total, 1),
        'verdict': verdict,
        # 经营评分（"能不能赚钱"）：分数 + 三档区间；结论以它为准。见 business_score。
        '经营评分': biz,
        # 机器可读的否决信息：下游（UI/PDF/LLM prompt）读字段，不要解析结论文案
        'veto': {'触发': bool(veto_reason), '原因': veto_reason,
                 '判定情景': DEFAULT_SCENARIO,
                 '位置分结论': address_verdict,
                 '地址结论': address_verdict},
        'rent_limits': rent_limits,
        'warnings': warnings,
        'evidence': {
            '客群引力累计': guest_g,
            '竞品数': comp_n,
            '捕获份额P': capture_p,
            '需求规模D': sales_est['需求规模D'],
            '竞品样本': comp_samples,
            '最近通勤点(m)': metro_d,
            '500m内通勤点数': n_stops,
            '预估月流水': est_sales,
            '预估日单量': sales_est['估算日单量'],
            '流水明细': sales_est,
            '租金占流水比': f'{rent_ratio:.0%}',
            '客单价': sales_est['客单价'],
            '客单价来源': sales_est['客单价来源'],
        },
        '客单价校正': {
            # ⚠️ 校正客单价的口径是**每单金额**（元/单），
            #    不是高德 cost（那是单杯价/人均，口径差约 1.7 杯）
            '校正客单价': corrected_price,
            '品类画像客单价': profile['price'],
            '单杯价': price_ref.get('单杯价'),
            '每单金额口径来源': price_ref.get('口径来源'),
            '校正倍数': price_ref.get('校正倍数'),
            '口径': price_ref.get('口径') or '未做校正',
            '证据': price_ref.get('证据'),
            # 取数溯源：同一份报告的数字必须能说清"哪来的、什么时候取的"，
            # 否则用户无法判断该不该复核
            '抓取状态': price_ref.get('抓取状态'),
            '数据来源': price_ref.get('来源'),
            '取证时间': price_ref.get('取证时间'),
        },
        'decoration': deco,
        'guest_details': guest_details,
        'profile_desc': profile['profile_desc'],
        'utility': utility,
        'profit': profit,
        'profit_bands': profit_bands,
        # 口径区间（价格-单量弹性未知）：与 profit_bands 正交——那三档变的是
        # 成本假设（扣点/税/损耗/产能），这一档变的是需求假设（单量跟不跟单价动）。
        '距离口径': dist_report(),
        '口径区间': caliper_band,
        'model': 'huff-v4',
    }


def apply_storefront(result, vlm):
    """把门头照片的真实视觉证据(VLM 输出)并入已有评分结果。
    形象分 = 0.5×装修档次 + 0.3×门头可见度 + 0.2×卫生观感 (1-5 分档映射 0~100)
    权重 10%, 其余维度按原比例缩放到 90%; 重算总分与结论。
    不修改任何经营测算(流水/成本/回本), 只增加"形象"软指标维度。
    vlm: agent.vision.analyze_storefront 的返回 dict
    """
    if not result or not vlm:
        return result
    # 非门头实景(logo/宣传图/室内局部) → 不计分, 避免用假证据污染总分
    if not vlm.get('是否门头实景'):
        return result
    w_deco, w_front, w_clean = 0.5, 0.3, 0.2
    raw = (w_deco * vlm.get('装修档次', 3)
           + w_front * vlm.get('门头可见度', 3)
           + w_clean * vlm.get('卫生观感', 3))
    photo_score = round((raw - 1) / 4 * 100, 1)   # 1→0, 3→50, 5→100

    old_dims = dict(result.get('dims') or {})
    old_weights = dict(result.get('weights') or {})
    old_total = result.get('total')
    if not old_dims or not old_weights:
        return result

    # 已有"门头形象(照片)"维度时, 先剔除再重加(避免重复上传照片导致权重膨胀)
    old_dims.pop('门头形象(照片)', None)
    old_weights.pop('门头形象(照片)', None)
    rest = 0.90
    wsum = sum(old_weights.values()) or 1.0
    new_weights = {k: v / wsum * rest for k, v in old_weights.items()}
    new_weights['门头形象(照片)'] = 0.10
    new_dims = dict(old_dims)
    new_dims['门头形象(照片)'] = photo_score
    total = round(sum(new_dims[k] * new_weights[k] for k in new_dims), 1)

    # 结论沿用同一套判定（含盈利一票否决）：否则上传一张门头照抬高总分，
    # 就能把"账算不过来"洗回"推荐"，等于绕过否决
    veto = dict(result.get('veto') or {'触发': False, '原因': None})
    address_verdict = _verdict(total)
    veto['位置分结论'] = address_verdict
    veto['地址结论'] = address_verdict
    # 结论以经营评分为准：门头照只改**地址评分**，不改经营评分 →
    #   未否决时保留原（经营驱动的）结论，一张照片不该改写"赚不赚钱"；
    #   否决时仍走双轴（位置分可能被照片抬高，但否决不能被洗白）。
    if veto.get('触发'):
        verdict = _verdict(total, veto.get('原因'))
    elif (result.get('经营评分') or {}).get('分数') is not None:
        verdict = result['经营评分'].get('结论') or address_verdict
    else:
        verdict = address_verdict

    warnings = list(result.get('warnings') or [])
    warnings = [w for w in warnings if '门头形象' not in w]
    if photo_score < 40:
        warnings.append(f'⚠️ 门头形象偏低（照片实测 {photo_score:.0f} 分）：'
                        '门头/装修观感差会直接压制到店转化，签约前需预留门头翻新预算')
    deco = result.get('decoration') or {}
    deco_score = deco.get('档次分')
    if deco_score is not None and abs(deco_score - photo_score) >= 20:
        warnings.append(
            f'ℹ️ 投入金额推断的装修档次（{deco_score} 分）与照片实际观感（{photo_score:.0f} 分）'
            f'差异较大，已按照片证据计分——花得多不等于看得好')

    result['dims'] = new_dims
    result['weights'] = new_weights
    result['total'] = total
    result['地址评分'] = total          # 与 total 同值的展示键，照片改动后必须同步
    result['verdict'] = verdict
    result['veto'] = veto
    result['warnings'] = warnings
    result['storefront'] = {
        '招牌文字': vlm.get('招牌文字'),
        '识别品牌': vlm.get('识别品牌'),
        '装修档次': vlm.get('装修档次'),
        '门头可见度': vlm.get('门头可见度'),
        '卫生观感': vlm.get('卫生观感'),
        '观察描述': vlm.get('观察描述'),
        '经营建议': vlm.get('经营建议'),
        '形象分': photo_score,
        '照片前总分': old_total,
        '照片后总分': total,
        '权重占比': 0.10,
        '模型': vlm.get('_model'),
    }
    return result


def evaluate_decoration(budget, area_m2, category):
    """根据装修预算评估装修档次(需求3):
    档次分 = 预算/面积 得到的单位面积装修投入(元/㎡) 映射到 0~100。
    - 经济型: <1000元/㎡
    - 标准型: 1000~2000元/㎡
    - 品质型: 2000~3500元/㎡
    - 高端型: >3500元/㎡
    返回 dict(档次, 档次分, 单位投入)
    """
    if not budget or not area_m2:
        return None
    per_m2 = budget / area_m2
    if per_m2 >= 3500:
        tier, score = '高端', 90
    elif per_m2 >= 2000:
        tier, score = '品质', 75
    elif per_m2 >= 1000:
        tier, score = '标准', 60
    else:
        tier, score = '经济', 40
    return {
        '装修预算': budget,
        '面积': area_m2,
        '单位投入(元/㎡)': round(per_m2),
        '档次': tier,
        '档次分': score,
        '说明': f'{tier}型装修，单位面积投入约{per_m2:.0f}元/㎡',
    }


def compare_sites(category, sites, monthly_rent):
    """对比多个候选地址: sites = [(name, lng, lat), ...]"""
    results = [score_site(category, lng, lat, monthly_rent, name) for name, lng, lat in sites]
    results.sort(key=lambda r: r['total'], reverse=True)
    return results


if __name__ == '__main__':
    print('评分引擎 v2 (Huff 引力模型) 加载成功。')
    print('  from engine.scoring import score_site')
    print('  r = score_site("奶茶", 120.1552, 30.2741, monthly_rent=8000)')
