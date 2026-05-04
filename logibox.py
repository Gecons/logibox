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
        # End-of-line comments are allowed only on assignments. A '#' in any
        # other context falls through to tokenize and produces the usual
        # "unexpected character" syntax error. Pure-comment lines are empty.
        source = self._strip_assignment_comment(source)
        if source.lstrip().startswith("#"):
            return ("empty",)

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

    @staticmethod
    def _strip_assignment_comment(source):
        """If the line is an assignment ('=' before '#'), drop everything
        from '#' onward. Otherwise leave the source as-is."""
        hash_pos = source.find("#")
        if hash_pos == -1:
            return source
        eq_pos = source.find("=")
        if eq_pos != -1 and eq_pos < hash_pos:
            return source[:hash_pos].rstrip()
        return source

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
            # Blank lines and full-line comments are skipped here. Mid-line
            # comments are stripped inside evaluate().
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

# Output category tags. Each call to log() may pass one of these to mark
# what kind of line it is, so the workspace can color it accordingly.
TAG_DEFAULT = "default"
TAG_PROMPT  = "prompt"      # the '> command' echo
TAG_OUTPUT  = "output"      # 'Output: 1' results
TAG_ASSIGN  = "assign"      # 'Assigned: foo' confirmations
TAG_PENDING = "pending"     # deferred assignment notices
TAG_ERROR   = "error"       # syntax/undefined/runtime errors
TAG_INFO    = "info"        # save/load/copy confirmations
TAG_HEADER  = "header"      # banner / section headings in help

