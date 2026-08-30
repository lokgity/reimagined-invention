# -*- coding: utf-8 -*-
"""
config.py —— 全局配置与品类画像参数
=====================================
- 品类画像参数表（奶茶/甜品/早餐/便利店）的代码实现
- API key 从环境变量 / .env 文件加载（不上传 Git）
"""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / '.env')
except Exception:
    pass

# Windows 控制台 GBK 代码页兼容：输出统一 UTF-8，避免 ¥ 等字符崩溃
import sys
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# ---------------------------------------------------------------
# 1. API Keys（用户在 .env 中填写）
# ---------------------------------------------------------------
AMAP_KEY = os.getenv('AMAP_KEY', '')        # 高德开放平台 Web 服务 key
AMAP_SECRET = os.getenv('AMAP_SECRET', '')  # 高德 key 的安全密钥（新版 key 必需，用于 SHA256 签名）

# 大模型 API（主用：火山方舟豆包 doubao-seed；备用：小米 mimo；再备：DeepSeek）
LLM_ARK_API_KEY = os.getenv('LLM_ARK_API_KEY', '')
LLM_ARK_BASE_URL = os.getenv('LLM_ARK_BASE_URL', 'https://ark.cn-beijing.volces.com/api/v3')
# 注：doubao-seed-2.1-pro/turbo 是展示名，API 实际模型 ID 需带版本号
LLM_ARK_MODEL = os.getenv('LLM_ARK_MODEL', 'doubao-seed-2-1-pro-260628')      # 火山方舟主选
LLM_ARK_MODEL_FALLBACK = os.getenv('LLM_ARK_MODEL_FALLBACK', 'doubao-seed-2-1-turbo-260628')  # 次选

# 小米 mimo（备用）
LLM_API_KEY = os.getenv('LLM_API_KEY', '')
LLM_BASE_URL = os.getenv('LLM_BASE_URL', 'https://api.xiaomimimo.com/v1')
LLM_MODEL = os.getenv('LLM_MODEL', 'mimo-v2.5-pro')

# DeepSeek 备用（余额不足时降级）
LLM_FALLBACK_API_KEY = os.getenv('LLM_FALLBACK_API_KEY', '')
LLM_FALLBACK_BASE_URL = os.getenv('LLM_FALLBACK_BASE_URL', 'https://api.deepseek.com/v1')
LLM_FALLBACK_MODEL = os.getenv('LLM_FALLBACK_MODEL', 'deepseek-chat')

# ---------------------------------------------------------------
# 2. 数据路径
# ---------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / 'data'
DB_PATH = DATA_DIR / 'zj_poi.db'
DATA_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------
# 3. 浙江 11 地级市（用于数据预抓取和城市校验）
# ---------------------------------------------------------------
ZHEJIANG_CITIES = [
    '杭州', '宁波', '温州', '嘉兴', '湖州',
    '绍兴', '金华', '衢州', '舟山', '台州', '丽水',
]

