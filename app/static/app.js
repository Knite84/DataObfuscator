const editor = document.getElementById("editor");
const analyzeBtn = document.getElementById("analyze-btn");
const clearBtn = document.getElementById("clear-btn");
const returnReviewBtn = document.getElementById("return-review-btn");
const reviewStaleHint = document.getElementById("review-stale-hint");
const inputPanel = document.getElementById("input-panel");
const inputWarnings = document.getElementById("input-warnings");
const backInputBtn = document.getElementById("back-input-btn");
const backReviewBtn = document.getElementById("back-review-btn");
const startOverBtn = document.getElementById("start-over-btn");
const resultsPanel = document.getElementById("results-panel");
const mappingBody = document.getElementById("mapping-body");
const approveRemainingBtn = document.getElementById("approve-remaining-btn");
const rejectRemainingBtn = document.getElementById("reject-remaining-btn");
const warningsEl = document.getElementById("warnings");
const reviewProgress = document.getElementById("review-progress");
const unverifiedHeading = document.getElementById("unverified-heading");
const unverifiedTable = document.getElementById("unverified-table");
const unverifiedBody = document.getElementById("unverified-body");
const manualQuoteEl = document.getElementById("manual-quote");
const manualCategoryEl = document.getElementById("manual-category");
const manualAddBtn = document.getElementById("manual-add-btn");
const manualForm = document.getElementById("manual-form");
const manualReplacementEl = document.getElementById("manual-replacement");
const manualError = document.getElementById("manual-error");
let suggestions = [];
let activeSuggestion = null;
let previewVersion = 0;
let previewData = null;
let previewTimer;
let replacementCustomized = false;
const finalizeBtn = document.getElementById("finalize-btn");
const finalPanel = document.getElementById("final-panel");
const finalWarnings = document.getElementById("final-warnings");
const finalHtml = document.getElementById("final-html");
const finalTxt = document.getElementById("final-txt");
const copyTxtBtn = document.getElementById("copy-txt-btn");
const copyHtmlBtn = document.getElementById("copy-html-btn");
const copyFeedback = document.getElementById("copy-feedback");
const downloadTxt = document.getElementById("download-txt");
const healthEl = document.getElementById("health");

let lastSource = { html: null, text: null };
let hasReview = false;
let inputHasFormatting = false;
let items = [];
let manualAdds = [];
let expandedGroups = new Set();
let reviewContext = {};

let llmCheckInFlight = false;

