# -*- coding: utf-8 -*-
"""verify_ui.py —— 前端/展示层与并发改造的静态+逻辑回归（**离线门禁组成员**）
================================================================================
为什么"读源码做断言"在这里是合理做法（而不是偷懒）：
本项目的运行环境是**两个解释器**——
  · `C:\\Python312` + Chainlit 3.x 才能跑 `app_chainlit.py`（3.14 下 StaticFiles
    直接抛 `anyio.NoEventLoopError`）；
  · `C:\\Python314` 跑引擎与分析（`.pylibs` 是 cp314 轮子，3.12 里 import numpy
    会炸 `No module named 'numpy._core._multiarray_umath'`）。
离线门禁跑在 **3.14**，所以它**根本无法 import** `app_chainlit.py` 或渲染
`sidebar.js`。于是本套件分两层：

  A) **静态断言**：对 `sidebar.js` / `app_chainlit.py` / `agent_graph.py` 的源码
     文本做断言。它挡不住"逻辑写错"，但能挡住**回退**——这个项目历史上真正
     出过的事故就是"改 A 处忘了 B 处"（softHide 与 autoscroll、两处知识库表面、
     指令白名单 5 处 indexOf、改名漏掉 `config.toml` 的应用标题）。回归的价值正在
     于"把已修的坑钉住"。
  B) **逻辑断言（真跑）**：不依赖任何 UI 的纯算术（`agent/replay.py` 的回放批次）
     直接 import 真跑，断言"不重不漏"——这是最容易静默出错的一环。

覆盖：§2 历史会话一步到位+回放 · §3 PDF 置顶 · §4 计时器/并发/prompt 裁剪 ·
      §5 滚动不跳顶 · §7 双轴评分展示 · §8 欢迎语标题渐变可读性+花纹 ·
      §9 产品名一致性（旧名不得回流，**不限后缀**扫全仓 + 应用标题单独钉死）。

用法：C:\\Python314\\python.exe src/analysis/verify_ui.py
输出：同目录 _ui_report.txt
"""
import io
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / '.pylibs'))

OUT = HERE / '_ui_report.txt'
L, FAIL = [], []


def p(*a):
    s = ' '.join(str(x) for x in a)
    print(s)
    L.append(s)


def check(name, cond, detail=''):
    p(f'  {"PASS" if cond else "FAIL"}  {name}' + (f'  |  {detail}' if detail else ''))
    if not cond:
        FAIL.append(name)


def sect(t):
    p('')
    p(f'=== {t} ===')


def _read(rel):
    f = ROOT / rel
    return f.read_text(encoding='utf-8') if f.exists() else ''


def strip_comments(src, kind):
    """去掉注释后再断言 —— **这一步是必需的，不是讲究**。

    这些改造的说明性注释里会反复提到"改前的那个函数名"（例如
    `renderHistPage()`、`conv_page.json`）。如果拿带注释的原文去断言
    "该名字已不存在"，注释本身就会让断言失败；而如果为此把注释删干净，
    下一个人就再也搞不清为什么不能改回去 —— 正是本项目反复吃过的亏。
    所以：**保留注释给人看，断言跑在去注释的代码上**。
    """
    if kind == 'js':
        src = re.sub(r'/\*.*?\*/', '', src, flags=re.S)          # 块注释
        src = re.sub(r'(?m)^[ \t]*//.*$', '', src)               # 整行 //
        return src
    src = re.sub(r'(?m)^[ \t]*#.*$', '', src)                     # 整行 #
    return src


JS_RAW = _read('public/sidebar.js')
APP_RAW = _read('src/ui/app_chainlit.py')
GRAPH_RAW = _read('src/agent/agent_graph.py')

JS = strip_comments(JS_RAW, 'js')
APP = strip_comments(APP_RAW, 'py')
GRAPH = strip_comments(GRAPH_RAW, 'py')
REALTIME = strip_comments(_read('src/engine/realtime.py'), 'py')
PDF = strip_comments(_read('src/ui/report_pdf.py'), 'py')
CSS_ROLE = '[role="dialog"]{z-index:3000 !important;}'

p('verify_ui.py —— 前端/展示层与并发改造回归')
p(f'  sidebar.js {len(JS_RAW)} 字符 · app_chainlit.py {len(APP_RAW)} 字符 · '
  f'agent_graph.py {len(GRAPH_RAW)} 字符（断言均跑在**去注释**文本上）')


# ---------------------------------------------------------------- 准备
def _fn_body(src, header, maxlen=6000):
    """截取某个函数/变量的源码片段（从 header 起到下一个同级定义前）。

    片段截取是必需的：整文件里 `display` 这种词到处都是，只有限定在
    `hideCmdBubbles` 内部断言才有意义。JS 与 Python 的"下一个同级定义"
    长相不同，所以两组标记都要认 —— 只认 JS 那组的话，Python 函数片段会
    一路吃到下一个函数（例如 `_vlm_probe` 会吞掉 `analyze_node` 里的
    `apply_storefront`，于是"probe 内不调 apply_storefront"的断言会假失败）。"""
    i = src.find(header)
    if i < 0:
        return ''
    seg = src[i:i + maxlen]
    markers = ('\n  function ', '\n  var ', '\n  /* ----',   # JS
               '\n# ---', '\nasync def ', '\ndef ', '\nclass ',  # Python
               '\n# =')
    for marker in markers:
        j = seg.find(marker, len(header) + 1)
        if j > 0:
            seg = seg[:j]
    return seg


