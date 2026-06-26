/* SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Staff curation widget for assigning MULTIPLE countries/regions to a work that
 * the automated point-in-polygon join could not match (issue #261). Reuses the
 * EO4GEO BoK tagger UX (combobox + autosuggest dropdown + removable chips) and
 * its CSS (css/bok.css), but filters a small option list CLIENT-SIDE instead of
 * hitting a search endpoint.
 *
 * Markup contract — one ".curation-tagger" per work row:
 *   <tr data-curate-url="/.../curate/work/<id>/">
 *     <td>
 *       <div class="curation-tagger"
 *            data-options="curation-country-options"  (id of a json_script block)
 *            data-value-key="iso_code"                (option field used as value)
 *            data-post-key="iso_codes"                (JSON key sent on Assign)
 *            data-search-fields="name,iso_code"       (option fields matched while typing)
 *            data-label-suffix-key="">                (optional bracketed suffix, e.g. region_type)
 *         <div class="bok-combobox" role="combobox" aria-haspopup="listbox" aria-expanded="false">
 *           <input class="form-control form-control-sm curation-search" ...>
 *           <ul class="bok-suggestions curation-suggestions" role="listbox" hidden></ul>
 *         </div>
 *         <ul class="bok-chip-list curation-selected mt-2"></ul>
 *       </div>
 *     </td>
 *     <td>
 *       <button class="curation-assign-btn">Assign</button>
 *       <button class="curation-exclude-btn">Will not be matched</button>
 *       <span class="curation-row-status"></span>
 *     </td>
 *   </tr>
 *
 * Backend contract: POST <data-curate-url> with
 *   { "<post-key>": [<value>, ...] }   to assign, or  { "exclude": true }
 *   -> { success: true, ... }
 *
 * The card element passed to setupCurationCard() must contain a CSRF token input.
 */