async function checkLlmStatus() {
  if (llmCheckInFlight || document.hidden) return;
  llmCheckInFlight = true;
  try {
    const res = await fetch("/api/health", { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const llm = data.llm || {};
    const disabled = llm.detail === "disabled";
    healthEl.textContent = llm.ready
      ? `LLM: ${llm.model || "available"}`
      : disabled ? "LLM: disabled" : "LLM: unavailable";
    healthEl.className = `health ${llm.ready ? "ok" : disabled ? "" : "err"}`;
    healthEl.title = llm.ready
      ? "LLM server lists an available model. Status refreshes every 15 seconds while this tab is visible."
      : disabled
        ? "LLM detection is disabled in the app configuration."
        : "Start your local LLM server and make a model available. Status refreshes every 15 seconds while this tab is visible.";
  } catch {
    healthEl.textContent = "LLM: status unknown";
    healthEl.className = "health err";
    healthEl.title = "Could not check LLM availability. The app will retry automatically.";
  } finally {
    llmCheckInFlight = false;
  }
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

function currentPayload() {
  // Browser-created div/br tags do not turn a plain-text paste into rich text.
  if (inputHasFormatting) return { html: editor.innerHTML, text: null };
  return { html: null, text: editor.innerText };
}

function updateReturnToReview() {
  const source = currentPayload();
  const changed = source.html !== lastSource.html || source.text !== lastSource.text;
  returnReviewBtn.hidden = !hasReview;
  returnReviewBtn.disabled = changed || analyzeBtn.disabled;
  reviewStaleHint.hidden = !hasReview || !changed;
}

function showStep(panel) {
  for (const step of [inputPanel, resultsPanel, finalPanel]) {
    step.hidden = step !== panel;
  }
  if (panel === inputPanel) updateReturnToReview();
  panel.querySelector("h2").focus({ preventScroll: true });
  window.scrollTo({ top: 0, behavior: "instant" });
}

async function analyze() {
  analyzeBtn.disabled = true;
  updateReturnToReview();
  clearBtn.disabled = true;
  editor.contentEditable = "false";
  inputWarnings.textContent = "";
  analyzeBtn.textContent = "Analyzing… (regex + spaCy + LLM)";
  try {
    const source = currentPayload();
    const res = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(source),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const result = await res.json();
    items = (result.findings || []).map((f) => ({
      ...f,
      // Plain input: findings have plain offsets; span resolution irrelevant.
      resolution: f.source_span === undefined ? "unknown" : f.source_span ? "yes" : "no",
      status: "pending",
      replacementValue: f.replacement ?? "",
    }));
    manualAdds = [];
    const skipped = (result.dropped || []).filter(f => (f.reason || "").includes("CSV"));
    const unique = new Map();
    [...(result.llm_unverified || []), ...skipped].forEach(u => {
      const key = JSON.stringify([u.quote, u.category]);
      if (!unique.has(key)) unique.set(key, { ...u, status: "pending", reasons: new Set() });
      unique.get(key).reasons.add(u.mapping_reason || u.reason || "Could not map automatically");
    });
    suggestions = [...unique.values()].map(u => ({ ...u, reason: [...u.reasons].join("; ") }));
    closeManualForm();
    manualQuoteEl.value = "";
    manualCategoryEl.value = "free_text";
    expandedGroups = new Set();
    reviewContext = result;
    lastSource = source;
    renderResults(result);
    hasReview = true;
    showStep(resultsPanel);
  } catch (err) {
    inputWarnings.textContent = `Analysis failed: ${err.message}`;
  } finally {
    analyzeBtn.disabled = false;
    clearBtn.disabled = false;
    editor.contentEditable = "true";
    analyzeBtn.textContent = "Analyze";
    updateReturnToReview();
  }
}

function buildGroups() {
  const groups = new Map();
  items.forEach((f, i) => {
    const key = JSON.stringify([f.category, f.quote, f.replacementValue || ""]);
    if (!groups.has(key)) {
      groups.set(key, {
        key,
        quote: f.quote,
        category: f.category,
        replacement: f.replacementValue,
        members: [],
        manualMembers: [],
      });
    }
    groups.get(key).members.push(i);
  });
  manualAdds.forEach((a, j) => {
    const key = JSON.stringify([a.category, a.quote, a.replacementValue || ""]);
    if (!groups.has(key)) {
      groups.set(key, {
        key,
        quote: a.quote,
        category: a.category,
        replacement: a.replacementValue,
        members: [],
        manualMembers: [],
      });
    }
    groups.get(key).manualMembers.push(j);
  });
  return [...groups.values()];
}

function groupStatus(group) {
  const statuses = group.members.map((i) => items[i].status);
  group.manualMembers.forEach(j => {
    for (let n = 0; n < manualAdds[j].count; n++) statuses.push(manualAdds[j].status);
  });
  if (!statuses.length) return "—";
  const counts = {};
  statuses.forEach((s) => { counts[s] = (counts[s] || 0) + 1; });
  const parts = Object.entries(counts).map(([s, n]) => `${n} ${s}`);
  if (Object.keys(counts).length === 1) return parts[0];
  return `mixed (${parts.join(", ")})`;
}

function updateReviewProgress() {
  const pending = items.filter(f => f.status === "pending").length;
  const unresolved = suggestions.filter(u => u.status === "pending").length;
  const invalid = [...items, ...manualAdds].some(f => f.status !== "rejected" && !f.replacementValue.trim());
  finalizeBtn.disabled = Boolean(pending || unresolved || invalid || !manualForm.hidden);
  document.getElementById("detected-count").textContent = pending ? `(${pending} pending)` : "(reviewed)";
  document.getElementById("manual-count").textContent = unresolved ? `(${unresolved} need a decision)` : "(reviewed)";
  reviewProgress.textContent = pending || unresolved
    ? `${pending ? `${pending} detected finding(s) still need approval or rejection.` : "Detected mappings reviewed."} ${unresolved} manual suggestion(s) still need a decision.`
    : invalid ? "Enter a replacement for each active mapping before finalizing."
    : !manualForm.hidden ? "Save or cancel the open manual mapping before finalizing."
    : "All detected mappings and manual suggestions reviewed. Ready to finalize.";
}

function renderResults(result) {
  updateReviewProgress();
  const unresolved = suggestions.filter(u => u.status === "pending").length;
  mappingBody.innerHTML = "";
  const groups = buildGroups();
  groups.forEach((g, gi) => {
    const count = g.members.length + g.manualMembers.reduce((n, j) => n + manualAdds[j].count, 0);
    const expanded = expandedGroups.has(g.key);
    const tr = document.createElement("tr");
    tr.id = `mapping-${gi}`;
    tr.mappingGroup = g;
    if ([...g.members.map(i => items[i]), ...g.manualMembers.map(j => manualAdds[j])].every(f => f.status === "rejected")) tr.className = "rejected";
    else if (g.members.some((i) => items[i].status === "pending")) tr.className = "needs-review";
    const summary = groupStatus(g);
    tr.innerHTML = `
      <td><button data-mact="toggle" data-gidx="${gi}" class="mini toggle">${expanded ? "▾" : "▸"}</button></td>
      <td class="value">${escapeHtml(g.quote)}</td>
      <td class="cat">${escapeHtml(g.category)}</td>
      <td class="value"><input class="group-repl repl" data-members="${g.members.join(",")}" data-manual-members="${g.manualMembers.join(",")}" aria-label="Replacement for ${escapeHtml(g.quote)}" value="${escapeHtml(g.replacement)}" /></td>
      <td>${count}</td>
      <td>${escapeHtml(summary)}</td>
      <td class="row-actions">
        <button data-mact="approve-all" data-gidx="${gi}" class="mini" aria-pressed="${[...g.members.map(i => items[i]), ...g.manualMembers.map(j => manualAdds[j])].every(f => f.status === "approved" || f.status === "edited")}">Approve all</button>
        <button data-mact="reject-all" data-gidx="${gi}" class="mini" aria-pressed="${[...g.members.map(i => items[i]), ...g.manualMembers.map(j => manualAdds[j])].every(f => f.status === "rejected")}">Reject all</button>
      </td>`;
    mappingBody.appendChild(tr);
    if (expanded) {
      const dtr = document.createElement("tr");
      dtr.className = "group-detail";
      const membersHtml = g.members.map((i) => {
        const f = items[i];
        const rowCls = f.status === "rejected" ? "rejected" : f.status === "pending" ? "needs-review" : "";
        return `<tr class="${rowCls}">
          <td>#${i + 1}</td>
          <td>${escapeHtml(f.source)}</td>
          <td class="conf">${f.confidence.toFixed(2)}</td>
          <td>${f.resolution}</td>
          <td><input class="repl" data-idx="${i}" value="${escapeHtml(f.replacementValue)}" ${f.status === "rejected" ? "disabled" : ""} /></td>
          <td>${escapeHtml(f.status)}</td>
          <td class="row-actions">
            <button data-act="approve" data-idx="${i}" class="mini" aria-pressed="${f.status === "approved" || f.status === "edited"}">Approve</button>
            <button data-act="reject" data-idx="${i}" class="mini" aria-pressed="${f.status === "rejected"}">Reject</button>
          </td>
        </tr>`;
      }).join("") + g.manualMembers.map(j => `<tr><td colspan="7"><span class="meta">Manual mapping · ${manualAdds[j].count} exact occurrence(s) · ${escapeHtml(manualAdds[j].status)} · uses the replacement above</span></td></tr>`).join("");
      dtr.innerHTML = `<td></td><td colspan="6"><table class="findings members">
        <thead><tr><th>#</th><th>Source</th><th>Conf</th><th>Resolves?</th><th>Replacement</th><th>Decision</th><th>Actions</th></tr></thead>
        <tbody>${membersHtml || '<tr><td colspan="7"><span class="meta">no members</span></td></tr>'}</tbody>
      </table></td>`;
      mappingBody.appendChild(dtr);
    }
  });
  const dropped = result.dropped || [];
  const csvSkipped = dropped.filter(f => (f.reason || "").includes("CSV"));
  const llmUnverified = result.llm_unverified || [];
  const count = llmUnverified.length + csvSkipped.length;
  document.getElementById("manual-summary").textContent = count
    ? `${csvSkipped.length ? "Analysis" : "Pass 2"} — ${count} suggestion(s) could not be mapped automatically${count !== suggestions.length ? ` (${suggestions.length} unique)` : ""}. Verify and add mappings as needed, or dismiss. ${unresolved} still need a decision.`
    : "No suggestions require manual verification. You can add a mapping for anything the scans missed.";
  unverifiedTable.hidden = !suggestions.length;
  unverifiedBody.innerHTML = "";
  suggestions.forEach((u, index) => {
    const tr = document.createElement("tr");
    const mapping = manualAdds.find(a => a.suggestionIds.includes(index) && a.status !== "rejected");
    const gi = mapping ? groups.findIndex(g => g.manualMembers.some(j => manualAdds[j] === mapping)) : -1;
    tr.innerHTML = `<td>${escapeHtml(u.quote)}</td><td class="cat">${escapeHtml(u.category)}</td><td>${escapeHtml(u.reason)}</td><td>${u.status === "mapped" ? `<a href="#mapping-${gi}">Mapping added</a>` : u.status === "dismissed" ? "Dismissed" : "Needs a decision"}</td><td class="row-actions">${u.status === "pending" ? `<button class="mini" data-suggestion="${index}" data-sact="add">Add Mapping</button><button class="mini secondary" data-suggestion="${index}" data-sact="dismiss">Dismiss</button>` : `<button class="mini secondary" data-suggestion="${index}" data-sact="reopen">Reopen</button>`}</td>`;
    unverifiedBody.appendChild(tr);
  });
  const warnings = [];
  if (result.llm_errors && result.llm_errors.length) warnings.push(`Pass 2 (LLM) errors: ${result.llm_errors.join("; ")}`);
  document.getElementById("analysis-details").hidden = dropped.length <= csvSkipped.length;
  document.getElementById("analysis-details-text").textContent = `${dropped.length - csvSkipped.length} overlapping detections skipped to avoid conflicting replacements.`;
  warningsEl.textContent = warnings.join(" ");
}

function applyItemAction(idx, act) {
  const item = items[idx];
  if (!item) return;
  if (act === "reject" && item.status !== "rejected") {
    item.status = "rejected";
  } else if (item.status === "rejected") {
    item.status = item.replacementValue !== item.replacement ? "edited" : "approved";
  } else {
    item.status = item.replacementValue !== item.replacement ? "edited" : "approved";
  }
}

function bindActions() {
  mappingBody.addEventListener("click", (event) => {
    const bulk = event.target.closest("button[data-mact]");
    if (bulk) {
      const g = bulk.closest("tr").mappingGroup;
      if (!g) return;
      if (bulk.dataset.mact === "toggle") {
        if (expandedGroups.has(g.key)) expandedGroups.delete(g.key);
        else expandedGroups.add(g.key);
      } else if (bulk.dataset.mact === "approve-all") {
        g.members.forEach(i => applyItemAction(i, "approve"));
        g.manualMembers.forEach(j => {
          manualAdds[j].status = "edited";
          manualAdds[j].suggestionIds.forEach(id => { suggestions[id].status = "mapped"; });
        });
      } else if (bulk.dataset.mact === "reject-all") {
        g.members.forEach((i) => { items[i].status = "rejected"; });
        g.manualMembers.forEach(j => {
          manualAdds[j].status = "rejected";
          manualAdds[j].suggestionIds.forEach(id => { suggestions[id].status = "pending"; });
        });
      }
      refreshTable();
      return;
    }
    const button = event.target.closest("button[data-act]");
    if (!button) return;
    applyItemAction(Number(button.dataset.idx), button.dataset.act);
    refreshTable();
  });
  mappingBody.addEventListener("input", (event) => {
    if (event.target.classList.contains("group-repl")) {
      const indices = value => value ? value.split(",").map(Number) : [];
      indices(event.target.dataset.members).forEach(i => {
        items[i].replacementValue = event.target.value;
        if (items[i].status !== "rejected") items[i].status = "edited";
      });
      indices(event.target.dataset.manualMembers).forEach(j => { manualAdds[j].replacementValue = event.target.value; });
      const row = event.target.closest("tr");
      row.mappingGroup.key = JSON.stringify([row.mappingGroup.category, row.mappingGroup.quote, event.target.value]);
      row.children[5].textContent = groupStatus(row.mappingGroup);
      updateReviewProgress();
      return;
    }
    if (event.target.classList.contains("repl")) {
      const idx = Number(event.target.dataset.idx);
      if (event.target.value !== items[idx].replacementValue) {
        items[idx].replacementValue = event.target.value;
        items[idx].status = "edited";
        event.target.closest("tr").children[5].textContent = "edited";
      }
      updateReviewProgress();
    }
  });
}

function refreshTable() {
  renderResults(reviewContext);
}

function collectDecisions() {
  const decisions = [];
  items.forEach((f) => {
    decisions.push({
      start: f.start,
      end: f.end,
      quote: f.quote,
      category: f.category,
      replacement: f.status === "edited" ? f.replacementValue : f.replacement,
      status: f.status,
      source: f.source,
    });
  });
  manualAdds
    .filter((a) => a.status !== "rejected")
    .forEach((a) => {
      decisions.push({
        start: null,
        end: null,
        quote: a.quote,
        category: a.category,
        replacement: a.replacementValue,
        status: a.status === "edited" ? "edited" : "approved",
        source: "manual",
      });
    });
  return decisions;
}

async function finalize() {
  refreshTable();
  if (finalizeBtn.disabled) {
    return;
  }
  finalizeBtn.disabled = true;
  backInputBtn.disabled = true;
  finalizeBtn.textContent = "Finalizing…";
  try {
    const res = await fetch("/api/finalize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...lastSource, decisions: collectDecisions() }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const result = await res.json();
    finalTxt.textContent = result.txt;
    finalHtml.srcdoc = result.html || "";
    finalWarnings.textContent = (result.warnings || []).concat(
      result.dropped && result.dropped.length ? [`${result.dropped.length} dropped`] : []
    ).join(" ") ||
      `Applied ${result.applied} replacement(s).`;
    const txtBlob = new Blob([result.txt], { type: "text/plain" });
    const htmlBlob = new Blob([result.html || ""], { type: "text/html" });
    copyFeedback.textContent = "";
    downloadTxt.href = URL.createObjectURL(txtBlob);
    downloadTxt.dataset.html = "";
    downloadTxt.dataset.htmlBlobUrl = URL.createObjectURL(htmlBlob);
    if (!result.html) copyHtmlBtn.disabled = true;
    else copyHtmlBtn.disabled = false;
    copyTxtBtn.dataset.txt = result.txt;
    copyHtmlBtn.dataset.html = result.html || "";
    showStep(finalPanel);
  } catch (err) {
    warningsEl.textContent = `Finalize failed: ${err.message}`;
  } finally {
    refreshTable();
    backInputBtn.disabled = false;
    finalizeBtn.textContent = "Finalize";
  }
}

function closeManualForm() {
  clearTimeout(previewTimer);
  previewVersion++;
  previewData = null;
  activeSuggestion = null;
  manualForm.hidden = true;
}

function openManualForm(index = null) {
  closeManualForm();
  activeSuggestion = index;
  manualForm.hidden = false;
  manualQuoteEl.value = index === null ? "" : suggestions[index].quote || "";
  manualCategoryEl.value = index === null ? "free_text" : suggestions[index].category;
  if (!manualCategoryEl.value) manualCategoryEl.value = "free_text";
  manualReplacementEl.value = "";
  replacementCustomized = false;
  manualError.textContent = "";
  updateManualPreview();
  refreshTable();
  manualForm.scrollIntoView({ behavior: "smooth", block: "center" });
  manualQuoteEl.focus({ preventScroll: true });
}

async function updateManualPreview() {
  const version = ++previewVersion;
  previewData = null;
  manualAddBtn.disabled = true;
  manualError.textContent = "";
  const quote = manualQuoteEl.value;
  const category = manualCategoryEl.value;
  const matches = document.getElementById("manual-matches");
  document.getElementById("manual-contexts").hidden = true;
  matches.textContent = quote ? "Checking exact occurrences…" : "Enter the exact text to preview its replacement and occurrences.";
  if (!quote) return;
  try {
    const res = await fetch("/api/mapping-preview", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...lastSource, quote, category }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (version !== previewVersion) return;
    previewData = { ...data, quote, category };
    if (!replacementCustomized) manualReplacementEl.value = data.replacement;
    matches.textContent = data.count
      ? `This mapping replaces all ${data.count} exact occurrence(s), including matches inside longer text. ${data.count > 20 ? "Showing the first 20 contexts." : "Inspect the contexts before saving."}`
      : "No exact occurrences found. Edit the source text to match the input.";
    document.getElementById("manual-contexts").hidden = !data.count;
    document.getElementById("manual-context-list").innerHTML = data.contexts.map(c => `<li>${escapeHtml(c)}</li>`).join("");
    manualAddBtn.disabled = !data.count || !manualReplacementEl.value.trim();
  } catch (err) {
    if (version !== previewVersion) return;
    matches.textContent = "";
    manualError.textContent = `Could not preview mapping: ${err.message}. Edit the source text or category to retry.`;
  }
}

function addManual(event) {
  event.preventDefault();
  if (!previewData?.count || previewData.quote !== manualQuoteEl.value || previewData.category !== manualCategoryEl.value || !manualReplacementEl.value.trim()) return;
  const quote = manualQuoteEl.value;
  const category = manualCategoryEl.value;
  const suggestionIds = suggestions.flatMap((u, i) =>
    i === activeSuggestion || (u.quote === quote && u.category === category) ? [i] : []);
  // Updating an existing mapping must not add a second all-occurrences decision.
  const existing = manualAdds.find(a => a.quote === quote);
  const mapping = existing || { quote, suggestionIds: [] };
  mapping.category = category;
  mapping.status = "edited";
  mapping.count = previewData.count;
  mapping.replacementValue = manualReplacementEl.value;
  mapping.suggestionIds = [...new Set([...mapping.suggestionIds, ...suggestionIds])];
  mapping.suggestionIds.forEach(i => { suggestions[i].status = "mapped"; });
  if (!existing) manualAdds.push(mapping);
  closeManualForm();
  refreshTable();
}

function resetWorkflow() {
  editor.innerHTML = "";
  lastSource = { html: null, text: null };
  hasReview = false;
  inputHasFormatting = false;
  items = [];
  manualAdds = [];
  suggestions = [];
  closeManualForm();
  expandedGroups = new Set();
  reviewContext = {};
  inputWarnings.textContent = "";
  manualQuoteEl.value = "";
  showStep(inputPanel);
  editor.focus({ preventScroll: true });
}

clearBtn.addEventListener("click", resetWorkflow);
editor.addEventListener("paste", (event) => {
  // Keep HTML only when the clipboard actually supplies rich content.
  if (!editor.innerText) inputHasFormatting = false;
  if (event.clipboardData?.getData("text/html")) inputHasFormatting = true;
});
editor.addEventListener("input", updateReturnToReview);
returnReviewBtn.addEventListener("click", () => {
  updateReturnToReview();
  if (hasReview && !returnReviewBtn.disabled) showStep(resultsPanel);
});
startOverBtn.addEventListener("click", resetWorkflow);
backInputBtn.addEventListener("click", () => showStep(inputPanel));
backReviewBtn.addEventListener("click", () => showStep(resultsPanel));
analyzeBtn.addEventListener("click", analyze);
finalizeBtn.addEventListener("click", finalize);
manualForm.addEventListener("submit", addManual);
document.getElementById("manual-new-btn").addEventListener("click", () => openManualForm());
document.getElementById("manual-cancel-btn").addEventListener("click", () => { closeManualForm(); refreshTable(); });
manualQuoteEl.addEventListener("input", () => {
  clearTimeout(previewTimer);
  previewVersion++;
  previewData = null;
  manualAddBtn.disabled = true;
  previewTimer = setTimeout(updateManualPreview, 250);
});
manualCategoryEl.addEventListener("change", () => { replacementCustomized = false; updateManualPreview(); });
manualReplacementEl.addEventListener("input", () => {
  replacementCustomized = true;
  manualAddBtn.disabled = !previewData?.count || !manualReplacementEl.value.trim();
});
unverifiedBody.addEventListener("click", event => {
  const button = event.target.closest("button[data-suggestion]");
  if (!button) return;
  const index = Number(button.dataset.suggestion);
  if (button.dataset.sact === "add") return openManualForm(index);
  if (button.dataset.sact === "dismiss") suggestions[index].status = "dismissed";
  else {
    const mapping = manualAdds.find(a => a.suggestionIds.includes(index) && a.status !== "rejected");
    if (mapping) {
      mapping.status = "rejected";
      mapping.suggestionIds.forEach(i => { suggestions[i].status = "pending"; });
    }
    suggestions[index].status = "pending";
  }
  refreshTable();
});
approveRemainingBtn.addEventListener("click", () => {
  items.forEach((f, i) => { if (f.status === "pending") applyItemAction(i, "approve"); });
  refreshTable();
});
rejectRemainingBtn.addEventListener("click", () => {
  items.forEach((f) => { if (f.status === "pending") f.status = "rejected"; });
  refreshTable();
});
async function copyOutput(button, text, label) {
  button.disabled = true;
  try {
    await navigator.clipboard.writeText(text);
    button.textContent = "Copied!";
    copyFeedback.textContent = `${label} copied to clipboard.`;
    setTimeout(() => { button.textContent = `Copy ${label}`; }, 1500);
  } catch {
    copyFeedback.textContent = "Copy failed. Select and copy the output manually, or use Download TXT.";
  } finally {
    button.disabled = false;
  }
}

copyTxtBtn.addEventListener("click", () => copyOutput(copyTxtBtn, copyTxtBtn.dataset.txt || "", "TXT"));
copyHtmlBtn.addEventListener("click", () => copyOutput(copyHtmlBtn, copyHtmlBtn.dataset.html || "", "HTML"));
document.addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button || button.disabled) return;
  button.classList.add("clicked");
  setTimeout(() => button.classList.remove("clicked"), 500);
}, { capture: true });
bindActions();
checkLlmStatus();
setInterval(checkLlmStatus, 15000);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) checkLlmStatus();
});
window.addEventListener("focus", checkLlmStatus);
