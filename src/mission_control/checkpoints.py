"""Private baseline Git objects; no user repository commands or destructive restore."""
import os
from pathlib import Path
import subprocess
from .state import StateError, state_exists, load_state, save_state
from .storage import guard_path
from .validator import digest, relative
from .safety import check_file, process_environment
from .secure_files import write_file


def git(root,*args,input=None):
    root=guard_path(root);guard_path(root/'checkpoint.git')
    env=process_environment()
    env.update(GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL=os.devnull,
               GIT_AUTHOR_NAME='Mission Control',GIT_AUTHOR_EMAIL='checkpoint@localhost',
               GIT_COMMITTER_NAME='Mission Control',GIT_COMMITTER_EMAIL='checkpoint@localhost')
    try:
        p=subprocess.run(['git','-c','core.hooksPath='+os.devnull,'--git-dir',str(root/'checkpoint.git'),*args],
                         input=input,capture_output=True,timeout=20,env=env,
                         creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    except (OSError,subprocess.SubprocessError):raise StateError('Private Git checkpoint unavailable') from None
    if p.returncode:raise StateError('Private Git checkpoint command failed')
    return p.stdout


def expected(snapshot):
    return {relative(n):None if v is None else digest(v.encode('utf-8')) for n,v in snapshot['baseline'].items()}


def verify(root,snapshot):
    for name,value in snapshot['baseline'].items():check_file(name,None if value is None else value.encode('utf-8'))
    root=guard_path(root);receipt=load_state(root/'checkpoint.json')
    if receipt.get('version')!=1 or receipt.get('hashes')!=expected(snapshot):raise StateError('Checkpoint baseline changed')
    commit=git(root,'rev-parse','refs/checkpoints/baseline').decode().strip()
    if commit!=receipt.get('commit'):raise StateError('Checkpoint reference changed')
    names=git(root,'ls-tree','-r','--name-only','-z',commit).decode('utf-8').split('\0')
    if set(filter(None,names))!={n for n,h in receipt['hashes'].items() if h is not None}:raise StateError('Checkpoint file set changed')
    for name,h in receipt['hashes'].items():
        if h is not None and digest(git(root,'show',commit+':'+name))!=h:raise StateError('Checkpoint content differs')
    return receipt


def create(root,snapshot):
    for name,value in snapshot['baseline'].items():check_file(name,None if value is None else value.encode('utf-8'))
    root=guard_path(root)
    if state_exists(root/'checkpoint.json'):return verify(root,snapshot)
    if (root/'checkpoint.git').exists() or (root/'checkpoint.index').exists():raise StateError('Incomplete checkpoint; preserve for inspection')
    # Feed bytes directly: no filters, work-tree/index, user hooks or source Git configuration.
    git(root,'init','--bare','--template=')
    tree=[]
    for name,value in sorted(snapshot['baseline'].items()):
        relative(name)
        if value is None:continue
        blob=git(root,'hash-object','-w','--stdin',input=value.encode('utf-8')).decode().strip()
        tree.append(('100644 blob '+blob+'\t'+name).encode('utf-8')+b'\0')
    # mktree cannot create slash paths directly: use a private index only.
    index=root/'checkpoint.index'
    for entry in tree:
        _index(root,index,entry)
    tree_id=_index(root,index,None).decode().strip()
    commit=git(root,'commit-tree',tree_id,input=b'Mission baseline\n').decode().strip()
    git(root,'update-ref','refs/checkpoints/baseline',commit,'0'*40)
    save_state(root/'checkpoint.json',{'version':1,'commit':commit,'hashes':expected(snapshot)})
    return verify(root,snapshot)


def _index(root,index,entry):
    guard_path(index);guard_path(root/'checkpoint.git')
    # Isolated environment, including a private index, for plumbing only.
    env=process_environment()
    env.update(GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL=os.devnull,GIT_INDEX_FILE=str(index))
    args=['update-index','-z','--index-info'] if entry is not None else ['write-tree']
    try:
        p=subprocess.run(['git','-c','core.hooksPath='+os.devnull,'--git-dir',str(root/'checkpoint.git'),*args],
                         input=entry,capture_output=True,env=env,timeout=20,
                         creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    except (OSError,subprocess.SubprocessError):raise StateError('Private checkpoint index unavailable') from None
    if p.returncode:raise StateError('Private checkpoint index failed')
    return p.stdout


def export(root,snapshot,destination,allowed_roots):
    destination=guard_path(destination)
    if destination.exists() or any(destination.is_relative_to(guard_path(p)) for p in allowed_roots):
        raise StateError('Export requires a new directory outside allowed original project roots')
    if destination.is_relative_to(guard_path(root)):raise StateError('Export cannot overwrite private execution data')
    receipt=verify(root,snapshot)
    destination.mkdir(parents=True,exist_ok=False)
    for name,h in receipt['hashes'].items():
        if h is None:continue
        target=destination/relative(name)
        value=git(root,'show',receipt['commit']+':'+name);check_file(name,value)
        write_file(target,value,new=True)
