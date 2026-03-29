# Spec: Observability / Evals

## Метрики

- `end-to-end latency`:
  - считается как `finished_at - started_at` для всей сессии;
  - агрегируется как `p50`, `p95`, `p99`.
- `stage latency`:
  - считается как `stage_finished_at - stage_started_at`;
  - считается отдельно для `INGEST`, `OCR`, `ANONYMIZE`, `RETRIEVE`, `LLM_ANALYZE`, `VALIDATE`, `FINALIZE`.
- `error rate`:
  - `(число сессий, завершившихся ошибкой) / (общее число запущенных сессий)`;
  - дополнительно считается по стадиям.
- `completion rate`:
  - `(число сессий со статусом success или degraded_success) / (общее число запущенных сессий)`.
- `fallback rate`:
  - `(число сессий, где был активирован хотя бы один fallback) / (общее число запущенных сессий)`.
- `Precision@Top5`:
  - считается на размеченном eval-наборе;
  - для каждого документа проверяется, есть ли хотя бы один релевантный finding в top-5;
  - итоговое значение: `(число документов, где условие выполнено) / (число документов в eval-наборе)`.
- `evidence coverage`:
  - `(число findings с валидным evidence) / (общее число findings)`;
  - валидным считается finding, у которого есть source reference и цитата/фрагмент.
- `paragraph-anchor accuracy`:
  - считается на размеченном наборе;
  - `(число findings с корректным paragraph_id или span anchor) / (число findings, подлежащих проверке)`.
- `tokens per stage`:
  - сумма `prompt_tokens + completion_tokens` по каждому stage.
- `cost per document`:
  - сумма `cost_estimate` по всем LLM-вызовам в рамках одного `session_id`.
- `OCR success rate`:
  - `(число документов, где OCR завершился без ошибки) / (число документов, для которых OCR запускался)`.
- `low-quality OCR rate`:
  - `(число OCR-результатов с quality_flag=low) / (число документов, для которых OCR запускался)`.

## Какие данные нужны для расчета

- для session-level метрик:
  - `request_id`
  - `session_id`
  - `started_at`
  - `finished_at`
  - `final_status`
  - `degraded_flags`
- для stage-level метрик:
  - `stage`
  - `stage_started_at`
  - `stage_finished_at`
  - `stage_status`
  - `retry_count`
  - `error_code`
- для LLM/cost метрик:
  - `provider`
  - `model`
  - `prompt_tokens`
  - `completion_tokens`
  - `cost_estimate`
  - `llm_call_id`
  - `stage`
- для retrieval/evidence метрик:
  - `finding_id`
  - `source_id`
  - `snippet`
  - `retrieval_score`
  - `paragraph_id`
  - `evidence_present`
- для OCR метрик:
  - `ocr_invoked`
  - `ocr_status`
  - `ocr_quality_score` или `quality_flag`
- для eval quality метрик:
  - `dataset_id`
  - `document_id`
  - `expected_findings`
  - `predicted_findings`
  - `expected_paragraph_ids`

## Логи

- stage logs:
  - `session_id`
  - `stage`
  - `status`
  - `duration_ms`
  - `retry_count`
  - `error_code`
- LLM logs:
  - `provider`
  - `model`
  - `prompt_tokens`
  - `completion_tokens`
  - `cost_estimate`
  - `stage`
- policy logs:
  - privacy blocks
  - tool policy violations
- в логах не должно быть полного сырого текста документа.

## Трейсы

Основная цепочка:

- `request_id` связывает внешний HTTP-запрос;
- `session_id` связывает все этапы обработки одного документа;
- `stage_span_id` связывает конкретную стадию внутри пайплайна.

Для каждого запроса должны трассироваться:

- старт и завершение полного пайплайна;
- старт и завершение каждой стадии (`INGEST`, `OCR`, `ANONYMIZE`, `RETRIEVE`, `LLM_ANALYZE`, `VALIDATE`, `FINALIZE`);
- все внешние вызовы к LLM, web search и другим API;
- все переходы в fallback-режим;
- все случаи degraded execution, когда система продолжает работу с ограниченным качеством результата.

По трейсам должно быть возможно ответить на практические вопросы:

- на какой стадии запрос провел больше всего времени;
- какой внешний вызов завершился ошибкой или таймаутом;
- был ли активирован fallback;
- завершился ли запрос успешно, в degraded-режиме или ошибкой.

## Проверки

`Contract tests` проверяют межмодульные контракты:

- соответствует ли формат входа и выхода между сервисами ожидаемой схеме;
- возвращает ли LLM-адаптер результат в допустимой JSON-структуре;
- содержит ли retrieval-ответ обязательные поля `source_id`, `snippet`, `score`, `timestamp`;
- формируется ли итоговый report в корректном формате.

`Regression eval` проверяет качество на эталонном наборе документов:

- не ухудшилось ли качество поиска рисков после изменения промпта, модели или retrieval;
- сохраняется ли `Precision@Top5`;
- не выросло ли число findings без evidence;
- не ухудшилась ли точность привязки к paragraph anchors.

`Smoke checks` проверяют базовую устойчивость пайплайна на проблемных сценариях:

- недоступен LLM;
- retriever вернул timeout;
- модель вернула невалидный JSON;
- внешний LLM-вызов заблокирован privacy-policy;
- OCR вернул низкое качество текста.

Для каждого smoke-сценария должна быть заранее понятна ожидаемая реакция системы:

- остановка с диагностической ошибкой;
- переход в degraded-режим;
- fallback на rule-based отчет;
- блокировка внешнего вызова без утечки данных.
