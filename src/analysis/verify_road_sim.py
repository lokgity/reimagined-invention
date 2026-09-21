# -*- coding: utf-8 -*-
"""verify_road_sim.py —— 仿真数据看板（小人沿马路走）门禁
================================================================================
两段：
  A. **静态接线** —— 防"代码写了但没接上"（本项目第一高发错：同一件事几处表面）
  B. **实算对拍** —— 防"接上了但算错/口径不一致"

为什么单独立一套门禁：仿真看板横跨
  引擎(`engine/road_sim.py`) → 数据(`data/road_path.py`) → 接口(`ui/app_chainlit.py`)
  → 前端(`public/sidebar.js`)
四处，任何一处断层都**不会让别的门禁变红**（它们各自只看自己那一层）。
"""
import io
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / 'src'))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

FAIL = []


def check(name, ok, extra=''):
    print(('  [PASS] ' if ok else '  [FAIL] ') + name + (('  ← ' + str(extra)) if extra and not ok else ''))
    if not ok:
        FAIL.append(name)


def read(rel):
    return io.open(ROOT / rel, encoding='utf-8', errors='ignore').read()


def strip_comments(t, kind):
    if kind == 'js':
        t = re.sub(r'/\*.*?\*/', '', t, flags=re.S)
        t = re.sub(r'^\s*//.*$', '', t, flags=re.M)
    else:
        t = re.sub(r'^\s*#.*$', '', t, flags=re.M)
        t = re.sub(r'"""[\s\S]*?"""', '', t)
    return t


print('=' * 74)
print('§1 静态接线')
print('=' * 74)
APP = strip_comments(read('src/ui/app_chainlit.py'), 'py')
JS = strip_comments(read('public/sidebar.js'), 'js')
SIM = strip_comments(read('src/engine/road_sim.py'), 'py')
PATH = strip_comments(read('src/data/road_path.py'), 'py')

check('app_chainlit 导入 road_sim', 'from engine import road_sim' in APP)
check('app_chainlit 导入引擎 query_pois（地图选点口径）',
      'query_pois' in APP.split('def ')[0] or 'query_pois' in APP)
check("dashboard payload 带 'sim' 键", "'sim': sim," in APP or "'sim': sim" in APP)
check('仿真块异常会被兜住（不拖垮整张工作台）',
      "sim = {'ok': False" in APP and '仿真块构造失败' in APP)
check('地图几何参数来自 road_sim.map_geometry（不再各自算一遍）',
      'road_sim.map_geometry(' in APP)
check('地图 PNG 不再用直线口径选点（query_within 已让位给 query_pois）',
      'query_within(category, lng, lat, radius)' not in APP
      and 'def _road_pois' in APP)

check('sidebar.js 有 simOverlay()', 'function simOverlay' in JS)
check('sidebar.js 有 simMeta()', 'function simMeta' in JS)
check('侧栏把 sim 挂进地图块', 'simOverlay(d.sim)' in JS and 'simMeta(d.sim)' in JS)
check('覆盖层容器 zr-simstage（投影对齐用）', 'zr-simstage' in JS)
check('小人用 animateMotion 沿**折线**走（不是直线位移）',
      'animateMotion' in JS and 'path="' in JS)
check('仿真倍速显式声明并在画面标注',
      'SIM_SPEED = 8' in JS and '仿真倍速' in JS)
check('字体缩放层已同步新元素（漏进去=放大字体时它不变大）',
      '.zr-chip{font-size:calc(12px * var(--zl-fs));}' in JS)

# ---------------------------------------------------------------------------
# §1b 入口可触达（2026-09-21 补）
#
# 教训：实机探针 21/21 通过 **≠ 用户点得到**。
# 当时看板本身完全正确，但它只是右栏 analysis 的一个 section，
# 而 dashboard.json 一开新会话就被服务端 clear_dashboard() 写成 {'kind':'clear'}，
# section 随之消失 ⇒ 用户在新会话里**没有任何入口**能打开它。
# 实机探针是在"刚跑完分析"的同一会话里验的，所以这条断层它一条都挡不住。
# 因此补一组静态断言，盯的是"入口存在 + 快照生命周期与右栏解耦"。
# ---------------------------------------------------------------------------
print()
print('=' * 74)
print('§1b 入口可触达（用户手够得着，不只是算得对）')
print('=' * 74)

