> Актуальные изменения после аудита: [Security Hardening](SECURITY_HARDENING.md).
> Описание автоматического исполнения ниже относится к исходной версии этапа; теперь каждый результат требует отдельного разрешения.

# Этап 5: хранение, восстановление и разрешения

Реализация 11 октября 2026, база 44d03a9. Независимый аудит безопасности
не выполнялся: пользователь поручил его отдельно другой модели.

## Основной режим

Очередь CLI по умолчанию: `.local/missions.sqlite3`. SQLite хранит документы
очереди, состояния сессий/turn, попытки, паузы, результаты проверок, snapshots,
статистику моделей, настройки и разрешения. Каждый переход — транзакция
BEGIN IMMEDIATE с synchronous=FULL. Версия схемы/application_id, quick_check
при открытии и checksum каждого payload проверяются. Повреждение, исчезновение
известной базы, неизвестная схема и недостающие журналы останавливают работу.
Инициализация, оборванная до первого документа, не трактуется как пустая очередь.
Состояния queue и managed записываются последовательными транзакциями;
managed evidence и dispatchStarted позволяют безопасно обработать разрыв между ними.

Windows: payload и layout защищены CryptProtectData / CryptUnprotectData
(DPAPI, current user, UI forbidden, без открытого fallback). Это защита данных
на диске в рамках профиля Windows, а не от процессов под тем же пользователем.
Ключи и пароли приложение не сохраняет; авторизация остаётся у Codex.
На других ОС документы не шифруются, новый файл создаётся с mode 0600;
не-Windows интеграция в этом этапе не проверялась. Основная платформа — Windows.

Событийный журнал содержит только время и категорию, максимум 200 записей.
Содержимое задания/ответа необходимо для точного восстановления; оно находится
в защищённых документах. Старые JSON режимы этапов 1–3 остаются совместимыми
диагностическими режимами и не получают шифрование SQLite автоматически.

## Разрешения

Пример для отдельного исходного проекта (путь должен существовать):

```powershell
.\.venv\Scripts\mission-control.exe queue-configure --allow-root C:/Projects/MyApp
.\.venv\Scripts\mission-control.exe queue-add --mission mission.json
# Перед этой командой просмотрите manifest, task, input/writeFiles и все argv.
.\.venv\Scripts\mission-control.exe queue-approve --mission-id my-task
.\.venv\Scripts\mission-control.exe queue-run
```

Исходный проект должен быть отделён от базы/приватных workspaces. Разрешённый
root не может содержать базу и её run root. Имена/пути и junction/reparse points
проверяются, модель получает только явно выбранные bounded UTF-8 файлы.
Доступ по умолчанию запрещён. `approved: true` в manifest недостаточно:
`queue-approve` — явное подтверждение оператором задания и точных команд.
SHA-256 связывает разрешение с task, criteria, путями, argv, mode, budget, policy
и dependencies; при изменении требуется новое подтверждение. Изменение разрешённых
roots отзывает approvals. Во время активного задания настройки/разрешения заморожены.
Исключение: однократная первичная выдача разрешений для активной legacy-очереди
при явной миграции; после выдачи также действует заморозка.

Проверки запускают заранее подтверждённый доверенный код с правами пользователя
ОС. Они не являются песочницей для недоверенного кода: Python/сборка могут иметь
свои файловые, сетевые и подпроцессные эффекты. Предел пути контролирует действия
контроллера, а не права любого подтверждённого приложения. Модель не получает
произвольное исполнение команд; разрешение проверяется до dispatch и восстановления.
При необходимости сильной изоляции нужен отдельный OS sandbox, который здесь
не реализован. Проект не публикуется и исходные файлы автоматически не заменяются.

## Конфиденциальность

Очевидные API keys, private keys, password assignments, известные секретные
переменные окружения и типовые credential-файлы отклоняются перед snapshot/send.
Диагностика проверок ограничена 8192 bytes и редактируется до receipt/repair prompt.
CLI reports проходят рекурсивную фильтрацию строк. Фильтр эвристический:
обфусцированные, неизвестные и частично усечённые секреты не гарантированно обнаружатся.
Не включайте секреты в задания/файлы/названия; это не DLP и не очистка истории Codex.

Workspace, result.diff и private Git objects остаются обычными локальными файлами.
Выбранные исходники могут быть приватными даже без паролей — права каталога,
шифрование диска и настройки OneDrive/резервного копирования остаются задачей ОС.
Приложение не собирает скрытые файлы проекта и не копирует пользовательский `.git`.
Нет автоматической очистки пользовательских артефактов или паролей из старых JSON.

## Git checkpoints

Перед первым turn нового SQLite project mission создаётся приватный bare repository
в run root. Git plumbing записывает blobs из сохранённого baseline, private index,
commit и refs/checkpoints/baseline. Не используются исходный Git index, глобальные
Git настройки, hooks, фильтры, reset, checkout, clean, stash или overwrite.
Checkpoint receipt защищён в SQLite; восстановление проверяет commit, перечень
файлов и каждый hash. Частично созданный checkpoint сохраняется для разбора,
а не пересоздаётся поверх неизвестного состояния.

```powershell
.\.venv\Scripts\mission-control.exe queue-checkpoint-export --mission-id my-task --destination C:/Recovery/MyApp-baseline
```

