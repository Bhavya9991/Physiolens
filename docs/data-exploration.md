# PhysioLens data exploration

This document specifies the catalog exploration experience. It is the contract for the screens and the seed file. The two agents a project can start are described in the README. Do not invent a third browse tree, an exclusive category, or a PhysioNet "Database vs Challenge" front door.

The seed already exists at `data/physionet_catalog.json`. It is built by `uv run python scripts/try_physionet.py` from `https://physionet.org/api/v1/projects/published/`. Browse-time screens read that file. They do not call PhysioNet.

## Purpose

A person starts from a question about the subject or about the form of the data, narrows by walking a short tree of tiles, and lands on a table of matching projects. From a project they can open the PhysioNet page, read PhysioLens's own representation of that project, and start one of the two agents.

## Two ways in, and why the split exists

No single tree is the correct organization of this catalog. The product therefore offers two hierarchies. They are alternative doors, not two levels of one path.

| Door | Seed field | Question it answers |
| --- | --- | --- |
| What it is about | `subject` | Heart, brain, sleep, breathing, movement |
| What the data is | `data_form` | Signals, images, text, structured records, audio |

A project may appear under several labels in one door and under both doors. `slpdb` is heart, brain, sleep, and breathing, and its data form is signals. `mimic-cxr` is images, chest imaging, and clinical text. Membership is a list, not a single `category_path`.

These are not filters. A filter narrows a list the person already has. A hierarchy is how they start.

Filters, applied only on the project table:

| Seed field | Label in the seed | What the person does |
| --- | --- | --- |
| `access_policy` | Who can use it | Include or exclude Open, Credentialed, Restricted, Contributor Review |
| `publish_date` | When it was published | Sort, and optionally bound by a from/to date |
| `main_storage_size` | How big it is | Sort |
| `resource_type` | PhysioNet listing kind | Include or exclude Database, Challenge, Software, Model |

`resource_type` is a PhysioNet administrative fact. It must not be a tile on the opening screen. Someone looking for heart signals should see a challenge and a database in the same table, and can hide one with this filter.

`topics` is a free-text tag list. There are hundreds of distinct topics, so they are not a tree and not a fixed set of checkboxes. On the table they are a search box that matches topic text, title, and `short_description`.

Date, size, access, and listing kind can all be argued to be "categories." They stay filters because a person does not begin by browsing "files larger than 1 GB" or "published in 2019." They begin from a subject or a kind of data, then narrow.

## Seed file

Path: `data/physionet_catalog.json`.

Top-level fields:

- `source`: the PhysioNet URL the file was built from.
- `listing`: `latest version of each published project`.
- `source_rows`: number of version rows in the API payload (737 at the time of writing).
- `project_count`: number of projects in `projects` (547 at the time of writing).
- `hierarchies`: the doors and their nodes. The UI renders tiles from this array. Do not hardcode the node list.
- `filters`: the four filter fields and their labels.
- `tags`: `{ "field": "topics", "label": "Topics", "use": "search" }`.
- `projects`: one object per latest project.

Each project object:

- `slug`, `version`, `title`, `short_description`
- `resource_type`, `access_policy`
- `topics` (array of strings)
- `publish_date` (`YYYY-MM-DD`)
- `core_doi`, `version_doi` (either may be null)
- `source_url` (PhysioNet content page for this version)
- `main_storage_size` (bytes)
- `subject`: array of node ids from the subject hierarchy. May be empty.
- `data_form`: array of node ids from the data-form hierarchy. May be empty. A chest or eye image also includes the parent id `images`.

Current hierarchy, copied so this document stands alone. The file is the source of truth if the two disagree.

Subject nodes, no children: `heart`, `brain`, `sleep`, `breathing`, `movement`.

Data-form nodes: `signals`, `images` (children `chest`, `eye`), `text`, `records`, `audio`.

The labels are inferred from slug, title, and topics by `apps/backend/catalog.py`. They are not fields PhysioNet publishes. Empty arrays are allowed. Do not add an "Other" tile for projects that matched nothing. Those projects are absent from that tree. They remain in the file.

Regenerating the seed replaces the file. The running UI reads the file at startup. Browse interactions do not write it and do not refetch PhysioNet.

## How a tile decides its projects

Given the open hierarchy and a node id:

- The project is in that node when the node id is an element of `project[hierarchy.field]`.
- The tile count is the size of that set.
- Counts overlap. Do not present them as parts that add up to `project_count`.
- The table for `images` includes every project whose `data_form` contains `images`, including those that also contain `chest` or `eye`.
- The table for `chest` is the subset whose `data_form` contains `chest`.

## Screens

There are five screens. The first four are specified. The fifth is a slot.

1. Exploration start
2. Hierarchy level
3. Project table
4. Project representation
5. Agent run

