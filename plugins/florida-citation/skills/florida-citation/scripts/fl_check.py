"""The engine behind `fl_cite.py check`: read a document, find the citations Rule 9.800 covers,
decide which tier governs each one, and run the check records in data/checks.json against them.

  python fl_cite.py check brief.docx
  python fl_cite.py check brief.pdf --json          (runs pdftotext, if it's installed)
  pdftotext -enc UTF-8 brief.pdf - | python fl_cite.py check - --json

Every finding names its authority and has one of three severities: error (clearly departs from
Rule 9.800's form), check (probably wrong, or right in some contexts; the agent decides), or
unrecognized (a citation outside this script's patterns, or one another tier governs; the agent
handles it). Standard library only.
"""

import bisect
import datetime as dt
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import fl_cite as fc

TIER_RULE = "Rule 9.800"
TIER_BLUEBOOK = "Bluebook system (Indigo Book)"
TIER_FSM = "Florida Style Manual"
SEVERITIES = ("error", "check", "unrecognized")

MONTHS = {"Jan.": 1, "January": 1, "Feb.": 2, "February": 2, "Mar.": 3, "March": 3, "Apr.": 4, "April": 4,
          "May": 5, "June": 6, "July": 7, "Aug.": 8, "August": 8, "Sept.": 9, "Sep.": 9, "September": 9,
          "Oct.": 10, "October": 10, "Nov.": 11, "November": 11, "Dec.": 12, "December": 12}
MONTH_RX = "|".join(re.escape(m) for m in sorted(MONTHS, key=len, reverse=True))
FULL_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"


# ---------------------------------------------------------------- reading input

class Source:
    """A document as read: text with form feeds as page breaks, plus what the reader learned.

    emphasis: (start, end) ranges of italic or underlined text, or None when the format loses
    typeface (plain text, PDF extractions). line_labels: a label per line ("para. 3", "fn. 2")
    for formats where "line" means something else. blocks: (start, end) ranges of block quotations
    the format's layout shows (a PDF's indentation, a .docx paragraph's indents or style), or None
    when it shows none; then the text alone decides. footnote_starts: offsets where a page's
    footnotes begin, as its layout shows them, or None; then the text alone decides.
    """

    def __init__(self, text, name="<text>", kind="txt", emphasis=None, line_labels=None, blocks=None,
                 footnote_starts=None):
        self.text = text.replace("\r\n", "\n").replace("\r", "\n")
        self.name = name
        self.kind = kind
        self.emphasis = emphasis
        self.line_labels = line_labels
        self.blocks = blocks
        self.footnote_starts = footnote_starts
        self.cut = None                  # (last page kept, pages in all) after first_pages


def first_pages(source, n):
    """The Source cut after its nth page (--last-page), so exhibits or an appendix after the document
    aren't checked. Offsets before the cut are unchanged, so the layout's blocks and footnotes still fit."""
    if source.kind == "docx":
        sys.exit("--last-page works on PDFs and text with form feeds; a .docx's pages aren't fixed. "
                 "Save the document without its exhibits, or as a PDF, and check that.")
    if n < 1:
        sys.exit("--last-page takes a page number of 1 or more.")
    ff = [i for i, ch in enumerate(source.text) if ch == "\f"]
    if not ff:
        sys.exit("--last-page needs a document with pages: a PDF, or text with a form feed between pages.")
    total = len(ff) + (1 if source.text[ff[-1] + 1:].strip() else 0)
    if n >= total:
        return source
    end = ff[n - 1] + 1
    cut = Source(source.text[:end], source.name, source.kind, emphasis=source.emphasis,
                 blocks=[b for b in source.blocks if b[0] < end] if source.blocks is not None else None,
                 footnote_starts=[f for f in source.footnote_starts if f < end]
                 if source.footnote_starts is not None else None)
    cut.cut = (n, total)
    return cut


def decode(data):
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def read_source(path):
    if path == "-":
        return Source(decode(sys.stdin.buffer.read()), "<stdin>", "stdin")
    p = Path(path)
    if not p.is_file():
        sys.exit(f"no such file: {path}")
    suffix = p.suffix.lower()
    if suffix == ".pdf":
        return read_pdf(p)
    if suffix == ".doc":
        sys.exit("Word 97-2003 .doc files can't be read; save the file as .docx and check that.")
    if suffix == ".docx":
        return read_docx(p)
    text = decode(p.read_bytes())
    if suffix in (".md", ".markdown"):
        return read_md(text, str(p))
    return Source(text, str(p), "txt")


PIPE_INSTEAD = ("Or extract the text another way, with a form feed between pages (pdftotext -nodiag drops a "
                "diagonal watermark), and pipe it in:\n"
                "  <your extractor> FILE.pdf | python3 scripts/fl_cite.py check -")
NO_PDFTOTEXT = ("Reading a PDF needs pdftotext (Poppler or Xpdf), and it isn't on PATH. To install it:\n"
                "  macOS:          brew install poppler\n"
                "  Debian, Ubuntu: sudo apt-get install poppler-utils\n"
                "  Fedora:         sudo dnf install poppler-utils\n"
                "  Windows:        Git for Windows includes it (run from Git Bash), or scoop install poppler\n"
                + PIPE_INSTEAD)
NO_OCRMYPDF = ("To install OCRmyPDF and Tesseract, the OCR engine it runs:\n"
               "  macOS:          brew install ocrmypdf\n"
               "  Debian, Ubuntu: sudo apt-get install ocrmypdf\n"
               "  Fedora:         sudo dnf install ocrmypdf tesseract-osd\n"
               "  Windows:        winget install -e --id tesseract-ocr.tesseract, then winget install -e --id\n"
               "                  astral-sh.uv and uv tool install ocrmypdf (Ghostscript is recommended too)\n"
               "OCR misreads some characters (Id. as ld., 5th as Sth, a dropped hyphen in a page range), so read "
               "each finding's pinpoint against the page.")
SCANNED_PAGE_CHARS = 100        # most pages with less text than this means a scanned PDF
EMPTY_PAGE_CHARS = 20            # a page with less than this is listed in the report's notes
# A page that is only a slip sheet before an exhibit or appendix, and a case database's print footer.
SLIP_SHEET = re.compile(r"(?i)(?:exhibit|exh?\.|attachment|appendix|app\.|tab)\s*[\w.\-]{0,6}")
PRINTOUT = re.compile(r"(?i)\b(Westlaw)\b[^\n]{0,25}\bThomson Reuters\b|\bmember of the (LexisNexis) Group\b")


NODIAG_SLACK = 60                # characters a page may lose to -nodiag: a watermark's worth ...
NODIAG_KEEP = 0.9                # ... or this share of the page's characters, whichever is more


def _pdftotext(exe, path, layout=False, nodiag=True):
    """pdftotext on path, in reading order or -layout, discarding diagonal text (-nodiag) when asked: a clerk
    portal's corner-to-corner watermark (NOT A CERTIFIED COPY) would otherwise scatter its letters into the
    body's lines and citations. A build too old for -nodiag prints its usage and stops; then run without it."""
    base = [exe, "-enc", "UTF-8"] + (["-layout"] if layout else [])
    if nodiag:
        r = subprocess.run(base + ["-nodiag", str(path), "-"], capture_output=True, timeout=600)
        if not (r.returncode != 0 and b"Usage:" in r.stderr + r.stdout):
            return r
    return subprocess.run(base + [str(path), "-"], capture_output=True, timeout=600)


def _ink(text):
    return len(re.sub(r"\s", "", text))


def _without_diagonal(text, nodiag):
    """Is the -nodiag extraction safe to use in place of the full one: the same pages, each losing no more
    than a watermark's worth? Both pdftotext builds have been seen to drop a page number beside a diagonal
    stamp in a hand-built PDF, so a page that loses more than that keeps every character."""
    full, less = text.split("\f"), nodiag.split("\f")
    if len(full) != len(less):
        return False
    for a, b in zip(full, less):
        lost = _ink(a) - _ink(b)
        if lost > NODIAG_SLACK and lost > (1 - NODIAG_KEEP) * _ink(a):
            return False
    return True


def read_pdf(path):
    """A PDF's text through pdftotext, in reading order (-layout splits citations: extraction.md), with a
    form feed after each page, and its block quotations from a second, -layout pass. A scanned PDF, an
    encrypted one, or a pdftotext error ends with a message."""
    exe = shutil.which("pdftotext")
    if not exe:
        sys.exit(NO_PDFTOTEXT)
    try:
        r = _pdftotext(exe, path, nodiag=False)    # every character the PDF has
    except subprocess.TimeoutExpired:
        sys.exit(f"pdftotext took more than 10 minutes on {path} and was stopped.\n" + PIPE_INSTEAD)
    except OSError as e:
        sys.exit(f"couldn't run pdftotext ({exe}): {e}\n" + PIPE_INSTEAD)
    err = decode(r.stderr).strip()
    if r.returncode != 0:
        last = err.splitlines()[-1] if err else f"exit code {r.returncode}"
        if "password" in err.lower() or "encrypt" in err.lower():
            sys.exit(f"{path} is encrypted (password-protected), so pdftotext can't read it ({last}). "
                     "Open it with the password and save an unprotected copy, or extract the text another way.\n"
                     + PIPE_INSTEAD)
        if r.returncode == 3:
            sys.exit(f"{path} forbids copying its text, and this pdftotext honors that ({last}). "
                     "Poppler's pdftotext doesn't, or extract the text another way.\n" + PIPE_INSTEAD)
        sys.exit(f"pdftotext couldn't read {path}: {last}. If it's damaged, try saving a fresh copy.\n"
                 + PIPE_INSTEAD)
    text = decode(r.stdout)
    nodiag = False
    try:                               # without diagonal text, if that takes nothing but the stamp
        r2 = _pdftotext(exe, path)
        if r2.returncode == 0 and _without_diagonal(text, decode(r2.stdout)):
            text, nodiag = decode(r2.stdout), True
    except (subprocess.TimeoutExpired, OSError):
        pass
    pages = text.split("\f")
    if len(pages) > 1 and not pages[-1].strip():
        pages.pop()                    # pdftotext ends every page, the last included, with a form feed
    sizes = [len(re.sub(r"\s", "", pg)) for pg in pages]
    chars = sum(sizes)
    if sum(1 for n in sizes if n < SCANNED_PAGE_CHARS) * 2 > len(sizes):
        ocr = path.with_name(path.stem + "-ocr.pdf")
        sys.exit(f"{path} has almost no text ({chars} characters on {len(pages)} page"
                 f"{'s' if len(pages) != 1 else ''}), so it's probably scanned images. It needs OCR first, "
                 "which this script doesn't do. OCRmyPDF does it on this computer, with nothing uploaded:\n"
                 f'  ocrmypdf --output-type pdf --deskew "{path}" "{ocr}"\n'
                 f'then check "{ocr}".\n' + NO_OCRMYPDF)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = feet = None
    try:                               # a second pass, only to see layout; citations are read above
        r = _pdftotext(exe, path, layout=True, nodiag=nodiag)
        if r.returncode == 0:
            layout = decode(r.stdout).replace("\r\n", "\n").replace("\r", "\n")
            blocks = layout_blocks(text, layout)
            feet = layout_footnotes(text, layout)
    except (subprocess.TimeoutExpired, OSError):
        pass
    return Source(text, str(path), "pdf", blocks=blocks, footnote_starts=feet)


LAYOUT_MIN_CHARS = 30            # a line with this many non-space characters helps set the page's margins
LAYOUT_INDENT = 4                # columns in from the left margin that make a line indented
LAYOUT_CENTERED = 8              # a run's first line this far right of the next is a centered heading
LAYOUT_HEADING = 45              # ... if it's this short; a quotation's indented first line is full width
# A table of contents' dot leaders: long, or short before page numbers (". . . ." alone is an ellipsis).
LAYOUT_LEADER = re.compile(r"(?:\. ?){6,}|…{3,}|_{4,}|\.{3,} *\d[\d, \-–]*$")
LAYOUT_FURNITURE = 40            # a short line this far right of the margin is a running header
# The line after a block quote, when it gives the quotation's source: a case (full or short), a
# reporter cite, Id., a statute or rule, or a record cite.
LAYOUT_CITE_LINE = re.compile(
    r"(?:(?:See|See also|Cf\.|Accord|But see|E\.g\.),? )?(?:"
    r"[A-Z][\w.'&,\- ]{0,80}? v\. "
    r"|(?:In re|Ex parte) "
    r"|[A-Z][\w.'&-]*(?: [\w.'&-]+){0,6}, \d{1,4} [A-Z]"
    r"|\d{1,4} [A-Z][A-Za-z.' ]{0,25} \d"
    r"|[Ii]d\.|§|Art\. [IVX]|Fla\. (?:Stat|R\.)"
    r"|\(?(?:R|T|A|SA|App|Tr|Ex|Doc|ECF|Dkt)\.? ?(?:No\. ?)?-?\d)")


def layout_blocks(text, layout):
    """Ranges in reading-order text of the block quotations pdftotext -layout shows.

    Layout proposes: runs of two or more consecutive lines indented from the page's left margin.
    Body text runs from the margin, a paragraph's indented first line stands alone, and a table of
    contents' entries carry dot leaders. Only the left indent is measured: column counts can't show
    the right margin (a proportional font fits more narrow letters in a line), and -layout drops too
    many blank lines to show spacing. Context confirms: a scanned page's body can drift right by
    a few columns, so a run (or a group of them: a quotation's paragraphs, or its two halves across
    a page break) counts only when the line before it ends with a colon ("the court observed:") or
    the line after it gives a source (Smith v. ..., 594 So. 2d 292, Id., R. 60). Each run is found
    in the reading-order page by its characters, ignoring whitespace (the two modes space text
    differently). None when the page counts differ; [] when nothing qualifies."""
    paired = _paired_pages(text, layout)
    if paired is None:
        return None
    rpages, lpages = paired
    pages = []
    for lp in lpages:
        lines = []
        for line in lp.split("\n"):
            line = line.expandtabs().rstrip()
            lines.append((len(line) - len(line.lstrip()), line.strip()))
        pages.append((lines, [ind for ind, s in lines if len(s.replace(" ", "")) >= LAYOUT_MIN_CHARS]))
    runs = []
    for page, (lines, wide) in enumerate(pages):
        if len(wide) >= 3:
            runs += [dict(r, page=page) for r in _page_layout_runs(lines, _left_margin(wide))]
    # Group a quotation's runs: paragraphs with only blank lines between, or the run ending one page
    # and the run starting the next.
    groups = []
    for r in runs:
        g = groups[-1] if groups else None
        if g and ((r["page"] == g[-1]["page"] and g[-1]["after_at"] == r["start"])
                  or (r["page"] == g[-1]["page"] + 1 and g[-1]["after"] is None and r["intro"] is None)):
            g.append(r)
        else:
            groups.append([r])
    keep = {}
    for g in groups:
        intro, after = g[0]["intro"], g[-1]["after"]
        if re.search(r"\?[\"'”’)\]]*$", g[-1]["text"]):
            continue                   # an issue statement ("ISSUE I: Whether the court ...?"), set like a quote
        if (intro or "").rstrip("\"'”’)]").endswith(":") or LAYOUT_CITE_LINE.match(after or ""):
            for r in g:
                keep.setdefault(r["page"], []).append(r["text"])
    out, offset = [], 0
    for page, rp in enumerate(rpages):
        out += [(offset + a, offset + b) for a, b in _locate_runs(rp, keep.get(page, []))]
        offset += len(rp) + 1
    return out


def _paired_pages(text, layout):
    """The reading-order and -layout texts split into pages, trailing blank pages dropped, or None
    when the page counts differ."""
    rpages, lpages = text.split("\f"), layout.split("\f")
    while len(lpages) > len(rpages) and not lpages[-1].strip():
        lpages.pop()
    while len(rpages) > len(lpages) and not rpages[-1].strip():
        rpages.pop()
    if len(rpages) != len(lpages):
        return None
    return rpages, lpages


# A footnote's first line: "2 See ...", "2.   See ...", or Poppler's "2See ..." (but not "60(b)").
LAYOUT_FOOTNOTE = re.compile(r"(\d{1,3})(?:\.?\s+|(?=[A-Z]))([A-Z\"'“‘(\[§].*)")
FOOTNOTE_OPENS = re.compile(r"[A-Z\"'“‘(\[§]")
FOOTNOTE_NEEDLE = 40             # characters of a footnote's opening matched in reading-order text
LINE_NUMBERED = 0.3              # a page with this share of its lines opening with a number is numbered


def footnote_marker(n, text):
    """Does footnote number n appear in text as a marker: glued to a word or punctuation
    ("ordinances.2 See"), or one space after a period or a closing mark, where Poppler sets a
    superscript ("Rule 1.530. 6 See", "relief.” 4 The")? A number after a word or a comma and a space
    is a count or a pinpoint ("count 2 is", "at 10, 11")."""
    return bool(re.search(r"(?:[A-Za-z.,;:)\]\"'”’]|[.;)\]\"'”’] )" + n + r"(?=\s|$)", text))


def footnote_line(lines, k, expected=None, at_margin=False):
    """Does line k of a page's lines (stripped strings) open its footnotes: a number, then a capital
    or the like, that appears earlier on the page as a marker (footnote_marker)?

    The document's next footnote number (expected, or the one after, if one was missed) may also
    follow a word or a comma and a space, as Poppler sets a superscript ("the Williams 4 rule", "the
    rule, 4 the"), when the line after it is back at the left margin (at_margin), as a footnote's
    second line is and an indented quotation's isn't ("within 3 years" over a policy's "3. Duties").

    Not a line of a table of contents or authorities (dot leaders), a citation wrapped onto the line
    ("161 So. 3d at 1272"), a heading in capitals, an item after one numbered the same way above it
    ("2. The" under "1. The": a list, numbered paragraphs), or any line of a page whose lines are
    numbered (a transcript, pleading paper)."""
    m = LAYOUT_FOOTNOTE.fullmatch(lines[k])
    if not m:
        return False
    body = m.group(2)
    if (LAYOUT_LEADER.search(body) or WRAPPED_CITE.match(lines[k])
            or (sum(c.isalpha() for c in body[:40]) >= 4 and body[:40] == body[:40].upper())):
        return False
    if sum(1 for s in lines if re.match(r"\d{1,2}\s", s)) >= LINE_NUMBERED * len(lines) and len(lines) >= 10:
        return False
    n = int(m.group(1))
    if n > 1:
        dot = r"\.\s*" if lines[k][len(m.group(1))] == "." else r"(?!\.)\s*"
        prev = re.compile(str(n - 1) + dot + FOOTNOTE_OPENS.pattern)
        if any(prev.match(s) for s in lines[:k]):
            return False
    above = "\n".join(lines[:k])
    if footnote_marker(m.group(1), above):
        return True
    return (at_margin and expected is not None and expected <= n <= expected + 1
            and bool(re.search(r"[A-Za-z,] " + m.group(1) + r"(?=\s|$)", above)))


def last_footnote(lines, k):
    """The number of the last footnote on a page whose footnotes open at line k: the numbers that
    follow in sequence at the starts of the lines below."""
    last = int(LAYOUT_FOOTNOTE.fullmatch(lines[k]).group(1))
    for s in lines[k + 1:]:
        m = LAYOUT_FOOTNOTE.fullmatch(s)
        if m and int(m.group(1)) == last + 1:
            last += 1
    return last


def layout_footnotes(text, layout):
    """Offsets in reading-order text where each page's footnotes begin, found in the -layout pass.

    Extractors order a page's text differently. Poppler can move a footnote's number away from its
    text (to the line above, or after the footnote) and set a marker off by a space ("1.530. 6 See"),
    where Xpdf keeps "1.530.6 See" and "6 By way of ..."; in -layout, both put the number at the start
    of the footnote's first line, or on a line of its own beside it. A footnote starts at a line,
    below the page's first, that footnote_line accepts. Its opening characters, without the number,
    are then found in the reading-order page, ignoring whitespace. None when the page counts differ."""
    paired = _paired_pages(text, layout)
    if paired is None:
        return None
    rpages, lpages = paired
    out, offset, last = [], 0, 0
    for rp, lp in zip(rpages, lpages):
        rows = []
        for line in lp.split("\n"):
            line = line.expandtabs().rstrip()
            if line.strip():
                rows.append((len(line) - len(line.lstrip()), line.strip()))
        # Poppler can set a footnote's number on a line of its own, above or below the footnote's
        # first line; rejoin them. (A page number is the page's last line.)
        for j in range(len(rows) - 2, -1, -1):
            if not re.fullmatch(r"\d{1,3}\.?", rows[j][1]):
                continue
            if FOOTNOTE_OPENS.match(rows[j + 1][1]):
                rows[j:j + 2] = [(rows[j][0], rows[j][1] + " " + rows[j + 1][1])]
            elif j and FOOTNOTE_OPENS.match(rows[j - 1][1]) and not LAYOUT_FOOTNOTE.fullmatch(rows[j - 1][1]):
                rows[j - 1:j + 1] = [(rows[j - 1][0], rows[j][1] + " " + rows[j - 1][1])]
        lines = [s for _, s in rows]
        wide = [ind for ind, s in rows if len(s.replace(" ", "")) >= LAYOUT_MIN_CHARS]
        margin = _left_margin(wide) if wide else 0
        for k in range(1, len(lines)):
            # The next line back at the margin, or none: the page's end, or the next footnote.
            m = LAYOUT_FOOTNOTE.fullmatch(lines[k])
            nxt = lines[k + 1] if k + 1 < len(lines) else ""
            at_margin = (not nxt or rows[k + 1][0] <= margin + 1 or PAGE_NUMBER.match(nxt)
                         or bool(m and re.match(str(int(m.group(1)) + 1) + r"\b", nxt)))
            if not footnote_line(lines, k, last + 1, at_margin):
                continue
            last = last_footnote(lines, k)
            m = LAYOUT_FOOTNOTE.fullmatch(lines[k])
            own = [m.group(2)]                     # the footnote's own text: its number may move too
            for s in lines[k + 1:k + 3]:
                if LAYOUT_FOOTNOTE.fullmatch(s):
                    break
                own.append(s)
            needle = re.sub(r"\s", "", " ".join(own))[:FOOTNOTE_NEEDLE]
            keep = [j for j, ch in enumerate(rp) if not ch.isspace()]
            at = "".join(rp[j] for j in keep).rfind(needle)
            if at >= 0:
                out.append(offset + keep[at])
                break
        offset += len(rp) + 1
    return out


def _left_margin(indents):
    """A page's left margin: the leftmost indent at least two of its full lines start at (the body,
    even on a page that is nearly all quotation), allowing a column of OCR jitter. A single stray
    line further left (a header, an OCR fragment, a scanned page's drift) doesn't set it."""
    for v in sorted(set(indents)):
        n = sum(1 for i in indents if v <= i <= v + 1)
        if n >= 2 and n >= 0.05 * len(indents):
            return v
    return min(indents)


