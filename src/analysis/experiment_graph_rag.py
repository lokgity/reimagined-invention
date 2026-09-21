# -*- coding: utf-8 -*-
"""experiment_graph_rag.py —— Classic RAG 与图增强检索的召回增益对照实验
=======================================================================
要回答的问题（用户第五问）：**把 classic RAG 与 graph RAG 融合，能不能真正提升召回？**

做法：不猜，做可复现的对照实验 —— 四层检索器 × 三组查询集 × 四个指标。

四层检索器
----------
  classic      : 现有实现（中文 2-gram TF-IDF 余弦），直接调 kb.retrieve 的底层
  graph        : 只用"实体—文档图"打分（查询命中的实体沿边扩散到文档）
  hybrid(RRF)  : classic 与 graph 用 Reciprocal Rank Fusion 融合
  hybrid+2hop  : 在 hybrid 之上，把 classic 首位文档的实体也并入查询实体（β=0.5），
                 即"顺着图再走一跳"

⚠️ 为什么融合用 RRF 而不是加权求和
  两个检索器的分数量纲完全不同（余弦相似度 ∈ [0,1]，图分是无界加权和）。
  加权求和必须先 min-max 归一化，而"在哪个候选集上做 min-max"会**直接改变结论**
  —— 等于在实验里多埋一个自由度，谁都能调出想要的结果。
  RRF 只用**名次**、不用分值（score = Σ 1/(k+rank)，k=60），免归一化、可复现。
  这是检索融合的通行做法，也是本实验刻意规避自由度的地方。

三组查询集（各有各的用途，不能混着看）
--------------------------------------
  A 标注集  : 既有 42 条单答案标注查询。**是为 TF-IDF 设计的**，所以拿它评估
              "图能不能提升"先天偏袒 baseline —— 它本来就该被 classic 全中。
              它在这里的作用是**反向哨兵**：融合若把这组搞坏，就是纯粹的伤害。
  B 难题集  : 新写的单答案查询，刻意用**多跳 + 低词面重叠**的口语问法。
  C 多跳对  : 需要**同时**召回两条例目的问题，判据是"两条都进 top3"。
              —— 这一组才是图增强理论上最该赢的地方：单条检索器天生只能给一个
                 局部最优，而"需要两个知识点配合"的问题要求检索器理解条目间关系。

指标：recall@1 / recall@3 / MRR（对 A、B）；pair-hit@3（对 C）；零命中率（全组）。

⚠️ 结论的诚实边界（必须与结果一同呈现）
  1. B/C 两组是本实验**自己构造**的，不是独立标注数据；构造者同时也是图的设计者
     → 只能证明"在这个语料上有/没有增益"，**不能证明泛化**。
  2. 语料仅 70 条、单机、单语种 → 不代表上千条语料下的表现（量级一变，
     IDF 结构、实体覆盖率、2-gram 命中率全都变）。
  3. 三组都是**特定探针**，不是真实用户提问分布。真实分布里问题更长、更口语、
     更常把多个意图混在一起，那才是融合真正要面对的战场。
  4. 本脚本**不进回归门禁**：它是实验，不是不变量。跑法见文件末尾。

用法：C:\\Python314\\python.exe src/analysis/experiment_graph_rag.py
输出：同目录 _experiment_graph_rag.txt
"""
import math
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / '.pylibs'))
sys.path.insert(0, str(HERE))            # 复用 verify_knowledge_rag 的标注集

import agent.knowledge as kb                      # noqa: E402
from verify_knowledge_rag import LABELED, _wants  # noqa: E402

OUT = HERE / '_experiment_graph_rag.txt'
L = []


def p(*a):
    s = ' '.join(str(x) for x in a)
    print(s)
    L.append(s)


