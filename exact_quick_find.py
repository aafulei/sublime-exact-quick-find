"""
MIT License

Copyright (c) 2021 Aaron Fu Lei

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

# standard
import bisect
import collections
import re
import sys

# sublime
import sublime
import sublime_plugin


# --- macros ------------------------------------------------------------------

class Def:
    CASE = True
    WORD = True
    WRAP = True
    FLIP_CASE = True
    FLIP_WORD = True
    FLIP_WRAP = False
    WRAP_CHAR = "R"
    WRAP_POSN = 3
    SAVE_FLAGS = True
    SHOW_TILDE = False
    SHOW_ALERT = True
    SHOW_NOTICE = True
    INDICATOR = "icon"
    SHOW_ICON = True
    DEBUG = False
    DEBUG_WATCHLIST = []
    DEBUG_BLOCKLIST = []


class Code:
    NO_CODE = 0
    GOTO_NEXT = 1
    ADD_NEXT = 2
    ADD_ALL = 3
    PEEK_NEXT = 4
    PEEK_NEXT_SELECTED = 5
    ADD_THIS = 6
    SUBTRACT_THIS = 7
    SINGLE_SELECT_THIS = 8
    INVERT_SELECT_THIS = 9
    GO_FIRST = 10
    GO_BACK = 11
    _names = ("NO_CODE", "GOTO_NEXT", "ADD_NEXT", "ADD_ALL", "PEEK_NEXT",
              "PEEK_NEXT_SELECTED", "ADD_THIS", "SUBTRACT_THIS",
              "SINGLE_SELECT_THIS", "INVERT_SELECT_THIS", "GO_FIRST",
              "GO_BACK")

    @staticmethod
    def to_str(code):
        try:
            return Code._names[code]
        except (IndexError, TypeError):
            return str(code)


class Init:
    NOT_INIT = 0
    BASIC = 1
    EXTENDED = 2
    _names = ("NOT_INIT", "BASIC", "EXTENDED")

    @staticmethod
    def to_str(init):
        try:
            return Init._names[init]
        except (IndexError, TypeError):
            return str(init)


class Indicator:
    NONE = 0
    SUPERIMPOSE = 1
    ICON = 2


class Level:
    ALL = 0
    TRACE = 1
    DEBUG = 2
    INFO = 3
    WARN = 4
    ERROR = 5
    _names = ("ALL", "TRACE", "DEBUG", "INFO", "WARN", "ERROR")

    @staticmethod
    def to_str(level):
        try:
            return Level._names[level]
        except (IndexError, TypeError):
            return str(level)


# --- globals -----------------------------------------------------------------

g_set_filename = "Exact Quick Find.sublime-settings"
g_set = None
g_case = None
g_word = None
g_wrap = None
g_eqf_center = {}


def plugin_loaded():
    _load_settings()
    w = sublime.active_window()
    active_view = w.active_view()
    if active_view is None:
        _debug_print("Active view is None in Window {}".format(w.id()))
    else:
        _set_status(_get_eqf(active_view))
    _debug_print("-----------------------")
    _debug_print("Exact Quick Find Loaded")
    _debug_print("-----------------------")


# simulate plugin_loaded() for earlier versions
if int(sublime.version()) < 3000:
    plugin_loaded()


def plugin_unloaded():
    global g_eqf_center
    all_views = []
    for vid in g_eqf_center:
        eqf = g_eqf_center[vid]
        all_views.append(eqf.view)
        _reset_status(eqf)
        eqf.view.erase_regions("exact_quick_find_indicator")
    for view in all_views:
        _del_eqf(view)
    _debug_assert(not g_eqf_center, "Expect empty g_eqf_center")
    _debug_print("Bye ~")


def _load_settings():
    global g_set
    global g_case
    global g_word
    global g_wrap
    g_set = sublime.load_settings(g_set_filename)
    if g_case is None:
        g_case = g_set.get("default_case_sensitive", Def.CASE)
    if g_word is None:
        g_word = g_set.get("default_whole_word", Def.WORD)
    if g_wrap is None:
        g_wrap = g_set.get("default_wrap_scan", Def.WRAP)


def _save_settings():
    global g_set
    g_set.set("default_case_sensitive", g_case)
    g_set.set("default_whole_word", g_word)
    g_set.set("default_wrap_scan", g_wrap)
    sublime.save_settings(g_set_filename)


def _get_flags():
    if any((x is None for x in (g_case, g_word, g_wrap))):
        _load_settings()
    wrap_char = str(g_set.get("wrap_scan_flag_char", Def.WRAP_CHAR))
    wrap_posn = g_set.get("wrap_scan_flag_position", Def.WRAP_POSN)
    if wrap_posn == 1:
        flags = "[{x}][{c}][{w}]"
    elif wrap_posn == 2:
        flags = "[{c}][{x}][{w}]"
    else:
        flags = "[{c}][{w}][{x}]"
    tilde = "~" if g_set.get("show_tilde", Def.SHOW_TILDE) else ""
    c = "C" if g_case else tilde + "c"
    w = "W" if g_word else tilde + "w"
    x = (wrap_char.upper()) if g_wrap else (tilde + wrap_char.lower())
    return flags.format(c=c, w=w, x=x)


# --- utilities ---------------------------------------------------------------

def _abridge(s, maxlen=20):
    if len(s) <= maxlen:
        return s
    else:
        half = max(maxlen // 2 - 2, 0)
        return s[:half] + " .. " + s[-half:]


def _find_ge(a, x):
    index = bisect.bisect_left(a, x)
    return index if index < len(a) else 0


def _find_gt(a, x):
    index = bisect.bisect_right(a, x)
    return index if index < len(a) else 0


def _bounded_next(i, n, reverse):
    if reverse:
        i -= 1
        if i == -1:
            return 0
        return i
    else:
        i += 1
        if i == n:
            return n - 1
        return i


def _wrapped_next(i, n, reverse):
    if reverse:
        i -= 1
        if i == -1:
            return n - 1
        return i
    else:
        i += 1
        if i == n:
            return 0
        return i


def _region_to_rowcol(view, region):
    r1, c1 = view.rowcol(region.a)
    r2, c2 = view.rowcol(region.b)
    return (r1 + 1), (c1 + 1), (r2 + 1), (c2 + 1)


def _simplify_regions(regions):
    # api reference guarantees that the regions are kept in sorted order
    return tuple((x.begin(), x.end()) for x in regions)


def _region_to_reglet(region):
    return (region.begin(), region.end())


def _reglet_to_region(reglet):
    return sublime.Region(reglet[0], reglet[1])


# --- debug -------------------------------------------------------------------

def _debug_print(*args, vid=0, level=Level.DEBUG, frame_num=1, **kwargs):
    debug_level = g_set.get("debug", Def.DEBUG)
    if not debug_level:
        return
    watchlist = g_set.get("debug_watchlist", Def.DEBUG_WATCHLIST)
    blocklist = g_set.get("debug_blocklist", Def.DEBUG_BLOCKLIST)
    frame = sys._getframe(frame_num)
    func_name = frame.f_code.co_name
    line_num = frame.f_lineno
    if ((level >= debug_level and func_name not in blocklist)
            or func_name in watchlist):
        print("{:5.5}:{:18.18}:{:3} [{:03}]"
              .format(Level.to_str(level), func_name, line_num, vid), end=" ")
        print(*args, **kwargs)


def _trace_print(*args, vid=0, **kwargs):
    kwargs.pop("level", None)
    kwargs.pop("frame_num", None)
    _debug_print(*args, vid=vid, level=Level.TRACE, frame_num=2, **kwargs)


def _debug_assert(expected, msg=""):
    debug_on = g_set.get("debug", Def.DEBUG)
    if not debug_on:
        return
    if not expected:
        raise AssertionError(msg)


# --- eqf ---------------------------------------------------------------------

def _reset_eqf(eqf):
    eqf.init = Init.NOT_INIT
    eqf.last_text_cmd = getattr(eqf, "last_text_cmd", "")
    eqf.last_code = Code.NO_CODE
    eqf.code = Code.NO_CODE
    eqf.text = None
    eqf.pattern = None
    eqf.reverse = None
    eqf.reglets = []
    eqf.selected = []
    eqf.init_index = None
    eqf.this_index = None
    eqf.orig_region = None
    eqf.zero_region = None
    eqf.ruler = ""
    eqf.alert = ""
    eqf.notice = ""


class ExactQuickFind():
    def __init__(self, view):
        self._view = view
        _reset_eqf(self)

    @property
    def view(self):
        return self._view

    @property
    def vid(self):
        if not hasattr(self, "_vid"):
            self._vid = self.view.id()
        return self._vid

    @property
    def this_reglet(self):
        if not self.reglets:
            return None
        return self.reglets[self.this_index]

    @property
    def this_region(self):
        if not self.reglets:
            return None
        return _reglet_to_region(self.reglets[self.this_index])

    @property
    def this_is_selected(self):
        if not self.reglets:
            return None
        return self.selected[self.this_index]

    @this_is_selected.setter
    def this_is_selected(self, boolean):
        if not self.reglets:
            return
        self.selected[self.this_index] = boolean

    @property
    def size(self):
        return len(self.reglets)

    @property
    def num_selected(self):
        return sum(self.selected)

    @property
    def status(self):
        status = _get_flags()
        show_alert = g_set.get("show_alert", Def.SHOW_ALERT)
        show_notice = g_set.get("show_notice", Def.SHOW_NOTICE)
        if show_alert and self.alert:
            status = self.alert + " ! " + status
        if self.ruler:
            status += " @ " + self.ruler
        if show_notice and self.notice:
            status += " : " + self.notice
        return status


def _get_eqf(view):
    vid = view.id()
    if vid not in g_eqf_center:
        g_eqf_center[vid] = ExactQuickFind(view)
        _debug_print("Created eqf object", vid=vid)
    return g_eqf_center[vid]


def _del_eqf(view):
    vid = view.id()
    if vid in g_eqf_center:
        del g_eqf_center[vid]
        _debug_print("Deleted eqf object", vid=vid)


# --- init helpers ------------------------------------------------------------

def _set_status(eqf):
    for w in sublime.windows():
        active_view = w.active_view()
        if active_view is None:
            _debug_print("Active view is None in Window {}".format(w.id()))
            continue
        veqf = _get_eqf(active_view)
        veqf.view.set_status("exact_quick_find_status", veqf.status)
        _trace_print("Set status on Window {}: \"{}\""
                     .format(w.id(), veqf.status), vid=veqf.vid)
    eqf.alert = ""
    eqf.notice = ""


def _reset_status(eqf):
    _set_status(eqf)
    eqf.ruler = ""


def _to_next_region(eqf):
    next_func = _wrapped_next if g_wrap else _bounded_next
    eqf.this_index = next_func(i=eqf.this_index, n=eqf.size,
                               reverse=eqf.reverse)


def _move_to_next_region(eqf):
    prev_index = eqf.this_index
    _to_next_region(eqf)
    if eqf.size == 1:
        msg = "No Other Matches"
        eqf.alert = msg
        _debug_print(msg, vid=eqf.vid)
        return
    if not g_wrap:
        msg = ""
        if eqf.reverse and prev_index == 0:
            msg = "First Match"
        if not eqf.reverse and prev_index == eqf.size - 1:
            msg = "Last Match"
        if msg:
            eqf.alert = msg
            _debug_print(msg, vid=eqf.vid)


def _has_next_region_to_add(eqf):
    if g_wrap:
        return True
    msg = ""
    if eqf.reverse and all(eqf.selected[:eqf.this_index]):
        msg = "No Matches Above"
    if not eqf.reverse and all(eqf.selected[eqf.this_index + 1:]):
        msg = "No Matches Below"
    if msg:
        eqf.alert = msg
        _debug_print(msg, vid=eqf.vid)
        return False
    return True


def _move_to_next_region_to_add(eqf):
    if all(eqf.selected):
        plural = "es" if eqf.size > 1 else ""
        msg = "Already Added All {} Match{}".format(eqf.size, plural)
        eqf.alert = msg
        _debug_print(msg, vid=eqf.vid)
        return
    if not _has_next_region_to_add(eqf):
        return
    while True:
        _to_next_region(eqf)
        if not eqf.this_is_selected:
            break


def _has_next_added_region(eqf):
    if g_wrap:
        return True
    msg = ""
    if eqf.reverse and not any(eqf.selected[:eqf.this_index]):
        msg = "No Selections Above"
    if not eqf.reverse and not any(eqf.selected[eqf.this_index + 1:]):
        msg = "No Selections Below"
    if msg:
        eqf.alert = msg
        _debug_print(msg, vid=eqf.vid)
        return False
    return True


def _move_to_next_added_region(eqf):
    if not any(eqf.selected):
        msg = "No Selections"
        eqf.alert = msg
        _debug_print(msg, vid=eqf.vid)
        return
    if not _has_next_added_region(eqf):
        return
    prev_index = eqf.this_index
    while True:
        _to_next_region(eqf)
        if eqf.this_is_selected:
            break
    if eqf.this_index == prev_index:
        msg = "No Other Selections"
        eqf.alert = msg
        _debug_print(msg, vid=eqf.vid)


def _establish_matches(eqf):
    find_flags = 0
    if not g_case:
        find_flags |= sublime.IGNORECASE
    pattern = eqf.text
    if g_word:
        pattern = "\\b{}\\b".format(re.escape(eqf.text))
    else:
        find_flags |= sublime.LITERAL
    eqf.pattern = pattern
    all_regions = eqf.view.find_all(eqf.pattern, find_flags)
    if not all_regions:
        return False
    eqf.reglets = _simplify_regions(all_regions)
    eqf.selected = [False] * eqf.size
    return True


def _set_index(eqf, reglet, find_func, select, comp_select):
    index = find_func(eqf.reglets, reglet)
    eqf.this_index = index
    if select or (comp_select and reglet == eqf.this_reglet):
        eqf.this_is_selected = True
    if eqf.init_index is None:
        eqf.init_index = index
        _trace_print("Set init_index to {}".format(eqf.init_index),
                     vid=eqf.vid)


"""
          GN(s)    AN(s) AA(s) PN       PS(s) AT(s) ST(-) SS(s) IV(-)  GF(s)
