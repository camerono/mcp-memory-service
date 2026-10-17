#!/usr/bin/env python3
"""
Concurrency money-shot for the AI Tinkerers demo:
"what happens when two processes fight over the same SQLite file."

Shows the classic 'database is locked' with default (rollback) journaling,
then how WAL + busy_timeout — exactly mcp-memory-service's fix
(MCP_MEMORY_SQLITE_PRAGMAS=journal_mode=WAL,busy_timeout=15000) — makes
concurrent access work.

Uses a THROWAWAY /tmp database. Never touches the real memory DB.

Run:  python3 scripts/demo/concurrency_demo.py
"""
import os
import sys
import sqlite3
import threading
import time

DB = "/tmp/mcp_concurrency_demo.db"   # throwaway; never the real memory DB

_TTY = sys.stdout.isatty()


def _c(code, text):
    return f"\033[{code}m{text}\033[0m" if _TTY else text


def BOLD(t):   return _c("1",  t)
def CYAN(t):   return _c("36", t)
def GREEN(t):  return _c("32", t)
def RED(t):    return _c("31", t)
def YELLOW(t): return _c("33", t)
def DIM(t):    return _c("2",  t)


import re

ENV_VAR = "MCP_MEMORY_SQLITE_PRAGMAS"
ENV_VAL = "journal_mode=WAL,busy_timeout=15000"
CODE_REF = "src/mcp_memory_service/storage/mixins/base.py:295"


def _vis(s):
    """Visible length of a string — strips ANSI escape codes."""
    return len(re.sub(r"\033\[[0-9;]*m", "", s))


def _callout():
    """Print where the fix lives — .env line + source location."""
    w = 70  # inner width (visible chars between │ and │)
    def mid(s):
        pad = " " * max(0, w - 1 - _vis(s))
        return CYAN("│") + " " + s + pad + CYAN("│")
    current = os.environ.get(ENV_VAR, "(not set)")
    print()
    print(CYAN("┌" + "─" * w + "┐"))
    print(mid(BOLD("Where the fix lives")))
    print(mid(""))
    print(mid(f".env :  {YELLOW(ENV_VAR + '=' + ENV_VAL)}"))
    print(mid(f"live :  {GREEN(current)}"))
    print(mid(""))
    print(mid(f"code :  {DIM(CODE_REF)}"))
    print(mid(DIM(f'         os.environ.get("{ENV_VAR}", "")')))
    print(CYAN("└" + "─" * w + "┘"))
    print()


def reset(journal):
    for suffix in ("", "-wal", "-shm", "-journal"):
        try:
            os.remove(DB + suffix)
        except OSError:
            pass
    c = sqlite3.connect(DB)
    c.execute(f"PRAGMA journal_mode={journal}")
    c.execute("CREATE TABLE t (who TEXT, ts REAL)")
    c.commit()
    c.close()


def hold_lock(journal, seconds, ready):
    """Process A: grab the write lock and hold it (simulates a busy writer)."""
    c = sqlite3.connect(DB, timeout=0)
    c.execute(f"PRAGMA journal_mode={journal}")
    c.execute("BEGIN IMMEDIATE")                       # acquire write lock NOW
    c.execute("INSERT INTO t VALUES ('A', ?)", (time.time(),))
    print(f"  A: holds the write lock for {seconds}s ...")
    ready.set()
    time.sleep(seconds)
    c.commit()
    c.close()
    print("  A: committed, lock released")


def try_write(journal, busy_ms):
    """Process B: try to write while A holds the lock."""
    c = sqlite3.connect(DB, timeout=0)
    c.execute(f"PRAGMA journal_mode={journal}")
    c.execute(f"PRAGMA busy_timeout={busy_ms}")
    t0 = time.time()
    try:
        c.execute("BEGIN IMMEDIATE")
        c.execute("INSERT INTO t VALUES ('B', ?)", (time.time(),))
        c.commit()
        print(f"  B: WROTE OK after {time.time() - t0:.1f}s  "
              f"(busy_timeout queued it instead of failing)")
    except sqlite3.OperationalError as e:
        print(f"  B: >>> sqlite error: {e} <<<  (after {time.time() - t0:.1f}s)")
    finally:
        c.close()


def try_read(journal):
    """Process R: read while A holds the write lock (WAL lets readers through)."""
    c = sqlite3.connect(DB, timeout=0)
    c.execute(f"PRAGMA journal_mode={journal}")
    try:
        n = c.execute("SELECT COUNT(*) FROM t").fetchone()[0]
        print(f"  R: READ OK while A writes -> {n} row(s)  (WAL: readers never block)")
    except sqlite3.OperationalError as e:
        print(f"  R: read failed -> {e}")
    finally:
        c.close()


def phase(title, journal, busy_ms, with_reader=False):
    print(BOLD(CYAN(f"\n=== {title} ===")))
    reset(journal)
    ready = threading.Event()
    a = threading.Thread(target=hold_lock, args=(journal, 3, ready))
    a.start()
    ready.wait()
    time.sleep(0.3)            # make sure A is holding before B/R try
    if with_reader:
        try_read(journal)
    try_write(journal, busy_ms)
    a.join()


if __name__ == "__main__":
    print(BOLD(f"Two connections fight over ONE SQLite file: {DIM(DB)}"))
    phase("1) Default journal (rollback), busy_timeout=200ms  →  the classic failure",
          journal="DELETE", busy_ms=200, with_reader=False)
    _callout()
    phase("2) WAL + busy_timeout=15000ms  →  mcp-memory-service's fix",
          journal="WAL", busy_ms=15000, with_reader=True)
    print()
    print(BOLD("Takeaway: ") + RED("'database is locked'") + " unless you set WAL + busy_timeout.")
    print(f"  .env:  {YELLOW(ENV_VAR)}={YELLOW(ENV_VAL)}")
