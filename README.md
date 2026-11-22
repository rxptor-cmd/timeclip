# TimeClip (`ttc`)

A local-first **Time-Travel Clipboard** for terminals with a keyboard- and mouse-accessible TUI.  
Every clipboard entry is stored locally in SQLite along with the **working directory**, **Git branch**, and **exit code** active when it was captured.

## Features

- **Context-Aware History:** Captures clipboard text alongside `cwd`, `git_branch`, and `exit_code`.
- **Collapsible Folders:** Group entries by `date`, `week`, `branch`, or `none` (`g` key or click `[Group: ...]`).
- **Keyboard & Mouse TUI:** Full terminal UI with SGR mouse support (click, double-click to copy, scroll wheel) and Vim/arrow-key navigation.
- **Instant Search & Filters:** Search across content, branch, or directory (`/`), and filter by `All`, `Pinned`, or current `Branch` (`Tab`).
- **Zero External Dependencies:** Built with Python's standard library and native Win32 clipboard/console APIs.

## Installation

```powershell
pip install -e .
```

Make sure Python's `Scripts` directory is on your `PATH`, or run `ttc.cmd` directly.

## Usage

```powershell
ttc                              # Launch interactive TUI (watches clipboard while open)
ttc watch                        # Run headless background clipboard watcher
ttc list                         # Print recent entries in plain text
ttc record --exit-code $LASTEXITCODE  # Record clipboard + terminal context
```

### Keyboard Shortcuts

| Key | Action |
| --- | --- |
| `↑` / `↓` or `j` / `k` | Navigate entries and folders |
| `Enter` | Copy selected entry (or toggle folder) |
| `/` | Search content, branch, or directory |
| `Tab` | Cycle filter (`All` → `Pinned` → `Branch`) |
| `g` | Cycle folder grouping (`date` → `week` → `branch` → `none`) |
| `p` | Pin / unpin entry |
| `d` | Delete entry |
| `s` | Snapshot current clipboard immediately |
| `q` or `Esc` | Quit |

### Mouse Controls

- **Click** a row to inspect it; **double-click** to copy it to the clipboard.
- **Click** a folder header (`▾` / `▸`) to collapse or expand it.
- **Scroll wheel** to move up/down.
- **Click** header tabs (`[All]`, `[Pinned]`, `[Branch]`, `[Group: ...]`, `[+ Snap]`), the search bar, or `[Copy]` / `[Pin]` / `[Del]`.
