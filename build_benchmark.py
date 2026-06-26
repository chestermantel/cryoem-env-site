#!/usr/bin/env python3
"""build_benchmark.py — LINKAGE between the grade artifacts and the website's Benchmark page.

The grader writes full per-run grade rows to `runs/agent/grader/grades.json` (the latest grading run) and a
canonical multi-run snapshot lives in `runs/agent/grader/scorecard.json`. This script reads those cards,
keeps a cumulative store of every run ever graded, and regenerates the two scrolling "master" tables on
`site/benchmark.html` (Demo runs + Complete list) from that store. Nothing on the page is hand-transcribed.

WORKFLOW (push a new run or a new grade to the site):
  1. Grade the run as usual  ->  it lands in runs/agent/grader/grades.json
  2. python3 site/build_benchmark.py            # ingest the new grade, rebuild the tables
  3. bin/publish-site                            # push to the public site
  ( or `python3 site/build_benchmark.py --publish` to do 2+3 in one step ;
    `bin/build-benchmark [--publish]` is the thin wrapper. )

WHAT'S DATA vs. WHAT'S CONFIG:
  - The NUMBERS come straight from the grade JSONs (rows[<id>] = normalized subscores + _raw factors;
    outcomes[<id>] = raw measured scalars). Add a run to the grader and it shows up here automatically.
  - The ROSTER (`site/benchmark_roster.json`) is the only thing you edit by hand: which runs are public
    "Demo runs" and their display names, plus the not-yet-run placeholders. Every graded run also appears
    in "Complete list" with no config needed.

The cumulative store (`runs/agent/grader/site_grades.json`) survives grades.json being overwritten by the
next grading run: each build merges the configured `ingest` cards into it (newest wins per run id).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SITE = REPO / "site"
ROSTER = SITE / "benchmark_roster.json"
PAGE = SITE / "benchmark.html"

# ---- number formatting (one place, so the page is internally consistent) -------------------------
def f2(x):  return "—" if x is None else f"{float(x):.2f}"
def f3(x):  return "—" if x is None else f"{float(x):.3f}"


def _g(d, *path, default=None):
    """Nested get across dicts and lists: _g(R, 'a', 'b', 0) -> R['a']['b'][0] or default.
    (Subscores are stored as [value, weight] lists, so the final step often indexes a list.)"""
    cur = d
    for k in path:
        if isinstance(cur, dict):
            if k not in cur:
                return default
            cur = cur[k]
        elif isinstance(cur, (list, tuple)):
            if not isinstance(k, int) or not (-len(cur) <= k < len(cur)):
                return default
            cur = cur[k]
        else:
            return default
    return cur


# ===================================================================================================
# Cumulative store — merge the configured grade cards, newest wins per run id.
# ===================================================================================================
def build_store(roster: dict) -> dict:
    store_path = REPO / roster["store"]
    store = json.loads(store_path.read_text()) if store_path.exists() else {"rows": {}, "outcomes": {}}
    store.setdefault("rows", {}); store.setdefault("outcomes", {})
    for rel in roster.get("ingest", []):
        p = REPO / rel
        if not p.exists():
            print(f"  (skip missing ingest card: {rel})")
            continue
        card = json.loads(p.read_text())
        store["rows"].update(card.get("rows", {}))
        store["outcomes"].update(card.get("outcomes", {}))
        print(f"  ingested {rel}: {len(card.get('rows', {}))} graded run(s)")
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text(json.dumps(store, indent=2))
    return store


# ===================================================================================================
# One run -> its 19 data cells (matching the fixed column order on the page).
# ===================================================================================================
COLS = 19  # data columns after the sticky run-name column


def scored_cells(rid: str, store: dict) -> list:
    """Return [(html, css_class), ...] of length COLS for a fully/partially graded run, or None if the
    run has no grade row in the store (caller renders it as ungraded)."""
    R = store["rows"].get(rid)
    if not R:
        return None
    O = store["outcomes"].get(rid, {}) or {}
    sig = O.get("signal", {}) or {}

    # --- aggregates (normalized only) ---
    total      = f3(_g(R, "total"))
    outcome    = f3(_g(R, "blocks", "outcome"))
    mapqual    = f3(_g(R, "outcome_breakdown", "signal_quality"))
    mapsimil   = f3(_g(R, "outcome_breakdown", "reference_consistency"))
    gate       = f2(_g(R, "handedness_gate"))
    procedure  = f3(_g(R, "blocks", "procedure"))
    trajectory = f3(_g(R, "_subtotals", "procedure.trajectory"))
    select2d   = f3(_g(R, "_subtotals", "procedure.select_2d"))

    # --- map-quality leaves: raw measured (outcomes) + norm (rows) ---
    def leaf(raw_str, norm):
        return "n/a" if norm is None else f"{raw_str} ({f3(norm)})"

    global_raw = O.get("gsfsc_loosemask_0143_A")
    local_spread = None
    if sig.get("local_res_p95_A") is not None and sig.get("local_res_p05_A") is not None:
        local_spread = sig["local_res_p95_A"] - sig["local_res_p05_A"]

    c_global = leaf(f2(global_raw), _g(R, "outcome.signal_quality", "global_resolution", 0))
    c_fsc    = leaf(f2(sig.get("fsc_auc")), _g(R, "outcome.signal_quality", "fsc_curve", 0))
    c_local  = leaf(f2(local_spread), _g(R, "outcome.signal_quality", "local_resolution", 0))
    c_cfar   = leaf(f3(sig.get("cfar")), _g(R, "outcome.signal_quality", "anisotropy", 0))
    c_mapcc  = leaf(f3(O.get("cc_map_emdb")), _g(R, "outcome.reference_consistency.emdb", "map_emdb_cc", 0))
    c_mapfsc = leaf(f2(O.get("fsc_map_emdb_05")), _g(R, "outcome.reference_consistency.emdb", "map_emdb_fsc", 0))

    # --- procedure leaves: raw factors (_raw) + norm ---
    compl_raw = _g(R, "_raw", "procedure.trajectory.completeness", "completeness", default={})
    ncaps = len(compl_raw.get("present_caps", [])) if compl_raw else 0
    c_treecompl = leaf(f"{ncaps}/9", _g(R, "procedure.trajectory.completeness", "completeness", 0))

    sim_raw = _g(R, "_raw", "procedure.trajectory.reference_similarity", "reference_similarity", default={})
    sim_str = f"{sim_raw.get('extra', '?')}+{sim_raw.get('missing', '?')}/{sim_raw.get('union', '?')}" if sim_raw else "—"
    c_treesimil = leaf(sim_str, _g(R, "procedure.trajectory.reference_similarity", "reference_similarity", 0))

    tmpl_raw = _g(R, "_raw", "procedure.select_2d.templates", "select2d_templates", default={})
    n = tmpl_raw.get("n"); mu = tmpl_raw.get("cryosift_mean_kept")
    tmpl_str = f"{n}·{f2(mu) if mu is not None else '—'}" if n is not None else "—"
    c_template = leaf(tmpl_str, _g(R, "procedure.select_2d.templates", "select2d_templates", 0))

    # refine / picks drop out (weight 0) on runs where the box-side compute hasn't run -> n/a
    refine_sub = _g(R, "_subtotals", "procedure.select_2d.refine")
    if refine_sub is None:
        c_refine = ("n/a", "ungraded")
    else:
        rf = _g(R, "_raw", "procedure.select_2d.refine", "select2d_refine", default={})
        c_refine = (leaf(f"{f2(rf.get('precision'))}/{f2(rf.get('recall'))}",
                         _g(R, "procedure.select_2d.refine", "select2d_refine", 0)), "")

    picks_sub = _g(R, "_subtotals", "procedure.particle_picks")
    if picks_sub is None:
        c_picks = ("n/a", "ungraded")
    else:
        pk = _g(R, "_raw", "procedure.particle_picks", "particle_picks", default={})
        c_picks = (leaf(f"{f2(pk.get('precision'))}/{f2(pk.get('recall'))}",
                        _g(R, "procedure.particle_picks", "particle_picks", 0)), "")

    return [
        (total, "agg"), (outcome, "agg"), (mapqual, "agg"),
        (c_global, ""), (c_fsc, ""), (c_local, ""), (c_cfar, ""),
        (mapsimil, "agg"), (c_mapcc, ""), (c_mapfsc, ""), (gate, ""),
        (procedure, "agg"), (trajectory, "agg"), (c_treecompl, ""), (c_treesimil, ""),
        (select2d, "agg"), (c_template, ""), c_refine, c_picks,
    ]


# ===================================================================================================
# Rows + tables.
# ===================================================================================================
def _name_cell(name: str, sub: str, ungraded: bool = False) -> str:
    cls = ' class="ungraded"' if ungraded else ""
    s = f'<span class="rn-sub">{sub}</span>' if sub else ""
    return f"<td{cls}>{name}{s}</td>"


def render_row(entry: dict, store: dict) -> str:
    """entry: {name, sub, run?, status?, note?}. Resolves to scored / ungraded / reference."""
    name, sub = entry["name"], entry.get("sub", "")
    if entry.get("note"):                                  # reference / anchor row
        return (f"<tr>{_name_cell(name, sub)}"
                f'<td colspan="{COLS}" style="text-align:left;color:var(--muted)">{entry["note"]}</td></tr>')
    rid = entry.get("run")
    cells = scored_cells(rid, store) if rid else None
    if cells is None:                                      # ungraded / not-yet-run
        return f'<tr>{_name_cell(name, sub, ungraded=True)}<td colspan="{COLS}"></td></tr>'
    tds = "".join(f'<td class="{c}">{h}</td>' if c else f"<td>{h}</td>" for h, c in cells)
    return f"<tr>{_name_cell(name, sub)}{tds}</tr>"


HEADER = """<thead><tr>
<th>Run</th>
<th class="agg">Total</th>
<th class="agg grp-out">Outcome</th>
<th class="agg grp-out">Map quality</th>
<th class="grp-out">Global res Å</th>
<th class="grp-out">FSC AUC</th>
<th class="grp-out">Local Δ Å</th>
<th class="grp-out">cFAR</th>
<th class="agg grp-out">Map similarity</th>
<th class="grp-out">map–map CC</th>
<th class="grp-out">map–map FSC Å</th>
<th class="grp-out">Hand gate</th>
<th class="agg grp-proc">Procedure</th>
<th class="agg grp-proc">Trajectory</th>
<th class="grp-proc">Tree compl.</th>
<th class="grp-proc">Tree simil.</th>
<th class="agg grp-proc">Select-2D</th>
<th class="grp-proc">template</th>
<th class="grp-proc">refine</th>
<th class="grp-proc">picks F2</th>
</tr></thead>"""


def render_table(entries: list, store: dict) -> str:
    body = "\n".join(render_row(e, store) for e in entries)
    return ('<div class="mtable-wrap">\n<table class="mtable">\n'
            + HEADER + "\n<tbody>\n" + body + "\n</tbody>\n</table>\n</div>")


def demo_entries(roster: dict) -> list:
    return roster["demo"]


def complete_entries(roster: dict, store: dict) -> list:
    """Every graded run in the store (ordered), then the configured outcome-only / reference extras."""
    labels = roster.get("complete_labels", {})
    order = roster.get("complete_order", [])
    graded = list(order) + sorted(k for k in store["rows"] if k not in order)
    out = [{"name": rid, "sub": labels.get(rid, ""), "run": rid} for rid in graded]
    out += roster.get("complete_extra", [])
    return out


# ===================================================================================================
# Inject into the page between markers.
# ===================================================================================================
def inject(html: str, tag: str, block: str) -> str:
    pat = re.compile(rf"(<!-- GEN:{tag}:start -->).*?(<!-- GEN:{tag}:end -->)", re.DOTALL)
    if not pat.search(html):
        sys.exit(f"ERROR: markers <!-- GEN:{tag}:start/end --> not found in {PAGE.name}")
    return pat.sub(lambda m: f"{m.group(1)}\n{block}\n{m.group(2)}", html)


def main():
    ap = argparse.ArgumentParser(description="Build the Benchmark page tables from the grade artifacts.")
    ap.add_argument("--publish", action="store_true", help="run bin/publish-site after building")
    args = ap.parse_args()

    roster = json.loads(ROSTER.read_text())
    print("building benchmark tables from grade artifacts:")
    store = build_store(roster)
    n_graded = len(store["rows"])

    demo = render_table(demo_entries(roster), store)
    complete = render_table(complete_entries(roster, store), store)

    html = PAGE.read_text()
    html = inject(html, "demo", demo)
    html = inject(html, "complete", complete)
    PAGE.write_text(html)
    print(f"  {n_graded} graded run(s) in the store: {', '.join(sorted(store['rows']))}")
    print(f"wrote {PAGE.relative_to(REPO)}")

    if args.publish:
        pub = REPO / "bin" / "publish-site"
        print(f"running {pub.relative_to(REPO)} ...")
        subprocess.run([str(pub)], check=True)


if __name__ == "__main__":
    main()
