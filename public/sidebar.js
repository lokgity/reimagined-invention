/* ============================================================
   址南针 · 三栏工作台（custom_js）v3
   - 最左：新建对话 / 对比 / 快速演示 / 历史会话
   - 中间：对话框（文本回复）
   - 最右：分析工作台（指标卡片/热力图/得分表格/雷达图/对比/结构化录入表单）
   数据源：/public/sidebar.json + /public/dashboard.json（服务端写入）
   v3 要点：
   - 三栏宽度：中间最大(660) > 右(450) > 左(330)，两侧内容等比例放大
   - 双主题：暗=黑底+深蓝侧栏；亮=淡黄底+海盐蓝侧栏（跟随 Chainlit 明暗切换）
   - 左栏下移至头部之下，避免遮挡顶部明暗切换按钮
   - 聊天区内 emoji 全部替换为 Lottie 动画（public/lottie/*.json）
   - 执行过程步骤默认展开、内容半透明+等宽，实时可见
   ============================================================ */
(function () {
  if (window.__zl_rail) return;
  window.__zl_rail = true;

  var LEFT_W = 330;   // 左栏宽度
  var RIGHT_W = 450;  // 右栏宽度
  /* ⚠️ 首项是**自托管**的中文圆体（@font-face 声明在 public/app.css），离线可用。
     它是按 GB2312 + 项目用字子集化的，落在子集外的生僻字会逐字回落到后面的系统字体
     —— 这是刻意取舍，不是 bug。改这一行等于换全站字体，别随手删首项。 */
  var FONT = '"ZL Rounded SC","Noto Sans SC","Microsoft YaHei","PingFang SC","Source Han Sans SC",sans-serif';

  /* ---- Lucide 风格线性图标（24×24 stroke） ---- */
  var ICONS = {
    plus: '<path d="M5 12h14"/><path d="M12 5v14"/>',
    compare: '<path d="m16 3 4 4-4 4"/><path d="M20 7H4"/><path d="m8 21-4-4 4-4"/><path d="M4 17h16"/>',
    spark: '<path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"/>',
    coffee: '<path d="M17 8h1a4 4 0 1 1 0 8h-1"/><path d="M3 8h14v9a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4z"/><path d="M6 2v2"/><path d="M10 2v2"/><path d="M14 2v2"/>',
    cake: '<path d="M20 21v-8a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8"/><path d="M4 16s.5-1 2-1 2.5 2 4 2 2.5-2 4-2 2.5 2 4 2 2-1 2-1"/><path d="M2 21h20"/><path d="M7 8v3"/><path d="M12 8v3"/><path d="M17 8v3"/><path d="M7 4h.01"/><path d="M12 4h.01"/><path d="M17 4h.01"/>',
    utensils: '<path d="M3 2v7c0 1.1.9 2 2 2h4a2 2 0 0 0 2-2V2"/><path d="M7 2v20"/><path d="M21 15V2a5 5 0 0 0-5 5v6c0 1.1.9 2 2 2h3Zm0 0v7"/>',
    bag: '<path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/><path d="M3 6h18"/><path d="M16 10a4 4 0 0 1-8 0"/>',
    bulb: '<path d="M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1.3.5 2.6 1.5 3.5.7.7 1.3 1.5 1.5 2.5"/><path d="M9 18h6"/><path d="M10 22h4"/>',
    clock: '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    trash: '<path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/>',
    pin: '<path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0z"/><circle cx="12" cy="10" r="3"/>',
    gauge: '<path d="M3 3v18h18"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/>',
    grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    check: '<path d="M20 6 9 17l-5-5"/>',
    arrow: '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
    layers: '<path d="m12 2 10 6-10 6L2 8z"/><path d="m2 14 10 6 10-6"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.9 4.9 1.4 1.4"/><path d="m17.7 17.7 1.4 1.4"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m4.9 19.1 1.4-1.4"/><path d="m17.7 6.3 1.4-1.4"/>',
    moon: '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9z"/>',
    type: '<path d="M4 7V4h16v3"/><path d="M9 20h6"/><path d="M12 4v16"/>',
    info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    reset: '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>',
    link: '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
    book: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
    warn: '<path d="m10.3 3.6-8 13.9A2 2 0 0 0 4 20.5h16a2 2 0 0 0 1.7-3l-8-13.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4"/><path d="M12 16.5h.01"/>'
  };
  function xIco(size) {
    var s = size || 16;
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" width="' + s + '" height="' + s + '" aria-hidden="true"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>';
  }
  function ico(name, cls) {
    return '<svg class="ic' + (cls ? ' ' + cls : '') + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="19" height="19" aria-hidden="true">' + (ICONS[name] || ICONS.gauge) + '</svg>';
  }
  /* 欢迎语标题花纹的 SVG（诉求⑤，2026-09-17 定案 = 定位针）。
     为什么是 data-URI 而不是往 welcome 文案里塞 <svg>：
     Chainlit 的 markdown 渲染会把原始 HTML sanitize 掉，塞进去只会露成一堆标签。
     ⚠️ data-URI 内部读不到 CSS 变量，所以颜色只能"以参数传进来"——
        深浅两套各生成一份，分别挂在两条 h1 规则上。
     ⚠️ 形状必须是「描边 + 中心实心点」，**不能画成实心填充**：
        实心版在 34px 下整枚钉糊成一坨金色圆点，中心圈又叠在实心上（不是真洞），
        实机截图一看就露馅 —— 小尺寸装饰只能走线描。 */
  function pinURI(color) {
    return 'url("data:image/svg+xml,' + encodeURIComponent(
      "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 48 48' fill='none'>" +
      "<path d='M24 7C15.5 7 9 13.8 9 22C9 32.5 24 41 24 41C24 41 39 32.5 39 22C39 13.8 32.5 7 24 7Z' stroke='" + color + "' stroke-width='2' stroke-linejoin='round'/>" +
      "<circle cx='24' cy='21.5' r='4.4' fill='" + color + "'/>" +
      "<path d='M13 45.5Q24 49.5 35 45.5' stroke='" + color + "' stroke-width='2' stroke-linecap='round'/>" +
      "</svg>") + '")';
  }

  /* ---- 1. 样式（双主题 CSS 变量：暗为默认，亮用 html:not(.dark) 覆盖） ---- */
  var style = document.createElement('style');
  style.textContent = [
    /* 主题变量 —— 暗（默认）：深墨青底 + 藏青/金，品牌体系 */
    ':root{',
    '--zl-page:#0b1d22;--zl-chat:rgba(11,29,34,.97);--zl-chat-wash:rgba(11,29,34,.55);',
    '--zl-rail-grad:linear-gradient(180deg,#132e34 0%,#0d242a 55%,#17383f 100%);',
    '--zl-rail-bord:rgba(229,201,138,.18);',
    '--zl-title-grad:linear-gradient(90deg,#f0d9a6,#c9a45c);--zl-title-ic:#e5c98a;',
    '--zl-sub:#9db3b6;--zl-sec:#9db3b6;',
    '--zl-btn-bg:rgba(255,255,255,.06);--zl-btn-tx:#e9f0ee;--zl-btn-ic:#9db3b6;',
    '--zl-btn-hov:rgba(229,201,138,.15);--zl-btn-hov-ic:#f0d9a6;--zl-btn-bord-hov:rgba(229,201,138,.5);',
    '--zl-hist-hov:rgba(255,255,255,.08);',
    '--zl-tag-ok:#7ee0b8;--zl-tag-okbg:rgba(52,199,123,.18);',
    '--zl-tag-chat:#9fd0d6;--zl-tag-chatbg:rgba(61,130,140,.2);',
    /* 候选卡片的数据可信度标签（2026-09-17）：推算=琥珀、不可得=灰。
       三态必须视觉可分，否则推算值会被当成实测挂牌价。 */
    '--zl-tag-warn:#f0d9a6;--zl-tag-warnbg:rgba(201,164,92,.2);',
    '--zl-tag-mute:#9db3b6;--zl-tag-mutebg:rgba(157,179,182,.18);',
    '--zl-del-hov:#f87171;--zl-del-hovbg:rgba(239,68,68,.22);',
    '--zl-empty:#9db3b6;--zl-foot:#9db3b6;--zl-footbg:rgba(0,0,0,.22);',
    '--zl-badge:#e5c98a;--zl-badgebg:rgba(201,164,92,.16);--zl-ring:#e0c084;--zl-ring-soft:rgba(229,201,138,.25);',
    '--zl-wb-grad:linear-gradient(180deg,#132e34 0%,#0d242a 100%);--zl-wb-tx:#e9f0ee;--zl-wb-head-tx:#f4f2e6;',
    '--zl-card-bg:rgba(255,255,255,.05);--zl-card-bord:rgba(229,201,138,.15);--zl-card-lab:#9db3b6;--zl-card-val:#f2efe0;',
    /* 仿真大屏（自绘）：马路 / 画布 / 节点描边。⚠️ 深浅两套必须成对改（孪生坑） */
    '--zl-road:rgba(233,240,238,.30);--zl-road-hi:rgba(229,201,138,.55);--zl-canvas:rgba(0,0,0,.26);',
    '--zl-node-tx:#0b1f24;',
    '--zl-table-bg:rgba(255,255,255,.04);--zl-td-bord:rgba(229,201,138,.1);--zl-td-k:#9db3b6;--zl-td-v:#f2efe0;',
    '--zl-bar-track:rgba(255,255,255,.09);--zl-radar-bg:rgba(255,255,255,.04);--zl-radar-grid:#35555c;--zl-radar-tx:#9db3b6;',
    '--zl-warn-bg:rgba(239,68,68,.14);--zl-warn-bord:rgba(239,68,68,.4);--zl-warn-tx:#fda4a4;',
    '--zl-input-bg:rgba(255,255,255,.06);--zl-input-bord:rgba(229,201,138,.25);--zl-input-tx:#f2efe0;--zl-ph:#8fa6a8;',
    '--zl-skel1:rgba(255,255,255,.06);--zl-skel2:rgba(255,255,255,.15);',
    '--zl-ghost-tx:#9db3b6;--zl-ghost-bord:rgba(229,201,138,.28);',
    '--zl-step-tx:rgba(233,240,238,.82);--zl-legend-tx:#9db3b6;--zl-map-bord:rgba(229,201,138,.2);--zl-plch-tx:#9db3b6;',
    '--zl-score:#e0c084;',
    '--zl-accent-grad:linear-gradient(90deg,#c9a45c,#ddbd82);--zl-accent-tx:#1c1404;',
    '--zl-veya-tx:#f0d9a6;',
    '--zl-logo-c1:#e5c98a;--zl-logo-c2:#c9a45c;--zl-logo-ink:#0b1d22;--zl-logo-eyes:#fff;--zl-logo-glow:rgba(224,192,132,.35);',
    '}',
    /* 主题变量 —— 亮：米色底 + 藏青侧栏/强调 + 金点缀（品牌体系） */
    'html:not(.dark){',
    '--zl-page:#fbf5e3;--zl-chat:rgba(253,250,240,.94);--zl-chat-wash:rgba(253,250,240,.5);',
    '--zl-rail-grad:linear-gradient(180deg,rgba(250,245,222,.97) 0%,rgba(246,238,210,.97) 55%,rgba(252,248,230,.97) 100%);',
    '--zl-rail-bord:rgba(14,53,58,.18);',
    '--zl-title-grad:linear-gradient(90deg,#0e353a,#2a4a4d);--zl-title-ic:#0e353a;',
    '--zl-sub:#5d6f69;--zl-sec:#5d6f69;',
    '--zl-btn-bg:rgba(14,53,58,.07);--zl-btn-tx:#18383e;--zl-btn-ic:#48635f;',
    '--zl-btn-hov:rgba(14,53,58,.13);--zl-btn-hov-ic:#0e353a;--zl-btn-bord-hov:rgba(14,53,58,.45);',
    '--zl-hist-hov:rgba(14,53,58,.08);',
    '--zl-tag-ok:#0d6b57;--zl-tag-okbg:#d7efe6;',
    '--zl-tag-chat:#1d5c66;--zl-tag-chatbg:#dcebed;',
    /* 浅色主题：标签文字必须是深色（浅底 + 浅字 = 看不见） */
    '--zl-tag-warn:#7a4a06;--zl-tag-warnbg:#fbeecd;',
    '--zl-tag-mute:#55605f;--zl-tag-mutebg:#e6ebe9;',
    '--zl-del-hov:#c2410c;--zl-del-hovbg:#fde8d7;',
    '--zl-empty:#5d6f69;--zl-foot:#5d6f69;--zl-footbg:rgba(14,53,58,.06);',
    '--zl-badge:#0e353a;--zl-badgebg:#e7ece3;--zl-ring:#0e353a;--zl-ring-soft:rgba(14,53,58,.2);',
    '--zl-wb-grad:linear-gradient(180deg,rgba(250,245,222,.97) 0%,rgba(245,237,208,.97) 100%);--zl-wb-tx:#18383e;--zl-wb-head-tx:#0e353a;',
    '--zl-card-bg:rgba(255,255,255,.82);--zl-card-bord:rgba(14,53,58,.16);--zl-card-lab:#5d6f69;--zl-card-val:#0e353a;',
    /* 仿真大屏（自绘）：马路 / 画布 / 节点描边。⚠️ 与深色那套成对（孪生坑） */
    '--zl-road:rgba(24,56,62,.24);--zl-road-hi:rgba(180,140,60,.6);--zl-canvas:#eef2ec;',
    '--zl-node-tx:#0b1f24;',
    '--zl-table-bg:rgba(255,255,255,.66);--zl-td-bord:rgba(14,53,58,.13);--zl-td-k:#5d6f69;--zl-td-v:#0e353a;',
    '--zl-bar-track:rgba(14,53,58,.14);--zl-radar-bg:rgba(255,255,255,.68);--zl-radar-grid:#aebfba;--zl-radar-tx:#5d6f69;',
    '--zl-warn-bg:#fde8d7;--zl-warn-bord:#efb48a;--zl-warn-tx:#9a3412;',
    '--zl-input-bg:rgba(255,255,255,.88);--zl-input-bord:rgba(14,53,58,.3);--zl-input-tx:#0e353a;--zl-ph:#687a74;',
    '--zl-skel1:rgba(14,53,58,.08);--zl-skel2:rgba(14,53,58,.18);',
    '--zl-ghost-tx:#5d6f69;--zl-ghost-bord:rgba(14,53,58,.3);',
    '--zl-step-tx:rgba(14,53,58,.8);--zl-legend-tx:#5d6f69;--zl-map-bord:rgba(14,53,58,.24);--zl-plch-tx:#5d6f69;',
    '--zl-score:#0e353a;',
    '--zl-accent-grad:linear-gradient(90deg,#0e353a,#1d4a50);--zl-accent-tx:#fff;',
    '--zl-veya-tx:#0e353a;',
    '--zl-logo-c1:#0e353a;--zl-logo-c2:#2a4a4d;--zl-logo-ink:#ffffff;--zl-logo-eyes:#fff;--zl-logo-glow:rgba(14,53,58,.28);',
    'color-scheme:light;',
    '}',
    'html.dark{color-scheme:dark;}',
    /* 全站统一 CJK 字体 + 明暗底色 */
    'html,body{font-family:' + FONT + ' !important;background:var(--zl-page) !important;}',
    'body{letter-spacing:.1px;}',
    'textarea,input,button{font-family:' + FONT + ' !important;}',
    '.font-sans{font-family:' + FONT + ' !important;}',
    /* 浏览器表面：选区 / 滚动条 从调色板取色 */
    '::selection{background:rgba(224,192,132,.4);}',
    '::-webkit-scrollbar{width:9px;height:9px;}',
    '::-webkit-scrollbar-track{background:transparent;}',
    '::-webkit-scrollbar-thumb{background:rgba(125,145,175,.38);border-radius:6px;border:2px solid transparent;background-clip:content-box;}',
    'html:not(.dark) ::-webkit-scrollbar-thumb{background:rgba(30,64,120,.32);border-radius:6px;border:2px solid transparent;background-clip:content-box;}',
    /* 主内容区让出两栏（由 layout() 动态设置，不写死 !important，避免拖动/改宽后不跟随） */
    '.flex.flex-row.flex-grow.overflow-auto{margin-left:0;margin-right:0;}',
    /* 响应式：窄视口右栏/左栏转抽屉（保留 layout() 计算的聊天区宽度） */
    '@media (max-width:1100px){#zl-right{width:380px !important;}}',
    '@media (max-width:920px){#zl-right{width:340px !important;}}',
    /* ---- 左栏（下移避开顶部头部，保证明暗切换按钮可见） ---- */
    '#zl-rail{position:fixed;left:0;top:56px;bottom:0;width:' + LEFT_W + 'px;z-index:80;display:flex;flex-direction:column;',
    'background:var(--zl-rail-grad);color:var(--zl-wb-tx);',
    'font-family:' + FONT + ';box-shadow:3px 0 18px rgba(0,0,0,.4);overflow:hidden;}',
    '#zl-rail *{box-sizing:border-box;}',
    '#zl-rail .zl-head{padding:20px 18px 16px;border-bottom:1px solid var(--zl-rail-bord);',
    'background:radial-gradient(120% 90% at 0% 0%,rgba(201,164,92,.14),transparent 60%);}',
    '#zl-rail .zl-title{font-size:24px;font-weight:800;color:#fff;letter-spacing:.5px;display:flex;align-items:center;gap:8px;',
    'background:var(--zl-title-grad);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;}',
    '#zl-rail .zl-title .ic{-webkit-text-fill-color:var(--zl-title-ic);}',
    '#zl-rail .zl-sub{font-size:14px;color:var(--zl-sub);margin-top:4px;letter-spacing:1px;}',
    '#zl-rail .zl-body{flex:1;overflow-y:auto;padding:12px 12px 18px;}',
    '#zl-rail .zl-body::-webkit-scrollbar{width:5px;}',
    '#zl-rail .zl-body::-webkit-scrollbar-thumb{background:rgba(140,160,190,.3);border-radius:4px;border:none;}',
    '#zl-rail .zl-sec{font-size:13.5px;color:var(--zl-sec);margin:18px 8px 8px;letter-spacing:2px;font-weight:600;display:flex;align-items:center;gap:6px;}',
    '#zl-rail .zl-btn{display:flex;align-items:center;gap:9px;width:100%;min-width:0;text-align:left;',
    'padding:13px 14px;margin:6px 0;border-radius:12px;border:1px solid transparent;cursor:pointer;',
    'background:var(--zl-btn-bg);color:var(--zl-btn-tx);font-size:17px;line-height:1.35;',
    'font-family:' + FONT + ';font-weight:500;',
    'transition:transform .16s ease,background .18s ease,box-shadow .25s ease,border-color .25s ease;',
    'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
    '#zl-rail .zl-btn .zl-btn-txt{min-width:0;overflow:hidden;text-overflow:ellipsis;}',
    '#zl-rail .zl-btn .ic{color:var(--zl-btn-ic);flex:none;transition:color .18s ease,transform .18s ease;}',
    '#zl-rail .zl-btn:hover{background:var(--zl-btn-hov);transform:translateY(-1px);',
    'border-color:var(--zl-btn-bord-hov);box-shadow:0 6px 18px rgba(0,0,0,.35),0 0 0 1px rgba(224,192,132,.18);}',
    '#zl-rail .zl-btn:hover .ic{color:var(--zl-btn-hov-ic);transform:translateY(-1px);}',
    '#zl-rail .zl-btn:active{transform:translateY(0) scale(.985);}',
    '#zl-rail .zl-btn.primary{background:var(--zl-accent-grad);color:var(--zl-accent-tx);font-weight:700;',
    'box-shadow:0 4px 14px rgba(14,53,58,.35);}',
    '#zl-rail .zl-btn.primary .ic{color:var(--zl-accent-tx);opacity:.85;}',
    '#zl-rail .zl-btn.primary:hover{background:var(--zl-accent-grad);}',
    '#zl-rail .zl-btn.primary:hover .ic{color:#fff;}',
    '#zl-rail .zl-btn.disabled{opacity:.45;cursor:not-allowed;filter:saturate(.55);}',
    '#zl-rail .zl-btn.disabled:hover{transform:none;border-color:transparent;box-shadow:none;}',
    /* 反面教材（2026-09-18 欧文诉求 ①）：快速演示里除 4 个正面范例，再加真实低分案例。
       颜色直接复用已有的 --zl-warn-*（暗/亮两套都已定义），不新加变量 ——
       视觉上必须与正面范例**一眼可分**，否则用户点下去不知道自己在看反例。 */
    '#zl-rail .zl-demo-sub{margin:9px 2px 3px;padding-top:8px;border-top:1px dashed var(--zl-card-bord);',
    'font-size:12px;letter-spacing:.6px;color:var(--zl-sec);font-weight:700;}',
    '#zl-rail .zl-btn.bad{background:var(--zl-warn-bg);border-color:var(--zl-warn-bord);color:var(--zl-warn-tx);}',
    '#zl-rail .zl-btn.bad .ic{color:var(--zl-warn-tx);}',
    '#zl-rail .zl-btn.bad:hover{background:var(--zl-warn-bg);border-color:var(--zl-warn-tx);',
    'box-shadow:0 6px 18px rgba(0,0,0,.35),0 0 0 1px var(--zl-warn-bord);}',
    '#zl-rail .zl-btn.bad:hover .ic{color:var(--zl-warn-tx);}',
    '#zl-rail .zl-hist{margin:2px 0;}',
    '#zl-rail .zl-hist-row{display:flex;align-items:center;gap:4px;padding:9px 10px;border-radius:9px;transition:background .16s;}',
    '#zl-rail .zl-hist-row:hover{background:var(--zl-hist-hov);}',
    '#zl-rail .zl-hist-info{flex:1;min-width:0;cursor:pointer;}',
    '#zl-rail .zl-hist-title{font-size:15.5px;color:var(--zl-btn-tx);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
    '#zl-rail .zl-hist-ts{font-size:12.5px;color:var(--zl-sub);margin-top:2px;display:flex;align-items:center;gap:4px;}',
    '#zl-rail .zl-hist-ts .ic{color:var(--zl-sub);}',
    '#zl-rail .zl-tag{font-size:11.5px;padding:1px 7px;border-radius:8px;margin-right:5px;font-weight:600;}',
    '#zl-rail .zl-tag.ok{color:var(--zl-tag-ok);background:var(--zl-tag-okbg);}',
    '#zl-rail .zl-tag.chat{color:var(--zl-tag-chat);background:var(--zl-tag-chatbg);}',
    '#zl-right .zl-tag.warn{color:var(--zl-tag-warn);background:var(--zl-tag-warnbg);}',
    '#zl-right .zl-tag.mute{color:var(--zl-tag-mute);background:var(--zl-tag-mutebg);}',
    '#zl-rail .zl-del{width:32px;height:32px;flex:none;border-radius:8px;border:none;cursor:pointer;',
    'background:transparent;color:var(--zl-sub);display:flex;align-items:center;justify-content:center;',
    'transition:background .16s,color .16s,transform .16s;}',
    '#zl-rail .zl-del:hover{background:var(--zl-del-hovbg);color:var(--zl-del-hov);transform:scale(1.08);}',
    '#zl-rail .zl-empty{font-size:14px;color:var(--zl-empty);padding:10px 8px;}',
    '#zl-rail .zl-foot{padding:12px;border-top:1px solid var(--zl-rail-bord);font-size:13.5px;color:var(--zl-foot);',
    'text-align:center;background:var(--zl-footbg);}',
    '#zl-rail .zl-badge{font-size:12.5px;color:var(--zl-badge);background:var(--zl-badgebg);padding:1px 7px;',
    'border-radius:10px;margin-left:6px;}',
    /* ---- 右侧工作台 ---- */
    '#zl-right{position:fixed;right:0;top:56px;bottom:0;width:' + RIGHT_W + 'px;z-index:79;display:flex;flex-direction:column;',
    'background:var(--zl-wb-grad);color:var(--zl-wb-tx);',
    'font-family:' + FONT + ';border-left:1px solid var(--zl-rail-bord);box-shadow:-3px 0 18px rgba(0,0,0,.4);}',
    '#zl-right *{box-sizing:border-box;}',
    '#zl-right .zr-head{padding:14px 16px;border-bottom:1px solid var(--zl-rail-bord);position:relative;',
    'background:radial-gradient(120% 120% at 100% 0%,rgba(201,164,92,.14),transparent 60%);',
    'font-size:17px;font-weight:800;color:var(--zl-wb-head-tx);letter-spacing:.5px;display:flex;align-items:center;gap:8px;}',
    '#zl-right .zr-head .zr-head-ic{color:var(--zl-ring);display:flex;}',
    '#zl-right .zr-head .zr-busy{display:none;margin-left:auto;align-items:center;gap:6px;color:var(--zl-badge);font-size:13.5px;font-weight:500;}',
    '#zl-right .zr-head .zr-busy.on{display:flex;}',
    '#zl-right .zr-ring{animation:zr-spin 1s linear infinite;}',
    '@keyframes zr-spin{to{transform:rotate(360deg);}}',
    '#zr-progress{position:absolute;left:0;right:0;top:0;height:3px;overflow:hidden;display:none;z-index:6;pointer-events:none;}',
    '#zr-progress::before{content:"";position:absolute;left:-45%;width:45%;height:100%;',
    'background:linear-gradient(90deg,transparent,#e0c084,#c9a45c,transparent);animation:zr-slide 1.1s ease-in-out infinite;}',
    '@keyframes zr-slide{from{left:-45%;}to{left:110%;}}',
    '#zr-progress.on{display:block;}',
    '#zl-right .zr-body{flex:1;overflow-y:auto;padding:14px 14px 20px;}',
    '#zl-right .zr-body::-webkit-scrollbar{width:6px;}',
    '#zl-right .zr-body::-webkit-scrollbar-thumb{background:rgba(140,160,190,.3);border-radius:4px;border:none;}',
    '#zl-right .zr-body>*{animation:zr-fade .3s ease both;}',
    '@keyframes zr-fade{from{opacity:0;transform:translateY(5px);}to{opacity:1;transform:none;}}',
    '#zl-right .zr-placeholder{color:var(--zl-plch-tx);font-size:14.5px;text-align:center;padding:60px 18px;line-height:2;}',
    '#zl-right .zr-shop{font-size:16px;font-weight:800;color:var(--zl-wb-head-tx);margin-bottom:2px;line-height:1.4;}',
    '#zl-right .zr-sub{font-size:13.5px;color:var(--zl-sub);margin-bottom:10px;}',
    '#zl-right .zr-sec{font-size:15px;font-weight:800;color:var(--zl-badge);border-left:3px solid var(--zl-ring);',
    'padding-left:8px;margin:16px 0 8px;}',
    '#zl-right .zr-cards{display:grid;grid-template-columns:1fr 1fr;gap:8px;}',
    '#zl-right .zr-card{background:var(--zl-card-bg);border:1px solid var(--zl-card-bord);border-radius:12px;padding:11px 12px;',
    'box-shadow:0 1px 3px rgba(0,0,0,.25);transition:transform .16s,box-shadow .2s,border-color .2s;}',
    '#zl-right .zr-card:hover{transform:translateY(-1px);box-shadow:0 4px 14px rgba(0,0,0,.4);}',
    /* 候选商铺卡片（点击选择） */
    /* 2026-09-17 扩量：候选由 6 家增到 15 家 —— 单列会在窄栏里拖出很长一条，
       改成"自适应列数"（窄栏 1 列、宽栏 2 列），既不截断信息也不淹没选择。 */
    '#zl-right .cand-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:8px;}',
    /* 数据可信度标签（实测无标签 / 推算 / 未标） */
    '#zl-right .zl-tag{font-size:11.5px;padding:1px 7px;border-radius:8px;margin-right:5px;font-weight:600;}',
    '#zl-right .zl-tag.ok{color:var(--zl-tag-ok);background:var(--zl-tag-okbg);}',
    '#zl-right .zl-tag.chat{color:var(--zl-tag-chat);background:var(--zl-tag-chatbg);}',
    /* 房源性质标签（诉求③）：独立 class，与上面三态标签的 warn/ok 分开 */
    '#zl-right .zl-tag.dl-tr{color:var(--zl-tag-warn);background:var(--zl-tag-warnbg);}',
    '#zl-right .zl-tag.dl-rt{color:var(--zl-tag-ok);background:var(--zl-tag-okbg);}',
    '#zl-right .cand-card{display:flex;align-items:center;gap:10px;width:100%;min-width:0;text-align:left;cursor:pointer;',
    'background:var(--zl-card-bg);border:1px solid var(--zl-card-bord);border-radius:12px;padding:11px 12px;margin:8px 0;',
    'color:var(--zl-card-val);font-family:' + FONT + ';transition:transform .16s,box-shadow .2s,border-color .2s;}',
    '#zl-right .cand-card:hover{border-color:var(--zl-ring);box-shadow:0 4px 14px rgba(0,0,0,.4);transform:translateY(-1px);}',
    '#zl-right .cand-card:focus-visible{outline:2px solid var(--zl-ring);outline-offset:2px;}',
    '#zl-right .cand-card.picked{border-color:var(--zl-ring);box-shadow:0 0 0 2px var(--zl-ring-soft),0 4px 14px rgba(0,0,0,.4);}',
    '#zl-right .cand-no{flex:none;width:26px;height:26px;border-radius:50%;background:var(--zl-accent-grad);color:var(--zl-accent-tx);',
    'font-size:14px;font-weight:800;display:flex;align-items:center;justify-content:center;}',
    '#zl-right .cand-body{flex:1;min-width:0;}',
    '#zl-right .cand-name{font-size:15px;font-weight:700;color:var(--zl-card-val);display:flex;align-items:center;gap:6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
    '#zl-right .cand-info{font-size:13px;color:var(--zl-card-lab);margin-top:2px;}',
    '#zl-right .cand-addr{font-size:12.5px;color:var(--zl-card-lab);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
    /* ⚠️ 用 --zl-warn-tx（主题感知）而不是硬编码浅红：硬编码在浅色主题下
       是"浅红字 + 白底"，几乎看不见（浅色主题的既有坑）。 */
    '#zl-right .cand-warn{font-size:12px;color:var(--zl-warn-tx);margin-top:2px;}',
    '#zl-right .cand-go{flex:none;color:var(--zl-score);font-size:18px;font-weight:800;}',
    'html:not(.dark) #zl-right .cand-card{background:#fff;border-color:#eee8d5;color:#2c3e3b;}',
    'html:not(.dark) #zl-right .cand-name{color:#2c3e3b;}',
    /* 奶茶品牌选择卡片（复用 cand-card 骨架，追加品牌专属元素） */
    '#zl-right .brand-grid{display:block;gap:8px;}',
    '#zl-right .brand-card{display:flex;align-items:center;gap:10px;width:100%;min-width:0;text-align:left;cursor:pointer;',
    'background:var(--zl-card-bg);border:1px solid var(--zl-card-bord);border-radius:12px;padding:11px 12px;margin:8px 0;',
    'color:var(--zl-card-val);font-family:' + FONT + ';transition:transform .16s,box-shadow .2s,border-color .2s;}',
    '#zl-right .brand-card:hover{border-color:var(--zl-ring);box-shadow:0 4px 14px rgba(0,0,0,.4);transform:translateY(-1px);}',
    '#zl-right .brand-card:focus-visible{outline:2px solid var(--zl-ring);outline-offset:2px;}',
    '#zl-right .brand-card.picked{border-color:var(--zl-ring);box-shadow:0 0 0 2px var(--zl-ring-soft),0 4px 14px rgba(0,0,0,.4);}',
    '#zl-right .brand-card.self{background:rgba(201,164,92,.07);}',
    '#zl-right .brand-no{flex:none;width:26px;height:26px;border-radius:50%;background:var(--zl-accent-grad);color:var(--zl-accent-tx);',
    'font-size:14px;font-weight:800;display:flex;align-items:center;justify-content:center;}',
    '#zl-right .brand-body{flex:1;min-width:0;}',
    '#zl-right .brand-name{font-size:15px;font-weight:700;color:var(--zl-card-val);display:flex;align-items:center;gap:6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
    '#zl-right .brand-info{font-size:13px;color:var(--zl-card-lab);margin-top:2px;}',
    '#zl-right .brand-meta{font-size:12.5px;color:var(--zl-card-lab);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
    '#zl-right .brand-up{font-size:12.5px;margin-top:3px;color:var(--zl-tag-ok);}',
    '#zl-right .brand-up.ref{color:var(--zl-tag-chat);}',
    '#zl-right .brand-go{flex:none;color:var(--zl-score);font-size:18px;font-weight:800;}',
    '#zl-right .zl-tag.cal{color:var(--zl-tag-ok);background:var(--zl-tag-okbg);}',
    '#zl-right .zl-tag.ref{color:var(--zl-tag-chat);background:var(--zl-tag-chatbg);}',
    'html:not(.dark) #zl-right .brand-card{background:#fff;border-color:#eee8d5;color:#2c3e3b;}',
    'html:not(.dark) #zl-right .brand-name{color:#2c3e3b;}',
    /* 需求3：四品类推荐卡片（店铺优先分支，沿用品牌卡片骨架） */
    '#zl-right .cat-grid{display:block;gap:8px;}',
    '#zl-right .cat-card{display:flex;align-items:center;gap:10px;width:100%;min-width:0;text-align:left;cursor:pointer;',
    'background:var(--zl-card-bg);border:1px solid var(--zl-card-bord);border-radius:12px;padding:11px 12px;margin:8px 0;',
    'color:var(--zl-card-val);font-family:' + FONT + ';transition:transform .16s,box-shadow .2s,border-color .2s;}',
    '#zl-right .cat-card:hover{border-color:var(--zl-ring);box-shadow:0 4px 14px rgba(0,0,0,.4);transform:translateY(-1px);}',
    '#zl-right .cat-card:focus-visible{outline:2px solid var(--zl-ring);outline-offset:2px;}',
    '#zl-right .cat-card.picked{border-color:var(--zl-ring);box-shadow:0 0 0 2px var(--zl-ring-soft),0 4px 14px rgba(0,0,0,.4);}',
    '#zl-right .cat-no{flex:none;width:26px;height:26px;border-radius:50%;background:var(--zl-accent-grad);color:var(--zl-accent-tx);',
    'font-size:14px;font-weight:800;display:flex;align-items:center;justify-content:center;}',
    '#zl-right .cat-body{flex:1;min-width:0;}',
    '#zl-right .cat-name{font-size:15px;font-weight:700;color:var(--zl-card-val);display:flex;align-items:center;gap:6px;}',
    '#zl-right .cat-info{font-size:13px;color:var(--zl-card-lab);margin-top:2px;}',
    '#zl-right .cat-meta{font-size:12.5px;color:var(--zl-card-lab);margin-top:2px;}',
    '#zl-right .cat-reason{font-size:12.5px;color:var(--zl-tag-ok);margin-top:3px;}',
    '#zl-right .cat-go{flex:none;color:var(--zl-score);font-size:18px;font-weight:800;}',
    '#zl-right .cat-note{font-size:12px;color:var(--zl-card-lab);margin-top:10px;padding-top:8px;',
    'border-top:1px dashed var(--zl-card-bord);line-height:1.6;}',
    'html:not(.dark) #zl-right .cat-card{background:#fff;border-color:#eee8d5;color:#2c3e3b;}',
    'html:not(.dark) #zl-right .cat-name{color:#2c3e3b;}',
    /* 对比分析：勾选卡片 */
    '#zl-right .cp-grid{display:block;gap:8px;}',
    '#zl-right .cp-card{display:flex;align-items:flex-start;gap:10px;width:100%;min-width:0;cursor:pointer;',
    'background:var(--zl-card-bg);border:1px solid var(--zl-card-bord);border-radius:12px;padding:11px 12px;margin:8px 0;',
    'color:var(--zl-card-val);transition:border-color .16s,box-shadow .16s,background .16s;}',
    '#zl-right .cp-card:hover{border-color:var(--zl-ring-soft);}',
    '#zl-right .cp-card.picked{border-color:var(--zl-ring);box-shadow:0 0 0 2px var(--zl-ring-soft);background:rgba(201,164,92,.08);}',
    '#zl-right .cp-chk{position:absolute;opacity:0;width:0;height:0;margin:0;}',
    '#zl-right .cp-no{flex:none;width:24px;height:24px;border-radius:50%;background:var(--zl-card-bord);color:var(--zl-card-val);',
    'font-size:13px;font-weight:700;display:flex;align-items:center;justify-content:center;margin-top:1px;}',
    '#zl-right .cp-card.picked .cp-no{background:var(--zl-accent-grad);color:var(--zl-accent-tx);}',
    '#zl-right .cp-body{flex:1;min-width:0;}',
    '#zl-right .cp-name{font-size:15px;font-weight:700;color:var(--zl-card-val);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
    '#zl-right .cp-sub{font-size:12.5px;color:var(--zl-card-lab);margin-top:2px;}',
    '#zl-right .cp-score{font-size:13px;color:var(--zl-card-lab);margin-top:3px;}',
    '#zl-right .cp-score b{color:var(--zl-score);font-size:15px;}',
    '#zl-right .cp-verdict{color:var(--zl-tag-ok);}',
    '#zl-right .cp-dims{font-size:12px;color:var(--zl-card-lab);margin-top:3px;line-height:1.5;}',
    '#zl-right .cp-check{flex:none;width:20px;height:20px;border:2px solid var(--zl-card-bord);border-radius:6px;margin-top:2px;',
    'display:flex;align-items:center;justify-content:center;}',
    '#zl-right .cp-del{flex:none;width:30px;height:30px;border-radius:8px;border:none;cursor:pointer;',
    'background:transparent;color:var(--zl-sub);display:flex;align-items:center;justify-content:center;margin-top:0;padding:0;',
    'transition:background .16s,color .16s,transform .16s;}',
    '#zl-right .cp-del:hover{background:var(--zl-del-hovbg);color:var(--zl-del-hov);transform:scale(1.08);}',
    '#zl-right .cp-card.picked .cp-check{background:var(--zl-accent-grad);border-color:var(--zl-accent-grad);}',
    '#zl-right .cp-check .cp-tick{opacity:0;color:var(--zl-accent-tx);width:13px;height:13px;}',
    '#zl-right .cp-card.picked .cp-check .cp-tick{opacity:1;}',
    '#zl-right .cp-go{width:100%;padding:12px;margin-top:10px;border-radius:12px;border:none;cursor:pointer;',
    'background:var(--zl-accent-grad);color:var(--zl-accent-tx);font-size:15px;font-weight:700;font-family:' + FONT + ';',
    'transition:opacity .16s,transform .16s;}',
    '#zl-right .cp-go:disabled{opacity:.45;cursor:not-allowed;}',
    '#zl-right .cp-go:not(:disabled):hover{transform:translateY(-1px);}',
    'html:not(.dark) #zl-right .cp-card{background:#fff;border-color:#eee8d5;color:#2c3e3b;}',
    'html:not(.dark) #zl-right .cp-name{color:#2c3e3b;}',
    '#zl-right .zr-card .lab{font-size:12.5px;color:var(--zl-card-lab);}',
    '#zl-right .zr-card .val{font-size:21px;font-weight:800;color:var(--zl-card-val);margin-top:2px;}',
    '#zl-right .zr-card .val .u{font-size:12.5px;color:var(--zl-card-lab);font-weight:500;}',
    '#zl-right .zr-card.good{border-color:rgba(74,222,128,.35);}',
    '#zl-right .zr-card.good .val{color:#16a34a;}',
    '#zl-right .zr-card.bad{border-color:rgba(248,113,113,.35);}',
    '#zl-right .zr-card.bad .val{color:#ef4444;}',
    '#zl-right .zr-card.mid{border-color:rgba(250,204,21,.35);}',
    '#zl-right .zr-card.mid .val{color:#d97706;}',
    '#zl-right table{width:100%;border-collapse:collapse;font-size:13.5px;background:var(--zl-table-bg);border-radius:10px;overflow:hidden;}',
    '#zl-right table td{padding:7px 9px;border-bottom:1px solid var(--zl-td-bord);}',
    '#zl-right table td{font-variant-numeric:tabular-nums;}',
    '#zl-right table td.k{color:var(--zl-td-k);width:42%;}',
    '#zl-right table td.v{color:var(--zl-td-v);font-weight:700;text-align:right;}',
    '#zl-right .zr-cap{font-size:12px;color:var(--zl-sub);text-align:left;padding:0 2px 6px;caption-side:top;}',
    '#zl-right .zr-bar-fill{font-variant-numeric:tabular-nums;}',
    '#zl-right table tr:last-child td{border-bottom:none;}',
    '#zl-right .zr-bar-row{margin:7px 0;}',
    '#zl-right .zr-bar-label{font-size:13px;color:var(--zl-sub);margin-bottom:3px;}',
    '#zl-right .zr-bar-track{height:15px;background:var(--zl-bar-track);border-radius:7px;margin:2px 0;overflow:hidden;position:relative;}',
    '#zl-right .zr-bar-fill{height:100%;border-radius:7px;display:flex;align-items:center;justify-content:flex-end;',
    'padding-right:6px;color:#fff;font-size:10.5px;font-weight:700;min-width:2px;transition:width .4s;}',
    '#zl-right .zr-map img{width:100%;border-radius:12px;border:1px solid var(--zl-map-bord);}',
    '#zl-right .zr-legend{font-size:12.5px;color:var(--zl-legend-tx);margin-top:4px;}',
    /* 仿真数据看板（2026-09-20）：小人沿真实道路折线走。
       覆盖层叠在地图图上 —— 投影由服务端算好（engine.road_sim.project），
       前端**不重算**，否则两边一漂移，小人的轨迹就跑到地图外面去了。 */
    '#zl-right .zr-simstage{position:relative;line-height:0;}',
    '#zl-right .zr-simstage svg{position:absolute;left:0;top:0;width:100%;height:100%;}',
    '#zl-right .zr-sim-meta{display:flex;flex-wrap:wrap;gap:6px;margin-top:7px;}',
    '#zl-right .zr-chip{font-size:12px;color:var(--zl-sub);background:var(--zl-bar-track);border-radius:999px;padding:2px 9px;}',
    '#zl-right .zr-chip b{color:var(--zl-badge);}',
    '#zl-right .zr-warn{background:var(--zl-warn-bg);border:1px solid var(--zl-warn-bord);color:var(--zl-warn-tx);border-radius:10px;',
    'padding:8px 12px;font-size:13.5px;margin-top:8px;}',
    '#zl-right .zr-radar{display:flex;justify-content:center;background:var(--zl-radar-bg);border:1px solid var(--zl-card-bord);border-radius:12px;padding:6px;}',
    '#zl-right svg{max-width:100%;}',
    /* 骨架屏 */
    '#zl-right .zr-skeleton{padding:14px 2px;}',
    '#zl-right .zr-skeleton .sk{height:16px;border-radius:7px;margin:12px 0;',
    'background:linear-gradient(90deg,var(--zl-skel1) 25%,var(--zl-skel2) 50%,var(--zl-skel1) 75%);',
    'background-size:200% 100%;animation:zr-sk 1.2s linear infinite;}',
    '#zl-right .zr-skeleton .sk.sk1{width:60%;}',
    '#zl-right .zr-skeleton .sk.sk2{width:92%;}',
    '#zl-right .zr-skeleton .sk.sk3{width:80%;}',
    '#zl-right .zr-skeleton .sk.sk4{width:70%;}',
    '@keyframes zr-sk{from{background-position:200% 0;}to{background-position:-200% 0;}}',
    /* 结构化录入表单 */
    '#zl-right .zr-form{margin-top:4px;}',
    '#zl-right .zr-field{margin:12px 0;}',
    '#zl-right .zr-field label{display:block;font-size:14px;color:var(--zl-wb-tx);margin-bottom:6px;font-weight:600;}',
    '#zl-right .zr-field label .u{color:var(--zl-sub);font-weight:500;font-size:12.5px;}',
    '#zl-right .zr-field input{width:100%;padding:11px 12px;border-radius:10px;border:1px solid var(--zl-input-bord);',
    'background:var(--zl-input-bg);color:var(--zl-input-tx);font-size:16px;outline:none;',
    'transition:border-color .2s,box-shadow .2s,background .2s;}',
    '#zl-right .zr-field input:focus{border-color:var(--zl-ring);box-shadow:0 0 0 3px var(--zl-ring-soft);background:var(--zl-input-bg);}',
    '#zl-right .zr-field input::placeholder{color:var(--zl-ph);}',
    /* 口径说明 + 加盟费门槛提示（2026-09-17 诉求④）。
       ⚠️ 警示色必须用主题感知变量：硬编码的浅红/浅黄在浅色主题下看不清
       （--zl-warn-tx 在深色下是 #fda4a4、浅色下是 #9a3412）。 */
    '#zl-right .zr-note{font-size:12px;color:var(--zl-sub);margin-top:5px;line-height:1.5;}',
    '#zl-right .zr-floor{font-size:12px;line-height:1.55;margin-top:4px;}',
    '#zl-right .zr-floor.warn{color:var(--zl-warn-tx);font-weight:600;}',
    '#zl-right .zr-form-actions{display:flex;gap:10px;margin-top:18px;}',
    '#zl-right .zr-btn-primary{flex:1;padding:12px 14px;border:none;border-radius:10px;cursor:pointer;font-size:16px;font-weight:700;color:var(--zl-accent-tx);',
    'background:var(--zl-accent-grad);box-shadow:0 4px 14px rgba(14,53,58,.35);',
    'transition:transform .16s,box-shadow .2s,filter .2s;}',
    '#zl-right .zr-btn-primary:hover{transform:translateY(-1px);box-shadow:0 6px 18px rgba(14,53,58,.45);}',
    '#zl-right .zr-btn-primary:active{transform:translateY(0) scale(.985);}',
    '#zl-right .zr-btn-ghost{padding:12px 14px;border-radius:10px;cursor:pointer;font-size:16px;font-weight:600;',
    'background:transparent;color:var(--zl-ghost-tx);border:1px solid var(--zl-ghost-bord);transition:color .2s,border-color .2s,background .2s;}',
    '#zl-right .zr-btn-ghost:hover{color:var(--zl-wb-tx);border-color:var(--zl-input-bord);background:var(--zl-btn-bg);}',
    /* 执行过程步骤：内容半透明 + 等宽，与正式分析输出区分 */
    '.step[data-step-type] [role="region"]{opacity:.8;font-family:"SFMono-Regular","Consolas","JetBrains Mono",monospace !important;font-size:12.5px !important;}',
    '.step[data-step-type] [role="region"],.step[data-step-type] [role="region"] *{color:var(--zl-step-tx) !important;}',
    /* Lottie 动画替换 emoji */
    '.zl-lot{display:inline-block;width:19px;height:19px;vertical-align:-4px;margin:0 2px;}',
    '.zl-lot svg{width:100%;height:100%;}',
    /* 队列提示气泡 */
    '#zl-queue{position:fixed;left:' + (LEFT_W + 14) + 'px;top:14px;z-index:90;background:var(--zl-ring);color:#1c1404;padding:6px 12px;border-radius:8px;font-size:12px;box-shadow:0 4px 12px rgba(0,0,0,.3);font-family:' + FONT + ';}',
    /* 亮色模式：卡片色调加深，保证 ≥4.5:1（暗色保持原值，B 实测通过） */
    'html:not(.dark) #zl-right .zr-card.good .val{color:#15803d;}',
    'html:not(.dark) #zl-right .zr-card.bad .val{color:#b91c1c;}',
    'html:not(.dark) #zl-right .zr-card.mid .val{color:#b45309;}',
    /* 可访问性：自定义按钮/输入框的可见焦点环 */
    '#zl-rail .zl-btn:focus-visible,#zl-rail .zl-del:focus-visible,#zl-rail .zl-hist-info:focus-visible,',
    '#zl-right .zr-btn-primary:focus-visible,#zl-right .zr-btn-ghost:focus-visible',
    '{outline:2px solid var(--zl-ring);outline-offset:2px;}',
    '#zl-rail .zl-del:focus-visible{outline-offset:1px;border-radius:8px;}',
    '#zl-right .zr-field input:focus-visible{outline:2px solid var(--zl-ring);outline-offset:1px;}',
    /* ================= 新功能样式 ================= */
    /* 欢迎语艺术字（首条消息 h1 放大 + 主题自适应柔和渐变 + 展示字体；h5 为小字署名） */
    '[class*="message-content"] h1,[class*="Markdown"] h1,[class*="markdown"] h1',
    '{font-size:44px;font-weight:900;letter-spacing:2px;line-height:1.25;margin:12px 0 6px;',
    'font-family:"Georgia","Times New Roman","STKaiti","KaiTi","Noto Serif SC","Segoe UI",serif;',
    /* ⚠️ width:fit-content 是「渐变看得出」的前提（2026-09-17 欧文反馈"太不明显"的根因之一）：
       h1 是**块级**，默认撑满整行（~750px），而「早上好，BOSS」只占 ~260px。
       渐变按 750px 铺 → 文字只截到中间约 1/3 的色阶，几色被压成一片，看着就是单色。
       收缩到内容宽后，整个色阶恰好落在字面上。
       左对齐布局下不改变视觉位置（改前后都有实机截图对位）。 */
    'display:block;width:fit-content;max-width:100%;',
    /* 4 色标、暗部压到 #c9761a：金色系内部的**色相差很小**，"看得出渐变"只能靠
       **明度落差**撑（首末 ~99% → 暗部 ~52%，感知亮度极差 ≈47；旧版只有 ≈26，
       再叠加下面 fit-content + 背景留白两处压缩，就彻底看不见了）。 */
    'background:linear-gradient(100deg,#fffdf0 0%,#f9dd96 26%,#c9761a 56%,#ffeab4 100%);',
    /* ⚠️ 背景**只铺在文字区**：h1 的 padding box 里还夹着左右两枚花纹
       （::before / ::after 各 34px + 14px 间距 = 左右各 48px，合计 96px），
       默认背景铺满整个盒子 → 文字只吃到中间约 56% 的色阶，依然不够明显。
       用 calc 把背景宽度扣掉 96px、起点右移 48px，整个色阶 100% 落在字面上。
       ⚠️ 96px / 48px 与花纹尺寸（34px + 14px 各一）是**联动**的：
          改花纹尺寸必须同步改这两个数，否则渐变会跑到花纹底下或截断字尾。
          verify_ui §8 有断言把这个联动钉住。 */
    'background-size:calc(100% - 96px) 100%;background-position:48px 50%;background-repeat:no-repeat;',
    '-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;',
    /* ⚠️ 这里**不能用 text-shadow**：字身是 -webkit-text-fill-color:transparent 的，
       阴影会从字形**内部**透出来，把渐变糊成一片（"看不出渐变"的第二主因）。
       drop-shadow 作用在渲染结果上、不穿字身：既有金属光晕，又不污染字面色。 */
    'filter:drop-shadow(0 3px 16px rgba(240,201,120,.34));',
    '--zl-pin:' + pinURI('#e5c98a') + ';}',
    'html:not(.dark) [class*="message-content"] h1,html:not(.dark) [class*="Markdown"] h1,html:not(.dark) [class*="markdown"] h1',
    /* 浅色主题：米黄底上必须用**深色系**才看得清，所以走「近黑墨绿 → 青绿 → 橄榄金 → 金」
       的跨色相路径（色相 190°→45°），比深色主题的纯金色阶跨度更大才压得住浅底。 */
    '{background:linear-gradient(100deg,#04303a 0%,#125f57 38%,#8a7d2c 70%,#c9a24a 100%);',
    '-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;',
    'filter:drop-shadow(0 3px 12px rgba(14,53,58,.20));',
    '--zl-pin:' + pinURI('#a8843c') + ';}',
    /* 诉求⑤：欢迎语标题两侧的定位针花纹（2026-09-17 欧文选 B）。
       走 h1 的 ::before / ::after 贴内联 SVG，不往 welcome 文案里塞 HTML
       （Chainlit 的 markdown 会 sanitize）。纯 CSS 还白捡两个好处：
       历史会话回放同一条欢迎语时花纹自动生效、后端文案一个字都不用动。
       ⚠️ 颜色只能靠 --zl-pin 传（data-URI 里写不了 var()），所以深浅各一份 SVG。
       ⚠️ 34px 是配 44px 标题的固定值，且**故意不进 --zl-fs 缩放层** ——
          标题字号本身就不在缩放层里，花纹进去了就会两边不同步。
          将来谁给 h1 加缩放，必须同时把这两条改成 calc()。 */
    '[class*="message-content"] h1::before,[class*="Markdown"] h1::before,[class*="markdown"] h1::before,',
    '[class*="message-content"] h1::after,[class*="Markdown"] h1::after,[class*="markdown"] h1::after',
    '{content:"";display:inline-block;width:34px;height:34px;vertical-align:middle;',
    'background-image:var(--zl-pin);background-repeat:no-repeat;background-position:center;background-size:contain;',
    'background-clip:border-box;}',
    '[class*="message-content"] h1::before,[class*="Markdown"] h1::before,[class*="markdown"] h1::before{margin-right:14px;}',
    '[class*="message-content"] h1::after,[class*="Markdown"] h1::after,[class*="markdown"] h1::after{margin-left:14px;}',
    '[class*="message-content"] h5,[class*="Markdown"] h5,[class*="markdown"] h5',
    '{font-size:14.5px;color:var(--zl-sub);font-weight:500;letter-spacing:2px;margin:2px 0 20px;}',
    /* 两栏头部 = 拖动手柄 */
    '#zl-rail .zl-head,#zl-right .zr-head{cursor:grab;user-select:none;-webkit-user-select:none;}',
    '#zl-rail .zl-head:active,#zl-right .zr-head:active{cursor:grabbing;}',
    /* 左栏二级分组（下拉） */
    '#zl-rail .zl-group{margin:4px 0;}',
    '#zl-rail .zl-group-hd{display:flex;align-items:center;gap:8px;padding:10px 8px;border-radius:10px;cursor:pointer;',
    'color:var(--zl-sec);font-size:14.5px;font-weight:800;letter-spacing:1px;transition:background .16s;user-select:none;}',
    '#zl-rail .zl-group-hd:hover{background:var(--zl-hist-hov);}',
    '#zl-rail .zl-group-hd .zl-chev{margin-left:auto;color:var(--zl-sub);transition:transform .2s;display:flex;}',
    '#zl-rail .zl-group.open .zl-group-hd .zl-chev{transform:rotate(90deg);}',
    '#zl-rail .zl-group-bd{max-height:0;overflow:hidden;transition:max-height .28s ease;}',
    '#zl-rail .zl-group.open .zl-group-bd{max-height:1400px;}',
    '#zl-rail .zl-group-bd .zl-btn{margin:5px 0;padding:11px 13px;font-size:15px;}',
    '#zl-rail .zl-group[data-group="hist"] .zl-group-bd{max-height:0;overflow:hidden;}',
    '#zl-rail .zl-group[data-group="hist"].open .zl-group-bd{max-height:420px;overflow-y:auto;}',
    '#zl-rail .zl-group[data-group="hist"].open .zl-group-bd::-webkit-scrollbar{width:4px;}',
    /* 切换模型下拉（紧凑：贴合文字宽度） */
    '.zl-model{display:inline-flex;align-items:center;gap:4px;margin:0 8px 0 2px;padding:4px 8px;border-radius:9px;',
    'border:1px solid var(--zl-input-bord);background:var(--zl-card-bg);color:var(--zl-wb-tx);font-size:12.5px;cursor:pointer;vertical-align:middle;',
    'box-shadow:0 1px 4px rgba(0,0,0,.18);transition:border-color .2s,box-shadow .2s;}',
    '.zl-model:hover{border-color:var(--zl-ring);box-shadow:0 2px 8px var(--zl-ring-soft);}',
    '.zl-model span{white-space:nowrap;font-weight:600;color:var(--zl-sub);}',
    '.zl-model select{background:transparent;border:none;color:var(--zl-wb-tx);font-size:12.5px;font-weight:600;outline:none;cursor:pointer;font-family:' + FONT + ';max-width:none;padding:0 2px;}',
    '.zl-model select:focus-visible{outline:2px solid var(--zl-ring);outline-offset:2px;border-radius:6px;}',
    '.zl-model select option{color:#0f172a;background:#fff;}',
    /* 需求4：「自由对话」开关（与模型下拉同一行） */
    '.zl-freechat{display:inline-flex;align-items:center;margin:0 8px 0 2px;padding:4px 9px;border-radius:9px;',
    'border:1px solid var(--zl-input-bord);background:var(--zl-card-bg);color:var(--zl-sub);font-size:12.5px;font-weight:600;',
    'cursor:pointer;font-family:' + FONT + ';vertical-align:middle;box-shadow:0 1px 4px rgba(0,0,0,.18);',
    'transition:border-color .18s,box-shadow .18s,color .18s,background .18s;}',
    '.zl-freechat:hover{border-color:var(--zl-ring);box-shadow:0 2px 8px var(--zl-ring-soft);}',
    '.zl-freechat:focus-visible{outline:2px solid var(--zl-ring);outline-offset:2px;}',
    '.zl-freechat.on{background:var(--zl-ring-soft);border-color:var(--zl-ring);color:var(--zl-wb-tx);}',
    'html:not(.dark) .zl-freechat{background:#fff;}',
    /* 输入框（composer）整体美化 */
    '[class*="rounded-3xl"][class*="bg-accent"]{border-radius:18px !important;border:1px solid var(--zl-input-bord) !important;',
    'box-shadow:0 8px 30px rgba(0,0,0,.16) !important;transition:border-color .25s,box-shadow .25s;}',
    '[class*="rounded-3xl"][class*="bg-accent"]:focus-within{border-color:var(--zl-ring) !important;',
    'box-shadow:0 8px 30px rgba(0,0,0,.18),0 0 0 3px var(--zl-ring-soft) !important;}',
    /* 发送按钮：品牌藏青金（覆盖 Chainlit bg-primary；运行中不打标，停止钮保持红色） */
    'button.zl-send{background:var(--zl-accent-grad) !important;border-color:rgba(201,164,92,.5) !important;color:var(--zl-accent-tx) !important;',
    'box-shadow:0 3px 10px rgba(14,53,58,.35) !important;transition:transform .16s,box-shadow .2s,background .2s !important;}',
    'button.zl-send:hover{background:linear-gradient(90deg,#c9a45c,#ddbd82) !important;box-shadow:0 5px 14px rgba(14,53,58,.45) !important;transform:translateY(-1px);}',
    'button.zl-send:active{transform:translateY(0) scale(.96);}',
    /* 左右两栏：边框柔化（圆角 + 柔和阴影） */
    '#zl-rail{border-radius:0 16px 16px 0;border-right:1px solid var(--zl-rail-bord);',
    'box-shadow:3px 0 24px rgba(0,0,0,.28),0 0 0 1px rgba(255,255,255,.03) inset;}',
    '#zl-right{border-radius:16px 0 0 16px;border-left:1px solid var(--zl-rail-bord);',
    'box-shadow:-3px 0 24px rgba(0,0,0,.28),0 0 0 1px rgba(255,255,255,.03) inset;}',
    'html:not(.dark) #zl-rail{box-shadow:3px 0 22px rgba(14,53,58,.16),0 0 0 1px rgba(255,255,255,.4) inset;}',
    'html:not(.dark) #zl-right{box-shadow:-3px 0 22px rgba(14,53,58,.16),0 0 0 1px rgba(255,255,255,.4) inset;}',
    /* 栏边缘拖拽改宽把手 */
    '.zl-resize{position:absolute;top:0;bottom:0;width:7px;z-index:95;cursor:col-resize;',
    'background:transparent;transition:background .18s;}',
    '.zl-resize::after{content:"";position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);',
    'width:3px;height:56px;border-radius:3px;background:var(--zl-ring);opacity:0;transition:opacity .2s;}',
    '.zl-resize:hover::after,.zl-resize.dragging::after{opacity:1;}',
    '.zl-resize:hover,.zl-resize.dragging{background:var(--zl-ring-soft);}',
    '#zl-rail .zl-resize{right:-3px;}',
    '#zl-right .zl-resize{left:-3px;}',
    /* 置顶头（中间栏顶部）——2026-09-18 策要求去掉淡色实底（那块压住罗盘水印的长方块）。
       它挂在外层列容器、不在内层滚动区，消息不会从它下面穿过，透明不影响可读性 */
    '#zl-veya{position:sticky;top:0;z-index:20;display:flex;align-items:center;gap:14px;',
    'padding:14px 22px 10px;}',
    '#zl-veya .zv-logo{width:64px;height:64px;flex:none;filter:drop-shadow(0 5px 16px var(--zl-logo-glow));animation:zv-bob 4s ease-in-out infinite;}',
    '@keyframes zv-bob{0%,100%{transform:translateY(0)}50%{transform:translateY(-3px)}}',
    '#zl-veya .zv-name{font-size:44px;font-weight:600;letter-spacing:2.5px;line-height:1;',
    'font-family:"Playfair Display","Cormorant Garamond","Noto Serif SC","Georgia","Times New Roman",serif;',
    'color:var(--zl-veya-tx);text-shadow:0 4px 18px rgba(14,53,58,.16);}',
    '#zl-veya .zv-tag{font-size:12.5px;color:var(--zl-sub);letter-spacing:2px;margin-top:5px;font-weight:500;}',
    '#zl-veya .zv-badge{margin-left:auto;font-size:11.5px;color:var(--zl-badge);background:var(--zl-badgebg);',
    'padding:3px 10px;border-radius:20px;letter-spacing:1px;white-space:nowrap;border:1px solid transparent;}',
    /* 执行步骤：柔化左侧引导线 + 圆角 + 图标圆角化（配色与米色/藏青背景协调） */
    '.step[data-step-type]{border-radius:12px !important;border-left:none !important;position:relative;}',
    '.step[data-step-type] [role="button"],[data-step-type] button{cursor:pointer;}',
    '.step[data-step-type] [class*="step-icon"],.step[data-step-type] [class*="status"],.step[data-step-type] [class*="indicator"],.step[data-step-type] span[data-state]',
    '{border-radius:9px !important;}',
    '.step[data-step-type="run"] [data-state="closed"] > *:first-child,.step[data-step-type] [data-state] svg{color:#b8860b !important;}',
    '.step[data-step-type="tool"] [data-state] svg{color:#b8860b !important;}',
    'html:not(.dark) .step[data-step-type] [data-state] svg{color:#b8860b !important;}',
    'html:not(.dark) .step[data-step-type="tool"] [data-state] svg{color:#b8860b !important;}',
    '.step[data-step-type="run"]{background:linear-gradient(90deg,var(--zl-btn-bg),transparent 65%) !important;}',
    /* 步骤过程内任何左侧/顶部竖线 → 品牌金（匹配整体金色主题，杜绝 蓝/玫红/红 引导线） */
    '.step [data-step-type] *{border-left-color:#b8860b !important;border-top-color:#b8860b !important;}',
    /* 行内代码 / 关键词配色微调，更贴合主题 */
    'code{background:var(--zl-btn-bg) !important;border-radius:6px;padding:1px 5px;color:var(--zl-ring) !important;font-size:.92em;}',
    /* 对比双雷达配色（蓝/红→蓝/紫红柔和版） */
    '#zl-right .zr-sec{border-left:3px solid var(--zl-ring);}',
    /* 输入框下方免责声明 */
    '.zl-disclaimer{display:block;text-align:center;font-size:12px;color:var(--zl-sub);padding:8px 14px 2px;line-height:1.6;}',
    /* 齿轮设置按钮 + 全屏遮罩 */
    '#zl-gear{position:fixed;right:16px;top:10px;z-index:125;width:38px;height:38px;border-radius:10px;',
    'border:1px solid var(--zl-input-bord);background:var(--zl-card-bg);color:var(--zl-wb-tx);',
    'display:flex;align-items:center;justify-content:center;cursor:pointer;box-shadow:0 3px 12px rgba(0,0,0,.28);}',
    '#zl-gear:hover svg{transform:rotate(90deg);}',
    '#zl-gear svg{transition:transform .35s;}',
    '#zl-settings{position:fixed;inset:0;z-index:300;background:rgba(6,10,22,.62);display:none;',
    'align-items:center;justify-content:center;backdrop-filter:blur(4px);}',
    '#zl-settings.open{display:flex;}',
    '#zl-settings .zl-set-panel{width:min(660px,94vw);max-height:88vh;overflow:auto;border-radius:18px;',
    'background:var(--zl-wb-grad);color:var(--zl-wb-tx);box-shadow:0 24px 70px rgba(0,0,0,.55);',
    'border:1px solid var(--zl-rail-bord);padding:24px;}',
    '#zl-settings .zl-set-hd{display:flex;align-items:center;gap:10px;margin-bottom:18px;}',
    '#zl-settings .zl-set-back{background:none;border:none;color:var(--zl-sub);cursor:pointer;display:flex;padding:4px;}',
    '#zl-settings .zl-set-back:hover{color:var(--zl-wb-tx);}',
    '#zl-settings .zl-set-title{font-size:20px;font-weight:800;flex:1;}',
    '#zl-settings .zl-set-close{width:34px;height:34px;border-radius:9px;border:1px solid var(--zl-input-bord);',
    'background:var(--zl-card-bg);color:var(--zl-wb-tx);cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0;}',
    '#zl-settings .zl-set-menu{display:flex;flex-direction:column;gap:11px;}',
    '#zl-settings .zl-set-item{display:flex;align-items:center;gap:12px;padding:15px 16px;border-radius:12px;',
    'border:1px solid var(--zl-input-bord);background:var(--zl-card-bg);cursor:pointer;font-size:16px;font-weight:600;',
    'transition:background .16s,border-color .2s,transform .15s;}',
    '#zl-settings .zl-set-item:hover{background:var(--zl-btn-hov);border-color:var(--zl-ring);transform:translateY(-1px);}',
    '#zl-settings .zl-set-item .ic{color:var(--zl-ring);}',
    '#zl-settings .zl-set-item .arr{margin-left:auto;color:var(--zl-sub);}',
    '#zl-settings .zl-set-sub{color:var(--zl-sub);font-size:13.5px;line-height:1.9;}',
    '#zl-settings .zl-set-opt{display:flex;gap:10px;flex-wrap:wrap;margin-top:12px;}',
    '#zl-settings .zl-set-opt button{padding:11px 20px;border-radius:11px;border:1px solid var(--zl-input-bord);',
    'background:var(--zl-card-bg);color:var(--zl-wb-tx);font-size:15px;cursor:pointer;transition:border-color .16s,background .16s,color .16s;}',
    '#zl-settings .zl-set-opt button:hover{border-color:var(--zl-ring);}',
    '#zl-settings .zl-set-opt button.on{background:var(--zl-accent-grad);color:var(--zl-accent-tx);border-color:transparent;font-weight:700;}',
    '#zl-settings .zl-set-note{font-size:13px;color:var(--zl-sub);margin-top:14px;line-height:1.7;}',
    /* 历史会话独立页 / 知识库页（中间栏全页覆盖，z 在设置之下） */
    '#zl-page-ov{position:fixed;left:0;right:0;top:56px;bottom:0;z-index:2000;display:none;flex-direction:column;',
    'background:var(--zl-chat);color:var(--zl-wb-tx);}',
    '#zl-page-ov.open{display:flex;}',
    '#zl-page-ov .zl-pg-hd{display:flex;align-items:center;gap:10px;padding:14px 18px;border-bottom:1px solid var(--zl-rail-bord);',
    'background:var(--zl-wb-grad);}',
    '#zl-page-ov .zl-pg-title{font-size:17px;font-weight:800;flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
    '#zl-page-ov .zl-pg-close{width:34px;height:34px;border-radius:9px;border:1px solid var(--zl-input-bord);background:var(--zl-card-bg);color:var(--zl-wb-tx);cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0;}',
    '#zl-page-ov .zl-pg-body{flex:1;overflow-y:auto;padding:20px 26px;}',
    /* ⚠️ `.zl-pg-cta` / `.zl-pg-msg` / `.zl-pg-sum` 三条样式已于 2026-09-17 删除（§2）：
       它们专供"历史会话只读中间页"（`renderHistPage`）—— 那条路径改成
       "聊天区回放"后，DOM 里再也不会出现这三个 class，留着就是死样式；
       更糟的是它们会让后来人以为"历史页还在覆盖层里"。
       `--zl-fs` 缩放层里对应的 3 条（.zl-pg-msg .txt/.who、.zl-pg-sum）
       必须**一起删**，否则字号刻度指向不存在的元素（本项目的老坑：
       缩放层与子页面不同步，改一处忘另一处）。 */
    '#zl-page-ov .zl-kb-sec{font-size:16.5px;font-weight:800;color:var(--zl-badge);border-left:3px solid var(--zl-ring);padding-left:8px;margin:20px 0 9px;}',
    '#zl-page-ov .zl-kb-theory{margin:9px 0;background:var(--zl-card-bg);border:1px solid var(--zl-card-bord);border-radius:12px;',
    'padding:14px 16px;font-size:15.5px;line-height:1.9;}',
    '#zl-page-ov .zl-kb-theory a{color:var(--zl-ring);text-decoration:underline;}',
    /* 商业理论：多方块卡片排布（大小贴合文字，一行多个，不留大空白） */
    '#zl-page-ov .zl-kb-cards{display:flex;flex-wrap:wrap;gap:10px;}',
    '#zl-page-ov .zl-kb-card{flex:0 1 auto;width:auto;max-width:300px;min-width:176px;box-sizing:border-box;',
    'background:var(--zl-card-bg);border:1px solid var(--zl-card-bord);border-radius:12px;',
    'padding:12px 14px;font-size:14.5px;line-height:1.78;}',
    '#zl-page-ov .zl-kb-card b{display:block;margin-bottom:5px;color:var(--zl-card-val);font-size:15px;line-height:1.45;}',
    '#zl-page-ov .zl-kb-card a{color:var(--zl-ring);text-decoration:underline;display:inline-block;margin:6px 10px 0 0;font-size:14px;}',
    '#zl-page-ov .zl-kb-link{display:inline-block;margin-right:14px;color:var(--zl-ring);font-size:14px;}',
    /* 知识库·「选址打分依据」页新增三种排版元素：公式块 / 数据表 / 提示块。
       加它们的原因：原页面只有"一段段纯文字"，写不下 Huff 结构式、四维权重表、
       回归系数表这类内容 —— 而需求正是"把这页的打分依据大量写实"。 */
    '#zl-page-ov .zl-kb-fml{margin:9px 0;padding:10px 13px;border-radius:10px;background:var(--zl-ring-soft);',
    'border:1px dashed var(--zl-card-bord);font-size:15px;line-height:2;color:var(--zl-wb-tx);',
    'font-family:Consolas,Menlo,monospace;white-space:pre-wrap;word-break:break-word;overflow-x:auto;}',
    '#zl-page-ov .zl-kb-tb{width:100%;border-collapse:collapse;margin:10px 0 2px;font-size:14.5px;}',
    '#zl-page-ov .zl-kb-tb th,#zl-page-ov .zl-kb-tb td{border:1px solid var(--zl-card-bord);',
    'padding:6px 9px;text-align:left;vertical-align:top;line-height:1.7;}',
    '#zl-page-ov .zl-kb-tb th{background:var(--zl-ring-soft);font-weight:800;color:var(--zl-card-val);white-space:nowrap;}',
    '#zl-page-ov .zl-kb-tb td{color:var(--zl-wb-tx);}',
    '#zl-page-ov .zl-kb-note{margin:9px 0 2px;padding:9px 12px;border-radius:10px;',
    'border-left:3px solid var(--zl-ring);background:var(--zl-ring-soft);',
    'font-size:14.5px;line-height:1.85;color:var(--zl-sub);}',
    /* ---- 专家系统卡片页（左侧导航「专家系统」→ 覆盖层，严格三行三列） ---- */
    '#zl-page-ov .zl-ex-wrap{display:flex;flex-direction:column;min-height:100%;}',
    '#zl-page-ov .zl-ex-intro{background:var(--zl-card-bg);border:1px solid var(--zl-card-bord);border-radius:12px;',
    'padding:13px 16px;font-size:15px;line-height:1.9;margin-bottom:16px;color:var(--zl-wb-tx);}',
    /* 用 grid 而不是 flex-wrap：需求是"三行三列"，flex 自适应在宽屏会挤成一行 4-5 个 */
    /* flex:1 + grid-auto-rows 1fr：让三行平分剩余高度，卡片自然长高 —— 否则底部会空一大块 */
    '#zl-page-ov .zl-ex-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;',
    'align-items:stretch;flex:1;grid-auto-rows:minmax(146px,1fr);}',
    '#zl-page-ov .zl-ex-card{display:flex;flex-direction:column;gap:6px;text-align:left;cursor:pointer;height:100%;',
    'background:var(--zl-card-bg);border:1px solid var(--zl-card-bord);border-radius:14px;padding:14px 15px;',
    'color:var(--zl-wb-tx);font-family:' + FONT + ';transition:transform .16s,border-color .18s,box-shadow .2s;}',
    '#zl-page-ov .zl-ex-card:hover{transform:translateY(-2px);border-color:var(--zl-ring);box-shadow:0 8px 24px rgba(0,0,0,.34);}',
    '#zl-page-ov .zl-ex-card:focus-visible{outline:2px solid var(--zl-ring);outline-offset:2px;}',
    '#zl-page-ov .zl-ex-card.cur{border-color:var(--zl-ring);box-shadow:0 0 0 2px var(--zl-ring-soft);}',
    '#zl-page-ov .zl-ex-top{display:flex;align-items:center;gap:7px;font-size:12.5px;color:var(--zl-sub);}',
    '#zl-page-ov .zl-ex-no{width:22px;height:22px;border-radius:50%;background:var(--zl-accent-grad);color:var(--zl-accent-tx);',
    'font-size:12.5px;font-weight:800;display:flex;align-items:center;justify-content:center;flex:none;}',
    '#zl-page-ov .zl-ex-cur{margin-left:auto;color:var(--zl-ring);font-weight:800;}',
    /* ⚠️ 2026-09-18 欧文诉求：**定位（岗位名）必须最显眼，拟人名退居次要**。
       改前是反的（人名 19.5px/800 主色、定位 14px 次色）——“这是谁”压过了“他干什么”。
       类名语义不变：`.zl-ex-name` 里装的就是 `name` 字段（=定位，如“选址评估师”），
       拟人名（`alias`，如“沈砚舟”）收进 `.zl-ex-tit` 做次要标签。 */
    '#zl-page-ov .zl-ex-name{font-size:20px;font-weight:800;color:var(--zl-card-val);line-height:1.3;}',
    '#zl-page-ov .zl-ex-name .zl-ex-tit{font-size:13px;font-weight:500;color:var(--zl-sub);margin-left:6px;}',
    '#zl-page-ov .zl-ex-blurb{font-size:14.5px;line-height:1.8;color:var(--zl-wb-tx);flex:1;}',
    '#zl-page-ov .zl-ex-ex{font-size:13px;color:var(--zl-sub);border-top:1px dashed var(--zl-card-bord);padding-top:8px;line-height:1.65;}',
    /* ---- 仿真大屏（自绘）：基础样式 ----
       ⚠️ 这些**不带 font-size** 或只给 SVG 用的默认字号；
       真正的字号统一写在下面的缩放层里（写在后面才能覆盖这里，不会反过来被盖掉）。 */
    /* 大屏页：整个子页面撑满 —— 上下两条信息带压紧，SVG 吃掉剩余高度。
       （策 2026-09-21：「可以把整个子页面占满，大一点，少留点空白」） */
    '#zl-page-ov .zl-pg-body.zl-pg-sim{display:flex;flex-direction:column;gap:8px;',
    '  padding:12px 16px;overflow:hidden;}',
    '#zl-page-ov .sbx-canvas{display:block;width:100%;height:100%;min-height:0;flex:1 1 auto;',
    '  border-radius:14px;border:1px solid var(--zl-card-bord);background:var(--zl-canvas);}',
    /* 大屏「挑哪一次」卡片页（与对比分析同款交互，2026-09-21） */
    '#zl-page-ov .sbx-hint{color:var(--zl-card-lab);line-height:1.6;margin:2px 0 12px;max-width:900px;}',
    '#zl-page-ov .sbx-cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:12px;}',
    '#zl-page-ov .sbx-card{display:flex;flex-direction:column;gap:3px;text-align:left;cursor:pointer;',
    '  background:var(--zl-card-bg);border:1px solid var(--zl-card-bord);border-radius:12px;padding:12px 14px;',
    '  font-family:' + FONT + ';color:var(--zl-card-val);transition:transform .14s ease,border-color .18s ease;}',
    '#zl-page-ov .sbx-card:hover{transform:translateY(-2px);border-color:var(--zl-ring);}',
    '#zl-page-ov .sbx-card .sbx-c-shop{font-weight:800;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
    '#zl-page-ov .sbx-card .sbx-c-meta{color:var(--zl-card-lab);}',
    '#zl-page-ov .sbx-card .sbx-c-tot{color:var(--zl-card-lab);}',
    '#zl-page-ov .sbx-card .sbx-c-tot b{color:var(--zl-card-val);}',
    '#zl-page-ov .sbx-card .sbx-c-vd{color:var(--zl-card-lab);}',
    '#zl-page-ov .sbx-card .sbx-c-off{color:var(--zl-card-lab);opacity:.8;}',
    '#zl-page-ov .sbx-card .sbx-c-go{margin-top:3px;color:var(--zl-ring);font-weight:800;align-self:flex-start;}',
    '#zl-page-ov .sbx-card.off{cursor:not-allowed;opacity:.5;filter:saturate(.5);}',
    '#zl-page-ov .sbx-card.off:hover{transform:none;border-color:var(--zl-card-bord);}',
    '#zl-page-ov .sbx-back{cursor:pointer;margin:0 0 8px;padding:6px 13px;border-radius:9px;',
    '  border:1px solid var(--zl-card-bord);background:var(--zl-card-bg);color:var(--zl-card-val);',
    '  font-family:' + FONT + ';}',
    '#zl-page-ov .sbx-back:hover{border-color:var(--zl-ring);}',
    /* 顶部信息带：一行 chip（让位给画面） */
    '#zl-page-ov .sbx-src{display:flex;flex-wrap:wrap;gap:5px 14px;align-items:baseline;}',
    '#zl-page-ov .sbx-where{color:var(--zl-card-val);}',
    '#zl-page-ov .sbx-tag{display:inline-flex;align-items:baseline;gap:5px;color:var(--zl-card-lab);}',
    '#zl-page-ov .sbx-tag i{font-style:normal;opacity:.7;}',
    '#zl-page-ov .sbx-hud{display:flex;flex-wrap:wrap;gap:8px;align-items:stretch;}',
    '#zl-page-ov .sbx-kpi{background:var(--zl-card-bg);border:1px solid var(--zl-card-bord);',
    '  border-radius:10px;padding:4px 12px;display:flex;align-items:baseline;gap:7px;}',
    '#zl-page-ov .sbx-kpi .k{color:var(--zl-card-lab);}',
    '#zl-page-ov .sbx-kpi b{color:var(--zl-card-val);line-height:1.15;}',
    '#zl-page-ov .sbx-legend{display:flex;flex-wrap:wrap;gap:5px 14px;color:var(--zl-card-lab);}',
    '#zl-page-ov .sbx-lg{display:inline-flex;align-items:center;gap:6px;}',
    '#zl-page-ov .sbx-lg i{width:11px;height:11px;border-radius:3px;display:inline-block;flex:none;}',
    '#zl-page-ov .sbx-note{color:var(--zl-card-lab);line-height:1.55;max-height:4.6em;overflow:hidden;}',
    /* ⚠️ SVG 里 font-size 的 px 值会被解释成**用户单位** ⇒ 天然随 viewBox 缩放。
       配合缩放层的 var(--zl-fs)，用户放大字体时画面里的字也跟着变大。 */
    '#zl-page-ov .sbx-canvas text{font-family:' + FONT + ';}',
    '@media (max-width:1180px){#zl-page-ov .zl-ex-grid{grid-template-columns:repeat(2,minmax(0,1fr));}}',
    '@media (max-width:760px){#zl-page-ov .zl-ex-grid{grid-template-columns:1fr;}}',
    /* ---- 输入框上方的专家选择条（一级：当前专家；二级：展开 9 行；恒跟随输入框） ---- */
    '#zl-xbar{position:fixed;z-index:2050;display:flex;flex-direction:column;align-items:stretch;gap:6px;',
    'font-family:' + FONT + ';pointer-events:none;}',
    '#zl-xbar.hide{display:none !important;}',
    /* 需求 3：PDF 弹层必须置顶。
       Chainlit 的 Radix Dialog 层级只有 z=50(遮罩)/z-60(内容)，而本项目自绘浮层是
       79~2050（专家条 2050 / 中间覆盖层 2000 / 设置 300 / 左栏 80 / 右栏 79）
       —— 左栏/右栏/齿轮/专家条全都会盖在 PDF 上面。
       采用"抬高弹层"而不是"压低项目浮层"：后者会牵连既有层级关系，风险更大。 */
    '[role="dialog"]{z-index:3000 !important;}',
    'body.zl-pdf-open [role="dialog"]{z-index:3000 !important;}',
    /* 需求：选择专家 / 自由对话 / 模型 三个控件并排同一行。
       历史形态是把「自由对话 + 模型」挂在 Chainlit 输入框的回形针旁边 ——
       那是**寄生在框架 DOM 上**（靠找回形针父节点定位），框架升级就会断。
       搬进自己可控的 #zl-xbar 反而少了一个脆弱依赖，顺带让三个入口收成一行。 */
    '#zl-xbar .xb-tools{display:flex;align-items:center;gap:8px;flex-wrap:wrap;}',
    '#zl-xbar .xb-tools-r{margin-left:auto;display:inline-flex;align-items:center;gap:8px;flex-wrap:wrap;}',
    '#zl-xbar .xb-toggle{pointer-events:auto;display:inline-flex;align-items:center;gap:6px;align-self:flex-start;max-width:100%;',
    'padding:5px 11px;border-radius:11px;border:1px solid var(--zl-input-bord);background:var(--zl-card-bg);',
    'color:var(--zl-wb-tx);font-size:12.5px;font-weight:600;cursor:pointer;font-family:' + FONT + ';',
    'box-shadow:0 2px 10px rgba(0,0,0,.24);transition:border-color .18s,box-shadow .18s;}',
    '#zl-xbar .xb-toggle:hover{border-color:var(--zl-ring);box-shadow:0 3px 14px var(--zl-ring-soft);}',
    '#zl-xbar .xb-toggle:focus-visible{outline:2px solid var(--zl-ring);outline-offset:2px;}',
    '#zl-xbar .xb-lab{color:var(--zl-sub);font-weight:500;}',
    '#zl-xbar .xb-cur{display:inline-flex;align-items:baseline;gap:6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:44vw;}',
    /* 顶部"当前专家"同样以定位为主：定位加粗主色 + 拟人名轻量次色（2026-09-18） */
    '#zl-xbar .xb-cur-role{color:var(--zl-ring);font-weight:800;}',
    '#zl-xbar .xb-cur-alias{color:var(--zl-sub);font-weight:500;font-size:11.5px;}',
    '#zl-xbar .xb-chev{display:flex;color:var(--zl-sub);transition:transform .2s;}',
    '#zl-xbar.open .xb-toggle .xb-chev{transform:rotate(180deg);}',
    /* 搬进专家条的自由对话开关 / 模型下拉：必须显式 pointer-events:auto ——
       父级 #zl-xbar 是 pointer-events:none（整层透明，不能挡住对话），
       漏了这行按钮会"看得见点不动"。外观对齐 .xb-toggle。 */
    '#zl-xbar .zl-freechat,#zl-xbar .zl-model{pointer-events:auto;margin:0;',
    '   box-shadow:0 2px 10px rgba(0,0,0,.24);font-family:' + FONT + ';}',
    '#zl-xbar .zl-freechat{padding:5px 10px;border-radius:11px;font-size:12.5px;}',
    '#zl-xbar .zl-model{padding:5px 8px;border-radius:11px;}',
    /* 面板向上展开（DOM 顺序在 toggle 之前），必然盖住部分对话内容 —— 点外部收起 */
    /* max-height 只是 CSS 兜底；真正的值由 layoutBar() 按"输入框上方可用高度"动态写入
       （9 行实测 ~756px，要一次看全，但屏幕矮时要让位，见 layoutBar 里的 data-cap）。 */
    '#zl-xbar .xb-panel{pointer-events:auto;display:none;max-height:min(80vh,820px);overflow-y:auto;padding:8px;border-radius:14px;',
    'border:1px solid var(--zl-input-bord);background:var(--zl-wb-grad);box-shadow:0 -10px 36px rgba(0,0,0,.42);}',
    '#zl-xbar.open .xb-panel{display:block;animation:xb-up .18s ease both;}',
    '@keyframes xb-up{from{opacity:0;transform:translateY(8px);}to{opacity:1;transform:none;}}',
    '#zl-xbar .xb-hd{font-size:11.5px;color:var(--zl-sub);letter-spacing:1px;padding:4px 10px 8px;}',
    '#zl-xbar .xb-row{display:flex;align-items:center;gap:9px;width:100%;min-width:0;text-align:left;padding:7px 10px;',
    'border-radius:11px;border:1px solid transparent;background:transparent;color:var(--zl-wb-tx);cursor:pointer;',
    'font-family:' + FONT + ';transition:background .16s,border-color .16s;}',
    '#zl-xbar .xb-row:hover{background:var(--zl-btn-hov);border-color:var(--zl-btn-bord-hov);}',
    '#zl-xbar .xb-row:focus-visible{outline:2px solid var(--zl-ring);outline-offset:1px;}',
    '#zl-xbar .xb-row.cur{background:var(--zl-badgebg);border-color:var(--zl-ring);}',
    '#zl-xbar .xb-no{flex:none;width:22px;height:22px;border-radius:50%;background:var(--zl-accent-grad);color:var(--zl-accent-tx);',
    'font-size:12px;font-weight:800;display:flex;align-items:center;justify-content:center;}',
    '#zl-xbar .xb-body{flex:1;min-width:0;}',
    /* ⚠️ 同上（2026-09-18）：二级面板里也换成"定位最大最粗、拟人名次要"。
       类名语义：`.xb-role` = 定位（拿 `name`）、`.xb-alias` = 拟人名（拿 `alias`）。 */
    '#zl-xbar .xb-name{display:flex;align-items:baseline;gap:7px;min-width:0;}',
    '#zl-xbar .xb-role{font-size:14.5px;font-weight:800;color:var(--zl-card-val);}',
    '#zl-xbar .xb-alias{font-size:12px;font-weight:500;color:var(--zl-sub);}',
    '#zl-xbar .xb-desc{font-size:12px;color:var(--zl-sub);margin-top:1px;line-height:1.45;',
    'display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}',
    '#zl-xbar .xb-tick{flex:none;color:var(--zl-ring);font-weight:800;opacity:0;}',
    '#zl-xbar .xb-row.cur .xb-tick{opacity:1;}',
    /* 浮层提示：替代"往对话框回一条文字"，3 秒自动消失，不占对话历史 */
    '#zl-xbar .xb-toast{display:none;align-self:center;max-width:100%;padding:8px 15px;border-radius:12px;',
    'border:1px solid var(--zl-ring);background:var(--zl-wb-grad);color:var(--zl-wb-tx);font-size:13px;font-weight:600;',
    'box-shadow:0 8px 28px rgba(0,0,0,.4);line-height:1.6;}',
    '#zl-xbar .xb-toast.on{display:block;animation:xb-up .16s ease both;}',
    /* 字体缩放层（覆盖上面各字号，随 --zl-fs 缩放） */
    ':root{--zl-fs:1;}',
    '#zl-rail .zl-btn{font-size:calc(17px * var(--zl-fs));}',
    '#zl-rail .zl-title{font-size:calc(24px * var(--zl-fs));}',
    '#zl-rail .zl-sub{font-size:calc(14px * var(--zl-fs));}',
    '#zl-rail .zl-sec{font-size:calc(13.5px * var(--zl-fs));}',
    '#zl-rail .zl-group-hd{font-size:calc(14.5px * var(--zl-fs));}',
    '#zl-rail .zl-group-bd .zl-btn{font-size:calc(15px * var(--zl-fs));}',
    '#zl-rail .zl-hist-title{font-size:calc(15.5px * var(--zl-fs));}',
    '#zl-rail .zl-hist-ts{font-size:calc(12.5px * var(--zl-fs));}',
    '#zl-rail .zl-empty{font-size:calc(14px * var(--zl-fs));}',
    '#zl-rail .zl-foot{font-size:calc(13.5px * var(--zl-fs));}',
    '#zl-right .zr-shop{font-size:calc(16px * var(--zl-fs));}',
    '#zl-right .zr-sub{font-size:calc(13.5px * var(--zl-fs));}',
    '#zl-right .zr-sec{font-size:calc(15px * var(--zl-fs));}',
    '#zl-right .zr-card .lab{font-size:calc(12.5px * var(--zl-fs));}',
    '#zl-right .zr-card .val{font-size:calc(21px * var(--zl-fs));}',
    '#zl-right table{font-size:calc(13.5px * var(--zl-fs));}',
    '#zl-right .zr-field label{font-size:calc(14px * var(--zl-fs));}',
    '#zl-right .zr-field input{font-size:calc(16px * var(--zl-fs));}',
    /* 口径说明 / 加盟费门槛：新增元素必须同步纳入缩放层，
       否则用户把字体调大时，恰恰是最需要看清的警示文案不跟着变大。 */
    '#zl-right .zr-note,#zl-right .zr-floor{font-size:calc(12px * var(--zl-fs));}',
    /* 仿真看板的文字同样纳入缩放层（新元素漏进缩放层 = 用户放大字体时它不变大） */
    '#zl-right .zr-chip{font-size:calc(12px * var(--zl-fs));}',
    /* 仿真看板**独立入口页**（2026-09-21）：整页都建在 #zl-page-ov 里，
       用到的 .zl-kb-tb / .zl-kb-note / .zr-legend 此前都没有缩放层条目。
       ⚠️ 一律限定在 #zl-page-ov 下 —— 右栏那份 .zr-legend 是实机探针验过的旧渲染，
       不去动它的既有尺寸。 */
    '#zl-page-ov .zl-simsrc .zl-kb-tb{font-size:calc(13.5px * var(--zl-fs));}',
    '#zl-page-ov .zl-kb-note{font-size:calc(13.5px * var(--zl-fs));}',
    '#zl-page-ov .zr-legend{font-size:calc(12.5px * var(--zl-fs));}',
    '#zl-right .zr-btn-primary,#zl-right .zr-btn-ghost{font-size:calc(16px * var(--zl-fs));}',
    '[class*="message-content"],.step[data-step-type] [role="region"]{font-size:calc(15px * var(--zl-fs));}',
    /* ⚠️ 子页面（知识库 / 专家系统 / 历史会话）此前**漏在缩放层之外** ——
       用户在设置里把「字体大小」调到"大"，这两个页面的字纹丝不动。
       补进来的同时把基础字号也上调了一档（需求：子页面字再大一点点）。 */
    '#zl-page-ov .zl-pg-title{font-size:calc(18.5px * var(--zl-fs));}',
    '#zl-page-ov .zl-kb-sec{font-size:calc(16.5px * var(--zl-fs));}',
    '#zl-page-ov .zl-kb-theory{font-size:calc(15.5px * var(--zl-fs));}',
    '#zl-page-ov .zl-kb-card{font-size:calc(14.5px * var(--zl-fs));}',
    '#zl-page-ov .zl-kb-card b{font-size:calc(15px * var(--zl-fs));}',
    '#zl-page-ov .zl-kb-card a,#zl-page-ov .zl-kb-link{font-size:calc(14px * var(--zl-fs));}',
    '#zl-page-ov .zl-ex-intro{font-size:calc(15px * var(--zl-fs));}',
    '#zl-page-ov .zl-ex-top{font-size:calc(12.5px * var(--zl-fs));}',
    /* ⚠️ 2026-09-18：这两条**必须与上面的基础规则同步改** ——
       缩放层写在基础规则之后、且只覆盖 font-size，它是"最终生效值"。
       第一版只改了基础规则（20/13），实机量出来仍是 19.5/14，就是被这里静默盖掉的。 */
    '#zl-page-ov .zl-ex-name{font-size:calc(20px * var(--zl-fs));}',
    '#zl-page-ov .zl-ex-name .zl-ex-tit{font-size:calc(13px * var(--zl-fs));}',
    '#zl-page-ov .zl-ex-blurb{font-size:calc(14.5px * var(--zl-fs));}',
    '#zl-page-ov .zl-ex-ex{font-size:calc(13px * var(--zl-fs));}',
    /* 仿真大屏（自绘）—— 全部纳入缩放层。⚠️ 必须写在上面那批基础样式**之后**，
       否则被基础规则里的固定字号反过来盖掉（本项目踩过的孪生坑）。 */
    '#zl-page-ov .sbx-hint{font-size:calc(13px * var(--zl-fs));}',
    '#zl-page-ov .sbx-card .sbx-c-shop{font-size:calc(15.5px * var(--zl-fs));}',
    '#zl-page-ov .sbx-card .sbx-c-meta,#zl-page-ov .sbx-card .sbx-c-tot,',
    '#zl-page-ov .sbx-card .sbx-c-vd,#zl-page-ov .sbx-card .sbx-c-off,',
    '#zl-page-ov .sbx-card .sbx-c-go{font-size:calc(12.5px * var(--zl-fs));}',
    '#zl-page-ov .sbx-back{font-size:calc(13px * var(--zl-fs));}',
    '#zl-page-ov .sbx-src{font-size:calc(12.5px * var(--zl-fs));}',
    '#zl-page-ov .sbx-tag b{font-size:calc(12.5px * var(--zl-fs));}',
    '#zl-page-ov .sbx-kpi .k{font-size:calc(12px * var(--zl-fs));}',
    '#zl-page-ov .sbx-kpi b{font-size:calc(19px * var(--zl-fs));}',
    '#zl-page-ov .sbx-lg{font-size:calc(12.5px * var(--zl-fs));}',
    '#zl-page-ov .sbx-note{font-size:calc(11.5px * var(--zl-fs));}',
    /* ⚠️ --sbx-k 是"节点跨度系数"（由 JS 写在 <svg> 的 style 上）。
       必须乘进去：SVG 的 font-size px 是**用户单位**，跨度小的铺位画面会放大，
       若不乘 K，牌子缩了字没缩，文字就溢出牌面。 */
    '#zl-page-ov .sbx-canvas .sbx-t0{font-size:calc(14px * var(--zl-fs) * var(--sbx-k,1));font-weight:800;}',
    '#zl-page-ov .sbx-canvas .sbx-t1{font-size:calc(16px * var(--zl-fs) * var(--sbx-k,1));font-weight:800;}',
    '#zl-page-ov .sbx-canvas .sbx-t2{font-size:calc(11.5px * var(--zl-fs) * var(--sbx-k,1));}',
    '#zl-page-ov .sbx-canvas .sbx-t3{font-size:calc(13px * var(--zl-fs) * var(--sbx-k,1));font-weight:700;}'
  ].join('');
  document.head.appendChild(style);

  /* ---- 2. 左栏 DOM（二级下拉分组） ---- */
  function chev() { return '<span class="zl-chev">' + ico('arrow') + '</span>'; }
  var rail = document.createElement('div');
  rail.id = 'zl-rail';
  rail.setAttribute('role', 'navigation');
  rail.setAttribute('aria-label', '操作栏');
  rail.innerHTML =
    '<div class="zl-head"><div class="zl-title">' + ico('pin') + ' 址南针</div>' +
    '<div class="zl-sub">AI 商铺选址助手</div></div>' +
    '<div class="zl-body">' +
    '  <div class="zl-group open" data-group="ops">' +
    '    <div class="zl-group-hd" role="button" tabindex="0" aria-expanded="true">' + ico('gauge') + '快速操作' + chev() + '</div>' +
    '    <div class="zl-group-bd">' +
    '      <button class="zl-btn primary" data-cmd="new">' + ico('plus') + ' 新建对话</button>' +
    '      <button class="zl-btn" data-cmd="export">' + ico('arrow') + ' 导出分析</button>' +
    '      <button class="zl-btn disabled" data-cmd="compare" id="zl-cmp">' + ico('compare') + ' 对比分析</button>' +
    /* 仿真看板入口（2026-09-21）：看板本身早在 2026-09-20 就实机 21/21 通过，
       但用户**手够不着** —— 它只是右栏分析工作台的一个 section，而 dashboard.json
       一开新会话就被服务端写成 {'kind':'clear'}，section 跟着消失。
       所以这里给一个常驻入口，读的是**独立快照 /public/last_sim.json**
       （服务端 write_last_sim() 写，clear_dashboard() 不碰它）。
       ⚠️ 无快照时必须 disabled + title 说明，不许"点了没反应"（红线 4：不静默）。 */
    '      <button class="zl-btn disabled" data-cmd="simboard" id="zl-simboard" title="打开上一次选址分析的仿真看板（小人沿真实街道走向本铺）。现在还没有跑过分析，所以暂时不可用 —— 先跑一次选址分析。">' + ico('layers') + ' 仿真看板</button>' +
    '    </div>' +
    '  </div>' +
    '  <div class="zl-group" data-group="demo">' +
    '    <div class="zl-group-hd" role="button" tabindex="0" aria-expanded="false">' + ico('spark') + '快速演示' + chev() + '</div>' +
    '    <div class="zl-group-bd">' +
    '      <button class="zl-btn" data-cmd="demo_milktea">' + ico('coffee') + ' 奶茶·武林广场·8k</button>' +
    '      <button class="zl-btn" data-cmd="demo_cake">' + ico('cake') + ' 甜品·天一广场·1万5</button>' +
    '      <button class="zl-btn" data-cmd="demo_breakfast">' + ico('utensils') + ' 早餐·滨江·6k</button>' +
    '      <button class="zl-btn" data-cmd="demo_store">' + ico('bag') + ' 便利店·温州·1万</button>' +
    /* 反面教材（2026-09-18 欧文诉求 ①）：四个正面范例之外，补**真实低分案例**。
       为什么强调"真实"：下面两串问句都拿去跑过引擎（geocode → score_site，蜜雪冰城/30㎡），
       低分是**实测**出来的，不是编一个看起来会输的例子：
         · in77  月租2.5万 → 地址评分 83.2（位置分结论仍是「推荐」）却月净利 −¥5,327 → 一票否决
         · 千岛湖 月租8000 → 地址评分 56.8（「不建议优先选择」）月净利 −¥10,167，免租也亏 ¥2,167
       两串都**写明了品牌**（"加盟蜜雪冰城"）：不写品牌会先进选品牌环节，
       同一个铺子换品牌结论会变，演示就不确定了。 */
    '      <div class="zl-demo-sub">反面教材｜真实低分案例</div>' +
    '      <button class="zl-btn bad" data-cmd="demo_bad_rent" title="真实低分案例（选蜜雪冰城）：杭州湖滨银泰in77，30㎡月租2.5万 → 地址评分68.8、位置分结论仍是「推荐」，但月净利 −¥5,001 触发一票否决，综合结论「位置好·账算不过来」。要能签，月租得压到 ¥19,950 以下。">' + ico('warn') + ' 奶茶·in77·2.5万</button>' +
    '      <button class="zl-btn bad" data-cmd="demo_bad_place" title="真实低分案例（选蜜雪冰城）：杭州千岛湖银泰城，30㎡月租仅8000 → 地址评分56.8、位置分结论「不建议优先选择」，月净利 −¥10,167；即便免租仍亏 ¥2,167 —— 问题不在租金，谈租金救不回来。">' + ico('warn') + ' 奶茶·千岛湖·8k</button>' +
    '    </div>' +
    '  </div>' +
    '  <div class="zl-group open" data-group="hist">' +
    '    <div class="zl-group-hd" role="button" tabindex="0" aria-expanded="true">' + ico('clock') + '历史会话<span class="zl-badge" id="zl-count"></span>' + chev() + '</div>' +
    '    <div class="zl-group-bd"><div id="zl-hist"></div></div>' +
    '  </div>' +
    '  <div class="zl-group" data-group="kb">' +
    '    <div class="zl-group-hd" role="button" tabindex="0" aria-expanded="false">' + ico('bulb') + '知识库' + chev() + '</div>' +
    '    <div class="zl-group-bd">' +
    '      <button class="zl-btn" data-cmd="kb_theory">' + ico('layers') + ' 选址打分依据</button>' +
    '      <button class="zl-btn" data-cmd="kb_business">' + ico('bulb') + ' 商业理论知识</button>' +
    '    </div>' +
    '  </div>' +
    /* 专家系统：**单击即进子页**（不折叠）——需求是"点击以后进入子页面"，
       所以这里刻意不复用 toggleGroup，而是用 data-xpage 走 openPage('experts')。
       视觉上与其他导航组同高同级，保持在「知识库」正下方。 */
    '  <div class="zl-group" data-group="xpage">' +
    '    <div class="zl-group-hd" role="button" tabindex="0" data-xpage="experts" aria-label="进入专家系统">' +
    ico('grid') + '专家系统' + chev() + '</div>' +
    '  </div>' +
    '</div>' +
    '<div class="zl-foot">每个会话可单独删除</div>' +
    '<div class="zl-resize" id="zl-resize-l" title="拖拽调整宽度"></div>';
  document.body.appendChild(rail);

  /* ---- 3. 右侧工作台 DOM ---- */
  var right = document.createElement('div');
  right.id = 'zl-right';
  right.setAttribute('role', 'complementary');
  right.setAttribute('aria-label', '选铺结论工作台');
  right.innerHTML =
    '<div class="zr-head"><span class="zr-head-ic">' + ico('gauge') + '</span>选铺结论' +
    '<span class="zr-busy" id="zr-busy">' +
    '<svg class="zr-ring" width="14" height="14" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="9" style="stroke:var(--zl-ring-soft)" stroke-width="2.5"/><circle cx="12" cy="12" r="9" style="stroke:var(--zl-ring)" stroke-width="2.5" stroke-linecap="round" stroke-dasharray="56" stroke-dashoffset="14" transform="rotate(-90 12 12)"/></svg>' +
    '正在分析…</span></div>' +
    '<div class="zr-body" id="zr-body">' +
    '<div class="zr-placeholder">分析完成后，选铺结论（评分 / 指标 / 周边环境）<br>将自动显示在这里</div>' +
    '</div>' +
    '<div id="zr-progress"></div>' +
    '<div class="zl-resize" id="zl-resize-r" title="拖拽调整宽度"></div>';
  document.body.appendChild(right);

  /* ---- 4. 布局：两栏可横向拖动位置 + 可拖边改宽 + 聊天区实时跟随 ---- */
  var LAYOUT = { railL: 0, rightR: 0 };   // 左栏左缘距离；右栏距右缘距离
  var BARW = { left: 330, right: 450 };   // 两栏宽度（可拖边调整，持久化）
  try {
    var _saved = JSON.parse(localStorage.getItem('zl_layout') || '{}');
    if (typeof _saved.railL === 'number') LAYOUT.railL = _saved.railL;
    if (typeof _saved.rightR === 'number') LAYOUT.rightR = _saved.rightR;
    var _bw = JSON.parse(localStorage.getItem('zl_barw') || '{}');
    if (typeof _bw.left === 'number' && _bw.left >= 220 && _bw.left <= 640) BARW.left = _bw.left;
    if (typeof _bw.right === 'number' && _bw.right >= 240 && _bw.right <= 760) BARW.right = _bw.right;
  } catch (e) { /* ignore */ }

  function layout() {
    var railEl = document.getElementById('zl-rail');
    var rightEl = document.getElementById('zl-right');
    var vw = window.innerWidth;
    // 响应式护栏：<760px 隐藏右栏，<620px 隐藏左栏；<1100px 右栏收窄、<920px 更窄，保证聊天区始终可用
    var hideR = vw < 760, hideL = vw < 620;
    var bwL = hideL ? 0 : BARW.left;
    var bwR = hideR ? 0 : (vw < 920 ? 320 : (vw < 1100 ? 360 : BARW.right));
    if (rightEl) rightEl.style.display = hideR ? 'none' : '';
    if (railEl) railEl.style.display = hideL ? 'none' : '';
    var maxL = Math.max(0, vw - bwL - 160);
    var maxR = Math.max(0, vw - bwR - 160);
    if (LAYOUT.railL > maxL) LAYOUT.railL = maxL;
    if (LAYOUT.rightR > maxR) LAYOUT.rightR = maxR;
    if (railEl) { railEl.style.width = bwL + 'px'; railEl.style.left = LAYOUT.railL + 'px'; }
    if (rightEl) { rightEl.style.width = bwR + 'px'; rightEl.style.left = (vw - bwR - LAYOUT.rightR) + 'px'; }
    var mainRow = document.querySelector('.flex.flex-row.flex-grow.overflow-auto');
    if (mainRow) {
      mainRow.style.marginLeft = (LAYOUT.railL + bwL) + 'px';
      mainRow.style.marginRight = (bwR + LAYOUT.rightR) + 'px';
    }
    layoutBar();   // 专家条恒跟随输入框：输入框位置由上面几行决定，必须在这里重算
  }
  function shiftContent() { layout(); }
  function persistLayout() {
    try { localStorage.setItem('zl_layout', JSON.stringify(LAYOUT)); } catch (e) { /* ignore */ }
  }
  function persistBarw() {
    try { localStorage.setItem('zl_barw', JSON.stringify(BARW)); } catch (e) { /* ignore */ }
  }
  function resetLayout() {
    LAYOUT.railL = 0; LAYOUT.rightR = 0; BARW.left = 330; BARW.right = 450;
    persistLayout(); persistBarw(); layout();
  }

  /* 拖动（pointer 捕获；仅头部手柄，不干扰内部按钮/输入） */
  function bindDrag(barEl, axis) {
    if (!barEl) return;
    barEl.addEventListener('pointerdown', function (e) {
      if (e.target.closest('button, select, a, .zl-badge')) return;
      var startX = e.clientX;
      var startL = LAYOUT.railL, startR = LAYOUT.rightR;
      var vw = window.innerWidth;
      var moved = false;
      function move(ev) {
        var dx = ev.clientX - startX;
        if (axis === 'rail') {
          LAYOUT.railL = Math.max(0, Math.min(vw - BARW.left - 120, startL + dx));
        } else {
          LAYOUT.rightR = Math.max(0, Math.min(vw - BARW.right - 120, startR - dx));
        }
        layout(); moved = true;
      }
      function up() {
        document.removeEventListener('pointermove', move);
        document.removeEventListener('pointerup', up);
        if (moved) persistLayout();
      }
      document.addEventListener('pointermove', move);
      document.addEventListener('pointerup', up);
    });
  }
  bindDrag(document.getElementById('zl-rail'), 'rail');
  bindDrag(document.getElementById('zl-right'), 'right');

  /* 拖边改宽（左栏右缘 / 右栏左缘） */
  function bindResizeX(handleEl, side) {
    if (!handleEl) return;
    handleEl.addEventListener('pointerdown', function (e) {
      e.preventDefault();
      e.stopPropagation();
      handleEl.classList.add('dragging');
      var startX = e.clientX;
      var startW = side === 'left' ? BARW.left : BARW.right;
      var vw = window.innerWidth;
      var minW = side === 'left' ? 220 : 240;
      var maxW = side === 'left' ? 640 : 760;
      function move(ev) {
        var dx = ev.clientX - startX;
        var w = side === 'left' ? startW + dx : startW - dx;
        w = Math.max(minW, Math.min(maxW, w));
        if (side === 'left') BARW.left = w; else BARW.right = w;
        layout();
      }
      function up() {
        handleEl.classList.remove('dragging');
        document.removeEventListener('pointermove', move);
        document.removeEventListener('pointerup', up);
        persistBarw();
      }
      document.addEventListener('pointermove', move);
      document.addEventListener('pointerup', up);
    });
  }
  bindResizeX(document.getElementById('zl-resize-l'), 'left');
  bindResizeX(document.getElementById('zl-resize-r'), 'right');

  function shiftNow() { shiftContent(); }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      layout(); setTimeout(layout, 300); setTimeout(layout, 900);
    });
  } else {
    layout(); setTimeout(layout, 300); setTimeout(layout, 900);
  }
  if (window.ResizeObserver) {
    try {
      var ro = new ResizeObserver(shiftNow);
      var mainRow = document.querySelector('.flex.flex-row.flex-grow.overflow-auto');
      if (mainRow) ro.observe(mainRow);
      ro.observe(document.body);
      window.__zl_ro = ro;
    } catch (e) { /* ignore */ }
  }
  window.addEventListener('resize', layout);
  setInterval(layout, 900);

  /* ---- 5. 发送命令 ---- */
  var pendingCmd = null;
  var queueEl = null;

  /* 定位发送按钮：输入框所在圆角容器内、最右侧的可见按钮（布局无关） */
  function findSendBtn() {
    var ta = document.querySelector('textarea');
    if (!ta) return null;
    var taR = ta.getBoundingClientRect();
    var comp = ta.parentElement;   // 从父级开始找圆角 composer（避开 textarea 自身 class）
    for (var i = 0; i < 8 && comp; i++) {
      var cls = typeof comp.className === 'string' ? comp.className : '';
      if (/rounded/.test(cls)) break;
      comp = comp.parentElement;
    }
    var scope = (comp && comp.querySelectorAll) ? comp.querySelectorAll('button') : document.querySelectorAll('button');
    var best = null, bestX = -1e9;
    for (var k = 0; k < scope.length; k++) {
      var b = scope[k], r = b.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0) continue;
      if (r.x >= taR.x && r.x > bestX) { bestX = r.x; best = b; }
    }
    return best;
  }

  function isProcessing() {
    var sb = findSendBtn();
    if (!sb) return true;   // 发送按钮被停止按钮替换/消失 = 处理中
    var html = sb.innerHTML || '';
    // 停止按钮：方块/rect/stop 图标（处理中发送按钮图标为空或方块）
    if (/<rect|h12v12|H3 3h18|M9 9h6v6H9z|square|circle-stop/i.test(html)) return true;
    var p = sb.querySelector('svg path');
    var d = p ? (p.getAttribute('d') || '') : '';
    if (d === '') return true;   // 发送按钮无路径 = 停止图标（实测处理中 d 为空）
    // 兜底：页面任何可见停止按钮
    var stops = Array.prototype.filter.call(document.querySelectorAll('button'), function (b) {
      var r = b.getBoundingClientRect(), t = (b.textContent || '').trim();
      return r.width > 0 && (t === 'Stop' || t === '停止' || t.indexOf('Stop generating') >= 0 || t.indexOf('停止生成') >= 0);
    });
    return stops.length > 0;
  }

  /* ---- 滚动位置保护（需求 5：切专家/自由对话时对话框跳回最上方）----
     根因（已定位，不在滚动代码里）：sendCmd 是一条**真用户消息** → Chainlit 自带
     autoscroll 会 scrollTo(最后一条 user_message.offsetTop - 20)；而 hideCmdBubbles
     把该气泡设成 display:none → 它的 offsetTop 变成 0 → scrollTo(-20) 被夹到 0 → 跳顶。
     这里做两件事：
       A) hideCmdBubbles 改用 softHide()（零高度但**留在文档流**，offsetTop 仍有真实值）
          —— 治本，让 autoscroll 自己算对；
       B) captureScroll/guardScroll —— 兜底，无论 autoscroll 怎么动，都把滚动位置还原
          （原本贴底就回到底，否则回到原 scrollTop）。只对静默指令生效，不影响正常发消息。 */
  /* ⚠️ 这里**不能**用 querySelector（2026-09-17 实机踩到，真 bug 不是猜测）：
     Chainlit 的聊天区在 DOM 里是**两层**同源 class 的容器 ——
       外层 div.relative.flex.flex-col.flex-grow.overflow-y-auto.zl-chatcol  ← 不滚
       内层 div.flex.flex-col.flex-grow.overflow-y-auto.zl-chatcol          ← 真正滚
     两者都带 `zl-chatcol`（`ensureChatCol()` 故意给**所有**匹配列都加，为了底色铺满），
     所以加不加 `.zl-chatcol` 都区分不开。而 `querySelector` 返回的是**外层**：
     它的 `scrollHeight === clientHeight` —— 于是
       · `captureScroll()` 永远读到 `top: 0`、`bottom: true`；
       · `restoreScroll()` 把 scrollTop 写进一个不滚的元素，纹丝不动。
     兜底层看着在跑、日志也不报错，实际**全程空转**（症状只会表现为"偶尔还是跳顶"）。
     选法：在所有候选里挑**溢出量最大**的那个；都不溢出时（内容不足一屏）
     两个都不滚，取最后一个即可，等价。 */
  function scroller() {
    var all = document.querySelectorAll('.flex.flex-col.flex-grow.overflow-y-auto');
    if (!all.length) return null;
    var best = all[all.length - 1], bestOver = -1;
    for (var i = 0; i < all.length; i++) {
      var over = all[i].scrollHeight - all[i].clientHeight;
      if (over > bestOver) { bestOver = over; best = all[i]; }
    }
    return best;
  }
  function captureScroll() {
    var c = scroller();
    if (!c) return null;
    return { top: c.scrollTop, bottom: (c.scrollHeight - c.scrollTop - c.clientHeight) < 48 };
  }
  function restoreScroll(s) {
    if (!s) return;
    var c = scroller();
    if (!c) return;
    var want = s.bottom ? c.scrollHeight : s.top;
    if (Math.abs(c.scrollTop - want) > 2) c.scrollTop = want;   // 直接赋 scrollTop：瞬时，不与 smooth 动画打架
  }
  function guardScroll(s) {
    if (!s) return;
    var apply = function () { restoreScroll(s); };
    var raf = window.requestAnimationFrame;
    if (raf) raf(function () { raf(apply); });
    [80, 240, 600, 1000].forEach(function (ms) { setTimeout(apply, ms); });
  }
  function sendCmd(txt) {
    if (isProcessing()) {
      pendingCmd = txt;
      showQueue('命令已排队，处理完成自动执行…');
      return;
    }
    var _scroll = isCtrlCmd(txt) ? captureScroll() : null;   // 只在静默指令上记录滚动位
    if (isCtrlCmd(txt)) { hideTarget = normCmd(txt); hideTargetAt = Date.now(); }
    var ta = document.querySelector('textarea');
    if (!ta) return;
    var setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
    setter.call(ta, txt);
    ta.dispatchEvent(new Event('input', { bubbles: true }));
    var send = findSendBtn();
    if (send && !send.disabled) send.click();
    else ta.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', bubbles: true }));
    // 静默指令加固：观察器回调属**微任务**，浏览器要等"当前任务 + 所有微任务"跑完才绘制，
    // 所以正常情况下气泡根本不会被画出来。只有主线程被长任务占住时（模型还在流式输出、
    // 900ms 的 layout() 轮询与重排撞同一帧）才可能被画一帧。这里连挂 3 帧再藏一次，
    // 把那个极端窗口压到 1 帧（≈16ms，肉眼基本不可见）。零成本兜底，不动既有逻辑。
    (function rafHide(n) {
      var raf = window.requestAnimationFrame;
      if (!raf || n <= 0) return;
      raf(function () { hideCmdBubbles(); rafHide(n - 1); });
    })(3);
    setTimeout(hideCmdBubbles, 80);
    setTimeout(hideCmdBubbles, 400);
    setTimeout(hideCmdBubbles, 1500);
    guardScroll(_scroll);   // 兜底：把滚动位置还原到操作前（贴底就回底）
  }

  function showQueue(msg) {
    if (!queueEl) {
      queueEl = document.createElement('div');
      queueEl.id = 'zl-queue';
      document.body.appendChild(queueEl);
    }
    queueEl.textContent = msg;
    clearTimeout(queueEl._t);
    queueEl._t = setTimeout(function () { if (queueEl) queueEl.remove(); queueEl = null; }, 3000);
  }

  /* ---- 6. 历史会话 ---- */
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/[\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}\u{1F000}-\u{1FAFF}\uFE0F\u200D]/gu, '')
      .replace(/[&<>"']/g, function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
      });
  }
  function fmtNum(v) {
    var n = parseFloat(v);
    if (isNaN(n)) return v == null ? '-' : v;
    if (Math.abs(n) >= 10000) return (n / 10000).toFixed(1) + '万';
    return n.toLocaleString('zh-CN');
  }
  var analysesCount = 0;
  function updateCompareState() {
    var cmp = document.getElementById('zl-cmp');
    if (!cmp) return;
    if (analysesCount < 2) {
      cmp.classList.add('disabled');
      cmp.title = '需要先完成至少 2 次选址分析才能对比（当前 ' + analysesCount + ' 次）';
    } else {
      cmp.classList.remove('disabled');
      cmp.title = '对比已分析的商铺';
    }
  }
  function renderHist(data) {
    var histEl = document.getElementById('zl-hist');
    var cnt = document.getElementById('zl-count');
    var hist = (data && data.hist) || [];
    analysesCount = (data && typeof data.analyses === 'number') ? data.analyses : 0;
    updateCompareState();
    if (cnt) cnt.textContent = hist.length ? hist.length + '' : '';
    if (!hist.length) {
      histEl.innerHTML = '<div class="zl-empty">暂无历史会话，开始第一次对话吧～</div>';
      return;
    }
    var html = '';
    hist.forEach(function (c) {
      var isOk = c.mark === '分析';
      var score = (c.total != null && c.total !== '') ? ' · <span style="color:var(--zl-score)">' + esc(c.total) + '分</span>' : '';
      html += '<div class="zl-hist"><div class="zl-hist-row">' +
        '<div class="zl-hist-info" data-open="' + esc(c.id) + '" role="button" tabindex="0" title="点击打开该会话" aria-label="打开会话 ' + esc(c.title) + '">' +
        '<div class="zl-hist-title"><span class="zl-tag ' + (isOk ? 'ok' : 'chat') + '">' + esc(c.mark) + '</span>' + esc(c.title) + score + '</div>' +
        '<div class="zl-hist-ts">' + ico('clock', 'x12') + esc(c.ts) + '</div></div>' +
        '<button class="zl-del" data-del="' + esc(c.id) + '" type="button" title="删除该会话" aria-label="删除会话 ' + esc(c.title) + '">' + ico('trash') + '</button>' +
        '</div></div>';
    });
    histEl.innerHTML = html;
  }

  /* ---- 7. 事件委托 ---- */
  function openHistory(id) {
    /* §2（2026-09-17）：**一步到位**。
       改前是两段式：本函数 fetch sidebar.json → renderHistPage() 弹一个只读中间页，
       用户还要再点一次「继续对话」（#zl-pg-cta）才发 ##打开:。两个毛病：
         · 多点一次；中间页里只有右栏数据 + PDF，**聊天内容全丢**；
         · 覆盖层一开，专家条按 layoutBar() 的互斥逻辑被藏起来。
       现在直接发 ##打开:<id>## → 后端 process_open_conv 切状态 + 回放最近 N 条
       （真消息，见 app_chainlit.py 的 _replay_emit）。
       ⚠️ 指令气泡由 hideCmdBubbles 静默（白名单含 '##打开:'），滚动由
       captureScroll/guardScroll 兜底，因此点历史项同样不会跳顶。 */
    sendCmd('##打开:' + id + '##');
  }
  document.addEventListener('click', function (ev) {
    var openEl = ev.target.closest('[data-open]');
    if (openEl) {
      openHistory(openEl.getAttribute('data-open'));
      return;
    }
    var candBtn = ev.target.closest('[data-choose]');
    if (candBtn) {
      // 候选卡片：点击立即发"我选第N个"触发分析（前端高亮被点卡片防误触）
      var ci = candBtn.getAttribute('data-choose');
      document.querySelectorAll('.cand-card').forEach(function (c) { c.classList.remove('picked'); });
      candBtn.classList.add('picked');
      sendCmd('我选第' + ci + '个');
      return;
    }
    var brandBtn = ev.target.closest('[data-brand]');
    if (brandBtn) {
      // 品牌卡片：点击发"我选品牌XXX"（后端按品牌名解析，避免序号漂移）
      var bname = brandBtn.getAttribute('data-brand');
      document.querySelectorAll('.brand-card').forEach(function (c) { c.classList.remove('picked'); });
      brandBtn.classList.add('picked');
      sendCmd('我选品牌' + bname);
      return;
    }
    var catBtn = ev.target.closest('[data-cat]');
    if (catBtn) {
      // 需求3：四品类推荐卡片 → 发"我选XX"，后端按品类走详细分析
      var cname = catBtn.getAttribute('data-cat');
      document.querySelectorAll('.cat-card').forEach(function (c) { c.classList.remove('picked'); });
      catBtn.classList.add('picked');
      sendCmd('我选' + cname);
      return;
    }
    // 对比分析勾选卡片（点卡片整行切换勾选）
    var cpCard = ev.target.closest('.cp-card');
    // 删除按钮优先（stopPropagation 已阻止触发勾选）
    var cpDel = ev.target.closest('[data-cpdel]');
    if (cpDel) {
      ev.preventDefault();
      var aid = cpDel.getAttribute('data-cpdel');
      if (aid && window.confirm('确定删除这条分析记录吗？（不影响其他会话）')) {
        sendCmd('##删除分析:' + aid + '##');
        // 立即从 DOM 移除卡片并重新编号
        var row = cpDel.closest('.cp-card');
        if (row) row.remove();
        renumberCpCards();
      }
      return;
    }
    if (cpCard) {
      var chk = cpCard.querySelector('.cp-chk');
      if (chk) { chk.checked = !chk.checked; }
      updateComparePick();
      return;
    }
    // 开始对比按钮
    var cpGo = ev.target.closest('#cp-start');
    if (cpGo) {
      var picked = [];
      document.querySelectorAll('.cp-chk:checked').forEach(function (c) {
        picked.push(c.getAttribute('data-i'));
      });
      if (picked.length >= 2) sendCmd('对比 ' + picked.join(' '));
      return;
    }
    // 专家系统卡片页：点卡片即切专家 + 关页（与输入框上方面板共用 switchExpert）
    var xpick = ev.target.closest('[data-xpick]');
    if (xpick) {
      switchExpert(xpick.getAttribute('data-xpick'));
      closePage();
      return;
    }
    var gh = ev.target.closest('.zl-group-hd');
    if (gh) {
      // 「专家系统」是单击进子页（不是折叠组）——见左栏 DOM 注释
      if (gh.getAttribute('data-xpage')) { openPage(gh.getAttribute('data-xpage')); return; }
      toggleGroup(gh.parentElement);
      return;
    }
    var delBtn = ev.target.closest('[data-del]');
    if (delBtn) {
      var id = delBtn.getAttribute('data-del');
      if (window.confirm('确定删除这个历史会话吗？（不影响其他会话）')) {
        sendCmd('##删除:' + id + '##');
      }
      return;
    }
    var closeForm = ev.target.closest && ev.target.closest('#zr-form-close');
    if (closeForm) {
      var bodyEl = document.getElementById('zr-body');
      currentInput = null;
      wasPlaceholder = false;
      if (bodyEl) bodyEl.innerHTML = lastContent || placeholderHTML();
      return;
    }
    // ⚠️ 大屏卡片页的两个入口必须在 `if (cmdBtn)` **之外** ——
    //    卡片是 <button data-simboard=...>，不是 [data-cmd]，放到里面永远不会命中
    //    （2026-09-21 实测：点卡片毫无反应、连请求都没发出去）。
    var sbPick = ev.target.closest('[data-simboard]');
    if (sbPick) {
      loadSimBoard(sbPick.getAttribute('data-simboard'));
      return;
    }
    if (ev.target.closest && ev.target.closest('#zl-sim-back')) {
      simPicked = null;
      openPage('simboard');
      return;
    }
    var cmdBtn = ev.target.closest('[data-cmd]');
    if (cmdBtn) {
      var cmd = cmdBtn.getAttribute('data-cmd');
      if (cmd === 'compare') {
        // 触发对比流程：后端在右侧工作台列出所有历史分析卡片供勾选（2-4 个）
        sendCmd('对比分析');
        return;
      }
      if (cmd === 'kb_theory') { openPage('theory'); return; }
      if (cmd === 'kb_business') { openPage('business'); return; }
      if (cmd === 'simboard') {
        // ⚠️ 没有快照就**明确告知**，而不是静默什么都不做（红线 4：不静默）。
        // 按钮平时是 disabled 的，但轮询有 2.5s 间隔、首屏也可能没拉到，
        // 所以这里再兜一道：拿不到就给一句人话。
        if (!lastSimData && !simList.length) {
          simBoardUnavailable('还没有跑过选址分析 —— 先跑一次，看板会自动出现在这里。');
          return;
        }
        // 每次点都回到「挑哪一次」（策：先给卡片选择，再看内容）
        simPicked = null;
        openPage('simboard');
        return;
      }
      var map = {
        new: '##新对话##',
        compare: '对比1和2',
        export: '##导出##',
        demo_milktea: '有，看中了杭州武林广场的铺子，开奶茶店，面积30平方，月租8000',
        demo_cake: '有，宁波天一广场附近有个铺子，开甜品店，面积25平，房租1万5',
        demo_breakfast: '有，杭州滨江区长河路看了一家，开早餐店，面积20平，月租6000',
        demo_store: '有，温州鹿城区人民路有个铺子，开便利店，面积40平，月租1万',
        /* 反面教材（2026-09-18 欧文诉求 ①）：与上面 4 例同格式，但租金设成
           "会一票否决 / 位置分本身就低"的档，且**带上品牌** ——
           不写品牌会先进"选品牌"环节，同一铺子换品牌结论就变了，演示不确定。
           两串的实测结论写在按钮 title 里（引擎实跑，非估算）。 */
        demo_bad_rent: '有，看中了杭州湖滨银泰in77的铺子，开奶茶店，加盟蜜雪冰城，面积30平方，月租2万5',
        demo_bad_place: '有，看中了杭州千岛湖银泰城的铺子，开奶茶店，加盟蜜雪冰城，面积30平方，月租8000'
      };
      if (map[cmd]) sendCmd(map[cmd]);
    }
  });
  document.addEventListener('keydown', function (ev) {
    // Esc：优先关输入框上方的专家面板，其次关覆盖层子页
    if (ev.key === 'Escape') {
      var xb = document.getElementById('zl-xbar');
      if (xb && xb.classList.contains('open')) { xb.classList.remove('open'); return; }
      if (pageOv && pageOv.classList.contains('open')) { closePage(); return; }
    }
    var gh = ev.target && ev.target.closest && ev.target.closest('.zl-group-hd');
    if (gh) {
      if (ev.key === 'Enter' || ev.key === ' ') {
        ev.preventDefault();
        if (gh.getAttribute('data-xpage')) openPage(gh.getAttribute('data-xpage'));
        else toggleGroup(gh.parentElement);
      }
      return;
    }
    // 历史会话项：键盘可达（Enter/Space 打开），对齐鼠标点击
    var hi = ev.target && ev.target.closest && ev.target.closest('.zl-hist-info[data-open]');
    if (hi && (ev.key === 'Enter' || ev.key === ' ')) {
      ev.preventDefault();
      openHistory(hi.getAttribute('data-open'));
    }
  });

  /* ---- 8. 隐藏控制指令气泡（## 开头） ---- */
  var mo = new MutationObserver(function (muts) {
    muts.forEach(function (m) {
      m.addedNodes.forEach(function (n) {
        if (n.nodeType === 1) {
          var t = n.textContent || '';
          // 指令气泡不在此处整体隐藏（避免容器过大误隐藏），统一交给 hideCmdBubbles 补扫（叶子级+包裹层保护）
          if ((t.indexOf('##新对话##') >= 0 || t.indexOf('##打开:') >= 0 || t.indexOf('##删除:') >= 0 ||
               t.indexOf('##模型:') >= 0 || t.indexOf('##导出##') >= 0 || t.indexOf('##预览:') >= 0 ||
               t.indexOf('##自由对话:') >= 0 || t.indexOf('##专家:') >= 0) &&
              n.closest && (n.closest('.step[data-step-type]') || n.classList.contains('step'))) {
            n.style.display = 'none';
          }
          // 出正文（最终内容）时自动折叠执行过程步骤
          if (t.indexOf('##') !== 0 && t.length > 0) {
            var cls = n.className ? String(n.className) : '';
            var dt = n.getAttribute ? (n.getAttribute('data-step-type') || '') : '';
            // 用户发出新一轮提问：先重置「真内容」快照 —— 收缩只认本轮新出的内容
            if (dt === 'user_message' || (cls.indexOf('user') >= 0 && cls.indexOf('message') >= 0)) {
              _lastMsgSig = _realMsgSig();
            }
            var isFinal = dt === 'llm' || cls.indexOf('message') >= 0;
            if (!isFinal && n.querySelector) isFinal = !!n.querySelector('.message, [data-step-type="llm"]');
            if (isFinal) collapseProcessStep();
          }
        }
      });
      // 批次结束后统一补扫一次（覆盖「先壳后字」异步渲染漏掉的指令气泡）
      if (!window.__zl_hideTimer) {
        window.__zl_hideTimer = setTimeout(function () {
          window.__zl_hideTimer = null;
          hideCmdBubbles();
        }, 60);
      }
    });
  });
  mo.observe(document.body, { childList: true, subtree: true });

  /* ---- 8b. emoji → Lottie 动画替换（聊天区） ---- */
  var EMOJI_MAP = {
    '\u{1F3EA}': 'store', '\u{1F3EC}': 'store',      /* 🏪 🏬 */
    '\u{1F4CD}': 'pin', '\u{1F4CC}': 'pin',           /* 📍 📌 */
    '\u26A0': 'warn',                                  /* ⚠ */
    '\u{1F4B0}': 'coin',                               /* 💰 */
    '\u{1F4A1}': 'bulb',                               /* 💡 */
    '\u{1F4CA}': 'chart', '\u{1F4CB}': 'chart', '\u{1F4C8}': 'chart', '\u{1F4C9}': 'chart', /* 📊📋📈📉 */
    '\u2705': 'check', '\u{1F3AF}': 'check', '\u{1F44F}': 'check', '\u{1F44D}': 'check',      /* ✅🎯👏👍 */
    '\u2728': 'spark', '\u{1F4A5}': 'spark', '\u{1F4AB}': 'spark', '\u{1F50D}': 'spark', '\u{1F3C6}': 'spark', '\u{1F525}': 'spark', '\u{1F31F}': 'spark', /* ✨💥💫🔍🏆🔥🌟 */
    '\u{1F170}': 'abox', '\u{1F171}': 'bbox'          /* 🅰 🅱 */
  };
  var EMOJI_RE = /[\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}\u{1F000}-\u{1FAFF}](\uFE0F|\u200D[\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}\u{1F000}-\u{1FAFF}])*/gu;
  var EMOJI_TEST = /[\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}\u{1F000}-\u{1FAFF}]/u;
  var lotQueue = [];
  var lottieReady = new Promise(function (res) {
    var s = document.createElement('script');
    s.src = '/public/lottie/lottie.min.js';
    s.onload = function () { res(true); flushLot(); };
    s.onerror = function () { res(false); };
    document.head.appendChild(s);
  });
  function flushLot() {
    lotQueue.forEach(function (span) { initLot(span); });
    lotQueue = [];
  }
  function initLot(span) {
    if (span._lot) return;
    span._lot = true;
    lottieReady.then(function (ok) {
      if (!ok || !window.lottie) { span.style.display = 'none'; return; }
      try {
        window.lottie.loadAnimation({
          container: span, renderer: 'svg', loop: true, autoplay: true,
          path: '/public/lottie/' + span.getAttribute('data-lot') + '.json',
          rendererSettings: { preserveAspectRatio: 'xMidYMid meet' }
        });
      } catch (e) { span.style.display = 'none'; }
    });
  }
  function replaceEmojiInText(textNode) {
    var txt = textNode.nodeValue;
    if (!txt || !EMOJI_TEST.test(txt)) return false;
    var frag = document.createDocumentFragment();
    var last = 0, m;
    EMOJI_RE.lastIndex = 0;
    var spans = [];
    while ((m = EMOJI_RE.exec(txt))) {
      if (m.index > last) frag.appendChild(document.createTextNode(txt.slice(last, m.index)));
      var raw = m[0];
      var base = raw.replace(/[\uFE0F\u200D]/g, '');
      var name = EMOJI_MAP[base] || 'spark';
      var span = document.createElement('span');
      span.className = 'zl-lot';
      span.setAttribute('data-lot', name);
      span.setAttribute('aria-hidden', 'true');
      frag.appendChild(span);
      spans.push(span);
      last = EMOJI_RE.lastIndex;
    }
    if (last < txt.length) frag.appendChild(document.createTextNode(txt.slice(last)));
    if (!spans.length) return false;
    textNode.parentNode.replaceChild(frag, textNode);
    spans.forEach(function (sp) {
      if (window.lottie) initLot(sp);
      else lotQueue.push(sp);
    });
    return true;
  }
  var emojiMO = new MutationObserver(function (muts) {
    muts.forEach(function (m) {
      m.addedNodes.forEach(function (n) {
        if (n.nodeType === 3) { replaceEmojiInText(n); return; }
        if (n.nodeType !== 1) return;
        if (n.id === 'zl-rail' || n.id === 'zl-right') return;
        if (n.closest && n.closest('#zl-rail,#zl-right')) return;
        var w = document.createTreeWalker(n, NodeFilter.SHOW_TEXT, {
          acceptNode: function (t) {
            return (t.nodeValue && EMOJI_TEST.test(t.nodeValue)) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
          }
        });
        var t;
        while ((t = w.nextNode())) { replaceEmojiInText(t); }
      });
    });
  });
  emojiMO.observe(document.body, { childList: true, subtree: true });

  /* ---- 9. 右侧工作台渲染 ---- */
  function radarSVG(labels, series, size) {
    var W = size || 270, H = size || 270;
    var cx = W / 2, cy = H / 2, R = W / 2 - 40;
    var n = labels.length;
    if (!n) return '<div class="zr-placeholder" style="padding:10px">暂无维度数据</div>';
    var pts = [];
    for (var i = 0; i < n; i++) {
      var ang = -Math.PI / 2 + i * 2 * Math.PI / n;
      pts.push({ x: cx + R * Math.cos(ang), y: cy + R * Math.sin(ang) });
    }
    var svg = '<svg width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="维度雷达图" focusable="false">';
    [25, 50, 75, 100].forEach(function (rv) {
      var poly = pts.map(function (p) {
        var f = rv / 100;
        return (cx + (p.x - cx) * f).toFixed(1) + ',' + (cy + (p.y - cy) * f).toFixed(1);
      }).join(' ');
      svg += '<polygon points="' + poly + '" fill="none" style="stroke:var(--zl-radar-grid)" stroke-width="1"/>';
    });
    pts.forEach(function (p) {
      svg += '<line x1="' + cx + '" y1="' + cy + '" x2="' + p.x.toFixed(1) + '" y2="' + p.y.toFixed(1) + '" style="stroke:var(--zl-radar-grid)" stroke-width="1"/>';
    });
    series.forEach(function (s) {
      var poly = labels.map(function (l, i) {
        var f = Math.max(0, Math.min(100, parseFloat(s.values[i]) || 0)) / 100;
        return (cx + (pts[i].x - cx) * f).toFixed(1) + ',' + (cy + (pts[i].y - cy) * f).toFixed(1);
      }).join(' ');
      svg += '<polygon points="' + poly + '" fill="' + s.color + '" fill-opacity="0.22" stroke="' + s.color + '" stroke-width="2"/>';
    });
    labels.forEach(function (l, i) {
      var ang = -Math.PI / 2 + i * 2 * Math.PI / n;
      var lx = cx + (R + 22) * Math.cos(ang), ly = cy + (R + 22) * Math.sin(ang);
      var cosA = Math.cos(ang);
      var anchor = Math.abs(cosA) < 0.25 ? 'middle' : (cosA > 0 ? 'start' : 'end');
      var est = l.length * 12.5; // 13px 字号估算宽度，防止左右轴标签出界裁剪
      if (anchor === 'start') lx = Math.min(lx, W - 2 - est);
      else if (anchor === 'end') lx = Math.max(lx, est + 2);
      svg += '<text x="' + lx.toFixed(1) + '" y="' + (ly + 4).toFixed(1) + '" font-size="13" style="fill:var(--zl-radar-tx)" text-anchor="' + anchor + '">' + esc(l) + '</text>';
    });
    svg += '</svg>';
    return svg;
  }

  function barsHTML(chart, names, colors, showVal) {
    var html = '';
    Object.keys(chart).forEach(function (label) {
      var v = chart[label];
      var vals = Array.isArray(v) ? v : [v];
      var max = 1;
      vals.forEach(function (x) { max = Math.max(max, parseFloat(x) || 0); });
      html += '<div class="zr-bar-row"><div class="zr-bar-label">' + esc(label) + '</div>';
      vals.forEach(function (x, k) {
        var xv = parseFloat(x) || 0;
        html += '<div class="zr-bar-track"><div class="zr-bar-fill" style="width:' + Math.max(2, xv / max * 100) + '%;background:' + (colors[k % colors.length]) + '">' + esc(showVal(xv)) + '</div></div>';
      });
      html += '</div>';
    });
    return html;
  }

  function renderAnalysis(d) {
    var h = '';
    h += '<div class="zr-shop">' + esc(d.shop) + '</div>';
    h += '<div class="zr-sub">' + esc(d.category) + ' ｜ ' + esc(d.ts) + '</div>';
    if (d.cards && d.cards.length) {
      h += '<div class="zr-cards">';
      d.cards.forEach(function (c) {
        var tone = c.tone || 'mid';
        // 状态图标兜底：色盲/读屏用户不依赖纯颜色判断（✓=好 ⚠=风险 •=一般）
        var mark = tone === 'good' ? '✓ ' : (tone === 'bad' ? '⚠ ' : '• ');
        h += '<div class="zr-card ' + esc(tone) + '"><div class="lab"><span class="zr-tone">' + mark + '</span>' + esc(c.label) + '</div>' +
          '<div class="val">' + esc(c.value) + (c.unit ? '<span class="u"> ' + esc(c.unit) + '</span>' : '') + '</div></div>';
      });
      h += '</div>';
    }
    if (d.dims && Object.keys(d.dims).length) {
      h += '<div class="zr-sec">选址维度</div>';
      h += '<div class="zr-radar">' + radarSVG(Object.keys(d.dims), [{
        name: d.shop, color: '#c9a45c',
        values: Object.keys(d.dims).map(function (k) { return d.dims[k]; })
      }]) + '</div>';
    }
    if (d.dim_rows && d.dim_rows.length) {
      h += '<div class="zr-sec">选址得分</div><table>';
      d.dim_rows.forEach(function (r) {
        h += '<tr><td class="k">' + esc(r.name) + '</td><td class="v">' + esc(r.value) + ' 分 · 权重 ' + esc(r.weight) + '</td></tr>';
      });
      h += '</table>';
    }
    if (d.evidence_rows && d.evidence_rows.length) {
      h += '<div class="zr-sec">关键证据</div><table>';
      d.evidence_rows.forEach(function (r) { h += '<tr><td class="k">' + esc(r[0]) + '</td><td class="v">' + esc(r[1]) + '</td></tr>'; });
      h += '</table>';
    }
    if (d.utility_rows && d.utility_rows.length) {
      h += '<div class="zr-sec">水电成本测算</div><table>';
      d.utility_rows.forEach(function (r) { h += '<tr><td class="k">' + esc(r[0]) + '</td><td class="v">' + esc(r[1]) + '</td></tr>'; });
      h += '</table>';
    }
    if (d.profit_rows && d.profit_rows.length) {
      h += '<div class="zr-sec">盈利测算</div><table>';
      d.profit_rows.forEach(function (r) { h += '<tr><td class="k">' + esc(r[0]) + '</td><td class="v">' + esc(r[1]) + '</td></tr>'; });
      h += '</table>';
    }
    if (d.scenario_rows && d.scenario_rows.length) {
      h += '<div class="zr-sec">三档情景区间</div><table>';
      d.scenario_rows.forEach(function (r) { h += '<tr><td class="k">' + esc(r[0]) + '</td><td class="v">' + esc(r[1]) + '</td></tr>'; });
      h += '</table>';
    }
    /* 口径区间：与三档情景正交。三档变成本假设，这一档变需求假设 */
    if (d.caliper_rows && d.caliper_rows.length) {
      h += '<div class="zr-sec">口径区间（价格-单量弹性未标定）</div><table>';
      d.caliper_rows.forEach(function (r) { h += '<tr><td class="k">' + esc(r[0]) + '</td><td class="v">' + esc(r[1]) + '</td></tr>'; });
      h += '</table>';
    }
    if (d.map_b64) {
      /* ⚠️ 2026-09-21：这里**不再叫「仿真看板」**。右栏这块是**位置热力图**
         （高德底图 + POI 点位），而"仿真大屏"是左栏那个独立入口的**自绘场景**。
         两者曾是同一个名字，策看到浮层时才会说"和把右侧热力图搬过来有什么区别"。 */
      h += '<div class="zr-sec">周边热力图 · 客流轨迹</div>'
        + '<div class="zr-map"><div class="zr-simstage">'
        + '<img src="' + d.map_b64 + '" alt="周边地图"/>'
        + simOverlay(d.sim) + '</div>'
        + '<div class="zr-legend">红点 = 本铺 · 红圈 = 竞品 · 蓝点 = 客群 POI · 蓝环 = 分析半径'
        + ' · <b>彩色轨迹 = 步行路网路径，小人沿真实街道走向本铺</b></div></div>'
        + simMeta(d.sim);
    }
    if (d.warnings && d.warnings.length) {
      d.warnings.forEach(function (w) { h += '<div class="zr-warn">' + esc(w) + '</div>'; });
    }
    return h;
  }


  /* ================= 仿真数据看板（2026-09-20） =================
     把已经生效的「步行路网口径」**画出来**，而不是再算一遍模型：
       · 轨迹 = data/road_path 冻结的高德步行折线（真实街道）
       · 选点 = scoring.query_pois（与 D/P 用的是同一批点）
       · 小人沿折线匀速走，速度 = 步行 1.2 m/s × 仿真倍速（画面标注倍速，不糊弄）
     所有像素坐标都由服务端 project() 算好，前端只画。 */
  var SIM_SPEED = 8;                 // 仿真倍速（真实步行 1.2 m/s 的 8 倍）
  var SIM_COLOR = { '学校': '#f59e0b', '办公': '#10b981', '社区': '#8b5cf6',
                    '商圈': '#ef4444', '通勤': '#06b6d4' };

  function simColor(cat) { return SIM_COLOR[cat] || '#3b82f6'; }

  function simFigures(tg) {
    var out = '';
    tg.forEach(function (t, k) {
      var pts = t.path_px || [];
      if (pts.length < 2) return;
      var d = 'M' + pts.map(function (p) { return p[0] + ' ' + p[1]; }).join(' L');
      var road = t.road_m || 0;
      var dur = Math.max(2.2, road / (1.2 * SIM_SPEED));   // 匀速：路越长走得越久
      var col = simColor(t.cat);
      // 起点标一个"出发"小点，让"从哪来"看得见
      out += '<circle cx="' + pts[0][0] + '" cy="' + pts[0][1] + '" r="3.6" fill="'
             + col + '" opacity="0.75"/>';
      // 小人：头 + 身体，用 animateMotion 沿**同一条折线**移动
      out += '<g opacity="0.95">'
           + '<circle cx="0" cy="-5.2" r="2.9" fill="' + col + '" stroke="#fff" stroke-width="0.9"/>'
           + '<rect x="-2.4" y="-2.6" width="4.8" height="7.2" rx="2.2" fill="' + col
           + '" stroke="#fff" stroke-width="0.9"/>'
           + '<animateMotion dur="' + dur.toFixed(1) + 's" begin="-'
           + ((k * 1.37) % Math.max(1, dur)).toFixed(1) + 's" repeatCount="indefinite" '
           + 'calcMode="linear" path="' + d + '"/>'
           + '</g>';
    });
    return out;
  }

  function simOverlay(sim) {
    if (!sim || !sim.ok) return '';
    var g = sim.geo || {}, W = g.img_w || 768;
    var tg = (sim.targets || []).filter(function (t) { return (t.path_px || []).length > 1; });
    if (!tg.length) return '';
    var svg = '<svg viewBox="0 0 ' + W + ' ' + W + '" preserveAspectRatio="none" aria-hidden="true">';
    // ① 先铺轨迹（越短的主干画得越实，长尾淡一点，避免糊成一团）
    tg.forEach(function (t) {
      var pts = t.path_px;
      var d = 'M' + pts.map(function (p) { return p[0] + ' ' + p[1]; }).join(' L');
      var w = t.road_m <= 250 ? 3.2 : (t.road_m <= 600 ? 2.4 : 1.8);
      svg += '<path d="' + d + '" fill="none" stroke="' + simColor(t.cat)
           + '" stroke-width="' + w + '" stroke-linejoin="round" stroke-linecap="round"'
           + ' opacity="0.55"/>';
    });
    // ② 本铺
    var sp = sim.store_px || [W / 2, W / 2];
    svg += '<circle cx="' + sp[0] + '" cy="' + sp[1] + '" r="9" fill="#dc2626" stroke="#fff" stroke-width="3"/>';
    // ③ 小人
    svg += simFigures(tg);
    svg += '</svg>';
    return svg;
  }

  function simMeta(sim) {
    if (!sim || !sim.ok) {
      return '<div class="zr-legend">仿真看板不可用：'
             + esc((sim && sim['原因']) || '未计算') + '</div>';
    }
    var m = sim.meta || {}, st = m['路径统计'] || {};
    var tg = sim.targets || [];
    var withPath = tg.filter(function (t) { return (t.path_px || []).length > 1; }).length;
    var near = tg[0] || {};
    var h = '<div class="zr-sim-meta">';
    h += '<span class="zr-chip">轨迹 <b>' + withPath + '/' + tg.length + '</b> 条真实街道</span>';
    if (near.name) {
      h += '<span class="zr-chip">最近客群 <b>' + esc(near.name) + '</b> '
           + '<b>' + near.road_m + 'm</b> 步行（直线 ' + near.straight_m + 'm'
           + (near.ratio ? '，绕行 <b>' + near.ratio + '×</b>' : '') + '）</span>';
    }
    if (st['降级']) {
      h += '<span class="zr-chip">⚠️ 降级 <b>' + st['降级'] + '</b> 个点（未取到轨迹，已如实留空）</span>';
    }
    h += '<span class="zr-chip">仿真倍速 <b>' + SIM_SPEED + '×</b>（真实步行 1.2 m/s）</span>';
    h += '</div>';
    h += '<div class="zr-legend">选点口径：' + esc(m['选点口径'] || '') + '<br>轨迹口径：'
         + esc(m['轨迹口径'] || '') + '<br>' + esc(m['说明'] || '') + '</div>';
    if (st['API调用'] === 0 && st['取到']) {
      h += '<div class="zr-legend">本次 **0 次 API** —— 轨迹全部命中本地冻结库（可离线复现）</div>';
    }
    return h;
  }

  /* ================= 仿真大屏：**自绘场景**（2026-09-21 重做） =================
     策的原话（09-20 10:17 提、09-21 10:16 又强调一次，**两次都是同一个要求**）：
       「做成一个**一直动态的数据大屏**，用**小人的多少代表客流量的大小**，
         根据**边上有多少家竞品来分流**让小人一直走动」
       「你要**自己实时生成新的地图**，简化不必要的建筑，只留下开店的店铺、
         竞品店铺、还有人流量的来源（小区/学校/商城/写字楼），
         小人从这里出来后沿着马路走到各个店铺里，**一直是动态的**」

     ⇒ 所以**不再叠高德底图**。第一版把底图搬过来 + 叠一条单程轨迹，
       被策直接否掉（"和把右侧数据栏的地图热力图搬过来有什么区别"）。
       底图里全是建筑和路名，小人贴上去**根本看不清谁从哪来、去哪家店**。

     现在只画**关系**：
       马路骨架（真实步行折线的并集） → 三类节点（来源 / 本铺 / 竞品店铺） → 持续走动的小人
     口径全部来自引擎，见 `engine/road_sim.build_board()`；本函数只负责画。 */
  var SBX_STORE_C = '#dc2626';      // 本铺（去本铺的人）
  var SBX_RIVAL_C = '#ea580c';      // 竞品（被分流走的人）

  function sbxPath(pts) {
    return 'M' + pts.map(function (p) { return p[0] + ' ' + p[1]; }).join(' L');
  }

  /* 一个小人：头 + 身体。沿折线**循环**走，走到终点淡出（= 进店），
     再从来源重新出发 —— 这样画面永远是动的，不是播一次就停。 */
  function sbxPerson(pts, color, dur, begin, K) {
    var d = sbxPath(pts);
    K = K || 1;
    // ⚠️ 小人是这张图的**主角**（策："要用小人一直来回走动来代表人流量"），
    //    尺寸给足：第一版 3.2K 在 600+ 单位的画布上只有几个像素，等于看不见。
    var r = 8 * K, hw = 6.5 * K, hh = 19.4 * K;
    return '<g>'
      + '<circle cx="0" cy="' + (-14 * K).toFixed(2) + '" r="' + r.toFixed(2)
      + '" fill="' + color + '" stroke="#fff" stroke-width="' + (1 * K).toFixed(2) + '"/>'
      + '<path d="M' + (-hw).toFixed(2) + ' 0 L' + hw.toFixed(2) + ' 0 L'
      + (hw * 0.68).toFixed(2) + ' ' + hh.toFixed(2) + ' L' + (-hw * 0.68).toFixed(2) + ' '
      + hh.toFixed(2) + ' Z" fill="' + color + '" stroke="#fff" stroke-width="'
      + (0.9 * K).toFixed(2) + '"/>'
      + '<animateMotion dur="' + dur + 's" begin="-' + begin + 's" '
      + 'repeatCount="indefinite" calcMode="linear" path="' + d + '"/>'
      + '<animate attributeName="opacity" dur="' + dur + 's" begin="-' + begin + 's" '
      + 'repeatCount="indefinite" values="0;1;1;0" keyTimes="0;.10;.82;1"/>'
      + '</g>';
  }

  /* 截断文本（SVG 的 <text> 没有 ellipsis，只能自己截） */
  function sbxCut(s, n) {
    s = String(s || '');
    return s.length > n ? s.slice(0, n - 1) + '…' : s;
  }

  function simBoardScene(b) {
    var store = b.store || {}, srcs = b.sources || [], rivs = b.rivals || [];
    var roads = b.roads || [], flows = b.flows || [], meta = b.meta || {};
    if (!store.px) return '';

    /* ---- 几何（2026-09-21 11:05 第三次重写，前两版都没解决根本矛盾）----
       矛盾：画面要**横向铺满**，而节点在地理上往往是**纵向的一小条**（沿一条街排开）。
       第一版用整幅图幅 → 全挤在正中间；第二版用内容包围盒 + 牌子外推 + 强制横比 →
       跨度小就整体缩小，两侧仍是空网格。两版都在"内容尺度"里打转。

       这一版换思路：**先定一个横向视口，再把地理坐标映射进去**。
         · 视口固定 1560×975（1.6:1）—— 这就是"横向大屏"的版面
         · 地理包围盒**等比**放大到视口的 58% 区域（等比 ⇒ 形状不失真，只是看得更近）
         · 牌子环绕在横向椭圆上，把版面剩下的空间用掉
       放大量上限 7×：再大就只是把两个本就很近的点拉得莫名其妙地远。 */
    var VIEWW = 1560, VIEWH = 975;
    var K = VIEWH / 700;                    // 尺度系数：牌子/字号按视口定，不跟地理跨度走

    function bbox(pts) {
      var xs = pts.map(function (p) { return p[0]; });
      var ys = pts.map(function (p) { return p[1]; });
      return [Math.min.apply(null, xs), Math.min.apply(null, ys),
              Math.max.apply(null, xs), Math.max.apply(null, ys)];
    }
    function cp(o) {
      var r = {};
      for (var k in o) { if (Object.prototype.hasOwnProperty.call(o, k)) { r[k] = o[k]; } }
      return r;
    }

    var allRaw = [store.px];
    srcs.forEach(function (s) { allRaw.push(s.px); });
    rivs.forEach(function (r) { allRaw.push(r.px); });
    flows.forEach(function (f) { (f.pts || []).forEach(function (p) { allRaw.push(p); }); });
    var bb0 = bbox(allRaw);
    var cw = Math.max(bb0[2] - bb0[0], 12), ch = Math.max(bb0[3] - bb0[1], 12);
    var cc0 = [(bb0[0] + bb0[2]) / 2, (bb0[1] + bb0[3]) / 2];
    /* 内容映射到视口的 **72%** 区域（原 58%）。
       ⚠️ 策 2026-09-21 11:13：「不要光放大地图，马路也要放大，各个店铺之间的距离要等比例放大」
       —— 之前牌子环绕把版面撑满了，但**路和店还挤在中间**（内容和牌子脱节）。
       这里把放大量提上去（武林广场实测 S 2.3 → 2.9，店铺间距 +25%），
       马路线宽与小人尺寸在下面对应加粗放大，保证"一起放大"而不是只放大外框。 */
    var S = Math.max(0.5, Math.min(9, Math.min(VIEWW * 0.72 / cw, VIEWH * 0.72 / ch)));
    function T(p) {
      return [(p[0] - cc0[0]) * S + VIEWW / 2, (p[1] - cc0[1]) * S + VIEWH / 2];
    }

    var storeX = cp(store); storeX.px = T(store.px);
    var srcsX = srcs.map(function (s) { var o = cp(s); o.px = T(s.px); return o; });
    var rivsX = rivs.map(function (r) { var o = cp(r); o.px = T(r.px); return o; });
    var roadsX = roads.map(function (r) { var o = cp(r); o.pts = (r.pts || []).map(T); return o; });
    var flowsX = flows.map(function (f) {
      var o = cp(f); o.pts = (f.pts || []).map(T); return o;
    });
    var sp0 = storeX.px;

    /* 牌子**环绕**在横向椭圆上：按原始方位角排序后均匀铺开（保序 ⇒ 引线不交叉）。 */
    var items = [];
    srcsX.forEach(function (s, i) {
      items.push({k: 'src', i: i, px: s.px, w: 132 * K, h: 52 * K,
                  a: Math.atan2(s.px[1] - sp0[1], s.px[0] - sp0[0])});
    });
    rivsX.forEach(function (r, i) {
      items.push({k: 'riv', i: i, px: r.px, w: 96 * K, h: 36 * K,
                  a: Math.atan2(r.px[1] - sp0[1], r.px[0] - sp0[0])});
    });
    items.sort(function (p, q) { return p.a - q.a; });

    // 椭圆要**在内容之外**（内容半跨 0.72/2 = 0.36 视口，牌子半宽约 0.06）⇒ 半径 ≥ 0.42
    var RA = VIEWW * 0.425, RB = VIEWH * 0.44;
    var placed = [], boxOf = {src: {}, riv: {}};
    for (var it = 0; it < items.length; it++) {
      var nd = items[it];
      var ang = -Math.PI / 2 + (it + 0.5) * (2 * Math.PI / Math.max(1, items.length));
      var c = [sp0[0] + Math.cos(ang) * RA, sp0[1] + Math.sin(ang) * RB];
      for (var it2 = 0; it2 < 12; it2++) {          // 兜底避让
        var hit = null;
        for (var i2 = 0; i2 < placed.length; i2++) {
          var p2 = placed[i2];
          if (Math.abs(p2[0] - c[0]) < (p2[2] + nd.w) / 2
              && Math.abs(p2[1] - c[1]) < (p2[3] + nd.h) / 2) { hit = p2; break; }
        }
        if (!hit) break;
        c = [c[0], c[1] + nd.h * (0.95 + it2 * 0.14)];
      }
      placed.push([c[0], c[1], nd.w, nd.h]);
      boxOf[nd.k][nd.i] = c;
    }

    var vx = 0, vy = 0, vw = VIEWW, vh = VIEWH;
    var ccx = VIEWW / 2, ccy = VIEWH / 2;

    var svg = '<svg class="sbx-canvas" viewBox="' + [vx, vy, vw, vh].join(' ')
      + '" width="' + vw + '" height="' + vh
      + '" preserveAspectRatio="xMidYMid meet" role="img" '
      + 'style="--sbx-k:' + K.toFixed(3) + '" '
      + 'aria-label="仿真大屏：人流来源沿马路走向本铺与竞品店铺，持续动态">'
      + '<desc class="sbx-fit" data-cx="' + ccx + '" data-cy="' + ccy + '" data-w="' + vw
      + '" data-h="' + vh + '"></desc>';

    /* 底色 + 浅网格：都画成超出视口的大范围（超出部分被裁），
       因为 sbxFit 之后还会按容器真实宽高比再调一次 viewBox。
       ⚠️ 网格纯装饰 —— **不标数字**，避免被读成距离刻度。 */
    var FAR = 2600;
    svg += '<rect x="' + (ccx - FAR) + '" y="' + (ccy - FAR) + '" width="' + FAR * 2
         + '" height="' + FAR * 2 + '" fill="var(--zl-canvas)"/>';
    var gstep = 104 * K, ggrid = '';
    for (var gx = Math.ceil((ccx - FAR) / gstep) * gstep; gx < ccx + FAR; gx += gstep) {
      ggrid += '<line x1="' + gx.toFixed(1) + '" y1="' + (ccy - FAR) + '" x2="'
             + gx.toFixed(1) + '" y2="' + (ccy + FAR) + '"/>';
    }
    for (var gy = Math.ceil((ccy - FAR) / gstep) * gstep; gy < ccy + FAR; gy += gstep) {
      ggrid += '<line x1="' + (ccx - FAR) + '" y1="' + gy.toFixed(1) + '" x2="'
             + (ccx + FAR) + '" y2="' + gy.toFixed(1) + '"/>';
    }
    svg += '<g stroke="var(--zl-road)" stroke-width="' + (0.7 * K).toFixed(2)
         + '" opacity=".26">' + ggrid + '</g>';

    function sbxP(pts) {
      return 'M' + pts.map(function (p) {
        return p[0].toFixed(1) + ' ' + p[1].toFixed(1);
      }).join(' L');
    }

    // ① 分析半径（虚线圆）—— 真实像素半径也要跟着 S 缩放
    var rpx = meta['半径像素'];
    if (rpx) {
      svg += '<circle cx="' + sp0[0].toFixed(1) + '" cy="' + sp0[1].toFixed(1) + '" r="'
           + (rpx * S).toFixed(1) + '" fill="none" stroke="var(--zl-road-hi)" '
           + 'stroke-width="' + (1.6 * K).toFixed(2) + '" stroke-dasharray="'
           + (9 * K).toFixed(1) + ' ' + (8 * K).toFixed(1) + '" opacity=".7"/>';
    }

    // ② 马路骨架：走的人越多画得越粗
    roadsX.slice().sort(function (a, c) { return (c.count || 1) - (a.count || 1); })
      .forEach(function (r) {
        // 2026-09-21：内容放大后马路要**同步加粗**（否则相对内容反而显细）
        var base = (r.count >= 3) ? 22 : (r.count === 2 ? 16 : 10);
        svg += '<path d="' + sbxP(r.pts) + '" fill="none" stroke="var(--zl-road)" '
             + 'stroke-width="' + (base * K).toFixed(2) + '" stroke-linecap="round" '
             + 'stroke-linejoin="round"/>';
      });

    // ③ 去本铺的主客流路
    flowsX.forEach(function (f) {
      if (f.si_kind !== 'store') return;
      svg += '<path d="' + sbxP(f.pts) + '" fill="none" stroke="var(--zl-road-hi)" '
           + 'stroke-width="' + (5.6 * K).toFixed(2) + '" stroke-linecap="round" opacity=".6"/>';
    });

    // ④ 小人（画在节点下面）
    flowsX.forEach(function (f, fi) {
      var col = (f.si_kind === 'store') ? SBX_STORE_C : SBX_RIVAL_C;
      var n = Math.max(1, f.figures | 0);
      var dur = Math.max(2.6, (f.road_m || 120) / (1.2 * SIM_SPEED));
      for (var k2 = 0; k2 < n; k2++) {
        var begin = (dur * k2 / n + fi * 0.41) % dur;
        svg += sbxPerson(f.pts, col, dur.toFixed(1), begin.toFixed(2), K);
      }
    });

    // ⑤ 引线 + 锚点 + 人流来源牌
    function anchorDot(px) {
      return '<circle cx="' + px[0].toFixed(1) + '" cy="' + px[1].toFixed(1) + '" r="'
           + (3.4 * K).toFixed(2) + '" fill="var(--zl-card-val)" opacity=".85"/>';
    }
    function leader(from, to) {
      return '<path d="M' + from[0].toFixed(1) + ' ' + from[1].toFixed(1) + ' L'
           + to[0].toFixed(1) + ' ' + to[1].toFixed(1) + '" stroke="var(--zl-card-val)" '
           + 'stroke-width="' + (1.1 * K).toFixed(2) + '" opacity=".34" stroke-dasharray="'
           + (4 * K).toFixed(1) + ' ' + (4 * K).toFixed(1) + '"/>';
    }

    srcsX.forEach(function (s, si) {
      var w = 132 * K, h = 52 * K, c = boxOf.src[si];
      var x = c[0] - w / 2, y = c[1] - h / 2;
      svg += leader(s.px, c) + anchorDot(s.px) + '<g>'
        + '<title>' + esc(s.name) + '（' + esc(s.cat) + ' · 客流权重 '
        + Math.round((s.w || 0) * 100) + '% · 到本铺 ' + (s.to_store_m || 0)
        + 'm 步行）</title>'
        + '<rect x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '" width="' + w.toFixed(1)
        + '" height="' + h.toFixed(1) + '" rx="' + (12 * K).toFixed(1) + '" fill="' + s.color
        + '" opacity=".95" stroke="#fff" stroke-width="' + (1.2 * K).toFixed(2) + '"/>'
        + '<text class="sbx-t1" x="' + c[0].toFixed(1) + '" y="'
        + (c[1] - 3 * K).toFixed(1) + '" text-anchor="middle" fill="#fff">'
        + esc(s.short) + '</text>'
        + '<text class="sbx-t2" x="' + c[0].toFixed(1) + '" y="'
        + (c[1] + 16 * K).toFixed(1) + '" text-anchor="middle" fill="#fff" opacity=".93">客流 '
        + Math.round((s.w || 0) * 100) + '% · ' + (s.to_store_m || 0) + 'm</text>'
        + '</g>';
    });

    // ⑥ 竞品店铺牌
    rivsX.forEach(function (r, ri) {
      var w = 96 * K, h = 36 * K, c = boxOf.riv[ri];
      var x = c[0] - w / 2, y = c[1] - h / 2;
      svg += leader(r.px, c) + anchorDot(r.px) + '<g>'
        + '<title>' + esc(r.name) + '（竞品 · 步行 ' + (r.road_m || 0) + 'm'
        + (r.S ? ' · 品牌引力 ' + r.S : '') + '）</title>'
        + '<rect x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '" width="' + w.toFixed(1)
        + '" height="' + h.toFixed(1) + '" rx="' + (9 * K).toFixed(1) + '" fill="' + SBX_RIVAL_C
        + '" opacity=".93" stroke="#fff" stroke-width="' + (1.3 * K).toFixed(2) + '"/>'
        + '<text class="sbx-t3" x="' + c[0].toFixed(1) + '" y="'
        + (c[1] + 4.5 * K).toFixed(1) + '" text-anchor="middle" fill="#fff">'
        + esc(sbxCut(r.brand || r.name, 6)) + '</text>'
        + '</g>';
    });

    // ⑦ 本铺：呼吸光圈 + 标签 pill
    var r0 = 17 * K;
    svg += '<circle cx="' + sp0[0].toFixed(1) + '" cy="' + sp0[1].toFixed(1) + '" r="'
         + r0.toFixed(1) + '" fill="' + SBX_STORE_C + '" opacity=".22">'
         + '<animate attributeName="r" values="' + r0.toFixed(1) + ';'
         + (r0 * 2.1).toFixed(1) + ';' + r0.toFixed(1) + '" dur="2.8s" repeatCount="indefinite"/>'
         + '<animate attributeName="opacity" values=".30;.02;.30" dur="2.8s" '
         + 'repeatCount="indefinite"/></circle>'
         + '<circle cx="' + sp0[0].toFixed(1) + '" cy="' + sp0[1].toFixed(1) + '" r="'
         + (r0 * 0.88).toFixed(1) + '" fill="' + SBX_STORE_C + '" stroke="#fff" '
         + 'stroke-width="' + (3.2 * K).toFixed(2) + '"/>';
    var slab = '本铺' + (store.brand ? '·' + store.brand : '');
    var sw = (slab.length * 14 * 0.62 + 16) * K, sh = 27 * K;
    svg += '<rect x="' + (sp0[0] - sw / 2).toFixed(1) + '" y="'
         + (sp0[1] - r0 - 7 * K - sh).toFixed(1) + '" width="' + sw.toFixed(1) + '" height="'
         + sh.toFixed(1) + '" rx="' + (sh / 2).toFixed(1) + '" fill="' + SBX_STORE_C + '"/>'
         + '<text class="sbx-t0" x="' + sp0[0].toFixed(1) + '" y="'
         + (sp0[1] - r0 - 7 * K - sh * 0.3).toFixed(1) + '" text-anchor="middle" fill="#fff">'
         + esc(slab) + '</text>';
    svg += '</svg>';

    // ⑧ 顶部 HUD
    // ⚠️ 必须用服务端按**客流权重加权**算好的值。
    //    这里原来写的是 `Σ share`（把各来源的份额相加）——而 share 是每个来源
    //    **内部**归一化的（每个来源 Σshare=1），4 个来源各 30% 一加就是 120%。
    //    策当场看出"到铺率怎么在 100% 以上"，就是这处口径错（2026-09-21）。
    var toStore = (typeof meta['到本铺比例'] === 'number') ? meta['到本铺比例'] : 0;
    var hud = '<div class="sbx-hud">'
      + '<div class="sbx-kpi"><span class="k">人流来源</span><b>' + srcs.length + '</b></div>'
      + '<div class="sbx-kpi"><span class="k">竞品店铺</span><b>' + rivs.length + '</b></div>'
      + '<div class="sbx-kpi"><span class="k">走动小人</span><b>'
      + (meta['小人总数'] || 0) + '</b></div>'
      + '<div class="sbx-kpi"><span class="k">到本铺</span><b>'
      + Math.round(toStore * 100) + '%</b></div></div>';

    // ⑨ 图例 + 口径
    var leg = '<div class="sbx-legend">'
      + srcs.map(function (s) {
          return '<span class="sbx-lg"><i style="background:' + s.color + '"></i>'
               + esc(s.short) + '（' + Math.round((s.w || 0) * 100) + '%）</span>';
        }).join('')
      + '<span class="sbx-lg"><i style="background:' + SBX_STORE_C + '"></i>去本铺的人</span>'
      + '<span class="sbx-lg"><i style="background:' + SBX_RIVAL_C + '"></i>被竞品分流的人</span>'
      + '</div>';

    var note = '<div class="sbx-note">'
      + '小人的<b>数量</b> = 该来源的客流权重（取自 profile 的类别权重：'
      + (meta['来源类别'] || []).map(function (c) {
          return esc(c.short) + ' ' + Math.round((c.weight || 0) * 100) + '%';
        }).join(' / ')
      + '）；小人的<b>去向</b> = Huff 引力分流 ' + esc(meta['分流口径'] || '') + ' '
      + '轨迹：' + esc(meta['轨迹口径'] || '') + '；本条半径 ' + (meta['半径m'] || '-')
      + 'm，圈内取点。' + esc(meta['说明'] || '')
      + ' 这是<b>上一次</b>选址分析落盘的快照，不随新会话清空；要刷新就再跑一次分析。</div>';
    return hud + svg + leg + note;
  }

  /* 按**容器真实宽高比**二次贴合 viewBox。
     为什么需要：固定比例的 viewBox 装进任意比例的容器，必然 letterbox 出空白；
     而策要的是"横向、占满、少留白"（2026-09-21 10:48）。
     内容尺寸差一点不影响正确性 —— 只改视口，不动任何坐标。 */
  function sbxFit() {
    var svg = document.querySelector('#zl-pg-body .sbx-canvas');
    if (!svg) return;
    var d = svg.querySelector('desc.sbx-fit');
    if (!d) return;
    var r = svg.getBoundingClientRect();
    if (r.width < 40 || r.height < 40) return;
    var cx = parseFloat(d.getAttribute('data-cx'));
    var cy = parseFloat(d.getAttribute('data-cy'));
    var w = parseFloat(d.getAttribute('data-w'));
    var h = parseFloat(d.getAttribute('data-h'));
    if (!isFinite(cx) || !isFinite(w) || w <= 0 || h <= 0) return;
    var ratio = r.width / r.height;
    if (w / h < ratio) { w = h * ratio; } else { h = w / ratio; }
    svg.setAttribute('viewBox', [cx - w / 2, cy - h / 2, w, h].map(function (v) {
      return v.toFixed(1);
    }).join(' '));
  }
  window.addEventListener('resize', function () { sbxFit(); });

  /* ---- 仿真看板：独立入口页（2026-09-21） ----
     为什么要有这一页：看板原先只挂在右栏 analysis 的 `if (d.map_b64)` 里，
     而 dashboard.json 开新会话就被 clear ⇒ 用户在新会话里根本够不着。
     这一页读的是**独立快照** last_sim.json，生命周期与右栏解耦。 */
  function simBoardHTML(d) {
    var b = (d && d.board) || {};
    var h = '';
    // 从卡片页选进来的 ⇒ 给一个返回入口，否则用户只能关掉整页重开
    if (simPicked && simList.length) {
      h += '<button class="sbx-back" id="zl-sim-back">← 换个分析</button>';
    }
    /* ① 来源头（红线 4）：这份快照是哪次会话、什么时候、哪个铺子取的。
       没有这几行，用户在新会话里看到的图就是一张没有出处的图。
       ⚠️ 2026-09-21 从**表格压成一行 chip** —— 表格占掉三行高度，
       而策要的是"大屏占满子页面"，信息带必须让位给画面。 */
    function chip(k, v) {
      return '<span class="sbx-tag"><i>' + esc(k) + '</i>' + esc(String(v || '—')) + '</span>';
    }
    h += '<div class="sbx-src">'
       + (d['铺位'] ? '<b class="sbx-where">' + esc(String(d['铺位'])) + '</b>' : '')
       + chip('来源会话', String(d['来源会话'] || '').slice(0, 8))
       + chip('取证', d['取证时间'])
       + chip('品类', d['品类'])
       + chip('品牌', d['品牌'])
       + chip('经纬度', (d.lng != null && d.lat != null)
              ? (Number(d.lng).toFixed(5) + ', ' + Number(d.lat).toFixed(5)) : '')
       + chip('半径', d['半径m'] != null ? d['半径m'] + 'm' : '')
       + '</div>';
    /* ② 画面：**自绘**场景（不再叠底图） */
    if (b.ok) {
      h += simBoardScene(b);
    } else {
      h += '<div class="zl-kb-note">大屏不可用：'
         + esc(b['原因'] || (b.meta && b.meta['原因']) || '场景构造失败') + '</div>';
    }
    return h;
  }

  /* ---- 大屏的「挑哪一次」卡片页（2026-09-21 15:33 策要求）----
     与「对比分析」用**同一份** analyses.json（经 sidebar.json 的 sim_list 带过来），
     所以两处的铺位顺序完全一致，用户不会在两个入口里看到不同的编号。 */
  function simPickHTML() {
    var h = '';
    if (!simList.length) {
      return '<div class="zl-kb-note">还没有分析记录 —— 先跑一次选址分析，'
           + '这里会出现每次分析的卡片。</div>';
    }
    var usable = simList.filter(function (a) { return a.has_board; }).length;
    h += '<div class="zl-kb-sec" style="margin-top:0">选一次分析，看它的人流动线</div>';
    h += '<div class="sbx-hint">共 ' + simList.length + ' 次分析，其中 <b>' + usable
       + '</b> 次有大屏快照。小人从哪来、往哪家店走，是**那一次**的位置决定的，'
       + '所以要先选对分析。</div>';
    h += '<div class="sbx-cards">';
    simList.forEach(function (a) {
      var cls = 'sbx-card' + (a.has_board ? '' : ' off');
      h += '<button class="' + cls + '"'
        + (a.has_board ? ' data-simboard="' + esc(a.id) + '"' : ' disabled')
        + '>'
        + '<span class="sbx-c-shop">' + esc(a.shop || '（未命名）') + '</span>'
        + '<span class="sbx-c-meta">' + esc(a.category || '')
        + (a.category && a.ts ? ' · ' : '') + esc(a.ts || '') + '</span>'
        + '<span class="sbx-c-tot">地址评分 <b>'
        + (a.total != null ? Number(a.total).toFixed(1) : '—') + '</b></span>'
        + '<span class="sbx-c-vd">' + esc(a.verdict || '') + '</span>'
        + (a.has_board ? '<span class="sbx-c-go">看大屏 →</span>'
                       : '<span class="sbx-c-off">无大屏快照（旧分析）</span>')
        + '</button>';
    });
    h += '</div>';
    return h;
  }

  /* 选中某次分析 → 取它的大屏快照 → 直接渲染 */
  function loadSimBoard(sid) {
    fetch('/public/sim_boards/' + encodeURIComponent(sid) + '.json', { cache: 'no-store' })
      .then(function (r) { if (!r.ok) { throw new Error('no board'); } return r.json(); })
      .then(function (d) {
        simPicked = d;
        openPage('simboard');
      })
      .catch(function () {
        simBoardUnavailable('这次分析没有留下大屏快照 —— '
          + '旧版本跑的（那时还没做这个功能）或快照写入失败。重新分析一次即可。');
      });
  }

  /* 快照不可用时的兜底页 —— 不许"点了没反应" */
  function simBoardUnavailable(why) {
    ensurePageOv();
    pageOv.classList.add('open');
    pageOv.removeAttribute('data-id');
    document.getElementById('zl-pg-title').textContent = '仿真看板';
    document.getElementById('zl-pg-body').innerHTML =
      '<div class="zl-kb-note">' + esc(why) + '</div>';
    layoutBar();
  }

  /* 分析列表（供大屏卡片页）。只在拿到非空列表时覆盖，避免偶发空响应把列表清掉。 */
  function syncSimList(list) {
    if (list && list.length) { simList = list; }
  }

  /* 左栏按钮可用性 = 有没有快照（与右栏当前页无关） */
  function syncSimBoard(d) {
    var btn = document.getElementById('zl-simboard');
    if (!btn) return;
    // ⚠️ 主场景现在是 board（自绘大屏），sim 只是右栏那块热力图的叠加 —— 两者任一 ok 就算有。
    //    另外：即使"最近一次"没有快照，只要**历史上某次有**，按钮也应可用
    //    （否则用户明明有可看的大屏，按钮却是灰的）。
    var ok = !!(d && ((d.sim && d.sim.ok) || (d.board && d.board.ok)));
    lastSimData = ok ? d : null;
    var hasAny = ok || simList.some(function (a) { return a.has_board; });
    if (hasAny) {
      btn.classList.remove('disabled');
      btn.removeAttribute('disabled');
      // title 是**属性文本**不是 HTML，不能走 esc()，否则会原样显示 &amp; 之类
      btn.title = '打开上一次选址分析的仿真看板（'
                + String(d['取证时间'] || '—') + ' 取自 '
                + String(d['铺位'] || d['品类'] || '—') + '）';
    } else {
      btn.classList.add('disabled');
      btn.setAttribute('disabled', 'disabled');
      btn.title = '打开上一次选址分析的仿真看板（小人沿真实街道走向本铺）。'
                + '现在还没有跑过分析，所以暂时不可用 —— 先跑一次选址分析。';
    }
  }

  /* ---- 候选商铺卡片（可点击，点击即发"我选第N个"触发分析） ---- */
  /* 2026-09-17：加「租金/面积」数据可信度三态标签。
     三态必须**视觉可分**：实测（无标签）/ 推算（黄色"推算"）/ 不可得（灰色"未标"）——
     否则用户会把推算出来的租金当成平台挂牌价，而推算值会让净利/回本带上系统性偏差。 */
  // 定位层级文案（2026-09-17 诉求②）：门牌 > 楼宇 > 街区 > 区域。
  // 区域级必须显式写"无门牌" —— 用户抱怨的就是"给我的商铺地址有些又是区域级定位"，
  // 不写清楚就分不出"这个铺子在江陵路 88 号"和"这个铺子在滨江某处"。
  var ADDR_LEVEL_TXT = {
    door: '门牌级',
    building: '楼宇级',
    street: '街区级',
    area: '区域级·无门牌'
  };

  function candStateTag(state, kind) {
    if (state === 'derived') return '<span class="zl-tag warn">推算</span>';
    if (state === 'unavailable') return '<span class="zl-tag mute">未标</span>';
    return '';
  }

  function renderCandidates(d) {
    var cards = d.cards || [];
    var h = '';
    h += '<div class="zr-shop">' + esc(d.title || '候选商铺') + '</div>';
    if (d.hint) h += '<div class="zr-sub">' + esc(d.hint) + '</div>';
    h += '<div class="zr-cards cand-grid">';
    cards.forEach(function (c) {
      var info = [];
      if (c.area) {
        info.push(esc(c.area) + '㎡' + candStateTag(c.area_state, 'area'));
      }
      if (c.price != null) {
        info.push(esc(c.price) + '元/月' + candStateTag(c.rent_state, 'rent'));
      } else {
        info.push('租金未标');
      }
      // 房源性质（诉求③）：**三态** —— '转让' / '出租' / ''（判不出）。
      // ⚠️ 判不出的必须**不打标签**，不许默认成"房东招租"：那是替平台猜性质，
      //    既违反后端 `_deal_type` 的"判不出不标"，也会让用户把未知当成招租。
      //    实机抓到过：15 家里 11 家判不出，卡片却全标着"房东招租"。
      // ⚠️ 用独立 class（dl-tr / dl-rt），不能复用 warn / ok ——
      //    那两个 class 同时被「三态标签」探针用来数推算/未标
      //    （`live_ui_probe.py` §11 数 .zl-tag.warn），复用会把转让铺
      //    误统计成"推算值"，把数据可信度的口径搅浑。
      var tag = c.deal === '转让'
        ? '<span class="zl-tag dl-tr">转让</span>'
        : (c.deal === '出租'
           ? '<span class="zl-tag dl-rt">房东招租</span>' : '');
      var warn = '';
      var lv = c.addr_level || (c.precise === false ? 'area' : 'door');
      var lvTxt = ADDR_LEVEL_TXT[lv] || '区域级·无门牌';
      if (lv !== 'door') {
        warn += '<div class="cand-warn">📍 定位精度：' + esc(lvTxt) + '</div>';
      }
      if (c.rent_state === 'unavailable' || c.area_state === 'unavailable') {
        warn += '<div class="cand-warn">⚠️ 租金/面积不可得，不出经营评分</div>';
      } else if (c.rent_state === 'derived' || c.area_state === 'derived') {
        var why = c.rent_source || c.area_source || '推算值';
        var band = (c.rent_state === 'derived' && c.rent_band)
          ? '（区间 ' + esc(c.rent_band[0]) + '~' + esc(c.rent_band[1]) + ' 元/月）' : '';
        warn += '<div class="cand-warn">推算：' + esc(why) + band + '</div>';
      }
      if (c.deal === '转让') {
        // ⚠️ 这里不能用 markdown 的 ** 加粗：卡片是纯文本渲染，星号会原样露出来
        warn += '<div class="cand-warn">该铺是别人在转店：谈判对象是现任租户，'
          + '问清转让费、原租约剩余期、设备是否另计</div>';
      }
      h += '<button class="cand-card" data-choose="' + c.i + '" type="button" aria-label="选择第' + c.i + '家 ' + esc(c.name) + '">' +
        '<div class="cand-no">' + c.i + '</div>' +
        '<div class="cand-body">' +
        '  <div class="cand-name">' + esc(c.name) + ' ' + tag + '</div>' +
        '  <div class="cand-info">' + info.join(' · ') + '</div>' +
        '  <div class="cand-addr">' + esc(c.addr || '') + '</div>' + warn +
        '</div>' +
        '<div class="cand-go">→</div>' +
        '</button>';
    });
    h += '</div>';
    return h;
  }

  /* ---- 奶茶品牌卡片（可点击，点击即发"我选品牌XXX"触发确认） ---- */
  function renderBrands(d) {
    var cards = d.cards || [];
    var h = '';
    h += '<div class="zr-shop">' + esc(d.title || '选择加盟品牌') + '</div>';
    if (d.hint) h += '<div class="zr-sub">' + esc(d.hint) + '</div>';
    h += '<div class="zr-cards brand-grid">';
    cards.forEach(function (c) {
      var isSelf = !!c.self_created;
      // 可信度标签：TIER1 已标定 / TIER2 参考值 / TIER3 暂无标定
      var lab = c.tier === 'TIER1' ? '<span class="zl-tag cal">已标定</span>'
              : c.tier === 'TIER2' ? '<span class="zl-tag ref">参考值</span>'
              : '<span class="zl-tag ref">暂无标定</span>';
      var info = [];
      if (c.s != null) info.push('引力 ' + esc(c.s));
      if (c.invest_ref != null) info.push('起步投入约 ' + (c.invest_ref / 10000) + ' 万');
      else if (isSelf) info.push('无加盟费');
      var upTxt = '';
      if (c.uplift != null && !isSelf) {
        var pct = Math.round((c.uplift - 1) * 100);
        var sign = pct > 0 ? '+' : '';
        var ciTxt = c.ci ? '（区间 ' + esc(c.ci[0]) + '~' + esc(c.ci[1]) + '）' : '';
        upTxt = '<div class="brand-up' + (c.tier === 'TIER1' ? '' : ' ref') + '">' +
          '同商圈流水溢价 ' + sign + pct + '%' + ciTxt +
          (c.n ? '　n=' + esc(c.n) : '') + '</div>';
      } else if (isSelf) {
        // ⚠️ 百分比必须**从 c.uplift 取**，不许写死 —— v1 是 "+6%"，
        //    v6 整表重标定后已变成 "−16%"；写死的数字下次重标定就变假话。
        var spct = Math.round(((c.uplift != null ? c.uplift : 1) - 1) * 100);
        upTxt = '<div class="brand-up ref">按"个体/杂牌"标定，同商圈溢价 ' +
          (spct > 0 ? '+' : '') + spct + '%' +
          (c.n ? '　n=' + esc(c.n) : '') + '</div>';
      } else {
        upTxt = '<div class="brand-up ref">暂无同商圈溢价标定，按中性 ×1.00 处理</div>';
      }
      h += '<button class="brand-card' + (isSelf ? ' self' : '') + '" data-brand="' + esc(c.brand) + '" type="button" ' +
        'aria-label="选择品牌 ' + esc(c.brand) + '">' +
        '<div class="brand-no">' + c.i + '</div>' +
        '<div class="brand-body">' +
        '  <div class="brand-name">' + esc(c.brand) + ' ' + lab + '</div>' +
        '  <div class="brand-info">' + info.join(' · ') + '</div>' +
        '  <div class="brand-meta">' + esc(isSelf ? '没有加盟体系，自己起名字做' : '加盟品牌') + '</div>' +
        upTxt +
        '</div>' +
        '<div class="brand-go">→</div>' +
        '</button>';
    });
    h += '</div>';
    return h;
  }

  /* ---- 需求3：四品类推荐卡片（点卡片即发"我选XX"触发该品类的详细分析） ----
     排序依据是预估月净利（绝对量纲、跨品类可比）；竞争分跨品类不可比，
     故只在底部 note 里声明，不作为排序或推荐标签依据。 */
  function renderCategoryRec(d) {
    var cards = d.cards || [];
    var h = '';
    h += '<div class="zr-shop">' + esc(d.title || '这个位置更适合开什么？') + '</div>';
    if (d.hint) h += '<div class="zr-sub">' + esc(d.hint) + '</div>';
    h += '<div class="zr-cards cat-grid">';
    cards.forEach(function (c) {
      var lab = c.label === '首选' ? '<span class="zl-tag cal">首选</span>'
              : c.label === '可选' ? '<span class="zl-tag ok">可选</span>'
              : '<span class="zl-tag ref">谨慎</span>';
      var info = [];
      if (c.sales != null) info.push('月流水 ' + (c.sales / 10000).toFixed(1) + ' 万');
      if (c.net != null) info.push('月净利 ' + (c.net / 10000).toFixed(1) + ' 万');
      if (!info.length && c.error) info.push('测算失败');
      var pb = (c.payback != null)
        ? '回本约 ' + Math.round(c.payback) + ' 个月'
        : '回本周期不可算';
      h += '<button class="cat-card" data-cat="' + esc(c.category) + '" type="button" ' +
        'aria-label="选择品类 ' + esc(c.category) + '">' +
        '<div class="cat-no">' + c.i + '</div>' +
        '<div class="cat-body">' +
        '  <div class="cat-name">' + esc(c.category) + ' ' + lab + '</div>' +
        '  <div class="cat-info">' + info.join(' · ') + '</div>' +
        '  <div class="cat-meta">' + esc(pb) +
             (c.invest != null ? '　起步投入约 ' + Math.round(c.invest / 10000) + ' 万' : '') + '</div>' +
        (c.reason ? '  <div class="cat-reason">' + esc(c.reason) + '</div>' : '') +
        '</div>' +
        '<div class="cat-go">→</div>' +
        '</button>';
    });
    h += '</div>';
    if (d.note) h += '<div class="cat-note">' + esc(d.note) + '</div>';
    return h;
  }

  /* ---- 对比分析：卡片勾选 2-4 个历史分析 → 点开始对比 ---- */
  function renderComparePick(d) {
    var items = d.items || [];
    var h = '';
    h += '<div class="zr-shop">' + esc(d.title || '选择对比分析') + '</div>';
    if (d.hint) h += '<div class="zr-sub">' + esc(d.hint) + '</div>';
    h += '<div class="cp-grid">';
    items.forEach(function (it) {
      var dims_txt = '';
      if (it.dims) {
        var dl = [];
        Object.keys(it.dims).forEach(function (k) { dl.push(k + ' ' + it.dims[k]); });
        dims_txt = dl.join(' · ');
      }
      h += '<label class="cp-card" data-i="' + it.i + '">' +
        '<input type="checkbox" class="cp-chk" data-i="' + it.i + '">' +
        '<div class="cp-no">' + it.i + '</div>' +
        '<div class="cp-body">' +
        '  <div class="cp-name">' + esc(it.shop || ('分析 ' + it.i)) + '</div>' +
        '  <div class="cp-sub">' + esc(it.category || '') + ' ｜ ' + esc(it.ts || '') + '</div>' +
        '  <div class="cp-score">总分 <b>' + esc(it.total != null ? it.total : '-') + '</b>　<span class="cp-verdict">' + esc(it.verdict || '') + '</span></div>' +
        (dims_txt ? '<div class="cp-dims">' + esc(dims_txt) + '</div>' : '') +
        '</div>' +
        '<div class="cp-check">' + ico('check', 'cp-tick') + '</div>' +
        '<button class="cp-del" data-cpdel="' + esc(it.id || '') + '" type="button" title="删除该分析记录" aria-label="删除分析 ' + esc(it.shop || '') + '">' + ico('trash') + '</button>' +
        '</label>';
    });
    h += '</div>';
    h += '<button class="cp-go" id="cp-start" type="button" disabled>' +
      '<span id="cp-go-txt">请勾选 2-4 个分析</span></button>';
    return h;
  }

  /* 同步对比勾选状态：卡片高亮 + 按钮可用性（2-4 个） */
  function updateComparePick() {
    var go = document.getElementById('cp-start');
    var goTxt = document.getElementById('cp-go-txt');
    var n = 0;
    document.querySelectorAll('.cp-chk').forEach(function (c) {
      var card = c.closest('.cp-card');
      if (card) card.classList.toggle('picked', c.checked);
      if (c.checked) n++;
    });
    if (go) {
      if (n >= 2 && n <= 4) {
        go.disabled = false;
        if (goTxt) goTxt.textContent = '开始对比这 ' + n + ' 个分析';
      } else if (n > 4) {
        go.disabled = true;
        if (goTxt) goTxt.textContent = '最多只能选 4 个，请取消部分勾选';
      } else {
        go.disabled = true;
        if (goTxt) goTxt.textContent = '请勾选 2-4 个分析';
      }
    }
  }

  /* 删除对比卡片后重新编号 + 重置勾选状态 */
  function renumberCpCards() {
    var cards = document.querySelectorAll('.cp-card');
    cards.forEach(function (c, k) {
      var no = k + 1;
      c.setAttribute('data-i', no);
      var chk = c.querySelector('.cp-chk');
      if (chk) { chk.setAttribute('data-i', no); chk.checked = false; }
      var noEl = c.querySelector('.cp-no');
      if (noEl) noEl.textContent = no;
      c.classList.remove('picked');
    });
    updateComparePick();
  }

  function renderCompare(d) {
    var c = d.compare || {};
    var names = c.names || ['A', 'B'];
    var colors = ['#c9a45c', '#7ea6ad', '#4d7ea8', '#c96a5c'];   // 4 色，支持最多 4 个对比
    var h = '';
    h += '<div class="zr-shop">' + esc(d.shop || '对比') + '</div>';
    h += '<div class="zr-sub">' + esc(d.category || '') + '</div>';
    if (c.table && c.table.length) {
      h += '<div class="zr-sec">全方位对比</div><table>' +
        '<caption class="zr-cap">各分析结果全方位对比表</caption>';
      c.table.forEach(function (row) {
        h += '<tr><td class="k">' + esc(row[0]) + '</td>';
        for (var k = 1; k < row.length; k++) {
          h += '<td class="v" style="color:' + colors[(k - 1) % colors.length] + '">' + esc(row[k]) + '</td>';
        }
        h += '</tr>';
      });
      h += '</table>';
    }
    var dimKeys = c.dims ? Object.keys(c.dims) : [];
    if (dimKeys.length) {
      // 每个对比对象 = 一条雷达系列：values = 该对象在所有维度上的值
      var series = names.map(function (nm, di) {
        return { name: nm, color: colors[di % colors.length],
                 values: dimKeys.map(function (k) { return c.dims[k][di]; }) };
      });
      h += '<div class="zr-sec">多雷达对比</div><div class="zr-radar">' + radarSVG(dimKeys, series) + '</div><div class="zr-legend">' + names.map(function (nm, k) {
        return '<span style="color:' + colors[k % colors.length] + '">■ ' + esc(nm) + '</span>';
      }).join('　') + '</div>';
    }
    if (dimKeys.length) {
      h += '<div class="zr-sec">评分维度</div>' + barsHTML(c.dims, names, colors, function (v) { return v; });
    }
    if (c.metrics && Object.keys(c.metrics).length) {
      h += '<div class="zr-sec">经营指标</div>' + barsHTML(c.metrics, names, colors, function (v) { return fmtNum(v); });
    }
    return h;
  }

  /* 录入表单 */
  function renderInput(d) {
    var h = '';
    h += '<div class="zr-shop">录入经营信息</div>';
    h += '<div class="zr-sub">' + esc(d.hint || '') + '</div>';
    h += '<form class="zr-form" id="zl-input-form">';
    (d.fields || []).forEach(function (f, i) {
      var fid = 'zr-f-' + i;
      h += '<div class="zr-field"><label for="' + fid + '">' + esc(f.label) + (f.unit ? '<span class="u">（' + esc(f.unit) + '）</span>' : '') + '</label>' +
        '<input id="' + fid + '" type="text" data-key="' + esc(f.key) + '" placeholder="' + esc(f.placeholder || '') + '" value="' + esc(f.default || '') + '" autocomplete="off"/>';
      // 口径说明 + 加盟费门槛（2026-09-17 诉求④）。
      // floor 单位是**元**，但本表单投资字段的单位是**万元**，比较时必须换算，
      // 否则 11000 元会被当成 11000 万 —— 校验永远不触发（这种"看起来生效了"最危险）。
      if (f.note) {
        h += '<div class="zr-note">' + esc(f.note) + '</div>';
      }
      if (f.floor) {
        h += '<div class="zr-floor" data-floor="' + esc(f.floor) + '" data-brand="' + esc(f.floorBrand || '') + '"></div>';
      }
      h += '</div>';
    });
    h += '<div class="zr-form-actions">' +
      '<button type="button" class="zr-btn-ghost" id="zr-form-close">关闭</button>' +
      '<button type="submit" class="zr-btn-primary">提交并继续</button>' +
      '</div></form>';
    return h;
  }

  // 加盟费下限软校验（前端第一道；后端 collect_invest_node 是第二道）。
  // 只提示、不拦死：低于加盟费时要求再点一次"确认按此投入继续"。
  function checkInvestFloor(d, vals) {
    var inv = parseFloat(vals.investment);
    var fld = (d.fields || []).filter(function (f) { return f.key === 'investment'; })[0];
    var el = document.querySelector('#zl-input-form .zr-floor');
    if (!fld || !fld.floor || !isFinite(inv) || !el) return true;
    var invYuan = inv * 10000;                     // 表单单位是万元
    var floorYuan = Number(fld.floor);
    if (invYuan >= floorYuan) {
      el.className = 'zr-floor';
      el.textContent = '';
      return true;
    }
    if (el.getAttribute('data-acked') === '1') return true;   // 已确认过 -> 放行
    el.setAttribute('data-acked', '1');
    el.className = 'zr-floor warn';
    // ⚠️ floorText 本身就以"加盟费"开头，这里不能再写一遍
    //    —— 否则会念成"蜜雪冰城 加盟费 加盟费 ¥11,000"（实机抓到过）。
    el.textContent = '⚠️ ' + (fld.floorBrand || '该品牌') + '：' +
      (fld.floorText || ('加盟费 ¥' + floorYuan.toLocaleString())) +
      '，你填的 ' + inv + ' 万低于这个数。确认按此口径继续？再点一次「提交并继续」即可。';
    return false;
  }
  function composeInput(d, vals) {
    var parts = [];
    if (d.mode === 'invest') {
      if (vals.investment) parts.push('投入' + vals.investment + '万');
      if (vals.staff) parts.push(vals.staff + '人');
      if (!parts.length) return '';
      if (!vals.investment && vals.staff) parts.unshift('你定');
      return parts.join('，');
    }
    var flow = d.flow || '';
    if (vals.category) parts.push((flow === 'have_shop' ? '开' : '想开') + vals.category);
    if (vals.address) parts.push('地址' + vals.address);
    if (vals.rent) parts.push('月租' + vals.rent + '元');
    if (vals.area) parts.push('面积' + vals.area + '平');
    return parts.join('，');
  }
  document.addEventListener('submit', function (ev) {
    if (ev.target && ev.target.id === 'zl-input-form') {
      ev.preventDefault();
      var vals = {};
      ev.target.querySelectorAll('input[data-key]').forEach(function (inp) {
        vals[inp.getAttribute('data-key')] = (inp.value || '').trim();
      });
      var d = currentInput || {};
      if (d.mode === 'invest' && !checkInvestFloor(d, vals)) return;   // 未确认 -> 拦住本次提交
      var txt = composeInput(d, vals);
      if (txt) { sendCmd(txt); }
      else showQueue('请至少填写一项内容');
    }
  });

  var lastDashTs = null;
  /* 仿真看板快照（服务端 /public/last_sim.json）。
     单独存一份在内存里，是为了让左栏按钮的可用性**只取决于有没有快照**，
     而不取决于右栏当前是不是 analysis 页 —— 这正是"开新会话就点不到"的根因。 */
  var lastSimData = null;
  var lastSimTs = null;
  /* 仿真大屏的「挑哪一次」卡片页（2026-09-21 15:33 策要求：与对比分析一致）。
     simList  = 每次分析的摘要（来自 sidebar.json 的 sim_list，与服务端 analyses.json 同源）
     simPicked = 用户已经选中的那次的大屏快照；为空 ⇒ 显示卡片列表 */
  var simList = [];
  var simPicked = null;
  var lastContent = '';
  var currentInput = null;
  var wasPlaceholder = false;
  var prevBusy = false;

  function placeholderHTML() {
    return '<div class="zr-placeholder">分析完成后，选铺结论（评分 / 指标 / 周边环境）<br>将自动显示在这里</div>';
  }
  function setBusy(on) {
    var b = document.getElementById('zr-busy');
    var p = document.getElementById('zr-progress');
    if (b) b.classList.toggle('on', !!on);
    if (p) p.classList.toggle('on', !!on);
    var body = document.getElementById('zr-body');
    if (!body) return;
    if (on) {
      if (body.querySelector('.zr-placeholder') && !body.querySelector('.zr-skeleton') && !currentInput) {
        wasPlaceholder = true;
        body.innerHTML = '<div class="zr-skeleton"><div class="sk sk1"></div><div class="sk sk2"></div><div class="sk sk3"></div><div class="sk sk4"></div></div>';
      }
    } else {
      if (wasPlaceholder && body.querySelector('.zr-skeleton')) {
        wasPlaceholder = false;
        if (!currentInput) body.innerHTML = placeholderHTML();
      }
    }
  }

  function renderDashboard(d) {
    var body = document.getElementById('zr-body');
    if (!body) return;
    if (!d || !d.kind || d.kind === 'clear' || d.kind === 'empty') {
      currentInput = null; wasPlaceholder = false;
      applyWatermark('');
      body.innerHTML = placeholderHTML();
      return;
    }
    var html = '';
    if (d.kind === 'input') {
      currentInput = d;
      wasPlaceholder = false;
      html = renderInput(d);
      body.innerHTML = html;
      return;
    }
    if (d.kind === 'candidates') {
      currentInput = null; wasPlaceholder = false;
      html = renderCandidates(d);
      lastContent = html;
      body.innerHTML = html;
      // 候选列表出现 → 自动收拢执行过程（把空间留给选择卡片）
      collapseProcessStep();
      return;
    }
    if (d.kind === 'brands') {
      currentInput = null; wasPlaceholder = false;
      html = renderBrands(d);
      lastContent = html;
      body.innerHTML = html;
      // 品牌卡片出现 → 自动收拢执行过程（把空间留给选择卡片）
      collapseProcessStep();
      return;
    }
    if (d.kind === 'category-rec') {
      currentInput = null; wasPlaceholder = false;
      html = renderCategoryRec(d);
      lastContent = html;
      body.innerHTML = html;
      // 四品类推荐卡片出现 → 自动收拢执行过程
      collapseProcessStep();
      return;
    }
    if (d.kind === 'compare-pick') {
      currentInput = null; wasPlaceholder = false;
      html = renderComparePick(d);
      lastContent = html;
      body.innerHTML = html;
      collapseProcessStep();
      return;
    }
    if (d.kind === 'compare') html = renderCompare(d);
    else { html = renderAnalysis(d); applyWatermark(d.category); }
    currentInput = null;
    wasPlaceholder = false;
    lastContent = html;
    body.innerHTML = html;
  }

  /* ---- 10. a11y 增强（幂等）：标题层级 / 步骤播报 / 图标按钮命名 / 主题按钮中文名 ---- */
  function armA11y() {
    var title = document.querySelector('#zl-rail .zl-title');
    if (title && !title.getAttribute('role')) { title.setAttribute('role', 'heading'); title.setAttribute('aria-level', '1'); }
    document.querySelectorAll('#zl-right .zr-sec').forEach(function (el) {
      if (!el.getAttribute('role')) { el.setAttribute('role', 'heading'); el.setAttribute('aria-level', '2'); }
    });
    document.querySelectorAll('#zl-right .zr-shop').forEach(function (el) {
      if (!el.getAttribute('role')) { el.setAttribute('role', 'heading'); el.setAttribute('aria-level', '2'); }
    });
    // 执行过程步骤：内容变化对读屏播报
    document.querySelectorAll('.step[data-step-type] [role="region"]').forEach(function (el) {
      if (el.getAttribute('aria-live') !== 'polite') el.setAttribute('aria-live', 'polite');
    });
    // 主题切换按钮：中文可访问名
    document.querySelectorAll('button').forEach(function (b) {
      var t = (b.textContent || '').trim() || (b.getAttribute('aria-label') || '').trim();
      if (/^Toggle/i.test(t)) b.setAttribute('aria-label', '切换主题');
    });
    // 其余纯图标按钮补可访问名（头部菜单 / 附件 / 发送等）
    var ICON_NAMES = [
      ['M4 6h16M4 12h16M4 18h16', '打开菜单'],
      ['8.57-8.57A4', '添加附件'],
      ['22 2-7 20-4-9-9-4Z', '发送'],
      ['m3 11 18-8', '发送'],
      ['m22 2-7 20', '发送']
    ];
    document.querySelectorAll('button').forEach(function (b) {
      if ((b.getAttribute('aria-label') || '').trim()) return;
      if ((b.textContent || '').trim()) return;
      var p = b.querySelector('svg path');
      var d = p ? (p.getAttribute('d') || '') : '';
      var name = '按钮';
      for (var k = 0; k < ICON_NAMES.length; k++) if (d.indexOf(ICON_NAMES[k][0]) >= 0) { name = ICON_NAMES[k][1]; break; }
      b.setAttribute('aria-label', name);
    });
    // 发送按钮打标（深棕橙）；处理中/停止钮不打标（保持红色）
    var _sb = findSendBtn();
    if (_sb) {
      var _p = _sb.querySelector('svg path');
      var _dd = _p ? (_p.getAttribute('d') || '') : '';
      if (_dd) _sb.classList.add('zl-send'); else _sb.classList.remove('zl-send');
    }
  }

  /* ---- 10b. 左栏分组切换 ---- */
  function toggleGroup(grp) {
    if (!grp) return;
    var open = grp.classList.toggle('open');
    var hd = grp.querySelector('.zl-group-hd');
    if (hd) hd.setAttribute('aria-expanded', open ? 'true' : 'false');
  }

  /* ---- 10c. 设置（齿轮 → 全屏遮罩：说明 / 亮暗模式 / 字体大小 / 还原布局） ---- */
  var settingsEl = null, setViews = null, setTitle = null, setBack = null;
  function buildSettings() {
    settingsEl = document.createElement('div');
    settingsEl.id = 'zl-settings';
    settingsEl.innerHTML =
      '<div class="zl-set-panel">' +
      '<div class="zl-set-hd">' +
      '<button class="zl-set-back" id="zl-set-back" style="display:none" aria-label="返回">' + ico('arrow') + '</button>' +
      '<div class="zl-set-title" id="zl-set-title">设置</div>' +
      '<button class="zl-set-close" id="zl-set-close" aria-label="关闭">' + xIco() + '</button>' +
      '</div><div id="zl-set-views"></div></div>';
    document.body.appendChild(settingsEl);
    setViews = document.getElementById('zl-set-views');
    setTitle = document.getElementById('zl-set-title');
    setBack = document.getElementById('zl-set-back');
    document.getElementById('zl-set-close').addEventListener('click', closeSettings);
    settingsEl.addEventListener('click', function (e) { if (e.target === settingsEl) closeSettings(); });
    setBack.addEventListener('click', showSetMenu);
  }
  function openSettings() {
    if (!settingsEl) buildSettings();
    settingsEl.classList.add('open');
    showSetMenu();
  }
  function closeSettings() { if (settingsEl) settingsEl.classList.remove('open'); }
  function showSetMenu() {
    if (!settingsEl) buildSettings();
    setTitle.textContent = '设置';
    setBack.style.display = 'none';
    setViews.innerHTML =
      '<div class="zl-set-menu">' +
      '<div class="zl-set-item" data-set="help">' + ico('info') + '<span>说明</span><span class="arr">' + ico('arrow') + '</span></div>' +
      '<div class="zl-set-item" data-set="theme">' + ico('moon') + '<span>亮暗模式</span><span class="arr">' + ico('arrow') + '</span></div>' +
      '<div class="zl-set-item" data-set="font">' + ico('type') + '<span>字体大小</span><span class="arr">' + ico('arrow') + '</span></div>' +
      '<div class="zl-set-item" data-set="reset">' + ico('reset') + '<span>还原布局</span><span class="arr">' + ico('arrow') + '</span></div>' +
      '</div>';
    setViews.querySelectorAll('[data-set]').forEach(function (it) {
      it.addEventListener('click', function () {
        var s = it.getAttribute('data-set');
        if (s === 'help') showSetHelp();
        else if (s === 'theme') showSetTheme();
        else if (s === 'font') showSetFont();
        else if (s === 'reset') { resetLayout(); showQueue('已还原默认布局'); closeSettings(); }
      });
    });
  }
  function showSetHelp() {
    setTitle.textContent = '说明';
    setBack.style.display = 'inline-flex';
    setViews.innerHTML = '<div class="zl-set-sub">' +
      '<p><b>址南针</b> —— AI 商铺选址助手。</p>' +
      '<p>· <b>中间对话框</b>：告诉 AI「想开什么 + 开在哪里」，它会帮你找在租商铺并做选址分析；执行过程中的思考与工具调用会实时展开显示。</p>' +
      '<p>· <b>左侧操作栏</b>：快速操作（新建对话 / 导出分析 / 对比分析）、快速演示（内置 4 类范例）、历史会话（每条独立页面可继续对话）、知识库（选址打分依据与商业理论视频/论文）。</p>' +
      '<p>· <b>右侧工作台</b>：选铺结论（评分 / 指标 / 周边环境 / 盈利测算）。</p>' +
      '<p>· <b>两栏可拖动</b>：按住左栏/右栏顶部标题条左右拖动即可调整位置，聊天区会实时跟随。</p>' +
      '<p>· <b>切换模型</b>：在输入框回形针旁的下拉里选择 Doubao / DeepSeek / mimo，切换后续分析使用的 LLM。</p>' +
      '</div>';
  }
  function currentThemeMode() {
    var m = null; try { m = localStorage.getItem('zl_theme'); } catch (e) { /* ignore */ }
    return m || 'system';
  }
  function applyTheme(mode) {
    try { localStorage.setItem('zl_theme', mode); } catch (e) { /* ignore */ }
    if (mode === 'light') document.documentElement.classList.remove('dark');
    else if (mode === 'dark') document.documentElement.classList.add('dark');
    else {
      var dark = window.matchMedia('(prefers-color-scheme: dark)').matches;
      if (dark) document.documentElement.classList.add('dark');
      else document.documentElement.classList.remove('dark');
    }
    var sel = document.querySelector('#zl-set-views [data-theme].on');
    if (sel) sel.classList.remove('on');
    var cur = document.querySelector('#zl-set-views [data-theme="' + currentThemeMode() + '"]');
    if (cur) cur.classList.add('on');
    if (typeof wmStyle === 'function') wmStyle();   // 水印随主题换配色
  }
  function initTheme() {
    var m = null; try { m = localStorage.getItem('zl_theme'); } catch (e) { /* ignore */ }
    if (m) applyTheme(m);
  }
  function showSetTheme() {
    setTitle.textContent = '亮暗模式';
    setBack.style.display = 'inline-flex';
    setViews.innerHTML =
      '<div class="zl-set-sub">选择界面亮暗模式：</div>' +
      '<div class="zl-set-opt">' +
      '<button data-theme="light">' + ico('sun') + ' 浅色</button>' +
      '<button data-theme="dark">' + ico('moon') + ' 深色</button>' +
      '<button data-theme="system">跟随系统</button></div>' +
      '<div class="zl-set-note">「跟随系统」会随操作系统自动切换。</div>';
    setViews.querySelectorAll('[data-theme]').forEach(function (b) {
      b.addEventListener('click', function () { applyTheme(b.getAttribute('data-theme')); });
    });
    applyTheme(currentThemeMode());
  }
  function applyFont(size) {
    try { localStorage.setItem('zl_fs', size); } catch (e) { /* ignore */ }
    var f = size === 'small' ? 0.92 : (size === 'large' ? 1.12 : 1);
    document.documentElement.style.setProperty('--zl-fs', String(f));
    var sel = document.querySelector('#zl-set-views [data-font].on');
    if (sel) sel.classList.remove('on');
    var cur = document.querySelector('#zl-set-views [data-font="' + size + '"]');
    if (cur) cur.classList.add('on');
  }
  function initFont() {
    var s = null; try { s = localStorage.getItem('zl_fs'); } catch (e) { /* ignore */ }
    document.documentElement.style.setProperty('--zl-fs', s ? (s === 'small' ? '0.92' : s === 'large' ? '1.12' : '1') : '1');
  }
  function showSetFont() {
    setTitle.textContent = '字体大小';
    setBack.style.display = 'inline-flex';
    setViews.innerHTML =
      '<div class="zl-set-sub">调整界面字号（预览：）</div>' +
      '<div class="zl-set-opt">' +
      '<button data-font="small">小</button>' +
      '<button data-font="medium">中</button>' +
      '<button data-font="large">大</button></div>' +
      '<div class="zl-set-note">字号调整对左栏、右栏工作台与中间对话文本生效。</div>';
    setViews.querySelectorAll('[data-font]').forEach(function (b) {
      b.addEventListener('click', function () { applyFont(b.getAttribute('data-font')); });
    });
    var s = null; try { s = localStorage.getItem('zl_fs'); } catch (e) { /* ignore */ }
    applyFont(s || 'medium');
  }

  /* ---- 10d. 齿轮按钮（替代说明 + 亮暗切换） ---- */
  /* 每次轮询隐藏 Chainlit 自带的「说明 / 亮暗切换」按钮（纯图标用日/月形状识别，React 重渲染后也能持续隐藏） */
  function hideHeaderButtons() {
    document.querySelectorAll('header button, header > div button, button').forEach(function (b) {
      if (b.closest && b.closest('#zl-rail,#zl-right,#zl-settings,#zl-page-ov,#zl-veya')) return;
      var t = (b.textContent || '').trim();
      var al = (b.getAttribute('aria-label') || '').trim();
      var title = (b.getAttribute('title') || '').trim();
      var p = b.querySelector('svg path');
      var d = p ? (p.getAttribute('d') || '') : '';
      var hit = t === '说明' || t === 'Help' || t === 'Docs' ||
        t.indexOf('Toggle theme') >= 0 || al === '切换主题' || title === '切换主题' ||
        al === '说明' || al === 'Help' || al === 'Docs' ||
        d.indexOf('M12 2v2') >= 0 || d.indexOf('M20.985 12.486a9 9') >= 0 || d.indexOf('m4.9 4.9 1.4 1.4') >= 0;
      if (hit) b.style.display = 'none';
    });
  }
  function ensureGear() {
    if (document.getElementById('zl-gear')) return;
    var g = document.createElement('button');
    g.id = 'zl-gear';
    g.setAttribute('aria-label', '设置');
    g.title = '设置';
    g.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="20" height="20"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>';
    document.body.appendChild(g);
    g.addEventListener('click', openSettings);
  }

  /* ---- 10e. 切换模型下拉（与「选择专家」「自由对话」同一行） ---- */
  /* 挂载策略（自愈）：优先挂进专家条的右侧插槽 #xb-slot-md；
     专家条还没建出来时退回 Chainlit 输入框那一行，等专家条建好后再被收回插槽。
     这样"首次加载顺序"不会把控件永久留在错误位置。 */
  function homeSlot(id) {
    var slot = document.getElementById(id);
    return (slot && slot.id) ? slot : null;
  }
  function ensureModelSelect() {
    var lab = document.getElementById('zl-model-sel');
    lab = lab ? lab.parentElement : null;          // <label class="zl-model">
    if (!lab) {
      var ta = document.querySelector('textarea');
      if (!ta && !homeSlot('xb-slot-md')) return;  // 输入框与专家条都没有 → 无处可挂
      lab = document.createElement('label');
      lab.className = 'zl-model';
      lab.innerHTML = '<select id="zl-model-sel" aria-label="切换模型" title="切换模型">' +
        '<option value="" disabled selected>模型…</option>' +
        '<option value="Doubao-Seed-2.1-turbo">Doubao-Seed-2.1</option>' +
        '<option value="DeepSeek-V4-Flash">DeepSeek-V4</option>' +
        '<option value="mimo-v2.5">mimo-v2.5</option></select>';
      lab.querySelector('select').addEventListener('change', function () {
        if (this.value) sendCmd('##模型:' + this.value + '##');
      });
    }
    var slot = homeSlot('xb-slot-md');
    if (slot) {
      if (lab.parentElement !== slot) slot.appendChild(lab);   // 收回插槽（自愈）
    } else if (!lab.parentElement) {
      // 兜底：专家条建不出来时，仍挂到发送按钮左侧（右端），与回形针同一行
      var send = findSendBtn();
      var wrap = (document.querySelector('textarea') || {}).closest
        ? document.querySelector('textarea').closest('form') || document.querySelector('textarea').parentElement
        : document.body;
      if (send && send.parentElement) send.insertAdjacentElement('beforebegin', lab);
      else (wrap || document.body).appendChild(lab);
    }
    ensureFreeChatBtn();
  }
  function syncModelSelect(model) {
    var sel = document.getElementById('zl-model-sel');
    if (!sel || !model) return;
    if (sel.getAttribute('data-cur') !== model) {
      sel.value = model;
      sel.setAttribute('data-cur', model);
    }
  }

  /* ---- 10e-2. 需求4：「自由对话」开关（与「选择专家」「模型」同一行） ---- */
  function ensureFreeChatBtn() {
    if (document.getElementById('zl-freechat-btn')) return;
    var slot = homeSlot('xb-slot-fc');
    var sel = document.getElementById('zl-model-sel');
    // 专家条还没建出来时以模型下拉为锚（退回输入框那一行）；两者都没有就先不建
    if (!slot && (!sel || !sel.parentElement)) return;
    var btn = document.createElement('button');
    btn.id = 'zl-freechat-btn';
    btn.type = 'button';
    btn.className = 'zl-freechat';
    btn.setAttribute('aria-pressed', 'false');
    btn.title = '开启后不再触发选址流程，直接和你选择的模型聊天';
    btn.textContent = '自由对话';
    btn.addEventListener('click', function () {
      var on = btn.getAttribute('aria-pressed') !== 'true';
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
      btn.classList.toggle('on', on);
      sendCmd('##自由对话:' + (on ? 'on' : 'off') + '##');
      // 浮层提示替代"后端回一条文字消息"：开关是界面状态，不该占掉对话框一行
      showToast(on ? '自由对话：已开启（不再触发选址流程）'
                   : '自由对话：已关闭（回到常规选址流程）');
    });
    if (slot) slot.appendChild(btn);
    else sel.parentElement.insertAdjacentElement('afterend', btn);
  }
  function syncFreeChat(on) {
    var btn = document.getElementById('zl-freechat-btn');
    if (!btn) return;
    var cur = btn.getAttribute('aria-pressed') === 'true';
    if (!!on !== cur) {
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
      btn.classList.toggle('on', !!on);
    }
  }

  /* ---- 10e-3. 输入框上方的专家选择条（二级展开 · 恒跟随输入框） ---- */
  /* 数据来自 /public/sidebar.json 的 `experts` 字段（服务端由 registry 生成）。
     ⚠️ **不在前端写死 9 位专家** —— 写死就破坏了本项目"加专家 = 加 md 文件、不改代码"
     的约定，也等于把"人名"这份单一真源复制到第二个地方。 */
  var EXPERTS = [];      // [{id,alias,name,group,order,one_liner,blurb,start_sentence}]
  var CUR_EXPERT = '';   // 当前专家 id；'' = 未选，走默认顾问（按第一句话自动判断）
  var EX_SIG = '';       // 专家数据签名：只有真的变了才重绘，避免 2.5s 轮询重置面板滚动位置
  var EX_RENDERED = '';  // 上次已渲染的 "签名|当前专家"：内容没变就不动 DOM
  var CUR_LOCK = 0;      // 本地刚切过专家的时间戳：这段时间内不采纳服务端的旧值（防轮询回退）

  function findComposer() {
    var ta = document.querySelector('textarea');
    if (!ta) return null;
    var comp = ta.parentElement;      // 从父级开始找圆角 composer（与 findSendBtn 同一套判定）
    for (var i = 0; i < 8 && comp; i++) {
      var cls = typeof comp.className === 'string' ? comp.className : '';
      if (/rounded/.test(cls)) return comp;
      comp = comp.parentElement;
    }
    return ta.parentElement;
  }
  function expertById(id) {
    for (var i = 0; i < EXPERTS.length; i++) if (EXPERTS[i].id === id) return EXPERTS[i];
    return null;
  }
  /* ⚠️ 2026-09-18 欧文诉求：**定位（岗位名）放前面**，拟人名退后 ——
     一行里最显眼的位置留给“这个专家干什么的”，而不是“他叫什么”。
     这里是全站唯一真源：二级面板的 aria-label、切换 toast、顶部当前专家都从它取。 */
  function exLabel(e) { return e ? (e.alias ? e.name + ' · ' + e.alias : e.name) : ''; }
  /* 顶部“当前专家”要两种字重（定位粗主色 / 人名轻次色），所以不能塞纯文本 */
  function exCurHTML(e) {
    if (!e) return '<span class="xb-cur-role">默认顾问</span>';
    return '<span class="xb-cur-role">' + esc(e.name) + '</span>' +
      (e.alias ? '<span class="xb-cur-alias">' + esc(e.alias) + '</span>' : '');
  }

  /* 通用浮层提示：3 秒自动消失，不写进对话历史 */
  function showToast(msg, ms) {
    var t = document.getElementById('xb-toast');
    if (!t) { ensureExpertBar(); t = document.getElementById('xb-toast'); }
    if (!t) { showQueue(msg); return; }     // 极端兜底（输入框还没渲染出来时）
    t.textContent = msg;
    t.classList.add('on');
    clearTimeout(t._t);
    t._t = setTimeout(function () { t.classList.remove('on'); }, ms || 3000);
  }
  function caretUp() {
    return '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" ' +
      'stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
      '<path d="m6 15 6-6 6 6"/></svg>';
  }
  function ensureExpertBar() {
    var exist = document.getElementById('zl-xbar');
    if (exist) return exist;
    if (!findComposer()) return null;   // 输入框还没渲染出来 → 建了也没法定位
    var bar = document.createElement('div');
    bar.id = 'zl-xbar';
    // DOM 顺序：面板在前 → flex column 里自然向上展开；toggle 贴输入框
    /* 一行三控件：左「选择专家」，右「自由对话」「模型」。
       右侧用**固定插槽**而不是直接 appendChild：load() 每 2.5 秒轮询一次，
       靠 append 的顺序摆放控件会在重挂载时乱序；插槽天然幂等。
       面板仍在最前 —— flex column 下它就是"向上展开"。 */
    bar.innerHTML =
      '<div class="xb-panel" id="xb-panel" role="menu" aria-label="选择专家"></div>' +
      '<div class="xb-toast" id="xb-toast" role="status" aria-live="polite"></div>' +
      '<div class="xb-tools">' +
      '  <button class="xb-toggle" id="xb-toggle" type="button" aria-expanded="false" aria-haspopup="true" ' +
      '    aria-label="选择专家">' +
      '    <span class="xb-lab">专家</span><b class="xb-cur" id="xb-cur">' +
      '      <span class="xb-cur-role">默认顾问</span></b>' +
      '    <span class="xb-chev">' + caretUp() + '</span></button>' +
      '  <span class="xb-tools-r" id="xb-tools-r">' +
      '    <span class="xb-slot" id="xb-slot-fc"></span>' +
      '    <span class="xb-slot" id="xb-slot-md"></span>' +
      '  </span>' +
      '</div>';
    document.body.appendChild(bar);
    document.getElementById('xb-toggle').addEventListener('click', function (e) {
      e.stopPropagation();
      var open = bar.classList.toggle('open');
      this.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
    bar.addEventListener('click', function (e) {
      var row = e.target.closest && e.target.closest('[data-xid]');
      if (row) { e.stopPropagation(); switchExpert(row.getAttribute('data-xid')); }
    });
    // 面板向上展开必然盖住部分对话内容 —— 点外部收起是必须的
    document.addEventListener('click', function (e) {
      if (!bar.classList.contains('open')) return;
      if (e.target.closest && e.target.closest('#zl-xbar')) return;
      bar.classList.remove('open');
      var tg = document.getElementById('xb-toggle');
      if (tg) tg.setAttribute('aria-expanded', 'false');
    });
    /* 条子刚建出来 → 把「自由对话 / 模型」从输入框那一行收进右侧插槽。
       必须在 ensureExpertBar 内部做：load() 的调用顺序可能先走控件后走条子，
       只靠 load() 的先后无法保证控件最终落在这条上。 */
    ensureModelSelect();
    ensureFreeChatBtn();
    renderExpertBar();
    layoutBar();
    return bar;
  }
  function renderExpertBar() {
    var bar = document.getElementById('zl-xbar');
    if (!bar) return;
    var cur = expertById(CUR_EXPERT);
    var curEl = document.getElementById('xb-cur');
    if (curEl) {
      // 用 id 当签名：内容含两种字重，比 textContent 比对更稳（也免得每轮重挂）
      var sig = cur ? cur.id : '@default';
      if (curEl._sig !== sig) { curEl._sig = sig; curEl.innerHTML = exCurHTML(cur); }
    }
    var panel = document.getElementById('xb-panel');
    if (!panel) return;
    var key = EX_SIG + '|' + CUR_EXPERT + '|' + EXPERTS.length;
    if (key === EX_RENDERED && panel.childNodes.length) return;   // 内容没变 → 不动 DOM（防滚动位置被重置）
    EX_RENDERED = key;
    if (!EXPERTS.length) {
      panel.innerHTML = '<div class="xb-hd">专家列表加载中…</div>';
      return;
    }
    var h = '<div class="xb-hd">共 ' + EXPERTS.length + ' 位专家 · 点一行即切换</div>';
    EXPERTS.forEach(function (e, i) {
      var on = e.id === CUR_EXPERT;
      h += '<button class="xb-row' + (on ? ' cur' : '') + '" type="button" role="menuitem" ' +
        'data-xid="' + esc(e.id) + '">' +
        '<span class="xb-no">' + (i + 1) + '</span>' +
        '<span class="xb-body">' +
        '  <span class="xb-name"><b class="xb-role">' + esc(e.name) + '</b>' +
        '    <span class="xb-alias">' + esc(e.alias || '') + '</span></span>' +
        '  <span class="xb-desc">' + esc(e.blurb || e.one_liner || '') + '</span>' +
        '</span>' +
        '<span class="xb-tick">✓</span>' +
        '</button>';
    });
    panel.innerHTML = h;
  }
  /* 恒跟随输入框：position:fixed + 每轮 layout() 重算。
     这样"拖栏改宽 / 窗口 resize / 中间栏 margin 变化 / 输入区高度变化"都不会把它甩在原地。 */
  function layoutBar() {
    var bar = document.getElementById('zl-xbar');
    if (!bar) return;
    var ov = document.getElementById('zl-page-ov');
    var st = document.getElementById('zl-settings');
    var covered = (ov && ov.classList.contains('open')) ||
                  (st && st.classList.contains('open')) ||
                  document.body.classList.contains('zl-pdf-open');   // 需求 3：PDF 弹层打开时让出画面
    var comp = findComposer();
    if (covered || !comp) { bar.classList.add('hide'); return; }
    var r = comp.getBoundingClientRect();
    if (r.width < 60 || r.height < 10) { bar.classList.add('hide'); return; }
    bar.classList.remove('hide');
    bar.style.left = Math.round(r.left) + 'px';
    bar.style.width = Math.round(r.width) + 'px';
    // 锚 bottom 而不是 top：面板向上展开，锚底在"展开/收起"时不会自己下沉
    bar.style.bottom = Math.round(window.innerHeight - r.top + 8) + 'px';
    /* 面板限高：需求是"打开就是九行"，所以上限要够装 9 行（实测内容 ~756px）；
       但面板是往上长的，屏幕矮时必须让位，否则会顶出视口顶部。
       可用高度 = 输入框顶 − 8(bar 底留白) − toggle 高 − 6(gap) − 16(视口上边距)。
       只在数值变化时写 style，避免每轮 layout 都触发 layout thrash。 */
    var panel = document.getElementById('xb-panel');
    var tg = document.getElementById('xb-toggle');
    if (panel) {
      /* ⚠️ 这里必须量**整行**（.xb-tools）而不是单个 toggle：
         这行现在装三个控件，窄屏还会 flex-wrap 折成两行 —— 只减 toggle 的高度，
         算出来的 cap 会偏大，9 行面板会被顶出视口顶部。 */
      var tools = bar.querySelector('.xb-tools');
      var rowH = (tools && tools.getBoundingClientRect().height)
        || (tg ? tg.getBoundingClientRect().height : 30);
      var cap = Math.max(200, Math.min(820, Math.round(r.top - 8 - rowH - 6 - 16)));
      if (panel.getAttribute('data-cap') !== String(cap)) {
        panel.setAttribute('data-cap', String(cap));
        panel.style.maxHeight = cap + 'px';
      }
    }
  }
  function switchExpert(id) {
    var e = expertById(id);
    if (!e) return;
    CUR_EXPERT = id;
    CUR_LOCK = Date.now();          // 锁 6 秒：等后端把 current_expert 写进 sidebar.json，避免中途被旧值回退
    sendCmd('##专家:' + id + '##');   // 静默通道：白名单已含"专家"，对话框不留气泡
    showToast('已切换到 ' + exLabel(e) + '（数据不丢，只换视角）');
    renderExpertBar();
    var bar = document.getElementById('zl-xbar');
    if (bar) {
      bar.classList.remove('open');
      var tg = document.getElementById('xb-toggle');
      if (tg) tg.setAttribute('aria-expanded', 'false');
    }
    // 卡片页开着时同步高亮
    var pg = document.getElementById('zl-pg-body');
    if (pg && pg.querySelector('.zl-ex-grid')) pg.innerHTML = expertsPageHTML();
  }
  function syncExperts(list, cur) {
    if (list && list.length) {
      var sig = list.map(function (e) { return e.id + ':' + (e.alias || ''); }).join('|');
      if (sig !== EX_SIG) { EX_SIG = sig; EX_RENDERED = ''; }   // 清单变了 → 允许重绘
      EXPERTS = list;
    }
    // 本地刚切过（6 秒内）就不采纳服务端值：sendCmd 是异步的，
    // refresh_sidebar 还没跑完时轮询回来的 current_expert 仍是旧值，直接采纳会"弹回去"。
    if (cur !== undefined && Date.now() - CUR_LOCK > 6000) CUR_EXPERT = cur || '';
    renderExpertBar();
  }
  /* 专家系统卡片页正文（三行三列由 CSS grid 保证，见样式表 .zl-ex-grid） */
  function expertsPageHTML() {
    if (!EXPERTS.length) {
      return '<div class="zl-ex-intro">专家列表尚未就绪（服务端还没写入 sidebar.json）。' +
        '稍等片刻重新打开本页即可。</div>';
    }
    var h = '<div class="zl-ex-wrap">';
    h += '<div class="zl-ex-intro">这里一共 <b>' + EXPERTS.length + '</b> 位专家，覆盖开店全流程。' +
      '点任意一张卡片即可切换到该专家 —— 所有专家读的是<b>同一份会话数据</b>' +
      '（品类 / 铺位 / 评分 / 租金 / 流水），切换只换看问题的角度，前面的分析结果不会丢。</div>';
    h += '<div class="zl-ex-grid">';
    EXPERTS.forEach(function (e, i) {
      var on = e.id === CUR_EXPERT;
      h += '<button class="zl-ex-card' + (on ? ' cur' : '') + '" type="button" ' +
        'data-xpick="' + esc(e.id) + '" aria-label="切换到 ' + esc(exLabel(e)) + '">' +
        '<span class="zl-ex-top"><span class="zl-ex-no">' + (i + 1) + '</span>' +
        esc(e.group || '') + (on ? '<span class="zl-ex-cur">当前</span>' : '') + '</span>' +
        // 2026-09-18 欧文：定位在前、且最粗；拟人名退到后面对齐成次要标签
        '<span class="zl-ex-name">' + esc(e.name) +
        '<span class="zl-ex-tit">' + esc(e.alias || '') + '</span></span>' +
        '<span class="zl-ex-blurb">' + esc(e.blurb || e.one_liner || '') + '</span>' +
        '<span class="zl-ex-ex">例如：「' + esc(e.start_sentence || '') + '」</span>' +
        '</button>';
    });
    h += '</div>';
    h += '</div>';
    return h;
  }

  /* ---- 10f. 输入框下方免责声明 ---- */
  function ensureDisclaimer() {
    if (document.getElementById('zl-disclaimer')) return;
    // 隐藏可能存在的默认页脚文案
    document.querySelectorAll('div,span,p,footer').forEach(function (el) {
      if (el.children.length === 0) {
        var t = (el.textContent || '').trim();
        if (t.indexOf('大语言模型可能会犯错') >= 0 || t === 'Made with ❤️ by Chainlit') el.style.display = 'none';
      }
    });
    var ta = document.querySelector('textarea');
    if (!ta) return;
    var wrap = ta.closest('form') || ta.parentElement;
    var d = document.createElement('div');
    d.id = 'zl-disclaimer';
    d.className = 'zl-disclaimer';
    d.textContent = '分析基于公开 POI 数据，不含真实人流量与成交租金，结论为选址适宜度参考，建议现场复核。';
    // 追加到输入区容器最底部（对话框+按钮的最下面）
    if (wrap && wrap.parentElement) wrap.parentElement.appendChild(d);
    else document.body.appendChild(d);
  }

  /* ---- 10f2. 址南针罗盘 Logo（2026-09-18 策要求：原 Veyra 侦探弯月 logo 的同风格同配色重做）。
     风格承接：米色圆底 + 发丝边、藏青 #0e353a / 金 #c9a45c / 米白 #fdfbee 三色、线描为主、
     一处衬线小字（原「街」→ 现「南」）、米白光斑小点。
     主题语义：罗盘针尖**指南**——「址南针」就是「指南针」的选址变体。zv-bob 浮动呼吸动画沿用。 ---- */
  var ZS_TICKS = (function () {
    var s = '', i, a, card, ri, ro;
    for (i = 0; i < 24; i++) {
      a = i * 15 * Math.PI / 180;
      card = i % 6 === 0;                    /* 每 90° 一个正向刻度，加长加粗 */
      ri = card ? 36 : 39.5; ro = card ? 43.5 : 43;
      s += '<line x1="' + (50 + ri * Math.sin(a)).toFixed(1) + '" y1="' + (50 - ri * Math.cos(a)).toFixed(1) +
        '" x2="' + (50 + ro * Math.sin(a)).toFixed(1) + '" y2="' + (50 - ro * Math.cos(a)).toFixed(1) +
        '" stroke="#c9a45c" stroke-width="' + (card ? 1.6 : 1.05) + '" opacity="' + (card ? 1 : .72) +
        '" stroke-linecap="round"/>';
    }
    return s;
  })();
  var ZS_SVG =
    '<svg viewBox="0 0 100 100" width="100%" height="100%" role="img" aria-label="址南针罗盘 Logo" aria-hidden="true">' +
    /* 米色圆底 + 发丝边（与原 logo 同底） */
    '<circle cx="50" cy="50" r="47" fill="#fdfbee"/>' +
    '<circle cx="50" cy="50" r="47" fill="none" stroke="#e4dcc2" stroke-width="1.4"/>' +
    /* 罗盘刻度环：24 刻度、四正向加长（金色细密，对应原 logo 的街区路网） */
    ZS_TICKS +
    /* 内细圈：针面舞台 */
    '<circle cx="50" cy="50" r="31" fill="none" stroke="#e4dcc2" stroke-width="1"/>' +
    /* 罗盘针：北半藏青、南半金，针尖指南 */
    '<path d="M50 24 L55.5 50 L44.5 50 Z" fill="#0e353a"/>' +
    '<path d="M44.5 50 L55.5 50 L50 76 Z" fill="#c9a45c"/>' +
    /* 针身米白光斑（呼应原 logo 的月面小点） */
    '<circle cx="50" cy="32.5" r="1.6" fill="#fdfbee"/>' +
    '<circle cx="50" cy="60" r="1.2" fill="#fdfbee" opacity=".9"/>' +
    /* 南向针尖旁的「南」字（呼应原 logo 弯月上的「街」字） */
    '<text x="50" y="84.5" font-size="7" fill="#0e353a" text-anchor="middle" font-family="Noto Serif SC,STSong,SimSun,serif" font-weight="700">南</text>' +
    /* 中心轴：藏青圆 + 米色点 */
    '<circle cx="50" cy="50" r="4.4" fill="#0e353a"/>' +
    '<circle cx="50" cy="50" r="1.7" fill="#fdfbee"/>' +
    '</svg>';
  function ensureVeyra() {
    if (document.getElementById('zl-veya')) return;
    var col = document.querySelector('.flex.flex-col.flex-grow.overflow-y-auto');
    if (!col) return;
    var hd = document.createElement('div');
    hd.id = 'zl-veya';
    hd.innerHTML =
      '<div class="zv-logo">' + ZS_SVG + '</div>' +
      '<div><div class="zv-name">址南针</div><div class="zv-tag">你的 AI 商铺选址分析师</div></div>';
    col.insertBefore(hd, col.firstChild);
  }

  /* ---- 10f3. 隐藏控制指令气泡（## 指令 / 对比1和2，含 markdown 剥离后的形态）+ 出正文折叠步骤 ---- */
  var hideTarget = null, hideTargetAt = 0;   // 最近 sendCmd 发出的控制指令（标准化），精确隐藏对应气泡
  function normCmd(t) { return String(t || '').replace(/[#\s\u00a0]/g, ''); }
  /* ⚠️ 这张白名单是**一处真源**，但它在下面 4 个位置各引用一次（isCtrlCmd / 三条 isCmdText /
     整块判断 / MutationObserver 的 indexOf 探测）。2026-09-16 的 bug 就是"按自由对话按钮，
     对话框永久留下 ##自由对话:on## 字样"——根因不是闪烁，而是这 5 处**全都不含**自由对话与专家，
     所以 hideTarget 从未被设置、三条规则全部落空。加新的静默指令时，5 处必须一起改。 */
  var CTRL_ALT = '新对话|打开|删除|模型|导出|预览|自由对话|专家';
  function isCtrlCmd(t) { return new RegExp('^##(' + CTRL_ALT + ')').test(t) || t === '对比1和2'; }
  /* 软隐藏：让指令气泡"看不见但不脱离文档流"。
     ⚠️ 不能用 display:none —— 元素一脱离流，offsetTop 立刻变 0，
     Chainlit 的 autoscroll 会算出 scrollTo(0-20) 把对话框弹到最顶（需求 5 的根因）。
     零高度 + 溢出裁剪 + 透明，既能彻底看不见，又保留真实 offsetTop。 */
  function softHide(el) {
    if (!el || !el.style) return;
    el.style.display = '';
    el.style.height = '0';
    el.style.maxHeight = '0';
    el.style.overflow = 'hidden';
    el.style.margin = '0';
    el.style.padding = '0';
    el.style.border = '0';
    el.style.opacity = '0';
    el.style.pointerEvents = 'none';
  }
  function hideCmdBubbles() {
    var col = document.querySelector('.flex.flex-col.flex-grow.overflow-y-auto');
    if (!col) return;
    var now = Date.now(), target = hideTarget;
    function isCmdText(t) {
      if (!t) return false;
      // 完整命令 / 以##开头 / 对比指令 / 候选选择指令 / 纯指令文本（剥离空白与#后）
      // 加固：仅当文本本身就是指令形态（#开头）才隐藏；用户把正文跟在命令后（如「##导出## 顺便…」）不算
      if (/^##(新对话|打开|删除|模型|导出|预览|自由对话|专家)[:#]?/.test(t) && t.length <= 12) return true;
      if (/^##\s*(新对话|打开|删除|模型|导出|预览|自由对话|专家)/.test(t) && t.length <= 12) return true;
      if (/^##(新对话|打开|删除|模型|导出|预览|自由对话|专家)[\s\S]{0,80}##$/.test(t)) return true;
      if (t === '对比1和2' || normCmd(t) === '对比1和2') return true;
      if (/^我选第\s*\d+\s*个/.test(t)) return true;   // 候选卡片点击发出的选择指令
      if (target && now - hideTargetAt < 15000) {
        var n = normCmd(t);
        if (n === target) return true;   // 精确匹配，不再用 indexOf 前缀（防误伤「命令开头」的正文）
      }
      return false;
    }
    // A) 整块用户消息容器：文本整体即指令 → 隐藏整块（防 markdown 分段导致叶子匹配失败）
    var msgs = col.querySelectorAll('[data-step-type="user_message"],[data-step-type="user"],[class*="user"]');
    for (var mi = 0; mi < msgs.length; mi++) {
      var m = msgs[mi];
      if (!m.children || m.children.length === 0) continue;
      if (m === col) continue;
      var mt = (m.textContent || '').trim().replace(/\s+/g, '');
      // 指令形态（去空白后匹配），且块内没有明显的正常对话内容
      if (/^##(新对话|打开|删除|模型|导出|预览|自由对话|专家)/.test(mt) || mt === '对比1和2' || /^我选第\d+个/.test(mt)) {
        softHide(m);
      }
    }
    // B) 叶子级兜底
    var els = col.querySelectorAll('div,span,h1,h2,h3,h4,p,strong,em,li,button');
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      if (el.children && el.children.length > 0) continue;
      var t = (el.textContent || '').trim();
      if (!t) continue;
      if (isCmdText(t)) {
        var w0 = el.closest('[class*="message"],[class*="step"],[data-step-type]');
        var wrap = w0;
        if (!wrap || wrap === col) wrap = el;
        if (wrap !== col) softHide(wrap);
      }
    }
    if (target && now - hideTargetAt > 3000) hideTarget = null;   // 3 秒后清理目标，避免误伤后续真实对话
  }
  /* 「真内容」签名（2026-09-18 策定：执行过程要等对话框真正出了内容才收）。
     ⚠️ 为什么不用 DOM 顺序判定：实机诊断发现 Chainlit 把最终 assistant_message
     插在 run 步骤**之前**（compareDocumentPosition 返回 2 PRECEDING）——
     顺序判定会把本轮真消息全判成「旧消息」，永远不收。
     改用「签名变化」：提问时拍快照；回答攒到去空白 ≥12 字、签名变了才放行收缩。
     llm 壳/加载态（空文本）不进签名 → 不早收。 */
  var _lastMsgSig = null;
  function _realMsgSig() {
    var sig = '';
    document.querySelectorAll(
      '.step[data-step-type="assistant_message"], .step[data-step-type="llm"]')
      .forEach(function (m) {
        var len = (m.innerText || '').replace(/\s+/g, '').length;
        if (len >= 12) sig += len + ';';
      });
    return sig;
  }
  function collapseProcessStep() {
    var sig = _realMsgSig();
    if (!sig || sig === _lastMsgSig) return;   // 无真内容 / 没有新内容
    document.querySelectorAll('.step[data-step-type]').forEach(function (st) {
      if (!st.querySelector('.step[data-step-type]')) return;   // 仅最外层执行过程步骤
      if (st.getAttribute('data-collapsed') === 'true') return;
      var tog = st.querySelector('button[aria-expanded], [role="button"][aria-expanded]');
      if (tog) {
        if (tog.getAttribute('aria-expanded') === 'false') return;   // 已折叠
        tog.click();
      } else {
        st.setAttribute('data-collapsed', 'true');
      }
    });
    _lastMsgSig = sig;   // 本轮真内容只触发一次；用户手动展开后不会被反复收
  }

  /* ---- 10g. 知识库页 / 专家卡片页（中间栏覆盖层） ----
     ⚠️ 这个覆盖层**只剩两个用途**了：`openPage('theory'|'business'|'experts')`。
     历史会话那条路径在 2026-09-17 改走"聊天区回放"（§2），
     所以这里不再有 `继续对话` CTA、也没有 `renderHistPage`。 */
  var pageOv = null;
  function ensurePageOv() {
    if (pageOv) return;
    pageOv = document.createElement('div');
    pageOv.id = 'zl-page-ov';
    pageOv.innerHTML =
      '<div class="zl-pg-hd">' +
      '<button class="zl-pg-close" id="zl-pg-close" aria-label="返回">' + xIco() + '</button>' +
      '<div class="zl-pg-title" id="zl-pg-title"></div>' +
      '</div><div class="zl-pg-body" id="zl-pg-body"></div>';
    document.body.appendChild(pageOv);
    document.getElementById('zl-pg-close').addEventListener('click', closePage);
  }
  function closePage() {
    if (pageOv) { pageOv.classList.remove('open'); pageOv.removeAttribute('data-id'); }
    layoutBar();   // 覆盖层关了，专家条要重新显形
  }
  function openPage(kind) {
    ensurePageOv();
    pageOv.classList.add('open');
    pageOv.removeAttribute('data-id');
    var titleEl = document.getElementById('zl-pg-title');
    var bodyEl = document.getElementById('zl-pg-body');
    // 大屏页要撑满整个子页面（其余页保持可滚动的普通流式排版）
    bodyEl.classList.toggle('zl-pg-sim', kind === 'simboard');
    if (kind === 'experts') {
      titleEl.textContent = '专家系统 · 九位专家';
      bodyEl.innerHTML = expertsPageHTML();
      bodyEl.scrollTop = 0;
      layoutBar();
      return;
    }
    if (kind === 'simboard') {
      titleEl.textContent = '仿真大屏';
      if (simPicked) {
        bodyEl.innerHTML = simBoardHTML(simPicked);
      } else {
        // 没选过 ⇒ 先给卡片列表（与「对比分析」同款交互）
        bodyEl.innerHTML = simPickHTML();
      }
      bodyEl.scrollTop = 0;
      layoutBar();
      // 布局稳定后再贴合一次（layoutBar 会改尺寸，所以放到下一帧之后）
      if (simPicked) { requestAnimationFrame(function () { requestAnimationFrame(sbxFit); }); }
      return;
    }
    titleEl.textContent = kind === 'theory' ? '选址打分依据' : '商业理论知识';
    bodyEl.innerHTML = kind === 'theory' ? KB_THEORY : KB_BUSINESS;
    layoutBar();
  }
  /* `renderHistPage()`（历史会话只读中间页）已于 2026-09-17 删除（§2）。
     原实现把会话标题 + 右栏摘要 + 逐条消息渲染进 #zl-page-ov 覆盖层，
     由 openHistory() 与 conv_page.json 轮询两条路径调用。两条都改掉后，
     本函数没有任何调用方 —— 留着只会让后来人以为"历史页还是覆盖层"。
     现在的内容呈现是：后端把最近 N 条作为**真消息**回放进聊天区
     （app_chainlit.py: `_replay_emit` / `_replay_batch`）。 */

  /* ---- 10h. 知识库内容 ---- */
  /* 知识库·「选址打分依据」页的排版小工具。
     用函数生成表格/公式块，而不是手写上百个 <tr>：手写极易漏 </td>，
     而且文字一多没人敢改。三个 helper 都在本函数作用域内，声明会提升。
     · kbSec    : 分节标题（比卡片高一级）
     · kbCard   : 一张卡片 = 加粗小标题 + 正文（正文允许内联 <b>/<br>）
     · kbFml    : 公式块（等宽字体 + 虚线框；数组则逐行输出）
     · kbTable  : 数据表（单元格自动 esc，故表内不放 HTML） */
  function kbSec(t) { return '<div class="zl-kb-sec">' + t + '</div>'; }
  function kbCard(title, body) {
    return '<div class="zl-kb-theory"><b>' + title + '</b><br>' + body + '</div>';
  }
  function kbFml(lines) {
    var arr = (lines instanceof Array) ? lines : [lines];
    var h = '<div class="zl-kb-fml">';
    for (var i = 0; i < arr.length; i++) {
      h += (i ? '<br>' : '') + esc(arr[i]);
    }
    return h + '</div>';
  }
  function kbTable(head, rows) {
    var h = '<table class="zl-kb-tb"><thead><tr>';
    for (var i = 0; i < head.length; i++) h += '<th>' + esc(head[i]) + '</th>';
    h += '</tr></thead><tbody>';
    for (var r = 0; r < rows.length; r++) {
      h += '<tr>';
      for (var c = 0; c < rows[r].length; c++) h += '<td>' + esc(rows[r][c]) + '</td>';
      h += '</tr>';
    }
    return h + '</tbody></table>';
  }
  function kbNote(t) { return '<div class="zl-kb-note">' + t + '</div>'; }

  /* ⚠️ 本页在 2026-09-16 做过一次**口径纠正**，不只是"加内容"。
     改前的旧版写的是 v2 时代的东西，与现行引擎已经不符，三条都改掉了：
       ① 旧：「竞争环境 = 数同品类竞品数量，与 comp_base 比较，算竞品引力比」
          实：v4 起改成真 Huff 捕获份额 P，竞品"家数"已不直接进分数；
       ② 旧：「总分 >80 优质、60–80 中等、<60 谨慎」
          实：阈值是 ≥75 推荐 / ≥60 谨慎推荐 / ≥45 不建议优先 / <45 不建议，
              且**盈利不过关会一票否决**（旧版完全没提这条）；
       ③ 旧：「月流水 = 客单价 × 日单量」
          实：v5 起月流水由 D×P 结构式产出，客单价是品牌级"每单金额"（还踩过
              把高德单杯价当每单金额、少算 1.7 倍的坑）。
     教训：静态说明页会**悄悄腐烂**——算法改了页没改，答辩时说出来就是错的。
     所以下面每个数字都标了来源，改引擎时照着一处处核。 */
  var KB_THEORY =
    /* ===== 一、总览 ===== */
    kbSec('一、总览：一次评分是怎么走完的') +
    kbCard('两条并行的线，最后才合并',
      '系统同时跑两条互相独立的线：<b>位置线</b>（这家铺子值不值得占）与' +
      '<b>经营线</b>（这个租金下能不能赚钱）。两条线的结果都给出来，但' +
      '<b>不是相加</b> —— 最后用「盈利一票否决」合并（见第四节⑥）。<br>' +
      '刻意不让位置分去生成流水，是为了避开<b>循环论证</b>：' +
      '"用评分算流水、再拿流水证明评分对"，这种模型没法证伪自己。') +
    '<div class="zl-kb-theory">' +
      flowSVG(['商圈 POI 数据', '需求 D + 捕获份额 P', '四维打分', '加权总分', '位置结论']) +
      '<div style="height:10px"></div>' +
      flowSVG(['D×P 结构式', '成本拆解', '月净利', '回本周期', '一票否决']) +
    '</div>' +

    /* ===== 二、Huff 模型 ===== */
    kbSec('二、Huff 引力模型：是怎么建起来的') +
    kbCard('① 为什么不用「数竞品家数」',
      '最早的做法是统计半径内有多少家同类店，超过某个基准就算饱和。它的硬伤是：' +
      '<b>离你 50 米的一家店，和离你 800 米的一家店，被算得一样重。</b><br>' +
      'Huff(1963) 把这个问题改写成<b>概率分配</b>：消费者按"吸引力 ÷ 距离代价"的比例，' +
      '把光顾分摊给各家店。于是竞争不再是一个计数，而是一个<b>份额</b>。') +
    kbCard('② 模型结构式',
      '原始形式（Huff 1963）：' +
      kbFml('P_j = (S_j / d_j^λ) / Σ_k (S_k / d_k^λ)') +
      '本系统的写法（候选店 vs 半径内全部竞品）：' +
      kbFml('P = (S_自 / d0^λ) / [ S_自 / d0^λ + Σ_k S_k / (d_k + d0)^λ ]') +
      '分子是候选店自己的引力，分母是"自己 + 半径内所有同类竞品"的引力之和。' +
      '这样 P 天然落在 0~1，含义是<b>这家店能从周边同类里抢到多少需求</b>。' +
      '竞品的 S_k 由店名经品牌系数表识别，识别不出按 1.0 计；' +
      '非奶茶品类没有品牌表，自动退化为 S=1.0 的纯距离 Huff（行为与旧版一致）。') +
    kbCard('③ 距离衰减系数 λ 为什么取 2.0',
      'λ <b>不是逐店拟合出来的</b>，而是"取文献常用值 + 做敏感性检验"：' +
      'Huff 系实证研究常用 1.5~2.5，本系统取 2.0。稳健性证据：' +
      kbTable(['λ 对比', '门店排名 Spearman', 'Top10 重合'], [
        ['2.0 vs 1.0', '0.957', '70%'],
        ['2.0 vs 2.5', '0.994', '90%'],
        ['2.0 vs 3.0', '0.985', '90%'],
      ]) +
      '83 家真实门店在 λ∈[1.0, 3.0] 全区间变动时，两两排名相关<b>最低 0.921</b>；' +
      '文献区间 1.5~2.5 内最低 <b>0.976</b>（<b>2026-09-20 按步行路网距离重算</b>；直线口径下为 0.937 / 0.981）。所以正确说法是' +
      '"<b>结论不依赖 λ 的精确取值</b>"，不是"我们估出了 λ"。') +
    kbCard('④ 最小等效距离 d0 = 50 米是干什么的',
      '两个作用：① 避免 d→0 时引力发散（分母趋 0 会爆炸）；' +
      '② 模拟"店门前 50 米"这段无论如何都要走的到店距离。' +
      '它同时出现在分子与分母，所以口径自洽。') +
    kbCard('⑤ 品牌引力 S 怎么分档',
      kbTable(['档位', 'S', '代表', '依据'], [
        ['绝对头部', '2.5', '蜜雪冰城', '全国 3 万+ 家'],
        ['万店级', '2.2', '古茗 / 瑞幸（咖啡）', '古茗门店密度全国前列；瑞幸 3.1 万家但只部分产品线分流奶茶'],
        ['高势能', '2.0', '霸王茶姬 / 喜茶 / 爷爷不泡茶', '数千家、品牌势能强'],
        ['万店级', '1.8', '沪上阿姨 / CoCo / 奈雪 / 茶百道', '门店量级'],
        ['数百家连锁', '1.2~1.6', '茶理宜世 / LINLEE / 裕莲茶楼 等', '区域强势连锁'],
        ['个体 / 杂牌', '1.0', '（默认档）', '无品牌势能'],
      ]) +
      kbNote('实证校验：同商场内（控制住位置变量）品牌系数 vs 外卖月售 Spearman = 0.414，' +
        '方向与量级成立。用途边界：<b>只用于相对竞争力排序，不代表真实流水倍数</b>。' +
        '口径说明：瑞幸确实超过 3 万家，但它是<b>咖啡连锁</b>——在奶茶品类里只有轻乳茶/' +
        '茶咖等部分产品线与奶茶店抢同一杯需求，所以<b>不按 3 万+ 档给 2.5</b>，' +
        '而与古茗同档取 2.2（避免高估它的分流强度）。')) +
    kbCard('⑥ 需求规模 D 怎么算',
      kbFml('D = 0.8 × (学校 POI + 办公 POI + 社区 POI) + 0.2 × 商圈 POI') +
      '0.8 : 0.2 是"日常客流为主、商圈客流为辅"的结构性假设。' +
      '统计半径按品类取：奶茶 500m、甜品 800m、早餐 300m、便利店 500m。' +
      '三类日常 POI 全为 0 时判为<b>数据稀疏</b>，流水按 3 折保守处理并明确提示人工复核。') +

    /* ===== 三、系数标定 ===== */
    kbSec('三、系数是怎么标定出来的') +
    kbCard('① 流水锚点 REF_DP = 4.82',
      '含义："一家中位水平门店的 D×P"。标定方法：把<b>宁波天一广场、杭州湖滨 in77、' +
      '海宁银泰 3 个商圈的 83 家真实门店</b>，用与线上完全相同的查询路径跑一遍 D×P，' +
      '剔除 8 个低证据点后对 75 家取<b>中位数</b>（<b>步行路网距离</b>口径）。于是任意点位的流水估计有了基准：' +
      '中位门店 = 品类基准日单量。') +
    kbCard('② 竞争分锚点 P_REF = 0.6024',
      '同一次标定的 75 家门店捕获份额<b>中位数</b> → 定义"中等竞争 = 60 分"。' +
      '映射式：' +
      kbFml('s = 60 × P / P_REF   （封顶 100）') +
      kbNote('⚠️ 口径纪律：REF_DP 与 P_REF 必须由<b>同一次标定</b>产出、同为' +
        '"品牌一致 + 剔除低证据点后中位 + 未做密度调整"的口径，' +
        '<b>不能单独替换其中一个</b> —— 两个值口径不一致，阈值就失去意义。') +
      kbNote('⚠️ <b>口径变更（2026-09-20）</b>：距离口径换成<b>步行路网距离</b>' +
        '（高德步行规划，按铺位冻结在本地库）后，这两个锚点已<b>成对重标</b> —— ' +
        'REF_DP 6.2489 → <b>4.82</b>、P_REF 0.5012 → <b>0.6024</b>，' +
        '口径同为"剔除 (D<3 且 P>0.8) 后取中位"（83 家保留 75 家）。' +
        '旧的"P_REF 复现为 0.4997"注记随本次重标失效。') +
      kbNote('⚠️ <b>样本范围局限</b>：这 83 家只覆盖 3 个商圈，而 UPLIFT 又依赖' +
        '"同商圈内比较"——所以它标出的是 3 个大商业区内部的相对水平，' +
        '不能当作全省通行结论。本系统另有 <code>expand_sample.py</code> 用本地 POI 库' +
        '把样本扩到数百家做稳健性复核。')) +
    kbCard('③ 为什么锚点不按品牌分别标定',
      '实测方差分解（83 家门店）：' +
      kbTable(['模型', '参数个数', 'R²'], [
        ['仅商圈哑变量', '2', '0.6946'],
        ['仅品牌哑变量', '9', '0.0795'],
        ['品牌 + 商圈', '11', '0.7354'],
      ]) +
      '<b>2 个商圈哑变量解释 69.5%；9 个品牌哑变量只解释 8.0%。</b><br>' +
      '决定性证据：同一个品牌换个商圈，D×P 差 4 倍以上 —— 蜜雪 4.58 倍、' +
      '沪上阿姨 4.61 倍、CoCo 4.02 倍。<br>' +
      '用户是在<b>新商圈找铺</b>：给他一个"在宁波标出来的品牌锚点"，到海宁会错 4 倍。' +
      '所以锚点保持统一，品牌差异改走 UPLIFT。') +
    kbCard('④ 品牌同商圈溢价 UPLIFT',
      '既然商圈效应远大于品牌效应，正确做法是<b>在商圈内部比品牌</b>，把商圈差异消掉。' +
      '⚠️ 但要拿<b>品牌盲</b>的 D×P 去比 —— 因为 D×P 里的品牌差异本身就来自品牌引力 S，' +
      '直接比会把它<b>重复计入一次</b>：' +
      kbFml(['DP_blind = D × P（自己 S 置 1.0、竞品 S 保持真实）',
             'uplift_b = median( 该店 DP_blind / 该商圈 DP_blind 中位 )',
             'uplift   = 1 + w · (uplift_b − 1)，  w = n / (n + 5)']) +
      '含义：<b>1.0</b> = 该品牌门店的<b>位置/竞争微区位</b>与所在商圈的中位店相当；' +
      '<b>1.16</b> = 好 16%。<br>' +
      '<b>2026-09 两次口径变更</b>：① 样本从"3 个人工大商圈 / 77 家 / 9 个品牌"换成' +
      '"代理商圈 + 全库奶茶门店"共 <b>1508 家 / 28 个品牌</b>（v1 的 n=4~13 让 5% 效应的' +
      '检验功效只有 0.07~0.42，"不显著"其实是<b>样本不足</b>）；' +
      '② 比值换成"品牌盲残差"，消掉与品牌引力的重复计入（见下方局限）。<br>' +
      '<b>常见品牌</b>（按标定样本量取前 10 —— <b>不是</b>按溢价高低排）：' +
      kbTable(['品牌', 'uplift', '等级', 'n', 'bootstrap 95% 区间'], [
        ['个体 / 杂牌', '1.0000', 'TIER2', '504', '1.000 ~ 1.051'],
        ['古茗', '0.9970', 'TIER2', '200', '0.940 ~ 1.000'],
        ['蜜雪冰城', '1.0000', 'TIER2', '154', '0.985 ~ 1.019'],
        ['一点点', '0.9851', 'TIER2', '75', '0.915 ~ 1.031'],
        ['霸王茶姬', '1.0000', 'TIER2', '75', '0.953 ~ 1.038'],
        ['茶百道', '0.9005', 'TIER2', '69', '0.855 ~ 1.000'],
        ['CoCo', '0.9835', 'TIER2', '55', '0.857 ~ 1.000'],
        ['沪上阿姨', '1.0000', 'TIER2', '55', '0.903 ~ 1.032'],
        ['瑞幸', '1.3271', 'TIER1', '42', '1.117 ~ 1.250'],
        ['喜茶', '1.0399', 'TIER2', '40', '0.999 ~ 1.238'],
      ]) +
      kbNote('⚠️ <b>可靠性分级</b>：TIER1（n ≥ 10 且区间排除 1.0）直接采用点估计；' +
        'TIER2（n ≥ 3）采用但标注"参考值"；样本不足（n &lt; 3）<b>强制取 1.0，不编数字</b>。<br>' +
        '⚠️ <b>这条路走过一次弯路，留在页面上当教训</b>：上一版（v6）的定义是' +
        '"该店 D×P ÷ 同商圈 D×P 中位"，而 D×P 里的品牌差异<b>本身就来自品牌引力 S</b>' +
        '（P 的分子是自己那项的 S、分母是周边竞品）—— 于是它在<b>重复计入品牌力</b>，' +
        '而品牌力已经通过 S 进过一次流水，这就成了<b>双算</b>。它当时的表象是' +
        '「蜜雪 1.1903、个体/杂牌 0.8370」，看着很有信息量，其实只是把 S 换个说法。<br>' +
        '换成"品牌盲残差"后：<b>蜜雪 1.1903 → 1.0018、个体/杂牌 0.8370 → 1.0111</b>' +
        '（Spearman(品牌引力, 溢价) 从 +0.67 降到 +0.15）。' +
        '<b>所以它只能读作"这家的位置比同商圈中位店好/差多少"——' +
        '不是品牌溢价，更不能读成"流水就会高这么多"。</b><br>' +
        '完整 28 个品牌（含 CI 与 n）见 src/engine/brands.py 的 UPLIFT 四张表。')) +

    /* ===== 四、四维评分 ===== */
    kbSec('四、四个维度与权重') +
    kbCard('① 每个维度怎么算',
      kbTable(['维度', '怎么算'], [
        ['客群匹配度',
          '取"最强单项客群"的 Huff 引力（各类客群 POI 按距离衰减累计）作为主分，' +
          '其余类别做多样性加分（封顶 +20）。装修档次按投入金额推断，±8 分内修正。'],
        ['竞争压力',
          '由捕获份额 P 映射：s = 60 × P / P_REF，封顶 100；半径内无同类竞品时给中性 75 分。'],
        ['交通可达性',
          '最近地铁距离分段（≤300m 95 分 / ≤800m 80 / ≤1500m 55 / 更远 35），' +
          '再加公交站密度加分（封顶 +10）。'],
        ['租金承受力',
          '月租 ÷ 预估月流水，相对品类阈值（rent_ratio）分档给分。'],
      ]) +
      kbNote('客群匹配度取"最强单项"而不是要求四类齐全：不同商圈结构各有强项' +
        '（学校型 / 办公型 / 社区型都能开店），硬要求齐全会把特色商圈误杀。')) +
    kbCard('② 权重（按品类不同）',
      kbTable(['品类', '客群匹配度', '竞争压力', '交通可达性', '租金承受力'], [
        ['奶茶', '0.35', '0.25', '0.25', '0.15'],
        ['甜品', '0.35', '0.20', '0.25', '0.20'],
        ['早餐', '0.30', '0.20', '0.35', '0.15'],
        ['便利店', '0.40', '0.25', '0.20', '0.15'],
      ]) +
      kbNote('权重是<b>人工设定的经验值</b>，不是回归出来的 —— 总分本身就是加权和，' +
        '用回归去"验证"它等于抄定义式（详见第五节①）。设定逻辑：客群匹配度决定' +
        '"有没有人"，通常最高；<b>早餐的交通权重最高</b>，因为早餐本质是"抢通勤动线"；' +
        '<b>甜品的租金权重最高</b>，因为需要商圈氛围与展示面积，租金占比本就更敏感；' +
        '租金的普遍逻辑是：它可以通过谈判与选址互相置换，且终归会进成本测算。')) +
    kbCard('③ 面积适配度（填了面积才启用，固定 10%）',
      kbTable(['品类', '最佳区间', '理想面积'], [
        ['奶茶', '15 ~ 50 ㎡', '30 ㎡'],
        ['甜品', '30 ~ 80 ㎡', '50 ㎡'],
        ['早餐', '10 ~ 40 ㎡', '20 ㎡'],
        ['便利店', '30 ~ 100 ㎡', '60 ㎡'],
      ]) +
      '区间内离理想面积越远扣得越多；区间外快速衰减。启用时其余四维按原比例缩放到 90%。') +
    kbCard('④ 门头形象（上传门头照才启用，固定 10%）',
      kbFml('形象分 = 0.5 × 装修档次 + 0.3 × 门头可见度 + 0.2 × 卫生观感') +
      '三项各按 1~5 分档，映射到 0~100。两条硬约束：' +
      '<br>① <b>只认门头实景照</b> —— logo、宣传图、室内局部一律不计分，' +
      '避免用假证据污染总分；' +
      '<br>② <b>只增加"形象"这一个维度，不改任何经营测算</b>（流水/成本/回本原样不动），' +
      '也<b>不能绕过盈利一票否决</b> —— 否则传一张好看的照片就能把"账算不过来"洗回"推荐"。') +
    kbCard('⑤ 总分与结论阈值',
      kbFml('总分 = Σ (维度分 × 权重)') +
      kbTable(['总分', '结论'], [
        ['≥ 75', '推荐'],
        ['60 ~ 74.9', '谨慎推荐'],
        ['45 ~ 59.9', '不建议优先选择'],
        ['< 45', '不建议'],
      ]) +
      kbNote('⚠️ 阈值是人工设定的经验值，<b>没有外部依据</b>；' +
        '不同品类的分数也不可直接横比（权重不同、竞品基数不同）。')) +
    kbCard('⑥ 盈利一票否决：为什么位置分救不了亏损',
      '加权是<b>补偿性</b>的 —— 位置分够高，能把低了的分补回来。' +
      '这正是"总分 80 分、月净利却是负的"的成因。' +
      '而"这个租金下亏钱"是<b>非补偿性</b>硬约束：位置再好也不能签。' +
      '所以当<b>月净利 ≤ 0</b>，或<b>回本周期 &gt; 24 个月</b>时，直接改写结论：' +
      kbTable(['原位置分结论', '否决后'], [
        ['推荐', '位置好 · 账算不过来'],
        ['谨慎推荐', '账算不过来'],
        ['不建议优先 / 不建议', '保持不变（原本就为负的不动）'],
      ]) +
      kbNote('不提高"租金承受力"权重来替代否决，是因为加权永远能被其他维度补回来，' +
        '而亏损是硬约束。')) +

    /* ===== 五、回归与统计检验 ===== */
    kbSec('五、回归分析是怎么做的（以及刻意不做什么）') +
    kbCard('① 先说不能做的：不能用回归"验证权重"',
      '总分的定义就是 <b>总分 = Σ(维度分 × 权重)</b>，一个无截距的加权和。' +
      '拿 OLS 去回归它，必然得到 β ≡ 声明权重、R² ≡ 1：' +
      kbTable(['维度', 'OLS β', '声明权重', '差'], [
        ['客群匹配度', '0.350359', '0.3500', '+3.6e−04'],
        ['竞争压力', '0.250292', '0.2500', '+2.9e−04'],
        ['交通可达性', '0.250231', '0.2500', '+2.3e−04'],
        ['租金承受力', '0.149301', '0.1500', '−7.0e−04'],
      ]) +
      'R² = 0.99998。这是<b>定义式的算术结果，不是数据证据</b>。' +
      '把它报告成"回归验证了权重"是<b>伪严谨</b>，答辩时一问就穿 —— ' +
      '这个坑我们踩过，已写进文档以免后人重犯。') +
    kbCard('② 真正有信息量的检验：维度分自洽性',
      '维度分<b>不是</b>恒等式的产物，它是位置变量的函数，所以能检验"方向对不对"：' +
      kbTable(['维度', '上游变量', '预期', '实测 Pearson', '结论'], [
        ['客群匹配度', '需求规模 D', '正', '+0.5259', 'p &lt; 0.001 ✓'],
        ['竞争压力', '捕获份额 P', '正', '+0.8834', 'p &lt; 0.001 ✓'],
        ['交通可达性', '最近同类距离', '负', '−0.0532', '不显著，方向正确 ✓'],
      ]) +
      '三条方向全部正确，其中 <b>竞争压力 ↔ 捕获份额 = +0.8834</b> 是最有力的一个数：' +
      '它直接印证了竞争分的 P 映射在真实数据上成立。') +
    kbCard('③ 为什么 D 和 P 不能放进同一个回归',
      '实测 D 与 P 相关 <b>−0.511</b> —— 需求密集的地方竞品同样密集，份额被摊薄。' +
      '两者混放会产生 <b>suppression</b>：' +
      kbTable(['模型', 'β(P)'], [
        ['竞争压力 ~ P', '+82.17'],
        ['竞争压力 ~ P + D', '+82.17（β(D) = −0.42）'],
        ['客群匹配度 ~ P', '−63.84'],
        ['客群匹配度 ~ P + D', '−49.10  ← 符号直接翻转'],
      ]) +
      '所以规矩是：<b>每个维度只对自己的上游变量做单变量回归</b>。' +
      '这是刻意规避，不是遗漏。') +
    kbCard('④ λ 也做了参数估计，但边界要说清',
      kbFml(['log(月售) = 10.0819 + 0.5469·log(1/(d+50)) + 0.6549·log(S)',
             'R² = 0.2184,   n = 83',
             'λ 点估计 = 0.5469,   95% CI = [0.165, 0.929]']) +
      kbNote('⚠️ <b>这个置信区间不覆盖文献值 2.0。</b>必须主动说明两个原因，不能藏：' +
        '① log-log 形式只有一个距离弹性，与引擎里"含竞品求和项"的 Huff 式' +
        '<b>并不等价</b>；② 因变量是外卖月售，而这个代理已被证伪（见⑦）。' +
        '所以 λ=2.0 的正当理由是<b>敏感性检验</b>（见③），不是这个点估计。')) +
    kbCard('⑤ 竞争分映射式的线性检验',
      's = 60·P/P_REF 不是拟合出来的，是手写的参数化假设。检验结果：<br>' +
      '· 未截断区（P ≤ 0.6667，n=61）：<b>61/61 家逐点精确等于 round(150·P)</b>，零偏离；<br>' +
      '· 自由拟合斜率 95%CI [149.06, 150.41] 覆盖 150；Wald 检验不拒绝斜率=150、' +
      '也不拒绝截距=0（即纯比例、过原点）。' +
      kbNote('⚠️ 检验纪律：蓝海分支（无竞品给 75 分）与截断点必须<b>先隔离</b> —— ' +
        '常数混进残差会把高区标准差虚报成 8.78（实际为 0），' +
        '截断点混进来会把斜率人为压低到 89。')) +
    kbCard('⑥ 高区为什么不用"软饱和"恢复区分度',
      '事实：<b>P &gt; 0.8353 时竞争分一律 100</b>，热门点位（杭州 in77、武林广场、' +
      '海宁银泰）在竞争维度上并列满分、不可区分。<br>' +
      '我们评估过"保持低区不动的软饱和"，但<b>它在数学上不存在</b>：' +
      '希望同时满足 ①P=P* 处 s=100 ②P&gt;P* 处单调不减 ③恒有 s≤100 —— ' +
      '但 P* 处 s 已达上界 100，由 ②③ 推出 s(P)≥100 且 s(P)≤100，故 s(P)≡100。' +
      '要恢复区分度<b>必须放弃条件 ①</b>（如改用全程 Hill 式），' +
      '那会改变 60 分锚点的含义、牵动整条标定链，而竞争分权重仅 0.25、' +
      '头部门店又高度集中在同一商圈 —— 收益不足以偿付改模型的风险，故保留封顶并作为局限声明。') +
    kbCard('⑦ 为什么不做"选址分 → 营收"的对外效度检验',
      '因为<b>因变量不成立</b>。用外卖月售作经营代理做过检验：它与模型核心预测子 P 的相关是' +
      '<b>−0.229（p = 0.037）</b>，方向与预期相反；与其他变量全部不显著（p = 0.10~0.77）。' +
      '在这个前提下做回归，等于拿一个<b>已被自己证伪的因变量</b>去拟合模型。' +
      '所以我们不做，而是明确列为后续数据扩充计划：补到真实营业额（如窄门餐眼）' +
      '或成交租金（如 58 同城）后，把因变量换掉即可复用同一套脚本。') +

    /* ===== 六、经济学口径 ===== */
    kbSec('六、经济学口径：钱是怎么算的') +
    kbCard('① 月流水怎么产出（D×P 结构式）',
      kbFml(['月流水 = 日单量 × 每单金额 × 30',
             '日单量 = 基准日单量 × (D×P)/REF_DP × 面积修正 × 城市修正 × 品牌溢价 × 0.6']) +
      kbTable(['项', '取值', '说明'], [
        ['基准日单量', '品类画像（奶茶 250 单/天）', '来自 83 家中位门店参考'],
        ['D×P', 'Huff 结构产出', '需求池大小 × 捕获份额'],
        ['REF_DP', '4.82', '83 家真实门店（剔低证据后 75 家）中位锚点 · 步行路网口径'],
        ['面积修正', '低于区间下限按比例（最低 0.4）；超上限 1.5 倍取 0.85',
          '面积太小承载不了理想单量'],
        ['城市修正', '杭州 / 宁波 1.0，其他 0.85', '核心城市客流与消费力差异'],
        ['品牌溢价', 'UPLIFT', '同商圈内校准'],
        ['保守系数', '0.6', '开业爬坡期'],
      ]) +
      kbNote('保守系数 0.6 的含义：开业前 3~6 个月客流通常只有成熟店的 6~7 成。' +
        '它是<b>刻意的保守假设</b>（不是实测值），好处是所有回本结论都建立在' +
        '"假设爬坡不顺利"的前提下。')) +
    kbCard('② 每单金额的口径陷阱（这个坑我们踩过）',
      '高德 POI 的 cost 字段官方定义是"人均消费"，但在茶饮类目<b>实测值 ≈ 单杯价</b>，' +
      '不是<b>每单金额</b>。而公式里的日单量是"订单数"，两者口径不同：' +
      kbTable(['品牌', '高德 cost', '公开单杯价', '公开每单金额'], [
        ['蜜雪冰城', '¥7.0', '¥6.72', '¥11.4'],
        ['霸王茶姬', '¥20.0', '¥20.48', '≈ ¥20'],
      ]) +
      kbNote('⚠️ 直接把单杯价当每单金额乘进去 = <b>少算约 1.7 倍</b>（一单平均约 1.7 杯），' +
        '会让低价品牌全线显示亏损、回本周期翻倍 —— <b>结论方向都是错的</b>。' +
        '正确做法：优先用公开披露的"每单平均零售额"，缺失时才用"单杯价 × 每单 1.7 杯"换算，' +
        '并把这个不确定性交给下面第③条的"口径区间"呈现。')) +
    kbCard('③ 价格变了单量会不会变：一个未标定的自由度',
      '日单量基准 250 单/天是从 <b>83 家混合品牌</b>门店标定的中位数（蜜雪只占 16.9%），' +
      '隐含绑定 ¥16 那一档定价；而客单价校正是<b>品牌级</b>的。' +
      '只换单价、不换单量，在经济学上等价于假设<b>需求量对价格完全无弹性</b>（弹性 = 0）；' +
      '而现实恰恰相反 —— 低价品牌靠高频走量，弹性在 −1 与 0 之间。<br>' +
      '现有样本<b>无法标定它</b>（校准用表里没有任何营业数据），所以<b>不编一个弹性出来</b>，' +
      '改为并列两个建模极端：' +
      kbTable(['口径', '价格弹性', '含义'], [
        ['单量刚性', '0', '品牌不改变日单量：低价就按低价卖同样杯数'],
        ['营业额刚性', '−1', '品牌不改变营业额：低价就必须卖出更多杯'],
      ]) +
      kbNote('实测（宁波天一广场、30 ㎡、蜜雪、每单 ¥11.4）：月流水 ¥93,783 ~ ¥131,626，' +
        '月净利 ¥13,181 ~ ¥26,077。两端各自算出的盈亏平衡月租之间（<b>≈¥22,500 ~ ¥35,000</b>）' +
        '会给出完全<b>相反</b>的结论。系统不用"稳健／不稳健"两档了事，而是分四档：' +
        '<b>稳健</b>／<b>比较稳健</b>／<b>比较不稳健</b>／<b>不稳健</b>' +
        '（档位说明的是"结论有多确定"，不表示生意好坏）。落到后两档时系统会明确提示：' +
        '必须去核实该品牌在该商圈的<b>真实日单量</b>，不要只依据报告里的单一数字。<br>' +
        '⚠️ 上端净利<b>不是</b>按流水同比例放大的结果：该端日单量已跨过 2 人产能档' +
        '（人均 140 单/天 ×2 = 280）→ 测算按 <b>3 人</b>计人工，台阶吃掉了流水增量。' +
        '即区间<b>宽度本身含一个产能台阶</b>，不是纯经济量。<br>' +
        '⚠️ <b>口径留痕</b>（数字会随口径动，旧值不删）：v1 是 ¥99,552~¥139,722 / ' +
        '¥10,265~¥30,069（窗口 ¥21,000~¥39,000）；v6 是 ¥104,467~¥146,620 / ' +
        '¥12,688~¥27,709（窗口 ¥22,000~¥36,500）；现值是 2026-09-18 把品牌溢价' +
        '换成"品牌盲残差"（消双算）后的实测。')) +
    kbCard('④ 口径区间 ≠ 置信区间（别混）',
      kbTable(['对比项', '三档情景区间', '口径区间'], [
        ['变的假设', '成本假设（商场扣点 / 物业 / 税负 / 损耗 / 产能）',
          '需求假设（日单量跟不跟客单价动）'],
        ['取值', '乐观 / 中性 / 保守', '单量刚性 / 营业额刚性'],
        ['能读成概率吗', '不能', '不能'],
      ]) +
      '两者<b>方向不同、可以叠加</b>，所以必须并列展示，<b>不许合并成一个区间</b> —— ' +
      '那会把两种不确定性混成一种，掩盖掉"需求侧未标定"这个更根本的问题。' +
      kbNote('⚠️ 口径区间还是<b>单侧</b>的：报告里每个单点数字都取自"单量刚性"端，不是中点。' +
        '低价品牌的单点 = 区间的<b>悲观端</b>；高价品牌 = <b>乐观端</b>。')) +
    kbCard('⑤ 成本拆解与毛利率口径',
      kbFml(['月净利 = 月流水 − 物料 − 损耗 − 外卖抽成 − 场地成本(租金+物业)',
             '        − 人工 − 水电 − 摊销 − 品牌费 − 杂费',
             '',
             '毛利率 = (月流水 − 物料 − 损耗) / 月流水      ← 产品口径']) +
      kbNote('外卖抽成<b>不进毛利率</b>（它是渠道费用，不是产品成本），但必须<b>并列输出</b>：' +
        '外卖抽成占流水比 = 外卖占比 × 佣金率（如 30% × 22% ≈ 6.6%），以及"扣渠道后毛利率"。' +
        '三条理由：① 毛利率是行业通用口径，自创一个就没法与招股书等外部数据对照；' +
        '② 抽成是渠道费用；③ 混进去会掩盖"<b>外卖占比本身就是成本杠杆</b>"这件事。' +
        '<br>⚠️ 术语陷阱：<b>佣金率 22% ≠ 抽成占流水 7.7%</b> —— 后者还要乘外卖占比。')) +
    kbCard('⑥ 回本红线为什么定在 24 个月',
      '因为 <b>3 年租约里，只有前两年回本、最后一年才是真正赚到的</b>。' +
      kbNote('⚠️ 它刻意<b>不等于</b>摊销月数 36：回本 = 投入 /(月净利 + 月摊销)，' +
        '而月摊销 = 投入 / 摊销月数。两者相等时，"回本 = 摊销月数"与"净利 = 0"' +
        '是同一个方程 —— 第二个临界点会与盈亏平衡点恒等、信息量为零，' +
        '还会让谈判筹码把同一个数字说两遍当成两个条件。' +
        '<br>另一条相关结论：<b>提高流水不一定改善回本</b>（用工人数按日单量台阶跳，' +
        '人数跳档时人工成本台阶上升、净利反而可能回落）。')) +

    /* ===== 七、局限 ===== */
    kbSec('七、模型局限（必须与结论一同呈现）') +
    kbCard('答辩时主动说的七条边界',
      '1. <b>输入数据</b>：基于公开 POI 数据，<b>不含真实人流量、成交租金、真实营业额</b>。<br>' +
      '2. <b>参数性质</b>：λ 为文献值 + 稳健性检验，非逐店标定；品牌系数 S 与溢价 UPLIFT ' +
      '是分档参考值，<b>用于相对排序，不是流水倍数</b>。⚠️ 这两者曾经<b>同源</b>：' +
      '旧版 uplift 由 D×P 算出、而 D×P 的品牌差异只来自 S，把 S 抹掉后 uplift 就回到 1.0 ' +
      '——存在<b>重复计入品牌力</b>（双算）。现行版本已改成"品牌盲残差"把这一层消掉' +
      '（蜜雪 1.1903→1.0018、个体/杂牌 0.8370→1.0111），所以 UPLIFT 现在只读作' +
      '"<b>这家的位置/竞争微区位在同商圈里好多少</b>"，<b>不是</b>品牌溢价。<br>' +
      '3. <b>品类覆盖</b>：品牌表与 UPLIFT 只对奶茶标定过，其他品类自动退化为 S=1.0 的' +
      '纯距离 Huff；REF_DP / P_REF 其他品类沿用奶茶量级（近似）。<br>' +
      '4. <b>样本量</b>：品牌溢价样本 1508 家门店 / 28 个品牌（n = 3~504，2026-09 整表重标定，' +
      '2026-09-21 起改用<b>步行路网距离</b>重标）；' +
      '但本地库覆盖不完整（实测 in77 库内 19 家 vs 实时 49 家 = 39%），' +
      '且商圈口径已由"人工大区"改为"最近商圈 POI"——故只能做<b>同商圈内的相对比较</b>，' +
      '跨口径、跨城市外推都需重新标定。⚠️ 2026-09 这一张表改过两次口径' +
      '（先把样本从小扩到大，再把比值换成品牌盲残差），<b>旧报告里的数字不回填</b>。<br>' +
      '5. <b>未标定的自由度</b>：价格—单量弹性未标定 → 用"口径区间"并列两个极端呈现，不编系数。<br>' +
      '6. <b>已知截断</b>：P &gt; 0.8353 时竞争分一律 100，热门点位在竞争维度上不可区分。<br>' +
      '7. <b>输出性质</b>：是"选址适宜度相对评分"，<b>不是营收预测</b>。') +
    kbNote('本页所有数字都可在项目内复跑：标定脚本在 analysis/ 下，' +
      '结论与实测明细见 docs/Huff线性回归完善方案.md、docs/口径区间-价格弹性未标定.md 等文档。' +
      '这一页与聊天里 RAG 检索的知识库是<b>同一套依据的两种呈现</b>。');

  function flowSVG(steps) {
    var W = 620, bw = 108, bh = 44, gap = 16, x0 = 6, y = 12;
    var svg = '<svg width="100%" viewBox="0 0 ' + W + ' ' + (y + bh + 8) + '" role="img" aria-label="流程图" style="max-width:620px">';
    var x = x0;
    for (var i = 0; i < steps.length; i++) {
      svg += '<rect x="' + x + '" y="' + y + '" width="' + bw + '" height="' + bh + '" rx="8" style="fill:var(--zl-card-bg);stroke:var(--zl-ring);stroke-width:1.2"/>' +
        '<text x="' + (x + bw / 2) + '" y="' + (y + bh / 2 + 5) + '" font-size="12.5" text-anchor="middle" style="fill:var(--zl-wb-tx)">' + esc(steps[i]) + '</text>';
      if (i < steps.length - 1) {
        var xa = x + bw, ya = y + bh / 2;
        var xb2 = x + bw + gap + 8;
        svg += '<path d="M' + xa + ' ' + ya + ' H' + (xb2 - 4) + '" style="stroke:var(--zl-ring)" stroke-width="1.5" fill="none" marker-end="url(#zarr)"/>';
      }
      x += bw + gap;
    }
    svg += '<defs><marker id="zarr" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8 z" style="fill:var(--zl-ring)"/></marker></defs></svg>';
    return svg;
  }

  function KBLink(label, url) {
    return '<a class="zl-kb-link" href="' + url + '" target="_blank" rel="noopener">' + esc(label) + '</a>';
  }
  var KB_BUSINESS =
    '<div class="zl-kb-sec">商圈 / 零售选址经典理论</div>' +
    '<div class="zl-kb-cards">' +
    '<div class="zl-kb-card"><b>中心地理论（克里斯泰勒）</b>城市中不同等级中心地按六边形嵌套分布，高档商品向高级中心集聚。<br>' +
    KBLink('视频讲解（B站）', 'https://search.bilibili.com/all?keyword=' + encodeURIComponent('中心地理论 克里斯泰勒 讲解')) +
    KBLink('百科', 'https://baike.baidu.com/item/' + encodeURIComponent('中心地理论')) +
    KBLink('论文', 'https://xueshu.baidu.com/s?wd=' + encodeURIComponent('中心地理论 克里斯泰勒')) + '</div>' +
    '<div class="zl-kb-card"><b>廖什市场区位论</b>以需求圆锥/正六边形市场区解释生产区位，市场区随价格与运费变化。<br>' +
    KBLink('视频讲解（B站）', 'https://search.bilibili.com/all?keyword=' + encodeURIComponent('廖什市场区位论 讲解')) +
    KBLink('百科', 'https://baike.baidu.com/item/' + encodeURIComponent('廖什市场区位论')) +
    KBLink('论文', 'https://xueshu.baidu.com/s?wd=' + encodeURIComponent('廖什市场区位论')) + '</div>' +
    '<div class="zl-kb-card"><b>雷利零售引力法则</b>两商圈对中间消费者的吸引力与其规模成正比、与距离平方成反比。<br>' +
    KBLink('视频讲解（B站）', 'https://search.bilibili.com/all?keyword=' + encodeURIComponent('雷利零售引力法则 讲解')) +
    KBLink('百科', 'https://baike.baidu.com/item/' + encodeURIComponent('雷利零售引力法则')) +
    KBLink('论文', 'https://xueshu.baidu.com/s?wd=' + encodeURIComponent('雷利零售引力法则')) + '</div>' +
    '<div class="zl-kb-card"><b>赫夫概率模型（Huff）</b>顾客选择某商圈的概率 = 该商圈吸引力 / 所有商圈吸引力之和，是现代商圈客流预测基础。<br>' +
    KBLink('视频讲解（B站）', 'https://search.bilibili.com/all?keyword=' + encodeURIComponent('赫夫模型 Huff 商圈 讲解')) +
    KBLink('百科', 'https://baike.baidu.com/item/' + encodeURIComponent('赫夫模型')) +
    KBLink('论文', 'https://xueshu.baidu.com/s?wd=' + encodeURIComponent('Huff model 赫夫 商圈')) + '</div>' +
    '<div class="zl-kb-card"><b>康帕斯商圈断裂点模型</b>两商业中心之间客流的均衡点位置，用于划定商圈边界。<br>' +
    KBLink('视频讲解（B站）', 'https://search.bilibili.com/all?keyword=' + encodeURIComponent('康帕斯 商圈断裂点 讲解')) +
    KBLink('百科', 'https://baike.baidu.com/item/' + encodeURIComponent('商圈饱和指数')) +
    KBLink('论文', 'https://xueshu.baidu.com/s?wd=' + encodeURIComponent('康帕斯 断裂点 模型')) + '</div>' +
    '</div>' +
    '<div class="zl-kb-sec">出行 / 零售业态理论</div>' +
    '<div class="zl-kb-cards">' +
    '<div class="zl-kb-card"><b>出行路径理论（路径依赖）</b>消费者通勤/出行路线高度固定，选址本质是「抢动线」——早餐、咖啡等业态尤其依赖。<br>' +
    KBLink('视频讲解（B站）', 'https://search.bilibili.com/all?keyword=' + encodeURIComponent('路径依赖 理论 讲解')) +
    KBLink('百科', 'https://baike.baidu.com/item/' + encodeURIComponent('路径依赖')) +
    KBLink('论文', 'https://xueshu.baidu.com/s?wd=' + encodeURIComponent('路径依赖 理论')) + '</div>' +
    '<div class="zl-kb-card"><b>人货场理论</b>零售三要素「人、货、场」重构——以人为中心匹配货与场，是新零售选址与体验设计的底层框架。<br>' +
    KBLink('视频讲解（B站）', 'https://search.bilibili.com/all?keyword=' + encodeURIComponent('人货场 新零售 讲解')) +
    KBLink('百科', 'https://baike.baidu.com/item/' + encodeURIComponent('人货场')) +
    KBLink('论文', 'https://xueshu.baidu.com/s?wd=' + encodeURIComponent('人货场 零售 理论')) + '</div>' +
    '<div class="zl-kb-card"><b>零售轮理论（零售之轮）</b>零售业态以「低成本-低价」进入，逐步升级服务/环境、抬高价格，再被新业态取代，循环往复。<br>' +
    KBLink('视频讲解（B站）', 'https://search.bilibili.com/all?keyword=' + encodeURIComponent('零售轮理论 零售之轮 讲解')) +
    KBLink('百科', 'https://baike.baidu.com/item/' + encodeURIComponent('零售之轮')) +
    KBLink('论文', 'https://xueshu.baidu.com/s?wd=' + encodeURIComponent('零售轮 理论 业态')) + '</div>' +
    '</div>' +
    '<div class="zl-kb-sec">实战选址成功案例</div>' +
    '<div class="zl-kb-cards">' +
    '<div class="zl-kb-card"><b>星巴克选址策略</b>经典案例：门店密度 + 商圈分级（核心/非核心商圈），先锚定高势能点位再加密，擅长「傍大牌」与写字楼/机场布局。<br>' +
    KBLink('视频（B站）', 'https://search.bilibili.com/all?keyword=' + encodeURIComponent('星巴克 选址 策略 案例分析')) +
    KBLink('文章（知乎）', 'https://www.zhihu.com/search?type=content&q=' + encodeURIComponent('星巴克 选址 策略')) +
    KBLink('百科', 'https://baike.baidu.com/item/' + encodeURIComponent('星巴克')) + '</div>' +
    '<div class="zl-kb-card"><b>麦当劳/肯德基选址模型</b>成功案例：用「商圈等级 + 人流测算 + 竞品跟随」三重标准选点，设有专业选址团队做 A/B/C 级商圈评分。<br>' +
    KBLink('视频（B站）', 'https://search.bilibili.com/all?keyword=' + encodeURIComponent('麦当劳 肯德基 选址 方法 人流')) +
    KBLink('文章（知乎）', 'https://www.zhihu.com/search?type=content&q=' + encodeURIComponent('麦当劳 选址 模型')) +
    KBLink('百科', 'https://baike.baidu.com/item/' + encodeURIComponent('麦当劳')) + '</div>' +
    '<div class="zl-kb-card"><b>蜜雪冰城下沉选址</b>成功案例：专注三四线 + 校园/商圈边缘高人流点位，单店模型轻、密集开店快速建立品牌势能。<br>' +
    KBLink('视频（B站）', 'https://search.bilibili.com/all?keyword=' + encodeURIComponent('蜜雪冰城 选址 下沉市场 开店')) +
    KBLink('文章（知乎）', 'https://www.zhihu.com/search?type=content&q=' + encodeURIComponent('蜜雪冰城 选址')) +
    KBLink('百科', 'https://baike.baidu.com/item/' + encodeURIComponent('蜜雪冰城')) + '</div>' +
    '<div class="zl-kb-card"><b>7-11 / 便利店高密度选址</b>案例：商圈内「插花式」高密度布点形成规模效应，靠商圈数据 + 动线判断单店辐射范围。<br>' +
    KBLink('视频（B站）', 'https://search.bilibili.com/all?keyword=' + encodeURIComponent('7-11 便利店 选址 高密度')) +
    KBLink('文章（知乎）', 'https://www.zhihu.com/search?type=content&q=' + encodeURIComponent('便利店 选址 技巧')) +
    KBLink('百科', 'https://baike.baidu.com/item/' + encodeURIComponent('7-Eleven')) + '</div>' +
    '<div class="zl-kb-card"><b>喜茶 / 新茶饮选址</b>案例：看「商圈能级 + 年轻人流量」，头部茶饮早期深耕一线核心商圈旗舰店树立品牌再下沉。<br>' +
    KBLink('视频（B站）', 'https://search.bilibili.com/all?keyword=' + encodeURIComponent('喜茶 茶饮 选址 商圈')) +
    KBLink('文章（知乎）', 'https://www.zhihu.com/search?type=content&q=' + encodeURIComponent('奶茶店 选址 成功 案例')) +
    KBLink('百科', 'https://baike.baidu.com/item/' + encodeURIComponent('喜茶')) + '</div>' +
    '<div class="zl-kb-card"><b>海底捞 / 餐饮聚客选址</b>案例：选商场动线首层与聚客点，强调「排队势能」与周边业态互补。<br>' +
    KBLink('视频（B站）', 'https://search.bilibili.com/all?keyword=' + encodeURIComponent('海底捞 餐饮 选址 商场')) +
    KBLink('文章（知乎）', 'https://www.zhihu.com/search?type=content&q=' + encodeURIComponent('餐饮店 选址 成功 案例')) +
    KBLink('百科', 'https://baike.baidu.com/item/' + encodeURIComponent('海底捞')) + '</div>' +
    '</div>' +
    '<div class="zl-kb-note" style="color:var(--zl-sub);font-size:13px;margin-top:14px">链接为 B 站 / 知乎 / 百度百科检索页，点击后在新标签页打开；视频建议按关键词直接搜索案例讲解。</div>';

  /* ---- 10i. 四类店铺背景水印（更精致；双主题配色；按品类高亮） ---- */
  var SHOP_SVG = {
    milk: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><g fill="{c}" fill-opacity="{o}">' +
      '<path d="M14 27h36l-3 26a9 9 0 0 1-9 8H26a9 9 0 0 1-9-8z"/><path d="M29 9h6v18h-6z"/>' +
      '<path d="M35 7h10a7 7 0 0 1 0 14h-6"/><path d="M35 21v3h5"/><path d="M32 20l3 5-3 5-3-5z"/>' +
      '<rect x="18" y="35" width="7" height="13" rx="3"/><rect x="39" y="35" width="7" height="13" rx="3"/>' +
      '<circle cx="32" cy="48" r="2.4"/><circle cx="26" cy="50" r="1.8"/><circle cx="38" cy="50" r="1.8"/>' +
      '<path d="M24 31c-2-3 0-6 3-7M40 31c2-3 0-6-3-7" stroke="{c}" stroke-width="1.6" fill="none"/>' +
      '</g></svg>',
    store: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><g fill="{c}" fill-opacity="{o}">' +
      '<path d="M6 15l7-10h38l7 10z"/><rect x="6" y="15" width="52" height="47" rx="4"/>' +
      '<rect x="8" y="20" width="22" height="17" rx="2"/><rect x="34" y="20" width="22" height="17" rx="2"/>' +
      '<path d="M17 62V42a6 6 0 0 1 6-6h2a6 6 0 0 1 6 6v20"/><rect x="17" y="44" width="9" height="18" rx="2"/>' +
      '<rect x="42" y="42" width="10" height="20" rx="2"/><rect x="45" y="34" width="4" height="6" rx="1.5"/>' +
      '<rect x="10" y="18" width="6" height="5" rx="1"/>' +
      '</g></svg>',
    bfast: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><g fill="{c}" fill-opacity="{o}">' +
      '<path d="M6 30c0-12 11-22 26-22s26 10 26 22v5H6z"/><path d="M8 37c3 10 8 15 24 15s21-5 24-15H8z"/>' +
      '<circle cx="20" cy="34" r="4.5"/><circle cx="44" cy="34" r="4.5"/><rect x="27" y="30" width="10" height="9" rx="3"/>' +
      '<path d="M32 10c-3-4-7-4-9-2M32 10c3-4 7-4 9-2" stroke="{c}" stroke-width="1.6" fill="none"/>' +
      '<path d="M14 52h6M24 52h6M34 52h6" stroke="{c}" stroke-width="1.8"/>' +
      '</g></svg>',
    cake: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><g fill="{c}" fill-opacity="{o}">' +
      '<rect x="6" y="42" width="52" height="14" rx="4"/><rect x="12" y="31" width="40" height="13" rx="4"/>' +
      '<rect x="20" y="22" width="24" height="11" rx="4"/>' +
      '<path d="M6 42c0-5 4-7 7-7l11 7-9 14H6z"/><path d="M58 42c0-5-4-7-7-7l-11 7 9 14h9z"/>' +
      '<path d="M29 22v-7M35 22v-7" stroke="{c}" stroke-width="2"/><circle cx="29" cy="13" r="2.6"/><circle cx="35" cy="13" r="2.6"/>' +
      '<circle cx="48" cy="37" r="2.6"/><circle cx="16" cy="37" r="2.2"/>' +
      '</g></svg>'
  };
  function wmColor() {
    // 返回纯 rgb 分量（不含 alpha）：透明度改为「预混合」进不透明色，避免 Chromium 忽略 SVG data-URI 里的 rgba 透明度
    var c = document.documentElement.classList.contains('dark') ? '#e0c084' : '#0e353a';
    var n = parseInt(c.slice(1), 16);
    return ((n >> 16) & 255) + ',' + ((n >> 8) & 255) + ',' + (n & 255);
  }
  function chatBg() {
    // 读取聊天列当前底色，作为花纹「预混合」的背景基准
    try {
      var col = document.querySelector('.zl-chatcol');
      var m = col ? /rgba?\((\d+),\s*(\d+),\s*(\d+)/.exec(getComputedStyle(col).backgroundColor || '') : null;
      if (m) return m[1] + ',' + m[2] + ',' + m[3];
    } catch (e) {}
    return document.documentElement.classList.contains('dark') ? '11,29,34' : '253,251,238';
  }
  function blend(rgb, a, bg) {
    var p = rgb.split(','), q = bg.split(',');
    return 'rgb(' + Math.round(a * +p[0] + (1 - a) * +q[0]) + ',' +
      Math.round(a * +p[1] + (1 - a) * +q[1]) + ',' +
      Math.round(a * +p[2] + (1 - a) * +q[2]) + ')';
  }
  function shopUri(name, op) {
    // {c} 全部替换为「与底色预混合后的不透明色」，{o} 置 1：透明度必定生效且精确可控
    // 图标缩小到图块的 50% 居中留白，形状独立清晰可辨（不再密成条纹）
    // 用 base64 编码（而非 URL 编码）：Chromium 对 URL 编码的 SVG data URI 中特殊字符(括号/引号)解析不可靠，会导致整图加载失败/变形
    var svg = SHOP_SVG[name].replace(/\{c\}/g, blend(wmColor(), op, chatBg())).replace('{o}', '1');
    svg = svg.replace('<g fill=', '<g transform="translate(32 32) scale(0.5) translate(-32 -32)"><g fill=').replace('</g></svg>', '</g></g></svg>');
    var b64 = btoa(svg);
    return 'url("data:image/svg+xml;base64,' + b64 + '")';
  }
  /* 背景：4 条深色竖线（匹配 UI 主题色，稍粗）。
     根因（Chromium 渲染怪癖，本会话实测）：
     1) 列自身的背景层被压到 ~5%（不可见）；
     2) 外层列(relative)不能有 z-index（否则建立堆叠上下文，把整个子树压平）；
     3) z-index:1000 可满强度，但会盖住输入框/PDF 等内容 —— 用户要求柱子必须位于所有元素最底层，
        故使用 z-index:-1（绝对最底），代价是强度被压到 ~5%（很淡但绝不遮挡任何内容）。 */
  /* 址南针罗盘水印（2026-09-18 策定：聊天背景要贴合整页、有艺术、扣"址南针"）。
     与标题两侧的定位针（pinURI）同一套线描语言：细描边 + 中心实心点，
     不做实心填充（小透明度下实心会糊成一坨，实机验过）。
     ⚠️ data-URI 内读不到 CSS 变量 → 颜色以参数传入，亮暗各生成一份。 */
  function compassURI(rgb, a) {
    var c = 'rgba(' + rgb + ',' + a + ')';
    var ticks = '';
    for (var i = 0; i < 24; i++) {                 // 24 根刻度（每 15°），主方位加粗
      var ang = i * 15 * Math.PI / 180;
      var major = (i % 6 === 0);
      var r1 = major ? 82 : 87, r2 = 91;
      ticks += "<line x1='" + (100 + r1 * Math.sin(ang)).toFixed(1) +
        "' y1='" + (100 - r1 * Math.cos(ang)).toFixed(1) +
        "' x2='" + (100 + r2 * Math.sin(ang)).toFixed(1) +
        "' y2='" + (100 - r2 * Math.cos(ang)).toFixed(1) +
        "' stroke='" + c + "' stroke-width='" + (major ? 1.8 : 0.8) + "'/>";
    }
    return 'url("data:image/svg+xml,' + encodeURIComponent(
      "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 200 200' fill='none'>" +
      "<circle cx='100' cy='100' r='92' stroke='" + c + "' stroke-width='1.1'/>" +
      "<circle cx='100' cy='100' r='78' stroke='" + c + "' stroke-width='0.6'/>" +
      ticks +
      "<path d='M100 32 L108.5 91.5 L168 100 L108.5 108.5 L100 168 L91.5 108.5 L32 100 L91.5 91.5 Z' " +
      "stroke='" + c + "' stroke-width='1.5' stroke-linejoin='round'/>" +
      "<circle cx='100' cy='100' r='5' fill='" + c + "'/>" +
      "</svg>") + '")';
  }
  function wmLinesCss(rgb, a) {
    // 4 根粗立柱（各占宽 10%，合计 40% 藏青），米色空隙 5 段各 12%（合计 60%）→ 6:4
    return 'linear-gradient(rgba(' + rgb + ',' + a + '),rgba(' + rgb + ',' + a + ')) 13.3% 0 / 10% 100% no-repeat,' +
      'linear-gradient(rgba(' + rgb + ',' + a + '),rgba(' + rgb + ',' + a + ')) 37.8% 0 / 10% 100% no-repeat,' +
      'linear-gradient(rgba(' + rgb + ',' + a + '),rgba(' + rgb + ',' + a + ')) 62.2% 0 / 10% 100% no-repeat,' +
      'linear-gradient(rgba(' + rgb + ',' + a + '),rgba(' + rgb + ',' + a + ')) 86.7% 0 / 10% 100% no-repeat';
  }
  function wmStyle() {
    var cats = { '奶茶': 'milk', '甜品': 'cake', '早餐': 'bfast', '便利店': 'store' };
    var dark = document.documentElement.classList.contains('dark');
    var baseRgb = dark ? '224,192,132' : '14,53,58';   // 亮色=淡藏青；暗色=金（匹配主题）
    var baseA = dark ? 0.26 : 0.15;                     // 立柱名义值——透过 wash 后实见 ~7-12%
    var hiRgb = dark ? '224,192,132' : '180,140,70';   // 选中：亮色变金色，暗色加亮
    var hiA = dark ? 0.34 : 0.20;
    var compA = dark ? 0.24 : 0.13;                    // 罗盘名义值——实见隐约可辨（6%~11%），
                                                       // 太淡就只剩"贴合"丢了"艺术"（2026-09-18 实机截图定档）
    var SEL = 'div.flex.flex-col.flex-grow.overflow-y-auto.zl-chatcol';
    var comp = compassURI(baseRgb, compA);
    var css =
      /* ① 列底：不再是"一块实心淡色方块"。两侧融进页底色（边界消失、与整页贴合），
         中段留一抹淡洗色区分消息区与两侧栏。--zl-chat 不能动（#zl-page-ov 在用），
         故新开 --zl-chat-wash：比 --zl-chat 透得多，让下面 ::before 的罗盘透得出来。
         ⚠️ 罗盘铺在**最顶层 background**：放 ::before（z-index:-1）会被 wash 压到只剩
         ~45% 强度（实机截图看不见），挪上来后强度就是 compA 本身。
         ⚠️ 罗盘垂直位置 = 50%（2026-09-18 策要求：图案整幅落在对话框正中，
         不许探进顶部置顶头那一框——`.relative` 是外层定高可视列，50% 即屏幕正中）。 */
      SEL + '.relative{background:' +
      comp + ' center 50% / 480px 480px no-repeat,' +
      'linear-gradient(90deg,var(--zl-page) 0%,rgba(0,0,0,0) 76px,rgba(0,0,0,0) calc(100% - 76px),var(--zl-page) 100%),' +
      'var(--zl-chat-wash) !important;}\n' +
      SEL + ':not(.relative){position:relative;z-index:0;background:transparent !important;}\n' +
      /* ② 立柱水印层（z-index:-1 绝对最底、不挡任何内容）：品类联动换色，克制在
         背景深处。罗盘在上层（①）保持主题色不动——品牌视觉不跟品类换。 */
      SEL + '.relative::before{content:"";position:absolute;left:0;top:0;right:0;bottom:0;pointer-events:none;z-index:-1;' +
      'background:' + wmLinesCss(baseRgb, baseA) + ';}\n';
    Object.keys(cats).forEach(function (k) {
      css += 'body[data-zcat="' + k + '"] ' + SEL + '.relative::before{background:' +
        wmLinesCss(hiRgb, hiA) + ';}\n';
    });
    var st = document.getElementById('zl-wm-style');
    if (!st) { st = document.createElement('style'); st.id = 'zl-wm-style'; document.head.appendChild(st); }
    st.textContent = css;
  }
  function ensureChatCol() {
    // 聊天区有两层 .flex.flex-col.flex-grow.overflow-y-auto：外层定位容器 + 内层真实滚动区。
    // 必须给「所有」匹配列都加 zl-chatcol，否则内层纯色背景会盖住外层花纹。
    var cols = document.querySelectorAll('.flex.flex-col.flex-grow.overflow-y-auto');
    for (var i = 0; i < cols.length; i++) if (!cols[i].classList.contains('zl-chatcol')) cols[i].classList.add('zl-chatcol');
  }
  function applyWatermark(cat) {
    if (cat) document.body.setAttribute('data-zcat', cat);
    else document.body.removeAttribute('data-zcat');
    wmStyle();
  }

  /* ---- 11. 轮询刷新 + 冲刷排队命令 + 进度态 ---- */
  function load() {
    armA11y();
    hideHeaderButtons();
    ensureGear();
    // ⚠️ 顺序有意义：先建专家条，再让「自由对话 / 模型」直接落进它的右侧插槽。
    //    反过来会先挂到输入框那一行、下一轮再被搬走 —— 界面会闪一下换位置。
    ensureExpertBar();       // 输入框上方的专家选择条（依赖 composer 已渲染）
    ensureModelSelect();
    ensureFreeChatBtn();
    ensureDisclaimer();
    ensureChatCol();
    ensureVeyra();
    hideCmdBubbles();
    collapseProcessStep();
    layoutBar();
    raisePdfModal();   // 需求 3：每轮也校一次弹层层级（兜底）
    if (pendingCmd && !isProcessing()) {
      var c = pendingCmd;
      pendingCmd = null;
      sendCmd(c);
      return;
    }
    var busy = isProcessing();
    if (busy !== prevBusy) { prevBusy = busy; setBusy(busy); }
    fetch('/public/sidebar.json', { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error('no sidebar'); return r.json(); })
      .then(function (d) {
        renderHist(d);
        syncModelSelect(d.model);
        syncFreeChat(d.free_chat);
        syncExperts(d.experts, d.current_expert);   // 专家清单 + 当前专家（服务端为准）
        syncSimList(d.sim_list);                    // 大屏「挑哪一次」的分析列表
        shiftContent();
      })
      .catch(function () { shiftContent(); });
    fetch('/public/dashboard.json', { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error('no dashboard'); return r.json(); })
      .then(function (d) {
        shiftContent();
        if (d && d.ts !== lastDashTs) { lastDashTs = d.ts; renderDashboard(d); }
      })
      .catch(function () { shiftContent(); });
    /* 仿真看板快照：与 dashboard.json **分开拉**，所以它不被 kind=clear 影响。
       404（还没跑过分析）是正常的，不是错误 —— 静默 catch，只把按钮保持 disabled。 */
    fetch('/public/last_sim.json', { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error('no last_sim'); return r.json(); })
      .then(function (d) {
        var ts = d && d['取证时间'];
        if (ts !== lastSimTs) { lastSimTs = ts; syncSimBoard(d); }
      })
      .catch(function () {
        // ⚠️ 404（还没跑过分析）是**正常态**，不是错误。
        //    但首次就是 404 时 lastSimTs 本来就是 null，所以**不能**用
        //    `if (lastSimTs !== null)` 当门槛 —— 那样按钮永远拿不到
        //    真正的 disabled **属性**（只有 class，点了会走兜底提示而不是被禁掉）。
        if (lastSimTs !== null || lastSimData !== null) { lastSimTs = null; }
        syncSimBoard(null);
      });
    /* §2（2026-09-17）：`/public/conv_page.json` 的轮询已删除。
       它是"历史会话独立只读页"的数据源（后端 `process_preview_conv` 写入，
       前端每 2.5s 拉一次再覆盖层渲染）。§2 把历史项改成一步到位 + 回放后，
       这个文件不再有人写、覆盖层也不再有人开 —— 留着就是每 2.5s 一次必定 404
       的无用请求（§4 的"无条件 fetch"清单里正好也点了这条）。 */
  }
  wmStyle();
  initTheme();
  initFont();
  load();
  // 轮询：标签页隐藏时暂停（性能预算护栏，B 发现④）；回到前台立即恢复一次
  var _pollTimer = setInterval(function () {
    if (document.visibilityState === 'visible') load();
  }, 2500);
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible') load();
  });
  window.addEventListener('resize', layout);
  // 即时隐藏控制指令气泡（不等 2.5s 轮询）
  try {
    var _cmdObs = new MutationObserver(function () { hideCmdBubbles(); });
    _cmdObs.observe(document.body, { childList: true, subtree: true, characterData: true });
  } catch (e) {}

  /* ---- 需求 3：把 Chainlit 的 PDF / 图片弹层抬到最上层 ----
     为什么还需要 JS（上面已有两条 CSS）：Chainlit 是 minified 的第三方 bundle，
     弹层的 z 值是 Tailwind 任意值类（形如 .z-\[60\]，选择器要转义、且随版本变），
     纯 CSS 命中不稳定。这里在 DOM 变动时直接扫 [role="dialog"]，把它所在 portal
     子树里所有定位元素内联 !important 提到 3000，并对 body 打 zl-pdf-open
     （layoutBar 据此让专家条让位）。只监听 body 的**直接子节点**变动
     （Radix portal 是直接挂在 body 下的），避免流式输出时被高频触发。 */
  function raisePdfModal() {
    var list = document.querySelectorAll('[role="dialog"]');
    var dlg = null;
    for (var i = 0; i < list.length; i++) {
      var c0 = null;
      try { c0 = getComputedStyle(list[i]); } catch (e) { c0 = null; }
      if (c0 && c0.display !== 'none' && c0.visibility !== 'hidden') { dlg = list[i]; break; }
    }
    var open = !!dlg;
    if (open !== document.body.classList.contains('zl-pdf-open')) {
      document.body.classList.toggle('zl-pdf-open', open);
      layoutBar();
    }
    if (!dlg) return;
    var root = dlg;
    while (root.parentElement && root.parentElement !== document.body) root = root.parentElement;
    var nodes = Array.prototype.slice.call(root.querySelectorAll('*'));
    nodes.push(root);
    for (var j = 0; j < nodes.length; j++) {
      var n = nodes[j];
      try {
        var c2 = getComputedStyle(n);
        if ((c2.position === 'fixed' || c2.position === 'absolute') &&
            parseInt(c2.zIndex || '0', 10) < 3000) {
          n.style.setProperty('z-index', '3000', 'important');
        }
      } catch (e) {}
    }
  }
  var _pdfPending = false;
  function schedulePdfRaise() {
    if (_pdfPending) return;
    _pdfPending = true;
    var run = function () { _pdfPending = false; raisePdfModal(); };
    if (window.requestAnimationFrame) window.requestAnimationFrame(run);
    else setTimeout(run, 30);
  }
  try {
    var _pdfObs = new MutationObserver(schedulePdfRaise);
    _pdfObs.observe(document.body, { childList: true });   // 只看直接子节点：portal 挂载点
  } catch (e) {}
  // 兜底：每次轮询也校一次（万一 portal 复用了旧节点、没触发 childList）
  raisePdfModal();
})();