def _fn_code(src, header, maxlen=6000):
    """`_fn_body` + **去掉文档字符串**。

    为什么还要单独一步：文档字符串不是注释，上面那个 stripper 不会动它。
    而本项目的注释风格是把"为什么这么改"连同**被否定的旧写法**一起写进
    docstring（例如 `_vlm_probe` 的 docstring 里写着"统一 `apply_storefront()`"，
    那是在解释**调用方**做什么）。于是"probe 内不调 apply_storefront"这类
    **否定式断言**会被 docstring 自己打倒 —— 那不是代码错了，是断言取错了面。
    """
    seg = _fn_body(src, header, maxlen)
    return re.sub(r'(?s)""".*?"""', '', seg)


# ---------------------------------------------------------------- §5 滚动不跳顶
sect('§5 滚动：切专家/自由对话不跳回最上方')
_soft = _fn_body(JS, 'function softHide(')
check('softHide 已定义（零高度但留在文档流，不用 display:none）',
      "el.style.height = '0'" in _soft and "el.style.maxHeight = '0'" in _soft
      and "el.style.display = ''" in _soft,
      'softHide = height:0 + maxHeight:0 + overflow:hidden + opacity:0，display 保持原值')
_hcb = _fn_body(JS, 'function hideCmdBubbles(')
check('hideCmdBubbles **改用 softHide**，不再 display:none',
      'softHide(' in _hcb and "style.display = 'none'" not in _hcb
      and 'style.display=none' not in _hcb,
      "改前 display:none 会让气泡 offsetTop=0 → autoscroll scrollTo(-20) 被夹到 0 → 跳顶")
check('hideCmdBubbles 内确实**没有**任何 display:none 残留',
      "display = 'none'" not in _hcb and 'display:none' not in _hcb)
_sc_ = _fn_body(JS, 'function sendCmd(')
check('sendCmd 对静默指令 captureScroll() 记录滚动位', 'captureScroll()' in _sc_)
check('sendCmd 发出后 guardScroll(_scroll) 兜底还原（多帧重试）',
      'guardScroll(_scroll)' in _sc_)
_gs = _fn_body(JS, 'function guardScroll(')
check('guardScroll 绑多个时间点（rAF 连两帧 + 80/240/600/1000ms）',
      'raf(function () { raf(apply); })' in _gs and '[80, 240, 600, 1000]' in _gs)
check('restoreScroll 区分"原本贴底"（贴底就回到底，而非回到旧 scrollTop）',
      'bottom: (c.scrollHeight - c.scrollTop - c.clientHeight) < 48' in JS)
check('##打开: 在静默指令白名单内（点历史项也不留指令气泡）',
      "t.indexOf('##打开:') >= 0" in JS)

# ---------------------------------------------------------------- §3 PDF 置顶
sect('§3 PDF 弹层：打开时最上层、不被遮挡')
check('CSS 把 [role="dialog"] 抬到 z-index:3000 !important', CSS_ROLE in JS)
check('PDF 打开时 body.zl-pdf-open 同样抬层',
      'body.zl-pdf-open [role="dialog"]{z-index:3000 !important;}' in JS)
check('layoutBar 在 PDF 打开时让出画面（专家条不遮挡）',
      "document.body.classList.contains('zl-pdf-open')" in JS)
check('raisePdfModal 已定义（扫可见 [role="dialog"] + 对 body 打标记）',
      'function raisePdfModal(' in JS
      and "document.body.classList.toggle('zl-pdf-open', open)" in JS)
check('raisePdfModal 被 load() 每轮调用（兜底，Chainlit 是运行时插入的弹层）',
      JS.count('raisePdfModal()') >= 3, f'调用点 {JS.count("raisePdfModal()")} 处')
check('MutationObserver 监听弹层出现（不等 2.5s 轮询）',
      'new MutationObserver' in JS and 'raisePdfModal' in JS)

# ---------------------------------------------------------------- §2 历史会话
sect('§2 历史会话：去掉中间只读页 + 回放聊天内容')
_oh = _fn_body(JS, 'function openHistory(id)')
check('openHistory **直接**发 ##打开:<id>##（一步到位）',
      "sendCmd('##打开:' + id + '##')" in _oh)
check('openHistory 不再 fetch sidebar.json 去渲染覆盖层',
      "fetch('/public/sidebar.json'" not in _oh and 'renderHistPage' not in _oh)
check('renderHistPage 已彻底删除（无定义、无调用）',
      'function renderHistPage(' not in JS and 'renderHistPage(' not in JS,
      '留着会让后来人以为历史页还是覆盖层')
check('conv_page.json 轮询已删除（不再每 2.5s 一次必定 404 的请求）',
      "concat('conv_page.json')" not in JS
      and "'/public/conv_page.json'" not in JS)
check('lastConvTs 状态变量随之删除（否则是未使用变量）',
      'lastConvTs' not in JS)
check('中间页的「继续对话」CTA 已移除（只服务历史那条路径）',
      'zl-pg-cta' not in JS,
      '知识库页/专家卡片页仍用同一个 #zl-page-ov 容器')
