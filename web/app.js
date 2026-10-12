const stage = document.getElementById("stage");
const rail = document.getElementById("rail");

const state = {
  catalog: null,
  runs: [],
  currentRunId: "",
  table: null,
  project: null,
  run: null,
  filters: {},
  activitySig: "",
};

const ACTIVITY_GROUPS = [
  { id: "published", label: "Explore published research" },
  { id: "resources", label: "Find similar resources" },
];

const MARKS = {
  subject: `<svg viewBox="0 0 120 120" fill="none" stroke="currentColor" stroke-width="2.2"><circle cx="60" cy="60" r="34"/><path d="M60 26v68M26 60h68M38 38l44 44M82 38 38 82"/></svg>`,
  data_form: `<svg viewBox="0 0 120 120" fill="none" stroke="currentColor" stroke-width="2.2"><rect x="28" y="34" width="64" height="44" rx="8"/><path d="M28 48h64M44 34v44M28 62h64"/></svg>`,
  heart: `<svg viewBox="0 0 120 120" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M60 96s-32-18-32-42a16 16 0 0 1 28-10 16 16 0 0 1 28 10c0 24-24 42-24 42z"/><path d="M18 64h18l6-12 8 22 7-10h45"/></svg>`,
  brain: `<svg viewBox="0 0 120 120" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M60 28c-14 0-22 10-22 22 0 4-4 8-8 8-6 0-10 6-10 12s6 14 16 14c4 8 12 14 24 14s20-6 24-14c10 0 16-8 16-14s-4-12-10-12c-4 0-8-4-8-8 0-12-8-22-22-22z"/><path d="M60 28v68M46 46c6 4 8 10 8 16M74 46c-6 4-8 10-8 16"/></svg>`,
  sleep: `<svg viewBox="0 0 120 120" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M70 28a28 28 0 1 0 22 46 24 24 0 1 1-22-46z"/><path d="M24 78c10 8 24 12 40 12 8 0 16-1 22-4"/></svg>`,
  breathing: `<svg viewBox="0 0 120 120" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M60 30c-16 14-28 22-28 40a28 28 0 0 0 56 0c0-18-12-26-28-40z"/><path d="M60 48v36M48 66h24"/></svg>`,
  movement: `<svg viewBox="0 0 120 120" fill="none" stroke="currentColor" stroke-width="2.2"><circle cx="78" cy="28" r="8"/><path d="M74 40 58 62l-16 8M58 62l18 8 8 22M58 62 40 54M76 70l14 6"/></svg>`,
  signals: `<svg viewBox="0 0 120 120" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M10 64h24l8-24 12 48 10-28 8 4h38"/></svg>`,
  images: `<svg viewBox="0 0 120 120" fill="none" stroke="currentColor" stroke-width="2.2"><rect x="22" y="30" width="76" height="58" rx="8"/><circle cx="46" cy="50" r="7"/><path d="M30 78l18-16 14 12 10-8 18 16"/></svg>`,
  chest: `<svg viewBox="0 0 120 120" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M60 24c8 10 22 16 34 18-2 28-12 46-34 54-22-8-32-26-34-54 12-2 26-8 34-18z"/><path d="M60 40v48"/></svg>`,
  eye: `<svg viewBox="0 0 120 120" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M16 60s18-24 44-24 44 24 44 24-18 24-44 24S16 60 16 60z"/><circle cx="60" cy="60" r="12"/><circle cx="60" cy="60" r="4" fill="currentColor"/></svg>`,
  text: `<svg viewBox="0 0 120 120" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M34 28h40l16 16v48H34z"/><path d="M74 28v16h16M46 58h28M46 70h22M46 82h16"/></svg>`,
  records: `<svg viewBox="0 0 120 120" fill="none" stroke="currentColor" stroke-width="2.2"><rect x="30" y="24" width="60" height="72" rx="6"/><path d="M42 42h36M42 54h36M42 66h24M42 78h18"/></svg>`,
  audio: `<svg viewBox="0 0 120 120" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M52 44v32l-14-8H26V52h12zM66 48a16 16 0 0 1 0 24M74 40a28 28 0 0 1 0 40"/></svg>`,
};

document.getElementById("brand").addEventListener("click", () => location.hash = "#/about");
document.querySelectorAll(".nav a, .section-bar a").forEach((link) => {
  link.addEventListener("click", () => rail.classList.remove("is-open"));
});

let shownHash = location.hash || "#/";

window.addEventListener("hashchange", render);
boot();

async function boot() {
  const [catalog, runs] = await Promise.all([
    fetch("/api/catalog").then(readJson),
    fetch("/api/runs").then(readJson),
  ]);
  state.catalog = catalog;
  state.runs = runs.runs || [];
  render();
  setInterval(refreshRuns, 2500);
}

async function readJson(response) {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || "Request failed.");
  return payload;
}

async function refreshRuns() {
  try {
    const payload = await fetch("/api/runs").then(readJson);
    state.runs = payload.runs || [];
    paintNav();
    if (sectionOf(location.hash) === "activity" && state.activitySig !== runsSignature()) paintActivity();
    if (location.hash.startsWith("#/run/")) {
      const id = location.hash.slice(6);
      if (state.run && (state.run.status === "running" || state.run.status === "stopping")) {
        state.run = await fetch("/api/runs/" + id).then(readJson);
        paintRunView();
      }
      refreshLog(id);
    }
  } catch (_error) {
    /* The next poll retries. */
  }
}

function render() {
  paintNav();
  const hash = location.hash || "#/";
  const leftFullList = shownHash === "#/all" && hash !== "#/all";
  if (leftFullList) delete state.filters["/"];
  if (leftFullList || sectionOf(shownHash) !== sectionOf(hash) || (hash === "#/all" && shownHash !== "#/all")) window.scrollTo(0, 0);
  shownHash = hash;
  if (hash === "#/" || hash === "#" || hash === "#/about") return paintAbout();
  if (hash === "#/explore") return paintStart();
  if (hash === "#/activity") return paintActivity();
  if (hash === "#/all") return paintTable("", "");
  if (hash.startsWith("#/level/")) return paintLevel(hash.slice(8).split("/"));
  if (hash.startsWith("#/table/")) return paintTable(...hash.slice(8).split("/"));
  if (hash.startsWith("#/project/")) {
    const place = parseProjectHash(hash);
    return paintProject(place.slug, place);
  }
  if (hash.startsWith("#/run/")) return paintRun(hash.slice(6));
  paintAbout();
}

function sectionOf(hash) {
  const value = hash || "#/";
  if (value === "#/" || value === "#" || value.startsWith("#/about")) return "about";
  if (value.startsWith("#/activity") || value.startsWith("#/run/")) return "activity";
  return "explore";
}

