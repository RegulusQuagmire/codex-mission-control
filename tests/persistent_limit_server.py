"""Offline App Server fixture with disk history across subprocess restarts."""
import json
from pathlib import Path
import sys

path=Path(sys.argv[1]);scenario=sys.argv[2]
sys.stdin.reconfigure(encoding="utf-8")
state=json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"turns":[],"model":None,"effort":None,"calls":0}

loaded = False
thread_identity="wire-"+path.stem if scenario.startswith("project_") else "wire-thread"

def save(): path.write_text(json.dumps(state),encoding="utf-8")
def send(value): print(json.dumps(value),flush=True)

for line in sys.stdin:
    message=json.loads(line)
    method=message.get("method")
    if method=="initialized": continue
    rid=message["id"];params=message.get("params",{})
    if method=="initialize": result={}
    elif method=="account/read": result={"account":{"type":"chatgpt"},"requiresOpenaiAuth":True}
    elif method=="account/rateLimits/read":
        result={"ordinaryUsageAllowed":True,"rateLimits":{"limitId":"codex",
            "primary":{"usedPercent":10,"windowDurationMins":300,"resetsAt":2000},
            "secondary":{"usedPercent":10,"windowDurationMins":10080,"resetsAt":9999999999}}}
    elif method=="model/list":
        result={"data":[{"model":"gpt-6-luna","supportedReasoningEfforts":[{"reasoningEffort":"low"},{"reasoningEffort":"medium"}]}],"nextCursor":None}
    elif method=="thread/read":
        if scenario=="unmaterialized" and loaded and not state["turns"] and params.get("includeTurns"):
            send({"id":rid,"error":{"code":-32601,"message":"full history is unavailable before materialization"}});continue
        if scenario=="unmaterialized" and not loaded and not state["turns"]:
            send({"id":rid,"error":{"code":-32600,"message":"thread is not loaded"}});continue
        result={"thread":{"id":thread_identity,"status":{"type":"idle"},"turns":state["turns"]}}
    elif method in {"thread/start","thread/resume"}:
        assert params["sandbox"]=="read-only" and params["approvalPolicy"]=="never"
        if scenario=="unmaterialized" and method=="thread/resume" and not loaded and not state["turns"]:
            send({"id":rid,"error":{"code":-32600,"message":"no rollout found"}});continue
        if scenario=="context" and method=="thread/start":
            state["threadStarts"]=state.get("threadStarts",0)+1;save()
            send({"id":rid,"error":{"code":-32600,"message":"unexpected new conversation"}});continue
        if method=="thread/resume":
            state.setdefault("resumeIds",[]).append(params["threadId"])
        loaded=True
        state["model"]=params.get("model",state["model"]);save()
        result={"thread":{"id":thread_identity},"model":state["model"],"reasoningEffort":state["effort"]}
    elif method=="turn/start":
        assert params["approvalPolicy"]=="never" and params["sandboxPolicy"]["type"]=="readOnly"
        assert loaded, "Must load existing session before starting a turn"
        state.setdefault("requestThreadIds",[]).append(params["threadId"])
        state["calls"]+=1;state["model"]=params["model"];state["effort"]=params["effort"]
        tid="wire-"+str(state["calls"])
        failed=scenario in {"quota","context","project_quota"} and state["calls"]==1
        answer="2"
        if scenario.startswith("project_"):
            value=0 if scenario=="project_repair" and state["calls"]==1 else 2
            answer=json.dumps({"edits":[{"path":"app.py","content":f"VALUE = {value}\n"}]})
        if scenario=="context":
            answer=state["turns"][0]["items"][0]["content"][0]["text"].removeprefix("Remember marker ")
        turn={"id":tid,"status":"failed" if failed else "completed","itemsView":"full",
            "items":[{"id":"user-"+tid,"type":"userMessage","content":params["input"]},
                     {"id":"answer-"+tid,"type":"agentMessage","phase":"final_answer","text":"" if failed else answer}],
            "error":{"message":"PRIVATE","codexErrorInfo":"usageLimitExceeded"} if failed else None}
        state["turns"].append(turn);save()
        if scenario in {"lost_ack","project_lost_ack"} and state["calls"]==1: sys.exit(0)
        send({"id":rid,"result":{"turn":{"id":tid,"status":"inProgress"}}})
        send({"method":"item/completed","params":{"threadId":thread_identity,"turnId":tid,"item":turn["items"][1]}})
        send({"method":"turn/completed","params":{"threadId":thread_identity,"turn":turn}})
        continue
    else:
        send({"id":rid,"error":{"code":-32601,"message":"PRIVATE"}});continue
    send({"id":rid,"result":result})
