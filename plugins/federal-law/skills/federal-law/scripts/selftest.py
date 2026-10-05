"""Self-test for federal_law.py against the live sources.

Run:  python3 scripts/selftest.py   (from the skill's folder)

Each case runs one federal_law.py command and makes two kinds of check:

  FAIL     a structural check failed: the command errored, or its output lost a
           shape it must always have (a header, a VERDICT line, a cite format).
           This means the script is broken or a source changed its format.
  CHANGED  the structure is fine, but a fact recorded on 2026-09-29 is no longer
           in the output (a new GPO edition was published, a rule was amended).
           This is the law or the editions moving, not a bug; update the case.
  FLAKY    failed once and passed when rerun: a live source hiccupped. Not a
           failure, but if the same case keeps showing up, look into it.
  BLOCKED  eCFR or FederalRegister.gov refused this machine's network (HTTP 403),
           on both tries. The Office of the Federal Register blocks some networks,
           including some cloud servers, so this says nothing about the script;
           run the test from another network to check those cases.
  DOWN     uscode.house.gov answered with House.gov's maintenance page on both
           tries. That's the site, not the script; rerun those checks once it's back.

Exit status is 1 if anything FAILED, else 0. Under GitHub Actions, BLOCKED, DOWN,
and FLAKY cases are also raised as workflow warnings.
"""

import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SCRIPT = Path(__file__).with_name("federal_law.py")

