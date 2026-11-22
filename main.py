import argparse
import os
import time

from clipboard_win import get_clipboard_text
from context import capture_context, get_git_branch
from store import ClipStore
from tui import TimeTravelTUI


def cmd_tui(store: ClipStore) -> None:
    cur = get_clipboard_text()
    if cur:
        ctx = capture_context()
        store.add(
            content=cur,
            cwd=ctx["cwd"],
            git_branch=ctx["git_branch"],
            exit_code=None,
        )
    TimeTravelTUI(store).run()


def cmd_record(store: ClipStore, exit_code: int | None) -> None:
    cur = get_clipboard_text()
    if not cur:
        return
    ctx = capture_context(exit_code=exit_code)
    store.add(
        content=cur,
        cwd=ctx["cwd"],
        git_branch=ctx["git_branch"],
        exit_code=ctx["exit_code"],
    )


def cmd_watch(store: ClipStore, interval: float) -> None:
    print("Watching clipboard (Ctrl+C to stop)...")
    last_seen = None
    try:
        while True:
            cur = get_clipboard_text()
            if cur and cur != last_seen:
                last_seen = cur
                branch = get_git_branch()
                cid = store.add(
                    content=cur,
                    cwd=os.getcwd(),
                    git_branch=branch,
                    exit_code=None,
                )
                if cid:
                    print(f"[#{cid}] Captured ({branch or 'no-branch'}): {cur[:60]!r}")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nStopped.")


def cmd_list(store: ClipStore, query: str, limit: int) -> None:
    entries = store.list_entries(query=query, limit=limit)
    for e in entries:
        pin = "*" if e.pinned else " "
        branch = f"[{e.git_branch}]" if e.git_branch else ""
        print(f"{pin} #{e.id:<4} {e.short_time} {branch:<14} {e.preview}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ttc",
        description="Local-First Time-Travel Clipboard for Terminals",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("tui", help="Launch interactive keyboard + mouse TUI (default)")

    rec = sub.add_parser("record", help="Record current clipboard with terminal context")
    rec.add_argument("--exit-code", type=int, default=None, help="Last command exit code")

    watch = sub.add_parser("watch", help="Run headless clipboard watcher")
    watch.add_argument("--interval", type=float, default=0.6, help="Poll interval in seconds")

    ls = sub.add_parser("list", help="List recent clipboard entries")
    ls.add_argument("--query", default="", help="Filter text")
    ls.add_argument("--limit", type=int, default=20, help="Max entries")

    args = parser.parse_args()
    store = ClipStore()

    if args.command in (None, "tui"):
        cmd_tui(store)
    elif args.command == "record":
        cmd_record(store, args.exit_code)
    elif args.command == "watch":
        cmd_watch(store, args.interval)
    elif args.command == "list":
        cmd_list(store, args.query, args.limit)


if __name__ == "__main__":
    main()
