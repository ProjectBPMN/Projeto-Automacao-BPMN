"""Helpers para gerar nós n8n V9."""
import json
import os
import re

GLPI_URL_DEFAULT = os.getenv("GLPI_API_URL", "http://host.docker.internal:9080/apirest.php")
FISCAL_WH_KEY = os.getenv("FISCAL_WEBHOOK_KEY", "fiscal-ic-2026")
FISCAL_DECISION_BASE_URL = os.getenv(
    "FISCAL_DECISION_BASE_URL",
    f"http://localhost:5678/webhook/fiscal-decisao-{FISCAL_WH_KEY}",
)
DDI_DG_EMAIL = os.getenv("DDI_DG_EMAIL", "ddi-dg@campus.local")
PG_CRED = {"postgres": {"id": "PG_TRIAGEM", "name": "Postgres Triagem"}}
SMTP_CRED = {"smtp": {"id": "SMTP_MAILPIT_LOCAL", "name": "SMTP Mailpit Local"}}
WORKFLOW_IDS = {
    "V9 - WF01 Sincronizador": os.getenv("WF01_ID", "BCrENoTzdW20owz4"),
    "V9 - WF02 Triagem": os.getenv("WF02_ID", "nmNEsgC8kXmCVOsX"),
    "V9 - WF03 Classificação": os.getenv("WF03_ID", "reVggSpJiaPhnfIo"),
    "V9 - WF04 Decisão Fiscal": os.getenv("WF04_ID", "ZpQ0H9uV9Fiscal04"),
    "V9 - WF05 Métricas": os.getenv("WF05_ID", "ZpQ0H9uV9Metric05"),
    "V9 - WF06 Fila IA": os.getenv("WF06_ID", "ZpQ0H9uV9Fila06"),
}

GLPI_URL_EXPR = f"($env.GLPI_API_URL || '{GLPI_URL_DEFAULT}')"


def required_n8n_env_expr(name):
    """Return an n8n expression that stops before using a missing secret."""
    return (
        "={{ (() => { const value = String($env."
        + name
        + " || '').trim(); "
        + "if (!value || value === 'CHANGE_ME') { throw new Error('"
        + name
        + " ausente'); } return value; })() }}"
    )


APP_TOKEN_EXPR = required_n8n_env_expr("GLPI_APP_TOKEN")
AUTH_BASIC_EXPR = required_n8n_env_expr("GLPI_AUTH_BASIC")


_PROCESS_ENV_GUARD_RE = re.compile(
    r"\(\s*typeof\s+process\s*!==?\s*(['\"])undefined\1\s*&&\s*"
    r"process\.env(?P<access>\.[A-Za-z_$][A-Za-z0-9_$]*|\[[^\]\r\n]+\])\s*\)"
)
_PROCESS_ENV_DIRECT_RE = re.compile(
    r"process\.env(?P<access>\.[A-Za-z_$][A-Za-z0-9_$]*|\[[^\]\r\n]+\])"
)


def _has_env_first_prefix(source: str, start: int, access: str) -> bool:
    """Return whether a guarded process access already has the n8n $env branch."""
    env_prefix = re.compile(
        r"\(\s*typeof\s+\$env\s*!==?\s*(['\"])undefined\1\s*&&\s*"
        + re.escape("$env" + access)
        + r"\s*\)\s*\|\|\s*$"
    )
    return env_prefix.search(source[:start]) is not None


def normalize_n8n_env_access(source: str) -> str:
    """Remove ``$env`` from the deployable workflow representation.

    The main n8n process runs with ``N8N_BLOCK_ENV_ACCESS_IN_NODE=true``.
    Code nodes execute in an external runner whose launcher allowlists only
    non-secret operational settings. Keeping reads as ``process.env`` makes
    that boundary explicit; application secrets are never placed in the
    runner container.
    """
    return (
        source.replace("typeof $env", "typeof process")
        .replace("$env.", "process.env.")
        .replace("$env[", "process.env[")
        .replace("$env", "process.env")
    )


_SECRET_CODE_ENV_NAMES = {
    "GEMINI_API_KEY",
    "GEMINI_API_KEY_SECONDARY",
    "GLPI_APP_TOKEN",
    "GLPI_AUTH_BASIC",
    "GLPI_WEBHOOK_KEY",
    "IA_LOCAL_API_TOKEN",
    "TEST_AUTO_REVIEW_TOKEN",
}

