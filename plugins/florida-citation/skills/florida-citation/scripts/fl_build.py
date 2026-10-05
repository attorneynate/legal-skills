"""The engine behind `fl_cite.py build`: a citation in Rule 9.800's form, from its parts.

  python fl_cite.py build case "Fenelon v. State" --court SC --year 1992 --cite "594 So. 2d 292" --pin 293
  python fl_cite.py build case "Myers v. State" --court 4D --date 1991-06-05 --flw "16 Fla. L. Weekly D1507"
  python fl_cite.py build case "Singh v. State" --court SC --date 2014-12-30 --docket SC10-1544 --westlaw "2014 WL 7463592"
  python fl_cite.py build statute 48.031 --year 2014
  python fl_cite.py build rule civ 1.180

Every citation it builds is run through the `check` engine. Input that can't be right (a reporter
series that didn't exist that year, a court that hadn't been created) is refused with the reason.
A fact the script can't know is left as a visible blank (___) and named, never guessed.
Standard library only.
"""

import datetime as dt
import json
import re
import sys

import fl_check
import fl_cite as fc

BLANK = "___"
# Findings that mean the parts can't all be right, so build refuses instead of noting them.
IMPOSSIBLE = {"a-series-year", "b-court-before-it-existed", "flw-section-court", "flw-volume-year",
              "docket-court-mismatch", "j-rule-set-number", "court-unreadable"}
ROMAN = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
         (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]


class BuildError(Exception):
    pass


class Result:
    def __init__(self):
        self.citation = None
        self.check_text = None          # the citation with blanks filled by placeholders, for the self-check
        self.blanks = []
        self.notes = []
        self.abbreviated = []
        self.sentence = None
        self.authority = None


# ---------------------------------------------------------------- parts

def roman(s):
    s = str(s).strip().upper()
    if re.fullmatch(r"[IVXL]+", s):
        return s
    if not s.isdigit() or not 0 < int(s) < 100:
        raise BuildError(f"an article or amendment is a roman numeral or a number; got {s!r}")
    n, out = int(s), ""
    for v, r in ROMAN:
        while n >= v:
            out, n = out + r, n - v
    return out


def parse_date(s):
    """'1992' -> (1992, None); '1992-01-16' -> (1992, date)."""
    if s is None:
        return None, None
    s = s.strip()
    if re.fullmatch(r"\d{4}", s):
        return int(s), None
    try:
        d = dt.date.fromisoformat(s)
    except ValueError:
        raise BuildError(f"dates are YYYY or YYYY-MM-DD; got {s!r}")
    return d.year, d


def fmt_date(d, data):
    month = d.strftime("%B")
    return f"{data['months']['abbr'][month]} {d.day}, {d.year}"