def _page_layout_runs(lines, left):
    """A page's runs of indented lines: {start, text, intro, after, after_at}, where intro and after
    are the nearest lines of text above and below on the page (None at its edge; page numbers and
    running headers skipped) and after_at is the after line's index."""
    def furniture(ind, s):
        return bool(PAGE_NUMBER.match(s)) or (ind >= left + LAYOUT_FURNITURE and len(s) < 40)

    def near(k, step):
        while 0 <= k < len(lines):
            ind, s = lines[k]
            if s and not furniture(ind, s):
                return k
            k += step
        return None

    runs, cur = [], []
    for k, (ind, s) in enumerate(lines + [(0, "x")]):
        if not s:
            continue                   # -layout puts blank lines anywhere, inside quotations too
        if ind >= left + LAYOUT_INDENT and not LAYOUT_LEADER.search(s) and not furniture(ind, s):
            cur.append(k)
            continue
        # A last line set off by a blank line above, with a margin line right below it, is a body
        # paragraph's indented first line, not the quotation's end.
        if len(cur) >= 2 and not lines[cur[-1] - 1][1] and k == cur[-1] + 1:
            cur.pop()
        # Body text sits at the margin and never joins a run; what can is a heading just above it. A
        # centered one sits far right of the run's next line and is short: trim it. A quotation's own
        # first line can sit as far right, with a paragraph indent on top of the block's, but it runs
        # the full width (field test 4). (A left-aligned heading over a paragraph's indented first
        # line has no colon before it or source after it, below.)
        if (len(cur) >= 2 and lines[cur[0]][0] > lines[cur[1]][0] + LAYOUT_CENTERED
                and len(lines[cur[0]][1]) < LAYOUT_HEADING):
            cur.pop(0)
        # A run that carries on the sentence of a margin line just above it is a hanging indent (a
        # table of authorities entry: "Carr v. Dunn," over its cite). -layout drops blank lines,
        # so a quotation right under a finished sentence still counts.
        above = lines[cur[0] - 1][1] if cur and cur[0] > 0 else ""
        if above and not re.search(r"[.:;?!\"'”’)\]]$", above):
            cur = []
        if len(cur) >= 2:
            i, a = near(cur[0] - 1, -1), near(cur[-1] + 1, 1)
            runs.append({"start": cur[0], "text": " ".join(lines[j][1] for j in cur),
                         "intro": lines[i][1] if i is not None else None,
                         "after": lines[a][1] if a is not None else None, "after_at": a})
        cur = []
    return runs


def _locate_runs(rp, runs):
    """(start, end) offsets in a reading-order page of runs of -layout text, matched by characters."""
    if not runs:
        return []
    keep = [j for j, ch in enumerate(rp) if not ch.isspace()]
    hay = "".join(rp[j] for j in keep)
    found, start = [], 0
    for run in runs:
        needle = re.sub(r"\s", "", run)
        k = hay.find(needle, start)
        if k >= 0:
            a, b = k, k + len(needle)
        else:                          # the modes differ inside the run: match its two ends
            a = hay.find(needle[:40], start)
            b = hay.find(needle[-40:], a) if a >= 0 else -1
            if b < 0:
                continue
            b += len(needle[-40:])
            if not 0.8 * len(needle) <= b - a <= 1.25 * len(needle):
                continue
        found.append((keep[a], keep[b - 1] + 1))
        start = b
    return found


MD_EMPHASIS = re.compile(r"(?<![\w*\\])(\*{1,3}|_{1,3})(?=[^\s*_])([^\n]*?[^\s*_\\])\1(?![\w*])")


def read_md(text, name):
    """Drop Markdown emphasis markers, remembering *italic* and ***bold italic*** spans for 9.800(q)."""
    out, spans, pos, n = [], [], 0, 0
    for m in MD_EMPHASIS.finditer(text):
        out.append(text[pos:m.start()])
        n += m.start() - pos
        inner = m.group(2)
        if len(m.group(1)) != 2:          # ** and __ are bold, not italic
            spans.append((n, n + len(inner)))
        out.append(inner)
        n += len(inner)
        pos = m.end()
    out.append(text[pos:])
    return Source("".join(out), name, "md", emphasis=spans)


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
OFF = ("0", "false", "off", "none")


def _on(elem, tag):
    """Is a w:i / w:u style toggle present and on?"""
    e = elem.find(W + tag) if elem is not None else None
    if e is None:
        return None
    return e.get(W + "val", "true").lower() not in OFF


def emphasis_styles(styles_xml):
    """Ids of character styles that italicize or underline, following basedOn."""
    root = ET.fromstring(styles_xml)
    own, parent = {}, {}
    for s in root.iter(W + "style"):
        sid = s.get(W + "styleId")
        rpr = s.find(W + "rPr")
        flags = [_on(rpr, "i"), _on(rpr, "u")]
        own[sid] = True if any(flags) else (False if flags != [None, None] else None)
        b = s.find(W + "basedOn")
        parent[sid] = b.get(W + "val") if b is not None else None
    out = set()
    for sid in own:
        cur, seen = sid, set()
        while cur and cur not in seen:
            seen.add(cur)
            if own.get(cur) is not None:
                if own[cur]:
                    out.add(sid)
                break
            cur = parent.get(cur)
    return out


QUOTE_STYLE = re.compile(r"quot|block", re.I)       # Word's "Quote", "Block Text"; firms' "Block Quote"
BLOCK_TWIPS = 360                                     # a quarter inch in from each margin


def _indents(ppr):
    """(left, right, hanging) twips a w:pPr sets, None for each it leaves alone."""
    ind = ppr.find(W + "ind") if ppr is not None else None
    if ind is None:
        return None, None, None

    def twips(*names):
        for n in names:
            v = ind.get(W + n)
            if v is not None and re.fullmatch(r"-?\d+", v):
                return int(v)
        return None
    return twips("left", "start"), twips("right", "end"), twips("hanging")


def paragraph_styles(styles_xml):
    """{paragraph style id: (named like a block quote, left, right, hanging)}, following basedOn."""
    root = ET.fromstring(styles_xml)
    own, parent = {}, {}
    for s in root.iter(W + "style"):
        if s.get(W + "type") not in (None, "paragraph"):
            continue
        sid = s.get(W + "styleId")
        name = s.find(W + "name")
        own[sid] = (bool(QUOTE_STYLE.search(name.get(W + "val", "") if name is not None else "")),
                    *_indents(s.find(W + "pPr")))
        b = s.find(W + "basedOn")
        parent[sid] = b.get(W + "val") if b is not None else None
    out = {}
    for sid in own:
        quote, vals, cur, seen = False, [None, None, None], sid, set()
        while cur in own and cur not in seen:
            seen.add(cur)
            quote = quote or own[cur][0]
            vals = [v if v is not None else p for v, p in zip(vals, own[cur][1:])]
            cur = parent.get(cur)
        out[sid] = (quote, *vals)
    return out


def is_block_paragraph(ppr, styles):
    """A block quotation by its formatting: a quote style, or indented from both margins (a numbered or
    hanging-indent paragraph is a list item, not a quote)."""
    if ppr is not None and ppr.find(W + "numPr") is not None:
        return False
    st = ppr.find(W + "pStyle") if ppr is not None else None
    quote, left, right, hanging = styles.get(st.get(W + "val") if st is not None else "Normal", (False, None, None, None))
    d_left, d_right, d_hanging = _indents(ppr)
    left = d_left if d_left is not None else left
    right = d_right if d_right is not None else right
    hanging = d_hanging if d_hanging is not None else hanging
    if hanging:
        return False
    return quote or ((left or 0) >= BLOCK_TWIPS and (right or 0) >= BLOCK_TWIPS)


class _Builder:
    def __init__(self):
        self.parts, self.n, self.emph, self.labels, self.label = [], 0, [], [], "para. 1"
        self.blocks = []

    def add(self, s, emph=False):
        if not s:
            return
        if emph:
            self.emph.append((self.n, self.n + len(s)))
        for ch in s:
            if ch == "\n":
                self.labels.append(self.label)
        self.parts.append(s)
        self.n += len(s)


def read_docx(path):
    """Body text of a .docx, one line per paragraph, footnotes inline after their reference,
    page breaks as form feeds, and italic or underlined spans. Field codes (TOA entries) and
    deleted text are skipped."""
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        sys.exit(f"can't open {path} as a .docx: {e}")
    with z:
        names = set(z.namelist())
        if "word/document.xml" not in names:
            sys.exit(f"{path} has no word/document.xml; is it really a .docx?")
        styles = emphasis_styles(z.read("word/styles.xml")) if "word/styles.xml" in names else set()
        pstyles = paragraph_styles(z.read("word/styles.xml")) if "word/styles.xml" in names else {}
        notes = {}
        for part, tag in (("word/footnotes.xml", "footnote"), ("word/endnotes.xml", "endnote")):
            if part in names:
                for fn in ET.fromstring(z.read(part)).iter(W + tag):
                    notes[(tag, fn.get(W + "id"))] = fn
        body = ET.fromstring(z.read("word/document.xml")).find(W + "body")
    b = _Builder()
    counter = {"para": 0, "footnote": 0, "endnote": 0}

    def runs(node):
        for child in node:
            if child.tag == W + "r":
                yield child
            elif child.tag in (W + "hyperlink", W + "ins", W + "smartTag", W + "sdt", W + "sdtContent",
                               W + "fldSimple", W + "customXml"):
                yield from runs(child)

    def paragraphs(node):
        for child in node:
            if child.tag == W + "p":
                yield child
            elif child.tag in (W + "tbl", W + "tr", W + "tc", W + "sdt", W + "sdtContent", W + "customXml"):
                yield from paragraphs(child)

    def emit_paragraph(p, in_note):
        if not in_note:
            counter["para"] += 1
            b.label = f"para. {counter['para']}"
        ppr = p.find(W + "pPr")
        if ppr is not None and _on(ppr, "pageBreakBefore"):
            b.add("\f")
        block_start = b.n if is_block_paragraph(ppr, pstyles) else None
        in_field = False
        for r in runs(p):
            rpr = r.find(W + "rPr")
            style = rpr.find(W + "rStyle") if rpr is not None else None
            emph = bool(_on(rpr, "i") or _on(rpr, "u")
                        or (style is not None and style.get(W + "val") in styles and _on(rpr, "i") is not False))
            for el in r:
                tag = el.tag[len(W):] if el.tag.startswith(W) else el.tag
                if tag == "fldChar":
                    kind = el.get(W + "fldCharType")
                    in_field = kind == "begin" or (in_field and kind not in ("separate", "end"))
                elif in_field:
                    continue
                elif tag == "t":
                    b.add(el.text or "", emph)
                elif tag == "tab":
                    b.add("\t")
                elif tag in ("br", "cr"):
                    b.add("\f" if el.get(W + "type") == "page" else "\n")
                elif tag == "noBreakHyphen":
                    b.add("-")
                elif tag in ("footnoteReference", "endnoteReference"):
                    kind = tag[:-len("Reference")]
                    note = notes.get((kind, el.get(W + "id")))
                    if note is not None and not in_note:
                        counter[kind] += 1
                        saved = b.label
                        if block_start is not None and b.n > block_start:
                            b.blocks.append((block_start, b.n))     # the note isn't part of the quotation
                        b.add("\n")
                        b.label = f"{'fn' if kind == 'footnote' else 'endnote'} {counter[kind]}"
                        for np_ in paragraphs(note):
                            emit_paragraph(np_, True)
                        b.label = saved
                        if block_start is not None:
                            block_start = b.n
        if block_start is not None and b.n > block_start:
            b.blocks.append((block_start, b.n))
        b.add("\n")

    for p in paragraphs(body):
        emit_paragraph(p, False)
    b.labels.append(b.label)
    return Source("".join(b.parts), str(path), "docx", emphasis=b.emph, line_labels=b.labels,
                  blocks=b.blocks or None)


# ---------------------------------------------------------------- pages and normalized text

PAGE_NUMBER = re.compile(r"^\s*-?\s*(\d{1,4}|[ivxlc]{1,8}|[IVXLC]{1,8})\s*-?\s*$")
STAMP = re.compile(r"^\s*F{1,2}i{1,2}l{1,2}i{1,2}n{1,2}g{1,2} #")       # e-filing stamp, also OCR-doubled
BODY_COMPLETE = re.compile(r"[.!?:;\"'”’)\]]\d{0,3}\s*$")
SENTENCE_END = re.compile(r"\)[.;,]?\s|[a-z]{3}[.?!][\"'”’]?\s")
QUOTES = {"’": "'", "‘": "'", "“": '"', "”": '"', " ": " "}
BLOCK_QUOTE_MAX = 1200
BLOCK_INTRODUCER = re.compile(r"\b(?:as follows|the following(?: language| provision| text)?|provides|provided|states|"
                              r"stated|reads|held|holds|ordered|ruled|reasoned|explained|wrote|concluded):[ \t]+(?=\S)")


class Doc:
    """The normalized text the checks run on, mapped back to the source.

    norm: curly quotes made straight, runs of whitespace made one space, e-filing stamps and
    page-number lines dropped, and a page's footnotes moved after the sentence that continues on the
    next page (so a citation split by a page break and footnotes reads as one). nmap[i] is the source
    offset of norm[i].
    """

    def __init__(self, source):
        self.source = source
        raw = source.text
        self.raw = raw
        self.ff = [i for i, ch in enumerate(raw) if ch == "\f"]
        self.line_starts = [0] + [i + 1 for i, ch in enumerate(raw) if ch == "\n"]
        self.pages = len(self.ff) + 1 if self.ff and raw[self.ff[-1] + 1:].strip() else max(1, len(self.ff))
        self.page_labels = {}
        self._foot_ranges = []
        segs = self._segments()
        self.norm, self.nmap = self._normalize(segs)
        self.block_quotes = self._block_quotes()
        self.footnotes = self._norm_spans(self._foot_ranges)
        self.quotes, self.unclosed_quotes = paired_quotes(self)
        self.defined_terms = [q for q in self.quotes if defined_term(self.norm, *q)]
        self.quotes = [q for q in self.quotes if q not in self.defined_terms]

    def _block_quotes(self):
        """Norm spans of block quotations, which carry no quotation marks. The source's layout decides
        when it shows any (Source.blocks). Otherwise the text does: reading-order PDF text and .docx
        put each paragraph on its own line, so a block quote is the paragraph after one ending with a
        colon ("the order included the following language:"), or the rest of a line after an
        introducer ("the trial court held as follows: 1. Partition is ..."), continuing over wrapped
        lines until one ends a sentence."""
        if self.source.blocks is not None:
            return self._norm_spans(sorted(self.source.blocks))
        raw, ranges, prev, active, size = self.raw, [], "", False, 0
        for i, s in enumerate(self.line_starts):
            e = self.line_starts[i + 1] - 1 if i + 1 < len(self.line_starts) else len(raw)
            line = raw[s:e].strip()
            if not line or PAGE_NUMBER.match(line):
                continue
            start = None
            if active and size + e - s > BLOCK_QUOTE_MAX:
                active = False                 # past the limit the body has probably resumed
            if active:
                start = s
            elif re.search(r":[\"'”’]?$", prev) and len(prev) >= 8:
                start, size = s, 0             # a wrapped "... the court explained:" may end short
            else:
                m = BLOCK_INTRODUCER.search(raw, s, e)
                if m:
                    start, size = m.end(), 0
            if start is not None:
                ranges.append((start, e))
                size += e - start
                # Lines that wrap mid-sentence continue the quote; past BLOCK_QUOTE_MAX the body has
                # probably resumed (wrapped body text looks the same), so stop.
                active = not BODY_COMPLETE.search(line) and size < BLOCK_QUOTE_MAX
            prev = line
        return self._norm_spans(ranges)

    def _norm_spans(self, ranges):
        """Norm spans covering sorted, non-overlapping source ranges."""
        if not ranges:
            return []
        starts = [a for a, _ in ranges]
        spans, cur = [], None
        for k, r in enumerate(self.nmap[:-1]):
            j = bisect.bisect_right(starts, r) - 1
            inside = j >= 0 and ranges[j][0] <= r < ranges[j][1]
            if inside and cur is None:
                cur = k
            elif not inside and cur is not None:
                spans.append((cur, k))
                cur = None
        if cur is not None:
            spans.append((cur, len(self.norm)))
        return spans

    def stream(self, i):
        """Which run of text norm offset i belongs to: 'body', or one footnote block. A .docx labels its
        footnotes ('fn 3'); in PDF text a page's footnotes are the lines after its glued markers."""
        r = self.raw_pos(i)
        if self.source.line_labels:
            line = bisect.bisect_right(self.line_starts, r) - 1
            label = self.source.line_labels[line] if line < len(self.source.line_labels) else ""
            return label if label.startswith(("fn", "endnote")) else "body"
        for k, (a, b) in enumerate(self.footnotes):
            if a <= i < b:
                return f"footnotes {k}"
        return "body"

    def _lines(self, a, b):
        out, s = [], a
        while True:
            e = self.raw.find("\n", s, b)
            if e == -1:
                out.append((s, b))
                return out
            out.append((s, e))
            s = e + 1

    def _segments(self):
        raw = self.raw
        if not self.ff:
            return [(a, b) for a, b in self._lines(0, len(raw)) if not STAMP.match(raw[a:b])]
        bounds = [-1] + self.ff + [len(raw)]
        pages = []
        for i in range(len(bounds) - 1):
            lines = [(a, b) for a, b in self._lines(bounds[i] + 1, bounds[i + 1]) if not STAMP.match(raw[a:b])]
            while lines and not raw[lines[-1][0]:lines[-1][1]].strip():
                lines.pop()
            pg = {"lines": lines, "label": None, "trail": None}
            if lines:
                a, b = lines[-1]
                if PAGE_NUMBER.match(raw[a:b]):
                    pg["label"] = raw[a:b].strip(" -\t")
                    lines.pop()
                else:
                    m = re.search(r"\s(\d{1,4})\s*$", raw[a:b])
                    if m:
                        pg["trail"] = (int(m.group(1)), a + m.start())
            pages.append(pg)
        # A number glued to the end of a page's last line is its page number when it fits the neighbors.
        arabic = {i: int(p["label"]) for i, p in enumerate(pages) if p["label"] and p["label"].isdigit()}
        for i, pg in enumerate(pages):
            if pg["trail"] and any(v - pg["trail"][0] == j - i for j, v in arabic.items()):
                pg["label"] = str(pg["trail"][0])
                a, _ = pg["lines"][-1]
                pg["lines"][-1] = (a, pg["trail"][1])
        # Running lines: a header at the top of each page ("CASE NO. 2019-CA-0417"), often glued to the
        # first line of text, or a footer at the bottom ("2 ABLE & BAKER, P.A. ..."), would
        # otherwise land inside a citation that crosses the page break. A page number beside one is the
        # page's label.
        # A running line may take several lines (Poppler sets "16", a firm's name, and its address on
        # three), so each end is taken a line at a time, up to RUNNING_DEPTH lines.
        for at in ("first", "last"):
            for _ in range(RUNNING_DEPTH):
                done = set()
                for _ in range(MAX_HEADERS):
                    found = _running_line(raw, pages, at, done)
                    if not found:
                        break
                    for i, pg in enumerate(pages):
                        if pg["lines"] and i not in done and _strip_running(raw, pg, at, *found, pages=len(pages)):
                            done.add(i)
                            while pg["lines"] and not raw[pg["lines"][-1][0]:pg["lines"][-1][1]].strip():
                                pg["lines"].pop()
                            if at == "last" and pg["lines"] and not pg["label"]:
                                a, b = pg["lines"][-1]           # a page number above the footer
                                if PAGE_NUMBER.match(raw[a:b]):
                                    pg["label"] = raw[a:b].strip(" -\t")
                                    pg["lines"].pop()
                if not done:
                    break
        for i, pg in enumerate(pages):
            if pg["label"]:
                self.page_labels[i + 1] = pg["label"]
        self.page_labels = _plausible_labels(self.page_labels, len(pages))
        segs, pending = [], None
        for i, pg in enumerate(pages):
            lines = pg["lines"]
            fn_at = self._footnote_start(lines)
            body = lines[:fn_at] if fn_at else lines
            foot = lines[fn_at:] if fn_at else []
            if pending:
                cut = self._sentence_end(body)
                if cut is None:
                    segs.extend(pending)
                    segs.extend(body)
                else:
                    segs.extend(_split(body, cut, before=True))
                    segs.extend(pending)
                    segs.extend(_split(body, cut, before=False))
                pending = None
            else:
                segs.extend(body)
            if foot:
                self._foot_ranges.append((foot[0][0], foot[-1][1]))
                last = raw[body[-1][0]:body[-1][1]] if body else "."
                if i < len(pages) - 1 and not BODY_COMPLETE.search(last):
                    pending = foot
                else:
                    segs.extend(foot)
        if pending:
            segs.extend(pending)
        return segs

    def _footnote_start(self, lines):
        """Index of the line where the page's footnotes begin. The layout says where, when the source
        has one (Source.footnote_starts); a line holding body text before that point is split there.
        Otherwise it's a line opening with a number that appears earlier on the page as a marker
        (footnote_marker)."""
        raw = self.raw
        if self.source.footnote_starts is not None:
            if not lines:
                return None
            starts = self.source.footnote_starts
            j = bisect.bisect_left(starts, lines[0][0])
            if j == len(starts) or starts[j] > lines[-1][1]:
                return None
            s = starts[j]
            for k, (a, b) in enumerate(lines):
                if a <= s <= b:
                    if raw[a:s].strip() and not re.fullmatch(r"\s*\d{1,3}\.?\s*", raw[a:s]):
                        lines[k:k + 1] = [(a, s), (s, b)]   # body text, then the footnote, on one line
                        return k + 1
                    return k or None
            return None
        text = [raw[a:b].strip() for a, b in lines]
        for k in range(1, len(lines)):
            if footnote_line(text, k):
                return k
        return None

    def _sentence_end(self, lines):
        """Source offset just past the first sentence end near the top of these lines, or None."""
        if not lines:
            return None
        text = "\n".join(self.raw[a:b] for a, b in lines)[:800]
        m = SENTENCE_END.search(text)
        if not m:
            return None
        k = m.end()
        for a, b in lines:
            if k <= b - a:
                return a + k
            k -= b - a + 1
        return None

    def _normalize(self, segs):
        raw = self.raw
        chars, idx = [], []
        for a, b in segs:
            chars.extend(raw[a:b])
            idx.extend(range(a, b))
            chars.append("\n")
            idx.append(b)
        out, nmap = [], []
        k, n = 0, len(chars)
        while k < n:
            c = chars[k]
            if c.isspace():
                e = k
                while e < n and chars[e].isspace():
                    e += 1
                broke = any(ch in "\n\f" for ch in chars[k:e])
                # "865-\n66", "No. 20-\n00618", and "DC–\n8, Inc." were one token before the line broke
                joined = (broke and len(out) > 1 and out[-1] in "-–—" and out[-2].isalnum()
                          and e < n and chars[e].isalnum())
                if out and e < n and not joined:
                    out.append(" ")
                    nmap.append(idx[k])
                k = e
                continue
            if c == "_" and out and (out[-1].isalnum() or out[-1] == ".") and k + 1 < n and chars[k + 1].isalnum():
                out.append(" ")               # OCR's underscore for an underlined space: "Smith_v._Jones"
                nmap.append(idx[k])
            elif c != "­":
                out.append(QUOTES.get(c, c))
                nmap.append(idx[k])
            k += 1
        nmap.append(len(raw))
        return "".join(out), nmap

    def raw_pos(self, i):
        return self.nmap[min(i, len(self.nmap) - 1)]

    def location(self, start, end):
        r0 = self.raw_pos(start)
        r1 = self.raw_pos(max(start, end - 1))
        loc = {"start": start, "end": end}
        line = bisect.bisect_right(self.line_starts, r0)
        if self.source.line_labels and line - 1 < len(self.source.line_labels):
            loc["where"] = self.source.line_labels[line - 1]
        else:
            loc["line"] = line
        if self.ff:
            page = bisect.bisect_right(self.ff, r0) + 1
            loc["page"] = page
            if page in self.page_labels:
                loc["printed_page"] = self.page_labels[page]
            end_page = bisect.bisect_right(self.ff, r1) + 1
            if end_page != page:
                loc["split_to_page"] = end_page
            loc["label"] = self.page_name(page)
        return loc

    def page_name(self, page):
        """The printed page first, as a lawyer would quote it, then the PDF page: 'p. 12 (PDF p. 19)'.
        A .docx counts pages only by its explicit page breaks."""
        if self.source.kind == "docx":
            return f"p. {page}"
        if page in self.page_labels:
            return f"p. {self.page_labels[page]} (PDF p. {page})"
        return f"PDF p. {page}"

    def empty_pages(self):
        """Pages with little or no text (scanned pages, in a PDF that is otherwise text)."""
        if not self.ff:
            return []
        bounds = [-1] + self.ff + [len(self.raw)]
        out = []
        for i in range(min(self.pages, len(bounds) - 1)):
            text = "".join(ln for ln in self.raw[bounds[i] + 1:bounds[i + 1]].split("\n") if not STAMP.match(ln))
            if len(re.sub(r"\s", "", text)) < EMPTY_PAGE_CHARS:
                out.append(i + 1)
        return out

    def appended(self):
        """Where exhibits or an appendix seem to begin, after page 1: the first page that is only a slip
        sheet ("Exhibit 1", "Appendix A"), else the first page printed from a case database (a Westlaw
        or Lexis footer). Returns {"page", "why"} or None. Their citations are another writer's."""
        if not self.ff:
            return None
        bounds = [-1] + self.ff + [len(self.raw)]
        printed = None
        for i in range(1, min(self.pages, len(bounds) - 1)):
            text = "\n".join(ln for ln in self.raw[bounds[i] + 1:bounds[i + 1]].split("\n") if not STAMP.match(ln))
            m = SLIP_SHEET.fullmatch(text.strip())
            if m:
                return {"page": i + 1, "why": f'reads only "{m.group(0)}"'}
            p = PRINTOUT.search(text) if printed is None else None
            if p:
                printed = {"page": i + 1, "why": "is printed from " + ("Westlaw" if p.group(1) else "Lexis")}
        return printed


