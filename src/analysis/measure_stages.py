"""measure_stages.py —— §4 第 0 步：拿**真实**阶段耗时分布（不是按代码常数推断）

背景：方案里那份"耗时排序"全是按 timeout 常数推的。凭推断优化，很可能把力气
花在占比 3% 的那一环。所以先装表（`_Stage` → `hooks['stage_ms']`），跑真实链路，
拿到分布再决定动哪里。

本脚本做两件事：
  [A] 走一遍**完整品类优先流程**（高德 + 58 + 本地 POI + 火山方舟 LLM），
      逐轮打印 `hooks['stage_ms']`，并给出全流程汇总。
  [B] 单独测**工作台渲染**（地图瓦片 + PDF）—— 这两项在 UI 侧（3.12+Chainlit），
      不在 graph 的 stage_ms 账上，只能另测。

⚠️ 本脚本**依赖网络**（高德/58/火山方舟），天生 flaky → **不进离线门禁**。
   它的产出是"分布证据"，不是通过/失败断言（除了一条：stage_ms 必须非空，
   否则说明埋点被改坏了、优化将重新回到"凭感觉"）。

用法：
    C:\\Python314\\python.exe src/analysis/measure_stages.py       ← [A] 图流程
    C:\\Python312\\python.exe src/analysis/measure_stages.py --ui  ← [B] 工作台渲染
输出：src/analysis/_stage_measure.txt
"""
import asyncio
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = HERE.parent.parent.parent
sys.path.insert(0, str(ROOT / 'src'))
sys.stdout.reconfigure(errors='replace')

OUT = HERE.parent / '_stage_measure.txt'
L = []


def p(s=''):
    print(s)
    L.append(str(s))


# --------------------------------------------------------------- [A] 图流程
TURNS = [
    '我想在宁波天一广场附近开一家奶茶店',   # no_shop → 列出候选 → select_shop
    '选1',                                   # select_shop → 奶茶先问品牌 → collect_brand
    '蜜雪冰城',                              # collect_brand → 问预算 → collect_invest
    '装修预算 20 万，2 个人，面积 30 平，月租 12000',   # collect_invest → analyze → interpret
]


async def run_graph():
    from agent.agent_graph import run_agent

    p('=' * 74)
    p('[A] 完整品类优先流程 —— 真实 stage_ms')
    p('=' * 74)
    p(f'场景：{TURNS[0]}  →  逐步补 面积/租金/投资/人力/品牌')
    p('')

    state = None
    # ⚠️ hooks 必须**跨轮复用**：`run_agent` 每次调用都会 `hooks = hooks or {}`，
    # 不传就每轮一本新账 → 拿到的是"最后一轮"的快照，看不到整段会话的分布。
    # （这也是改造前 `state['hooks']` 跑完就消失的原因：它被 pop 掉了。）
    hooks = {}
    for i, msg in enumerate(TURNS, 1):
        t0 = time.perf_counter()
        state = await run_agent(msg, state, hooks)
        wall = time.perf_counter() - t0
        sr = state.get('score_result') or {}
        p(f'--- 轮{i}（{wall:.1f}s 墙钟）用户：{msg}')
        p(f'    phase={state.get("phase")} | brand={state.get("brand")} '
          f'| 地址评分={sr.get("total")} '
          f'| 经营评分={(sr.get("经营评分") or {}).get("分数")}')
        # 打印助手回了什么：流程卡住时能立刻看出它在等哪种输入（自诊断）
        _rep = (state['messages'][-1].get('content') or '').replace('\n', ' / ')
        p(f'    助手（{len(_rep)} 字）：{_rep[:150]}')
        _ms = dict(hooks.get('stage_ms') or {})
        if _ms:
            p('    本轮阶段：' + '、'.join(
                f'{k} {v}ms' for k, v in sorted(_ms.items(), key=lambda x: -x[1])))
        seen = set()
        for s in state.get('steps', []):
            nm = s.get('name') or ''
            if '阶段耗时' in nm:
                seen.add(nm)
        if not seen:
            p('    ·（本轮未产生阶段汇总事件）')
        state['steps'] = []

    # 优先用结果里**持久化**的那份（§4 收尾新增 result['stage_ms']）。
    # 改造前只能从 steps 文本里抠事件，既脆又拿不到"本轮没发汇总事件"的那些阶段。
    ms = dict((state or {}).get('stage_ms') or {})
    if not ms:
        ms = dict(hooks.get('stage_ms') or {})
    p('')
    p('=== 全流程阶段耗时（跨轮累加）===')
    if not ms:
        p('  ❌ stage_ms 为空 —— 埋点被改坏了，优化会重新回到"凭感觉"')
    tot = sum(ms.values())
    for k, v in sorted(ms.items(), key=lambda x: -x[1]):
        p(f'  {v:8d} ms  ({v / tot * 100 if tot else 0:5.1f}%)  {k}')
    p(f'  {tot:8d} ms  合计')
    p('')
    p(f'[判定] stage_ms 已落账：{"是" if ms else "否"}  →  '
      f'{"埋点有效，后续可按此分布靶向优化" if ms else "埋点失效，需先修"}')

    # 把完整结果落盘，供 [B] 复用（避免重复跑 LLM）
    try:
        (HERE.parent / '_stage_state.json').write_text(
            json.dumps(sr, ensure_ascii=False, default=str), encoding='utf-8')
        p(f'[落盘] 评分结果 → src/analysis/_stage_state.json（供 --ui 复用）')
    except Exception as e:
        p(f'[落盘失败] {e}')
    return bool(ms)