check('知识库页 / 专家卡片页的覆盖层**保留**（只是历史不再走它）',
      "openPage('theory')" in JS and 'expertsPageHTML()' in JS
      and 'function openPage(kind)' in JS)

check('后端 process_preview_conv 已删除（与前端同步退休）',
      'def process_preview_conv' not in APP and 'process_preview_conv(' not in APP)
check('后端 _conv_page_payload 备用版一并删除',
      '_conv_page_payload' not in APP)
check('##预览: 兼容映射到 process_open_conv（老书签/老前端不报错）',
      "text.startswith('##预览:')" in APP
      and "await process_open_conv(text[len('##预览:'):].rstrip('#'))" in APP)

_re = _fn_body(APP, 'async def _replay_emit(')
check("回放用 cl.Message(type='user_message') —— 2.11 没有 cl.UserMessage 类",
      "type='user_message'" in _re)
check('回放**不经过 graph**（只 send，不写 state[\'messages\']，防重复累积）',
      '_replay_emit' in APP and "state['messages'] +" not in _re)
check('回放用户消息时不带 author（气泡样式由 type 决定）',
      "cl.Message(content=m['content'], type='user_message')" in _re)
check('「查看更早」用 cl.Action + action_callback 实现（Chainlit 原生入口）',
      "@cl.action_callback('load_earlier')" in APP and "name='load_earlier'" in APP)
check('action payload 带 conv_id（回调不依赖全局当前会话）',
      "payload={'conv_id': conv_id" in APP)
check('进度以 user_session 为准、不信 payload 快照（连点两次不重复补发）',
      "rp = cl.user_session.get('replay')" in APP
      and "cl.user_session.set('replay'" in APP)
check('批次说明如实标注"更早的记录排在下方"（Chainlit 只能追加）',
      '时间上**早于**上方内容' in APP_RAW)
check('回放纯逻辑抽到 agent/replay.py（3.14 可 import → 能被真跑回归）',
      (ROOT / 'src' / 'agent' / 'replay.py').exists()
      and 'from agent.replay import' in APP)

sect('§2/§4 PDF 落盘复用')
check('PDF 落盘缓存到 data/reports/<conv_id>.pdf',
      "'reports'" in APP and "f'{conv_id}.pdf'" in APP and 'REPORT_DIR' in APP)
check('落盘用原子写（先 .tmp 再 os.replace，防半截文件被复用）',
      'os.replace(tmp,' in APP and '.pdf.tmp' in APP)
check('分析完成时把当前 conv_id 传进 render_analysis_dashboard（才会落盘）',
      "conv_id=cl.user_session.get('conv_id')" in APP)
check('历史打开时也传 conv_id（复用而不是重新生成）',
      'render_analysis_dashboard(sr, interpretation=interp, conv_id=conv_id)' in APP)
check('process_export 也复用落盘（导出不再重跑 Playwright）',
      '_analysis_pdf(sr, interp' in APP)
check('坏文件保护：<800B 视为损坏、不复用', 'st_size > 800' in APP)

# ---------------------------------------------------------------- §4 提速
sect('§4 第 0 步：阶段计时器')
check('_Stage 计时器已定义（hooks[\'stage_ms\'] 跨节点共享）',
      'class _Stage:' in GRAPH and "hooks.setdefault('stage_ms', {})" in GRAPH)
check('analyze_node 记「评分引擎」耗时', "st.start('评分引擎')" in GRAPH)
check('analyze_node 记并发段总耗时', "st.start('看铺‖竞品(并发段)')" in GRAPH)
check('interpret_node 记 RAG 与 LLM 解读耗时',
      "st.start('RAG检索')" in GRAPH and "st.start('LLM解读')" in GRAPH)
check('LLM 解读耗时走 finally（降级到规则解读的时间也要记账）',
      'st.stop(\'LLM解读\')' in _fn_body(GRAPH, 'async def interpret_node('))
check('汇总成 ⏱ 阶段耗时 事件（前端「执行过程」面板可见）',
      '⏱ 阶段耗时' in GRAPH)

sect('§4 第 1 步：并行化（全项目此前零 asyncio.gather）')
check('VLM 与竞品挖掘并发（asyncio.create_task ×2，同一事件循环内起跑）',
      GRAPH.count('asyncio.create_task(') >= 2)
check('并发只负责取数，**合并仍串行**（防副本覆盖丢字段）',
      '_vlm_task' in GRAPH and '_cmp_task' in GRAPH
      and 'apply_storefront' not in _fn_code(GRAPH, 'async def _vlm_probe(')
      and 'result = apply_storefront(result, vlm)'
          in _fn_code(GRAPH, 'async def analyze_node('),
      'VLM 经 apply_storefront 生成**新副本**、竞品往 result 写字段；并发里各改各的，'
      '先返回的副本会把另一分支的字段整块覆盖掉，且不抛异常')
check('VLM/竞品各自"失败不影响主流程"（probe 内 try/except 全兜）',
      'return None' in _fn_code(GRAPH, 'async def _vlm_probe(')
      and 'cmp_err' in GRAPH)
check('竞品"取数失败"与"真的没有"分开（不合并成一件事）',
      "return None, str(e), str(e)" in GRAPH and 'if cmp_err is not None:' in GRAPH,
      '合并会让用户以为这个商圈没竞品，从而低估竞争')
