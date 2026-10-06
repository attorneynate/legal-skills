"""Where sentences, clauses, and parentheticals end: one reader every check asks.

Legal text is hard on sentence splitting: most periods belong to abbreviations (Fla., So. 3d, Inc., v.,
Id.), not sentence ends. Before this module, fl_check.py decided that in six places, each its own way.
Here it's decided once, in layers built once per document:

1. Periods (Periods): every '.', '?', and '!' gets a reading: an abbreviation, a sentence end, or both
   (an abbreviation that ends the sentence: "... Fla. Stat. At sentencing"). The abbreviations come
   from the data tables (Abbreviations), plus a short general list here.
2. Brackets (Brackets): parentheses paired once, with quotations as opaque spans, and one recovery
   rule: a sentence end outside quotations closes any parenthesis the next sentence doesn't close either,
   so one missing ')' doesn't swallow the page.

Works on any text: the normalized document or a page's raw lines. Standard library only.
"""

import bisect
import re

ABBREVIATION, END, BOTH = "abbreviation", "end", "both"

# Abbreviations no table holds: signals and citation words, statute and code names, common legal
# shorthand, honorifics, and business forms. Written without the final period; matched case-sensitively,
# so "No." (number) is here and "no." is too.
GENERAL = {
    "v", "vs", "cf", "Cf", "e.g", "E.g", "i.e", "etc", "et", "al", "Id", "id", "Ibid", "ibid", "supra", "infra",
    "cert", "eff", "rev", "supp", "Supp", "approx", "art", "arts", "Art", "ann", "Ann", "app", "App", "dist",
    "Dist", "cir", "Cir", "reh'g", "amend", "Amend", "repl", "corr", "dep't", "env't", "gov't", "nat'l",
    "int'l", "ass'n", "sess", "Sess", "vol", "Vol", "ch", "chs", "Ch", "pt", "pts", "Pt", "p", "pp", "n", "nn",
    "no", "No", "nos", "Nos", "para", "paras", "sec", "secs", "Sec", "cl", "subd", "subsec", "ex", "Ex", "rel",
    "seq", "op", "Op", "ops", "Ops", "ed", "eds", "Ed", "mem", "cur", "aff'd", "rev'd", "fn", "ref",
    "Inc", "Co", "Corp", "Ltd", "Bros", "Mfg", "Ass'n", "Mr", "Mrs", "Ms", "Dr", "Jr", "Sr", "St", "Mt", "Ft",
    "Ave", "Blvd", "Rd", "Prop", "Stat", "Stats", "Const", "Admin", "Reg", "Gen", "Att'y", "Ct", "Cty",
    "Cnty", "Fed", "Cong", "Rec", "Tr", "Dep", "Aff", "Decl", "Exh", "Pet", "Resp", "Br", "Mot", "Compl", "Pl",
    "Pls", "Def", "Defs", "Doc", "Dkt", "Jud", "Prac", "Civ", "Crim", "Proc", "Pro", "Evid", "Fam", "Esq", "Rev",
    "Init", "Att",
}
# Multi-word forms no table holds, read as one abbreviation: "Fla. Stat." doesn't end at "Fla.".
GENERAL_PHRASES = [
    "Fla. Stat.", "Fla. Stat. Ann.", "Fla. Const.", "U.S. Const.", "Fla. Admin. Code", "Fla. Admin. Code Ann.",
    "Laws of Fla.", "Op. Att'y Gen.", "Ops. Att'y Gen.", "Fed. Reg.", "Cong. Rec.", "Fed. R. Civ. P.",
    "Fed. R. Crim. P.", "Fed. R. App. P.", "Fed. R. Evid.", "S. Ct.", "L. Ed.", "Cty. Ct.", "Cir. Ct.",
]
# Capitalized words that start a sentence and never continue an abbreviation's citation or name:
# after "Fla. Stat." or "Inc.", one of these means the period ended the sentence too.
OPENERS = {
    "The", "This", "That", "These", "Those", "It", "Its", "We", "Our", "He", "She", "His", "Her", "They",
    "Their", "There", "Here", "In", "At", "On", "As", "If", "When", "Where", "While", "Because", "Although",
    "Though", "Since", "After", "Before", "Under", "Accordingly", "Moreover", "However", "Thus", "Therefore",
    "Further", "Furthermore", "Finally", "Similarly", "Additionally", "Nonetheless", "Nevertheless", "Indeed",
    "Even", "Also", "But", "And", "Or", "Yet", "Not", "A", "An", "To", "Id", "See", "Cf", "Compare", "Accord",
    "Contra", "Plaintiff", "Plaintiffs", "Defendant", "Defendants", "Petitioner", "Petitioners", "Respondent",
    "Respondents", "Appellant", "Appellants", "Appellee", "Appellees", "Neither", "Nor", "None", "No", "Such",
    "Each", "Every", "Any", "All", "Both", "Other", "First", "Second", "Third", "Next", "Then", "What", "Why",
    "How", "Whether", "Instead", "Rather", "Notably", "Importantly", "Specifically", "Likewise", "Consequently",
    "You", "Your", "I", "My", "For", "With", "By", "From", "During", "Only", "Nothing", "Without", "Upon", "Once",
    "Given", "Absent", "Following", "Unlike", "Like", "Despite", "Regardless", "Note",
}
# Abbreviations that close a phrase, so a capitalized word after one starts a new sentence even when it
# isn't an opener: "Id. at 6 et seq. Simmons argued", "See id. For the reasons", "at 11:43 a.m. Another".
TERMINAL = {"seq", "etc", "a.m", "p.m", "id", "Id", "ibid", "Ibid", "al", "supra", "infra", "Inc", "Co", "Corp", "Ltd",
            "Const", "Stat", "Stats"}
