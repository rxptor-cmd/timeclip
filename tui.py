import ctypes
from ctypes import wintypes
import os
import re
import shutil
import sys
import threading
import time
from typing import List, Optional, Tuple

from clipboard_win import get_clipboard_text, set_clipboard_text
from context import get_git_branch
from store import ClipEntry, ClipStore

STD_INPUT_HANDLE = -10
STD_OUTPUT_HANDLE = -11

ENABLE_ECHO_INPUT = 0x0004
ENABLE_LINE_INPUT = 0x0002
ENABLE_PROCESSED_INPUT = 0x0001
ENABLE_MOUSE_INPUT = 0x0010
ENABLE_WINDOW_INPUT = 0x0008
ENABLE_EXTENDED_FLAGS = 0x0080
ENABLE_VIRTUAL_TERMINAL_INPUT = 0x0200
ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004

SGR_MOUSE_RE = re.compile(r"^\x1b\[<(\d+);(\d+);(\d+)([Mm])$")

# ANSI helpers
RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"
REVERSE = "\x1b[7m"
FG_CYAN = "\x1b[36m"
FG_GREEN = "\x1b[32m"
FG_RED = "\x1b[31m"
FG_YELLOW = "\x1b[33m"
FG_GRAY = "\x1b[90m"
FG_WHITE = "\x1b[97m"
BG_BLUE = "\x1b[44m"
BG_DARK = "\x1b[48;5;236m"


class ConsoleModeGuard:
    def __init__(self) -> None:
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.h_in = self.kernel32.GetStdHandle(STD_INPUT_HANDLE)
        self.h_out = self.kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
        self.orig_in = wintypes.DWORD()
        self.orig_out = wintypes.DWORD()

    def __enter__(self) -> "ConsoleModeGuard":
        self.kernel32.GetConsoleMode(self.h_in, ctypes.byref(self.orig_in))
        self.kernel32.GetConsoleMode(self.h_out, ctypes.byref(self.orig_out))

        new_in = (
            (self.orig_in.value & ~(ENABLE_ECHO_INPUT | ENABLE_LINE_INPUT | ENABLE_PROCESSED_INPUT))
            | ENABLE_MOUSE_INPUT
            | ENABLE_EXTENDED_FLAGS
            | ENABLE_VIRTUAL_TERMINAL_INPUT
        )
        new_out = self.orig_out.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING
        self.kernel32.SetConsoleMode(self.h_in, new_in)
        self.kernel32.SetConsoleMode(self.h_out, new_out)

        sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h")
        sys.stdout.flush()
        return self

    def __exit__(self, *args) -> None:
        sys.stdout.write("\x1b[?1006l\x1b[?1000l\x1b[?25h\x1b[?1049l")
        sys.stdout.flush()
        self.kernel32.SetConsoleMode(self.h_in, self.orig_in)
        self.kernel32.SetConsoleMode(self.h_out, self.orig_out)


def read_key_or_mouse(timeout: float = 0.1) -> Optional[str]:
    """Read a single key or VT/SGR mouse sequence from stdin on Windows."""
    import msvcrt

    deadline = time.monotonic() + timeout
    while not msvcrt.kbhit():
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.01)

    ch = msvcrt.getwch()
    if ch == "\x1b":
        seq = ch
        # Drain any immediately available escape sequence chars
        t0 = time.monotonic()
        while time.monotonic() - t0 < 0.02:
            if msvcrt.kbhit():
                seq += msvcrt.getwch()
                if seq[-1].isalpha() or seq[-1] in ("~", "M", "m"):
                    if not (seq.startswith("\x1b[<") and seq[-1] not in ("M", "m")):
                        break
            else:
                time.sleep(0.002)
        return seq
    return ch


