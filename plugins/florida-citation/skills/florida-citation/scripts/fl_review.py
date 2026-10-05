"""Reviewing a filing for substance, behind `fl_cite.py check`: the facts loop and opposing mode.

  python fl_cite.py check brief.pdf --facts-template > facts.json   # one entry per case cited
  (fill in what a case-law tool finds for each case)
  python fl_cite.py check brief.pdf --mode opposing --facts facts.json

The script never decides whether a case exists or says what it's cited for. It lists each case's
claimed facts, compares them with the facts an agent confirmed with its own case-law tools, does the
arithmetic on pinpoint ranges, and orders the findings by significance. Every finding is something to
confirm, never an accusation. Standard library only.
"""

import json
import re
import sys
from pathlib import Path

import fl_build
import fl_check

FIELDS = ("found", "case_name", "court", "year", "volume", "first_page", "last_page", "source", "note")
ABOUT = ("Fill in one entry per case with what a case-law research tool finds for that cite: found (true or "
         "false), case_name, court (SC, 1D to 6D, CA11, US, S.D. Fla., another state's court by its citation "
         "abbreviation such as Del. Ch., or the court's name), year, first_page and last_page of the opinion in "
         "the reporter cited, volume only if it differs, source (the tool or "
         "database), and note. Leave found null and source empty for a case not looked up; for a case looked up "
         "but in none of the databases, leave found null, name the databases in source, and say what was tried in "
         "note. 'claimed' is what the document says and is ignored when read back. "
         "Then: fl_cite.py check FILE --facts THIS_FILE")

# Form findings that say a citation's facts can't all be right, read from the script's own tables.
SUBSTANCE_CHECKS = {"a-series-year", "b-court-before-it-existed", "flw-volume-year", "flw-section-court",
                    "docket-court-mismatch", "short-volume-mismatch", "j-rule-set-number"}
PINPOINT_CHECKS = {"pin-before-first-page"}

ORDINAL_WORDS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
                 "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11}
NAME_STOP = {"v", "vs", "in", "re", "ex", "rel", "parte", "matter", "interest", "estate", "the", "of", "a", "an",
             "and", "for", "on", "to", "at", "by", "state", "florida", "fla", "united", "states", "america",
             "people", "commonwealth", "inc", "co", "corp", "llc", "ltd", "company", "corporation", "incorporated",
             "na", "pa", "lp", "llp", "pllc", "et", "al", "city", "county", "cnty", "cty", "town", "village", "dep't",
             "department", "dept", "bd", "board", "sch", "school", "dist", "district", "comm'n", "commission",
             "div", "division", "sec'y", "secretary", "corr", "fla.", "doe"}


class FactsError(Exception):
    pass


# ---------------------------------------------------------------- the cases a document cites

def _key(cite):
    """A cite as a comparable key: '594 So.2d 292' and '594 So. 2d 292' are the same."""
    return re.sub(r"[\s.]", "", (cite or "")).lower()


def _primary_pins(c):
    """The pinpoints that go with a full citation's own cite (not a parallel cite's)."""
    for r in c["reporters"]:
        if f"{r['volume']} {r['canonical']} {r['page']}" == c.get("cite"):
            return list(r.get("pins") or [])
    for part in (c.get("flw"), c.get("online")):
        if part:
            return list(part.get("pins") or [])
    return list(c["pins"])


def _series(cite):
    """('594', 'So. 2d', 292) for a reporter cite, else None."""
    m = re.fullmatch(r"(\d+) (.+) (\d+)", cite or "")
    return (m.group(1), m.group(2), int(m.group(3))) if m and not re.search(r"WL|LEXIS|Weekly", cite) else None


