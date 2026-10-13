# Stage 13 — Intelligent Router 2.0

This local development branch extends the published Stage 11 + Concept C Evolution
source at `85dac492185ae82002dacf15e4369be1e0b047ff`. It does not change the public
version, create a release, or authorize inference. Stage 14 is outside this work.

## Детерминированный анализ

Router использует существующие Task hints и локальные признаки текста: объём,
код/отладка, явно перечисленные шаги, зависимости/файлы, проверка результата,
неоднозначность, риск и глубокое рассуждение/компромиссы. Это объяснимая эвристика,
а не объективное определение сложности или вероятность успеха. Одинаковые входы,
каталог, policy и история дают одинаковый результат; история не создаёт inference.

Индекс суммирует восемь признаков. Объём, код, шаги, зависимости, проверка, риск и
reasoning дают 0–2, неоднозначность — 0–1; максимум 15. Индекс >=7 даёт HIGH.
Отдельные консервативные floors важнее суммы: архитектура/critical risk — CRITICAL;
отладка, high risk, >=6 файлов или >=2 предыдущих ошибок — минимум HIGH;
код, medium risk, >=2 файла или неоднозначность — минимум MEDIUM. Неизвестная общая
задача начинает с MEDIUM. Ограниченная текстовая операция с индексом <=2 остаётся
LOW, если нет более сильных оснований. Поэтому длинный простой перевод не получает
высокий effort только из-за длины. Добавление README к системному проектированию
не снижает архитектурный floor.

Анализ ограничен первыми 65536 символами; обрезанный ввод получает минимум HIGH и
явное пояснение. Полное задание по-прежнему хранится/отправляется прежним механизмом.
Негативные формулировки, цитаты и неизвестные языки могут давать ложные сигналы:
оператору следует использовать существующие operation/risk/file hints и Manual.
Алгоритм не анализирует файлы проекта и не обещает семантическое понимание текста.

## Model / effort

Сохранена качественная политика точных известных model IDs и режимов
Economy/Balanced/Quality. Это политика предпочтений, не бенчмарк мощности и не цена.
Каталог, поддерживаемые efforts, exclusions, automaticEnabled и maxEffort всегда
ограничивают выбор. Ultra автоматически не выбирается. Дубли model IDs исключены
как неоднозначные; неизвестным IDs не присваивается ранг по имени. Если известных
профилей нет, используется доступный default, затем лексикографический exact ID,
независимо от порядка каталога.

Manual сохраняет точный выбор и не эскалирует. Активная/сохранённая конфигурация не
заменяется инспекцией. Эскалация остаётся прежней: только после подтверждённой ошибки
проверки, без повторения посещённых пар, в пределах бюджета; сначала effort, затем
более высокий явный профиль. Метаданные причины/ограничений/истории обновляются при
эскалации. Ошибка сети, доступа, лимита, прерывание или неизвестный исход не являются
причиной автоматической эскалации или replay.

## Осторожное использование History

Новый `qualityRecords` — дополнительное поле существующего version-1 документа
history; SQL schema не меняется. Общие `records` и прежние observation IDs остаются
читаемыми. Старые агрегаты без категории проверки не становятся надёжной quality
историей автоматически. Они не влияют на новый выбор, даже если там много ошибок.

Только завершённые `quality`/`test_failure` результаты с boolean passed пополняют
quality evidence. Timeout, `not_retryable`, infrastructure, access, quota, interruption,
unknown и execution-approval wait не учитываются. Тесты являются прокси проверки
задания, а не доказательством универсального качества модели. Ошибка внешней среды,
которую сами проектные тесты неверно классифицировали как test_failure, остаётся
ограничением качества исходных данных.

Dedup использует однозначный JSON tuple [turn, thread ID, turn ID]. Для recovery
старого managed run учитывается прежний jobId:turnId alias: агрегат не удваивается,
а неизвестное происхождение не повышается до quality evidence. Запись history и
восстановление остаются под существующими leases/SQLite protection.

Сравниваются точные model/effort/complexity buckets. Менять предпочтительный профиль
можно только при >=8 наблюдениях и сглаженной доле неуспехов
`(failure+2)/(success+failure+4) >= 0.70`. Эта внутренняя оценка не показывается как
процент уверенности. Один успех, две ошибки, малые или противоречивые выборки не
перестраивают маршрут. Успехи не снижают сложность задания. Попытки коррелируют внутри
миссии; этот порог не заменяет независимый статистический эксперимент или benchmark.

## Router inspection / Evolution UI

Выберите существующую миссию в Router и нажмите «Оценить без отправки». Сервис читает
только сохранённую очередь/history и cached catalog/limits; не создаёт Adapter,
worker, turn или новую миссию. UI показывает оценку, конфигурацию, реальные признаки,
историю решения, применённые текущие ceilings, оставшиеся попытки и отдельные gates.
Сохранённый route явно отличается от рекомендации новой задачи. Устаревшие
альтернативы повторно проверяются по текущим catalog/policy/credit/limits.

Предпочтительный initial route совпадает с ManagedRunner: он сохраняет предпочтение
даже при исчерпанной квоте, вместо необоснованного перехода на более мощную модель.
Лимиты и Credit Policy показываются отдельно как блокирующие gates. Unknown/stale
limits не означают доступность. Инспекция не предоставляет project access, execution
approval или exact-turn consent. Общая пауза и waiting_resume видны независимо.

Fingerprint включает definition/live state выбранной миссии, общий paused, каталог,
limits/timestamp, подключение, policies и revision quality history. Изменение входов
инвалидирует preview и поздние ответы; свежие лимиты истекают через 60 секунд.
Язык/тема не меняют выбор. RU/EN переводят developer-owned пояснения, сохраняя exact
IDs и пользовательские данные. Backend перед turn/start заново выполняет текущие
проверки; snapshot никогда не является разрешением отправки.

## Offline QA and comparison

```powershell
python -m pytest -q
python -m compileall -q src tests tools
python -m pip check
git diff --check
python tools/compare_stage13_router.py --out .local/router-comparison.json
python tools/capture_stage13_router.py --out .local/router-native-new
```

Tests run serially using temporary SQLite and synthetic remote data. Comparison
loads the pinned pre-Stage13 router from Git and uses identical synthetic tasks,
catalog and observations. It measures policy differences and local algorithm time,
not model output quality, tokens, prices or savings. Native captures use Windows
Qt client areas, labelled demo snapshots and zero backend requests; system DPI is
unchanged. The capture directory must be new. Real inference is not part of QA.

Existing Stage 11 checkpoint review, exact-turn consent, durable recovery, independent
approvals, Model/Credit Policy and the final submission path remain mandatory.
