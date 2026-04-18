# LogiBox

A console-based logical sandbox. Define variables, build boolean
expressions with AND/OR/XOR/NAND/NOR/XNOR/IMPLY/NIMPLY, save and
load your workspace.

## Download

Grab the latest build from the [](/releases).
Extract the zip anywhere, then double-click `LogiBox.exe`.

Windows may show a SmartScreen warning the first time
("Windows protected your PC"). Click **More info** → **Run anyway**.
This happens for any unsigned executable and is not specific to LogiBox.

## Commands

Type `help` inside LogiBox to access

## Building from source

Requires Python 3.8+. On Windows, also install `windows-curses`.

    pip install pyinstaller windows-curses
    python -m PyInstaller --onedir --console --name LogiBox --noupx --clean logibox.py

The distributable folder ends up in `dist/LogiBox/`.
