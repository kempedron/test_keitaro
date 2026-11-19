# Adrobot T3 — Keitaro Campaign Manager

Веб-приложение для управления рекламными кампаниями в трекере **Keitaro** через Admin API v1:

1. **Создаватель кампаний** — кампания + два потока (гео-редирект на Google и поток с оффером).
2. **Редактор офферов** — добавление/удаление офферов, ручные и автоматические доли, сохранение в Keitaro с проверкой фактически сохранённых значений.

Все создаваемые сущности кампаний имеют префикс **`test_vdovichenko_`** (настраивается через `CAMPAIGN_PREFIX`).

---

## Стек

- Python 3.11+ (проверено на 3.12)
- FastAPI, Uvicorn
- SQLAlchemy 2.0 (typed, `Mapped`), Alembic
- httpx (асинхронный клиент Keitaro Admin API v1)
- pydantic / pydantic-settings
- Jinja2 + Tailwind CSS (CDN) + Vanilla JS
- pytest, pytest-asyncio (httpx `MockTransport` для тестов ошибок)

---

## Структура

```text
.
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/0001_initial.py
├── alembic.ini
├── app/
│   ├── main.py                  # FastAPI, lifespan, статика, обработчик ошибок Keitaro
│   ├── config.py                # pydantic-settings (.env), префикс кампаний
│   ├── database.py              # engine, SessionLocal, Base, get_db
│   ├── models.py                # CampaignRecord, CampaignAuditLog
│   ├── schemas.py               # Pydantic-схемы REST API
│   ├── clients/
│   │   └── keitaro.py           # типизированный клиент Admin API v1
│   ├── services/
│   │   ├── campaign_creator.py  # Часть 1: создание кампании и двух потоков
│   │   ├── campaign_editor.py   # Часть 2: математика долей, PUT потока, верификация
│   │   ├── references.py        # кэш справочников и выбор FORTESTS по умолчанию
│   │   └── audit.py             # запись CampaignAuditLog
│   ├── routers/
│   │   ├── deps.py              # зависимости FastAPI
│   │   ├── pages.py             # HTML-страница
│   │   └── api.py               # JSON API
│   ├── templates/index.html
│   └── static/{styles.css,app.js}
├── tests/
│   ├── test_shares.py           # математика долей
│   ├── test_payloads.py         # сборка payload'ов кампании и потоков
│   ├── test_client_errors.py    # 401/404/422, таймауты, заголовки
│   ├── test_creator.py          # создание и очистка при частичном сбое
│   ├── test_editor.py           # сохранение долей, защита от расхождений
│   ├── test_enrichment.py       # имена домена/группы/источника и URL кампании
│   ├── test_api.py              # smoke-тесты API/страницы
│   ├── test_e2e_offline.py      # полный E2E на фейковом Keitaro (без сети)
│   └── test_e2e_live.py         # живой E2E (opt-in)
├── .env.example
├── .gitignore
├── requirements.txt
├── pytest.ini
└── README.md
```

---

## Быстрый старт

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# откройте .env и укажите KEITARO_API_KEY

alembic upgrade head
uvicorn app.main:app --reload
```

Интерфейс: <http://127.0.0.1:8000/>  
OpenAPI приложения: <http://127.0.0.1:8000/docs>

### Переменные `.env`

| Переменная | Назначение | Пример |
|---|---|---|
| `KEITARO_BASE_URL` | База Admin API v1 | `https://tlgk.host/admin_api/v1` |
| `KEITARO_API_KEY` | Ключ API (не коммитить) | `...` |
| `DATABASE_URL` | SQLAlchemy URL | `sqlite:///./app.db` |
| `CAMPAIGN_PREFIX` | Обязательный префикс кампаний | `test_vdovichenko_` |
| `HTTP_TIMEOUT` | Таймаут одного запроса к Keitaro, сек | `600` |
| `OFFER_CACHE_TTL` | TTL кэша справочников, сек | `60` |

PostgreSQL:

```env
DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/keitaro_manager
```

Для PostgreSQL установите драйвер (`pip install "psycopg[binary]"`) и выполните `alembic upgrade head`.

---

## Как работает создание кампании (Часть 1)

`POST /api/campaigns`

1. Название нормализуется: если нет префикса `test_vdovichenko_`, он добавляется автоматически. UI показывает живой preview.
2. Гео принимается как один код (`AU`) или список (`MX, AU, RO`), нормализуется в верхний регистр и проверяется через `pycountry` (ISO-3166-1 alpha-2).
3. Оффер проверяется запросом `GET /offers/{id}`. Если ключ не имеет права на чтение оффера (`403`), создание продолжается: существование оффера окончательно проверяет Keitaro при создании Потока 2. В UI для этого есть ручной ввод ID.
4. `POST /campaigns`:
   - обязательные `name`, `alias`;
   - `type=position`, `state=active`, `cost_type=CPC`, `cost_value=0`, `cost_currency=USD`;
   - `domain_id`, `group_id` (в запросе строкой, как требует схема), `traffic_source_id`.
