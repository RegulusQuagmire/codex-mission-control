# Security Hardening после аудита Astra

Этап 6 не начат. Изменены существующие механизмы этапов 1–5.

## Выполнение результата (C1)

По умолчанию проектное задание сохраняет edits/diff и останавливается в
`waiting_approval` **до запуска любой команды проверки**. Исходное разрешение
`queue-approve` разрешает получение предложения, но не его исполнение.

```powershell
.\.venv\Scripts\mission-control.exe queue-run
.\.venv\Scripts\mission-control.exe queue-review-result --mission-id my-task
# Просмотрите result.diff, ВСЕ файлы workspace, argv и внешние зависимости команд.
.\.venv\Scripts\mission-control.exe queue-approve-result --mission-id my-task --review-id <reviewId> --accept-user-rights
.\.venv\Scripts\mission-control.exe queue-run
```

Разрешение связано с response/spec, полным набором и SHA-256 файлов workspace,
diff и конкретным turn. Новая попытка требует нового разрешения. Изменение или
добавление файла аннулирует разрешение. Approval потребляется durable `started`
receipt до первой команды; после неизвестного исхода цепочка не повторяется.
Ожидание возвращает управление и не держит App Server. Проверенный завершённый
ответ с сохранённой effective configuration валидируется локально без новой
сессии/отправки. Smart Router и ограниченные repair/escalation сохранены, но
каждый новый исполняемый результат снова требует просмотра.

**Это режим с ручным разрешением, а не ОС-песочница.** После `--accept-user-rights`
оператор сознательно разрешает данному коду работу с правами Windows-пользователя,
включая файлы, сеть и credentials профиля. Проверка argv/хешей, Job Object и
очищенное окружение не ограничивают эти права. Полностью автономное исполнение
недоверенного кода ночью требует отдельной изолированной среды; её здесь нет.
Исполняемые файлы и зависимости вне workspace тоже должны быть доверенными.
Процессы, уже имеющие тот же Windows identity, не являются изолированными
противниками: они могут вмешиваться в память/настройки и расшифровывать DPAPI.

## Файлы и receipt (H1, M2)

Контроллер не пишет поверх существующего inode. Workspace edits, diff, JSON,
экспорт и создание backup используют уникальный temp, fsync и атомарную замену
записи каталога. На Windows предки удерживаются дескрипторами без SHARE_DELETE;
reparse objects и hard links отклоняются по фактически открытому объекту.
Подстановка hard link после проверки цели также не меняет внешний inode.
SQLite и lock files удерживаются открытыми при использовании. Лимиты файлов и
пространства имён сохранены. Windows API: [CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew),
[MoveFileExW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-movefileexw).

Изменённые результаты и diff сбрасываются на диск до успешного receipt;
невозможность flush не считается успехом. При новом запуске QueueWorker сверяет
завершённые project artifacts с durable hashes. Утрата или изменение результата
останавливает очередь с needs_attention; inference автоматически не повторяется.
Это последовательный fail-closed протокол, не общая транзакция NTFS+SQLite.
Реальное отключение питания и гарантии аппаратного дискового кеша не проверялись.
POSIX ветка использует dir_fd/O_NOFOLLOW; в этой работе тестировалась Windows.

## Секреты (H2)

Короткие/составные password assignments, credential URL, AWS secret access keys,
Basic/Bearer, refresh/access tokens, private keys и credential-файлы отклоняются
до копирования/отправки. Применение overlays повторно проверяется. Prompt feedback
редактируется; checkpoint create/verify/export проверяют baseline независимо от
старого snapshot. Ответ модели с обнаруженным секретом заменяется целиком
маркером и останавливает managed run; новый секрет не сохраняется в JSON-журнале.
Проверки и Git получают минимальное окружение без API keys и PYTHONPATH/инъекций.
App Server получает отдельный allowlist с путями профиля/конфигурации для login,
без ambient API keys. Используйте авторизацию Codex в сохранённом профиле.

Фильтр эвристический и консервативный: возможны false positives и пропуски
неизвестных/обфусцированных форматов. Это не DLP. Не включайте секреты в выбранные
файлы. DPAPI защищает payload SQLite только в рамках профиля; workspace/Git/diff
остаются открытыми локальными файлами. Ранее созданные JSON/backups/история Codex
не очищаются автоматически. Старые исходники сохраняются для пользователя.

## Неопределённый исход, лимиты и миграции (H3, M1, M3)

Обычный queue-retry отвергает not_retryable. Только после ручной сверки внешних
побочных эффектов оператор может вызвать `queue-retry --mission-id my-task
--acknowledge-uncertain-result`; подтверждение записывается в archive. Это может
повторить операцию, поэтому не используется автоматически. Неидентифицированные
remote turns и незавершённые submitted phases этим флагом не обходятся.

Weekly без достоверного окна 10080 минут остаётся limits_unknown даже при
ordinaryUsageAllowed=true. Сохраняются backoff, свежая проверка и общий budget.

До создания destination DB миграция фиксирует durable handoff рядом с legacy
source (`<queue>.migration.json`). Повтор разрешён только в ту же базу; другая
destination и исполнение старого JSON после handoff отвергаются. После сбоя
повторите миграцию с теми же путями. Удалять marker для обхода защиты нельзя.
Произвольные вручную переименованные/скопированные legacy-источники не обладают
общей внешней идентичностью; автоматическое определение таких копий не обещается.

Отмена до первого исполнения освобождает reservation без запуска команд.
Между командами validator проверяет pause/cancel; начатая команда завершается
по своему timeout. Если цепочка прервана после команды, результат not_retryable,
а не replay. Это кооперативная отмена, не аварийный kill по кнопке очереди.

## Проверка

`tests/test_security_hardening.py` воспроизводит сценарии Astra с собственными
временными файлами и синтетическими секретами. Реальные subprocesses, NTFS hard
links и Windows handles проверяются без inference. Прежние тесты не удалены:
тестовые operator helpers явно подтверждают каждый доверенный fixture-результат,
после чего сохраняются прежние assertions на реальные команды/repair/состояния.
Security tests используют raw runners и проверяют отсутствие исполнения до
approval. Протокольные, принудительное завершение, DPAPI, очередь, routing и
лимиты проверяются общим набором. Точный результат запуска приведён в отчёте.

Старые успешные project receipts без hash diff требуют ручной сверки: они не
превращаются автоматически в новые подтверждения и не перезапускаются.

CLI --output создаёт только новый файл, включая защиту от создания цели между
проверкой и записью; путь handoff marker исключён из путей отчёта миграции.

Итоговый полный прогон: **282 passed, 1 skipped за 170.12 s**. Пропущено
создание symlink без Windows-привилегии; junction/hard links проверены.
Команда: `.venv/Scripts/python.exe -B -m pytest -q -p no:cacheprovider --tb=short`
с отдельным basetemp и PYTHONDONTWRITEBYTECODE=1. `pip check` и
`git diff --check` прошли. Реальный doctor подтвердил ChatGPT login, семь
моделей и оба окна лимитов без inference.
