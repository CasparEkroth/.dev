ROUTER_PROMPT = """
Decide whether this question needs fresh web search.

User question:
{user_input}

Relevant project files:
{files}

Use web search ONLY for current/external/version-specific information.
Do NOT use web search for general coding, debugging, design, or explanations.

Return ONLY valid JSON:

{{
  "requires_search": true,
  "search_query": "..."
}}

or

{{
  "requires_search": false
}}
"""


WEB_SEARCH_PROMPT = """
You are answering a user's question using web search results.

User question:
{user_input}

Files provided by the user:
{files}

Web search results:
{search_context}

Instructions:

- Prioritize the provided files whenever they are relevant.
- Use the web search results to supplement or update the information.
- If the search results contradict the files, explain the discrepancy.
- Do not invent facts.
- If the search results are insufficient, explicitly state that.
- When referencing search results, include the corresponding URLs.
- Respond using Markdown

Provide a complete answer.
"""

NO_SEARCH_PROMPT = """
You are answering the user's question.

User question:
{user_input}

Files provided by the user:
{files}

Instructions:

- If files are provided above, base your answer primarily on them, and use
  general knowledge only when it does not contradict them.
- If no files are provided (shown as "None"), answer directly from general
  knowledge. Never ask the user to paste files or file paths — this tool was
  invoked without any, so treat that as a deliberate choice, not an omission.
- Only note that the answer could be sharper with repo context (e.g.
  "re-run with -f/-d to point at the relevant file for specifics") if the
  question is clearly about this specific codebase rather than general
  programming knowledge.
- Do not invent facts.
- Respond using Markdown

Provide a complete answer.
"""
