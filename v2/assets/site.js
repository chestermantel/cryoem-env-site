/* New Atlantic — cryo-EM benchmark site (v2). Shared nav, TOC, scroll-spy, score heatmap. */
(function (global) {
  var PAGES = [
    { id: 'index',      href: 'index.html',      label: 'Overview' },
    { id: 'rollouts',   href: 'rollouts.html',   label: 'Tasks' },
    { id: 'grader',     href: 'grader.html',     label: 'Grader' },
    { id: 'benchmark',  href: 'benchmark.html',  label: 'Benchmark' },
    { id: 'rfp',        href: 'rfp.html',        label: 'Env spec' },
    { id: 'next-phase', href: 'next-phase.html', label: 'Next phase' }
  ];

  function slug(s) {
    return String(s).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
  }

  function nav(active, prefix) {
    prefix = prefix || '';
    var header = document.createElement('header');
    header.className = 'topnav';
    var links = PAGES.map(function (p) {
      return '<a href="' + prefix + p.href + '"' + (p.id === active ? ' class="active"' : '') + '>' + p.label + '</a>';
    }).join('');
    header.innerHTML =
      '<a class="brand" href="' + prefix + 'index.html">' +
        '<span class="mark">New Atlantic</span>' +
        '<span class="dim">cryo-EM&nbsp;benchmark</span>' +
      '</a>' +
      '<nav class="links">' + links + '</nav>';
    document.body.insertBefore(header, document.body.firstChild);
  }

  // Build a sidebar TOC from the article's H2s (and optionally H3s) into #toc, then scroll-spy.
  // Skips if #toc already holds links (report pages ship a hand-built TOC).
  function buildTOC(opts) {
    opts = opts || {};
    var toc = document.getElementById(opts.tocId || 'toc');
    var scope = document.querySelector(opts.scope || 'article');
    if (!toc || !scope) return;
    if (toc.querySelector('a.toclink')) { spy(scope, toc); return; }

    var heads = scope.querySelectorAll(opts.sub ? 'h2, h3' : 'h2');
    heads.forEach(function (h) {
      if (!h.id) h.id = slug(h.textContent);
      var a = document.createElement('a');
      a.href = '#' + h.id;
      a.className = 'toclink' + (h.tagName === 'H3' ? ' sub' : '');
      a.textContent = h.textContent;
      a.dataset.target = h.id;
      toc.appendChild(a);
    });
    spy(scope, toc);
  }

  function spy(scope, toc) {
    var heads = scope.querySelectorAll('h2[id], h3[id]');
    var links = Array.prototype.slice.call(toc.querySelectorAll('a.toclink'));
    if (!heads.length || !links.length) return;
    var obs = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) {
          links.forEach(function (l) { l.classList.toggle('active', l.dataset.target === e.target.id); });
        }
      });
    }, { rootMargin: '-9% 0px -82% 0px', threshold: 0 });
    heads.forEach(function (h) { if (h.id) obs.observe(h); });
  }

  // Turn normalized [0,1] cells in table.scoretable into a value heatmap.
  // Skips the first (label) column and any "Wt"/"Weight" column. Non-[0,1] cells (Å, ratios) stay plain.
  var NUM = /^(0(\.\d+)?|1(\.0+)?|\.\d+)$/;
  function heatmap() {
    document.querySelectorAll('table.scoretable').forEach(function (tbl) {
      var heads = tbl.querySelectorAll('thead th');
      var skip = {};
      heads.forEach(function (th, i) {
        var t = th.textContent.trim().toLowerCase();
        if (i === 0 || t === 'wt' || t === 'weight' || t === 'w') skip[i] = true;
      });
      tbl.querySelectorAll('tbody tr').forEach(function (tr) {
        Array.prototype.forEach.call(tr.children, function (td, i) {
          if (skip[i] || td.tagName !== 'TD') return;
          var txt = td.textContent.trim();
          if (!NUM.test(txt)) return;
          var v = parseFloat(txt);
          if (isNaN(v) || v < 0 || v > 1) return;
          td.style.setProperty('--v', v.toFixed(3));
          td.classList.add('cell-heat');
        });
      });
    });
  }

  function init(opts) {
    opts = opts || {};
    if (opts.nav !== false) nav(opts.active, opts.prefix);
    buildTOC(opts);
    heatmap();
  }

  global.Site = { nav: nav, buildTOC: buildTOC, heatmap: heatmap, slug: slug, init: init };
})(window);
