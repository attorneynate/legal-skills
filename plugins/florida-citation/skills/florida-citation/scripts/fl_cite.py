"""Florida citation forms under Fla. R. App. P. 9.800 (the Uniform Citation System).

Usage:
  python fl_cite.py rule [SUBDIVISION]        # text of Rule 9.800: rule f, rule "(j)(3)", rule 9.800(d)(4)(A)
  python fl_cite.py abbrev QUERY [--json]     # forms for courts, reporters, rule sets, counties, months
  python fl_cite.py casenum NUMBER [...]      # old case numbers to the four-digit form: SC09-839 -> SC2009-0839
  python fl_cite.py checks [--authority 9.800(f)] [--kind pattern]   # the check records
  python fl_cite.py check FILE|- [--json] [--date YYYY-MM-DD] [--citations]   # check a document
  python fl_cite.py check FILE --last-page N  # only pages 1 to N, leaving out exhibits after the document
  python fl_cite.py check FILE --cite-list    # each case once, citation only, for a batch citation tool
  python fl_cite.py check FILE --facts-template > facts.json   # the cases cited, for a case-law tool to confirm
  python fl_cite.py check FILE --mode opposing [--facts facts.json]   # review the other side's filing
  python fl_cite.py build TYPE ...            # a citation from its parts: case, agency, statute, annotated,
                                              # const, admin, law, rule, ago (each takes --help)

Standard library only. Data lives beside this script: data/florida.json (tables),
data/checks.json (check records), references/rule-9.800.md (the rule's text).
"""

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
DATA = SKILL / "data"
RULE_FILE = SKILL / "references" / "rule-9.800.md"


def load(name):
    try:
        return json.loads((DATA / name).read_text(encoding="utf-8"))
    except FileNotFoundError:
        sys.exit(f"missing {DATA / name}; the skill's data folder is incomplete")


def ordinal(n):
    """Ordinals in the rule's style: 1st, 2d, 3d, 4th, 11th, 12th, 13th, 21st, 22d."""
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}" + {1: "st", 2: "d", 3: "d"}.get(n % 10, "th")


def normalize(text):
    """Curly quotes to straight, any run of whitespace (including line and page breaks) to one space."""
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", text)


# ---------------------------------------------------------------- rule text

SUB_LETTERS = "abcdefghijklmnopq"


def rule_sections():
    """{'intro': text, 'a': (title, [paragraphs]), ..., 'notes': text} from references/rule-9.800.md."""
    text = RULE_FILE.read_text(encoding="utf-8")
    body = text.split("<!-- rule-text-start -->", 1)[1].split("<!-- rule-text-end -->", 1)[0]
    parts = re.split(r"^## ", body, flags=re.M)
    sections = {"intro": parts[0].strip()}
    for part in parts[1:]:
        head, _, rest = part.partition("\n")
        paras = [p.strip() for p in rest.strip().split("\n\n") if p.strip()]
        m = re.match(r"\(([a-q])\) (.*)", head.strip())
        if m:
            sections[m.group(1)] = (m.group(2), paras)
        elif head.strip() == "Committee Notes":
            sections["notes"] = "\n\n".join(paras)
    return sections


def parse_subdivision(spec):
    """'9.800(j)(3)', '(j)(3)', 'j3', 'j(3)', 'd4A' -> ['j', '3'] / ['d', '4', 'A']."""
    s = spec.strip().lower().replace(" ", "")
    s = re.sub(r"^(?:fla\.r\.app\.p\.)?9\.800", "", s)
    if s in ("", "all"):
        return []
    if s in ("intro", "introduction", "notes", "committeenotes"):
        return ["notes" if s.startswith(("notes", "committee")) else "intro"]
    tokens = re.findall(r"[a-z]+|\d+", s.replace("(", " ").replace(")", " "))
    out = []
    for i, t in enumerate(tokens):
        if i == 0:
            if len(t) == 1 and t in SUB_LETTERS:
                out.append(t)
            elif len(t) > 1 and t[0] in SUB_LETTERS and not re.fullmatch(r"[ivx]+", t):
                sys.exit(f"can't read {spec!r}; write it like (j)(3) or j3")
            else:
                sys.exit(f"Rule 9.800's subdivisions run (a) to (q); got {spec!r}")
        elif t.isdigit():
            out.append(t)
        elif len(out) == 2:
            out.append(t.upper())          # (d)(4)(A)
        else:
            out.append(t)                  # (d)(4)(A)(i)
    return out


