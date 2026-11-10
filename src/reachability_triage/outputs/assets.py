"""`rt assets`: charts (PNG 1600px + SVG), an interactive Plotly page, diagrams, and screenshots.

Everything is drawn from eval/results/*.json and runs/, so it regenerates with no LLM calls.
Config colors were validated with the dataviz palette checker on the #0B0F17 surface (CVD WARN on the
blue/violet pair -> every series is also direct-labeled).
"""
from __future__ import annotations

import json
import shutil
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

from ..config import ASSETS, EVAL, ROOT, RUNS  # noqa: E402

BG, PANEL, BORDER, TEXT, MUTED, ACCENT = "#0B0F17", "#131A26", "#1F2937", "#E5E7EB", "#9CA3AF", "#A78BFA"
VERDICT = {"reachable": "#EF4444", "not_reachable": "#22C55E", "uncertain": "#F59E0B", "fixed": "#38BDF8"}
CONFIG_COLOR = {"full": "#8B5CF6", "no-retrieval": "#0284C7", "no-reflection": "#DB2777", "local": "#B45309"}
CONFIG_LABEL = {"full": "Full agent", "no-retrieval": "No retrieval", "no-reflection": "No reflection",
                "local": "Local Qwen2.5-Coder 14B"}
METRICS = [("false_suppression_rate", "False suppression ↓"), ("precision", "Precision"), ("recall", "Recall"),
           ("noise_reduction", "Noise reduction")]
CHARTS = ASSETS / "charts"


def _style():
    fam = "Inter" if any("Inter" in f.name for f in font_manager.fontManager.ttflist) else "DejaVu Sans"
    plt.rcParams.update({
        "figure.facecolor": BG, "axes.facecolor": BG, "savefig.facecolor": BG, "axes.edgecolor": BORDER,
        "axes.labelcolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED, "text.color": TEXT,
        "font.family": fam, "font.size": 15, "axes.titlesize": 17, "axes.titleweight": "bold",
        "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "axes.grid.axis": "y",
        "grid.color": BORDER, "grid.linewidth": 0.8, "legend.frameon": False, "legend.fontsize": 13,
        "svg.fonttype": "none",
    })


def _save(fig, name: str, title: str, subtitle: str = ""):
    fig.suptitle(title, x=0.02, ha="left", y=0.985, fontsize=22, fontweight="bold", color=TEXT)
    if subtitle:
        fig.text(0.02, 0.915, subtitle, ha="left", fontsize=13.5, color=MUTED)
    CHARTS.mkdir(parents=True, exist_ok=True)
    w = fig.get_size_inches()[0]
    fig.savefig(CHARTS / f"{name}.png", dpi=1600 / w)
    fig.savefig(CHARTS / f"{name}.svg")
    plt.close(fig)
    print(f"  chart {name}", file=sys.stderr)


def _pct(v):
    return "–" if v is None else f"{100 * v:.0f}%"


def _bars(ax, groups, configs, data, show_values=True):
    """Grouped bars with CI whiskers. data[config][metric] = (value, ci)."""
    n = len(configs)
    width = 0.8 / n
    for j, c in enumerate(configs):
        xs, ys, lo, hi = [], [], [], []
        for i, (m, _) in enumerate(groups):
            v, ci = data[c].get(m, (None, None))
            if v is None:
                continue
            x = i - 0.4 + width * (j + 0.5)
            xs.append(x)
            ys.append(100 * v)
            lo.append(100 * (v - ci[0]) if ci else 0)
            hi.append(100 * (ci[1] - v) if ci else 0)
        ax.bar(xs, ys, width * 0.92, color=CONFIG_COLOR[c], label=CONFIG_LABEL[c], zorder=3,
               edgecolor=BG, linewidth=2)
        ax.errorbar(xs, ys, yerr=[lo, hi], fmt="none", ecolor=TEXT, elinewidth=1.4, capsize=4, zorder=4, alpha=.8)
        if show_values:
            for x, y, h in zip(xs, ys, hi, strict=False):
                ax.text(x, y + h + 2, f"{y:.0f}", ha="center", va="bottom", fontsize=12, color=TEXT)
    ax.set_xticks(range(len(groups)), [g[1] for g in groups])
    ax.set_ylim(0, 112)
    ax.set_yticks([0, 25, 50, 75, 100], ["0", "25", "50", "75", "100%"])
    ax.tick_params(axis="x", length=0)


