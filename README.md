# HydraX — Карта знаний R&D (кейс «Научный клубок»)

Единая карта знаний для горно-металлургических исследований: система строит граф
знаний по корпусу документов (отчёты, статьи, патенты) и отвечает на сложные
многопараметрические запросы с цитатами — материал + процесс + условия +
география + числовые ограничения.

LLM вызывается **только на запрос пользователя**, а не на каждый документ —
обработка корпуса локальная и бесплатная (словари + правила + локальные
эмбеддинги).

---

## 🚀 Быстрый старт (одна команда)

Требуется только **Docker** (Docker Desktop на Windows/Mac или docker + compose plugin на Linux).

```bash
# 1. Положить документы (PDF/DOCX/XLSX/TXT, ZIP/RAR) в ./corpus
mkdir -p corpus && cp /путь/к/документам/* corpus/

# 2. Поднять весь стек
docker compose up -d --build
```

Готово:

| Адрес | Что это |
|---|---|
| http://localhost:8000 | Приложение (вход — демо-учётки ниже) |
| http://localhost:7474 | Neo4j Browser (neo4j / testpass) |
| http://localhost:8080 | Keycloak Admin Console (admin / kcadmin123) |

Проверка, что данные загрузились: `curl localhost:8000/api/stats` →
`"neo4j": true` и `nodes > 0`.

API-ключ LLM нужен **только для генерации текстовых ответов** (поиск, граф,
аналитика работают без него):

```bash
YANDEX_API_KEY=AQVN... YANDEX_FOLDER_ID=b1g... docker compose up -d --build
```

Основной провайдер — **Yandex AI Studio (YandexGPT)**; Anthropic Claude —
резервный (`ANTHROPIC_API_KEY`, ключ по умолчанию уже прописан в
`docker-compose.yml` для демо). Принудительный выбор — `LLM_PROVIDER=yandex|anthropic`.

### Что происходит при `docker compose up`

1. Стартуют `neo4j` (пароль `testpass`) и `keycloak` (realm `hydrax` импортируется автоматически).
2. Разовый сервис `ingest` распаковывает архивы в `./corpus` и прогоняет
   пайплайн Stage 1–5, складывая артефакты в `./hydrax_out`.
3. После успешного завершения `ingest` стартует `app`.

### ⚡ Инкрементальная сборка — повторные запуски за секунды

Пайплайн **автоматически пропускает готовые стадии**: каждая стадия
выполняется, только если её артефакта нет или входные данные новее. Если папка
`./hydrax_out` уже готова (например, приехала вместе с архивом проекта),
`ingest` за пару секунд проверит всё и завершится, догрузив граф в Neo4j
только если он пуст:

```
[skip] Stage 1 — documents.ndjson актуален (N документов)
[skip] Stage 2 — chunks.ndjson актуален (N чанков)
[skip] Stage 3 — extracted.ndjson актуален (N записей)
[skip] Stage 4 — граф уже загружен (N узлов)
[skip] Stage 5 — векторный индекс актуален
```

Типовые операции:

```bash
# Добавили документы в ./corpus — переиндексировать (пересчитаются только нужные стадии)
docker compose stop app && docker compose run --rm ingest && docker compose start app

# Принудительный полный пересчёт всех стадий
docker compose stop app && HYDRAX_FORCE=1 docker compose run --rm ingest && docker compose start app

# Полный сброс (включая граф Neo4j и Keycloak)
docker compose down -v && rm -rf hydrax_out && docker compose up -d --build
```

> `app` нужно останавливать перед ручным прогоном `ingest`, только если
> реально нужна переиндексация: embedded Qdrant блокирует папку. Если все
> стадии актуальны, `ingest` не трогает Qdrant и спокойно работает при
> запущенном `app`.

## 👤 Демо-учётки

| Логин / пароль | Роль | Доступ |
|---|---|---|
| `admin` / `admin123` | Администратор | всё + админ-панель (аудит, входы, пользователи) |
| `manager` / `manager123` | Руководитель проекта | все данные вкл. коммерческую тайну |
| `analyst` / `analyst123` | Аналитик | внутренние данные, радар, экспорт |
| `researcher` / `researcher123` | Исследователь | внутренние данные, экспорт |
| `partner` / `partner123` | Внешний партнёр | только открытые документы, без экспорта |

Аутентификация — через **Keycloak** (OIDC, поднимается автоматически, realm
импортируется из `keycloak/realm-hydrax.json`, регистрация включена). Без
`KEYCLOAK_URL` приложение работает в локальном режиме с теми же демо-учётками.

Документы классифицируются по уровням `public / internal / confidential`
(по имени файла); поиск, ответы и списки фильтруются по допуску роли. Все
действия и входы (с GeoIP и детекцией подозрительной активности) логируются —
журнал доступен админу на странице «Администрирование».

## 🧭 Что смотреть в интерфейсе

- **Поиск** — семантический поиск с диалогами: стриминг ответа с цитатами `[N]`,
  режимы «Ответ / Обзор / Сравнение», гео-фильтр 🇷🇺/🌍 (отечественная vs
  зарубежная практика), числовые ограничения («не более 50 л/мин» распознаётся
  и сопоставляется с параметрами графа), стили ответа (кратко / академично /
  простым языком), голосовой ввод 🎤, экспорт в Markdown / JSON-LD / PDF.
- **Дашборд** — личный кабинет под роль: быстрые действия, счётчики активности,
  последние диалоги; состав базы, противоречия, рекомендации.
- **Граф знаний** — визуализация с досье сущности (материал → процесс →
  оборудование → результат).
