from tavily import TavilyClient
from config import settings


tavily_client = TavilyClient(api_key=settings.TAVILY_API_KEY)


def web_search(query: str, max_results: int = 5) -> dict:
    response = tavily_client.search(
        query=query,
        max_results=max_results,
        include_favicon=False,
        include_answer=False,
        include_raw_content=False,
    )
    chunks = []
    for r in response["results"]:
        chunks.append(f"""
            Title: {r.get("title")}
            URL: {r.get("url")}
            Score: {r.get("score")}
            Content: {r.get("content")}
            """)
    return chunks


def search(question: str) -> str:
    return web_search(query=question)
