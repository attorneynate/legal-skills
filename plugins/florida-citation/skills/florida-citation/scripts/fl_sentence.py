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
3. Clauses and sentences, the parts built so far. Clauses: where the clause holding an offset ends, at a
   ';' or a sentence end outside quotations, at that offset's own depth in parentheses. Sentences: the
   writer's sentences (quotations' own sentence ends aside), so two offsets can be asked whether they
   share one; and, with the citations overlaid after extraction, what governs a citation in its sentence
   and whether the sentence ends with it.

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
    "Init", "Att", "Lt", "Sgt", "Capt", "Cpl", "Det", "Ofc", "Hon", "Prof",
    # Florida case-name words the tables don't abbreviate: "Mia. Harbor Tours Corp.", "Mia.-Dade Cnty.",
    # "Gulf Neuro. Injury Comp. Ass'n". Unknown, they read as words ending a sentence, like "Hurst. Able v.".
    "Mia", "Neuro",
    # The older form of County, which the table gives as Cnty., and its plural (the table's own plurals are
    # derived): "Real Prop. in Able & Baker Ctys. in State of Ala.".
    "Ctys",
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
# Abbreviations a word always follows, so they never end a sentence, even before an opener: a party's
# name ("Olsen v. First Team Ford", "State ex rel. The Florida Bar"), a person's ("Mr. Long", "Lt. Able"), a
# citation ("Cf. In re Able").
FOLLOWED = {"v", "vs", "rel", "Cf", "cf", "Mr", "Mrs", "Ms", "Lt", "Sgt", "Capt", "Cpl", "Det", "Ofc", "Hon", "Prof"}
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

# Layer 3's citation overlay. Words after which a citation isn't governed by the writer's sentence: a
# signal, a parenthetical's "quoting" or "citing", a list's connector ("§ 1 and § 2").
NOT_GOVERNING = {"see", "also", "cf.", "e.g.,", "accord", "compare", "contra", "but", "quoting", "citing", "and",
                 "or", "&", "generally"}
# A signal opening a clause makes it a citation clause: "Compare X with Y", "See Able, ..., construing Y".
SIGNAL_OPENING = re.compile(r"(?:see(?:,? also| generally)?|cf\.|compare|accord|contra|but (?:see|cf\.)|e\.g\.)"
                            r"(?=[\s,])", re.I)
# A short opener before a citation that opens its sentence: "Similarly, ", "In addition, ".
SHORT_OPENER = re.compile(r"([A-Z][a-z]+(?: [a-z]+){0,2}), ")
# What may come before a citation that frames its clause: a short opener, then "In", "Under", or a court
# saying something in it ("As this Court explained in", "We held in"), or none of these.
FRAME_LEAD = re.compile(r"(?:([A-Z][a-z]+(?: [a-z]+){0,2}), )?(?:[Ii]n |[Uu]nder |(?:[Aa]s )?(?:(?:[Tt]he|[Tt]his|[Oo]ur) "
                        r"(?:[A-Z][a-z]+ ){0,3}(?:[Cc]ourt|Circuit|District)(?: Court)?(?: of Appeals?)?|[Ww]e)"
                        r"(?: (?!that\b)[a-z]+){1,2} in )?")
