import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from shared.llm_client import call_llm

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


load_dotenv()

base_url = os.environ.get("LLM_BASE_URL")
api_key = os.environ.get("LLM_API_KEY")
model = os.environ.get("LLM_MODEL")


print(
    call_llm(
        base_url=base_url,
        api_key=api_key,
        model=model,
        prompt="what is the time in sweden?",
    )
)
