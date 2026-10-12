# Concept C Evolution Implementation Plan

**Goal:** Улучшить понимание состояний и управление задачами через единый нативный GUI.
**Architecture:** Существующие bridge и страницы сохраняются. Общие Qt-компоненты,
семантические токены и presentation-only функции работают с существующими snapshots.
**Tech Stack:** PySide6 Qt Widgets, Python, SQLite без миграций, текущий RU/EN catalog.
**Spec:** [STAGE12-DESIGN.md](STAGE12-DESIGN.md).
**Execution:** Inline implementation; независимое ревью всей ветки после реализации.
Предварительное согласование каждой детали пользователь явно отменил для Concept C Evolution.

## Global constraints

- Base main: `f9c58f164b96bd899ca6cf0c56c023785ec4778c`.
- Не менять backend, author/committer, MIT, App Server или схемы данных.
- Никаких реальных inference-вызовов, платных кредитов, Release или установщика.
- Stage 11 не переносить; Stage 12 не публиковать без подтверждения.
- Новые строки добавлять в `translations.json` RU/EN.

## Review focus

Неизвестные/устаревшие лимиты; исчезнувшая из каталога выбранная модель;
фильтрация скрывает выбранную миссию; запрос отмены не означает подтверждённую остановку;
переключение языка/темы не сбрасывает выбор и не выдаёт разрешение.

## Tasks

- [x] **1. Общие компоненты и токены** (`theme.py`, `components.py`, `presentation.py`).
  Red tests: `test_stage12_state_priority`, `test_stage12_limit_freshness`,
  `test_stage12_responsive_columns`, семантический контраст обеих тем.
  Реализовать общий баннер состояния, адаптивную пару панелей и сводку показателей.
  Проверить и закоммитить самостоятельную основу.
- [x] **2. Dashboard** (`window.py`, `visuals.py`).
  Red tests: существенные состояния, причины выбора, реальные следующие задачи,
  запрос отмены остаётся неподтверждённым. Сохранить существующие контролы/API.
  Убрать пустые карточки и декоративную доминанту; проверить малое окно и reduced motion.
- [x] **3. Interactive Router** (`router.py`, `visuals.py`, `presentation.py`).
  Red tests: только реальные ID, policy ceiling, hidden/input modalities,
  отсутствующая выбранная модель, инспекция узла не вызывает bridge request.
  Дать графу мышь/клавиатуру и равноправное текстовое представление всех моделей.
- [x] **4. Missions** (`missions.py`).
  Red tests: поиск/фильтр, ID после перестановки, скрытый выбор отключает действия,
  зависимости, отсутствие изменений пользовательского текста и определения задачи.
  Добавить поиск, фильтр, детали и честное отображение pending stop/pause.
- [x] **5. Остальные экраны** (`insights.py`, `approvals.py`, `settings.py`, `overlay.py`).
  Red tests: неизвестные лимиты, возраст данных, реальные soft-pause причины,
  финансовые предупреждения, неизменность approvals. Общая типографика/состояния.
- [x] **6. GUI QA и производительность** (`tools/capture_stage12.py`, tests).
  Снимки RU/EN × Dark/Light; размеры/DPI; error/empty/large queue/attention/wait.
  Измерить idle CPU/memory, задержку event loop и обновление большой очереди.
  Запустить полный pytest и независимое ревью; исправить находки и повторить проверки.
- [x] **7. Подготовка результата** (docs, screenshot gallery).
  Проверить чистую локальную копию, secret scan, original HEAD/17 commits,
  состав staged changes и идентичность каждого нового коммита.
  Финальный отчёт и остановка перед публикацией Stage 12.

## Ledger

- Localization PR #1 merged by fast-forward; owner author/committer preserved.
- Ruling: сохраняем текущие navigation destinations и нативное окно; scope — GUI evolution.
- Ruling: UI/UX database предложила landing-page patterns, не подходящие нативному desktop;
  используются проверенные рекомендации по focus и Qt/Fluent, без web-компонентов/шрифтов.

- Implementation commits: 40cdc91, 51948f6, 61bcd6e, 35b5f08.
- Independent review: 3 presentation findings fixed, rechecked, no remaining findings.
- Windows QA: 214 native captures, offline only; Qt scaling 100/125/150/200%, no OS DPI changes.
- Clean clone: wheel/sdist, RU/EN native startup, seven pages, no connection checks.
- Original repository: 17 commits, HEAD 5e6128bee9e4b439ddf25d82c46a673e9385c6ae, clean.
- Stage 12 stays local pending owner confirmation. Details: ../STAGE12.md.