function paintNav() {
  const section = sectionOf(location.hash || "#/");
  document.querySelectorAll(".nav a, .section-bar a").forEach((link) => {
    const current = link.dataset.section === section;
    link.classList.toggle("is-current", current);
    if (current) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
}

function runsSignature() {
  return state.runs.map((run) => `${run.id}:${run.status}`).join("|");
}

async function deleteRun(id) {
  const response = await fetch("/api/runs/" + encodeURIComponent(id), { method: "DELETE" });
  if (!response.ok) return;
  state.runs = state.runs.filter((run) => run.id !== id);
  if (state.currentRunId === id) state.currentRunId = "";
  if (location.hash === "#/run/" + id) {
    location.hash = "#/activity";
    return;
  }
  if (sectionOf(location.hash) === "activity") paintActivity();
}

async function deleteAllRuns() {
  if (!window.confirm("Delete every run in this list?")) return;
  const response = await fetch("/api/runs", { method: "DELETE" });
  if (!response.ok) return;
  state.runs = [];
  state.currentRunId = "";
  if (location.hash.startsWith("#/run/")) {
    location.hash = "#/activity";
    return;
  }
  if (sectionOf(location.hash) === "activity") paintActivity();
}

function paintAbout() {
  const published = AGENT_FACE.published.mark;
  const resources = AGENT_FACE.resources.mark;
  stage.innerHTML = `
    <p class="kicker">About</p>
    <h1>Read past the PhysioNet page.</h1>
    <p class="lede">Find a dataset by what it is about, or by the kind of data it holds. Then see which papers used it, and which other resources share its subject, its kind of data, or its topic.</p>
    <div class="about-contrast">
      <section>
        <h2>On PhysioNet</h2>
        <p>You search, or you browse by listing kind: database, challenge, software, model. The project page holds the description, the files, who can use it, and the citations. Papers that used the dataset, and datasets that sit next to it, are something you go and find.</p>
      </section>
      <section>
        <h2>Here</h2>
        <p>You start from what a project is about, or from what the data is. A project can sit in more than one place. Access, date, size, and listing kind only narrow a list you already opened. Open a project and two agents take it from there: one shows the papers that used the dataset, the other shows resources that share its subject, its kind of data, or its topic.</p>
      </section>
    </div>
    <h2 class="about-next">Two agents, on every project</h2>
    <div class="about-agents">
      <article class="about-agent" data-agent="published">
        <span class="mark" aria-hidden="true">${published}</span>
        <h3>Explore published research</h3>
        <p>Reads the citations on the project page, finds the resource and the original publication on Scholar, and keeps up to 10 papers that cite them. Each paper is read. A usage card is written when the text shows the dataset was used.</p>
      </article>
      <article class="about-agent" data-agent="resources">
        <span class="mark" aria-hidden="true">${resources}</span>
        <h3>Find similar resources</h3>
        <p>Compares this project with other PhysioNet resources that share a subject, a kind of data, or a topic, and with a short list of pages from the web. Each card says what is the same, what differs, and what was not stated.</p>
      </article>
    </div>
  `;
}

function paintActivity() {
  state.activitySig = runsSignature();
  const known = new Set(ACTIVITY_GROUPS.map((group) => group.id));
  const extras = [];
  for (const run of state.runs) {
    if (known.has(run.action_id) || extras.some((group) => group.id === run.action_id)) continue;
    extras.push({ id: run.action_id, label: run.action_label || run.action_id });
  }
  const clear = state.runs.length
    ? `<button class="text-btn delete-all" id="delete-all" type="button">Delete all</button>`
    : "";
  stage.innerHTML = `
    <p class="kicker">Past activity</p>
    <h1>Jobs already started.</h1>
    <p class="lede">Grouped by agent. Open a job to read it. These stay on this machine after you leave the page.</p>
    ${clear}
    ${ACTIVITY_GROUPS.concat(extras).map(activityGroup).join("")}
  `;
  const deleteAll = document.getElementById("delete-all");
  if (deleteAll) deleteAll.addEventListener("click", deleteAllRuns);
  stage.querySelectorAll("[data-run]").forEach((button) => {
    button.addEventListener("click", () => {
      location.hash = "#/run/" + button.dataset.run;
    });
  });
  stage.querySelectorAll("[data-delete]").forEach((button) => {
    button.addEventListener("click", () => deleteRun(button.dataset.delete));
  });
}

function activityGroup(group) {
  const runs = state.runs.filter((run) => run.action_id === group.id);
  const count = runs.length
    ? `<span>${runs.length} ${runs.length === 1 ? "job" : "jobs"}</span>`
    : "";
  const body = runs.length
    ? `<div class="activity-list">${runs.map(activityRow).join("")}</div>`
    : `<p class="quiet-light">No jobs yet.</p>`;
  return `<section class="activity-group" data-agent="${esc(group.id)}">
    <header><h2>${esc(group.label)}</h2>${count}</header>
    ${body}
  </section>`;
}

function activityRow(run) {
  return `<div class="activity-row">
    <button class="activity-card ${run.id === state.currentRunId ? "is-current" : ""}" data-run="${esc(run.id)}" type="button">
      <strong>${esc(run.project_title)}</strong>
      <span class="status ${esc(run.status)}"><i></i>${esc(run.status)}</span>
    </button>
    <button class="activity-delete" data-delete="${esc(run.id)}" type="button" aria-label="Delete this run">×</button>
  </div>`;
}

function paintStart() {
  const catalog = state.catalog;
  stage.innerHTML = `
    <h1>Start from a dataset.</h1>
    <p class="lede">Two ways in. Clinical subject follows the medical area, such as heart, brain, or sleep. Kind of data follows the recording, such as a waveform, an image, or a note.</p>
    <div class="tiles">
      ${catalog.doors.map((door) => tile({
        theme: door.id,
        kicker: doorKicker(door.id),
        title: door.label,
        count: `${door.count} projects`,
        subtitle: door.subtitle,
        href: "#/level/" + door.id,
      })).join("")}
    </div>
    <p class="note">For every dataset hosted here, open the full project list.</p>
    <button class="text-btn full-list" id="full-list" type="button">Full project list</button>
  `;
  bindTiles();
  document.getElementById("full-list").addEventListener("click", () => { location.hash = "#/all"; });
}

function paintLevel(parts) {
  const [hierarchyId, parentId] = parts;
  const door = state.catalog.doors.find((item) => item.id === hierarchyId);
  if (!door) return paintStart();
  let nodes = door.nodes;
  let title = door.label;
  let parent = null;
  if (parentId) {
    parent = findNode(door.nodes, parentId);
    if (!parent) return paintStart();
    nodes = parent.children || [];
    title = `${door.label} / ${parent.label}`;
  }
  const extra = parent ? [tile({
    theme: parent.id,
    kicker: "Every project in this group",
    title: `All ${parent.label}`,
    count: `${parent.count} projects`,
    subtitle: parent.blurb ? `${parent.blurb} This list includes projects that are not in a narrower group.` : "Every project in this group, including ones that are not in a narrower group.",
    href: `#/table/${hierarchyId}/${parent.id}`,
  })] : [];
  stage.innerHTML = `
    ${crumbs([{ label: "Explore", href: "#/explore" }, { label: title }])}
    <h1>${esc(title)}</h1>
    <div class="tiles">
      ${nodes.map((node) => tile({
        theme: node.id,
        kicker: node.has_children ? "Has a narrower group" : "Group",
        title: node.label,
        count: `${node.count} projects`,
        subtitle: node.blurb || node.label,
        href: node.has_children ? `#/level/${hierarchyId}/${node.id}` : `#/table/${hierarchyId}/${node.id}`,
      })).join("")}
      ${extra.join("")}
    </div>
  `;
  bindTiles();
}

function doorKicker(id) {
  if (id === "subject") return "By medical area";
  if (id === "data_form") return "By recording";
  return "Way in";
}

function tile({ theme, kicker, title, count, subtitle, href }) {
  return `
    <button class="tile" data-theme="${esc(theme)}" data-href="${esc(href)}" type="button">
      <span class="mark" aria-hidden="true">${MARKS[theme] || MARKS.subject}</span>
      <span class="tile-kicker">${esc(kicker)}</span>
      <span class="tile-title">${esc(title)}</span>
      <span class="tile-count">${esc(count)}</span>
      <span class="tile-sub">${esc(subtitle)}</span>
    </button>
  `;
}

function bindTiles() {
  const coarse = window.matchMedia("(pointer: coarse)").matches;
  stage.querySelectorAll(".tile").forEach((button) => {
    button.addEventListener("click", () => {
      if (coarse && !button.classList.contains("is-open")) {
        stage.querySelectorAll(".tile").forEach((other) => other.classList.remove("is-open"));
        button.classList.add("is-open");
        return;
      }
      location.hash = button.dataset.href;
    });
  });
}

async function paintTable(hierarchy, node) {
  const key = `${hierarchy}/${node}`;
  if (!state.filters[key]) {
    state.filters[key] = { q: "", access: null, resource: null, from: "", to: "", sort: "title_asc", page: 1 };
  }
  const filters = state.filters[key];
  stage.innerHTML = `<p class="stage-loading">Loading projects…</p>`;
  const params = new URLSearchParams();
  if (hierarchy && node) {
    params.set("hierarchy", hierarchy);
    params.set("node", node);
  }
  params.set("page", String(filters.page || 1));
  params.set("page_size", "25");
  if (filters.q) params.set("q", filters.q);
  if (filters.access) params.set("access", filters.access.size ? [...filters.access].join(",") : "__none__");
  if (filters.resource) params.set("resource", filters.resource.size ? [...filters.resource].join(",") : "__none__");
  if (filters.from) params.set("published_from", filters.from);
  if (filters.to) params.set("published_to", filters.to);
  params.set("sort", filters.sort);
  try {
    state.table = await fetch("/api/projects?" + params.toString()).then(readJson);
  } catch (error) {
    stage.innerHTML = `<p class="error">${esc(error.message)}</p>`;
    return;
  }
  if (!filters.access) filters.access = new Set(state.table.access_policies);
  if (!filters.resource) filters.resource = new Set(state.table.resource_types);
  const door = hierarchy ? state.catalog.doors.find((item) => item.id === hierarchy) : null;
  const nodeLabel = node ? labelFor(node) : "Full project list";
  const levelBack = tableBack(hierarchy, node, door);
  stage.innerHTML = `
    ${crumbs([
      { label: "Explore", href: "#/explore" },
      hierarchy ? { label: door.label, href: `#/level/${hierarchy}` } : null,
      { label: nodeLabel },
    ].filter(Boolean))}
    <div class="crumb">
      <button type="button" id="back-level">Back</button>
    </div>
    <h1>${esc(nodeLabel)}</h1>
    <p class="lede">${state.table.total} projects in this view.</p>
    <form class="filters" id="filters">
      <label><span>Search</span><input name="q" value="${esc(filters.q)}" placeholder="Title, description, or topic" /></label>
      <label><span>Sort</span>
        <select name="sort">
          ${option("title_asc", "Title A–Z", filters.sort)}
          ${option("title_desc", "Title Z–A", filters.sort)}
          ${option("newest", "Newest", filters.sort)}
          ${option("oldest", "Oldest", filters.sort)}
          ${option("largest", "Largest", filters.sort)}
          ${option("smallest", "Smallest", filters.sort)}
        </select>
      </label>
      <label><span>From</span><input type="date" name="from" value="${esc(filters.from)}" /></label>
      <label><span>To</span><input type="date" name="to" value="${esc(filters.to)}" /></label>
    </form>
    <div class="check-set">
      <strong>Who can use it</strong>
      <div class="check-row" id="access-checks">
        ${state.table.access_policies.map((name) => check("access", name, filters.access.has(name))).join("")}
      </div>
    </div>
    <div class="check-set">
      <strong>Listing kind</strong>
      <div class="check-row" id="resource-checks">
        ${state.table.resource_types.map((name) => check("resource", name, filters.resource.has(name))).join("")}
      </div>
    </div>
    <div class="table-wrap" style="margin-top:0.8rem">
      ${state.table.projects.length ? tableHtml(state.table.projects) : `<p class="empty">Nothing in this group matches the filters.</p>`}
    </div>
    ${pagerHtml(state.table)}
  `;
  document.getElementById("back-level").addEventListener("click", () => { location.hash = levelBack; });
  document.getElementById("filters").addEventListener("change", () => saveFilters(key));
  document.getElementById("filters").addEventListener("submit", (event) => { event.preventDefault(); saveFilters(key); });
  document.querySelector("#filters input[name=q]").addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); saveFilters(key); }
  });
  stage.querySelectorAll(".check-row input").forEach((input) => {
    input.addEventListener("change", () => saveFilters(key));
  });
  stage.querySelectorAll(".row").forEach((row) => {
    row.addEventListener("click", (event) => {
      if (event.target.closest("a")) return;
      location.hash = projectHash(row.dataset.slug, currentPlace());
    });
  });
  const prev = document.getElementById("page-prev");
  const next = document.getElementById("page-next");
  if (prev) prev.addEventListener("click", () => saveFilters(key, (filters.page || 1) - 1));
  if (next) next.addEventListener("click", () => saveFilters(key, (filters.page || 1) + 1));
}

function saveFilters(key, page) {
  const form = document.getElementById("filters");
  const data = new FormData(form);
  const access = new Set([...stage.querySelectorAll("#access-checks input:checked")].map((input) => input.value));
  const resource = new Set([...stage.querySelectorAll("#resource-checks input:checked")].map((input) => input.value));
  state.filters[key] = {
    q: String(data.get("q") || ""),
    access,
    resource,
    from: String(data.get("from") || ""),
    to: String(data.get("to") || ""),
    sort: String(data.get("sort") || "title_asc"),
    page: page || 1,
  };
  const hash = location.hash;
  history.replaceState(null, "", hash);
  if (hash === "#/all") paintTable("", "");
  else paintTable(...hash.slice(8).split("/"));
}

function pagerHtml(table) {
  const page = table.page || 1;
  const size = table.page_size || 25;
  const start = table.total ? (page - 1) * size + 1 : 0;
  const end = Math.min(page * size, table.total || 0);
  return `<div class="pager">
    <button type="button" id="page-prev" ${page <= 1 ? "disabled" : ""}>Previous</button>
    <span>${start}–${end} of ${table.total}</span>
    <button type="button" id="page-next" ${page >= (table.page_count || 1) ? "disabled" : ""}>Next</button>
  </div>`;
}

function tableHtml(projects) {
  return `<table>
    <thead><tr><th>Title</th><th>Access</th><th>Published</th><th>Size</th><th>Kind</th><th></th></tr></thead>
    <tbody>
      ${projects.map((project) => `
        <tr class="row" data-slug="${esc(project.slug)}" tabindex="0">
          <td class="title-cell">${esc(project.title)}<span class="desc">${esc(project.short_description || "—")}</span></td>
          <td><span class="badge ${esc(badgeClass(project.access_policy))}">${esc(project.access_policy)}</span></td>
          <td>${esc(project.publish_date)}</td>
          <td>${esc(project.size_label)}</td>
          <td>${esc(project.resource_type)}</td>
          <td><a href="${esc(project.source_url)}" target="_blank" rel="noreferrer">PhysioNet</a></td>
        </tr>
      `).join("")}
    </tbody>
  </table>`;
}

async function paintProject(slug, place) {
  stage.innerHTML = `<p class="stage-loading">Opening project…</p>`;
  try {
    state.project = await fetch("/api/projects/" + encodeURIComponent(slug)).then(readJson);
  } catch (error) {
    stage.innerHTML = `<p class="error">${esc(error.message)}</p>`;
    return;
  }
  const project = state.project;
  const here = place && place.hierarchy ? place : { hierarchy: "", node: "" };
  if (here.hierarchy) rememberPlace(slug, here);
  const theme = (project.subject && project.subject[0]) || (project.data_form && project.data_form[0]) || "subject";
  stage.innerHTML = `
    ${trailCrumbs(here, [{ label: project.title }])}
    <div class="crumb"><button type="button" id="back-project">Back</button></div>
    <article class="hero" data-theme="${esc(theme)}">
      <span class="mark" aria-hidden="true">${MARKS[theme] || MARKS.subject}</span>
      <p class="tile-kicker">${esc(project.resource_type)} · v${esc(project.version)}</p>
      <h1>${esc(project.title)}</h1>
      <p>${esc(project.short_description || "No short description in the catalog.")}</p>
      <div class="chips">
        ${chips(project.subject, project.subject_labels, "subject")}
        ${chips(project.data_form, project.data_form_labels, "data_form")}
      </div>
    </article>
    <div class="meta-grid">
      ${meta("Access", project.access_policy)}
      ${meta("Published", project.publish_date)}
      ${meta("Size", project.size_label)}
      ${meta("Listing", project.resource_type)}
      ${project.core_doi ? meta("Core DOI", project.core_doi) : ""}
      ${project.version_doi ? meta("Version DOI", project.version_doi) : ""}
    </div>
    <p><a href="${esc(project.source_url)}" target="_blank" rel="noreferrer">Open the official PhysioNet page</a></p>
    ${project.topics && project.topics.length ? `<p class="note">Topics: ${esc(project.topics.join(", "))}</p>` : ""}
    <div class="actions">
      ${project.actions.map((action) => actionButton(action)).join("")}
    </div>
  `;
  document.getElementById("back-project").addEventListener("click", () => {
    if (here.hierarchy) location.hash = listHash(here);
    else history.back();
  });
  stage.querySelectorAll(".chip").forEach((button) => {
    button.addEventListener("click", () => {
      location.hash = `#/table/${button.dataset.hierarchy}/${button.dataset.node}`;
    });
  });
  stage.querySelectorAll(".action").forEach((button) => {
    button.addEventListener("click", () => startRun(project.slug, button.dataset.action));
  });
}

