# LogiBox

A console-based virtual sandbox environment that executes logic procedures.
This program allows users to practice experimental logic statements and
build standalone complex computational logic architectures.

Define variables, build boolean
expressions with AND/OR/XOR/NAND/NOR/XNOR/IMPLY/NIMPLY, save and
load your workspace.

## Download

Grab the latest build from [Releases Page](https://github.com/Gecons/logibox/releases).
Extract the zip anywhere, open the "LogiBox" folder, then double-click `LogiBox.exe`.
Ignore the "_internal" folder.
There are loadable pre-written samples in the "saves" folder.
Use the `load` command in LogiBox to load saves.

## First-run security warnings

LogiBox is not code-signed (signing certificates cost hundreds of dollars per
year, which isn't reasonable for a small open-source project). All major
operating systems will show a warning the first time you run an unsigned app.
This is normal and not specific to LogiBox.

**Windows:** SmartScreen may say "Windows protected your PC". Click
**More info**, then **Run anyway**. Windows remembers your choice for
future launches.

**macOS:** Gatekeeper may say "Cannot be opened because the developer cannot
be verified" or "macOS cannot verify that this app is free from malware".
Right-click (or Control-click) `LogiBox` in Finder and choose **Open**, the
warning then offers an Open button that plain double-click does not. If that
still refuses, go to **System Settings → Privacy & Security**, scroll down,
and click **Open Anyway** next to the LogiBox entry. Once allowed, future
launches work normally.

**Linux:** No security prompt by default. If the file refuses to run,
you may need to mark it executable first:

    chmod +x LogiBox

Some desktop environments (mainly GNOME on certain distros) require this
before double-click works. Running from a terminal as `./LogiBox` always works.

This is an open-source project. Feel free to inspect the source in
[`logibox.py`](https://github.com/Gecons/logibox)

## Help

Type `help` inside LogiBox to access the help menu.