def case_entries(report):
    """One entry per distinct case the document cites (full citations, with the short forms, supras,
    and Ids that refer to them), in order of first citation."""
    cites = report["citations"]
    entries, order = {}, []
    for c in cites:
        if c["kind"] != "case" or c["in_quote"] or c.get("toa") or not c.get("cite"):
            continue
        k = _key(c["cite"])
        if k not in entries:
            entries[k] = {"cite": c["cite"], "full": [], "mentions": []}
            order.append(k)
        entries[k]["full"].append(c)
        entries[k]["mentions"].append({"citation": c, "pins": _primary_pins(c), "form": "full"})
    for c in cites:
        if c["kind"] not in ("case_short", "id", "supra") or c["in_quote"] or c.get("toa"):
            continue
        if c.get("refers_to") is None:
            continue
        full = cites[c["refers_to"]]
        e = entries.get(_key(full.get("cite")))
        if e is None:
            continue
        pin = c.get("pin")
        if c["kind"] == "id":
            pin = re.sub(r"^at ", "", pin) if pin and c.get("pin_kind") == "page" else None
        series = _series(e["cite"])
        if c["kind"] == "case_short" and series and c["reporters"]:
            r = c["reporters"][0]
            if (r["volume"], r["canonical"]) != series[:2]:
                pin = None                     # a parallel cite's pinpoint; facts are for the main one
        if c["kind"] == "id" and isinstance(c.get("antecedent"), int):
            ant = cites[c["antecedent"]]
            if ant["kind"] == "case_short" and ant["reporters"] and series \
                    and (ant["reporters"][0]["volume"], ant["reporters"][0]["canonical"]) != series[:2]:
                pin = None
        e["mentions"].append({"citation": c, "pins": [pin] if pin else [], "form": c["kind"]})
    for k in order:
        entries[k]["mentions"].sort(key=lambda m: m["citation"]["location"]["start"])
    return [entries[k] for k in order]


def facts_template(report):
    out = {"about": ABOUT, "document": report["input"], "cases": []}
    for e in case_entries(report):
        first = e["full"][0]
        paren = first.get("paren") or {}
        pins = []
        for m in e["mentions"]:
            for p in m["pins"]:
                if p not in pins:
                    pins.append(p)
        where = []
        for m in e["mentions"]:
            w = fl_check._where(m["citation"]["location"])
            if w not in where:
                where.append(w)
        claimed = {"case_name": first.get("case_name"), "court": paren.get("court_text") or None,
                   "year": paren.get("year"), "pinpoints": pins, "cited_at": where[:12]}
        if len(where) > 12:
            claimed["cited_at"].append(f"and {len(where) - 12} more")
        entry = {"cite": e["cite"], "claimed": claimed}
        entry.update({f: None for f in FIELDS})
        out["cases"].append(entry)
    return out


# ---------------------------------------------------------------- reading facts.json

def _int(v, field, label):
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        raise FactsError(f"{label}: {field} must be a number; got {v!r}")
    if isinstance(v, int):
        return v
    if isinstance(v, str) and re.fullmatch(r"\s*\d+\s*", v):
        return int(v)
    if field == "year" and isinstance(v, str) and re.match(r"\s*(\d{4})-\d\d-\d\d", v):
        return int(v.strip()[:4])
    raise FactsError(f"{label}: {field} must be a number; got {v!r}")


def found_court(spec, data):
    """A court as a case-law tool names it -> the court ids classify_court uses, or None if unreadable."""
    s = re.sub(r"\s+", " ", spec or "").strip()
    if not s:
        return None
    try:
        return fl_build.court(s, data)["id"]
    except fl_build.BuildError:
        pass
    c = fl_check.classify_court(s.strip("()"))
    if c and c["id"] not in ("other", "DCA?"):
        return c["id"]
    low = s.lower()
    if re.search(r"supreme court of (?:the state of )?florida|florida supreme court", low):
        return "SC"
    if re.search(r"supreme court of the united states|u\.? ?s\.? supreme court", low):
        return "USSC"
    if "district court of appeal" in low:
        m = re.search(r"\b(first|second|third|fourth|fifth|sixth|[1-6](?:st|nd|d|rd|th))\b", low)
        if m:
            n = ORDINAL_WORDS.get(m.group(1)) or int(m.group(1)[0])
            return f"{n}D"
        return "DCA"
    m = re.search(r"court of appeals for the (\w+) circuit", low)
    if m:
        if m.group(1) in ORDINAL_WORDS:
            return f"CA{ORDINAL_WORDS[m.group(1)]}"
        return {"district": "CADC", "federal": "CAFED"}.get(m.group(1))
    m = re.search(r"(northern|middle|southern) district of florida|\b([nms])\.\s?d\.\s?fl(?:a\b|orida)", low)
    if m:
        return f"{(m.group(1) or m.group(2))[0].upper()}.D. Fla."
    if (re.search(r"\bdistrict court\b", low) and "united states" in low) or re.match(r"[nsewmc]\.d\. ", low):
        return "district"
    return state_court(s, data)


