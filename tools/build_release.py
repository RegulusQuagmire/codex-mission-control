"""Build one fresh local candidate; never installs, uploads or publishes it."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib
from release_audit import environment, audit, clean_environment


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--iscc', type=Path, required=True)
    parser.add_argument('--wheelhouse', type=Path, required=True)
    parser.add_argument('--runtime-archive',type=Path,required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    receipt = environment(root,args.wheelhouse,args.runtime_archive)
    compiler = args.iscc.resolve(strict=True)
    if compiler.name.lower()!='iscc.exe': raise ValueError('Select the pinned ISCC.exe compiler')
    toolchain=json.loads((root/'packaging/inno-toolchain.json').read_text())
    for entry in toolchain['files']:
        target=compiler.parent/entry['path']
        if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest()!=entry['sha256']:
            raise ValueError('Compiler toolchain mismatch: '+entry['path'])
    # Version check is independent of PATH; acquisition/signature verification is
    # documented separately. Never download or silently replace tools here.
    info = subprocess.run([str(compiler), '-'], input='', capture_output=True, text=True)
    if 'Compiler engine version: Inno Setup 6.7.3' not in info.stdout+info.stderr:
        raise ValueError('Inno Setup 6.7.3 is required')
    version = tomllib.loads((root/'pyproject.toml').read_text())['project']['version']
    receipt.update(sourceHead=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
                   compiler={'version':'6.7.3','sha256':hashlib.sha256(compiler.read_bytes()).hexdigest(),
                             'files':toolchain['files']},
                   version=version)
    output.mkdir(parents=True, exist_ok=False)
    # Ignore existing installed bytecode as well as verifying wheel source/DLL bytes.
    # -B alone prevents writes, but still reads an old cache.
    cache=output/'fresh-pycache'
    audit_cache=output/'fresh-audit-pycache'
    if cache.exists() or audit_cache.exists(): raise ValueError('Bytecode cache must be fresh')
    sys.pycache_prefix=str(audit_cache)
    env = clean_environment(Path(sys.base_prefix),cache)
    env.update(CMC_BUILD_WHEELHOUSE=str(args.wheelhouse.resolve()),
               CMC_BUILD_RUNTIME_ARCHIVE=str(args.runtime_archive.resolve()))
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--clean', '--noconfirm',
                    '--distpath',str(output/'dist'),'--workpath',str(output/'build'),
                    str(root/'packaging/MissionControl.spec')],cwd=root,env=env,check=True)
    payload = output/'dist/MissionControl'
    if environment(root,args.wheelhouse,args.runtime_archive)['sourceFiles'] != receipt['sourceFiles']:
        raise ValueError('Source changed during build; discard candidate')
    write_json(payload/'_internal/build-receipt.json',receipt)
    provenance=json.loads((output/'build/MissionControl/native-inputs.json').read_text())
    write_json(payload/'_internal/native-inputs.json',provenance)
    manifest = audit(payload)
    write_json(output/'bundle-manifest.json',manifest)
    subprocess.run([str(compiler), '/O'+str(output), '/DPayloadDir='+str(payload),
                    str(root/'packaging/installer.iss')],cwd=root,env=env,check=True)
    if environment(root,args.wheelhouse,args.runtime_archive)['sourceFiles'] != receipt['sourceFiles']:
        raise ValueError('Source changed during installer compile; discard candidate')
    setup = output/f'MissionControl-Setup-{version}-x64.exe'
    write_json(output/'artifacts.json',{'publicationAuthorized':False,
               'installer':{'path':setup.name,'sha256':hashlib.sha256(setup.read_bytes()).hexdigest()},
               'application': next(f for f in manifest['files'] if f['path']=='MissionControl.exe')})


if __name__ == '__main__': main()
