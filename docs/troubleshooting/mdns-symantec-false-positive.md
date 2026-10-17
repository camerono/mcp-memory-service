# mDNS / zeroconf flagged as a trojan by Symantec (Windows false positive)

## Symptom

On Windows with Symantec Endpoint Protection (SEP) active, importing the
`zeroconf` package fails at the compiled C extension:

```
ImportError: DLL load failed while importing _listener: Zugriff verweigert
ImportError: DLL load failed while importing multicast_outgoing_queue: Zugriff verweigert
ImportError: ... keine zulaessige Win32-Anwendung   (not a valid Win32 application)
ValueError: zeroconf._handlers.multicast_outgoing_queue.MulticastOutgoingQueue
            size changed, may indicate binary incompatibility
```

Test collection then aborts for the mDNS / discovery suites:

```
ERROR collecting tests/discovery/test_tls_verification.py
ERROR collecting tests/integration/test_mdns_integration.py
ERROR collecting tests/unit/test_mdns.py
FAILED  tests/unit/test_mdns_simple.py::test_imports
```

## Cause

`zeroconf` ships compiled C extensions (`.pyd`). Symantec heuristics flag these
binaries as a trojan (false positive) and quarantine or lock the file. The OS
then denies the DLL load ("Zugriff verweigert" / access denied). A partially
quarantined install also leaves mismatched binaries, producing the
"size changed / binary incompatibility" error.

This is a **false positive**. zeroconf is a legitimate mDNS/DNS-SD library.

## Impact

mDNS is used only for **automatic service discovery** on the local network
(advertising the HTTP server so clients can find it without a hardcoded URL).

The core service does NOT depend on it:
- HTTP API, MCP transport, and all storage backends work without mDNS.
- The HTTP server starts normally; mDNS advertisement is skipped if the import
  fails.

## Resolution

### Option A - you do not need mDNS (recommended on this machine)

Disable mDNS advertisement so the server never imports zeroconf:

```bash
# .env
MCP_MDNS_ENABLED=false
```

Default is `true`. Connect clients to the explicit URL
(`http://127.0.0.1:8000`) instead of relying on discovery.

Run the test suite excluding the mDNS / discovery suites:

```bash
pytest tests/ \
  --ignore=tests/discovery \
  --ignore=tests/unit/test_mdns.py \
  --ignore=tests/integration/test_mdns_integration.py
# also deselect tests/unit/test_mdns_simple.py if present
```

### Option B - you need mDNS discovery

1. Add a Symantec exception for the zeroconf package directory, e.g.
   `.venv\Lib\site-packages\zeroconf` (and the project `.venv` if policy allows).
2. Reinstall zeroconf with a clean, uncached build (stop the running server
   first, since it locks the loaded `.pyd`):

   ```bash
   memory stop
   uv pip install --no-cache --reinstall "zeroconf>=0.130.0"
   python -c "import zeroconf; print('OK', zeroconf.__version__)"
   memory restart
   ```

3. If the import still fails, the SEP exception did not take effect - confirm
   with your endpoint admin that the path is whitelisted.

## Notes

- Do not "fix" this by editing storage or server code; it is purely an
  environment / antivirus issue.
- `uv run` may silently uninstall/reinstall packages and can leave a corrupted
  zeroconf if SEP interferes mid-operation. Prefer `uv pip install` for targeted
  changes, and reinstall zeroconf with `--no-cache --reinstall` if it breaks.
