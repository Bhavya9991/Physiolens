"""A self-contained HTML report for one agent run.

The shape follows the nightly audit report: a header, summary cards,
a filterable evidence table, then one section per step. Nothing extra
is stored. The file opens without a network connection.
"""

from __future__ import annotations

import json
import re


def render_report(run: dict) -> str:
    result = run.get("result") or {}
    report = result.get("report") or {}
    if isinstance(report, dict) and report.get("kind") == "resources":
        return _resources_document(run, report)
    if isinstance(report, dict) and "papers" in report:
        return _published_document(run, report)
    steps = run.get("steps") or []
    groups = result.get("groups") or []
    evidence = _evidence_rows(steps, groups)
    counts = _label_counts(evidence)
    cards = [
        ("Status", run.get("status") or "—"),
        ("Steps", str(len(steps))),
        ("Evidence rows", str(len(evidence))),
        ("Labels", str(len(counts)) or "0"),
    ]
    generated = run.get("updated_at") or run.get("created_at") or ""
    payload = json.dumps(evidence).replace("<", "\\u003c")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{_esc(run.get("project_title") or "PhysioLens report")}</title>
  <style>
    :root {{ --paper: #f3efe6; --ink: #1c1915; --muted: #5e584f; --line: #e3dace; --card: #fffdf8; --focus: #0f6e6a; }}
    body {{ margin: 0; background: var(--paper); color: var(--ink); font-family: "Segoe UI", sans-serif; }}
    main {{ max-width: 980px; margin: 0 auto; padding: 2rem 1.2rem 3rem; }}
    h1 {{ font-size: 2rem; letter-spacing: -0.03em; margin: 0.2rem 0; }}
    h2 {{ font-size: 1.15rem; margin: 0 0 0.6rem; }}
    .brand {{ letter-spacing: 0.14em; text-transform: uppercase; font-size: 0.75rem; color: var(--focus); }}
    .meta {{ color: var(--muted); }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 0.7rem; margin: 1rem 0; }}
    .card, .section {{ background: var(--card); border: 1px solid var(--line); border-radius: 16px; padding: 0.9rem 1rem; }}
    .card strong {{ display: block; font-size: 1.35rem; margin-top: 0.2rem; }}
    .card span, .muted {{ color: var(--muted); font-size: 0.82rem; }}
    .summary {{ margin: 0.8rem 0 1rem; line-height: 1.45; }}
    .controls {{ display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 0.7rem; }}
    input {{ flex: 1; min-width: 12rem; border: 1px solid var(--line); border-radius: 10px; padding: 0.45rem 0.6rem; font: inherit; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ text-align: left; vertical-align: top; padding: 0.55rem 0.4rem; border-bottom: 1px solid var(--line); }}
    th {{ font-size: 0.75rem; letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted); }}
    a {{ color: var(--focus); }}
    .badge {{ display: inline-block; border-radius: 999px; padding: 0.1rem 0.45rem; background: #efe7da; font-size: 0.78rem; }}
    .resume {{ background: var(--card); border: 1px solid var(--line); border-radius: 16px; padding: 0.9rem 1rem; margin: 0.7rem 0; }}
    .resume h3, .cite-row h3 {{ margin: 0 0 0.2rem; font-size: 1.05rem; }}
    .pill {{ display: inline-block; background: #efe7da; border-radius: 999px; padding: 0.12rem 0.5rem; margin: 0.15rem 0.25rem 0.15rem 0; font-size: 0.84rem; }}
    .resume ul {{ margin: 0.4rem 0 0; padding-left: 1.15rem; }}
    .resume blockquote {{ margin: 0.7rem 0 0; padding-left: 0.7rem; border-left: 2px solid var(--line); color: var(--muted); }}
    .cite-row {{ padding: 0.7rem 0; border-top: 1px solid var(--line); }}
    .cite-list {{ list-style: none; margin: 0.2rem 0 0; padding: 0; }}
    .cite-list li {{ padding: 0.45rem 0; border-top: 1px solid var(--line); }}
    .cite-list .meta {{ display: block; }}
    .tagline {{ margin: 0.35rem 0; }}
    .tagline > span {{ display: block; font-size: 0.75rem; letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted); }}
    .why span {{ font-weight: 600; }}
    .unread {{ margin-top: 1rem; }}
    .unread summary {{ cursor: pointer; color: var(--muted); }}
    .query {{ font-family: ui-monospace, Menlo, monospace; font-size: 0.86rem; color: var(--muted); }}
    .section {{ margin-top: 0.8rem; }}
    .error {{ color: #8d2f2f; }}
    .hidden {{ display: none; }}
  </style>
</head>
<body>
<main>
  <div class="brand">PhysioLens</div>
  <h1>{_esc(run.get("project_title") or "Untitled project")}</h1>
  <p class="meta">{_esc(run.get("action_label") or "")} · started {_esc(run.get("created_at") or "")} · updated {_esc(generated)}</p>
  <div class="grid">
    {"".join(f'<div class="card"><span>{_esc(label)}</span><strong>{_esc(value)}</strong></div>' for label, value in cards)}
  </div>
  {f'<p class="error">{_esc(run.get("error"))}</p>' if run.get("error") else ""}
  <p class="summary">{_esc(result.get("summary") or "No brief was written.")}</p>
  {_usage_dashboard(result.get("report") or {})}
  <section class="section">
    <h2>Evidence</h2>
    <div class="controls">
      <input id="filter" type="search" placeholder="Filter by title, label, or detail" />
    </div>
    <table>
      <thead><tr><th>Title</th><th>Label</th><th>Access</th><th>From</th><th>Detail</th></tr></thead>
      <tbody id="rows"></tbody>
    </table>
    <p id="empty" class="muted hidden">Nothing matches that filter.</p>
  </section>
  <h2 style="margin-top:1.2rem">How the agent got there</h2>
  {"".join(_step_html(index, step) for index, step in enumerate(steps, start=1)) or '<p class="muted">No steps were recorded.</p>'}
  <p class="muted">A snippet is a hit from the first search. A cites row only means that paper cites the seed, not that it used the dataset. A catalog row is a PhysioNet project in this app. A web row is a Google result, and its access stays unclear unless that page states it.</p>
</main>
<script>
const ROWS = {payload};
const body = document.getElementById("rows");
const empty = document.getElementById("empty");
function draw(query) {{
  const needle = query.trim().toLowerCase();
  const shown = ROWS.filter((row) => !needle || (row.title + " " + row.label + " " + row.detail + " " + row.access).toLowerCase().includes(needle));
  body.innerHTML = shown.map((row) => `<tr><td>${{row.link ? `<a href="${{row.link}}" target="_blank" rel="noreferrer">${{row.title}}</a>` : row.title}}</td><td><span class="badge">${{row.label}}</span></td><td>${{row.access}}</td><td>${{row.source}}</td><td>${{row.detail}}</td></tr>`).join("");
  empty.classList.toggle("hidden", shown.length > 0);
}}
document.getElementById("filter").addEventListener("input", (event) => draw(event.target.value));
draw("");
</script>
</body>
</html>
"""


_DOI = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", re.I)


def _similar_cards(cards: list) -> list:
    """A card is shown when at least one compared field matches."""
    kept = []
    for card in cards or []:
        if any((item or {}).get("verdict") == "same" for item in (card.get("dimensions") or [])):
            kept.append(card)
    return kept


def _resources_document(run: dict, report: dict) -> str:
    """One seed card, then similar peers, similar outside pages, and page links."""
    when = report.get("retrieved_on") or (run.get("updated_at") or run.get("created_at") or "")[:10]
    seed = report.get("seed") or {}
    sections = [
        ("In this catalog", _similar_cards(report.get("catalog") or []), "No similar resource in this catalog."),
        ("Outside PhysioNet", _similar_cards(report.get("outside") or []), "No similar page outside PhysioNet."),
    ]
    if report.get("family"):
        sections.append(("Related on this page", report.get("family") or [], ""))
    body = "".join(_resource_section(heading, cards, empty) for heading, cards, empty in sections)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{_esc(run.get("project_title") or "PhysioLens report")}</title>
  <style>
    :root {{ --paper: #f3efe6; --ink: #1c1915; --muted: #5e584f; --line: #e3dace; --card: #fffdf8; --focus: #0f6e6a; }}
    body {{ margin: 0; background: var(--paper); color: var(--ink); font-family: "Segoe UI", sans-serif; line-height: 1.45; }}
    main {{ max-width: 880px; margin: 0 auto; padding: 2rem 1.2rem 3rem; }}
    h1 {{ font-size: 1.8rem; letter-spacing: -0.03em; margin: 0.2rem 0 0.4rem; }}
    h2 {{ font-size: 1.15rem; margin: 1.6rem 0 0.5rem; }}
    a {{ color: var(--focus); }}
    .brand {{ letter-spacing: 0.14em; text-transform: uppercase; font-size: 0.75rem; color: var(--focus); }}
    .meta, .muted {{ color: var(--muted); }}
    .verdict {{ font-size: 1.15rem; margin: 0.8rem 0; }}
    .seed, .usage-card {{ background: var(--card); border: 1px solid var(--line); border-radius: 16px; padding: 1rem 1.1rem 0.8rem; margin: 0.7rem 0; }}
    .paper {{ padding: 0.75rem 0; border-top: 1px solid var(--line); }}
    .paper-top {{ display: flex; justify-content: space-between; gap: 0.8rem; align-items: baseline; }}
    .paper-top h3 {{ margin: 0; font-size: 1.05rem; }}
    .badge {{ flex: none; border-radius: 999px; padding: 0.12rem 0.55rem; font-size: 0.75rem; background: #efe7da; }}
    .pill {{ display: inline-block; border-radius: 999px; padding: 0.12rem 0.55rem; margin: 0.15rem 0.3rem 0.15rem 0; font-size: 0.82rem; background: #efe7da; }}
    .pill.same {{ background: #e7f6ec; color: #1d7a3a; }}
    .pill.different {{ background: #f8efd8; color: #6b4e16; }}
    .pill.unknown {{ background: transparent; color: var(--muted); border: 1px solid var(--line); }}
    .why span {{ font-weight: 600; }}
  </style>
</head>
<body>
<main>
  <div class="brand">Similar resources</div>
  <h1>{_esc(run.get("project_title") or "Untitled project")}</h1>
  <p class="meta">{_esc(run.get("status") or "")} · {_esc(when)}</p>
  {_seed_block(seed)}
  <p class="verdict">{_esc(report.get("summary") or "")}</p>
  <p class="meta">{_esc(report.get("method") or "")}</p>
  {body}
</main>
</body>
</html>
"""


def _seed_block(seed: dict) -> str:
    chips = [seed.get("kind") or "", seed.get("access") or "", *(seed.get("subjects") or []), *(seed.get("forms") or [])]
    soft = []
    if seed.get("modality"):
        soft.append(f"Modality: {', '.join(seed['modality'])}")
    if seed.get("tasks"):
        soft.append(f"Task: {', '.join(seed['tasks'])}")
    if seed.get("population"):
        soft.append(f"Population: {seed['population']}")
    link = f'<p class="meta"><a href="{_esc(seed.get("url") or "")}">PhysioNet project page</a></p>' if seed.get("url") else ""
    extra = f"<p>{_esc(' · '.join(soft))}</p>" if soft else ""
    return (
        "<article class='seed'><p class='brand'>This resource</p>"
        f"<h2>{_esc(seed.get('title') or '')}</h2>{link}"
        f"<p>{_resource_pills([{'field': chip, 'verdict': ''} for chip in chips if chip])}</p>{extra}</article>"
    )


def _resource_section(heading: str, cards: list[dict], empty: str) -> str:
    if not cards:
        return f"<h2>{_esc(heading)}</h2><p class='muted'>{_esc(empty)}</p>" if empty else ""
    return f"<h2>{_esc(heading)}</h2>{''.join(_resource_card(card) for card in cards)}"


def _resource_card(card: dict) -> str:
    kind = f"<span class='badge'>{_esc(card.get('kind') or '')}</span>" if card.get("kind") else ""
    access = f"<p class='meta'>{_esc(card.get('access') or '')}</p>" if card.get("access") else ""
    why_text = card.get("why") or ""
    if card.get("relation") == "peer" and why_text:
        why = f"<p class='why'><span>Insight</span> {_esc(why_text)}</p>"
    elif why_text:
        why = f"<p class='why'>{_esc(why_text)}</p>"
    else:
        why = ""
    return (
        f"<article class='usage-card'><div class='paper-top'><h3>{_resource_heading(card)}</h3>{kind}</div>"
        f"{access}{_resource_pills(card.get('dimensions') or [])}{why}</article>"
    )


def _resource_heading(card: dict) -> str:
    title = _esc(card.get("title") or "Untitled")
    link = card.get("link") or ""
    if not link:
        return title
    return f'<a href="{_esc(link)}">{title}</a>'


def _resource_pills(dimensions: list[dict]) -> str:
    pills = []
    for item in dimensions:
        field = item.get("field") or ""
        verdict = item.get("verdict") or ""
        if not field or verdict == "unknown":
            continue
        label = field if not verdict else f"{verdict.capitalize()} {field.lower()}"
        pills.append(f"<span class='pill {verdict}'>{_esc(label)}</span>")
    return f"<p>{''.join(pills)}</p>" if pills else ""


def _usage_line(report: dict, fallback: str = "") -> str:
    counts = report.get("counts") or {}
    if not counts:
        return fallback
    from apps.agents.published import usage_sentence

    return usage_sentence(counts)


def _usage_bar(counts: dict) -> str:
    users = int(counts.get("users") or 0)
    other = int(counts.get("other") or 0)
    unclear = int(counts.get("unclear") or 0)
    parts = [
        ("used", users, "can be found to use it"),
        ("other", other, "does not use it" if other == 1 else "do not use it"),
        ("miss", unclear, "could not be read"),
    ]
    shown = [part for part in parts if part[1]]
    if not shown:
        return ""
    bar = "".join(f"<span class='split-{kind}' style='flex:{count} 1 0'></span>" for kind, count, _label in shown)
    key = "".join(
        f"<li><i class='split-{kind}'></i><strong>{count}</strong> {_esc(label)}</li>"
        for kind, count, label in shown
    )
    return f"<div class='usage-split'><div class='split-bar'>{bar}</div><ul class='split-key'>{key}</ul></div>"


def _published_document(run: dict, report: dict) -> str:
    """Findings first. The search trace stays closed."""
    result = run.get("result") or {}
    when = report.get("retrieved_on") or (run.get("updated_at") or run.get("created_at") or "")[:10]
    source, dois = _source_bits(run, report)
    links = []
    if source:
        links.append(f'<a href="{_esc(source)}">PhysioNet project page</a>')
    links.extend(f'<a href="https://doi.org/{_esc(doi)}">DOI {_esc(doi)}</a>' for doi in dois)
    link = f"<p class='meta'>{' · '.join(links)}</p>" if links else ""
    audit = _audit_html(run.get("steps") or [], report.get("method") or "")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{_esc(run.get("project_title") or "PhysioLens report")}</title>
  <style>
    :root {{ --paper: #f3efe6; --ink: #1c1915; --muted: #5e584f; --line: #e3dace; --card: #fffdf8; --focus: #0f6e6a; }}
    body {{ margin: 0; background: var(--paper); color: var(--ink); font-family: "Segoe UI", sans-serif; line-height: 1.45; }}
    main {{ max-width: 880px; margin: 0 auto; padding: 2rem 1.2rem 3rem; }}
    h1 {{ font-size: 1.8rem; letter-spacing: -0.03em; margin: 0.2rem 0 0.4rem; }}
    h2 {{ font-size: 1.15rem; margin: 1.4rem 0 0.4rem; }}
    h3 {{ margin: 0 0 0.2rem; font-size: 1.05rem; }}
    a {{ color: var(--focus); }}
    .brand {{ letter-spacing: 0.14em; text-transform: uppercase; font-size: 0.75rem; color: var(--focus); }}
    .meta, .muted {{ color: var(--muted); }}
    .verdict {{ font-size: 1.2rem; margin: 0.8rem 0 0.3rem; }}
    .usage-split {{ margin: 0.6rem 0 0.8rem; max-width: 36rem; }}
    .split-bar {{ display: flex; height: 0.8rem; border-radius: 999px; overflow: hidden; background: var(--line); }}
    .split-bar .split-used, .split-key i.split-used {{ background: #1d7a3a; }}
    .split-bar .split-other, .split-key i.split-other {{ background: #b08968; }}
    .split-bar .split-miss, .split-key i.split-miss {{ background: #c4524a; }}
    .split-key {{ display: flex; flex-wrap: wrap; gap: 0.35rem 1rem; list-style: none; margin: 0.5rem 0 0; padding: 0; color: var(--muted); font-size: 0.86rem; }}
    .split-key i {{ display: inline-block; width: 0.55rem; height: 0.55rem; border-radius: 99px; margin-right: 0.35rem; }}
    .split-key strong {{ color: var(--ink); }}
    .paper {{ padding: 0.9rem 0; border-top: 1px solid var(--line); }}
    .usage-card {{ background: var(--card); border: 1px solid var(--line); border-radius: 16px; padding: 1rem 1.1rem 0.7rem; margin: 0.85rem 0; }}
    .paper-top {{ display: flex; justify-content: space-between; gap: 0.8rem; align-items: baseline; }}
    .paper-top h3 {{ margin: 0; font-size: 1.05rem; }}
    .usage-card h4 {{ margin: 0.85rem 0 0.25rem; font-size: 0.78rem; letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted); font-weight: 600; }}
    .pills {{ margin: 0.15rem 0 0.2rem; }}
    .badge {{ flex: none; border-radius: 999px; padding: 0.12rem 0.55rem; font-size: 0.75rem; letter-spacing: 0.03em; background: #efe7da; }}
    .badge.yes {{ background: #e7f6ec; color: #1d7a3a; }}
    .badge.miss {{ background: #fdecea; color: #a3262a; }}
    .resume {{ background: var(--card); border: 1px solid var(--line); border-radius: 16px; padding: 0.9rem 1rem; margin: 0.7rem 0; }}
    .pill {{ display: inline-block; background: #efe7da; border-radius: 999px; padding: 0.12rem 0.5rem; margin: 0.15rem 0.25rem 0.15rem 0; font-size: 0.84rem; }}
    .tagline {{ margin: 0.35rem 0; }}
    .tagline > span, .why span {{ font-size: 0.75rem; letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted); }}
    .why span {{ font-size: 0.95rem; letter-spacing: 0; text-transform: none; font-weight: 600; color: var(--ink); }}
    details {{ margin-top: 1.6rem; }}
    summary {{ cursor: pointer; color: var(--muted); }}
    .section {{ margin-top: 0.8rem; }}
    .query {{ font-family: ui-monospace, Menlo, monospace; font-size: 0.82rem; color: var(--muted); }}
  </style>
</head>
<body>
<main>
  <div class="brand">Published use</div>
  <h1>{_esc(run.get("project_title") or "Untitled project")}</h1>
  <p class="meta">{_esc(run.get("status") or "")} · {_esc(when)}</p>
  {link}
  <p class="verdict">{_esc(_usage_line(report, result.get("summary") or ""))}</p>
  {_usage_bar(report.get("counts") or {})}
  <p class="meta">{_esc(report.get("method") or "")}</p>
  {_paper_sections(report)}
  <details>
    <summary>How this was generated</summary>
    {audit}
  </details>
</main>
</body>
</html>
"""


def _source_bits(run: dict, report: dict) -> tuple[str, list[str]]:
    source = report.get("source_url") or ""
    dois = [doi for doi in (report.get("dois") or []) if doi]
    for step in run.get("steps") or []:
        if step.get("id") == "page_citations" and not source:
            source = step.get("query") or ""
        for match in _DOI.findall(step.get("query") or ""):
            doi = match.rstrip(".")
            if doi not in dois:
                dois.append(doi)
    return source, dois


def _paper_sections(report: dict) -> str:
    """Used papers first, then papers that do not use the dataset, then pages that could not be read."""
    used, other, unread = [], [], []
    for paper in report.get("papers") or []:
        if paper.get("card"):
            used.append(paper)
        elif paper.get("usage_class") == "unclear" or paper.get("label") == "Could not be read":
            unread.append(paper)
        else:
            other.append(paper)
    parts = []
    if used:
        parts.append("<h2>Used this dataset</h2>" + "".join(_paper_block(paper) for paper in used))
        parts.append(_insight_html(report))
    else:
        parts.append("<p class='muted'>No confirmed usage found, so no insights were generated.</p>")
    if other:
        parts.append("<h2>Does not use it</h2>" + "".join(_paper_block(paper) for paper in other))
    if unread:
        parts.append("<h2>Could not be read</h2>" + "".join(_paper_block(paper) for paper in unread))
    return "".join(parts)


def _paper_block(paper: dict) -> str:
    kind = "yes" if paper.get("card") else ("miss" if paper.get("usage_class") == "unclear" else "no")
    detail = _usage_body(paper.get("card") or {}) if paper.get("card") else f"<p>{_esc(_reason(paper))}</p>"
    return (
        f"<article class='usage-card'>"
        "<div class='paper-top'>"
        f"<h3>{_paper_heading(paper)}</h3>"
        f"<span class='badge {kind}'>{_esc(_verdict(paper))}</span>"
        "</div>"
        f"<p class='meta'>{_esc(_paper_meta(paper))}</p>"
        f"{detail}</article>"
    )


def _usage_body(card: dict) -> str:
    if card.get("how_used") or card.get("why_explore") or card.get("research_tasks") or card.get("techniques"):
        return (
            "<h4>How the dataset was used</h4>"
            f"<p>{_esc(card.get('how_used') or '')}</p>"
            f"{_tag_line('Role', card.get('dataset_role'))}"
            f"{_tag_line('Task', card.get('research_tasks'))}"
            f"{_tag_line('Techniques', card.get('techniques'))}"
            f"<p class='why'><span>Why explore this paper?</span> {_esc(card.get('why_explore') or '')}</p>"
        )
    return f"<p>{_esc(card.get('headline') or card.get('why') or '')}</p>"


def _verdict(paper: dict) -> str:
    if paper.get("card"):
        return "Used this dataset"
    if paper.get("usage_class") == "unclear":
        return "Could not be read"
    return "Does not use it"


def _reason(paper: dict) -> str:
    card = paper.get("card") or {}
    explore = paper.get("explore") or {}
    if card:
        return card.get("why_explore") or card.get("how_used") or paper.get("why") or ""
    return explore.get("why_open") or paper.get("why") or ""


def _insight_html(report: dict) -> str:
    insights = report.get("insights") or {}
    labels = (
        ("research_tasks", "Research tasks"),
        ("methods_and_models", "Methods"),
        ("setups_and_findings", "Setups"),
    )
    blocks = []
    for key, label in labels:
        text = " ".join(str(insights.get(key) or "").split())
        if not text or text.lower().startswith("no usage"):
            continue
        blocks.append(f"<p><strong>{_esc(label)}</strong> {_esc(text)}</p>")
    if not blocks:
        return ""
    return "<h2>Across these papers</h2>" + "".join(blocks)


def _audit_html(steps: list[dict], method: str = "") -> str:
    kept = []
    quiet = 0
    note = " ".join(method.split())
    for index, step in enumerate(steps, start=1):
        why = " ".join((step.get("why") or "").split())
        if note and note in why:
            why = why.replace(note, "").strip(" .")
        if step.get("items"):
            shown = dict(step)
            shown["why"] = why
            kept.append(_step_html(index, shown))
            continue
        if why:
            kept.append(f"<p class='muted'>{index}. {_esc(step.get('title') or 'Step')}. {_esc(why)}</p>")
        else:
            quiet += 1
    if quiet:
        kept.append(f"<p class='muted'>{quiet} steps returned nothing.</p>")
    return "".join(kept) or "<p class='muted'>No steps were recorded.</p>"


def _explore_item(paper: dict) -> str:
    explore = paper.get("explore") or {}
    reason = explore.get("why_open") or paper.get("why") or ""
    meta = _paper_meta(paper)
    extra = f"<span class='meta'>{_esc(meta)}</span>" if meta else ""
    return f"<li>{_paper_heading(paper)}{extra}<span>{_esc(reason)}</span></li>"


def _usage_dashboard(report: dict) -> str:
    if not report:
        return ""
    if report.get("empty"):
        return (
            "<section class='section'>"
            "<div class='brand'>Dataset usage</div>"
            "<h2>No published records yet</h2>"
            f"<p>{_esc(report.get('notice') or 'No published papers that cite this dataset were found.')}</p>"
            "<article class='resume'><h3>What this dataset is</h3>"
            f"<p>{_esc(report.get('dataset_summary') or '')}</p></article>"
            "</section>"
        )
    counts = report.get("counts") or {}
    papers = report.get("papers") or []
    used = [paper for paper in papers if paper.get("card")]
    other = [paper for paper in papers if not paper.get("card") and paper.get("usage_class") != "unclear"]
    unclear = [paper for paper in papers if not paper.get("card") and paper.get("usage_class") == "unclear"]
    users = counts.get("users", len(used))
    total = counts.get("candidates", len(papers))
    others = counts.get("other", len(other))
    missed = counts.get("unclear", len(unclear))
    quiet = _usage_line(
        {"counts": {"users": users, "candidates": total, "other": others, "unclear": missed}},
        f"{users} used this dataset · {others} cited it for another purpose",
    )
    used_html = "".join(_resume_paper(paper) for paper in used) or "<p class='muted'>No paper in this sample had text that confirmed use.</p>"
    other_html = (
        f"<h2>Also citing this dataset</h2><ul class='cite-list'>{''.join(_cite_item(paper) for paper in other)}</ul>"
        if other
        else ""
    )
    unclear_html = (
        f"<details class='unread'><summary>{_esc(missed)} papers could not be read</summary>"
        f"<ul class='cite-list'>{''.join(_cite_item(paper) for paper in unclear)}</ul></details>"
        if unclear
        else ""
    )
    return (
        "<section class='section'>"
        "<div class='brand'>Published use</div>"
        f"<h2>{_esc(users)} of {_esc(total)} papers in this sample use the dataset</h2>"
        f"<p class='meta'>Retrieved {_esc(report.get('retrieved_on') or '')}. {_esc(report.get('method') or '')}</p>"
        f"<p class='meta'>{_esc(quiet)}</p>"
        "<h2>Used this dataset</h2>"
        f"{used_html}"
        f"{other_html}"
        f"{unclear_html}"
        "</section>"
    )


def _resume_paper(paper: dict) -> str:
    card = paper.get("card") or {}
    if card.get("how_used") or card.get("why_explore") or card.get("research_tasks") or card.get("techniques"):
        body = (
            f"<h3>How the dataset was used</h3><p>{_esc(card.get('how_used') or '')}</p>"
            f"{_tag_line('Role', card.get('dataset_role'))}"
            f"{_tag_line('Task', card.get('research_tasks'))}"
            f"{_tag_line('Techniques', card.get('techniques'))}"
            f"<p class='why'><span>Why explore this paper?</span> {_esc(card.get('why_explore') or '')}</p>"
        )
    else:
        body = f"<p>{_esc(card.get('headline') or card.get('why') or '')}</p>"
    return (
        "<article class='resume'>"
        f"<h3>{_paper_heading(paper)}</h3><p class='meta'>{_esc(_paper_meta(paper))}</p>{body}</article>"
    )


def _pills(values) -> str:
    items = [item for item in (values or []) if item]
    if not items:
        return "<p class='muted'>Not stated in the sections that were read.</p>"
    return "".join(f"<span class='pill'>{_esc(item)}</span>" for item in items)


def _tag_line(label: str, values) -> str:
    items = [item for item in (values or []) if item]
    if not items:
        return ""
    return f"<p class='tagline'><span>{_esc(label)}</span></p><p class='pills'>{_pills(items)}</p>"


def _cite_item(paper: dict) -> str:
    meta = _paper_meta(paper)
    extra = f"<span class='meta'>{_esc(meta)}</span>" if meta else ""
    return f"<li>{_paper_heading(paper)}{extra}</li>"


def _cite_paper(paper: dict) -> str:
    return (
        "<article class='cite-row'>"
        f"<h3>{_paper_heading(paper)}</h3>"
        f"<p class='meta'>{_esc(_paper_meta(paper))}</p>"
        f"<p>{_esc(paper.get('why') or paper.get('label') or '')}</p>"
        "</article>"
    )


def _paper_heading(paper: dict) -> str:
    title = paper.get("title") or "Untitled"
    link = paper.get("link") or ""
    return f'<a href="{_esc(link)}">{_esc(title)}</a>' if link else _esc(title)


def _paper_meta(paper: dict) -> str:
    cited = paper.get("cited_by_total") or 0
    return " · ".join(part for part in (paper.get("byline") or "", f"{cited} citations" if cited else "") if part)


def _evidence_rows(steps: list[dict], groups: list[dict]) -> list[dict]:
    rows = []
    seen = set()
    for source, items in [("step", _step_items(steps)), ("finding", _group_items(groups))]:
        for item in items:
            key = ((item.get("link") or item.get("title") or "") + (item.get("label") or "")).casefold()
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "title": _esc(item.get("title") or "Untitled"),
                    "link": _esc(item.get("link") or ""),
                    "label": _esc(item.get("label") or "—"),
                    "access": _esc(item.get("access") or "—"),
                    "detail": _esc(item.get("detail") or ""),
                    "source": _esc(item.get("_source") or source),
                }
            )
    return rows


def _step_items(steps: list[dict]) -> list[dict]:
    items = []
    for step in steps:
        for item in step.get("items") or []:
            items.append({**item, "_source": step.get("title") or "Step"})
    return items


def _group_items(groups: list[dict]) -> list[dict]:
    items = []
    for group in groups:
        for item in group.get("items") or []:
            items.append({**item, "_source": group.get("heading") or "Finding"})
    return items


def _label_counts(rows: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        label = row.get("label") or "—"
        counts[label] = counts.get(label, 0) + 1
    return counts


def _step_html(index: int, step: dict) -> str:
    query = ""
    if step.get("query"):
        query = f'<p class="query">{_esc(step.get("engine") or "")}: {_esc(step.get("query"))}</p>'
    why = f'<p>{_esc(step.get("why"))}</p>' if step.get("why") else ""
    count = len(step.get("items") or [])
    note = _step_note(step, count)
    return (
        f'<section class="section"><h2>{index}. {_esc(step.get("title") or "Step")}</h2>'
        f"{why}{query}<p class=\"muted\">{_esc(note)}</p></section>"
    )


def _step_note(step: dict, count: int) -> str:
    if count:
        noun = "record" if count == 1 else "records"
        return f"{count} {noun} from this step."
    step_id = step.get("id") or ""
    if step_id in {"scholar_query", "challenge_queries", "trace_queries", "web_decision"}:
        return "This step only chooses the query. The records are in the next step."
    if step_id == "seed":
        return "No seed paper was kept, so the citation trail stops."
    return "This search returned nothing."


def _esc(value: object) -> str:
    return str(value if value is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