_PUBLIC_CODE_CONSTANTS = {
    "DEDUP_CANDIDATE_LIMIT": "20",
    "DEDUP_LOCAL_TOP_K": "20",
    "DEDUP_NEGATIVE_THRESHOLD": "0.22",
    "DEDUP_POSITIVE_THRESHOLD": "0.78",
    "DEMO_EQUIPE_DISPONIVEL": "true",
    "FISCAL_CONFIRMATION_BASE_URL": "http://localhost:5678/webhook/fiscal-confirmacao-v9",
    "IA_CONFIANCA_MINIMA": "0.65",
    "IA_OBRA_CONFIANCA_MINIMA": "0.90",
    "WF01_GLPI_CHUNK_SIZE": "10",
}


def _map_strings(value, transform):
    if isinstance(value, dict):
        for key, item in value.items():
            value[key] = _map_strings(item, transform)
        return value
    if isinstance(value, list):
        for index, item in enumerate(value):
            value[index] = _map_strings(item, transform)
        return value
    return transform(value) if isinstance(value, str) else value


def _harden_runtime_node(node):
    """Apply the runtime isolation contract after legacy normalization."""
    node_type = str(node.get("type", ""))
    parameters = node.get("parameters")
    if not isinstance(parameters, dict):
        return node

    is_code = node_type == "n8n-nodes-base.code"

    def transform(source: str) -> str:
        # GLPI is reached through an internal credential-injecting proxy. The
        # URL is configuration, not a secret, and is intentionally immutable
        # in the published workflow.
        source = source.replace(
            "process.env.GLPI_API_URL",
            "'http://glpi-credential-proxy:8080/apirest.php'",
        )
        if is_code:
            # O prompt recebe o limiar congelado, sem expressão de ambiente.
            source = source.replace(
                "{{ Number(process.env.IA_CONFIANCA_MINIMA || 0.65) }}",
                "0.65",
            ).replace(
                "{{ Number($env.IA_CONFIANCA_MINIMA || 0.65) }}",
                "0.65",
            )
            for name in _SECRET_CODE_ENV_NAMES:
                source = source.replace(f"process.env.{name}", "undefined")
            for name, constant in _PUBLIC_CODE_CONSTANTS.items():
                source = source.replace(
                    f"process.env.{name}",
                    json.dumps(constant, ensure_ascii=False),
                )
            source = source.replace("process.env[name]", "undefined")
            # Chamadas diretas ao GLPI passam pelo proxy que injeta o App-Token.
            # O Code node conserva apenas o Session-Token efêmero.
            source = re.sub(
                r"const appToken = .*?;\n",
                "const appToken = '';\n",
                source,
            )
            source = source.replace("'App-Token': appToken, ", "")
            return source
        # Expressions outside Code nodes run in the main process, where env
        # access is blocked. Undefined preserves each expression's explicit,
        # public fallback without exposing process configuration.
        source = re.sub(r"process\.env\.[A-Z][A-Z0-9_]*", "undefined", source)
        return source.replace("process.env[name]", "undefined")

    _map_strings(parameters, transform)

    if node_type == "n8n-nodes-base.httpRequest":
        url = str(parameters.get("url", ""))
        if "glpi-credential-proxy" in url:
            header_parameters = parameters.get("headerParameters", {}).get("parameters", [])
            parameters.setdefault("headerParameters", {})["parameters"] = [
                row
                for row in header_parameters
                if str(row.get("name", "")).lower() not in {"app-token", "authorization"}
            ]
    return node


def _required_process_env_expr(name):
    return (
        "(() => { const value = String(((typeof $env !== 'undefined' && "
        f"$env.{name}) || (typeof process !== 'undefined' && process.env.{name})) || '').trim(); "
        f"if (!value || value === 'CHANGE_ME') throw new Error('{name} ausente'); "
        "return value; })()"
    )