check('服务端定义了独立快照文件 last_sim.json',
      "LAST_SIM_FILE = ROOT / 'public' / 'last_sim.json'" in APP)
check('服务端有 write_last_sim()', 'def write_last_sim(' in APP)
# 2026-09-21：落盘条件从"sim ok"放宽为"**board 或 sim 任一 ok**"
# （board = 自绘大屏场景，是现在的主场景；sim = 右栏那块热力图的轨迹叠加，保留兼容）
check('快照只在场景 ok 时落盘（不留空入口）',
      "_bok = isinstance(board, dict) and board.get('ok')" in APP
      and 'if not _bok and not (isinstance(sim, dict) and sim.get(\'ok\')):' in APP)
check('快照带 来源会话 id（红线 4：外部数据带来源）',
      "cl.user_session.get('id')" in APP and "'来源会话'" in APP)
check('快照带 取证时间', "'取证时间'" in APP)
check('快照带 铺位经纬度 + 半径',
      "'lng': result.get('lng')" in APP and "'lat': result.get('lat')" in APP
      and "'半径m'" in APP)
# clear_dashboard 的函数体（注释已剥掉，故只看**真代码**里有没有动快照）
_seg = APP.split('def clear_dashboard():')[-1].split('def write_last_sim(')[0]
check('clear_dashboard() 不碰 last_sim.json（快照生命周期与右栏解耦）',
      'last_sim' not in _seg and "{'kind': 'clear'}" in _seg, _seg.strip()[:80])
check('analysis 面板的两处调用已切到带快照的包装函数',
      APP.count('build_analysis_dashboard_with_sim(result, map_b64)') >= 2,
      APP.count('build_analysis_dashboard_with_sim(result, map_b64)'))
check('包装函数仍然调用纯函数（不破坏纯函数可测性）',
      'payload = build_analysis_dashboard(result, map_b64)' in APP)

check('快速操作组里有 data-cmd="simboard" 按钮',
      'data-cmd="simboard"' in JS and '仿真看板' in JS)
check('无快照时按钮 disabled（不静默：点了没反应最糟）',
      'data-cmd="simboard" id="zl-simboard"' in JS
      or re.search(r'data-cmd="simboard"[^>]*disabled|class="zl-btn disabled"[^>]*data-cmd="simboard"', JS))
check('无快照时有 title 说明"先跑一次选址分析"',
      '先跑一次选址分析' in JS)
check('按钮点击有兜底提示（轮询未到位时也不静默）',
      'function simBoardUnavailable' in JS and "cmd === 'simboard'" in JS)
check('看板页复用右栏同一套渲染（不另写一份，防两处渲染分叉）',
      'function simBoardHTML' in JS
      and 'simOverlay(sim)' in JS and 'simMeta(sim)' in JS)
check('前端轮询 last_sim.json（独立于 dashboard.json）',
      "'/public/last_sim.json'" in JS)
check('openPage 支持 simboard 分支', "kind === 'simboard'" in JS)

# ---------------------------------------------------------------------------
# §1c 仿真大屏「自绘」（2026-09-21 重做）
#
# 策两次强调的原始需求：**自己生成新地图**（不是叠高德底图）、简化掉建筑、
# 只留开店的店铺 / 竞品店铺 / 人流来源，小人从来源沿马路走进店里、**一直动态**。
# 第一版做成"底图 + 一条单程轨迹"，被直接否掉（"和把右侧地图热力图搬过来有什么区别"）。
# 这一组断言就是钉住"自绘 + 持续动画 + 客流权重 + 竞品分流"四件事。
# ---------------------------------------------------------------------------
print()
print('=' * 74)
print('§1c 仿真大屏：自绘场景 + 持续动态')
print('=' * 74)
SIM_SRC = strip_comments(read('src/engine/road_sim.py'), 'py') + SIM

check('服务端有 build_board()（自绘大屏场景）', 'def build_board(' in SIM_SRC)
check('客流权重取自 profile.target_pois[].weight（引擎算 D 的同一套，不是编的）',
      "t.get('weight')" in SIM_SRC and "'w': w" in SIM_SRC)