def _metric_data(res, configs, dataset):
    out = {}
    for c in configs:
        m = res["configs"].get(c, {}).get(dataset)
        out[c] = {k: (m[k], m.get(f"{k}_ci95")) for k, _ in METRICS} if m else {}
    return out


def chart_ablation(res):
    configs = [c for c in ("full", "no-retrieval", "no-reflection") if c in res["configs"]]
    if not configs:
        return
    sets = [d for d in ("bench-test", "real-eval") if any(res["configs"][c].get(d) for c in configs)]
    fig, axes = plt.subplots(1, len(sets), figsize=(16, 7.4), squeeze=False)
    for ax, d in zip(axes[0], sets, strict=False):
        _bars(ax, METRICS, configs, _metric_data(res, configs, d))
        m = res["configs"]["full"].get(d) or {}
        prov = " · provisional labels" if m.get("provisional") else ""
        ax.set_title(("Synthetic benchmark (test split)" if d == "bench-test" else "Real repos (50 findings)")
                     + f"  n={m.get('n', '?')}{prov}", loc="left", color=TEXT, pad=12)
    axes[0][0].legend(loc="upper left", bbox_to_anchor=(0, -0.08), ncol=3)
    full = res["configs"]["full"].get("bench-test") or {}
    take = []
    for c in configs[1:]:
        o = res["configs"][c].get("bench-test") or {}
        if o.get("accuracy") is not None and full.get("accuracy") is not None:
            take.append(f"{CONFIG_LABEL[c].lower()}: {100 * (o['accuracy'] - full['accuracy']):+.0f} pts accuracy")
    title = "What retrieval and reflection each add"
    fig.subplots_adjust(top=0.80, bottom=0.2, left=0.05, right=0.99, wspace=0.12)
    _save(fig, "ablation", title, "Benchmark ablation vs full agent — " + ("; ".join(take) or "see table")
          + ". Whiskers: 95% bootstrap CI.")


def chart_local(res):
    if "local" not in res["configs"]:
        return
    configs = ["full", "local"]
    d = "bench-test"
    fig, ax = plt.subplots(figsize=(14, 7.2))
    _bars(ax, METRICS, configs, _metric_data(res, configs, d))
    ax.legend(loc="upper left", bbox_to_anchor=(0, -0.08), ncol=2)
    f, l = res["configs"]["full"][d], res["configs"]["local"][d]
    fig.subplots_adjust(top=0.8, bottom=0.2, left=0.06, right=0.99)
    _save(fig, "local_vs_claude",
          f"A 14B local model: {_pct(l['accuracy'])} accurate vs Claude's {_pct(f['accuracy'])}",
          f"Synthetic benchmark test split (n={f['n']}), same graph, prompts and retrieval. "
          f"Local p50 {l['seconds_per_finding_p50']}s/finding vs {f['seconds_per_finding_p50']}s. Whiskers: 95% CI.")