# Abbreviations that begin a citation or a name, so a short word before one may end a sentence:
# "near Ocala. Fla. Stat.", "Dr. Upson. Dr. Upson testified".
CITE_STARTERS = {"Fla", "Fed", "U.S", "Op", "Ops", "Art", "Ch", "Pub", "Dr", "Mr", "Mrs", "Ms"}
# A short word with periods inside: "U.S", "S.D", "e.g", "a.m", "Fla.R.Civ.P". Not a web address or a
# run-together ellipsis ("serious...suppression").
INNER_PERIODS = re.compile(r"(?:[A-Za-z']{1,4}\.)+[A-Za-z0-9']{1,4}")

CLOSERS = "\"'”’)]"
OPENING = "(\"“‘'[{"
# What may begin the next sentence: a capital, a digit, an opening quotation or bracket, a section sign.
STARTS = re.compile(r"[A-Z\d\"“‘'(\[§¶]")


def _tokens(form):
    return [t for t in form.split() if t]


class Abbreviations:
    """The abbreviations the period layer knows, from the data tables (florida.json) and GENERAL.
    tokens: each abbreviation word without its final period ("Fla", "So", "S.D"). phrases: multi-word
    forms ("Fla. L. Weekly", "Fla. R. Civ. P."), indexed by every word they contain, so the reader can
    tell a citation going on ("Fla. L. Weekly") from a new sentence ("Fla. Stat. At")."""

    def __init__(self, data):
        forms = set(GENERAL_PHRASES)
        rep = data["reporters"]
        forms.update(s["abbr"] for s in rep["series"] + rep["bluebook_series"])
        forms.update(m[k] for m in rep["misspellings"] + rep["bluebook_misspellings"] for k in ("wrong", "right"))
        forms.update(e["abbr"] for e in data["florida_law_weekly"]["editions"])
        courts = data["courts"]
        forms.update(c["paren"] for c in courts["florida_appellate"])
        forms.update(c["paren"] for c in courts["federal_courts_of_appeals"] + courts["florida_federal_districts"])
        forms.add(courts["circuit_paren"].replace("{ordinal}", "1st"))
        forms.add(courts["county_paren"].replace("{county} ", ""))
        forms.update(data["states"]["names"])
        forms.update(data["months"]["abbr"].values())
        forms.update(data["case_name_words"]["words"].values())
        for s in data["rule_sets"]["sets"]:
            forms.add(s["abbr"])
            forms.update(s["variants"])
        self.tokens = set(GENERAL)
        self.phrases = {}
        for f in forms:
            words = _tokens(f)
            for w in words:
                # A lowercase misspelling ("so. 2d") counts only inside its form, so "do so. The" still ends.
                if w.endswith(".") and len(w) > 1 and not (w.islower() and f not in GENERAL_PHRASES and len(words) > 1):
                    self.tokens.add(w[:-1])
            if len(words) > 1:
                for k, w in enumerate(words):
                    self.phrases.setdefault(w, set()).add(" ".join(words[k:]))

    def known(self, word):
        """Is word (no final period) an abbreviation: in the tables or GENERAL, a single letter (an
        initial), or a word with a period inside ("U.S", "S.D", "e.g")?"""
        return word in self.tokens or (len(word) == 1 and word.isalpha()) or INNER_PERIODS.fullmatch(word) is not None

    def goes_on(self, text, start, mark):
        """Does a known multi-word form start at the word text[start:mark] and go past its period?"""
        word = text[start:mark + 1]
        cands = self.phrases.get(word)
        if not cands:
            return False
        ahead = re.sub(r"\s+", " ", text[start:start + 80])
        return any(ahead.startswith(p) and len(p) > len(word) and ahead[len(p):len(p) + 1] in ("", " ", ",", ")", ";")
                   for p in cands)


