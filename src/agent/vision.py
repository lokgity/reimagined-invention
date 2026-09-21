# -*- coding: utf-8 -*-
"""
vision.py —— 门头照 VLM 分析（AI 方向③）
========================================
用户上传商铺门头照片 → 豆包视觉模型(doubao-seed-2-1-pro 支持图像输入)
输出结构化观察：招牌品牌识别 / 装修档次 / 门头可见度 / 卫生观感 / 评分修正建议。

分工：VLM 只做"看图说话"（视觉证据），不编造经营数据；
      评分修正幅度限制在 ±5 分以内，只影响"装修档次/形象"类软指标。
"""
import sys
import json
import base64
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import LLM_ARK_API_KEY, LLM_ARK_BASE_URL, LLM_ARK_MODEL, LLM_ARK_MODEL_FALLBACK

_VLM_EXTRA = {'max_tokens': 800, 'thinking': {'type': 'disabled'}}

# ---------------------------------------------------------------
# 门头照 VLM 的时限约定（**两条调用路径共用**）
# ---------------------------------------------------------------
# 背景：analyze_storefront 内部按 (主模型, 备模型) 顺序各试一次，
#      若各自用默认 timeout=90，最坏 2×90 = 180s 界面零反馈。
#      "自动看铺"路径（agent_graph.py）本就有 75s 的 wait_for 包裹，
#      而"用户手动上传"路径（app_chainlit.py）一直漏着 → 两条路径行为不一致。
#      故把时限收敛成常量，两条路径统一引用：
VLM_PER_MODEL_TIMEOUT = 60   # 单个视觉模型（主/备）的 socket 超时
VLM_TOTAL_BUDGET = 75        # 整条链（主+备）的总预算，由调用方 asyncio.wait_for 包裹
# ⚠️ 不变式：VLM_PER_MODEL_TIMEOUT × 2 > VLM_TOTAL_BUDGET。
#    否则"总预算"形同虚设——两个模型各自跑满也不超预算，包裹白加。
#    该不变式由 verify_degrade_fallback.py 断言。

_SYSTEM = """你是商铺选址评估中的"门头照片审核员"。用户会给你一张商铺门头/店面照片。
请只基于图片中真实可见的内容，输出严格 JSON（不要输出多余文字）：
{
  "是否门头实景": true/false（图中是否有真实店铺门头/店面场景；若只是品牌logo、产品宣传图、菜单、室内局部，填 false）,
  "招牌文字": "照片中招牌上实际显示的文字，看不清填 null",
  "识别品牌": "若招牌或标识是已知连锁品牌则给品牌名（如 蜜雪冰城），否则 null",
  "装修档次": 1-5 的整数（1=简陋/老旧, 3=普通整洁, 5=精致高档）,
  "门头可见度": 1-5 的整数（招牌是否醒目、夜间是否有发光字、是否被遮挡）,
  "卫生观感": 1-5 的整数,
  "观察描述": "50 字以内客观描述照片中看到的内容",
  "经营建议": "80 字以内，针对门头/形象层面的可执行建议",
  "评分修正": -5 到 +5 的整数（对选址评分中"形象/装修"软指标的建议修正分）
}
规则：看不清就如实说看不清；不是门头实景就填 false 并把评分修正填 0；
不要猜测照片外的信息；不要编造经营数据。"""


def _call_vision(model: str, b64: str, mime: str, user_text: str,
                 timeout=VLM_PER_MODEL_TIMEOUT) -> str:
    import urllib.request
    import urllib.error
    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': _SYSTEM},
            {'role': 'user', 'content': [
                {'type': 'text', 'text': user_text},
                {'type': 'image_url',
                 'image_url': {'url': f'data:{mime};base64,{b64}'}},
            ]},
        ],
        'temperature': 0.2,
    }
    payload.update(_VLM_EXTRA)
    req = urllib.request.Request(
        f'{LLM_ARK_BASE_URL.rstrip("/")}/chat/completions',
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json',
                 'Authorization': f'Bearer {LLM_ARK_API_KEY}'},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        return data['choices'][0]['message']['content']
    except urllib.error.HTTPError as e:
        body = ''
        try:
            body = e.read().decode('utf-8', 'replace')[:200]
        except Exception:
            pass
        raise Exception(f'HTTP {e.code} {body}') from e


def _parse_json(text: str) -> dict:
    """从 LLM 输出中稳健提取 JSON 对象"""
    m = re.search(r'\{[\s\S]*\}', text or '')
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {}


def _clamp(v, lo, hi, default):
    try:
        return max(lo, min(hi, int(v)))
    except Exception:
        return default