# Words a clause of citations holds besides the citations: signals, connectors, subsequent history. Any
# other word left once the citations and parentheticals are set aside is the writer's.
CITATION_WORDS = {
    "see", "also", "generally", "cf", "compare", "accord", "contra", "but", "and", "or", "with", "quoting",
    "citing", "aff'd", "rev'd", "affirmed", "reversed", "approved", "quashed", "disapproved", "vacated",
    "modified", "abrogated", "overruled", "receded", "superseded", "dismissed", "declined", "follow", "cert",
    "denied", "granted", "review", "reh'g", "mandamus", "appeal", "in", "part", "on", "other", "grounds", "by",
    "sub", "nom", "as", "stated", "from", "to", "at", "amended", "repealed", "renumbered", "transferred",
    "codified", "recodified",
}


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
        name_words = set(data["case_name_words"]["words"].values())
        forms.update(name_words)
        for s in data["rule_sets"]["sets"]:
            forms.add(s["abbr"])
            forms.update(s["variants"])
        self.tokens = set(GENERAL)
        # A case-name word is an abbreviation with or without its period ("Ass'n", and "Env't." by mistake),
        # and so is its plural, which adds s (the table's own rule): "Emps.", "Invs.", "Trs.", "Dep'ts".
        for f in name_words:
            for w in re.findall(r"[A-Z][A-Za-z']*[A-Za-z]\.?", f):
                if "." in f[:-1] and " " not in f:
                    continue                    # "R.R.", "U.S.": read by INNER_PERIODS
                if "'" in w or w.endswith("."):
                    self.tokens.update((w.rstrip("."), w.rstrip(".") + "s"))
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
        self.plain = [i for i in self.ends if self.readings[i] == END]

    # ---- reading one mark

    def _word(self, i):
        """Start of the word that ends at the mark text[i]: back to whitespace or an opening mark, or to a
        parenthesis or bracket run into the word before it ("266(Fla.")."""
        s = i
        while s > 0 and not self.text[s - 1].isspace() and self.text[s - 1] not in "([":
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
        # A period just inside a closing double quotation mark, after a word that isn't an abbreviation, is
        # the writer's: the sentence can't go on in lowercase ('"in writing." determining' means text was
        # lost, as at a page break). "?" and "!" can: '"Was it personal?" asked the court'.
        starts = starts or text[i + 1:i + 2] in "\"”"
        # So is a period right after a closing parenthesis, which no abbreviation ends: "(Fla. 2001). the
        # court" means text was lost, as in a two-column page read across.
        if word[-1:] == ")":
            return END, past
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
        if not nxt.isupper() or word in FOLLOWED:
            return ABBREVIATION, past                           # "cert. denied", "Fla. 2001", "v. First"
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

    def sentence_start(self, i, plain=False):
        """Offset where the sentence holding offset i starts (past the previous end and its whitespace).
        plain: count only plain ends (END), not an abbreviation that may also end the sentence (BOTH), for
        a caller that knows more about what follows it: a party's name going on to "v." ("Coastal Ltd.
        P'ship v.", "Sec. First Ins. v.")."""
        ends = self.plain if plain else self.ends

        def before(j):
            k = bisect.bisect_left(ends, j)
            return ends[k - 1] if k else None
        e = before(i)
        while e is not None and self.after[e] > i:
            e = before(e)                       # i sits in the closers of that end: its sentence is the one before
        k = 0 if e is None else self.after[e]
        while k < i and self.text[k].isspace():
            k += 1
        return k


def _inside(spans):
    """A test for whether an offset lies in one of spans, (open, close) offsets of quotation marks
    (open <= i < close). Nested or overlapping spans count as one."""
    merged = []
    for a, b in sorted(spans):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    starts = [a for a, _ in merged]

    def inside(i):
        k = bisect.bisect_right(starts, i) - 1
        return k >= 0 and i < merged[k][1]
    return inside


