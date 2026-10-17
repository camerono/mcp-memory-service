# Extension points

Read this before adding an MCP tool, a storage backend, or a document loader.

## Adding a new MCP tool

Tools are declarative as of v11. The old inline `types.Tool(...)` list in `list_tools()`
and the `call_tool()` elif chain are both gone.

1. Add a `ToolDef(name, description, input_schema, annotations)` to `TOOL_REGISTRY` in
   `tools/registry.py`. Set `annotations={"readOnlyHint": True, ...}` for non-mutating
   tools: annotations drive OAuth scope, and without `readOnlyHint` the HTTP `/mcp`
   layer treats the tool as a write tool and demands the OAuth `write` scope
   (GHSA-2r68-g678-7qr3).
2. Implement `async def handle_X(server, arguments) -> List[types.TextContent]` in
   `server/handlers/*.py`.
3. Add `"<tool_name>": <handler>` to `ROUTING_TABLE` in `tools/routing.py`. Use a module
   function reference, or the `("__self__", "handle_X")` tuple to dispatch to a
   `MemoryServer` method.
4. If the tool reads a caller-supplied path (`project_path`, `file_path`,
   `directory_path`), add its name to `local_only_tools()` in `server_impl.py` so the
   HTTP shim will not expose it.
5. Add tests in `tests/server/test_handlers.py`.

Renaming a tool is a breaking change. The alias layer (`compat.DEPRECATED_TOOLS`) was
removed in v11 (Issue #53), so a rename drops the old name outright. Treat it as a major
version change and document the migration in `docs/MIGRATION.md`.

## Other extension points

New storage backend: implement `BaseStorage` (`storage/base.py`), add a factory method
in `storage/factory.py`, add `tests/storage/test_<backend>.py`. New document loader:
implement `DocumentLoader` (`ingestion/base.py`), register it in
`ingestion/registry.py`, add `tests/ingestion/test_<loader>.py`.

Maintenance scripts, all supporting `--dry-run`:
`scripts/maintenance/improve_memory_ontology.py` re-classifies memory types,
`update_graph_relationship_types.py` infers relationship types for existing
associations, `cleanup_memories.py` removes test memories and orphaned data.

`scripts/migration/migrate_sqlite_vec_embeddings.py` does not follow that shape. It
takes the database path as a positional argument, has no flags and no `--dry-run`, and
prompts `Continue? (y/N)` — so it cannot run unattended. It copies the database to
`<db>.backup_<timestamp>` before touching anything, then rebuilds the schema and
re-embeds every memory. It also carries over the tables the rebuild cannot regenerate,
graph edges and derived beliefs; before v11.6.0 it dropped them silently (#189). Both
Docker images ship it (#188).
