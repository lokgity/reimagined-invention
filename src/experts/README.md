# 专家层设计稿 + 落地说明（src/experts/）

> 日期：2026-09-16 ｜ 状态：**已落地（P0 + P1 + P2 全部完成）**
> 上游文档：`docs/专家系统方案评估.md`（架构结论）、`docs/四能力实现度审计.md`
> 相关：`src/engine/store_diagnosis.py`、`src/agent/knowledge.py`
>
> **落地清单（对账用）**
>
> | 阶段 | 交付 | 位置 | 回归 |
> |---|---|---|---|
> | P0 | 运行时注册表 | `registry.py`（启动即校验，失败抛 `ExpertConfigError`） | §1/§2 结构断言 |
> | P0 | 会话状态字段 | `agent/state.py` 的 `AgentState.expert` | — |
> | P0 | 专家切换入口 | 见下方「三个入口」 | §8 接线哨兵 |
> | P1 | 铁律拆为「公共 + 增量」 | `_common.md`（唯一一份，13 条）+ 9 份 persona 无副本 | §3 单源哨兵 |
> | P1 | kb 分区检索 | `knowledge.py` 语料补 `tags` + `search(tags=)` **排序后过滤** | §4 分区一致性 |
> | P1 | 经营测算接 graph 节点 | `agent_graph.py::diagnose_node` + `_wants_diagnose` | §5/§6 |
> | P2 | 专家级回归 | `src/analysis/verify_experts.py`（**74 项**，离线门禁） | 自身 |
> | UI-1 | 静默切换（无对话气泡） | `sidebar.js` 5 处白名单 + 后端不再回文字消息 | §8 |
> | UI-2 | 首屏导航词瘦身 | `app_chainlit.py::on_chat_start` 欢迎语 237 字 | §8 |
> | UI-3 | 输入框上方专家条 | `sidebar.js` `#zl-xbar`（恒跟随 + 二级展开 9 行） | §8 |
> | UI-4 | 左栏「专家系统」3×3 卡片页 | `sidebar.js` `openPage('experts')` + `.zl-ex-grid` | §8 |
> | — | 人名与简介（卡片页数据） | 9 份 md 的 `alias` / `blurb`（**已进 REQUIRED**） | §1 |
> | — | 创业政策语料 | `knowledge.py` 12 条（逐条带法规/文号来源）→ 专家解 blocked | `verify_knowledge_rag.py` |
>
> ### 三个切换入口（共用一条静默通道 `##专家:<id>##`）
>
> | 入口 | 位置 | 交互 | 反馈 |
> |---|---|---|---|
> | ① 输入框上方专家条 | `#zl-xbar` | 点「专家」向上展开 9 行，点行即切 | 3 秒浮层 |
> | ② 左栏「专家系统」卡片页 | `openPage('experts')` | 3×3 卡片，点卡片即切并关页 | 3 秒浮层 |
> | ③ `/expert <序号\|id>` | 手打命令 | 列出 / 切换 | **保留文字回执**（用户打了字就该有回应） |
>
> ⚠️ ①②走 `##专家:id##`（前端已把该指令纳入**静默白名单**，全程不产生对话气泡）；
> ③走 `/expert`，故意保留文字回执。
> ⚠️ 前端**不写死**专家清单：`sidebar.json.experts` 由 `app_chainlit._expert_payload()`
> 从 registry 生成 —— 加专家仍然只是加一个 md 文件。
>
> ⚠️ `_common.md` 与 9 份专家 md 是**运行时输入**（registry 直接读）；
> `validate_design.py` 只是**开发期校验器**，不参与运行时。

---

## 一、一句话定位

**这不是"九个独立 Agent"，而是"九个视角 + 一份共享量化底座"。**

```
用户选专家  ──▶  共享会话状态 AgentState（category/brand/score_result/rent/area…）
                          │  所有专家读同一份
      ┌────────┬──────────┼──────────┬──────────┬─────────┐
  选址评估师  品类反推   竞品分析师  租金谈判   门头审核员   …（共 9）
  persona+    persona+  persona+   persona+   persona+
  工具白名单  工具白名单  工具白名单  工具白名单  工具白名单
  输出契约    输出契约   输出契约   输出契约    输出契约
```

