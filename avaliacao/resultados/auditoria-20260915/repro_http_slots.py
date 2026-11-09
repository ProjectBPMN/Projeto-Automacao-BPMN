"""Isolated audit: fake service, ephemeral loopback port, no live services."""
import http.client
import json
from pathlib import Path
import socket
import sys
import threading
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from local_ai.http_api import LocalAIHTTPServer


class FakeService:
    settings = SimpleNamespace(max_concurrent_requests=1, api_token="", max_body_bytes=1024)

    def classify(self, payload):
        return SimpleNamespace(result={"ok": True}, metadata={})

    embed = deduplicate = extract = classify

    def health(self):
        return {"alive": True}


started = time.monotonic()
server = LocalAIHTTPServer(("127.0.0.1", 0), FakeService())
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
slow = None
connections = []
result = {"address": list(server.server_address), "fake_service": True}


def request(method, path, body=None):
    conn = http.client.HTTPConnection(*server.server_address, timeout=2)
    connections.append(conn)
    conn.request(method, path, body=body)
    response = conn.getresponse()
    data = response.read().decode()
    conn.close()
    return {"status": response.status, "body": json.loads(data)}


try:
    slow = socket.create_connection(server.server_address, timeout=2)
    slow.settimeout(2)
    slow.sendall(b"POST /v1/classify HTTP/1.1\r\nHost: localhost\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{")
    deadline = time.monotonic() + 2
    while server.request_slots.acquire(blocking=False):
        server.request_slots.release()
        if time.monotonic() > deadline:
            raise AssertionError("partial request did not acquire slot")
        time.sleep(0.01)
    result["while_partial"] = request("POST", "/v1/classify", b"{}")
    result["health_while_partial"] = request("GET", "/health")
    time.sleep(1)
    result["after_one_second_partial"] = request("POST", "/v1/classify", b"{}")
    slow.sendall(b"}")
    raw = b""
    while chunk := slow.recv(4096):
        raw += chunk
    result["completed_partial_status_line"] = raw.split(b"\r\n", 1)[0].decode()
    result["after_completion"] = request("POST", "/v1/classify", b"{}")
    assert result["while_partial"]["status"] == 429
    assert result["after_one_second_partial"]["status"] == 429
    assert result["health_while_partial"]["status"] == 200
    assert result["after_completion"]["status"] == 200
    wf = json.loads((ROOT / "n8n/workflows/Versão9/V9-WF03-Classificacao.json").read_text(encoding="utf-8"))
    nodes = {node["name"]: node for node in wf["nodes"]}
    result["wf03"] = {
        "put_on_error": nodes["GLPI: Fechar OBRA"].get("onError"),
        "put_connections": wf["connections"]["GLPI: Fechar OBRA"],
        "pg_query": nodes["PG: Fechado OBRA"]["parameters"]["query"],
        "final_code": nodes["LOG: Fim Classificação"]["parameters"]["jsCode"],
    }
    result["assertions_passed"] = True
finally:
    if slow is not None:
        slow.close()
    for conn in connections:
        conn.close()
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)
    result["server_thread_stopped"] = not thread.is_alive()
    result["duration_seconds"] = round(time.monotonic() - started, 3)
    output = Path(__file__).with_suffix(".json")
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