# =====================================================================
# 1. 实体词典与抽取器（规则式，零依赖）
# =====================================================================
# 设计取舍：**用人工词典而不是自动实体抽取**。
#   理由是这是个 70 条的专业小语料 —— 自动抽（TF-IDF 高频词 / TextRank）在这个
#   量级上噪声很大，而且抽出来的"实体"无法解释、无法验收。
#   人工词典的代价是**不泛化**（换领域要重写），但本实验的结论本来也只在
#   这个语料上成立，所以取舍一致：宁可窄而准。
# 别名的作用：让"蜜雪"和"蜜雪冰城"、"huff"和"Huff"、"租金承受力"和"rent_ratio"
#   落到同一个节点上 —— 这正是图相比词面匹配的**唯一优势来源**。
LEXICON = [
    # ── 品牌 ──
    ('蜜雪冰城', ['蜜雪冰城', '蜜雪']),
    ('古茗', ['古茗']),
    ('霸王茶姬', ['霸王茶姬']),
    ('喜茶', ['喜茶']),
    ('茶百道', ['茶百道']),
    ('沪上阿姨', ['沪上阿姨']),
    ('CoCo', ['coco', '都可']),
    ('茉莉奶白', ['茉莉奶白']),
    ('LINLEE', ['linlee', '林里']),
    ('奈雪', ['奈雪']),
    ('乐乐茶', ['乐乐茶', 'lelecha']),
    ('一点点', ['一点点']),
    ('茉酸奶', ['茉酸奶']),
    ('爷爷不泡茶', ['爷爷不泡茶']),
    ('茶理宜世', ['茶理宜世']),
    # ── 品类 ──
    ('奶茶', ['奶茶', '茶饮', '新式茶饮', '饮品店']),
    ('甜品', ['甜品', '烘焙', '蛋糕']),
    ('早餐', ['早餐', '早点']),
    ('便利店', ['便利店']),
    # ── 商圈（标定样本来源，图上的"共同出处"节点）──
    ('宁波天一广场', ['宁波天一', '天一广场']),
    ('杭州湖滨in77', ['湖滨in77', 'in77', '湖滨银泰']),
    ('海宁银泰', ['海宁银泰']),
    ('83家门店样本', ['83 家', '83家', '85 家', '真实门店']),
    # ── 模型量 / 参数（图的核心骨架）──
    ('Huff模型', ['huff', '赫夫']),
    ('距离衰减λ', ['λ', '距离衰减', 'lambda']),
    ('最小等效距离d0', ['d0', '最小等效距离']),
    ('流水锚点REF_DP', ['ref_dp', '流水锚点', '锚点']),
    ('竞争锚点P_REF', ['p_ref', '60 分', '60分']),
    ('捕获份额', ['捕获份额']),
    ('需求规模D', ['需求规模', '需求池']),
    ('品牌引力S', ['品牌引力', 'brand_s']),
    ('品牌溢价UPLIFT', ['uplift', '品牌溢价']),
    ('标定', ['标定']),
    ('权重', ['权重', '赋权']),
    ('回归', ['回归', 'ols']),
    ('敏感性检验', ['敏感性']),
    ('截断封顶', ['截断', '封顶']),
    ('竞争分', ['竞争压力', '竞争分']),
    ('客群匹配度', ['客群匹配度', '客群引力']),
    ('交通可达性', ['交通可达性', '地铁']),
    ('租金承受力', ['租金承受力', 'rent_ratio']),
    ('面积适配度', ['面积适配度', '理想面积']),
    ('门头形象分', ['形象分', '门头照', '门头']),
    ('一票否决', ['一票否决', '否决']),
    ('口径区间', ['口径区间']),
    ('置信区间', ['置信区间', 'bootstrap']),
    ('价格弹性', ['弹性']),
    ('毛利率', ['毛利率']),
    ('外卖抽成', ['外卖抽成', '佣金', '抽成']),
    ('回本周期', ['回本']),
    ('保守系数', ['保守系数', '爬坡']),
    ('suppression', ['suppression', '共线']),
    ('统计检验', ['spearman', 'wald', 'pearson', 'p值', 'p 值']),
    ('RAG检索', ['rag', '知识库', '检索', '召回']),
]


def extract_tf(text):
    """抽取实体 → Counter（含词频，供 tf 加权用）。"""
    t = text.lower()
    out = Counter()
    for canon, forms in LEXICON:
        c = 0
        for f in forms:
            c += t.count(f.lower())
        if c:
            out[canon] = c
    return out


N = len(kb.KNOWLEDGE_BASE)
TITLES = [d['title'] for d in kb.KNOWLEDGE_BASE]
TITLE_IDX = {t: i for i, t in enumerate(TITLES)}
IDX = kb._get_index()

DOC_ENT = []
_DF = Counter()
for d in kb.KNOWLEDGE_BASE:
    tf = extract_tf(d['title'] + '。' + d['text'])
    DOC_ENT.append(tf)
    for e in tf:
        _DF[e] += 1

