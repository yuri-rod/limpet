from iterm2.api_pb2 import CellStyle as ProtoCellStyle
from iterm2.api_pb2 import RGBColor as ProtoRGBColor
from iterm2.screen import CellStyle

from limpet.frames import Style, color_param, sgr


def standard(n):
    return CellStyle.Color(standard=n)


def rgb(r, g, b):
    return CellStyle.Color(rgb=CellStyle.RGBColor(ProtoRGBColor(red=r, green=g, blue=b)))


def test_color_param_default():
    assert color_param(None, bg=False) == "39"
    assert color_param(None, bg=True) == "49"
    alt = CellStyle.Color(alternate=CellStyle.AlternateColor.DEFAULT)
    assert color_param(alt, bg=False) == "39"
    assert color_param(alt, bg=True) == "49"
    reversed_alt = CellStyle.Color(alternate=CellStyle.AlternateColor.REVERSED_DEFAULT)
    assert color_param(reversed_alt, bg=False) == "39"
    assert color_param(reversed_alt, bg=True) == "49"


def test_color_param_palette_and_rgb():
    assert color_param(standard(196), bg=False) == "38;5;196"
    assert color_param(standard(17), bg=True) == "48;5;17"
    assert color_param(rgb(10, 20, 30), bg=False) == "38;2;10;20;30"
    assert color_param(rgb(1, 2, 3), bg=True) == "48;2;1;2;3"


def test_sgr_default_style():
    assert sgr(Style()) == "\x1b[0;39;49m"


def test_sgr_full_style():
    st = Style(
        fg="38;5;196",
        bg="49",
        bold=True,
        italic=True,
        underline=True,
        inverse=True,
        strikethrough=True,
        faint=True,
    )
    assert sgr(st) == "\x1b[0;1;2;3;4;7;9;38;5;196;49m"


from limpet.frames import Frame, from_screen_contents, line_to_runs


class FakeCellStyle:
    def __init__(self, fg=None, bg=None, **flags):
        self.fg_color, self.bg_color = fg, bg
        for f in ("bold", "faint", "italic", "underline", "inverse", "strikethrough"):
            setattr(self, f, flags.get(f, False))


class FakeLine:
    """Mirrors iterm2.screen.LineContents: cells, not code points."""

    def __init__(self, string, styles, cells=None):
        self.string = string
        self._styles = styles
        self._cells = list(string) if cells is None else list(cells)

    def style_at(self, x):
        return self._styles[x] if x < len(self._styles) else None

    def string_at(self, x):
        return self._cells[x]


class FakePoint:
    def __init__(self, x, y):
        self.x, self.y = x, y


class FakeContents:
    def __init__(self, lines, cursor):
        self._lines = lines
        self.number_of_lines = len(lines)
        self.cursor_coord = cursor

    def line(self, i):
        return self._lines[i]


def test_line_to_runs_groups_equal_styles():
    red = FakeCellStyle(fg=standard(196))
    line = FakeLine("abXY", [red, red, None, None])
    runs = line_to_runs(line)
    assert len(runs) == 2
    assert runs[0][0] == "ab" and runs[0][1].fg == "38;5;196"
    assert runs[1][0] == "XY" and runs[1][1].fg == "39"


def test_line_to_runs_turns_unwritten_cells_into_blanks():
    line = FakeLine("ab\x00\x00cd", [None] * 6)
    assert line_to_runs(line) == (("ab  cd", Style()),)


def test_line_to_runs_empty():
    assert line_to_runs(FakeLine("", [])) == ()


def test_line_to_runs_styles_by_cell_not_code_point():
    red = FakeCellStyle(fg=standard(196))
    # "e" + combining acute is one cell but two code points; indexing by code
    # point would hand the "!" cell the style that belongs to the accent
    line = FakeLine("e\u0301!", [red, None], cells=["e\u0301", "!"])
    runs = line_to_runs(line)
    assert len(runs) == 2
    assert runs[0][0] == "e\u0301" and runs[0][1].fg == "38;5;196"
    assert runs[1][0] == "!" and runs[1][1].fg == "39"


def test_line_to_runs_drops_double_width_filler_cells():
    line = FakeLine("\u4f60x", [None, None, None], cells=["\u4f60", "", "x"])
    assert line_to_runs(line) == (("\u4f60x", Style()),)


def test_line_to_runs_blanks_out_control_bytes():
    line = FakeLine("a\x07b\x7fc", [None] * 5)
    assert line_to_runs(line) == (("a b c", Style()),)


def test_line_to_runs_stops_at_a_short_cell_table():
    line = FakeLine("abc", [None] * 3, cells=["a", "b"])
    assert line_to_runs(line) == (("ab", Style()),)


from limpet.frames import _cell_style


def test_cell_style_standard_color_and_bold():
    line = FakeLine("a", [CellStyle(ProtoCellStyle(fgStandard=196, bold=True))])
    assert _cell_style(line, 0) == Style(fg="38;5;196", bg="49", bold=True)


def test_cell_style_rgb_color_and_flags():
    proto = ProtoCellStyle(
        bgRgb=ProtoRGBColor(red=10, green=20, blue=30), italic=True, underline=True
    )
    line = FakeLine("a", [CellStyle(proto)])
    assert _cell_style(line, 0) == Style(bg="48;2;10;20;30", italic=True, underline=True)


def test_cell_style_default_color_cell():
    line = FakeLine("a", [CellStyle(ProtoCellStyle())])
    assert _cell_style(line, 0) == Style()


def test_from_screen_contents_clamps_cursor():
    c = FakeContents([FakeLine("hi", [None, None])], FakePoint(99, 99))
    f = from_screen_contents(c, cols=80)
    assert f.rows == 1 and f.cols == 80
    assert f.cursor == (79, 0)
    assert f.lines[0][0][0] == "hi"


from limpet.frames import render


def _frame(texts, cursor=(0, 0), cols=10):
    lines = [((t, Style()),) if t else () for t in texts]
    return Frame(cols=cols, rows=len(lines), cursor=cursor, lines=lines)


def test_render_full_clears_and_paints_all():
    ansi, full = render(None, _frame(["ab", "cd"]), force_full=False)
    assert full
    assert ansi.startswith("\x1b[2J")
    assert "\x1b[1;1H" in ansi and "\x1b[2;1H" in ansi
    assert "ab" in ansi and "cd" in ansi
    assert ansi.endswith("\x1b[1;1H")


def test_render_diff_paints_only_dirty_lines():
    prev = _frame(["ab", "cd"])
    new = _frame(["ab", "zz"], cursor=(2, 1))
    ansi, full = render(prev, new, force_full=False)
    assert not full
    assert "\x1b[1;1H" not in ansi
    assert "\x1b[2;1H" in ansi and "zz" in ansi
    assert ansi.endswith("\x1b[2;3H")


def test_render_no_change_no_output():
    f = _frame(["ab"])
    assert render(f, _frame(["ab"]), force_full=False) == ("", False)


def test_render_cursor_only_move():
    prev = _frame(["ab"], cursor=(0, 0))
    new = _frame(["ab"], cursor=(1, 0))
    ansi, full = render(prev, new, force_full=False)
    assert ansi == "\x1b[1;2H" and not full


def test_render_resize_forces_full():
    prev = _frame(["ab"], cols=10)
    new = _frame(["ab"], cols=20)
    _, full = render(prev, new, force_full=False)
    assert full