def state_court(text, data):
    """Another state's court -> 'ST:Del. Ch.' from its citation abbreviation ('Del. Ch.', 'Conn. App. Ct.'),
    or 'STATE:Del.' from a full name that names the state ('Court of Chancery of Delaware'), or None."""
    s = re.sub(r"\s+", " ", text or "").strip(" ()")
    names = data.get("states", {}).get("names", {})
    for abbr in sorted(names, key=len, reverse=True):
        if s == abbr or s.startswith(abbr + " "):
            rest = s[len(abbr):].strip()
            if not rest or (re.fullmatch(r"[A-Z][\w.']*(?: [A-Z&][\w.']*)*", rest) and "Cir." not in rest):
                return "ST:" + s
    low = s.lower()
    for abbr, name in sorted(names.items(), key=lambda kv: len(kv[1]), reverse=True):
        if re.search(r"\b" + re.escape(name.lower()) + r"\b", low) and not re.search(r"\bdistrict of\b|\bcircuit\b", low):
            return "STATE:" + abbr
    return None


DCA_IDS = {"1D", "2D", "3D", "4D", "5D", "6D", "DCA"}
FEDERAL_DISTRICTS = {"N.D. Fla.", "M.D. Fla.", "S.D. Fla.", "district"}


def courts_agree(claimed, found):
    """True, False, or None when the two can't be compared (an unreadable or other court)."""
    if claimed in (None, "other", "DCA?") or found is None:
        return None
    if claimed.startswith("STATE:") or found.startswith("STATE:"):     # a full name: same state is all it shows
        state = lambda c: c.split(":", 1)[1].split(" ")[0] if c.startswith(("ST:", "STATE:")) else None
        return state(claimed) == state(found) if state(claimed) and state(found) else False
    if claimed == "DCA" or found == "DCA":
        return claimed in DCA_IDS and found in DCA_IDS
    if claimed == "district" or found == "district":
        return claimed in FEDERAL_DISTRICTS and found in FEDERAL_DISTRICTS
    return claimed == found


def load_facts(path, data):
    """Read facts.json: a list of entries keyed by 'cite', or an object with a 'cases' list (what
    --facts-template writes). Returns ({key: entry}, problems). Bad files raise FactsError."""
    p = Path(path)
    if not p.is_file():
        raise FactsError(f"no such facts file: {path}")
    try:
        raw = json.loads(fl_check.decode(p.read_bytes()))
    except ValueError as e:
        raise FactsError(f"{path} isn't valid JSON: {e}")
    items = raw.get("cases") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise FactsError(f"{path} must be a list of entries, or an object with a 'cases' list "
                         "(as --facts-template writes)")
    facts, problems = {}, []
    for n, item in enumerate(items, 1):
        label = f"entry {n}"
        if not isinstance(item, dict):
            problems.append(f"{label}: not an object; skipped")
            continue
        cite = item.get("cite")
        if not isinstance(cite, str) or not cite.strip():
            problems.append(f"{label}: no 'cite'; skipped")
            continue
        label = f"entry {n} ({cite})"
        unknown = sorted(set(item) - set(FIELDS) - {"cite", "claimed"})
        if unknown:
            problems.append(f"{label}: ignored unknown field{'s' if len(unknown) > 1 else ''} {', '.join(unknown)}")
        try:
            found = item.get("found")
            if found not in (True, False, None):
                raise FactsError(f"{label}: found must be true, false, or null; got {found!r}")
            e = {"cite": cite.strip(), "found": found, "label": label,
                 "case_name": item.get("case_name") or None, "source": item.get("source") or None,
                 "note": item.get("note") or None}
            for f in ("year", "volume", "first_page", "last_page"):
                e[f] = _int(item.get(f), f, label)
            for f in ("case_name", "source", "note"):
                if e[f] is not None and not isinstance(e[f], str):
                    raise FactsError(f"{label}: {f} must be text; got {e[f]!r}")
        except FactsError as err:
            problems.append(f"{err}; entry skipped")
            continue
        court = item.get("court")
        e["court_text"] = court if isinstance(court, str) and court.strip() else None
        e["court"] = found_court(court, data) if e["court_text"] else None
        if e["court_text"] and e["court"] is None:
            problems.append(f"{label}: can't read the court {court!r}, so it isn't compared (use SC, 1D to 6D, "
                            "CA1 to CA11, US, a federal district such as S.D. Fla., another state's court by its "
                            "citation abbreviation (Del. Ch.) or a name that includes the state, or a Florida or "
                            "federal court's full name)")
        if e["first_page"] and e["last_page"] and e["last_page"] < e["first_page"]:
            problems.append(f"{label}: last_page {e['last_page']} comes before first_page {e['first_page']}; "
                            "the page range isn't used")
            e["last_page"] = None
        k = _key(cite)
        if k in facts:
            problems.append(f"{label}: the same cite as {facts[k]['label']}; the first one is used")
            continue
        facts[k] = e
    return facts, problems


