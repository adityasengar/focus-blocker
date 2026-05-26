# Focus

Unblockable site & app blocker for macOS. Blocks websites via `/etc/hosts` and force-quits apps via a LaunchDaemon.

## Install

```bash
git clone https://github.com/adityasengar/focus-blocker.git
cd focus-blocker
pip install -e .
cp config.example.json ~/.focus/config.json  # pre-configured block lists + presets
focus install  # sets up daemon, requires sudo
```

## Quick Start

```bash
focus start deepwork           # block everything for 2h
focus start deepwork --for 4h  # override duration
focus block social news --for 3h  # block specific lists
focus status                   # see what's active
focus cancel --force           # emergency cancel all
```

## Presets

Pre-configured combos of lists with a default duration.

```bash
focus preset list                                    # view presets
focus preset add work social news --for 3h           # create
focus preset remove work                             # delete
focus start work                                     # activate
```

Included presets: `deepwork` (all lists, 2h), `casual` (social, 1h), `lockdown` (all except apps, 4h)

## Pomodoro

Work/break cycles. Default: 25m work, 5m break, 15m long break every 4th.

```bash
focus pomodoro deepwork                              # 4 sessions, standard
focus pomodoro deepwork --sessions 6                 # more sessions
focus pomodoro deepwork --work 50m --break 10m       # custom timing
```

Sites are blocked during work, accessible during breaks.

## Schedules

Recurring or one-time blocks that run automatically.

```bash
focus schedule add social --weekdays 9:00-17:00      # Mon-Fri
focus schedule add entertainment --weekends 10:00-18:00
focus schedule add social --daily 22:00-06:00        # overnight works
focus schedule add news --once "2026-06-01 14:00" --for 3h
focus schedule list                                  # view all
focus schedule remove <id> --force                   # remove (--force if active)
```

## Managing Lists

```bash
focus lists                              # view all lists + apps
focus list add social snapchat.com       # add a site
focus list drop social snapchat.com      # remove a site
focus list edit social                   # bulk edit in $EDITOR
focus list remove mylist                 # delete entire list
```

Subdomains: `www.` is auto-blocked. Add others explicitly (e.g., `old.reddit.com`).

## App Blocking

Force-quit apps when a list is blocked. The daemon kills them every 15 seconds.

```bash
focus app list                           # see configured apps
focus app add email WhatsApp Slack       # kill these when email is blocked
focus app remove email WhatsApp          # stop killing WhatsApp
```

## Block Lists (included in config.example.json)

| List | Sites | Apps killed |
|------|-------|-------------|
| `social` | facebook, reddit, twitter, instagram, linkedin, +6 | Discord |
| `news` | cnn, bbc, nytimes, wsj, +29 | - |
| `entertainment` | youtube, netflix, twitch, hulu, +3 | - |
| `email` | gmail, outlook, slack, whatsapp, +4 | WhatsApp, Slack |
| `apps` | whatsapp.com | Mail, WhatsApp |

## In-App Help

```bash
focus guide     # full cheatsheet
focus --help    # list all commands
focus <cmd> --help  # help for a specific command
```

## How It Works

- **Site blocking**: Adds entries to `/etc/hosts` (127.0.0.1 + ::1) to redirect blocked domains
- **App killing**: Daemon runs `killall <AppName>` every 15 seconds for configured apps
- **Enforcement**: A root-level LaunchDaemon re-applies blocks if `/etc/hosts` is tampered with, runs every 15s + triggers on file changes
- **Config**: `~/.focus/config.json` (user-editable, no sudo needed)
- **State**: `/usr/local/etc/focus/state.json` (root-owned, tracks active blocks + schedules)
- **Daemon**: `/usr/local/libexec/focus/focus_daemon.py` (system Python, stdlib only)

## After Code Changes

Re-run `focus install` to update the daemon script. This is safe to run multiple times.

## Uninstall

```bash
focus uninstall  # removes daemon (requires sudo, fails if blocks active)
pip uninstall focus
# Optionally: rm -rf ~/.focus /usr/local/etc/focus
```
