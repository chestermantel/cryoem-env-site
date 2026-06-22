#!/usr/bin/env python3
"""Generate site-styled per-run report pages under site/reports/ from the run artifacts.

For each run it reads run_meta.json (+ trajectory.json + decisions.json) and the observation
PNGs, copies the images into site/reports/<id>/, and emits site/reports/<id>.html rendered in
the website style (shared assets/site.css + site.js). Linked from the Rollouts cards.

Read-order is result-first: a 'Result at a glance' card, then run metadata, model inputs,
action surface, and outputs (resolution + summary, DAG, the full trajectory, images). Tables use
fixed column layout so long file paths can't starve the code column; the agent's code lives in
exactly one place (the trajectory), in a horizontal-scroll code box.

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


def recover_finish(m, dec):
    """The agent's free-text summary sometimes leaked into finish.resolution_note as a raw tool-call
    parameter block (the `summary` key ends up present-but-empty). Recover it for display: return
    (clean_finish_dict, summary_text). No-op when the marker is absent."""
    finish = dict(m.get("finish") or {})
    summary = (m.get("summary") or "").strip() or ((dec.get("finish") or {}).get("summary") or "").strip()
    note = finish.get("resolution_note") or ""
    marker = '<parameter name="summary">'
    if marker in note:
        pre, post = note.split(marker, 1)
        recovered = post.split("</parameter>")[0].strip()
        if recovered:
            summary = recovered
        finish["resolution_note"] = pre.split("</parameter>")[0].strip()
    return finish, summary


def _first_sentence(text):
    t = (text or "").strip()
    if not t:
        return ""
    nl = t.find("\n")                      # stop at the first line break (avoids running into a numbered list)
    if nl != -1:
        t = t[:nl].strip()
    s = t.split(". ")[0].strip()
    return s if s.endswith((".", ":")) else s + "."


def glance_card(m, summary, badge_cls, badge_txt):
    res = m.get("resolution") or {}
    loose = None
    if res:
        fin_uid = (m.get("finish") or {}).get("final_map_uid")
        d = res.get(fin_uid) or next(iter(res.values()))
        loose = (d or {}).get("radwn_loosemask_A")
    u = m.get("usage") or {}
    stats = []
    if loose:
        stats.append(("resolution", f"{loose:.2f} Å vs golden 3.15 Å"))
    stats += [("jobs", m.get("n_jobs")), ("run_python blocks", m.get("n_code_blocks")),
              ("turns", m.get("turns")), ("wall", f"{m.get('wall_min')} min")]
    if m.get("usage_captured"):
        stats.append(("tokens", f"{u.get('input_tokens', 0):,} in / {u.get('output_tokens', 0):,} out"))
    stats.append(("images", m.get("images_sent")))
    statline = "".join(f"<span>{esc(k)} <b>{v}</b></span>" for k, v in stats if v not in (None, ""))
    verdict = _first_sentence(summary)
    verdict_html = f'<p class="verdict">{esc(verdict)}</p>' if verdict else ""
    return (f'<section class="glance" id="glance">'
            f'<span class="badge {badge_cls}">{esc(badge_txt)}</span>'
            f'<div class="statline">{statline}</div>{verdict_html}</section>')


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
    return ('<table class="meta"><colgroup><col style="width:230px"><col></colgroup>'
            + body + "</table>")


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
        params = esc(json.dumps(r.get("params", {}), indent=2))     # pretty-print: one key per line
        rows.append(
            f"<tr><td><code>{esc(r.get('uid'))}</code></td>"
            f"<td><b>{esc(r.get('type'))}</b><br>"
            f"<span class='dag-title'>{esc(r.get('title', ''))}</span></td>"
            f"<td class='dag-meta'>{esc(wiring)}</td>"
            f"<td class='dag-meta'>{esc(r.get('status'))}</td>"
            f"<td><details><summary>params</summary><pre>{params}</pre></details></td></tr>")
    return ('<table class="dag">'
            '<colgroup><col style="width:64px"><col style="width:22%"><col style="width:30%">'
            '<col style="width:90px"><col></colgroup>'
            "<tr><th>uid</th><th>type / title</th><th>inputs (wiring)</th>"
            "<th>status</th><th>params</th></tr>" + "".join(rows) + "</table>")


def traj_table(traj):
    rows = []
    for r in traj or []:
        t = r.get("tool", "?")
        turn = esc(r.get("turn"))
        if t == "_assistant":
            rows.append(f"<tr><td>{turn}</td><td><i>reasoning</i></td>"
                        f"<td colspan=2>{esc(r.get('text', ''))}</td></tr>")
            continue
        code = (r.get("input", {}) or {}).get("code")
        code = code if code is not None else json.dumps(r.get("input", {}))
        txt = r.get("text", "") or ""
        # raise the result slice; show a visible marker only when content was actually cut
        shown = txt[:2000]
        trunc = (f'<span class="trunc">…(truncated, {len(txt):,} chars)</span>'
                 if len(txt) > 2000 else "")
        cls = " class='errrow'" if r.get("is_error") else ""
        rows.append(
            f"<tr{cls}><td>{turn}</td><td><b>{esc(t)}</b></td>"
            f"<td class='code'><div class='codecell'><pre>{esc(code)}</pre></div></td>"
            f"<td class='result'>{esc(shown)}{trunc}</td></tr>")
    if not rows:
        return "<i>(no trajectory recorded)</i>"
    return ('<table class="traj">'
            '<colgroup><col style="width:44px"><col style="width:96px"><col style="width:46%"><col></colgroup>'
            "<tr><th>turn</th><th>tool</th><th>code / input</th><th>result</th></tr>"
            + "".join(rows) + "</table>")


def task_inputs_html(task_text):
    """Split the (huge) task message into PI brief / API notes / verbatim tutorial on its stable
    '## Supplementary material —' headings, each in its own height-capped <details>. The ~51 KB
    verbatim tutorial is rendered last (most buried). Falls back to one capped block."""
    marker = "## Supplementary material —"
    idxs = [i for i in range(len(task_text)) if task_text.startswith(marker, i)]
    chars = len(task_text)
    if len(idxs) >= 2:
        pi = task_text[:idxs[0]].strip()
        tutorial = task_text[idxs[0]:idxs[1]].strip()
        api = task_text[idxs[1]:].strip()
        parts = [("PI brief", pi), ("cryosparc-tools API notes", api),
                 ("Verbatim public tutorial", tutorial)]
        inner = "".join(
            f"<details><summary>{esc(name)} ({len(body):,} chars)</summary><pre>{esc(body)}</pre></details>"
            for name, body in parts)
        return (f"<details><summary><b>Task message</b> ({chars:,} chars — PI brief + tutorial + API notes)"
                f"</summary>{inner}</details>")
    return (f"<details><summary><b>Task message</b> ({chars:,} chars)</summary>"
            f"<pre>{esc(task_text)}</pre></details>")


def build_one(run):
    rid = run["id"]
    rdir = ROOT / run["dir"]
    m = _load(rdir / "run_meta.json")
    if not m:
        print(f"  ! skip {rid}: no run_meta.json at {rdir}")
        return None
    traj = _load(rdir / "trajectory.json") or []
    dec = _load(rdir / "decisions.json") or {}
    finish, summary = recover_finish(m, dec)

    # copy observation images into site/reports/<id>/
    out_img_dir = REPORTS / rid
    if out_img_dir.exists():
        shutil.rmtree(out_img_dir)
    pngs = sorted(rdir.glob("*.png"))
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
    if m.get("reached_map"):
        badge_cls, badge_txt = "reached", "reached a final map"
    elif phase == "build":
        badge_cls, badge_txt = "build", "build-only — nothing executed"
    else:
        badge_cls, badge_txt = "partial", "partial — no final map"

    blurb = ("The agent drives the whole reconstruction by writing <code>cryosparc-tools</code> Python "
             "(<code>run_python</code>), given only a PI brief, the verbatim public tutorial, and public API "
             "notes. This is the full run record: what it was given, the tools it had, and everything it "
             "produced — its code, the DAG, the trajectory, and every observation image.")

    res = m.get("resolution") or {}
    res_html = esc(json.dumps(res, indent=2)) if res else "—"

    n_reason = sum(1 for r in traj if r.get("tool") == "_assistant")
    n_tool = sum(1 for r in traj if r.get("tool") not in ("_assistant", None))
    traj_summary = f"Trajectory — {len(traj)} rows ({n_tool} tool calls + {n_reason} reasoning)"

    sections = f"""