async function startRun(slug, actionId) {
  const button = stage.querySelector(`[data-action="${actionId}"]`);
  if (button) button.disabled = true;
  try {
    const payload = await fetch("/api/runs").then(readJson);
    state.runs = payload.runs || [];
    const previous = state.runs.find((run) => run.slug === slug && run.action_id === actionId);
    const active = state.runs.filter((run) => run.status === "running" || run.status === "stopping").length;
    if (previous) {
      const choice = await askAboutPrevious(previous, active);
      if (choice === "open") {
        location.hash = "#/run/" + previous.id;
        return;
      }
      if (choice !== "rerun") {
        if (button) button.disabled = false;
        return;
      }
    }
    if (active >= 2) {
      throw new Error("Two agent jobs are already running. Wait for one to finish, or stop one, before starting another.");
    }
    const run = await fetch("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slug, action_id: actionId }),
    }).then(readJson);
    state.currentRunId = run.id;
    location.hash = "#/run/" + run.id;
    refreshRuns();
  } catch (error) {
    if (button) button.disabled = false;
    stage.insertAdjacentHTML("beforeend", `<p class="error">${esc(error.message)}</p>`);
  }
}

function askAboutPrevious(previous, active) {
  const inFlight = previous.status === "running" || previous.status === "stopping";
  const crowded = !inFlight && active >= 2;
  return new Promise((resolve) => {
    const root = document.createElement("div");
    root.className = "modal-back";
    const again = inFlight || crowded
      ? ""
      : `<button type="button" data-choice="rerun">Run it again</button>`;
    const note = crowded
      ? `<p class="note">Two agent jobs are already running, so this one cannot start until one of them stops.</p>`
      : "";
    const lead = inFlight
      ? `${esc(previous.action_label)} is already running for this dataset.`
      : `${esc(previous.action_label)} has already run for this dataset.`;
    const statusLine = inFlight
      ? `The status is ${esc(previous.status)}.`
      : `Last time the status was “${esc(previous.status)}”.`;
    root.innerHTML = `
      <div class="modal" role="dialog" aria-modal="true">
        <h2>${lead}</h2>
        <p>${statusLine}</p>
        ${note}
        <div class="modal-actions">
          <button type="button" class="primary" data-choice="open">Take me to the report</button>
          ${again}
          <button type="button" class="text-btn" data-choice="cancel">Cancel</button>
        </div>
      </div>
    `;
    document.body.appendChild(root);
    let settled = false;
    const done = (choice) => {
      if (settled) return;
      settled = true;
      window.removeEventListener("hashchange", onHash);
      root.remove();
      resolve(choice);
    };
    const onHash = () => done("cancel");
    window.addEventListener("hashchange", onHash);
    root.querySelectorAll("[data-choice]").forEach((button) => {
      button.addEventListener("click", () => done(button.dataset.choice));
    });
    root.addEventListener("click", (event) => {
      if (event.target === root) done("cancel");
    });
  });
}

