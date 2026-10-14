"""RAG Task 2: turning uploaded files into structured text blocks."""
from __future__ import annotations

import pytest

from app.rag.loaders import UnsupportedFile, detect_kind, load
from tests.helpers import make_docx, make_pdf, make_xlsx


def kinds(doc):
    return [(b.kind, b.level) for b in doc.blocks]


def test_markdown_headings():
    doc = load("notes.md", b"# A\n\npara one\n\n## B\n\npara two")
    assert kinds(doc) == [("heading", 1), ("paragraph", 0), ("heading", 2), ("paragraph", 0)]
    assert [b.text for b in doc.blocks] == ["A", "para one", "B", "para two"]


def test_html_strips_scripts():
    doc = load("page.html", b"<html><body><h1>T</h1><script>x()</script><style>p{}</style><p>Hi</p></body></html>")
    assert all("x()" not in b.text and "p{}" not in b.text for b in doc.blocks)
    assert doc.blocks[0].kind == "heading" and doc.blocks[0].text == "T" and doc.blocks[0].level == 1
    assert any(b.text == "Hi" for b in doc.blocks)


def test_pdf_pages():
    doc = load("report.pdf", make_pdf(["First page text", "Second page text"]))
    assert doc.pages == 2
    pages = {b.page for b in doc.blocks if "page text" in b.text}
    assert pages == {1, 2}


def test_scanned_pdf_rejected():
    with pytest.raises(UnsupportedFile, match="no selectable text"):
        load("scan.pdf", make_pdf(["", ""]))


def test_docx_headings_and_tables():
    doc = load("cv.docx", make_docx("Experience", "Built things.", [["Year", "Role"], ["2024", "Engineer"]]))
    assert ("heading", 1) in kinds(doc) and any(b.text == "Built things." for b in doc.blocks)
    tables = [b for b in doc.blocks if b.kind == "table"]
    assert len(tables) == 1 and "Year | Role" in tables[0].text and "2024 | Engineer" in tables[0].text


def test_csv_row_groups():
    rows = "name,qty\n" + "".join(f"item{i},{i}\n" for i in range(120))
    doc = load("stock.csv", rows.encode())
    tables = [b for b in doc.blocks if b.kind == "table"]
    assert len(tables) == 3
    for table in tables:
        lines = table.text.splitlines()
        assert lines[0] == "name | qty" and len(lines) <= 51


def test_xlsx_sheets():
    data = make_xlsx({"Q1": [["month", "sales"], ["Jan", 10]], "Q2": [["month", "sales"], ["Apr", 20]]})
    doc = load("sales.xlsx", data)
    headings = [b.text for b in doc.blocks if b.kind == "heading"]
    assert headings == ["Q1", "Q2"]
    assert any("Apr | 20" in b.text for b in doc.blocks if b.kind == "table")


def test_non_utf8_text():
    doc = load("prices.csv", "café;1\n".encode("cp1252"))
    assert "caf" in doc.blocks[0].text


def test_refuses_binaries():
    with pytest.raises(UnsupportedFile, match="empty"):
        load("blank.txt", b"")
    for name, data in [("a.zip", b"PK\x03\x04rest-of-zip"), ("p.png", b"\x89PNG\r\n\x1a\n\x00\x00"), ("x.exe", b"MZ\x90\x00\x03")]:
        with pytest.raises(UnsupportedFile, match="isn't supported"):
            load(name, data)


def test_detect_kind():
    assert detect_kind("x.md", b"# hi") == "markdown"
    assert detect_kind("x.json", b'{"a": 1}') == "text"
    assert detect_kind("noext", make_pdf(["hi"])) == "pdf"


def test_rejects_zip_bomb_before_decompressing_it():
    """A small Office/zip upload that declares gigabytes of contents is refused (shared-worker memory DoS)."""
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", b"<Types>" + b"A" * (300 * 1024 * 1024) + b"</Types>")  # ~300 MB of 'A'
    bomb = buffer.getvalue()
    assert len(bomb) < 1_000_000  # compresses tiny
    with pytest.raises(UnsupportedFile, match="too large|too big"):
        load("bomb.docx", bomb)
