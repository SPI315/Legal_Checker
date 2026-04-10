import sys
import types

from app.services.anonymization.transformer_detector import TransformerNerDetector


class DummyPipeline:
    def __init__(self, predictions=None, raise_on_call: bool = False):
        self.predictions = predictions or []
        self.raise_on_call = raise_on_call

    def __call__(self, text: str):
        if self.raise_on_call:
            raise RuntimeError("boom")
        return self.predictions


def test_transformer_detector_returns_empty_if_model_not_configured() -> None:
    detector = TransformerNerDetector(model_name="")
    assert detector.detect("hello") == []


def test_transformer_detector_load_failure_is_handled(monkeypatch) -> None:
    fake_transformers = types.SimpleNamespace(
        pipeline=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("load fail"))
    )
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)

    detector = TransformerNerDetector(model_name="fake/model")

    assert detector.detect("text") == []


def test_transformer_detector_maps_predictions(monkeypatch) -> None:
    predictions = [
        {"entity_group": "PER", "score": 0.95, "start": 0, "end": 4},
        {"entity_group": "ORG", "score": 0.30, "start": 5, "end": 9},
        {"entity_group": "UNKNOWN", "score": 0.99, "start": 10, "end": 14},
    ]

    fake_transformers = types.SimpleNamespace(
        pipeline=lambda **kwargs: DummyPipeline(predictions=predictions)
    )
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)

    detector = TransformerNerDetector(model_name="fake/model", min_score=0.6)
    spans = detector.detect("John ACME")

    assert len(spans) == 1
    assert spans[0].entity_type == "PERSON"
    assert spans[0].source == "ner"


def test_transformer_detector_maps_bio_labels(monkeypatch) -> None:
    predictions = [
        {"entity_group": "B-PER", "score": 0.95, "start": 0, "end": 4},
        {"entity_group": "I-ORG", "score": 0.95, "start": 5, "end": 9},
    ]
    fake_transformers = types.SimpleNamespace(
        pipeline=lambda **kwargs: DummyPipeline(predictions=predictions)
    )
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)

    detector = TransformerNerDetector(model_name="fake/model", min_score=0.6)
    spans = detector.detect("John ACME")

    assert len(spans) == 2
    assert spans[0].entity_type == "PERSON"
    assert spans[1].entity_type == "ORGANIZATION"


def test_transformer_detector_inference_failure_is_handled(monkeypatch) -> None:
    fake_transformers = types.SimpleNamespace(
        pipeline=lambda **kwargs: DummyPipeline(raise_on_call=True)
    )
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)

    detector = TransformerNerDetector(model_name="fake/model")

    assert detector.detect("text") == []


def test_transformer_detector_uses_cached_pipeline_and_skips_invalid_offsets() -> None:
    detector = TransformerNerDetector(model_name="fake/model", min_score=0.1)
    detector._pipeline = DummyPipeline(
        predictions=[
            {"entity_group": "PER", "score": 0.9, "start": None, "end": 4},
            {"entity_group": "PER", "score": 0.9, "start": 0, "end": None},
        ]
    )

    assert detector.detect("John") == []
