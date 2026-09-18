const editor = document.getElementById("editor");
const analyzeBtn = document.getElementById("analyze-btn");
const clearBtn = document.getElementById("clear-btn");
const resultsPanel = document.getElementById("results-panel");
const findingsBody = document.getElementById("findings-body");
const mappingBody = document.getElementById("mapping-body");
const warningsEl = document.getElementById("warnings");
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
const downloadTxt = document.getElementById("download-txt");
const healthEl = document.getElementById("health");

let lastSource = { html: null, text: null };
let items = [];
let manualAdds = [];
let expandedGroups = new Set();
const AUTO_APPROVE_CONF = 0.85;

async function checkHealth() {
  try {
    const res = await fetch("/api/health");
    const data = await res.json();
    const llm = data.llm || {};
    const llmBit = llm.ready ? ` · LLM: ${llm.model || "loaded"}` : " · LLM: offline";
    healthEl.textContent = (res.ok ? "ready" : "error") + llmBit;
    healthEl.className = `health ${res.ok ? "ok" : "err"}`;
  } catch {
    healthEl.textContent = "unreachable";
    healthEl.className = "health err";
  }
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

function currentPayload() {
  if (editor.querySelector("*")) return { html: editor.innerHTML, text: null };
  return { html: null, text: editor.innerText };
}

async function analyze() {
  analyzeBtn.disabled = true;
  analyzeBtn.textContent = "Analyzing… (regex + spaCy + LLM)";
  finalPanel.hidden = true;
  try {
    lastSource = currentPayload();
    const res = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(lastSource),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const result = await res.json();
    items = (result.findings || []).map((f) => ({
      ...f,
      // Plain input: findings have plain offsets; span resolution irrelevant.
      resolution: f.source_span === undefined ? "unknown" : f.source_span ? "yes" : "no",
      status: f.confidence >= AUTO_APPROVE_CONF && f.source !== "llm" ? "approved" : "pending",
      replacementValue: f.replacement ?? "",
    }));
    manualAdds = [];
    expandedGroups = new Set();
    manualQuoteEl.value = "";
    manualCategoryEl.value = "free_text";
    renderResults(result);
    resultsPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    warningsEl.textContent = `Analysis failed: ${err.message}`;
    resultsPanel.hidden = false;
  } finally {
    analyzeBtn.disabled = false;
    analyzeBtn.textContent = "Analyze (Pass 1)";
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
  findingsBody.innerHTML = "";
  items.forEach((f, i) => {
    const tr = document.createElement("tr");
    if (f.status === "pending") tr.className = "needs-review";
    if (f.status === "rejected") tr.className = "rejected";
    tr.innerHTML = `
      <td>${i + 1}</td>
      <td>${escapeHtml(f.quote)}</td>
      <td class="cat">${escapeHtml(f.category)}</td>
      <td><input class="repl" data-idx="${i}" value="${escapeHtml(f.replacementValue)}" ${f.status === "rejected" ? "disabled" : ""} /></td>
      <td>${escapeHtml(f.source)}</td>
      <td class="conf ${f.confidence < AUTO_APPROVE_CONF ? "low" : ""}">${f.confidence.toFixed(2)}</td>
      <td>${f.resolution}</td>
      <td>${escapeHtml(f.status)}</td>
      <td>
        <button data-act="approve" data-idx="${i}" class="mini">Approve</button>
        <button data-act="reject" data-idx="${i}" class="mini">Reject</button>
      </td>`;
    findingsBody.appendChild(tr);
  });
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
      <td>${escapeHtml(g.quote)}</td>
      <td class="cat">${escapeHtml(g.category)}</td>
      <td>${escapeHtml(g.replacement)}</td>
      <td>${count}</td>
      <td>${escapeHtml(summary)}</td>
      <td>
        <button data-mact="approve-all" data-gidx="${gi}" class="mini">Approve all</button>
        <button data-mact="reject-all" data-gidx="${gi}" class="mini">Reject all</button>
      </td>`;
    mappingBody.appendChild(tr);
    if (expanded) {
      const dtr = document.createElement("tr");
      dtr.className = "group-detail";
      const membersHtml = g.members.map((i) => {
        const f = items[i];
        return `<div class="member">
          <span>#${i + 1}</span>
          <span class="meta">conf ${f.confidence.toFixed(2)} · ${escapeHtml(f.source)} · ${escapeHtml(f.status)}</span>
          <span>
            <button data-act="approve" data-idx="${i}" class="mini">Approve</button>
            <button data-act="reject" data-idx="${i}" class="mini">Reject</button>
          </span>
        </div>`;
      }).join("") + g.manualMembers.map(() => `<div class="member"><span class="meta">manual entry — edit in Findings table</span></div>`).join("");
      dtr.innerHTML = `<td></td><td colspan="6"><div class="group-members">${membersHtml || '<div class="member"><span class="meta">no members</span></div>'}</div></td>`;
      mappingBody.appendChild(dtr);
    }
  });
  const unverified = result.llm_unverified || [];
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
  if (unverified.length) warnings.push(`Pass 2: ${unverified.length} finding(s) not mapped — approve below or add manually.`);
  if (result.dropped && result.dropped.length) warnings.push(`${result.dropped.length} overlapping finding(s) dropped — see table.`);
  warningsEl.textContent = warnings.join(" ");
  resultsPanel.hidden = false;
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
  findingsBody.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-act]");
    if (!button) return;
    applyItemAction(Number(button.dataset.idx), button.dataset.act);
    refreshTable();
  });
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
  findingsBody.addEventListener("change", (event) => {
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
  renderResults({
    llm_unverified: [],
    llm_errors: [],
    dropped: [],
  });
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
      status: f.status === "pending" ? "approved" : f.status,
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
  finalizeBtn.disabled = true;
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
    copyTxtBtn.dataset.confirm = "copied";
    downloadTxt.href = URL.createObjectURL(txtBlob);
    downloadTxt.dataset.html = "";
    downloadTxt.dataset.htmlBlobUrl = URL.createObjectURL(htmlBlob);
    if (!result.html) copyHtmlBtn.disabled = true;
    else copyHtmlBtn.disabled = false;
    copyTxtBtn.dataset.txt = result.txt;
    copyHtmlBtn.dataset.html = result.html || "";
    finalPanel.hidden = false;
    finalPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    finalWarnings.textContent = `Finalize failed: ${err.message}`;
    finalPanel.hidden = false;
  } finally {
    finalizeBtn.disabled = false;
    finalizeBtn.textContent = "Approve decisions & finalize";
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
  const plainMatches = plainText.split(quote).length - 1;
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

clearBtn.addEventListener("click", () => {
  editor.innerHTML = "";
  items = [];
  manualAdds = [];
  resultsPanel.hidden = true;
  finalPanel.hidden = true;
});
analyzeBtn.addEventListener("click", analyze);
finalizeBtn.addEventListener("click", finalize);
manualAddBtn.addEventListener("click", addManual);
copyTxtBtn.addEventListener("click", () => navigator.clipboard.writeText(copyTxtBtn.dataset.txt || ""));
copyHtmlBtn.addEventListener("click", () => navigator.clipboard.writeText(copyHtmlBtn.dataset.html || ""));
bindActions();
checkHealth();
