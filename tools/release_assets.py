"""Assemble private, deterministic release files from explicitly audited inputs."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED
from release_audit import audit
from source_audit import audit as audit_source


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def zip_files(output, entries):
    names=set()
    with ZipFile(output,'x',compression=ZIP_DEFLATED,compresslevel=9) as archive:
        for name,path in sorted(entries):
            parts=PurePosixPath(name).parts
            if name in names or not parts or name.startswith('/') or '..' in parts or '\\' in name:
                raise ValueError('Unsafe or duplicate asset member')
            names.add(name)
            path=Path(path)
            if any(p.is_symlink() or p.is_junction() for p in [path,*path.parents]):
                raise ValueError('Linked asset input')
            info=ZipInfo(name,(2026,10,14,0,0,0));info.compress_type=ZIP_DEFLATED
            info.external_attr=0o100644<<16
            archive.writestr(info,path.read_bytes(),compress_type=ZIP_DEFLATED,compresslevel=9)


def source_files(catalogue, directories):
    entries=[]
    for group in ('sources','rustCrates'):
        for item in catalogue[group]:
            name=item.get('path',item.get('name'))
            if PurePosixPath(name).name!=name or '\\' in name:raise ValueError('Unsafe source catalogue path')
            matches=[Path(directory)/name for directory in directories if (Path(directory)/name).is_file()]
            if not matches or any(digest(p)!=item['sha256'] for p in matches):
                raise ValueError('Missing or changed corresponding source: '+name)
            entries.append(('upstream/'+name,matches[0]))
    return entries


def bind_source(root, receipt, source):
    """Do not label unrelated source/docs with the binary's revision identity."""
    expected={item['path']:item['sha256'] for item in receipt['sourceFiles']}
    actual={item['path']:item['sha256'] for item in source['files']}
    if len(actual)!=len(source['files']):raise ValueError('Duplicate candidate source member')
    generated={'PKG-INFO','setup.cfg',*(
        'src/codex_mission_control.egg-info/'+name for name in (
            'PKG-INFO','SOURCES.txt','dependency_links.txt','entry_points.txt','requires.txt','top_level.txt'))}
    if set(expected)-set(actual) or set(actual)-set(expected)-generated:
        raise ValueError('Source archive does not contain exactly the candidate inputs')
    for name,checksum in expected.items():
        path=Path(root)/name
        if (not path.is_file() or any(p.is_symlink() or p.is_junction() for p in [path,*path.parents])
                or digest(path)!=checksum or actual[name]!=checksum):
            raise ValueError('Source or companion input changed from candidate: '+name)


def license_files(root,receipt):
    prefix='packaging/licenses/'
    return [('licenses/'+item['path'][len(prefix):],Path(root)/item['path'])
            for item in receipt['sourceFiles'] if item['path'].startswith(prefix)]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate',type=Path,required=True)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--source-dir',type=Path,action='append',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();root=Path(__file__).resolve().parents[1]
    payload=args.candidate/'dist/MissionControl';manifest=audit(payload)
    expected=json.loads((args.candidate/'bundle-manifest.json').read_text(encoding='utf-8'))
    if manifest!=expected:raise ValueError('Candidate changed since audit')
    source_report=audit_source(args.source)
    receipt=json.loads((payload/'_internal/build-receipt.json').read_text(encoding='utf-8'))
    version=receipt['version']
    if args.source.name!=f'codex_mission_control-{version}.tar.gz':raise ValueError('Wrong candidate source version/name')
    bind_source(root,receipt,source_report)
    catalogue=json.loads((root/'packaging/source-distributions.json').read_text(encoding='utf-8'))
    sources=source_files(catalogue,args.source_dir)
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    setup=args.candidate/f'MissionControl-Setup-{version}-x64.exe'
    candidate_artifacts=json.loads((args.candidate/'artifacts.json').read_text(encoding='utf-8'))
    if digest(setup)!=candidate_artifacts['installer']['sha256']:raise ValueError('Installer changed since build')
    shutil.copyfile(setup,output/setup.name);shutil.copyfile(args.source,output/args.source.name)
    zip_files(output/f'MissionControl-{version}-windows-x64.zip',
              [('MissionControl/'+item['path'],payload/item['path']) for item in manifest['files']])
    sources += [('README.md',root/'docs/LIBRARY_SOURCES.md'),
                ('source-distributions.json',root/'packaging/source-distributions.json'),
                ('sqlite-runtime.json',root/'packaging/sqlite-runtime.json'),
                ('THIRD_PARTY_NOTICES.md',root/'THIRD_PARTY_NOTICES.md')]
    sources += license_files(root,receipt)
    zip_files(output/f'MissionControl-{version}-corresponding-sources.zip',sources)
    shutil.copyfile(root/'docs/RELEASE_0.7.1.md',output/'RELEASE_NOTES.ru-en.md')
    artifacts=[{'file':p.name,'bytes':p.stat().st_size,'sha256':digest(p)} for p in sorted(output.iterdir())]
    report={'schema':1,'version':version,'sourceHead':receipt['sourceHead'],
            'publicationAuthorized':False,'signed':False,'independentCleanWindowsTested':False,
            'sqlite':receipt['sqlite'],'artifacts':artifacts}
    (output/'release-manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    sums=[(p.name,digest(p)) for p in sorted(output.iterdir())]
    (output/'SHA256SUMS.txt').write_text(''.join(h+'  '+n+'\n' for n,h in sums),encoding='utf-8')
    # Local API-ready draft. No network, tag creation or public asset upload occurs.
    draft={'tag_name':'v'+version,'target_commitish':receipt['sourceHead'],'name':'Mission Control '+version,
           'draft':True,'prerelease':True,'body':(root/'docs/RELEASE_0.7.1.md').read_text(encoding='utf-8')}
    (output.parent/'github-release-draft.json').write_text(json.dumps(draft,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
