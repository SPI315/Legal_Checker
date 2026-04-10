# Legal Doc Checker

PoC-система для первичной проверки юридических документов: загрузка `pdf`/`docx`, анонимизация, rule-based поиск рисков, web-retrieval по доверенным источникам, LLM-анализ и экспорт `docx`-отчета.

## Что сейчас реализовано

- Web UI на `/` с drag-and-drop загрузкой документа.
- Онлайн-история выполнения через polling timeline.
- Парсинг `docx` и текстовых `pdf`.
- OCR-этап есть в pipeline, но сейчас это stub, а не полноценный OCR для сканов.
- Анонимизация через regex и опциональный transformers NER.
- Rule-based кандидаты рисков.
- Decision loop по каждому кандидату:
  - initial retrieval;
  - оценка достаточности evidence;
  - refined retrieval при слабом evidence;
  - дополнительный поиск, если LLM сослалась на неподтвержденную правовую норму;
  - LLM-анализ;
  - предупреждение, если правовое основание не подтверждено evidence.
- Retrieval через Tavily при наличии ключа, fallback на allowlist-источники без ключа.
- LLM через OpenRouter при наличии ключа, fallback на локальный vLLM-compatible endpoint или встроенный шаблон.
- Сохранение артефактов в `.artifacts/<session_id>/`.
- Экспорт итогового `docx`-отчета.

## Что пока не реализовано

- Полноценный OCR для сканированных PDF.
- Local RAG по внутренней базе проектных документов.
- Экспорт исходного документа с настоящими Word comments/annotations. Сейчас экспортируется отдельный отчет.
- Полноценный frontend с подсветкой исходного текста и переходом к абзацу.
- Production-ready DLP/SIEM/IAM.

## Быстрый старт

Команды ниже предполагают PowerShell и запуск из корня репозитория.

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload
```

После запуска открой UI:

[http://127.0.0.1:8000](http://127.0.0.1:8000)

Проверка health endpoint:

```powershell
curl http://127.0.0.1:8000/health
```

Ожидаемый ответ:

```json
{"status":"ok"}
```

## Настройка `.env`

Для первого локального прогона ключи можно не заполнять. Pipeline все равно пройдет документ, но часть этапов может работать в fallback-режиме.

Минимально полезные настройки:

```env
LEGAL_NER_MODEL_NAME=
LEGAL_STORAGE_DIR=.artifacts
LEGAL_OPENROUTER_API_KEY=
LEGAL_TAVILY_API_KEY=
```

Если нет поднятого локального vLLM, лучше оставить:

```env
LEGAL_VLLM_BASE_URL=
```

Иначе backend будет пытаться отправлять fallback LLM-запросы на указанный vLLM-compatible endpoint.

Для полного e2e без деградации обычно нужны:

```env
LEGAL_OPENROUTER_API_KEY=<your_openrouter_key>
LEGAL_TAVILY_API_KEY=<your_tavily_key>
```

Опционально для русского NER:

```env
LEGAL_NER_MODEL_NAME=nesemenpolkov/msu-wiki-ner
LEGAL_NER_DEVICE=-1
LEGAL_NER_MIN_SCORE=0.6
```

Если `LEGAL_NER_MODEL_NAME` пустой, сервис работает в regex-only режиме.

## UI-сценарий проверки

1. Запусти API командой `uvicorn app.main:app --reload`.
2. Открой [http://127.0.0.1:8000](http://127.0.0.1:8000).
3. Перетащи `.pdf` или `.docx` в форму.
4. Нажми `Запустить проверку`.
5. Справа смотри онлайн-историю выполнения.
6. После завершения проверь findings и evidence.
7. Нажми `Скачать DOCX-отчет`.

## Основные API endpoint'ы

- `GET /health`
- `POST /api/anonymize`
- `POST /api/document/parse`
- `POST /api/documents/process`
- `POST /api/documents/process/start`
- `GET /api/documents/{session_id}`
- `GET /api/documents/{session_id}/status`
- `GET /api/documents/{session_id}/timeline`
- `GET /api/documents/{session_id}/export.docx`

Синхронный e2e-запрос:

```powershell
curl -X POST "http://127.0.0.1:8000/api/documents/process?jurisdiction=RU&use_ner=false" `
  -F "file=@C:\path\to\contract.docx"
```

Асинхронный старт обработки:

```powershell
curl -X POST "http://127.0.0.1:8000/api/documents/process/start?jurisdiction=RU&use_ner=false" `
  -F "file=@C:\path\to\contract.docx"
```

Проверка статуса:

```powershell
curl http://127.0.0.1:8000/api/documents/<SESSION_ID>/status
```

Получение timeline:

```powershell
curl http://127.0.0.1:8000/api/documents/<SESSION_ID>/timeline
```

Скачивание отчета:

```powershell
curl -o report.docx http://127.0.0.1:8000/api/documents/<SESSION_ID>/export.docx
```

## Артефакты

Для каждой сессии создается директория:

```text
.artifacts/<session_id>/
```

В ней сохраняются:

- `report.bin` - зашифрованный JSON-отчет;
- `anonymized.bin` - зашифрованный анонимизированный текст и spans;
- `report.docx` - итоговый DOCX-отчет;
- `events.json` - observability events;
- `pipeline.jsonl` - timeline выполнения.

## Тесты

```powershell
venv\Scripts\python -m pytest -q
```

## Документация

- [Product Proposal](docs/product-proposal.md)
- [Governance](docs/governance.md)
- [System Design](docs/system-design.md)
- [Agent Orchestrator Spec](docs/specs/agent-orchestrator.md)
