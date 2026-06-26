FILE_SUMMARY_PROMPT = """
Summarize this source file for code search.

Return only:
Purpose: <1 sentence>
Main symbols: <important classes/functions/constants>
Dependencies: <important imports/modules>
Side effects: <file I/O, network, subprocess, DB, global mutation, or none>
Keywords: <comma-separated search terms>

Rules:
- Be factual.
- Do not invent behavior.
- Keep it compact.

Path: {path}
Language: {language}

Code:
```{language}
{content}
```
""".strip()

SYMBOL_SUMMARY_PROMPT = """
Summarize this code symbol for code search.

Return only:
Summary: <1 sentence>
Inputs: <important parameters or none>
Output: <return value or none/unknown>
Side effects: <I/O, network, DB, mutation, or none>
Keywords: <comma-separated search terms>

Rules:

Be factual.
Do not explain syntax.
Do not invent missing context.
Keep it compact.

Path: {path}
Language: {language}
Symbol: {kind} {name}
Signature: {signature}
Code:
```{language}
{code}
```
""".strip()
