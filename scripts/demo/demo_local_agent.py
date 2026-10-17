#!/usr/bin/env python3
"""
Offline local-LLM agent for the AI Tinkerers Zürich demo.

Proves "any agent gets persistent semantic memory" WITHOUT internet:
a local OpenAI-compatible LLM (oMLX or Ollama) drives tool-calls against the
mcp-memory-service REST API.

Backend-agnostic: oMLX and Ollama both speak /v1/chat/completions, so one
script drives either — just point LLM_BASE_URL at the right port.

Usage:
  # End-to-end (needs a local LLM running):
  #   Path A (oMLX):   LLM_BASE_URL=http://127.0.0.1:8080/v1  LLM_MODEL=qwen3-8b-8bit
  #   Path B (Ollama): LLM_BASE_URL=http://127.0.0.1:11434/v1 LLM_MODEL=qwen2.5:7b-instruct
  python3 demo_local_agent.py "Remember that the demo runs offline on a MacBook M2, then recall it."

  # Interactive REPL chat (STAGE MODE — no args, or --chat): type messages, watch tool-calls:
  python3 demo_local_agent.py
  python3 demo_local_agent.py --chat

  # Self-test the REST plumbing only (NO LLM needed — proves memory works offline):
  python3 demo_local_agent.py --selftest

Env:
  LLM_BASE_URL    OpenAI-compatible base (default http://127.0.0.1:11434/v1 = Ollama)
  LLM_MODEL       model id (default qwen2.5:7b-instruct)
  LLM_API_KEY     usually unused locally (default "local")
  LLM_EXTRA_BODY  JSON merged into the request body. For Qwen3 turn thinking OFF:
                  '{"chat_template_kwargs": {"enable_thinking": false}}'
                  (Qwen3 thinking silently breaks tool-calls.)
  MEMORY_BASE_URL default https://127.0.0.1:8000  (HTTPS self-signed)
  MCP_API_KEY     bearer for the memory API; auto-read from repo .env if unset
"""
import json
import os
import re
import ssl
import sys
import urllib.request
import urllib.error

# --- terminal colors (TTY-safe, no deps) ------------------------------------
_TTY = sys.stdout.isatty()
def _c(code, t): return f"\033[{code}m{t}\033[0m" if _TTY else t
def BOLD(t):   return _c("1",    t)
def CYAN(t):   return _c("36",   t)
def GREEN(t):  return _c("32",   t)
def RED(t):    return _c("31",   t)
def YELLOW(t): return _c("33",   t)
def DIM(t):    return _c("2",    t)

# --- config -----------------------------------------------------------------
# Defaults = MacBook stage setup (oMLX + plain-HTTP memory). Override any via env.
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:8081/v1").rstrip("/")   # oMLX/mlx_lm.server
LLM_MODEL = os.environ.get("LLM_MODEL", "mlx-community/Qwen3-4B-8bit")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "local")
MEMORY_BASE_URL = os.environ.get("MEMORY_BASE_URL", "https://127.0.0.1:8000").rstrip("/")  # demo server (plain HTTP)

# Qwen3 thinking OFF by default (thinking breaks tool-calls). For Ollama/non-Qwen3: set LLM_EXTRA_BODY='{}'.
try:
    LLM_EXTRA_BODY = json.loads(os.environ.get(
        "LLM_EXTRA_BODY", '{"chat_template_kwargs": {"enable_thinking": false}}'))
except json.JSONDecodeError:
    print("WARN: LLM_EXTRA_BODY is not valid JSON; ignoring.", file=sys.stderr)
    LLM_EXTRA_BODY = {}


def _memory_api_key():
    key = os.environ.get("MCP_API_KEY")
    if key:
        return key
    # auto-read from the repo .env (two dirs up from scripts/demo/)
    env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    try:
        with open(os.path.abspath(env_path), encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MCP_API_KEY="):
                    return line.split("=", 1)[1].strip().strip("\"'")
    except OSError:
        pass
    return ""


MCP_API_KEY = _memory_api_key()
# self-signed cert on the local memory server -> don't verify (localhost only)
_TLS = ssl.create_default_context()
_TLS.check_hostname = False
_TLS.verify_mode = ssl.CERT_NONE


def _post_json(url, payload, headers, timeout=120):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    ctx = _TLS if url.startswith("https") else None
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"_error": f"HTTP {e.code}", "_body": e.read().decode("utf-8", "replace")[:500]}
    except Exception as e:  # noqa: BLE001 - demo robustness
        return {"_error": str(e)}


