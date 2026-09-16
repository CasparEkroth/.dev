"""Tavily-backed web search helpers used by the search CLI."""

from __future__ import annotations

from tavily import TavilyClient

from config import settings

_tavily_client: TavilyClient | None = None


def _get_tavily_client() -> TavilyClient:
    """Return a process-wide Tavily client, created on first use."""
    global _tavily_client
    if _tavily_client is None:
        _tavily_client = TavilyClient(api_key=settings.TAVILY_API_KEY)
    return _tavily_client


def reset_tavily_client() -> None:
    """Drop the cached client. Intended for tests."""
    global _tavily_client
    _tavily_client = None


def web_search(query: str, max_results: int = 5) -> list[str]:
    """Search the web and return one formatted text block per hit."""
    response = _get_tavily_client().search(
        query=query,
        max_results=max_results,
        include_favicon=False,
        include_answer=False,
        include_raw_content=False,
    )
    chunks: list[str] = []
    for r in response["results"]:
        chunks.append(f"""
            Title: {r.get("title")}
            URL: {r.get("url")}
            Score: {r.get("score")}
            Content: {r.get("content")}
            """)
    return chunks


def search(question: str) -> list[str]:
    """Convenience wrapper: search *question* with default result count."""
    return web_search(query=question)
