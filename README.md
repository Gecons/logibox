# LogiBox

A console-based virtual sandbox environment that executes logic procedures.
This program allows users to practice experimental logic statements and
build standalone complex computational logic architectures.

Define variables, build boolean
expressions with AND/OR/XOR/NAND/NOR/XNOR/IMPLY/NIMPLY, save and
load your workspace.

## Download

Grab the latest build from [Releases Page](https://github.com/Gecons/logibox/releases).
Extract the zip anywhere, then double-click `LogiBox.exe`.

Windows may show a SmartScreen warning the first time
("Windows protected your PC"). Click **More info** → **Run anyway**.
This happens for any unsigned executable and is not specific to LogiBox.
This is an open-source project. Feel free to check the source code
in `logibox.py` which is shared in the [Repository Page](https://github.com/Gecons/logibox).

## Commands

Type `help` inside LogiBox to access

## Building from source

Requires Python 3.8+. On Windows, also install `windows-curses`.

    pip install pyinstaller windows-curses
    python -m PyInstaller --onedir --console --name LogiBox --noupx --clean logibox.py

The distributable folder ends up in `dist/LogiBox/`.
