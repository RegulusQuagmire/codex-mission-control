"""Bounded ordinal heuristics, not a learned estimate of intrinsic difficulty."""
import re

MAX_ANALYSIS = 65536


def analyze(task):
    text = task.text[:MAX_ANALYSIS].casefold()
    has = lambda pattern: bool(re.search(pattern, text))
    files = task.estimated_files
    if files is None:
        files = len(set(re.findall(r'[\w./\\-]+\.(?:py|tsx?|jsx?|rs|go|cs|cpp|md|sql|json)\b', text)))
    scoped = task.operation in {'text','docs','format'} or has(
        r'\bformat\b|опечат|spelling|переведи|\btranslate\b|short text|коротк.*текст')
    numbered = len(re.findall(r'^\s*(?:\d+[.)]|[-*])\s+\S', text, re.M))
    code = task.operation in {'code','refactor','debug','architecture'} or has(
        r'```(?:python|py|js|ts|sql|rust|go)|\b(?:implement|function|endpoint|parser|refactor)\b|реализ|напиш.*(?:код|функци)|\bdef \w+\(')
    debugging = task.operation=='debug' or has(r'\bdebug|deadlock|race condition|отлад|гонк[аи]')
    architecture = task.operation=='architecture' or (has(
        r'архитектур|\barchitecture\b|distributed system|распределённ') and
        (not scoped or has(r'\b(?:design|redesign|rework)\b|переработ|спроектир|измени.*архитектур')))
    cross = has(r'dependenc|зависим|cross.module|multi.file|нескольк.*модул|компонент|components')
    verification = has(r'\b(?:test|tests|verify|validate|edge cases|acceptance)\b|провер|тест|валидаци')
    deep = has(r'trade.?offs|compare.*approach|prove|proof|reason.*step|сравн.*подход|докаж|доказ|обосн|компромисс')
    ambiguous = has(r'unclear|ambiguous|somehow|missing.*(?:criteria|requirements)|неясн|неоднознач|как.нибудь|непонят|на.усмотрение')
    risk = task.risk
    if risk=='auto':
        if has(r'drop\s+table|удал.*(?:таблиц|баз[уы])|delete.*database|destructive migration'):
            risk='critical'
        elif has(r'\bsecurity\b|безопасност|authentication|авторизац|database migration|миграци.*баз'):
            risk='high'
    features = {
        'scope': 2 if len(text)>3000 else int(len(text)>1000),
        'code': 2 if debugging else int(code),
        'steps': 2 if numbered>=4 else int(numbered>=2),
        'dependencies': 2 if files>=6 or (files>=2 and cross) else int(files>=2 or cross),
        'verification': int(verification)*(2 if code or numbered>=2 else 1),
        'ambiguity': int(ambiguous),
        'risk': 2 if risk in {'high','critical'} else int(risk=='medium'),
        'reasoning': 2 if deep or architecture else 0,
    }
    score = sum(features.values())
    # Preserve an unknown task's conservative MEDIUM floor. Long payload alone
    # is not evidence of deep reasoning for an explicitly scoped text operation.
    level = 0 if scoped and score<=2 else 1
    if score>=7 or debugging or files>=6 or task.previous_errors>=2: level=max(level,2)
    if architecture or risk=='critical': level=3
    elif risk=='high': level=max(level,2)
    if task.previous_errors or code or ambiguous or risk=='medium' or files>=2: level=max(level,1)
    reasons = ['scoped text/document operation' if scoped else 'general task; conservative baseline']
    signals = {
        'scope':'substantial specification', 'code':'implementation/refactoring',
        'steps':'multiple explicit work steps', 'dependencies':'cross-component or file dependencies',
        'verification':'explicit result verification', 'ambiguity':'requirements contain ambiguity',
        'risk':f'risk={risk}', 'reasoning':'deep reasoning or trade-off analysis',
    }
    reasons += [signals[key] for key,value in features.items() if value]
    if debugging: reasons.append('debugging or cross-module changes')
    if architecture: reasons.append('architecture or system-wide dependencies')
    if files: reasons.append(f'estimated files={files}')
    if task.previous_errors: reasons.append(f'previous errors={task.previous_errors}')
    if len(task.text)>MAX_ANALYSIS:
        level=max(level,2);reasons.append('analysis input truncated; conservative floor')
    return level,tuple(reasons),files,score,tuple(features.items())
