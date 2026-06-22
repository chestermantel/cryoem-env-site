#!/usr/bin/env python3
"""Generate site-styled per-run report pages under site/reports/ from the run artifacts.

For each run it reads run_meta.json (+ trajectory.json + decisions.json) and the observation
PNGs, copies the images into site/reports/<id>/, and emits site/reports/<id>.html rendered in
the website style (shared assets/site.css + site.js). Linked from the Rollouts cards.

Run it after collecting/grading new rollouts:
    python3 site/build_reports.py
Then `bin/publish-site` mirrors site/ (reports + images included) to the public Pages repo.
"""
import html
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # env repo root
SITE = ROOT / "site"
REPORTS = SITE / "reports"

# Which runs to publish as full reports. id -> site/reports/<id>.html (+ <id>/ for its images).
# Keep these ids in sync with the report links in rollouts.html.
RUNS = [
    dict(id="raw-realistic-exec-v2", dir="runs/agent/raw_tools/execute/realistic/v2",
         title="realistic · execute · v2", star=True),
    dict(id="raw-realistic-exec-v1", dir="runs/agent/raw_tools/execute/realistic/v1",
         title="realistic · execute · v1", star=False),
    dict(id="raw-realistic-build-v1", dir="runs/agent/raw_tools/build/realistic/v1",
         title="realistic · build-only · v1", star=False),
]

GOLDEN_NOTE = ("Golden reference: W1 by-hand ≈ 3.15 Å loose-mask GSFSC on the same 20-movie subset "
               "(published full-dataset T20S ≈ 2.9 Å). Resolution alone does not rank runs — see the grader.")


def esc(s):
    return html.escape("" if s is None else str(s))


def _load(p):
    try:
        return json.load(open(p))
    except Exception:
        return None


def meta_table(m):
    ip = m.get("input_prompt") or {}
    u = m.get("usage") or {}
    tok = (f"{u.get('input_tokens', 0):,} in · {u.get('output_tokens', 0):,} out"
           if m.get("usage_captured") else "not captured")
    rows = [
        ("Task / variant / phase",
         f"<code>raw_tools</code> · <code>{esc(m.get('variant'))}</code> · "
         f"<code>{esc(m.get('phase'))}</code> · run <code>{esc(m.get('run_id'))}</code>"),
        ("Run date", esc(m.get("date") or "—")),
        ("cryoSPARC project / workspace", f"{esc(m.get('project'))} / {esc(m.get('workspace'))}"),
        ("Model", f"<code>{esc(m.get('model'))}</code>"
                  + (f" · max_tokens/turn {m.get('max_tokens'):,}" if m.get("max_tokens") else "")),
    ]
    if m.get("phase") == "execute":
        rows.append(("Reached final map?", "✅ yes" if m.get("reached_map") else "❌ no"))
    rows += [
        ("Stop reason", esc(m.get("stop_reason"))),
        ("Jobs", esc(m.get("n_jobs"))),
        ("run_python blocks", esc(m.get("n_code_blocks"))),
        ("Agent turns", esc(m.get("turns"))),
        ("Wall-clock", f"{esc(m.get('wall_min'))} min"),
        ("Observation images", esc(m.get("images_sent"))),
        ("Token usage", tok),
        ("Input-prompt size",
         f"system {ip.get('system_chars', 0):,} + task {ip.get('task_chars', 0):,} chars"
         + (f" = {ip.get('prompt_tokens'):,} input tokens" if ip.get("prompt_tokens") else "")),
    ]
    body = "".join(f"<tr><td><b>{esc(k)}</b></td><td>{v}</td></tr>" for k, v in rows)
    return f"<table>{body}</table>"


def action_surface(asf):
    out = []
    for a in asf or []:
        params = "".join(
            f"<li><code>{esc(p.get('name'))}</code> ({esc(p.get('type'))}"
            f"{', required' if p.get('required') else ''}) — {esc(p.get('description', ''))}</li>"
            for p in a.get("params", []))
        out.append(f"<h3><code>{esc(a.get('name'))}</code></h3><p>{esc(a.get('description', ''))}</p>"
                   + (f"<ul>{params}</ul>" if params else ""))
    return "".join(out) or "<i>none recorded</i>"