The back stack is the hierarchy id plus the node ids chosen so far. The person can step back one level, or return to the two doors, without losing the fact that both doors exist.

### 1. Exploration start

The first screen is only the invitation to begin, plus two large tiles.

Each tile shows:

- The hierarchy `label` (`What it is about`, `What the data is`).
- The count of projects that have at least one label in that hierarchy. At the time of writing that is 275 and 506. Read the count from the seed. Do not hardcode it.

The tile does not show its explanation until the person goes to it.

Going to a tile means pointer hover, or keyboard focus. On a touch screen, the first tap goes to the tile and does not navigate. While the person is on a tile, a subtitle is visible. Leaving the tile hides it. The other tile's subtitle stays hidden.

Subtitles for the two doors:

- What it is about: "Start from the clinical subject. A project can sit under more than one of these."
- What the data is: "Start from the form of the data. Images can be narrowed one step further."

A click (or a second tap on the same tile, on touch) enters that hierarchy at its root. The next screen is a hierarchy level whose nodes are `hierarchies[i].nodes`.

### 2. Hierarchy level

This screen shows one level of the open hierarchy.

Chrome:

- A short title: the door label, then the labels of the nodes already chosen. Example: `What the data is / Images`.
- A control to go back one level, and a control to return to the two doors.

Body: one tile per node at this level.

Each tile shows the node `label` and the count of projects in that node. The same hover, focus, and first-tap rule reveals a subtitle. Lower-level subtitle copy is: "Opens this group." If the node has `children`, add: "It also has a narrower step."

What a click does:

- If the node has `children`, the next screen is another hierarchy level. Its tiles are those children, plus one extra tile labeled `All {node label}`. `All Images` opens the project table for the parent node. This tile exists so a project tagged `images` but not `chest` or `eye` can still be reached. It is not a seed node. It is a UI affordance.
- If the node has no `children`, the next screen is the project table for that node.

Subject nodes have no children, so the first click inside "What it is about" goes straight to a table. Data form is the hierarchy that has a second tile step, and only under Images.

Do not show an Other tile.

### 3. Project table

Shown when the person has reached a node with nowhere deeper to walk, or has chosen `All {node label}`.

The table lists only the projects in that node, then applies the table's own filters and search. Changing a filter does not change the tree and does not remove the node the person picked.

Columns, in this order:

- Title
- One-line `short_description`, truncated
- `access_policy`
- `publish_date`
- `main_storage_size`, shown in a readable unit (KB, MB, GB) and sorted by the raw byte count
- `resource_type`
- A text link "PhysioNet" whose href is `source_url`. It opens in a new browsing context. It is not the control that opens the PhysioLens representation.

Controls above the table:

- Text search over `title`, `short_description`, and `topics`.
- Access: checkboxes for the distinct `access_policy` values present in this node.
- Listing kind: checkboxes for the distinct `resource_type` values present in this node.
- Published date: sort, and an optional from/to bound.
- Size: sort.
- Title sort. This is the default, ascending.

Sorting is one column at a time. Empty results stay on this screen and say that nothing in this group matches the filters. Clearing filters restores the node’s full set.

The row itself, not the PhysioNet link, opens the project representation. The whole row is that control, except the PhysioNet link, which must not also navigate inside the app.

### 4. Project representation

PhysioLens keeps its own page for the project, keyed by `slug`. The seed holds one latest version per slug, so slug is enough.

The page shows the seed fields in readable form:

- Title, version, `short_description`
- The subject labels and data-form labels, using the human labels from `hierarchies`, not the raw ids
- Topics
- Access, publish date, size, listing kind
- `core_doi` and `version_doi` when present
- The same PhysioNet link as the table

Below that, a set of actions. The number of actions is not decided. Render the configured list. If the list is empty, the page still makes sense: it is the representation plus the outbound link, and the action area is absent rather than filled with placeholders.

Each action is:

- `id`: stable string
- `label`: short imperative shown on the control
- `description`: one sentence, visible before the person commits
- `follow_ups`: a list of action ids that may be offered after this run completes. Empty means this run is the end of the path.

Choosing an action starts an agent run. It does not navigate to another catalog level.

### 5. Agent run

An agent run is a terminal operation for the action that started it. The run receives:

- The full project object from the seed
- The door and node ids the person walked to reach the table
- The action `id`

The run ends by presenting its result. It does not silently continue into another task.

If `follow_ups` is empty, the result screen offers a way back to the project representation and no further agent actions. If `follow_ups` is not empty, the result screen offers those actions, and each of them is again a run of the same kind. Whether more options exist is a property of the action, not a global rule. The concrete tasks are intentionally unspecified.

## What this document does not decide

- The visual design: type, color, and spacing.
- The concrete agent tasks and the value of n.
- A catalog-wide search that bypasses both trees. Projects with an empty `subject` or empty `data_form` are simply missing from that tree.
- Editing the seed from the UI.