# 与 kb 同形的 IDF：log((N+1)/(df+1)) + 1
# 含义：满语料都出现的实体（如「回本」）权重被压到 1，只在少数条目出现的
#   （如「suppression」「Wald」）权重高 —— 后者才是能把条目区分开的骨架实体。
IDF = {e: math.log((N + 1) / (c + 1)) + 1 for e, c in _DF.items()}
ENT_COVER = len(_DF)


def edge_weight(doc_i, ent):
    """文档 i 与实体 ent 的边权 = (1 + log tf) × idf。"""
    tf = DOC_ENT[doc_i].get(ent, 0)
    if not tf:
        return 0.0
    return (1.0 + math.log(tf)) * IDF.get(ent, 0.0)


def _rank(scores):
    return [t for t, _ in sorted(scores.items(), key=lambda x: -x[1])]


# =====================================================================
# 2. 四个检索器
# =====================================================================
def classic_scores(q):
    """全库原始余弦（min_score=0 以拿到完整分布）。"""
    return {d['title']: s for d, s in IDX.search(q, top_k=N, min_score=0.0)}


def graph_scores(q, extra=None, beta=0.5):
    """图分 = Σ_{e∈E_q} w_q(e) · edge_weight(d, e)。

    extra: 额外并入的实体（2 跳用）；beta 是它们的降权系数。
    返回 (score_dict, E_q)。E_q 为空时返回 ({}, {}) —— 调用方必须处理，
    不能假装"图检索没结果 = 没有相关文档"。
    """
    eq = {e: 1.0 for e in extract_tf(q)}
    if extra:
        for e in extra:
            eq[e] = max(eq.get(e, 0.0), beta)
    if not eq:
        return {}, {}
    out = {}
    for i in range(N):
        s = 0.0
        for e, wq in eq.items():
            w = edge_weight(i, e)
            if w:
                s += wq * w
        if s > 0:
            out[TITLES[i]] = s
    return out, set(eq)


def _rrf(rank_lists, k=60):
    """Reciprocal Rank Fusion：只用名次，免归一化。"""
    acc = Counter()
    for lst in rank_lists:
        for r, t in enumerate(lst, start=1):
            acc[t] += 1.0 / (k + r)
    return acc


# 候选池大小：RRF 的 classic 侧取前 CAND 名。
# ⚠️ 这是个**自由参数**，本实验固定 20 并说明理由：CAND 太小会让图侧无从"救回"
#    被 classic 排到 30 名的条目（那正是图该发挥作用的情形），太大则把大量
#    长尾噪声带进融合。取 20 ≈ 语料的 29%，是"能救回"与"不引噪"的折中。
#    我们**没有**对 CAND 调参求最优 —— 那会让结论变成"调出来的"。
CAND = 20


def ret_classic(q, top_k=3):
    return _rank(classic_scores(q))[:top_k]


def ret_graph(q, top_k=3):
    gs, _ = graph_scores(q)
    if not gs:                      # 查询里没有任何已知实体 → 诚实地退回 classic
        return ret_classic(q, top_k)
    return _rank(gs)[:top_k]


def ret_hybrid(q, top_k=3, two_hop=False):
    c_rank = _rank(classic_scores(q))[:CAND]
    if two_hop and c_rank:
        # 从 classic 首位文档取实体，作为"第二跳"并入
        extra = set(DOC_ENT[TITLE_IDX[c_rank[0]]])
        gs, _ = graph_scores(q, extra=extra, beta=0.5)
    else:
        gs, _ = graph_scores(q)
    g_rank = _rank(gs)
    fused = _rrf([c_rank, g_rank])
    return [t for t, _ in fused.most_common(top_k)]


RETRIEVERS = [
    ('classic', ret_classic),
    ('graph', ret_graph),
    ('hybrid (RRF)', lambda q, k=3: ret_hybrid(q, k, two_hop=False)),
    ('hybrid + 2hop', lambda q, k=3: ret_hybrid(q, k, two_hop=True)),
]


# =====================================================================
# 3. 三组查询集
# =====================================================================
# ── A 组：既有 42 条标注（复用，避免两处维护）──
SET_A = [(q, _wants(w)) for q, w in LABELED]

