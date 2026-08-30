from dataclasses import dataclass


@dataclass(frozen=True)
class Style:
    fg: str = "39"
    bg: str = "49"
    bold: bool = False
    faint: bool = False
    italic: bool = False
    underline: bool = False
    inverse: bool = False
    strikethrough: bool = False


def color_param(c, bg):
    base = 48 if bg else 38
    default = "49" if bg else "39"
    if c is None:
        return default
    if c.is_standard:
        return f"{base};5;{c.standard}"
    if c.is_rgb:
        rgb = c.rgb
        return f"{base};2;{rgb.red};{rgb.green};{rgb.blue}"
    return default


def sgr(style):
    params = ["0"]
    for flag, code in (
        (style.bold, "1"),
        (style.faint, "2"),
        (style.italic, "3"),
        (style.underline, "4"),
        (style.inverse, "7"),
        (style.strikethrough, "9"),
    ):
        if flag:
            params.append(code)
    params.append(style.fg)
    params.append(style.bg)
    return "\x1b[" + ";".join(params) + "m"


def _cell_style(line, x):
    st = line.style_at(x)
    if st is None:
        return Style()
    return Style(
        fg=color_param(st.fg_color, bg=False),
        bg=color_param(st.bg_color, bg=True),
        bold=bool(st.bold),
        faint=bool(st.faint),
        italic=bool(st.italic),
        underline=bool(st.underline),
        inverse=bool(st.inverse),
        strikethrough=bool(st.strikethrough),
    )


# iTerm2 reports a cell the app never wrote as NUL, and a stray control byte
# can survive into cell text. Either one shows as a blank on the Mac but would
# steer the client's parser instead of drawing, so both become that blank.
_BLANKS = str.maketrans({c: " " for c in list(range(0x20)) + [0x7F]})


def cells(line):
    """The line split by cell, not by code point.

    style_at() is indexed by cell, but line.string is code points: one emoji
    or CJK glyph is a single cell and two or more code points, so walking the
    string slides every later cell's style over by one.
    """
    out = []
    x = 0
    while True:
        try:
            ch = line.string_at(x)
        except IndexError:
            return out
        out.append(ch)
        x += 1


def line_to_runs(line):
    runs = []
    cur = None
    buf = []
    for x, ch in enumerate(cells(line)):
        # a double-width glyph's trailing cell carries no code points of its
        # own; the glyph already covers that column on the client
        if not ch:
            continue
        st = _cell_style(line, x)
        if buf and st != cur:
            runs.append(("".join(buf), cur))
            buf = []
        cur = st
        buf.append(ch.translate(_BLANKS))
    if buf:
        runs.append(("".join(buf), cur))
    return tuple(runs)


@dataclass
class Frame:
    cols: int
    rows: int
    cursor: tuple
    lines: list


def from_screen_contents(contents, cols):
    lines = [line_to_runs(contents.line(i)) for i in range(contents.number_of_lines)]
    rows = max(len(lines), 1)
    cur = contents.cursor_coord
    x = min(max(cur.x, 0), max(cols - 1, 0))
    y = min(max(cur.y, 0), rows - 1)
    return Frame(cols=cols, rows=len(lines), cursor=(x, y), lines=lines)


def _render_line(runs):
    out = "".join(sgr(st) + text for text, st in runs)
    return out + "\x1b[0m\x1b[K"


def render(prev, new, force_full):
    full = force_full or prev is None or prev.cols != new.cols or prev.rows != new.rows
    if full:
        dirty = range(new.rows)
    else:
        dirty = [i for i in range(new.rows) if prev.lines[i] != new.lines[i]]
    cursor_moved = prev is None or prev.cursor != new.cursor
    if not full and not dirty and not cursor_moved:
        return "", False
    parts = ["\x1b[2J"] if full else []
    for i in dirty:
        parts.append(f"\x1b[{i + 1};1H")
        parts.append(_render_line(new.lines[i]))
    parts.append(f"\x1b[{new.cursor[1] + 1};{new.cursor[0] + 1}H")
    return "".join(parts), full
