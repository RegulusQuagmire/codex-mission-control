"""Deterministic subprocess speaking the real NDJSON envelope. No network."""
import json
import sys
import time

sys.stdin.reconfigure(encoding="utf-8")
scenario = sys.argv[1]
active_model = None
active_effort = None
turn_number = 0
saved_turns = []
counters = {"resume": 0, "turn": 0, "interrupt": 0}

def send(obj):
    print(json.dumps(obj), flush=True)

for line in sys.stdin:
    msg = json.loads(line)
    if "method" not in msg:
        if scenario == "approval" and msg.get("error", {}).get("code") == -32601:
            send({"method": "approval/refused", "params": {}})
        continue
    method = msg["method"]
    if method == "initialized":
        continue
    rid = msg["id"]
    if method == "initialize":
        send({"id": rid, "result": {"userAgent": "fake", "platformOs": "windows"}})
    elif scenario == "exit":
        sys.exit(0)
    elif scenario == "malformed":
        print("not json", flush=True)
    elif scenario == "hang":
        time.sleep(30)
    elif scenario == "error":
        send({"id": rid, "error": {"code": -32602, "message": "SECRET_TOKEN"}})
    elif scenario == "approval":
        send({"id": "server-1", "method": "item/commandExecution/requestApproval",
              "params": {"command": "do not execute"}})
        send({"id": rid, "result": {}})
    elif method == "test/counters":
        send({"id": rid, "result": counters})
    elif method == "thread/read":
        thread = {"id": "thread-1", "status": {"type": "idle"}, "turns": []}
        if scenario == "limits_wire":
            thread["turns"] = saved_turns
        if scenario == "active_status":
            thread["status"] = {"type": "active", "activeFlags": []}
        if scenario == "active_turn":
            thread["turns"] = [{"id": "unrelated", "status": "inProgress"}]
        if scenario == "missing_status":
            thread.pop("status")
        send({"id": rid, "result": {"thread": thread}})
    elif method == "turn/interrupt":
        counters["interrupt"] += 1
        send({"id": rid, "result": {}})
    elif method == "model/list":
        cursor = msg["params"].get("cursor")
        send({"id": rid, "result": {
            "data": [{"model": "second" if cursor else "first",
                      "supportedReasoningEfforts": [{"reasoningEffort": "low"}]}],
            "nextCursor": "page2" if scenario == "cycle" or not cursor else None}})
    elif method == "account/read":
        send({"id": rid, "result": {"account": {"type": "chatgpt",
              "email": "private@example.com", "planType": "plus"},
              "requiresOpenaiAuth": True}})
    elif method == "account/rateLimits/read":
        value = {"rateLimits": None, "rateLimitsByLimitId": None, "accountId": "PRIVATE_ACCOUNT", "rateLimitUpsell": {"url": "PRIVATE_URL"}}
        if scenario != 'unknown_limits':
            value.update(ordinaryUsageAllowed=True, rateLimits={"limitId":"codex",
                "primary":{"usedPercent":10,"windowDurationMins":300,"resetsAt":time.time()+3600},
                "secondary":{"usedPercent":10,"windowDurationMins":10080,"resetsAt":time.time()+86400}})
        send({"id": rid, "result": value})
    elif method in ("thread/start", "thread/resume"):
        if method == "thread/resume":
            counters["resume"] += 1
        if msg["params"].get("sandbox") != "read-only":
            send({"id": rid, "error": {"code": -32600}})
            continue
        active_model = msg["params"].get("model", active_model)
        send({"id": rid, "result": {"thread": {"id": "thread-1"},
              "model": active_model, "reasoningEffort": active_effort, "sandbox": "readOnly"}})
    elif method == "turn/start":
        counters["turn"] += 1
        params = msg["params"]
        if params.get("approvalPolicy") != "never" or params.get("sandboxPolicy", {}).get("type") != "readOnly":
            send({"id": rid, "error": {"code": -1}})
            continue
        if scenario == "stderr":
            sys.stderr.write("x" * 200000)
            sys.stderr.flush()
        active_model = params["model"]
        active_effort = params["effort"]
        turn_number += 1
        turn_id = f"turn-{turn_number}"
        final_text = json.dumps({"model": active_model, "effort": active_effort}) if scenario == "wire" else "\u041f\u0440\u0438\u0432\u0435\u0442 \u2713"
        if scenario == "wire":
            send({"method": "item/completed", "params": {
                "threadId": params["threadId"], "turnId": turn_id,
                "item": {"id": "commentary", "type": "agentMessage", "phase": "commentary",
                         "text": "Commentary should not be included in the validated final answer"}}})
        if scenario == "limits_wire":
            saved_turns.append({"id":turn_id,"status":"completed","itemsView":"full",
                "items":[{"id":"item-1","type":"agentMessage","phase":"final_answer",
                          "text":final_text,"memoryCitation":{"secret":"SECRET"}}],"error":None})
            send({"method":"account/rateLimits/updated","params":{"rateLimits":{
                "limitId":"codex","primary":{"usedPercent":23,"windowDurationMins":300,"resetsAt":2000}},
                "secret":"SECRET"}})
        # Lifecycle events intentionally precede response (a real possible race).
        send({"method": "item/completed", "params": {
            "threadId": params["threadId"], "turnId": turn_id,
            "item": {"id": "item-1", "type": "agentMessage", "text": final_text, "phase": "final_answer"}}})
        send({"method": "turn/completed", "params": {
            "threadId": params["threadId"],
            "turn": {"id": turn_id, "status": "failed" if scenario in {"failed", "classified"} else "completed",
                     "error": {"message": "SECRET", "codexErrorInfo": "unauthorized"} if scenario in {"failed", "classified"} else None}}})
        send({"id": rid, "result": {"turn": {"id": turn_id, "status": "inProgress"}}})
    else:
        send({"id": rid, "result": msg.get("params", {})})