# ── B 组：难题集 ──
# 构造原则（写出来免得后人以为是在"编测试"）：
#   **问法里刻意不含目标条目标题的核心词**，只给场景 + 一个侧面的实体。
#   这样 classic（词面匹配）会掉到别的条目上，而图能顺着实体爬回正确条目。
#   每条后面括号里写"为什么难"，便于审核这条是不是真的难。
SET_B = [
    # 问"两个数字为什么必须绑在一起"，标题里没有"绑/一起"这类词
    ('那两个定分基准为什么不能只换一个', ('流水锚点是怎么标定出来的',
                                          '竞争分的 60 分基准是怎么定的')),
    # 问"能不能给我一个概率"，标题里没有"概率"
    ('这个区间我能理解成有多大把握吗', ('口径区间是置信区间吗',)),
    # 场景化：不说"权重"，说"拍脑袋"
    ('你们分数里的比例是有依据还是拍的', ('四个维度的权重是怎么定下来的',)),
    # 场景化：不说"回归"，说"检验"
    ('我怎么知道你的模型不是自己骗自己', ('权重能不能用回归验证',)),
    # 多跳式：需要先想到"竞争分由 P 定，P 由密度定"
    ('周围店多是不是就一定不好', ('捕获份额 P 高是不是说明品牌强',)),
    # 场景化：不说"截断"，说"都是一百分"
    ('为什么好几个地方的分一模一样', ('为什么热门点位的竞争分都是满分',)),
    # 场景化：不说"弹性"，说"涨价"
    ('我把东西卖贵点会不会反而少赚', ('提高流水就一定能改善回本吗',)),
    # 场景化：不说"毛利率口径"，说"平台扣的钱"
    ('平台扣的那笔钱算不算我的成本', ('毛利率是按什么口径算的',)),
    # 多跳式：需要把"品牌溢价只进流水"这条挖出来
    ('同样一家店换成不同牌子结果差在哪', ('品牌同商圈溢价是怎么算的',)),
    # 场景化：不说"log-log"，说"你们算出来不一样"
    ('你们算的距离系数和书上写的不一样', ('λ 估计出来为什么和文献值对不上',)),
    # 场景化：不说"一票否决"，说"不给过"
    ('分数明明挺高的为什么最后不给过', ('位置分很高但还是亏钱 这铺子还能签吗',)),
    # 场景化：不说"D 和 P 混放"，说"两个变量"
    ('模型里有两个数能不能一起用', ('需求 D 和份额 P 能不能放一个回归里',)),
]

# ── C 组：多跳对（判据 = 两条都进 top3）──
# 每条都必须**真的需要两条例目配合**才能答全 —— 只答一条是残缺的。
# 若某条其实一条就够，那它测的是单条召回，放进 C 组会虚高基线。
SET_C = [
    ('蜜雪的溢价看着比喜茶高，怎么竞争分反倒一比一平',
     ('品牌同商圈溢价是怎么算的', '品牌溢价为什么不算进竞争分')),
    ('你们哪些数字是拍的，哪些是真标定过的',
     ('四个维度的权重是怎么定下来的', '流水锚点是怎么标定出来的')),
    ('这个租金到底能不能签，该先看哪条线再看哪条',
     ('盈亏平衡月租和回本上限有什么区别', '位置分很高但还是亏钱 这铺子还能签吗')),
    ('外卖占比高是不是同时压了两样东西',
     ('毛利率是按什么口径算的', '堂食与外卖的利润差异')),
    ('为什么换个牌子同一家店流水就变了，可分数没变',
     ('品牌同商圈溢价是怎么算的', '本系统的选址评分是怎么算出来的')),
    ('你既有把握区间又有信区间，这俩是一回事吗',
     ('口径区间是置信区间吗', '回本红线为什么是 24 个月')),
    ('周围店多不多这件事，到底影响的是人流还是份额',
     ('捕获份额 P 高是不是说明品牌强', '需求规模 D 是怎么统计的（0.8 和 0.2 从哪来）')),
    ('一次评分里参数是从哪来的，又是怎么被检验的',
     ('距离衰减系数 λ 和最小等效距离取多少', '维度分是怎么检验的')),
]