# Foreground color name per category. Background is whatever the terminal
# already uses, so the workspace blends in naturally.
TAG_COLORS = {
    TAG_DEFAULT: "white",
    TAG_PROMPT:  "cyan",
    TAG_OUTPUT:  "yellow",
    TAG_ASSIGN:  "green",
    TAG_PENDING: "magenta",
    TAG_ERROR:   "red",
    TAG_INFO:    "cyan",
    TAG_HEADER:  "yellow",
}

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
    Continuation rows match the line's own leading whitespace, plus an
    extra WRAP_INDENT, so wrapped output stays visually aligned with
    the source indent. The extra indent drops on very narrow windows
    where it would leave almost no room for content."""
    if width <= 0 or len(line) <= width:
        return [line]

    # Preserve the source's own leading whitespace on every continuation row.
    leading = ""
    for c in line:
        if c == " " or c == "\t":
            leading += c
        else:
            break

    rows = [line[:width]]
    indent = leading + WRAP_INDENT
    if len(indent) + 2 > width:
        # Window too narrow to afford the extra indent - fall back to
        # just matching leading whitespace, or no indent at all.
        indent = leading if len(leading) + 2 <= width else ""
    cont_width = max(1, width - len(indent))
    i = width
    while i < len(line):
        rows.append(indent + line[i:i + cont_width])
        i += cont_width
    return rows


class LogiBox:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.workspace_lines = []   # list of (text, tag); tag drives coloring
        self.command_buffer = ""    # what the user is currently typing
        self.cursor_pos = 0         # cursor index within command_buffer
        self.cmd_view_offset = 0    # horizontal scroll for long input lines
        self.history = []           # previous commands (for up/down arrows)
        self.history_index = None
        self.scroll_offset = 0      # how many visual rows scrolled up from bottom
        self.running = True

        self.engine = LogicEngine()
        self.attrs = {}             # tag -> curses attribute (set in _init_colors)

        curses.curs_set(1)
        curses.mousemask(curses.ALL_MOUSE_EVENTS)
        curses.mouseinterval(0)
        self._init_colors()
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
        self.log("===     LogiBox by Gecons     ===", TAG_HEADER)
        self.log("=== Logic Sandbox Environment ===", TAG_HEADER)
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

    # == COLORS ==
    def _init_colors(self):
        """Allocate one curses color pair per output category. Background
        is left at the terminal default so the workspace blends in with
        the user's color scheme."""
        self.attrs = {tag: 0 for tag in TAG_COLORS}
        if not curses.has_colors():
            return
        try:
            curses.start_color()
            curses.use_default_colors()
        except curses.error:
            return
        for i, (tag, name) in enumerate(TAG_COLORS.items(), start=1):
            color = getattr(curses, f"COLOR_{name.upper()}", curses.COLOR_WHITE)
            try:
                curses.init_pair(i, color, -1)   # -1 = default background
                self.attrs[tag] = curses.color_pair(i)
            except curses.error:
                self.attrs[tag] = 0

    # == DRAWING ==
    def _wrap_width(self):
        """Column budget for a single row of workspace text."""
        return max(1, self.width - 4)

    def draw_workspace(self):
        attr_default = self.attrs.get(TAG_DEFAULT, 0)
        self.workspace_win.erase()
        self.workspace_win.attrset(attr_default)
        self.workspace_win.border()
        self.workspace_win.addstr(0, 2, " Workspace ",
                                  self.attrs.get(TAG_HEADER, attr_default))

        inner_h = self.workspace_height - 2
        wrap_w = self._wrap_width()

        # Flatten logical lines into visual rows. This happens every draw so
        # the layout always matches the current window width.
        visual_rows = []
        for text, tag in self.workspace_lines:
            for row in wrap_line(text, wrap_w):
                visual_rows.append((row, tag))

        total = len(visual_rows)
        max_offset = max(0, total - inner_h)
        self.scroll_offset = max(0, min(self.scroll_offset, max_offset))

        end = total - self.scroll_offset
        start = max(0, end - inner_h)

        for i, (row, tag) in enumerate(visual_rows[start:end]):
            attr = self.attrs.get(tag, attr_default)
            try:
                self.workspace_win.addstr(i + 1, 2, row[: self.width - 4], attr)
            except curses.error:
                pass

        # indicators on the borders when there's hidden content
        if start > 0:
            label = f" -- {start} more above -- "
            try:
                self.workspace_win.addstr(
                    0, max(2, self.width - len(label) - 2), label,
                    self.attrs.get(TAG_INFO, attr_default))
            except curses.error:
                pass
        if self.scroll_offset > 0:
            label = f" -- {self.scroll_offset} more below -- "
            try:
                self.workspace_win.addstr(
                    self.workspace_height - 1, 2, label,
                    self.attrs.get(TAG_INFO, attr_default))
            except curses.error:
                pass

        self.workspace_win.refresh()

    def draw_command_line(self):
        attr_default = self.attrs.get(TAG_DEFAULT, 0)
        self.command_win.erase()
        self.command_win.attrset(attr_default)
        self.command_win.border()
        try:
            self.command_win.addstr(0, 2, " Command ",
                                    self.attrs.get(TAG_HEADER, attr_default))
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
            self.command_win.addstr(1, 2, prompt,
                                    self.attrs.get(TAG_PROMPT, attr_default))
            self.command_win.addstr(1, 2 + len(prompt), display, attr_default)
        except curses.error:
            pass

        cursor_col = 2 + len(prompt) + (self.cursor_pos - self.cmd_view_offset)
        try:
            self.command_win.move(1, cursor_col)
        except curses.error:
            pass
        self.command_win.refresh()

    # == HELPERS ==
    def log(self, text="", tag=TAG_DEFAULT):
        """Append a line to the workspace pane."""
        self.workspace_lines.append((text, tag))
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
            self.log("Usage: set <n> = <up to 16 binary digits>", TAG_ERROR)
            return
        prefix, value = args.split("=", 1)
        prefix = prefix.strip()
        value = re.sub(r"\s+", "", value)
        if not prefix:
            self.log("set: missing variable name.", TAG_ERROR)
            return
        if not PREFIX_RE.match(prefix):
            self.log(f"set: invalid name {prefix!r}.", TAG_ERROR)
            return
        if not value:
            self.log("set: missing value.", TAG_ERROR)
            return
        if not BITS_RE.match(value):
            self.log(f"set: value must contain only 0 and 1.", TAG_ERROR)
            return
        if len(value) > 16:
            self.log(f"set: value is {len(value)} digits; maximum is 16.", TAG_ERROR)
            return

        padded = value.zfill(16)
        for i in range(16):
            bit = padded[15 - i]
            self.engine.evaluate(f"{prefix}{i} = {bit}")
        decimal = int(padded, 2)
        self.log(f"Set: {prefix} = {padded}  ({decimal}, 0x{decimal:04X})", TAG_OUTPUT)

    def _do_show(self, args):
        prefix = args.strip()
        if not prefix:
            self.log("Usage: show <n>", TAG_ERROR)
            return
        if not PREFIX_RE.match(prefix):
            self.log(f"show: invalid name {prefix!r}.", TAG_ERROR)
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
            self.log(f"show: no variables found matching {prefix}0..{prefix}15.",
                     TAG_ERROR)
            return
        binstr = "".join(bits)
        if "?" in binstr:
            self.log(f"{prefix} = {binstr}  (some bits undefined)", TAG_PENDING)
        else:
            val = int(binstr, 2)
            self.log(f"{prefix} = {binstr}  ({val}, 0x{val:04X})", TAG_OUTPUT)

    # == COPY ==
    def _do_copy(self, args):
        if not args:
            self.log("Usage: copy <number of lines>", TAG_ERROR)
            return
        try:
            n = int(args)
        except ValueError:
            self.log(f"copy: {args!r} is not a valid number.", TAG_ERROR)
            return
        if n <= 0:
            self.log("copy: number of lines must be positive.", TAG_ERROR)
            return

        # Skip the last line: it is our own '> copy N' echo.
        history = [text for text, _ in self.workspace_lines[:-1]]
        available = len(history)
        if n > available:
            self.log(f"copy: only {available} line(s) available to copy.", TAG_ERROR)
            return

        text = "\n".join(history[-n:])
        try:
            self._copy_to_clipboard(text)
        except FileNotFoundError as e:
            self.log(f"copy: clipboard tool not found ({e.filename!r}).", TAG_ERROR)
            return
        except subprocess.CalledProcessError as e:
            self.log(f"copy: clipboard tool failed (exit {e.returncode}).", TAG_ERROR)
            return
        except OSError as e:
            self.log(f"copy: {e}", TAG_ERROR)
            return
        except Exception as e:
            self.log(f"copy: unexpected error: {e}", TAG_ERROR)
            return

        suffix = "" if n == 1 else "s"
        self.log(f"Copied last {n} line{suffix} to clipboard.", TAG_INFO)

    # == HELP PAGES ==
    # Help text is data, not control flow. Each entry is a list of
    # (text, tag) tuples; handle_command just iterates one of them.
    def _help_pages(self):
        return {
            "help": [
                ("Help Menu:", TAG_HEADER),
                ("  help commands    - Lists all available commands.", TAG_DEFAULT),
                ("  help operators   - Lists all available operators.", TAG_DEFAULT),
                ("  help parameters  - Lists all available parameters.", TAG_DEFAULT),
                ("  help parantheses - Displays information about parantheses.", TAG_DEFAULT),
                ("  help batch       - Explains the 'set' and 'show' commands.", TAG_DEFAULT),
                ("  help keys        - Lists keyboard shortcuts.", TAG_DEFAULT),
            ],
            "help commands": [
                ("Commands:", TAG_HEADER),
                ("  help    - Displays the help menu.", TAG_DEFAULT),
                ("  clear   - Clears the workspace.", TAG_DEFAULT),
                ("  exit    - Terminates the workspace.", TAG_DEFAULT),
                ("  var     - Lists all variables.", TAG_DEFAULT),
                ("  set?    - Batch-assigns a 16-bit register. See 'help batch'.", TAG_DEFAULT),
                ("  show?   - Displays a 16-bit register. See 'help batch'.", TAG_DEFAULT),
                ("  save X  - Saves variables to 'saves/X.txt'.", TAG_DEFAULT),
                ("  load X  - Loads variables from 'saves/X.txt'.", TAG_DEFAULT),
                ("  copy N  - Copies the last N workspace lines to the clipboard.", TAG_DEFAULT),
                ("You can use commands anytime.", TAG_DEFAULT),
            ],
            "help operators": [
                ("Operators:", TAG_HEADER),
                ("  OR     - Used for an OR gate.", TAG_DEFAULT),
                ("  AND    - Used for an AND gate.", TAG_DEFAULT),
                ("  XOR    - Used for an XOR gate.", TAG_DEFAULT),
                ("  IMPLY  - Used for an IMPLY gate.", TAG_DEFAULT),
                ("  NOR    - Used for a NOT OR gate.", TAG_DEFAULT),
                ("  NAND   - Used for a NOT AND gate.", TAG_DEFAULT),
                ("  XNOR   - Used for a NOT XOR gate.", TAG_DEFAULT),
                ("  NIMPLY - Used for a NOT IMPLY gate.", TAG_DEFAULT),
                ("A value is expected before and after an operator, with spaces in between.", TAG_DEFAULT),
            ],
            "help parameters": [
                ("Parameters:", TAG_HEADER),
                ("  *      - Inverts a variable. Used for NOT.", TAG_DEFAULT),
                ("  =      - Assigns a variable to a value.", TAG_DEFAULT),
                ("  #      - Begins a comment (assignment lines only).", TAG_DEFAULT),
                ("Parameters can only be used after a variable.", TAG_DEFAULT),
                ("Entering a value performs calculation and outputs the result.", TAG_DEFAULT),
            ],
            "help parantheses": [
                ("Parentheses:", TAG_HEADER),
                ("  (      - Opening Parenthesis", TAG_DEFAULT),
                ("  )      - Closing Parenthesis", TAG_DEFAULT),
                ("Parantheses are used to specify operation precedence.", TAG_DEFAULT),
                ("Parantheses must include a value inside them.", TAG_DEFAULT),
                ("A paranthesis is opened with '(' and closed with ')'.", TAG_DEFAULT),
                ("A closed paranthesis is expected in every procedure.", TAG_DEFAULT),
            ],
            "help batch": [
                ("Batch Commands:", TAG_HEADER),
                ("  set <n> = <bits>", TAG_DEFAULT),
                ("    Assigns <n>0..<n>15 from a binary string.", TAG_DEFAULT),
                ("    Leftmost digit is the highest bit; upper bits pad with 0.", TAG_DEFAULT),
                ("    Value must be 1-16 digits of only 0 and 1 (spaces allowed).", TAG_DEFAULT),
                ("    Existing bits are overwritten.", TAG_DEFAULT),
                ("  show <n>", TAG_DEFAULT),
                ("    Displays <n>0..<n>15 as binary, decimal, and hex.", TAG_DEFAULT),
                ("    Unassigned or unresolvable bits show as '?'.", TAG_DEFAULT),
            ],
            "help keys": [
                ("Keyboard:", TAG_HEADER),
                ("  Left / Right       - Move cursor within the input line.", TAG_DEFAULT),
                ("  Ctrl+(Left/Right)  - Jump cursor by word.", TAG_DEFAULT),
                ("  Home / End         - Jump cursor to start / end of input.", TAG_DEFAULT),
                ("  Backspace / Del    - Delete char before / at cursor.", TAG_DEFAULT),
                ("  Ctrl+Backspace     - Delete the previous word.", TAG_DEFAULT),
                ("  Up / Down          - Previous / next command from history.", TAG_DEFAULT),
                ("  PageUp / PageDown  - Scroll the workspace.", TAG_DEFAULT),
                ("  Mouse wheel        - Scroll the workspace.", TAG_DEFAULT),
                ("To copy text, use the 'copy N' command (see 'help commands').", TAG_DEFAULT),
            ],
        }

    # == COMMAND HANDLERS ==
    # Each handler takes the args string (everything after the command word,
    # already stripped). Handlers for argument-less commands accept and
    # ignore args, so the dispatch shape stays uniform.

    def _cmd_quit(self, args):
        self.running = False

    def _cmd_clear(self, args):
        self.workspace_lines = []
        self._welcome()

    def _cmd_help(self, args):
        # Resolve the requested page; 'help paranthesis' falls back to
        # 'help parantheses' so both spellings work.
        key = "help" if not args else f"help {args.casefold()}"
        if key == "help paranthesis":
            key = "help parantheses"
        pages = self._help_pages()
        page = pages.get(key)
        if page is None:
            self.log(f"help: no page named {args!r}.", TAG_ERROR)
            return
        for text, tag in page:
            self.log(text, tag)

    def _cmd_var(self, args):
        if not self.engine.variables:
            self.log("  (no variables defined)")
            return
        for name in self.engine.variables:
            self.log(f"  {name} = {self.engine.sources[name]}")

    def _cmd_save(self, args):
        if not args:
            self.log("Usage: save <n>", TAG_ERROR)
            return
        try:
            path = self._save(args)
            self.log(f"Saved to '{path}'.", TAG_INFO)
        except Exception as e:
            self.log(f"Save failed: {e}", TAG_ERROR)

    def _cmd_load(self, args):
        if not args:
            self.log("Usage: load <n>", TAG_ERROR)
            return
        try:
            path = self._load(args)
            count = len(self.engine.variables)
            self.log(f"Loaded {count} variable(s) from '{path}'.", TAG_INFO)
        except Exception as e:
            self.log(f"Load failed: {e}", TAG_ERROR)

    def _cmd_engine(self, source):
        # Fallback handler: source had no recognized command word, so feed
        # the whole line to the logic engine.
        try:
            result = self.engine.evaluate(source)
            kind = result[0]
            if kind == "value":
                self.log(f"Output: {int(result[1])}", TAG_OUTPUT)
            elif kind == "assignment":
                _, name, value = result
                if value is None:
                    self.log(f"Pending: {name} := {self.engine.sources[name]}",
                             TAG_PENDING)
                else:
                    self.log(f"Assigned: {name}", TAG_ASSIGN)
        except SyntaxError as e:
            self.log(f"Syntax error: {e}", TAG_ERROR)
        except NameError as e:
            self.log(f"Undefined: {e}", TAG_ERROR)
        except RuntimeError as e:
            self.log(f"Error: {e}", TAG_ERROR)

    # == COMMAND DISPATCH ==
    def _commands(self):
        """Map of command-word -> handler. Adding a new command means
        writing one method and adding one row here."""
        return {
            "quit":  self._cmd_quit,
            "exit":  self._cmd_quit,
            "clear": self._cmd_clear,
            "help":  self._cmd_help,
            "var":   self._cmd_var,
            "set":   self._do_set,
            "show":  self._do_show,
            "copy":  self._do_copy,
            "save":  self._cmd_save,
            "load":  self._cmd_load,
        }

    def handle_command(self, cmd):
        cmd = cmd.strip()
        if not cmd:
            return

        self.history.append(cmd)
        self.log(f"> {cmd}", TAG_PROMPT)

        # Split on the first whitespace run. The first token (case-folded)
        # is matched against the command table; anything else is engine input.
        parts = cmd.split(None, 1)
        word = parts[0].casefold()
        args = parts[1].strip() if len(parts) > 1 else ""

        handler = self._commands().get(word)
        if handler is not None:
            handler(args)
        else:
            self._cmd_engine(cmd)

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