ROMAN_NUMERAL = re.compile(r"m{0,3}(?:cm|cd|d?c{0,3})(?:xc|xl|l?x{0,3})(?:ix|iv|v?i{0,3})", re.I)


def _label_value(label):
    """('arabic', 12) or ('roman', 4); None for something no page is numbered with ('ll' from OCR)."""
    if label.isdigit():
        return "arabic", int(label)
    if ROMAN_NUMERAL.fullmatch(label) and label in (label.lower(), label.upper()):
        n, prev = 0, 0
        for ch in reversed(label.lower()):
            v = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}[ch]
            n, prev = (n - v, prev) if v < prev else (n + v, v)
        return "roman", n
    return None


def _plausible_labels(labels, pages):
    """Printed page numbers that fit their neighbors in the same numbering. An OCR'd 'iii' read as '111',
    or a table of authorities' page column, fits neither neighbor, so that page is reported by its PDF
    page instead."""
    vals = {p: _label_value(l) for p, l in labels.items()}
    out = {}
    for p, v in vals.items():
        if v is None or (v[0] == "arabic" and v[1] > pages):
            continue
        near = [(q, vals[q]) for q in (p - 1, p + 1) if vals.get(q) and vals[q][0] == v[0]]
        if not near or any(w[1] - v[1] == q - p for q, w in near):
            out[p] = labels[p]
    return out


DIGITISH = "0123456789lI|O"      # OCR reads a case number's 1 as l, I, or |, and 0 as O
HEADER_MIN = 8                   # skeleton characters, at least three of them letters
HEADER_MAX = 60                  # a header is often glued to body text: compare no further
FOOTER_MAX = 100                 # a footer is usually a whole line, and a firm's address runs past 60
OCR_DIGITS = str.maketrans("lI|O", "1110")
MAX_HEADERS = 6                  # a filing and its exhibits, each with its own running header
RUNNING_DEPTH = 3                # lines a running header or footer may take


def _skeleton(text):
    """Text without spaces, each digit-like character as '#': 'CASE NO. 2019-CA-04 l 7' and
    'CASE NO. 2019-CA-0417' both become 'CASEN#.####-CA-####'."""
    return "".join("#" if ch in DIGITISH else ch for ch in text if not ch.isspace())


def _header_text(text):
    """A header's text as printed, OCR's misreadings undone: 'CASE NO. 2019-CA-O4l7' -> 'CASENO.2019-CA-0417'."""
    return re.sub(r"\s", "", text).translate(OCR_DIGITS).replace("N0.", "NO.")


def _dense(pages_hit):
    """At least three pages, on 60% or more of the pages from the first to the last of them (a motion's
    header stops where its exhibits begin)."""
    return len(pages_hit) >= 3 and len(pages_hit) * 5 >= (max(pages_hit) - min(pages_hit) + 1) * 3


# A page number at a line's edge, set aside before running lines are compared: "2 ABLE & BAKER ...",
# "... ANSWER BRIEF - 12 -". Not the end of a number OCR split with spaces ("2019-CA-l l 52",
# "2019-CA-l 152"): the token before it ends in one or two digit-like characters.
_OCR_TAIL = "[" + re.escape(DIGITISH) + "]"
EDGE_NUMBER_START = re.compile(r"[ \t]*-?[ \t]*\d{1,4}[ \t]*-?[ \t]+(?=\S)(?!" + _OCR_TAIL + r"{1,2}(?:[\s-]|$))")
EDGE_NUMBER_END = re.compile("".join(r"(?<!" + pre + _OCR_TAIL * n + ")" for pre in (r"\s", "^", "-") for n in (1, 2))
                             + r"[ \t]+-?[ \t]*\d{1,4}[ \t]*-?[ \t]*$")


def _core(raw, a, b):
    """A line's span without a page number at either edge."""
    m = EDGE_NUMBER_START.match(raw, a, b)
    ca = m.end() if m else a
    m = EDGE_NUMBER_END.search(raw, ca, b)
    return ca, (m.start() if m else b)


def _running_line(raw, pages, at, skip=()):
    """(regex, text) for a running line on a run of pages: a header at the top of each page (at="first")
    or a footer at the bottom (at="last"), or None. Pages in skip already had one removed (a motion and
    each exhibit may have its own).

    Each page's first or last line is compared without a page number at its edges ("2 ABLE & BAKER ...").
    A header is the longest skeleton prefix those lines share, a footer the longest suffix, backed off
    to a word break; a header is often glued to the page's first line of text, and a footer can be glued
    to its last. The regex allows OCR's stray spaces and misread digits but requires the same number of
    characters, ending (or, for a footer, starting) at a word break, so it never takes text from the
    body. And the text must be the same on most of those pages, so pages that merely start or end alike
    ("Id. at 5.", "Id. at 7.") are never taken for one."""
    first = at == "first"
    cores = {}
    for i, pg in enumerate(pages):
        if pg["lines"] and i not in skip and (i or not first):
            ca, cb = _core(raw, *pg["lines"][0 if first else -1])
            sk = _skeleton(raw[ca:cb])
            cores[i] = (ca, cb, sk[:HEADER_MAX] if first else sk[::-1][:FOOTER_MAX])
    best = ""
    for k in range(HEADER_MIN, (HEADER_MAX if first else FOOTER_MAX) + 1):
        groups = {}
        for i, (_, _, sk) in cores.items():
            if len(sk) >= k:
                groups.setdefault(sk[:k], []).append(i)
        dense = [h for h, hit in groups.items() if _dense(hit)]
        if not dense:
            break
        best = max(dense, key=lambda h: len(groups[h]))
    for k in range(len(best), HEADER_MIN - 1, -1):     # back off to a word break
        head = best[:k] if first else best[:k][::-1]
        if sum(ch.isalpha() for ch in head) < 3:
            return None
        parts = ["[" + re.escape(DIGITISH) + "]" if ch == "#" else re.escape(ch) for ch in head]
        body = r"\s*".join(parts)
        rx = re.compile(r"\s*" + body + r"(?=\s|$)" if first else r"(?<!\S)" + body + r"\s*$")
        texts = {}
        for i, (ca, cb, _) in cores.items():
            m = rx.match(raw, ca, cb) if first else rx.search(raw, ca, cb)
            if m:
                texts.setdefault(_header_text(m.group(0)), []).append(i)
        if texts:
            text, hit = max(texts.items(), key=lambda kv: len(kv[1]))
            if _dense(hit) and len(hit) * 5 >= sum(len(v) for v in texts.values()) * 3:
                return rx, text
    return None


def _strip_running(raw, pg, at, rx, text, pages=None):
    """Remove a running line from a page whose first or last line carries it. A page number left beside
    it ("2" before a footer, "- 4 -" after a header) becomes the page's label when it has none.
    Returns whether the page carried it."""
    k = 0 if at == "first" else -1
    a, b = pg["lines"][k]
    ca, cb = _core(raw, a, b)
    m = rx.match(raw, ca, cb) if at == "first" else rx.search(raw, ca, cb)
    if not m or _header_text(m.group(0)) != text:
        return False
    if at == "first":
        outer, inner, rest = raw[a:ca], raw[m.end():b], (m.end(), b)
    else:
        outer, inner, rest = raw[cb:b], raw[a:m.start()], (a, m.start())
    numbers = [s for s in (outer, inner) if PAGE_NUMBER.match(s) and s.strip()
               and not (pages and s.strip(" -\t").isdigit() and int(s.strip(" -\t")) > pages)]   # not "1141 71ST ST."
    if numbers and not pg["label"]:
        pg["label"] = numbers[0].strip(" -\t")
    if not inner.strip() or PAGE_NUMBER.match(inner):
        del pg["lines"][k]
    else:
        pg["lines"][k] = rest
    return True


def _split(lines, cut, before):
    out = []
    for a, b in lines:
        if before:
            if a < cut:
                out.append((a, min(b, cut)))
        elif b > cut:
            out.append((max(a, cut), b))
    return out


# ---------------------------------------------------------------- the document's date

EFILED = re.compile(r"E-Filed (\d{2})/(\d{2})/(\d{4})")
OPINION_FILED = re.compile(r"Opinion filed (" + FULL_MONTHS + r") (\d{1,2}), (\d{4})")
CAPTION_DATE = re.compile(
    r"(?:^[ \t]*\[?|(?:Respondents?|Appellees?|Petitioners?|Appellants?)\.[ \t]+)"
    r"(" + FULL_MONTHS + r") (\d{1,2}), (\d{4})\]?"
    r"(?=[ \t]*$|[ \t]*\n?[ \t]*(?:PER CURIAM|CORRECTED|[A-Z][A-Z'\-]+, (?:C\.)?J\.|(?:An )?Appeal from|On appeal from"
    r"|Petition for|Original [Pp]roceeding))", re.M)


def infer_date(raw):
    """The document's own date, if it shows one: an e-filing stamp, 'Opinion filed ...', or a date
    standing alone on a caption line. Returns (date, how) or (None, None)."""
    head = raw[:raw.find("\f")] if "\f" in raw[:6000] else raw[:4000]
    m = EFILED.search(raw[:3000])
    if m:
        try:
            return dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2))), "the e-filing stamp"
        except ValueError:
            pass
    for rx, how in ((OPINION_FILED, "'Opinion filed' line"), (CAPTION_DATE, "the date in the caption")):
        m = rx.search(head)
        if m:
            try:
                return dt.date(int(m.group(3)), MONTHS[m.group(1)], int(m.group(2))), how
            except ValueError:
                pass
    return None, None


# ---------------------------------------------------------------- courts and date parentheticals

DCA_ORDINALS = {"1st": "1D", "2d": "2D", "2nd": "2D", "3d": "3D", "3rd": "3D", "4th": "4D", "5th": "5D", "6th": "6D"}
COURT_WORD = re.compile(r"[A-Z0-9\[\]][\w.'&\-\]]*|of|for|the|and|on|en|banc|ex|rel\.|[—–\-]")


def classify_court(ct):
    """A court parenthetical's court ('Fla. 3d DCA', 'S.D. Fla.') -> {'id', 'family', 'sub'} or None."""
    ct = ct.strip().rstrip(",").strip()
    if not ct:
        return None
    if re.fullmatch(r"Fla\.?(?: Sup(?:reme|\.)? ?Ct\.?)?", ct):
        return {"id": "SC", "family": "florida", "sub": "a"}
    m = re.fullmatch(r"(?:Fla\.? )?(1st|2d|2nd|3d|3rd|4th|5th|6th) ?(?:DCA|D\. ?C\. ?A\.)", ct)
    if m:                                  # the space may be missing: "4thDCA" (b-dca-glued)
        return {"id": DCA_ORDINALS[m.group(1)], "family": "florida", "sub": "b"}
    m = re.fullmatch(r"Fla\. (1st|2d|2nd|3d|3rd|4th|5th|6th)", ct)
    if m:                                  # "(Fla. 2d 2020)": DCA left out (b-dca-missing)
        return {"id": DCA_ORDINALS[m.group(1)], "family": "florida", "sub": "b"}
    m = re.fullmatch(r"Fla\.? ?(?:Dist\. ?Ct\. ?)?App\. ?([1-6])(?:st|d|nd|rd|th)? ?Dist\.", ct)
    if m:                                  # Westlaw's "(Fla. App. 4th Dist. 2013)": b-west-district
        return {"id": m.group(1) + "D", "family": "florida", "sub": "b", "west": True}
    if re.fullmatch(r"Fla\.? ?(?:Dist\. ?Ct\. ?)?App\..*", ct):
        return {"id": "DCA", "family": "florida", "sub": "b"}
    if re.fullmatch(r"Fla\.? \S+ (?:DCA|D\. ?C\. ?A\.)", ct):
        # "Fla. Ist DCA", "Fla. Sth DCA": an OCR-garbled or mistyped district
        return {"id": "DCA?", "family": "florida", "sub": "b", "unreadable": True}
    if re.search(r"\bCir(?:cuit|\.)? Ct\.|\bJud(?:icial|\.)? Cir", ct) and re.search(r"\bFla?\.", ct):
        return {"id": "circuit", "family": "florida", "sub": "c"}
    if re.search(r"\b(?:Cty\.|County|Cnty\.) (?:Ct\.|Court)$", ct):
        return {"id": "county", "family": "florida", "sub": "c"}
    if re.fullmatch(r"(?:Fla\. )?DOAH", ct):
        return {"id": "DOAH", "family": "florida", "sub": "d"}
    if ct.startswith("Fla. ") and re.search(r"Bd\.|Comm'n|Dep't|Div\.|Agency|Off\.|Auth\.", ct):
        return {"id": "agency", "family": "florida", "sub": "d"}
    if ct == "U.S.":
        return {"id": "USSC", "family": "federal", "sub": "l"}
    m = re.fullmatch(r"(\d{1,2})(?:st|d|nd|rd|th) Cir\.?(?: Unit [AB])?", ct)
    if m:
        return {"id": f"CA{m.group(1)}", "family": "federal", "sub": "m"}
    m = re.fullmatch(r"(\d{1,2})(?:st|d|nd|rd|th) Cir\. ?\(?[A-Z][a-z]{1,4}\.\)?", ct)
    if m:                                  # West's "(11th Cir. Ga. 1988)": the state doesn't belong
        return {"id": f"CA{m.group(1)}", "family": "federal", "sub": "m", "west": True}
    if ct in ("D.C. Cir.", "Fed. Cir."):
        return {"id": "CA" + ct.split()[0].replace(".", ""), "family": "federal", "sub": "m"}
    m = re.fullmatch(r"C\.A\. ?(\d{1,2}|D\.C\.|Fed\.)(?: ?\([^)]*\))?", ct)
    if m:
        return {"id": "CA" + m.group(1).replace(".", ""), "family": "federal", "sub": "m", "west": True}
    if re.fullmatch(r"[NMS]\.? ?D\.? ?Fla\.?", ct):
        return {"id": ct[0] + ".D. Fla.", "family": "federal", "sub": "n"}
    if re.fullmatch(r"(?:[NSEWMC]\. ?)?D\. ?[A-Z][\w.]*(?: [A-Z][\w.]*)?", ct):
        return {"id": "district", "family": "federal", "sub": "n"}
    return None


DATE_TAIL = re.compile(r"(?:,? ?(?P<mon>" + MONTH_RX + r")(?: (?P<day>\d{1,2}))?,?)? ?(?P<year>(?:1[6-9]|20)\d\d)$")
MONTH_DAY_TAIL = re.compile(r"(?:^|,? )(?P<mon>" + MONTH_RX + r") (?P<day>\d{1,2})$")


def parse_paren(text):
    """'Fla. 3d DCA Mar. 6, 2002' -> court, year, month, day. None if it isn't a court-and-date
    parenthetical (an explanatory parenthetical, '(Table)', ...)."""
    t = text.strip()
    out = {"text": t, "year": None, "month": None, "day": None}
    m = DATE_TAIL.search(t)
    court_text = t
    if m:
        out["year"] = int(m.group("year"))
        if m.group("mon"):
            out["month"] = MONTHS[m.group("mon")]
            out["day"] = int(m.group("day")) if m.group("day") else None
        court_text = t[:m.start()]
    else:
        m = MONTH_DAY_TAIL.search(t)
        if m:
            out["month"], out["day"] = MONTHS[m.group("mon")], int(m.group("day"))
            court_text = t[:m.start()]
    court_text = court_text.strip().rstrip(",").strip()
    court = classify_court(court_text)
    if court is None:
        if out["year"] is None and out["month"] is None:
            return None
        words = court_text.split()
        if court_text and (len(court_text) > 60 or not all(COURT_WORD.fullmatch(w) for w in words)):
            return None
        court = {"id": "other" if court_text else None, "family": "other" if court_text else None, "sub": None}
    out["court_text"] = court_text
    out["court"] = court
    if out["year"] and out["month"] and out["day"]:
        try:
            out["date"] = dt.date(out["year"], out["month"], out["day"]).isoformat()
        except ValueError:
            pass
    return out


# ---------------------------------------------------------------- patterns for extraction

# Words that end a case name when walking back from "v." (signals and sentence openers), words a
# name can contain in lowercase, and what a party name never contains (another citation, a sentence).
NAME_STOP = {"see", "cf.", "accord", "compare", "contra", "but", "quoting", "citing", "e.g.,", "e.g.", "also",
             "generally", "under", "in", "as", "because", "since", "after", "following", "although", "thus",
             "therefore", "here", "when", "while", "like", "unlike", "per", "from", "by", "with", "that",
             "applying", "discussing", "explaining", "holding", "noting", "overruling", "reviewing", "and", "or",
             "id.", "id", "ibid.", "supra", "pursuant", "whether", "where", "unless", "until", "before", "during"}
NAME_CONNECTORS = {"of", "the", "&", "for", "de", "del", "la", "ex", "rel.", "on", "to", "a", "an",
                   "d/b/a", "f/k/a", "n/k/a", "et", "al.", "al.,", "y", "-", "–", "—"}   # "Baker Western – De Luca Joint Venture"
# A sentence or citation inside a party's name. Lowercase after a period is a sentence unless it's a
# connector after an abbreviation: "Sch. Bd. of Lake Cnty.", "Univ. of Fla.".
BAD_NAME = re.compile(r"[;\"()]|\. (?!(?:of|and|for|de|del|la|ex|rel|on|to|y)\b)[a-z]|\d{1,4} [A-Z][\w.']* ?\d")
TOA_HEADINGS = {"CASES", "TABLE", "CITATIONS", "AUTHORITIES", "PAGE", "PAGES", "NO.", "STATUTES", "RULES", "OTHER",
                "CONSTITUTIONAL", "PROVISIONS", "ARGUMENT", "CONCLUSION", "CERTIFICATE", "SERVICE", "COMPLIANCE"}


def _name_word(t, bare, low):
    """Can this token (walking back from "v.") belong to a party's name?"""
    if t in ("-", "–", "—"):
        return True                        # a spaced dash inside a name; one left at the front is trimmed
    if re.search(r"[;:]$|\)|[.!?][\"'”’]$|\.{3}|…", t):
        return False                       # ends a clause, a parenthetical, or a quotation; TOA leader dots
    if re.fullmatch(r"[A-Z][a-z]{7,}\.|Yes\.", t):
        return False                       # "Constitution." ends a sentence; abbreviations are shorter. "A. Yes."
    if re.fullmatch(r"[a-z]{2,}[.,]", t) and low not in NAME_CONNECTORS:
        return False                       # "court." ends the sentence before
    if re.fullmatch(r"[\d\-–.,()*]+", t):
        return False                       # "73-178." or a table-of-authorities page number
    if bare.rstrip(".,") in TOA_HEADINGS or bare in TOA_HEADINGS:
        return False
    return bare[0].isupper() or bare[0].isdigit() or low in NAME_CONNECTORS
HISTORY = re.compile(
    r"(?:aff'd|rev'd|affirmed|reversed|approved|quashed|disapproved|vacated|modified|abrogated|overruled|"
    r"receded from|superseded|dismissed|declined to follow|cert\. (?:denied|granted|dismissed)|"
    r"review (?:denied|granted|dismissed|declined)|reh'g (?:denied|granted)|mandamus denied|appeal dismissed)"
    r"(?: in part(?: and (?:aff'd|rev'd|vacated|approved|quashed) in part)?)?(?: on other grounds)?(?: by)?"
    r"(?: sub nom\.)?(?: as stated in)?,? $")

# A Florida Statutes section and its pinpoint: 48.031, 775.082(3)(a)1., 921.141(2)(b)2.a.-b., 624.307(1)-(2);
# then more of them: "(6), (7)", "782.07(1) and (3)", "688.001-009", "§§ 626.785(1), 626.7845(1)".
SUBS = r"(?:\([\w.]+\))+"
SEC = r"\d{1,4}[A-Z]?\.\d+[A-Za-z]?(?:" + SUBS + r"(?:\d+\.?(?:[a-z]\.)?(?:[-–][a-z]\.)?)?)?(?:[-–]" + SUBS + r")?"
SECS = (SEC + r"(?:(?:,? (?:and|or|&|through) |, |[-–] ?)(?:" + SEC + r"|" + SUBS + r"(?:[-–]" + SUBS + r")?|\.\d+[\w]*(?:"
        + SUBS + r")?)|[-–]\d{2,4}(?![\d.]))*")
CHAPTER = r"\d{1,3}[A-Z]?(?:, [Pp]art [IVX]+)?"
YEAR_PAREN = r"(?: \((?P<year>(?:Supp\. |West )*(?:1[89]|20)\d\d)\))?"
STAT_CODE = r"(?:Fla\. Stats?\.?(?![\w.]| Ann\.)|Florida Statutes)"
STATUTES = [
    # (form, regex); the 'year' group, when present, gives the edition
    ("abbreviated", re.compile(r"(?P<sign>§§?) ?(?P<sec>" + SECS + r"),? (?P<code>" + STAT_CODE + r")" + YEAR_PAREN, re.I)),
    ("abbreviated", re.compile(r"\b[Cc]h(?:apters?|s?\.) (?P<sec>" + CHAPTER + r"),? (?P<code>Fla\. Stat\.?(?![\w.]| Ann\.))" + YEAR_PAREN, re.I)),
    ("sentence", re.compile(r"\b(?:[Ss]ections?|[Cc]hapters?) (?P<sec>" + SECS + r"|" + CHAPTER + r"),? (?:of (?:the )?)?"
                            r"(?P<code>Florida Statutes|Fla\. Stat\.)" + YEAR_PAREN)),
    ("bluebook-order", re.compile(r"\b(?P<code>Fla\. Stat\.) (?:§§? ?)?(?P<sec>" + SECS + r")" + YEAR_PAREN)),
    ("fs", re.compile(r"(?:(?:§§?|[Ss]ections?) ?(?P<sec>" + SECS + r"),? (?P<code>F\. ?S\.)(?![\w.])(?! ?A\.)|(?P<code2>F\. ?S\.) §? ?(?P<sec2>" + SEC + r"))" + YEAR_PAREN)),
]
# "§ 48.031, Fla. Stat. Ann.": the official form's order with the annotated code's name (9.800(f) or (g)).
ANNOTATED_ORDER = re.compile(r"(?P<sign>§§?) ?(?P<sec>" + SECS + r"),? Fla\. Stat\. Ann\.(?: \((?P<year>(?:West )?(?:1[89]|20)\d\d)\))?")
ANNOTATED = re.compile(r"(?:\b(?P<vol>\d{1,2}[A-Z]?) )?Fla\. Stat\. Ann\. (?:§§? ?(?P<sec>" + SECS + r")|(?P<pages>\d+[-–]\d+))(?: \((?P<year>[^()]{0,20}\d{4})\))?", re.I)