# (name, argv, must: regexes that must match, expect: regexes true on 2026-09-29)
CASES = [
    ("usc pulls a section by cite",
     ["usc", "5", "552", "--max", "3000"],
     [r"^5 U\.S\.C\. 552 — GPO \d{4} edition", r"§552\. Public information"],
     [r"GPO 2024 edition"]),
    ("currency: unchanged statute",
     ["currency", "5", "552"],
     [r"laws in effect on \w+ \d+, \d{4}", r"^VERDICT: "],
     [r"Statute text: identical", r"VERDICT: no change"]),
    ("currency: amended statute names the public law",
     ["currency", "26", "24", "--diff", "3"],
     [r"^VERDICT: ", r"Source credit: "],
     [r"NEW since GPO edition: Pub\. L\. 119-21", r"Statute text: DIFFERENT"]),
    ("cfr pulls the annual edition with a currency line",
     ["cfr", "5", "2635.502", "--max", "2000"],
     [r"^5 CFR 2635\.502 — annual CFR revised as of \d{4}-\d\d-\d\d",
      r"§ 2635\.502 Personal and business relationships\.", r"^CURRENCY: "],
     [r"CURRENCY: no change"]),
    ("cfr --current pulls today's eCFR text",
     ["cfr", "29", "1404.10", "--current"],
     [r"^29 CFR 1404\.10 — eCFR, up to date as of \d{4}-\d\d-\d\d", r"not an official legal edition"],
     [r"\[91 FR 55477, Aug\. 28, 2026\]"]),
    ("cfr-currency matches amendments to Federal Register rules",
     ["cfr-currency", "29", "1404.10", "--diff", "3"],
     [r"^VERDICT: ", r"Federal Register rules affecting 29 CFR part 1404"],
     [r"FR Doc\. 2026-17652", r"FR Doc\. 2026-15798"]),
    ("cfr-currency flags a change no rule explains",
     ["cfr-currency", "21", "131.200", "--diff", "3"],
     [r"^VERDICT: "],
     [r"No rule matches the eCFR version\(s\) dated 2026-07-20"]),
    ("search prints ready-made cites",
     ["search", 'collection:USCODE title:"public records"', "-n", "5"],
     [r"^\d+ results; showing \d+", r"cite:\s+\d+ U\.S\.C\. \w+\s+→ usc \d+ \w+"],
     [r"cite:\s+2 U\.S\.C\. 6574"]),
    ("search --all --grep reads every hit",
     ["search", 'collection:CFR "yogurt" means', "--all", "--grep", "yogurt", "--lines", "1"],
     [r"^\d+ results; showing \d+", r"^\d+ CFR [\d.]+ — .*→ cfr \d+ [\d.]+"],
     [r"7 CFR 220\.2 — Definitions", r"Yogurt means commercially prepared"]),
    ("search --grep tags notes and cites court rules",
     ["search", 'collection:USCODE "public records"', "--all", "--grep", "public records", "--lines", "1"],
     [r"· \[note\] "],
     [r"^Fed\. R\. Evid\. 1005 — ", r"^Fed\. R\. Civ\. P\. 44 — "]),
    ("ecfr-search searches current regulations",
     ["ecfr-search", '"yogurt" means', "-n", "30"],
     [r"^\d+ sections in current eCFR", r"^\d+ CFR [\d.]+ — .+\n  .*\(in effect since \d{4}-\d\d-\d\d\)"],
     [r"16 CFR 260\.12 — Recyclable claims"]),
    ("fr-rules lists rules affecting a part",
     ["fr-rules", "21", "131", "--since", "2020-01-01"],
     [r"Federal Register final rules affecting 21 CFR part 131",
      r"→ text FR-\d{4}-\d\d-\d\d \d{4}-\d+"],
     [r"FR Doc\. 2021-12220"]),
    ("plaw finds the Stat. cite and the bill",
     ["plaw", "114-185", "--max", "500"],
     [r"^Pub\. L\. 114-185, \d+ Stat\. \d+ \(\d{4}-\d\d-\d\d\)"],
     [r"130 Stat\. 538", r"enacted as S\. 337"]),
    ("plaw --grep finds amending language",
     ["plaw", "119-21", "--grep", r"Section 24\(h\) is amended", "--lines", "2"],
     [r"matching paragraph"],
     [r"\$2,200"]),
    ("cfr --appendix pulls a lettered appendix",
     ["cfr", "7", "210", "--appendix", "A", "--max", "1500"],
     [r"^7 CFR part 210, Appendix A — annual CFR revised as of \d{4}-\d\d-\d\d",
      r"Appendix A to Part 210.Alternate Foods for Meals", r"^CURRENCY: "],
     []),
    ("cfr --appendix finds a supplement GPO misfiles, and --grep --context reads it",
     ["cfr", "12", "1026", "--appendix", "Supplement I", "--grep", r"^19\(e\)\(3\)\(i\) ", "--context", "1"],
     [r"^12 CFR part 1026, Supplement I — annual CFR revised as of", r"matching paragraph",
      r"^CURRENCY: "],
     [r"part1026-appI-id92, CFR-2025-title12-vol9-part1026-appI-id93",
      r"19\(e\)\(3\)\(i\) General rule\.\n    1\. Requirement\."]),
    ("cfr-currency works on an appendix",
     ["cfr-currency", "12", "1026", "--appendix", "Supplement I", "--diff", "2"],
     [r"^12 CFR part 1026, Supplement I$", r"^VERDICT: "],
     [r"FR Doc\. 2024-30628"]),
    ("usc says whether a title is positive law",
     ["usc", "42", "1983", "--max", "200"],
     [r"^Title 42 is (NOT )?positive law"],
     [r"^Title 42 is NOT positive law"]),
    ("usc --pin pulls one subsection",
     ["usc", "5", "552", "--pin", "(b)(6)"],
     [r"^5 U\.S\.C\. 552\(b\)\(6\)$", r"^\(6\) personnel and medical files"],
     []),
    ("usc --pin flags flush language after the last paragraph",
     ["usc", "5", "552", "--pin", "(b)(9)"],
     [r"flush language belonging to a higher level"],
     []),
    ("usc --as-of pulls the edition in effect on a date",
     ["usc", "5", "552", "--as-of", "2016-01-01", "--pin", "(b)(5)"],
     [r"as of 2016-01-01 — 2012 Ed\. and Supplement II, laws in effect as of 2015-01-05",
      r"^AS-OF CHECK: "],
     [r"which would not be available by law to a party other than an agency in litigation "
      r"with the agency;$"]),
    ("usc --as-of flags laws enacted after that edition",
     ["usc", "5", "552", "--as-of", "2016-08-01", "--pin", "(b)(5)"],
     [r"^AS-OF CHECK: "],
     [r"Pub\. L\. 114-185 \(enacted 2016-06-30\) amended this section after this edition"]),
    ("cfr --as-of uses eCFR's point-in-time text from 2017 on",
     ["cfr", "21", "131.200", "--as-of", "2020-06-01", "--pin", "(a)"],
     [r"^21 CFR 131\.200 as of 2020-06-01 — eCFR point-in-time text"],
     [r"Lactobacillus bulgaricus and Streptococcus thermophilus"]),
    ("cfr --as-of uses the annual edition before 2017, with a rules check",
     ["cfr", "21", "131.200", "--as-of", "2012-06-01", "--pin", "(a)"],
     [r"as of 2012-06-01 — annual CFR revised as of \d{4}-\d\d-\d\d", r"^AS-OF CHECK: "],
     [r"revised as of 2012-04-01"]),
    ("cfr --pin splits run-together paragraph headings",
     ["cfr", "21", "131.200", "--current", "--pin", "(e)(1)(ii)"],
     [r"^21 CFR 131\.200\(e\)\(1\)\(ii\)$"],
     [r"^\(ii\) Milk solids not fat\."]),
    ("history assembles a law's legislative history",
     ["history", "114-185"],
     [r"^Legislative history: Pub\. L\. 114-185", r"^BILL: ", r"^CONGRESSIONAL RECORD \(\d+ entries"],
     [r"BILL: S\. 337 \(114th Cong\.\)", r"S\. Rep\. No\. 114-4: FOIA IMPROVEMENT ACT OF 2015",
      r"162 Cong\. Rec\. H3714-H3719 \(daily ed\. June 13, 2016\)", r"5 U\.S\.C\. 552: "]),
    # Citation formats from the 2026-09-30 sweep: each of these broke before.
    ("usc --pin past a bracketed repealed subsection",
     ["usc", "26", "401", "--pin", "(k)(2)(B)"],
     [r"^26 U\.S\.C\. 401\(k\)\(2\)\(B\)$", r"^\(B\) "],
     []),
    ("usc --pin in a section numbered (1), (2), (10A)",
     ["usc", "11", "101", "--pin", "(10A)"],
     [r"^11 U\.S\.C\. 101\(10A\)$"],
     [r'^\(10A\) The term "current monthly income"']),
    ("cfr --pin skips contents tables and tells letter (i) from roman (i)",
     ["cfr", "8", "214.2", "--current", "--pin", "(h)(1)(ii)(B)"],
     [r"^8 CFR 214\.2\(h\)\(1\)\(ii\)\(B\)$", r"^\(B\) "],
     [r"^\(B\) An H-1B classification"]),
    ("cfr --pin: subsection (i), not a roman (i) inside (h)",
     ["cfr", "8", "214.2", "--current", "--pin", "(i)"],
     [r"^8 CFR 214\.2\(i\)$"],
     [r"^\(i\) Representatives of information media"]),
    ("cfr --pin splits a paragraph that starts after a heading's period",
     ["cfr", "29", "1910.1200", "--current", "--pin", "(i)(1)"],
     [r"^29 CFR 1910\.1200\(i\)\(1\)$", r"^\(1\) "],
     []),
    ("cfr finds a tax regulation with parentheses in its number",
     ["cfr", "26", "1.401(k)-1", "--pin", "(a)(1)"],
     [r"^26 CFR 1\.401\(k\)-1 — annual CFR revised as of", r"^26 CFR 1\.401\(k\)-1\(a\)\(1\)$"],
     [r"CFR-2025-title26-vol6-sec1-401k-1"]),
    ("search cites a tax regulation with its parentheses",
     ["search", 'collection:CFR title:"Cash or deferred arrangements"', "-n", "3"],
     [r"cite:\s+26 CFR 1\.401\(k\)-1\s+→ cfr 26 '1\.401\(k\)-1'"],
     []),
    ("history falls back to a Record search when GovInfo errors",
     ["history", "111-148", "-n", "1"],
     [r"^Legislative history: Pub\. L\. 111-148"],
     [r"CONGRESSIONAL RECORD: GovInfo returned an error",
      r"search 'collection:CREC congress:111 \"H\.R\. 3590\"' --all"]),
    ("bad cite: a pre-1995 law points to the Statutes at Large",
     ["plaw", "90-23"],
     [r"start with the 104th Congress \(1995\)", r"summary STATUTE-81 STATUTE-81-Pg54"], []),
    ("bad cite: malformed pinpoint",
     ["usc", "5", "552", "--pin", "b6"],
     [r"a pinpoint looks like"], []),
    ("bad cite: unknown appendix lists the real ones",
     ["cfr", "7", "210", "--appendix", "Z"],
     [r'"Z" matches nothing in 7 CFR part 210', r"Appendix C to Part 210"], []),
    ("bad cite: public law",
     ["plaw", "999-999"],
     [r"GovInfo has no public law 999-999"], []),
    ("bad cite: CFR part without a section",
     ["cfr", "5", "2635"],
     [r"give a section number with its part"], []),
]