check('竞品店铺来自 query_pois（与 Huff 分母同一批）',
      "query_pois(category, lng, lat, radius)" in SIM_SRC)
check('分流用 Huff 引力（与引擎同 λ/d0 常量）',
      'from engine.scoring import LAMBDA, D0' in SIM_SRC
      and '((road_m + D0) ** LAMBDA)' in SIM_SRC)
check('取不到折线的流向**不留假轨迹**（降级单独计数）',
      "'直线回退': pts is None" in SIM_SRC and "path_stat['降级']" in SIM_SRC)
check('明确标注"只做可视化、不参与 D/P 计算"',
      '不参与 D/P 计算' in SIM_SRC)

# ---- 2026-09-21 策实测抓到的两个错，各钉一条 ----
# ① HUD「到本铺」显示 >100%：原实现把各来源的 share **相加**，而 share 是
#    每个来源**内部**归一化的（每个来源 Σshare=1）⇒ 4 来源各 30% 就是 120%。
#    必须按**来源客流权重加权**，且必须在**裁剪之前**算（裁剪只决定画什么）。
check('「到本铺比例」按来源客流权重加权（不是 Σshare，防 >100%）',
      "_ss = {f['si']: f['share'] for f in flows if f['si_kind'] == 'store'}" in SIM_SRC
      and "sum(fig_by_src[i] * _ss.get(i, 0.0) for i in range(len(sources))) / _tf"
      in SIM_SRC)
check('「到本铺比例」在裁剪之前计算（裁剪不得影响统计）',
      SIM_SRC.index('to_store = sum(fig_by_src')
      < SIM_SRC.index('by_src = {}'))
check('前端 HUD 读的是服务端加权值，不是自己 Σshare',
      "meta['到本铺比例']" in JS
      and "reduce(function (a, f) { return a + (f.share || 0); }, 0)" not in JS)
# ② 有些竞品店铺**一条路都没有**：裁剪只留每来源 top3，某家店可能在所有来源里都排不上。
check('每个店铺至少有一条路连过去（裁剪后逐店兜底）',
      'if not any(id(f) in keep for f in fs):' in SIM_SRC
      and 'best = max(fs, key=lambda f: fig_by_src[f[\'si\']] * f[\'share\'])' in SIM_SRC)
check('分流口径与引擎 P 明确区分（不许混着讲）',
      '不是引擎的捕获份额 P' in SIM_SRC)

check('前端有 simBoardScene()（自绘渲染）', 'function simBoardScene' in JS)
check('前端有 sbxPerson()，用 animateMotion 沿折线走',
      'function sbxPerson' in JS and 'animateMotion' in JS)
check('小人是**循环**动画（repeatCount=indefinite ⇒ 一直动，不是播一次就停）',
      "repeatCount=\"indefinite\"" in JS)
check('小人走到终点淡出（进店效果）',
      'attributeName="opacity"' in JS and 'values="0;1;1;0"' in JS)
check('大屏**不再依赖高德底图**（自绘）',
      '.sbx-canvas' in JS and 'sbx-canvas" viewBox' in JS)
check('视图框按内容自适应（否则节点全挤在中心/牌子被裁）',
      'function bbox(' in JS and 'var bb0 = bbox(' in JS)
# 2026-09-21 11:05 第三版：**先定横向视口、再把地理坐标映射进去**
#   （前两版都在"内容尺度"里打转：跨度小就整体缩小、两侧留白，策连提两次）
check('先定**横向视口**（1560×975）再映射地理坐标',
      'VIEWW = 1560' in JS and 'VIEWH = 975' in JS and 'VIEWW / 2' in JS)
check('地理坐标**等比**映射（等比 ⇒ 形状不失真）',
      'function T(p)' in JS and '* S + VIEWW / 2' in JS)
check('牌子**环绕**在横向椭圆上（把版面撑满）',
      'RA = VIEWW *' in JS and 'RB = VIEWH *' in JS and 'Math.cos(ang)' in JS)
check('牌子保序铺开（保序 ⇒ 引线不交叉）',
      'items.sort(function (p, q) { return p.a - q.a; })' in JS)
check('牌子用引线连回真实位置（挪了位置但指向仍准）',
      'function leader(' in JS and 'function anchorDot(' in JS)
