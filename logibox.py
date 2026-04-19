"""
LogiBox - A console-based logical sandbox.
LogiBox is a virtual sandbox environment to perform experimental logical operations:
- This is structured in a way that allows the user to build standalone complex computational logic architectures.

A two-pane terminal UI:
  - Workspace (top): displays command history, results, and state
  - Command line (bottom): where you type commands
"""

import curses
import os
import re
import subprocess
import sys
from collections import namedtuple


# == LOGIC ENGINE ==
Token = namedtuple("Token", "type value")

WORD_OPERATORS = {"AND", "OR", "XOR", "NAND", "NOR", "XNOR", "IMPLY", "NIMPLY"}

BINARY_OPS = {
    "AND":    lambda a, b: a and b,
    "OR":     lambda a, b: a or b,
    "XOR":    lambda a, b: bool(a) != bool(b),
    "NAND":   lambda a, b: not (a and b),
    "NOR":    lambda a, b: not (a or b),
    "XNOR":   lambda a, b: bool(a) == bool(b),
    "IMPLY":  lambda a, b: (not a) or b,
    "NIMPLY": lambda a, b: a and not b,
}


class LogicEngine:
    """
    Boolean expression engine. Variables store the AST they were assigned,
    not a cached value, so every lookup re-evaluates against current state.

    Node shapes:
        ("LIT", 0|1)
        ("VAR", name)
        ("NOT", node)
        (<OP>, left, right)        # OP is any key of BINARY_OPS
        ("ASSIGN", name, node)
    """

    def __init__(self):
        self.variables = {}
        self.sources = {}
        self._evaluating = set()

    def evaluate(self, source):
        tokens = self.tokenize(source)
        if len(tokens) == 1:
            return ("empty",)
        ast = self.parse(tokens)

        if ast[0] == "ASSIGN":
            name, expr = ast[1], ast[2]
            if self._creates_cycle(name, expr):
                raise RuntimeError(
                    f"cyclic dependency: {name!r} would reference itself"
                )
            self.variables[name] = expr
            self.sources[name] = self._stringify(expr)
            try:
                return ("assignment", name, self._eval(expr))
            except (NameError, RuntimeError):
                return ("assignment", name, None)

        return ("value", self._eval(ast))

    def lookup(self, name):
        if name not in self.variables:
            raise NameError(f"{name!r} is not defined")
        return self._eval(("VAR", name))

    def export(self):
        return [f"{name} = {self.sources[name]}" for name in self.variables]

    def import_state(self, lines):
        fresh = LogicEngine()
        for i, line in enumerate(lines, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                result = fresh.evaluate(line)
            except Exception as e:
                raise ValueError(f"line {i}: {e}")
            if result[0] != "assignment":
                raise ValueError(f"line {i}: not an assignment")
        self.variables = fresh.variables
        self.sources = fresh.sources

    def _creates_cycle(self, name, node):
        seen = set()

        def walk(n):
            tag = n[0]
            if tag == "VAR":
                var = n[1]
                if var == name:
                    return True
                if var in seen:
                    return False
                seen.add(var)
                if var in self.variables:
                    return walk(self.variables[var])
                return False
            if tag == "NOT":
                return walk(n[1])
            if tag in BINARY_OPS:
                return walk(n[1]) or walk(n[2])
            return False

        return walk(node)

    def tokenize(self, source):
        tokens = []
        i, n = 0, len(source)

        while i < n:
            c = source[i]

            if c.isspace():
                i += 1
                continue

            if c == "(": tokens.append(Token("LPAREN", "(")); i += 1; continue
            if c == ")": tokens.append(Token("RPAREN", ")")); i += 1; continue
            if c == "=": tokens.append(Token("EQ",     "=")); i += 1; continue
            if c == "*": tokens.append(Token("STAR",   "*")); i += 1; continue

            if c in "01":
                tokens.append(Token("LIT", int(c)))
                i += 1
                continue

            if c.isalpha() or c == "_":
                j = i
                while j < n and (source[j].isalnum() or source[j] == "_"):
                    j += 1
                word = source[i:j]
                upper = word.upper()
                if upper in WORD_OPERATORS:
                    tokens.append(Token(upper, upper))
                else:
                    tokens.append(Token("IDENT", word))
                i = j
                continue

            raise SyntaxError(f"unexpected character {c!r} at position {i}")

        tokens.append(Token("EOF", None))
        return tokens

    # Grammar (lowest to highest precedence):
    #   statement   := IDENT '=' expression | expression
    #   imply_expr  := or_expr   (('IMPLY'|'NIMPLY')         or_expr)*
    #   or_expr     := and_expr  (('OR'|'NOR'|'XOR'|'XNOR')  and_expr)*
    #   and_expr    := not_expr  (('AND'|'NAND')             not_expr)*
    #   not_expr    := primary ('*')*
    #   primary     := LIT | IDENT | '(' expression ')'
    def parse(self, tokens):
        self._tokens = tokens
        self._pos = 0
        node = self._parse_statement()
        self._expect("EOF")
        return node

    def _peek(self):    return self._tokens[self._pos]
    def _advance(self):
        tok = self._tokens[self._pos]; self._pos += 1; return tok
    def _accept(self, *types):
        return self._advance() if self._peek().type in types else None
    def _expect(self, type_):
        tok = self._peek()
        if tok.type != type_:
            raise SyntaxError(f"expected {type_} but got {tok.type} ({tok.value!r})")
        return self._advance()

    def _parse_statement(self):
        if (self._peek().type == "IDENT"
                and self._tokens[self._pos + 1].type == "EQ"):
            name = self._advance().value
            self._advance()
            return ("ASSIGN", name, self._parse_expression())
        return self._parse_expression()

    def _parse_expression(self): return self._parse_imply()

    def _parse_imply(self):
        node = self._parse_or()
        while True:
            op = self._accept("IMPLY", "NIMPLY")
            if not op: return node
            node = (op.type, node, self._parse_or())

    def _parse_or(self):
        node = self._parse_and()
        while True:
            op = self._accept("OR", "NOR", "XOR", "XNOR")
            if not op: return node
            node = (op.type, node, self._parse_and())

    def _parse_and(self):
        node = self._parse_not()
        while True:
            op = self._accept("AND", "NAND")
            if not op: return node
            node = (op.type, node, self._parse_not())

    def _parse_not(self):
        node = self._parse_primary()
        while self._accept("STAR"):
            node = ("NOT", node)
        return node

    def _parse_primary(self):
        tok = self._peek()
        if tok.type == "LIT":
            self._advance()
            return ("LIT", tok.value)
        if tok.type == "IDENT":
            self._advance()
            return ("VAR", tok.value)
        if tok.type == "LPAREN":
            self._advance()
            node = self._parse_expression()
            self._expect("RPAREN")
            return node
        raise SyntaxError(
            f"unexpected {tok.type} ({tok.value!r}); expected value, variable, or '('"
        )

    def _eval(self, node):
        tag = node[0]

        if tag == "LIT":
            return bool(node[1])

        if tag == "VAR":
            name = node[1]
            if name not in self.variables:
                raise NameError(f"{name!r} is not defined")
            if name in self._evaluating:
                raise RuntimeError(f"cyclic dependency at {name!r}")
            self._evaluating.add(name)
            try:
                return self._eval(self.variables[name])
            finally:
                self._evaluating.discard(name)

        if tag == "NOT":
            return not self._eval(node[1])

        if tag in BINARY_OPS:
            return bool(BINARY_OPS[tag](self._eval(node[1]), self._eval(node[2])))

        raise RuntimeError(f"unknown AST node: {tag}")

    def _stringify(self, node):
        tag = node[0]
        if tag == "LIT": return str(node[1])
        if tag == "VAR": return node[1]
        if tag == "NOT":
            inner = self._stringify(node[1])
            if node[1][0] in ("LIT", "VAR", "NOT"):
                return f"{inner}*"
            return f"({inner})*"
        if tag in BINARY_OPS:
            return f"({self._stringify(node[1])} {tag} {self._stringify(node[2])})"
        return "?"


# == CONSOLE WINDOW ==
SAVE_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]+$")
PREFIX_RE    = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
BITS_RE      = re.compile(r"^[01]+$")

