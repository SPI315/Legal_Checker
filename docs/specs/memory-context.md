# Spec: Memory / Context

## Session State

Session state нужен для управления жизненным циклом обработки одного документа. Он позволяет оркестратору понимать, на каком этапе находится запрос и можно ли его безопасно продолжить после ошибки.

Основные поля:

- `session_id`
- `stage`
- `status`
- `retry_count`
- `started_at`
- `updated_at`
- `degraded_flags`

TTL для PoC: `24 часа`.

## Memory Policy

Память делится на два уровня.

`Working memory` живет только во время активной обработки и содержит:

- структуру документа;
- OCR output;
- anonymized text;
- промежуточные findings;
- retrieval evidence;
- LLM drafts.

`Persistent memory` сохраняется после завершения обработки и содержит:

- final report;
- trace ids;
- stage metadata;
- model info;
- агрегированные метрики.

Полный исходный текст документа в persistent memory не сохраняется.

## Privacy / Data Policy

Перед внешним LLM-вызовом система формирует `anonymized_text`.

Допускается хранение:

- `anonymized_text`
- `spans`
- `analysis_report`
- технических метрик

Оригинальный текст разрешен только in-memory на время обработки.

## Context Budget

Контекст нужен для того, чтобы передавать в модель только релевантные части документа и не превышать лимит токенов.

Основные правила:

- hard cap на один LLM-вызов: `16k` токенов на вход и выход вместе;
- приоритет включения:
  1. paragraph с candidate risk
  2. top evidence from retriever
  3. соседние paragraphs
  4. служебные инструкции

Если бюджет превышен:

- сначала отбрасываются низкоранговые evidence;
- затем сокращается соседний контекст;
- paragraph-источник риска сохраняется всегда.