CONSTITUTIONS = [
    ("abbreviated", re.compile(r"\b(?P<what>[Aa]rt(?:\.|icle)) (?P<num>[IVXL]+)(?:, (?:§§?|[Ss]ec(?:tions?|s?\.)) ?(?P<sec>\d+[\w()]*(?:[-–]\d+[\w()]*)?(?:, " + SUBS + r")*))?(?:, cl\. (?P<cl>\d+))?,? (?P<which>Fla\. Const\.|U\.S\. Const\.)(?: \((?P<year>\d{4})\))?", re.I)),
    ("abbreviated", re.compile(r"\b(?P<what>[Aa]mend(?:\.|ment)) (?P<num>[IVXL]+)(?:, (?:§|[Ss]ec\.) ?(?P<sec>\d+))?, (?P<which>U\.S\. Const\.)", re.I)),
    ("bluebook-order", re.compile(r"\b(?P<which>Fla\.|U\.S\.) Const\. (?P<what>art\.|amend\.) (?P<num>[IVXL]+)(?:, § ?(?P<sec>\d+[\w()]*))?(?:, cl\. (?P<cl>\d+))?", re.I)),
    ("sentence", re.compile(r"\b[Aa]rticle (?P<num>[IVXL]+)(?:, [Ss]ections? (?P<sec>\d+[\w()]*))?,? of the (?P<which>Florida|United States|U\.S\.) Constitution")),
]
ADMIN_CODE = [
    ("abbreviated", re.compile(r"\bFla\. Admin\. Code (?:Ann\. )?(?:[Rr](?:ule|\.)? ?)?(?P<rule>\d+[A-Z]{0,3}-\d+\.\d+[\w()]*)(?: \((?P<year>\d{4})\))?", re.I)),
    ("fac", re.compile(r"\b(?:[Rr]ules? )?(?P<rule>\d+[A-Z]{0,3}-\d+\.\d+[\w()]*), F\. ?A\. ?C\.(?!\w)(?: \((?P<year>\d{4})\))?")),
    ("sentence", re.compile(r"\b(?:Florida Administrative Code [Rr]ule (?P<rule>\d+[A-Z]{0,3}-\d+\.\d+[\w()]*)|[Rr]ule (?P<rule2>\d+[A-Z]{0,3}-\d+\.\d+[\w()]*),? (?:of the )?Florida Administrative Code)(?: \((?P<year>\d{4})\))?")),
]
SESSION_LAWS = [
    ("abbreviated", re.compile(r"\b[Cc]h(?:\.|apter) (?P<ch>\d{2,4}-\d+|\d{3,5})(?:, § ?(?P<sec>\d+))?, Laws of Fla\.(?: \((?P<year>\d{4})\))?")),
    ("bluebook-order", re.compile(r"\bLaws of Fla\. ch\. (?P<ch>\d+-\d+)(?:, § ?(?P<sec>\d+))?")),
    ("sentence", re.compile(r"\b[Cc]hapter (?P<ch>\d{2,4}-\d+|\d{3,5})(?:, section \d+)?,? Laws of Florida(?: \((?P<year>\d{4})\))?")),
]
AG_OPINIONS = [
    re.compile(r"\b(?:Fla\. )?Ops?\. Att'y Gen\.(?: Fla\.)? (?P<num>\d{2,4}-\d{1,4})(?: \((?P<year>\d{4})\))?"),
    re.compile(r"\b(?:Fla\. )?AGO (?P<num>\d{2,4}-\d{1,4})(?: \((?P<year>\d{4})\))?"),
    re.compile(r"\bAtt'y Gen\. Op\.(?: Fla\.)? (?P<num>\d{2,4}-\d{1,4})(?: \((?P<year>\d{4})\))?"),
]
CANONICAL_AG = re.compile(r"Op\. Att'y Gen\. Fla\. \d{2,4}-\d{1,4} \(\d{4}\)")

UNRECOGNIZED = [
    # (tier, what, regex). Recognized citations win any overlap.
    (TIER_BLUEBOOK, "federal statute, regulation, or session law",
     re.compile(r"\b\d+ (?:U\.S\.C\.(?:A\.|S\.)?|C\.F\.R\.|Fed\. Reg\.|Stat\.) (?:§§? ?|pts?\. |at )?\d[\w()\-–]*(?:\.[\w()\-–]+)*(?: \([^()]{0,30}\d{4}\))?")),
    (TIER_BLUEBOOK, "federal session law", re.compile(r"\bPub\. L\. (?:No\. )?\d+-\d+(?:, § ?[\w()]+)?(?:, \d+ Stat\. \d+)?(?: \(\d{4}\))?")),
    (TIER_BLUEBOOK, "Restatement", re.compile(r"\bRestatement \((?:First|Second|Third|Fourth)\)[^;()]{0,60}?§ ?[\w.]+(?: \([^()]{0,40}\d{4}\))?")),
    (TIER_BLUEBOOK, "dictionary", re.compile(r"\bBlack's Law Dictionary(?: \([^()]{0,30}\))?")),
    (TIER_FSM, "legislative history (staff or bill analysis)",
     re.compile(r"\bFla\. (?:S\.|H\.R\.|H\.) (?:Comm\.|Comm'n|Jour\.|Journal)[^;()]{0,160}?(?:\((?:" + MONTH_RX + r") \d{1,2}, \d{4}\)|\(\d{4}\))")),
    (TIER_FSM, "staff or bill analysis",
     re.compile(r"\b(?:CS/)*(?:C?S/)?(?:H\.B\.|S\.B\.|HB|SB|HJR|SJR) \d{1,4},? (?:\(\d{4}\) )?(?:Final )?(?:Staff|Bill) Analysis\b"
                r"(?: \([^()]{0,30}\d{4}\))?")),
    (TIER_FSM, "Florida bill", re.compile(r"\b(?:CS/)*(?:C?S/)?(?:H\.B\.|S\.B\.|HB|SB|HJR|SJR) \d{1,4}(?: \(Fla\. \d{4}\)| \(\d{4}\))")),
    (TIER_FSM, "executive order", re.compile(r"\b(?:Fla\. )?Exec(?:utive|\.)? Order (?:No\. )?\d{2,4}-\d+(?: \([^()]{0,30}\d{4}\))?")),
]
# A word of a reporter's abbreviation, spaced or closed up: "Wash.", "2d", "M.J.", "Cal.Rptr.3d", "(NS)".
REP_WORD = r"(?:(?:[A-Z][A-Za-z'&]*\.)*[A-Z][A-Za-z'&]*\.?(?:\d[a-z]{1,2})?|\d[a-z]{1,2}|&|\([A-Z]+\))"
# A citation's volume and reporter wrapped onto the start of a line: "161 So. 3d at 1272", "317 So. 3d
# 72, 74". Not a record cite ("2 R. 385"), which a footnote may open with.
WRAPPED_CITE = re.compile(r"\d{1,4} (?=\S*\.)(?!(?:[A-Z]\.|Tr\.|App\.) )" + REP_WORD + r"(?: " + REP_WORD + r"){0,3} (?:at )?\d")
GENERIC_REPORTER = re.compile(
    r"(?<![\w.,§])(?P<vol>\d{1,4}) (?P<rep>" + REP_WORD + r"(?: " + REP_WORD + r"){0,6}) "
    r"(?P<page>\d{1,6})(?:, \d+(?:[-–]\d+)?)* \((?P<paren>[^()]{0,60}\d{4})\)")
# A state's own reporter given before the regional one: "250 Ga. 100, 102, 300 S.E.2d 5 (1983)".
OFFICIAL_BEFORE = re.compile(r"(?<![\w.,§])\d{1,4} (?P<rep>" + REP_WORD + r"(?: " + REP_WORD + r"){0,3}) "
                             r"\d{1,5}(?:, \d+(?:[-–]\d+)?)*, $")

PIN = re.compile(r"(?:,|,? )(?:at )?(\*{0,2}\d+(?:[-–—]\*{0,2}\d+)?(?: nn?\. ?\d+(?:[-–]\d+)?)?(?: & nn?\. ?\d+)?)(?!\d)")
PAREN = re.compile(r" ?\(((?:[^()]|\([^()]*\))*)\)")
EXTRA_PAREN = re.compile(r" ?\((?:Table|table|mem\.?|unpublished table decision|per curiam)\)")
DOCKET = r"[A-Za-z0-9][\w:./\-]*\d[\w:./\-]*"
# A blank for a cite not yet assigned: "___ So. 3d ___", "--- So. 3d ---", "— U.S. —".
BLANK = r"(?:_{2,}|-{2,}|[—–]{1,3})"
# A docket number written without "No.": a Florida appellate number (SC2010-1544), or a federal one
# (14-12345-CIV, 1:21-cv-45-XY-ABC, CV 2:18-00123-AB-C, 3:12-cv-100-AB/CD, 2019-CA-001234).
BARE_DOCKET = (r"(?:SC|[1-6]D)\d{2,4}-\d+"
               r"|(?:C[VRA] )?\d{1,2}:\d{2}-?[A-Za-z]{2,3}-\d{1,6}(?:-[\w/]+)*"
               r"|(?:C[VRA] )?\d{1,2}:\d{2}-\d{3,6}(?:-[\w/]+)*"
               r"|\d{1,2}-\d{3,6}-[A-Z]{2,5}(?:-[\w/]+)*"
               r"|\d{2,4}-[A-Z]{2}-\d{3,7}(?:-[\w/]+)*")
DOCKET_BEFORE = re.compile(
    r"(?:\b(?:Case )?Nos?\.\s?(?P<d>(?:C[VRA] )?" + DOCKET + r"(?:(?:, | & | and )" + DOCKET + r")*)"
    r"|(?<![\w\-])(?P<bare>" + BARE_DOCKET + r")),? $")
SLIP = re.compile(r"\b(?:Case )?Nos?\.\s?(?P<d>(?:C[VRA] )?" + DOCKET + r"(?:(?:, | & | and )" + DOCKET + r")*)(?:, (?:slip op\. at |p\. )\d+)?(?= ?\()")
FL_DOCKET = re.compile(r"(?<![\w\-])(?:SC|[1-6]D)-?(?:\d{2}|\d{4})-\d+(?![\w\-])")

# Short forms (Indigo Book R6.2, R15). "Id" without its period is caught only where a citation's would
# follow: before "at <page>", a citation parenthetical, or a section or paragraph; capital "Id" also before a
# bare page. Not "ID", and not Freud's "id (".
PAGE_PIN = r"\*{0,2}[A-Z]?\d+(?:[-–—]\*{0,2}[A-Z]?\d+)?(?: nn?\. ?\d+(?:[-–]\d+)?)?"
ID_PAREN = r" \((?:citing|quoting|emphasis|alteration|internal|citation|footnote|cleaned up)\b"
ID_RX = re.compile(r"(?<![\w.'])(?:(?P<id>[Ii]d\.|[Ii]bid\.?|[Ii]d(?=,? at \*?\d|" + ID_PAREN + r"| [§¶] ?\d))"
                   r"(?P<pin>,? at " + PAGE_PIN + r"(?:, " + PAGE_PIN + r")*(?![\d(])"
                   r"|,? at [^\s,;)]+| §§? ?\d[\w.()\-–]*| ¶ ?\d+| (?:art|cl|r)\. ?[\w.()]+)?"
                   r"|(?P<bare_id>Id) (?P<bare>\d{1,5}(?:[-–]\d{1,5})?)(?![\d:]|[.,]\d))")
SUPRA_RX = re.compile(r"\(?\bsupra\b\)?(?: note \d+)?(?P<pin>,? at (?P<page>" + PAGE_PIN + r"))?")
SUPRA_NAME = re.compile(r"((?:[A-Z][\w'&\-]*\.?|v\.|of|the|de|for|&|ex rel\.)(?: (?:[A-Z][\w'&\-]*\.?,?|v\.|of|the|de|for|&|ex rel\.)){0,10}),? $")
SHORT_NAME = re.compile(r"((?:[A-Z][\w'&\-]*\.?|of|the|de|&|ex rel\.)(?: (?:[A-Z][\w'&\-]*\.?|of|the|de|&|ex rel\.)){0,5}), $")
# Record and appendix cites ("Trial R.19", "(R. 45)", "(V3 T. 120)", "App. 12", "I.B. at 5"), which an
# Id. may follow (wrongly, Indigo Book R26), though the script doesn't extract them.
RECORD_RX = re.compile(r"(?<![\w.])(?:(?:Trial|Supp\.|Vol\.|V\d+|[IVX]+|PC|Post-?conviction)\s?)?"
                       r"(?:R|T|TR|Tr|SR|PCR|PC-R|ROA|App|Appx|A|Ex|SA|I\.?B|A\.?B|R\.?B|Doc|ECF(?: No)?)\.? ?"
                       r"(?:at |p\. ?|pp\. ?|\d+:)?\d+")
# Depositions, transcripts, affidavits, and exhibits in a trial-court filing ("Dep. A. Smith, at 12:4-6",
# "Smith Dep. 12:4", "Hr'g Tr. 5", "Aff. ¶ 3", 'Exhibit "C"'), and any page:line pinpoint. An Id. after one
# of these refers to it, not to the case or statute before it.
TRANSCRIPT_RX = re.compile(r"(?<![\w.])(?:Dep(?:o)?\.|Deposition|Tr\.|Transcript|Aff\.|Affidavit|Decl\.|Declaration)(?=[\s,])"
                           r"|\b(?:Exhibit|Ex\.) [\"“]?[A-Z0-9]{1,3}\b"
                           r"|(?<![\d:])\d{1,4}: ?\d{1,2}(?:-\d{1,4}(?::\d{1,2})?)?(?![\d:])")
# An Id. pinpointed to a page and line ("Id. at 14:2") cites a transcript.
ID_TRANSCRIPT_PIN = re.compile(r"[Ii]d\.?,? at \d{1,4}: ?\d{1,2}\b")
# A year parenthetical the script didn't take as a citation ("... Federal Courts and the Law 24 (Amy
# Gutmann ed., 1997)") is probably a book or article an Id. may refer to.
UNSEEN_CITE = re.compile(r"\((?:[^()]*[ ,])?(?:1[6-9]|20)\d\d\)"
                         r"|\b[A-Z][A-Za-z.]*\.(?: ?\d?[a-z]{0,2})? at \*?\d")   # or a stray "U.S. at 825"
STRING_GAP = re.compile(r"\s*[.,]?\s*;\s*(?:(?:see|also|cf\.|but|accord|e\.g\.,?|compare|contra|and|with)\s*,?\s*)*$", re.I)
SECTION_KINDS = ("statute", "constitution", "admin_code", "session_law", "rule")
SHORT_KINDS = ("id", "supra")
GOVERNMENT_PARTY = re.compile(r"^(?:State(?: of [A-Z]\w+)?|United States(?: of America)?|People|Commonwealth|Florida|"
                              r"(?:City|Town|Village|County|School Board|Board|Dep't|Department|Div\.|Agency) of\b|In re\b|Ex parte\b)")
REPEAT_WINDOW = 10            # a full citation repeated within this many citations, on the same page, takes a short form


# ---------------------------------------------------------------- the engine