check('大屏按容器真实宽高比二次贴合（否则 letterbox 出空白）',
      'function sbxFit' in JS and "setAttribute('viewBox'" in JS)
check('大屏页撑满子页面（flex 列 + SVG 吃掉剩余高度）',
      'zl-pg-sim' in JS and 'flex:1 1 auto' in JS)
check('字号乘了跨度系数 --sbx-k（否则牌缩了字没缩、文字溢出牌面）',
      '--sbx-k:' in JS and 'var(--zl-fs) * var(--sbx-k,1)' in JS)
check('右栏那块不再叫「仿真看板」（避免与自绘大屏混淆）',
      '周边热力图 · 客流轨迹' in JS and '周边热力图 · 仿真看板' not in JS)

# ---------------------------------------------------------------------------
# §1d 「先挑哪一次，再看内容」的卡片页（2026-09-21 15:33 策要求）
#   与「对比分析」同一份 analyses.json，两处列表顺序必须一致。
# ---------------------------------------------------------------------------
print()
print('=' * 74)
print('§1d 仿真大屏：先挑分析、再看内容')
print('=' * 74)
STORE = strip_comments(read('src/agent/analysis_store.py'), 'py')

check('analysis_store 有 save_board / load_board / list_board_ids',
      'def save_board(' in STORE and 'def load_board(' in STORE
      and 'def list_board_ids(' in STORE)
check('快照存到 public/ 下（前端要 fetch，不在 data/）',
      "DATA_DIR.parent / 'public' / 'sim_boards'" in STORE)
check('没有 analysis_id 就不落盘（对不上列表的快照没意义）',
      "if not analysis_id:" in STORE)
check('add_analysis **把 id 回写进 result**（UI 层才知道存哪一份）',
      "result['analysis_id'] = entry['id']" in STORE)
check('UI 层按 analysis_id 落盘 + 写进 payload',
      'save_board(result.get(\'analysis_id\'), payload)' in APP
      and "'analysis_id': result.get('analysis_id', '')" in APP)
check('sidebar.json 带 sim_list（复用 analyses.json，与对比分析同源）',
      "'sim_list': _sim_index()" in APP and 'def _sim_index(' in APP
      and 'list_board_ids()' in APP)
check('sim_list 键名不与「分析数(int)」的 analyses 撞车',
      "'analyses': _history_stats()" in APP)

check('前端有卡片页 simPickHTML() 与 loadSimBoard()',
      'function simPickHTML' in JS and 'function loadSimBoard' in JS)
check('卡片带 data-simboard，可点即取那一次的快照',
      'data-simboard=' in JS and "'/public/sim_boards/'" in JS)
# ⚠️ 这条是 2026-09-21 实测踩的坑：卡片点击处理曾写在 `if (cmdBtn)` **里面**，
#    而卡片不是 [data-cmd] ⇒ 永远不命中，点卡片毫无反应、连请求都不发。
#    **用顺序表达**（消费方不变式），不要用字面查。
check('卡片点击处理在 `if (cmdBtn)` **之外**（否则永远不命中）',
      JS.index("var sbPick = ev.target.closest('[data-simboard]')")
      < JS.index("var cmdBtn = ev.target.closest('[data-cmd]')"))
check('点左栏按钮**总是先回到卡片列表**（每次让用户重新挑）',
      'simPicked = null;' in JS and 'bodyEl.innerHTML = simPickHTML();' in JS)
check('大屏上有「← 换个分析」返回入口',
      'zl-sim-back' in JS and 'sbx-back' in JS)
check('卡片页元素进了字体缩放层',
      '.sbx-card .sbx-c-shop{font-size:calc(' in JS)
check('看板页新元素已纳入字体缩放层',
      "#zl-page-ov .zl-simsrc .zl-kb-tb{font-size:calc(13.5px * var(--zl-fs));}" in JS
      and "#zl-page-ov .zl-kb-note{font-size:calc(13.5px * var(--zl-fs));}" in JS
      and "#zl-page-ov .zr-legend{font-size:calc(12.5px * var(--zl-fs));}" in JS)

