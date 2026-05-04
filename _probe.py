import asyncio, warnings
warnings.filterwarnings("ignore")
from langchain_ollama import ChatOllama
from langchain.agents import create_agent
from langchain_core.tools import tool
import config

@tool
def dummy(x: str) -> str:
    """A dummy tool."""
    return "ok"

async def probe():
    llm = ChatOllama(model=config.OLLAMA_MODEL, base_url=config.OLLAMA_BASE_URL, temperature=0)
    agent = create_agent(llm, tools=[dummy], system_prompt="You are a helpful assistant.")
    msgs = {"messages": [{"role": "user", "content": "Say hello in one word."}]}
    async for chunk in agent.astream(msgs):
        print("KEYS:", list(chunk.keys()))
        for k, v in chunk.items():
            msgs_in_chunk = v.get("messages", []) if isinstance(v, dict) else []
            for m in msgs_in_chunk:
                content = str(m.content)[:120] if hasattr(m, "content") else "n/a"
                print(f"  [{k}] {type(m).__name__}  content={content!r}")

asyncio.run(probe())

