# Dependency license inventory

Audit date: 2026-10-12. Exact installed versions from an isolated Windows Python 3.12 environment. These are the project runtime, desktop, test and frozen-build dependencies, not the separately installed audit tools. No dependency binaries are included in the public Git tree. Recheck licenses after any version change.

| Component | Version | Scope | License | Distribution obligations |
| --- | --- | --- | --- | --- |
| [cryptography](../packaging/licenses/cryptography/LICENSE) | 50.0.2 | runtime | Apache-2.0 OR BSD-3-Clause | Preserve copyright, license and disclaimers; Apache components also retain applicable NOTICE and modification notices. |
| [cffi](../packaging/licenses/cffi/LICENSE) | 2.1.1 | runtime | MIT-0 | Preserve copyright, license and disclaimers; Apache components also retain applicable NOTICE and modification notices. |
| [pycparser](../packaging/licenses/pycparser/LICENSE) | 3.11 | runtime | BSD-3-Clause | Preserve copyright, license and disclaimers; Apache components also retain applicable NOTICE and modification notices. |
| [PySide6-Essentials](../packaging/licenses/PySide6-Essentials/LicenseRef-Qt-Commercial.txt) | 6.12.0 | desktop | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | Use LGPL option; preserve notices, permit library replacement/relinking and provide corresponding library source when distributing binaries. |
| [shiboken6](../packaging/licenses/shiboken6/LicenseRef-Qt-Commercial.txt) | 6.12.0 | desktop | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | Use LGPL option; preserve notices, permit library replacement/relinking and provide corresponding library source when distributing binaries. |
| [pytest](../packaging/licenses/pytest/LICENSE) | 9.1.1 | test | MIT | Preserve copyright, license and disclaimers; Apache components also retain applicable NOTICE and modification notices. |
| [colorama](../packaging/licenses/colorama/LICENSE.txt) | 0.4.6 | test | BSD-3-Clause | Preserve copyright, license and disclaimers; Apache components also retain applicable NOTICE and modification notices. |
| [iniconfig](../packaging/licenses/iniconfig/LICENSE) | 2.3.1 | test | MIT | Preserve copyright, license and disclaimers; Apache components also retain applicable NOTICE and modification notices. |
| [packaging](../packaging/licenses/packaging/LICENSE) | 26.3 | test | Apache-2.0 OR BSD-2-Clause | Preserve copyright, license and disclaimers; Apache components also retain applicable NOTICE and modification notices. |
| [pluggy](../packaging/licenses/pluggy/LICENSE) | 1.6.0 | test | MIT | Preserve copyright, license and disclaimers; Apache components also retain applicable NOTICE and modification notices. |
| [Pygments](../packaging/licenses/Pygments/AUTHORS) | 2.21.0 | test | BSD-2-Clause | Preserve copyright, license and disclaimers; Apache components also retain applicable NOTICE and modification notices. |
| [setuptools](../packaging/licenses/setuptools/LICENSE) | 84.0.0 | build | MIT | Preserve copyright, license and disclaimers; Apache components also retain applicable NOTICE and modification notices. |
| [pyinstaller](../packaging/licenses/pyinstaller/COPYING.txt) | 6.22.0 | build | GPL-2.0-or-later WITH Bootloader-exception; selected files Apache-2.0 | Preserve applicable notices and exception; changes to PyInstaller itself retain its license. |
| [altgraph](../packaging/licenses/altgraph/LICENSE) | 0.17.5 | build | MIT | Preserve copyright, license and disclaimers; Apache components also retain applicable NOTICE and modification notices. |
| [pefile](../packaging/licenses/pefile/LICENSE) | 2024.8.26 | build | MIT | Preserve copyright, license and disclaimers; Apache components also retain applicable NOTICE and modification notices. |
| [pyinstaller-hooks-contrib](../packaging/licenses/pyinstaller-hooks-contrib/LICENSE) | 2026.8 | build | GPL-2.0-or-later (build hooks); Apache-2.0 (runtime hooks) | GPL applies to redistributed standard hooks; bundled runtime hooks are Apache-2.0. Build tool is not project code. |
| [pywin32-ctypes](../packaging/licenses/pywin32-ctypes/LICENSE.txt) | 0.2.3 | build | BSD-3-Clause | Preserve copyright, license and disclaimers; Apache components also retain applicable NOTICE and modification notices. |

## Additional components and assets

- CPython 3.12.14: PSF-2.0 and included notices; required interpreter, not bundled in Git.
- OpenSSL and Rust dependencies embedded in cryptography wheels: separate upstream terms; preserve their exact notices and sources as required before distributing a frozen binary. [Upstream guidance](https://cryptography.io/en/latest/faq/#what-licenses-apply-to-cryptography).
- Qt Core/Gui/Widgets and QtTest used here are available under the LGPL route. No GPL-only Qt module is imported by the application. Installing Essentials avoids the broader Addons/WebEngine package. [Qt licensing](https://doc.qt.io/qt-6/licensing.html).
- Inno Setup is an external optional installer compiler; not redistributed. Review its [license](https://jrsoftware.org/files/is/license.txt) for any future installer workflow.
- Git and Codex are external applications, not bundled or relicensed by this project.
- UI graphics are drawn by project code and standard Qt style icons. No third-party image packs or icon fonts were found in the public tree.
- Segoe UI/Consolas are referenced from the user’s Windows installation; no font files are redistributed.
- Screenshots are actual project widgets with synthetic demo data; no private historical screenshots are carried into this tree.

## Conclusion

No license conflict was identified for distributing this source tree under MIT for original project code. Third-party components retain their licenses. This conclusion does not authorize binary distribution: a frozen distribution requires an exact bundled-module/SBOM audit, corresponding source compliance, complete notices and library replacement verification. [PyInstaller exception](https://pyinstaller.org/en/stable/license.html) does not override Qt or other dependency obligations.