# ---------------------------------------------------------------- comparing

def pin_range(pin):
    """'946-47' -> (946, 947); '52 n.6' -> (52, 52); star pages and page letters -> None."""
    m = re.match(r"(\d+)(?:\s*[-–—]\s*(\d+))?(?![\d*A-Za-z])", (pin or "").strip())
    if not m:
        return None
    lo = int(m.group(1))
    if not m.group(2):
        return lo, lo
    hi_s = m.group(2)
    hi = int(m.group(1)[:-len(hi_s)] + hi_s) if len(hi_s) < len(m.group(1)) else int(hi_s)
    return lo, max(lo, hi)


def _readable_range(r, first):
    """A pinpoint range that makes sense for a case starting at `first`, or None. A dash the PDF's font
    dropped runs two pages together ('886887' for 886-887); split those back apart."""
    lo, hi = r
    if lo < first * 5 or len(str(lo)) <= len(str(first)) + 1:
        return r
    s = str(lo)
    for cut in range(len(str(first)), len(s)):
        a, b = int(s[:cut]), s[cut:]
        b = int(s[:cut][:-len(b)] + b) if len(b) < cut else int(b)
        if a >= first and 0 <= b - a < 100:
            return a, b
    return None


def _name_words(name, data):
    abbr, _ = fl_build.abbreviate_name(name, data)
    # Hyphens dropped: a word split at a line end ("Col-lins") still matches the database's "Collins".
    words = re.findall(r"[a-z][a-z'’\-]*", abbr.lower())
    words = [w.strip("'’-").replace("-", "") for w in words]
    return {w for w in words if w not in NAME_STOP and len(w) >= 3}


def names_agree(claimed, found, data):
    """Do the names share a distinctive party word? None when either has none to compare."""
    if not claimed or not found:
        return None
    a, b = _name_words(claimed, data), _name_words(found, data)
    if not a or not b:
        return None
    return bool(a & b)