def chart_retrieval(res):
    r = res.get("retrieval")
    if not r:
        return
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(16, 7), gridspec_kw={"width_ratios": [1.5, 1]})
    ks = [1, 3, 5, 10]
    styles = {"chroma": ("-", "o", ACCENT), "faiss": ("--", "s", "#0284C7")}
    for part in ("advisory", "code"):
        for store, (ls, mk, col) in styles.items():
            ys = [100 * r[part][store][f"recall@{k}"] for k in ks]
            # Chroma drawn wide underneath so it stays visible when FAISS lands on exactly the same values.
            a1.plot(ks, ys, ls, marker=mk, color=col, lw=6 if store == "chroma" else 2, ms=13 if store == "chroma" else 8,
                    alpha=.55 if store == "chroma" else 1, zorder=2 if store == "chroma" else 3,
                    markeredgecolor=BG, markeredgewidth=1.5)
        y1 = 100 * r[part]["chroma"]["recall@1"]
        a1.annotate(f"{part} index (n={r[part]['chroma']['n']})", (1, y1), xytext=(14, -4 if y1 > 80 else 0),
                    textcoords="offset points", fontsize=13, color=TEXT, va="top" if y1 > 80 else "center")
    a1.plot([], [], "-", marker="o", color=ACCENT, lw=6, alpha=.55, ms=13, label="Chroma (HNSW)")
    a1.plot([], [], "--", marker="s", color="#0284C7", label="FAISS (exact)")
    a1.set_xticks(ks, [f"k={k}" for k in ks])
    a1.set_xlim(0.6, 10.6)
    a1.set_ylim(0, 105)
    a1.set_ylabel("recall@k (%)")
    a1.legend(loc="lower right")
    a1.set_title("Right item in the top k", loc="left", pad=12)
    labels, vals, cols = [], [], []
    for part in ("advisory", "code"):
        for store in ("chroma", "faiss"):
            labels.append(f"{part}\n{store}")
            vals.append(r[part][store]["latency_ms_p50"])
            cols.append(styles[store][2])
    a2.bar(range(4), vals, 0.6, color=cols, zorder=3, edgecolor=BG, linewidth=2)
    for i, v in enumerate(vals):
        a2.text(i, v + max(vals) * 0.02, f"{v:.1f} ms", ha="center", va="bottom", fontsize=12)
    a2.set_xticks(range(4), labels)
    a2.set_title("Median query latency", loc="left", pad=12)
    a2.tick_params(axis="x", length=0)
    fig.subplots_adjust(top=0.8, bottom=0.14, left=0.06, right=0.98, wspace=0.18)
    code5 = r["code"]["chroma"]["recall@5"]
    adv5 = r["advisory"]["chroma"]["recall@5"]
    _save(fig, "retrieval", f"Retrieval finds the right advisory {_pct(adv5)} and the right code {_pct(code5)} of the time in the top 5",
          f"Same {r['embed_model']} embeddings in both stores: recall is identical; FAISS is faster unfiltered, "
          "Chroma faster with a metadata filter.")


