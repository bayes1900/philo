import os
import requests
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("deepseek-search")
KEY = os.environ["DEEPSEEK_API_KEY"]
HEADERS = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}

@mcp.tool()
def search(query: str, count: int = 10, need_content: bool = False) -> dict:
    """Search the web via DeepSeek. query max 128 chars, count 1-50."""
    r = requests.post(
        "https://api.deepseek.com/v1/tools/search",
        headers=HEADERS,
        timeout=60,
        json={"query": query, "count": count, "need_content": need_content}
    )
    r.raise_for_status()
    return r.json()

@mcp.tool()
def fetch(url: str) -> dict:
    """Fetch a web page and return its title and content as Markdown."""
    r = requests.post(
        "https://api.deepseek.com/v1/tools/fetch",
        headers=HEADERS,
        timeout=60,
        json={"url": url}
    )
    r.raise_for_status()
    return r.json()


if __name__ == "__main__":
    mcp.run()