print()
print('=' * 74)
print('§2 数据侧的纪律（不猜 / 不静默）')
print('=' * 74)
check('路径接口 status != 1 明确抛错（不返回空折线冒充"路是直的"）',
      "raise RuntimeError" in PATH and "status=%s" in PATH)
check('路径是**有向**存储（步行单行道）', 'PRIMARY KEY(olng, olat, dlng, dlat)' in PATH)
check('路径冻结库带取证时间', 'fetched_at' in PATH)
check('5km 射程常量与 road.py 一致', 'WALK_MAX_M = 5000' in PATH)

print()
print('=' * 74)
print('§3 实算对拍（天一广场，真跑一遍）')
print('=' * 74)
from config import get_profile              # noqa: E402
from data import road, road_path            # noqa: E402
from engine.road_sim import build_sim, map_geometry   # noqa: E402

LNG, LAT = 121.551902, 29.869684
prof = get_profile('奶茶')
radius = prof.get('radius', 500)
geo = map_geometry(LAT, LNG, radius)
before_calls = road_path.calls()['n']
doc = build_sim('奶茶', LNG, LAT, radius, profile=prof, limit=6, geo=geo)

check('build_sim 返回 ok', doc.get('ok') is True, doc.get('原因'))
tg = doc.get('targets') or []
check('取到 ≥4 个候客群点', len(tg) >= 4, len(tg))

W = geo['img_w']
withpath = [t for t in tg if len(t.get('path_px') or []) > 1]
check('≥4 条真实道路折线', len(withpath) >= 4, len(withpath))

inside = all(0 <= x <= W and 0 <= y <= W
             for t in withpath for x, y in t['path_px'])
check('所有折点落在地图图幅内（投影与地图同源）', inside)
sx, sy = doc.get('store_px') or (None, None)
check('本铺像素坐标在图幅内', sx is not None and 0 <= sx <= W and 0 <= sy <= W,
      (sx, sy))

# 折点顺序必须与"走向本铺"一致：末端应贴近本铺像素
near_end = []
for t in withpath:
    ex, ey = t['path_px'][-1]
    near_end.append(((ex - sx) ** 2 + (ey - sy) ** 2) ** 0.5)
check('折线末端都收敛到本铺附近（小人确实是"走向本铺"）',
      all(d < 40 for d in near_end), [round(d, 1) for d in near_end])

# 与冻结距离库对拍（同族接口 ⇒ 距离应逐位一致）
bad = []
for t in withpath:
    w = road.lookup((LNG, LAT), (t['lng'], t['lat']))
    if w is not None and abs(w - t['road_m']) > 2:
        bad.append((t['name'], w, t['road_m']))
check('路径接口距离 == road_distance.db 距离（容差 2m）', not bad, bad)

# 绕行倍数必须来自实测（不是常数）
ratios = sorted(t['ratio'] for t in withpath if t.get('ratio'))
check('绕行倍数逐点不同（不是被常数近似掉）',
      len(set(ratios)) >= 3, ratios)

# 0 API：重复调用必须全部命中冻结库（可离线复现）
c2 = road_path.calls()['n']
doc2 = build_sim('奶茶', LNG, LAT, radius, profile=prof, limit=6, geo=geo)
check('重复构造 0 次 API（冻结库命中 ⇒ 可离线复现）',
      road_path.calls()['n'] == c2, road_path.calls())
same = (len(withpath) == len([t for t in (doc2.get('targets') or [])
                              if len(t.get('path_px') or []) > 1]))
check('重复构造结果一致', same)

print()
print('=' * 74)
print('总览')
print('=' * 74)
print(f'  折线 {len(withpath)} 条 ｜ 折点合计 '
      f'{sum(len(t["path_px"]) for t in withpath)} 个 ｜ '
      f'路网距离 {[t["road_m"] for t in withpath]}')
print(f'  直线距离 {[t["straight_m"] for t in withpath]}')
print(f'  绕行倍数 {[t["ratio"] for t in withpath]}')
print(f'  road_path.db 累计 {road_path.stats()} 条路径 ｜ 本轮 API {before_calls} 次')
print()
if FAIL:
    print(f'✗ {len(FAIL)} 项未通过：')
    for f in FAIL:
        print('   ·', f)
    sys.exit(1)
print('✓ 仿真看板门禁全部通过')