def sanitize_workflow_secrets(value):
    """Recursively replace weak secret fallbacks with fail-closed expressions."""
    if isinstance(value, dict):
        for key, item in value.items():
            value[key] = sanitize_workflow_secrets(item)
        return _harden_runtime_node(value) if "type" in value else value
    if isinstance(value, list):
        for index, item in enumerate(value):
            value[index] = sanitize_workflow_secrets(item)
        return value
    if not isinstance(value, str):
        return value

    stripped = value.strip()
    if stripped.startswith("={{") and "$env.GLPI_APP_TOKEN" in value:
        return APP_TOKEN_EXPR
    if stripped.startswith("={{") and "$env.GLPI_AUTH_BASIC" in value:
        return AUTH_BASIC_EXPR

    for name in ("GLPI_APP_TOKEN", "GLPI_AUTH_BASIC"):
        replacement = _required_process_env_expr(name)
        for spacing in (" !== ", "!=="):
            weak = (
                "String((typeof process"
                + spacing
                + f"'undefined' && process.env.{name}) || '')"
            )
            value = value.replace(weak, replacement)

    # Code nodes that call the GLPI API directly do not benefit from the
    # separate "Validar Sessão GLPI" node at the exact call site.  Require the
    # session token locally as well, so a missing/invalid initSession result can
    # never be sent as an empty header.
    session_pattern = re.compile(
        r"const sessionToken = String\((\$\('[^']+'\)\.first\(\)\.json\.session_token) \|\| ''\);"
    )
    value = session_pattern.sub(
        r"const sessionToken = (() => { const value = String(\1 || '').trim(); "
        r"if (!value) throw new Error('GLPI session_token ausente'); return value; })();",
        value,
    )
    return normalize_n8n_env_access(value)

def n8n_expr(js):
    return "={{ " + js + " }}"

def code_node(nid, name, pos, js, always=True):
    n = {"parameters":{"jsCode":js},"type":"n8n-nodes-base.code","typeVersion":2,"position":pos,"id":nid,"name":name}
    if always: n["alwaysOutputData"]=True
    return n

def pg_query(nid, name, pos, query, opts=None, always=True):
    p = {"operation":"executeQuery","query":query,"options":opts or {}}
    n = {"parameters":p,"type":"n8n-nodes-base.postgres","typeVersion":2.5,"position":pos,"id":nid,"name":name,"credentials":PG_CRED}
    if always: n["alwaysOutputData"]=True
    return n

def http_req(nid, name, pos, url, method="GET", session_from=None, headers=None, query=None, body=None, always=True, on_error=None):
    p = {"url": url, "options": {}}
    if method != "GET": p["method"] = method
    hdrs = [{"name":"App-Token","value":APP_TOKEN_EXPR}]
    if session_from:
        hdrs.append({"name":"Session-Token","value":f"={{{{ $('{session_from}').first().json.session_token }}}}"})
    else:
        hdrs.append({"name":"Authorization","value":AUTH_BASIC_EXPR})
    if headers: hdrs.extend(headers)
    p["sendHeaders"] = True
    p["headerParameters"] = {"parameters": hdrs}
    if query:
        p["sendQuery"] = True
        p["queryParameters"] = {"parameters": query}
    if body:
        p["sendBody"] = True
        p["specifyBody"] = "json"
        p["jsonBody"] = body
    n = {"parameters":p,"type":"n8n-nodes-base.httpRequest","typeVersion":4.2,"position":pos,"id":nid,"name":name,"typeOptions":{"timeoutMilliseconds":15000}}
    if always: n["alwaysOutputData"]=True
    if on_error: n["onError"]=on_error
    return n

def glpi_init(nid, name, pos):
    return http_req(nid, name, pos, n8n_expr(f"{GLPI_URL_EXPR} + '/initSession'"))

def glpi_kill(nid, name, pos, session_from):
    return http_req(nid, name, pos, n8n_expr(f"{GLPI_URL_EXPR} + '/killSession'"), session_from=session_from, on_error="continueRegularOutput")

def glpi_search(nid, name, pos, criteria, session_from, rng="0-9999"):
    fields = [1,2,12,21,83,15,4,22,14,19]
    q = []
    for i,c in enumerate(criteria):
        q.append({"name":f"criteria[{i}][field]","value":str(c.get("field","12"))})
        q.append({"name":f"criteria[{i}][searchtype]","value":c.get("st","equals")})
        q.append({"name":f"criteria[{i}][value]","value":str(c["val"])})
        if "link" in c: q.append({"name":f"criteria[{i}][link]","value":c["link"]})
    for i,f in enumerate(fields):
        q.append({"name":f"forcedisplay[{i}]","value":str(f)})
    q.append({"name":"range","value":rng})
    return http_req(nid, name, pos, n8n_expr(f"{GLPI_URL_EXPR} + '/search/Ticket'"), session_from=session_from, query=q)

def glpi_update_ticket(nid, name, pos, ticket_id_expr, body, session_from):
    url = n8n_expr(f"{GLPI_URL_EXPR} + '/Ticket/' + {ticket_id_expr}")
    return http_req(nid, name, pos, url, method="PUT", session_from=session_from, body={"input":body})