async function stopRun(id, button) {
  button.disabled = true;
  try {
    state.run = await fetch("/api/runs/" + encodeURIComponent(id) + "/stop", { method: "POST" }).then(readJson);
    stage.dataset.sig = "";
    paintRunView();
    refreshRuns();
  } catch (error) {
    button.disabled = false;
    stage.insertAdjacentHTML("beforeend", `<p class="error">${esc(error.message)}</p>`);
  }
}

async function paintRun(id) {
  state.currentRunId = id;
  if (!state.run || state.run.id !== id) {
    stage.innerHTML = `<p class="stage-loading">Loading run…</p>`;
    try {
      state.run = await fetch("/api/runs/" + encodeURIComponent(id)).then(readJson);
    } catch (error) {
      stage.innerHTML = `<p class="error">${esc(error.message)}</p>`;
      return;
    }
    paintNav();
  }
  paintRunView();
}

function paintRunView() {
  if (!state.run) return;
  const signature = `${state.run.id}:${state.run.status}:${(state.run.steps || []).length}:${(state.run.result && state.run.result.summary) || ""}`;
  if (stage.dataset.sig === signature && stage.querySelector("#run-body")) return;
  stage.dataset.sig = signature;
  paintRunBody();
  refreshLog(state.run.id);
}

let openPlan = new Set();

async function refreshLog(id) {
  if (!document.querySelector(".plan-fold") || !id) return;
  try {
    const response = await fetch("/api/runs/" + encodeURIComponent(id) + "/log");
    if (!response.ok) return;
    fillStepLogs(await response.text());
  } catch (_error) {
    /* The next poll retries. */
  }
}

function parseLog(text) {
  const buckets = {};
  for (const raw of String(text || "").split("\n")) {
    if (!raw.trim()) continue;
    const parts = raw.split("\t");
    if (parts.length >= 3 && /^\d{2}:\d{2}:\d{2}$/.test(parts[0])) {
      const step = parts[1];
      buckets[step] = buckets[step] || [];
      buckets[step].push(`${parts[0]}  ${parts.slice(2).join(" ")}`);
    } else {
      buckets.run = buckets.run || [];
      buckets.run.push(raw);
    }
  }
  return buckets;
}

function fillStepLogs(text) {
  const buckets = parseLog(text);
  document.querySelectorAll(".plan-fold").forEach((fold) => {
    const ids = (fold.dataset.steps || "").split(",").filter(Boolean);
    const lines = ids.flatMap((id) => buckets[id] || []);
    const box = fold.querySelector(".plan-log");
    if (!box) return;
    const next = logListHtml(lines);
    if (box.innerHTML !== next) {
      const nearEnd = box.scrollHeight - box.scrollTop - box.clientHeight < 24;
      box.innerHTML = next;
      if (nearEnd) box.scrollTop = box.scrollHeight;
    }
    const live = fold.querySelector(".plan-live");
    if (live && fold.dataset.state === "now") {
      live.textContent = lines.length ? briefLogLine(lines[lines.length - 1]) : "Working.";
    }
  });
}