def paragraph_label(p):
    m = re.match(r"\(([0-9]+|[A-Z]|[ivx]+)\)", p)
    return m.group(1) if m else None


def level(label):
    if label is None:
        return 0
    if label.isdigit():
        return 1
    if label.isupper():
        return 2
    return 3


def cmd_rule(args):
    sections = rule_sections()
    path = parse_subdivision(args.subdivision or "")
    header = ("Fla. R. App. P. 9.800{}, as amended effective September 1, 2026 "
              "(In re Amendments to Fla. Rules of Appellate Procedure, No. SC2025-0241 (Fla. June 11, 2026) (corrected opinion))")
    if not path:
        print(header.format("") + "\n")
        print("(intro) " + sections["intro"][:160] + "...")
        for letter in SUB_LETTERS:
            print(f"({letter}) {sections[letter][0]}")
        print("(notes) Committee Notes")
        print("\nShow one with, for example: rule f    rule (j)(3)    rule (d)(4)(A)")
        return
    if path[0] in ("intro", "notes"):
        print(header.format(" (introductory paragraph)" if path[0] == "intro" else ", Committee Notes") + "\n")
        print(sections[path[0]])
        return
    title, paras = sections[path[0]]
    cite = "(" + ")(".join(path) + ")"
    if len(path) == 1:
        print(header.format(cite) + "\n")
        print(f"({path[0]}) {title}\n")
        print("\n\n".join(paras))
        return
    # Walk down the labels: (4) then (A) then (i), each found after the previous one.
    start = 0
    for depth, want in enumerate(path[1:], start=1):
        for i in range(start, len(paras)):
            lab = paragraph_label(paras[i])
            if lab == want and level(lab) == depth:
                start = i
                break
            if lab is not None and level(lab) < depth and i > start:
                i = None
                break
        else:
            i = None
        if i is None:
            have = [paragraph_label(p) for p in paras if level(paragraph_label(p)) == depth]
            sys.exit(f"9.800({path[0]}) has no {cite}. Its paragraphs at that level: "
                     + ", ".join(f"({h})" for h in have if h))
    out = [paras[start]]
    for p in paras[start + 1:]:
        lab = paragraph_label(p)
        if lab is not None and level(lab) <= len(path) - 1:
            break
        out.append(p)
    print(header.format(cite) + "\n")
    print("\n\n".join(out))


# ---------------------------------------------------------------- case numbers

def convert_case_number(raw, data=None):
    """Return (new_form, note) or (None, reason). Accepts 'SC09-839', 'No. 1D01-2734', 'SC2025-708'."""
    data = data or load("florida.json")
    cn = data["case_numbers"]
    s = raw.strip().rstrip(".,;")
    s = re.sub(r"^Nos?\.\s*", "", s, flags=re.I)
    m = re.fullmatch(r"([A-Za-z]{2}|\d[A-Za-z])\s*(\d{2}|\d{4})-(\d+)", s)
    if not m:
        return None, "not a Florida appellate case number (expected forms like SC09-839, 1D01-2734, SC2025-0708)"
    prefix, year, number = m.group(1).upper(), m.group(2), m.group(3)
    if prefix not in cn["prefixes"]:
        if re.fullmatch(r"\dD", prefix):
            return None, f"there is no {ordinal(int(prefix[0]))} District Court of Appeal (Florida has six)"
        return None, f"{prefix} isn't a Florida appellate prefix ({', '.join(cn['prefixes'])})"
    if len(number) > 4:
        return None, f"case number {number} has more than four digits, so it can't take the four-digit form; check it against the docket"
    if len(year) == 2:
        yy = int(year)
        year = str((2000 if yy <= cn["two_digit_century_cutoff"] else 1900) + yy)
    if prefix == "6D" and int(year) < 2023:
        return None, f"the Sixth District began January 1, 2023, so 6D{year} can't exist"
    new = f"{prefix}{year}-{int(number):04d}"
    if new == s.upper():
        return new, "already in the four-digit form"
    return new, ""