# =====================================================================
# 4. 评估
# =====================================================================
def eval_single(retriever, queries, top_k=3):
    """返回 (recall@1, recall@3, MRR, n, misses)。expected 是"都算对"的标题集合。"""
    n = len(queries)
    h1 = h3 = 0
    rr = 0.0
    misses = []
    for q, wanted in queries:
        got = retriever(q, top_k)
        if got and got[0] in wanted:
            h1 += 1
        if any(w in got for w in wanted):
            h3 += 1
        else:
            misses.append((q, wanted[0], got))
        for r, t in enumerate(got, start=1):
            if t in wanted:
                rr += 1.0 / r
                break
    return h1 / n, h3 / n, rr / n, n, misses


def eval_pairs(retriever, queries, top_k=3):
    """pair-hit@3 = 两条期望条目**都**落在 top3 的比例。"""
    n = len(queries)
    ok = 0
    detail = []
    for q, pair in queries:
        got = retriever(q, top_k)
        hit = [t for t in pair if t in got]
        if len(hit) == len(pair):
            ok += 1
        detail.append((q, pair, got, len(hit)))
    return ok / n, n, detail


def zero_rate(queries, min_score=0.11):
    """零命中率：用生产阈值 min_score 跑 classic，返回"一条都没召回到"的比例。

    ⚠️ 必须走 IDX.search(..., min_score=) 而不是 kb.retrieve()：
       `kb.retrieve(query, top_k, tags)` 的签名里**没有** min_score 参数
       （阈值固定用 _Index.search 的默认值），传了会 TypeError。
    注意：这个指标只对 classic 有意义（graph 与 RRF 不套 min_score，
    它们的输出永远是"排名"而不是"过没过线"）。保留它是为了说明
    "阈值过滤掉了多少查询"——一个图融合可以顺带解决的问题。
    """
    z = 0
    for q, _w in queries:
        if not IDX.search(q, top_k=3, min_score=min_score):
            z += 1
    return z / len(queries)


def coverable_pairs(queries):
    """只保留"期望条目在图上至少有一个实体"的用例（单答案组用）。

    ⚠️ 为什么必须分开算 —— 这是本次实验最关键的一个方法论决定：
    本词典覆盖不到全部语料（实测 70 条里有 18 条是**孤点**）。
    图检索对这些条目**在原理上**就不可能召回 —— 那不是算法输，是图没建到那儿。
    把两种失败混在一个数字里算，等于**用人造短板给图判负**，结论就不可信了。
    所以同时报两套：
      · 全集       ：反映"这套图能不能直接替换 classic"（工程可行性问题）
      · 可覆盖子集 ：反映"图这个思路在它够得着的地方到底有没有用"（算法问题）
    答辩时如果只报其中一套，一定要说清是哪一套。
    """
    return [(q, w) for q, w in queries
            if any(t in TITLE_IDX and DOC_ENT[TITLE_IDX[t]] for t in w)]


def coverable_pair_set(queries):
    """C 组用：两条期望条目**都**在图上可覆盖才算（少一条都做不到 pair-hit）。"""
    return [(q, pair) for q, pair in queries
            if all(t in TITLE_IDX and DOC_ENT[TITLE_IDX[t]] for t in pair)]


def table(queries, indent='    '):
    """打印四个检索器在同一查询集上的指标表，返回 {name: (r1, r3, mrr)}。"""
    out = {}
    for name, fn in RETRIEVERS:
        r1, r3, mrr, _n, _miss = eval_single(fn, queries)
        out[name] = (r1, r3, mrr)
        p(f'{indent}{name:<14} recall@1 {r1:6.1%}   recall@3 {r3:6.1%}   MRR {mrr:.4f}')
    return out