function logListHtml(lines) {
  const rows = condenseLog(lines);
  if (!rows.length) return `<p class="note">No lines for this step yet.</p>`;
  return `<ul class="log-lines">${rows.map((row) => `<li><time>${esc(row.time)}</time><span>${esc(row.text)}</span></li>`).join("")}</ul>`;
}

function condenseLog(lines) {
  const rows = [];
  for (const line of lines) {
    const time = (line.match(/^(\d{2}:\d{2})/) || ["", ""])[1];
    const text = line.replace(/^\d{2}:\d{2}:\d{2}\s+/, "");
    if (/^AI Overview for /.test(text)) continue;
    if (/^AI Overview failed/.test(text)) {
      rows.push({ time, text: "The overview request timed out." });
      continue;
    }
    const judgement = text.match(/^Judgement for [“"](.+?)[”"]: (true|false|unanswered)/);
    if (judgement) {
      const verdict = { true: "uses the dataset", false: "does not use the dataset", unanswered: "no overview came back" }[judgement[2]];
      rows.push({ time, text: `${clipTitle(judgement[1])} — ${verdict}` });
      continue;
    }
    const waiting = text.match(/^Waiting for the AI Overview of [“"](.+?)[”"]/);
    if (waiting) {
      rows.push({ time, text: `Waiting for an overview of ${clipTitle(waiting[1])}` });
      continue;
    }
    const action = text.match(/^(.+): ((?:Waiting|Scholar cache|paper page|read a PDF|PDF |sections |The model|usage ).*)$/);
    if (action && action[1].length > 48) {
      const rest = action[2].length > 120 ? `${action[2].slice(0, 117)}…` : action[2];
      rows.push({ time, text: `${clipTitle(action[1])} — ${rest}` });
      continue;
    }
    rows.push({ time, text: text.length > 160 ? `${text.slice(0, 157)}…` : text });
  }
  let previous = "";
  return rows.map((row) => {
    const parts = row.text.split(" — ");
    if (parts.length > 1 && parts[0] === previous) {
      return { time: row.time, text: parts.slice(1).join(" — ") };
    }
    if (parts.length > 1) previous = parts[0];
    return row;
  });
}

function clipTitle(title) {
  const text = String(title || "A paper");
  return text.length > 64 ? `${text.slice(0, 61)}…` : text;
}

function briefLogLine(line) {
  const text = line.replace(/^\d{2}:\d{2}:\d{2}\s+/, "");
  if (text.startsWith("Waiting")) return text;
  const judgement = text.match(/^Judgement for .+?: (true|false|unanswered)/);
  if (judgement) return `Judgement: ${judgement[1]}`;
  return text.length > 160 ? `${text.slice(0, 157)}…` : text;
}

function paintRunBody() {
  const run = state.run;
  if (!run) return;
  openPlan = new Set([...document.querySelectorAll("#run-body .plan-fold[open]")].map((el) => el.dataset.steps));
  const groups = (run.result && run.result.groups) || [];
  const report = run.result && run.result.report;
  const inProgress = run.status === "running";
  const trace = planBlock(run);
  const findings = report
    ? reportHtml(report)
    : (run.result && run.result.summary ? `<p>${esc(run.result.summary)}</p>` : "");
  const findingsFirst = (run.action_id === "published" || run.action_id === "resources") && !inProgress;
  const activity = !trace
    ? ""
    : (findingsFirst
      ? `<details class="audit"><summary>Activity</summary>${trace}</details>`
      : trace);
  const body = findingsFirst ? `${findings}${activity}` : `${activity}${findings}`;
  stage.innerHTML = `
    <div id="run-body">
      ${trailCrumbs(storedPlace(run.slug), [
        { label: run.project_title, href: projectHash(run.slug, storedPlace(run.slug)) },
        { label: run.action_label },
      ])}
      <div class="crumb"><button type="button" id="back-run">Back to project</button></div>
      <div class="run-head">
        <p class="kicker">${esc(run.action_label)}</p>
        <h1>${esc(run.project_title)}</h1>
        <div class="status-row">
          <p class="status ${esc(run.status)}"><i></i>${esc(run.status)}</p>
          ${runControl(run)}
        </div>
      </div>
      ${run.error ? `<p class="error">${esc(run.error)}</p>` : ""}
      ${body}
      ${run.action_id === "published" || run.action_id === "resources" ? "" : `<div class="steps">
        ${(run.steps || []).map((step, index) => `
          <article class="step">
            <h3>${index + 1}. ${esc(step.title)}</h3>
            <p>${esc(step.why || "")}</p>
            ${step.query ? `<p class="query">${esc(engineLabel(step.engine))}: ${esc(step.query)}</p>` : ""}
            ${stepRecords(step)}
          </article>
        `).join("") || `<p class="empty">${inProgress ? "Finished steps will show up here." : "No steps were recorded."}</p>`}
      </div>`}
      ${report ? "" : groups.map((group) => `
        <section class="group">
          <h3>${esc(group.heading)}</h3>
          ${(group.items || []).map(itemHtml).join("") || `<p class="empty">Nothing in this group.</p>`}
        </section>
      `).join("")}
    </div>
  `;
  document.getElementById("back-run").addEventListener("click", () => {
    location.hash = projectHash(run.slug, storedPlace(run.slug));
  });
  const stop = document.getElementById("stop-run");
  if (stop) stop.addEventListener("click", () => stopRun(run.id, stop));
}

function runControl(run) {
  if (run.status === "running") {
    return `<button class="download stop" id="stop-run" type="button">Stop</button>`;
  }
  if (run.status === "stopping") {
    return `<span class="download is-waiting">Stopping…</span>`;
  }
  return `<a class="download" href="/api/runs/${esc(run.id)}/report">Download HTML report</a>`;
}

const AGENT_PLAN = {
  published: [
    { id: "page_citations", label: "Read the citations on the project page" },
    { id: "seed_resource", also: ["seed_original"], label: "Look up the resource and the original publication on Scholar" },
    { id: "citing_resource", also: ["citing_original", "candidates"], label: "Collect the papers that cite them" },
    { id: "usage_cards", logs: ["classify"], label: "Read each citing paper" },
    { id: "insights", label: "Assemble the usage report" },
  ],
  resources: [
    { id: "profile_seed", label: "Read this resource" },
    { id: "catalog_peers", label: "Find resources in this catalog" },
    { id: "web_queries", label: "Search the web" },
    { id: "read_pages", label: "Read pages outside PhysioNet" },
    { id: "compare", label: "Assemble the comparison" },
  ],
};

function planHtml(run) {
  const plan = AGENT_PLAN[run.action_id];
  if (!plan) return "";
  const steps = run.steps || [];
  const byId = Object.fromEntries(steps.map((step) => [step.id, step]));
  const skipped = skippedPlanIds(byId);
  const failed = run.status === "failed" || run.status === "interrupted" || run.status === "stopped";
  const inFlight = run.status === "running" || run.status === "stopping";
  let markedBreak = false;
  const rows = plan.map((item) => {
    const ids = [item.id, ...(item.also || [])];
    const logIds = [...ids, ...(item.logs || [])];
    const active = ids.filter((id) => !skipped.has(id));
    const finished = active.length > 0 && active.every((id) => (item.virtual ? Boolean(run.result && run.result.summary) : byId[id]));
    let state = "later";
    if (!active.length) state = "skipped";
    else if (finished) state = "done";
    else if (!markedBreak) {
      state = failed ? "failed" : (inFlight ? "now" : "later");
      markedBreak = true;
    } else if (failed) state = "idle";
    const reason = planNote(ids, byId, skipped);
    const primaryWhy = (byId[item.id] && byId[item.id].why) || "";
    const reportCounts = run.result && run.result.report && run.result.report.counts;
    const counted = item.id === "insights" && state === "done" && reportCounts && reportCounts.candidates
      ? usageSentence(reportCounts)
      : "";
    const summary = counted || (state === "done"
      ? [primaryWhy, reason].filter((text, index, all) => text && all.indexOf(text) === index).join(" ")
      : (reason || (item.when && state !== "done" ? item.when : "")));
    const logKey = logIds.join(",");
    const open = state === "now" || openPlan.has(logKey) ? " open" : "";
    const live = state === "now" ? `<span class="plan-live">${run.status === "stopping" ? "Stopping." : "Working."}</span>` : "";
    const note = state === "done" && summary ? `<p class="plan-note">${esc(shortText(summary, 140))}</p>` : "";
    return `<li class="plan-${state}"><details class="plan-fold" data-steps="${esc(logKey)}" data-state="${esc(state)}"${open}>
      <summary><span class="plan-mark">${esc(planMark(state))}</span><span class="plan-label">${esc(item.label)}</span>${live}</summary>
      ${note}
      <div class="plan-log"><p class="note">No lines for this step yet.</p></div>
    </details></li>`;
  });
  return `<ol class="plan" aria-label="Sequence for this agent">${rows.join("")}</ol>`;
}