def court(spec, data):
    """A court as the user names it ('SC', '3D', '4th DCA', 'circuit:17', 'county:Miami-Dade', 'US',
    'CA11', '11th Cir.', 'S.D. Fla.') -> {'paren', 'sub', 'id'}."""
    if not spec:
        raise BuildError("give the court with --court (SC, 1D-6D, circuit:N, county:NAME, US, CA1-CA11, S.D. Fla., ...)")
    s = spec.strip()
    low = s.lower().replace(" ", "")
    for c in data["courts"]["florida_appellate"]:
        if low in (c["id"].lower(), c["paren"].lower().replace(" ", ""), c["name"].lower().replace(" ", "")):
            return {"paren": c["paren"], "sub": c["rule"][-2], "id": c["id"]}
    m = re.fullmatch(r"(?:fla\.?)?([1-6])(?:d|st|nd|rd|th)?(?:dca|districtcourtofappeal)?", low)
    if m:
        return court(f"{m.group(1)}D", data)
    if low in ("sc", "fla", "fla.", "fsc", "floridasupremecourt"):
        return court("SC", data)
    m = re.fullmatch(r"(?:circuit:?|fla\.?)(\d{1,2})(?:st|d|nd|rd|th)?(?:cir\.?ct\.?)?|(\d{1,2})(?:st|d|nd|rd|th)?judicialcircuit", low)
    if m:
        n = int(m.group(1) or m.group(2))
        if not 1 <= n <= data["courts"]["circuit_count"]:
            raise BuildError(f"Florida has {data['courts']['circuit_count']} judicial circuits; got {n}")
        return {"paren": data["courts"]["circuit_paren"].format(ordinal=fc.ordinal(n)), "sub": "c", "id": "circuit"}
    m = re.fullmatch(r"(?i)county:\s*(.+)|(.+?)\s+(?:county|cty\.?)(?:\s+(?:court|ct\.?))?", s)
    if m:
        want = (m.group(1) or m.group(2)).strip().lower()
        for name in data["counties"]["names"]:
            if name.lower() == want:
                return {"paren": data["courts"]["county_paren"].format(county=name), "sub": "c", "id": "county"}
        raise BuildError(f"no Florida county named {want!r}; `fl_cite.py abbrev county` lists them")
    if low in ("us", "u.s.", "ussc", "scotus", "supremecourtoftheunitedstates"):
        return {"paren": "U.S.", "sub": "l", "id": "USSC"}
    m = re.fullmatch(r"ca(\d{1,2}|dc|fed)|(\d{1,2})(?:st|d|nd|rd|th)cir(?:\.|cuit)?|(d\.c\.|fed\.)cir\.?", low)
    if m:
        n = m.group(1) or m.group(2) or m.group(3)
        if n.isdigit():
            if not 1 <= int(n) <= 11:
                raise BuildError(f"the federal circuits are numbered 1-11 (plus D.C. and Federal); got {n}")
            return {"paren": f"{fc.ordinal(int(n))} Cir.", "sub": "m", "id": f"CA{n}"}
        return {"paren": "D.C. Cir." if "d" in n.lower()[:1] else "Fed. Cir.", "sub": "m", "id": "CA" + n.upper()}
    m = re.fullmatch(r"([nms])\.?d\.?(?:fla\.?)?", low)
    if m:
        return {"paren": f"{m.group(1).upper()}.D. Fla.", "sub": "n", "id": f"{m.group(1).upper()}.D. Fla."}
    raise BuildError(f"can't read the court {spec!r}. Use SC, 1D-6D, circuit:N, county:NAME, US, CA1-CA11, "
                     "CADC, CAFED, or N.D./M.D./S.D. Fla. Other courts are outside Rule 9.800 (9.800(p)).")


def abbreviate_name(name, data):
    """Abbreviate case-name words in a citation (Indigo Book R11.3, Table T11). Returns (name, changes)."""
    table = data["case_name_words"]["words"]
    not_first = set(data["case_name_words"]["not_first"])
    out, changes = [], []
    for part in re.split(r"( v\. )", name):
        if part == " v. " or part.strip() in ("United States", "Florida", "State", "United States of America"):
            out.append(part)                 # a geographical name that is a whole party stays whole
            continue
        toks = re.split(r"([^\w'&\-]+)", part)
        first = True
        for i, t in enumerate(toks):
            if not t or not re.match(r"[\w&]", t):
                continue
            abbr = table.get(t)
            if abbr is None and len(t) > 3 and t.endswith("s") and t[:-1] in table:
                a = table[t[:-1]]
                abbr = a[:-1] + "s." if a.endswith(".") else a + "s"      # Services -> Servs., Departments -> Dep'ts
            if abbr and abbr != t and not (first and t in not_first) and (t[0].isupper() or t == "and"):
                changes.append((t, abbr))
                toks[i] = abbr
            first = False
        out.append("".join(toks))
    return "".join(out), changes


def reporter_cite(text, engine):
    m = re.fullmatch(r"\s*(\d{1,4})\s+(.+?)\s+(\d{1,6})\s*", text or "")
    if not m:
        raise BuildError(f"--cite takes volume, reporter, and first page, like '594 So. 2d 292'; got {text!r}")
    rep = re.sub(r"\s+", " ", m.group(2))
    canonical = engine.reporter_forms.get(rep)
    if canonical is None:
        squeezed = rep.replace(" ", "")
        canonical = next((v for k, v in engine.reporter_forms.items() if k.replace(" ", "") == squeezed), None)
    if canonical is None or canonical in engine.bluebook_reporters:
        raise BuildError(f"{rep!r} isn't a reporter Rule 9.800 uses (So., So. 2d, So. 3d, Fla., U.S., S. Ct., "
                         "F., F.2d-F.4th, F. App'x, F. Supp.-F. Supp. 3d, Fla. Supp.); others follow 9.800(p).")
    return m.group(1), canonical, m.group(3)