class Engine:
    def __init__(self, data=None, checks=None):
        self.data = data or fc.load("florida.json")
        self.records = checks or fc.load("checks.json")["checks"]
        self.by_id = {r["id"]: r for r in self.records}
        self.compiled = fc.compiled_checks(self.records, self.data)
        self.series = {s["abbr"]: s for s in self.data["reporters"]["series"]}
        # Reporters the rule doesn't name, read as Bluebook-tier case citations (9.800(p)).
        self.bluebook_reporters = {s["abbr"] for s in self.data["reporters"]["bluebook_series"]}
        self.reporter_forms = fc.reporter_forms(self.data)
        rep = fc.reporter_alternation(self.data)
        flw = r"Fla\.? ?L(?:\.|aw) ?W(?:ee)?kly\.?(?P<fed> (?:Supp|Fed)\.)?"
        self.anchor = re.compile(
            r"(?<![\w.,])(?:(?P<vol>\d{1,4}|" + BLANK + r") (?P<rep>" + rep + r") (?:¶ ?)?(?P<page>\d{1,5}|" + BLANK + r")(?!\w)"
            r"|(?P<fvol>\d{1,3}) (?P<flw>" + flw + r") (?P<fsec>[A-Z]?)(?P<fpage>\d{1,5})(?P<fsuf>[a-z]?)(?!\w)"
            r"|(?P<wyear>(?:19|20)\d\d) ?(?P<db>WL|(?:Fla\.|U\.S\.)(?: (?:App\.|Dist\.|Cir\.))? LEXIS) ?(?P<wnum>\d+)(?!\d)"
            r"|(?P<pyear>\d{4}) (?P<fpsc>F\.P\.S\.C\.) (?P<ppage>\d+:\d+))")
        self.short = re.compile(r"(?<![\w.,])(?P<vol>\d{1,4}|" + BLANK + r") (?:(?P<rep>" + rep + r")|(?P<flw>"
                                + flw.replace("(?P<fed>", "(?:") + r")) at (?P<pin>" + PAGE_PIN + r")")
        sets = self.data["rule_sets"]["sets"]
        self.rule_forms = {}
        for s in sets:
            for f in [s["abbr"]] + s["variants"]:
                self.rule_forms[f.lower()] = s
        alt = "|".join(re.escape(f) for f in sorted({f for s in sets for f in [s["abbr"]] + s["variants"]}, key=len, reverse=True))
        num = r"(?P<form>Form )?(?P<num>(?:[IVXL]+, §\s?)?\d+(?:[-–]\d+)?(?:\.\d+)*[A-Z]?[a-z]?(?:\([\w.]+\))*)"
        self.rule_abbr = re.compile(r"(?<![\w.])(?P<set>" + alt + r") ?" + num + r"(?: \((?P<year>\d{4})\))?", re.I)
        names = "|".join(re.escape(s["name"]).replace("Rules", "Rules?") for s in sorted(sets, key=lambda s: -len(s["name"])))
        self.rule_name = re.compile(r"\b(?P<set>" + names + r") " + num)
        self.logic = {
            "series_year": lc_series_year, "flw_exact_date": lc_flw_exact_date, "flw_volume_year": lc_flw_volume_year,
            "flw_section_court": lc_flw_section_court, "flw_stale": lc_flw_stale, "slip_old_form": lc_slip_old_form,
            "westlaw_docket": lc_westlaw_docket, "docket_court": lc_docket_court, "court_began": lc_court_began,
            "date_on_reported": lc_date_on_reported, "paren_unbalanced": lc_paren_unbalanced,
            "quote_unclosed": lc_quote_unclosed, "quote_no_pin": lc_quote_no_pin,
            "statute_year_summary": lc_statute_year_summary, "statute_future_year": lc_statute_future_year,
            "rule_set_number": lc_rule_set_number, "ag_opinion": lc_ag_opinion, "sct_without_us": lc_sct_without_us,
            "federal_no_court": lc_federal_no_court, "west_circuit": lc_west_circuit, "west_dca": lc_west_dca, "docket_no_prefix": lc_docket_no_prefix, "in_sentence": lc_in_sentence,
            "case_name_typeface": lc_case_name_typeface, "court_unreadable": lc_court_unreadable,
            "id_after_string": lc_id_after_string, "id_antecedent": lc_id_antecedent,
            "pin_before_first_page": lc_pin_before_first_page, "short_before_full": lc_short_before_full,
            "short_without_full": lc_short_without_full, "short_volume": lc_short_volume,
            "supra_case": lc_supra_case, "full_repeated": lc_full_repeated, "signal_capital": lc_signal_capital,
            "record_cite_form": lc_record_cite_form, "ellipsis_form": lc_ellipsis_form,
        }
        missing = [r["logic"] for r in self.records if r["kind"] == "logic" and r["logic"] not in self.logic]
        if missing:
            sys.exit("check records name logic functions that don't exist: " + ", ".join(missing))

    # ---- extraction

    def extract(self, doc):
        norm = doc.norm
        quotes = [(a - 1, b) for a, b in doc.block_quotes] + doc.quotes
        cites = []
        cites += self._cases(norm)
        taken = [(c["start"], c["end"]) for c in cites]
        for c in self._slips(norm):
            if not _overlaps(c, taken):
                cites.append(c)
        others = self._statutes(norm) + self._constitutions(norm) + self._admin(norm) + self._laws(norm) \
            + self._rules(norm) + self._ags(norm) + self._shorts(norm) + self._ids(norm) + self._supras(norm)
        spans = [(o["start"], o["end"]) for o in others]
        blocks = []                            # block quotations, their lines joined
        for a, b in sorted(doc.block_quotes):
            if blocks and not norm[blocks[-1][1]:a].strip():
                blocks[-1] = (blocks[-1][0], max(b, blocks[-1][1]))
            else:
                blocks.append((a, b))
        for c in cites:
            if c.get("case_name") and any(c["start"] < b and a < c["cite_start"] for a, b in spans):
                c["case_name"] = None          # the walk back from "v." ran into another citation
                c.pop("name_start", None)
                c["start"] = c["cite_start"]
            for a, b in blocks:
                if c.get("case_name") and a <= c["start"] < b <= c["cite_start"]:
                    # ... or into the block quotation the citation gives the source of ("A. Yes. Smith v. ...")
                    # Only when what follows the block is a whole name; a block ending mid-name is the
                    # text rules' guess, so the name stays as it was.
                    b += len(norm[b:]) - len(norm[b:].lstrip())
                    name = norm[b:c["cite_start"]].rstrip(", ")
                    if re.match(r"\S.* v\. \S", name) or name.startswith(("In re ", "Ex parte ")):
                        c["case_name"], c["start"], c["name_start"] = name, b, b
        cites = _resolve(cites, others)
        cites = _resolve(cites, self._unrecognized(norm))
        cites.sort(key=lambda c: c["start"])
        prev_case = None
        for i, c in enumerate(cites):
            c["index"] = i
            c["text"] = norm[c["start"]:c["end"]]
            c["in_quote"] = any(a < c["start"] < b for a, b in quotes)
            c["location"] = doc.location(c["start"], c["end"])
            if c["kind"] == "case":
                c["cite"] = case_cite(c)
                if c.get("history") and prev_case is not None:
                    c["history_of"] = prev_case["index"]
                prev_case = c
        return cites

    def _cases(self, norm):
        anchors = list(self.anchor.finditer(norm))
        by_start = {m.start(): m for m in anchors}
        out, consumed = [], -1
        for a in anchors:
            if a.start() < consumed:
                continue
            parts, pins, pos = [a], [], a.end()
            part_pins = [[]]                   # each part's own pinpoints: "530 U.S. 1, 5, 120 S. Ct. 2, 9"
            while True:
                while True:
                    m = PIN.match(norm, pos)
                    if not m or m.start(1) in by_start:
                        break
                    pins.append(m.group(1))
                    part_pins[-1].append(m.group(1))
                    pos = m.end()
                m = EXTRA_PAREN.match(norm, pos)
                if m and norm.startswith(", ", m.end()) and m.end() + 2 in by_start:
                    pos = m.end()
                if norm.startswith(", ", pos) and pos + 2 in by_start:
                    parts.append(by_start[pos + 2])
                    part_pins.append([])
                    pos = parts[-1].end()
                    continue
                break
            paren = None
            m = PAREN.match(norm, pos)
            if m:
                p = parse_paren(m.group(1))
                if p:
                    p["start"], p["end"] = m.start() + m.group(0).index("("), m.end()
                    paren = p
                    pos = m.end()
            consumed = pos
            if paren is None and a.group("rep") and self.reporter_forms[a.group("rep")] in self.bluebook_reporters:
                continue                       # "22 A. 23" in a deposition, "4500 N.W. 27 Avenue": no court and year
            c = {"kind": "case", "start": a.start(), "end": pos, "pins": pins, "paren": paren,
                 "reporters": [], "flw": None, "online": None, "docket": None}
            for p, own_pins in zip(parts, part_pins):
                if p.group("rep"):
                    c["reporters"].append({"volume": p.group("vol"), "reporter": p.group("rep"),
                                           "canonical": self.reporter_forms[p.group("rep")], "page": p.group("page"),
                                           "pins": own_pins, "start": p.start(), "end": p.end()})
                elif p.group("flw"):
                    ed = "main"
                    if p.group("fed"):
                        ed = "supp" if "Supp" in p.group("fed") else "fed"
                    c["flw"] = {"volume": int(p.group("fvol")), "edition": ed, "section": p.group("fsec") or None,
                                "page": p.group("fsec") + p.group("fpage") + p.group("fsuf"), "pins": own_pins,
                                "start": p.start(), "end": p.end(), "primary": not c["reporters"]}
                elif p.group("db") and c["online"] is None:
                    c["online"] = {"service": "Westlaw" if p.group("db") == "WL" else "LEXIS", "year": int(p.group("wyear")),
                                   "number": p.group("wnum"), "text": p.group(0), "pins": own_pins,
                                   "start": p.start(), "end": p.end(), "primary": not c["reporters"] and not c["flw"]}
                elif p.group("fpsc"):
                    c["reporters"].append({"volume": p.group("pyear"), "reporter": "F.P.S.C.", "canonical": "F.P.S.C.",
                                           "page": p.group("ppage"), "pins": own_pins, "start": p.start(), "end": p.end()})
            numeric = [r for r in c["reporters"] if r["volume"][0].isdigit()]
            c["placeholder"] = bool(c["reporters"]) and not numeric
            if c["online"] and (c["reporters"] or c["flw"]):
                c["online"]["primary"] = False      # a parallel to a reporter or Fla. L. Weekly cite, in either order
            # a docket number before a Westlaw/LEXIS or slip cite: "No. SC2010-1544, 2014 WL ..."
            w = norm[max(0, c["start"] - 160):c["start"]]
            m = DOCKET_BEFORE.search(w)
            if m and (c["online"] or not c["reporters"]):
                d0 = c["start"] - len(w) + m.start()
                c["docket"] = _docket(norm, d0, c["start"] - len(w) + m.end())
                c["docket"].update(start=d0, end=d0 + len(c["docket"]["text"]), bare=bool(m.group("bare")))
                c["start"] = d0
            if c["reporters"] and c["reporters"][0]["canonical"] in self.bluebook_reporters and not c["docket"]:
                m = OFFICIAL_BEFORE.search(norm, max(0, c["start"] - 80), c["start"])
                if m and "." in m.group("rep") and m.group("rep") not in self.reporter_forms:
                    c["official"] = m.group(0).rstrip(", ")      # its case name comes before it
                    c["start"] = m.start()
            if paren is None and not c["reporters"] and not c["flw"]:
                c["kind"] = "case_short"          # "Beckman, 2026 WL 91580, at *12"
            self._name_and_history(norm, c)
            if c["kind"] == "case_short":
                c["pin"] = pins[0] if pins else None
                _short_name(norm, c)
            self._tier_case(c)
            out.append(c)
        return out

    def _slips(self, norm):
        out = []
        for m in SLIP.finditer(norm):
            pm = PAREN.match(norm, m.end())
            if not pm:
                continue
            p = parse_paren(pm.group(1))
            if not p or (p["year"] is None and p["month"] is None) or p["court"]["id"] is None:
                continue
            p["start"], p["end"] = pm.start() + pm.group(0).index("("), pm.end()
            c = {"kind": "case", "start": m.start(), "end": pm.end(), "pins": [], "paren": p, "reporters": [],
                 "flw": None, "online": None, "placeholder": False,
                 "docket": _docket(norm, m.start(), m.end())}
            self._name_and_history(norm, c)
            self._tier_case(c)
            out.append(c)
        return out

    def _name_and_history(self, norm, c):
        c["case_name"] = None
        name_start = c["start"]
        w0 = max(0, c["start"] - 220)
        w = norm[w0:c["start"]]
        if w.endswith(", "):
            head = w[:-2]
            v = None
            for m in re.finditer(r" (?:v|vs)\. ", head):
                v = m
            inre = None
            for m in re.finditer(r"\b(?:In re|Ex parte|In the Interest of|In the Matter of|Petition of) ", head):
                inre = m
            if v and (not inre or v.start() > inre.start()):
                defendant = re.sub(r" \([A-Z][^()]{0,40}\)$", "", head[v.end():])   # "State (Phoenix II)"
                # A party may start with a number ("United States v. 4100 Elm St."); a citation inside
                # the name may not.
                rest = re.sub(r"^\$?\d[\d,]*\s", "", defendant)
                if len(defendant) <= 140 and not BAD_NAME.search(rest):
                    first = None                       # offset in head of the plaintiff's first word
                    toks = list(re.finditer(r"\S+", head[:v.start()]))
                    j = len(toks) - 1
                    while j >= 0:
                        tm, t = toks[j], toks[j].group(0)
                        if (t == "through" and j >= 2 and toks[j - 1].group(0) in ("&", "and")
                                and toks[j - 2].group(0) == "by"):
                            j -= 3                     # "Doe by & through Doe"
                            continue
                        bare = t.strip("(\"'[")
                        low = bare.lower()
                        if not bare or len(toks) - 1 - j >= 14 or low in NAME_STOP or not _name_word(t, bare, low):
                            break
                        first = tm.start() + (len(t) - len(t.lstrip("(\"'[")))
                        if t[0] in "(\"'[":
                            break
                        j -= 1
                    if first is not None:
                        name = head[first:]
                        while True:                    # "of the Smith v. Jones" -> "Smith v. Jones"
                            m = re.match(r"(\S+) ", name)
                            if not m or m.group(1).lower() not in NAME_CONNECTORS or name.startswith(m.group(1) + " v. "):
                                break
                            name = name[m.end():]
                        c["case_name"] = name
                        name_start = c["start"] - 2 - len(name)
            elif inre:
                rest = head[inre.start():]
                if len(rest) <= 140 and not BAD_NAME.search(rest):
                    c["case_name"] = rest
                    name_start = w0 + inre.start()
        c["cite_start"] = c["start"]
        if c["case_name"]:
            c["name_start"] = name_start
            c["start"] = name_start
        h = HISTORY.search(norm[max(0, name_start - 90):name_start])
        c["history"] = h.group(0).rstrip(", ") if h else None

    def _tier_case(self, c):
        rep = c["reporters"][0]["canonical"] if c["reporters"] else None
        if c["kind"] == "case" and rep in self.bluebook_reporters:
            c["sub"], c["tier"], c["authority"] = None, TIER_BLUEBOOK, "9.800(p)"
            c["what"] = f"case reported in {rep}, a reporter Rule 9.800 doesn't name"
            return
        court = c["paren"]["court"] if c["paren"] else None
        sub = court["sub"] if court else None
        family = court["family"] if court else None
        if court is None or court["id"] is None:
            rep = c["reporters"][0]["canonical"] if c["reporters"] else None
            if rep in ("U.S.", "S. Ct.", "L. Ed.", "L. Ed. 2d"):
                sub, family = "l", "federal"
            elif rep in ("F.", "F.2d", "F.3d", "F.4th", "F. App'x"):
                sub, family = "m", "federal"
            elif rep and rep.startswith("F. Supp."):
                sub, family = "n", "federal"
            elif rep == "Fla.":
                sub, family = "a", "florida"
            elif rep in ("F.C.S.R.", "F.P.E.R.", "F.P.S.C."):
                sub, family = "d", "florida"
            elif c["flw"]:
                f = c["flw"]
                if f["edition"] == "fed":
                    sub = {"S": "l", "C": "m", "D": "n"}.get(f["section"])
                    family = "federal"
                elif f["edition"] == "supp":
                    sub, family = "c", "florida"
                else:
                    sub = {"S": "a", "D": "b", "C": "c"}.get(f["section"])
                    family = "florida"
            elif rep and rep.startswith("So."):
                sub, family = None, "florida?"
        c["sub"] = sub
        if family == "other":
            c["tier"], c["authority"] = TIER_BLUEBOOK, "9.800(p)"
        elif sub:
            c["tier"], c["authority"] = TIER_RULE, f"9.800({sub})"
        else:
            c["tier"], c["authority"] = TIER_RULE, "9.800(a)-(b)" if family == "florida?" else "9.800"

    def _statutes(self, norm):
        out = []
        for form, rx in STATUTES:
            for m in rx.finditer(norm):
                g = m.groupdict()
                year = g.get("year")
                code = (g.get("code") or "").lower()
                hybrid = (form == "abbreviated" and code.startswith("florida")) or (form == "sentence" and code.startswith("fla."))
                # hybrid: "§ 827.03, Florida Statutes" or "section 61.13, Fla. Stat."
                sec_end = m.end("sec") if g.get("sec") else m.end("sec2")
                out.append({"kind": "statute", "form": "hybrid" if hybrid else form, "start": m.start(), "end": m.end(),
                            "section": g.get("sec") or g.get("sec2"), "year": _year(year),
                            "unreadable": _unreadable_sub(norm, sec_end, m.end()),
                            "tier": TIER_RULE, "authority": "9.800(f)"})
        for m in ANNOTATED_ORDER.finditer(norm):
            out.append({"kind": "statute", "form": "annotated-order", "start": m.start(), "end": m.end(),
                        "section": m.group("sec"), "year": _year(m.group("year")),
                        "unreadable": _unreadable_sub(norm, m.end("sec"), m.end()), "tier": TIER_RULE,
                        "authority": "9.800(f)"})
        for m in ANNOTATED.finditer(norm):
            out.append({"kind": "statute", "form": "annotated", "start": m.start(), "end": m.end(),
                        "section": m.group("sec"), "year": _year(m.group("year")), "tier": TIER_RULE, "authority": "9.800(g)"})
        return out

    def _constitutions(self, norm):
        out = []
        for form, rx in CONSTITUTIONS:
            for m in rx.finditer(norm):
                which = m.group("which")
                florida = which.lower().startswith(("fla", "florida"))
                out.append({"kind": "constitution", "form": form, "start": m.start(), "end": m.end(),
                            "which": "Florida" if florida else "United States",
                            "article": m.group("num"), "section": m.groupdict().get("sec"),
                            "amendment": "amend" in (m.groupdict().get("what") or "").lower(),
                            "tier": TIER_RULE, "authority": "9.800(e)" if florida else "9.800(o)"})
        return out

    def _admin(self, norm):
        out = []
        for form, rx in ADMIN_CODE:
            for m in rx.finditer(norm):
                g = m.groupdict()
                out.append({"kind": "admin_code", "form": form, "start": m.start(), "end": m.end(),
                            "rule": g.get("rule") or g.get("rule2"), "year": _year(g.get("year")),
                            "tier": TIER_RULE, "authority": "9.800(h)"})
        return out

    def _laws(self, norm):
        out = []
        for form, rx in SESSION_LAWS:
            for m in rx.finditer(norm):
                out.append({"kind": "session_law", "form": form, "start": m.start(), "end": m.end(),
                            "chapter": m.group("ch"), "tier": TIER_RULE, "authority": "9.800(i)"})
        return out

    def _rules(self, norm):
        out = []
        for m in self.rule_abbr.finditer(norm):
            s = self.rule_forms[m.group("set").lower()]
            out.append({"kind": "rule", "form": "abbreviated", "start": m.start(), "end": m.end(),
                        "set": s["n"], "set_as_written": m.group("set"), "number": m.group("num"),
                        "is_form": bool(m.group("form")), "number_start": m.start("num"),
                        "unreadable": _unreadable_sub(norm, m.end("num"), m.end()),
                        "tier": TIER_RULE, "authority": f"9.800(j)({s['n']})"})
        by_name = {s["name"].lower(): s for s in self.data["rule_sets"]["sets"]}
        for m in self.rule_name.finditer(norm):
            name = m.group("set").lower()
            s = by_name.get(name) or by_name.get(name.replace("rule ", "rules ", 1)) or \
                next((v for k, v in by_name.items() if re.fullmatch(re.escape(k).replace("rules", "rules?"), name)), None)
            if s is None:
                continue
            out.append({"kind": "rule", "form": "sentence", "start": m.start(), "end": m.end(), "set": s["n"],
                        "set_as_written": m.group("set"), "number": m.group("num"), "is_form": bool(m.group("form")),
                        "unreadable": _unreadable_sub(norm, m.end("num"), m.end()),
                        "number_start": m.start("num"), "tier": TIER_RULE, "authority": f"9.800(j)({s['n']})"})
        return out

    def _ags(self, norm):
        out = []
        for rx in AG_OPINIONS:
            for m in rx.finditer(norm):
                out.append({"kind": "ag_opinion", "start": m.start(), "end": m.end(), "number": m.group("num"),
                            "year": _year(m.group("year")), "tier": TIER_RULE, "authority": "9.800(k)"})
        return out

    def _shorts(self, norm):
        out = []
        for m in self.short.finditer(norm):
            c = {"kind": "case_short", "start": m.start(), "end": m.end(), "tier": TIER_RULE, "authority": "9.800",
                 "reporters": [], "flw": None, "online": None, "paren": None, "docket": None, "pin": m.group("pin")}
            if m.group("rep"):
                c["reporters"].append({"volume": m.group("vol"), "reporter": m.group("rep"),
                                       "canonical": self.reporter_forms[m.group("rep")], "page": None,
                                       "start": m.start(), "end": m.start("rep") + len(m.group("rep"))})
            else:
                f = m.group("flw")
                ed = "supp" if "Supp" in f else ("fed" if "Fed" in f else "main")
                c["flw"] = {"volume": int(m.group("vol")), "edition": ed, "page": None}
            _short_name(norm, c)
            out.append(c)
        return out

    def _ids(self, norm):
        out = []
        for m in ID_RX.finditer(norm):
            pin = "at " + m.group("bare") if m.group("bare") else (m.group("pin") or "").lstrip(", ")
            kind = None
            if pin.startswith("at "):
                kind = "page" if re.match(r"at \*{0,2}[A-Z]?\d+(?![\d.:(])", pin) else "other"
            elif pin.startswith("§"):
                kind = "section"
            elif pin:
                kind = "other"
            out.append({"kind": "id", "start": m.start(), "end": m.end(), "form": m.group("id") or m.group("bare_id"),
                        "pin": pin or None,
                        "pin_kind": kind, "tier": TIER_BLUEBOOK, "authority": "9.800(p)"})
        return out

    def _supras(self, norm):
        out = []
        for m in SUPRA_RX.finditer(norm):
            w0 = max(0, m.start() - 120)
            nm = SUPRA_NAME.search(norm, w0, m.start())
            if not nm:
                continue
            name, start = nm.group(1), nm.start(1)
            while True:                            # "See also Jackson" -> "Jackson"
                t = re.match(r"(\S+) ", name)
                if not t or t.group(1).lower().rstrip(",") not in NAME_STOP | {"see"}:
                    break
                name, start = name[t.end():], start + t.end()
            if not name or not name[0].isupper():
                continue
            out.append({"kind": "supra", "start": start, "end": m.end(), "name": name.rstrip(","),
                        "pin": m.group("page"), "tier": TIER_BLUEBOOK, "authority": "9.800(p)"})
        return out

    def _unrecognized(self, norm):
        out = []
        for tier, what, rx in UNRECOGNIZED:
            for m in rx.finditer(norm):
                end = m.end() - 1 if m.group(0).endswith(".") and norm[m.end():m.end() + 1] in (" ", "") else m.end()
                while norm[end - 1] == ")" and norm.count("(", m.start(), end) < norm.count(")", m.start(), end):
                    end -= 1                   # "(... 18 U.S.C. § 922(g))": the last ) closes the sentence's paren
                out.append({"kind": "unrecognized", "start": m.start(), "end": end, "what": what,
                            "tier": tier, "authority": "9.800(p)"})
        for m in GENERIC_REPORTER.finditer(norm):
            if "." not in m.group("rep") or m.group("rep") in self.reporter_forms:
                continue
            if re.match(r"(?:" + MONTH_RX + r")$", m.group("rep")):
                continue
            out.append({"kind": "unrecognized", "start": m.start(), "end": m.end(),
                        "what": "reporter outside Rule 9.800", "tier": TIER_BLUEBOOK, "authority": "9.800(p)"})
        return out

    # ---- checking

    def run(self, source, doc_date=None, date_source=None):
        doc = Doc(source)
        cites = self.extract(doc)
        ctx = {"doc": doc, "cites": cites, "doc_date": doc_date, "engine": self, "source": source}
        ctx["links"] = link_short_forms(doc, cites)
        for c in cites:
            if c["kind"] in ("case", "case_short"):
                c["toa"] = _toa_entry(doc, c)     # a table-of-authorities line, not a use of the case
        quotations = tie_quotations(doc, cites)
        ctx["quotations"] = quotations
        findings, quoted_pages = [], []
        for f in fc.scan(doc.norm, self.compiled, include_quoted=True):
            if any(a <= f["start"] < b for a, b in doc.block_quotes) or any(a < f["start"] < b for a, b in doc.quotes):
                quoted_pages.append(doc.location(f["start"], f["end"]).get("page"))
                continue                      # the quoted writer's form, not this document's
            rec = self.by_id[f["check"]]
            c = _containing(cites, f["start"], f["end"])
            if (c is not None and c["tier"] != TIER_RULE and c["kind"] not in SHORT_KINDS
                    and not (c["tier"] == TIER_BLUEBOOK and rec.get("tier") == "bluebook")):
                continue                      # another tier governs; reported as unrecognized below
            findings.append(self._finding(doc, rec, f["start"], f["end"], fix=f["fix"], authority=f["authority"],
                                          citation=c))
        for rec in self.records:
            if rec["kind"] != "logic":
                continue
            for hit in self.logic[rec["logic"]](ctx, rec):
                findings.append(self._finding(doc, rec, **hit))
        for f in findings:
            if f["fix"] and f["citation"] is not None and cites[f["citation"]].get("unreadable"):
                f["fix"] = None               # it would drop the subsection; paren-unbalanced reports it
                f["message"] += " No fix is offered: the subsection after the number can't be read."
        for c in cites:
            if c["tier"] != TIER_RULE and not c["in_quote"] and c["kind"] not in SHORT_KINDS:
                what = c.get("what") or {"case": "case from a court Rule 9.800 doesn't cover"}.get(c["kind"], c["kind"])
                if c["tier"] == TIER_FSM:
                    msg = (f"{what[0].upper() + what[1:]}: Florida material neither Rule 9.800 nor the Bluebook covers. "
                           "Check its form against the Florida Style Manual (9.800(p)).")
                else:
                    msg = (f"{what[0].upper() + what[1:]}: outside Rule 9.800's forms, so 9.800(p) sends it to the "
                           "Bluebook system. Check it by hand against the Indigo Book.")
                findings.append({"check": "p-other-citations", "severity": "unrecognized", "authority": "9.800(p)",
                                 "tier": c["tier"], "message": msg, "found": c["text"], "fix": None,
                                 "citation": c["index"], "location": c["location"]})
        findings = self._summarize(findings)
        findings.sort(key=lambda f: (SEVERITIES.index(f["severity"]), f["location"]["start"], f["check"]))
        for i, f in enumerate(findings, 1):
            f["id"] = f"F{i}"
        counts = {s: sum(1 for f in findings if f["severity"] == s) for s in SEVERITIES}
        tiers = {}
        for c in cites:
            if c["kind"] not in ("case_short",) + SHORT_KINDS:
                tiers[c["tier"]] = tiers.get(c["tier"], 0) + 1
        notes = []
        appended = None
        if source.cut:
            notes.append(f"Checked pages 1 to {source.cut[0]} of {source.cut[1]} (--last-page {source.cut[0]}).")
        else:
            appended = doc.appended()
        if appended:
            k = appended["page"]
            appended["label"] = doc.page_name(k)
            notes.append(f"{doc.page_name(k)} {appended['why']}, so the pages from there on are probably exhibits "
                         "or an appendix: another writer's citations and quotations, checked and listed with this "
                         f"document's. To check only the document, rerun with --last-page {k - 1}.")
        if source.emphasis is None:
            notes.append("Case-name typeface (9.800(q)) can't be checked in plain text; check a .docx to cover it.")
        unclear = sum(1 for c in cites if c["kind"] == "id" and c.get("antecedent") == "unclear")
        if unclear:
            notes.append(f"{unclear} Id. citation{'s' if unclear != 1 else ''} weren't checked because what "
                         f"{'they refer' if unclear != 1 else 'it refers'} to isn't clear to the script (a record "
                         "cite, a quotation, an unrecognized citation, or a footnote comes between).")
        if quoted_pages:
            n, where = len(quoted_pages), sorted({p for p in quoted_pages if p})
            notes.append(f"{n} form departure{'s' if n != 1 else ''} inside quotations weren't reported: the quoted "
                         f"writer's form, not this document's" + (f" ({_page_list(where, doc)})" if where else "")
                         + ". If a passage there isn't really a quotation, check it by hand.")
        empty = doc.empty_pages()
        if empty and len(empty) < doc.pages:
            notes.append(f"Little or no text on {_page_list(empty, doc)}. If {'those pages are' if len(empty) > 1 else 'it is'} "
                         "scanned, the citations there weren't checked; run OCR on them (ocrmypdf --skip-text "
                         "leaves the pages that have text alone).")
        return {
            "tool": "fl_cite.py check",
            "input": source.name,
            "format": source.kind,
            "rule_as_of": self.data["rule_as_of"],
            "doc_date": doc_date.isoformat() if doc_date else None,
            "doc_date_source": date_source,
            "pages": doc.pages if doc.ff else None,
            "summary": {"findings": counts, "citations": sum(tiers.values()), "by_tier": tiers},
            "findings": findings,
            "citations": [_public(c) for c in cites],
            "quotations": quotations,
            "appended": appended,
            "notes": notes,
        }

    def _finding(self, doc, rec, start, end, fix=None, authority=None, citation=None, detail=None, count=None,
                 occurrences=None, severity=None, found=None):
        if fix is not None:
            end, fix = _tidy_fix(doc.norm, end, fix)
        authority = _narrow(authority or rec["authority"], citation.get("sub") if citation else None)
        f = {"check": rec["id"], "severity": severity or rec["severity"], "authority": authority,
             "tier": TIER_BLUEBOOK if rec.get("tier") == "bluebook" else TIER_RULE,
             "message": rec["message"] + (" " + detail if detail else ""),
             "found": found if found is not None else doc.norm[start:end], "fix": fix,
             "citation": citation["index"] if citation else None, "location": doc.location(start, end)}
        if count is not None:
            f["count"] = count
        if occurrences is not None:
            f["occurrences"] = [doc.location(a, b) for a, b in occurrences]
        return f

    def _summarize(self, findings):
        """Records marked 'summarize' report one finding per distinct (found, fix), with a count."""
        out, groups = [], {}
        for f in findings:
            rec = self.by_id.get(f["check"])
            if rec and rec.get("summarize"):
                key = (f["check"], f["found"], f["fix"])
                if key in groups:
                    g = groups[key]
                    g["count"] += 1
                    g["occurrences"].append(f["location"])
                    continue
                f["count"] = 1
                f["occurrences"] = [f["location"]]
                groups[key] = f
            out.append(f)
        return out


CITATION_ENDS = ("F.A.C.", "F. A. C.", "F.S.", "F. S.", "Fla. Stat.", "Fla. Const.", "U.S. Const.", "Laws of Fla.")


def _tidy_fix(norm, end, fix):
    """Keep a sentence's final period right when a fix replaces text that ends in an abbreviation:
    'Fla. Const. art. V, § 3.' -> 'Art. V, § 3, Fla. Const.' (one period, not two), and
    'Rule 62D-2.014, F.A.C. The' -> 'Fla. Admin. Code R. 62D-2.014. The' (the period stays)."""
    found = norm[:end]
    after = norm[end:end + 2]
    if fix.endswith(".") and after[:1] == ".":
        return end + 1, fix
    if (found.endswith(CITATION_ENDS) and not fix.endswith(".")
            and (after == "" or re.fullmatch(r" [A-Z\"(]", after))):
        return end, fix + "."
    return end, fix


def _narrow(authority, sub):
    """'9.800(a)(3), (b)(2)' -> '9.800(b)(2)' for a district court citation; unchanged otherwise."""
    if not sub or not authority.startswith("9.800(") or ", (" not in authority:
        return authority
    parts = re.findall(r"\(([a-q])\)((?:\(\w+\))*)", authority.split(";")[0])
    for letter, rest in parts:
        if letter == sub:
            return f"9.800({letter}){rest}"
    return authority


def _year(s):
    if not s:
        return None
    m = re.search(r"\d{4}", s)
    return int(m.group(0)) if m else None