**最大的坑（做错就会翻车）**：把专家做成**独立会话**。
`score_result` 一旦丢失，谈判教练的"承受力上限"、竞品分析的"参照组"、
解读的"证据引用"**全部失效**，专家立刻退化成只会说空话的聊天机器人。
⇒ **必须单会话 + 共享 state，专家只切"视角"。**

---

## 二、目录与文件约定

```
src/experts/
  README.md                      # 本文件（设计总说明，权威）
  _common.md                     # 公共铁律（唯一一份，所有专家继承，禁止复制）
  site_advisor.md                # 1 选址评估师
  category_reverse.md            # 2 品类反推顾问
  competitor_analyst.md          # 3 竞品分析师
  rent_negotiator.md             # 4 租金谈判教练
  storefront_auditor.md          # 5 门头审核员
  startup_policy_advisor.md      # 6 创业政策顾问   ✅ 语料已补（12 条，逐条带来源）
  store_diagnosis_advisor.md     # 7 经营测算专家   ✅ 已接 graph 节点
  franchise_advisor.md           # 8 加盟顾问
  model_auditor.md               # 9 模型审计师
  registry.py                    # 运行时入口（P0 已落地）
  validate_design.py             # 开发期校验器（复用 registry 常量，不参与运行时）
```

**一个专家 = 一个 md 文件。加专家 = 加文件，不改代码。**（答辩可讲的"skill 化"）

`registry.py` 负责：扫描目录 → `yaml.safe_load(frontmatter)` → 校验字段 →
暴露 `list_experts()` / `get_expert(id)` / `compose_system_prompt(id, kb_text)`。
加载即校验、**失败即抛**（不静默跳过：写错却照常启动，比启动失败危险得多）。
已核实本机 `.pylibs` **可用 PyYAML**（`find_spec('yaml')=True`），
不必自写 frontmatter 解析器。

---

## 三、frontmatter 字段规范（权威 schema）

```yaml
---
id: rent_negotiator              # 必填，唯一，snake_case，与文件名一致
name: 租金谈判教练                # 必填，用户可见（岗位名）
alias: 谭铮                      # 必填，人名（唯一，2-4 字）—— 记人比记岗位容易
blurb: "先由引擎算出你这家店的租金承受力天花板，再抓同城同商圈的真实挂牌行情做对照，给你带原话的谈判动作。"
                                 # 必填，2-3 句"我到底帮你做什么"（实测 66-86 字，门槛 ≥40 字）。
                                 # one_liner 只有一句，撑不起卡片页的"详细解释"；
                                 # 缺了卡片页就退化成"只有岗位名的九宫格"。
                                 # ⚠️ 用双引号包住：blurb 里常有 `（`、`——`、`：`，裸标量容易踩 YAML。
icon: handshake                  # 必填，前端图标键
group: 开店前决策链               # 必填：开店前决策链 | 开店后 | 阶段无关
order: 4                         # 必填，组内排序
one_liner: 用真实挂牌行情和承受力上限，教你把租金谈下来   # 卡片副标题
start_sentence: 租金能砍到多少    # 必填，用户"第一句话"示例（用于入口卡预填）
requires:                        # 必填，缺前提时必须明说"给不出"，不许硬编
  - score_result.rent_limits
requires_absent: [category]      # 可选。声明"出现该字段就不该由我处理"
                                 # （唯一使用者：品类反推顾问 —— 有品类就该转评估师）
optional: [monthly_rent, area]
tools: [negotiation_brief, rent_benchmark, kb_retrieve]   # 工具白名单（见第五节）
forbids:                         # 明确禁止调用的能力（与别的专家形成硬差异）
  - analyze_storefront
  - diagnose_existing_store
kb_tags: [谈判与签约]             # 分区检索标签（kb 条目已补 tags，已生效）
node: negotiate_node             # 已实现则填节点名；未实现填 none
fallback: 结构化筹码纯文本         # LLM 全挂时的兜底产物
output_contract: 结论 → 天花板≠开价 → 差额锚 → 3-5 条话术 → 原样转达可比性声明
assertions:                      # P2 专家级断言（每条必须"机器可判"；
                                 # 落地在 src/analysis/verify_experts.py）
  - 输出里不出现"先出 X 元/目标价"这类把天花板当开价的表述
  - 证据包含"可比性声明"时，输出里必须逐字出现
status: ready                    # ready | blocked
---
```