FLW = re.compile(r"\s*(\d{1,3})\s+Fla\.?\s*L\.?\s*W(?:ee)?kly\.?(\s+(?:Supp|Fed)\.)?\s+([A-Z]?\d{1,5}[a-z]?)\s*", re.I)


# ---------------------------------------------------------------- the types

def build_case(a, data, engine):
    r = Result()
    name = a.name.strip()
    if not a.no_abbreviate:
        name, r.abbreviated = abbreviate_name(name, data)
    ct = court(a.court, data)
    year, date = parse_date(a.date or a.year)
    if year is None:
        raise BuildError("give the decision's year (--year) or exact date (--date YYYY-MM-DD)")
    sources = [x for x in (a.cite, a.flw) if x]
    if len(sources) > 1:
        raise BuildError("give one of --cite or --flw: Rule 9.800 cites Southern Reporter first, then Florida Law "
                         "Weekly only if the case isn't in Southern Reporter")
    if not sources and not a.docket and not (a.westlaw or a.lexis):
        raise BuildError("give where the case is published: --cite (a reporter), --flw (Florida Law Weekly), or "
                         "--docket (the slip opinion), optionally with --westlaw or --lexis")
    pin = f", {a.pin}" if a.pin else ""
    exact = fmt_date(date, data) if date else None
    if a.cite:
        vol, rep, page = reporter_cite(a.cite, engine)
        given = re.sub(r"\s+", " ", a.cite.strip())[len(vol) + 1:-len(page) - 1]
        if given != rep:
            r.notes.append(f"Reporter written {rep}, not {given} (9.800's examples; Indigo Book R11.6).")
        if rep == "Fla." and year <= 1886:
            paren = f"({year})"              # 9.800(a)(2): the court is clear from the reporter
        elif ct["id"] == "USSC" and rep in ("U.S.", "S. Ct."):
            paren = f"({year})"              # 9.800(l)(1)
        else:
            paren = f"({ct['paren']} {year})"
        body = f"{vol} {rep} {page}{pin}"
        r.citation = r.check_text = f"{name}, {body} {paren}"
        if date:
            r.notes.append("A reporter citation takes only the year; the exact date is for Fla. L. Weekly, "
                           "slip opinions, and Westlaw or LEXIS.")
    else:
        if exact:
            when, when_check = exact, exact
        else:
            when, when_check = f"{BLANK} {BLANK}, {year}", f"Dec. 31, {year}"
            r.blanks.append("the decision's exact month and day (9.800 gives Fla. L. Weekly and slip-opinion "
                            "citations their exact date)")
        if a.flw:
            m = FLW.fullmatch(a.flw)
            if not m:
                raise BuildError(f"--flw takes a cite like '17 Fla. L. Weekly S42' or '17 Fla. L. Weekly Supp. 619'; got {a.flw!r}")
            ed = (" " + m.group(2).strip().capitalize()) if m.group(2) else ""
            body = f"{m.group(1)} Fla. L. Weekly{ed} {m.group(3)}{pin}"
            if a.docket or a.westlaw or a.lexis:
                r.notes.append("A Fla. L. Weekly cite stands alone; the docket and Westlaw or LEXIS cite were left out.")
        else:
            docket, docket_check = a.docket, a.docket
            if docket:
                if re.fullmatch(r"(?:SC|[1-6]D)\s*\d{2,4}-\d+", docket.strip(), re.I) and ct["id"] in ("SC", "1D", "2D", "3D", "4D", "5D", "6D"):
                    new, note = fc.convert_case_number(docket, data)
                    if new is None:
                        raise BuildError(f"case number {docket}: {note}")
                    if new != docket.strip().upper():
                        r.notes.append(f"Case number written in the four-digit form, {docket} -> {new} "
                                       f"({data['case_numbers']['source'].split(':')[0]}).")
                    docket = docket_check = new
            else:
                docket = BLANK
                docket_check = f"{ct['id']}{year}-0001" if ct["id"] in ("SC", "1D", "2D", "3D", "4D", "5D", "6D") else "1"
                r.blanks.append("the docket number (9.800 gives a Westlaw or LEXIS cite only alongside the slip "
                                "opinion's docket number)")
            online = ""
            if a.westlaw and a.lexis:
                raise BuildError("give --westlaw or --lexis, not both")
            if a.westlaw:
                m = re.fullmatch(r"\s*(\d{4})\s*WL\s*(\d+)\s*", a.westlaw)
                if not m:
                    raise BuildError(f"--westlaw takes a cite like '2014 WL 7463592'; got {a.westlaw!r}")
                online = f", {m.group(1)} WL {m.group(2)}"
            elif a.lexis:
                m = re.fullmatch(r"\s*(\d{4})\s+(.+?LEXIS)\s+(\d+)\s*", a.lexis)
                if not m:
                    raise BuildError(f"--lexis takes a cite like '2010 Fla. LEXIS 62'; got {a.lexis!r}")
                online = f", {m.group(1)} {m.group(2)} {m.group(3)}"
            opin = f", at {a.pin}" if a.pin and online else pin
            body = f"No. {docket}{online}{opin}"
            body_check = f"No. {docket_check}{online}{opin}"
        r.citation = f"{name}, {body} ({ct['paren']} {when})"
        r.check_text = f"{name}, {body_check if not a.flw else body} ({ct['paren']} {when_check})"
    return r