def compare_facts(report, facts, problems, data):
    """Claimed against confirmed facts. Adds report['facts']."""
    entries = case_entries(report)
    by_key = {_key(e["cite"]): e for e in entries}
    findings, unconfirmed_upper, missing = [], [], []
    counts = {"cases": len(entries), "confirmed": 0, "not_found": 0, "not_in_databases": 0, "not_looked_up": 0}
    for k, f in facts.items():
        if k not in by_key:
            problems.append(f"{f['label']}: no case in the document is cited as {f['cite']}")
    for e in entries:
        f = facts.get(_key(e["cite"]))
        first = e["full"][0]
        if f is None or (f["found"] is None and not f["source"]):
            counts["not_looked_up"] += 1
            continue
        if f["found"] is None:                 # looked up (it names its sources) but in none of them
            counts["not_in_databases"] += 1
            missing.append({"cite": e["cite"], "citation": first["index"], "location": first["location"],
                            "text": first["text"], "source": f["source"], "note": f["note"]})
            continue
        src = f" ({f['source']})" if f["source"] else ""

        def add(kind, c, claimed, found, message):
            findings.append({"kind": kind, "cite": e["cite"], "citation": c["index"], "location": c["location"],
                             "text": c["text"], "claimed": claimed, "found": found, "source": f["source"],
                             "note": f["note"], "message": message})

        if f["found"] is False:
            counts["not_found"] += 1
            add("not_found", first, e["cite"], None,
                f"Not found{src}. Confirm it by hand: it may be miscited, unreported, or under another cite.")
            continue
        counts["confirmed"] += 1
        series = _series(e["cite"])
        wrong_cite = False
        if series and f["volume"] is not None and str(f["volume"]) != series[0]:
            add("volume", first, series[0], f["volume"],
                f"The document gives volume {series[0]}; found in volume {f['volume']}{src}.")
            wrong_cite = True
        if series and f["first_page"] is not None and f["first_page"] != series[2]:
            add("first_page", first, series[2], f["first_page"],
                f"The document gives first page {series[2]}; the case begins at page {f['first_page']}{src}.")
            wrong_cite = True
        for c in e["full"]:
            p = c.get("paren") or {}
            claimed_court = (p.get("court") or {}).get("id")
            if claimed_court == "other":
                claimed_court = state_court(p.get("court_text"), data) or "other"
            agree = courts_agree(claimed_court, f["court"])
            if agree is False:
                add("court", c, p.get("court_text"), f["court_text"],
                    f"The document says {p.get('court_text')}; found {f['court_text']}{src}.")
            if p.get("year") and f["year"] and p["year"] != f["year"]:
                add("year", c, p["year"], f["year"], f"The document says {p['year']}; found {f['year']}{src}.")
            if names_agree(c.get("case_name"), f["case_name"], data) is False:
                add("case_name", c, c.get("case_name"), f["case_name"],
                    f"The document names {c.get('case_name')}; the case at this cite is {f['case_name']}{src}.")
        if not series or wrong_cite:
            continue                           # pinpoints mean nothing against the wrong case
        lo_page = f["first_page"] or series[2]
        for m in e["mentions"]:
            for pin in m["pins"]:
                r = pin_range(pin)
                r = _readable_range(r, lo_page) if r else None
                if r is None:
                    continue
                c = m["citation"]
                if r[0] < lo_page and f["first_page"] is not None:
                    add("pin_below", c, pin, f"{f['first_page']}-{f['last_page'] or '?'}",
                        f"Pinpoint {pin} comes before the case's first page, {f['first_page']}{src}.")
                elif f["last_page"] is not None and r[1] > f["last_page"]:
                    add("pin_above", c, pin, f"{f['first_page'] or series[2]}-{f['last_page']}",
                        f"Pinpoint {pin} is past the case's last page, {f['last_page']}{src}.")
                elif f["last_page"] is None:
                    unconfirmed_upper.append({"cite": e["cite"], "pin": pin, "citation": c["index"],
                                              "location": c["location"]})
    findings.sort(key=lambda x: x["location"]["start"])
    report["facts"] = {"counts": counts, "findings": findings, "upper_bound_unconfirmed": unconfirmed_upper,
                       "not_in_databases": missing, "problems": problems}
    return report


# ---------------------------------------------------------------- opposing mode

FACT_KINDS = ("not_found", "volume", "first_page", "court", "year", "case_name")
PIN_KINDS = ("pin_below", "pin_above")