check('9 张地图瓦片并发拉取（ThreadPoolExecutor，9 张同一批 map）',
      'ThreadPoolExecutor(max_workers=len(_cells))' in APP and '_ex.map(' in APP
      and len(re.findall(r'_cells = \[\(gx, gy\)', APP)) == 1)
check('瓦片并发安全：mkdir 单句兜 FileExistsError（Windows 窄竞争）',
      'except FileExistsError:' in APP)
check('拼图回主线程串行（PIL 对象并发 paste 不安全）',
      'im.paste(tile, (gx * 256, gy * 256))' in APP)
check('工作台渲染：地图与 PDF 并发（两个 create_task，发送仍按固定顺序）',
      'asyncio.create_task(' in _fn_body(APP, 'async def render_analysis_dashboard(')
      and 'asyncio.create_task(_analysis_pdf(' in APP
      and 'asyncio.to_thread(_build_shop_map_png' in APP)
check('渲染阶段耗时落控制台（不混进 hooks 里误导归因）',
      '[timing] 工作台渲染' in APP)

sect('§4 realtime retries 病理路径修复')
check('realtime.py 的 http_get 显式传 retries=2（默认 4 → 最坏 ~60s）',
      'retries=2' in REALTIME,
      '4×10s 超时 + 积 20s 睡眠；同项目 competitor_insight 早已降到 2')

sect('§4 prompt 裁剪')
check('interpret 的 prompt 用 _view（不再整份 json.dumps(result)）',
      'json.dumps(_view, ensure_ascii=False)' in GRAPH
      and 'json.dumps(result, ensure_ascii=False)' not in _fn_body(GRAPH, 'async def interpret_node('))
check('_slim_profit / _slim_bands 存在（三档只留月净利+回本两端）',
      'def _slim_profit(' in GRAPH and 'def _slim_bands(' in GRAPH)

# ---------------------------------------------------------------- §7 双轴评分
sect('§7 双轴评分展示（地址评分 × 经营评分，结论以经营评分为准）')
check('看板有「地址评分」卡', "'地址评分'" in APP)
check('看板有「经营评分」卡（含否决封顶标注）', "'经营评分'" in APP and '封顶' in APP)
check('看板有「经营评分区间(三档)」卡', '经营评分区间' in APP)
check('结论卡注明"以经营评分为准"', '以经营评分为准' in APP)
check('三种"没有经营评分"分开说（字段缺失 ≠ 算不出）',
      "'经营评分' not in result" in APP and '旧版本结果，请重新分析' in APP
      and 'biz.get(\'不可得原因\')' in APP,
      '实机踩到：旧版本存盘的结果没有该字段，改前也显示"不出分"，'
      '看着像"这个铺子算不出来"，其实是"这份分析早于该功能"')
check('旧结果的结论卡标注"仅地址"口径（不冒充以经营评分为准）',
      '旧版本·仅地址' in APP)
check('卡片 label 里不放 markdown 加粗（label 是纯文本渲染，会原样显示 **）',
      '**旧版本' not in APP,
      '实机截图踩到：写 `**旧版本，仅地址**` 会原样显示出星号')
check('旧结果在证据表里给出重算建议（而不是留个空白）',
      '请对同一地址重新分析一次' in APP)
check('历史页旧字段名「综合评分」已不再出现于展示层',
      "'综合评分'" not in APP)
check('PDF 双轴：否决时同时给出位置分结论与经营结论',
      '位置分：' in _read('src/ui/report_pdf.py')
      and '地址评分：' in _read('src/ui/report_pdf.py'))

# ---------------------------------------------------------------- 逻辑真跑
sect('§2 回放批次算法（真跑，不重不漏）')
try:
    from agent.replay import (REPLAY_TAIL, replayable, replay_slice,
                              next_shown, clamp_shown)

    tot, shown, cov = 20, 0, []
    for _ in range(50):
        s, e = replay_slice(tot, shown)
        if s >= e:
            break
        cov.append((s, e))
        shown = next_shown(tot, shown, s, e)
    check('多轮批次严丝合缝（本轮 end == 上轮 start）',
          all(cov[i][1] == cov[i - 1][0] for i in range(1, len(cov))), str(cov))
    flat = [i for s, e in cov for i in range(s, e)]
    check('覆盖 [0,total) 恰好一次：不重复', len(flat) == len(set(flat)) == tot,
          f'条数 {len(flat)} / 去重 {len(set(flat))} / total {tot}')
    check('确实覆盖全部下标（无漏发）', sorted(flat) == list(range(tot)))
    check('首轮 = 最近 N 条', replay_slice(20, 0) == (20 - REPLAY_TAIL, 20),
          f'{replay_slice(20, 0)}')
    check('消息数 ≤ N 时一轮发完', replay_slice(5, 0) == (0, 5))
    check('已到顶 → 空区间（调用方应提示而非发消息）', replay_slice(20, 20) == (0, 0))
    check('脏 shown（>total）被夹住，不产生负区间或 start>end',
          replay_slice(5, 8) == (0, 0) and replay_slice(5, -3) == (0, 5))
    check('clamp_shown 兜非法类型（None/字符串）',
          clamp_shown(10, None) == 0 and clamp_shown(10, '3') == 3)
    msgs = [{'role': 'user', 'content': '你好'},
            {'role': 'assistant', 'content': ''},
            {'role': 'assistant', 'content': None},
            {'role': 'assistant', 'content': '  分析完成  '},
            {'content': '无 role 也算助手'}]
    rp = replayable(msgs)
    check('replayable 过滤空正文（空气泡会让用户以为记录丢了）',
          len(rp) == 3 and all(m['content'].strip() for m in rp), str(rp))
    check('replayable 对缺 role 的消息回落 assistant（不崩）',
          rp[1]['role'] == 'assistant')
    check('replayable 去首尾空白', rp[1]['content'] == '分析完成')
    check('replayable 容忍 None / 空列表', replayable(None) == [] and replayable([]) == [])
