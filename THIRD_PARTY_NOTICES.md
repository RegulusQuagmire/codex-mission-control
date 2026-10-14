# Third-party notices

Original Codex Mission Control code is MIT licensed. Dependency licenses remain
independent. Source alpha is v0.7.0; Stage 15 candidate is 0.7.1, not a release.

The frozen directory preserves exact nested wheel license files and CPython's full
LICENSE.txt. `packaging/licenses/` adds Qt LGPL/GPL/exception texts, embedded Qt
attributions, cryptography's Rust crate notices, OpenSSL and Inno notices.
`packaging/license-sources.json` records license provenance;
`packaging/source-distributions.json` records full upstream source archive URLs and
SHA256 verified during the local audit. Archives stay outside this Git repository.
Qt attribution and Rust crate lists deliberately retain a conservative upstream
source/build superset, including platform-only and compile-time entries: their
length is not a claim about how many components ship in Windows DLLs. Unused Mesa
software OpenGL and image-codec plugins are excluded; SVG is retained.

## Qt and PySide6

PySide6-Essentials/shiboken6 and Qt 6.12.0 use LGPL-3.0 where offered. The app uses
Core/Gui/Widgets and transitively Network/Svg, not GPL-only Qt modules. Qt DLLs stay
replaceable beside the EXE. Users may replace compatible LGPL libraries and debug
those modifications. No app license or installer condition removes those rights.
Qt's third-party attributions include their individual permissive/MPL terms.
GPL texts and Qt exceptions are retained as upstream notices, not a relicensing
of the MIT application. Before binary publication provide the exact corresponding
Qt/PySide sources and build/configuration/replacement instructions by an appropriate
LGPL distribution method; upstream links alone are not a source-delivery guarantee.

## Python, cryptography and native runtime

The release runtime is official CPython 3.14.8 x64, with its complete PSF and bundled
component notices. Source compatibility remains Python 3.12+. Its native DLL inputs
are checked against the pinned official archive. cryptography 50.0.2 embeds OpenSSL
4.0.3; CPython uses OpenSSL 3.5.9. Full upstream sources and checksum evidence were
acquired. Rust crate notices include Unicode and Apache/LLVM exceptions where
applicable, and the Rust standard library's MIT/Apache notices.

Microsoft Distributable Code has component-specific conditions preserved verbatim
from CPython's actual Windows LICENSE.txt in `packaging/INSTALLER_LICENSE.txt`.
The installer presents these terms for acceptance. They apply only to Microsoft
code, not Python, this MIT application or LGPL library modification/replacement.
Do not remove Microsoft notices, imply endorsement, redistribute its code for
non-Microsoft platforms, or use it in malicious/deceptive/unlawful programs.

## Build and installer

PyInstaller 6.22.0 has a GPL bootloader exception permitting an independently
licensed app; its bootloader zlib notice and hook licenses are retained. Inno Setup
6.7.3 and embedded decoder/component notices are included. This product is made
using RemObjects Pascal Script: https://www.remobjects.com/ps . Decoder notices
preserve their original linking exceptions; they are not all labeled public domain.
Git/Codex and Windows fonts are external and not redistributed. No third-party font
or image pack is bundled.

## Distribution remains a separate decision

The PR contains source/notices only, no binary uploads. Before public installer
release the owner must approve distribution, complete corresponding-source delivery
and compatible-library replacement verification, and assess the unperformed
independent clean-Windows test. The project EXE/installer are not Authenticode signed;
SmartScreen may warn or block. CI smoke is not a clean consumer Windows certification.
See [Stage 15 checklist](docs/STAGE15.md) and [build instructions](docs/BUILDING.md).