class Periods:
    """Every '.', '?', and '!' in text, read once. reading(i) is ABBREVIATION, END, BOTH, or None (not a
    candidate: no space after it, as in "1.140", "e.g.,", "U.S.C."; or part of an ellipsis)."""

    def __init__(self, text, abbr):
        self.text, self.abbr = text, abbr
        self.readings = {}
        self.after = {}             # mark: offset just past its closers and any footnote number
        for m in re.finditer(r"[.?!]", text):
            i = m.start()
            r, past = self._read(i)
            if r is not None:
                self.readings[i], self.after[i] = r, past
        self.ends = sorted(i for i, r in self.readings.items() if r in (END, BOTH))

    # ---- reading one mark

    def _word(self, i):
        """Start of the word that ends at the mark text[i]: back to whitespace or an opening mark."""
        s = i
        while s > 0 and not self.text[s - 1].isspace():
            s -= 1
        while s < i and self.text[s] in OPENING:
            s += 1
        return s

    def _past(self, i):
        """Offset just past the mark's closers ('.")' ) and a footnote number ('relief.19 In'), or None if
        no whitespace or end of text follows there. After a number, digits are a footnote's only when an
        opener follows ('at 34-35.8 While'); otherwise they're a decimal ('Rule 3.850 Fla.', '$9,217.63')."""
        text, n = self.text, len(self.text)
        j = i + 1
        while j < n and text[j] in CLOSERS:
            j += 1
        if j < n and text[j].isdigit() and i > 0:
            k = j
            while k < n and k - j < 3 and text[k].isdigit():
                k += 1
            if k == n or text[k].isspace():
                after_digit = text[i - 1].isdigit() and j == i + 1
                w = re.match(r"\s+([A-Za-z']+)", text[k:k + 30])
                if not after_digit or (w and w.group(1) in OPENERS):
                    j = k
        if j == n or text[j].isspace():
            return j
        return None

    def _ellipsis(self, i):
        """The run of periods (closed up or single-spaced) holding text[i], as (first, last), or None if it's alone."""
        t = self.text
        a = b = i
        while a >= 1 and t[a - 1] == "." or a >= 2 and t[a - 2:a] == ". ":
            a -= 1 if t[a - 1] == "." else 2
        while t[b + 1:b + 2] == "." or t[b + 1:b + 3] == " .":
            b += 1 if t[b + 1] == "." else 2
        return (a, b) if a != b else None

    def _read(self, i):
        text = self.text
        past = self._past(i)
        if past is None:
            return None, None
        k = past
        while k < len(text) and text[k].isspace():
            k += 1
        nxt = text[k:k + 1]
        starts = nxt == "" or STARTS.match(nxt) is not None
        run = self._ellipsis(i) if text[i] == "." else None
        if run:
            # An ellipsis ends nothing, except four dots before a new sentence: "injured. . . . Do you".
            dots = text[run[0]:run[1] + 1].count(".")
            return (END if i == run[1] and dots >= 4 and starts and nxt != "" and not nxt.isdigit() else None), past
        if text[i] in "?!":
            return (END if starts else None), past
        s = self._word(i)
        word = text[s:i]
        if word and self.abbr.goes_on(text, s, i):
            return ABBREVIATION, past                           # "So. 3d", "Fla. L. Weekly", "so. 2d"
        if not word or word[-1] in CLOSERS or word[-1].isdigit():
            return (END if starts else ABBREVIATION), past     # "2001). The", "at 5. Id.", "1.140(b)."
        if not self.abbr.known(word):
            # A word, not an abbreviation: "court. The". Lowercase next means it was one after all, and so
            # does a number after a short all-capitals word, a record cite: "(PCR. 362)".
            if nxt.isdigit() and word.isupper() and len(word) <= 5:
                return ABBREVIATION, past
            # A short capitalized word before a known abbreviation is one too, from a source the tables
            # don't hold: "74 Marq. L. Rev.", "Fair Empl. Prac. Cas.". Not before an opener: "Yes. Id."
            m = re.match(r"([A-Z][A-Za-z']*)\.", text[k:k + 20])
            if (m and word[:1].isupper() and word.isalpha() and len(word) <= 5 and self.abbr.known(m.group(1))
                    and m.group(1) not in OPENERS and m.group(1) not in CITE_STARTERS):
                return ABBREVIATION, past
            return (END if starts else ABBREVIATION), past
        if nxt == "":
            return BOTH, past
        if not nxt.isupper():
            return ABBREVIATION, past                           # "cert. denied", "Fla. 2001", "id. § 5"
        m = re.match(r"([A-Za-z']+)(\.?)", text[k:k + 30])
        if m and m.group(1) in OPENERS:
            return BOTH, past                                   # "Fla. Stat. At sentencing", "Inc. The"
        if word in TERMINAL and not (m and m.group(2) and self.abbr.known(m.group(1))):
            return BOTH, past                                   # "et seq. Simmons"; not "Dade Co. Cir. Ct."
        return ABBREVIATION, past                               # "Fla. Power & Light Co.", "v. Smith"

    # ---- queries

    def reading(self, i):
        return self.readings.get(i)

    def sentence_end(self, i):
        """Does the mark text[i] end a sentence (END or BOTH)?"""
        return self.readings.get(i) in (END, BOTH)

    def end_after(self, i):
        """The first sentence-ending mark at or after offset i, or None."""
        k = bisect.bisect_left(self.ends, i)
        return self.ends[k] if k < len(self.ends) else None

    def end_before(self, i):
        """The last sentence-ending mark before offset i, or None."""
        k = bisect.bisect_left(self.ends, i)
        return self.ends[k - 1] if k else None

    def past(self, mark):
        """Offset just past a sentence end's closers and footnote number: where the next sentence's space begins."""
        return self.after.get(mark)

    def sentence_start(self, i):
        """Offset where the sentence holding offset i starts (past the previous end and its whitespace)."""
        e = self.end_before(i)
        while e is not None and self.after[e] > i:
            e = self.end_before(e)              # i sits in the closers of that end: its sentence is the one before
        k = 0 if e is None else self.after[e]
        while k < i and self.text[k].isspace():
            k += 1
        return k