except Exception as e:
    import traceback
    check('agent/replay.py 可导入且行为正确', False, f'{type(e).__name__}: {e}')
    p(traceback.format_exc()[:800])

# ---------------------------------------------------------------- §8
sect('§8 欢迎语标题：渐变「看得出来」三要素 + 花纹（诉求⑤）')

check('pinURI() 存在：花纹 SVG 由它生成', 'function pinURI(' in JS)
check('花纹走 data-URI 内联 SVG（不往后端 welcome 文案塞 HTML —— markdown 会 sanitize）',
      'data:image/svg+xml,' in JS and 'encodeURIComponent' in JS)

_dark_at = JS.find("pinURI('#e5c98a'")
_light_at = JS.find("pinURI('#a8843c'")
check('深/浅两套花纹各生成一份（data-URI 里写不了 var()，少一份就有一边没颜色）',
      _dark_at != -1 and _light_at != -1, f'dark@{_dark_at} light@{_light_at}')
check('浅色覆盖规则排在深色之后（两条同权重，只靠源码顺序取胜）',
      0 <= _dark_at < _light_at)
check('定位针是线描（描边 + 中心实心点），不是实心填充 —— '
      '实心版在 34px 下整枚糊成一坨金圆点（实机截图抓到的）',
      "viewBox='0 0 48 48' fill='none'" in JS
      and "stroke='" in JS and "<circle cx='24' cy='21.5' r='4.4' fill='" in JS)
check('花纹颜色经 --zl-pin 下发（挂在 h1 上，伪元素继承）',
      JS.count("--zl-pin:'") == 2 and JS.count('var(--zl-pin)') == 1)
check('::before / ::after 两条规则都在，左右 margin 各归一边（不能在贴同侧）',
      'h1::before{margin-right:14px;}' in JS and 'h1::after{margin-left:14px;}' in JS)
check('花纹尺寸 34px 显式声明（配 44px 标题）', 'width:34px;height:34px;' in JS)
check('伪元素显式 background-clip:border-box（防父级 -webkit-background-clip:text 把花纹裁没）',
      'background-clip:border-box;' in JS)
check('花纹尺寸故意不进 --zl-fs 缩放层（标题字号本身不缩放，花纹进去就会两边不同步）',
      re.search(r'h1[^{}]*\{[^{}]*var\(--zl-fs\)', JS) is None)

# ---- 渐变「看得出来」三要素（2026-09-17 欧文反馈"渐变太不明显"后补）---------------
# 旧版看不见渐变是三条原因叠加，缺一条都还会犯，所以三条分开钉：
#   ① h1 是块级、撑满整行（~750px），而文字只占 ~260px → 文字只截到中间 1/3 色阶，
#      几色被压成一片，看着就是单色。修法：收缩到内容宽。
#   ② 色标全在同一金色系内（色相差极小），"明显"只能靠**明度**落差撑；旧版只 ~26。
#   ③ text-shadow 在 -webkit-text-fill-color:transparent 的字身上会从字形**内部**
#      透出来，把渐变糊平。修法：换 drop-shadow（作用在渲染结果上，不穿字身）。
check('h1 收窄到内容宽（width:fit-content）—— 缺这条，块级 h1 撑满整行，'
      '渐变只落在文字上不到 1/3 的色阶，看着就是单色',
      ';width:fit-content;' in JS)
check('深浅两套渐变都是 4 色标、100deg 起手（旧版 120deg/3 色，色阶被压缩）',
      JS.count('linear-gradient(100deg,#') == 2)
check('渐变背景只铺文字区（background-size 扣掉左右花纹各 48px）—— '
      '不扣的话色阶被花纹区吃掉近一半，文字只吃到 ~56%，依然不够明显',
      'background-size:calc(100% - 96px) 100%;background-position:48px 50%;'
      'background-repeat:no-repeat;' in JS)

_zpin = re.search(r'display:inline-block;width:(\d+)px;height:(\d+)px;vertical-align:middle;', JS)
_zmr = re.search(r'h1::before\{margin-right:(\d+)px;\}', JS)
_zml = re.search(r'h1::after\{margin-left:(\d+)px;\}', JS)
_zbg = re.search(r'background-size:calc\(100% - (\d+)px\) 100%;background-position:(\d+)px', JS)
if _zpin and _zmr and _zml and _zbg:
    _zside = int(_zpin.group(1)) + int(_zmr.group(1))      # 单侧：花纹宽 + 间距
    check(f'渐变留白与花纹几何**联动**（花纹 {_zpin.group(1)}px + 间距 {_zmr.group(1)}px 各一侧 '
          f'→ 应扣 {_zside * 2}px、起点 {_zside}px）—— 把花纹改大改小都必须同步改这两个数，'
          '否则渐变会缩到花纹底下或截断字尾',
          int(_zbg.group(1)) == _zside * 2 and int(_zbg.group(2)) == _zside,
          f'CSS 写的是 {_zbg.group(1)}/{_zbg.group(2)}，按花纹几何应为 {_zside * 2}/{_zside}')
    check('左右花纹间距对称（before 的 margin-right 与 after 的 margin-left 相等，'
          '否则渐变留白按单侧算会错位）',
          int(_zmr.group(1)) == int(_zml.group(1)),
          f'mr={_zmr.group(1)} ml={_zml.group(1)}')