def _unreadable_sub(norm, num_end, end):
    """Does a statute or rule number that ends its citation run into a subsection the script can't read,
    such as "48.031(2(b))" or "1.510(c", where the parentheses don't pair? Not a parenthetical set
    without its space: "48.031(1)(emphasis added)"."""
    return num_end == end and re.match(r"\((?:\d+|[A-Za-z]|[ivxIVX]{2,4})?(?:[(\s,;}\]|]|$)", norm[end:end + 8]) is not None


def _docket(norm, start, end):
    text = norm[start:end].rstrip(", ")
    nums = [(m.start(), m.end()) for m in re.finditer(DOCKET, text)]
    toks = [{"text": text[a:b], "start": start + a, "end": start + b} for a, b in nums
            if not re.fullmatch(r"(?:Case|Nos?)\.?", text[a:b])]
    return {"text": text, "numbers": toks}


def _short_name(norm, c):
    """The party name before a short case cite ("See Fenelon, 594 So. 2d at 293" -> "Fenelon"), taken
    into the citation's span. Not every short cite has one: the name may sit in the sentence before."""
    c["short_name"] = None
    m = SHORT_NAME.search(norm, max(0, c["start"] - 80), c["start"])
    if not m:
        return
    name, start = m.group(1), m.start(1)
    while True:
        t = re.match(r"(\S+) ", name)
        if not t or t.group(1).lower() not in NAME_STOP | {"see"}:
            break
        name, start = name[t.end():], start + t.end()
    if (name and name[0].isupper() and name.lower() not in NAME_STOP
            and not re.search(r"\b(?:Fla|Stat|Const|Ann|Admin|Ct|Cir|Supp)\.|\bDCA\b", name)):
        c["short_name"] = name
        c["start"] = start


FLW_ABBR = {"main": "Fla. L. Weekly", "supp": "Fla. L. Weekly Supp.", "fed": "Fla. L. Weekly Fed."}


def case_cite(c):
    """The cite a case-law tool looks a case up by, in standard form: '594 So. 2d 292', '16 Fla. L. Weekly
    D1507', '2014 WL 7463592', or the docket number. None for a placeholder (___ So. 3d ___)."""
    for r in c["reporters"]:
        if r["volume"][0].isdigit() and r["page"] and r["page"][0].isdigit():
            return f"{r['volume']} {r['canonical']} {r['page']}"
    if c["flw"]:
        return f"{c['flw']['volume']} {FLW_ABBR[c['flw']['edition']]} {c['flw']['page']}"
    if c["online"]:
        o = c["online"]
        return f"{o['year']} WL {o['number']}" if o["service"] == "Westlaw" else re.sub(r"\s+", " ", o["text"])
    if c["docket"] and c["docket"]["numbers"]:
        return c["docket"]["numbers"][0]["text"]
    return None


def _overlaps(c, spans):
    return any(c["start"] < b and a < c["end"] for a, b in spans)


def _resolve(kept, candidates):
    """Add candidates that overlap nothing kept; among overlapping candidates the longest wins."""
    spans = [(c["start"], c["end"]) for c in kept]
    out = list(kept)
    for c in sorted(candidates, key=lambda c: (-(c["end"] - c["start"]), c["start"])):
        if not _overlaps(c, spans):
            out.append(c)
            spans.append((c["start"], c["end"]))
    return out


def _containing(cites, start, end):
    for c in cites:
        if c["start"] <= start and end <= c["end"]:
            return c
    return None


def _public(c):
    keep = {k: v for k, v in c.items() if k not in ("start", "end", "number_start", "name_start")}
    return keep


def _full_cases(ctx):
    for c in ctx["cites"]:
        if c["kind"] == "case" and not c["in_quote"]:
            yield c


def _sub_auth(c, which, default):
    table = {
        "reporter": {"a": "(a)(1)", "b": "(b)(1)", "l": "(l)(1)", "m": "(m)(1)", "n": "(n)(1)"},
        "unpublished": {"a": "(a)(3)", "b": "(b)(2)", "c": "(c)", "d": "(d)", "l": "(l)(2)", "m": "(m)(2)", "n": "(n)(2)"},
    }[which]
    p = table.get(c.get("sub"))
    return "9.800" + p if p else default


def _court_id(c):
    return c["paren"]["court"]["id"] if c["paren"] and c["paren"]["court"] else None


# ---------------------------------------------------------------- logic checks (data/checks.json 'logic')
# Each takes (ctx, record) and yields keyword arguments for Engine._finding.

def lc_series_year(ctx, rec):
    series = ctx["engine"].series
    for c in _full_cases(ctx):
        y = c["paren"]["year"] if c["paren"] else None
        if not y:
            continue
        for r in c["reporters"]:
            s = series.get(r["canonical"])
            if not s or s.get("date_check") is False or not r["volume"][0].isdigit():
                continue
            hi = s["last"] + 1 if s["last"] else 9999
            if not s["first"] - 1 <= y <= hi:
                yield {"start": r["start"], "end": c["paren"]["end"], "citation": c,
                       "authority": _sub_auth(c, "reporter", rec["authority"]),
                       "detail": f"{s['abbr']} covers {s['first']}-{s['last'] or 'present'}; this citation gives {y}."}


def _flw_primary(c):
    return c["flw"] and (c["flw"]["primary"] or c["placeholder"])


def lc_flw_exact_date(ctx, rec):
    for c in _full_cases(ctx):
        if _flw_primary(c) and c["paren"] and c["paren"]["year"] and not c["paren"]["month"]:
            yield {"start": c["paren"]["start"], "end": c["paren"]["end"], "citation": c,
                   "authority": _sub_auth(c, "unpublished", rec["authority"]),
                   "detail": "The exact date comes from the source."}


def lc_flw_volume_year(ctx, rec):
    eds = {e["abbr"]: e for e in ctx["engine"].data["florida_law_weekly"]["editions"]}
    key = {"main": "Fla. L. Weekly", "supp": "Fla. L. Weekly Supp.", "fed": "Fla. L. Weekly Fed."}
    for c in _full_cases(ctx):
        f = c["flw"]
        if not f or not c["paren"] or not c["paren"]["year"]:
            continue
        e = eds[key[f["edition"]]]
        y = c["paren"]["year"]
        if f["volume"] - (y - e["offset"]) not in e["allow"]:
            yield {"start": f["start"], "end": c["paren"]["end"], "citation": c,
                   "authority": _sub_auth(c, "unpublished", rec["authority"]),
                   "detail": f"Volume {f['volume']} of {e['abbr']} points to about {f['volume'] + e['offset']}, not {y}."}


def lc_flw_section_court(ctx, rec):
    expect = {"main": {"S": ("SC",), "D": ("1D", "2D", "3D", "4D", "5D", "6D", "DCA"), "C": ("circuit", "county")},
              "fed": {"S": ("USSC",), "C": "CA", "D": ("district", "N.D. Fla.", "M.D. Fla.", "S.D. Fla.")}}
    for c in _full_cases(ctx):
        f = c["flw"]
        cid = _court_id(c)
        if not f or not cid or f["edition"] not in expect or not f["section"]:
            continue
        want = expect[f["edition"]].get(f["section"])
        if want is None:
            continue
        ok = cid.startswith(want) if isinstance(want, str) else cid in want
        if not ok and cid not in ("other",):
            yield {"start": f["start"], "end": c["paren"]["end"], "citation": c,
                   "authority": _sub_auth(c, "unpublished", rec["authority"]),
                   "detail": f"Section {f['section']} doesn't fit ({c['paren']['court_text']})."}


def lc_flw_stale(ctx, rec):
    doc_date = ctx["doc_date"]
    months = ctx["engine"].data["florida_law_weekly"].get("stale_after_months", 12)
    if not doc_date:
        return
    for c in _full_cases(ctx):
        f = c["flw"]
        if not f or f["edition"] != "main" or not _flw_primary(c) or not c["paren"] or not c["paren"]["year"]:
            continue
        p = c["paren"]
        decided = dt.date(p["year"], p["month"] or 12, p["day"] or 28)
        if (doc_date - decided).days > months * 30.44:
            yield {"start": f["start"], "end": p["end"], "citation": c,
                   "authority": _sub_auth(c, "unpublished", rec["authority"]),
                   "detail": f"Decided {(doc_date - decided).days // 30} months before this document; "
                             "if it's in Southern Reporter now, cite that (a fact to look up)."}


def lc_slip_old_form(ctx, rec):
    doc_date = ctx["doc_date"]
    eff = dt.date.fromisoformat(ctx["engine"].data["case_numbers"]["new_form_effective"])
    if not doc_date or doc_date < eff:
        return
    for c in _full_cases(ctx):
        if not c["docket"]:
            continue
        for d in c["docket"]["numbers"]:
            if not re.fullmatch(r"(?:SC|[1-6]D)(?:\d{2}|\d{4})-\d+", d["text"]):
                continue
            new, _ = fc.convert_case_number(d["text"], ctx["engine"].data)
            if new and new != d["text"]:
                yield {"start": d["start"], "end": d["end"], "fix": new, "citation": c,
                       "authority": _sub_auth(c, "unpublished", rec["authority"])}


def lc_westlaw_docket(ctx, rec):
    for c in _full_cases(ctx):
        o = c["online"]
        if (o and o["primary"] and not c["docket"] and not c["history"] and c["paren"] and c.get("sub")
                and c["tier"] == TIER_RULE):
            yield {"start": o["start"], "end": c["paren"]["end"], "citation": c,
                   "authority": _sub_auth(c, "unpublished", rec["authority"]),
                   "detail": "The docket number is a fact to look up."}


def lc_docket_court(ctx, rec):
    for c in _full_cases(ctx):
        cid = _court_id(c)
        if not c["docket"] or cid not in ("SC", "1D", "2D", "3D", "4D", "5D", "6D"):
            continue
        for d in c["docket"]["numbers"]:
            m = re.match(r"(SC|[1-6]D)", d["text"])
            if m and FL_DOCKET.fullmatch(d["text"]) and m.group(1) != cid:
                yield {"start": d["start"], "end": c["paren"]["end"], "citation": c,
                       "authority": _sub_auth(c, "unpublished", rec["authority"]),
                       "detail": f"{m.group(1)} is the {_court_name(m.group(1))}'s prefix."}


def lc_docket_no_prefix(ctx, rec):
    """A docket number before a Westlaw, LEXIS, or slip cite without the "No." every example in Rule 9.800
    gives it: "14-12345-CIV, 2015 WL ..." for "No. 14-12345-CIV, 2015 WL ..."."""
    for c in _full_cases(ctx):
        d = c["docket"]
        if d and d.get("bare") and c["tier"] == TIER_RULE:
            yield {"start": d["start"], "end": d["end"], "citation": c, "fix": "No. " + d["text"],
                   "authority": _sub_auth(c, "unpublished", rec["authority"])}


def _court_name(prefix):
    if prefix == "SC":
        return "Supreme Court"
    return f"{fc.ordinal(int(prefix[0]))} District"


def lc_court_began(ctx, rec):
    data = ctx["engine"].data["courts"]
    began = {c["id"]: c["began"] for c in data["florida_appellate"]}
    for c in data["federal_courts_of_appeals"]:
        if c.get("began"):
            began["CA" + c["paren"].split()[0].rstrip("thndrs").replace(".", "")] = c["began"]
    for c in data["florida_federal_districts"]:
        if c.get("began"):
            began[c["paren"]] = c["began"]
    for c in _full_cases(ctx):
        cid = _court_id(c)
        p = c["paren"]
        if cid not in began or not p["year"]:
            continue
        b = began[cid]
        start_year = int(b[:4])
        if p.get("date"):
            too_early = p["date"] < (b if len(b) > 4 else f"{b}-01-01")
        else:
            too_early = p["year"] < start_year
        if too_early:
            yield {"start": p["start"], "end": p["end"], "citation": c,
                   "authority": _sub_auth(c, "reporter", rec["authority"]),
                   "detail": f"({p['court_text']}) began {b}."}


def lc_date_on_reported(ctx, rec):
    """A month and day on a case cited only to a print reporter. Not slip opinions, placeholders, or cites
    with a Florida Law Weekly, Westlaw, or LEXIS parallel, which take the exact date."""
    for c in _full_cases(ctx):
        p = c["paren"]
        if (not p or not p["month"] or not p["year"] or c["tier"] != TIER_RULE or c["placeholder"] or c["flw"]
                or c["online"] or c["docket"] or not c["reporters"]):
            continue
        fix = f"({p['court_text']} {p['year']})" if p["court_text"] else f"({p['year']})"
        yield {"start": p["start"], "end": p["end"], "citation": c, "fix": fix,
               "authority": _sub_auth(c, "reporter", rec["authority"]),
               "detail": "A date that doesn't fit the reported decision may mean another ruling in the same case; "
                         "the facts loop confirms which."}


def _statutes(ctx):
    return [c for c in ctx["cites"] if c["kind"] == "statute" and c["form"] not in ("annotated", "fs") and not c["in_quote"]]


STATUTE_NOTE = re.compile(r"(?:references?|citations?)\b[^.]{0,80}?(?:(\d{4}) (?:version|edition) of (?:the )?Florida Statutes|"
                          r"Florida Statutes \((\d{4})\)|(\d{4}) Florida Statutes)", re.I)


def lc_statute_year_summary(ctx, rec):
    if STATUTE_NOTE.search(ctx["doc"].norm):
        return
    missing = []
    for c in _statutes(ctx):
        if c["year"]:
            break                      # a year given once carries forward
        missing.append(c)
    if missing:
        first = missing[0]
        yield {"start": first["start"], "end": first["end"], "citation": first, "count": len(missing),
               "occurrences": [(c["start"], c["end"]) for c in missing],
               "detail": f"{len(missing)} statute citation{'s' if len(missing) != 1 else ''} before any edition year is given."}


def lc_statute_future_year(ctx, rec):
    doc_date = ctx["doc_date"]
    if not doc_date:
        return
    for c in ctx["cites"]:
        if c["kind"] == "statute" and not c["in_quote"] and c["year"] and c["year"] > doc_date.year:
            yield {"start": c["start"], "end": c["end"], "citation": c,
                   "detail": f"This document is dated {doc_date.isoformat()}."}


def lc_rule_set_number(ctx, rec):
    sets = {s["n"]: s for s in ctx["engine"].data["rule_sets"]["sets"]}
    for c in ctx["cites"]:
        if c["kind"] != "rule" or c["in_quote"] or c["is_form"]:
            continue
        s = sets[c["set"]]
        number = c["number"].replace("–", "-")
        if s["numbers"] and not re.match(s["numbers"], number):
            fits = [o["abbr"] for o in sets.values() if o["numbers"] and re.match(o["numbers"], number)
                    and o["n"] not in (13, 18, 23)]
            yield {"start": c["start"], "end": c["end"], "citation": c,
                   "detail": f"{s['abbr']} rules are numbered like {s['example']}"
                             + (f"; {c['number']} fits {fits[0]}." if fits else ".")}


def lc_ag_opinion(ctx, rec):
    for c in ctx["cites"]:
        if c["kind"] != "ag_opinion" or c["in_quote"]:
            continue
        text = ctx["doc"].norm[c["start"]:c["end"]]
        if CANONICAL_AG.fullmatch(text):
            continue
        year = c["year"]
        if not year:
            pre = c["number"].split("-")[0]
            year = int(pre) if len(pre) == 4 else (2000 + int(pre) if int(pre) <= 26 else 1900 + int(pre))
        yield {"start": c["start"], "end": c["end"], "citation": c, "fix": f"Op. Att'y Gen. Fla. {c['number']} ({year})"}


def lc_sct_without_us(ctx, rec):
    doc_date = ctx["doc_date"] or dt.date.today()
    lag = ctx["engine"].data["reporters"].get("us_reports_lag_years", 3)
    for c in _full_cases(ctx):
        if (not c["reporters"] or c["reporters"][0]["canonical"] != "S. Ct." or c["history"] or not c["case_name"]
                or not c["paren"] or not c["paren"]["year"]):
            continue
        if re.search(r"(?:" + BLANK + r" U\.S\. " + BLANK + r"|U\.S\. " + BLANK + r")", ctx["doc"].norm[max(0, c["start"] - 30):c["start"]]):
            continue
        if c["paren"]["year"] <= doc_date.year - lag:
            r = c["reporters"][0]
            yield {"start": r["start"], "end": r["end"], "citation": c,
                   "detail": "A case decided that long ago has a U.S. cite by now."}


FEDERAL_REPORTERS = ("F.", "F.2d", "F.3d", "F.4th", "F. App'x", "F. Supp.", "F. Supp. 2d", "F. Supp. 3d")


def lc_federal_no_court(ctx, rec):
    for c in _full_cases(ctx):
        p = c["paren"]
        if (c["reporters"] and c["reporters"][0]["canonical"] in FEDERAL_REPORTERS and p and p["year"]
                and p["court"]["id"] is None):
            yield {"start": p["start"], "end": p["end"], "citation": c,
                   "authority": "9.800(n)(1)" if c["reporters"][0]["canonical"].startswith("F. Supp.") else "9.800(m)(1)",
                   "detail": "Which court is a fact to look up."}


def lc_court_unreadable(ctx, rec):
    for c in _full_cases(ctx):
        p = c["paren"]
        if p and p["court"].get("unreadable"):
            yield {"start": p["start"], "end": p["end"], "citation": c,
                   "detail": f"'{p['court_text']}' names no district; which one is a fact to look up."}


def lc_west_circuit(ctx, rec):
    for c in _full_cases(ctx):
        p = c["paren"]
        if p and p["court"].get("west") and p["court"]["family"] == "federal":
            n = p["court"]["id"][2:]
            court = f"{fc.ordinal(int(n))} Cir." if n.isdigit() else ("D.C. Cir." if n == "DC" else "Fed. Cir.")
            date = p["text"][len(p["court_text"]):].strip()
            yield {"start": p["start"], "end": p["end"], "citation": c, "fix": f"({court} {date})".replace("  ", " ")}


def lc_west_dca(ctx, rec):
    """Westlaw's and Lexis's style for a district court, "(Fla. App. 4th Dist. 2013)" or "(Fla.App. 4 Dist.
    2013)", for the rule's "(Fla. 4th DCA 2013)"."""
    for c in _full_cases(ctx):
        p = c["paren"]
        if p and p["court"].get("west") and p["court"]["family"] == "florida":
            court = f"Fla. {fc.ordinal(int(p['court']['id'][0]))} DCA"
            date = p["text"][len(p["court_text"]):].strip()
            yield {"start": p["start"], "end": p["end"], "citation": c, "fix": f"({court} {date})".replace("  ", " ")}


GOVERNING_STOP = {"see", "also", "cf.", "e.g.,", "accord", "compare", "contra", "but", "quoting", "citing", "and",
                  "or", "&", "generally"}
ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10, "XI": 11,
         "XII": 12, "XIII": 13, "XIV": 14, "XV": 15, "XVI": 16, "XVII": 17, "XVIII": 18, "XIX": 19, "XX": 20,
         "XXI": 21, "XXII": 22, "XXIII": 23, "XXIV": 24, "XXV": 25, "XXVI": 26, "XXVII": 27}
ORDINAL_WORDS = ["", "First", "Second", "Third", "Fourth", "Fifth", "Sixth", "Seventh", "Eighth", "Ninth", "Tenth",
                 "Eleventh", "Twelfth", "Thirteenth", "Fourteenth", "Fifteenth", "Sixteenth", "Seventeenth",
                 "Eighteenth", "Nineteenth", "Twentieth", "Twenty-first", "Twenty-second", "Twenty-third",
                 "Twenty-fourth", "Twenty-fifth", "Twenty-sixth", "Twenty-seventh"]


def spelled_out(c, text, data):
    """The sentence form of an abbreviated citation (9.800's introductory paragraph), or None."""
    k = c["kind"]
    if k == "constitution" and c["form"] == "abbreviated":
        if c["amendment"]:
            n = ROMAN.get(c["article"].upper())
            return f"the {ORDINAL_WORDS[n]} Amendment to the United States Constitution" if n else None
        m = re.match(r"[Aa]rt(?:\.|icle) ([IVXL]+)(?:, §§? ?([^,]+))?(?:, cl\. (\d+))?", text)
        if not m:
            return None
        out = f"article {m.group(1)}"
        if m.group(2):
            out += f", section {m.group(2)}"
        if m.group(3):
            out += f", clause {m.group(3)}"
        return out + (" of the Florida Constitution" if c["which"] == "Florida" else " of the United States Constitution")
    if k == "statute" and c["form"] in ("abbreviated", "hybrid"):
        m = re.match(r"(§§|§|[Ss]ections|[Ss]ection) ?(.+?),? (?:Fla\. Stats?\.?|Florida Statutes)(?: \((.+)\))?$", text, re.I)
        if not m:
            return None
        word = "sections" if m.group(1).lower() in ("§§", "sections") else "section"
        return f"{word} {m.group(2)}, Florida Statutes" + (f" ({m.group(3)})" if m.group(3) else "")
    if k == "rule" and c["form"] == "abbreviated":
        s = next(s for s in data["rule_sets"]["sets"] if s["n"] == c["set"])
        if c["set"] in (1, 3, 4, 6, 8, 9, 12) or s["name"].startswith("Florida Rules of"):
            return s["name"].replace("Rules", "Rule", 1) + " " + c["number"]
        return None
    if k == "admin_code" and c["form"] == "abbreviated":
        return f"Florida Administrative Code Rule {c['rule']}"
    if k == "session_law" and c["form"] == "abbreviated":
        m = re.match(r"[Cc]h(?:\.|apter) ([\d-]+)(?:, § ?(\d+))?", text)
        return f"chapter {m.group(1)}" + (f", section {m.group(2)}" if m.group(2) else "") + ", Laws of Florida"
    return None


def _mark_record(norm, c, prev, cites):
    """Mark an Id. that repeats a record cite (Indigo Book R26): one between it and the citation before
    it (or the document's start), or an Id. just before it that does. record_para: the record cite is
    to a paragraph ("Smith Aff. ¶ 78")."""
    gap = _gap(norm, prev["end"] if prev else 0, c["start"], cites)
    recs = [m.end() for rx in (RECORD_RX, TRANSCRIPT_RX) for m in rx.finditer(gap)]
    pin = ID_TRANSCRIPT_PIN.match(norm, c["start"])
    if pin and (norm[pin.end():pin.end() + 1] == ":" or (prev and prev["kind"] == "id" and not prev.get("record"))):
        pin = None                     # an audio timestamp ("Id. at 6:07:13", then "Id. at 43:45"), not a
        #                                transcript's page and line
    if recs or pin:
        last = max(recs) if recs else None
        c["record"] = True
        c["record_para"] = bool(last is not None and re.match(r"[\s,]*¶", gap[last:last + 6]))
    elif prev and prev["kind"] == "id" and prev.get("record") and not (" v. " in gap or UNSEEN_CITE.search(gap)):
        c["record"], c["record_para"] = True, prev.get("record_para")


# A pinpoint to several paragraphs with one paragraph sign: "Smith Aff. ¶ 8, 12, 13", "¶ 48-50".
PARA_SEVERAL = re.compile(r"(?<![¶\w])¶ ?\d+[a-z]?(?:(?:, ?(?:and )?| ?[-–] ?)\d+[a-z]?)+(?![\d\w])")


def _quoted(doc, a):
    return any(x <= a < y for x, y in doc.block_quotes) or any(x < a < y for x, y in doc.quotes)


def lc_record_cite_form(ctx, rec):
    """Record and paragraph pinpoints, reported once per document: several paragraphs under one ¶, an
    Id. that repeats a record cite, and such an Id. with "at" before a paragraph number."""
    doc = ctx["doc"]
    norm = doc.norm
    paras = [(m.start(), m.end()) for m in PARA_SEVERAL.finditer(norm) if not _quoted(doc, m.start())]
    ids = [c for c in ctx["cites"] if c["kind"] == "id" and c.get("record") and not c["in_quote"]]
    at_para = [c for c in ids if c.get("record_para") and re.match(r"[Ii]d\.?,? at \d", norm[c["start"]:c["end"]])]
    if not paras and not ids:
        return
    spans = sorted(paras + [(c["start"], c["end"]) for c in ids])
    parts = []
    if paras:
        parts.append(f"{len(paras)} pinpoint{'s' if len(paras) != 1 else ''} to several paragraphs under one ¶ "
                     "(¶ 8, 12 should be ¶¶ 8, 12)")
    if ids:
        parts.append(f"{len(ids)} Id. citation{'s' if len(ids) != 1 else ''} repeating a record cite")
    if at_para:
        parts.append(f"{len(at_para)} of {'them' if ids else 'these'} with \"at\" before a paragraph number "
                     "(Id. ¶ 79, not Id. at 79)")
    yield {"start": spans[0][0], "end": spans[0][1], "count": len(spans), "occurrences": spans,
           "detail": "Found: " + "; ".join(parts) + "."}