def chart_cost(res):
    rows = []
    for c in ("full", "no-retrieval", "no-reflection", "local"):
        recs = [json.loads(p.read_text(encoding="utf-8")) for p in (RUNS / c).glob("*.json")] if (RUNS / c).exists() else []
        if recs:
            rows.append((c, recs))
    if not rows:
        return
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(16, 7))
    import random
    rng = random.Random(1)
    for i, (c, recs) in enumerate(rows):
        secs = [r["totals"]["seconds"] for r in recs]
        xs = [i + rng.uniform(-0.22, 0.22) for _ in secs]
        a1.scatter(xs, secs, s=40, color=CONFIG_COLOR[c], alpha=.75, edgecolors=BG, linewidths=1.2, zorder=3)
        med = sorted(secs)[len(secs) // 2]
        a1.plot([i - 0.32, i + 0.32], [med, med], color=TEXT, lw=2.5, zorder=4)
        a1.text(i + 0.36, med, f"{med:.0f}s", va="center", fontsize=12)
        tin = sum(r["totals"]["tokens_in"] for r in recs) / len(recs)
        tout = sum(r["totals"]["tokens_out"] for r in recs) / len(recs)
        a2.bar(i, tin / 1000, 0.6, color=CONFIG_COLOR[c], zorder=3, edgecolor=BG, linewidth=2)
        a2.bar(i, tout / 1000, 0.6, bottom=tin / 1000, color=CONFIG_COLOR[c], alpha=.45, zorder=3, edgecolor=BG, linewidth=2)
        cost = sum(r["totals"]["cost_usd_est"] for r in recs) / len(recs)
        a2.text(i, (tin + tout) / 1000 + 0.3, f"{(tin + tout) / 1000:.1f}k\n${cost:.3f}" if c != "local" else
                f"{(tin + tout) / 1000:.1f}k\nlocal", ha="center", va="bottom", fontsize=12)
    names = [CONFIG_LABEL[c].replace(" ", "\n", 1) for c, _ in rows]
    a1.set_xticks(range(len(rows)), names)
    a2.set_xticks(range(len(rows)), names)
    a1.set_ylabel("seconds per finding")
    a2.set_ylabel("tokens per finding (thousands)")
    a1.set_title("Latency per finding (line = median)", loc="left", pad=12)
    a2.set_title("Tokens per finding (solid in, light out)", loc="left", pad=12)
    for a in (a1, a2):
        a.tick_params(axis="x", length=0)
    a2.set_ylim(0, max(sum(r["totals"]["tokens_in"] + r["totals"]["tokens_out"] for r in recs) / len(recs)
                       for _, recs in rows) / 1000 * 1.3)
    fig.subplots_adjust(top=0.8, bottom=0.16, left=0.06, right=0.98, wspace=0.2)
    full = dict(rows).get("full")
    title = "What one triage costs"
    if full:
        med = sorted(r["totals"]["seconds"] for r in full)[len(full) // 2]
        cost = sum(r["totals"]["cost_usd_est"] for r in full) / len(full)
        title = f"About {med:.0f} seconds and ~${cost:.2f} (API-price estimate) per finding"
    _save(fig, "cost_latency", title, "All findings each config ran on. Cost = published API list price × tokens; "
          "runs actually used a Claude subscription.")


def chart_funnel(res):
    rem = res.get("remediation")
    full = res["configs"].get("full", {}).get("real-eval")
    if not rem:
        return
    reach = full["predictions"].get("reachable", 0) if full else rem["attempted"]
    stages = [("Marked reachable (real set)", reach, VERDICT["reachable"]),
              ("Remediation attempted (cap 10)", rem["attempted"], ACCENT),
              ("Failing test written (red)", rem["failing_test_written"], "#DB2777"),
              ("Fixed: test green, suite intact", rem["fixed"], VERDICT["fixed"])]
    fig, ax = plt.subplots(figsize=(14, 6.4))
    mx = max(s[1] for s in stages) or 1
    for i, (_name, v, col) in enumerate(stages):
        ax.barh(len(stages) - 1 - i, v, 0.62, color=col, zorder=3, edgecolor=BG, linewidth=2)
        ax.text(v + mx * 0.015, len(stages) - 1 - i, str(v), va="center", fontsize=16, fontweight="bold")
    ax.set_yticks(range(len(stages)), [s[0] for s in reversed(stages)])
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", visible=True)
    ax.set_xlim(0, mx * 1.15)
    ax.tick_params(axis="y", length=0)
    fig.subplots_adjust(top=0.78, bottom=0.1, left=0.27, right=0.97)
    _save(fig, "remediation_funnel",
          f"{rem['fixed']} of {rem['attempted']} attempted fixes went red → green with the suite intact",
          "Test-first: a fix is accepted only if a new test fails before it, passes after it, and no existing test "
          f"breaks. Failures: {', '.join(f'{k} ({v})' for k, v in rem['failure_reasons'].items()) or 'none'}.")


def plotly_page(res):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    configs = [c for c in ("full", "no-retrieval", "no-reflection", "local") if c in res["configs"]]
    sets = [d for d in ("bench-test", "real-eval") if any(res["configs"][c].get(d) for c in configs)]
    fig = make_subplots(rows=1, cols=len(sets), subplot_titles=[
        "Synthetic benchmark (test split)" if d == "bench-test" else "Real repos (provisional labels)" for d in sets],
        shared_yaxes=True)
    for j, d in enumerate(sets, 1):
        for c in configs:
            m = res["configs"][c].get(d)
            if not m:
                continue
            ys = [100 * (m[k] or 0) for k, _ in METRICS]
            err_hi = [100 * ((m.get(f"{k}_ci95") or [0, m[k] or 0])[1] - (m[k] or 0)) for k, _ in METRICS]
            err_lo = [100 * ((m[k] or 0) - (m.get(f"{k}_ci95") or [m[k] or 0, 0])[0]) for k, _ in METRICS]
            fig.add_trace(go.Bar(name=CONFIG_LABEL[c], x=[n for _, n in METRICS], y=ys, marker_color=CONFIG_COLOR[c],
                                 error_y={"type": "data", "array": err_hi, "arrayminus": err_lo, "color": TEXT},
                                 legendgroup=c, showlegend=j == 1,
                                 hovertemplate=f"{CONFIG_LABEL[c]}<br>%{{x}}: %{{y:.0f}}%<br>n={m['n']}<extra></extra>"),
                          row=1, col=j)
    fig.update_layout(template="plotly_dark", paper_bgcolor=BG, plot_bgcolor=BG, barmode="group",
                      font={"family": "Inter, system-ui, sans-serif", "color": TEXT, "size": 14},
                      title={"text": "Sieve — ablations with 95% bootstrap CIs (hover for values)", "x": 0.01},
                      legend={"orientation": "h", "y": -0.15}, height=560, margin={"t": 90, "l": 50, "r": 20})
    fig.update_yaxes(range=[0, 110], gridcolor=BORDER, ticksuffix="%")
    fig.write_html(CHARTS / "interactive.html", include_plotlyjs="cdn", full_html=True)
    print("  chart interactive.html", file=sys.stderr)


# ------------------------------------------------------------------ diagrams

MERMAID_THEME = {"theme": "base", "themeVariables": {
    "background": BG, "primaryColor": PANEL, "primaryTextColor": TEXT, "primaryBorderColor": ACCENT,
    "lineColor": MUTED, "secondaryColor": PANEL, "tertiaryColor": PANEL, "fontFamily": "Inter, sans-serif",
    "fontSize": "18px", "edgeLabelBackground": BG}}


def graph_mermaid() -> str:
    from ..agent.graph import build_graph
    from ..agent.providers import MockProvider
    return build_graph(MockProvider()).get_graph().draw_mermaid()


ARCH = """flowchart TD
    A[OSV-Scanner finding]:::io -->|1. load finding| B[Retrieve advisory · Chroma]
    B -->|2. vulnerable symbols + fixed version| C[Static evidence · imports and call sites]
    C -->|3. matching code locations| D[Retrieve code context · Chroma]
    D -->|4. code snippets + call paths| E[Reachability verdict · LLM]:::llm
    E -->|5. verdict + evidence| F[Self-reflection · LLM critique]:::llm
    F -->|weak evidence, retry once| E
    F -->|not reachable| G[Suppress with evidence]:::nr
    F -->|uncertain| H[Flag for human]:::unc
    F -->|reachable| I[Write failing test · LLM]:::r
    I -->|6. run test, must be red| J[Apply fix · upgrade or patch]
    J -->|7. run new test + full suite| K{Red to green and suite green?}
    K -->|yes| L[Accept fix + diff]:::fixed
    K -->|no, retry up to 2x| J
    K -->|still failing| H
    G --> M[(runs/ JSON cache)]
    H --> M
    L --> M
    M -->|build| N[Case explorer + charts]:::io
    classDef llm stroke:#A78BFA,stroke-width:2px
    classDef r stroke:#EF4444,stroke-width:2px
    classDef nr stroke:#22C55E,stroke-width:2px
    classDef unc stroke:#F59E0B,stroke-width:2px
    classDef fixed stroke:#38BDF8,stroke-width:2px
    classDef io stroke:#9CA3AF,stroke-dasharray:4 3
"""


NODE_NAMES = {"__start__": "OSV-Scanner finding", "__end__": "run record → runs/", "load_finding": "load finding",
              "retrieve_advisory": "retrieve advisory · Chroma", "static_evidence": "static evidence · AST",
              "retrieve_code": "retrieve code context · Chroma", "verdict": "reachability verdict · LLM",
              "reflect": "self-reflection · LLM", "decide": "route: suppress / flag / remediate"}


def _restyle_graph(mm: str) -> str:
    import re
    lines = []
    for l in mm.splitlines():
        if l.strip().startswith(("classDef", "%%{init")):
            continue
        m = re.match(r"^(\s*)(\w+)(\(\[|\()(.*?)(\]\)|\))(:::\w+)?;?\s*$", l)
        if m and m.group(2) in NODE_NAMES:
            l = f'{m.group(1)}{m.group(2)}{m.group(3)}"{NODE_NAMES[m.group(2)]}"{m.group(5)}{m.group(6) or ""}'
        lines.append(l)
    lines += ["    classDef default fill:#131A26,stroke:#A78BFA,color:#E5E7EB,stroke-width:1.5px",
              "    classDef first fill:#131A26,stroke:#9CA3AF,color:#E5E7EB,stroke-dasharray:4 3",
              "    classDef last fill:#131A26,stroke:#38BDF8,color:#E5E7EB,stroke-width:2px"]
    return "\n".join(lines) + "\n"


def _mermaid_html(src: str) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap" rel="stylesheet">
<style>html,body{{margin:0;background:{BG};}} #d{{display:inline-block;padding:32px;background:{BG}}}</style>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"></script></head>
<body><div id="d"><pre class="mermaid">{src}</pre></div>
<script>mermaid.initialize(Object.assign({{startOnLoad:false}}, {json.dumps(MERMAID_THEME)}));
// measure text only after Inter has loaded, or node labels get clipped
document.fonts.load("18px Inter").then(() => document.fonts.ready).then(() => mermaid.run());</script></body></html>"""


def diagrams():
    out = ASSETS / "diagram"
    out.mkdir(parents=True, exist_ok=True)
    g = _restyle_graph(graph_mermaid())
    (out / "langgraph.mmd").write_text(g, encoding="utf-8", newline="\n")
    (out / "architecture.mmd").write_text(ARCH, encoding="utf-8", newline="\n")
    for name, src in (("langgraph", g), ("architecture", ARCH)):
        (out / f"{name}.html").write_text(_mermaid_html(src), encoding="utf-8", newline="\n")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch()
            page = b.new_page(device_scale_factor=2)
            for name in ("langgraph", "architecture"):
                page.goto((out / f"{name}.html").as_uri())
                page.wait_for_selector("#d svg", timeout=20000)
                el = page.query_selector("#d")
                el.screenshot(path=str(out / f"{name}.png"))
                svg = page.eval_on_selector("#d svg", "e => e.outerHTML")
                (out / f"{name}.svg").write_text(svg, encoding="utf-8", newline="\n")
                print(f"  diagram {name}", file=sys.stderr)
            b.close()
    except Exception as e:  # diagrams still exist as .mmd/.html
        print(f"  diagrams: rendering skipped ({e})", file=sys.stderr)


def logo():
    src = ROOT / "site" / "logo.svg"
    if src.exists():
        (ASSETS / "logo.svg").write_bytes(src.read_bytes())


def build_assets(screenshots: bool = True) -> None:
    _style()
    res = json.loads((EVAL / "results" / "results.json").read_text(encoding="utf-8"))
    if CHARTS.exists():
        shutil.rmtree(CHARTS)
    chart_ablation(res)
    chart_local(res)
    chart_retrieval(res)
    chart_cost(res)
    chart_funnel(res)
    plotly_page(res)
    diagrams()
    logo()
    if screenshots:
        from .screenshots import take_screenshots
        take_screenshots()