point     ge       ge    ge    ge       -     ge    -     ge    ge[v]  ge [0]
selected  ge(-)+gt ge+gt ge    ge(c)+gt ge    ge    ge    ge    ge[v]  ge [-1]
"""


def _establish_index(eqf, region, point):
    gn = eqf.code == Code.GOTO_NEXT
    an = eqf.code == Code.ADD_NEXT
    aa = eqf.code == Code.ADD_ALL
    pn = eqf.code == Code.PEEK_NEXT
    ps = eqf.code == Code.PEEK_NEXT_SELECTED
    at = eqf.code == Code.ADD_THIS
    st = eqf.code == Code.SUBTRACT_THIS
    ss = eqf.code == Code.SINGLE_SELECT_THIS
    iv = eqf.code == Code.INVERT_SELECT_THIS
    gf = eqf.code == Code.GO_FIRST
    # order matters for two _set_index() functions below
    reglet = _region_to_reglet(region)
    _set_index(
        eqf,
        reglet,
        find_func=_find_ge,
        select=any((point and gn, an, aa, ps, at, ss, iv)),
        comp_select=(not point) and pn)
    if (not point) and any((gn, an, pn)):
        _set_index(
            eqf,
            reglet,
            find_func=_find_gt,
            select=gn or an,
            comp_select=False)
    if aa:
        eqf.selected = [True] * eqf.size
    elif ss:
        if reglet != eqf.this_reglet:
            _debug_assert(g_word, "Expect [W]")
            msg = ("Selection \"{}\" Not In A Whole Word"
                   .format(_abridge(eqf.text)))
            eqf.alert = msg
            _debug_print(msg, vid=eqf.vid)
            return False
    elif iv:
        eqf.selected = [not x for x in eqf.selected]
        if not eqf.num_selected:
            msg = "No Other Matches"
            eqf.alert = msg
            _debug_print(msg, vid=eqf.vid)
            return False
    elif gf:
        eqf.this_index = (eqf.size - 1) if eqf.reverse else 0
        eqf.this_is_selected = True
    return True


def _add_selected_regions(eqf):
    regions_to_add = [_reglet_to_region(v) for i, v in enumerate(eqf.reglets)
                      if eqf.selected[i]]
    eqf.view.sel().add_all(regions_to_add)


def _establish_regions(eqf):
    stashed_regions = [x for x in eqf.view.sel()][:-1]
    eqf.view.sel().clear()
    _add_selected_regions(eqf)
    eqf.view.sel().add_all(stashed_regions)


# --- init --------------------------------------------------------------------

# return True for success, False for failure
def _basic_init(eqf):
    def _pre_check(unwanted, msg):
        if unwanted:
            eqf.alert = msg
            _debug_print(msg, vid=eqf.vid)
            return False
        return True
    # --- WRONG -------------
    # if not eqf.view.sel():
    # -----------------------
    # eqf.view.sel() evaluates to True even if there are no selections
    if len(eqf.view.sel()) == 0:
        msg = "No Selections"
        eqf.alert = msg
        _debug_print(msg, vid=eqf.vid)
        return False
    if eqf.init == Init.EXTENDED:
        code = eqf.code
        _reset_eqf(eqf)
        eqf.code = code
    eqf.orig_region = region = eqf.view.sel()[-1]
    point = region.empty()
    # -1. pre-check to rule out illogical commands
    if not all((
        _pre_check(point and eqf.code == Code.PEEK_NEXT_SELECTED,
                   "No Other Selections"),
        _pre_check(point and eqf.code == Code.SUBTRACT_THIS, "Can't Subtract"),
            _pre_check(eqf.code == Code.GO_BACK, "Can't Go Back"))):
        return False
    # 0. expand point selection
    if point:
        eqf.view.run_command("expand_selection", {"to": "word"})
        region = eqf.view.sel()[-1]
        if region.empty():
            return False
    eqf.text = eqf.view.substr(region)
    # 1. establish matches
    if not _establish_matches(eqf):
        msg = "No Matches Found For \"{}\"".format(_abridge(eqf.text))
        eqf.alert = msg
        _debug_print(msg, vid=eqf.vid)
        return False
    # 2. establish index
    if not _establish_index(eqf, region, point=point):
        return False
    # 3. establish regions
    _establish_regions(eqf)
    # 4. add back
    if eqf.code == Code.PEEK_NEXT:
        eqf.view.sel().add(eqf.orig_region)
    _push_zero_region(eqf)
    eqf.init = Init.BASIC
    return True


# return True for success, False for failure
def _extended_init(eqf):
    # --- WRONG -------------
    # if not eqf.view.sel():
    # -----------------------
    # eqf.view.sel() evaluates to True even if there are no selections
    if len(eqf.view.sel()) == 0:
        msg = "No Selections"
        eqf.alert = msg
        _debug_print(msg, vid=eqf.vid)
        return False
    eqf.reglets = _simplify_regions(eqf.view.sel())
    eqf.this_index = 0 if eqf.reverse else eqf.size - 1
    eqf.init_index = eqf.size - 1 if eqf.reverse else 0
    eqf.selected = [True] * eqf.size
    eqf.init = Init.EXTENDED
    return True


# --- dispatch helpers --------------------------------------------------------

def _push_zero_region(eqf):
    if any(eqf.selected):
        return
    eqf.zero_region = eqf.this_region
    eqf.view.sel().add(eqf.zero_region)
    _debug_print("Pushed {} to temporary zero_region."
                 .format(eqf.zero_region), vid=eqf.vid)


def _pop_zero_region(eqf):
    if eqf.zero_region is None:
        return
    zr = eqf.zero_region
    eqf.view.sel().subtract(eqf.zero_region)
    eqf.zero_region = None
    _debug_print("Popped temporary zero_region {}".format(zr), vid=eqf.vid)


def _add_this_region(eqf):
    _pop_zero_region(eqf)
    eqf.view.sel().add(eqf.this_region)
    eqf.this_is_selected = True


def _subtract_this_region(eqf):
    eqf.view.sel().subtract(eqf.this_region)
    eqf.this_is_selected = False


def _substract_region_avoid_zero(eqf):
    _subtract_this_region(eqf)
    _push_zero_region(eqf)


def _context_aware_go(eqf, dest_index, notice_name):
    # depending on last_code, could be goto/peek, subtracting old region or not
    if eqf.this_index == dest_index:
        msg = "Already " + notice_name
        eqf.alert = msg
        _debug_print(msg, vid=eqf.vid)
        return
    if eqf.last_code in {Code.NO_CODE, Code.GOTO_NEXT}:
        _subtract_this_region(eqf)
    eqf.this_index = dest_index
    if eqf.last_code in {Code.NO_CODE, Code.GOTO_NEXT, Code.ADD_NEXT,
                         Code.ADD_ALL, Code.ADD_THIS, Code.SUBTRACT_THIS}:
        _add_this_region(eqf)


# --- dispatches --------------------------------------------------------------

def _noop_dispatch(eqf):
    pass


def _goto_next_dispatch(eqf):
    _subtract_this_region(eqf)
    _move_to_next_region(eqf)
    _add_this_region(eqf)


def _add_next_dispatch(eqf):
    _move_to_next_region_to_add(eqf)
    _add_this_region(eqf)


def _add_all_dispatch(eqf):
    if eqf.num_selected == eqf.size:
        plural = "es" if eqf.size > 1 else ""
        msg = "Already Added All {} Match{}".format(eqf.size, plural)
        eqf.alert = msg
        _debug_print(msg, vid=eqf.vid)
        return
    _pop_zero_region(eqf)
    eqf.selected = [True] * eqf.size
    _add_selected_regions(eqf)


def _peek_next_dispatch(eqf):
    _move_to_next_region(eqf)


def _peek_next_selected_dispatch(eqf):
    _move_to_next_added_region(eqf)


def _add_this_dispatch(eqf):
    if eqf.this_is_selected:
        msg = "Already Added"
        eqf.alert = msg
        _debug_print(msg, vid=eqf.vid)
        return
    _add_this_region(eqf)


def _subtract_this_dispatch(eqf):
    if not eqf.this_is_selected:
        msg = "Already Subtracted"
        eqf.alert = msg
        _debug_print(msg, vid=eqf.vid)
        return
    _substract_region_avoid_zero(eqf)


def _single_select_this_dispatch(eqf):
    if eqf.this_is_selected and eqf.num_selected == 1:
        msg = "Already Single Selected"
        eqf.alert = msg
        _debug_print(msg, vid=eqf.vid)
        return
    # even selections outside the ring will be cleared
    eqf.view.sel().clear()
    eqf.selected = [False] * eqf.size
    _add_this_region(eqf)


def _invert_select_this_dispatch(eqf):
    if eqf.size == 1:
        msg = "No Other Selections"
        eqf.alert = msg
        _debug_print(msg, vid=eqf.vid)
        return
    if (not eqf.this_is_selected) and (eqf.num_selected == eqf.size - 1):
        msg = "Already Invert Selected"
        eqf.alert = msg
        _debug_print(msg, vid=eqf.vid)
        return
    _pop_zero_region(eqf)
    _subtract_this_region(eqf)
    eqf.selected = [True] * eqf.size
    eqf.this_is_selected = False
    _add_selected_regions(eqf)


def _go_first_dispatch(eqf):
    dest_index = (eqf.size - 1) if eqf.reverse else 0
    notice_name = "Last" if eqf.reverse else "First"
    _context_aware_go(eqf, dest_index=dest_index, notice_name=notice_name)


def _go_back_dispatch(eqf):
    dest_index = eqf.init_index
    notice_name = "Back"
    _context_aware_go(eqf, dest_index=dest_index, notice_name=notice_name)


g_dispatches = (
    _noop_dispatch,                  # 0
    _goto_next_dispatch,             # 1
    _add_next_dispatch,              # 2
    _add_all_dispatch,               # 3
    _peek_next_dispatch,             # 4
    _peek_next_selected_dispatch,    # 5
    _add_this_dispatch,              # 6
    _subtract_this_dispatch,         # 7
    _single_select_this_dispatch,    # 8
    _invert_select_this_dispatch,    # 9
    _go_first_dispatch,              # 10
    _go_back_dispatch                # 11
)


def _dispatch(eqf):
    return g_dispatches[eqf.code](eqf)


# --- finalize helpers --------------------------------------------------------

def _show_this_region(eqf):
    eqf.view.show(eqf.this_region)


def _get_indicator():
    i = str(g_set.get("indicator", Def.INDICATOR)).lower()
    if i == "icon":
        return Indicator.ICON
    if i == "superimpose":
        return Indicator.SUPERIMPOSE
    if i == "none":
        return Indicator.NONE
    return Def.INDICATOR


"""
             Selected       No-Sel
