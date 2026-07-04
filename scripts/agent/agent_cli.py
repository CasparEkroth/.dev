from scripts.agent.agent_loop import run_agent
from scripts.agent.tools.registry import tool_registry

r = run_agent(
    system_prompt="you are a coding agent",
    user_input="what bash files are in this repo",
    tool_registry=tool_registry
)

print(r)