5. `POST /streams` — **Поток 1** (`position: 1`, `type: regular`, `schema: redirect`):
   - фильтр `country`, режим `accept`, payload — список ISO-кодов;
   - `action_type: http`, `action_payload: https://google.com/`.
6. `POST /streams` — **Поток 2** (`position: 2`, `type: default`, `schema: landings`):
   - оффер `{offer_id, share: 100, state: active}`.
7. Успех пишется в `campaign_records` и `campaign_audit_logs` (`action=create`, `status=success`).
8. При ошибке Keitaro возвращается подробный HTTP-статус и текст; при частичном сбое созданная кампания мягко архивируется (`DELETE /campaigns/{id}`), в аудит пишется `status=error`.
9. При таймауте `POST /campaigns` / `POST /streams` сервис опрашивает Keitaro и подхватывает уже созданные объекты (alias/name и position/type), чтобы не плодить дубликаты на перегруженном стенде.

Домены, группы и источники по умолчанию: сначала ищется активная сущность с именем `FORTESTS`, иначе первый активный элемент. На стенде это группа `FORTESTS` (#10332) и источник `FORTESTS` (#836); домен `kylovoa.com` (#1813) выбран как первый активный.

---

## Как работает редактор (Часть 2)

`GET /api/campaigns/{id}` возвращает кампанию, все потоки, резолвленные имена офферов, `target_stream_id` (поток со схемой `landings` и офферами) и локальную запись. Кампания обогащается именами домена/группы/источника (`domain_name`, `group_name`, `traffic_source_name`) и ссылкой `campaign_url` вида `https://<domain>/<alias>`; при недоступности справочников UI откатывается на ID.

Математика (`app/services/campaign_editor.py`):

```python
def equal_shares(count: int) -> list[int]:
    if count <= 0:
        return []
    base, remainder = divmod(100, count)
    return [base + 1 if i < remainder else base for i in range(count)]
```

| N офферов | Доли | Сумма |
|---:|---|---:|
| 0 | `[]` | 0 |
| 1 | `100` | 100 |
| 2 | `50, 50` | 100 |
| 3 | `34, 33, 33` | 100 |
| 4 | `25, 25, 25, 25` | 100 |
| 7 | `15, 15, 14, 14, 14, 14, 14` | 100 |

- Добавление и удаление оффера автоматически перераспределяют доли через backend (`POST /api/shares/equalize`), поэтому JS и Python используют один и тот же алгоритм.
- Ручной ввод: сумма активных долей должна быть ровно `100`; кнопка сохранения блокируется при расхождении. Живой индикатор: `Итого: N%`.
- Дубликаты офферов запрещены и на клиенте, и на сервере.
- Если оффер не виден в автокомплите (у ключа нет доступа к `GET /offers`), его можно добавить по числовому ID; доля пересчитывается тем же алгоритмом. Это же доступно при создании кампании.
- Сохранение: `PUT /streams/{stream_id}` с полным набором ключевых полей (`name`, `type`, `position`, `schema`, `action_type`, `action_payload`, `filters` с `id`, `offers`) — имя, позиция, тип и фильтры не затираются.
- После `PUT` выполняется повторный `GET /streams/{id}`. Доли сверяются по `offer_id`; при расхождении возвращается `502` с фактическими и ожидаемыми значениями. Также проверяется, что Keitaro не изменил имя/тип/позицию/схему/фильтры.
- Каждое сохранение пишется в `campaign_audit_logs` (`add_offer` / `remove_offer` / `update_shares`) со снимком до/после и отправленным payload. Архивирование дополнительно пишется с `action=archive`.

---

## REST API приложения

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/` | HTML-интерфейс |
| GET | `/api/health` | health-check и текущий префикс |
| GET | `/api/references/offers?q=` | Автокомплит офферов (кэш) |
| GET | `/api/references/domains` | Домены + `default_id` |
| GET | `/api/references/groups` | Группы кампаний + `default_id` |
| GET | `/api/references/traffic_sources` | Источники + `default_id` |
| POST | `/api/campaigns` | Создать кампанию и два потока |
| GET | `/api/campaigns?mine=true&q=` | Список кампаний (фильтр по префиксу) |
| GET | `/api/campaigns/{id}` | Кампания, потоки, офферы, локальная запись |
| PUT | `/api/campaigns/{id}/streams/{stream_id}/offers` | Сохранить офферы/доли в Keitaro |
| POST | `/api/shares/equalize` | Детерминированный пересчёт долей |
| POST | `/api/campaigns/{id}/archive` | Мягкий архив только для кампаний с префиксом |
| GET | `/api/campaigns/{id}/audit` | Локальный журнал изменений |

Примеры:

```bash
curl -s http://127.0.0.1:8000/api/references/offers?q=Flexacil

curl -s -X POST http://127.0.0.1:8000/api/campaigns \
  -H 'Content-Type: application/json' \
  -d '{"name":"e2e_check","geo":"MX, AU","offer_id":18813}'

curl -s -X PUT http://127.0.0.1:8000/api/campaigns/123/streams/456/offers \
  -H 'Content-Type: application/json' \
  -d '{"offers":[{"offer_id":18813,"share":34,"state":"active"},{"offer_id":17210,"share":33,"state":"active"},{"offer_id":24800,"share":33,"state":"active"}]}'
```

---

## Интерфейс

- **Создать кампанию**: название с live-preview префикса, гео, мгновенный автокомплит оффера (debounce 120 мс, клавиатурная навигация) и ручной ввод ID, селекты домена/группы/источника с предвыбранным `FORTESTS`, спиннер, карточка результата с ID, alias, URL кампании и структурой потоков, кнопка «Открыть в редакторе».
- **Редактор**: список кампаний с поиском и фильтром «Только мои», открытие по ID, параметры кампании с именами домена/группы/источника и URL, все потоки (гео-фильтр и редирект видны явно), таблица офферов с удалением, добавлением через поиск или по ID, «Выровнять поровну», живой счётчик суммы, блокировка сохранения при сумме ≠ 100, подробные ошибки Keitaro (HTTP-статус + текст + payload) в модальном окне.

---

## Тесты

```bash
pytest -q
```

Покрыто:

- доли для `0, 1, 2, 3, 4, 7` и инвариант суммы для `0..25`;
- нормализация гео, префикса имени, alias;
- payload'ы кампании, Потока 1 (гео + Google), Потока 2 (оффер), `PUT /streams/{id}` с сохранением фильтров и `id` офферов;
- ошибки `401`, `404`, `422`, сетевые ошибки → `502`, проверка заголовка `Api-Key`;
- создание кампании, частичный сбой и автоархив, запись аудита;
- создание при `403` на чтение оффера (ручной ID);
- сохранение офферов, обнаружение расхождения фактических долей, выбор целевого потока;
- enrichment кампании именами справочников и `campaign_url`;
- smoke-тесты API и страницы;
- полный офлайн-E2E: создание → два потока → добавление трёх офферов (`34/33/33`) → удаление (`50/50`) → аудит → архив на stateful-фейке Keitaro (без сети).
- полный онлайн-E2E

## Безопасность и ограничения стенда

- API-ключ берётся только из `.env`; `.env` исключён в `.gitignore`, в коде/тестах/README ключа нет.
- Используются только кампании с префиксом `test_vdovichenko_`; архивирование чужих кампаний запрещено на уровне API-эндпоинта.
- Никакие деструктивные методы (`clean_archive`, `clicks/clean`, `DELETE /botlist`, `DELETE /logs/*`, `/users*`) не вызываются.
- Удаление тестовых кампаний — только мягкий архив `DELETE /campaigns/{id}`.
- Ключ стенда имеет ограниченные права на офферы: `GET /offers` возвращает только `18813`; `GET /offers/17210`, `/24800`, `/25327` дают `403`, а `POST /offers` — `403`. Поэтому в живом E2E для проверки долей использовались существующие офферы по ID (`18813`, `17210`, `24800`); их данные не изменялись — доли хранятся в потоке нашей тестовой кампании. В UI такие офферы добавляются ручным вводом ID.

---

## Разработка

- Спецификация Admin API: `https://admin-api.docs.keitaro.io/openapi.json` (публичное зеркало). URL `https://tlgk.host/admin/?object=adminApi.spec` требует сессию администратора и с `Api-Key` возвращает `403`.
- Создание новой миграции:

```bash
alembic revision --autogenerate -m "describe change"
alembic upgrade head
```

- Локальная БД по умолчанию: `./app.db` (SQLite). Модели совместимы с PostgreSQL.
- Ошибки Keitaro нормализуются: `{"error": ...}`, `{"name": ...}`, `{"errors": ...}`, текст; возвращаются с исходным HTTP-статусом (сетевые — `502`).

---

## Возможные проблемы

| Симптом | Решение |
|---|---|
| `KEITARO_API_KEY is not configured` | заполните `.env`, перезапустите приложение |
| `403 You have no permission to access this page - Offers` | ключ не имеет доступа к офферу; выберите доступный оффер или укажите его ID вручную |
| `422 Name has already been used in the archive` | имя кампании занято архивной записью; используйте уникальный суффикс |
| `502 Keitaro connection error (ReadTimeout)` | стенд перегружен; увеличьте `HTTP_TIMEOUT`, повторите операцию |
| `502 Keitaro did not persist the requested shares` | Keitaro сохранил другие проценты; смотрите payload в ответе/аудите |
| Миграции не применяются | проверьте `DATABASE_URL` и выполните `alembic upgrade head` |