**校验规则（`registry.collect_errors()` 实现，`validate_design.py` 复用同一份）**：
1. `id` 与文件名一致；9 个 `id` 唯一且与预期清单完全相等（多一个少一个都报错）。
2. `tools` / `forbids` 里每个名字必须能在"工具词汇表"（第五节）里查到 → 否则报错，防拼写漂移。
3. `requires` 非空的专家，其 `fallback` 必须非空，不得留空。
4. `group` ∈ {开店前决策链, 开店后, 阶段无关}；`status` ∈ {ready, blocked}。
5. `status: blocked` 的专家**不得出现在用户可选列表**（现 9 位**全部 ready**，blocked=0）。
6. 上面**第 2 条已经抓过真问题**：`franchise_advisor.md` 的 `fallback` 以反引号开头
   → YAML 非法（裸标量不能以 `` ` `` 起头）。**这正是"可断言"的价值** ——
   靠肉眼看 9 份 md 是发现不了的。
7. **规则本身也要被验证**：`collect_errors()` 曾把 `requires: []`（零依赖的正当写法）
   误判成"缺必填"——是规则 bug 不是数据 bug。
8. `alias`（人名）必须**唯一**且 2-4 字 —— 两位专家同名，用户就分不清刚才切给谁了。
   （`id` 是给机器认的，`alias` 是给人记的，两者都要唯一。）
9. `alias` / `blurb` 已升为**必填**（2026-09-16）。理由不是"卡片页要用"，
   而是"缺了就会静默退化成岗位名罗列" —— 这类退化必须启动即失败，不能等用户看见。

---

## 四、九位专家总表

### 4.1 按开店阶段分 3 组

| # | 专家（人名·岗位） | group | 用户第一句话 | requires | 唯一性（"别处没有"的东西） |
|---|---|---|---|---|---|
| 1 | **沈砚舟**·选址评估师 | 开店前 | 「我要在宁波天一广场开奶茶店，这铺子行不行」 | 地址/坐标 + 品类 + 月租 | 唯一产**四维分 + 总分 + 一票否决 + 租金天花板** |
| 2 | **陆知遥**·品类反推顾问 | 开店前 | 「这铺子月租 1.2 万、30㎡，开什么好」 | 地址 + 月租 + 面积（**禁止有品类**） | 唯一**输入里没有品类**、唯一输出**品类排序** |
| 3 | **何竞川**·竞品分析师 | 开店前 | 「周边竞品口碑怎么样」 | 地址/坐标 + 品类 | 唯一产**口碑分/人均价格带/HHI/连锁占比** |
| 4 | **谭铮**·租金谈判教练 | 开店前 | 「租金能砍到多少」 | `score_result.rent_limits` | 唯一产**谈判话术 + 差额锚**（行情≠承受力） |
| 5 | **顾明轩**·门头审核员 | 开店前 | 「帮我看看这张门头照片」 | 一张门头照 | 唯一产**装修/门头/卫生三项视觉分** |
| 6 | **郑策**·创业政策顾问 | 开店前 | 「在宁波开奶茶店要办什么证、有哪些补贴」 | 城市（限浙江） | 唯一产**证照流程 + 地方政策**（语料已补 12 条，逐条带来源） |
| 7 | **钱衡**·经营测算专家 | **开店后** | 「我店已经开了，月流水 8 万，帮我看看哪里不对」 | **用户自报月流水** + 月租 + 品类 | 唯一用**真实流水**（不是模型估）做拆解与对标 |
| 8 | **连知盟**·加盟顾问 | 阶段无关 | 「加盟蜜雪冰城大概要投多少钱」 | 品牌名 | 唯一产**加盟政策参考 + 品牌溢价可信度** |
| 9 | **纪明**·模型审计师 | 阶段无关 | 「你这模型凭什么准」 | 空（零数据依赖） | 唯一"元专家"：唯一输出**不确定性**而非结论 |

### 4.2 三个互斥起点（全清单里最干净的边界）

用户"第一句话"就决定走哪条，**三者数学前提互斥**：

| 起点 | 有品类？ | 有铺位？ | 有真实流水？ | 走哪位 |
|---|---|---|---|---|
| A | ✅ | ✅ | — | **选址评估师**（先算能不能开） |
| B | ❌ | ✅ | — | **品类反推顾问**（先定做什么） |
| C | ✅ | ✅ | ✅（已开店） | **经营测算专家**（不评估，只诊断） |

> ⚠️ A 与 B 的边界**必须靠"有没有品类"判**，不能靠措辞。
> 用户说"这铺子怎么样"——**没提品类** → 反推顾问；说了"开奶茶" → 评估师。
> 这条在 `classify_node` 里已有对应分支（`_wants_shop_first`），专家层只需复用。
>
> C（已开店）的判定已在 `agent_graph.py::_wants_diagnose()` 落地：
> **"已开店措辞" **且** "报了流水"** 才走诊断。两个条件缺一不可 ——
> 只报"我有个店"没有流水 → 仍归 B（还没想好做什么），不会被误判成诊断。
> ⚠️ 三者的判断顺序有硬约束：`_wants_diagnose` 必须**先于** `_wants_shop_first`
> 判定（"我有个店，月流水8万"会同时命中两者的关键词）。
> 回归用 6 条正反例锁死（`verify_experts.py` §5）。

### 4.3 与现有代码的对应关系（**九位全部已接线**）

| 专家 | 实现 | 现状 |
|---|---|---|
| 选址评估师 | `interpret_node` + `compose_system_prompt('site_advisor')` | ✅ 字段级指引已从 prompt 迁进 persona 增量 |
| 品类反推顾问 | `reverse_match_node`（四品类并联，按**月净利**排序） | ✅ 跨品类不可比声明已在卡片与 persona 双落地 |
| 竞品分析师 | `competitor_node` + `competitor_insight.py` | ✅ persona 固定用 `competitor_analyst`，kb 限 `[品类画像,数据与模型边界,营销与运营]` |
| 租金谈判教练 | `negotiate_node` + `negotiation.py` | ✅ persona 固定用 `rent_negotiator`，kb 限 `谈判与签约` |
| 门头审核员 | `vision.py` + `scoring.apply_storefront` | ✅ 两条路径（UI 上传 / graph 自动）共用同一时限常量 |
| 创业政策顾问 | `knowledge.py` 政策分区 + `free_chat_node` | ✅ 语料 12 条（含 4 项未覆盖方向的诚实标注） |
| **经营测算专家** | **`store_diagnosis.py` + `agent_graph.py::diagnose_node`** | ✅ **P1-2 已接线；节点人设固定为该专家** |
| 加盟顾问 | `collect_brand_node`（品牌卡片）+ 附加问题分支 | ✅ kb 限 `加盟政策` |
| 模型审计师 | `knowledge.py` 边界条目 + `free_chat_node` | ✅ kb 限 `[数据与模型边界,选址方法论]` |

> **节点人设固定 vs 用户选择**：`interpret` / `negotiate` / `competitor` / `diagnose`
> 四个节点各自固定用对应专家的人设 —— 因为**节点职责本身**就对应某位专家，
> 不该取决于用户是否手动选了他。`free_chat` 不同：只有用户显式选了专家才换人设，
> **未选时保持改造前的默认行为逐字不变**（回归因此有干净基准）。

---

## 五、工具词汇表（`tools` 只能取这些名字）

> registry 校验用；同时是"专家白名单"与"工具名漂移"的护栏。

| 工具名 | 实现位置 | 说明 |
|---|---|---|
| `score_site` | `engine.scoring` | 四维评分 + 流水 + 成本 + 回本 + 租金临界 |
| `elasticity_band` | `engine.scoring` | 口径区间（价格-单量弹性两端） |
| `solve_rent_limits` | `engine.scoring` | 盈亏平衡月租 / 回本达标月租上限（二分） |
| `compare_sites` | `engine.scoring` | 多铺位对比 |
| `apply_storefront` | `engine.scoring` | 形象分按 10% 权重并入总分 |
| `estimate_profit` / `estimate_profit_bands` | `engine.utilities` | 成本测算 / 三档情景 |
| `estimate_monthly_utility` | `engine.utilities` | 水电成本 |
| `reverse_match` | `agent.agent_graph` | 四品类并联 → 按月净利排序 |
| `competitor_brief` / `brand_price_reference` / `analyze_competitors` | `engine.competitor_insight` | 竞品口碑画像 / 每单金额参照 |
| `negotiation_brief` / `rent_benchmark` | `engine.negotiation` | 谈判筹码 / 58 挂牌分布 |
| `fetch_shops` | `agent.rental58` | 在租铺源抓取 |
| `get_franchise_info` / `supported_brands` / `brand_store_metrics` / `brand_order_value` | `engine.brands` | 加盟政策 / 品牌清单 / 公开经营数据 |
| `brand_uplift` / `brand_uplift_detail` / `brand_attractiveness` / `is_self_brand` | `engine.brands` | 同商圈溢价 / 溢价明细(含 TIER·n·CI) / 品牌引力 S / 自创品牌判定 |
| `analyze_storefront` | `agent.vision` | VLM 门头照（装修/门头/卫生） |
| `diagnose_existing_store` / `brand_benchmark` | `engine.store_diagnosis` | 已开店诊断 / 品牌公开基准 |
| `get_material_ratio` / `get_delivery_ratio` | `engine.utilities` | 物料占比 / 外卖占比（口径可追溯） |
| `kb_retrieve` | `agent.knowledge` | 本地 TF-IDF 检索（0 API） |
| `list_analyses` / `add_analysis` | `agent.analysis_store` | 跨会话历史分析 |
| `rule_based_interpret` | `agent.agent` | 规则解读（LLM 全挂兜底） |
| `geocode` | `agent.agent` | 地址→坐标 |

**白名单不是为了拦用户，是为了让"专家"有可验证差异**：
谈判教练不调 `analyze_storefront`、门头审核员不调 `diagnose_existing_store`。
评委会问"这和换个人设有什么区别"——`tools` 差异是能**测出来**的回答。

---

## 六、组合式 prompt 规则（最容易被做砸的地方）

**最终 prompt 必须这样拼，禁止复制粘贴：**

```
system = _common.md 的公共铁律（1 份，所有专家继承）
       + 该专家的 persona 正文（各自增量职责）
       + 该专家允许的工具产出的证据包
       + （可选）kb_retrieve 结果