else:
    check('能解析出花纹几何与渐变留白（联动断言的前提）', False,
          f'pin={bool(_zpin)} mr={bool(_zmr)} ml={bool(_zml)} bg={bool(_zbg)}')


def _zluma(hx):
    """感知亮度（近似）：只用来比较"明暗落差够不够看得出来"。"""
    _r, _g, _b = (int(hx[_k:_k + 2], 16) for _k in (1, 3, 5))
    return (_r * .299 + _g * .587 + _b * .114) / 255 * 100


_zgrads = re.findall(r'linear-gradient\(100deg,([^)]*)\)', JS)
for _zgi, _zgb in enumerate(_zgrads):
    _zcols = re.findall(r'#[0-9a-f]{6}', _zgb)
    _zspan = (max(_zluma(_c) for _c in _zcols) - min(_zluma(_c) for _c in _zcols)) if _zcols else 0
    check(f'渐变 #{_zgi + 1} 明度落差 ≥ 40（金色系色相差极小，"明显"只能靠明度：'
          f'实测 {_zspan:.1f}；旧版约 26 → 看不出）',
          len(_zcols) == 4 and _zspan >= 40, _zgb)
check('已弃用 text-shadow（transparent 字身会让阴影从字形内部透出来糊平渐变），'
      '深浅各改用一条 drop-shadow（作用在渲染结果上、不穿字身）',
      # ⚠️ 不能数全局的 filter:drop-shadow( 个数（.zv-logo 那条也有），要认 h1 这两条的
      #    具体参数值——第一版就是这么误报的。
      'text-shadow:0 6px' not in JS
      and 'filter:drop-shadow(0 3px 16px' in JS
      and 'filter:drop-shadow(0 3px 12px' in JS)

_h1_hits = []
# ⚠️ 扫描针必须**拼出来**，不能写成完整字面量：写成完整字面量的话，本文件自己的
#    源码里就出现了那一串，扫到 verify_ui.py 时会把检查器自己数成 1 次，
#    于是断言自己把自己打倒（本轮真踩到：报出 ['verify_ui.py:2', 'app_chainlit.py:1']）。
_H1_NEEDLE_A = '"""' + '# '
_H1_NEEDLE_B = "'''" + '# '
for _f in sorted((ROOT / 'src').rglob('*.py')):
    _t = _f.read_text(encoding='utf-8', errors='ignore')
    _c = _t.count(_H1_NEEDLE_A) + _t.count(_H1_NEEDLE_B)
    if _c:
        _h1_hits.append(f'{_f.name}:{_c}')
check('全 src 只有欢迎语一处一级标题（h1 选择器是全局的，多一处就会莫名长花纹）',
      _h1_hits == ['app_chainlit.py:1'], str(_h1_hits))

_wm = re.search(r'welcome\s*=\s*"""(.*?)"""', APP_RAW, re.S)
_wt = _wm.group(1) if _wm else ''
check('欢迎语文案仍是纯 markdown（没有 <svg>/<span> 之类的原始 HTML）',
      bool(_wt) and '<svg' not in _wt and '<span' not in _wt and '<img' not in _wt,
      f'{len(_wt)} 字')

# ---------------------------------------------------------------- §9 产品名一致性
sect('§9 产品名一致性：旧名不得回流（应用标题/配置/示例/文档全在射程内）')
# 旧名不得回流。这一节的**每一个坑都是实打实踩出来的**（2026-09-18）：
#  ① 改名**不能按后缀白名单**扫。上一轮脚本只认 .py/.js/.md/.html/.css/.json/.txt/.yaml，
#     于是漏掉两个面：`.chainlit/config.toml`（`[UI] name` = **应用标题，用户直接看见**）
#     和 `.env.example`（后缀是 `.example`，谁也不会想到）。改名报了"41 处/17 文件、
#     旧名归零"，标题却还挂着旧名 —— 白名单本身就是"漏"的定义。
#  ② 改名**不能只信 ripgrep**：`.chainlit/` 在 `.gitignore` 里，ripgrep 默认跳过它，
#     所以"全仓 grep 0 命中"是**假绿**。这里自己 rglob，不信任何 ignore 规则。
#  ③ 针必须**拼出来**（同上方 h1 那个坑）：写成完整字面量的话，本文件自己就是第一处
#     "残留"，断言会自己把自己打倒。
_OLD_NAME = '浙里' + '选址'
_NEW_NAME = '址南针'
# 豁免：改名记录里**必须**写明「旧名 → 新名」，否则读的人不知道从哪改到哪
_NAME_EXEMPT = {
    'docs/欧文三条需求-实施记录.md': '改名实施记录，正文按 from→to 写法引用旧名',
}
_SKIP_DIRS = {'.git', '.pylibs', '.wheels_cache', '.venv', 'venv', 'node_modules',
              '__pycache__', 'output', 'screenshots', 'ui_screenshots', '.files',
              'dist', 'build', '.pytest_cache', '.mypy_cache', '.ruff_cache'}
