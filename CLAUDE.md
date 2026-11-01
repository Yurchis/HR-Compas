# HR Compass — контекст проекта для Claude

## Что это
Сквозной проект курса **AI Engineer** (материалы курса на украинском).
**HR Compass** — HR-бот, помощник для персонала, который знает ответы на вопросы,
связанные с компанией.

## Требования курса
### Что должно быть в репозитории
- код сервиса и схема;
- папка `prompts/` с версиями и changelog;
- `data/` с текстами и golden set;
- `results/` с выходами моделей;
- `REPORT.md` с отчётом-сравнением;
- `README.md`: как запустить и что нужно установить.

### Технические требования
- Python 3.11+, любой провайдер (OpenAI, Anthropic, Gemini и т.д.) **+ локальная модель**.
- Ключи — в `.env`, в репозиторий попадает только `.env.example`.
- Запуск одной командой (`make run` или `python main.py`).
- Стоимость старта: хватает бесплатных лимитов или до $5 на API; локальная модель должна
  работать на обычном ноутбуке.

## Состояние
- 2026-10-25: создана **только заготовка** (структура папок, `.env.example`, `.gitignore`,
  `Makefile`, `requirements.txt`, шаблоны README/REPORT/CHANGELOG, заглушка `main.py`).
  Провайдер, локальная модель, архитектура и данные ещё не выбраны — реализацию делает
  пользователь в рамках курса. **Не реализовывать проект без явной просьбы.**

- 2026-10-27: по явной просьбе реализована техническая часть: `main.py` (CLI/чат), intake
  (`prompts/intake_promt.md`, `hr_compass/intake.py`), `hr_compass/pipeline.py`, сравнение моделей
  (`evaluate --models`, алиасы `[models]` в `config/settings.toml`). Провайдер — OpenRouter, подход — full-context
  (весь хендбук в промпте). Не сделано: локальная модель, slug модели luna, LLM-judge, REPORT.
- 2026-10-31: golden set расширен до 10 вопросов (q06–q10).
- 2026-10-31: добавлен reranker (`hr_compass/retrieval.py`, `[rerank]`, `--rerank`; модель
  `nvidia/llama-nemotron-rerank-vl-1b-v2:free`, эндпоинт `/rerank`). По умолчанию выключен — основной подход
  по-прежнему full-context; при сбое rerank — откат на полный контекст.
- 2026-10-31: таблица отчёта генерируется `evaluate` (`table.md` в папке прогона; цены — `[pricing]`). В REPORT.md
  записан 1 прогон gpt-4o-mini / v2_structured (разделы 2–4); анализ и выводы (5–6) — за пользователем.
- 2026-11-01: REPORT 4.1 — v1 vs v2 на gpt-4o-mini / nemotron / haiku-5.5 (full-context, 6 прогонов) + колонка
  «мова = мова питання» (считалась скриптом, в `evaluate` её нет). v1 запускается с копией конфига, где
  `structured_output.enabled = false` (флага нет). Прогоны 2026-10-31 (rerank, REPORT 4.2) из `results/runs/` удалены.
  Запуск — через `.venv\Scripts\python.exe` (в системном python нет зависимостей).
- 2026-11-01: `Handbook - Ukraine.pdf` порезан на 25 чанков `data/raw/ua_*.json` (`country: "UA"`,
  `sub_company: ["IT-Product"]`, имена анонимизированы как в USA: MGNY → It Company). id совпадают с USA-шными
  (`2-4` есть в обеих странах) — различает только `country`. Все прогоны в REPORT сделаны на 58 USA-чанках;
  golden set без `country` теперь получает все 83 чанка. PDF Costa Rica побайтно совпадает с Ukraine.
- 2026-11-01: нарезка вынесена в `scripts/split_handbook.py` (`pypdf` в requirements). Набор Costa Rica
  (`data/raw/cr_*.json`, 25 шт., `sub_company: ["IT-Outsourcing"]`) — **намеренно** собран из украинского PDF с заменой
  Ukraine/Ukrainian → Costa Rica/Costa Rican; пользователь будет править cr-чанки вручную, поэтому НЕ перегенерировать
  их (скрипт без `--force` не перезаписывает). Всего 108 чанков; golden set без `country` получает все ~239k символов.
- 2026-11-01: в cr-чанках изменены 10 тестовых параметров (отпуск 18 дн./50 нед., без martial law, праздники CR с
  Guanacaste, 7 floating, больничный 50%/CCSS 60%, декрет 4 мес., отцам 8 опл. дней, aguinaldo, офис 8–17).
  Golden set заменён: 40 вопросов = 10 × USA/UA/Costa Rica (`qNN-usa/ua/cr`, с country+sub_company) + те же 10 без
  профиля (`qNN-any`).
- 2026-11-01: `evaluate` идёт через полный pipeline (`HRCompass.ask(question, country=, sub_company=)`; intake по
  умолчанию, `--no-intake`; при structured off intake авто-выключается). Golden set: `expected_kind` — 30 × `answer`,
  `qNN-any` × `clarification` (без keywords); колонка «Тип відповіді, %».
- 2026-11-01: промпт **v3** (`prompts/v3_country_clarification.md`): «во фрагментах несколько стран и страна не названа →
  уточнение» + явное правило «мова answer = мова питання». Своя схема `HRAnswerV3` (`needs_clarification`), задаётся
  первой строкой промпта `<!-- schema: hr_answer_v3 -->`; pipeline превращает её в `kind=clarification`.
  Правило именно в промпте (по просьбе пользователя), не в коде pipeline. Чат по умолчанию по-прежнему на v2.
  Прогоны в REPORT (q01–q10 старого набора) с новым golden set не сопоставимы.

## Соглашения
- Документы репозитория (README, REPORT, промпты, данные) — на украинском; общение — на русском.
- Новая версия промпта = новый файл в `prompts/` + запись в `prompts/CHANGELOG.md`.
- `.env` не коммитить.