def cmd_casenum(args):
    data = load("florida.json")
    bad = 0
    for raw in args.numbers:
        new, note = convert_case_number(raw, data)
        if new is None:
            bad += 1
            print(f"{raw}: CAN'T CONVERT: {note}")
        else:
            print(f"{raw} -> {new}" + (f"  ({note})" if note else ""))
    if bad:
        sys.exit(1)


# ---------------------------------------------------------------- abbreviations

def abbrev_entries(data):
    e = []
    add = lambda form, desc, auth, *also: e.append({"form": form, "for": desc, "authority": auth, "also": list(also)})
    for c in data["courts"]["florida_appellate"]:
        add(f"({c['paren']} year)", c["name"], c["rule"], c["id"], f"docket prefix {c['docket_prefix']}")
    for n in range(1, data["courts"]["circuit_count"] + 1):
        add(f"(Fla. {ordinal(n)} Cir. Ct. date)", f"Circuit Court, {ordinal(n)} Judicial Circuit", "9.800(c)(1)")
    for county in data["counties"]["names"]:
        add(f"({county} Cty. Ct. date)", f"{county} County Court", "9.800(c)(2)", f"{county} County")
    for c in data["courts"]["federal_courts_of_appeals"]:
        add(f"({c['paren']} year)", f"U.S. Court of Appeals, {c['paren'].replace(' Cir.', ' Circuit')}", "9.800(m)",
            *(["began " + c["began"]] if c.get("began") else []))
    for c in data["courts"]["florida_federal_districts"]:
        name = {"N": "Northern", "M": "Middle", "S": "Southern"}[c["paren"][0]]
        add(f"({c['paren']} year)", f"U.S. District Court, {name} District of Florida", "9.800(n)")
    for r in data["reporters"]["series"]:
        span = f"{r['first']}-{r['last'] or 'present'}"
        add(r["abbr"], f"{r['name']} ({span})", r["rule"])
    for r in data["reporters"]["bluebook_series"]:
        span = f"{r['first']}-{r['last'] or 'present'}"
        add(r["abbr"], f"{r['name']} ({span}); not a Rule 9.800 reporter, so the Bluebook system's form", r["rule"])
    for m in data["reporters"]["misspellings"] + data["reporters"]["bluebook_misspellings"]:
        add(m["right"], f"not {m['wrong']}", m["rule"], m["wrong"])
    for f in data["florida_law_weekly"]["editions"]:
        secs = "; ".join(f"{k} = {v}" for k, v in f["sections"].items())
        add(f["abbr"], f"Florida Law Weekly{f['abbr'][14:]} (volume = year - {f['offset']}, give or take a year"
            f"{'; ' + secs if secs else ''})", f["rule"])
    for s in data["rule_sets"]["sets"]:
        add(f"{s['abbr']} {s['example']}", s["name"], f"9.800(j)({s['n']})", *s["variants"], *s.get("former_names", []))
    for full, short in data["months"]["abbr"].items():
        add(short, full, "9.800 (date parentheticals)", full)
    fixed = [
        ("Art. V, § 3(b)(3), Fla. Const.", "Florida Constitution (spelled out in a sentence: article V, section 3(b)(3) of the Florida Constitution)", "9.800(e)"),
        ("§ 48.031, Fla. Stat. (2014)", "Florida Statutes (in a sentence: section 48.031, Florida Statutes (2014))", "9.800(f)"),
        ("7 Fla. Stat. Ann. § 95.11 (2017)", "Florida Statutes Annotated", "9.800(g)"),
        ("Fla. Admin. Code R. 62D-2.014", "Florida Administrative Code", "9.800(h)"),
        ("Ch. 74-177, § 5, Laws of Fla.", "Laws of Florida (before 1957: Ch. 22000, Laws of Fla. (1943))", "9.800(i)"),
        ("Op. Att'y Gen. Fla. 73-178 (1973)", "Florida Attorney General opinion", "9.800(k)"),
        ("(Fla. DOAH date) (Recommended Order)", "Division of Administrative Hearings", "9.800(d)(2)"),
        ("Art. IV, § 2, cl. 2, U.S. Const.", "U.S. Constitution, article", "9.800(o)(1)"),
        ("Amend. V, U.S. Const.", "U.S. Constitution, amendment", "9.800(o)(2)"),
    ]
    for form, desc, auth in fixed:
        add(form, desc, auth)
    return e