def glpi_followup(nid, name, pos, ticket_id_expr, content_expr, session_from):
    return http_req(nid, name, pos, n8n_expr(f"{GLPI_URL_EXPR} + '/ITILFollowup'"), method="POST", session_from=session_from,
        body={"input":{"items_id":f"={{{{  {ticket_id_expr} }}}}","itemtype":"Ticket","content":f"={{{{{content_expr}}}}}"}})

def switch_node(nid, name, pos, cases, fallback=None):
    vals = []
    for c in cases:
        vals.append({
            "conditions":{"options":{"caseSensitive":True,"leftValue":"","typeValidation":"strict","version":2},
                "conditions":[{"leftValue":c["left"],"rightValue":c["right"],"operator":{"type":"string","operation":"equals"},"id":c.get("cid","c1")}],
                "combinator":"and"},
            "renameOutput":True,"outputKey":c["key"]
        })
    opts = {}
    if fallback: opts["fallbackOutput"] = fallback
    return {"parameters":{"rules":{"values":vals},"options":opts},"type":"n8n-nodes-base.switch","typeVersion":3.2,"position":pos,"id":nid,"name":name}

def if_node(nid, name, pos, left, op_type, op, right=None):
    cond = {"leftValue":left,"operator":{"type":op_type,"operation":op},"id":"if1"}
    if right is not None: cond["rightValue"]=right
    return {"parameters":{"conditions":{"options":{"caseSensitive":True,"leftValue":"","typeValidation":"strict","version":2},
        "conditions":[cond],"combinator":"and"},"options":{}},"type":"n8n-nodes-base.if","typeVersion":2.2,
        "position":pos,"id":nid,"name":name}

def webhook_node(nid, name, pos, path, method="POST", response_mode=None):
    p = {"path":path,"options":{}}
    if method != "GET": p["httpMethod"]=method
    if response_mode: p["responseMode"]=response_mode
    return {"parameters":p,"type":"n8n-nodes-base.webhook","typeVersion":2,"position":pos,"id":nid,"name":name,"webhookId":nid}

def respond_node(nid, name, pos, body_expr, code=200):
    return {"parameters":{"respondWith":"text","responseBody":body_expr,
        "options":{"responseCode":code,"responseHeaders":{"entries":[{"name":"Content-Type","value":"text/plain; charset=utf-8"}]}}},
        "type":"n8n-nodes-base.respondToWebhook","typeVersion":1.5,"position":pos,"id":nid,"name":name}

def exec_wf_trigger(nid, name, pos):
    return {"parameters":{},"type":"n8n-nodes-base.executeWorkflowTrigger","typeVersion":1,"position":pos,"id":nid,"name":name}

def exec_wf(nid, name, pos, wf_id_expr="", wait=False):
    return {"parameters":{"workflowId":{"__rl":True,"mode":"id","value":wf_id_expr},
        "workflowInputs":{"mappingMode":"defineBelow","value":{},"matchingColumns":[],"schema":[],"attemptToConvertTypes":False,"convertFieldsToString":True},
        "mode":"each","options":{"waitForSubWorkflow":wait}},
        "type":"n8n-nodes-base.executeWorkflow","typeVersion":1.2,"position":pos,"id":nid,"name":name}

def email_node(nid, name, pos, from_e, to_e, subject_expr, body_expr):
    return {"parameters":{"fromEmail":from_e,"toEmail":to_e,"subject":subject_expr,
        "emailFormat":"text","text":body_expr,"options":{"appendAttribution":False}},
        "type":"n8n-nodes-base.emailSend","typeVersion":2.1,"position":pos,"id":nid,"name":name,"credentials":SMTP_CRED}

def conn(src, *targets):
    """Build connection entry: conn('A', 'B') or conn('A', ['B','C'], ['D'])"""
    outputs = []
    for t in targets:
        if isinstance(t, str): t = [t]
        outputs.append([{"node":n,"type":"main","index":0} for n in t])
    return (src, {"main": outputs})

def workflow(name, nodes, connections, active=True):
    conns = {}
    for c in connections:
        conns[c[0]] = c[1]
    wf = {"name":name,"nodes":nodes,"pinData":{},"connections":conns,"active":active,
        "settings":{"executionOrder":"v1","timezone":"America/Sao_Paulo","saveExecutionProgress":True,"saveManualExecutions":True},
        "versionId":f"v9-{name[:10]}","meta":{},"tags":[]}
    if WORKFLOW_IDS.get(name):
        wf["id"] = WORKFLOW_IDS[name]
    return wf

def save(wf, path):
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(wf, f, indent=2, ensure_ascii=False)
    print(f"Salvo: {path}")