def main():
    p('=== experiment_graph_rag —— Classic RAG vs 图增强检索（召回增益对照实验）===')
    p(f'语料条数：{N}　实体词表：{len(LEXICON)} 个规范实体　图上实际出现：{ENT_COVER} 个')
    p(f'查询集：A 标注 {len(SET_A)} 条　B 难题 {len(SET_B)} 条　C 多跳对 {len(SET_C)} 组')
    p('')

    # ---- 图的基本盘：实体覆盖率 ----
    p('=== T0 图的基本盘 ===')
    no_ent = [TITLES[i] for i in range(N) if not DOC_ENT[i]]
    p(f'  至少命中 1 个实体的条目：{N - len(no_ent)}/{N}')
    if no_ent:
        p(f'  ⚠️ 零实体条目（图上是孤点，只能靠 classic 召回）：{no_ent}')
    ent_cnt = sorted((len(tf), TITLES[i]) for i, tf in enumerate(DOC_ENT))
    p(f'  实体最少的 3 条：{[(c, t) for c, t in ent_cnt[:3]]}')
    p(f'  实体最多的 3 条：{[(c, t) for c, t in ent_cnt[-3:]]}')
    # 只出现 1 次的实体：它们是"能把某个条目单独拉出来"的稀有骨架
    rare = [e for e, c in _DF.items() if c == 1]
    p(f'  只出现在 1 条语料里的实体：{len(rare)} 个（稀有骨架，最能拉出单条）')
    mq = Counter()
    for d in kb.KNOWLEDGE_BASE:
        for e in extract_tf(d['title'] + '。' + d['text']):
            mq[e] += 1
    p(f'  图度数最高的 8 个实体（最容易把不相关条目连起来的"枢纽"）：')
    for e, c in mq.most_common(8):
        p(f'    {e}: 出现在 {c} 条语料')
    p('')

    # ---- A 组（反向哨兵）----
    p('=' * 68)
    p('【A 组】既有标注查询（%d 条）—— 作用：反向哨兵（融合不能把这组搞坏）' % len(SET_A))
    p('  说明：这组是**为 TF-IDF 设计**的，baseline 本就该接近满分；')
    p('        图融合若在这里掉分，就是纯伤害，没有任何借口。')
    res_a = {}
    for name, fn in RETRIEVERS:
        r1, r3, mrr, n, miss = eval_single(fn, SET_A)
        res_a[name] = (r1, r3, mrr, miss)
        p(f'  {name:<14} recall@1 {r1:6.1%}   recall@3 {r3:6.1%}   MRR {mrr:.4f}')
    for name, (_r1, _r3, _m, miss) in res_a.items():
        for q, w, g in miss:
            p(f'    [{name}] MISS 期望「{w}」｜{q}｜实得 {g}')
    p(f'  classic 零命中率（min_score=0.11，一条都没召回）：{zero_rate(SET_A):.1%}')
    _ca = coverable_pairs(SET_A)
    p(f'  ── 仅「图上可覆盖」子集（{len(_ca)}/{len(SET_A)} 条；剔除期望条目是孤点的）──')
    p('     这一套才是对"图这个思路"公平的判据：够不着的不算它头上。')
    res_ca = table(_ca)
    p('')

    # ---- B 组（难题）----
    p('=' * 68)
    p('【B 组】难题集 —— 多跳 / 低词面重叠的口语问法')
    res_b = {}
    for name, fn in RETRIEVERS:
        r1, r3, mrr, n, miss = eval_single(fn, SET_B)
        res_b[name] = (r1, r3, mrr, miss)
        p(f'  {name:<14} recall@1 {r1:6.1%}   recall@3 {r3:6.1%}   MRR {mrr:.4f}')
    p('  逐条明细（看 classic 掉在哪、图有没有拉回来）：')
    for q, wanted in SET_B:
        line = f'    · {q}'
        p(line)
        p(f'      期望 {list(wanted)}')
        for name, fn in RETRIEVERS:
            got = fn(q, 3)
            flag = '✓' if any(w in got for w in wanted) else '✗'
            p(f'      {flag} {name:<14} {got}')
    _cb = coverable_pairs(SET_B)
    p(f'  ── 仅「图上可覆盖」子集（{len(_cb)}/{len(SET_B)} 条）──')
    res_cb = table(_cb)
    p('')

    # ---- C 组（多跳对）----
    p('=' * 68)
    p('【C 组】多跳对 —— 判据：两条期望条目**都**进 top3')
    p('  —— 这是图增强理论上最该赢的一组：要求检索器给出"配套的两个知识点"')
    res_c = {}
    for name, fn in RETRIEVERS:
        rate, n, detail = eval_pairs(fn, SET_C)
        res_c[name] = (rate, detail)
        p(f'  {name:<14} pair-hit@3 {rate:6.1%}  ({round(rate * n)}/{n})')
        for q, pair, got, hit in detail:
            if hit < len(pair):
                p(f'      缺 {len(pair) - hit} 条｜{q}')
                p(f'        期望 {list(pair)}｜实得 {got}')
    _cc = coverable_pair_set(SET_C)
    res_cc = {}
    p(f'  ── 仅「图上可覆盖」子集（{len(_cc)}/{len(SET_C)} 组；两条都要够得着）──')
    for name, fn in RETRIEVERS:
        rate, n, _d = eval_pairs(fn, _cc)
        res_cc[name] = rate
        p(f'    {name:<14} pair-hit@3 {rate:6.1%}  ({round(rate * n)}/{n})')
    p('')

    # ---- 汇总 + 自动结论 ----
    p('=' * 68)
    p('=== 汇总表（全集）===')
    p(f'{"检索器":<16}{"A r@1":>9}{"A r@3":>9}{"B r@1":>9}{"B r@3":>9}{"C pair@3":>11}')
    for name, _fn in RETRIEVERS:
        p(f'{name:<16}{res_a[name][0]:>9.1%}{res_a[name][1]:>9.1%}'
          f'{res_b[name][0]:>9.1%}{res_b[name][1]:>9.1%}{res_c[name][0]:>11.1%}')
    p('')
    p('=== 汇总表（仅「图上可覆盖」子集 —— 对图公平的那一套）===')
    p(f'{"检索器":<16}{"A r@1":>9}{"A r@3":>9}{"B r@1":>9}{"B r@3":>9}{"C pair@3":>11}')
    for name, _fn in RETRIEVERS:
        p(f'{name:<16}{res_ca[name][0]:>9.1%}{res_ca[name][1]:>9.1%}'
          f'{res_cb[name][0]:>9.1%}{res_cb[name][1]:>9.1%}{res_cc[name]:>11.1%}')
    p('')

    p('=== 自动结论（由数字推出，不是预先写好的立场）===')
    p('  判据分两栏：全集看"能不能直接替换 classic"；可覆盖子集看"图这个思路有没有用"。')
    for name, _fn in RETRIEVERS:
        if name == 'classic':
            continue
        d_a1 = res_ca[name][0] - res_ca['classic'][0]
        d_a3 = res_ca[name][1] - res_ca['classic'][1]
        d_b1 = res_cb[name][0] - res_cb['classic'][0]
        d_b3 = res_cb[name][1] - res_cb['classic'][1]
        d_c = res_cc[name] - res_cc['classic']
        f_a1 = res_a[name][0] - res_a['classic'][0]
        f_a3 = res_a[name][1] - res_a['classic'][1]
        verdict = []
        # ① 工程判据：会不会把已经做对的事情做坏
        if f_a3 < 0 or f_a1 < 0:
            verdict.append(f'⚠️ 全集下把 A 组打坏（r@1 {f_a1:+.1%} / r@3 {f_a3:+.1%}）')
        else:
            verdict.append(f'A 组全集不掉分（r@1 {f_a1:+.1%} / r@3 {f_a3:+.1%}）')
        # ② 算法判据：在够得着的地方有没有正增益
        gains = []
        if d_a1 > 0 or d_a3 > 0:
            gains.append(f'A 可覆盖 r@1 {d_a1:+.1%} / r@3 {d_a3:+.1%}')
        if d_b1 > 0 or d_b3 > 0:
            gains.append(f'B 可覆盖 r@1 {d_b1:+.1%} / r@3 {d_b3:+.1%}')
        if d_c > 0:
            gains.append(f'C 可覆盖 pair@3 {d_c:+.1%}')
        verdict.append('正增益：' + ('、'.join(gains) if gains else '无（没有任何一处在可覆盖子集上赢过 classic）'))
        p(f'  {name}：' + '；'.join(verdict))
    p('')
    p('结论请连同下面三条边界一起读：')
    p('  ① B/C 两组是自建的，构造者=图设计者 ⇒ 不能证明泛化；')
    p('  ② 语料仅 %d 条，量级一变结论可能翻转；' % N)
    p('  ③ 不以"能不能调出正增益"为目标——CAND/β/k 都固定，没有对指标调参；')
    p('     唯一的"调参"是拒绝调参：发现图有 18 条孤点后，选择**补一个可覆盖子集视图**')
    p('     把事实摆出来，而不是回头去改词典把数字堆好看。')

    OUT.write_text('\n'.join(L), encoding='utf-8')
    print('\n[写入]', OUT)


if __name__ == '__main__':
    main()
