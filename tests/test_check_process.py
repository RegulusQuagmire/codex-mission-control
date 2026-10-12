import asyncio
from pathlib import Path
import sys
import time
import pytest
from mission_control.check_process import run_command, run_check


def test_output_is_bounded_but_child_pipe_is_drained(tmp_path):
    r=run_command([sys.executable,'-c',"print('x'*1000000)"],tmp_path,5)
    assert r['exitCode']==0 and len(r['output'])==8192


def test_detached_descendant_is_killed_when_check_finishes(tmp_path):
    marker=tmp_path/'escaped'
    script="import time; from pathlib import Path; time.sleep(1); Path('escaped').write_text('bad')"
    parent='import subprocess,sys; subprocess.Popen([sys.executable,"-c",'+repr(script)+'])'
    r=run_command([sys.executable,'-c',parent],tmp_path,5)
    assert r['exitCode']==0
    time.sleep(1.3)
    assert not marker.exists()


def test_cancellation_stops_own_process_tree_promptly(tmp_path):
    async def check():
        task=asyncio.create_task(run_check([sys.executable,'-c',"import time; time.sleep(3); open('escaped','w').write('bad')"],tmp_path,30))
        await asyncio.sleep(0.15);task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
    started=time.monotonic();asyncio.run(check())
    assert time.monotonic()-started<2 and not (tmp_path/'escaped').exists()
