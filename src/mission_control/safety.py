"""Local operator approvals and conservative, best-effort secret filtering."""
import hashlib
import json
import os
from pathlib import Path
import re
from .state import StateError, state_lock
from .storage import guard_path

SECRET_NAME=r'(?:[a-z][a-z0-9]*[_-])*(?:password|passwd|api[_-]?key|(?:access|refresh|auth|session)[_-]?token|client[_-]?secret|(?:aws[_-]?)?secret[_-]?access[_-]?key|connection[_-]?string|private[_-]?key|token|secret)'
SECRET_KEY=re.compile(r'(?i)^'+SECRET_NAME+r'$')
ASSIGNMENT=re.compile(r'(?i)\b'+SECRET_NAME+r'''\s*["']?\s*[:=]\s*(?:"(?:\\.|[^"\\\r\n])+"|'(?:\\.|[^'\\\r\n])+'|[^\s"',;}]+)''')
PATTERNS=[re.compile(r'(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{20,}'),
          re.compile(r'(?:AKIA|ASIA)[0-9A-Z]{16}'),
          re.compile(r'(?i)(?:Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+'),
          re.compile(r'''(?i)[a-z][a-z0-9+.-]*://[^\s/@:]+:[^\s/@]+@[^\s"']+'''),
          re.compile(r'sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}'),
          re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?(?:-----END[^\n]*|$)'),
          ASSIGNMENT]



def redact(text):
    text=str(text)
    # Decode structured diagnostic strings so escaped quotes cannot expose the
    # remainder of a credential. Return valid JSON when structural redaction wins.
    if text.lstrip().startswith(('{','[','"')):
        try:parsed=json.loads(text)
        except (ValueError,TypeError):parsed=None
        except RecursionError:return '[REDACTED: oversized structured diagnostic]'
        if isinstance(parsed,(dict,list)):
            try:clean=sanitize(parsed)
            except RecursionError:return '[REDACTED: oversized structured diagnostic]'
            if clean!=parsed:return json.dumps(clean,ensure_ascii=False)
        elif isinstance(parsed,str):
            clean=redact(parsed)
            if clean!=parsed:return json.dumps(clean,ensure_ascii=False)
    for pattern in PATTERNS:text=pattern.sub('[REDACTED]',text)
    for key,value in os.environ.items():
        if re.search(r'(?i)(token|secret|password|passwd|api_?key)',key) and len(value)>=3:
            text=text.replace(value,'[REDACTED]')
    return text


def sanitize(value):
    if isinstance(value,str):return redact(value)
    if isinstance(value,list):return [sanitize(v) for v in value]
    if isinstance(value,dict):
        return {k:'[REDACTED]' if SECRET_KEY.fullmatch(str(k)) and v not in (None,'') else sanitize(v) for k,v in value.items()}
    return value


def reject_secrets(text):
    if sanitize(text)!=text:raise StateError('Possible secret detected; remove it before storing or sending')


def check_file(name,value):
    base=Path(name).name.casefold()
    if base=='.env' or base.startswith('.env.') or base in {'credentials','credentials.json','id_rsa','id_ed25519','.git-credentials','.netrc','.npmrc','.pypirc'} or base.endswith(('.p12','.pfx','.pem','.key')):
        raise StateError('Credential files are excluded from mission context')
    if value is not None:reject_secrets(value.decode('utf-8'))


def fingerprint(job):
    keys=('id','title','type','task','project','criteria','expected','mode','manual','maxAttempts','turnTimeout','policy','dependsOn')
    data={k:job[k] for k in keys if k in job}
    return hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def settings(q,*,check_workspace=True):
    store=q.journal()
    if not store.exists('settings'):raise StateError('Configure allowed project roots before execution')
    result=store.load('settings')
    if set(result)!={'version','allowedRoots'} or result['version']!=1 or not isinstance(result['allowedRoots'],list) or not result['allowedRoots']:
        raise StateError('Unknown access settings; execution stopped')
    for value in result['allowedRoots']:_root(q,value,check_workspace=check_workspace)
    return result


def _root(q,value,*,check_workspace=True):
    if not isinstance(value,str) or not Path(value).is_absolute():raise StateError('Absolute allowed root required')
    path=guard_path(value)
    if check_workspace and not path.is_dir():raise StateError('Allowed root must exist')
    # Checks have local user rights; never place the controller state inside an allowed project.
    if q.path.is_relative_to(path) or q.journal().run_root.is_relative_to(path) or path.is_relative_to(q.journal().run_root):
        raise StateError('Project roots must be separate from queue and private workspaces')
    return path


def configure(q,roots):
    with state_lock(q.path),q.storage():
        data=q.read()
        if not q.journal().exists('queue'):q._save(data)
        if data['active'] is not None and not (q.journal().exists('migration') and not q.journal().exists('settings')):
            raise StateError('Access settings cannot change while a mission is active')
        paths=sorted({str(_root(q,r)) for r in roots})
        if not paths:raise StateError('At least one allowed root required')
        store=q.journal()
        with store.transaction() as c:
            store.write(c,'settings',{'version':1,'allowedRoots':paths})
            store.write(c,'approvals',{})


def approve(q,identity,*,expected_fingerprint=None):
    with state_lock(q.path),q.storage():
        data=q.read()
        store=q.journal()
        if data['active'] is not None and not (store.exists('migration') and data['active']==identity and (not store.exists('approvals') or identity not in store.load('approvals'))):
            raise StateError('Approvals cannot change while a mission is active')
        if identity not in data['missions']:raise StateError('Unknown mission')
        job=data['missions'][identity];allowed(q,job)
        if expected_fingerprint is not None and fingerprint(job)!=expected_fingerprint:
            raise StateError('Mission changed; review access again')
        store=q.journal();approvals=store.load('approvals') if store.exists('approvals') else {}
        approvals[identity]=fingerprint(job);store.save('approvals',approvals)


def allowed(q,job):
    roots=[guard_path(p) for p in settings(q)['allowedRoots']]
    project=guard_path(job['project'])
    if not any(project.is_relative_to(p) for p in roots):raise StateError('Project is outside allowed roots')
    reject_secrets({k:job.get(k) for k in ('task','criteria','expected')})


def authorize(q,job):
    allowed(q,job)
    store=q.journal()
    if not store.exists('approvals') or store.load('approvals').get(job['id'])!=fingerprint(job):
        raise StateError('Explicit approval of this mission and exact check commands is required')


def process_environment():
    """Minimal OS startup environment; never inherit API credentials or injection flags.

    This reduces accidental disclosure; an explicitly approved full-user process
    can still read files and Windows credentials and is not sandboxed.
    """
    keep={'SYSTEMROOT','WINDIR','SYSTEMDRIVE','COMSPEC','PATHEXT','TEMP','TMP','LANG','LC_ALL','TZ'}
    result={k:v for k,v in os.environ.items() if k.upper() in keep}
    # PATH entries are needed for trusted build tools, but never accept a relative
    # entry (including an implicit current directory). No arbitrary env passthrough.
    result['PATH']=os.pathsep.join(p for p in os.get_exec_path() if Path(p).is_absolute())
    result['PYTHONDONTWRITEBYTECODE']='1'
    result['PYTHONNOUSERSITE']='1'
    return result


def codex_environment():
    """Keep login/config location, omit ambient API keys and tool injection flags."""
    result=process_environment()
    for key,value in os.environ.items():
        if key.upper() in {'HOME','USERPROFILE','APPDATA','LOCALAPPDATA','CODEX_HOME'}:result[key]=value
    return result
