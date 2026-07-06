/* IssueLens 프론트엔드 동작
   1) 다크/라이트 테마 토글 (localStorage 유지)
   2) 스크롤 진입 애니메이션 (IntersectionObserver)
   3) 종목 자동완성 (시장별 그룹, 키보드 탐색 지원) */

(function () {
  "use strict";

  /* ── 1. 테마 ─────────────────────────────────────────── */
  const root = document.documentElement;
  const saved = localStorage.getItem("issuelens-theme");
  if (saved === "light" || saved === "dark") root.setAttribute("data-theme", saved);

  function currentTheme() {
    return root.getAttribute("data-theme") === "light" ? "light" : "dark";
  }
  function applyToggleIcon(btn) {
    btn.textContent = currentTheme() === "light" ? "다크 모드" : "라이트 모드";
  }
  document.addEventListener("DOMContentLoaded", function () {
    const btn = document.getElementById("theme-toggle");
    if (btn) {
      applyToggleIcon(btn);
      btn.addEventListener("click", function () {
        const next = currentTheme() === "light" ? "dark" : "light";
        root.setAttribute("data-theme", next);
        localStorage.setItem("issuelens-theme", next);
        applyToggleIcon(btn);
      });
    }

    /* ── 2. 스크롤 진입 애니메이션 ──────────────────────── */
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const targets = document.querySelectorAll(".reveal");
    if (reduced || !("IntersectionObserver" in window)) {
      targets.forEach(function (el) { el.classList.add("in-view"); });
    } else {
      const io = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) {
          if (e.isIntersecting) {
            e.target.classList.add("in-view");
            io.unobserve(e.target);
          }
        });
      }, { threshold: 0.12 });
      targets.forEach(function (el) { io.observe(el); });
    }

    /* ── 3. 종목 자동완성 ───────────────────────────────── */
    document.querySelectorAll("[data-autocomplete]").forEach(setupAutocomplete);
  });

  function setupAutocomplete(input) {
    const wrap = input.closest(".ac-wrap");
    if (!wrap) return;
    const panel = wrap.querySelector(".ac-panel");
    let items = [];        // 평탄화된 선택 가능 항목
    let active = -1;
    let timer = null;

    function close() { panel.classList.remove("open"); panel.innerHTML = ""; items = []; active = -1; }

    function render(results) {
      if (!results.length) { close(); return; }
      const groups = { KR: [], US: [] };
      results.forEach(function (r) { (groups[r.market] || (groups[r.market] = [])).push(r); });
      let html = "";
      items = [];
      [["KR", "한국 증시"], ["US", "미국 증시"]].forEach(function (g) {
        const key = g[0], label = g[1];
        if (!groups[key] || !groups[key].length) return;
        html += '<div class="ac-group">' + label + "</div>";
        groups[key].forEach(function (r) {
          const idx = items.length;
          items.push(r);
          html += '<button type="button" class="ac-item" data-idx="' + idx + '">'
                + '<span class="ac-name">' + escapeHtml(r.name) + "</span>"
                + '<span class="ac-meta">' + escapeHtml(r.ticker) + "</span>"
                + "</button>";
        });
      });
      panel.innerHTML = html;
      panel.classList.add("open");
      active = -1;
      panel.querySelectorAll(".ac-item").forEach(function (el) {
        el.addEventListener("mousedown", function (ev) {
          ev.preventDefault();
          choose(parseInt(el.getAttribute("data-idx"), 10));
        });
      });
    }

    function choose(idx) {
      const r = items[idx];
      if (!r) return;
      input.value = r.ticker;          // 티커로 확정 (정확 매칭 보장)
      const nameField = input.form && input.form.querySelector('input[name="name"]');
      if (nameField) nameField.value = r.name;
      close();
    }

    input.addEventListener("input", function () {
      clearTimeout(timer);
      const q = input.value.trim();
      if (q.length < 1) { close(); return; }
      timer = setTimeout(function () {
        fetch("/api/search?q=" + encodeURIComponent(q))
          .then(function (res) { return res.json(); })
          .then(render)
          .catch(close);
      }, 140);
    });
    input.addEventListener("keydown", function (ev) {
      const els = panel.querySelectorAll(".ac-item");
      if (!els.length) return;
      if (ev.key === "ArrowDown") { ev.preventDefault(); active = (active + 1) % els.length; }
      else if (ev.key === "ArrowUp") { ev.preventDefault(); active = (active - 1 + els.length) % els.length; }
      else if (ev.key === "Enter" && active >= 0) { ev.preventDefault(); choose(active); return; }
      else if (ev.key === "Escape") { close(); return; }
      else return;
      els.forEach(function (el, i) { el.classList.toggle("active", i === active); });
    });
    input.addEventListener("blur", function () { setTimeout(close, 120); });
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
})();
