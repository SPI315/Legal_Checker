# Spec: Agent / Orchestrator

## Назначение

Оркестратор управляет полным пайплайном обработки документа. Он отвечает за запуск стадий в правильном порядке, передачу данных между модулями, обработку ошибок и выбор fallback-сценариев.

В PoC orchestrator не рассматривается как полностью автономный агент общего назначения. Его агентность ограничена минимальным decision loop внутри заданного пайплайна: после выделения risk-кандидатов он выбирает следующий action для каждого кандидата, вызывает нужный tool/API, обновляет state и решает, достаточно ли результата для перехода дальше.

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

- если входной файл не относится к поддерживаемым форматам, запрос отклоняется до запуска `INGEST`;
- `OCR` запускается только для PDF-сканов;
- если `INGEST` завершился ошибкой парсинга или документ поврежден, обработка останавливается с ошибкой этапа;
- если `OCR` завершился ошибкой и текст иначе недоступен, обработка останавливается с ошибкой этапа;
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

## Agent Loop

Запускается после `RULES` и выполняется для каждого risk-кандидата в пределах `RETRIEVE -> LLM_ANALYZE -> VALIDATE`.

Шаги цикла:

1. выбрать следующий risk-кандидат из state;
2. определить, нужен ли retrieval и какие источники использовать;
3. вызвать retrieval tools;
4. оценить полноту evidence и ограничения context budget;
5. при необходимости сделать один дополнительный retrieval-pass или перейти в degraded mode;
6. вызвать `LLM_ANALYZE`;
7. выполнить `VALIDATE`;
8. зафиксировать finding, retry, fallback или перейти к следующему risk-кандидату.


## Error Handling Matrix

- `unsupported_file_format` -> ошибка входной валидации, пайплайн не запускается;
- `parse_failed` / `document_corrupted` -> критичная ошибка стадии `INGEST`, без fallback;
- `ocr_failed` -> критичная ошибка стадии `OCR`, если без OCR текст недоступен;
- `low_quality_text` -> продолжение в degraded mode с quality flag в отчете;
- `retrieval_unavailable` -> продолжение с degraded flag;
- `retrieval_empty` -> не ошибка, анализ продолжается;
- `timeout` / `provider_5xx` / `invalid_json` на `LLM_ANALYZE` -> retry, затем `rules-only` при исчерпании попыток;
- `policy_blocked` -> внешний LLM-вызов запрещен, дальнейшее поведение определяется privacy-policy и fallback-правилами.