WRAP_INDENT = "  "  # 2-space prefix for continuation rows

# Ctrl-key codes differ between Windows (windows-curses) and Unix (ncurses).
# Windows: regular Backspace = 8, Ctrl+Backspace = 127, Ctrl+(Left/Right) = 443/444
# Unix:    regular Backspace = 127, Ctrl+Backspace = 8, Ctrl+(Left/Right) = 545/560
if sys.platform == "win32":
    CTRL_LEFT_CODES       = {443}
    CTRL_RIGHT_CODES      = {444}
    CTRL_BACKSPACE_CODES  = {127}
    REGULAR_BS_EXTRA      = {8}
else:
    CTRL_LEFT_CODES       = {545}
    CTRL_RIGHT_CODES      = {560}
    CTRL_BACKSPACE_CODES  = {8}
    REGULAR_BS_EXTRA      = {127}


def wrap_line(line, width):
    """Wrap a logical line into visual rows.
    First row has no extra indent; continuation rows are prefixed with
    WRAP_INDENT. The indent is dropped on very narrow windows where it
    would leave almost no room for actual content per row."""
    if width <= 0 or len(line) <= width:
        return [line]
    rows = [line[:width]]
    # Use the indent only when at least 2 chars of content fit after it.
    indent = WRAP_INDENT if width >= len(WRAP_INDENT) + 2 else ""
    cont_width = max(1, width - len(indent))
    i = width
    while i < len(line):
        rows.append(indent + line[i:i + cont_width])
        i += cont_width
    return rows