# ---------------------------------------------------------------
# 4. 品类画像参数（与 docs/品类画像参数表.md 一一对应）
# ---------------------------------------------------------------
# 每个品类定义:
#   cn_name      : 中文品类名
#   poi_keywords : 竞品 POI 关键词（高德类型/关键词，用于搜索同类店）
#   target_pois  : 目标客群 POI 关键词列表，每项带权重(0~1)
#   weights      : 四维度权重（客群/竞争/交通/租金），和为 1
#   radius       : 参考半径（米）
#   comp_base    : 竞争基准（半径内同品类多少家算饱和）
#   price        : 客单价参考（元）
#   rent_ratio   : 盈亏平衡租金占月流水比例
#   daily_sales  : 参考日单量（用于租金承受力粗估）
CATEGORY_PROFILES = {
    '奶茶': {
        'cn_name': '奶茶',
        'poi_keywords': ['奶茶', '新式茶饮', '茶饮'],
        'target_pois': [
            {'kw': ['大学', '学院', '职业技术学院'], 'weight': 0.35, 'label': '学校'},
            {'kw': ['写字楼', '商务大厦', '产业园'], 'weight': 0.25, 'label': '办公'},
            {'kw': ['购物中心', '商场', '商业街', '步行街'], 'weight': 0.20, 'label': '商圈'},
            {'kw': ['小区', '公寓'], 'weight': 0.20, 'label': '社区'},
        ],
        'weights': {'客群匹配度': 0.35, '竞争压力': 0.25, '交通可达性': 0.25, '租金承受力': 0.15},
        'radius': 500,
        'comp_base': 8,
        'price': 16,
        'rent_ratio': 0.12,
        'daily_sales': 250,
        'area_range': (15, 50),   # 最佳面积区间(㎡): 奶茶店标准店15-50㎡
        'area_ideal': 30,         # 理想面积(㎡)
        'profile_desc': '高客流年轻客群驱动的冲动型消费：核心是"路过的人对不对"。',
    },
    '甜品': {
        'cn_name': '甜品',
        'poi_keywords': ['甜品', '蛋糕', '烘焙', '糖水'],
        'target_pois': [
            {'kw': ['购物中心', '商场', '商业街', '步行街'], 'weight': 0.30, 'label': '商圈'},
            {'kw': ['写字楼', '商务大厦'], 'weight': 0.25, 'label': '办公'},
            {'kw': ['大学', '中学', '学院'], 'weight': 0.20, 'label': '学校'},
            {'kw': ['小区', '公寓'], 'weight': 0.25, 'label': '社区'},
        ],
        'weights': {'客群匹配度': 0.35, '竞争压力': 0.20, '交通可达性': 0.25, '租金承受力': 0.20},
        'radius': 800,
        'comp_base': 6,
        'price': 30,
        'rent_ratio': 0.15,
        'daily_sales': 120,
        'area_range': (30, 80),   # 甜品店需要烘焙/展示空间
        'area_ideal': 50,
        'profile_desc': '目的性+场景性消费：消费者专门去买，看重可达性与商圈氛围。',
    },
    '早餐': {
        'cn_name': '早餐',
        'poi_keywords': ['早餐', '早点', '包子', '煎饼', '肠粉', '豆浆'],
        'target_pois': [
            {'kw': ['地铁站', '公交站'], 'weight': 0.40, 'label': '通勤'},
            {'kw': ['写字楼', '商务大厦', '产业园'], 'weight': 0.30, 'label': '办公'},
            {'kw': ['小区', '公寓', '住宅区'], 'weight': 0.30, 'label': '社区'},
        ],
        'weights': {'客群匹配度': 0.30, '竞争压力': 0.20, '交通可达性': 0.35, '租金承受力': 0.15},
        'radius': 300,
        'comp_base': 5,
        'price': 10,
        'rent_ratio': 0.10,
        'daily_sales': 400,
        'area_range': (10, 40),   # 早餐店档口/小店即可
        'area_ideal': 20,
        'profile_desc': '高频低价刚需：靠通勤路上正好路过，选址本质是"抢动线"。',
    },
    '便利店': {
        'cn_name': '便利店',
        'poi_keywords': ['便利店', '超市'],
        'target_pois': [
            {'kw': ['小区', '公寓', '住宅区', '社区'], 'weight': 0.40, 'label': '社区'},
            {'kw': ['写字楼', '商务大厦', '产业园'], 'weight': 0.30, 'label': '办公'},
            {'kw': ['大学', '学院', '中学'], 'weight': 0.15, 'label': '学校'},
            {'kw': ['地铁站', '公交站'], 'weight': 0.15, 'label': '通勤'},
        ],
        'weights': {'客群匹配度': 0.40, '竞争压力': 0.25, '交通可达性': 0.20, '租金承受力': 0.15},
        'radius': 500,
        'comp_base': 4,
        'price': 15,
        'rent_ratio': 0.20,
        'daily_sales': 300,
        'area_range': (30, 100),  # 便利店需要货架/冷柜空间
        'area_ideal': 60,
        'profile_desc': '居住/办公密度驱动的高频复购：靠人口基数，24h 属性强。',
    },
}

# 目标客群 POI 的完整关键词表（用于高德 POI 搜索聚合查询）
# 每个品类从 target_pois 中提取，合并去重后用于数据抓取
TARGET_POI_TYPES = {
    '学校': ['大学', '学院', '职业技术学院', '中学'],
    '办公': ['写字楼', '商务大厦', '产业园'],
    '商圈': ['购物中心', '商场', '商业街', '步行街'],
    '社区': ['小区', '公寓', '住宅区', '社区'],
    '通勤': ['地铁站', '公交站'],
}


def get_profile(category: str) -> dict:
    """按名称取品类画像；不区分大小写，容忍'奶茶店'等后缀。"""
    if category in CATEGORY_PROFILES:
        return CATEGORY_PROFILES[category]
    for key, prof in CATEGORY_PROFILES.items():
        if key in category or category in key:
            return prof
    raise KeyError(f'未知品类: {category}，支持: {list(CATEGORY_PROFILES.keys())}')


if __name__ == '__main__':
    print('支持品类:', list(CATEGORY_PROFILES.keys()))
    for name, p in CATEGORY_PROFILES.items():
        print(f"\n【{name}】{p['profile_desc']}")
        print(f"  半径 {p['radius']}m | 竞争基准 {p['comp_base']} 家 | 客单价 ¥{p['price']}")
        print(f"  权重: {p['weights']}")