<a class="backlink" href="../rollouts.html">← all rollouts</a>
<h1>{esc(run['title'])}{' ★' if run.get('star') else ''}</h1>
<p class="subtitle">{blurb}</p>
<div class="docmeta">
  <span class="tag stage">raw cryosparc-tools · realistic</span>
  <span class="tag dot">{esc(m.get('date'))}</span>
</div>

{glance_card(m, summary, badge_cls, badge_txt)}

<h2 id="metadata">1 · Run metadata</h2>
{meta_table(m)}

<h2 id="inputs">2 · Model inputs</h2>
<p>The model gets a static start prompt — a <i>system</i> prompt (role + how <code>run_python</code> works)
and a <i>task</i> message (the PI brief + the verbatim public tutorial + cryosparc-tools API notes). It is
<b>not</b> given the golden answer key or fitted thresholds; the inspection helpers are non-leaking.</p>
<details><summary><b>System prompt</b> ({ip.get('system_chars', 0):,} chars)</summary>
<pre>{esc(ip.get('system', ''))}</pre></details>
{task_inputs_html(ip.get('task_text', ''))}
<details><summary><b>Dataset / acquisition</b></summary>
<pre>{esc(json.dumps(m.get('dataset', {}), indent=2))}</pre></details>

<h2 id="surface">3 · Action surface</h2>
<p>Orchestration is a bounded streaming tool-use loop. The action surface is arbitrary code execution in a
persistent box-side namespace: the agent writes <code>cryosparc-tools</code> Python and the harness returns
stdout / the last expression / tracebacks / any images the inspection helpers emit.</p>
{action_surface(m.get('action_surface', []))}

