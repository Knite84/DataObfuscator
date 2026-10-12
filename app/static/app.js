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
    manualQuoteEl.value = "";
    manualCategoryEl.value = "free_text";
    expandedGroups = new Set();
    reviewContext = result;
    renderResults(result);
    lastSource = source;
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
        replacement: f.status === "edited" ? f.replacementValue : f.replacementValue || "[pending]",
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
        replacement: a.replacementValue || "[pending]",
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
  group.manualMembers.forEach(() => statuses.push("approved"));
  if (!statuses.length) return "—";
  const counts = {};
  statuses.forEach((s) => { counts[s] = (counts[s] || 0) + 1; });
  const parts = Object.entries(counts).map(([s, n]) => `${n} ${s}`);
  if (Object.keys(counts).length === 1) return parts[0];
  return `mixed (${parts.join(", ")})`;
}

function renderResults(result) {
  const pending = items.filter(f => f.status === "pending").length;
  reviewProgress.textContent = pending
    ? `${pending} finding(s) still need approval or rejection before finalizing.`
    : "All findings reviewed. Ready to finalize.";
  mappingBody.innerHTML = "";
  const groups = buildGroups();
  groups.forEach((g, gi) => {
    const count = g.members.length + g.manualMembers.length;
    const expanded = expandedGroups.has(g.key);
    const tr = document.createElement("tr");
    if (g.members.length && g.members.every((i) => items[i].status === "rejected")) tr.className = "rejected";
    else if (g.members.some((i) => items[i].status === "pending")) tr.className = "needs-review";
    const summary = groupStatus(g);
    tr.innerHTML = `
      <td><button data-mact="toggle" data-gidx="${gi}" class="mini toggle">${expanded ? "▾" : "▸"}</button></td>
      <td class="value">${escapeHtml(g.quote)}</td>
      <td class="cat">${escapeHtml(g.category)}</td>
      <td class="value">${escapeHtml(g.replacement)}</td>
      <td>${count}</td>
      <td>${escapeHtml(summary)}</td>
      <td class="row-actions">
        <button data-mact="approve-all" data-gidx="${gi}" class="mini" aria-pressed="${g.members.length > 0 && g.members.every(i => items[i].status === "approved" || items[i].status === "edited")}">Approve all</button>
        <button data-mact="reject-all" data-gidx="${gi}" class="mini" aria-pressed="${g.members.length > 0 && g.members.every(i => items[i].status === "rejected")}">Reject all</button>
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
      }).join("") + g.manualMembers.map(() => `<tr><td colspan="7"><span class="meta">manual entry — uses the group replacement on finalize</span></td></tr>`).join("");
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
  const unverified = llmUnverified.concat(csvSkipped);
  unverifiedHeading.textContent = csvSkipped.length
    ? "Findings requiring manual review"
    : "Pass 2 — not resolvable to exact text";
  unverifiedHeading.hidden = !unverified.length;
  unverifiedTable.hidden = !unverified.length;
  unverifiedBody.innerHTML = "";
  unverified.forEach((u) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${escapeHtml(u.quote)}</td><td class="cat">${escapeHtml(u.category)}</td><td>${escapeHtml(u.reason || u.mapping_reason || "")}</td>`;
    unverifiedBody.appendChild(tr);
  });
  const warnings = [];
  if (result.llm_errors && result.llm_errors.length) warnings.push(`Pass 2 (LLM) errors: ${result.llm_errors.join("; ")}`);
  if (llmUnverified.length) warnings.push(`Pass 2: ${llmUnverified.length} finding(s) not mapped — add manually if verified.`);
  if (csvSkipped.length) warnings.push(`${csvSkipped.length} finding(s) crossed CSV field boundaries or escaped quotes and were skipped. Add the exact text manually if needed.`);
  if (dropped.length > csvSkipped.length) warnings.push(`${dropped.length - csvSkipped.length} overlapping finding(s) dropped.`);
  warningsEl.textContent = warnings.join(" ");
}

function applyItemAction(idx, act) {
  const item = items[idx];
  if (!item) return;
  if (act === "reject" && item.status !== "rejected") {
    item.status = "rejected";
  } else if (item.status === "rejected") {
    item.status = "approved";
  } else {
    item.status = "approved";
  }
}

function bindActions() {
  mappingBody.addEventListener("click", (event) => {
    const bulk = event.target.closest("button[data-mact]");
    if (bulk) {
      const groups = buildGroups();
      const g = groups[Number(bulk.dataset.gidx)];
      if (!g) return;
      if (bulk.dataset.mact === "toggle") {
        if (expandedGroups.has(g.key)) expandedGroups.delete(g.key);
        else expandedGroups.add(g.key);
      } else if (bulk.dataset.mact === "approve-all") {
        g.members.forEach((i) => { items[i].status = "approved"; });
      } else if (bulk.dataset.mact === "reject-all") {
        g.members.forEach((i) => { items[i].status = "rejected"; });
      }
      refreshTable();
      return;
    }
    const button = event.target.closest("button[data-act]");
    if (!button) return;
    applyItemAction(Number(button.dataset.idx), button.dataset.act);
    refreshTable();
  });
  mappingBody.addEventListener("change", (event) => {
    if (event.target.classList.contains("repl")) {
      const idx = Number(event.target.dataset.idx);
      if (event.target.value !== items[idx].replacementValue) {
        items[idx].replacementValue = event.target.value;
        items[idx].status = "edited";
      }
      refreshTable();
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
        replacement: a.status === "edited" ? a.replacementValue : null,
        status: a.status === "edited" ? "edited" : "approved",
        source: "manual",
      });
    });
  return decisions;
}

async function finalize() {
  if (items.some(f => f.status === "pending") || manualAdds.some(f => f.status === "pending")) {
    warningsEl.textContent = "Approve or reject all pending findings before finalizing. You can use Approve remaining or Reject remaining.";
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
    finalizeBtn.disabled = false;
    backInputBtn.disabled = false;
    finalizeBtn.textContent = "Finalize";
  }
}

async function addManual() {
  const quote = manualQuoteEl.value.trim();
  if (!quote) return;
  const res = await fetch("/api/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(lastSource),
  });
  const plainPayload = await res.json().catch(() => null);
  const plainText = plainPayload && plainPayload.plain_text ? plainPayload.plain_text : "";
  const plainMatches = plainPayload?.csv_values
    ? plainPayload.csv_values.reduce((count, value) => count + value.split(quote).length - 1, 0)
    : plainText.split(quote).length - 1;
  if (plainMatches === 0) {
    warningsEl.textContent = `Manual quote not found verbatim in the text: ${JSON.stringify(quote)}`;
    return;
  }
  manualAdds.push({
    quote,
    category: manualCategoryEl.value,
    status: "approved",
    replacementValue: null, // server computes the deterministic default
  });
  manualQuoteEl.value = "";
  refreshTable();
}

function resetWorkflow() {
  editor.innerHTML = "";
  lastSource = { html: null, text: null };
  hasReview = false;
  inputHasFormatting = false;
  items = [];
  manualAdds = [];
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
manualAddBtn.addEventListener("click", addManual);
approveRemainingBtn.addEventListener("click", () => {
  items.forEach((f) => { if (f.status === "pending") f.status = "approved"; });
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
