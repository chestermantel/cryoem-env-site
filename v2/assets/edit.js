/* ============================================================================
   Direct in-browser text editing.

   Adds a floating "Edit text" button. In edit mode every prose block becomes
   directly editable in place; changes are saved to this browser (localStorage,
   keyed per page) and re-applied on every visit. "Export HTML" downloads the
   page with your edits baked into the markup, so it can replace the source file.

   No backend. Edits are local to your browser until you export + commit them.
   ============================================================================ */
(function () {
  var KEY = 'nae-edit:' + location.pathname;

  // The set of editable blocks: prose inside the article, never the chrome.
  // Excludes the sidebar, nav, code/equations/SVG, and anything inside a <summary>
  // (so opening/closing collapsibles never fights with editing).
  var SEL = [
    'article p', 'article li', 'article h1', 'article h2', 'article h3', 'article h4',
    'article figcaption', 'article blockquote', 'article dd', 'article dt',
    'article th', 'article td', '.lead', '.subtitle',
    '.stat .num', '.stat .lbl', '.hubcard h3', '.hubcard p', 'article .kicker'
  ].join(',');

  function editable() {
    var out = [];
    document.querySelectorAll(SEL).forEach(function (el) {
      if (el.closest('.side, .topnav, .no-edit, pre, .eqn, svg, .edit-bar, .edit-fab')) return;
      if (el.closest('summary')) return;                 // avoid the toggle/edit conflict
      if (el.querySelector('p, li, ul, ol, table, dl, figure, .kv')) return; // only leaf-ish text blocks
      out.push(el);
    });
    return out;
  }

  // Apply saved edits (run after any JS-rendered content exists).
  function applyOverrides() {
    var store;
    try { store = JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (e) { store = {}; }
    if (!store || !Object.keys(store).length) return;
    editable().forEach(function (el, i) {
      if (store[i] != null) el.innerHTML = store[i];
    });
  }

  function save(i, html) {
    var store;
    try { store = JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (e) { store = {}; }
    store[i] = html;
    localStorage.setItem(KEY, JSON.stringify(store));
  }

  var editing = false;
  function enter() {
    editing = true;
    document.body.classList.add('editing');
    editable().forEach(function (el, i) {
      el.setAttribute('contenteditable', 'true');
      el.setAttribute('spellcheck', 'true');
      el.dataset.ek = i;
      el.addEventListener('input', onInput);
    });
    toast('Editing on — click any text to change it');
  }
  function exit() {
    editing = false;
    document.body.classList.remove('editing');
    document.querySelectorAll('[contenteditable="true"]').forEach(function (el) {
      el.removeAttribute('contenteditable');
      el.removeAttribute('spellcheck');
      el.removeEventListener('input', onInput);
    });
  }
  var t;
  function onInput(e) {
    var el = e.currentTarget;
    clearTimeout(t);
    t = setTimeout(function () { save(+el.dataset.ek, el.innerHTML); }, 250);
  }

  function resetPage() {
    if (!confirm('Discard all of your edits on this page and restore the original text?')) return;
    localStorage.removeItem(KEY);
    location.reload();
  }

  function exportHTML() {
    var clone = document.documentElement.cloneNode(true);
    // strip edit-mode artifacts from the exported copy
    clone.querySelectorAll('[contenteditable]').forEach(function (el) {
      el.removeAttribute('contenteditable'); el.removeAttribute('spellcheck'); el.removeAttribute('data-ek');
    });
    clone.querySelectorAll('.edit-fab, .edit-bar, .toast').forEach(function (el) { el.remove(); });
    var body = clone.querySelector('body'); if (body) body.classList.remove('editing');
    var doc = '<!doctype html>\n' + clone.outerHTML;
    var name = (location.pathname.split('/').pop() || 'index.html');
    var blob = new Blob([doc], { type: 'text/html' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = name;
    document.body.appendChild(a); a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
    toast('Downloaded ' + name + ' with your edits');
  }

  var toastEl;
  function toast(msg) {
    if (!toastEl) { toastEl = document.createElement('div'); toastEl.className = 'toast'; document.body.appendChild(toastEl); }
    toastEl.textContent = msg; toastEl.classList.add('show');
    clearTimeout(toast._t); toast._t = setTimeout(function () { toastEl.classList.remove('show'); }, 2400);
  }

  function mountUI() {
    var fab = document.createElement('button');
    fab.className = 'edit-fab'; fab.type = 'button'; fab.setAttribute('aria-label', 'Edit page text');
    fab.innerHTML = '<span class="ic">✎</span> Edit text';
    fab.addEventListener('click', enter);

    var bar = document.createElement('div');
    bar.className = 'edit-bar';
    bar.innerHTML =
      '<span class="status"><span class="live"></span>Editing — saved in this browser</span>' +
      '<span class="sep"></span>' +
      '<button type="button" class="ghost" data-act="reset">Reset page</button>' +
      '<button type="button" data-act="export">Export HTML</button>' +
      '<button type="button" class="primary" data-act="done">Done</button>';
    bar.addEventListener('click', function (e) {
      var act = e.target.getAttribute('data-act');
      if (act === 'reset') resetPage();
      else if (act === 'export') exportHTML();
      else if (act === 'done') { exit(); toast('Edits saved in this browser'); }
    });

    document.body.appendChild(fab);
    document.body.appendChild(bar);
  }

  // Apply saved overrides after everything (including JS-rendered cards) is on the page.
  if (document.readyState === 'complete') { applyOverrides(); mountUI(); }
  else { window.addEventListener('load', function () { applyOverrides(); mountUI(); }); }
})();