<h2 id="outputs">4 · Outputs</h2>
<h3 id="resolution">Result, resolution &amp; summary</h3>
<p><b>Final-map resolution (GSFSC, Å){' / Guinier B-factor' if phase == 'execute' else ''}</b></p>
<pre class="outputs-res">{res_html}</pre>
<p class="note">{esc(GOLDEN_NOTE)}</p>
<p><b>Agent summary</b></p>
<blockquote>{esc(summary) or '<i>(no summary recorded)</i>'}</blockquote>
<details><summary><b>Finish payload</b> (raw)</summary>
<pre>{esc(json.dumps(finish, indent=2))}</pre></details>

<h3 id="dag">The DAG the agent authored ({esc(m.get('n_jobs'))} jobs · {esc(m.get('project'))} / {esc(m.get('workspace'))})</h3>
{dag_table(m.get('dag', []))}

<h3 id="trajectory">Trajectory — every tool call + the model's reasoning</h3>
<p class="note">The agent's code lives here, in order, with each call's result. Code scrolls horizontally; long results are capped with a marker.</p>
<details><summary>{esc(traj_summary)}</summary>
{traj_table(traj)}</details>

<h3 id="images">Observation images returned to the model ({len(pngs)})</h3>
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
    <a class="toclink" href="#glance">0 · At a glance</a>
    <a class="toclink" href="#metadata">1 · Run metadata</a>
    <a class="toclink" href="#inputs">2 · Model inputs</a>
    <a class="toclink" href="#surface">3 · Action surface</a>
    <a class="toclink" href="#outputs">4 · Outputs</a>
    <a class="toclink sub" href="#resolution">· result &amp; summary</a>
    <a class="toclink sub" href="#dag">· DAG</a>
    <a class="toclink sub" href="#trajectory">· trajectory</a>
    <a class="toclink sub" href="#images">· images</a>
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