# An ellipsis that isn't three spaced periods: "...", "....", "…". In a filer's own quotation the
# ellipsis is the filer's alteration, so it's checked inside quotation marks (Indigo Book R8.3.1).
ELLIPSIS_BAD = re.compile(r"…\.?|(?<!\.)\.{3,4}(?!\.)")


def lc_ellipsis_form(ctx, rec):
    """Unspaced ellipses inside the document's own inline quotations (not block quotations, which may
    carry the quoted court's own)."""
    doc = ctx["doc"]
    norm = doc.norm
    for a, b in doc.quotes:
        for m in ELLIPSIS_BAD.finditer(norm, a + 1, b):
            dots = m.group(0).strip().replace("…", "...").count(".")
            lead = "" if m.start() == a + 1 or norm[m.start() - 1] in " [(" else " "
            trail = " " if m.end() < b and (norm[m.end()].isalnum() or norm[m.end()] == "[") else ""
            yield {"start": m.start(), "end": m.end(), "fix": lead + ". . ." + (" ." if dots >= 4 else "") + trail}


# A signal after a semicolon: "...(Fla. 2010); See also ...". Only a signal that begins a citation
# sentence is capitalized (Indigo Book R4.5).
SIGNAL_AFTER_SEMICOLON = re.compile(r"; (?P<sig>See(?: also| generally)?|Cf\.|Compare|Accord|Contra|But see|But cf\.|E\.g\.)"
                                    r"(?=[ ,])")
SIGNAL_GAP = 20                  # characters between a citation's end and the semicolon (", (g)", " (emphasis added)")


def lc_signal_capital(ctx, rec):
    """A capitalized signal after a semicolon inside a citation sentence: a citation ends just before
    the semicolon, with no sentence end between."""
    doc = ctx["doc"]
    norm = doc.norm
    ends = sorted(c["end"] for c in ctx["cites"] if not c["in_quote"])
    for m in SIGNAL_AFTER_SEMICOLON.finditer(norm):
        semi = m.start()
        k = bisect.bisect_right(ends, semi) - 1
        if k < 0 or semi - ends[k] > SIGNAL_GAP or re.search(r"[.?!]\s", norm[ends[k]:semi]):
            continue
        a, b = m.start("sig"), m.end("sig")
        if any(x <= a < y for x, y in doc.block_quotes) or any(x < a < y for x, y in doc.quotes):
            continue
        yield {"start": a, "end": b, "fix": norm[a].lower() + norm[a + 1:b]}


def lc_in_sentence(ctx, rec):
    """Abbreviated forms used as an integral part of a sentence: a governing word before the
    citation ("under", "of", "pursuant to") and the sentence going on after it (", the court ...")."""
    norm = ctx["doc"].norm
    for c in ctx["cites"]:
        if c["in_quote"] or c["kind"] not in ("constitution", "statute", "rule", "admin_code", "session_law") \
                or c.get("form") not in ("abbreviated", "hybrid"):
            continue
        before = norm[max(0, c["start"] - 40):c["start"]]
        m = re.search(r"(?:^|[\s(])([A-Za-z][a-z]+)\s$", before)
        if not m or m.group(1).lower() in GOVERNING_STOP or re.search(r",\s?with\s$", before):
            continue                       # a signal ("see", "compare ..., with"), not a governing word
        if not re.match(r", (?!see\b|e\.g\.|aff'd|rev'd|cert\.|review|and\b|or\b)[a-z]", norm[c["end"]:c["end"] + 12]):
            continue
        text = norm[c["start"]:c["end"]]
        fix = spelled_out(c, text, ctx["engine"].data)
        yield {"start": c["start"], "end": c["end"], "citation": c, "fix": fix}


def lc_case_name_typeface(ctx, rec):
    """Case names not italicized or underlined (9.800(q)). Only formats that keep typeface (.docx, .md)."""
    emph = ctx["source"].emphasis
    if emph is None:
        return
    emph = sorted(emph)
    starts = [a for a, _ in emph]
    doc = ctx["doc"]

    def styled(norm_i):
        r = doc.raw_pos(norm_i)
        k = bisect.bisect_right(starts, r) - 1
        return k >= 0 and emph[k][0] <= r < emph[k][1]

    for c in ctx["cites"]:
        if c["kind"] != "case" or c["in_quote"] or not c.get("case_name") or " v. " not in c["case_name"]:
            continue
        ns = c["name_start"]
        v = ns + c["case_name"].index(" v. ") + 1
        if not (styled(ns) or styled(v)):
            yield {"start": ns, "end": ns + len(c["case_name"]), "citation": c}


# ---------------------------------------------------------------- short forms across the document
# Rule 9.800 has no short forms, so 9.800(p) sends them to the Bluebook system, checked here through
# the Indigo Book: R6.2 (short citations, id., supra), R11.7 (pincites), R15 (short forms for cases).
# Precision first: when the script can't tell what an Id. refers to, it says nothing about it.

SEPARATE_OPINION = re.compile(r"\b[A-Z][A-Za-z'\-]+, (?:C\. )?J\., (?:dissenting|concurring|specially concurring)")


PAREN_SENTENCE_END = re.compile(r"(?:\)|\b[a-z]{3,})[.!?] (?=[A-Z][a-z])")


def _depth(text):
    """Parentheses left open at the end of text. A sentence ending outside quotation marks closes any
    left open, since a court's missing ')' would otherwise swallow the rest of the page."""
    ends = {m.end() for m in PAREN_SENTENCE_END.finditer(text)}
    d, quoted = 0, False
    for i, ch in enumerate(text):
        if ch == '"':
            quoted = not quoted
        elif ch == "(":
            d += 1
        elif ch == ")" and d:
            d -= 1
        if d and not quoted and i + 1 in ends:
            d = 0
    return d


def _strip_parens(text):
    prev = None
    while prev != text:
        prev, text = text, re.sub(r"\([^()]*\)", "", text)
    return text


def _case_keys(c):
    """What identifies the case a full or short citation cites: a reporter volume and series, a Fla. L.
    Weekly volume and edition, a Westlaw or LEXIS number. Pages aren't part of it, since a short form
    gives only a pinpoint."""
    keys = [("rep", r["volume"], r["canonical"]) for r in c["reporters"] if r["volume"][0].isdigit()]
    if c["flw"]:
        keys.append(("flw", str(c["flw"]["volume"]), c["flw"]["edition"]))
    if c["online"] and c["online"].get("number"):
        keys.append(("online", c["online"]["service"], str(c["online"]["year"]), c["online"]["number"]))
    return keys


def _full_key(c):
    """One key for a full citation, first page included, to spot the same citation given in full twice."""
    for r in c["reporters"]:
        if r["volume"][0].isdigit() and r["page"] and r["page"][0].isdigit():
            return ("rep", r["volume"], r["canonical"], r["page"])
    if c["flw"]:
        return ("flw", c["flw"]["volume"], c["flw"]["edition"], c["flw"]["page"])
    if c["online"] and c["online"].get("number"):
        return ("online", c["online"]["service"], c["online"]["year"], c["online"]["number"])
    return None


def _parties(case_name):
    if not case_name:
        return []
    return [p.strip(" ,") for p in re.split(r" (?:v|vs)\. ", case_name) if p.strip(" ,")]


def _name_matches(short, case_name):
    """Does a short-form name ('Fenelon', 'Gulf Oil') name a party in this full case name?"""
    if not short or not case_name:
        return False
    s = " " + short.lower().rstrip(".,") + " "
    return any(s in " " + re.sub(r"[,]", "", p.lower()) + " " for p in _parties(case_name))


def short_party(case_name):
    """The party name for a case's short form (Indigo Book R15.2.2-.4): the first party, or the second
    when the first is a government or 'State'; corporate endings and anything after a comma dropped."""
    ps = _parties(case_name)
    if not ps:
        return None
    pick = ps[1] if len(ps) > 1 and GOVERNMENT_PARTY.match(ps[0]) else ps[0]
    pick = re.split(r",? (?:Inc|Corp|Co|LLC|L\.L\.C|Ltd|P\.A|N\.A|L\.P|LLP|P\.L\.L\.C)\.?(?=,|$)", pick)[0]
    return pick.split(", ")[0].strip() or None


def _number(pin):
    """The first page of a pinpoint ('293', '946-47', '52 n.6'), or None for star pages, page letters, and the like."""
    m = re.match(r"(\d+)(?![\d*])", pin or "")
    return int(m.group(1)) if m and not re.match(r"\d+[A-Za-z]", pin) else None


def _first_page(full, canonical=None):
    """First page of a full citation in the given series (or its only series)."""
    reps = [r for r in full["reporters"] if r["volume"][0].isdigit() and (canonical is None or r["canonical"] == canonical)]
    if len(reps) != 1 or not reps[0]["page"] or not reps[0]["page"].isdigit():
        return None
    return int(reps[0]["page"])


def _toa_entry(doc, c):
    """A table-of-authorities line: the citation, then leader dots or tabs and page numbers."""
    r = doc.raw_pos(c["end"] - 1) + 1
    nl = doc.raw.find("\n", r)
    rest = doc.raw[r:nl if nl != -1 else len(doc.raw)]
    return bool(re.fullmatch(r"[\s.…·_]*(?:\d+(?:\s*[,&\-–]\s*\d+)*|passim)\s*", rest) and re.search(r"\.{3}|…|\t|passim|\d", rest))


def _gap(norm, a, b, cites):
    """Text between two citations, with citations nested in the first one's parentheticals blanked."""
    g = list(norm[a:b])
    for x in cites:
        if x.get("nested_in") is not None and a <= x["start"] and x["end"] <= b:
            for i in range(x["start"] - a, x["end"] - a):
                g[i] = " "
    return "".join(g)


def _page(c):
    return c["location"].get("page")


def link_short_forms(doc, cites):
    """Tie each short form to the full citation it stands for, and each Id. to what it refers to.

    Sets on each citation: nested_in (the citation whose parenthetical or subsequent history holds it),
    group (citations joined by semicolons into one string), refers_to (a short form's or Id.'s full
    citation), and on an Id. antecedent: a citation index, 'string', or 'unclear'. Returns the links
    the logic checks report from."""
    norm = doc.norm
    links = {"ids": [], "shorts": [], "supras": [], "repeats": []}
    fulls = [c for c in cites if c["kind"] == "case" and not c.get("placeholder")]
    by_key = {}
    for c in fulls:
        for k in _case_keys(c):
            by_key.setdefault(k, []).append(c)

    # A citation in another's parenthetical ("(quoting ...)") or subsequent history is part of it
    # (Indigo Book R15.3.3's note: it doesn't become the preceding citation for Id.).
    top, last = [], None
    for c in cites:
        c["nested_in"] = None
        if c.get("history_of") is not None:
            c["nested_in"] = c["history_of"]
            continue
        if last is not None:
            gap = norm[last["end"]:c["start"]]
            if len(gap) <= 600 and _depth(gap) > 0:
                c["nested_in"] = last["index"]
                continue
        top.append(c)
        last = c
    group, prev = 0, None
    for c in top:
        if (prev is not None and "id" not in (c["kind"], prev["kind"])
                and STRING_GAP.fullmatch(_strip_parens(norm[prev["end"]:c["start"]]))):
            c["group"] = prev["group"]
        else:
            group += 1
            c["group"] = group
        prev = c
    size = {}
    for c in top:
        size[c["group"]] = size.get(c["group"], 0) + 1

    # Short case citations: "Fenelon, 594 So. 2d at 293".
    for c in cites:
        if c["kind"] != "case_short" or c["in_quote"]:
            continue
        c["refers_to"] = None
        if c["docket"] or c.get("case_name") or _toa_entry(doc, c):
            continue                       # a full citation missing its parenthetical, or a table-of-authorities line
        cands = [f for k in _case_keys(c) for f in by_key.get(k, [])]
        named = []
        if c.get("short_name"):
            named = [f for f in cands if _name_matches(c["short_name"], f.get("case_name"))]
            cands = named or cands
        earlier = [f for f in cands if f["start"] < c["start"]]
        # A later "full" citation must be one: "Patios West, 388 So. 3d 898-99" is a short form missing "at".
        later = [f for f in cands if f["start"] > c["start"] and not f["in_quote"] and f["paren"]]
        entry = {"cite": c, "earlier": earlier, "later": later, "mismatch": None, "named": bool(named),
                 "any": bool(cands)}
        if earlier:
            # Two cases can share a volume ("Pratt, 161 So. 3d at 1272" and "Audiffred, 161 So. 3d
            # 1274"): take the one whose first page the pinpoint can follow.
            n = _number(c["pin"])
            canonical = c["reporters"][0]["canonical"] if c["reporters"] else None
            fit = [f for f in earlier if n is not None and (_first_page(f, canonical) or 0) <= n]
            if fit:
                c["refers_to"] = max(fit, key=lambda f: (_first_page(f, canonical) or 0, f["start"]))["index"]
            elif named or n is None:
                c["refers_to"] = earlier[-1]["index"]
        elif later and doc.ff and any(_page(f) == _page(c) for f in later):
            c["refers_to"] = later[0]["index"]      # same page: a footnote printed below the text
            entry["later"] = []
        elif not cands and c.get("short_name") and c["reporters"] and not GOVERNMENT_PARTY.match(c["short_name"]):
            rep = c["reporters"][0]["canonical"]
            other = {}
            for f in fulls:
                if _name_matches(c["short_name"], f.get("case_name")):
                    for r in f["reporters"]:
                        if r["canonical"] == rep and r["volume"][0].isdigit():
                            other[r["volume"]] = (f, r)
            if len(other) == 1:
                entry["mismatch"] = next(iter(other.values()))
        links["shorts"].append(entry)

    # supra with a case: "Fenelon, supra, at 293" (Indigo Book R6.2.3). Names of books and articles
    # ("Scalia & Garner, supra") match no case cited in full and have no "v.", so they're left alone.
    for c in cites:
        if c["kind"] != "supra" or c["in_quote"]:
            continue
        name = c["name"]
        first = _parties(name)[0] if " v. " in name else name
        matches = [f for f in fulls if _name_matches(first, f.get("case_name"))]
        keys = {_full_key(f) for f in matches}
        c["is_case"] = " v. " in name or bool(matches)
        c["refers_to"] = matches[0]["index"] if len(keys) == 1 else None
        if c["is_case"]:
            links["supras"].append({"cite": c, "full": matches[0] if len(keys) == 1 else None})

    # Id.: what it refers to is the preceding citation, if nothing the script can't see comes between.
    prev = earlier = None
    for c in top:
        if c["kind"] == "id" and not c["in_quote"]:
            info = {"cite": c, "prev": prev, "antecedent": None, "string": None}
            c["antecedent"] = "unclear"
            _mark_record(norm, c, prev, cites)
            if prev is not None:
                gap = _gap(norm, prev["end"], c["start"], cites)
                bare = _strip_parens(gap)
                broken = prev["kind"] == "case" and prev["paren"] is None    # cut off, as by a page break
                transcript = TRANSCRIPT_RX.search(gap) or ID_TRANSCRIPT_PIN.match(norm, c["start"])
                if not (prev["in_quote"] or broken or RECORD_RX.search(gap) or UNSEEN_CITE.search(gap) or transcript
                        or " v. " in bare or "supra" in bare or doc.stream(prev["start"]) != doc.stream(c["start"])):
                    if size[prev["group"]] > 1:
                        info["string"] = size[prev["group"]]
                        c["antecedent"] = "string"
                    else:
                        ant = _antecedent(prev, cites)
                        if ant is not None and not _unseen_footnote(doc, earlier, prev, c, cites):
                            info["antecedent"] = ant
                            c["antecedent"] = ant["index"]
                            c["repeats"] = prev["index"]    # the citation it repeats, pinpoint and all
                            full = cites[ant["refers_to"]] if ant["kind"] == "case_short" and ant.get("refers_to") is not None else ant
                            c["refers_to"] = full["index"]
            links["ids"].append(info)
        prev, earlier = c, prev

    # The same full citation twice, close together (Indigo Book R15.2.1 allows repeating it after a
    # new heading or page break, so only repeats on the same page count; separate opinions restart).
    seen = {}
    breaks = [m.start() for m in SEPARATE_OPINION.finditer(norm)]
    for c in fulls:
        if c["in_quote"] or not c["paren"] or _toa_entry(doc, c):
            continue                       # "Casadesus, 160 So. 3d 436" is a malformed short form, not a full one
        k = _full_key(c)
        if k is None:
            continue
        e = seen.get(k)
        if e is not None and c["nested_in"] is None:
            between = sum(1 for t in top if e["start"] < t["start"] < c["start"] and t["kind"] not in SHORT_KINDS)
            if ((not doc.ff or _page(e) == _page(c)) and between <= REPEAT_WINDOW
                    and doc.stream(e["start"]) == doc.stream(c["start"])        # text and a footnote are apart
                    and not any(e["start"] < b < c["start"] for b in breaks)):
                links["repeats"].append({"cite": c, "earlier": e, "between": between})
        if c["nested_in"] is None:         # one cited inside another's parenthetical may be given in full later
            seen[k] = c
    return links


def _id_case_first(x, cites):
    """The first page of the case a citation stands for (a full or short case, or an Id. of one), or None."""
    a = _antecedent(x, cites)
    if a is None:
        return None
    canonical = None
    if a["kind"] == "case_short":
        if a.get("refers_to") is None or not a["reporters"]:
            return None
        canonical = a["reporters"][0]["canonical"]
        a = cites[a["refers_to"]]
    if a["kind"] != "case" or a["flw"] or a["online"]:
        return None
    return _first_page(a, canonical)


def _unseen_footnote(doc, earlier, prev, c, cites):
    """Is prev probably a footnote the layout didn't show? Footnotes print at the foot of a page, between its
    body text and the next page's, and an OCR'd footnote number (5 read as >) hides one from layout_footnotes.
    Then an Id. on the next page whose page fits the citation before prev, but comes before prev's first page,
    belongs to that earlier citation, and what it refers to isn't clear enough to check."""
    if earlier is None or not doc.ff or _page(prev) == _page(c) or c.get("pin_kind") != "page":
        return False
    n = _number(c["pin"][3:])
    p, e = _id_case_first(prev, cites), _id_case_first(earlier, cites)
    return n is not None and p is not None and e is not None and e <= n < p


def _antecedent(prev, cites):
    k = prev["kind"]
    if k == "id":
        a = prev.get("antecedent")
        return cites[a] if isinstance(a, int) else None
    if k == "case":
        return prev
    if k == "case_short":
        return cites[prev["refers_to"]] if prev.get("refers_to") is not None else prev
    if k == "supra":
        return cites[prev["refers_to"]] if prev.get("refers_to") is not None else None
    if k in SECTION_KINDS:
        return None if prev.get("form") == "sentence" else prev
    if k == "ag_opinion":
        return prev
    return None                                # unrecognized: what it cites is unknown


# ---------------------------------------------------------------- quotations tied to citations
# The script never judges a quotation. It ties each one to the citation that gives its source, so an
# agent can check the words with a quote-verification tool. A wrong tie would send that check to the
# wrong case, so when the tie isn't clear the quotation is listed as unattributed instead.

MIN_QUOTE_WORDS = 4               # shorter quotations are terms and scare quotes, not passages to verify
QUOTE_SHOWN = 300
SIGNAL = r"(?:(?:see|see also|accord|cf\.|but see|see generally)(?:,? e\.g\.,)?|e\.g\.,)\s+"
QUOTE_THEN_CITE = re.compile(r"[\s.,;:!?\]\"']*(?:" + SIGNAL + r")?", re.I)
# The rest of the quotation's sentence, then the citation sentence: '"..." and reversed. Smith, ...'
SENTENCE_THEN_CITE = re.compile(r"[^.!?\"()]{0,250}[.!?][\"'\]]*\s+(?:" + SIGNAL + r")?", re.I)
# Between a citation and the parenthetical holding a quotation, only other parentheticals:
# '(Fla. 2015) (citation omitted) ("...")'
PARENS_BETWEEN = re.compile(r"(?:\s*\((?:[^()]|\([^()]*\))*\))*\s*")
# A record or briefing cite right after a quotation: "[R. 79]", "R-320:10-11", "(S.R. 251)", "Petition at 15".
RECORD_AFTER = re.compile(r"[\s.,;:\"']*[(\[]?\s*(?:[Ss]ee |[Cc]f\. )?(?:" + RECORD_RX.pattern
                          + r"|(?:[A-Z][\w'.]*\.? ){0,2}(?:Dep(?:o)?\.|Tr\.|Aff\.|Decl\.)|(?:Exhibit|Ex\.) [\"“]?[A-Z0-9]{1,3}\b"
                          + r"|(?:[A-Z]{1,4}\.? ?)?R ?-\d+|S\.R\. ?\d+|(?:(?:Initial|Answer|Reply|Amended) )?"
                          r"(?:Pet(?:ition)?|Br(?:ief)?|Resp(?:onse)?|Mot(?:ion)?|IB|AB|RB)\.? at \d+)")
END_MATTER = re.compile(r"\bCERTIFICATE OF (?:SERVICE|COMPLIANCE)\b")
SENTENCE_BREAK = re.compile(r"[.!?][\"')\]]*\s+[A-Z]")


def quotation_pin(c, cites, depth=0):
    """The pinpoint a quotation's citation gives: the first reporter's own pinpoint, a short form's or
    Id.'s pinpoint, or for an Id. with none, the pinpoint of the citation it repeats ('Smith, 594 So. 2d
    at 293. "..." Id.' is at 293)."""
    k = c["kind"]
    if k == "case":
        own = c["reporters"][0]["pins"] if c["reporters"] else (c["flw"] or c["online"] or {}).get("pins", [])
        return (own or c["pins"] or [None])[0]
    if k in ("case_short", "supra"):
        return c.get("pin")
    if k == "id":
        if c.get("pin"):
            return re.sub(r"^at ", "", c["pin"])
        a = c.get("repeats", c.get("antecedent"))
        return quotation_pin(cites[a], cites, depth + 1) if isinstance(a, int) and depth < 20 else None
    if k in SECTION_KINDS:
        return c.get("section") or c.get("number") or c.get("rule")
    return None


# A defined term: a short phrase in quotation marks that is all of a parenthetical introducing it,
# '(the "Agreement")', '(together, the "federal standard")', '(hereinafter "Act")'. It's the
# writer's own label, not a quotation. A parenthetical that is only a quotation ('("The rule is ...")')
# has no article or cue word before the mark, and stays a quotation.
DEFINED_TERM_BEFORE = re.compile(r"\((?:(?:together|collectively|jointly|hereinafter(?: referred to as| called)?),? )?"
                                 r"(?:(?:the|a|an) )?$", re.I)
DEFINED_TERM_CUE = re.compile(r"\((?:together|collectively|jointly|hereinafter|the |a |an )", re.I)
DEFINED_TERM_MAX = 60            # characters in the term


def defined_term(norm, a, b):
    """Is the quotation pair (a, b) a defined term (DEFINED_TERM_BEFORE)?"""
    before = norm[max(0, a - 40):a]
    m = DEFINED_TERM_BEFORE.search(before)
    return bool(m and DEFINED_TERM_CUE.match(m.group(0)) and b - a - 1 <= DEFINED_TERM_MAX
                and norm[b + 1:b + 2] == ")" and not re.search(r"[.?!] [A-Z]", norm[a + 1:b]))


