"""Web search and system monitoring tools."""
import psutil
from .helpers import _get_arg


def web_search_tool(query):
    q = _get_arg(query, ["query", "q", "search", "text", "search_query", "keywords"])
    if not q and isinstance(query, dict):
        values = [v for v in query.values() if isinstance(v, str) and v.strip()]
        q = values[0] if values else None
    if not q and isinstance(query, str):
        q = query
    if not q:
        return "Error: No search query specified."
    try:
        from ddgs import DDGS
        results = DDGS().text(query=q, max_results=5, region="it-it")
        if not results: return "No results found. DO NOT fabricate data under any circumstances. Inform the user that the search returned no results."
        
        output = []
        for r in results:
            output.append(f"--- {r['title']} ---\n{r['body']}\n")
        return "\n".join(output)
    except Exception as e:
        return f"Search Error: {e}. The search servers are unreachable or the API has changed. DO NOT fabricate any information. Inform the user that a technical error occurred."

def system_stats_tool(_):
    return f"CPU: {psutil.cpu_percent()}%, RAM: {psutil.virtual_memory().percent}%"
