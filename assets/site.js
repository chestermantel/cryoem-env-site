/* New Atlantic — cryo-EM env internal site. Shared nav + markdown rendering. */
(function (global) {
  var PAGES = [
    { id: 'index',    href: 'index.html',    label: 'Overview' },
    { id: 'rollouts', href: 'rollouts.html', label: 'Rollouts' },
    { id: 'grader',   href: 'grader.html',   label: 'Grader' },
    { id: 'rfp',      href: 'rfp.html',      label: 'RFP spec' }
  ];

  function nav(active, prefix) {
    prefix = prefix || '';
    var header = document.createElement('header');
    header.className = 'topnav';
    var links = PAGES.map(function (p) {
      return '<a href="' + prefix + p.href + '"' + (p.id === active ? ' class="active"' : '') + '>' + p.label + '</a>';
    }).join('');
    header.innerHTML =
      '<span class="brand">New Atlantic <span class="dim">· cryo-EM env</span></span>' +
      '<nav class="links">' + links + '</nav>';
    document.body.insertBefore(header, document.body.firstChild);
  }

  function slug(s) {
    return s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
  }

  // Render embedded markdown (in <script type="text/markdown" id=srcId>) into #outId,
  // wire the leading H1 as a header (+ optional meta tags), and build a sidebar TOC from H2s.
  function renderDoc(opts) {
    opts = opts || {};
    var srcEl = document.getElementById(opts.srcId || 'doc');
    var out = document.getElementById(opts.outId || 'doc-out');
    if (!srcEl || !out) return;
    var src = srcEl.textContent;

    if (!global.marked) {
      out.innerHTML = '<pre style="white-space:pre-wrap">' +
        src.replace(/[&<>]/g, function (c) { return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[c]; }) + '</pre>';
      return;
    }
    global.marked.setOptions({ gfm: true, breaks: false });
    out.innerHTML = global.marked.parse(src);

    var h1 = out.querySelector('h1');
    if (h1) {
      var sub = h1.nextElementSibling;
      if (sub && sub.tagName === 'P') sub.classList.add('subtitle');
      if (opts.meta) h1.insertAdjacentHTML('afterend', opts.meta);
    }

    var toc = document.getElementById(opts.tocId || 'toc');
    if (!toc) return;
    var heads = out.querySelectorAll('h2');
    heads.forEach(function (h) {
      var id = slug(h.textContent);
      h.id = id;
      var a = document.createElement('a');
      a.href = '#' + id;
      a.className = 'toclink';
      a.textContent = h.textContent;
      a.dataset.target = id;
      toc.appendChild(a);
    });
    var links = Array.prototype.slice.call(toc.querySelectorAll('a.toclink'));
    var obs = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) {
          links.forEach(function (l) { l.classList.toggle('active', l.dataset.target === e.target.id); });
        }
      });
    }, { rootMargin: '-8% 0px -80% 0px', threshold: 0 });
    heads.forEach(function (h) { obs.observe(h); });
  }

  global.Site = { nav: nav, renderDoc: renderDoc, slug: slug };
})(window);
