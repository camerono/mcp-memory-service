#!/usr/bin/env python3
"""
backfill_has_entity.py — Rebuild has_entity edges from existing memories.

Use after applying the prune fix (#150) to repopulate has_entity edges
that were incorrectly deleted by previous consolidation cycles.

Usage:
    python scripts/maintenance/backfill_has_entity.py [--dry-run] [--db PATH]

Options:
    --dry-run   Show what would be inserted without writing
    --db PATH   Path to sqlite_vec.db (default: ~/.local/share/mcp-memory/sqlite_vec.db)
"""

import argparse
import json
import os
import sqlite3
import sys
import time

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))


def get_default_db_path():
    """Resolve default DB path from env or standard location."""
    return os.environ.get(
        "MCP_MEMORY_SQLITE_PATH",
        os.path.expanduser("~/.local/share/mcp-memory/sqlite_vec.db"),
    )


def main():
    parser = argparse.ArgumentParser(description="Backfill has_entity edges")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--db", default=get_default_db_path(), help="Path to sqlite_vec.db")
    args = parser.parse_args()

    if not os.path.exists(args.db):
        print(f"Error: database not found at {args.db}")
        sys.exit(1)

    try:
        from mcp_memory_service.extraction.entity_extractor import EntityExtractor
    except ImportError:
        print("Error: cannot import EntityExtractor. Run from repo root or install package.")
        sys.exit(1)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    # Count existing has_entity edges
    before = conn.execute(
        "SELECT COUNT(*) FROM memory_graph WHERE relationship_type = 'has_entity'"
    ).fetchone()[0]
    print(f"has_entity edges before: {before}")

    # Get all non-deleted memories
    cursor = conn.execute(
        "SELECT content_hash, content, metadata FROM memories WHERE deleted_at IS NULL"
    )

    extractor = EntityExtractor()
    inserted = 0
    processed = 0
    now = time.time()

    for row in cursor:
        processed += 1
        if processed % 1000 == 0:
            print(f"  processed {processed} memories...")

        content = row["content"] or ""
        if len(content) < 20:
            continue

        metadata = {}
        if row["metadata"]:
            try:
                metadata = json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"]
            except (json.JSONDecodeError, TypeError):
                pass

        try:
            entities = extractor.extract_entities(content, metadata)
        except Exception:
            continue

        for ent in entities:
            if args.dry_run:
                inserted += 1
            else:
                try:
                    conn.execute(
                        """INSERT OR IGNORE INTO memory_graph
                           (source_hash, target_hash, similarity, connection_types, metadata, created_at, relationship_type)
                           VALUES (?, ?, 1.0, '["entity"]', ?, ?, 'has_entity')""",
                        (
                            row["content_hash"],
                            ent.name,
                            json.dumps({"entity_type": getattr(ent, 'entity_type', 'unknown')}),
                            now,
                        ),
                    )
                    inserted += 1
                except sqlite3.Error:
                    pass

    if not args.dry_run:
        conn.commit()

    after = conn.execute(
        "SELECT COUNT(*) FROM memory_graph WHERE relationship_type = 'has_entity'"
    ).fetchone()[0]
    conn.close()

    mode = "DRY-RUN" if args.dry_run else "LIVE"
    print(f"\nResults ({mode}):")
    print(f"  Memories processed: {processed}")
    print(f"  Edges {'would be' if args.dry_run else ''} inserted: {inserted}")
    print(f"  has_entity edges after: {after if not args.dry_run else before + inserted}")


if __name__ == "__main__":
    main()
