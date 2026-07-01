from tavily import TavilyClient
from config import settings
import json
from scripts.docs.prompts import WEB_SEARCH_PROMPT
from shared.llm_client import call_llm

tavily_client = TavilyClient(api_key=settings.TAVILY_API_KEY)


def web_search(query: str, max_results: int = 5) -> dict:
    response = tavily_client.search(
        query=query,
        max_results=max_results,
        include_favicon=False,
        include_answer=False,
        include_raw_content=False,
    )
    print(json.dumps(response, indent=2))
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
    resp = web_search(query=question)
    prompt = WEB_SEARCH_PROMPT.format(
        user_input=question,
        search_context=resp,
    )
    return call_llm(prompt=prompt)
