"""
council/tools/search_tool.py

Web search tool for COUNCIL expert agents.
"""

from __future__ import annotations

import os
from typing import Type

import os
from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

import council.config  # noqa: F401 — triggers load_dotenv


class SearchInput(BaseModel):
    query: str = Field(..., description="The search query to look up on the web.")
    max_results: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Maximum number of results to return.",
    )


class WebSearchTool(BaseTool):
    """
    Searches the web for up-to-date information.
    Uses Tavily if an API key is available, otherwise falls back to DuckDuckGo.
    """

    name: str = "web_search"
    description: str = (
        "Search the web for recent, authoritative information on a topic. "
        "Input a specific search query. Returns numbered results with titles, URLs, "
        "and content snippets. Note the result number [N] — you will need the "
        "exact URL when storing findings via library_write."
    )
    args_schema: Type[BaseModel] = SearchInput

    def _run(self, query: str, max_results: int = 5) -> str:
        backend = os.getenv("SEARCH_BACKEND", "auto").strip().lower()
        tavily_key = council.config.get_tavily_key()

        if backend == "duckduckgo":
            return self._duckduckgo_search(query, max_results)
        elif backend == "tavily":
            if not tavily_key:
                return "TAVILY_API_KEY not set. Set it in .env or switch to SEARCH_BACKEND=duckduckgo."
            return self._tavily_search(query, max_results, tavily_key)
        else:  # auto: Tavily if key exists, else DuckDuckGo
            if tavily_key:
                return self._tavily_search(query, max_results, tavily_key)
            return self._duckduckgo_search(query, max_results)

    def _tavily_search(self, query: str, max_results: int, api_key: str) -> str:
        try:
            from tavily import TavilyClient

            client = TavilyClient(api_key=api_key)
            response = client.search(
                query=query,
                max_results=max_results,
                search_depth="advanced",
                include_answer=True,
            )

            lines: list[str] = []
            if response.get("answer"):
                lines.append(f"[Summary] {response['answer']}\n")

            for i, result in enumerate(response.get("results", []), 1):
                title = result.get("title", "No title")
                url = result.get("url", "")
                content = result.get("content", "").strip()
                if len(content) > 400:
                    content = content[:400] + "…"
                lines.append(f"[{i}] {title}")
                lines.append(f"    URL: {url}")
                lines.append(f"    {content}")
                lines.append("")

            return "\n".join(lines) if lines else "No results found."

        except Exception as exc:
            return f"Tavily search failed: {exc}. Try rephrasing your query."

    def _duckduckgo_search(self, query: str, max_results: int) -> str:
        try:
            from ddgs import DDGS

            results = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=max_results):
                    results.append(r)

            if not results:
                return "No results found via DuckDuckGo."

            lines: list[str] = []
            for i, r in enumerate(results, 1):
                title = r.get("title", "No title")
                url = r.get("href", "")
                body = r.get("body", "").strip()
                if len(body) > 400:
                    body = body[:400] + "…"
                lines.append(f"[{i}] {title}")
                lines.append(f"    URL: {url}")
                lines.append(f"    {body}")
                lines.append("")

            return "\n".join(lines)

        except ImportError:
            return (
                "DuckDuckGo search is not available (duckduckgo_search not installed). "
                "Please set TAVILY_API_KEY in your .env file."
            )
        except Exception as exc:
            return f"DuckDuckGo search failed: {exc}"


def create_search_tool() -> WebSearchTool:
    """Factory function to create a WebSearchTool instance."""
    return WebSearchTool()