class LogiBox:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.workspace_lines = []   # everything shown in the top pane
        self.command_buffer = ""    # what the user is currently typing
        self.cursor_pos = 0         # cursor index within command_buffer
        self.cmd_view_offset = 0    # horizontal scroll for long input lines
        self.history = []           # previous commands (for up/down arrows)
        self.history_index = None
        self.scroll_offset = 0      # how many visual rows scrolled up from bottom
        self.running = True

        self.engine = LogicEngine()

        curses.curs_set(1)
        curses.mousemask(curses.ALL_MOUSE_EVENTS)
        curses.mouseinterval(0)
        self.stdscr.clear()

        self._build_layout()
        self._welcome()

    # == LAYOUT ==
    def _build_layout(self):
        self.height, self.width = self.stdscr.getmaxyx()
        self.workspace_height = self.height - 3

        self.workspace_win = curses.newwin(self.workspace_height, self.width, 0, 0)
        self.command_win = curses.newwin(3, self.width, self.workspace_height, 0)
        self.command_win.keypad(True)

    def _welcome(self):
        self.log("===     LogiBox by Gecons     ===")
        self.log("=== Logic Sandbox Environment ===")
        self.log("Type 'help' for commands, 'quit' to exit.")
        self.log("")

    def _handle_resize(self):
        """Rebuild the UI when the window is resized."""
        new_h, new_w = self.stdscr.getmaxyx()
        try:
            curses.resize_term(new_h, new_w)
        except curses.error:
            pass
        self.stdscr.clear()
        self.stdscr.refresh()
        self._build_layout()
        self.draw_workspace()

    # == DRAWING ==
    def _wrap_width(self):
        """Column budget for a single row of workspace text."""
        return max(1, self.width - 4)

    def draw_workspace(self):
        self.workspace_win.erase()
        self.workspace_win.border()
        self.workspace_win.addstr(0, 2, " Workspace ")

        inner_h = self.workspace_height - 2
        wrap_w = self._wrap_width()

        # Flatten logical lines into visual rows. This happens every draw so
        # the layout always matches the current window width.
        visual_rows = []
        for line in self.workspace_lines:
            visual_rows.extend(wrap_line(line, wrap_w))

        total = len(visual_rows)
        max_offset = max(0, total - inner_h)
        self.scroll_offset = max(0, min(self.scroll_offset, max_offset))

        end = total - self.scroll_offset
        start = max(0, end - inner_h)
        visible = visual_rows[start:end]

        for i, row in enumerate(visible):
            try:
                self.workspace_win.addstr(i + 1, 2, row[: self.width - 4])
            except curses.error:
                pass

        # indicators on the borders when there's hidden content
        if start > 0:
            tag = f" -- {start} more above -- "
            try:
                self.workspace_win.addstr(0, max(2, self.width - len(tag) - 2), tag)
            except curses.error:
                pass
        if self.scroll_offset > 0:
            tag = f" -- {self.scroll_offset} more below -- "
            try:
                self.workspace_win.addstr(self.workspace_height - 1, 2, tag)
            except curses.error:
                pass

        self.workspace_win.refresh()

    def draw_command_line(self):
        self.command_win.erase()
        self.command_win.border()
        try:
            self.command_win.addstr(0, 2, " Command ")
        except curses.error:
            pass

        # prompt + horizontal scroll so the cursor is always visible
        prompt = "> "
        inner_width = max(1, self.width - 4)
        visible_text_width = max(1, inner_width - len(prompt))

        if self.cursor_pos < self.cmd_view_offset:
            self.cmd_view_offset = self.cursor_pos
        elif self.cursor_pos - self.cmd_view_offset >= visible_text_width:
            self.cmd_view_offset = self.cursor_pos - visible_text_width + 1

        slice_start = self.cmd_view_offset
        slice_end = slice_start + visible_text_width
        display = self.command_buffer[slice_start:slice_end]

        try:
            self.command_win.addstr(1, 2, prompt + display)
        except curses.error:
            pass

        cursor_col = 2 + len(prompt) + (self.cursor_pos - self.cmd_view_offset)
        try:
            self.command_win.move(1, cursor_col)
        except curses.error:
            pass
        self.command_win.refresh()

    # == HELPERS ==
    def log(self, text=""):
        """Append a line to the workspace pane."""
        self.workspace_lines.append(text)
        # If the user is scrolled up, keep their view anchored by advancing
        # the offset past however many visual rows this new line produces.
        if self.scroll_offset > 0:
            self.scroll_offset += len(wrap_line(text, self._wrap_width()))
        self.draw_workspace()

    # == INPUT EDITING ==
    def _is_word_char(self, c):
        return c.isalnum() or c == "_"

    def _word_left(self):
        buf = self.command_buffer
        i = self.cursor_pos
        while i > 0 and not self._is_word_char(buf[i - 1]):
            i -= 1
        while i > 0 and self._is_word_char(buf[i - 1]):
            i -= 1
        return i

    def _word_right(self):
        buf = self.command_buffer
        n = len(buf)
        i = self.cursor_pos
        while i < n and self._is_word_char(buf[i]):
            i += 1
        while i < n and not self._is_word_char(buf[i]):
            i += 1
        return i

    def _insert_char(self, c):
        self.command_buffer = (
            self.command_buffer[:self.cursor_pos] + c + self.command_buffer[self.cursor_pos:]
        )
        self.cursor_pos += 1

    def _backspace(self):
        if self.cursor_pos > 0:
            self.command_buffer = (
                self.command_buffer[:self.cursor_pos - 1]
                + self.command_buffer[self.cursor_pos:]
            )
            self.cursor_pos -= 1

    def _delete_forward(self):
        if self.cursor_pos < len(self.command_buffer):
            self.command_buffer = (
                self.command_buffer[:self.cursor_pos]
                + self.command_buffer[self.cursor_pos + 1:]
            )

    def _delete_word_back(self):
        target = self._word_left()
        self.command_buffer = (
            self.command_buffer[:target] + self.command_buffer[self.cursor_pos:]
        )
        self.cursor_pos = target

    def _set_buffer(self, text):
        self.command_buffer = text
        self.cursor_pos = len(text)

    def _clear_buffer(self):
        self.command_buffer = ""
        self.cursor_pos = 0
        self.cmd_view_offset = 0

    # == FILE I/O ==
    def _saves_dir(self):
        if getattr(sys, "frozen", False):
            base = os.path.dirname(sys.executable)
        else:
            base = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(base, "saves")
        os.makedirs(path, exist_ok=True)
        return path

    def _validate_save_name(self, name):
        if not SAVE_NAME_RE.match(name):
            raise ValueError(
                "name must contain only letters, digits, underscores, or hyphens"
            )

    def _save(self, name):
        self._validate_save_name(name)
        path = os.path.join(self._saves_dir(), f"{name}.txt")
        lines = self.engine.export()
        with open(path, "w", encoding="utf-8") as f:
            f.write("# LogiBox save file\n")
            for line in lines:
                f.write(line + "\n")
        return path

    def _load(self, name):
        self._validate_save_name(name)
        path = os.path.join(self._saves_dir(), f"{name}.txt")
        if not os.path.isfile(path):
            raise FileNotFoundError(f"save {name!r} not found")
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        self.engine.import_state(lines)
        return path

    # == CLIPBOARD ==
    def _copy_to_clipboard(self, text):
        """Copy text to the system clipboard via platform-native tools."""
        if sys.platform == "win32":
            subprocess.run(["clip"], input=text, text=True, check=True, shell=False)
        elif sys.platform == "darwin":
            subprocess.run(["pbcopy"], input=text, text=True, check=True)
        else:
            try:
                subprocess.run(
                    ["xclip", "-selection", "clipboard"],
                    input=text, text=True, check=True,
                )
            except FileNotFoundError:
                try:
                    subprocess.run(
                        ["xsel", "--clipboard", "--input"],
                        input=text, text=True, check=True,
                    )
                except FileNotFoundError:
                    raise OSError("xclip or xsel is required on Linux")

    # == BULK SET / SHOW ==
    def _do_set(self, args):
        if "=" not in args:
            self.log("Usage: set <n> = <up to 16 binary digits>")
            return
        prefix, value = args.split("=", 1)
        prefix = prefix.strip()
        value = re.sub(r"\s+", "", value)
        if not prefix:
            self.log("set: missing variable name.")
            return
        if not PREFIX_RE.match(prefix):
            self.log(f"set: invalid name {prefix!r}.")
            return
        if not value:
            self.log("set: missing value.")
            return
        if not BITS_RE.match(value):
            self.log(f"set: value must contain only 0 and 1.")
            return
        if len(value) > 16:
            self.log(f"set: value is {len(value)} digits; maximum is 16.")
            return

        padded = value.zfill(16)
        for i in range(16):
            bit = padded[15 - i]
            self.engine.evaluate(f"{prefix}{i} = {bit}")
        decimal = int(padded, 2)
        self.log(f"Set: {prefix} = {padded}  ({decimal}, 0x{decimal:04X})")

    def _do_show(self, args):
        prefix = args.strip()
        if not prefix:
            self.log("Usage: show <n>")
            return
        if not PREFIX_RE.match(prefix):
            self.log(f"show: invalid name {prefix!r}.")
            return

        bits = []
        any_defined = False
        for i in range(15, -1, -1):
            name = f"{prefix}{i}"
            if name not in self.engine.variables:
                bits.append("?")
            else:
                any_defined = True
                try:
                    bits.append(str(int(self.engine.lookup(name))))
                except (NameError, RuntimeError):
                    bits.append("?")

        if not any_defined:
            self.log(f"show: no variables found matching {prefix}0..{prefix}15.")
            return
        binstr = "".join(bits)
        if "?" in binstr:
            self.log(f"{prefix} = {binstr}  (some bits undefined)")
        else:
            val = int(binstr, 2)
            self.log(f"{prefix} = {binstr}  ({val}, 0x{val:04X})")

    # == COPY ==
    def _do_copy(self, args):
        if not args:
            self.log("Usage: copy <number of lines>")
            return
        try:
            n = int(args)
        except ValueError:
            self.log(f"copy: {args!r} is not a valid number.")
            return
        if n <= 0:
            self.log("copy: number of lines must be positive.")
            return

        # Skip the last line: it is our own '> copy N' echo.
        history = self.workspace_lines[:-1]
        available = len(history)
        if n > available:
            self.log(f"copy: only {available} line(s) available to copy.")
            return

        text = "\n".join(history[-n:])
        try:
            self._copy_to_clipboard(text)
        except FileNotFoundError as e:
            self.log(f"copy: clipboard tool not found ({e.filename!r}).")
            return
        except subprocess.CalledProcessError as e:
            self.log(f"copy: clipboard tool failed (exit {e.returncode}).")
            return
        except OSError as e:
            self.log(f"copy: {e}")
            return
        except Exception as e:
            self.log(f"copy: unexpected error: {e}")
            return

        suffix = "" if n == 1 else "s"
        self.log(f"Copied last {n} line{suffix} to clipboard.")

    # == COMMAND DISPATCH ==
    def handle_command(self, cmd):
        cmd = cmd.strip()
        if not cmd:
            return

        self.history.append(cmd)
        self.log(f"> {cmd}")

        inst = cmd.casefold()
        if inst in ("quit", "exit"):
            self.running = False
        elif inst == "clear":
            self.workspace_lines = []
            self._welcome()
        elif inst == "help":
            self.log("Help Menu:")
            self.log("  help commands    - Lists all available commands.")
            self.log("  help operators   - Lists all available operators.")
            self.log("  help parameters  - Lists all available parameters.")
            self.log("  help parantheses - Displays information about parantheses.")
            self.log("  help batch       - Explains the 'set' and 'show' commands.")
            self.log("  help keys        - Lists keyboard shortcuts.")
        elif inst == "help commands":
            self.log("Commands:")
            self.log("  help   - Displays the help menu.")
            self.log("  clear  - Clears the workspace.")
            self.log("  exit   - Terminates the workspace.")
            self.log("  var    - Lists all variables.")
            self.log("  set?   - Batch-assigns a 16-bit register. See 'help batch'.")
            self.log("  show?  - Displays a 16-bit register. See 'help batch'.")
            self.log("  save X - Saves variables to 'saves/X.txt'.")
            self.log("  load X - Loads variables from 'saves/X.txt'.")
            self.log("  copy N - Copies the last N workspace lines to the clipboard.")
            self.log("You can use commands anytime.")
        elif inst == "help operators":
            self.log("Operators:")
            self.log("  OR     - Used for an OR gate.")
            self.log("  AND    - Used for an AND gate.")
            self.log("  XOR    - Used for an XOR gate.")
            self.log("  IMPLY  - Used for an IMPLY gate.")
            self.log("  NOR    - Used for a NOT OR gate.")
            self.log("  NAND   - Used for a NOT AND gate.")
            self.log("  XNOR   - Used for a NOT XOR gate.")
            self.log("  NIMPLY - Used for a NOT IMPLY gate.")
            self.log("A value is expected before and after an operator, with spaces in between.")
        elif inst == "help parameters":
            self.log("Parameters:")
            self.log("  *      - Inverts a variable. Used for NOT.")
            self.log("  =      - Assigns a variable to a value.")
            self.log("Parameters can only be used after a variable.")
            self.log("Entering a value performs calculation and outputs the result.")
        elif inst in ("help parantheses", "help paranthesis"):
            self.log("Parentheses:")
            self.log("  (      - Opening Parenthesis")
            self.log("  )      - Closing Parenthesis")
            self.log("Parantheses are used to specify operation precedence.")
            self.log("Parantheses must include a value inside them.")
            self.log("A paranthesis is opened with '(' and closed with ')'.")
            self.log("A closed paranthesis is expected in every procedure.")
        elif inst == "help batch":
            self.log("Batch Commands:")
            self.log("  set <n> = <bits>")
            self.log("    Assigns <n>0..<n>15 from a binary string.")
            self.log("    Leftmost digit is the highest bit; upper bits pad with 0.")
            self.log("    Value must be 1-16 digits of only 0 and 1 (spaces allowed).")
            self.log("    Existing bits are overwritten.")
            self.log("  show <n>")
            self.log("    Displays <n>0..<n>15 as binary, decimal, and hex.")
            self.log("    Unassigned or unresolvable bits show as '?'.")
        elif inst == "help keys":
            self.log("Keyboard:")
            self.log("  Left / Right       - Move cursor within the input line.")
            self.log("  Ctrl+(Left/Right)  - Jump cursor by word.")
            self.log("  Home / End         - Jump cursor to start / end of input.")
            self.log("  Backspace / Del    - Delete char before / at cursor.")
            self.log("  Ctrl+Backspace     - Delete the previous word.")
            self.log("  Up / Down          - Previous / next command from history.")
            self.log("  PageUp / PageDown  - Scroll the workspace.")
            self.log("  Mouse wheel        - Scroll the workspace.")
            self.log("To copy text, use the 'copy N' command (see 'help commands').")
        elif inst == "var":
            if not self.engine.variables:
                self.log("  (no variables defined)")
            else:
                for name in self.engine.variables:
                    self.log(f"  {name} = {self.engine.sources[name]}")
        elif inst == "set" or inst.startswith("set "):
            self._do_set(cmd[3:].strip())
        elif inst == "show" or inst.startswith("show "):
            self._do_show(cmd[4:].strip())
        elif inst == "copy" or inst.startswith("copy "):
            self._do_copy(cmd[4:].strip())
        elif inst == "save" or inst.startswith("save "):
            name = cmd[4:].strip()
            if not name:
                self.log("Usage: save <n>")
            else:
                try:
                    path = self._save(name)
                    self.log(f"Saved to '{path}'.")
                except Exception as e:
                    self.log(f"Save failed: {e}")
        elif inst == "load" or inst.startswith("load "):
            name = cmd[4:].strip()
            if not name:
                self.log("Usage: load <n>")
            else:
                try:
                    path = self._load(name)
                    count = len(self.engine.variables)
                    self.log(f"Loaded {count} variable(s) from '{path}'.")
                except Exception as e:
                    self.log(f"Load failed: {e}")
        else:
            try:
                result = self.engine.evaluate(cmd)
                kind = result[0]
                if kind == "value":
                    self.log(f"Output: {int(result[1])}")
                elif kind == "assignment":
                    _, name, value = result
                    if value is None:
                        self.log(f"Pending: {name} := {self.engine.sources[name]}")
                    else:
                        self.log(f"Assigned: {name}")
            except SyntaxError as e:
                self.log(f"Syntax error: {e}")
            except NameError as e:
                self.log(f"Undefined: {e}")
            except RuntimeError as e:
                self.log(f"Error: {e}")

    # == MAIN LOOP ==
    def run(self):
        while self.running:
            self.draw_command_line()
            ch = self.command_win.getch()

            if ch == curses.KEY_RESIZE:
                self._handle_resize()
                continue

            if ch == curses.KEY_MOUSE:
                try:
                    _, _, _, _, bstate = curses.getmouse()
                except curses.error:
                    continue
                scroll_up = curses.BUTTON4_PRESSED
                scroll_down = getattr(curses, "BUTTON5_PRESSED", 0x00200000)
                if bstate & scroll_up:
                    self.scroll_offset += 3
                    self.draw_workspace()
                elif bstate & scroll_down:
                    self.scroll_offset = max(0, self.scroll_offset - 3)
                    self.draw_workspace()
                continue

            # Workspace scroll
            if ch == curses.KEY_PPAGE:
                page = max(1, self.workspace_height - 3)
                self.scroll_offset += page
                self.draw_workspace()
                continue
            if ch == curses.KEY_NPAGE:
                page = max(1, self.workspace_height - 3)
                self.scroll_offset = max(0, self.scroll_offset - page)
                self.draw_workspace()
                continue

            # -------- Cursor movement --------
            if ch == curses.KEY_LEFT:
                if self.cursor_pos > 0:
                    self.cursor_pos -= 1
                continue
            if ch == curses.KEY_RIGHT:
                if self.cursor_pos < len(self.command_buffer):
                    self.cursor_pos += 1
                continue
            if ch in CTRL_LEFT_CODES:
                self.cursor_pos = self._word_left()
                continue
            if ch in CTRL_RIGHT_CODES:
                self.cursor_pos = self._word_right()
                continue
            if ch == curses.KEY_HOME:
                self.cursor_pos = 0
                continue
            if ch == curses.KEY_END:
                self.cursor_pos = len(self.command_buffer)
                continue

            # -------- Editing --------
            # Ctrl+Backspace first (its code may overlap with a BS variant).
            if ch in CTRL_BACKSPACE_CODES:
                self._delete_word_back()
                continue
            if ch == curses.KEY_BACKSPACE or ch in REGULAR_BS_EXTRA:
                self._backspace()
                continue
            if ch == curses.KEY_DC:
                self._delete_forward()
                continue

            # -------- Submit / history --------
            if ch in (curses.KEY_ENTER, 10, 13):
                cmd = self.command_buffer
                self._clear_buffer()
                self.history_index = None
                self.handle_command(cmd)
                continue

            if ch == curses.KEY_UP:
                if self.history:
                    if self.history_index is None:
                        self.history_index = len(self.history) - 1
                    else:
                        self.history_index = max(0, self.history_index - 1)
                    self._set_buffer(self.history[self.history_index])
                continue

            if ch == curses.KEY_DOWN:
                if self.history and self.history_index is not None:
                    self.history_index += 1
                    if self.history_index >= len(self.history):
                        self.history_index = None
                        self._clear_buffer()
                    else:
                        self._set_buffer(self.history[self.history_index])
                continue

            # Printable ASCII -> insert at cursor
            if 32 <= ch <= 126:
                self._insert_char(chr(ch))


def main(stdscr):
    LogiBox(stdscr).run()


if __name__ == "__main__":
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        sys.exit(0)