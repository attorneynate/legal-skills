"""Self-test for fl_cite.py: every command offline, plus two live checks.

Run:  python3 scripts/selftest.py   (from the skill's folder)

The offline cases run each fl_cite.py command on fixed input. The live cases:

  - Clean opinions: two Florida District Court of Appeal opinions filed after the
    September 1, 2026 amendment are downloaded from the Florida courts' website and
    run through `check`. Courts follow Rule 9.800, and these two raised no finding
    when they were recorded, so any error or check finding now is a regression.
    Reading a PDF needs pdftotext (Poppler or Xpdf).
  - Amendment watch: CourtListener's opinion search for Florida Supreme Court
    opinions amending the appellate rules that mention Rule 9.800. Any opinion not
    listed under amendment_watch in data/florida.json is reported.

Each case reports one of:

  FAIL     the script is broken: a command errored, or its output lost a shape it
           must have (the rule's as-of line, a fix, a finding's authority), or an
           unchanged opinion now draws findings.
  CHANGED  the structure is fine, but a fact recorded on 2026-10-02 has moved: a
           court replaced an opinion's PDF (perhaps a corrected opinion), or a new
           rules opinion mentions Rule 9.800. That is the law or the source moving,
           not a bug. Read it, then update references/rule-9.800.md and the
           amendment_watch list in data/florida.json, or this file.
  FLAKY    failed once and passed when rerun: a live source hiccupped.
  BLOCKED  a live case couldn't run: the source refused or failed on both tries, or
           pdftotext isn't installed. This says nothing about the script.

Exit status is 1 if anything FAILED, else 0. Under GitHub Actions, CHANGED, FLAKY,
and BLOCKED cases are also raised as workflow warnings.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SCRIPT = Path(__file__).with_name("fl_cite.py")
DATA = Path(__file__).resolve().parent.parent / "data" / "florida.json"
USER_AGENT = "florida-citation-skill (+https://github.com/attorneynate/legal-skills)"
SEARCH = "https://www.courtlistener.com/api/rest/v4/search/"

# Offline: (name, argv, stdin, must: regexes that must match the output, exit status)
COMMANDS = [
    ("rule prints a subdivision with its as-of line",
     ["rule", "f"], None,
     [r"^Fla\. R\. App\. P\. 9\.800\(f\), as amended effective September 1, 2026 "
      r"\(.*No\. SC2025-0241 \(Fla\. June 11, 2026\) \(corrected opinion\)\)",
      r"^\(1\) § 48\.031, Fla\. Stat\. \(2014\)\."], 0),
    ("rule lists the subdivisions",
     ["rule"], None,
     [r"^\(a\) Florida Supreme Court\.", r"^\(q\) "], 0),
    ("abbrev finds a renamed rule set",
     ["abbrev", "judicial administration"], None,
     [r"^Fla\. R\. Gen\. Prac\. & Jud\. Admin\. ", r"\[9\.800\(j\)\(3\)\]",
      r"Fla\. R\. Jud\. Admin\."], 0),
    ("abbrev corrects a reporter",
     ["abbrev", "So.2d"], None,
     [r"^So\. 2d$", r"not So\.2d\s+\[9\.800\(a\)\(1\)\]"], 0),
    ("casenum converts to the four-digit form",
     ["casenum", "SC09-839", "1D01-2734"], None,
     [r"^SC09-839 -> SC2009-0839$", r"^1D01-2734 -> 1D2001-2734$"], 0),
    ("casenum refuses a court that doesn't exist",
     ["casenum", "7D2020-0001"], None,
     [r"CAN'T CONVERT: there is no 7th District"], 1),
    ("checks lists the records for a subdivision",
     ["checks", "--authority", "9.800(f)"], None,
     [r"^f-fs\s+error\s+pattern\s+9\.800\(f\)"], 0),
    ("build rebuilds the rule's own case example",
     ["build", "case", "Fenelon v. State", "--court", "SC", "--year", "1992",
      "--cite", "594 So. 2d 292", "--pin", "293"], None,
     [r"^Fenelon v\. State, 594 So\. 2d 292, 293 \(Fla\. 1992\)\.$", r"authority: 9\.800\(a\)"], 0),
    ("build gives a statute's sentence form",
     ["build", "statute", "48.031", "--year", "2014"], None,
     [r"^§ 48\.031, Fla\. Stat\. \(2014\)\.$",
      r"in a sentence: section 48\.031, Florida Statutes \(2014\)"], 0),
    ("build refuses parts that can't all be right",
     ["build", "case", "Smith v. State", "--court", "SC", "--year", "1992", "--cite", "300 So. 3d 100"],
     None,
     [r"can't all be right", r"So\. 3d covers 2008-present"], 1),
    ("check reports form errors with authority and fix",
     ["check", "-", "--date", "2026-10-01"],
     "See Smith v. Jones, 594 So.2d 292 (Fla. 3rd DCA 1992).\n",
     [r"^2 errors, 0 to check, 0 unrecognized", r"\[9\.800\(a\)\(1\)\] So\.2d", r"fix: So\. 2d",
      r"\[9\.800\(b\)\(1\)\] 3rd DCA", r"fix: 3d DCA"], 0),
    ("check follows short forms across the document",
     ["check", "-", "--date", "2026-10-01"],
     "Smith v. Jones, 594 So. 2d 292, 293 (Fla. 1992). The rule applies. Id at 294.\n",
     [r"^1 error, 0 to check", r"\[Indigo Book R6\.2\.2\] Id", r"fix: Id\."], 0),
    ("check reads page breaks and printed page numbers",
     ["check", "-", "--date", "2026-10-01"],
     "Cover page\n\ni\n\fArgument text.\n\nSmith v. Jones, 594 So.2d 292 (Fla. 1992).\n\n1\n",
     [r"^  p\. 1 \(PDF p\. 2\)\s+\[9\.800\(a\)\(1\)\] So\.2d"], 0),
    ("check notes exhibits after the filing",
     ["check", "-", "--date", "2026-10-01", "--mode", "opposing"],
     "Argument. Smith v. Jones, 594 So. 2d 292 (Fla. 1992).\n\fExhibit 1\n\fRoe v. Doe, 600 So. 2d 100 (Fla. 1993).\n",
     [r'^Exhibits\? PDF p\. 2 reads only "Exhibit 1"\. To review only the filing, rerun with --last-page 1\.$'], 0),
    ("check --last-page and --cite-list give the filing's cases alone",
     ["check", "-", "--date", "2026-10-01", "--last-page", "1", "--cite-list"],
     "Argument. Smith v. Jones, 594 So. 2d 292 (Fla. 1992).\n\fExhibit 1\n\fRoe v. Doe, 600 So. 2d 100 (Fla. 1993).\n",
     [r"\ASmith v\. Jones, 594 So\. 2d 292 \(Fla\. 1992\)\n\Z"], 0),
]

DOCUMENT = "The rule is settled. Fenelon v. State, 594 So. 2d 292, 297 (Fla. 1992).\n"
FACTS = [{"cite": "594 So. 2d 292", "found": True, "case_name": "Fenelon v. State", "court": "1D",
          "year": 1992, "first_page": 292, "last_page": 295, "source": "self-test"}]

# Live: opinions that drew no findings on 2026-10-02, with the first 16 hex digits of the
# PDF's SHA-256 then (enough to notice a replaced file), the fewest citations check must
# find in it, and the court's own departures that later checks find, as (check, text found).
OPINIONS = [
    ("4D2025-0167", "https://flcourts-media.flcourts.gov/content/download/2496006/opinion/Opinion_2025-0167.pdf",
     "d21d3432bbbeaf16", 70, ()),
    ("1D2025-0988", "https://flcourts-media.flcourts.gov/content/download/2495985/opinion/Opinion_2025-0988.pdf",
     "f04797a44e71d573", 18, (("ellipsis-form", "..."),)),
]


class Blocked(Exception):
    """A live source refused or failed: not the script's fault."""


