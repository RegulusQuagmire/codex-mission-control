"""Offline policy comparison against the pinned pre-Stage13 source, not model evals."""
import argparse,json,subprocess,sys,time,types
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
from mission_control import routing
from mission_control.history import History
from test_routing import catalog

BASE='85dac492185ae82002dacf15e4369be1e0b047ff'
CASES=[
    ('simple_text',{'text':'Return only 2','operation':'text'},0),
    ('long_translation',{'text':'Translate the following text: '+('hello '*900),'operation':'text'},0),
    ('multistep',{'text':'1. Implement parser.py.\n2. Connect service.py and queue.py with dependencies.\n3. Verify tests and edge cases.\n4. Compare two approaches and explain trade-offs.'},0),
    ('ambiguous',{'text':'Make it better somehow; requirements unclear and acceptance criteria missing.'},0),
    ('small_code',{'text':'Implement a function returning an integer','operation':'code'},0),
    ('debugging',{'text':'Debug deadlock across components','operation':'debug'},0),
    ('architecture',{'text':'Design a distributed system architecture'},0),
    ('architecture_docs',{'text':'Correct spelling in architecture.md','operation':'docs'},0),
    ('architecture_plus_readme',{'text':'Design a distributed system architecture and update README'},0),
    ('critical_risk',{'text':'Format text','operation':'format','risk':'critical'},0),
    ('two_failures',{'text':'format'},2),
    ('eight_failures',{'text':'format'},8),
]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    source=subprocess.check_output(['git','show',BASE+':src/mission_control/routing.py'],cwd=ROOT).decode('utf-8')
    previous=types.ModuleType('mission_control._before_stage13');previous.__package__='mission_control'
    sys.modules[previous.__name__]=previous;exec(compile(source,'pinned-before-stage13.py','exec'),previous.__dict__)
    rows=[]
    for name,kwargs,failures in CASES:
        history=History()
        for i in range(failures):history.record_once(str(i),'gpt-6-luna','low',routing.Complexity.LOW,False)
        before=previous.SmartRouter(history=history).choose(previous.Task(**kwargs),catalog()).to_dict()
        after=routing.SmartRouter(history=history).choose(routing.Task(**kwargs),catalog()).to_dict()
        rows.append({'case':name,'input':kwargs,'validatedFailures':failures,'before':before,'after':after,
            'configurationChanged':(before['model'],before['effort'])!=(after['model'],after['effort'])})
    begin=time.perf_counter()
    for i in range(1000):
        routing.SmartRouter().choose(routing.Task(**CASES[i%len(CASES)][1]),catalog())
    payload={'baselineSHA':BASE,'synthetic':True,'noInference':True,'cases':rows,
        'localAlgorithmTiming':{'iterations':1000,'seconds':time.perf_counter()-begin},
        'limits':'Policy/heuristic comparison only; no model quality, prices or token savings measured.'}
    args.out.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'cases':len(rows),'changed':sum(r['configurationChanged'] for r in rows),'timing':payload['localAlgorithmTiming']},indent=2))

if __name__=='__main__':main()
