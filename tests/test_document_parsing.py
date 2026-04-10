import sys
import types

import pytest

from app.services.documents.ingestion_service import (
    DocumentIngestionService,
    UnsupportedDocumentTypeError,
)


class FakePage:
    def __init__(self, text: str):
        self._text = text

    def get_text(self, mode: str):
        assert mode == "text"
        return self._text


class FakePdf:
    def __init__(self, pages):
        self.pages = pages

    def __len__(self):
        return len(self.pages)

    def __getitem__(self, idx):
        return self.pages[idx]


def test_parse_rejects_unsupported_extension() -> None:
    service = DocumentIngestionService()
    with pytest.raises(UnsupportedDocumentTypeError):
        service.parse("a.txt", b"text")


def test_parse_pdf_text_only(monkeypatch) -> None:
    fake_fitz = types.SimpleNamespace(open=lambda stream, filetype: FakePdf([FakePage("Стр 1"), FakePage(" "), FakePage("Стр 3")]))
    monkeypatch.setitem(sys.modules, "fitz", fake_fitz)

    service = DocumentIngestionService()
    result = service.parse("sample.pdf", b"%PDF")

    assert result.file_type == "pdf"
    assert len(result.paragraphs) == 2
    assert result.paragraphs[0].paragraph_id == "p1_1"
    assert result.paragraphs[0].start_offset == 0
    assert result.paragraphs[0].end_offset == len("Стр 1")
    assert "Стр 3" in result.full_text


def test_parse_docx_with_tables(monkeypatch) -> None:
    fake_row1 = types.SimpleNamespace(
        cells=[types.SimpleNamespace(text="Наименование"), types.SimpleNamespace(text="Цена")]
    )
    fake_row2 = types.SimpleNamespace(
        cells=[types.SimpleNamespace(text="Услуга А"), types.SimpleNamespace(text="1000")]
    )
    fake_table = types.SimpleNamespace(rows=[fake_row1, fake_row2])
    fake_docx = types.SimpleNamespace(
        Document=lambda stream: types.SimpleNamespace(
            paragraphs=[
                types.SimpleNamespace(text="Договор поставки"),
                types.SimpleNamespace(text=""),
            ],
            tables=[fake_table],
        )
    )
    monkeypatch.setitem(sys.modules, "docx", fake_docx)

    service = DocumentIngestionService()
    result = service.parse("table.docx", b"bytes")

    assert result.file_type == "docx"
    assert "Договор поставки" in result.full_text
    assert "Наименование | Цена" in result.full_text
    assert "Услуга А | 1000" in result.full_text
    assert result.paragraphs[0].start_offset == 0
    assert result.paragraphs[0].end_offset == len("Договор поставки")