def fetch(url, tries=3):
    for i in range(tries):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or i == tries - 1:
                raise Blocked(f"HTTP {e.code} from {urllib.parse.urlsplit(url).netloc}")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if i == tries - 1:
                reason = getattr(e, "reason", e)
                raise Blocked(f"{urllib.parse.urlsplit(url).netloc} unreachable: {reason}")
        time.sleep(3 * (i + 1))


def fl_cite(argv, stdin=None):
    try:
        proc = subprocess.run([sys.executable, str(SCRIPT), *argv], input=stdin, capture_output=True,
                              text=True, encoding="utf-8", timeout=300)
    except subprocess.TimeoutExpired:
        return None, "timed out after 300s"
    return proc.returncode, proc.stdout + proc.stderr


# ---------------------------------------------------------------- the cases
# Each returns (failures, changes); a live case raises Blocked when it can't run.

def command_case(argv, stdin, must, status):
    def run():
        code, out = fl_cite(argv, stdin)
        failures = [] if code == status else [f"exit status {code}, expected {status}: {out.strip()[-300:]}"]
        failures += [f"missing /{p}/" for p in must if not re.search(p, out, re.M)]
        return failures, []
    return run


def facts_loop():
    """The opposing-filing loop: template, then a facts file with a wrong court and a
    pinpoint past the last page."""
    with tempfile.TemporaryDirectory() as d:
        doc, facts = Path(d, "brief.txt"), Path(d, "facts.json")
        doc.write_text(DOCUMENT, encoding="utf-8")
        failures = []
        code, out = fl_cite(["check", str(doc), "--facts-template"])
        try:
            cites = [c["cite"] for c in json.loads(out)["cases"]]
            if cites != ["594 So. 2d 292"]:
                failures.append(f"template lists {cites}, expected ['594 So. 2d 292']")
        except (ValueError, KeyError, TypeError):
            failures.append(f"--facts-template didn't print the template: {out.strip()[-300:]}")
        facts.write_text(json.dumps(FACTS), encoding="utf-8")
        code, out = fl_cite(["check", str(doc), "--mode", "opposing", "--facts", str(facts)])
        if code != 0:
            failures.append(f"exit status {code}: {out.strip()[-300:]}")
        for p in (r"^1\. FACTS THAT DON'T MATCH", r"The document says Fla\.; found 1D \(self-test\)\.",
                  r"^2\. PINPOINTS OUT OF RANGE",
                  r"Pinpoint 297 is past the case's last page, 295 \(self-test\)\.",
                  r"^Everything below is something to confirm"):
            if not re.search(p, out, re.M):
                failures.append(f"missing /{p}/")
        return failures, []


