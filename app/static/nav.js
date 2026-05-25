/*
 * nav.js — единый sidebar для ВСЕХ страниц Codex v2.
 * UC-72 + UC-80 (Pavel 2026-05-21): полная переделка под claude.ai-стиль.
 * - Lucide SVG inline (без npm)
 * - Header 56px: лого 32x32 + Lucide panel-left-close toggle
 * - Активный пункт = серый фон (не цветной)
 * - Профиль внизу: аватар + Pavel + Хилингод
 * - Cmd+B / Ctrl+B горячая клавиша
 * - localStorage: kodeks.sidebar.left.collapsed
 *
 * 7 пунктов меню: Новая глава, Оглавление, Редактор, Утренний брифинг,
 * Хранилище, Критики. Внизу: Компоненты.
 */

(function() {
  const ICON = {
    plus:           '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14"/></svg>',
    messageCircleQuestion: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M7.9 20A9 9 0 1 0 4 16.1L2 22z"/><path d="M9.1 9a3 3 0 1 1 5.1 2.6c-.6.5-1.2.9-1.2 1.9"/><path d="M12 17h.01"/></svg>',
    library:        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="m16 6 4 14"/><path d="M12 6v14"/><path d="M8 8v12"/><path d="M4 4v16"/></svg>',
    bookOpen:       '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>',
    penLine:        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.376 3.622a1 1 0 0 1 3.002 3.002L7.368 18.635a2 2 0 0 1-.855.506l-2.872.838a.5.5 0 0 1-.62-.62l.838-2.872a2 2 0 0 1 .506-.854z"/></svg>',
    sun:            '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/></svg>',
    archive:        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><rect width="20" height="5" x="2" y="3" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8"/><path d="M10 12h4"/></svg>',
    gavel:          '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="m14.5 12.5-8 8a2.119 2.119 0 1 1-3-3l8-8"/><path d="m16 16 6-6"/><path d="m8 8 6-6"/><path d="m9 7 8 8"/><path d="m21 11-8-8"/></svg>',
    palette:        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><circle cx="13.5" cy="6.5" r=".5" fill="currentColor"/><circle cx="17.5" cy="10.5" r=".5" fill="currentColor"/><circle cx="8.5" cy="7.5" r=".5" fill="currentColor"/><circle cx="6.5" cy="12.5" r=".5" fill="currentColor"/><path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.926 0 1.648-.746 1.648-1.688 0-.437-.18-.835-.437-1.125-.29-.289-.438-.652-.438-1.125a1.64 1.64 0 0 1 1.668-1.668h1.996c3.051 0 5.555-2.503 5.555-5.554C21.965 6.012 17.461 2 12 2Z"/></svg>',
    panelLeftClose: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><rect width="18" height="18" x="3" y="3" rx="2"/><path d="M9 3v18"/><path d="m16 15-3-3 3-3"/></svg>',
    panelLeftOpen:  '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><rect width="18" height="18" x="3" y="3" rx="2"/><path d="M9 3v18"/><path d="m14 9 3 3-3 3"/></svg>',
  };

  const NAV_ITEMS = [
    { id: "wizard",      label: "Новая глава",       href: "/wizard",      icon: ICON.plus },
    { id: "toc",         label: "Оглавление",        href: "/",            icon: ICON.bookOpen },
    { id: "briefing",    label: "Утренний брифинг",  href: "/briefing",    icon: ICON.sun },
    { id: "editor",      label: "Редактор Главы",    href: "/editor",      icon: ICON.penLine },
    { id: "critics",     label: "Критики",           href: "/critics",     icon: ICON.gavel },
    { id: "book-editor", label: "Редактор Книги",    href: "/book-editor", icon: ICON.library },
    { id: "storage",     label: "Хранилище",         href: "/storage",     icon: ICON.archive },
    { id: "library",     label: "Библиотека примеров", href: "/library",   icon: ICON.library },
    { id: "styles",      label: "Стили",             href: "/styles",      icon: ICON.palette },
  ];

  function detectActive() {
    const path = (window.location.pathname || "/").replace(/\/$/, "") || "/";
    if (path === "/") return "toc";
    if (path.startsWith("/editor")) return "editor";
    if (path.startsWith("/briefing")) return "briefing";
    if (path.startsWith("/storage")) return "storage";
    if (path.startsWith("/wizard")) return "wizard";
    if (path.startsWith("/critics")) return "critics";
    if (path.startsWith("/book-editor")) return "book-editor";
    if (path.startsWith("/journalist")) return "journalist";
    if (path.startsWith("/library")) return "library";
    if (path.startsWith("/styles")) return "styles";
    if (path.startsWith("/morning-plan") || path.startsWith("/recommendations")) return "briefing";
    if (path.startsWith("/components")) return "components";
    return null;
  }

  function render() {
    const host = document.getElementById("appSidebar");
    if (!host) return;
    const active = host.dataset.page || detectActive();
    const collapsed = localStorage.getItem("kodeks.sidebar.left.collapsed") === "true";
    if (collapsed) document.body.classList.add("sidebar-collapsed");

    const itemsHtml = NAV_ITEMS.map(it => {
      const isActive = it.id === active ? " active" : "";
      return '<a href="' + it.href + '" class="nav-item' + isActive + '" data-nav="' + it.id + '" title="' + it.label + '">'
        + '<span class="nav-icon">' + it.icon + '</span>'
        + '<span class="nav-label">' + it.label + '</span>'
        + '</a>';
    }).join("");

    const toggleIcon = collapsed ? ICON.panelLeftOpen : ICON.panelLeftClose;
    const componentsActive = active === "components" ? " active" : "";

    host.innerHTML = ''
      + '<header class="nav-header">'
      +   '<div class="nav-brand">'
      +     '<div class="nav-brand-mark">К</div>'
      +     '<div class="nav-brand-text"><div class="nav-brand-name">Кодекс</div></div>'
      +   '</div>'
      +   '<button class="nav-toggle" id="navToggle" aria-label="toggle" title="Свернуть (Cmd+B)">' + toggleIcon + '</button>'
      + '</header>'
      + '<nav class="nav-group" id="appNavGroup">' + itemsHtml + '</nav>'
      + '<div class="nav-recent" id="navRecent">'
      +   '<div class="nav-recent-header">Последние работы</div>'
      +   '<div class="nav-recent-list" id="navRecentList"><div class="nav-recent-empty">загружаю…</div></div>'
      + '</div>'
      + '<div class="nav-footer">'
      +   '<a href="/components" class="nav-item' + componentsActive + '" data-nav="components" title="Компоненты">'
      +     '<span class="nav-icon">' + ICON.palette + '</span>'
      +     '<span class="nav-label">Компоненты</span>'
      +   '</a>'
      + '</div>'
      + '<div class="nav-profile">'
      +   '<div class="nav-profile-avatar">П</div>'
      +   '<div class="nav-profile-info">'
      +     '<div class="nav-profile-name">Pavel</div>'
      +     '<div class="nav-profile-plan">Хилингод</div>'
      +   '</div>'
      + '</div>';

    const toggleBtn = document.getElementById("navToggle");
    if (toggleBtn) toggleBtn.addEventListener("click", toggleSidebar);

    // UC-112: подгружаем список последних работ
    loadRecentWorks();
  }

  function loadRecentWorks() {
    const list = document.getElementById("navRecentList");
    if (!list) return;
    fetch("/api/recent-works")
      .then(function(r) { return r.json(); })
      .then(function(d) {
        const out = [];
        const chs = (d.chapters || []).slice(0, 5);
        if (chs.length === 0 && (!d.journalist_sessions || !d.journalist_sessions.length)) {
          list.innerHTML = '<div class="nav-recent-empty">пока пусто</div>';
          return;
        }
        chs.forEach(function(c) {
          const title = c.title || c.chapter_id;
          const when = c.saved_at ? relativeTime(c.saved_at) : "";
          out.push(
            '<a href="/editor?chapter=' + encodeURIComponent(c.chapter_id) + '" class="nav-recent-item" title="' + escapeHtml(title) + '">'
            + '<span class="nav-recent-title">' + escapeHtml(title) + '</span>'
            + '<span class="nav-recent-time">' + escapeHtml(when) + '</span>'
            + '</a>'
          );
        });
        const js = (d.journalist_sessions || []).filter(function(j) { return !j.complete; }).slice(0, 2);
        js.forEach(function(j) {
          out.push(
            '<a href="/wizard?journalist=' + encodeURIComponent(j.session_id) + '" class="nav-recent-item" title="Журналист: ' + escapeHtml(j.topic) + '">'
            + '<span class="nav-recent-title">[Журналист] ' + escapeHtml(j.topic || j.session_id) + '</span>'
            + '<span class="nav-recent-time">' + escapeHtml(j.updated_at ? relativeTime(j.updated_at) : "") + '</span>'
            + '</a>'
          );
        });
        list.innerHTML = out.join("") || '<div class="nav-recent-empty">пока пусто</div>';
      })
      .catch(function() {
        list.innerHTML = '<div class="nav-recent-empty">нет данных</div>';
      });
  }

  function relativeTime(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    const now = new Date();
    const diff = (now - d) / 1000;
    if (diff < 60) return "только что";
    if (diff < 3600) return Math.floor(diff / 60) + " мин";
    if (diff < 86400) return Math.floor(diff / 3600) + " ч";
    if (diff < 86400 * 7) return Math.floor(diff / 86400) + " д";
    const months = ["янв","фев","мар","апр","мая","июн","июл","авг","сен","окт","ноя","дек"];
    return d.getDate() + " " + months[d.getMonth()];
  }

  function escapeHtml(s) {
    if (s == null) return "";
    return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
  }

  function toggleSidebar() {
    const collapsed = document.body.classList.toggle("sidebar-collapsed");
    localStorage.setItem("kodeks.sidebar.left.collapsed", collapsed ? "true" : "false");
    const btn = document.getElementById("navToggle");
    if (btn) btn.innerHTML = collapsed ? ICON.panelLeftOpen : ICON.panelLeftClose;
  }

  document.addEventListener("keydown", function(e) {
    if ((e.metaKey || e.ctrlKey) && !e.shiftKey && e.key === "b") {
      const tag = (document.activeElement && document.activeElement.tagName || "").toLowerCase();
      if (tag === "input" || tag === "textarea" || (document.activeElement && document.activeElement.isContentEditable)) return;
      e.preventDefault();
      toggleSidebar();
    }
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", render);
  } else {
    render();
  }
})();
