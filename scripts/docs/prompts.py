WEB_SEARCH_PROMPT = """
You are answering using fresh web search context.

User question:
{user_input}

Search results:
{search_context}

Instructions:
- Use the search results when relevant.
- Do not invent facts.
- Mention when the search results are insufficient.
- Include source URLs when useful.
"""
