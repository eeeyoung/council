"""
council/tools/pdf_tool.py

PDF parsing tool for COUNCIL expert agents.
Allows agents to extract and read text from a local file path or a remote URL.
"""

from __future__ import annotations

import io
import os
import urllib.request
from pathlib import Path
from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field


class PDFInput(BaseModel):
    source: str = Field(
        ...,
        description=(
            "Path to a local PDF file or a direct URL to a PDF. "
            "Example: 'C:/papers/arxiv1234.pdf' or 'https://arxiv.org/pdf/2301.00001'"
        ),
    )
    max_pages: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum number of pages to extract. Defaults to 10.",
    )


class PDFParserTool(BaseTool):
    """
    Extract text from a PDF file (local path or URL).
    Use this when you have a direct link to a research paper or technical report.
    Returns the extracted text, truncated to the specified number of pages.
    """

    name: str = "pdf_parser"
    description: str = (
        "Extract and read text from a PDF file. "
        "Provide a local file path or a direct URL to a PDF. "
        "Useful for reading research papers, technical reports, or documentation. "
        "Returns the extracted plain text."
    )
    args_schema: Type[BaseModel] = PDFInput

    def _run(self, source: str, max_pages: int = 10) -> str:
        source = source.strip()
        try:
            pdf_bytes = self._load_bytes(source)
            return self._extract_text(pdf_bytes, max_pages)
        except Exception as exc:
            return f"PDF parsing failed for '{source}': {exc}"

    def _load_bytes(self, source: str) -> bytes:
        if source.startswith("http://") or source.startswith("https://"):
            req = urllib.request.Request(
                source,
                headers={"User-Agent": "COUNCIL-Research-Bot/1.0"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        else:
            path = Path(source)
            if not path.exists():
                raise FileNotFoundError(f"File not found: {source}")
            return path.read_bytes()

    def _extract_text(self, pdf_bytes: bytes, max_pages: int) -> str:
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(pdf_bytes))
            total_pages = len(reader.pages)
            pages_to_read = min(max_pages, total_pages)

            lines: list[str] = [
                f"[PDF: {total_pages} total pages, extracting {pages_to_read}]\n"
            ]

            for i in range(pages_to_read):
                page = reader.pages[i]
                text = page.extract_text() or ""
                text = text.strip()
                if text:
                    lines.append(f"--- Page {i + 1} ---")
                    lines.append(text)
                    lines.append("")

            result = "\n".join(lines)
            # Cap total output to avoid context window overflow
            if len(result) > 8000:
                result = result[:8000] + "\n\n[… truncated to 8000 chars]"
            return result

        except ImportError:
            return "pypdf not installed. Run: uv add pypdf"


def create_pdf_tool() -> PDFParserTool:
    """Factory function to create a PDFParserTool instance."""
    return PDFParserTool()