def clean_opinion(docket, url, fingerprint, min_citations, court_deviations=()):
    def run():
        pdf = fetch(url)
        if not shutil.which("pdftotext"):
            raise Blocked("pdftotext isn't installed, so the PDF can't be read")
        moved = hashlib.sha256(pdf).hexdigest()[:16] != fingerprint
        with tempfile.TemporaryDirectory() as d:
            path = Path(d, docket + ".pdf")
            path.write_bytes(pdf)
            code, out = fl_cite(["check", str(path), "--json"])
        try:
            report = json.loads(out)
            counts, n = report["summary"]["findings"], report["summary"]["citations"]
        except (ValueError, KeyError, TypeError):
            return [f"check didn't produce a report (exit {code}): {out.strip()[-300:]}"], []
        found = [f"{f['severity']} [{f['authority']}] {f.get('found', '')}" for f in report["findings"]
                 if f["severity"] in ("error", "check") and (f["check"], f.get("found")) not in court_deviations]
        if moved:
            return [], ["the court replaced this PDF since 2026-10-02 (a corrected opinion?); "
                        f"{n} citations, {len(found)} findings now"] + found[:5]
        failures = found[:10]
        if n < min_citations:
            failures.append(f"found {n} citations, expected at least {min_citations}")
        if counts.get("error") is None:
            failures.append("the report has no error count")
        return failures, []
    return run