- **Аналитика, Матрица покрытия, Пробелы** — покрытие знаний по доменам, слабо
  изученные комбинации.
- **Мировая наука, Радар исследований, Связи-мосты, Верификация** — внешние
  публикации, тренды, междоменные связи, верификация фактов.

## Архитектура

```
корпус (PDF/DOCX/DOC/XLS/XLSX/TXT, ZIP/RAR)
  → Stage 1  ETL: текст + OCR                 (ingest.run)
  → Stage 2  чанкинг                          (ingest.chunker)
  → Stage 3  извлечение сущностей:
       local — словари + regex, без LLM       (ingest.local_extractor)  ← default
       llm   — Claude по каждому чанку        (ingest.extractor)
  → Stage 4  граф знаний в Neo4j              (ingest.graph)
             (версионирование фактов: version + updated_at на узлах и связях)
  → Stage 5  векторный индекс (Qdrant embedded + multilingual ONNX-эмбеддинги)
                                              (search.indexer)
  → Веб-приложение: гибридный поиск (вектор + граф) + ответ LLM с цитатами
                                              (app.main, FastAPI + React)
```

Оркестратор пайплайна — `run_pipeline.py`; все стадии инкрементальны
(см. docstring в файле: `HYDRAX_FORCE`, `HYDRAX_SKIP_*`, `HYDRAX_EXTRACTOR`).

### Режимы Stage 3

| Режим | Как включить | Стоимость | Скорость |
|---|---|---|---|
| `local` (default) | — | $0 | ~30k чанков за минуты |
| `llm` | `HYDRAX_EXTRACTOR=llm` | ~$3–5 за 1k чанков | часы |

## Запуск без Docker (для разработки)

<details>
<summary>Linux / macOS</summary>

```bash
pip install -r ingest/requirements.txt -r search/requirements.txt uvicorn fastapi

docker compose up -d neo4j        # Neo4j из того же compose (не отдельным docker run!)

python prepare_corpus.py --input ./corpus
HYDRAX_INPUT=./corpus python run_pipeline.py

YANDEX_API_KEY=AQVN... YANDEX_FOLDER_ID=b1g... \
QDRANT_PATH=./hydrax_out/qdrant_data uvicorn app.main:app --port 8000
```
</details>

<details>
<summary>Windows PowerShell</summary>

```powershell
pip install -r ingest/requirements.txt -r search/requirements.txt uvicorn fastapi

docker compose up -d neo4j

python prepare_corpus.py --input .\corpus
$env:HYDRAX_INPUT = ".\corpus"
python run_pipeline.py

$env:YANDEX_API_KEY   = "AQVN..."
$env:YANDEX_FOLDER_ID = "b1g..."
$env:QDRANT_PATH      = ".\hydrax_out\qdrant_data"
uvicorn app.main:app --port 8000
```
</details>

<details>
<summary>Фронтенд (React + Vite + Tailwind)</summary>

```bash
cd frontend
npm install
npm run dev     # дев-сервер c proxy на :8000
npm run build   # прод-сборка в frontend/dist — её отдаёт FastAPI
```

В Docker-сборке фронтенд собирается автоматически (multi-stage Dockerfile).
Если `frontend/dist` нет, FastAPI отдаёт запасной одностраничный UI из `app/static`.
</details>

## API

- `POST /api/search` `{query, top_k}` — гибридный поиск: чанки + факты графа + распознанные сущности
- `POST /api/answer` `{query, top_k, geo?, style?}` — то же + ответ LLM с цитатами `[N]`
- `POST /api/answer/stream` `{query, top_k, session_id?, geo?, style?}` — SSE-стриминг с контекстом диалога
- `POST /api/graph` `{query}` — подграф для визуализации; `GET /api/graph/full?limit=N` — глобальный граф
- `GET /api/documents`, `/api/analytics`, `/api/stats`, `/api/gaps` — корпус, аналитика, пробелы
- `GET /api/me/overview` — личный кабинет: счётчики активности, последние диалоги
- `GET/POST /api/sessions`, `GET/DELETE /api/sessions/{id}` — сессии чата
- `POST /api/auth/login|refresh`, `GET /api/auth/me` — авторизация (Keycloak/локальный режим)
- `GET /api/admin/summary|audit|logins|users` — админ-панель (роль admin)
- `POST /api/audit/export` — логирование экспорта

Все data-эндпоинты требуют `Authorization: Bearer <JWT>`.

## 🛠 Troubleshooting

| Симптом | Причина / решение |
|---|---|
| Граф пустой, `nodes: 0` | Пайплайн гнали против другого Neo4j (ручной `docker run`). Использовать Neo4j из этого compose: `docker compose run --rm ingest` |
| «Storage folder … already accessed» | `app` держит embedded Qdrant. `docker compose stop app`, прогнать `ingest`, `docker compose start app` |
| Старый UI после `git pull` | Пересобрать образ: `docker compose up -d --build` |
| «Ошибка LLM» в ответах | Не задан `YANDEX_API_KEY`/`YANDEX_FOLDER_ID` (или резервный `ANTHROPIC_API_KEY`). Поиск и граф работают без ключей |
| Стадии пересчитываются заново | mtime файлов корпуса новее артефактов (например, свежий clone). Это безопасно; ускорить: `HYDRAX_SKIP_EXTRACTION=1` и т.п. |

## Документация проекта

- `Memory.md` — подробный контекст проекта для разработчиков/ИИ
- `REPORT.md` — отчёт о проделанной работе, соответствие требованиям кейса
- `docs/` — дополнительные материалы