def cmd_abbrev(args):
    data = load("florida.json")
    q = normalize(args.query).lower().strip()
    if not q:
        sys.exit("give something to look up, like: abbrev appellate   abbrev 'Palm Beach'   abbrev So. 2d")
    scored = []
    for entry in abbrev_entries(data):
        hay = [entry["form"], entry["for"]] + entry["also"]
        best = 0
        for h in hay:
            h = h.lower()
            if h == q or h.strip("()") == q:
                best = max(best, 3)
            elif h.startswith(q) or re.search(r"\b" + re.escape(q), h):
                best = max(best, 2)
            elif q in h:
                best = max(best, 1)
        if best:
            scored.append((-best, entry))
    if not scored:
        sys.exit(f"nothing matches {args.query!r}. Try a court, county, reporter, rule set, or month.")
    scored.sort(key=lambda x: x[0])
    rows = [e for _, e in scored[: args.limit]]
    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return
    for e in rows:
        also = [a for a in e["also"] if a.lower() != e["for"].lower()]
        print(f"{e['form']}\n    {e['for']}  [{e['authority']}]" + (f"\n    variants and older forms: {', '.join(also)}" if also else ""))
    if len(scored) > args.limit:
        print(f"... {len(scored) - args.limit} more; narrow the query or raise --limit")


# ---------------------------------------------------------------- check records

def literal(s):
    """A literal string as a re.sub template."""
    return s.replace("\\", "\\\\")


# A court's date parenthetical: "(Fla. ", "(Fla. 1st DCA ", "(Miami-Dade Cty. Ct. ", "(S.D. Fla. ", "(11th Cir. ", "(U.S. ".
COURT_PAREN = r"(\((?:[^()]{0,60}?(?:Fla\.|DCA|Cir\.|Ct\.|DOAH|Comm'n|U\.S\.)) )"


def table_patterns(record, data):
    """Expand a 'table' record into (regex, fix template, authority) triples."""
    out = []
    if record["table"] in ("reporters.misspellings", "reporters.bluebook_misspellings"):
        for m in data["reporters"][record["table"].split(".")[1]]:
            out.append((r"(?<=\d )" + re.escape(m["wrong"]) + r"(?= \d| at \d)", literal(m["right"]), m["rule"]))
    elif record["table"] == "rule_sets.variants":
        for s in data["rule_sets"]["sets"]:
            for v in s["variants"]:
                # Not when the case's own citation follows the number: "In re Amends to Fla. R. Civ. Pro.
                # 1.510, 309 So. 3d 192" is a case name. A rule citation never runs into a volume and reporter.
                out.append((r"(?<![\w.])" + re.escape(v) + r"(?= ?\d)(?! ?\d[\w.()]*, \d{1,4} [A-Z])",
                            literal(s["abbr"]), f"9.800(j)({s['n']})"))
    elif record["table"] == "months":
        # Only in a court's date parenthetical; other sources (staff analyses, recordings) are outside 9.800.
        months = [(full, short) for full, short in data["months"]["abbr"].items() if full != short] + [("Sep.", "Sept.")]
        for full, short in months:
            out.append((COURT_PAREN + re.escape(full) + r"(?= \d{1,2}, \d{4}\))", r"\1" + literal(short),
                        record["authority"]))
    else:
        sys.exit(f"check {record['id']}: unknown table {record['table']}")
    return out


