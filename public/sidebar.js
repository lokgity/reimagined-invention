/* ============================================================
   浙里选址 · 三栏工作台（custom_js）v3
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
  var FONT = '"Noto Sans SC","Microsoft YaHei","PingFang SC","Source Han Sans SC",sans-serif';

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
    book: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>'
  };
  function xIco(size) {
    var s = size || 16;
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" width="' + s + '" height="' + s + '" aria-hidden="true"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>';
  }
  function ico(name, cls) {
    return '<svg class="ic' + (cls ? ' ' + cls : '') + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="19" height="19" aria-hidden="true">' + (ICONS[name] || ICONS.gauge) + '</svg>';
  }

  /* ---- 1. 样式（双主题 CSS 变量：暗为默认，亮用 html:not(.dark) 覆盖） ---- */
  var style = document.createElement('style');
  style.textContent = [
    /* 主题变量 —— 暗（默认）：深墨青底 + 藏青/金，品牌体系 */
    ':root{',
    '--zl-page:#0b1d22;--zl-chat:rgba(11,29,34,.97);',
    '--zl-rail-grad:linear-gradient(180deg,#132e34 0%,#0d242a 55%,#17383f 100%);',
    '--zl-rail-bord:rgba(229,201,138,.18);',
    '--zl-title-grad:linear-gradient(90deg,#f0d9a6,#c9a45c);--zl-title-ic:#e5c98a;',
    '--zl-sub:#9db3b6;--zl-sec:#9db3b6;',
    '--zl-btn-bg:rgba(255,255,255,.06);--zl-btn-tx:#e9f0ee;--zl-btn-ic:#9db3b6;',
    '--zl-btn-hov:rgba(229,201,138,.15);--zl-btn-hov-ic:#f0d9a6;--zl-btn-bord-hov:rgba(229,201,138,.5);',
    '--zl-hist-hov:rgba(255,255,255,.08);',
    '--zl-tag-ok:#7ee0b8;--zl-tag-okbg:rgba(52,199,123,.18);',
    '--zl-tag-chat:#9fd0d6;--zl-tag-chatbg:rgba(61,130,140,.2);',
    '--zl-del-hov:#f87171;--zl-del-hovbg:rgba(239,68,68,.22);',
    '--zl-empty:#9db3b6;--zl-foot:#9db3b6;--zl-footbg:rgba(0,0,0,.22);',
    '--zl-badge:#e5c98a;--zl-badgebg:rgba(201,164,92,.16);--zl-ring:#e0c084;--zl-ring-soft:rgba(229,201,138,.25);',
    '--zl-wb-grad:linear-gradient(180deg,#132e34 0%,#0d242a 100%);--zl-wb-tx:#e9f0ee;--zl-wb-head-tx:#f4f2e6;',
    '--zl-card-bg:rgba(255,255,255,.05);--zl-card-bord:rgba(229,201,138,.15);--zl-card-lab:#9db3b6;--zl-card-val:#f2efe0;',
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
    '--zl-page:#fbf5e3;--zl-chat:rgba(253,250,240,.94);',
    '--zl-rail-grad:linear-gradient(180deg,rgba(250,245,222,.97) 0%,rgba(246,238,210,.97) 55%,rgba(252,248,230,.97) 100%);',
    '--zl-rail-bord:rgba(14,53,58,.18);',
    '--zl-title-grad:linear-gradient(90deg,#0e353a,#2a4a4d);--zl-title-ic:#0e353a;',
    '--zl-sub:#5d6f69;--zl-sec:#5d6f69;',
    '--zl-btn-bg:rgba(14,53,58,.07);--zl-btn-tx:#18383e;--zl-btn-ic:#48635f;',
    '--zl-btn-hov:rgba(14,53,58,.13);--zl-btn-hov-ic:#0e353a;--zl-btn-bord-hov:rgba(14,53,58,.45);',
    '--zl-hist-hov:rgba(14,53,58,.08);',
    '--zl-tag-ok:#0d6b57;--zl-tag-okbg:#d7efe6;',
    '--zl-tag-chat:#1d5c66;--zl-tag-chatbg:#dcebed;',
    '--zl-del-hov:#c2410c;--zl-del-hovbg:#fde8d7;',
    '--zl-empty:#5d6f69;--zl-foot:#5d6f69;--zl-footbg:rgba(14,53,58,.06);',
    '--zl-badge:#0e353a;--zl-badgebg:#e7ece3;--zl-ring:#0e353a;--zl-ring-soft:rgba(14,53,58,.2);',
    '--zl-wb-grad:linear-gradient(180deg,rgba(250,245,222,.97) 0%,rgba(245,237,208,.97) 100%);--zl-wb-tx:#18383e;--zl-wb-head-tx:#0e353a;',
    '--zl-card-bg:rgba(255,255,255,.82);--zl-card-bord:rgba(14,53,58,.16);--zl-card-lab:#5d6f69;--zl-card-val:#0e353a;',
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
    '#zl-right .cand-grid{display:block;gap:8px;}',
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
    '#zl-right .cand-warn{font-size:12px;color:#fda4a4;margin-top:2px;}',
    '#zl-right .cand-go{flex:none;color:var(--zl-score);font-size:18px;font-weight:800;}',
    'html:not(.dark) #zl-right .cand-card{background:#fff;border-color:#eee8d5;color:#2c3e3b;}',
    'html:not(.dark) #zl-right .cand-name{color:#2c3e3b;}',
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
    'background:linear-gradient(120deg,#f0d9a6 0%,#e0c084 45%,#b8964a 100%);',
    '-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;',
    'text-shadow:0 6px 30px rgba(224,192,132,.3);}',
    'html:not(.dark) [class*="message-content"] h1,html:not(.dark) [class*="Markdown"] h1,html:not(.dark) [class*="markdown"] h1',
    '{background:linear-gradient(120deg,#0e353a 0%,#3a5550 50%,#b8964a 100%);',
    '-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;',
    'text-shadow:0 6px 26px rgba(14,53,58,.22);}',
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
    /* Veyra 置顶头（中间栏顶部，滚动时悬浮） */
    '#zl-veya{position:sticky;top:0;z-index:20;display:flex;align-items:center;gap:14px;',
    'padding:14px 22px 10px;background:var(--zl-chat);backdrop-filter:blur(6px);}',
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
    '#zl-page-ov .zl-pg-cta{padding:9px 16px;border-radius:10px;border:none;cursor:pointer;font-size:14px;font-weight:700;color:var(--zl-accent-tx);',
    'background:var(--zl-accent-grad);}',
    '#zl-page-ov .zl-pg-body{flex:1;overflow-y:auto;padding:20px 26px;}',
    '#zl-page-ov .zl-pg-msg{display:flex;margin:12px 0;}',
    '#zl-page-ov .zl-pg-msg .who{flex:none;width:58px;font-size:12px;color:var(--zl-sub);padding-top:4px;text-align:right;margin-right:12px;}',
    '#zl-page-ov .zl-pg-msg .txt{flex:1;background:var(--zl-card-bg);border:1px solid var(--zl-card-bord);border-radius:12px;',
    'padding:10px 13px;font-size:14.5px;line-height:1.75;white-space:pre-wrap;word-break:break-word;color:var(--zl-wb-tx);}',
    '#zl-page-ov .zl-pg-msg.user .txt{background:rgba(14,53,58,.07);border-color:rgba(14,53,58,.22);}',
    '#zl-page-ov .zl-pg-sum{background:var(--zl-card-bg);border:1px solid var(--zl-card-bord);border-radius:12px;',
    'padding:12px 15px;font-size:14px;margin-bottom:16px;line-height:1.9;}',
    '#zl-page-ov .zl-kb-sec{font-size:15px;font-weight:800;color:var(--zl-badge);border-left:3px solid var(--zl-ring);padding-left:8px;margin:18px 0 8px;}',
    '#zl-page-ov .zl-kb-theory{margin:8px 0;background:var(--zl-card-bg);border:1px solid var(--zl-card-bord);border-radius:12px;',
    'padding:13px 15px;font-size:14px;line-height:1.85;}',
    '#zl-page-ov .zl-kb-theory a{color:var(--zl-ring);text-decoration:underline;}',
    /* 商业理论：多方块卡片排布（大小贴合文字，一行多个，不留大空白） */
    '#zl-page-ov .zl-kb-cards{display:flex;flex-wrap:wrap;gap:10px;}',
    '#zl-page-ov .zl-kb-card{flex:0 1 auto;width:auto;max-width:300px;min-width:176px;box-sizing:border-box;',
    'background:var(--zl-card-bg);border:1px solid var(--zl-card-bord);border-radius:12px;',
    'padding:11px 13px;font-size:13px;line-height:1.62;}',
    '#zl-page-ov .zl-kb-card b{display:block;margin-bottom:4px;color:var(--zl-card-val);font-size:13.5px;line-height:1.4;}',
    '#zl-page-ov .zl-kb-card a{color:var(--zl-ring);text-decoration:underline;display:inline-block;margin:5px 10px 0 0;}',
    '#zl-page-ov .zl-kb-link{display:inline-block;margin-right:14px;color:var(--zl-ring);}',
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
    '#zl-right .zr-btn-primary,#zl-right .zr-btn-ghost{font-size:calc(16px * var(--zl-fs));}',
    '[class*="message-content"],.step[data-step-type] [role="region"]{font-size:calc(15px * var(--zl-fs));}'
  ].join('');
  document.head.appendChild(style);

  /* ---- 2. 左栏 DOM（二级下拉分组） ---- */
  function chev() { return '<span class="zl-chev">' + ico('arrow') + '</span>'; }
  var rail = document.createElement('div');
  rail.id = 'zl-rail';
  rail.setAttribute('role', 'navigation');
  rail.setAttribute('aria-label', '操作栏');
  rail.innerHTML =
    '<div class="zl-head"><div class="zl-title">' + ico('pin') + ' 浙里选址</div>' +
    '<div class="zl-sub">AI 商铺选址助手</div></div>' +
    '<div class="zl-body">' +
    '  <div class="zl-group open" data-group="ops">' +
    '    <div class="zl-group-hd" role="button" tabindex="0" aria-expanded="true">' + ico('gauge') + '快速操作' + chev() + '</div>' +
    '    <div class="zl-group-bd">' +
    '      <button class="zl-btn primary" data-cmd="new">' + ico('plus') + ' 新建对话</button>' +
    '      <button class="zl-btn" data-cmd="export">' + ico('arrow') + ' 导出分析</button>' +
    '      <button class="zl-btn disabled" data-cmd="compare" id="zl-cmp">' + ico('compare') + ' 对比分析</button>' +
    '    </div>' +
    '  </div>' +
    '  <div class="zl-group" data-group="demo">' +
    '    <div class="zl-group-hd" role="button" tabindex="0" aria-expanded="false">' + ico('spark') + '快速演示' + chev() + '</div>' +
    '    <div class="zl-group-bd">' +
    '      <button class="zl-btn" data-cmd="demo_milktea">' + ico('coffee') + ' 奶茶·武林广场·8k</button>' +
    '      <button class="zl-btn" data-cmd="demo_cake">' + ico('cake') + ' 甜品·天一广场·1万5</button>' +
    '      <button class="zl-btn" data-cmd="demo_breakfast">' + ico('utensils') + ' 早餐·滨江·6k</button>' +
    '      <button class="zl-btn" data-cmd="demo_store">' + ico('bag') + ' 便利店·温州·1万</button>' +
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

  function sendCmd(txt) {
    if (isProcessing()) {
      pendingCmd = txt;
      showQueue('命令已排队，处理完成自动执行…');
      return;
    }
    if (isCtrlCmd(txt)) { hideTarget = normCmd(txt); hideTargetAt = Date.now(); }
    if (/^##预览:/.test(txt)) window.__zl_convReqAt = Date.now();   // 历史项预览：允许覆盖层立即渲染（即使跨刷新已展示过）
    var ta = document.querySelector('textarea');
    if (!ta) return;
    var setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
    setter.call(ta, txt);
    ta.dispatchEvent(new Event('input', { bubbles: true }));
    var send = findSendBtn();
    if (send && !send.disabled) send.click();
    else ta.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', bubbles: true }));
    setTimeout(hideCmdBubbles, 80);
    setTimeout(hideCmdBubbles, 400);
    setTimeout(hideCmdBubbles, 1500);
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
    // 直接 fetch sidebar.json 按 id 取该会话完整数据渲染覆盖层，
    // 不再注入 ##预览 指令 → 聊天区永不出现指令字样，且每次点击都可靠打开
    fetch('/public/sidebar.json', { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var hit = (d && d.hist) ? d.hist.filter(function (c) { return c.id === id; })[0] : null;
        if (hit) {
          renderHistPage({ id: hit.id, title: hit.title, ts: hit.ts,
                           messages: hit.messages || [], analysis: hit.analysis || null });
        } else {
          showQueue('该会话不存在或已被清理');
        }
      })
      .catch(function () { showQueue('预览加载失败，请重试'); });
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
    var gh = ev.target.closest('.zl-group-hd');
    if (gh) { toggleGroup(gh.parentElement); return; }
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
      var map = {
        new: '##新对话##',
        compare: '对比1和2',
        export: '##导出##',
        demo_milktea: '有，看中了杭州武林广场的铺子，开奶茶店，面积30平方，月租8000',
        demo_cake: '有，宁波天一广场附近有个铺子，开甜品店，面积25平，房租1万5',
        demo_breakfast: '有，杭州滨江区长河路看了一家，开早餐店，面积20平，月租6000',
        demo_store: '有，温州鹿城区人民路有个铺子，开便利店，面积40平，月租1万'
      };
      if (map[cmd]) sendCmd(map[cmd]);
    }
  });
  document.addEventListener('keydown', function (ev) {
    var gh = ev.target && ev.target.closest && ev.target.closest('.zl-group-hd');
    if (gh) {
      if (ev.key === 'Enter' || ev.key === ' ') {
        ev.preventDefault();
        toggleGroup(gh.parentElement);
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
               t.indexOf('##模型:') >= 0 || t.indexOf('##导出##') >= 0 || t.indexOf('##预览:') >= 0) &&
              n.closest && (n.closest('.step[data-step-type]') || n.classList.contains('step'))) {
            n.style.display = 'none';
          }
          // 出正文（最终内容）时自动折叠执行过程步骤
          if (t.indexOf('##') !== 0 && t.length > 0) {
            var cls = n.className ? String(n.className) : '';
            var dt = n.getAttribute ? (n.getAttribute('data-step-type') || '') : '';
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
    if (d.map_b64) {
      h += '<div class="zr-sec">周边热力图</div><div class="zr-map"><img src="' + d.map_b64 + '" alt="周边地图"/>' +
        '<div class="zr-legend">红点 = 本铺 · 红圈 = 竞品 · 蓝点 = 客群 POI · 蓝环 = 分析半径</div></div>';
    }
    if (d.warnings && d.warnings.length) {
      d.warnings.forEach(function (w) { h += '<div class="zr-warn">' + esc(w) + '</div>'; });
    }
    return h;
  }

  /* ---- 候选商铺卡片（可点击，点击即发"我选第N个"触发分析） ---- */
  function renderCandidates(d) {
    var cards = d.cards || [];
    var h = '';
    h += '<div class="zr-shop">' + esc(d.title || '候选商铺') + '</div>';
    if (d.hint) h += '<div class="zr-sub">' + esc(d.hint) + '</div>';
    h += '<div class="zr-cards cand-grid">';
    cards.forEach(function (c) {
      var info = [];
      if (c.area) info.push(esc(c.area) + '㎡');
      if (c.price != null) info.push(esc(c.price) + '元/月');
      var tag = c.in_rent ? '<span class="zl-tag ok">在租</span>' : '<span class="zl-tag chat">出租</span>';
      var pin = c.precise === false ? '<div class="cand-warn">⚠️ 区域级定位</div>' : '';
      h += '<button class="cand-card" data-choose="' + c.i + '" type="button" aria-label="选择第' + c.i + '家 ' + esc(c.name) + '">' +
        '<div class="cand-no">' + c.i + '</div>' +
        '<div class="cand-body">' +
        '  <div class="cand-name">' + esc(c.name) + ' ' + tag + '</div>' +
        '  <div class="cand-info">' + info.join(' · ') + '</div>' +
        '  <div class="cand-addr">' + esc(c.addr || '') + '</div>' + pin +
        '</div>' +
        '<div class="cand-go">→</div>' +
        '</button>';
    });
    h += '</div>';
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
        '<input id="' + fid + '" type="text" data-key="' + esc(f.key) + '" placeholder="' + esc(f.placeholder || '') + '" value="' + esc(f.default || '') + '" autocomplete="off"/></div>';
    });
    h += '<div class="zr-form-actions">' +
      '<button type="button" class="zr-btn-ghost" id="zr-form-close">关闭</button>' +
      '<button type="submit" class="zr-btn-primary">提交并继续</button>' +
      '</div></form>';
    return h;
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
      var txt = composeInput(currentInput || {}, vals);
      if (txt) { sendCmd(txt); }
      else showQueue('请至少填写一项内容');
    }
  });

  var lastDashTs = null;
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
      '<p><b>浙里选址</b> —— AI 商铺选址助手。</p>' +
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

  /* ---- 10e. 切换模型下拉（回形针在左、模型按钮在右，同一行） ---- */
  function ensureModelSelect() {
    if (document.getElementById('zl-model-sel')) return;
    var ta = document.querySelector('textarea');
    if (!ta) return;
    var lab = document.createElement('label');
    lab.className = 'zl-model';
    lab.innerHTML = '<select id="zl-model-sel" aria-label="切换模型" title="切换模型">' +
      '<option value="" disabled selected>模型…</option>' +
      '<option value="Doubao-Seed-2.1-turbo">Doubao-Seed-2.1</option>' +
      '<option value="DeepSeek-V4-Flash">DeepSeek-V4</option>' +
      '<option value="mimo-v2.5">mimo-v2.5</option></select>';
    // 插到发送按钮左侧（右端），与左端回形针同一行
    var send = findSendBtn();
    if (send && send.parentElement) send.insertAdjacentElement('beforebegin', lab);
    else {
      var wrap = ta.closest('form') || ta.parentElement;
      (wrap || document.body).appendChild(lab);
    }
    lab.querySelector('select').addEventListener('change', function () {
      if (this.value) sendCmd('##模型:' + this.value + '##');
    });
  }
  function syncModelSelect(model) {
    var sel = document.getElementById('zl-model-sel');
    if (!sel || !model) return;
    if (sel.getAttribute('data-cur') !== model) {
      sel.value = model;
      sel.setAttribute('data-cur', model);
    }
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

  /* ---- 10f2. Veyra 品牌 Logo（依用户设计图重建：C形弯月+城市路网+侦探剪影） ---- */
  var VEYA_SVG =
    '<svg viewBox="0 0 100 100" width="100%" height="100%" role="img" aria-label="Veyra 品牌 Logo" aria-hidden="true">' +
    '<defs><mask id="zvP"><rect x="0" y="0" width="100" height="100" fill="#fff"/>' +
    '<circle cx="62" cy="40" r="17" fill="#000"/></mask></defs>' +
    /* 米色圆底 */
    '<circle cx="50" cy="50" r="47" fill="#fdfbee"/>' +
    '<circle cx="50" cy="50" r="47" fill="none" stroke="#e4dcc2" stroke-width="1.4"/>' +
    /* C形弯月（藏青，开口朝右上） */
    '<circle cx="52" cy="54" r="27" fill="#0e353a" mask="url(#zvP)"/>' +
    /* 弯月实体上的金色街区路网 */
    '<path d="M26 42 L40 42 M26 54 L40 54 M26 66 L40 66" stroke="#c9a45c" stroke-width="1.1" fill="none" opacity=".9"/>' +
    '<path d="M28 48 L34 36 M32 60 L38 48 M38 72 L44 60" stroke="#c9a45c" stroke-width="1" fill="none" opacity=".7"/>' +
    /* 白色"街"字 */
    '<text x="36" y="39" font-size="11" fill="#fff" font-family="Noto Serif SC,STSong,SimSun,serif" font-weight="700">街</text>' +
    /* 顶部三个米白小点（月面光斑） */
    '<circle cx="38" cy="31" r="1.7" fill="#fdfbee"/><circle cx="42" cy="30" r="1.3" fill="#fdfbee"/><circle cx="45" cy="32" r="1.6" fill="#fdfbee"/>' +
    /* 白色脚印（追踪痕迹） */
    '<ellipse cx="34" cy="60" rx="2.3" ry="1.4" fill="#fff" opacity=".85"/>' +
    '<ellipse cx="38" cy="66" rx="2" ry="1.3" fill="#fff" opacity=".8"/>' +
    '<ellipse cx="42" cy="71" rx="1.8" ry="1.2" fill="#fff" opacity=".7"/>' +
    /* 弯月空心内的金色道路 + 地图定位标 */
    '<path d="M64 42 L74 50 M62 50 L72 58 M58 46 v11" stroke="#c9a45c" stroke-width="1.3" fill="none"/>' +
    '<path d="M70 54 c2.2 3.4 4.4 5 4.4 7.4 a2.6 2.6 0 1 1 -5.2 0 c0-2.4 2.2-4 4.4-7.4" fill="#c9a45c"/>' +
    '<circle cx="72.2" cy="61.4" r="1.1" fill="#fdfbee"/>' +
    /* 极小的眼睛图标（内弧左侧，侦探观察意象） */
    '<path d="M56 50 q2 -1.7 4 0 q-2 1.7 -4 0" stroke="#0e353a" stroke-width="1" fill="none"/>' +
    /* 侦探剪影（礼帽 + 长风衣，站于内弧最低点，脚下与弯月衔接） */
    '<path d="M55.5 49.5 h13 l-1.7 -3.4 h-9.6 z" fill="#0e353a"/>' +
    '<path d="M59.5 46.5 h4.6 v3.4 h-4.6 z" fill="#0e353a"/>' +
    '<circle cx="62" cy="45.6" r="1.9" fill="#0e353a"/>' +
    '<path d="M59.6 51 h4.8 l2 11 h-8.8 z" fill="#0e353a"/>' +
    '<path d="M60.4 62 l-.9 3 h2.1 M63.6 62 l.9 3 h-2.1" stroke="#0e353a" stroke-width="1.5" fill="none" stroke-linecap="round"/>' +
    '</svg>';
  function ensureVeyra() {
    if (document.getElementById('zl-veya')) return;
    var col = document.querySelector('.flex.flex-col.flex-grow.overflow-y-auto');
    if (!col) return;
    var hd = document.createElement('div');
    hd.id = 'zl-veya';
    hd.innerHTML =
      '<div class="zv-logo">' + VEYA_SVG + '</div>' +
      '<div><div class="zv-name">浙里选址</div><div class="zv-tag">你的 AI 商铺选址分析师</div></div>';
    col.insertBefore(hd, col.firstChild);
  }

  /* ---- 10f3. 隐藏控制指令气泡（## 指令 / 对比1和2，含 markdown 剥离后的形态）+ 出正文折叠步骤 ---- */
  var hideTarget = null, hideTargetAt = 0;   // 最近 sendCmd 发出的控制指令（标准化），精确隐藏对应气泡
  function normCmd(t) { return String(t || '').replace(/[#\s\u00a0]/g, ''); }
  function isCtrlCmd(t) { return /^##(新对话|打开|删除|模型|导出|预览)/.test(t) || t === '对比1和2'; }
  function hideCmdBubbles() {
    var col = document.querySelector('.flex.flex-col.flex-grow.overflow-y-auto');
    if (!col) return;
    var now = Date.now(), target = hideTarget;
    function isCmdText(t) {
      if (!t) return false;
      // 完整命令 / 以##开头 / 对比指令 / 候选选择指令 / 纯指令文本（剥离空白与#后）
      // 加固：仅当文本本身就是指令形态（#开头）才隐藏；用户把正文跟在命令后（如「##导出## 顺便…」）不算
      if (/^##(新对话|打开|删除|模型|导出|预览)[:#]?/.test(t) && t.length <= 12) return true;
      if (/^##\s*(新对话|打开|删除|模型|导出|预览)/.test(t) && t.length <= 12) return true;
      if (/^##(新对话|打开|删除|模型|导出|预览)[\s\S]{0,80}##$/.test(t)) return true;
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
      if (/^##(新对话|打开|删除|模型|导出|预览)/.test(mt) || mt === '对比1和2' || /^我选第\d+个/.test(mt)) {
        m.style.display = 'none';
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
        if (wrap !== col) wrap.style.display = 'none';
      }
    }
    if (target && now - hideTargetAt > 3000) hideTarget = null;   // 3 秒后清理目标，避免误伤后续真实对话
  }
  function collapseProcessStep() {
    // 有最终答复（assistant/user/llm 消息）时才折叠最外层执行过程步骤
    var hasFinal = !!document.querySelector(
      '.step[data-step-type$="message"], .step[data-step-type="llm"], .step[data-step-type="user"]');
    if (!hasFinal) return;
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
  }

  /* ---- 10g. 历史会话独立页 / 知识库页（中间栏覆盖层） ---- */
  var pageOv = null;
  function ensurePageOv() {
    if (pageOv) return;
    pageOv = document.createElement('div');
    pageOv.id = 'zl-page-ov';
    pageOv.innerHTML =
      '<div class="zl-pg-hd">' +
      '<button class="zl-pg-close" id="zl-pg-close" aria-label="返回">' + xIco() + '</button>' +
      '<div class="zl-pg-title" id="zl-pg-title"></div>' +
      '<button class="zl-pg-cta" id="zl-pg-cta" style="display:none">继续对话</button>' +
      '</div><div class="zl-pg-body" id="zl-pg-body"></div>';
    document.body.appendChild(pageOv);
    document.getElementById('zl-pg-close').addEventListener('click', closePage);
    document.getElementById('zl-pg-cta').addEventListener('click', function () {
      var id = pageOv.getAttribute('data-id');
      if (id) sendCmd('##打开:' + id + '##');
      closePage();
    });
  }
  function closePage() { if (pageOv) { pageOv.classList.remove('open'); pageOv.removeAttribute('data-id'); } }
  function openPage(kind) {
    ensurePageOv();
    pageOv.classList.add('open');
    pageOv.removeAttribute('data-id');
    var cta = document.getElementById('zl-pg-cta');
    if (cta) cta.style.display = 'none';
    document.getElementById('zl-pg-title').textContent = kind === 'theory' ? '选址打分依据' : '商业理论知识';
    document.getElementById('zl-pg-body').innerHTML = kind === 'theory' ? KB_THEORY : KB_BUSINESS;
  }
  function renderHistPage(data) {
    if (!data || !data.id) return;
    ensurePageOv();
    pageOv.setAttribute('data-id', data.id);
    pageOv.classList.add('open');
    document.getElementById('zl-pg-title').textContent = '历史会话 · ' + data.title + '（' + data.ts + '）';
    var cta = document.getElementById('zl-pg-cta');
    if (cta) cta.style.display = 'inline-block';
    var body = document.getElementById('zl-pg-body');
    var h = '';
    if (data.analysis && data.analysis.shop) {
      h += '<div class="zl-pg-sum">商铺：<b>' + esc(data.analysis.shop) + '</b>（' + esc(data.analysis.category || '') +
        '） · 综合评分 <b>' + esc(data.analysis.total) + '</b> · ' + esc(data.analysis.verdict || '') + '</div>';
    }
    (data.messages || []).forEach(function (m) {
      var isU = m.role === 'user';
      h += '<div class="zl-pg-msg' + (isU ? ' user' : '') + '"><div class="who">' + (isU ? '你' : 'AI') +
        '</div><div class="txt">' + esc(m.content) + '</div></div>';
    });
    body.innerHTML = h;
    body.scrollTop = 0;
  }

  /* ---- 10h. 知识库内容 ---- */
  var KB_THEORY =
    '<div class="zl-kb-sec">选址打分模型</div>' +
    '<div class="zl-kb-theory"><b>四维评分权重</b><br>客群匹配度 35% ｜ 竞争环境 25% ｜ 交通可达性 25% ｜ 租金承受力 15%（面积适配度辅助 10%）。总分 = Σ(维度分 × 权重)，>80 优质、60–80 中等、<60 谨慎。</div>' +
    '<div class="zl-kb-theory"><b>客群引力（Huff 修正）</b><br>店铺对某客群 POI 的吸引力 = 客群规模权重 / 距离^λ（λ≈2，距离衰减）。客群匹配度 = Σ 各类客群 POI 加权引力累计，越高说明周边「路过的人越对」。</div>' +
    '<div class="zl-kb-theory"><b>竞争环境</b><br>在分析半径内统计同品类竞品数量，与品类基准（comp_base）比较得出竞争压力；同时计算「竞品引力比」，比值越大竞争越激烈。</div>' +
    '<div class="zl-kb-theory"><b>租金承受力</b><br>盈亏平衡租金 = 预估月流水 × rent_ratio（按品类取值，如奶茶 12%）。月租超出承受线则给出「租金偏高」警告。</div>' +
    '<div class="zl-kb-sec">盈利测算流程</div>' +
    '<div class="zl-kb-theory">预估月流水（客单价 × 日单量 × 30）→ 减租金、水电、人工、物料 → 月净利估算 → 回本周期 = 前期投入（装修+设备+转让费等）÷ 月净利。回本周期>24 个月或月净利为负时判定「难回本」。</div>' +
    '<div class="zl-kb-sec">理论依据（示意图）</div>' +
    '<div class="zl-kb-theory">' + flowSVG(['商圈 POI 数据', '客群引力 + 竞品统计', '四维打分', '加权总分', '选址建议']) + '</div>' +
    '<div class="zl-kb-theory">' + flowSVG(['预估流水', '成本拆分', '月净利', '回本周期', '盈亏判断']) + '</div>';

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
    var baseA = dark ? 0.4 : 0.18;                     // 低透明度：粗柱可见但文字清晰
    var hiRgb = dark ? '224,192,132' : '180,140,70';   // 选中：亮色变金色，暗色加亮
    var hiA = dark ? 0.5 : 0.22;
    var SEL = 'div.flex.flex-col.flex-grow.overflow-y-auto.zl-chatcol';
    var css =
      SEL + '.relative{background:var(--zl-chat) !important;}\n' +
      SEL + ':not(.relative){position:relative;z-index:0;background:transparent !important;}\n' +
      SEL + '.relative::before{content:"";position:absolute;left:0;top:0;right:0;bottom:0;pointer-events:none;z-index:-1;background:' + wmLinesCss(baseRgb, baseA) + ';}\n';
    Object.keys(cats).forEach(function (k) {
      css += 'body[data-zcat="' + k + '"] ' + SEL + '.relative::before{background:' + wmLinesCss(hiRgb, hiA) + ';}\n';
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
  var lastConvTs = null;
  function load() {
    armA11y();
    hideHeaderButtons();
    ensureGear();
    ensureModelSelect();
    ensureDisclaimer();
    ensureChatCol();
    ensureVeyra();
    hideCmdBubbles();
    collapseProcessStep();
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
      .then(function (d) { renderHist(d); syncModelSelect(d.model); shiftContent(); })
      .catch(function () { shiftContent(); });
    fetch('/public/dashboard.json', { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error('no dashboard'); return r.json(); })
      .then(function (d) {
        shiftContent();
        if (d && d.ts !== lastDashTs) { lastDashTs = d.ts; renderDashboard(d); }
      })
      .catch(function () { shiftContent(); });
    fetch('/public/conv_page.json', { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error('no conv_page'); return r.json(); })
      .then(function (d) {
        var key = d && d.id ? d.id + '|' + d.ts : '';
        if (key && key !== lastConvTs) {
          lastConvTs = key;
          // 跨刷新记忆：本浏览器已展示过该独立页则不再自动重开，
          // 避免刷新后历史页覆盖层一直盖住整个应用（用户已看过并关闭）。
          // 仅当用户刚点过历史项（##预览: 请求 8 秒内）才强制渲染。
          var justRequested = window.__zl_convReqAt && (Date.now() - window.__zl_convReqAt < 8000);
          var shown = false;
          try { shown = sessionStorage.getItem('zl_conv_page') === key; } catch (e) {}
          if (shown && !justRequested) return;
          try { sessionStorage.setItem('zl_conv_page', key); } catch (e) {}
          window.__zl_convReqAt = 0;
          renderHistPage(d);
        }
      })
      .catch(function () { /* 无独立页数据 */ });
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
})();