------------------------------------
ICON
             icon=circle    icon=dot
             flags=HIDDEN   flags=0
SUPERIMPOSE
             icon=          icon=
             flags=0        flags=0
NONE
             icon=          icon=
             flags=HIDDEN   flags=0

* flags=0 is to draw
"""


def _set_indicator(eqf):
    if not eqf.init:
        return
    icon = ""
    flags = 0
    i = _get_indicator()
    if i == Indicator.ICON:
        if eqf.this_is_selected:
            icon = "circle"
            flags = sublime.HIDDEN
        else:
            icon = "dot"
    elif i == Indicator.NONE:
        if eqf.this_is_selected:
            flags = sublime.HIDDEN
    eqf.view.add_regions(key="exact_quick_find_indicator",
                         regions=[eqf.this_region], scope="string", icon=icon,
                         flags=flags)


def _get_selected_rank(eqf):
    nlt = sum(eqf.selected[:eqf.this_index])
    nge = sum(eqf.selected[eqf.this_index:])
    return (nlt + 1, nlt + nge)


def _set_ruler(eqf):
    if not eqf.init:
        return
    n = eqf.size
    i = eqf.this_index
    eqf.ruler = "Region {}/{}".format(i + 1, n)
    if eqf.selected[i]:
        j, m = _get_selected_rank(eqf)
        if m > 1:
            eqf.ruler += " (Selection {}/{})".format(j, m)


# --- finalize ----------------------------------------------------------------

def _finalize(eqf):
    _show_this_region(eqf)
    _set_indicator(eqf)
    _set_ruler(eqf)


# --- listener ----------------------------------------------------------------

def _trace_print_region(eqf, region, region_name):
    if region is not None:
        r1, c1, r2, c2 = _region_to_rowcol(eqf.view, region)
        _trace_print("{} = {} ((row={}, col={}), (row={}, col={}))"
                     .format(region_name, region, r1, c1, r2, c2), vid=eqf.vid)
    else:
        _trace_print("{} = None".format(region_name), vid=eqf.vid)


def _describe():
    nw = len(sublime.windows())
    nv = sum(len([s for s in w.sheets() if s.view()])
             for w in sublime.windows())
    ne = len(g_eqf_center)
    return "{} window{}, {} view{}, {} eqf object{}".format(
            nw, "s" * (nw > 1),
            nv, "s" * (nv > 1),
            ne, "s" * (ne > 1))


def _trace_print_listener(eqf, cmd):
    text = "None" if eqf.text is None else "\"{}\"".format(eqf.text)
    pattern = "None" if eqf.pattern is None else "\"{}\"".format(eqf.pattern)
    _trace_print("-" * 79, vid=eqf.vid)
    _trace_print("eqf.vid =", eqf.vid, vid=eqf.vid)
    _trace_print("eqf.last_text_cmd =", eqf.last_text_cmd, vid=eqf.vid)
    _trace_print("app.this_cmd_name =", cmd, vid=eqf.vid)
    _trace_print("eqf.init =", Init.to_str(eqf.init), vid=eqf.vid)
    _trace_print("eqf.last_code =", Code.to_str(eqf.last_code), vid=eqf.vid)
    _trace_print("eqf.code =", Code.to_str(eqf.code), vid=eqf.vid)
    _trace_print("eqf.reverse =", eqf.reverse, vid=eqf.vid)
    _trace_print("eqf.text =", text, vid=eqf.vid)
    _trace_print("eqf.pattern =", pattern, vid=eqf.vid)
    _trace_print("eqf.size =", eqf.size, vid=eqf.vid)
    _trace_print("eqf.reglets =", eqf.reglets, vid=eqf.vid)
    _trace_print("eqf.selected =", eqf.selected, vid=eqf.vid)
    _trace_print("eqf.num_selected =", eqf.num_selected, vid=eqf.vid)
    _trace_print("vew.num_selected =", len(eqf.view.sel()), vid=eqf.vid)
    _trace_print("eqf.init_index =", eqf.init_index, vid=eqf.vid)
    _trace_print("eqf.this_index =", eqf.this_index, vid=eqf.vid)
    _trace_print_region(eqf, eqf.orig_region, "eqf.orig_region")
    _trace_print_region(eqf, eqf.this_region, "eqf.this_region")
    _trace_print_region(eqf, eqf.zero_region, "eqf.zero_region")
    _trace_print("app.flags = \"{}\"".format(_get_flags()), vid=eqf.vid)
    _trace_print("eqf.ruler = \"{}\"".format(eqf.ruler), vid=eqf.vid)
    _trace_print("eqf.notice = \"{}\"".format(eqf.notice), vid=eqf.vid)
    _trace_print("eqf.alert = \"{}\"".format(eqf.alert), vid=eqf.vid)
    _trace_print("eqf.status = \"{}\"".format(eqf.status), vid=eqf.vid)
    _trace_print("app.describe =", _describe(), vid=eqf.vid)
    _trace_print("=" * 79, vid=eqf.vid)


class ExactQuickFindListener(sublime_plugin.EventListener):
    def on_activated(self, view):
        eqf = _get_eqf(view)
        _set_status(eqf)
        _trace_print_listener(eqf, "on_activated_async")

    def on_modified(self, view):
        eqf = _get_eqf(view)
        _reset_status(eqf)
        eqf.view.erase_regions("exact_quick_find_indicator")

    def on_pre_save(self, view):
        if g_set.get("save_flags_on_save", Def.SAVE_FLAGS):
            _save_settings()

    def on_post_text_command(self, view, cmd, args):
        eqf = _get_eqf(view)
        if cmd.startswith("exact_quick_find"):
            _trace_print_listener(eqf, cmd)
            _set_status(eqf)
        else:
            _reset_eqf(eqf)
            _reset_status(eqf)
            view.erase_regions("exact_quick_find_indicator")
        eqf.last_text_cmd = cmd

    def on_close(self, view):
        _del_eqf(view)


# --- commands ----------------------------------------------------------------

def _toggle_case():
    global g_case
    g_case = not g_case


def _toggle_whole_word():
    global g_word
    g_word = not g_word


def _toggle_wrap_scan():
    global g_wrap
    g_wrap = not g_wrap


class ExactQuickFindToggleCaseSensitiveCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        _toggle_case()
        eqf = _get_eqf(self.view)
        _reset_eqf(eqf)
        eqf.notice = "Case Sensitive" if g_case else "Case Insensitive"


class ExactQuickFindToggleWholeWordCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        _toggle_whole_word()
        eqf = _get_eqf(self.view)
        _reset_eqf(eqf)
        eqf.notice = "Whole Word" if g_word else "No Whole Word"


class ExactQuickFindToggleWrapScanCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        _toggle_wrap_scan()
        eqf = _get_eqf(self.view)
        eqf.notice = "Wrap Scan" if g_wrap else "No Wrap Scan"


class ExactQuickFindFlipFindFlagsCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        do_reset = False
        if g_set.get("flip_case", Def.FLIP_CASE):
            _toggle_case()
            do_reset = True
        if g_set.get("flip_whole_word", Def.FLIP_WORD):
            _toggle_whole_word()
            do_reset = True
        if g_set.get("flip_wrap_scan", Def.FLIP_WRAP):
            _toggle_wrap_scan()
        eqf = _get_eqf(self.view)
        if do_reset:
            _reset_eqf(eqf)
        eqf.notice = "Flip Find Flags"


class ExactQuickFindCommand(sublime_plugin.TextCommand):
    def run(self, edit, code, reverse=False):
        eqf = _get_eqf(self.view)
        if eqf.code not in {Code.GO_FIRST, Code.GO_BACK}:
            eqf.last_code = eqf.code
        eqf.code = code
        eqf.reverse = reverse
        if eqf.init != Init.BASIC:
            if not _basic_init(eqf):
                return
        else:
            _dispatch(eqf)
        _finalize(eqf)


class ExtendedExactQuickFindCommand(sublime_plugin.TextCommand):
    def run(self, edit, code, reverse=False):
        eqf = _get_eqf(self.view)
        eqf.last_code = eqf.code
        eqf.code = code
        eqf.reverse = reverse
        if eqf.init == Init.NOT_INIT:
            if not _extended_init(eqf):
                return
        _dispatch(eqf)
        _finalize(eqf)


class ExactQuickFindGotoNextCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        eqf = _get_eqf(self.view)
        args = {"code": Code.GOTO_NEXT}
        eqf.view.run_command("exact_quick_find", args)
        eqf.notice = "Move"


class ExactQuickFindGotoPrevCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        eqf = _get_eqf(self.view)
        args = {"code": Code.GOTO_NEXT, "reverse": True}
        eqf.view.run_command("exact_quick_find", args)
        eqf.notice = "Move"


class ExactQuickFindAddNextCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        eqf = _get_eqf(self.view)
        args = {"code": Code.ADD_NEXT}
        eqf.view.run_command("exact_quick_find", args)
        eqf.notice = "Add"


class ExactQuickFindAddPrevCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        eqf = _get_eqf(self.view)
        args = {"code": Code.ADD_NEXT, "reverse": True}
        eqf.view.run_command("exact_quick_find", args)
        eqf.notice = "Add"


class ExactQuickFindAddAllCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        eqf = _get_eqf(self.view)
        args = {"code": Code.ADD_ALL}
        eqf.view.run_command("exact_quick_find", args)
        eqf.notice = "Add All"


def _get_cmd(eqf):
    if ((eqf.init == Init.NOT_INIT and len(eqf.view.sel()) == 1)
            or eqf.init == Init.BASIC):
        return "exact_quick_find"
    else:
        return "extended_exact_quick_find"


class ExactQuickFindPeekNextCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        eqf = _get_eqf(self.view)
        cmd = _get_cmd(eqf)
        args = {"code": Code.PEEK_NEXT}
        eqf.view.run_command(cmd, args)
        eqf.notice = "Peek"


class ExactQuickFindPeekPrevCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        eqf = _get_eqf(self.view)
        cmd = _get_cmd(eqf)
        args = {"code": Code.PEEK_NEXT, "reverse": True}
        eqf.view.run_command(cmd, args)
        eqf.notice = "Peek"


class ExactQuickFindPeekNextSelectedCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        eqf = _get_eqf(self.view)
        cmd = _get_cmd(eqf)
        args = {"code": Code.PEEK_NEXT_SELECTED}
        eqf.view.run_command(cmd, args)
        eqf.notice = "Review"


class ExactQuickFindPeekPrevSelectedCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        eqf = _get_eqf(self.view)
        cmd = _get_cmd(eqf)
        args = {"code": Code.PEEK_NEXT_SELECTED, "reverse": True}
        eqf.view.run_command(cmd, args)
        eqf.notice = "Review"


class ExactQuickFindAddThisCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        eqf = _get_eqf(self.view)
        cmd = _get_cmd(eqf)
        args = {"code": Code.ADD_THIS}
        eqf.view.run_command(cmd, args)
        eqf.notice = "Add"


class ExactQuickFindSubtractThisCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        eqf = _get_eqf(self.view)
        cmd = _get_cmd(eqf)
        args = {"code": Code.SUBTRACT_THIS}
        eqf.view.run_command(cmd, args)
        eqf.notice = "Subtract"


class ExactQuickFindSingleSelectThisCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        eqf = _get_eqf(self.view)
        cmd = _get_cmd(eqf)
        args = {"code": Code.SINGLE_SELECT_THIS}
        eqf.view.run_command(cmd, args)
        eqf.notice = "Single Select"


class ExactQuickFindInvertSelectThisCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        eqf = _get_eqf(self.view)
        cmd = _get_cmd(eqf)
        args = {"code": Code.INVERT_SELECT_THIS}
        eqf.view.run_command(cmd, args)
        eqf.notice = "Invert Select"


class ExactQuickFindGoFirstCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        eqf = _get_eqf(self.view)
        cmd = _get_cmd(eqf)
        args = {"code": Code.GO_FIRST}
        eqf.view.run_command(cmd, args)
        eqf.notice = "First"


class ExactQuickFindGoLastCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        eqf = _get_eqf(self.view)
        cmd = _get_cmd(eqf)
        args = {"code": Code.GO_FIRST, "reverse": True}
        eqf.view.run_command(cmd, args)
        eqf.notice = "Last"


class ExactQuickFindGoBackCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        eqf = _get_eqf(self.view)
        cmd = _get_cmd(eqf)
        args = {"code": Code.GO_BACK}
        eqf.view.run_command(cmd, args)
        eqf.notice = "Back"