def reporter_forms(data):
    """{reporter as written: its standard form} for every reporter the checker reads: Rule 9.800's series,
    the ones 9.800(p) sends to the Bluebook system, and the misspellings of both."""
    rep = data["reporters"]
    forms = {s["abbr"]: s["abbr"] for s in rep["series"] + rep["bluebook_series"]}
    for m in rep["misspellings"] + rep["bluebook_misspellings"]:
        forms[m["wrong"]] = m["right"]
    for f in ("L. Ed. 2d", "L. Ed.", "L.Ed.2d", "L.Ed. 2d", "L.Ed."):
        forms[f] = "L. Ed. 2d" if "2d" in f else "L. Ed."
    for f in ("F.C.S.R.", "F.P.E.R."):
        forms[f] = f
    return forms


def reporter_alternation(data):
    """The reporter forms as a regex alternation, longest first."""
    return "|".join(re.escape(f) for f in sorted(reporter_forms(data), key=len, reverse=True))


def compiled_checks(checks=None, data=None):
    """[(record, compiled regex, fix template, authority)] for every pattern and table record. A pattern's
    {reporter} stands for any reporter form the checker reads."""
    checks = checks or load("checks.json")["checks"]
    data = data or load("florida.json")
    reporters = reporter_alternation(data)
    out = []
    for r in checks:
        if r["kind"] == "pattern":
            out.append((r, re.compile(r["pattern"].replace("{reporter}", reporters)), r["fix"], r["authority"]))
        elif r["kind"] == "table":
            for rx, fix, auth in table_patterns(r, data):
                out.append((r, re.compile(rx), fix, auth))
    return out


MAX_QUOTE = 1500  # a "quotation" longer than this is more likely a stray quote mark than a real quote


def quoted_spans(norm):
    """(start, end) of each double-quoted passage in normalized text. Citations inside a quotation
    are the quoted author's, not the writer's, so the checks skip them."""
    marks = [m.start() for m in re.finditer('"', norm)]
    return [(a, b) for a, b in zip(marks[::2], marks[1::2]) if b - a <= MAX_QUOTE]


def scan(text, compiled=None, include_quoted=False):
    """Run the pattern and table checks over text. Returns findings with offsets into the normalized text."""
    compiled = compiled or compiled_checks()
    norm = normalize(text)
    quotes = [] if include_quoted else quoted_spans(norm)
    findings = []
    for record, rx, fix, auth in compiled:
        for m in rx.finditer(norm):
            if any(a < m.start() < b for a, b in quotes):
                continue
            findings.append({
                "check": record["id"], "authority": auth, "severity": record["severity"],
                "start": m.start(), "end": m.end(), "found": m.group(0),
                "fix": m.expand(fix) if fix is not None else None,
                "message": record["message"],
            })
    findings.sort(key=lambda f: (f["start"], f["check"]))
    return findings


def cmd_checks(args):
    checks = load("checks.json")["checks"]
    shown = 0
    for r in checks:
        if args.kind and r["kind"] != args.kind:
            continue
        if args.authority and args.authority.replace(" ", "") not in r["authority"].replace(" ", ""):
            continue
        shown += 1
        print(f"{r['id']:<28} {r['severity']:<6} {r['kind']:<8} {r['authority']}\n    {r['message']}")
    if not shown:
        sys.exit("no check matches those filters")


