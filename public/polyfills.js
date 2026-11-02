/* ============================================================
   址南针 · 旧浏览器兼容补丁（2026-09-23）
   ------------------------------------------------------------
   【为什么要这个文件】
     Chainlit 2.12 的前端在 **PDF 预览组件（pdf.js）** 里调用了 `URL.parse()` ——
     那是 ES2024 的静态方法，**Chrome 126 / Safari 18 / Firefox 126（均为 2024 年中）
     才提供**。旧浏览器上表现为：分析走到最后一步（生成并预览报告）时整页抛错——

         URL.parse is not a function.
         (In 'URL.parse(t,window.location)', 'URL.parse' is undefined)

     最后那行的报错格式是 **Safari / WebKit 特有**的写法 ⇒ 出问题的多半是他人电脑上的 Safari。

   【已核对的事实】
     · 本项目自己的代码 `public/sidebar.js` 里 `URL.parse` 出现 **0 次**；
     · 8 处全在 chainlit 的 `assets/index-*.js` 内，另有 2 处在 `pdf.worker.min-*.mjs`；
     · 它们**全部落在 PDF 相关代码路径上**（`Invalid PDF url data`、`_isSameOrigin`、
       `rangeChunkSize`、`responseHeaders`）⇒ 只在"出报告"这一步才被触发，
       这正好解释了"前面对话都好、最后一步才崩"的现象。

   【为什么由 index.html 同步引入，而不是放进 sidebar.js】
     补丁必须**早于** Chainlit 的 bundle 执行，否则拦不住。
     `custom_js`（sidebar.js）是 `defer` 加载，不保证足够早；
     所以由 index.html 在 <head> 里以**同步脚本**引入（见 src/analysis/_patch_index_html.py）。
     本文件很小（2 KB 级），在 1 Mbps 下约 0.02 s，对首屏无感。

   【语义要点（容易写错的地方）】
     原生 `URL.parse(url, base)` 在解析失败时**返回 null，不抛异常**。
     所以这里必须 try/catch 后返回 null —— 不能直接把 `new URL` 暴露出去。
     否则 pdf.js 里那句 `const e = URL.parse(t, window.location); if (e) return e.href`
     会从"安静地跳过"变成"整页崩"，反而更糟。
   ============================================================ */
(function () {
  'use strict';

  /* ① URL.parse —— 本次故障的主角（ES2024：Chrome 126 / Safari 18） */
  if (typeof URL.parse !== 'function') {
    URL.parse = function parse(url, base) {
      try {
        return new URL(url, base);
      } catch (e) {
        return null;          /* 与原生一致：失败返回 null，不抛 */
      }
    };
  }

  /* ② Object.hasOwn（ES2022：Safari 15.4 / Chrome 93） */
  if (typeof Object.hasOwn !== 'function') {
    Object.hasOwn = function hasOwn(obj, key) {
      return Object.prototype.hasOwnProperty.call(obj, key);
    };
  }

  /* ③ Array / String 的 .at()（Safari 15.4 / Chrome 92） */
  function defineAt(proto) {
    if (typeof proto.at === 'function') return;
    Object.defineProperty(proto, 'at', {
      value: function at(i) {
        var n = Math.trunc(i) || 0;
        if (n < 0) n += this.length;
        return (n < 0 || n >= this.length) ? undefined : this[n];
      },
      writable: true, configurable: true
    });
  }
  defineAt(Array.prototype);
  defineAt(String.prototype);

  /* ④ Array.prototype.findLast / findLastIndex（Safari 15.4 / Chrome 97） */
  if (typeof Array.prototype.findLast !== 'function') {
    Object.defineProperty(Array.prototype, 'findLast', {
      value: function findLast(fn, thisArg) {
        for (var i = this.length - 1; i >= 0; i--) {
          if (fn.call(thisArg, this[i], i, this)) return this[i];
        }
        return undefined;
      },
      writable: true, configurable: true
    });
  }
  if (typeof Array.prototype.findLastIndex !== 'function') {
    Object.defineProperty(Array.prototype, 'findLastIndex', {
      value: function findLastIndex(fn, thisArg) {
        for (var i = this.length - 1; i >= 0; i--) {
          if (fn.call(thisArg, this[i], i, this)) return i;
        }
        return -1;
      },
      writable: true, configurable: true
    });
  }

  /* ⑤ String.prototype.replaceAll（Safari 13.1 / Chrome 85） */
  if (typeof String.prototype.replaceAll !== 'function') {
    Object.defineProperty(String.prototype, 'replaceAll', {
      value: function replaceAll(find, rep) {
        if (find instanceof RegExp) {
          if (!find.global) {
            throw new TypeError('replaceAll must be called with a global RegExp');
          }
          return this.replace(find, rep);
        }
        return this.split(find).join(rep);
      },
      writable: true, configurable: true
    });
  }

  /* ⑥ Promise.allSettled（Safari 13 / Chrome 76） */
  if (typeof Promise.allSettled !== 'function') {
    Promise.allSettled = function allSettled(list) {
      return Promise.all(Array.prototype.map.call(list, function (p) {
        return Promise.resolve(p).then(
          function (v) { return { status: 'fulfilled', value: v }; },
          function (e) { return { status: 'rejected', reason: e }; }
        );
      }));
    };
  }

  /* ⑦ structuredClone（Safari 15.4 / Chrome 98）
     ⚠️ 这条是**降级**不是等价实现：JSON 深拷贝会丢失 Date / Map / Set / undefined 属性。
        之所以还是加：缺它时旧浏览器上相关代码**直接崩**，降级至少能走通；
        且在浏览器控制台留一行 warn，便于日后判断"是不是踩到了这个降级"。 */
  if (typeof window.structuredClone !== 'function') {
    window.structuredClone = function structuredCloneFallback(obj) {
      if (window.console && console.warn) {
        console.warn('[址南针/polyfill] structuredClone 缺失，已降级为 JSON 深拷贝'
          + '（Date/Map/Set 会失真）');
      }
      return JSON.parse(JSON.stringify(obj));
    };
  }
})();
