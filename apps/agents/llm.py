"""One chat model for every PhysioLens agent.

The key stays in the environment. Errors must not echo it.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from apps.backend.paths import ENV_PATH

load_dotenv(ENV_PATH)

POLICY = (
    "Use only the records you are given. "
    "A snippet is a search hit. A cites record means that paper cites the seed, "
    "not that it used the dataset. Do not mark confirmed dataset use from a snippet. "
    "Do not treat a short result list as the size of the literature, or an empty list "
    "as proof of a research gap. Web access is unclear unless the retrieved text states "
    "a policy. Do not invent a ranking, a parent dataset, or a paper that is not in the list."
)


_GROQ_URL = "https://api.groq.com/openai/v1"
_GROQ_MODEL = "openai/gpt-oss-120b"


def provider() -> str:
    """gemini or groq. Agents keep calling ask(); this is the only switch."""
    name = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
    if name in {"gemini", "google"}:
        return "gemini"
    if name == "groq":
        return "groq"
    raise RuntimeError("LLM_PROVIDER must be gemini or groq.")


def endpoint() -> dict:
    """The model and URL for the active provider. The key stays out of this dict."""
    if provider() == "groq":
        model = os.getenv("GROQ_MODEL", _GROQ_MODEL).strip() or _GROQ_MODEL
        base = os.getenv("GROQ_BASE_URL", _GROQ_URL).strip() or _GROQ_URL
        return {"provider": "groq", "model": model, "base_url": base}
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
    return {"provider": "gemini", "model": model, "base_url": os.getenv("OPENAI_BASE_URL", "").strip()}


def require_model() -> None:
    chosen = endpoint()
    if chosen["provider"] == "groq":
        if not os.getenv("GROQ_API_KEY", "").strip():
            raise RuntimeError("Set GROQ_API_KEY in .env, then restart the server. LLM_PROVIDER is groq.")
        return
    if not os.getenv("OPENAI_API_KEY", "").strip():
        raise RuntimeError("Set OPENAI_API_KEY in .env, then restart the server. LLM_PROVIDER is gemini.")


def ask(schema: type[BaseModel], system: str, human: str, *, timeout: float | None = None) -> BaseModel:
    require_model()
    chosen = endpoint()
    if chosen["provider"] == "groq":
        key = os.environ["GROQ_API_KEY"].strip()
    else:
        key = os.environ["OPENAI_API_KEY"].strip()
    kwargs = {"model": chosen["model"], "temperature": 0, "api_key": key}
    if chosen["base_url"]:
        kwargs["base_url"] = chosen["base_url"]
    if timeout is not None:
        kwargs["timeout"] = timeout
        kwargs["max_retries"] = 0
    structured = ChatOpenAI(**kwargs).with_structured_output(schema, strict=chosen["provider"] == "groq")
    try:
        return structured.invoke([SystemMessage(content=system), HumanMessage(content=human)])
    except Exception as exc:
        message = str(exc)
        for name in ("OPENAI_API_KEY", "GROQ_API_KEY"):
            secret = os.environ.get(name, "").strip()
            if secret:
                message = message.replace(secret, "[redacted]")
        raise RuntimeError(f"The model call failed. {message[:300]}") from exc