# --------------------------------------------------------------- [B] 工作台渲染
def run_ui():
    """地图瓦片 + PDF 的耗时（UI 侧，只有 3.12 + Chainlit 环境能跑）。"""
    # `report_pdf` 是 src/ui 下的**顶层模块**（app_chainlit 靠 src/ui 在 sys.path 上
    # 才能 `from report_pdf import ...`）。这里必须补上该目录，否则报
    # "No module named 'report_pdf'" —— 那是测脚本的环境问题，不是 PDF 坏了。
    sys.path.insert(0, str(ROOT / 'src' / 'ui'))
    p('=' * 74)
    p('[B] 工作台渲染耗时（地图瓦片 / PDF）')
    p('=' * 74)
    sp = HERE.parent / '_stage_state.json'
    if sp.exists():
        result = json.loads(sp.read_text(encoding='utf-8'))
        p(f'  复用 src/analysis/_stage_state.json（{result.get("name")}）')
    else:
        result = {'name': '天一广场测试点', 'category': '奶茶',
                  'lng': 121.5506, 'lat': 29.8745, 'total': 80,
                  'dims': {}, 'verdict': '谨慎推荐', 'warnings': []}
        p('  未找到 _stage_state.json → 用内置测试点（121.5506, 29.8745）')

    import asyncio as _aio

    from ui.app_chainlit import _analysis_pdf, _build_shop_map_png  # noqa

    def _map(rslt, tag):
        t0 = time.perf_counter()
        png = _build_shop_map_png(rslt)
        d = (time.perf_counter() - t0) * 1000
        p(f'  地图瓦片（{tag}）→ {d:8.0f} ms  （{len(png) if png else 0} bytes）')
        return d

    # 关键：**必须区分"瓦片已缓存"与"新位置首次"** —— 两者差一个量级。
    # 方案里排第 3 位的"地图新位置可能数秒~数十秒"说的就是冷的那次。
    t_warm = _map(result, '当前坐标·瓦片可能已缓存')
    shifted = dict(result)
    if result.get('lng') is not None:
        shifted['lng'] = result['lng'] + 0.02    # 偏移一点，命中全新瓦片
        shifted['lat'] = result['lat'] + 0.02
    t_cold = _map(shifted, '偏移后的新坐标·冷瓦片')

    # PDF：先测"无缓存生成"，再测"落盘复用"（§4 第 6 项就是为了消掉前者）
    t0 = time.perf_counter()
    try:
        pdf = _aio.run(_analysis_pdf(result, '口径与区间说明……'))
        t_pdf = (time.perf_counter() - t0) * 1000
        p(f'  PDF 生成（无 conv_id·不落盘）→ {t_pdf:8.0f} ms  '
          f'（{len(pdf) if pdf else 0} bytes）')
    except Exception as e:
        t_pdf = None
        p(f'  PDF 生成 → 失败：{e}')

    try:
        _aio.run(_analysis_pdf(result, '口径与区间说明……', 'measure_probe'))
        t0 = time.perf_counter()
        _aio.run(_analysis_pdf(result, '口径与区间说明……', 'measure_probe'))
        t_hit = (time.perf_counter() - t0) * 1000
        p(f'  PDF 落盘复用（同 conv_id 第二次）→ {t_hit:8.0f} ms')
    except Exception as e:
        t_hit = None
        p(f'  PDF 落盘复用 → 失败：{e}')

    p('')
    p(f'[合计] 冷渲染 {((t_cold or 0) + (t_pdf or 0)) / 1000:.2f}s'
      f' ｜ 暖渲染 {((t_warm or 0) + (t_pdf or 0)) / 1000:.2f}s'
      f' ｜ 复用后 {((t_warm or 0) + (t_hit or 0)) / 1000:.2f}s')
    p('（这部分不在 graph 的 stage_ms 上 —— 它在 UI 侧，只能在此测）')
    return True


def main():
    if '--ui' in sys.argv:
        ok = run_ui()
    else:
        ok = asyncio.run(run_graph())
    OUT.write_text('\n'.join(L), encoding='utf-8')
    print(f'\n[写入] {OUT}')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