BAD_INPUT = {"bad cite: public law", "bad cite: CFR part without a section",
             "bad cite: unknown appendix lists the real ones", "bad cite: malformed pinpoint",
             "bad cite: a pre-1995 law points to the Statutes at Large"}


def attempt(case):
    name, argv, must, expect = case
    try:
        proc = subprocess.run([sys.executable, str(SCRIPT), *argv], capture_output=True,
                              text=True, encoding="utf-8", timeout=300)
    except subprocess.TimeoutExpired:
        return ["timed out after 300s"], [], None
    out = proc.stdout + proc.stderr
    blocked = re.search(r"ACCESS BLOCKED: (\S+) refused", out)
    down = re.search(r"([\w.]+) is down for maintenance", out)
    failures, changes = [], []
    if proc.returncode != 0 and name not in BAD_INPUT:
        failures.append(f"exit status {proc.returncode}: {out.strip()[-300:]}")
    if "using DEMO_KEY" in out:
        failures.append("fell back to DEMO_KEY: no API key found")
    failures += [f"missing /{p}/" for p in must if not re.search(p, out, re.M)]
    changes += [f"no longer /{p}/" for p in expect if not re.search(p, out, re.M)]
    if blocked:
        outage = ("BLOCKED", f"{blocked[1]} refused this network (HTTP 403)")
    elif down:
        outage = ("DOWN", f"{down[1]} is down for maintenance")
    else:
        outage = None
    return failures, changes, outage


