(() => {
  const $ = (id) => document.getElementById(id);

  const searchInput = $("drug-search");
  const typeahead = $("typeahead");
  const drugCard = $("drug-card");
  const factsSection = $("facts-section");
  const factsForm = $("facts-form");
  const btnCheck = $("btn-check");
  const btnClear = $("btn-clear");
  const formError = $("form-error");
  const resultEmpty = $("result-empty");
  const resultPanel = $("result-panel");

  let selected = null;
  let debounceTimer = null;
  let activeIndex = -1;

  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function encodingBadge(status) {
    if (!status) return "";
    if (status === "partial" || status === "full") {
      return `<span class="badge badge-partial">${esc(status)}</span>`;
    }
    return `<span class="badge badge-text">${esc(status)}</span>`;
  }

  async function api(path, opts) {
    const res = await fetch(path, opts);
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const j = await res.json();
        detail = j.detail || JSON.stringify(j);
      } catch (_) {}
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return res.json();
  }

  function renderTypeahead(results) {
    if (!results.length) {
      typeahead.classList.add("hidden");
      typeahead.innerHTML = "";
      return;
    }
    typeahead.innerHTML = results
      .map((r, i) => {
        const pa = r.requires_pa
          ? `<span class="badge badge-pa">PA</span>`
          : `<span class="badge badge-ok">no PA flag</span>`;
        const pdl = r.pdl_status
          ? `<span class="badge badge-pdl">${esc(r.pdl_status)}</span>`
          : "";
        const enc = encodingBadge(r.encoding_status);
        return `<li role="option" data-slug="${esc(r.slug)}" data-idx="${i}">
          <span class="name">${esc(r.primary_name)}</span>
          <span class="meta">${pa}${pdl}${enc}<span>${esc(r.slug)}</span></span>
        </li>`;
      })
      .join("");
    typeahead.classList.remove("hidden");
    activeIndex = -1;
    typeahead.querySelectorAll("li").forEach((li) => {
      li.addEventListener("click", () => selectSlug(li.dataset.slug));
    });
  }

  async function doSearch(q) {
    if (!q || q.length < 1) {
      renderTypeahead([]);
      return;
    }
    try {
      const data = await api(`/api/drugs/search?q=${encodeURIComponent(q)}`);
      renderTypeahead(data.results || []);
    } catch (e) {
      renderTypeahead([]);
    }
  }

  searchInput.addEventListener("input", () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => doSearch(searchInput.value.trim()), 180);
  });

  searchInput.addEventListener("keydown", (e) => {
    const items = [...typeahead.querySelectorAll("li")];
    if (!items.length || typeahead.classList.contains("hidden")) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      activeIndex = Math.min(activeIndex + 1, items.length - 1);
      items.forEach((el, i) => el.classList.toggle("active", i === activeIndex));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      activeIndex = Math.max(activeIndex - 1, 0);
      items.forEach((el, i) => el.classList.toggle("active", i === activeIndex));
    } else if (e.key === "Enter" && activeIndex >= 0) {
      e.preventDefault();
      selectSlug(items[activeIndex].dataset.slug);
    } else if (e.key === "Escape") {
      typeahead.classList.add("hidden");
    }
  });

  document.addEventListener("click", (e) => {
    if (!e.target.closest(".search-wrap")) typeahead.classList.add("hidden");
  });

  async function selectSlug(slug) {
    typeahead.classList.add("hidden");
    formError.classList.add("hidden");
    try {
      selected = await api(`/api/drugs/${encodeURIComponent(slug)}`);
      searchInput.value = selected.primary_name;
      renderDrugCard(selected);
      renderFactsForm(selected);
      resultEmpty.classList.remove("hidden");
      resultPanel.classList.add("hidden");
      resultEmpty.textContent =
        "Drug loaded. Enter facts (if shown) and click Run check — or review text-only criteria below after checking.";
    } catch (e) {
      formError.textContent = e.message;
      formError.classList.remove("hidden");
    }
  }

  function renderDrugCard(d) {
    const pa = d.requires_pa
      ? `<span class="badge badge-pa">requires PA</span>`
      : `<span class="badge badge-ok">PA not flagged on index</span>`;
    const citations = (d.citations || [])
      .map((c) => `<li><a href="${esc(c)}" target="_blank" rel="noopener">${esc(c)}</a></li>`)
      .join("");
    drugCard.innerHTML = `
      <h3>${esc(d.primary_name)} ${pa} ${encodingBadge(d.encoding_status)}</h3>
      <dl class="drug-meta">
        <dt>Slug</dt><dd>${esc(d.slug)}</dd>
        ${d.generic_name ? `<dt>Generic</dt><dd>${esc(d.generic_name)}</dd>` : ""}
        <dt>PDL</dt><dd>${esc(d.pdl_status || "unknown / not listed")}</dd>
        <dt>Max units (30d)</dt><dd>${esc(d.max_units_30_days ?? "—")}</dd>
        <dt>Rule pack</dt><dd>${esc(d.rule_pack_slug || "none linked")}</dd>
        <dt>Encoding</dt><dd>${esc(d.encoding_status || "n/a")}${
          d.can_evaluate ? " · evaluate() available" : " · text / checklist only"
        }</dd>
        ${d.market_basket ? `<dt>Class</dt><dd>${esc(d.market_basket)}</dd>` : ""}
      </dl>
      ${
        citations
          ? `<p class="muted">Citations</p><ul class="citations">${citations}</ul>`
          : `<p class="muted">No criteria citation linked for this slug.</p>`
      }
    `;
    drugCard.classList.remove("hidden");
  }

  function humanize(s) {
    return String(s ?? "").replace(/_/g, " ");
  }

  function optionValue(o) {
    return typeof o === "object" && o !== null ? o.value : o;
  }

  function optionLabel(o) {
    if (typeof o === "object" && o !== null) return o.label || humanize(o.value);
    return humanize(o);
  }

  function renderFactsForm(d) {
    const fields = d.fact_fields || [];
    if (!d.rule_pack_slug) {
      factsSection.classList.add("hidden");
      return;
    }
    factsSection.classList.remove("hidden");
    if (!fields.length) {
      factsForm.innerHTML =
        `<p class="muted">No structured required facts on this pack. You can still run check to surface encoding status / archived text.</p>`;
      return;
    }
    factsForm.innerHTML = fields
      .map((f) => {
        const hint = f.hint ? `<p class="hint">${esc(f.hint)}</p>` : "";
        const opts = f.options || [];

        // Multi-select facts → checkbox group (never free text)
        if (f.type === "multi" || f.type === "checkbox" || f.type === "checkboxes") {
          const boxes = opts
            .map((o, i) => {
              const val = optionValue(o);
              const id = `fact-${esc(f.key)}-${i}`;
              return `<label class="check-item" for="${id}">
                <input type="checkbox" id="${id}" name="${esc(f.key)}" value="${esc(val)}" />
                <span>${esc(optionLabel(o))}</span>
              </label>`;
            })
            .join("");
          return `<fieldset class="fact-multi" data-fact="${esc(f.key)}">
            <legend>${esc(f.label)}</legend>
            <div class="check-group">${boxes || `<p class="hint">No options available.</p>`}</div>
            ${hint}
          </fieldset>`;
        }

        // Single select — default for all other fact controls
        // Age bands, indications, specialty, booleans, fallbacks: always <select>
        const selectOpts = [`<option value="">Select…</option>`]
          .concat(
            opts.map(
              (o) =>
                `<option value="${esc(optionValue(o))}">${esc(optionLabel(o))}</option>`
            )
          )
          .join("");
        // Guaranteed controlled options even if API omitted them
        const safeOpts =
          opts.length > 0
            ? selectOpts
            : `<option value="">Select…</option>
               <option value="yes">Yes</option>
               <option value="no">No</option>
               <option value="unknown">Unknown</option>`;
        return `<label for="fact-${esc(f.key)}">${esc(f.label)}</label>
          <select id="fact-${esc(f.key)}" name="${esc(f.key)}">${safeOpts}</select>
          ${hint}`;
      })
      .join("");
  }

  function collectFacts() {
    const data = {};
    const multiKeys = new Set(
      [...factsForm.querySelectorAll("input[type=checkbox][name]")].map((el) => el.name)
    );
    for (const key of multiKeys) {
      const vals = [
        ...factsForm.querySelectorAll(
          `input[type=checkbox][name="${CSS.escape(key)}"]:checked`
        ),
      ].map((el) => el.value);
      if (vals.length) data[key] = vals;
    }
    const fd = new FormData(factsForm);
    for (const [k, v] of fd.entries()) {
      if (multiKeys.has(k)) continue;
      if (v !== "") data[k] = v;
    }
    return data;
  }

  btnClear.addEventListener("click", () => {
    factsForm.reset();
    formError.classList.add("hidden");
  });

  btnCheck.addEventListener("click", async () => {
    if (!selected) {
      formError.textContent = "Select a drug first.";
      formError.classList.remove("hidden");
      return;
    }
    if (!selected.rule_pack_slug) {
      formError.textContent =
        "No rule pack for this drug. PA/PDL info is shown above; criteria evaluate() is unavailable.";
      formError.classList.remove("hidden");
      renderIndexOnlyResult(selected);
      return;
    }
    formError.classList.add("hidden");
    btnCheck.disabled = true;
    try {
      const result = await api("/api/check", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ slug: selected.slug, patient: collectFacts() }),
      });
      renderResult(result, selected);
    } catch (e) {
      formError.textContent = e.message;
      formError.classList.remove("hidden");
    } finally {
      btnCheck.disabled = false;
    }
  });

  function renderIndexOnlyResult(d) {
    resultEmpty.classList.add("hidden");
    resultPanel.classList.remove("hidden");
    resultPanel.innerHTML = `
      <div class="banner need_info">
        <div class="decision">Index only</div>
        <div class="mode-tag">No criteria rule pack linked — cannot run evaluate()</div>
      </div>
      <p class="muted">Requires PA (from list): <strong>${d.requires_pa ? "yes" : "not flagged"}</strong>.
        PDL: ${esc(d.pdl_status || "—")}. Max units: ${esc(d.max_units_30_days ?? "—")}.</p>
    `;
  }

  function renderResult(r, d) {
    resultEmpty.classList.add("hidden");
    resultPanel.classList.remove("hidden");

    const decision = r.decision || "need_info";
    const modeNote =
      r.mode === "text_only"
        ? "Text-only / encoding incomplete — showing archived criteria text and fact checklist. No invented coverage yes/no."
        : `Deterministic evaluate() on ${esc(r.encoding_status || "encoded")} pack`;

    let html = `
      <div class="banner ${esc(decision)}">
        <div class="decision">${esc(decision.replace("_", " "))}</div>
        <div class="mode-tag">${modeNote}</div>
        <div class="muted" style="margin-top:0.35rem">${esc(r.drug || d.primary_name)}</div>
      </div>
    `;

    if (r.mode === "text_only") {
      const checklist = (r.checklist || [])
        .map(
          (f) =>
            `<li><input type="checkbox" disabled /> <span><strong>${esc(
              f.label || f.key
            )}</strong> <span class="muted">(${esc(f.key)})</span> — document against source PDF</span></li>`
        )
        .join("");
      html += `
        <div class="section">
          <h3>Required-fact checklist (manual)</h3>
          <ul class="checklist">${
            checklist || "<li class='muted'>No inferred facts listed on pack.</li>"
          }</ul>
          <p class="muted">Checkboxes are a clinician worksheet only — they do not change the engine decision.</p>
        </div>
      `;
      const ct = r.criteria_text;
      if (ct && ct.extracted_text) {
        html += `
          <div class="section">
            <h3>Extracted criteria text</h3>
            <p class="muted">Source:
              ${
                ct.source_url
                  ? `<a href="${esc(ct.source_url)}" target="_blank" rel="noopener">${esc(
                      ct.source_file || ct.source_url
                    )}</a>`
                  : esc(ct.source_file || "archived PDF")
              }
              ${ct.effective_date ? ` · effective ${esc(ct.effective_date)}` : ""}
            </p>
            <pre class="criteria-box">${esc(ct.extracted_text)}</pre>
          </div>
        `;
      } else {
        html += `<p class="muted">No extracted criteria text file for this pack slug.</p>`;
      }
    }

    if ((r.failed_clauses || []).length) {
      html += `<div class="section"><h3>Failed clauses</h3><ul class="clause-list">`;
      for (const c of r.failed_clauses) {
        html += `<li><div class="id">${esc(c.id)}</div><div>${esc(c.text)}</div>
          ${c.citation ? `<div><a href="${esc(c.citation)}" target="_blank" rel="noopener">citation</a></div>` : ""}
        </li>`;
      }
      html += `</ul></div>`;
    }

    if ((r.missing_facts || []).length) {
      html += `<div class="section"><h3>Missing facts</h3><ul class="notes-list">`;
      for (const f of r.missing_facts) {
        html += `<li><code>${esc(f)}</code></li>`;
      }
      html += `</ul></div>`;
    }

    if (r.mode === "evaluate" && (r.criteria_clauses || []).length) {
      html += `<div class="section"><h3>Encoded criteria</h3><ul class="clause-list">`;
      for (const c of r.criteria_clauses) {
        html += `<li><div class="id">${esc(c.id)}</div><div>${esc(c.text)}</div></li>`;
      }
      html += `</ul></div>`;
    }

    if ((r.alternatives || []).length) {
      const title =
        r.mode === "text_only"
          ? "Suggested alternatives (class / PDL)"
          : decision === "fail"
            ? "Alternatives"
            : "Suggested alternatives";
      html += `<div class="section"><h3>${title}</h3><ul class="alt-list">`;
      for (const a of r.alternatives) {
        const ver = a.verification || "";
        const badge =
          ver === "evaluate_pass"
            ? `<span class="badge badge-ok">evaluate pass</span>`
            : ver === "pdl_preferred_same_class"
              ? `<span class="badge badge-pdl">PDL preferred · same class</span>`
              : ver
                ? `<span class="badge badge-text">${esc(ver)}</span>`
                : "";
        const note = a.verification_note
          ? `<div class="hint">${esc(a.verification_note)}</div>`
          : "";
        const meta = [
          a.rule_id ? `pack ${a.rule_id}` : null,
          a.market_basket ? a.market_basket : null,
          a.pdl_status ? `PDL ${a.pdl_status}` : null,
        ]
          .filter(Boolean)
          .map(esc)
          .join(" · ");
        const cites = (a.citations || [])
          .slice(0, 2)
          .map(
            (c) =>
              `<a href="${esc(c)}" target="_blank" rel="noopener">${esc(c)}</a>`
          )
          .join(" · ");
        html += `<li>
          <div><strong>${esc(a.drug)}</strong> ${badge}</div>
          ${meta ? `<div class="muted">${meta}</div>` : ""}
          ${note}
          ${cites ? `<div class="muted">${cites}</div>` : ""}
        </li>`;
      }
      html += `</ul></div>`;
    } else if (decision === "fail") {
      html += `<p class="muted">No evaluate()-verified or PDL preferred same-class alternatives found for these facts.</p>`;
    }

    if ((r.citations || []).length) {
      html += `<div class="section"><h3>Citations</h3><ul class="citations">`;
      for (const c of r.citations) {
        html += `<li><a href="${esc(c)}" target="_blank" rel="noopener">${esc(c)}</a></li>`;
      }
      html += `</ul></div>`;
    }

    if ((r.notes || []).length) {
      html += `<div class="section"><h3>Notes</h3><ul class="notes-list">`;
      for (const n of r.notes) {
        html += `<li>${esc(n)}</li>`;
      }
      html += `</ul></div>`;
    }

    html += `<p class="muted" style="margin-top:1rem">Advisory · published AK criteria · not a guarantee of payer approval.</p>`;
    resultPanel.innerHTML = html;
  }
})();