def dag_table(dag):
    rows = []
    for r in dag or []:
        wiring = "; ".join(f"{g}←{su}.{og}" for g, su, og in r.get("inputs", [])) or "—"
        params = esc(json.dumps(r.get("params", {})))
        rows.append(
            f"<tr><td><code>{esc(r.get('uid'))}</code></td>"
            f"<td><b>{esc(r.get('type'))}</b><br>"
            f"<span style='color:var(--faint);font-size:12px'>{esc(r.get('title', ''))}</span></td>"
            f"<td style='font-size:12px'>{esc(wiring)}</td>"
            f"<td style='font-size:12px'>{esc(r.get('status'))}</td>"
            f"<td><details><summary>params</summary><pre>{params}</pre></details></td></tr>")
    return ("<table><tr><th>uid</th><th>type / title</th><th>inputs (wiring)</th>"
            "<th>status</th><th>params</th></tr>" + "".join(rows) + "</table>")


def code_blocks(cbs):
    out = []
    for i, c in enumerate(cbs or [], 1):
        op = "open" if i <= 2 else ""
        out.append(f"<details {op}><summary>run_python #{i} · {len(c):,} chars</summary>"
                   f"<pre>{esc(c)}</pre></details>")
    return "".join(out) or "<i>(no code blocks)</i>"


def traj_table(traj):
    rows = []
    for r in traj or []:
        t = r.get("tool", "?")
        if t == "_assistant":
            rows.append(f"<tr><td>{esc(r.get('turn'))}</td><td><i>reasoning</i></td>"
                        f"<td colspan=2>{esc(r.get('text', ''))[:1400]}</td></tr>")
        else:
            code = esc((r.get("input", {}) or {}).get("code", json.dumps(r.get("input", {}))))[:1200]
            txt = esc(r.get("text", ""))[:800]
            cls = " class='errrow'" if r.get("is_error") else ""
            rows.append(f"<tr{cls}><td>{esc(r.get('turn'))}</td><td><b>{esc(t)}</b></td>"
                        f"<td><pre style='font-size:11px;margin:0'>{code}</pre></td>"
                        f"<td style='font-size:12px'>{txt}</td></tr>")
    if not rows:
        return "<i>(no trajectory recorded)</i>"
    return ("<table><tr><th>turn</th><th>tool</th><th>code / input</th><th>result</th></tr>"
            + "".join(rows) + "</table>")


