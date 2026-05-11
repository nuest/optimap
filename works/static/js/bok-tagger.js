/* SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Vanilla JS combobox for tagging works with EO4GEO BoK concepts (issue #245).
 *
 * Backend contracts:
 *   GET  /api/v1/bok/search/?q=<term>&limit=10
 *        -> { query, results: [{code,name,uri,parent_code,breadcrumb,description}] }
 *   POST /work/<id>/contribute-bok/   { add: [...], remove: [...] }
 *        -> { success, bok_concepts, status }
 *
 * Required global config (set by the template before this script loads):
 *   window.OPTIMAP_BOK = { workId, doi, useIdUrls, minQueryLength, initialCodes }
 */

(function () {
  "use strict";

  const cfg = window.OPTIMAP_BOK;
  if (!cfg) return;

  const input = document.getElementById("bok-search-input");
  const suggestionsEl = document.getElementById("bok-suggestions");
  const selectedEl = document.getElementById("bok-selected");
  const saveBtn = document.getElementById("bok-save-btn");
  const combobox = input ? input.parentElement : null;
  if (!input || !suggestionsEl || !selectedEl || !saveBtn || !combobox) return;

  const initial = Array.isArray(cfg.initialCodes) ? cfg.initialCodes.slice() : [];
  let activeIndex = -1;
  let currentResults = [];
  let debounceTimer = null;

  function getCsrfToken() {
    const el = document.querySelector("[name=csrfmiddlewaretoken]");
    return el ? el.value : "";
  }

  function getSelectedCodes() {
    return Array.from(selectedEl.querySelectorAll("li[data-code]"))
      .map((li) => li.dataset.code);
  }

  function setExpanded(expanded) {
    combobox.setAttribute("aria-expanded", expanded ? "true" : "false");
    suggestionsEl.hidden = !expanded;
  }

  function clearSuggestions() {
    suggestionsEl.innerHTML = "";
    activeIndex = -1;
    currentResults = [];
    setExpanded(false);
  }

  function renderSuggestions(results, query) {
    suggestionsEl.innerHTML = "";
    currentResults = results;
    activeIndex = -1;

    if (results.length === 0) {
      const li = document.createElement("li");
      li.className = "bok-suggestion-empty";
      li.textContent = `No matches for "${query}".`;
      suggestionsEl.appendChild(li);
      setExpanded(true);
      return;
    }

    const selected = new Set(getSelectedCodes());
    results.forEach((c, idx) => {
      const li = document.createElement("li");
      li.className = "bok-suggestion";
      li.id = `bok-suggestion-${idx}`;
      li.setAttribute("role", "option");
      li.setAttribute("aria-selected", "false");
      li.dataset.code = c.code;

      const isSelected = selected.has(c.code);

      const name = document.createElement("div");
      name.className = "bok-suggestion-name";
      const nameText = document.createElement("span");
      nameText.textContent = c.name + (isSelected ? " (already added)" : "");
      const codeText = document.createElement("span");
      codeText.className = "bok-suggestion-code";
      codeText.textContent = c.code;
      name.appendChild(nameText);
      name.appendChild(codeText);
      li.appendChild(name);

      if (Array.isArray(c.breadcrumb) && c.breadcrumb.length > 0) {
        const bc = document.createElement("div");
        bc.className = "bok-suggestion-breadcrumb";
        bc.textContent = c.breadcrumb.map((b) => b.name).join(" › ") + " ›";
        li.appendChild(bc);
      }

      if (c.description) {
        const desc = document.createElement("div");
        desc.className = "bok-suggestion-description";
        desc.textContent = c.description;
        li.appendChild(desc);
      }

      if (!isSelected) {
        li.addEventListener("mousedown", (e) => {
          e.preventDefault();
          addCode(c);
        });
      } else {
        li.style.opacity = "0.55";
        li.style.cursor = "default";
      }

      suggestionsEl.appendChild(li);
    });

    setExpanded(true);
  }

  function setActive(idx) {
    const items = suggestionsEl.querySelectorAll(".bok-suggestion");
    items.forEach((el) => el.setAttribute("aria-selected", "false"));
    if (idx < 0 || idx >= items.length) {
      activeIndex = -1;
      input.removeAttribute("aria-activedescendant");
      return;
    }
    activeIndex = idx;
    items[idx].setAttribute("aria-selected", "true");
    input.setAttribute("aria-activedescendant", items[idx].id);
    items[idx].scrollIntoView({ block: "nearest" });
  }

  function moveActive(delta) {
    if (suggestionsEl.hidden) return;
    const items = suggestionsEl.querySelectorAll(".bok-suggestion");
    if (items.length === 0) return;
    let next = activeIndex + delta;
    if (next < 0) next = items.length - 1;
    if (next >= items.length) next = 0;
    setActive(next);
  }

  function addCode(concept) {
    const code = concept.code;
    if (!code) return;
    if (getSelectedCodes().includes(code)) return;

    const li = document.createElement("li");
    li.dataset.code = code;

    if (concept.uri) {
      const a = document.createElement("a");
      a.className = "bok-chip";
      a.href = concept.uri;
      a.target = "_blank";
      a.rel = "noopener";
      a.textContent = concept.name + " ";
      const small = document.createElement("small");
      small.className = "bok-chip-code";
      small.textContent = concept.code;
      a.appendChild(small);
      li.appendChild(a);
    } else {
      const span = document.createElement("span");
      span.className = "bok-chip bok-chip-orphan";
      span.title = "No longer in current EO4GEO BoK";
      span.textContent = code;
      li.appendChild(span);
    }

    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "bok-chip-remove";
    removeBtn.setAttribute("aria-label", `Remove ${concept.name || code}`);
    removeBtn.textContent = "×";
    removeBtn.addEventListener("click", () => li.remove());
    li.appendChild(removeBtn);

    selectedEl.appendChild(li);

    input.value = "";
    clearSuggestions();
  }

  function removeLastChip() {
    const items = selectedEl.querySelectorAll("li[data-code]");
    if (items.length === 0) return;
    items[items.length - 1].remove();
  }

  function fetchSuggestions(query) {
    if (query.length < cfg.minQueryLength) {
      clearSuggestions();
      return;
    }
    const url = `/api/v1/bok/search/?q=${encodeURIComponent(query)}&limit=10`;
    fetch(url, { headers: { Accept: "application/json" } })
      .then((r) => r.json())
      .then((data) => {
        if (input.value.trim() !== query) return; // user kept typing
        renderSuggestions(data.results || [], query);
      })
      .catch((err) => {
        console.warn("BoK search failed:", err);
        clearSuggestions();
      });
  }

  // Wire delegated remove buttons on initial chips.
  selectedEl.querySelectorAll(".bok-chip-remove").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      const li = e.currentTarget.closest("li[data-code]");
      if (li) li.remove();
    });
  });

  input.addEventListener("input", (e) => {
    const q = e.target.value.trim();
    if (debounceTimer) clearTimeout(debounceTimer);
    if (q.length < cfg.minQueryLength) {
      clearSuggestions();
      return;
    }
    debounceTimer = setTimeout(() => fetchSuggestions(q), 180);
  });

  input.addEventListener("keydown", (e) => {
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        moveActive(1);
        break;
      case "ArrowUp":
        e.preventDefault();
        moveActive(-1);
        break;
      case "Enter":
        if (!suggestionsEl.hidden && activeIndex >= 0 && currentResults[activeIndex]) {
          e.preventDefault();
          addCode(currentResults[activeIndex]);
        }
        break;
      case "Escape":
        clearSuggestions();
        input.value = "";
        break;
      case "Backspace":
        if (input.value === "") removeLastChip();
        break;
    }
  });

  input.addEventListener("blur", () => {
    // Delay so a click on a suggestion still fires.
    setTimeout(clearSuggestions, 120);
  });

  saveBtn.addEventListener("click", () => {
    const next = getSelectedCodes();
    const initialSet = new Set(initial);
    const nextSet = new Set(next);
    const add = next.filter((c) => !initialSet.has(c));
    const remove = initial.filter((c) => !nextSet.has(c));

    if (add.length === 0 && remove.length === 0) {
      if (typeof OPTIMAP_FLASH === "function") {
        OPTIMAP_FLASH("info", "No changes to save.");
      }
      return;
    }

    const url = cfg.useIdUrls
      ? `/work/${cfg.workId}/contribute-bok/`
      : `/work/${cfg.doi}/contribute-bok/`;

    saveBtn.disabled = true;
    fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCsrfToken(),
      },
      body: JSON.stringify({ add, remove }),
    })
      .then((r) => r.json().then((d) => ({ ok: r.ok, body: d })))
      .then(({ ok, body }) => {
        if (!ok || !body.success) {
          throw new Error(body.error || "Could not save topics.");
        }
        location.reload();
      })
      .catch((err) => {
        console.error("BoK save failed:", err);
        if (typeof OPTIMAP_FLASH === "function") {
          OPTIMAP_FLASH("error", "Error: " + err.message);
        } else {
          alert("Error: " + err.message);
        }
        saveBtn.disabled = false;
      });
  });
})();
