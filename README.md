# PhysioLens

PhysioLens is a local browser for the [PhysioNet](https://physionet.org/) catalog, plus two agents that read past a project page.

You start from a clinical subject, such as heart or sleep, or from the kind of data, such as a waveform or an image. A project can sit in more than one place. From a project you can open the PhysioNet page, or start one of two agents:

- **Explore published research** reads the citations on the project page, finds papers that cite them, and reads those papers. A usage card is written only when the text shows the dataset was used.
- **Find similar resources** compares the project with other rows in this catalog, then with a short list of pages from the web.

The catalog is `data/physionet_catalog.json`. Agent runs are rows in `data/runs.sqlite3` on this machine. There is no database server and no accounts. Closing the browser tab does not stop a run. At most two runs can be in progress at once. The next time the server starts, a run that was still going is marked `interrupted`.

Browsing the catalog reads the JSON file. It does not call PhysioNet or SerpAPI.

## Contents

- [How SerpAPI is used](#how-serpapi-is-used)
- [Tech stack](#tech-stack)
- [Project structure](#project-structure)
- [Setup](#setup)
  - [macOS and Linux](#macos-and-linux)
  - [Windows](#windows)
- [Run](#run)
- [API](#api)

## How SerpAPI is used

SerpAPI is how the agents reach Google. The model does not browse. A run asks SerpAPI for a result list, then this server downloads the page or PDF and the model reads that text. Every call goes to `https://serpapi.com/search.json` from `apps/backend/scholar.py`. One call is one search.

An empty Scholar result is an empty list, not a failed run. A real SerpAPI error, including a key that is out of searches, fails that search.

**Explore published research** uses Google Scholar.

1. Read the PhysioNet project page and keep the resource citation and, when the page has one, the original publication. The generic PhysioNet platform citation is ignored. This step does not use SerpAPI.
2. Search Scholar for each citation: the DOI first, then the title if the DOI does not match.
3. For each matched record, search the papers that cite it, 20 at a time. Each page is its own search. The run stops at 10 unique papers.
4. Download those papers and read them. That download is not a SerpAPI call.

**Find similar resources** uses ordinary Google search for pages that are not on PhysioNet. The catalog comparison itself does not call SerpAPI. The agent then runs up to four web searches and keeps at most six pages outside PhysioNet. Each page is fetched and read. A card is kept only when the two resources share a subject, a data form, a topic, a modality, a task, or a kind.

Without `SERPAPI_API_KEY`, published research cannot build the citation trail. Similar resources skips the web search and still returns the catalog comparison.

`POST /api/scholar` is a manual Scholar search for checking a query. The page does not call it. `scripts/try_scholar.py` calls the same function.

## Tech stack

Python 3.11 or newer. [uv](https://docs.astral.sh/uv/) installs the dependencies. The API is FastAPI, served by uvicorn. The two agents are fixed LangGraph sequences. The model is called through `ask()` in `apps/agents/llm.py`: `LLM_PROVIDER=gemini` sends that call to Gemini, and `LLM_PROVIDER=groq` sends it to Groq. SerpAPI and page downloads use `httpx`. PDFs use `pdfplumber`. The UI is `web/index.html`, `web/app.js`, and `web/app.css`, with no frontend build.

## Project structure

```
physiolens/
  apps/backend/     API, catalog, SerpAPI, citations, paper parsing, reports
  apps/agents/      The two agents and the shared model call
  web/              The page served at /
  data/             Catalog JSON and the SQLite run log
  scripts/          Rebuild the catalog, or try one Scholar query
  tests/            Unit tests
```

`apps/agents/published.py` is Explore published research. `apps/agents/resources.py` is Find similar resources. `apps/backend/scholar.py` is every SerpAPI call.

## Setup

Follow one section only. macOS and Linux are first. Windows is the next section. Both end with the same keys.

Use `uv run` for every project command. You do not activate the virtual environment by hand.

### macOS and Linux

1. Install uv once.

   macOS:

   ```bash
   brew install uv
   ```

   Linux:

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. Open a new terminal if `uv` is not found. Check with `uv --version`.
3. Clone the repository and install the dependencies.

   ```bash
   git clone https://github.com/Bhavya9991/Physiolens.git
   cd Physiolens
   uv sync
   cp .env.sample .env
   ```

4. Open `.env` and set the keys in the table below. Do not commit `.env`.

### Windows

Use PowerShell for these steps.

1. Install uv once.

   ```powershell
   winget install --id=astral-sh.uv -e
   ```

2. Close that window and open a new PowerShell window. Check with `uv --version`.
3. Clone the repository and install the dependencies.

   ```powershell
   git clone https://github.com/Bhavya9991/Physiolens.git
   cd Physiolens
   uv sync
   Copy-Item .env.sample .env
   ```

   In Command Prompt, the copy line is `copy .env.sample .env`. `cd` and `uv sync` stay the same.

4. Open `.env` and set the keys in the table below. Do not commit `.env`.

### Keys

| Variable | When it is required |
| --- | --- |
| `SERPAPI_API_KEY` | Scholar and Google searches. From [serpapi.com](https://serpapi.com/). |
| `OPENAI_API_KEY` | The model, when `LLM_PROVIDER=gemini`. The client library reads this name. A key comes from [Google AI Studio](https://aistudio.google.com/apikey). |
| `OPENAI_MODEL` | Gemini model. The sample uses `gemini-3.8-flash`. |
| `OPENAI_BASE_URL` | `https://generativelanguage.googleapis.com/v1beta/openai/` |
| `LLM_PROVIDER` | `gemini` or `groq`. |
| `GROQ_API_KEY` | The model, when `LLM_PROVIDER=groq`. From [Groq](https://console.groq.com/keys). |
| `GROQ_MODEL` | Groq model. The sample uses `openai/gpt-oss-120b`. |

Restart the server after changing `.env`.

The catalog file is already in `data/physionet_catalog.json`. Rebuild it only when you want a fresh PhysioNet snapshot:

```bash
uv run python scripts/try_physionet.py
```

Check the SerpAPI key:

```bash
uv run python scripts/try_scholar.py
uv run python scripts/try_scholar.py "MIMIC-IV mortality prediction"
```

## Run

```bash
uv run uvicorn apps.backend.main:app --reload
```

That command is the same on macOS, Linux, and Windows. Open http://127.0.0.1:8000 .

The page has three sections: About, Explore, and Past activity.

Tests do not call SerpAPI or the model:

```bash
uv run python -m unittest discover -s tests
```

## API

Catalog routes read the JSON file.

- `GET /api/catalog` returns the two doors and their counts.
- `GET /api/projects` returns one page of the table. `hierarchy=subject&node=heart` is one group. Omit both for the full catalog.
- Filters: `q` (title, description, topics), `access`, `resource` (Database, Challenge, Software, Model), `published_from`, `published_to`, `sort` (`title_asc`, `title_desc`, `newest`, `oldest`, `largest`, `smallest`), `page` (default 1), `page_size` (default 25, maximum 100).
- `GET /api/projects/{slug}` is one project, including the two actions.

Agent routes:

- `POST /api/runs` with `{"slug": "mitdb", "action_id": "published"}` or `"action_id": "resources"` returns immediately with status `running`. Any other action is rejected. A third start while two runs are still going returns 409.
- `GET /api/runs` lists past runs, newest first.
- `GET /api/runs/{id}` returns the steps and the result.
- `GET /api/runs/{id}/log` returns the plain-text log.
- `GET /api/runs/{id}/report` downloads the HTML report.
- `POST /api/runs/{id}/stop` finishes the current paper or step, then stops.
- `DELETE /api/runs/{id}` deletes one run. `DELETE /api/runs` deletes every run.
- `POST /api/scholar` with `{"query": "..."}` runs one Scholar search.