function planBlock(run) {
  if (!AGENT_PLAN[run.action_id]) return "";
  const show = run.action_id === "published" || run.action_id === "resources" || ["running", "stopping", "failed", "interrupted", "stopped"].includes(run.status);
  if (!show) return "";
  return planHtml(run);
}

function shortText(text, limit) {
  const clean = String(text || "").replace(/\s+/g, " ").trim();
  return clean.length > limit ? `${clean.slice(0, limit - 1)}…` : clean;
}

function planNote(ids, byId, skipped) {
  for (const id of ids) {
    if (!skipped.has(id)) continue;
    const why = byId[id] && byId[id].why;
    return why || skipFallback(id);
  }
  return "";
}

function skipFallback(id) {
  if (id === "citing_original" || id === "seed_original") return "The original publication has no citation trail, so that search was skipped.";
  return "This step was skipped.";
}

function skippedPlanIds(byId) {
  const skipped = new Set();
  const original = byId.seed_original;
  if (original && !(original.items || []).length) skipped.add("citing_original");
  return skipped;
}

function planMark(state) {
  if (state === "now") return "Now";
  if (state === "done") return "Done";
  if (state === "skipped") return "Skipped";
  if (state === "failed") return "Failed";
  if (state === "idle") return "Not started";
  return "Later";
}

function engineLabel(engine) {
  if (engine === "google") return "Web search";
  if (engine === "google_scholar") return "Scholar";
  if (engine === "catalog") return "This catalog";
  return engine || "Search";
}

function stepRecords(step) {
  const items = step.items || [];
  if (!items.length) {
    const note = emptyStepNote(step);
    return note ? `<p class="note">${esc(note)}</p>` : "";
  }
  const shown = items.slice(0, 4).map(itemHtml).join("");
  const more = items.length > 4 ? `<p class="note">Showing 4 of ${items.length}.</p>` : "";
  return `<p class="note">${items.length} ${items.length === 1 ? "record" : "records"} from this step.</p>${shown}${more}`;
}

function emptyStepNote(step) {
  const id = step.id || "";
  if (id === "web_decision" && !String(step.query || "").trim()) {
    return "The catalog list was enough, so no web search was run.";
  }
  if (id === "web_decision") {
    return "This step only chooses the query. The records are in the next step.";
  }
  if (id === "intro_overview" || id === "similar_overview" || id === "challenge_overview" || id === "trace_overview") {
    return "";
  }
  if (id === "intro_candidate" || id === "challenge_candidate" || id === "trace_candidate" || id === "seed") {
    return "";
  }
  if (id === "paper_reads") return "No citing page could be read.";
  if (id === "scholar_search") return "Scholar returned no papers for this query.";
  if (id === "web_search") return "The web search returned no pages outside PhysioNet.";
  if (id === "cites") return "No citing papers came back.";
  if (id === "catalog_similar") return "No other project in this catalog shares a subject, data form, or topic.";
  if (id === "trace_catalog") return "No other catalog project was named in the retrieved text.";
  return "This search returned nothing.";
}

function reportHtml(report) {
  if (report.kind === "resources") return resourcesReport(report);
  if (report.empty) {
    return `
      <section class="report">
        <p class="kicker">Dataset usage</p>
        <h2>No published records yet</h2>
        <p>${esc(report.notice || "No published papers that cite this dataset were found.")}</p>
        <article class="resume">
          <h3>What this dataset is</h3>
          <p>${esc(report.dataset_summary || "")}</p>
        </article>
      </section>
    `;
  }
  const counts = report.counts || {};
  const papers = report.papers || [];
  const used = papers.filter((paper) => paper.card);
  const tally = {
    users: counts.users || used.length || 0,
    candidates: counts.candidates || papers.length || 0,
    other: counts.other ?? papers.filter((paper) => !paper.card && paper.usage_class !== "unclear").length,
    unclear: counts.unclear ?? papers.filter((paper) => !paper.card && paper.usage_class === "unclear").length,
  };
  const sentence = usageSentence(tally);
  const source = report.source_url
    ? `<p class="note"><a href="${esc(report.source_url)}">PhysioNet project page</a>${(report.dois || []).map((doi) => ` · <a href="https://doi.org/${esc(doi)}">DOI ${esc(doi)}</a>`).join("")}</p>`
    : "";
  const grouped = paperGroups(papers);
  const usedBlock = grouped.used.length
    ? `<h2>Used this dataset</h2><div class="papers">${grouped.used.map(paperRow).join("")}</div>${insightBlock(report)}`
    : `<p class="note">No confirmed usage found, so no insights were generated.</p>`;
  const otherBlock = grouped.other.length
    ? `<h2>Does not use it</h2><div class="papers">${grouped.other.map(paperRow).join("")}</div>`
    : "";
  const unreadBlock = grouped.unread.length
    ? `<h2>Could not be read</h2><div class="papers">${grouped.unread.map(paperRow).join("")}</div>`
    : "";
  return `
    <section class="report">
      ${source}
      <h2>${esc(sentence)}</h2>
      ${usageBar(tally)}
      <p class="note">Retrieved ${esc(report.retrieved_on || "")}. ${esc(report.method || "")}</p>
      ${usedBlock}
      ${otherBlock}
      ${unreadBlock}
    </section>
  `;
}

function paperGroups(papers) {
  const used = [];
  const other = [];
  const unread = [];
  papers.forEach((paper) => {
    if (paper.card) used.push(paper);
    else if (paper.usage_class === "unclear" || paper.label === "Could not be read") unread.push(paper);
    else other.push(paper);
  });
  return { used, other, unread };
}

function insightBlock(report) {
  const insights = report.insights || {};
  const rows = [
    ["Research tasks", insights.research_tasks],
    ["Methods", insights.methods_and_models],
    ["Setups", insights.setups_and_findings],
  ].filter(([, text]) => text && !String(text).toLowerCase().startsWith("no usage"));
  if (!rows.length) return "";
  return `<h2>Across these papers</h2>${rows.map(([label, text]) => `<p><strong>${esc(label)}</strong> ${esc(text)}</p>`).join("")}`;
}

function usageSentence(counts) {
  const users = counts.users || 0;
  const total = counts.candidates || 0;
  const other = counts.other || 0;
  const unclear = counts.unclear || 0;
  const papers = total === 1 ? "paper" : "papers";
  const lead = `${users} of ${total} ${papers} can be found to use this dataset`;
  const verb = other === 1 ? "does not" : "do not";
  if (other && unclear) return `${lead} whereas ${other} ${verb} use it, and ${unclear} could not be read.`;
  if (other) return `${lead} whereas ${other} ${verb} use it.`;
  if (unclear) return `${lead}, and ${unclear} could not be read.`;
  return `${lead}.`;
}