Экспорт берёт worker lease: сначала остановите живой worker; unresolved reservation
при этом сохраняется. Можно извлечь baseline остановленного uncertain задания.
Экспортирует только выбранный baseline в новую папку вне разрешённых исходных
roots и controller workspaces; existing destination запрещён. Это не полный backup
репозитория/бинарных файлов/метаданных. Автоматического применения результата или
отката исходного проекта нет. При миграции checkpoint создаётся в момент импорта
из сохранённого baseline, без заявления о наличии checkpoint до старых операций.

## Миграция и backup

```powershell
.\.venv\Scripts\mission-control.exe queue-migrate --legacy-queue .local/missions.json --queue .local/missions.sqlite3
.\.venv\Scripts\mission-control.exe queue-configure --allow-root C:/Projects/MyApp
.\.venv\Scripts\mission-control.exe queue-approve --mission-id my-task
.\.venv\Scripts\mission-control.exe queue-backup --destination .local/archive.sqlite3
```

Миграция требует source/destination в одной папке; импортирует JSON документы одной
транзакцией, сохраняет прежние cwd/thread/run paths и переносит durable reservation
под общей worker lease. Повторный вызов завершает handoff без перезаписи DB.
Original JSON остаются; новые private checkpoints не изменяют исходный проект.
Запуск legacy JSON через CLI запрещён. Python API JSON оставлен для совместимости;
не используйте его как защищённый режим автономной очереди.

Backup использует SQLite backup API и integrity_check, только новый файл,
сохраняя DPAPI. Защищённый layout привязан к пути основной базы: непомеченная копия на другом
пути отвергается, в том числе при сбое до записи backup marker.
Копия отмечена архивной/read-only и не запускается как очередь:
старая копия может не знать о выполнении запросов после её создания. Автоматического
восстановления произвольной старой копии нет. Для disaster recovery требуется
сверка с последним журналом и серверной историей. Backup не копирует workspace/Git
objects; сохраняйте приватный run root отдельно, не публикуя его. Layout привязан
к исходной папке; перенос на другой путь/профиль Windows автоматически не поддержан.

## Восстановление и остановки

После перезапуска Windows/контроллера повторите `queue-run --queue ...`:
очередь сохраняет приоритеты, зависимости, активное задание, выбранную модель,
effort, бюджет, политику лимитов, thread и turn. Автозапуск Windows/служба — будущая
работа, в этапе 5 не устанавливаются. Работающий worker сам ждёт reset/backoff;
во время ожидания App Server закрыт, polling ограничен и растёт до одного часа.
До новой отправки читаются реальные account/model/list/rate limits.
Недоступная конфигурация до отправки — waiting_model с backoff, без платного turn.
Сеть/закрытие Codex — waiting_network и reconciliation; auth требует codex login.

После ack используется сохранённый turn ID. После потерянного ack допускается
единственный новый turn с точным prompt относительно baseline истории. Потенциально
выполненный запрос не отправляется повторно при отсутствии доказательства.
Active turn наблюдается, completed проверяется. Unknown/missing history, active
foreign writer, missing receipts/checkpoint, source drift и конфликты безопасно
останавливают очередь. Смена модели не подменяет thread. Repair ограничен 1..8
попытками с cumulative budget, partial check outcome не повторяется. Состояние
не снимает remote writer lock и не продолжает генерацию побайтово.

## Проверки и отдельный аудит

Автотесты используют offline Codex service/NDJSON, реальные SQLite/DPAPI/Git и
локальные процессы. Forced exit после acknowledgement -> новый процесс -> тот же
turn, ровно одна отправка. Forced exit внутри SQLite transaction -> прежний документ.
Проверены quota/network/auth/unknown outcomes, потерянный ack, модель вне каталога,
проверки реальных файлов, редактирование diagnostics, explicit permissions,
сохранность staged/unstaged/untracked и безопасный export, миграция text/project.
Реальные квоты не исчерпывались; новых платных Codex-вызовов на этапе 5 нет.
Настоящая перезагрузка Windows, потеря питания и другой Windows-профиль не проверялись.

Отдельному независимому аудиту нужны: DPAPI/ACL/SQLite payload и sidecars;
граница доверия approvals/argv и процессы с правами пользователя; path/junction/TOCTOU;
секреты в prompts/diagnostics/workspaces; миграция/reservation/crash windows;
проверка checkpoint objects и восстановление неизвестных remote outcomes.
Этот документ описывает реализацию и результаты тестирования, не независимый аудит.


Финальная проверка 11 октября 2026:
- `.venv/Scripts/python.exe -m pytest -q --tb=short`: **240 passed, 1 skipped**, 66.17s.
- Skip: Windows symlink privilege; junction regression passed.
- `.venv/Scripts/python.exe -m compileall -q src`: exit 0.
- `.venv/Scripts/python.exe -m pip check`: No broken requirements found.
- Реальные интеграционные компоненты в тестах: SQLite, Windows DPAPI, Git,
  файловые проверки, локальные subprocess/forced exits. Codex ответы/лимиты — offline fixtures.
- Этапы 1–4 входят в полный regression suite. Живой inference этапа 5 не запускался.