def run(case):
    """One case, rerun once if it fails: the sources are live government sites, and a
    one-off outage shouldn't fail the suite. A pass on the rerun is reported as FLAKY;
    a site refusing this network on both tries, as BLOCKED; a site down for
    maintenance on both tries, as DOWN."""
    failures, changes, outage = attempt(case)
    first = None
    if failures:
        first = failures
        failures, changes, outage = attempt(case)
    return case[0], failures, changes, first, outage


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run, CASES))
    counts = {"ok": 0, "FLAKY": 0, "BLOCKED": 0, "DOWN": 0, "CHANGED": 0, "FAIL": 0}
    in_actions = bool(os.environ.get("GITHUB_ACTIONS"))
    for name, failures, changes, first, outage in results:
        if failures and outage:
            status, failures, changes = outage[0], [outage[1]], []
        else:
            status = "FAIL" if failures else "CHANGED" if changes else "FLAKY" if first else "ok"
        counts[status] += 1
        print(f"{status:<8}{name}")
        detail = failures + changes + ([f"first try: {x}" for x in first]
                                       if first and status == "FLAKY" else [])
        for line in detail:
            print(f"          {line}")
        if in_actions and status in ("BLOCKED", "DOWN", "FLAKY"):
            print(f"::warning title=self-test {status}::{name}: {(detail or [''])[0][:200]}")
    print(f"\n{counts['ok']} ok, {counts['FLAKY']} flaky, {counts['BLOCKED']} blocked, "
          f"{counts['DOWN']} down, {counts['CHANGED']} changed, {counts['FAIL']} failed, "
          f"of {len(results)}")
    sys.exit(1 if counts["FAIL"] else 0)


if __name__ == "__main__":
    main()