def build_one(run):
    rid = run["id"]
    rdir = ROOT / run["dir"]
    m = _load(rdir / "run_meta.json")
    if not m:
        print(f"  ! skip {rid}: no run_meta.json at {rdir}")
        return None
    traj = _load(rdir / "trajectory.json") or []
    dec = _load(rdir / "decisions.json") or {}

    # copy observation images into site/reports/<id>/
    out_img_dir = REPORTS / rid
    if out_img_dir.exists():
        shutil.rmtree(out_img_dir)
    pngs = sorted(rdir.glob("*.png"))
    img_html = ""
    if pngs:
        out_img_dir.mkdir(parents=True, exist_ok=True)
        for p in pngs:
            shutil.copy2(p, out_img_dir / p.name)
        img_html = "".join(
            f'<figure><img src="{rid}/{esc(p.name)}" loading="lazy">'
            f'<figcaption>{esc(p.name)}</figcaption></figure>' for p in pngs)
    else:
        img_html = "<p class='note'>No observation images were rendered for this run.</p>"

    ip = m.get("input_prompt") or {}
    phase = m.get("phase")
    summary = m.get("summary") or (dec.get("finish") or {}).get("summary") or ""
    badge = ("reached a final map" if m.get("reached_map")
             else ("build-only — nothing executed" if phase == "build" else "partial — no final map"))

    blurb = ("The agent drives the whole reconstruction by writing <code>cryosparc-tools</code> Python "
             "(<code>run_python</code>), given only a PI brief, the verbatim public tutorial, and public API "
             f"notes. This is the full run record: what it was given, the tools it had, and everything it "
             f"produced — its code, the DAG, the trajectory, and every observation image. ({esc(badge)}.)")

    sections = f"""
<a class="backlink" href="../rollouts.html">← all rollouts</a>
<h1>{esc(run['title'])}{' ★' if run.get('star') else ''}</h1>
<p class="subtitle">{blurb}</p>
<div class="docmeta">
  <span class="tag stage">raw cryosparc-tools · realistic</span>
  <span class="tag dot">{esc(m.get('date'))}</span>
</div>

<h2 id="metadata">1 · Run metadata</h2>
{meta_table(m)}

<h2 id="inputs">2 · Model inputs</h2>
<p>The model gets a static start prompt — a <i>system</i> prompt (role + how <code>run_python</code> works)
and a <i>task</i> message (the PI brief + the verbatim public tutorial + cryosparc-tools API notes). It is
<b>not</b> given the golden answer key or fitted thresholds; the inspection helpers are non-leaking.</p>
<details><summary><b>System prompt</b> ({ip.get('system_chars', 0):,} chars)</summary>
<pre>{esc(ip.get('system', ''))}</pre></details>
<details><summary><b>Task message</b> ({ip.get('task_chars', 0):,} chars — PI brief + verbatim tutorial + API notes)</summary>
<pre>{esc(ip.get('task_text', ''))}</pre></details>
<details><summary><b>Dataset / acquisition</b></summary>
<pre>{esc(json.dumps(m.get('dataset', {}), indent=2))}</pre></details>

<h2 id="surface">3 · Action surface</h2>
<p>Orchestration is a bounded streaming tool-use loop. The action surface is arbitrary code execution in a
persistent box-side namespace: the agent writes <code>cryosparc-tools</code> Python and the harness returns
stdout / the last expression / tracebacks / any images the inspection helpers emit.</p>
{action_surface(m.get('action_surface', []))}

<h2 id="outputs">4 · Outputs</h2>
<h3>Final-map resolution (GSFSC, Å){' / Guinier B-factor' if phase == 'execute' else ''}</h3>
<pre class="outputs-res">{esc(json.dumps(m.get('resolution', {}), indent=2)) or '—'}</pre>
<p class="note">{esc(GOLDEN_NOTE)}</p>
<h3>Agent summary</h3>
<blockquote>{esc(summary) or '<i>(see finish payload)</i>'}</blockquote>
<h3>Finish payload</h3>
<pre>{esc(json.dumps(m.get('finish', {}), indent=2))}</pre>
<h3>The DAG the agent authored ({esc(m.get('n_jobs'))} jobs · {esc(m.get('project'))} / {esc(m.get('workspace'))})</h3>
{dag_table(m.get('dag', []))}
<h3>The agent's code — every <code>run_python</code> block</h3>
{code_blocks(m.get('code_blocks', []))}
<h3>Trajectory — every tool call + the model's reasoning</h3>
{traj_table(traj)}
<h3>Observation images returned to the model ({len(pngs)})</h3>
{img_html}
"""

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Report — {esc(run['title'])}</title>
<link rel="stylesheet" href="../assets/site.css">
</head>
<body>
<div class="wrap">
  <aside class="side"><div class="brand">Report</div><div id="toc">
    <a class="toclink" href="../rollouts.html">← all rollouts</a>
    <a class="toclink" href="#metadata">1 · Run metadata</a>
    <a class="toclink" href="#inputs">2 · Model inputs</a>
    <a class="toclink" href="#surface">3 · Action surface</a>
    <a class="toclink" href="#outputs">4 · Outputs</a>
  </div></aside>
  <main><article class="report">{sections}</article></main>
</div>
<script src="../assets/site.js"></script>
<script>Site.nav('rollouts', '../');</script>
</body>
</html>
"""
    (REPORTS / f"{rid}.html").write_text(page, encoding="utf-8")
    return rid


def main():
    REPORTS.mkdir(parents=True, exist_ok=True)
    built = []
    for run in RUNS:
        rid = build_one(run)
        if rid:
            built.append(rid)
            print(f"  ✓ {rid}.html")
    print(f"Built {len(built)} report(s) under {REPORTS.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