def build_agency(a, data, engine):
    r = Result()
    name = a.name.strip()
    if not a.no_abbreviate:
        name, r.abbreviated = abbreviate_name(name, data)
    year, date = parse_date(a.date)
    if not date:
        raise BuildError("agency orders take the exact date: --date YYYY-MM-DD (9.800(d)(1), (2))")
    body = a.body.strip()
    if body.upper() == "DOAH":
        body = "Fla. DOAH"
    elif not body.startswith("Fla. "):
        body = "Fla. " + body
    if not a.docket:
        raise BuildError("give the agency or DOAH case number with --docket")
    order = f" ({a.order})" if a.order else ""
    if body == "Fla. DOAH" and not a.order:
        r.notes.append("A DOAH decision names its type in a parenthetical: (Recommended Order) or (Final Order) (9.800(d)(2)).")
    r.citation = r.check_text = f"{name}, No. {a.docket} ({body} {fmt_date(date, data)}){order}"
    return r


def build_statute(a, data, engine):
    r = Result()
    secs = [s.strip() for s in a.sections]
    for s in secs:
        if not re.fullmatch(fl_check.SEC, s):
            raise BuildError(f"{s!r} isn't a Florida Statutes section number (like 48.031 or 775.082(3)(a)1.)")
    if a.year and a.supp:
        raise BuildError("give --year or --supp, not both")
    year = f" ({a.year})" if a.year else (f" (Supp. {a.supp})" if a.supp else "")
    sign = "§§" if len(secs) > 1 else "§"
    r.citation = r.check_text = f"{sign} {', '.join(secs)}, Fla. Stat.{year}"
    return r


def build_annotated(a, data, engine):
    r = Result()
    if a.pages:
        what = a.pages.replace("-", "–")
    elif a.section and re.fullmatch(fl_check.SEC, a.section):
        what = f"§ {a.section}"
    else:
        raise BuildError("give --section (a statute section) or --pages (material other than a section, 9.800(g)(2))")
    year = a.year or BLANK
    if not a.year:
        r.blanks.append("the volume's year (9.800(g) gives one)")
    r.citation = f"{a.volume} Fla. Stat. Ann. {what} ({year})"
    r.check_text = f"{a.volume} Fla. Stat. Ann. {what} ({a.year or 2020})"
    return r