function usageBar(counts) {
  const parts = [
    ["used", counts.users || 0, "can be found to use it"],
    ["other", counts.other || 0, (counts.other || 0) === 1 ? "does not use it" : "do not use it"],
    ["miss", counts.unclear || 0, "could not be read"],
  ].filter((part) => part[1] > 0);
  if (!parts.length) return "";
  const bar = parts.map(([kind, count]) => `<span class="split-${kind}" style="flex:${count} 1 0"></span>`).join("");
  const key = parts.map(([kind, count, label]) => `<li><i class="split-${kind}"></i><strong>${count}</strong> ${esc(label)}</li>`).join("");
  return `<div class="usage-split"><div class="split-bar" aria-hidden="true">${bar}</div><ul class="split-key">${key}</ul></div>`;
}

function resourcesReport(report) {
  const seed = report.seed || {};
  const chips = [seed.kind, seed.access, ...(seed.subjects || []), ...(seed.forms || [])].filter(Boolean);
  const soft = [
    (seed.modality || []).length ? `Modality: ${seed.modality.join(", ")}` : "",
    (seed.tasks || []).length ? `Task: ${seed.tasks.join(", ")}` : "",
    seed.population ? `Population: ${seed.population}` : "",
  ].filter(Boolean);
  const sections = [
    ["In this catalog", similarCards(report.catalog), "No similar resource in this catalog."],
    ["Outside PhysioNet", similarCards(report.outside), "No similar page outside PhysioNet."],
  ];
  if ((report.family || []).length) sections.push(["Related on this page", report.family, ""]);
  return `
    <section class="report">
      <article class="usage-card seed-card">
        <p class="kicker">This resource</p>
        <h3>${esc(seed.title || "")}</h3>
        ${seed.url ? `<p class="note"><a href="${esc(seed.url)}">PhysioNet project page</a></p>` : ""}
        <p class="pills">${chips.map((item) => `<span class="pill">${esc(item)}</span>`).join("")}</p>
        ${soft.length ? `<p>${esc(soft.join(" · "))}</p>` : ""}
      </article>
      <h2>${esc(report.summary || "")}</h2>
      <p class="note">${esc(report.method || "")}</p>
      ${sections.map(([heading, cards, empty]) => resourceSection(heading, cards, empty)).join("")}
    </section>
  `;
}

function resourceSection(heading, cards, empty) {
  const body = cards.length
    ? cards.map(resourceCard).join("")
    : (empty ? `<p class="note">${esc(empty)}</p>` : "");
  return `<h2>${esc(heading)}</h2>${body}`;
}

function similarCards(cards) {
  return (cards || []).filter((card) => (card.dimensions || []).some((item) => item.verdict === "same"));
}

function resourceCard(card) {
  const kind = card.kind ? `<span class="badge">${esc(card.kind)}</span>` : "";
  const access = card.access ? `<p class="note">${esc(card.access)}</p>` : "";
  const why = card.relation === "peer" && card.why
    ? `<p class="why"><span>Insight</span> ${esc(card.why)}</p>`
    : (card.why ? `<p class="why">${esc(card.why)}</p>` : "");
  const title = card.link
    ? `<a href="${esc(card.link)}" target="_blank" rel="noreferrer">${esc(card.title || "Untitled")}</a>`
    : esc(card.title || "Untitled");
  return `
    <article class="usage-card">
      <div class="paper-top"><h3>${title}</h3>${kind}</div>
      ${access}
      ${dimensionPills(card.dimensions)}
      ${why}
    </article>
  `;
}

function dimensionPills(dimensions) {
  const items = (dimensions || []).filter((item) => item.field && item.verdict !== "unknown");
  if (!items.length) return "";
  return `<p class="pills">${items.map((item) => {
    const verdict = item.verdict || "";
    const label = verdict ? `${verdict.charAt(0).toUpperCase()}${verdict.slice(1)} ${String(item.field || "").toLowerCase()}` : item.field;
    return `<span class="pill ${esc(verdict)}">${esc(label)}</span>`;
  }).join("")}</p>`;
}

function paperRow(paper) {
  const kind = paper.card ? "yes" : (paper.usage_class === "unclear" ? "miss" : "no");
  const detail = paper.card ? discoveryBody(paper.card) : (paperReason(paper) ? `<p>${esc(paperReason(paper))}</p>` : "");
  return `
    <article class="usage-card">
      <div class="paper-top">
        <h3>${paperTitle(paper)}</h3>
        <span class="badge ${kind}">${esc(paperVerdict(paper))}</span>
      </div>
      ${paperMeta(paper) ? `<p class="note">${paperMeta(paper)}</p>` : ""}
      ${detail}
    </article>
  `;
}

function paperVerdict(paper) {
  if (paper.card) return "Used this dataset";
  if (paper.usage_class === "unclear") return "Could not be read";
  return "Does not use it";
}

function paperReason(paper) {
  const card = paper.card || {};
  const explore = paper.explore || {};
  if (paper.card) return card.why_explore || card.how_used || paper.why || "";
  return explore.why_open || paper.why || "";
}

function exploreItem(paper) {
  const reason = (paper.explore && paper.explore.why_open) || paper.why || "";
  const meta = paperMeta(paper);
  return `<li>${paperTitle(paper)}${meta ? `<span class="note">${meta}</span>` : ""}${reason ? `<span>${esc(reason)}</span>` : ""}</li>`;
}

function resumePaper(paper) {
  return `
    <article class="usage-card">
      <h3>${paperTitle(paper)}</h3>
      ${paperMeta(paper) ? `<p class="note">${paperMeta(paper)}</p>` : ""}
      ${discoveryBody(paper.card)}
    </article>
  `;
}

function discoveryBody(card) {
  const source = card || {};
  if (source.how_used || source.why_explore || (source.research_tasks || []).length || (source.techniques || []).length) {
    return `
      <h4>How the dataset was used</h4>
      <p>${esc(source.how_used || "")}</p>
      ${tagLine("Role", source.dataset_role)}
      ${tagLine("Task", source.research_tasks)}
      ${tagLine("Techniques", source.techniques)}
      ${source.why_explore ? `<p class="why"><span>Why explore this paper?</span> ${esc(source.why_explore)}</p>` : ""}
    `;
  }
  return cardBody(source);
}

function tagLine(label, values) {
  const items = (values || []).filter(Boolean);
  if (!items.length) return "";
  return `<p class="tagline"><span>${esc(label)}</span></p>${pillRow(items)}`;
}

function citeItem(paper) {
  const meta = paperMeta(paper);
  return `<li>${paperTitle(paper)}${meta ? `<span class="note">${meta}</span>` : ""}</li>`;
}

function pillRow(values) {
  const items = (values || []).filter(Boolean);
  if (!items.length) return `<p class="note">Not stated in the sections that were read.</p>`;
  return `<p class="pills">${items.map((item) => `<span class="pill">${esc(item)}</span>`).join("")}</p>`;
}

function citePaper(paper) {
  return `
    <article class="cite-row">
      <h3>${paperTitle(paper)}</h3>
      ${paperMeta(paper) ? `<p class="note">${paperMeta(paper)}</p>` : ""}
      <p>${esc(paper.why || paper.label || "")}</p>
    </article>
  `;
}

function paperTitle(paper) {
  return paper.link
    ? `<a href="${esc(paper.link)}" target="_blank" rel="noreferrer">${esc(paper.title || "Untitled")}</a>`
    : esc(paper.title || "Untitled");
}

function paperMeta(paper) {
  const cited = paper.cited_by_total ? `${paper.cited_by_total} citations` : "";
  return [paper.byline, cited].filter(Boolean).map(esc).join(" · ");
}

