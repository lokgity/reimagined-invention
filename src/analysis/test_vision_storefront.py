# -*- coding: utf-8 -*-
"""
test_vision_storefront.py —— 门头照 VLM 回归测试（真实 58 实拍图）
==================================================================
用 analysis/fixtures 下两张真实在租商铺实拍图跑视觉模型，验证：
1. 是否门头实景判定为 true（logo/宣传图应为 false，不给假分）
2. 招牌文字能读出
3. 三项 1-5 观察分与形象分能并入评分（apply_storefront）

运行: cd src && python analysis/test_vision_storefront.py
"""
import sys
import json
from pathlib import Path

sys.stdout.reconfigure(errors='replace')
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.vision import analyze_storefront, render_storefront_report
from engine.scoring import apply_storefront

FIX = Path(__file__).resolve().parent / 'fixtures'

FAKE_RESULT = {
    'name': '回归测试铺', 'category': '奶茶', 'total': 66.0, 'verdict': '谨慎推荐',
    'dims': {'客群匹配度': 70.0, '竞争压力': 60.0, '交通可达性': 75.0, '租金承受力': 55.0},
    'weights': {'客群匹配度': 0.35, '竞争压力': 0.30, '交通可达性': 0.20, '租金承受力': 0.15},
    'warnings': [], 'decoration': {'档次分': 60},
}


def main():
    ok = True
    for f in sorted(FIX.glob('storefront_58_*.jpg')):
        data = f.read_bytes()
        r = analyze_storefront(data, 'image/jpeg', '计划品类：奶茶；58同城在租商铺实拍图')
        print(f'=== {f.name} ({len(data)//1024}KB)')
        print(json.dumps({k: v for k, v in r.items() if k != '_model'},
                         ensure_ascii=False, indent=1))
        if not r.get('是否门头实景'):
            print('!! 判定为非门头实景（真实实拍图应为 true）')
            ok = False
        if not r.get('招牌文字'):
            print('!! 未读出招牌文字')
            ok = False
        # 并入评分
        res = json.loads(json.dumps(FAKE_RESULT))
        before = res['total']
        apply_storefront(res, r)
        sf = res.get('storefront') or {}
        print(f'形象分 {sf.get("形象分")}（权重10%）→ 总分 {before} → {res["total"]} {res["verdict"]}')
        assert abs(sum(res['weights'].values()) - 1.0) < 1e-6, '权重未归一'
        assert '门头形象(照片)' in res['dims'], '维度未写入'
        print(render_storefront_report(r)[:200])
        print()
    print('回归结果:', 'PASS' if ok else 'FAIL')


if __name__ == '__main__':
    main()
