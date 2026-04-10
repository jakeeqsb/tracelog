"""TraceLog CLI — index, diagnose, and commit postmortems.

Usage:
    tracelog index <dump_dir>
    tracelog diagnose <dump_file>
    tracelog postmortem commit --incident-id <id> --root-cause <...> --fix <...>
    tracelog postmortem search --query <text> [--top-k N]
"""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _cmd_index(args: argparse.Namespace) -> None:
    from tracelog.rag.indexer import TraceLogIndexer

    dump_dir = Path(args.dump_dir)
    if not dump_dir.is_dir():
        print(f"Error: {dump_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    indexer = TraceLogIndexer()
    total = indexer.index_directory(dump_dir)
    print(f"Indexed {total} chunks from {dump_dir}")


def _cmd_diagnose(args: argparse.Namespace) -> None:
    from tracelog.rag.indexer import TraceLogIndexer
    from tracelog.rag.retriever import TraceLogRetriever
    from tracelog.rag.diagnoser import TraceLogDiagnoser
    from tracelog.rag.stores.qdrant import QdrantStore

    dump_file = Path(args.dump_file)
    if not dump_file.is_file():
        print(f"Error: {dump_file} does not exist", file=sys.stderr)
        sys.exit(1)

    incident_store = QdrantStore(collection_name=os.environ["TRACELOG_INCIDENTS_COLLECTION"])
    postmortem_store = QdrantStore(collection_name=os.environ["TRACELOG_POSTMORTEMS_COLLECTION"])

    retriever = TraceLogRetriever(
        store=incident_store,
        postmortem_store=postmortem_store,
    )
    diagnoser = TraceLogDiagnoser()

    current_chunk = dump_file.read_text(encoding="utf-8")
    similar = retriever.search(current_chunk, top_k=args.top_k)
    result = diagnoser.diagnose(current_chunk, similar)

    print(json.dumps(result, indent=2, ensure_ascii=False))


def _cmd_postmortem_search(args: argparse.Namespace) -> None:
    from tracelog.rag.retriever import TraceLogRetriever
    from tracelog.rag.stores.qdrant import QdrantStore
    from dataclasses import asdict

    postmortem_store = QdrantStore(collection_name=os.environ["TRACELOG_POSTMORTEMS_COLLECTION"])
    retriever = TraceLogRetriever(
        store=QdrantStore(collection_name=os.environ["TRACELOG_INCIDENTS_COLLECTION"]),
        postmortem_store=postmortem_store,
    )

    results = retriever.search_fixes(args.query, top_k=args.top_k)
    print(json.dumps([asdict(r) for r in results], indent=2, ensure_ascii=False))


def _cmd_postmortem_commit(args: argparse.Namespace) -> None:
    from tracelog.rag.postmortem_indexer import PostmortemIndexer
    from tracelog.rag.stores.qdrant import QdrantStore

    incident_store = QdrantStore(collection_name=os.environ["TRACELOG_INCIDENTS_COLLECTION"])
    postmortem_store = QdrantStore(collection_name=os.environ["TRACELOG_POSTMORTEMS_COLLECTION"])

    indexer = PostmortemIndexer(store=postmortem_store)
    indexer.commit(
        incident_id=args.incident_id,
        root_cause=args.root_cause,
        fix=args.fix,
    )
    indexer.update_incident_status(incident_store, args.incident_id)
    print(f"Postmortem committed for incident_id={args.incident_id}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="tracelog")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # tracelog index <dump_dir>
    index_parser = subparsers.add_parser("index", help="Index dump files into the vector store")
    index_parser.add_argument("dump_dir", help="Directory containing .log dump files")

    # tracelog diagnose <dump_file>
    diagnose_parser = subparsers.add_parser("diagnose", help="Diagnose a dump file using RAG")
    diagnose_parser.add_argument("dump_file", help="Path to the .log dump file to diagnose")
    diagnose_parser.add_argument("--top-k", type=int, default=5, help="Number of similar chunks to retrieve")

    # tracelog postmortem commit
    pm_parser = subparsers.add_parser("postmortem", help="Postmortem management")
    pm_sub = pm_parser.add_subparsers(dest="pm_command", required=True)

    commit_parser = pm_sub.add_parser("commit", help="Commit a postmortem for a resolved incident")
    commit_parser.add_argument("--incident-id", required=True, help='Incident ID (e.g. "error.log::0")')
    commit_parser.add_argument("--root-cause", required=True, help="Root cause description")
    commit_parser.add_argument("--fix", required=True, help="Fix description")

    search_parser = pm_sub.add_parser("search", help="Search past postmortems by fix similarity")
    search_parser.add_argument("--query", required=True, help="Free-text query (e.g. 'string to int cast failure')")
    search_parser.add_argument("--top-k", type=int, default=5, help="Number of results to return")

    args = parser.parse_args()

    if args.command == "index":
        _cmd_index(args)
    elif args.command == "diagnose":
        _cmd_diagnose(args)
    elif args.command == "postmortem":
        if args.pm_command == "commit":
            _cmd_postmortem_commit(args)
        elif args.pm_command == "search":
            _cmd_postmortem_search(args)


if __name__ == "__main__":
    main()
