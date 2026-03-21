from fastapi.testclient import TestClient

from app.main import app
from app.services.anonymization.anonymizer import AnonymizerService
from app.services.anonymization.regex_detector import RegexDetector
from app.services.anonymization.span_resolver import SpanResolver


class DummyNerDetector:
    def detect(self, text: str):
        return []


def test_regex_anonymization_replaces_email_and_phone() -> None:
    service = AnonymizerService(RegexDetector(), DummyNerDetector(), SpanResolver())
    text = "Контакт: ivan.petrov@example.com, телефон +7 (999) 123-45-67"

    result = service.anonymize(text, use_ner=False)

    assert "[EMAIL_1]" in result.anonymized_text
    assert "[PHONE_1]" in result.anonymized_text
    assert result.stats["EMAIL"] == 1
    assert result.stats["PHONE"] == 1


def test_regex_anonymization_replaces_inn() -> None:
    service = AnonymizerService(RegexDetector(), DummyNerDetector(), SpanResolver())
    text = "ИНН: 7707083893"

    result = service.anonymize(text, use_ner=False)

    assert "[INN_1]" in result.anonymized_text
    assert result.stats["INN"] == 1


def test_regex_anonymization_replaces_valid_inn_examples_from_stdnum_docs() -> None:
    # Examples from stdnum.ru.inn docs.
    service = AnonymizerService(RegexDetector(), DummyNerDetector(), SpanResolver())
    text = "ИНН организации 1234567894, ИНН физлица 123456789047"

    result = service.anonymize(text, use_ner=False)

    assert result.stats["INN"] == 2
    assert "[INN_1]" in result.anonymized_text
    assert "[INN_2]" in result.anonymized_text


def test_regex_anonymization_replaces_valid_ogrn_examples_from_stdnum_docs() -> None:
    # Examples from stdnum.ru.ogrn docs.
    service = AnonymizerService(RegexDetector(), DummyNerDetector(), SpanResolver())
    text = "ОГРН 1022200525819, ОГРНИП 385768585948949"

    result = service.anonymize(text, use_ner=False)

    assert result.stats["OGRN"] == 2
    assert "[OGRN_1]" in result.anonymized_text
    assert "[OGRN_2]" in result.anonymized_text


def test_regex_anonymization_replaces_snils_and_passport_formats() -> None:
    service = AnonymizerService(RegexDetector(), DummyNerDetector(), SpanResolver())
    text = "СНИЛС 112-233-445 95, паспорт 4510 123456"

    result = service.anonymize(text, use_ner=False)

    assert result.stats["SNILS"] == 1
    assert result.stats["PASSPORT"] == 1
    assert "[SNILS_1]" in result.anonymized_text
    assert "[PASSPORT_1]" in result.anonymized_text


def test_regex_anonymization_replaces_bank_account_and_bic() -> None:
    service = AnonymizerService(RegexDetector(), DummyNerDetector(), SpanResolver())
    text = "Р/с 40702810900000000001, БИК 044525225"

    result = service.anonymize(text, use_ner=False)

    assert result.stats["BANK_ACCOUNT"] == 1
    assert result.stats["BIC"] == 1
    assert "[BANK_ACCOUNT_1]" in result.anonymized_text
    assert "[BIC_1]" in result.anonymized_text


def test_regex_does_not_match_embedded_digits_in_longer_sequence() -> None:
    service = AnonymizerService(RegexDetector(), DummyNerDetector(), SpanResolver())
    text = "Длинная строка 123456789012345678901 не должна стать INN/OGRN."

    result = service.anonymize(text, use_ner=False)

    assert "INN" not in result.stats
    assert "OGRN" not in result.stats
    assert "BANK_ACCOUNT" not in result.stats


def test_api_anonymize_endpoint_works_in_regex_mode() -> None:
    client = TestClient(app)
    payload = {
        "text": "Контакт ivan.petrov@example.com, телефон +7 (999) 123-45-67",
        "use_ner": False,
    }

    response = client.post("/api/anonymize", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["stats"]["EMAIL"] == 1
    assert body["stats"]["PHONE"] == 1
    assert "[EMAIL_1]" in body["anonymized_text"]
    assert "[PHONE_1]" in body["anonymized_text"]
