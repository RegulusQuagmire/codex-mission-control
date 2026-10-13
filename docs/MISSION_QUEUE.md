> Актуальные изменения после аудита: [Security Hardening](SECURITY_HARDENING.md).
> Описание автоматического исполнения ниже относится к исходной версии этапа; теперь каждый результат требует отдельного разрешения.

# Mission Queue — использование этапов 4–5

Запускайте CLI из папки router. Очередь по умолчанию: `.local/missions.sqlite3`.
Все управляющие команды работают без Codex; только `queue-run` вызывает inference.

```powershell
.\.venv\Scripts\mission-control.exe queue-configure --allow-root C:/projects/example
.\.venv\Scripts\mission-control.exe queue-add --mission mission.json
.\.venv\Scripts\mission-control.exe queue-approve --mission-id fix-add
.\.venv\Scripts\mission-control.exe queue-list
.\.venv\Scripts\mission-control.exe queue-priority --mission-id fix-add --priority 20
.\.venv\Scripts\mission-control.exe queue-run
.\.venv\Scripts\mission-control.exe queue-pause
.\.venv\Scripts\mission-control.exe queue-resume
.\.venv\Scripts\mission-control.exe queue-cancel --mission-id fix-add
.\.venv\Scripts\mission-control.exe queue-retry --mission-id fix-add
```

`queue-resume` снимает флаг паузы. Если worker уже вышел, затем нужен `queue-run`.
Флаг `--queue path.sqlite3` выбирает другую очередь. `--codex` принимает полный путь
к Codex. `--max-wait 0` возвращает управление при необходимости ожидания, сохраняя
задание; без этого флага worker ждёт автоматически. Это лимит времени ожидания,
а не ограничение длительности inference. Последующие `queue-run` используют те
же журналы; успешно завершённые задания не отправляются повторно.

## Manifest проектного задания

Пример требует адаптации абсолютных путей и команд к вашему проекту. `approved:true`
обязательно для manifest, но в SQLite окончательное подтверждение точного argv
выдаётся отдельно через queue-approve после просмотра задания. Модель не может
выбирать или добавлять команды. Укажите абсолютный путь к Python вашего окружения,
если зависимости проекта находятся в venv. Дополнительные входы, тесты и ресурсы
нужно перечислить явно — копируется только выбранная область.

```json
{
  "id": "fix-add",
  "title": "Исправить сложение",
  "type": "project",
  "project": "C:/projects/example",
  "priority": 10,
  "dependsOn": [],
  "mode": "economy",
  "maxAttempts": 3,
  "turnTimeout": 120,
  "policy": {"mode": "balanced", "threshold": 100},
  "task": {
    "text": "Исправь add в app.py, чтобы тесты проходили",
    "operation": "code",
    "estimated_files": 1,
    "risk": "low"
  },
  "criteria": {
    "project": "C:/projects/example",
    "inputFiles": ["app.py", "tests/test_app.py"],
    "writeFiles": ["app.py"],
    "requireChanges": true,
    "contains": {},
    "commands": [
      {"name": "tests", "kind": "test", "argv": ["C:/projects/example/.venv/Scripts/python.exe", "-m", "pytest", "-q", "tests"], "timeout": 60, "approved": true}
    ]
  }
}
```

Policy использует `mode` и `threshold` dataclass LimitPolicy.
Для обычного balanced можно опустить policy.

Текстовое задание содержит `type:"text"`, `task`, `project`, `expected` вместо
`criteria`. Проверяется точный текст, как в managed-run. ID неизменяемый: нижний
регистр, цифры, `-`/`_`, до 64 символов; зависимости должны уже существовать.
Приоритет больше — раньше; при равенстве FIFO. Успешные зависимости обязательны.
Ожидающие неуспешную зависимость задания остаются pending, отчёт показывает blocked.

## Результаты и безопасность файлов

В `<queue>.runs/<id>/<generation>/` находятся `managed.json`, `snapshot.json`,
`workspace/`, `checks/` и `result.diff`. В routing history попадают только реально
проверенные попытки. Диагностика команд ограничена 8192 байт на команду, хранится
локально и используется для исправления; CLI не печатает её произвольный текст.
Журналы содержат выбранные файлы/задания, поэтому default `.local` исключён из Git.