def opposing(report):
    """The findings ordered by significance: facts that don't match, pinpoints out of range,
    quotations to verify, then form, summarized. Adds report['opposing']."""
    facts = report.get("facts") or {}
    ff = facts.get("findings", [])
    form = [f for f in report["findings"] if f["severity"] != "unrecognized"]

    def item(f, basis):
        return {"where": fl_check._where(f["location"]), "location": f["location"], "text": f.get("text", f.get("found")),
                "message": f["message"], "basis": basis, "kind": f.get("kind") or f.get("check"),
                "citation": f.get("citation")}

    section1 = [item(f, "confirmed facts") for f in ff if f["kind"] in FACT_KINDS]
    section1 += [item(f, f"the script's tables [{f['authority']}]") for f in form if f["check"] in SUBSTANCE_CHECKS]
    section2 = [item(f, "confirmed facts") for f in ff if f["kind"] in PIN_KINDS]
    confirmed_at = {(x["citation"], x["location"]["start"]) for x in section2}
    section2 += [item(f, f"the case's first page as cited [{f['authority']}]") for f in form
                 if f["check"] in PINPOINT_CHECKS and (f["citation"], f["location"]["start"]) not in confirmed_at]
    section2.sort(key=lambda x: x["location"]["start"])
    cites = report["citations"]
    quotes = []
    for q in report.get("quotations", []):
        c = cites[q["citation"]] if q["citation"] is not None else None
        full = cites[q["refers_to"]] if q.get("refers_to") is not None else None
        quotes.append({"where": fl_check._where(q["location"]), "location": q["location"], "text": q["text"],
                       "length": q["length"], "citation": q["citation"], "cited_as": c["text"] if c else None,
                       "source": full["text"] if full else None, "pin": q["pin"], "no_pin": q.get("no_pin", False),
                       "note": q["note"], "attributed_by": q["attributed_by"]})
    attributed = [q for q in quotes if q["citation"] is not None]
    unattributed = [q for q in quotes if q["citation"] is None]
    groups = {}
    for f in form:
        if f["check"] in SUBSTANCE_CHECKS | PINPOINT_CHECKS:
            continue
        # One group per check and authority: So.2d under 9.800(a)(1) apart from S.Ct. under 9.800(l)(2).
        g = groups.setdefault((f["check"], f["authority"]), {"check": f["check"], "severity": f["severity"], "authority": f["authority"],
                                           "message": f["message"].split(". ")[0].rstrip(".") + ".",
                                           "count": 0, "pages": []})
        locs = f.get("occurrences") or [f["location"]]
        g["count"] += f.get("count", 1) if f["check"] != "f-year-missing" else 1
        for loc in locs:
            w = fl_check._where(loc)
            if w not in g["pages"]:
                g["pages"].append(w)
    form_groups = sorted(groups.values(), key=lambda g: (fl_check.SEVERITIES.index(g["severity"]), -g["count"]))
    unrec = {}
    for f in report["findings"]:
        if f["severity"] == "unrecognized":
            unrec[f["tier"]] = unrec.get(f["tier"], 0) + 1
    report["opposing"] = {"facts_confirmed": bool(facts), "facts": section1, "pinpoints": section2,
                          "quotations": attributed, "unattributed_quotations": unattributed,
                          "form": form_groups, "unrecognized": unrec}
    return report


def _clip(s, n):
    s = s or ""
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


def render_opposing(report, facts_path=None):
    o = report["opposing"]
    out = [f"fl_cite check: {report['input']}  (opposing mode; Rule 9.800 as of {report['rule_as_of']})"]
    s = report["summary"]
    bits = []
    if report["doc_date"]:
        bits.append(f"document date {report['doc_date']} ({report['doc_date_source']})")
    if report["pages"]:
        bits.append(f"{report['pages']} pages")
    bits.append(f"{s['citations']} citations")
    out.append("; ".join(bits))
    out.append("Everything below is something to confirm. A mismatch can be a typo, the wrong case, or a case "
               "that can't be found; report it that way.")
    facts = report.get("facts")
    if facts:
        n = facts["counts"]
        out.append(f"Facts from {facts_path or 'the facts file'}: {_facts_counts(n)}.")

    out.append("")
    out.append("1. FACTS THAT DON'T MATCH")
    if not facts:
        out.append("   Case facts not confirmed yet. To confirm them: run check FILE --facts-template > facts.json,")
        out.append("   look up each case with a case-law tool and fill in its entry, then rerun with --facts facts.json.")
    if not o["facts"]:
        out.append("   none" + (" found in the script's tables" if not facts else ""))
    for it in o["facts"]:
        out.append(f"   {it['where']:<20} {_clip(it['text'], 110)}")
        out.append(f"   {'':<20} {it['message']}  (from {it['basis']})")
    out += _not_in_databases(facts, "   ")

    out.append("")
    out.append("2. PINPOINTS OUT OF RANGE")
    if not o["pinpoints"]:
        out.append("   none")
    for it in o["pinpoints"]:
        out.append(f"   {it['where']:<20} {_clip(it['text'], 110)}")
        out.append(f"   {'':<20} {it['message']}  (from {it['basis']})")
    if facts and facts["upper_bound_unconfirmed"]:
        u = facts["upper_bound_unconfirmed"]
        cases = sorted({x["cite"] for x in u})
        out.append(f"   Upper bound unconfirmed for {len(u)} pinpoint{'s' if len(u) != 1 else ''} in {len(cases)} "
                   f"case{'s' if len(cases) != 1 else ''} (no last_page): {', '.join(cases[:8])}"
                   + (" ..." if len(cases) > 8 else ""))

    out.append("")
    out.append(f"3. QUOTATIONS TO VERIFY ({len(o['quotations'])} tied to a citation; check each against its source "
               "with a quote tool, or by fetching the source by citation, which keeps a confidential filing's text private)")
    for q in o["quotations"]:
        src = q["cited_as"]
        if q["source"] and q["source"] != q["cited_as"]:
            src = f"{q['cited_as']} = {_clip(q['source'], 80)}"
        out.append(f"   {q['where']:<20} \"{_clip(q['text'], 100)}\"" + (f" ({q['length']} chars)" if q["length"] > 100 else ""))
        out.append(f"   {'':<20} -> {_clip(src, 120)}" + (f", at {q['pin']}" if q["pin"] and q["pin"] not in (src or "") else ""))
        if q["no_pin"]:
            out.append(f"   {'':<20} no pinpoint: the citation gives no page for the quotation; find it in the source")
        if q["note"]:
            out.append(f"   {'':<20} note: {q['note']}")
    un = o["unattributed_quotations"]
    if un:
        record = sum(1 for q in un if q["note"])
        out.append(f"   Not tied to a citation: {len(un)}" + (f" ({record} followed by a record cite)" if record else "")
                   + ". Their sources may be the record, a statute or contract quoted earlier, or the other side;")
        out.append("   find each one's source before relying on it: " + "; ".join(
            f"{q['where']} \"{_clip(q['text'], 50)}\"" for q in un[:6]) + (" ..." if len(un) > 6 else ""))

    out.append("")
    n_err = sum(g["count"] for g in o["form"] if g["severity"] == "error")
    n_chk = sum(g["count"] for g in o["form"] if g["severity"] == "check")
    out.append(f"4. FORM ({n_err} error{'s' if n_err != 1 else ''}, {n_chk} to check; in another side's filing "
               "these are rarely worth raising)")
    for g in o["form"]:
        pages = ", ".join(g["pages"][:6]) + (f" +{len(g['pages']) - 6} more" if len(g["pages"]) > 6 else "")
        out.append(f"   {g['severity']:<5} x{g['count']:<3} [{g['authority']}] {g['check']}: {pages}")
    if o["unrecognized"]:
        out.append("   Unrecognized (outside the script's forms): "
                   + ", ".join(f"{n} under {t}" for t, n in o["unrecognized"].items()))
    probs = (facts or {}).get("problems") or []
    if probs or report["notes"]:
        out.append("")
    for p in probs:
        out.append(f"Facts file: {p}")
    for note in report["notes"]:
        out.append(f"Note: {note}")
    out.append("")
    out.append("Not checked: whether each case says what it's cited for, or is still good law. Use a case-law tool.")
    return "\n".join(out)


