from fastapi.testclient import TestClient

from app.api.deps import get_document_ingestion_service
from app.main import app
from app.services.documents.ingestion_service import UnsupportedDocumentTypeError
from app.services.documents.types import DocumentParseResult, DocumentParagraph


class DummyDocumentService:
    def parse(self, file_name: str, content: bytes) -> DocumentParseResult:
        if file_name.endswith(".txt"):
            raise UnsupportedDocumentTypeError("Unsupported file type. Allowed: .pdf, .docx")
        return DocumentParseResult(
            file_name=file_name,
            file_type="pdf",
            full_text="parsed",
            paragraphs=[DocumentParagraph(paragraph_id="p1_1", page=1, text="parsed")],
        )


def test_document_parse_route_success() -> None:
    app.dependency_overrides[get_document_ingestion_service] = lambda: DummyDocumentService()
    client = TestClient(app)

    response = client.post(
        "/api/document/parse",
        files={"file": ("contract.pdf", b"%PDF-test", "application/pdf")},
    )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["file_type"] == "pdf"
    assert body["full_text"] == "parsed"


def test_document_parse_route_rejects_unsupported_extension() -> None:
    app.dependency_overrides[get_document_ingestion_service] = lambda: DummyDocumentService()
    client = TestClient(app)

    response = client.post(
        "/api/document/parse",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )

    app.dependency_overrides.clear()

    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["detail"]


def test_document_parse_route_rejects_empty_file() -> None:
    app.dependency_overrides[get_document_ingestion_service] = lambda: DummyDocumentService()
    client = TestClient(app)

    response = client.post(
        "/api/document/parse",
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )

    app.dependency_overrides.clear()

    assert response.status_code == 400
    assert response.json()["detail"] == "Uploaded file is empty"
