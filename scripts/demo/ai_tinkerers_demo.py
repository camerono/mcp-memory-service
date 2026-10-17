#!/usr/bin/env python3
"""
AI Tinkerers Zürich — MCP Memory Service standalone demo (Tier-0, no LLM).
No Claude/Codex/local model needed — just the running HTTP server.
Deterministic: pre-canned dogfooding memories + 3 keyword-free semantic searches.

Usage:
    python scripts/demo/ai_tinkerers_demo.py          # full demo
    python scripts/demo/ai_tinkerers_demo.py --reset  # delete demo memories first

Env:
    MEMORY_BASE_URL  default http://127.0.0.1:8000
    MCP_API_KEY      bearer for the API; auto-read from repo .env if unset
"""
import os
import sys
import time
import shutil
import datetime
import textwrap
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_TTY = sys.stdout.isatty()
_W = shutil.get_terminal_size((100, 24)).columns


def _c(code, text):
    return f"\033[{code}m{text}\033[0m" if _TTY else text


def BOLD(t):   return _c("1",  t)
def CYAN(t):   return _c("36", t)
def GREEN(t):  return _c("32", t)
def RED(t):    return _c("31", t)
def YELLOW(t): return _c("33", t)
def DIM(t):    return _c("2",  t)


def _wrap(text, indent=7):
    return textwrap.fill(text, width=_W, subsequent_indent=" " * indent)


def _fmt_ts(mem):
    iso = mem.get("created_at_iso")
    if iso:
        try:
            return datetime.datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            pass
    ts = mem.get("created_at")
    if ts:
        return datetime.datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M")
    return "unknown"

BASE = os.environ.get("MEMORY_BASE_URL", "https://127.0.0.1:8000").rstrip("/")
DEMO_TAG = "ai-tinkerers-demo"