def clip_str(s: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(s) <= width:
        return s.ljust(width)
    if width == 1:
        return s[:1]
    return s[: width - 1] + "…"


class TimeTravelTUI:
    def __init__(self, store: ClipStore) -> None:
        self.store = store
        self.entries: List[ClipEntry] = []
        self.selected_idx: int = 0
        self.scroll_offset: int = 0
        self.query: str = ""
        self.search_mode: bool = False
        self.filter_mode: str = "all"  # "all" | "pinned" | "branch"
        self.current_branch: str = get_git_branch()
        self.status_msg: str = "Ready. Watching clipboard…"
        self.running: bool = True
        self.last_click_time: float = 0.0
        self.last_click_idx: int = -1
        self._lock = threading.Lock()

        # Clickable UI hitboxes: (y, x1, x2, action_name)
        self.hitboxes: List[Tuple[int, int, int, str]] = []

    def refresh_entries(self) -> None:
        pinned_only = self.filter_mode == "pinned"
        branch = self.current_branch if self.filter_mode == "branch" else ""
        self.entries = self.store.list_entries(
            query=self.query,
            pinned_only=pinned_only,
            branch_filter=branch,
        )
        if not self.entries:
            self.selected_idx = 0
            self.scroll_offset = 0
        else:
            self.selected_idx = max(0, min(self.selected_idx, len(self.entries) - 1))

    def _watch_clipboard(self) -> None:
        last_seen = get_clipboard_text()
        while self.running:
            time.sleep(0.6)
            try:
                cur = get_clipboard_text()
                if cur and cur != last_seen:
                    last_seen = cur
                    branch = get_git_branch()
                    self.store.add(
                        content=cur,
                        cwd=os.getcwd(),
                        git_branch=branch,
                        exit_code=None,
                    )
                    with self._lock:
                        self.refresh_entries()
                        self.status_msg = "Captured new clipboard entry"
            except Exception:
                pass

    def copy_selected(self) -> None:
        if not self.entries:
            return
        entry = self.entries[self.selected_idx]
        if set_clipboard_text(entry.content):
            self.status_msg = f"Copied #{entry.id} to clipboard"
        else:
            self.status_msg = "Failed to write to clipboard"

    def toggle_pin_selected(self) -> None:
        if not self.entries:
            return
        entry = self.entries[self.selected_idx]
        self.store.toggle_pin(entry.id)
        self.refresh_entries()
        self.status_msg = f"Toggled pin on #{entry.id}"

    def delete_selected(self) -> None:
        if not self.entries:
            return
        entry = self.entries[self.selected_idx]
        self.store.delete(entry.id)
        self.refresh_entries()
        self.status_msg = f"Deleted #{entry.id}"

    def snapshot_now(self) -> None:
        cur = get_clipboard_text()
        if not cur:
            self.status_msg = "Clipboard is empty"
            return
        cid = self.store.add(
            content=cur,
            cwd=os.getcwd(),
            git_branch=get_git_branch(),
            exit_code=0,
            dedupe_latest=False,
        )
        self.refresh_entries()
        self.status_msg = f"Snapshot saved (#{cid})"

    def render(self) -> None:
        cols, rows = shutil.get_terminal_size((100, 30))
        cols = max(60, cols)
        rows = max(14, rows)

        self.hitboxes = []
        buf: List[str] = ["\x1b[H"]

        # Row 1: Header + Filter Tabs
        title = f" {BOLD}{FG_CYAN}TIME-TRAVEL CLIPBOARD{RESET} "
        tabs = []
        x_cursor = 24
        for mode, label in [("all", "All"), ("pinned", "Pinned"), ("branch", "Branch")]:
            tag = f"[{label}]"
            if self.filter_mode == mode:
                tabs.append(f"{BG_BLUE}{FG_WHITE}{BOLD}{tag}{RESET}")
            else:
                tabs.append(f"{FG_GRAY}{tag}{RESET}")
            self.hitboxes.append((1, x_cursor, x_cursor + len(tag) - 1, f"filter:{mode}"))
            x_cursor += len(tag) + 1

        snap_btn = "[+ Snap]"
        snap_x = cols - len(snap_btn) - 1
        self.hitboxes.append((1, snap_x, snap_x + len(snap_btn) - 1, "snap"))

        header_left = title + " ".join(tabs)
        buf.append(f"\x1b[1;1H\x1b[2K{header_left}")
        buf.append(f"\x1b[1;{snap_x}H{FG_GREEN}{BOLD}{snap_btn}{RESET}")

        # Row 2: Search bar
        search_prefix = " / Search: " if self.search_mode else " / Search (click or press /): "
        search_val = self.query + ("_" if self.search_mode else "")
        search_line = f"{FG_YELLOW}{search_prefix}{RESET}{search_val}"
        self.hitboxes.append((2, 1, cols, "search"))
        buf.append(f"\x1b[2;1H\x1b[2K{search_line}")

        # Row 3: Divider
        left_w = max(28, int(cols * 0.45))
        right_w = cols - left_w - 1
        buf.append(f"\x1b[3;1H{FG_GRAY}{'─' * left_w}┬{'─' * right_w}{RESET}")

        body_rows = rows - 5  # rows 4 .. rows-2
        if self.selected_idx < self.scroll_offset:
            self.scroll_offset = self.selected_idx
        elif self.selected_idx >= self.scroll_offset + body_rows:
            self.scroll_offset = self.selected_idx - body_rows + 1

        selected_entry: Optional[ClipEntry] = (
            self.entries[self.selected_idx] if self.entries else None
        )

        # Prepare right-pane lines
        right_lines: List[str] = []
        if selected_entry:
            ec = selected_entry.exit_code
            ec_str = f"exit:{ec}" if ec is not None else "exit:-"
            right_lines.append(
                f"{BOLD}#{selected_entry.id}{RESET}  {FG_GRAY}{selected_entry.short_date} {selected_entry.short_time}{RESET}"
            )
            right_lines.append(f"{FG_CYAN}Dir:{RESET}    {selected_entry.cwd or '-'}")
            right_lines.append(
                f"{FG_CYAN}Branch:{RESET} {selected_entry.git_branch or '-'}   {FG_CYAN}Status:{RESET} {ec_str}"
            )
            # Action buttons on right pane row 4 (screen row 7)
            btn_row_screen = 7
            rx = left_w + 3
            copy_lbl = "[Copy (Enter)]"
            pin_lbl = "[Unpin (p)]" if selected_entry.pinned else "[Pin (p)]"
            del_lbl = "[Del (d)]"
            self.hitboxes.append((btn_row_screen, rx, rx + len(copy_lbl) - 1, "copy"))
            rx2 = rx + len(copy_lbl) + 2
            self.hitboxes.append((btn_row_screen, rx2, rx2 + len(pin_lbl) - 1, "pin"))
            rx3 = rx2 + len(pin_lbl) + 2
            self.hitboxes.append((btn_row_screen, rx3, rx3 + len(del_lbl) - 1, "delete"))

            right_lines.append(
                f"{FG_GREEN}{copy_lbl}{RESET}  {FG_YELLOW}{pin_lbl}{RESET}  {FG_RED}{del_lbl}{RESET}"
            )
            right_lines.append(f"{FG_GRAY}{'─' * max(10, right_w - 2)}{RESET}")
            for line in selected_entry.content.splitlines():
                right_lines.append(line)
        else:
            right_lines.append(f"{FG_GRAY}No clipboard entries match.{RESET}")
            right_lines.append(f"{FG_GRAY}Copy anything or click [+ Snap].{RESET}")

        # Render body rows
        for i in range(body_rows):
            screen_y = 4 + i
            entry_idx = self.scroll_offset + i

            if entry_idx < len(self.entries):
                e = self.entries[entry_idx]
                pin_mark = "★" if e.pinned else " "
                branch_tag = f"[{e.git_branch[:10]}]" if e.git_branch else ""
                meta = f"{pin_mark}{e.short_time} {branch_tag}".strip()
                avail = max(6, left_w - len(meta) - 3)
                row_text = f" {meta} {clip_str(e.preview, avail)}"
                row_text = clip_str(row_text, left_w)
                if entry_idx == self.selected_idx:
                    left_cell = f"{BG_BLUE}{FG_WHITE}{BOLD}{row_text}{RESET}"
                else:
                    left_cell = row_text
                self.hitboxes.append((screen_y, 1, left_w, f"select:{entry_idx}"))
            else:
                left_cell = " " * left_w

            r_text = right_lines[i] if i < len(right_lines) else ""
            # Truncate plain right text only if it has no ANSI escapes
            if "\x1b[" not in r_text and len(r_text) > right_w - 2:
                r_text = r_text[: right_w - 3] + "…"

            buf.append(f"\x1b[{screen_y};1H\x1b[2K{left_cell}{FG_GRAY}│{RESET} {r_text}")

        # Bottom divider & status bar
        buf.append(f"\x1b[{rows - 1};1H{FG_GRAY}{'─' * left_w}┴{'─' * right_w}{RESET}")
        hints = " ↑↓/j/k:Nav  Enter:Copy  /:Search  Tab:Filter  p:Pin  d:Del  q:Quit | Mouse: Click/Wheel"
        status = f" {FG_CYAN}{self.status_msg}{RESET} |{FG_GRAY}{hints}{RESET}"
        buf.append(f"\x1b[{rows};1H\x1b[2K{status}")

        sys.stdout.write("".join(buf))
        sys.stdout.flush()

    def handle_mouse(self, seq: str) -> None:
        m = SGR_MOUSE_RE.match(seq)
        if not m:
            return
        btn, x, y, kind = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)

        # Mouse wheel
        if btn == 64:  # Wheel up
            self.selected_idx = max(0, self.selected_idx - 1)
            return
        if btn == 65:  # Wheel down
            if self.entries:
                self.selected_idx = min(len(self.entries) - 1, self.selected_idx + 1)
            return

        if kind != "M" or btn != 0:
            return

        for hy, hx1, hx2, action in self.hitboxes:
            if y == hy and hx1 <= x <= hx2:
                if action == "search":
                    self.search_mode = True
                elif action == "snap":
                    self.snapshot_now()
                elif action == "copy":
                    self.copy_selected()
                elif action == "pin":
                    self.toggle_pin_selected()
                elif action == "delete":
                    self.delete_selected()
                elif action.startswith("filter:"):
                    self.filter_mode = action.split(":", 1)[1]
                    self.refresh_entries()
                elif action.startswith("select:"):
                    self.search_mode = False
                    idx = int(action.split(":", 1)[1])
                    now = time.monotonic()
                    if idx == self.last_click_idx and (now - self.last_click_time) < 0.4:
                        self.selected_idx = idx
                        self.copy_selected()
                    else:
                        self.selected_idx = idx
                    self.last_click_idx = idx
                    self.last_click_time = now
                return

    def handle_key(self, key: str) -> None:
        if key.startswith("\x1b[<"):
            self.handle_mouse(key)
            return

        if self.search_mode:
            if key in ("\r", "\n", "\x1b"):
                self.search_mode = False
            elif key in ("\x08", "\x7f"):
                self.query = self.query[:-1]
                self.refresh_entries()
            elif len(key) == 1 and key.isprintable():
                self.query += key
                self.refresh_entries()
            return

        if key in ("q", "\x1b"):
            self.running = False
        elif key in ("\x1b[A", "k"):
            self.selected_idx = max(0, self.selected_idx - 1)
        elif key in ("\x1b[B", "j"):
            if self.entries:
                self.selected_idx = min(len(self.entries) - 1, self.selected_idx + 1)
        elif key in ("\r", "\n"):
            self.copy_selected()
        elif key == "/":
            self.search_mode = True
        elif key == "\t":
            order = ["all", "pinned", "branch"]
            self.filter_mode = order[(order.index(self.filter_mode) + 1) % len(order)]
            self.refresh_entries()
        elif key == "p":
            self.toggle_pin_selected()
        elif key == "d":
            self.delete_selected()
        elif key == "s":
            self.snapshot_now()

    def run(self) -> None:
        self.refresh_entries()
        watcher = threading.Thread(target=self._watch_clipboard, daemon=True)
        watcher.start()

        with ConsoleModeGuard():
            while self.running:
                with self._lock:
                    self.render()
                ev = read_key_or_mouse(timeout=0.25)
                if ev is not None:
                    with self._lock:
                        self.handle_key(ev)