_BIN_EXT = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico', '.pdf', '.docx', '.xlsx',
            '.pptx', '.zip', '.7z', '.ttf', '.otf', '.woff', '.woff2', '.pyc', '.pyd',
            '.so', '.dll', '.exe', '.db', '.sqlite', '.mp4', '.mov', '.chm', '.whl',
            # 日志是运行时痕迹，不是产品面：里面出现什么取决于用户敲了什么、服务打了什么，
            # 拿它当"名字残留"判据只会误报（`_server.log` 一边写一边被扫）。产物目录同理。
            '.log'}
_name_hits, _name_scanned = [], 0
for _f in sorted(ROOT.rglob('*')):
    if not _f.is_file():
        continue
    _rel = _f.relative_to(ROOT).as_posix()
    if set(Path(_rel).parts) & _SKIP_DIRS or _f.suffix.lower() in _BIN_EXT:
        continue
    try:
        _txt = _f.read_text(encoding='utf-8')
    except (UnicodeDecodeError, PermissionError, OSError):
        continue
    _name_scanned += 1
    if _OLD_NAME in _txt and _rel not in _NAME_EXEMPT:
        _name_hits.append(f'{_rel}:{_txt.count(_OLD_NAME)}') 
check('全仓（**不限后缀**）无旧产品名残留',
      not _name_hits,
      f'仍含旧名 → {_name_hits}；扫描 {_name_scanned} 个文本文件'
      if _name_hits else f'扫描 {_name_scanned} 个文本文件，豁免 {sorted(_NAME_EXEMPT)}')

# 应用标题这一面单独钉死：它是 config.toml 里的 `[UI] name`，**不入任何 .py/.js 扫描**，
# 也正是上一轮唯一漏到用户眼前的那一处。
_cfg = _read('.chainlit/config.toml')
check(f'应用标题（.chainlit/config.toml 的 `[UI] name`）=「{_NEW_NAME}」—— 改它必须重启服务才生效',
      bool(re.search(r'^name\s*=\s*"' + _NEW_NAME + r'"', _cfg, re.M)),
      (_cfg[_cfg.find('[UI]'):_cfg.find('[UI]') + 120].replace('\n', ' ⏎ ') if '[UI]' in _cfg
       else 'config.toml 里没有 [UI] 段'))
check(f'欢迎页 chainlit.md 用新名（它是 Chainlit 默认加载的 markdown，用户第一眼看的就是它）',
      _NEW_NAME in _read('chainlit.md'))

# ---------------------------------------------------------------- §10 步骤条收缩时机 + 聊天背景（2026-09-18 策两条）
sect('§10 步骤条收缩时机（真内容才收）+ 聊天背景（融边/罗盘水印）')
# ⚠️ 本节的坑都在注释里，回退任何一个都会复发：
#  a) 旧守卫只查「DOM 里存在 message/llm 步骤」——user_message 从提问那刻就在 → 永真；
#     llm 壳一建（正文没出）就收 → 「分析还没输出，过程先合上了」。
#  b) --zl-chat 是全局变量（Veya 置顶头/欢迎层在用），列底只能另开 --zl-chat-wash，
#     动 --zl-chat 会把两个无关表面一起改坏（红线 8 的又一次应用）。
_c = JS
check('收缩守卫用「真内容签名」(_realMsgSig)：签名没变就不收',
      'function _realMsgSig(' in _c and 'if (!sig || sig === _lastMsgSig) return;' in _c,
      '回到「有 message 就收」的写法，分析没输出就会先合上')
check('签名阈值：去空白 ≥ 12 字才算「真正的内容」（llm 空壳/加载态不进签名）',
      _c.count('len >= 12') >= 1)
check('提问时重置快照（新一轮的回答才算新内容；否则历史消息就会立刻触发收缩）',
      '_lastMsgSig = _realMsgSig();' in _c and '_lastMsgSig = sig;' in _c,
      '观察器 user_message 分支 + 收缩完成后各更新一次')
check('收缩守卫不用 DOM 顺序判定 —— 实机诊断（2026-09-18）：Chainlit 把最终 '
      'assistant_message 插在 run 步骤**之前**（PRECEDING），顺序判定永远不成立',
      'compareDocumentPosition' not in _fn_code(JS_RAW, 'function collapseProcessStep(')
      if 'function collapseProcessStep(' in JS_RAW else False)
check('聊天列底用 --zl-chat-wash（不能动 --zl-chat：Veya 头/欢迎层两个表面共用它）',
      JS.count('--zl-chat-wash:rgba(') == 2 and 'var(--zl-chat-wash) !important' in JS,
      '暗/亮两套必须各一份')
check('列底两侧融进页底色（不再是「一块突兀的淡色方块」）',
      'linear-gradient(90deg,var(--zl-page) 0%,rgba(0,0,0,0) 76px' in JS)
check('罗盘水印由 compassURI() 生成（址南针主题；与 pinURI 同为线描 + data-URI）',
      'function compassURI(' in JS and 'viewBox=\'0 0 200 200\' fill=\'none\'' in JS)
