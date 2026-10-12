# PhysioLens

PhysioLens is a local browser for the [PhysioNet](https://physionet.org/) catalog, plus two agents that read past the project page.

The catalog is a JSON file on this machine. Agent runs are rows in one SQLite file. There is no database server and no accounts. Closing the browser tab does not stop a run: the server keeps writing steps after the request returns. At most two runs can be in progress at once. Stopping a run lets the paper it is already reading finish, then the run stops. The next time the server starts, a run that was still `running` or `stopping` is marked `interrupted`.

Browsing the catalog does not call the network. SerpAPI is used only when an agent run, or the manual Scholar endpoint, asks for it.

## How SerpAPI is used

SerpAPI is the only way this project reaches Google. The model does not browse. A run asks SerpAPI for a specific result set, then this server downloads the public page or PDF and asks the model to read that text.

Every call goes to `https://serpapi.com/search.json` from `apps/backend/scholar.py`. One call is one search. An empty Scholar result (`Google hasn't returned any results`) is an empty list, not a failed run. A real SerpAPI error, including a key that is out of searches, fails that search.

### 1. Published research spends searches on a citation trail

`Explore published research` (`published`) does not search the web for "papers about this dataset" and then guess. It does this:

1. Read the PhysioNet project page. Keep the resource citation and, when the page has one, the original publication. Ignore the generic PhysioNet platform citation. This step does not use SerpAPI.
2. **Google Scholar keyword search** (`engine=google_scholar`). For each kept citation, search the DOI first. If that does not match, search the title. A hit is kept when the DOI appears in the record, when it is the only hit, or when the title matches.
3. **Google Scholar cited-by search** (`engine=google_scholar` with `cites`). For each matched record that has a citation id, request the papers that cite it, 20 at a time, at most 5 pages. Each page is its own SerpAPI search. The run stops once 10 unique papers remain after the two trails are merged.
4. Download each of those papers (HTML, then one PDF if the HTML is not the paper). The model writes a usage card only when that text shows the dataset was used. A paper that does not use it gets a short reason to open it. A paper that cannot be read stays unread.

So a published run spends SerpAPI quota on resolving the one or two PhysioNet citations, then on the cited-by pages needed to fill a sample of 10 papers. It does not spend a search on every paper in the literature, and it does not treat "Scholar returned 10 hits" as the size of the literature.

### 2. Similar resources spends searches on pages outside PhysioNet

`Find similar resources` (`resources`) compares this project with other rows already in the local catalog. That comparison uses catalog fields and does not call SerpAPI.

It then runs up to four **Google web searches** (`engine=google`, 5 results each). The queries are fixed from the project: the title plus its kind (dataset, challenge, software, or model), up to two related names the project page states, and the modality or task when the page states one. PhysioNet links are dropped, because those projects are already in the catalog. At most six outside pages are kept. Each page is fetched and read. A comparison card is kept only when the two resources share a subject, a data form, a topic, a modality, a task, or a kind, and a soft field is kept only when a quote from the page supports it.

If `SERPAPI_API_KEY` is missing, this agent skips the web search and still returns the catalog comparison. The published agent cannot do its job without the key: Scholar is how it finds the citation trail.

### 3. Google AI Overview is a follow-up search, not the literature review

`google_overview()` runs a normal Google search and, when Google includes an AI Overview with a `page_token` but no text yet, a second call with `engine=google_ai_overview`. The overview is prose plus source links. Google often returns none, and that is an empty overview, not an error.

`fetch_overview()` uses that helper to ask whether one named paper actually used the dataset. `classify()` in `apps/agents/published.py` calls it. **That function is not a step in the sequence the page starts.** The running published agent reads the paper HTML or PDF instead of trusting an overview. Browsing does not call it either.

### What does not call SerpAPI

Opening the app, walking the subject or data-form tiles, filtering the table, and opening a project page all read `data/physionet_catalog.json`. Rebuilding that file calls PhysioNet, not SerpAPI.

`POST /api/scholar` is a manual Scholar search. It spends one SerpAPI search and returns the organic results. The page does not call it. `scripts/try_scholar.py` calls the same Scholar function so you can check the key before starting the server.

## Tech stack

| Piece | What it is |
| --- | --- |
| Python | 3.11 or newer. [uv](https://docs.astral.sh/uv/) installs dependencies and can install Python. |
| API | FastAPI, served by uvicorn. |
| Agents | Two fixed [LangGraph](https://langchain-ai.github.io/langgraph/) sequences. They do not choose their own tools. |
| Model | LangChain's OpenAI client. `LLM_PROVIDER=gemini` sends it to Google's OpenAI-compatible endpoint. `LLM_PROVIDER=groq` sends it to Groq. Both go through `ask()` in `apps/agents/llm.py`. |
| Search | SerpAPI, via `httpx`, only for the calls above. |
| Papers | `httpx` for HTML. `pdfplumber` for one PDF when the HTML is not the paper. |
| Storage | `data/physionet_catalog.json` and `data/runs.sqlite3`. |
| UI | `web/index.html`, `web/app.js`, and `web/app.css`. No frontend build. |

## Project structure

```
physiolens/
  apps/backend/     FastAPI app, catalog, SerpAPI, citations, paper parsing, reports
  apps/agents/      The two LangGraph agents and the shared model call
  web/              The single-page UI, served at /
  data/             Catalog JSON, SQLite runs, and per-run text logs
  scripts/          Rebuild the catalog, or try one Scholar query
  tests/            Unit tests that do not call the network
  docs/             Catalog screen contract
```

| Path | Role |
| --- | --- |
| `apps/backend/main.py` | HTTP routes. |
| `apps/backend/catalog_view.py` | Reads the seed file for the browse screens. |
| `apps/backend/catalog.py` | Builds a new seed from PhysioNet's published-project list. Used by `scripts/try_physionet.py` only. |
| `apps/backend/scholar.py` | Every SerpAPI call. |
| `apps/backend/citations.py` | Parses the citation block on a PhysioNet project page. |
| `apps/backend/paper_html.py`, `paper_pdf.py` | Turn a paper page or PDF into sections the model can read. |
| `apps/backend/store.py` | SQLite runs. Two runs at a time. |
| `apps/backend/report.py` | The downloadable HTML report. |
| `apps/agents/published.py` | Explore published research. |
| `apps/agents/resources.py` | Find similar resources. |
| `apps/agents/run.py` | Starts the graph for one saved run. |
| `apps/agents/usage.py` | Reads a paper and writes a usage card. |
| `docs/data-exploration.md` | Why the catalog has two doors, and how the seed is shaped. |

## Setup

Install uv once. After that, the project commands are the same on macOS, Linux, and Windows. Do not activate `.venv` by hand. `uv run` finds it, and the activate path is different on Windows (`.venv\Scripts\activate` instead of `source .venv/bin/activate`).

**macOS**

```bash
brew install uv
```

The official installer also works: `curl -LsSf https://astral.sh/uv/install.sh | sh`. Open a new terminal if `uv` is not found.

**Linux**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Open a new terminal if `uv` is not found.

**Windows**

In PowerShell:

```powershell
winget install --id=astral-sh.uv -e
```

Or: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`. Open a new terminal if `uv` is not found.

**Then, in this folder, on every system**

macOS and Linux:

```bash
cd physiolens
uv sync
cp .env.sample .env
```

Windows Command Prompt uses `copy .env.sample .env`. Windows PowerShell uses `Copy-Item .env.sample .env`. `uv sync` is the same command on all three. The first sync writes `uv.lock`. Commit that file when you commit dependency changes.

Edit `.env` and set the keys. Do not commit `.env`.

| Variable | Required for | Notes |
| --- | --- | --- |
| `SERPAPI_API_KEY` | Both agents, for the searches above | From [serpapi.com](https://serpapi.com/). Without it, published research fails and similar resources skips the web. |
| `OPENAI_API_KEY` | The model, when `LLM_PROVIDER=gemini` | The name stays `OPENAI_API_KEY` because the client library reads that name. A free key comes from [Google AI Studio](https://aistudio.google.com/apikey). |
| `OPENAI_MODEL` | Gemini | Default in the sample is `gemini-3.8-flash`. |
| `OPENAI_BASE_URL` | Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` |
| `LLM_PROVIDER` | Both agents | `gemini` or `groq`. |
| `GROQ_API_KEY` | The model, when `LLM_PROVIDER=groq` | From [Groq](https://console.groq.com/keys). Leave the provider as `gemini` until this is set. |
| `GROQ_MODEL` | Groq | Default `openai/gpt-oss-120b`. |

Restart the server after changing `.env`.

The catalog file is already in `data/physionet_catalog.json`. Rebuild it only when you want a fresh PhysioNet snapshot:

```bash
uv run python scripts/try_physionet.py
```

Check the SerpAPI key with one Scholar query:

```bash
uv run python scripts/try_scholar.py
uv run python scripts/try_scholar.py "MIMIC-IV mortality prediction"
```

## Run

```bash
uv run uvicorn apps.backend.main:app --reload
```

That command is the same on macOS, Linux, and Windows. Open http://127.0.0.1:8000 .

The UI is three sections: About, Explore, and Past activity. Explore starts from clinical subject or kind of data, then a project table, then a project page with the two agents.

Run the tests (they do not call SerpAPI or the model):

```bash
uv run python -m unittest discover -s tests
```

## Catalog API

`GET /api/catalog` returns the two doors, tile counts, and how many projects have no subject or no data form.

`GET /api/projects` returns one page of the table. Omit `hierarchy` and `node` for the full catalog. `hierarchy=subject&node=heart` is one group.

| Query | Meaning |
| --- | --- |
| `q` | Matches title, description, topics, and slug. |
| `access` | Comma-separated access policies. |
| `resource` | Comma-separated PhysioNet listing kinds: Database, Challenge, Software, Model. |
| `published_from`, `published_to` | `YYYY-MM-DD` bounds. |
| `sort` | `title_asc`, `title_desc`, `newest`, `oldest`, `largest`, `smallest`. |
| `page` | Default 1. |
| `page_size` | Default 25, maximum 100. |

`GET /api/projects/{slug}` is the project page, including the two actions.

## Agent API

`POST /api/runs` with `{"slug": "mitdb", "action_id": "published"}` or `"action_id": "resources"` returns immediately with status `running`. Any other `action_id` is rejected. The same project can have more than one run. The page asks before starting a second one.

| Method | Path | What it does |
| --- | --- | --- |
| `GET` | `/api/runs` | Past runs, newest first. |
| `GET` | `/api/runs/{id}` | Steps and result. |
| `GET` | `/api/runs/{id}/log` | Plain-text log for that run. |
| `GET` | `/api/runs/{id}/report` | Download the HTML report. |
| `POST` | `/api/runs/{id}/stop` | Status becomes `stopping`, then `stopped` after the current paper or step finishes. |
| `DELETE` | `/api/runs/{id}` | Delete one run and its log. |
| `DELETE` | `/api/runs` | Delete every run. |
| `POST` | `/api/scholar` | Body `{"query": "..."}`. One Scholar search. Needs `SERPAPI_API_KEY`. |

A third `POST /api/runs` while two are still running returns 409.

## Publish this repository

`git push` does not create a GitHub repository. From inside this folder, the GitHub CLI can create the repo and push it in one step. Install [GitHub CLI](https://cli.github.com/) (`brew install gh` on macOS, `winget install --id GitHub.cli` on Windows).

On the machine you are pushing from, check that git is installed and that this folder is the repository you mean:

```bash
git --version
gh --version
git status
git remote -v
git config --show-origin --get user.name
git config --show-origin --get user.email
gh auth status
```

`git status` should show a branch and should not list `.env`. `git remote -v` shows where a push would go. If `origin` already points at a different GitHub account, do not push there.

GitHub decides which account owns the new repo from the credentials in that command, not from `user.name`. `user.name` and `user.email` only set the author stored on new commits. To use another GitHub account for this terminal only, put that account's personal access token in `GH_TOKEN` and do not change global git config. Create the token on the other account at GitHub → Settings → Developer settings → Personal access tokens, with access to create repositories.

macOS and Linux, this terminal only:

```bash
export GH_TOKEN="github_pat_from_the_other_account"
gh auth status
gh repo create physiolens --private --source=. --remote=origin --push
```

`gh auth status` should name the token's account. `GH_TOKEN` overrides the account logged in on the machine, and it disappears when you close the terminal. Do not put the token in the remote URL.

Windows PowerShell, this window only:

```powershell
$env:GH_TOKEN = "github_pat_from_the_other_account"
gh auth status
gh repo create physiolens --private --source=. --remote=origin --push
```

Windows Command Prompt uses `set GH_TOKEN=github_pat_from_the_other_account` in that window only.

If `origin` already exists and points at the wrong account, pick another remote name, for example `--remote=other`. If this folder is not a git repo yet (`git status` says it is not), run `git init` and make the first commit before `gh repo create`.

If `gh repo create` says the name is taken, choose another name. `--public` instead of `--private` makes the repo public. Do that only after `git status` confirms `.env` is untracked.

A later push from this same clone is `git push`. From the other laptop, `git clone` the new URL, copy `.env` by hand (it is not in git), then `uv sync` and start the server as above.