(function () {
  "use strict";

  function setupCurationCard(card) {
    if (!card) return;
    const csrfEl = card.querySelector("[name=csrfmiddlewaretoken]");
    const csrf = csrfEl ? csrfEl.value : "";

    function post(url, body, status, onDone) {
      status.textContent = "Saving…";
      status.className = "curation-row-status small ml-2 text-muted";
      fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
        credentials: "same-origin",
        body: JSON.stringify(body),
      })
        .then((r) => r.json().then((d) => ({ ok: r.ok, d })))
        .then(({ ok, d }) => {
          if (!ok || !d.success) throw new Error(d.error || "request failed");
          onDone(d);
        })
        .catch((err) => {
          status.textContent = "Error: " + err.message;
          status.className = "curation-row-status small ml-2 text-danger";
        });
    }

    // Remove a resolved row; hint if the page is now empty.
    function resolveRow(row) {
      const tbody = row.parentNode;
      row.remove();
      if (tbody && tbody.querySelectorAll("tr").length === 0) {
        tbody.insertAdjacentHTML(
          "beforeend",
          '<tr><td colspan="3" class="text-success">Resolved on this page — reload to refresh counts.</td></tr>'
        );
      }
    }

    // Each .curation-tagger is an independent combobox instance.
    card.querySelectorAll(".curation-tagger").forEach((tagger) => initTagger(tagger));

    // Delegated Assign / "Will not be matched" handling.
    card.addEventListener("click", function (ev) {
      const assign = ev.target.closest(".curation-assign-btn");
      const exclude = ev.target.closest(".curation-exclude-btn");
      if (!assign && !exclude) return;
      const row = ev.target.closest("tr");
      const status = row.querySelector(".curation-row-status");
      const url = row.dataset.curateUrl;
      if (exclude) {
        post(url, { exclude: true }, status, () => resolveRow(row));
        return;
      }
      const tagger = row.querySelector(".curation-tagger");
      const values = selectedValues(tagger);
      if (values.length === 0) {
        status.textContent = "Add at least one " + (tagger.dataset.noun || "value") + " first.";
        status.className = "curation-row-status small ml-2 text-danger";
        return;
      }
      const body = {};
      body[tagger.dataset.postKey] = values;
      post(url, body, status, () => resolveRow(row));
    });
  }

  function selectedValues(tagger) {
    return Array.from(tagger.querySelectorAll(".curation-selected li[data-value]")).map(
      (li) => li.dataset.value
    );
  }

  function initTagger(tagger) {
    const input = tagger.querySelector(".curation-search");
    const suggestionsEl = tagger.querySelector(".curation-suggestions");
    const selectedEl = tagger.querySelector(".curation-selected");
    const combobox = input ? input.parentElement : null;
    if (!input || !suggestionsEl || !selectedEl || !combobox) return;

    const optionsEl = document.getElementById(tagger.dataset.options);
    let options = [];
    try {
      options = optionsEl ? JSON.parse(optionsEl.textContent) : [];
    } catch (e) {
      options = [];
    }
    const valueKey = tagger.dataset.valueKey;
    const searchFields = (tagger.dataset.searchFields || valueKey).split(",");
    const suffixKey = tagger.dataset.labelSuffixKey || "";
    const showCode = tagger.dataset.showCode === "1";

    let activeIndex = -1;
    let currentResults = [];

    function label(opt) {
      const suffix = suffixKey && opt[suffixKey] ? " (" + opt[suffixKey] + ")" : "";
      return (opt.name || opt[valueKey]) + suffix;
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

    function search(q) {
      const needle = q.trim().toLowerCase();
      if (!needle) return [];
      const taken = new Set(selectedValues(tagger));
      return options
        .filter((opt) => !taken.has(String(opt[valueKey])))
        .filter((opt) => searchFields.some((f) => String(opt[f] || "").toLowerCase().includes(needle)))
        .slice(0, 10);
    }

    function renderSuggestions(results, query) {
      suggestionsEl.innerHTML = "";
      currentResults = results;
      activeIndex = -1;
      if (results.length === 0) {
        const li = document.createElement("li");
        li.className = "bok-suggestion-empty";
        li.textContent = 'No matches for "' + query + '".';
        suggestionsEl.appendChild(li);
        setExpanded(true);
        return;
      }
      results.forEach((opt, idx) => {
        const li = document.createElement("li");
        li.className = "bok-suggestion";
        li.id = (tagger.id || "tagger") + "-suggestion-" + idx;
        li.setAttribute("role", "option");
        li.setAttribute("aria-selected", "false");

        const name = document.createElement("div");
        name.className = "bok-suggestion-name";
        const nameText = document.createElement("span");
        nameText.textContent = label(opt);
        name.appendChild(nameText);
        if (showCode) {
          const codeText = document.createElement("span");
          codeText.className = "bok-suggestion-code";
          codeText.textContent = opt[valueKey];
          name.appendChild(codeText);
        }
        li.appendChild(name);

        li.addEventListener("mousedown", (e) => {
          e.preventDefault();
          addChip(opt);
        });
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

    function addChip(opt) {
      const value = String(opt[valueKey]);
      if (selectedValues(tagger).includes(value)) return;
      const li = document.createElement("li");
      li.dataset.value = value;

      const span = document.createElement("span");
      span.className = "bok-chip";
      span.textContent = label(opt) + (showCode ? " " : "");
      if (showCode) {
        const small = document.createElement("small");
        small.className = "bok-chip-code";
        small.textContent = value;
        span.appendChild(small);
      }
      li.appendChild(span);

      const removeBtn = document.createElement("button");
      removeBtn.type = "button";
      removeBtn.className = "bok-chip-remove";
      removeBtn.setAttribute("aria-label", "Remove " + label(opt));
      removeBtn.textContent = "×";
      removeBtn.addEventListener("click", () => li.remove());
      li.appendChild(removeBtn);

      selectedEl.appendChild(li);
      input.value = "";
      clearSuggestions();
    }

    function removeLastChip() {
      const items = selectedEl.querySelectorAll("li[data-value]");
      if (items.length > 0) items[items.length - 1].remove();
    }

    input.addEventListener("input", (e) => {
      const q = e.target.value;
      if (!q.trim()) {
        clearSuggestions();
        return;
      }
      renderSuggestions(search(q), q);
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
            addChip(currentResults[activeIndex]);
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

    input.addEventListener("blur", () => setTimeout(clearSuggestions, 120));
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-curation-card]").forEach((card) => setupCurationCard(card));
  });
})();