function cardBody(card) {
  const source = card || {};
  const bullets = (source.bullets || []).filter(Boolean);
  if (source.headline || bullets.length) {
    return `
      ${source.headline ? `<p class="resume-headline">${esc(source.headline)}</p>` : ""}
      ${bullets.length ? `<ul>${bullets.map((line) => `<li>${esc(line)}</li>`).join("")}</ul>` : ""}
      ${source.evidence ? `<blockquote>${esc(source.evidence)}</blockquote>` : ""}
    `;
  }
  return cardFields(source);
}

function cardFields(card) {
  const rows = [
    ["Research objective", card.research_objective],
    ["Dataset role", card.dataset_role],
    ["Methods and models", card.methods_and_models],
    ["Data used", card.data_used],
    ["Evaluation and findings", card.evaluation_and_findings],
    ["Evidence", card.evidence],
  ];
  return rows.map(([label, text]) => `<p><strong>${esc(label)}</strong> ${esc(text || "—")}</p>`).join("");
}

function itemHtml(item) {
  const slug = item.slug ? `#/project/${encodeURIComponent(item.slug)}` : "";
  const title = item.link
    ? `<a href="${esc(item.link)}" target="_blank" rel="noreferrer">${esc(item.title || "Untitled")}</a>`
    : esc(item.title || "Untitled");
  const local = slug ? ` · <a href="${esc(slug)}">Open in PhysioLens</a>` : "";
  return `<div class="result-item">${title}<span class="tag">${esc(item.label || "")}</span>${item.access ? `<span class="tag">${esc(item.access)}</span>` : ""}${local}<div class="desc">${esc(item.detail || "")}</div></div>`;
}

const AGENT_FACE = {
  resources: {
    kicker: "Similar resources",
    steps: "Read this project, compare other PhysioNet resources, then read a short list of web pages. Each card says what is the same, what differs, and what was not stated.",
    mark: `<svg viewBox="0 0 120 120" fill="none" stroke="currentColor" stroke-width="2.2"><circle cx="48" cy="58" r="22"/><circle cx="74" cy="58" r="22"/></svg>`,
  },
  published: {
    kicker: "Published research",
    steps: "PhysioNet citations, then up to 10 citing papers. Each paper is read. A usage card is written when the text shows the dataset was used.",
    mark: `<svg viewBox="0 0 120 120" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M34 28h52v64H34z"/><path d="M46 44h28M46 58h28M46 72h16"/></svg>`,
  },
};

function actionButton(action) {
  const face = AGENT_FACE[action.id] || { mark: "" };
  return `
    <button class="action" type="button" data-action="${esc(action.id)}">
      <span class="mark" aria-hidden="true">${face.mark}</span>
      <strong>${esc(action.label)}</strong>
      <p>${esc(action.description)}</p>
    </button>
  `;
}

function currentPlace() {
  const hash = location.hash || "";
  if (hash === "#/all") return { hierarchy: "all", node: "" };
  if (hash.startsWith("#/table/")) {
    const [hierarchy, node] = hash.slice(8).split("/");
    return { hierarchy: hierarchy || "", node: decodeURIComponent(node || "") };
  }
  return { hierarchy: "", node: "" };
}

function projectHash(slug, place) {
  const base = "#/project/" + encodeURIComponent(slug);
  if (!place || !place.hierarchy) return base;
  if (place.hierarchy === "all") return base + "?h=all";
  if (!place.node) return base;
  return `${base}?h=${encodeURIComponent(place.hierarchy)}&n=${encodeURIComponent(place.node)}`;
}

function parseProjectHash(hash) {
  const raw = hash.slice(10);
  const split = raw.indexOf("?");
  const slugPart = split === -1 ? raw : raw.slice(0, split);
  const params = new URLSearchParams(split === -1 ? "" : raw.slice(split + 1));
  return {
    slug: decodeURIComponent(slugPart),
    hierarchy: params.get("h") || "",
    node: params.get("n") || "",
  };
}

function rememberPlace(slug, place) {
  state.place = { slug, hierarchy: place.hierarchy || "", node: place.node || "" };
  try {
    sessionStorage.setItem("physiolens-place:" + slug, JSON.stringify(state.place));
  } catch (error) {
    /* The crumb still works for this page load. */
  }
}

function storedPlace(slug) {
  if (state.place && state.place.slug === slug) return state.place;
  try {
    const raw = sessionStorage.getItem("physiolens-place:" + slug);
    if (raw) return JSON.parse(raw);
  } catch (error) {
    /* A missing place falls back to Doors. */
  }
  return { hierarchy: "", node: "" };
}

function listHash(place) {
  if (!place || !place.hierarchy) return "#/explore";
  if (place.hierarchy === "all") return "#/all";
  if (!place.node) return "#/explore";
  return `#/table/${encodeURIComponent(place.hierarchy)}/${encodeURIComponent(place.node)}`;
}

function trailCrumbs(place, tail) {
  const items = [{ label: "Explore", href: "#/explore" }];
  if (place && place.hierarchy === "all") {
    items.push({ label: "Full project list", href: "#/all" });
  } else if (place && place.hierarchy && place.node && state.catalog) {
    const door = state.catalog.doors.find((item) => item.id === place.hierarchy);
    if (door) {
      items.push({ label: door.label, href: `#/level/${place.hierarchy}` });
      const parent = parentOf(door, place.node);
      if (parent) items.push({ label: labelFor(parent), href: `#/level/${place.hierarchy}/${parent}` });
      items.push({ label: labelFor(place.node), href: `#/table/${place.hierarchy}/${encodeURIComponent(place.node)}` });
    }
  }
  return crumbs(items.concat(tail));
}

function crumbs(items) {
  return `<nav class="crumb">${items.map((item, index) => item.href
    ? `<a href="${esc(item.href)}">${esc(item.label)}</a>${index < items.length - 1 ? "<span>/</span>" : ""}`
    : `<span>${esc(item.label)}</span>`).join(" ")}</nav>`;
}

function chips(ids, labels, hierarchy) {
  return (ids || []).map((id, index) => `
    <button class="chip" type="button" data-hierarchy="${esc(hierarchy)}" data-node="${esc(id)}">${esc(labels[index] || id)}</button>
  `).join("");
}

function meta(label, value) {
  return `<div><span>${esc(label)}</span><strong>${esc(value || "—")}</strong></div>`;
}

function check(name, value, checked) {
  return `<label><input type="checkbox" name="${esc(name)}" value="${esc(value)}" ${checked ? "checked" : ""}/> ${esc(value)}</label>`;
}

function option(value, label, current) {
  return `<option value="${esc(value)}" ${value === current ? "selected" : ""}>${esc(label)}</option>`;
}

function findNode(nodes, id) {
  for (const node of nodes) {
    if (node.id === id) return node;
    const child = findNode(node.children || [], id);
    if (child) return child;
  }
  return null;
}

function tableBack(hierarchy, node, door) {
  if (!hierarchy || !door) return "#/explore";
  const parent = parentOf(door, node);
  if (parent) return `#/level/${hierarchy}/${parent}`;
  const current = findNode(door.nodes, node);
  if (current && current.has_children) return `#/level/${hierarchy}/${node}`;
  return `#/level/${hierarchy}`;
}

function parentOf(door, id) {
  for (const node of door.nodes) {
    if ((node.children || []).some((child) => child.id === id)) return node.id;
  }
  return "";
}

function labelFor(id) {
  for (const door of state.catalog.doors) {
    const node = findNode(door.nodes, id);
    if (node) return node.label;
  }
  return id;
}

function badgeClass(access) {
  return access === "Contributor Review" ? "Contributor" : access;
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[char]));
}