def amendment_watch():
    watch = json.loads(DATA.read_text(encoding="utf-8"))["amendment_watch"]
    known = {(k["docket"], k["filed"]) for k in watch["known"]}
    query = urllib.parse.urlencode({"type": "o", "court": "fla", "q": watch["query"],
                                    "filed_after": watch["filed_after"], "order_by": "dateFiled desc"})
    url, results = f"{SEARCH}?{query}", []
    for _ in range(5):
        try:
            page = json.loads(fetch(url))
        except ValueError:
            raise Blocked("CourtListener returned something other than JSON")
        if not isinstance(page.get("results"), list):
            return ["CourtListener's search response has no results list; its format changed"], []
        results += page["results"]
        url = page.get("next")
        if not url:
            break
    changes = []
    for r in results:
        key = (r.get("docketNumber") or "", r.get("dateFiled") or "")
        if key in known:
            continue
        links = [o.get("download_url") for o in r.get("opinions") or [] if o.get("download_url")]
        link = links[0] if links else "https://www.courtlistener.com" + (r.get("absolute_url") or "")
        changes.append(f"not on the known list: {key[0] or 'no docket'} filed {key[1]}, "
                       f"{r.get('caseName', '')}: {link}")
    return [], changes


CASES = ([(name, False, command_case(argv, stdin, must, status))
          for name, argv, stdin, must, status in COMMANDS]
         + [("check --facts loop ranks a wrong court and an out-of-range pinpoint", False, facts_loop)]
         + [(f"live: {d} (after the amendment) checks clean", True, clean_opinion(d, u, s, n, dev))
            for d, u, s, n, dev in OPINIONS]
         + [("live: no new Rule 9.800 amendment on CourtListener", True, amendment_watch)])


def attempt(fn):
    try:
        failures, changes = fn()
        return failures, changes, None
    except Blocked as e:
        return [], [], str(e)


def run(case):
    """One case. A live case that fails or is blocked is rerun once: a pass on the rerun
    is FLAKY; blocked on both tries is BLOCKED."""
    name, live, fn = case
    failures, changes, blocked = attempt(fn)
    first = None
    if live and (failures or blocked):
        first = failures or [blocked]
        time.sleep(5)
        failures, changes, blocked = attempt(fn)
    return name, failures, changes, first, blocked


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run, CASES))
    counts = {"ok": 0, "FLAKY": 0, "BLOCKED": 0, "CHANGED": 0, "FAIL": 0}
    in_actions = bool(os.environ.get("GITHUB_ACTIONS"))
    for name, failures, changes, first, blocked in results:
        if blocked and not failures:
            status, detail = "BLOCKED", [blocked]
        else:
            status = "FAIL" if failures else "CHANGED" if changes else "FLAKY" if first else "ok"
            detail = failures + changes + ([f"first try: {x}" for x in first]
                                           if first and status == "FLAKY" else [])
        counts[status] += 1
        print(f"{status:<8}{name}")
        for line in detail:
            print(f"          {line}")
        if in_actions and status in ("CHANGED", "BLOCKED", "FLAKY"):
            print(f"::warning title=self-test {status}::{name}: {(detail or [''])[0][:200]}")
    print(f"\n{counts['ok']} ok, {counts['FLAKY']} flaky, {counts['BLOCKED']} blocked, "
          f"{counts['CHANGED']} changed, {counts['FAIL']} failed, of {len(results)}")
    sys.exit(1 if counts["FAIL"] else 0)


if __name__ == "__main__":
    main()
