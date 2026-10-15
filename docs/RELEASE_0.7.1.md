# Mission Control 0.7.1 — подготовленный выпуск / prepared release

Статус: кандидат; публикация бинарных файлов требует отдельного разрешения владельца.
Release notes описывают подготовленные файлы, а не уже опубликованный установщик.

## Русский

Первый подготовленный Windows x64 установщик объединяет Stage 11–15:
безопасную Pause & Resume с просмотром checkpoint и согласием на конкретный turn,
Concept C Evolution, объяснимый Router и проекты с зависимостями миссий.
Черновик плана не расширяет доступ. Доступ к папкам, согласие на план, исполнение
результата и продолжение turn остаются отдельными разрешениями.

Выпуск добавляет закреплённую сборку, аудит файлов и зависимостей, лицензии,
проверки установки/обновления/удаления и диагностику первого запуска. В замороженном
приложении SQLite обновлена до 3.54.0 отдельной проверенной DLL; SQL schema не меняется.
Источник: [SQLite CVE](https://sqlite.org/cves.html).

### Установка и проверка

Поддерживаются Windows 10 2004+ / Windows 11 x64. Для EXE Python не нужен.
Codex и Git устанавливаются отдельно. Для просмотра интерфейса подключение Codex
не требуется. Реальные миссии расходуют лимиты аккаунта и требуют настройки политик.

Получайте файлы только из Release репозитория `RegulusQuagmire/codex-mission-control`.
До запуска сравните `Get-FileHash .\MissionControl-Setup-0.7.1-x64.exe -Algorithm SHA256`
со строкой в `SHA256SUMS.txt` из того же официального выпуска. Хеш из постороннего
источника не подтверждает издателя. Установщик работает от текущего пользователя.
Для portable ZIP распакуйте **всю папку**, затем запустите `MissionControl.exe`.
Portable означает переносимые программные файлы; база по умолчанию остаётся в профиле.

### Обновление и данные

Сначала остановите очередь и восстановите операции с неизвестным исходом. Сохраните
checkpoint, закройте программу и сделайте защищённую копию всей папки
`%LOCALAPPDATA%\CodexMissionControl` под тем же пользователем Windows. Не публикуйте её.
Установите новую версию поверх старой в ту же папку. Не запускайте две версии одновременно.
Проверьте настройки, миссии, проекты и approvals до продолжения очереди.
Удаление приложения оставляет данные профиля и проекты. DPAPI привязана к пользователю
Windows; копия базы не гарантирует перенос на другой аккаунт. Не понижайте версию базы.
См. [первый запуск](FIRST_RUN.md).

### Известные ограничения

- EXE и установщик **не подписаны Authenticode**. SmartScreen может предупреждать
  или блокировать запуск. Обходы защиты не предлагаются. Подпись в будущем подтвердит
  издателя и целостность, но не гарантирует отсутствие предупреждений репутации.
- Независимая чистая пользовательская Windows недоступна и не проверена. Текущая
  Windows, временные каталоги и GitHub Windows runner дают ограниченную проверку;
  runner содержит средства разработки. Это раскрытый риск, не автоматический запрет выпуска.
- Обновление 0.7.0 проверяется по неизменному старому исходному коду и локально
  восстановленному QA-установщику; ранее публичного установщика не было.
- Нет гарантии отсутствия побочных действий после ACK остановки или пустого checkpoint.
- Замена Qt проверяется ограниченным smoke с изменённым ресурсом DLL; собственная
  сборка полного SDK Qt не сертифицирована. Нет заявления о полном LGPL compliance.

## English

Prepared Windows x64 release combining Stage 11–15: exact-turn checkpoint review,
Concept C Evolution, explainable routing and projects with mission dependencies.
Draft plans grant no access. Folder access, plan approval, result execution and
interrupted-turn continuation remain separate approvals. No new execution engine
or automatic inference is introduced. The frozen application uses authenticated
SQLite 3.54.0 without changing the application SQL schema.

Windows 10 2004+ / Windows 11 x64 are supported. Python is unnecessary for the EXE;
Codex and Git are separate prerequisites for actual work. Obtain artifacts only
from this repository's official GitHub Release, and compare PowerShell `Get-FileHash`
SHA256 with its `SHA256SUMS.txt` before launch. Install as your current user, or
extract the entire portable ZIP. Portable program files still use profile data.

Before upgrading, stop/recover the queue, review checkpoints, close the app and back
up the complete `%LOCALAPPDATA%\CodexMissionControl` directory privately under the
same Windows user. Install into the same program directory; never run both versions
at once or downgrade active data. Check settings, approvals and missions before
resuming. Uninstall retains profile data and projects; DPAPI is user-bound.
See [first launch](FIRST_RUN.en.md).

The EXE/installer are unsigned. SmartScreen may warn or block; no bypass is provided.
Future signing provides publisher identity/integrity, not guaranteed reputation.
An independent clean consumer Windows machine was unavailable: host/isolated-path
and Windows CI smoke are useful but are not that certification. This alone is not
an automatic release blocker. The 0.7.0 QA installer is reconstructed from immutable
source, not a previously published installer. Qt replacement smoke uses a modified
resource, not a rebuilt Qt SDK; full LGPL compliance is not asserted. Stop RPC ACKs
and empty checkpoints never prove absence of side effects.

## Files / Файлы

- `MissionControl-Setup-0.7.1-x64.exe` — per-user installer.
- `MissionControl-0.7.1-windows-x64.zip` — complete replaceable-library program bundle.
- `codex_mission_control-0.7.1.tar.gz` — application source, tests, notices and build tools.
- `MissionControl-0.7.1-corresponding-sources.zip` — exact upstream source archives,
  notices, build/replacement directions and acquisition hashes; distribute beside binaries.
- `release-manifest.json`, `SHA256SUMS.txt` — inventory and integrity checks.

Corresponding library sources must remain freely available alongside binary downloads.
Do not publish binaries without the companion archive. See [library sources](LIBRARY_SOURCES.md).
