// Shared helpers for the Sieve case explorer (no build step, works from file:// too).
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const pct = v => v == null ? "–" : `${Math.round(100 * v)}%`;
const ciTxt = ci => ci ? `95% CI ${Math.round(100 * ci[0])}–${Math.round(100 * ci[1])}%` : "";
const LABEL = { reachable: "reachable", not_reachable: "not reachable", uncertain: "uncertain", fixed: "fixed" };
const pill = v => v ? `<span class="pill v-${v}">${LABEL[v] || v}</span>` : `<span class="pill v-none">n/a</span>`;
const CONFIG = { full: "Full agent", "no-retrieval": "No retrieval", "no-reflection": "No reflection", local: "Local 14B" };

function nav(active) {
  const links = [["index.html", "Overview", "overview"], ["findings.html", "Findings", "findings"]];
  document.body.insertAdjacentHTML("afterbegin", `
  <div class="nav"><div class="wrap">
    <a class="brand" href="index.html"><img src="logo.svg" alt="">Sieve</a>
    ${links.map(([h, t, k]) => `<a class="link ${k === active ? "on" : ""}" href="${h}">${t}</a>`).join("")}
    <span style="flex:1"></span>
    <span class="muted" style="font-size:13px">reachability triage for dependency vulns</span>
  </div></div>`);
}

function loadScript(src) {
  return new Promise((ok, bad) => { const s = document.createElement("script"); s.src = src; s.onload = ok; s.onerror = bad; document.head.appendChild(s); });
}