def cmd_check(args):
    import fl_check
    import fl_review
    date = None
    if args.date:
        try:
            date = dt.date.fromisoformat(args.date)
        except ValueError:
            sys.exit(f"--date takes YYYY-MM-DD; got {args.date!r}")
    engine = fl_check.Engine()
    if args.facts and args.facts_template:
        sys.exit("--facts-template writes a new facts file; --facts reads a filled-in one. Use one at a time.")
    facts = fl_review.facts_or_exit(args.facts, engine.data) if args.facts else None
    source = fl_check.read_source(args.file)
    if args.last_page is not None:
        source = fl_check.first_pages(source, args.last_page)
    report = fl_check.check(source, date=date, engine=engine)
    if args.facts_template:
        print(json.dumps(fl_review.facts_template(report), indent=2, ensure_ascii=False))
        return
    if args.cite_list:
        print(fl_review.cite_list(report))
        return
    if facts is not None:
        fl_review.compare_facts(report, facts[0], facts[1], engine.data)
    if args.mode == "opposing":
        fl_review.opposing(report)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    elif args.mode == "opposing":
        print(fl_review.render_opposing(report, args.facts))
    else:
        print(fl_review.render_facts(report, args.facts) + fl_check.render_text(report, show_citations=args.citations))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    r = sub.add_parser("rule", help="print Rule 9.800 or one subdivision")
    r.add_argument("subdivision", nargs="?")
    r.set_defaults(fn=cmd_rule)
    a = sub.add_parser("abbrev", help="look up a form")
    a.add_argument("query")
    a.add_argument("--json", action="store_true")
    a.add_argument("--limit", type=int, default=12)
    a.set_defaults(fn=cmd_abbrev)
    c = sub.add_parser("casenum", help="convert case numbers to the four-digit form")
    c.add_argument("numbers", nargs="+")
    c.set_defaults(fn=cmd_casenum)
    k = sub.add_parser("checks", help="list the check records")
    k.add_argument("--authority")
    k.add_argument("--kind", choices=["pattern", "table", "logic", "none"])
    k.set_defaults(fn=cmd_checks)
    d = sub.add_parser("check", help="check the citations in a document (.txt, .md, .docx, .pdf, or - for standard input)")
    d.add_argument("file", help="a .txt, .md, .docx, or .pdf file (a PDF needs pdftotext), or - to read text from "
                                "standard input (form feeds are page breaks)")
    d.add_argument("--json", action="store_true", help="findings, citations, and quotations as JSON")
    d.add_argument("--date", help="the document's date (YYYY-MM-DD); otherwise read from the document, else today")
    d.add_argument("--citations", action="store_true", help="also list every citation found, with its tier")
    d.add_argument("--mode", choices=["own", "opposing"], default="own",
                   help="own (default): every form finding, for your own draft. opposing: for the other side's "
                        "filing, ordered by significance: facts, pinpoints, quotations, then form summarized")
    d.add_argument("--facts-template", action="store_true",
                   help="write a facts file (JSON) with one entry per case cited, for a case-law tool's findings")
    d.add_argument("--facts", metavar="FACTS.json",
                   help="compare each case's court, year, name, and pages with these confirmed facts")
    d.add_argument("--cite-list", action="store_true",
                   help="print each case once, as a citation alone, one per line: for a citation tool that "
                        "checks a whole list in one request (nothing else from the document is printed)")
    d.add_argument("--last-page", type=int, metavar="N",
                   help="check only pages 1 to N, leaving out exhibits or an appendix after the document")
    d.set_defaults(fn=cmd_check)
    import fl_build
    fl_build.register(sub)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    args.fn(args)


if __name__ == "__main__":
    main()