def build_const(a, data, engine):
    r = Result()
    us = a.us or bool(a.amendment)
    which = "U.S. Const." if us else "Fla. Const."
    if a.amendment:
        if a.article:
            raise BuildError("give an article or --amendment, not both")
        out = f"Amend. {roman(a.amendment)}" + (f", § {a.section}" if a.section else "")
    else:
        if not a.article:
            raise BuildError("give the article (V, or 5), or --amendment for the U.S. Constitution")
        out = f"Art. {roman(a.article)}" + (f", § {a.section}" if a.section else "") + (f", cl. {a.clause}" if a.clause else "")
    out += f", {which}"
    if a.year:
        if us:
            raise BuildError("--year is for a repealed, superseded, or amended Florida provision (9.800(e))")
        out += f" ({a.year})"
    r.citation = r.check_text = out
    return r


def build_admin(a, data, engine):
    r = Result()
    if not re.fullmatch(r"\d+[A-Z]{0,3}-\d+\.\d+[\w()]*", a.rule):
        raise BuildError(f"{a.rule!r} isn't a Florida Administrative Code rule number (like 62D-2.014)")
    r.citation = r.check_text = f"Fla. Admin. Code R. {a.rule}" + (f" ({a.year})" if a.year else "")
    return r


def build_law(a, data, engine):
    r = Result()
    ch = a.chapter.strip()
    if not re.fullmatch(r"\d{2,4}-\d+|\d{3,5}", ch):
        raise BuildError(f"{ch!r} isn't a Laws of Florida chapter (like 74-177, or 22000 before 1957)")
    sec = f", § {a.section}" if a.section else ""
    out = f"Ch. {ch}{sec}, Laws of Fla."
    check = out
    if "-" not in ch:                        # 9.800(i)(2): before 1957, chapters ran in one series; give the year
        if a.year:
            out += f" ({a.year})"
            check = out
        else:
            out += f" ({BLANK})"
            check += " (1943)"
            r.blanks.append("the year (9.800(i)(2): chapters before 1957 take the year)")
    elif a.year:
        r.notes.append("9.800(i)(1) gives chapters after 1956 no year (the chapter number carries it); --year left out.")
    r.citation, r.check_text = out, check
    return r


RULE_SET_ALIASES = {"civ": 1, "civil": 1, "svp": 2, "gen prac": 3, "jud admin": 3, "judicial administration": 3,
                    "crim": 4, "criminal": 4, "prob": 5, "probate": 5, "traf": 6, "traffic": 6, "sm cl": 7,
                    "small claims": 7, "juv": 8, "juvenile": 8, "app": 9, "appellate": 9, "med": 10, "mediators": 10,
                    "arb": 11, "arbitrators": 11, "fam": 12, "family": 12, "bar": 13, "jud conduct": 14,
                    "jqc": 18, "jury civ": 19, "jury cont": 20, "jury crim": 21, "sanctions": 22, "admissions": 23}


def find_rule_set(query, data):
    sets = data["rule_sets"]["sets"]
    q = query.strip().lower()
    if q.isdigit() and 1 <= int(q) <= len(sets):
        return sets[int(q) - 1]
    if q.rstrip(".") in RULE_SET_ALIASES:
        return sets[RULE_SET_ALIASES[q.rstrip(".")] - 1]
    exact = [s for s in sets if q in (s["abbr"].lower(), s["name"].lower(), *(v.lower() for v in s["variants"]))]
    if exact:
        return exact[0]
    words = q.replace(".", " ").split()
    hits = [s for s in sets if all(w in (s["name"] + " " + s["abbr"]).lower().replace(".", " ") for w in words)]
    if len(hits) == 1:
        return hits[0]
    shown = hits or sets
    raise BuildError(f"{'which' if hits else 'no'} rule set matches {query!r}"
                     + (": " if hits else "; the 23 sets: ") + "; ".join(f"{s['n']} {s['name']}" for s in shown)
                     + ". Give its number (1-23) or more of its name.")


def build_rule(a, data, engine):
    r = Result()
    s = find_rule_set(a.set, data)
    r.citation = r.check_text = f"{s['abbr']} {a.number}" + (f" ({a.year})" if a.year else "")
    r.notes.append(f"{s['name']}, 9.800(j)({s['n']}).")
    return r


