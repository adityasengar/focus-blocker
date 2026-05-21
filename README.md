# Focus

Unblockable site & app blocker for macOS. Blocks websites via `/etc/hosts` and force-quits apps via a LaunchDaemon.

## Install

```bash
git clone https://github.com/adityasengar/focus-blocker.git
cd focus-blocker
pip install -e .
focus install  # sets up daemon, requires sudo

# Copy the pre-configured block lists + presets
cp config.example.json ~/.focus/config.json
```

## Quick Start

```bash
# Block everything for 2 hours
focus start deepwork

# Block specific lists
focus block social news --for 3h

# Pomodoro (25m work / 5m break)
focus pomodoro deepwork

# Check status
focus status

# Cancel all blocks (emergency)
focus cancel --force
```

## Full Guide

```bash
focus guide
```

## How It Works

- **Site blocking**: Adds entries to `/etc/hosts` (127.0.0.1 + ::1) to redirect blocked domains
- **App killing**: Daemon force-quits configured apps every 15 seconds
- **Enforcement**: A root-level LaunchDaemon re-applies blocks if `/etc/hosts` is tampered with
- **Config**: `~/.focus/config.json` (user-editable, no sudo)
- **State**: `/usr/local/etc/focus/state.json` (root-owned)

## After Code Changes

Re-run `focus install` to update the daemon.
