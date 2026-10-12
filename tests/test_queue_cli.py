import json
from mission_control.cli import main, parser


def test_queue_cli_add_list_and_controls_without_codex(tmp_path,capsys):
    q=tmp_path/'queue.json';manifest=tmp_path/'mission.json'
    manifest.write_text(json.dumps({'id':'one','title':'One','type':'text','project':str(tmp_path),
                                   'task':{'text':'Return only 2','operation':'text'},'expected':'2'}))
    assert main(['queue-add','--queue',str(q),'--mission',str(manifest),'--codex','absent'])==0
    capsys.readouterr()
    assert main(['queue-list','--queue',str(q)])==0
    out=json.loads(capsys.readouterr().out);assert out['missions'][0]['id']=='one'
    assert main(['queue-priority','--queue',str(q),'--mission-id','one','--priority','7'])==0
    assert main(['queue-pause','--queue',str(q)])==0
    assert main(['queue-resume','--queue',str(q)])==0
    assert main(['queue-cancel','--queue',str(q),'--mission-id','one'])==0


def test_queue_output_cannot_overwrite_queue_or_existing_user_file(tmp_path):
    q=tmp_path/'queue.json';user=tmp_path/'user.txt';user.write_text('keep')
    assert main(['queue-list','--queue',str(q),'--output',str(q)])==1
    assert main(['queue-list','--queue',str(q),'--output',str(user)])==1
    assert user.read_text()=='keep'