def build_ago(a, data, engine):
    r = Result()
    m = re.fullmatch(r"\s*(?:AGO\s*)?(\d{2,4})-(\d{1,4})\s*", a.number, re.I)
    if not m:
        raise BuildError(f"{a.number!r} isn't an Attorney General opinion number (like 73-178 or 2005-12)")
    pre = m.group(1)
    year = int(pre) if len(pre) == 4 else (2000 + int(pre) if int(pre) <= 26 else 1900 + int(pre))
    r.citation = r.check_text = f"Op. Att'y Gen. Fla. {pre}-{m.group(2)} ({a.year or year})"
    return r


BUILDERS = {"case": build_case, "agency": build_agency, "statute": build_statute, "annotated": build_annotated,
            "const": build_const, "admin": build_admin, "law": build_law, "rule": build_rule, "ago": build_ago}


# ---------------------------------------------------------------- self-check and output

def build(a, engine=None):
    engine = engine or fl_check.Engine()
    data = engine.data
    r = BUILDERS[a.type](a, data, engine)
    as_of = dt.date.fromisoformat(a.as_of) if getattr(a, "as_of", None) else dt.date.today()
    report = fl_check.check(fl_check.Source(_period(r.check_text)), date=as_of, infer=False, fallback_today=False,
                            engine=engine)
    found = [f for f in report["findings"] if f["severity"] != "unrecognized"]
    bad = [f for f in found if f["severity"] == "error" or f["check"] in IMPOSSIBLE]
    if bad:
        raise BuildError("these parts can't all be right:\n" + "\n".join(
            f"  [{f['authority']}] {f['message']}" for f in bad))
    for f in found:
        r.notes.append(f"[{f['authority']}] {f['message']}")
    for f in report["findings"]:
        if f["severity"] == "unrecognized":
            r.notes.append(f"[{f['authority']}] {f['message']}")
    cs = [c for c in report["citations"] if c["kind"] not in ("case_short",) + fl_check.SHORT_KINDS]
    if cs:
        c = cs[0]
        r.authority = c["authority"]
        if c["kind"] in ("statute", "constitution", "rule", "admin_code", "session_law"):
            s = fl_check.spelled_out(c, c["text"], data)
            if s:
                r.sentence = s.replace("(1943)", f"({BLANK})") if BLANK in r.citation else s
    else:
        r.notes.append("The check engine didn't recognize the result as a citation; check its form by hand.")
    return r


def _period(text):
    """A citation standing alone ends with a period; one ending in an abbreviation ('Fla. Const.') has it."""
    return text if text.endswith(".") else text + "."


def render(r):
    out = [_period(r.citation)]
    if r.sentence:
        out.append(f"  in a sentence: {r.sentence}")
    if r.authority:
        out.append(f"  authority: {r.authority}")
    if r.abbreviated:
        out.append("  case-name words abbreviated (Indigo Book R11.3, Table T11): "
                   + ", ".join(f"{w} -> {ab}" for w, ab in r.abbreviated) + "; --no-abbreviate keeps them whole")
    for b in r.blanks:
        out.append(f"  fill in {BLANK}: {b}")
    for n in r.notes:
        out.append(f"  note: {n}")
    return "\n".join(out)


def as_json(r):
    return {"citation": _period(r.citation), "sentence_form": r.sentence, "authority": r.authority,
            "blanks": r.blanks, "notes": r.notes,
            "abbreviated": [{"word": w, "abbreviation": ab} for w, ab in r.abbreviated]}