# --- memory tools (the two functions the LLM can call) ----------------------
def _mem_headers():
    return {"Authorization": f"Bearer {MCP_API_KEY}", "Content-Type": "application/json"}


def store_memory(content, tags=None, memory_type="note"):
    body = {"content": content, "tags": list({*(tags or []), "ai-tinkerers-demo"}), "memory_type": memory_type}
    r = _post_json(f"{MEMORY_BASE_URL}/api/memories", body, _mem_headers())
    if r.get("_error"):
        return {"ok": False, "error": r["_error"], "detail": r.get("_body", "")}
    return {"ok": bool(r.get("success")), "content_hash": r.get("content_hash") or ""}


def search_memory(query, n_results=5):
    body = {"query": query, "n_results": n_results}
    r = _post_json(f"{MEMORY_BASE_URL}/api/search", body, _mem_headers())
    if r.get("_error"):
        return {"ok": False, "error": r["_error"]}
    hits = []
    for x in r.get("results", []):
        m = x.get("memory", x)
        hits.append({
            "hash": m.get("content_hash"),
            "content": (m.get("content") or "")[:280],
            "tags": m.get("tags", []),
        })
    return {"ok": True, "count": len(hits), "results": hits}


def _mem_request(method, path, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(MEMORY_BASE_URL + path, data=data,
                                 headers=_mem_headers(), method=method)
    ctx = _TLS if MEMORY_BASE_URL.startswith("https") else None
    try:
        with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"_error": f"HTTP {e.code}", "_body": e.read().decode("utf-8", "replace")[:300]}
    except Exception as e:  # noqa: BLE001 - demo robustness
        return {"_error": str(e)}


def delete_memory(content_hash):
    r = _mem_request("DELETE", f"/api/memories/{content_hash}")
    if r.get("_error"):
        return {"ok": False, "error": r["_error"]}
    return {"ok": bool(r.get("success", True)), "deleted": content_hash[:12]}


def merge_memories(content_hashes, merged_content, tags=None):
    """Merge 2+ memories into one: delete all sources, then store the merged content."""
    if not content_hashes or len(content_hashes) < 2:
        return {"ok": False, "error": "requires at least 2 content_hashes"}
    for h in content_hashes:
        d = _mem_request("DELETE", f"/api/memories/{h}")
        if d.get("_error"):
            return {"ok": False, "error": f"delete failed for {h[:12]}: {d['_error']}"}
        if not d.get("success", True):
            return {"ok": False, "error": f"memory not found: {h[:12]}"}
    new = store_memory(merged_content, tags=tags)
    new["merged"] = content_hashes
    return new


def update_memory(content_hash, content, tags=None):
    """Replace a memory's content: delete the old hash, then store the new content."""
    d = _mem_request("DELETE", f"/api/memories/{content_hash}")
    if d.get("_error"):
        return {"ok": False, "error": "delete failed: " + d["_error"]}
    if not d.get("success", True):
        return {"ok": False, "error": f"delete failed: {d.get('message', 'not found')}"}
    new = store_memory(content, tags=tags)
    new["replaced"] = content_hash
    return new


def _fmt_hits(data, limit=8):
    items = data.get("results") or data.get("memories") or []
    hits = []
    for x in items[:limit]:
        m = x.get("memory", x) if isinstance(x, dict) else {}
        hits.append({
            "hash": m.get("content_hash"),
            "content": (m.get("content") or "")[:240],
            "tags": m.get("tags", []),
        })
    return hits


def recall_by_time(time_query, semantic_query=None, n_results=5):
    """Time-based recall: time_query like 'yesterday', 'last week', '3 days ago'."""
    body = {"query": time_query, "n_results": n_results}
    if semantic_query:
        body["semantic_query"] = semantic_query
    r = _post_json(f"{MEMORY_BASE_URL}/api/search/by-time", body, _mem_headers())
    if r.get("_error"):
        return {"ok": False, "error": r["_error"]}
    hits = _fmt_hits(r)
    return {"ok": True, "count": len(hits), "results": hits}