def paired_quotes(doc):
    """(open, close) offsets of double quotation marks, paired by direction: curly marks say which way
    they face, and a straight one is read from its neighbors. An open mark never closed is dropped,
    so one stray mark doesn't throw off every pair after it. Returns the pairs, and the open marks that
    never close even when quotations nested in double marks ("... "inner" ...") are allowed."""
    norm, out, open_at, marks = doc.norm, [], None, []
    for m in re.finditer('"', norm):
        i = m.start()
        ch = doc.raw[doc.raw_pos(i)]
        prev = norm[i - 1] if i else " "
        nxt = norm[i + 1] if i + 1 < len(norm) else " "
        if ch == "“":
            kind = "open"
        elif ch == "”":
            kind = "close"
        elif prev.isspace() and norm[i - 2:i - 1] == "'" and (nxt.isspace() or nxt in ".,;:!?)]}—–"):
            kind = "close"                   # nested quotations set off with a space: '... evidence.' " Sec.'
        elif (prev.isspace() or prev in "([{—–/") and not nxt.isspace():
            kind = "open"
        elif not prev.isspace() and (nxt.isspace() or nxt in ".,;:!?)]}—–'§¶" or re.match(r"\d{1,3}(?:\s|$)", norm[i + 1:i + 5])):
            kind = "close"                   # a footnote marker or a section sign may follow:
            #                                  '"judiciary"6 serving', '"long enough."§ 48.031'
        else:
            kind = None
        if kind:
            marks.append((i, kind))
        if kind == "open":
            open_at = i
        elif kind == "close":
            if open_at is not None and i - open_at <= fc.MAX_QUOTE:
                out.append((open_at, i))
            open_at = None
    return out, _unclosed_quotes(norm, marks)


# Single quotation marks; and a closing double mark OCR misread as '' or ' ("to negate'')", "plaintiff' would").
SINGLE_OPEN = re.compile(r"(?<=[\s(\[—–\"])'(?=\w)")
SINGLE_CLOSE = re.compile(r"(?<=[\w.,!?\]])('{1,2})(?=[\s.,;:!?)\]]|$)")


def _unclosed_quotes(norm, marks):
    """Open double marks that never close, allowing quotations nested in double marks ('"... "inner" ..."').
    A single mark closes an open single quotation first; otherwise it, or two of them, stands in for a
    closing double mark that OCR misread. Those stand-ins can only hide a finding, never add one."""
    events = list(marks) + [(m.start(), "single open") for m in SINGLE_OPEN.finditer(norm)]
    events += [(m.start(), "close" if len(m.group(1)) == 2 else "single close") for m in SINGLE_CLOSE.finditer(norm)]
    stack, unclosed = [], []
    for i, kind in sorted(events):
        if kind in ("open", "single open"):
            stack.append((i, kind))
            continue
        while stack:                       # a double close ends the innermost double quotation
            a, k = stack.pop()
            if k == "open" and i - a > fc.MAX_QUOTE:
                unclosed.append(a)
            if k == "open" or kind == "single close":
                break
    return sorted(unclosed + [a for a, k in stack if k == "open"])


def _open_paren(norm, i, reach=600):
    """Offset of the parenthesis left open at norm[i], within reach, or None. A sentence end outside
    any parenthesis stops the search."""
    depth = 0
    for j in range(i - 1, max(-1, i - reach), -1):
        ch = norm[j]
        if ch == ")":
            depth += 1
        elif ch == "(":
            if depth == 0:
                return j
            depth -= 1
        elif depth == 0 and ch in ".!?" and re.match(r" [A-Z\"“§]", norm[j + 1:j + 3]) \
                and not re.search(r"(?:\b[A-Z][a-z]{0,3}|\bv|\bal|\bId|\bco|\bInc|\bU\.S)$", norm[max(0, j - 5):j]):
            return None
    return None


def tie_quotations(doc, cites):
    """Each quotation of MIN_QUOTE_WORDS or more, with the citation it's tied to (or none)."""
    norm = doc.norm
    blocks = list(doc.block_quotes)
    spans = [(a, e, True) for a, e in blocks]
    for a, b in doc.quotes:
        if not any(s <= a < e for s, e in blocks):
            spans.append((a + 1, b, False))      # the text inside the marks
    spans.sort()
    usable = [c for c in cites if not c["in_quote"]]
    starts = [c["start"] for c in usable]
    # The certificates at the end (addresses, signatures) aren't quotations; the last heading counts,
    # since the table of contents names them too.
    ends = [m.start() for m in END_MATTER.finditer(norm) if m.start() > len(norm) // 2]
    end_matter = ends[0] if ends else len(norm)
    out = []
    for a, e, block in spans:
        text = norm[a:e].strip()
        if len(text.split()) < MIN_QUOTE_WORDS or _containing(cites, a, e) is not None or a > end_matter:
            continue
        q = {"text": text if len(text) <= QUOTE_SHOWN else text[:QUOTE_SHOWN].rstrip() + "…", "length": len(text),
             "block": block, "location": doc.location(a, e), "citation": None, "attributed_by": None,
             "refers_to": None, "pin": None, "no_pin": False, "note": None, "_start": a, "_end": e}
        stream = doc.stream(a)
        # 1. A quotation inside a citation's explanatory parenthetical: '(Fla. 2015) (holding that "...")'.
        opened = None if block else _open_paren(norm, a - 1)
        if opened is not None:
            k = bisect.bisect_right(starts, opened) - 1
            while k >= 0 and usable[k]["end"] > opened:
                k -= 1                       # a citation inside the parenthetical, before the quotation
            if (k >= 0 and PARENS_BETWEEN.fullmatch(norm[usable[k]["end"]:opened])
                    and doc.stream(usable[k]["start"]) == stream):
                q["citation"], q["attributed_by"] = usable[k]["index"], "parenthetical"
        # 2. The quotation, then its citation. Not when the quotation sits in a parenthetical
        # that closes after it: '(rejecting it because "...")'; Chandler v. Crosby, ...' isn't Chandler's.
        elif q["citation"] is None:
            close = e + (0 if block else 1)
            k = bisect.bisect_left(starts, close)
            if k < len(usable) and doc.stream(usable[k]["start"]) == stream:
                c, gap = usable[k], norm[close:usable[k]["start"]]
                if QUOTE_THEN_CITE.fullmatch(gap):
                    q["citation"], q["attributed_by"] = c["index"], "follows"
                elif (not block and SENTENCE_THEN_CITE.fullmatch(gap) and not RECORD_RX.search(gap)
                      and re.match(r"[,;:]?\s+[a-z]", gap) and not re.search(r"[.!?]['’]?$", text)):
                    # the quotation's own sentence goes on, then ends with the citation sentence
                    q["citation"], q["attributed_by"] = c["index"], "end of sentence"
            if q["citation"] is None and RECORD_AFTER.match(norm, close):
                q["note"] = "followed by a record cite: the source is the record, not case law"
        out.append(q)
    # 3. Quotations in one sentence share its citation: '"The statute," the court said, "is clear." Smith, ...'
    # Not across a sentence end, whether inside the first quotation ('"... harmless." It held that "..."') or
    # right before the next one opens ('... in the motion. "[W]e ..."').
    for i in range(len(out) - 2, -1, -1):
        q, nxt = out[i], out[i + 1]
        if q["citation"] is None and not q["note"] and not q["block"] and not nxt["block"]:
            gap = norm[q["_end"] + 1:nxt["_start"] - 1]
            ended = re.search(r"[.!?]['\])]*$", norm[q["_start"]:q["_end"]]) or re.search(r"[.!?]['\")\]]*\s*$", gap)
            if (len(gap) <= 120 and not SENTENCE_BREAK.search(gap) and not ended and not re.search(r"[()]", gap)
                    and nxt["citation"] is not None):
                q["citation"], q["attributed_by"] = nxt["citation"], "same sentence"
    for q in out:
        q.pop("_start"), q.pop("_end")
        if q["citation"] is None:
            continue
        c = cites[q["citation"]]
        q["pin"] = quotation_pin(c, cites)
        if c["kind"] == "case":
            q["refers_to"] = c["index"]
        elif c.get("refers_to") is not None:
            q["refers_to"] = c["refers_to"]
        elif c["kind"] in ("id", "case_short", "supra"):
            q["note"] = (f"tied to {c['text']}, but what that refers to isn't clear to the script "
                         "(it may be the record); find the source by hand")
        # A quotation from a case needs the page it's on (Indigo Book R11.7): quote-no-pin. Not when it's tied
        # to subsequent history ("..., 41 (Fla. 5th DCA 1981), approved, 419 So. 2d 1041 (Fla. 1982) ("...")"),
        # where the page may be the main citation's.
        q["no_pin"] = q["refers_to"] is not None and not q["pin"] and c.get("history_of") is None
    return out


PAREN_KINDS = ("case", "statute", "constitution", "rule", "admin_code", "session_law", "ag_opinion")
PAREN_REACH = 1000


def _sentence_end(norm, j):
    """Does norm[j] end a citation sentence: a period after ')', a page number, or a lowercase word (not an
    abbreviation like 'Fla.' or 'v.'), then a new sentence, perhaps after a footnote marker ('relief).19 In')?"""
    m = re.search(r"(?:\)|\d|\b([a-z]{3,}))$", norm[max(0, j - 30):j])
    return (norm[j] in ".!?" and m is not None and m.group(1) not in LOWER_ABBREVIATIONS
            and re.match(r"\d{0,3}\s+[A-Z\d\"(§]|\s*$", norm[j + 1:j + 7]) is not None)


LOWER_ABBREVIATIONS = {"eff", "cert", "etc", "rev", "supp", "approx", "art", "ann", "app", "dist", "cir", "reh'g",
                       "amend", "repl", "corr", "dep't", "env't", "gov't", "nat'l", "int'l", "ass'n", "sess", "vol"}


def lc_paren_unbalanced(ctx, rec):
    """Parentheses that don't pair, counted from a citation's start through its parentheticals and history
    to the end of its citation sentence (a semicolon outside any parenthetical, or a sentence end outside
    quotation marks). A parenthetical opened before the citation ("(see ...)", "(citing ...)") may close in
    it. A statute or rule number that runs into a subsection the script can't read is reported too."""
    doc = ctx["doc"]
    norm, reported = doc.norm, set()
    for c in ctx["cites"]:
        if (c["kind"] not in PAREN_KINDS or c["in_quote"] or c.get("nested_in") is not None or c["tier"] != TIER_RULE
                or c.get("toa")):
            continue
        if c.get("unreadable"):
            yield {"start": c["start"], "end": c["end"], "citation": c, "authority": c["authority"],
                   "detail": f"The subsection after {c.get('section') or c.get('number')} can't be read, so no fix "
                             "touches it; fix it by hand."}
            continue
        outer = 1 if _open_paren(norm, c["start"]) is not None else 0
        stop = min(len(norm), c["start"] + PAREN_REACH)
        quoted = [(a, b) for a, b in doc.quotes if a < stop and b > c["start"]]
        opened, bad, j = [], None, c["start"]
        if re.match(r"\s+[A-Z]", norm[c["end"]:c["end"] + 2]) and norm[c["end"] - 1] == ".":
            stop = c["end"]                        # "..., Fla. Stat. At sentencing": the sentence ended
        while j < stop:
            ch = norm[j]
            if ch in "();." and any(a < j < b for a, b in quoted):
                pass                               # inside a quotation: the quoted writer's punctuation
            elif ch == "(":
                opened.append(j)
            elif ch == ")":
                if opened:
                    opened.pop()
                elif outer:
                    outer = 0                      # closes the parenthetical the citation sits in
                elif bad is None:
                    bad = ("extra", j)
            elif (ch == ";" and not opened) or (j >= c["end"] and _sentence_end(norm, j)):
                break
            j += 1
        if bad is None and opened and j < len(norm) and j < c["start"] + PAREN_REACH:
            bad = ("open", opened[-1])
        if bad is None or bad[1] in reported:
            continue
        region = norm[c["start"]:j]
        if (re.search(r"(?:\. ?){6,}|…{3,}|_{4,}|\)\.*\s*\d{1,3}(?:\s*,\s*\d{1,3}){2,}", region)   # a table of authorities
                or any(c["start"] <= u < j for u in doc.unclosed_quotes)      # quote-unclosed reports the cause
                or doc.location(c["start"], j).get("split_to_page")            # a page break or moved footnote
                or any(c["start"] < b and a < j for a, b in doc.footnotes)):  # can scramble the text
            continue
        reported.add(bad[1])
        what, k = bad
        detail = (f"A ')' closes nothing: …{norm[max(c['start'], k - 30):k + 1]}" if what == "extra"
                  else f"A '(' is never closed: {norm[k:k + 30]}…")
        yield {"start": c["start"], "end": max(c["end"], k + 1) if what == "extra" else j, "citation": c,
               "authority": c["authority"], "detail": detail}


def _in_citation_parenthetical(norm, i, cites):
    """Is offset i inside a parenthetical that follows a citation: '(Fla. 2015) (holding that "...'?"""
    p = _open_paren(norm, i)
    return p is not None and any(c["end"] <= p and not c["in_quote"] and PARENS_BETWEEN.fullmatch(norm[c["end"]:p])
                                 for c in cites)


def lc_quote_unclosed(ctx, rec):
    """An opening quotation mark that never closes, when a citation follows it before the next opening mark,
    or when it sits in a citation's parenthetical. Where the quotation ends, and so whether that citation
    is quoted or the writer's own, is unclear."""
    doc, cites = ctx["doc"], ctx["cites"]
    norm = doc.norm
    opens = sorted(set(doc.unclosed_quotes) | {a for a, _ in doc.quotes + doc.defined_terms})
    for i in doc.unclosed_quotes:
        if any(a <= i < b for a, b in doc.block_quotes):
            continue
        k = bisect.bisect_right(opens, i)
        limit = min(opens[k] if k < len(opens) else len(norm), i + fc.MAX_QUOTE)
        after = next((c for c in cites if i < c["start"] < limit and not c["in_quote"]), None)
        if after is None and not _in_citation_parenthetical(norm, i, cites):
            continue
        end = after["start"] if after else limit
        if doc.location(i, end).get("split_to_page") or any(i < b and a < end for a, b in doc.footnotes):
            continue                           # a page break or moved footnote can scramble the text between
        words = re.match(r'"\s*(?:\S+\s+){0,5}\S*', norm[i:i + 80])
        yield {"start": i, "end": i + len(words.group(0)),
               "detail": f"No closing mark before {norm[after['start']:after['end']]}." if after else
                         "It opens inside a citation's parenthetical, which ends without closing it."}


def lc_quote_no_pin(ctx, rec):
    """A citation given for a quotation from a case, with no page: no pinpoint of its own, through Id., or
    through a short form. Reported once per citation, naming the first quotation it's given for."""
    cites, seen = ctx["cites"], set()
    for q in ctx["quotations"]:
        if not q["no_pin"] or q["citation"] in seen:
            continue
        seen.add(q["citation"])
        c = cites[q["citation"]]
        words = " ".join(q["text"].split()[:6])
        yield {"start": c["start"], "end": c["end"], "citation": c,
               "detail": f"It's given for the quotation \"{words}…\" ({_where(q['location'])})."}


def lc_id_after_string(ctx, rec):
    for info in ctx["links"]["ids"]:
        if info["string"]:
            c = info["cite"]
            yield {"start": c["start"], "end": c["end"], "citation": c,
                   "detail": f"The citation before it is a string of {info['string']} authorities."}


def lc_id_antecedent(ctx, rec):
    for info in ctx["links"]["ids"]:
        c, ant = info["cite"], info["antecedent"]
        if ant is None or not c["pin"]:
            continue
        what = ctx["doc"].norm[ant["start"]:ant["end"]]
        if c["pin_kind"] == "page" and ant["kind"] in SECTION_KINDS:
            yield {"start": c["start"], "end": c["end"], "citation": c,
                   "detail": f"It refers to {what}, which is cited by section, but its pinpoint is a page; "
                             "if it means a case cited earlier, use that case's short form."}
        elif c["pin_kind"] == "section" and ant["kind"] in ("case", "case_short"):
            yield {"start": c["start"], "end": c["end"], "citation": c,
                   "detail": f"It refers to {what}, a case, but its pinpoint is a section."}


def lc_pin_before_first_page(ctx, rec):
    cites = ctx["cites"]
    for c in _full_cases(ctx):
        first = _first_page(c)
        if first is None or c["flw"] or c["online"] or len(c["reporters"]) != 1:
            continue
        for p in c["pins"]:
            n = _number(p)
            if n is not None and n < first:
                yield {"start": c["start"], "end": c["end"], "citation": c,
                       "detail": f"Pinpoint {p} comes before the case's first page, {first}."}
                break
    for e in ctx["links"]["shorts"]:
        c = e["cite"]
        if not e["earlier"] or not c["reporters"] or not e["named"]:
            continue                       # without a name, an early pinpoint may mean another case in the volume
        firsts = [_first_page(f, c["reporters"][0]["canonical"]) for f in e["earlier"]]
        n = _number(c["pin"])
        if n is not None and firsts and None not in firsts and n < min(firsts):
            yield {"start": c["start"], "end": c["end"], "citation": c,
                   "detail": f"Pinpoint {c['pin']} comes before the case's first page, {min(firsts)}."}
    for info in ctx["links"]["ids"]:
        c, ant = info["cite"], info["antecedent"]
        if ant is None or c["pin_kind"] != "page":
            continue
        canonical = None
        if ant["kind"] == "case_short":
            if ant.get("refers_to") is None or not ant["reporters"]:
                continue
            canonical = ant["reporters"][0]["canonical"]
            ant = cites[ant["refers_to"]]
        if ant["kind"] != "case" or ant["flw"] or ant["online"]:
            continue
        first = _first_page(ant, canonical)
        n = _number(c["pin"][3:])
        if first is not None and n is not None and n < first:
            yield {"start": c["start"], "end": c["end"], "citation": c, "severity": "check",
                   "detail": f"It seems to refer to {ctx['doc'].norm[ant['start']:ant['end']]}, which begins at "
                             f"page {first}; either the pinpoint or what Id. refers to is wrong."}


def lc_short_before_full(ctx, rec):
    for e in ctx["links"]["shorts"]:
        if not e["earlier"] and e["later"]:
            c, f = e["cite"], e["later"][0]
            yield {"start": c["start"], "end": c["end"], "citation": c,
                   "detail": f"The full citation comes later ({_where(f['location'])}): "
                             f"{ctx['doc'].norm[f['start']:f['end']]}."}


def lc_short_without_full(ctx, rec):
    norm = ctx["doc"].norm
    for e in ctx["links"]["shorts"]:
        c = e["cite"]
        if e["any"] or e["mismatch"] or c.get("refers_to") is not None:
            continue
        name = c.get("short_name")
        if name:
            n = re.escape(re.sub(r" (?:I|II|III|IV|V)$", "", name))
            if re.search(r"\b" + n + r",? v\. |\bv\. " + n + r"\b|\b" + n + r" \(", norm):
                continue                   # named in a caption the script couldn't read whole (split by a page)
        yield {"start": c["start"], "end": c["end"], "citation": c}


def lc_short_volume(ctx, rec):
    for e in ctx["links"]["shorts"]:
        if not e["mismatch"]:
            continue
        c = e["cite"]
        f, r = e["mismatch"]
        fix = f"{c['short_name']}, {r['volume']} {r['canonical']} at {c['pin']}"
        yield {"start": c["start"], "end": c["end"], "citation": c, "fix": fix,
               "detail": f"The full citation of {f['case_name']} gives volume {r['volume']}."}


def lc_supra_case(ctx, rec):
    for e in ctx["links"]["supras"]:
        c, f = e["cite"], e["full"]
        fix = None
        if f is not None and c["pin"] and f["reporters"] and len(f["reporters"]) == 1:
            r = f["reporters"][0]
            fix = f"{short_party(f['case_name'])}, {r['volume']} {r['canonical']} at {c['pin']}"
        yield {"start": c["start"], "end": c["end"], "citation": c, "fix": fix}


def lc_full_repeated(ctx, rec):
    for e in ctx["links"]["repeats"]:
        c = e["cite"]
        fix = None
        reps = [r for r in c["reporters"] if r["volume"][0].isdigit()]
        name = short_party(c.get("case_name"))
        if len(reps) == 1 and not c["flw"] and not c["online"] and c["pins"]:
            fix = f"{reps[0]['volume']} {reps[0]['canonical']} at {c['pins'][0]}"
            if name:
                fix = f"{name}, {fix}"     # without a name, the case is named in the sentence (Indigo Book R15.1)
        yield {"start": c["start"], "end": c["end"], "citation": c, "fix": fix,
               "detail": f"It was cited in full {_where(e['earlier']['location'])}, "
                         f"{e['between']} citation{'s' if e['between'] != 1 else ''} before."}


# ---------------------------------------------------------------- output

def check(source, date=None, infer=True, fallback_today=True, engine=None):
    """Check a Source. date: a datetime.date; if None, infer it from the text, then fall back to today."""
    how = "given" if date else None
    if date is None and infer:
        date, how = infer_date(source.text)
    if date is None and fallback_today:
        date, how = dt.date.today(), "today (no date found in the document; pass --date)"
    return (engine or Engine()).run(source, date, how)


def render_text(report, show_citations=False):
    out = []
    s = report["summary"]
    out.append(f"fl_cite check: {report['input']}  (Rule 9.800 as of {report['rule_as_of']})")
    bits = []
    if report["doc_date"]:
        bits.append(f"document date {report['doc_date']} ({report['doc_date_source']})")
    if report["pages"]:
        bits.append(f"{report['pages']} pages")
    tiers = ", ".join(f"{n} {t}" for t, n in sorted(s["by_tier"].items(), key=lambda x: -x[1]))
    bits.append(f"{s['citations']} citations" + (f" ({tiers})" if tiers else ""))
    out.append("; ".join(bits))
    n = s["findings"]
    out.append(f"{n['error']} error{'s' if n['error'] != 1 else ''}, {n['check']} to check, {n['unrecognized']} unrecognized")
    titles = {"error": "ERRORS (departs from Rule 9.800's form)", "check": "TO CHECK (probably wrong; your call)"}
    for sev in ("error", "check"):
        fs = [f for f in report["findings"] if f["severity"] == sev]
        if not fs:
            continue
        out.append("")
        out.append(titles[sev])
        for f in fs:
            where = _where(f["location"])
            count = f" (x{f['count']})" if f.get("count", 1) > 1 else ""
            out.append(f"  {where:<10} [{f['authority']}] {f['found']}{count}")
            out.append(f"  {'':<10} {f['message']}")
            if f["fix"]:
                out.append(f"  {'':<10} fix: {f['fix']}")
            if f.get("count", 1) > 1:
                more = ", ".join(_where(o) for o in f["occurrences"][1:12])
                extra = f" (+{f['count'] - 12} more)" if f["count"] > 12 else ""
                out.append(f"  {'':<10} also at: {more}{extra}")
    un = [f for f in report["findings"] if f["severity"] == "unrecognized"]
    if un:
        out.append("")
        out.append("UNRECOGNIZED (outside the script's forms; check by hand under the tier named)")
        for tier in (TIER_BLUEBOOK, TIER_FSM, TIER_RULE):
            fs = [f for f in un if f["tier"] == tier]
            if fs:
                out.append(f"  {tier}, 9.800(p):")
                for f in fs:
                    out.append(f"    {_where(f['location']):<10} {f['found']}")
    if show_citations:
        out.append("")
        out.append("CITATIONS")
        for c in report["citations"]:
            out.append(f"  {_where(c['location']):<10} {c['kind']:<13} {c['authority']:<12} {c['text']}")
    if report["notes"]:
        out.append("")
        for note in report["notes"]:
            out.append(f"Note: {note}")
    return "\n".join(out)


def _where(loc):
    if "label" in loc:
        return loc["label"]
    if "page" in loc:
        return f"PDF p. {loc['page']}"
    return loc.get("where") or f"line {loc['line']}"


def _page_list(pages, doc):
    names = [doc.page_name(p) for p in pages[:10]]
    more = f" and {len(pages) - 10} more" if len(pages) > 10 else ""
    return ", ".join(names) + more