class Brackets:
    """Parentheses in text, paired once. quotes: (open, close) offsets of paired quotation marks; their
    insides are opaque, paired on their own, so a source's parentheses don't pair with the writer's and
    its sentence ends close nothing. quoted(i): is offset i inside one of them?

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
        self.quoted = quoted = _inside(quotes)
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


class Clauses:
    """Where a clause ends: at a ';' or a sentence end outside quotations, at the depth in parentheses of
    the offset it's asked about. A parenthesis opened inside the clause and still open carries it past
    one: in "Able, 1 So. 3d 2 (Fla. 2001) (citing Baker; Cole). Next.", Able's clause ends at the final
    period. One opened before doesn't: in "(see Able, 1 So. 3d 2; Baker, ...)", Able's ends at the ';'.
    A parenthesis the bracket layer closes at a sentence end (one never closed) is open up to that end,
    not over it, so the end still closes the clause.

    Sentences (below) holds the rest of layer 3 built so far: same_sentence, and the citation overlay."""

    def __init__(self, text, periods, brackets):
        quoted = brackets.quoted
        self.brackets = brackets
        self.semicolons = [i for i, ch in enumerate(text) if ch == ";" and not quoted(i)]
        self.ends = [e for e in periods.ends if not quoted(e)]

    def _covered(self, i, j):
        """Is a parenthesis opened in text[i:j] still open over offset j?"""
        br = self.brackets
        lo, hi = bisect.bisect_left(br.opens, i), bisect.bisect_left(br.opens, j)
        return any(br.span[o] > j for o in br.opens[lo:hi])

    def clause_end(self, i, after=None, reach=None):
        """Offset of the ';' or sentence-ending mark that ends the clause holding offset i, or None if
        none does before i + reach. A sentence end counts only at or after offset `after` (default i): a
        citation's own last period may end its sentence ("..., Fla. Stat. At the hearing"), but no
        period inside it can."""
        after = i if after is None else after
        limit = len(self.brackets.text) + 1 if reach is None else i + reach
        semis, ends = self.semicolons, self.ends
        s, e = bisect.bisect_left(semis, i), bisect.bisect_left(ends, after)
        while True:
            a = semis[s] if s < len(semis) else limit
            b = ends[e] if e < len(ends) else limit
            j = min(a, b)
            if j >= limit:
                return None
            if j == a:
                s += 1
            else:
                e += 1
            if not self._covered(i, j):
                return j


class Sentences:
    """The writer's sentences: which one holds an offset, and where it starts and ends. A sentence end
    from the period layer is the writer's when it's outside quotations, or when it ends a quotation and the
    writer's sentence with it, so its closers reach past the closing mark: 'called it "harmless." It
    held'. One inside a quotation that goes on is the source's: '"It erred. We reverse," the court said'
    is one sentence. A sentence runs past its end's closers and footnote number ('relief."19 In').

    The citation overlay (overlay(), after extraction): what governs a citation in its sentence
    (governing_word), read from its clause, which is a citation clause or holds the writer's own words;
    whether it frames its clause (frames); and whether its sentence ends with it (ends_at). Whether the
    sentence goes on after a citation in the writer's words is the caller's, which knows what more of a
    citation looks like ("or 9.331", "&(i)")."""

    def __init__(self, text, periods, brackets):
        quoted = brackets.quoted
        self.text = text
        self.brackets = brackets
        self.ends = [e for e in periods.ends if not quoted(periods.past(e) - 1)]
        self.bounds = [periods.past(e) for e in self.ends]      # where each next sentence's space begins
        self.semicolons = [i for i, ch in enumerate(text) if ch == ";" and not quoted(i)]
        self.cites = []

    def index(self, i):
        """The number of the sentence holding offset i, counting from 0."""
        return bisect.bisect_right(self.bounds, i)

    def same_sentence(self, a, b):
        """Do offsets a and b lie in one sentence: no writer's sentence end between them?"""
        return self.index(a) == self.index(b)

    def end(self, i):
        """The mark that ends the sentence holding offset i, or None if the text runs out first."""
        k = self.index(i)
        return self.ends[k] if k < len(self.ends) else None

    def start(self, i):
        """Offset where the sentence holding offset i starts: past the end before it and any whitespace."""
        k = self.index(i)
        s = self.bounds[k - 1] if k else 0
        while s < i and self.text[s].isspace():
            s += 1
        return s

    # ---- the citation overlay

    def overlay(self, spans):
        """Lay the citations over the sentences: (start, end) offsets, a case's name included."""
        self.cites = sorted(spans)

    def ends_at(self, j):
        """Does a writer's sentence end with a citation ending at offset j: at its own last period ("...,
        Fla. Stat. Moreover") or at the mark right after it ("... 1.190(a). The", "... 9.130(a)(3).2 The")?"""
        k = bisect.bisect_left(self.ends, j - 1)
        return k < len(self.ends) and self.ends[k] <= j

    def clause_start(self, i):
        """Offset where the clause holding offset i starts: its sentence's start, or past the last ';'
        before i outside quotations and outside a parenthetical closed before i, or past the '(' of a
        parenthetical holding i, which is a phrase of its own: in "See Able, 1 So. 3d 2 (discussing the
        clause in Art. II, § 3, Fla. Const., which ...)", the citation's clause is "discussing ...", not
        the citation sentence the signal opens."""
        s = self.start(i)
        k = bisect.bisect_left(self.semicolons, i) - 1
        br = self.brackets
        while k >= 0 and self.semicolons[k] >= s:
            semi = self.semicolons[k]
            o = br.open_paren(semi)
            if o is None or br.span[o] >= i:
                s = semi + 1
                break
            k -= 1
        o = br.open_paren(i)
        if o is not None and o >= s:
            s = o + 1
        while s < i and self.text[s].isspace():
            s += 1
        return s

    def _textual(self, a, b):
        """Does text[a:b] hold the writer's own words: a word left once the overlaid citations, the text in
        parentheses, and a citation clause's own words (signals, connectors, history) are set aside?"""
        t = list(self.text[a:b])
        for x, y in self.cites:
            if x >= b:
                break
            for p in range(max(x, a), min(y, b)):
                t[p - a] = " "
        t = "".join(t)
        while True:
            u = re.sub(r"\([^()]*\)", " ", t)
            if u == t:
                break
            t = u
        return any(w.lower() not in CITATION_WORDS for w in re.findall(r"[A-Za-z][A-Za-z']+", t))

    def governing_word(self, i):
        """What governs a citation starting at offset i in the writer's sentence (call overlay() first):
        "" when the citation opens its sentence, alone or after a short opener ("Similarly, ", "In
        addition, "); the word right before it, lowercased ("under", "to" in "pursuant to", "that"), when
        its clause holds the writer's own words; or None: after a signal or a list's connector ("See ",
        "and "), in a clause a signal opens ("Compare X with Y"), in a clause of only citations and their
        history ("§ 1, Fla. Stat. (2019), amended by ch. 2020-1, Laws of Fla."), or after punctuation or
        an abbreviation ("Cf. ", "Inc. ")."""
        s = self.start(i)
        lead = self.text[s:i]
        if not lead:
            return ""
        m = SHORT_OPENER.fullmatch(lead)
        if m and not set(m.group(1).lower().split()) & NOT_GOVERNING:
            return ""
        c = self.clause_start(i)
        clause = self.text[c:i]
        w = re.search(r"(?:^|[\s(])([A-Za-z][a-z]+)\s$", clause)
        if (not w or w.group(1).lower() in NOT_GOVERNING or re.search(r",\s?with\s$", clause)
                or SIGNAL_OPENING.match(clause) or not self._textual(c, i)):
            return None
        return w.group(1).lower()

    def frames(self, i):
        """Does the citation starting at offset i frame its clause: open it, alone, after a short opener
        ("Similarly, "), after "In" or "Under", or after a court saying something in it ("In Able v. Baker,
        1 So. 3d 2 (Fla. 2001), the court held that ...", "Section 1, Fla. Stat., provides that ...", "As
        this Court explained in Able v. Baker, ...")? Then the clause's words are about it. A citation
        further into its clause may be in someone else's words: in "Cole noted that in Able v. Baker, ...,
        the court ...", what follows may be Cole's."""
        c = self.clause_start(i)
        m = FRAME_LEAD.fullmatch(self.text[c:i])
        return bool(m) and not (m.group(1) and set(m.group(1).lower().split()) & NOT_GOVERNING)