def recall_by_tag(tags, time_filter=None, match_all=False):
    """Find memories by tag(s); optional time_filter ('last week') narrows the window."""
    body = {"tags": tags, "match_all": match_all}
    if time_filter:
        body["time_filter"] = time_filter
    r = _post_json(f"{MEMORY_BASE_URL}/api/search/by-tag", body, _mem_headers())
    if r.get("_error"):
        return {"ok": False, "error": r["_error"]}
    hits = _fmt_hits(r)
    return {"ok": True, "count": len(hits), "results": hits}


def list_recent(limit=5):
    """Browse the most recent memories (no query)."""
    r = _mem_request("GET", f"/api/memories?page=1&page_size={int(limit)}")
    if r.get("_error"):
        return {"ok": False, "error": r["_error"]}
    hits = _fmt_hits(r, limit=int(limit))
    return {"ok": True, "count": len(hits), "results": hits}


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "store_memory",
            "description": "Persist a piece of information in long-term semantic memory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "The information to remember."},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_memory",
            "description": "Semantically search long-term memory and return the best matches.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "n_results": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_memory",
            "description": "Delete a memory permanently by its content_hash (get the hash from search_memory first).",
            "parameters": {
                "type": "object",
                "properties": {"content_hash": {"type": "string", "description": "hash from search_memory"}},
                "required": ["content_hash"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "merge_memories",
            "description": "Merge two or more redundant or related memories into one consolidated entry. Deletes all source memories and stores the merged content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content_hashes": {"type": "array", "items": {"type": "string"}, "description": "hashes of the memories to merge (minimum 2, get them from search_memory)"},
                    "merged_content": {"type": "string", "description": "the combined, consolidated content"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["content_hashes", "merged_content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_memory",
            "description": "Replace a memory's content: deletes the old memory (content_hash from search_memory) and stores the new content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content_hash": {"type": "string", "description": "hash of the memory to replace"},
                    "content": {"type": "string", "description": "the corrected/new content"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["content_hash", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall_by_time",
            "description": "Recall memories from a time window. time_query is natural language: 'yesterday', 'last week', '3 days ago'. Optional semantic_query narrows by meaning.",
            "parameters": {
                "type": "object",
                "properties": {
                    "time_query": {"type": "string", "description": "e.g. 'yesterday', 'last week'"},
                    "semantic_query": {"type": "string", "description": "optional topic filter within the time range"},
                    "n_results": {"type": "integer", "default": 5},
                },
                "required": ["time_query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall_by_tag",
            "description": "Find memories that have specific tag(s). Optional time_filter ('last week') narrows the window.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "time_filter": {"type": "string", "description": "optional, e.g. 'last month'"},
                    "match_all": {"type": "boolean", "description": "true = must have ALL tags (default ANY)"},
                },
                "required": ["tags"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_recent",
            "description": "Browse the most recently stored memories (no query needed).",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "default": 5}},
            },
        },
    },
]
DISPATCH = {
    "store_memory": store_memory,
    "search_memory": search_memory,
    "recall_by_time": recall_by_time,
    "recall_by_tag": recall_by_tag,
    "list_recent": list_recent,
    "update_memory": update_memory,
    "merge_memories": merge_memories,
    "delete_memory": delete_memory,
}


# --- LLM loop ---------------------------------------------------------------
def _chat(messages):
    payload = {"model": LLM_MODEL, "messages": messages, "tools": TOOLS,
               "tool_choice": "auto", "stream": False}
    payload.update(LLM_EXTRA_BODY)
    headers = {"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"}
    return _post_json(f"{LLM_BASE_URL}/chat/completions", payload, headers)


SYSTEM = {"role": "system", "content": (
    "You are a helpful assistant with persistent memory. "
    "RULE 1 — ALWAYS call a tool before answering any question about the user's past, "
    "preferences, habits, or context. NEVER say 'I need more info' or ask for clarification "
    "— just pick the best query and call search_memory. Vague questions are fine: guess a "
    "good search term and search. "
    "RULE 2 — Never generate <error> tags or refuse. If unsure, call search_memory anyway. "
    "Tools: store_memory, search_memory (by meaning), recall_by_time ('yesterday'/'last week'), "
    "recall_by_tag, list_recent, update_memory, merge_memories, delete_memory. "
    "Routing: time questions -> recall_by_time; 'tagged X' -> recall_by_tag; "
    "'recent/what do I have' -> list_recent; everything else -> search_memory. "
    "To update/delete: search first to get the hash, then call update_memory/delete_memory. "
    "To merge duplicates: use merge_memories with their hashes + combined content. "
    "Never fake an action by storing a note. Be concise.")}


def _parse_text_toolcalls(content):
    # ponytail: fallback for Qwen3 text-format tool calls when enable_thinking doesn't reach mlx_lm.server
    calls = []
    for m in re.finditer(r'<tool_call>\s*(\{.*?\})\s*</tool_call>', content or "", re.DOTALL):
        try:
            data = json.loads(m.group(1))
            calls.append({"id": data.get("name", "call"), "function": {
                "name": data.get("name", ""),
                "arguments": json.dumps(data.get("arguments", data.get("parameters", {}))),
            }})
        except json.JSONDecodeError:
            pass
    return calls


def agent_turn(messages, max_steps=6):
    """Run the tool-call loop until the model returns a final text.
    messages is mutated in place (so chat history persists). Returns final text."""
    for _ in range(max_steps):
        resp = _chat(messages)
        if resp.get("_error"):
            print(RED(f"  ⚠ LLM error: {resp['_error']} {resp.get('_body', '')}"))
            return None
        msg = resp["choices"][0]["message"]
        messages.append(msg)
        calls = msg.get("tool_calls") or _parse_text_toolcalls(msg.get("content"))
        if not calls:
            return msg.get("content") or ""
        for call in calls:
            fn = call["function"]["name"]
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            args_str = json.dumps(args, ensure_ascii=False)[:140]
            print(f"  {CYAN('->')} {BOLD(fn)}{DIM('(' + args_str + ')')}")
            result = DISPATCH.get(fn, lambda **_: {"error": "unknown tool"})(**args)
            print(DIM(f"     {json.dumps(result, ensure_ascii=False)[:180]}"))
            messages.append({
                "role": "tool",
                "tool_call_id": call.get("id", fn),
                "content": json.dumps(result, ensure_ascii=False),
            })
    return "(max steps reached)"


def run_agent(user_prompt):
    """One-shot: single prompt, run the loop, print the answer."""
    messages = [SYSTEM, {"role": "user", "content": user_prompt}]
    out = agent_turn(messages)
    print(f"\n{GREEN(BOLD('Assistant'))}: " + (out or "(no content)"))


def chat():
    """Interactive REPL: type messages, watch tool-calls, persistent history."""
    print(BOLD(CYAN("Local memory agent (offline)")) + " — type a message; tool-calls show as '-> name(...)'.")
    print(DIM(f"  LLM:    {LLM_MODEL} @ {LLM_BASE_URL}"))
    key_status = GREEN("set") if MCP_API_KEY else RED("MISSING")
    print(DIM(f"  Memory: {MEMORY_BASE_URL}  (key: ") + key_status + DIM(")"))
    print(DIM("  Commands: /reset (clear history), exit | quit") + "\n")
    messages = [SYSTEM]
    while True:
        try:
            user = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            return
        if not user:
            continue
        if user in ("exit", "quit", "/exit", "/quit"):
            print("bye")
            return
        if user == "/reset":
            messages = [SYSTEM]
            print(DIM("(history cleared)\n"))
            continue
        messages.append({"role": "user", "content": user})
        out = agent_turn(messages)
        print(f"\n{GREEN(BOLD('Assistant'))}: " + (out or "(no content)") + "\n")


# --- self-test (no LLM): proves the memory REST plumbing works offline ------
def selftest():
    key_status = GREEN("set") if MCP_API_KEY else RED("MISSING")
    print(f"memory: {MEMORY_BASE_URL}  key:" + key_status)
    s = store_memory("AI Tinkerers Zürich offline-demo selftest marker.",
                     tags=["__demo_selftest__"])
    print(DIM("store_memory  ->"), s)
    q = search_memory("offline demo selftest marker", n_results=3)
    print(DIM("search_memory ->"), json.dumps(q, ensure_ascii=False)[:400])
    ok = s.get("ok") and q.get("ok") and q.get("count", 0) > 0
    result_str = GREEN(BOLD("PASS")) if ok else RED(BOLD("FAIL"))
    print(f"\n{BOLD('SELFTEST:')} {result_str}")
    return 0 if ok else 1


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "--selftest":
        sys.exit(selftest())
    elif a and a[0] in ("--chat", "-i"):
        chat()
    elif a and a[0] in ("-h", "--help"):
        print(__doc__)
    elif a:
        run_agent(" ".join(a))      # one-shot (back-compat)
    else:
        chat()                       # no args -> interactive REPL (stage mode)