def _api_key():
    k = os.environ.get("MCP_API_KEY")
    if k:
        return k
    env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    try:
        with open(os.path.abspath(env_path), encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MCP_API_KEY="):
                    return line.split("=", 1)[1].strip().strip("\"'")
    except OSError:
        pass
    return ""


HEADERS = {"Authorization": f"Bearer {_api_key()}"}
S = requests.Session()
S.verify = False  # ponytail: self-signed cert on localhost
S.headers.update(HEADERS)

MEMORIES = [
    (
        "SQLite-vec replaces a dedicated vector database for KNN semantic search. "
        "One SQLite extension, one file, 5ms reads. No Pinecone, no Chroma, no Milvus.",
        ["architecture", "sqlite", "vector-search", DEMO_TAG],
        "learning",
    ),
    (
        "WAL journal mode (journal_mode=WAL) fixes concurrent SQLite access. "
        "Without WAL, two processes on the same file cause random 'database is locked' errors "
        "that are nearly impossible to reproduce in tests.",
        ["sqlite", "concurrency", "lessons-learned", DEMO_TAG],
        "error",
    ),
    (
        "ONNX model initialization (all-MiniLM-L6-v2) takes 30–60 seconds on first load. "
        "A global singleton cache prevents paying this cost on every MCP tool call. "
        "Without the cache: 30s hangs. With it: 534,628x speedup on subsequent calls.",
        ["onnx", "performance", "caching", DEMO_TAG],
        "learning",
    ),
    (
        "The Model Context Protocol (MCP) lets any AI client call tools via JSON-RPC "
        "over stdio or HTTP. Claude Desktop, Codex, OpenCode, and LangGraph all connect "
        "to the same MCP server without code changes. "
        "Any AI tool plugs into the same backend — one server, many clients, zero per-client configuration.",
        ["mcp", "protocol", "integration", DEMO_TAG],
        "observation",
    ),
    (
        "Local ONNX embeddings cost $0 and run at 80–150ms with no internet connection. "
        "The sentence-transformers model (all-MiniLM-L6-v2) is 22MB and runs fully offline. "
        "No OpenAI API key needed.",
        ["embeddings", "cost", "offline", DEMO_TAG],
        "decision",
    ),
    (
        "Hybrid storage: SQLite-vec handles fast local reads (5ms), "
        "Cloudflare D1 + Vectorize syncs in the background. "
        "Reads never touch the network — the cloud is write-only from the client's perspective.",
        ["architecture", "hybrid", "cloudflare", DEMO_TAG],
        "pattern",
    ),
]

QUERIES = [
    (
        "why does the database crash under concurrent access?",
        "→ surfaces the WAL/locking lesson (no keyword overlap with 'database is locked')",
    ),
    (
        "what does it cost to generate embeddings?",
        "→ surfaces the ONNX offline/cost memory ('cost' is not in the text)",
    ),
    (
        "how do different AI tools plug in to the same backend?",
        "→ surfaces the MCP protocol memory",
    ),
]


def separator(title=""):
    if title:
        print(BOLD(CYAN(f"\n{'─' * 20} {title} {'─' * 20}")))
    else:
        print(DIM("─" * 60))


def health_check():
    try:
        r = S.get(f"{BASE}/api/health", timeout=5)
        h = r.json()
        status = h.get('status', '?')
        print(f"Server:  {GREEN(status) if status == 'ok' else YELLOW(status)}")
        key_status = GREEN('set') if _api_key() else RED('MISSING')
        print(f"URL:     {BASE}  (key: {key_status})")
        return True
    except Exception as e:
        print(RED(f"ERROR: Cannot reach server at {BASE}"))
        print("       Demo launch:  MCP_HTTPS_ENABLED=false memory launch --storage-backend sqlite_vec")
        print(DIM(f"       {e}"))
        return False


def reset_demo_memories():
    print(f"Deleting memories tagged '{DEMO_TAG}'...")
    r = S.post(f"{BASE}/api/search/by-tag", json={"tags": [DEMO_TAG]}, timeout=10)
    items = r.json().get("results") or r.json().get("memories") or []
    deleted = 0
    for it in items:
        m = it.get("memory", it)
        h = m.get("content_hash") or m.get("hash")
        if h:
            S.delete(f"{BASE}/api/memories/{h}", timeout=5)
            deleted += 1
    print(f"Deleted {deleted} demo memories.\n")


def store_memories():
    separator("STORING MEMORIES")
    for content, tags, mtype in MEMORIES:
        r = S.post(f"{BASE}/api/memories",
                   json={"content": content, "tags": tags, "memory_type": mtype},
                   timeout=15)
        ok = r.status_code == 200
        status = GREEN("OK ") if ok else RED("ERR")
        print(f"  {status}  [{YELLOW(mtype)}]  {_wrap(content, indent=14)}")
        if not ok:
            print(DIM(f"       {r.text}"))
    print()


def semantic_search(query, note):
    print(f"Query:  {BOLD(repr(query))}")
    print(f"Expect: {DIM(note)}")
    t0 = time.time()
    r = S.post(f"{BASE}/api/search", json={"query": query, "n_results": 5}, timeout=15)
    elapsed = (time.time() - t0) * 1000
    results = r.json().get("results") or r.json().get("memories") or []
    print(f"{GREEN(BOLD(f'Found {len(results)} results'))} in {elapsed:.0f}ms:\n")
    for i, item in enumerate(results, 1):
        mem = item.get("memory", item)
        score = item.get("similarity_score") or item.get("relevance_score") or item.get("score")
        score_str = f"{score:.3f}" if isinstance(score, float) else str(score)
        tags = mem.get('tags', [])
        ts = _fmt_ts(mem)
        badge = YELLOW(" ★ demo") if DEMO_TAG in tags else ""
        print(f"  [{BOLD(str(i))}] score={BOLD(score_str)}  tags={CYAN(str(tags))}  {DIM(ts)}{badge}")
        content = mem.get('content') or ''
        wrapped = _wrap(content, indent=7)
        print(f"       {YELLOW(wrapped) if DEMO_TAG in tags else wrapped}\n")


def run_demo():
    separator("HEALTH CHECK")
    if not health_check():
        sys.exit(1)
    store_memories()
    separator("SEMANTIC SEARCH — keyword-free retrieval")
    print("The queries below share NO keywords with the stored memories.\n")
    for query, note in QUERIES:
        separator()
        semantic_search(query, note)
    separator("DONE")
    print(f"Memories are tagged '{DEMO_TAG}' — run with --reset to clean up.\n")


if __name__ == "__main__":
    if "--reset" in sys.argv:
        if not health_check():
            sys.exit(1)
        reset_demo_memories()
    else:
        run_demo()