```

**为什么不能各抄一份**：`interpret_node` 现有 9 条铁律若被复制 9 份 →
① 改一次要改 9 处 → 必然漏 → 9 个专家行为不一致；
② 测试无法写（难道每个专家各测一遍铁律？）。

**唯一一处定义**：`_common.md`。专家 md 只写"我比公共铁律多做什么"。

> ⚠️ **P1 拆分已完成，回归对比通过**：拆分前先跑了全量离线门禁留基线
> （`_baseline_before_split.txt`），拆完再跑一次对比（`_after_split.txt`），
> 两次均 12/12 全绿且结果一致 —— 语义未漂移。
> ⇒ 结论：**先留基线再改 prompt，是唯一能证明"没改坏"的办法**。

---

## 七、公共铁律（`_common.md`）与专家增量的分工

`_common.md` 承载**所有专家都成立**的 **13 条铁律**（见该文件）。专家文件里**不重复**，
只写：我的角色、我读哪些字段、我输出什么、我禁止什么、我缺前提时说什么。

举一个"增量"的正确写法（租金谈判教练）：

```
我的增量职责：
- 只解读 `negotiation_brief` 产出的一份证据包；
- 必须把"可承受月租上限"明确说成**天花板**、不是开价；
- 开价用"报价 − 天花板"的**差额**去锚，绝不自己编一个"合理开价"；
- 必须原样转达证据包的"可比性声明"。
公共铁律里已经有的（数字不许编、必须报口径、必须附局限）我不再重复。
```

---

## 八、诚实标注（设计稿自身的局限，必须与方案一同呈现）

1. **`kb_tags` 已生效，但分区过滤是"全库算分 → 排序后过滤"。**
   **刻意不按分区另建索引**：TF-IDF 的 IDF 依赖文档集大小，按分区建索引会让
   每个专家的得分尺度漂移，而 `min_score=0.11` 是在**全局分布**上标定的
   （间隙仅 ~0.02 宽）。
   ⇒ 代价：**分区内命中数可能少于 `top_k`** —— 这是刻意的，
   宁可少给，也不跨区混入（那正是"审计师被喂《奶茶店选址要点》"的老问题）。
   回归直接锁这个设计：断言分区结果是全库结果的**子集**且**分数不变**
   （若改成按分区建索引，这条必挂）。

2. **创业政策顾问已解 blocked（语料 12 条，逐条带法规/文号/机构来源）。**
   但**仍有 4 个方向未覆盖**（健康证、注册主体选择、所得税、消防验收）——
   语料里对此**明说"暂未收录"**，不编。范围刻意收窄到
   **证照流程骨架 + 法定前置条件 + 申请渠道/条件**，**不含具体补贴金额**
   （区县口径不同，慈溪/鄞州/北仑各不一样，写一个数就是错的）。

3. **`assertions` 覆盖"结构 + 确定性输出"，不覆盖语气。**
   能断言"谈判教练不调 `score_site`""门头审核员不调 `solve_rent_limits`"
   "经营测算输出不含『预估月流水』""铁律不被复制成 9 份"；
   **不能**断言"话说得像人话"。后者仍需人工抽查（与
   `docs/专家系统方案评估.md` §八.3 一致）。
   ⚠️ **对 LLM 自由文本的断言不得锁定措辞**（项目纪律：那类套件天然 flaky）——
   针对 LLM 输出的两条断言放在 `verify_experts.py` §7，需显式开
   `VERIFY_EXPERTS_LLM=1` 才跑，**不进离线门禁**。

4. **落地范围**：`registry.py` / `AgentState.expert` / Chainlit 选择器 /
   铁律拆分 / kb 分区 / 经营测算节点 / `verify_experts.py` **均已完成**。
   `validate_design.py` 不参与运行时、不改任何链路，跑法见第九节。
   ⚠️ 但"专家系统完成"仅指**接线完成**；每位专家的话术质量仍需人工抽查。

5. **专家数量 9 不是"越多越好"。** P2 断言成本随专家数线性增长；
   只要每个专家都有"别处没有"的东西（见 4.1 唯一性列）就不算稀释。
   若某个专家的唯一性列写不出硬差异，应合并而不是硬凑。

---

## 九、校验与回归（怎么跑、抓到过什么）

**开发期设计校验**（结构自洽，不参与运行时）：

```powershell
$env:PYTHONPATH="<项目>\.pylibs"; $env:PYTHONIOENCODING="utf-8"
C:\Python314\python.exe src\experts\validate_design.py    # 退出码 1 = 校验未过
```

它做的事：解析 9 份 frontmatter → 校验必填字段 / id 与文件名一致 / id 集合与预期清单相等 /
`tools`·`forbids` ⊆ 词汇表 / `requires` 非空则 `fallback` 非空 / group 与 status 合法
→ 打印逐个摘要与失败清单。**校验规则从 `registry.py` import，不重复定义**（两份规则必然漂移）。

**专家层回归**（进离线门禁）：

```powershell
$env:PYTHONPATH="<项目>\.pylibs"; $env:PYTHONIOENCODING="utf-8"
C:\Python314\python.exe src\analysis\verify_experts.py    # 51 项，rc=1 = 未过
# 可选：加跑真实 LLM 断言（网络依赖，不计门禁）
$env:VERIFY_EXPERTS_LLM="1"; C:\Python314\python.exe src\analysis\verify_experts.py
```

`verify_experts.py` 分七节：§1 注册表纪律 / §2 专家可验证差异 / §3 铁律单源
（含**编号重复哨兵**）/ §4 kb 分区一致性 / §5 三个互斥起点 / §6 已开店诊断接线 /
§7 LLM 信息性（默认跳过）。已纳入 `run_regression.py` 的**离线门禁组**。

**这些校验已经抓过 4 个真问题**（都已修）：

| # | 问题 | 为什么肉眼看不出来 |
|---|---|---|
| 1 | `franchise_advisor.md` 的 `fallback` 以反引号开头 → **YAML 非法** | 正文里的反引号是 markdown 代码标记，写进裸标量就崩；9 份 md 里只有这一处 |
| 2 | 校验规则本身把 `requires: []`（零依赖）误判为"缺必填" | 规则 bug，不是数据 bug —— 说明"规则也要被验证" |
| 3 | `_common.md` 铁律条目**编号重复**（11 被写成第二个 10） | 13 条里的编号断点，人工通读极易滑过；机器比对 `[1..13]` 一眼抓出 |
| 4 | 已开店诊断**会被"我有个店"抢进品类反推** | `_wants_shop_first` 与 `_wants_diagnose` 关键词重叠，靠**判定顺序**解决；用 6 条正反例锁死 |

**已知未覆盖**（诚实标注）：
- `output_contract` / `assertions` 的**文本内容**质量无法机器判定（只校验存在性 + 关键差异项）；
- 校验通过 ≠ 设计正确，只说明**结构自洽 + 确定性输出正确**。
