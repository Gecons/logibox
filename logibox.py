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
        self.variables = {}          # name -> AST
        self.sources = {}            # name -> pretty-printed source
        self._evaluating = set()     # cycle guard during lookup

    # == ENTRY POINT ==
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
        """Return a list of 'name = expression' lines for all bindings."""
        return [f"{name} = {self.sources[name]}" for name in self.variables]

    def import_state(self, lines):
        """Replace all state from a list of assignment strings.
        If any line is invalid, current state is left untouched."""
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

    # == CYCLE CHECK ==
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

    # == TOKENIZE ==
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

    # == PARSE ==
    # Grammar, lowest to highest precedence:
    #   statement   := IDENT '=' expression | expression
    #   imply_expr  := or_expr   (('IMPLY'|'NIMPLY')         or_expr)*
    #   or_expr     := and_expr  (('OR'|'NOR'|'XOR'|'XNOR')  and_expr)*
    #   and_expr    := not_expr  (('AND'|'NAND')             not_expr)*
    #   not_expr    := primary ('*')*
    #   primary     := LIT | IDENT | '(' expression ')'
    # Binary ops are left-associative.
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

    # == EXECUTE ==
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

    # == AST -> SOURCE ==
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


class LogiBox:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.workspace_lines = []   # everything shown in the top pane
        self.command_buffer = ""    # what the user is currently typing
        self.history = []           # previous commands (for up/down arrows)
        self.history_index = None
        self.scroll_offset = 0      # how many lines scrolled up from bottom
        self.running = True

        self.engine = LogicEngine()

        curses.curs_set(1)
        curses.mousemask(curses.ALL_MOUSE_EVENTS)
        curses.mouseinterval(0)  # don't wait for click-release detection
        self.stdscr.clear()

        self._build_layout()
        self._welcome()

    # == LAYOUT ==
    def _build_layout(self):
        self.height, self.width = self.stdscr.getmaxyx()
        self.workspace_height = self.height - 3  # command pane uses bottom 3 rows

        self.workspace_win = curses.newwin(self.workspace_height, self.width, 0, 0)
        self.command_win = curses.newwin(3, self.width, self.workspace_height, 0)
        self.command_win.keypad(True)  # enables arrow keys, backspace, etc.

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
    def draw_workspace(self):
        self.workspace_win.erase()
        self.workspace_win.border()
        self.workspace_win.addstr(0, 2, " Workspace ")

        inner_h = self.workspace_height - 2
        total = len(self.workspace_lines)
        max_offset = max(0, total - inner_h)
        self.scroll_offset = max(0, min(self.scroll_offset, max_offset))

        end = total - self.scroll_offset
        start = max(0, end - inner_h)
        visible = self.workspace_lines[start:end]

        for i, line in enumerate(visible):
            try:
                self.workspace_win.addstr(i + 1, 2, line[: self.width - 4])
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
        self.command_win.addstr(0, 2, " Command ")
        try:
            self.command_win.addstr(1, 2, "> " + self.command_buffer)
        except curses.error:
            pass
        self.command_win.refresh()

    # == HELPERS ==
    def log(self, text=""):
        """Append a line to the workspace pane."""
        self.workspace_lines.append(text)
        # if user has scrolled up, keep their view anchored by nudging the offset
        if self.scroll_offset > 0:
            self.scroll_offset += 1
        self.draw_workspace()

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
        elif inst == "help commands":
            self.log("Commands:")
            self.log("  help   - Displays the help menu.")
            self.log("  clear  - Clears the workspace.")
            self.log("  exit   - Terminates the workspace.")
            self.log("  var    - Lists all variables.")
            self.log("  save X - Saves current variables to 'saves/X.txt'.")
            self.log("  load X - Loads variables from 'saves/X.txt'.")
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
            self.log("  *      - Inverts a variable.")
            self.log("  =      - Assigns a variable to a value.")
            self.log("Parameters can only be used after a variable.")
            self.log("Example usage:")
            self.log("> p = 1")
            self.log("> q = 0")
            self.log("> r = p* OR q")
            self.log("> s = r*")
            self.log("> s")
            self.log("Output: 1")
            self.log("Entering a value performs calculation and outputs the result.")
        elif inst in ("help parantheses", "help paranthesis"):
            self.log("Parentheses:")
            self.log("  (      - Opening Parenthesis")
            self.log("  )      - Closing Parenthesis")
            self.log("Parantheses are used to specify operation precedence.")
            self.log("Parantheses must include a value inside them.")
            self.log("A paranthesis is opened with '(' and closed with ')'.")
            self.log("A closed paranthesis is expected in every procedure.")
            self.log("Example usage:")
            self.log("> t = ((p AND q*) IMPLY (r OR s*)) XOR s*")
            self.log("Output: 0")
        elif inst == "var":
            if not self.engine.variables:
                self.log("  (no variables defined)")
            else:
                for name in self.engine.variables:
                    self.log(f"  {name} = {self.engine.sources[name]}")
        elif inst == "save" or inst.startswith("save "):
            name = cmd[4:].strip()
            if not name:
                self.log("Usage: save <name>")
            else:
                try:
                    path = self._save(name)
                    self.log(f"Saved to '{path}'.")
                except Exception as e:
                    self.log(f"Save failed: {e}")
        elif inst == "load" or inst.startswith("load "):
            name = cmd[4:].strip()
            if not name:
                self.log("Usage: load <name>")
            else:
                try:
                    path = self._load(name)
                    count = len(self.engine.variables)
                    self.log(f"Loaded {count} variable(s) from '{path}'.")
                except Exception as e:
                    self.log(f"Load failed: {e}")
        else:
            # feed everything else to the logic engine
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
                # ("empty",) -> nothing to print
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
                # BUTTON5_PRESSED isn't defined on every windows-curses build
                scroll_up = curses.BUTTON4_PRESSED
                scroll_down = getattr(curses, "BUTTON5_PRESSED", 0x00200000)
                if bstate & scroll_up:
                    self.scroll_offset += 3
                    self.draw_workspace()
                elif bstate & scroll_down:
                    self.scroll_offset = max(0, self.scroll_offset - 3)
                    self.draw_workspace()
                continue

            if ch == curses.KEY_PPAGE:       # PageUp - scroll workspace up
                page = max(1, self.workspace_height - 3)
                self.scroll_offset += page
                self.draw_workspace()
                continue

            if ch == curses.KEY_NPAGE:       # PageDown - scroll workspace down
                page = max(1, self.workspace_height - 3)
                self.scroll_offset = max(0, self.scroll_offset - page)
                self.draw_workspace()
                continue

            if ch == curses.KEY_HOME:        # Home - jump to top of workspace
                self.scroll_offset = len(self.workspace_lines)
                self.draw_workspace()
                continue

            if ch == curses.KEY_END:         # End - jump to latest
                self.scroll_offset = 0
                self.draw_workspace()
                continue

            if ch in (curses.KEY_ENTER, 10, 13):
                cmd = self.command_buffer
                self.command_buffer = ""
                self.history_index = None
                self.handle_command(cmd)

            elif ch in (curses.KEY_BACKSPACE, 127, 8):
                self.command_buffer = self.command_buffer[:-1]

            elif ch == curses.KEY_UP:
                if self.history:
                    if self.history_index is None:
                        self.history_index = len(self.history) - 1
                    else:
                        self.history_index = max(0, self.history_index - 1)
                    self.command_buffer = self.history[self.history_index]

            elif ch == curses.KEY_DOWN:
                if self.history and self.history_index is not None:
                    self.history_index += 1
                    if self.history_index >= len(self.history):
                        self.history_index = None
                        self.command_buffer = ""
                    else:
                        self.command_buffer = self.history[self.history_index]

            elif 32 <= ch <= 126:  # printable ASCII
                self.command_buffer += chr(ch)


def main(stdscr):
    LogiBox(stdscr).run()


if __name__ == "__main__":
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        sys.exit(0)