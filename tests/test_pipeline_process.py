from pathlib import Path

import logging
from fastapi.testclient import TestClient

from app.main import app


def _build_docx_bytes(text: str) -> bytes:
    from io import BytesIO

    from docx import Document

    doc = Document()
    doc.add_paragraph(text)
    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def test_process_document_end_to_end_returns_findings_and_artifacts() -> None:
    client = TestClient(app)
    file_bytes = _build_docx_bytes(
        "\u0414\u043e\u0433\u043e\u0432\u043e\u0440 \u0430\u0432\u0442\u043e\u043c\u0430\u0442\u0438\u0447\u0435\u0441\u043a\u0438 "
        "\u043f\u0440\u043e\u0434\u043b\u0435\u0432\u0430\u0435\u0442\u0441\u044f \u043d\u0430 \u0441\u043b\u0435\u0434\u0443\u044e\u0449\u0438\u0439 "
        "\u0441\u0440\u043e\u043a, \u0430 \u0438\u0441\u043f\u043e\u043b\u043d\u0438\u0442\u0435\u043b\u044c "
        "\u043d\u0435 \u043d\u0435\u0441\u0435\u0442 \u043e\u0442\u0432\u0435\u0442\u0441\u0442\u0432\u0435\u043d\u043d\u043e\u0441\u0442\u0438."
    )

    response = client.post(
        "/api/documents/process?jurisdiction=RU&use_ner=false",
        files={
            "file": (
                "contract.docx",
                file_bytes,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"success", "degraded_success"}
    assert len(body["findings"]) >= 1
    assert body["artifacts"]["encrypted_report_path"]
    assert body["artifacts"]["export_docx_path"]
    assert "observability" in body
    assert "events" in body["observability"]
    assert Path(body["artifacts"]["encrypted_report_path"]).exists()
    assert Path(body["artifacts"]["export_docx_path"]).exists()


def test_process_document_export_docx_works() -> None:
    client = TestClient(app)
    file_bytes = _build_docx_bytes(
        "\u0417\u0430\u043a\u0430\u0437\u0447\u0438\u043a \u0432\u043f\u0440\u0430\u0432\u0435 \u0432 "
        "\u043e\u0434\u043d\u043e\u0441\u0442\u043e\u0440\u043e\u043d\u043d\u0435\u043c \u043f\u043e\u0440\u044f\u0434\u043a\u0435 "
        "\u0438\u0437\u043c\u0435\u043d\u0438\u0442\u044c \u0443\u0441\u043b\u043e\u0432\u0438\u044f \u0434\u043e\u0433\u043e\u0432\u043e\u0440\u0430."
    )
    process_response = client.post(
        "/api/documents/process?jurisdiction=RU&use_ner=false",
        files={
            "file": (
                "contract.docx",
                file_bytes,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    session_id = process_response.json()["session_id"]

    export_response = client.get(f"/api/documents/{session_id}/export.docx")

    assert export_response.status_code == 200
    assert export_response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


def test_process_document_logs_stage_progress(caplog) -> None:
    client = TestClient(app)
    file_bytes = _build_docx_bytes("Договор автоматически продлевается на следующий срок.")

    with caplog.at_level(logging.INFO):
        response = client.post(
            "/api/documents/process?jurisdiction=RU&use_ner=false",
            files={
                "file": (
                    "contract.docx",
                    file_bytes,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )

    assert response.status_code == 200
    log_text = caplog.text
    assert "pipeline_started" in log_text
    assert "stage=INGEST status=started" in log_text
    assert "stage=INGEST status=success" in log_text
    assert "stage=ANONYMIZE status=started" in log_text
    assert "pipeline_finished" in log_text


def test_process_document_logs_decision_loop_steps(caplog) -> None:
    client = TestClient(app)
    file_bytes = _build_docx_bytes("Договор автоматически продлевается на следующий срок.")

    with caplog.at_level(logging.INFO):
        response = client.post(
            "/api/documents/process?jurisdiction=RU&use_ner=false",
            files={
                "file": (
                    "contract.docx",
                    file_bytes,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )

    assert response.status_code == 200
    log_text = caplog.text
    assert "candidate_processing_started" in log_text
    assert "retrieval_pass_started pass=1" in log_text
    assert "decision=evidence_evaluated pass=1" in log_text
    assert "decision=finding_accepted" in log_text


def test_process_document_status_endpoint_and_session_logs_exist() -> None:
    client = TestClient(app)
    file_bytes = _build_docx_bytes("Договор автоматически продлевается на следующий срок.")

    process_response = client.post(
        "/api/documents/process?jurisdiction=RU&use_ner=false",
        files={
            "file": (
                "contract.docx",
                file_bytes,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    body = process_response.json()
    session_id = body["session_id"]

    status_response = client.get(f"/api/documents/{session_id}/status")

    assert status_response.status_code == 200
    status_body = status_response.json()
    assert status_body["session_id"] == session_id
    assert status_body["status"] in {"success", "degraded_success"}
    assert status_body["current_stage"] == "FINALIZE"
    assert Path(body["artifacts"]["events_path"]).exists()
    assert Path(body["artifacts"]["session_log_path"]).exists()


def test_process_document_timeline_endpoint_works() -> None:
    client = TestClient(app)
    file_bytes = _build_docx_bytes("Договор автоматически продлевается на следующий срок.")

    process_response = client.post(
        "/api/documents/process?jurisdiction=RU&use_ner=false",
        files={
            "file": (
                "contract.docx",
                file_bytes,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    session_id = process_response.json()["session_id"]

    timeline_response = client.get(f"/api/documents/{session_id}/timeline")

    assert timeline_response.status_code == 200
    body = timeline_response.json()
    assert len(body) >= 1
    assert any(item["event_type"] == "pipeline_finished" for item in body)


def test_process_document_start_endpoint_returns_session_and_status() -> None:
    client = TestClient(app)
    file_bytes = _build_docx_bytes("Договор автоматически продлевается на следующий срок.")

    response = client.post(
        "/api/documents/process/start?jurisdiction=RU&use_ner=false",
        files={
            "file": (
                "contract.docx",
                file_bytes,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"]
    assert body["status"] in {"queued", "success", "degraded_success"}
