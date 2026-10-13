"""The agent's "create a file" tool (the files themselves live in app/files.py)."""
from __future__ import annotations

from typing import Any

from app.files import create_file
from app.integrations.base import IntegrationTool


class CreateFile(IntegrationTool):
    """Always there, under the app "files"; offered when a request is about making a file."""

    def __init__(self) -> None:
        async def make(p: dict[str, Any]) -> Any:
            made = create_file(str(p.get("filename") or ""), str(p.get("content") or ""))
            return {"text": f"Created {made['name']} (file id {made['id']}); the user can download it from the chat. "
                            "Attach it to an email with that id.", "data": {"file": made}}

        super().__init__("files", "Files", "create_file", "Create a downloadable file: CSV or Excel spreadsheet (export a "
                         "table), Word document, Markdown, text, JSON or HTML (a report, list, letter or export).", {
                             "properties": {
                                 "filename": {"type": "string", "description": "With its extension: .csv .xlsx .docx .md .txt .json .html"},
                                 "content": {"type": "string", "description": "Tables (.csv/.xlsx): a JSON list of objects, a Markdown "
                                             "table or CSV text; for a tracker or template, fill in a few realistic example rows "
                                             "instead of placeholders. .docx: Markdown (headings, bullets, tables, **bold**). "
                                             "Others: the text itself."}},
                             "required": ["filename", "content"]}, make, read_only=False, policy="allow", title="Create file")

    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        return await self._run(parameters or {})