def analyze_storefront(image_bytes: bytes, mime: str = 'image/jpeg',
                       context: str = '', timeout=VLM_PER_MODEL_TIMEOUT) -> dict:
    """分析门头照片，返回结构化观察 dict；失败抛异常由调用方降级。
    context: 可选上下文（如"用户打算开奶茶店，品牌古茗"），帮助 VLM 对焦。
    """
    if not LLM_ARK_API_KEY:
        raise Exception('未配置火山方舟 API KEY')
    b64 = base64.b64encode(image_bytes).decode('ascii')
    user_text = '请分析这张商铺门头照片。' + (f'背景信息：{context}' if context else '')

    errors = []
    for model in (LLM_ARK_MODEL, LLM_ARK_MODEL_FALLBACK):
        try:
            raw = _call_vision(model, b64, mime, user_text, timeout=timeout)
            d = _parse_json(raw)
            if not d:
                raise Exception(f'返回非 JSON: {raw[:120]}')
            return {
                '是否门头实景': bool(d.get('是否门头实景', False)) if isinstance(d.get('是否门头实景'), bool) else str(d.get('是否门头实景', '')).lower() in ('true', '是', 'yes', '1'),
                '招牌文字': d.get('招牌文字'),
                '识别品牌': d.get('识别品牌'),
                '装修档次': _clamp(d.get('装修档次'), 1, 5, 3),
                '门头可见度': _clamp(d.get('门头可见度'), 1, 5, 3),
                '卫生观感': _clamp(d.get('卫生观感'), 1, 5, 3),
                '观察描述': d.get('观察描述') or '',
                '经营建议': d.get('经营建议') or '',
                '评分修正': _clamp(d.get('评分修正'), -5, 5, 0),
                '_model': model,
            }
        except Exception as e:
            errors.append(f'{model}: {e}')
    raise Exception('视觉模型调用失败：' + '；'.join(errors))


def _download(url: str, timeout=25, max_bytes=6_000_000) -> bytes:
    """下载图片（带 UA/Referer，限制体积，避免超大图拖垮请求）"""
    import urllib.request
    req = urllib.request.Request(
        url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://nb.58.com/'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(max_bytes)


def analyze_storefront_url(url: str, context: str = '',
                           timeout=VLM_PER_MODEL_TIMEOUT) -> dict:
    """按图片 URL 分析门头（用于 58 在租商铺实拍图自动看铺）。"""
    if not url:
        raise Exception('无图片地址')
    data = _download(url)
    if len(data) < 3000:
        raise Exception(f'图片过小或下载失败（{len(data)} 字节）')
    mime = 'image/png' if '.png' in url.lower() else 'image/jpeg'
    return analyze_storefront(data, mime, context, timeout=timeout)


def render_storefront_report(d: dict) -> str:
    """把 VLM 结果渲染成给用户的 Markdown 回复"""
    stars = lambda n: '★' * n + '☆' * (5 - n)
    if not d.get('是否门头实景'):
        lines = ['📷 **门头照分析（视觉模型）**', '',
                 '这张图**不是门头实景**（看起来是品牌 logo / 产品宣传图 / 室内局部），'
                 '我没法据此给形象打分——不给假分。']
        if d.get('识别品牌'):
            lines.append(f'不过图里能认出品牌：**{d["识别品牌"]}**'
                         + (f'（招牌/标识文字：{d["招牌文字"]}）' if d.get('招牌文字') else ''))
        if d.get('观察描述'):
            lines.append(f'图片内容：{d["观察描述"]}')
        lines.append('\n想要形象评分，请上传**白天/夜间正面拍到的门头照**（能看到招牌和门脸）。')
        return '\n'.join(lines)

    lines = ['📷 **门头照分析（视觉模型）**', '']
    if d.get('招牌文字'):
        lines.append(f'**招牌**：{d["招牌文字"]}' +
                     (f'（识别为连锁品牌 **{d["识别品牌"]}**）' if d.get('识别品牌') else ''))
    elif d.get('识别品牌'):
        lines.append(f'**识别品牌**：{d["识别品牌"]}')
    if d.get('观察描述'):
        lines.append(f'**观察**：{d["观察描述"]}')
    lines.append(f'**装修档次**：{stars(d["装修档次"])}　'
                 f'**门头可见度**：{stars(d["门头可见度"])}　'
                 f'**卫生观感**：{stars(d["卫生观感"])}')
    if d.get('经营建议'):
        lines.append(f'**建议**：{d["经营建议"]}')
    adj = d.get('评分修正', 0)
    if adj:
        lines.append(f'\n形象软指标修正建议：**{"+" if adj > 0 else ""}{adj} 分**'
                     '（仅影响形象/装修维度，不改经营测算）')
    lines.append('\n（注：照片仅反映拍摄时刻的门头状态，建议结合实地不同时段复核）')
    return '\n'.join(lines)


if __name__ == '__main__':
    # 自检：生成一张模拟"招牌"图片测试链路
    import io
    try:
        from PIL import Image, ImageDraw
        img = Image.new('RGB', (600, 300), (245, 245, 240))
        dr = ImageDraw.Draw(img)
        dr.rectangle([0, 0, 600, 90], fill=(200, 30, 40))
        dr.text((200, 30), 'MILK TEA', fill=(255, 255, 255))
        dr.rectangle([50, 150, 550, 260], fill=(180, 210, 230))
        buf = io.BytesIO()
        img.save(buf, 'PNG')
        r = analyze_storefront(buf.getvalue(), 'image/png')
        print(json.dumps(r, ensure_ascii=False, indent=1))
    except ImportError:
        print('PIL 不可用，跳过自检')
