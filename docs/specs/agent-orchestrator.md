# Spec: Agent / Orchestrator

## Назначение

Оркестратор управляет полным пайплайном обработки документа. Он отвечает за запуск стадий в правильном порядке, передачу данных между модулями, обработку ошибок и выбор fallback-сценариев.

## Шаги

Основные стадии пайплайна:

1. `INIT` - создание `session_id`, инициализация state.
2. `INGEST` - парсинг и структурирование документа.
3. `OCR` - локальное распознавание текста для сканов PDF.
4. `ANONYMIZE` - маскирование PII перед внешними вызовами.
5. `RULES` - rule-based поиск кандидатов рисков.
6. `RETRIEVE` - получение внешних и локальных evidence.
7. `LLM_ANALYZE` - объяснение, правка, confidence.
8. `VALIDATE` - schema checks, evidence checks, policy checks.
9. `FINALIZE` - формирование итогового report.

## Правила переходов

Нормальный путь выглядит так:

`INIT -> INGEST -> OCR? -> ANONYMIZE -> RULES -> RETRIEVE -> LLM_ANALYZE -> VALIDATE -> FINALIZE`

Особые правила:

- `OCR` запускается только для PDF-сканов;
- если retrieval недоступен, система продолжает выполнение с degraded flag;
- если privacy-проверка не пройдена, внешний LLM-вызов блокируется;
- если LLM не ответил даже после retry, система завершает анализ в режиме `rules-only`.

## Stop Condition

Обработка завершается, если:

- отчет успешно сформирован;
- достигнут `max_retries` на критичной стадии;
- произошла невосстановимая ошибка privacy-policy или parse-stage.

## Retry / Fallback

Retry policy:

- до `2` попыток на внешних вызовах;
- exponential backoff.

Fallback hierarchy:

1. partial evidence + LLM
2. rules-only report
3. fail with stage error для критичных стадий
