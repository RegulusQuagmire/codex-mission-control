# Stage 11 + Concept C Evolution — source integration

Source integration based on: `e2feccadb7d6fb1f35a17fd5ed9e4988497a4572`;
Stage 11 source: `f421976a05bdfa66161ea5301f4025504b2a29ef`.
The backend checkpoint preceded the UI integration; earlier branch test counts
are historical and do not establish combined compatibility. Final evidence is kept
in the owner's integration review report, including exact branch/HEAD and current diff.

## Продолжение миссии

1. Missions показывает «Ход завершён · просмотрите checkpoint», в том числе при
   общей паузе очереди. Фильтр waiting_resume включает этот случай.
2. Resume открывает существующее окно результата на вкладке Checkpoint.
3. Прочитайте текст до конца и самостоятельно сверьте файлы, процессы и внешние
   последствия. Пустой checkpoint не означает, что действий не было.
4. Отметьте отдельное согласие и нажмите «Продолжить эту миссию». Передаются
   exact turn ID и explicit acknowledgement через существующий Service/Queue flow.
5. Общая пауза очереди остаётся отдельным ограничением. При необходимости снимите
   её после review. Если после одобрения была поставлена пауза именно миссии,
   её Resume позволяет явно подтвердить тот же checkpoint ещё раз для снятия паузы.

Смена turn ID, текста/evidence, отмена, новое согласие из другого окна или выход
из допустимой стадии инвалидируют открытое согласие. Закройте окно и перечитайте
актуальный результат. Повторное нажатие не создаёт вторую отправку. Language switch
не выдаёт согласие и не переводит checkpoint, ID, JSON или пользовательские данные.

Три разных разрешения: доступ к определению миссии/проекту; исполнение конкретной
версии результата; продолжение конкретного turn. Одно не заменяет другое.
Dashboard urgent action выбирает соответствующее review или журнал. Limits и
Overlay используют то же представление фактического состояния.

## English workflow

Missions Resume opens Checkpoint review for a paused turn, including when the whole
queue is paused. Read to the end, verify actual effects, check explicit consent, then
continue that exact turn. Whole-queue pause remains independent. Re-confirming an
already-approved checkpoint is allowed to explicitly remove a later mission pause.
Changed evidence or an ineligible stage permanently invalidates an open dialog's
consent. The backend rechecks remote history, remaining budget and current policies.

## Safety and compatibility

ACK means a control request was accepted, not that processes stopped, files were
rolled back or external actions were undone. Unknown inference outcomes are never
automatically repeated. Complete remote turn IDs must equal the saved baseline plus
reviewed turn before continuation; extra/missing/duplicate turns require attention.
There is still no atomic expected-idle server guard, and external concurrent control
of this thread is unsupported. Checkpoints are bounded to 65536 Python characters,
not a proved 64 KiB UTF-8 byte limit. Client-side policies cannot guarantee zero charges.
Downgrade of active Stage 11 journals to Stage 10 is not supported; SQL schema is unchanged.

## Offline QA

`python -m pytest -q` must run serially: test adapters share synthetic turn IDs and
production OS leases. Tests use isolated temporary SQLite/workspaces, never the
user's queue. UI integration tests drive real Service → Queue → ManagedRunner with
a synthetic remote; protocol tests use a local fake NDJSON server.

For actual native Windows Qt captures, run:

```powershell
python tools/capture_stage11_evolution.py --out .local/stage11-evolution-native-new
```

The output path must be new. The harness uses labelled offline snapshots and a
non-executing bridge; zero backend calls are required. It verifies requested client
sizes at 800×600, 960×740, 1920×1080 and Qt scale factors 1/1.25/1.5/2 in separate
processes. It does not change OS DPI or prove compatibility on every monitor.
No real inference, installer, release or publishing is authorized by these commands.
