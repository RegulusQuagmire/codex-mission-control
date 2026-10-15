# Library sources and replacement / Исходники и замена библиотек

Mission Control is MIT. Libraries keep their original licenses. The installed
`_internal/licenses/` directory includes LGPL3, GPL3, Qt exceptions, Python,
Microsoft component terms, OpenSSL, Rust, Inno and PyInstaller notices.
`THIRD_PARTY_NOTICES.md`, `source-distributions.json`, `build-receipt.json` and
`native-inputs.json` identify versions, licensed components and shipped native bytes.
Attribution lists are conservative source/build supersets, not shipped DLL counts.

## Source delivery

Publish `MissionControl-0.7.1-corresponding-sources.zip` next to the EXE/portable ZIP
with equivalent free access and clear links. It contains the original complete
QtBase/QtSvg 6.12.0 and PySide/shiboken 6.12.0 source archives, including their build
scripts and third-party sources; CPython, cryptography, OpenSSL, PyInstaller/hooks,
Inno, Rust crate sources and SQLite 3.54.0 are included as additional provenance.
QtTranslations 6.12.0 provides the preferred `.ts` sources for redistributed `.qm`
translations. QtTools provides lrelease/generation scripts. The Qt5 6.12.0
superproject supplies Coin platform configuration and provisioning scripts as a
build-configuration supplement; its submodules are supplied as separate archives.
The catalogue records archive URLs and SHA256. No local Qt/PySide patches are applied.
Source acquisition links are supplemental; they do not replace distributor delivery.
Do not delete the companion asset while its binaries remain available.

## Shared library mechanism

The directory bundle loads shared Qt/PySide/shiboken libraries. There is no runtime
hash lock, activation or integrity repair preventing replacement. Build-time pins
authenticate official release inputs, not users' later modifications. Users may
modify/replace LGPL libraries and reverse engineer the application to debug those
modifications. Microsoft runtime restrictions apply only to Microsoft code.

Close the app and copy the **entire** portable directory to a new writable folder.
Use Windows x64 libraries with compatible Qt 6.12/Python 3.14 release ABI and matching
MSVC runtime. Replace the relevant `_internal/PySide6/Qt6*.dll`, plugins and matching
bindings/shiboken files as needed; preserve directory layout and licenses. Test with
an explicit disposable `--queue` and `--smoke-report` path. Never modify a live
installation or use real projects/data. Do not run a repair installer over modified
libraries; it intentionally restores distributed files.

## Source build directions and limits

Complete upstream build scripts remain in each archive. QtBase supplies `configure`,
CMake files and platform mkspecs; QtSvg supplies its CMake module build; PySide's
`setup.py`, `build_scripts/` and `coin_build_instructions.py` supply binding/wheel
build logic. Review those exact-version scripts before selecting options.
PySide's `coin/instructions_utils.py` records standalone, unity, limited-api and
qtpaths packaging switches. Qt5's `coin/platform_configs/cmake_platforms.yaml`
contains Windows MSVC2022 packaging options including debug-and-release,
force-debug-info and qt-zlib. These are upstream configuration evidence, not a
proven receipt of the exact vendor wheel job. Translation regeneration uses matching
QtTools 6.12.0 `lrelease` and QtTranslations' CMake files. QtTools is source/build
material here, not an additional shipped GPL executable.

A compatible local Qt build starts in an x64 MSVC developer shell with CMake/Ninja:

```powershell
mkdir qtbase-build
cd qtbase-build
..\qtbase-6.12.0\configure.bat -prefix C:\qt-local -release -shared -opensource -confirm-license -nomake examples -nomake tests
cmake --build . --parallel
cmake --install .
cd ..
cmake -S qtsvg-6.12.0 -B qtsvg-build -G Ninja -DCMAKE_PREFIX_PATH=C:\qt-local -DCMAKE_INSTALL_PREFIX=C:\qt-local
cmake --build qtsvg-build --parallel
cmake --install qtsvg-build
```

For PySide/shiboken, use the matching source's Windows build guide, compatible
libclang and Python 3.14, and point `setup.py build` at that Qt's qmake using the
options documented by `python setup.py --help`. Build the required Core/Gui/Widgets/
Network/Svg bindings and shiboken together. These are directions for compatible
modifications, **not a claim of bit-exact vendor-wheel reconstruction** or an executed
SDK build. Official guides: https://doc.qt.io/qt-6/windows-building.html and
https://doc.qt.io/qtforpython-6/building_from_source/windows.html .

Release QA performs an ABI-preserving resource-marker change to QtCore in a copied
bundle and verifies the actually loaded modified DLL hash. This is limited evidence
that the package allows replacement; it does not certify all source-modified libraries
or establish complete legal compliance. Outstanding concrete source/configuration
obligations must be resolved before publication, not hidden behind this smoke test.

## Русский

Архив соответствующих исходников распространяется бесплатно рядом с бинарными файлами.
В нём полные неизменённые исходники Qt/PySide и сценарии сборки, дополнительные
исходники и лицензии. Пользователь вправе заменять совместимые LGPL-библиотеки
и исследовать приложение для отладки своих изменений. Проверяйте замену на копии
всего portable-каталога и отдельной тестовой базе; runtime не запрещает её по хешу.
Описанный SDK recipe не выдаётся за проверенную сборку исходников поставщика.