Codex получает только явно выбранные UTF-8 файлы (до 256000 байт каждый, общий
контекст до 512000 байт) и возвращает JSON replacements. Контроллер разрешает лишь
writeFiles; удаления, traversal, абсолютные пути, ADS, case collisions и ссылки/
Windows junctions отклоняются. Исходники пользователя не перезаписываются.
Результат остаётся в workspace и diff для просмотра и ручного переноса. Автоматического
применения в исходный проект нет. Diff следующей зависимой задачи относителен к её
входному snapshot, уже включающему проверенные изменения предшественников.

Зависимости одного проекта передают только фактические изменения с проверкой хешей.
Конфликтующие независимые правки одного файла требуют решения пользователя;
изменение исходников или подмена проверенного workspace останавливает дальнейшую
работу. Между разными проектами зависимости задают только порядок выполнения.

Команды запускают доверенный пользователем код с правами текущего Windows-профиля.
Рабочая копия и Windows Job Object защищают жизненный цикл дочерних процессов,
но не являются ОС-песочницей для вредоносного кода. Передавайте только доверенные
команды и проекты. Shell не используется; timeout конечен, потомки завершаются
вместе с проверкой, отмена также останавливает собственное дерево процессов.

## Управление, попытки и восстановление

Один worker в пределах текущего Windows-профиля/temp scope. Durable reservation
блокирует другие очереди, пока активная задача не завершена или безопасно отменена.
Обычный lock освобождается при падении процесса; reservation сохраняется. Внешние
клиенты Codex не соблюдают эти locks — эксклюзивное владение thread всё ещё нужно.

Пауза/отмена кооперативные: перед отправкой, между попытками и при ожидании
(интервал проверки флагов до 30 секунд). Уже выполняющийся turn не откатывается;
его результат сохраняется и валидируется, затем отмена запрещает исправления.
Если удалённый исход ещё неизвестен, задача остаётся зарезервированной до сверки.
Отмена при паузе не создаёт тупик; завершённые задания отменять нельзя.

Новая задача всегда оценивается заново SmartRouter. Ошибка теста/контента передаёт
диагностику следующему turn того же thread: один шаг effort, затем более сильная
доступная модель. Максимум 1..8 попыток за всю жизнь ID, включая quota-сбои и явные
retry. `queue-retry` разрешён лишь при доказанной terminal validation failure и
оставшемся бюджете; предыдущий журнал архивируется, бюджет не обнуляется.
Auth/network/quota не вызывают качественную эскалацию. При лимите сохраняются
очередь, модель, prompt и thread/turn; Limit Manager ждёт сброса без App Server
во время сна. После перезапуска Windows/worker нужен `queue-run`.

Перед отправкой сохраняются dispatch marker и managed journal; после потери ack
используется полная история. Если журнал после dispatch исчез, исход неоднозначен
или validator имеет started receipt без finished, статус needs_attention: никаких
повторных команд/turn. Окно падения между marker и созданием journal также требует
проверки вручную. Проверки с готовым receipt переиспользуются только при совпадении
response/spec/turn и хешей файлов. Отдельный процесс может держать active writer;
программа не убивает его и не подменяет разговор.

Stage 5 (SQLite, расширенное восстановление и checkpoints), GUI и автозапуск ещё
не реализуются. Не удаляйте reservation/журналы, чтобы обойти неизвестный outcome.


SQLite, разрешения, миграция старых JSON, checkpoints, backup и ограничения
описаны в [STAGE5_SAFETY.md](STAGE5_SAFETY.md). CLI legacy queue-run отключён;
управление/чтение старых очередей сохранено для миграции.
## Local reviewed continuation

The Stage 11 integration adds `waiting_resume` and `paused_turn`.
CLI continuation requires both `--acknowledge-uncertain-result` and `--pause-turn-id`
for the exact reviewed turn. Controls persist intent; only the existing worker submits
inference after policy/history checks. See [checkpoint review](STAGE11_INTEGRATION.md).