class Brackets:
    """Parentheses in text, paired once. quotes: (open, close) offsets of paired quotation marks; their
    insides are opaque, paired on their own, so a source's parentheses don't pair with the writer's and
    its sentence ends close nothing.

    The recovery rule, decided here once: outside quotations, a sentence end (from periods) closes what's
    still open and won't close in the next sentence either, so one missing ')' doesn't swallow the page.
    A parenthesis that closes within the next sentence stays open across the end: "(Emphasis added.)",
    "(The court so held. See Able.)", and a period misread as a sentence end, "(Dade Co. Cir. Ct. 2024)".

    pairs: {open: close}. unclosed: opens closed by a sentence end or never closed. stray: ')' closing
    nothing."""

    def __init__(self, text, periods, quotes=()):
        self.text = text
        self.pairs, self.unclosed, self.stray = {}, [], []
        self.span = {}                  # open: offset of the last character it covers
        n = len(text)
        quote_end = {}
        for a, b in quotes:
            quote_end[a] = b
        qa = sorted(quote_end)

        def quoted(m):
            k = bisect.bisect_right(qa, m) - 1
            return k >= 0 and m < quote_end[qa[k]]

        recover_at = {}
        for mark in periods.ends:
            if not quoted(mark):
                recover_at.setdefault(periods.past(mark), mark)
        points = sorted(recover_at)
        outside = [i for i, ch in enumerate(text) if ch in "()" and not quoted(i) and i not in quote_end]

        def closes_ahead(r):
            """How many parentheses open at r the next sentence closes (its lowest running depth)."""
            k = bisect.bisect_right(points, r)
            stop = points[k] if k < len(points) else n
            d = low = 0
            for j in outside[bisect.bisect_left(outside, r):bisect.bisect_left(outside, stop)]:
                d += 1 if text[j] == "(" else -1
                low = min(low, d)
            return -low

        outer, inner, inside = [], [], None
        for i in range(n + 1):
            if i in recover_at and inside is None and outer:
                keep = min(closes_ahead(i), len(outer))
                mark = recover_at[i]
                for o in outer[:len(outer) - keep]:
                    self.unclosed.append(o)
                    self.span[o] = mark
                outer = outer[len(outer) - keep:]
            if i == n:
                break
            ch = text[i]
            if inside is not None and i == inside:
                for o in inner:
                    self.unclosed.append(o)
                    self.span[o] = i
                inner, inside = [], None
                continue
            if inside is None and i in quote_end:
                inside = quote_end[i]
                continue
            stack = outer if inside is None else inner
            if ch == "(":
                stack.append(i)
            elif ch == ")":
                if stack:
                    o = stack.pop()
                    self.pairs[o] = i
                    self.span[o] = i
                else:
                    self.stray.append(i)
        for o in outer + inner:
            self.unclosed.append(o)
            self.span[o] = n
        self.unclosed.sort()
        self.opens = sorted(self.span)

    def open_paren(self, i, reach=None):
        """The innermost '(' open at offset i (opened before i, still open at i), or None. reach limits how
        far back it may be."""
        k = bisect.bisect_left(self.opens, i) - 1
        while k >= 0:
            o = self.opens[k]
            if reach is not None and i - o > reach:
                return None
            if self.span[o] >= i:
                return o
            k -= 1
        return None

    def depth(self, a, b):
        """Parentheses opened in text[a:b] and still open at its end."""
        lo, hi = bisect.bisect_left(self.opens, a), bisect.bisect_left(self.opens, b)
        return sum(1 for o in self.opens[lo:hi] if self.span[o] >= b)