def register(sub):
    """Add `build` and its types to fl_cite.py's command line."""
    b = sub.add_parser("build", help="build a citation from its parts (case, agency, statute, const, rule, ...)",
                       description="Build a citation in Rule 9.800's form. Each type takes --help.")
    types = b.add_subparsers(dest="type", required=True)

    def common(p):
        p.add_argument("--json", action="store_true")
        p.add_argument("--as-of", help="date the date-dependent checks use (YYYY-MM-DD); default today")
        return p

    p = common(types.add_parser("case", help="a court decision (9.800(a)-(c), (l)-(n))"))
    p.add_argument("name", help='the case name as captioned, e.g. "Fenelon v. State"')
    p.add_argument("--court", required=True, help="SC, 1D-6D, circuit:N, county:NAME, US, CA1-CA11, CADC, CAFED, N.D./M.D./S.D. Fla.")
    p.add_argument("--year", help="year decided (enough for a reporter cite)")
    p.add_argument("--date", help="exact date decided, YYYY-MM-DD (needed for Fla. L. Weekly and slip opinions)")
    p.add_argument("--cite", help="reporter cite: volume, reporter, first page ('594 So. 2d 292')")
    p.add_argument("--flw", help="Florida Law Weekly cite ('17 Fla. L. Weekly S42')")
    p.add_argument("--docket", help="case number, for a slip opinion ('SC2010-1544'; old forms are converted)")
    p.add_argument("--westlaw", help="Westlaw cite with a slip opinion ('2014 WL 7463592')")
    p.add_argument("--lexis", help="LEXIS cite with a slip opinion ('2010 Fla. LEXIS 62')")
    p.add_argument("--pin", help="pinpoint page ('293', '*3')")
    p.add_argument("--no-abbreviate", action="store_true", help="keep the case name's words whole")

    p = common(types.add_parser("agency", help="an agency final order or DOAH decision (9.800(d))"))
    p.add_argument("name", help="the case name, e.g. \"Dep't of Health v. Migicovsky\"")
    p.add_argument("--body", required=True, help="DOAH, or the agency as in its parenthetical ('Bd. of Med.')")
    p.add_argument("--docket", help="the agency or DOAH case number")
    p.add_argument("--date", required=True, help="date of the order, YYYY-MM-DD")
    p.add_argument("--order", help="'Recommended Order', 'Final Order No. DOH-12-2692-FOF-MQA', ...")
    p.add_argument("--no-abbreviate", action="store_true")

    p = common(types.add_parser("statute", help="Florida Statutes (9.800(f))"))
    p.add_argument("sections", nargs="+", help="section numbers: 48.031, or several")
    p.add_argument("--year", help="the edition's year")
    p.add_argument("--supp", help="a supplement's year (9.800(f)(2))")

    p = common(types.add_parser("annotated", help="Florida Statutes Annotated (9.800(g))"))
    p.add_argument("--volume", required=True)
    p.add_argument("--section")
    p.add_argument("--pages", help="for material other than a section: '69-70'")
    p.add_argument("--year")

    p = common(types.add_parser("const", help="Florida or U.S. Constitution (9.800(e), (o))"))
    p.add_argument("article", nargs="?", help="article: V or 5")
    p.add_argument("--section", help="'3(b)(3)'")
    p.add_argument("--clause")
    p.add_argument("--amendment", help="a U.S. Constitution amendment: V or 14")
    p.add_argument("--us", action="store_true", help="the U.S. Constitution (the default is Florida's)")
    p.add_argument("--year", help="year of a repealed, superseded, or amended Florida provision (9.800(e)(2))")

    p = common(types.add_parser("admin", help="Florida Administrative Code (9.800(h))"))
    p.add_argument("rule", help="'62D-2.014'")
    p.add_argument("--year", help="year of a repealed, superseded, or amended rule (9.800(h)(2))")

    p = common(types.add_parser("law", help="Laws of Florida (9.800(i))"))
    p.add_argument("chapter", help="'74-177', or '22000' before 1957")
    p.add_argument("--section")
    p.add_argument("--year", help="needed before 1957")

    p = common(types.add_parser("rule", help="a Florida rule set (9.800(j))"))
    p.add_argument("set", help="the set: its number (1-23), abbreviation, or words of its name ('civ', 'crim', 'app')")
    p.add_argument("number", help="'1.180', '4-1.10', '601.4'")
    p.add_argument("--year", help="year of a repealed, superseded, or amended rule")

    p = common(types.add_parser("ago", help="a Florida Attorney General opinion (9.800(k))"))
    p.add_argument("number", help="'73-178'")
    p.add_argument("--year", help="if it differs from the number's year")
    b.set_defaults(fn=cmd_build)


def cmd_build(args):
    try:
        r = build(args)
    except BuildError as e:
        sys.exit(f"can't build that citation: {e}")
    if args.json:
        print(json.dumps(as_json(r), indent=2, ensure_ascii=False))
    else:
        print(render(r))