check('罗盘是线描 + 中心实心点（实心填充在低透明度下糊成一坨 —— pinURI 踩过的同一坑）',
      "<circle cx='100' cy='100' r='5' fill='" in JS
      and 'stroke-linejoin=\'round\'' in JS)
check('罗盘铺在列底最顶层 background 且垂直居中（挪上来的理由：放 ::before 会被 wash 压到 45%，实机看不见；'
      '位置 50% 是策 2026-09-18 要求：整幅落在对话框正中、不探进置顶头那一框）',
      JS.count("' center 50% / 480px 480px no-repeat,'") == 1,
      '罗盘只出现在基础条的列底（品类高亮只换立柱，罗盘保持主题色）')
check('品类高亮只换立柱色（罗盘不进品类规则：品牌视觉不跟品类换）',
      "SEL + '.relative::before{background:'" in JS
      and "wmLinesCss(hiRgb, hiA)" in JS)
_vjs = re.search(r'sidebar\.js\?v=(\d+)', _cfg)
check('custom_js 版本号 >= v23 且随 sidebar.js 改动升级（浏览器缓存铁律；不钉死具体数字，'
      '每次升版本不用再改本断言）',
      bool(_vjs) and int(_vjs.group(1)) >= 23,
      _vjs.group(0) if _vjs else 'config.toml 里没有 sidebar.js?v=')

# 后端过程文案（agent_graph.py）：本轮顺带丰富的三处，钉住不许缩回占位符
AG = _read('src/agent/agent_graph.py')
check('定位完成步骤带「坐标用途」说明（不是孤零零一个坐标）',
      '全部基于这个坐标计算' in AG)
check('四品类并联测算步骤带本地库规模（4.4 万 POI）',
      '浙江 4.4 万条' in AG)
check('四品类完成 output 带「月净利预估：」前缀（原来是裸分号拼接）',
      '四品类月净利预估：' in AG)
check('政策顾问完成步骤注明「参考链接已附上」',
      '参考链接（原文出处）已随回答附上' in AG)

# ---------------------------------------------------------------- §11 置顶头透明 + 罗盘 Logo（2026-09-18 策两条）
sect('§11 置顶头去掉淡色实底 + Veyra logo 换址南针罗盘（同风格同配色）')
#  a) 那块「更淡色的长方块」就是 #zl-veya 的 background:var(--zl-chat)（94%~97% 不透明）+ blur，
#     盖住了列底罗盘水印的顶部。它在 .zl-chatcol 外层容器、不在内层滚动区 —— 消息不会
#     从它下面穿过，去掉实底不影响可读性（这是敢去掉的依据，回退说明没想清楚布局）。
check('置顶头不再有淡色实底/毛玻璃（罗盘水印从头部区域透出来）',
      'padding:14px 22px 10px;}' in JS
      and 'background:var(--zl-chat);backdrop-filter:blur(6px)' not in JS,
      '#zl-veya 回加实底会重新盖住罗盘')
check('--zl-chat 剩下的消费面还在（#zl-page-ov 全页覆盖层没被误伤）',
      "background:var(--zl-chat);color:var(--zl-wb-tx)" in JS)
#  b) 新罗盘 logo：旧 Veyra（C形弯月+侦探剪影）整段替换。风格承接点必须逐个钉住：
#     同底（米色圆底+发丝边）、同三色（藏青/金/米白）、线描、衬线小字、光斑小点、
#     针尖指南（址南针=指南针的选址变体）、zv-bob 浮动呼吸沿用。
check('旧 Veyra logo（弯月/侦探/「街」字/mask zvP）已整段移除',
      'Veyra 品牌 Logo' not in JS and 'mask id="zvP"' not in JS and '>街</text>' not in JS)
check('新 logo 是址南针罗盘（aria-label + 同底同发丝边）',
      'aria-label="址南针罗盘 Logo"' in JS
      and 'fill="#fdfbee"' in JS and 'stroke="#e4dcc2"' in JS)
check('罗盘刻度环由生成器画 24 根（四正向加长，i%6===0）',
      'for (i = 0; i < 24; i++)' in JS and 'i % 6 === 0' in JS)
check('罗盘针双色：北半藏青 / 南半金，针尖指南',
      'M50 24 L55.5 50 L44.5 50 Z" fill="#0e353a"' in JS
      and 'M44.5 50 L55.5 50 L50 76 Z" fill="#c9a45c"' in JS)
check('「南」字小标注沿用原 logo 的衬线字体栈（原「街」字的呼应）',
      '>南</text>' in JS and 'Noto Serif SC,STSong,SimSun,serif' in JS)
check('浮动呼吸动画沿用（zv-bob + drop-shadow 光晕，策点名要保留）',
      'animation:zv-bob 4s ease-in-out infinite' in JS
      and '@keyframes zv-bob{0%,100%{transform:translateY(0)}50%{transform:translateY(-3px)}}' in JS
      and 'filter:drop-shadow(0 5px 16px var(--zl-logo-glow))' in JS)

# ---------------------------------------------------------------- 汇总
p('')
p('=' * 66)
if FAIL:
    p(f'FAILED = {len(FAIL)}：' + ' / '.join(FAIL))
else:
    p('全部 PASS')
OUT.write_text('\n'.join(L), encoding='utf-8')
print(f'\n[写入] {OUT}')
sys.exit(1 if FAIL else 0)