def _facts_counts(n):
    return (f"{n['confirmed']} of {n['cases']} cases confirmed, {n['not_found']} not found, "
            f"{n['not_in_databases']} looked up but not in the databases, {n['not_looked_up']} not looked up")


def _not_in_databases(facts, indent):
    """The cases looked up but in none of the databases searched, with what was tried."""
    missing = (facts or {}).get("not_in_databases") or []
    if not missing:
        return []
    out = [f"{indent}Looked up but not in the databases ({len(missing)}); confirm each another way, such as Westlaw, "
           "Lexis, or the court's docket:"]
    for m in missing:
        out.append(f"{indent}{fl_check._where(m['location']):<20} {_clip(m['text'], 110)}")
        out.append(f"{indent}{'':<20} searched: {m['source']}" + (f"; {m['note']}" if m["note"] else ""))
    return out


def render_facts(report, facts_path=None):
    """The facts section for --mode own: what didn't match, ahead of the form report."""
    facts = report.get("facts")
    if not facts:
        return ""
    out = [f"FACTS (from {facts_path or 'the facts file'}: {_facts_counts(facts['counts'])})"]
    if not facts["findings"]:
        out.append("  no mismatches")
    for f in facts["findings"]:
        out.append(f"  {fl_check._where(f['location']):<20} {_clip(f['text'], 100)}")
        out.append(f"  {'':<20} {f['message']}")
    out += _not_in_databases(facts, "  ")
    if facts["upper_bound_unconfirmed"]:
        out.append(f"  {len(facts['upper_bound_unconfirmed'])} pinpoints checked only against the first page "
                   "(no last_page).")
    for p in facts["problems"]:
        out.append(f"  Facts file: {p}")
    return "\n".join(out) + "\n"


def facts_or_exit(path, data):
    try:
        return load_facts(path, data)
    except FactsError as e:
        sys.exit(str(e))
