# Third-party notices

The MIT License covers original Codex Mission Control code. It does not replace
the licenses, copyright notices or attribution requirements of dependencies.
The owner confirmed the right to license their own project code under MIT.

See the [dependency license table](docs/DEPENDENCIES.md) and machine-readable
[inventory](docs/dependency-inventory.json) for 17 audited direct and transitive
runtime, desktop, test and frozen-build components. Their license texts are preserved
under `packaging/licenses/`. This Git repository distributes source and notices,
not third-party wheels, DLLs, fonts, an interpreter or an installer.

## Qt and PySide6

The desktop imports Qt Core, Gui and Widgets; tests also use QtTest. The declared
dependency is PySide6-Essentials with shiboken6, audited at 6.12.0. The application
does not import the GPL-only modules listed in [Qt licensing](https://doc.qt.io/qt-6/licensing.html).
Use the LGPL-3.0 option where available. A future binary distributor must preserve
notices, permit library replacement and debugging of modifications, provide the
corresponding library sources as required, and inventory Qt's third-party components.
Dynamic linking alone does not discharge every LGPL obligation.

Upstream sources (select the exact distributed version):

- https://code.qt.io/cgit/pyside/pyside-setup.git/
- https://code.qt.io/cgit/qt/qtbase.git/

## Cryptography and build tools

cryptography 50.0.2 is dual-licensed Apache-2.0 / BSD-3-Clause. Its wheels embed
OpenSSL and Rust components with their own licenses; those need an exact inventory
before binary distribution. [Upstream guidance](https://cryptography.io/en/latest/faq/#what-licenses-apply-to-cryptography).

PyInstaller 6.22.0 uses GPL with its bootloader exception and Apache-2.0 for selected
files. Its exception permits application distribution under another license while
preserving dependency obligations. Standard community build hooks use GPL-2.0-or-later;
runtime hooks use Apache-2.0. No hook implementation is copied into project code.
See [PyInstaller licensing](https://pyinstaller.org/en/stable/license.html) and
[community hook licensing](https://github.com/pyinstaller/pyinstaller-hooks-contrib/blob/master/LICENSE).

CPython and Inno Setup are separately obtained tools with their own licenses. Git
and Codex are external programs. No third-party fonts or image packs are redistributed;
the UI uses project drawing code, Qt style icons and fonts from the user's Windows.

## Binary distribution is not approved

The current audit identified no conflict for this MIT source distribution. It is
not a completed binary license audit. Before any installer publication, inventory
every included module and native dependency, retain all required notices, satisfy
corresponding-source obligations, verify replaceable Qt libraries and test on a clean
Windows machine. No GitHub Release or installer is published for this alpha.
