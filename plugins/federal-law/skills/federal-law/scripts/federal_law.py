"""Small command-line client for the GovInfo API (https://api.govinfo.gov).

The API key is read from the GOVINFO_API_KEY environment variable, or else
from the file ~/.govinfo_api_key. With neither, it falls back to DEMO_KEY,
which works but is heavily rate-limited.

Usage:
  python federal_law.py collections
  python federal_law.py search 'collection:USCODE "public records"' [-n 10] [--offset MARK]
                           [--all [--limit 300]] [--grep REGEX [--lines 3]]
  python federal_law.py ecfr-search '"yogurt" means' [--title 21] [-n 20] [--grep REGEX]
  python federal_law.py fr-rules TITLE PART [--since DATE] [--until DATE] [--all-types]
  python federal_law.py plaw 119-21 [--private] [--max 20000]
  python federal_law.py summary PACKAGE_ID [GRANULE_ID]
  python federal_law.py text PACKAGE_ID [GRANULE_ID] [--max 20000]
  python federal_law.py granules PACKAGE_ID [-n 100]
  python federal_law.py usc TITLE SECTION [--notes] [--max 20000]
  python federal_law.py currency TITLE SECTION [--diff 40]
  python federal_law.py cfr-currency TITLE SECTION [--diff 40]    # e.g. 5 2635.502
  python federal_law.py cfr-currency TITLE PART --appendix A      # appendices and supplements
  python federal_law.py cfr TITLE SECTION [--current] [--grep REGEX] [--max 20000]
  python federal_law.py cfr TITLE PART --appendix "Supplement I" [--current] [--grep REGEX]
"""

import argparse
import difflib
import gzip
import html
import http.client
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://api.govinfo.gov"
LINK = "https://www.govinfo.gov/link"
OLRC = "https://uscode.house.gov/view.xhtml"
OLRC_BROWSE = "https://uscode.house.gov/browse.xhtml"
OLRC_DOWNLOAD = "https://uscode.house.gov/download/download.shtml"
ECFR = "https://www.ecfr.gov/api/versioner/v1"
ECFR_SEARCH = "https://www.ecfr.gov/api/search/v1/results"
FEDREG = "https://www.federalregister.gov/api/v1/documents.json"
# Identifies this tool to the sites it calls, with a link to where it comes from.
USER_AGENT = "federal-law-skill (+https://github.com/attorneynate/legal-research-skills)"


def api_key():
    key = os.environ.get("GOVINFO_API_KEY")
    if key:
        return key.strip()
    path = Path.home() / ".govinfo_api_key"
    if path.exists():
        return path.read_text(encoding="utf-8-sig").strip()
    print("note: no API key found; using DEMO_KEY (rate-limited)", file=sys.stderr)
    return "DEMO_KEY"


_socket_create_connection = socket.create_connection


def _connect_ipv4_first(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None,
                        **kwargs):
    """socket.create_connection, but IPv4 addresses first and a short connect timeout per
    address. GovInfo publishes IPv6 addresses that some networks can't reach, and Python
    (unlike curl or a browser) waits out each one, about 20 s apiece, before trying IPv4."""
    host, port = address
    try:
        infos = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
    except OSError:
        return _socket_create_connection(address, timeout, source_address)
    infos.sort(key=lambda info: info[0] != socket.AF_INET)
    full = None if timeout is socket._GLOBAL_DEFAULT_TIMEOUT else timeout
    last_error = None
    for family, socktype, proto, _, sockaddr in infos:
        sock = socket.socket(family, socktype, proto)
        try:
            sock.settimeout(min(8, full) if full else 8)
            if source_address:
                sock.bind(source_address)
            sock.connect(sockaddr)
            sock.settimeout(full)
            return sock
        except OSError as e:
            last_error = e
            sock.close()
    raise last_error or OSError(f"no addresses for {host}")


# http.client picks this up when it builds each connection.
socket.create_connection = _connect_ipv4_first

TRANSIENT_HTTP = {429, 500, 502, 503, 504}


def fetch(req, opener=None, tries=3):
    """Open a request and read it: (body bytes, final URL, headers). Timeouts, dropped
    connections, and 429/5xx responses are retried twice with a short backoff; other
    HTTP errors (404, a redirect caught by _NoRedirect, ...) are raised to the caller."""
    host = urllib.parse.urlsplit(req.full_url).netloc
    for attempt in range(tries):
        try:
            with (opener.open if opener else urllib.request.urlopen)(req, timeout=60) as resp:
                return resp.read(), resp.geturl(), resp.headers
        except urllib.error.HTTPError as e:
            if e.code not in TRANSIENT_HTTP or attempt == tries - 1:
                raise
        except (OSError, http.client.HTTPException) as e:  # URLError, timeouts, resets
            if attempt == tries - 1:
                sys.exit(f"network error reaching {host}: {getattr(e, 'reason', e)}")
        time.sleep(2 * (attempt + 1))


def request(url, body=None, raw=False):
    parts = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parts.query) + [("api_key", api_key())]
    url = urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    req.add_header("Accept", "*/*" if raw else "application/json")
    req.add_header("User-Agent", USER_AGENT)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        payload = fetch(req)[0].decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:500]}")
    return payload if raw else json.loads(payload)


def fetch_page(url, allow_missing=False):
    """GET a public web page (no API key). Returns (final URL, decoded body)."""
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
    try:
        content, final, headers = fetch(req)
        charset = headers.get_content_charset()
        if headers.get("Content-Encoding") == "gzip":
            content = gzip.decompress(content)
    except urllib.error.HTTPError as e:
        if allow_missing and e.code == 404:
            return url, None
        host = urllib.parse.urlsplit(url).netloc
        if e.code == 403 and host.endswith(("ecfr.gov", "federalregister.gov")):
            sys.exit(f"ACCESS BLOCKED: {host} refused this request (HTTP 403). The Office of the "
                     "Federal Register blocks some networks from eCFR and FederalRegister.gov, even "
                     "for their developer APIs: often cloud servers, VPNs, and networks with heavy "
                     "automated traffic. This is the network, not the citation. Try again later or "
                     "from another network; GovInfo and uscode.house.gov are unaffected.")
        sys.exit(f"HTTP {e.code} fetching {url}")
    for encoding in filter(None, (charset, "utf-8", "cp1252")):
        try:
            return final, content.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return final, content.decode("utf-8", errors="replace")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def redirect_target(url):
    """Where a URL redirects to, without downloading the target."""
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        fetch(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), opener=opener)
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308):
            return e.headers.get("Location")
        return None
    return None


def collections(_):
    for c in request(f"{BASE}/collections")["collections"]:
        print(f"{c['collectionCode']:<12} {c.get('packageCount', ''):>8}  {c['collectionName']}")


# --- Helpers shared by the search commands.

def cite_for(package, granule=""):
    """(citation, follow-up command) for a GovInfo package/granule, or (None, None)."""
    g = granule or ""
    m = re.match(r"CFR-\d{4}-title(\d+)-vol\d+-sec(\d+)-(.+)$", g)
    if m:
        section = m[3]
        # Tax regulations number sections after Code provisions, parentheses and all
        # (26 CFR 1.401(k)-1); GovInfo drops the parentheses from the granule ID.
        tax = re.fullmatch(r"(\d+)((?:[a-z]+|\d+)+?)-(\d+[A-Z]?)", section) if m[1] == "26" else None
        if tax and re.search(r"[a-z]", tax[2]):
            parens = "".join(f"({p})" for p in re.findall(r"[a-z]+|\d+", tax[2]))
            section = f"{tax[1]}{parens}-{tax[3]}"
        arg = f"'{m[2]}.{section}'" if "(" in section else f"{m[2]}.{section}"  # shell-safe
        return f"{m[1]} CFR {m[2]}.{section}", f"cfr {m[1]} {arg}"
    m = re.match(r"CFR-\d{4}-title(\d+)-vol\d+-part(\d+)-app(\w+)$", g)
    if m:
        return f"{m[1]} CFR part {m[2]}, Appendix {m[3]}", f"cfr {m[1]} {m[2]} --appendix {m[3]}"
    m = re.match(r"CFR-\d{4}-title(\d+)-vol\d+-part(\d+)(?:-(.+))?$", g)
    if m:
        # e.g. "-appI-id92": a continuation granule GPO files under another appendix's
        # name (here, Supplement I). Its heading, not its ID, says what it is.
        extra = f" ({m[3]}; check the heading)" if (m[3] or "").startswith("app") else \
            (f", {m[3]}" if m[3] else "")
        return f"{m[1]} CFR part {m[2]}{extra}", None
    m = re.match(r"USCODE-\d{4}-title(\w+)-app-.*-(rule|sec)([\w.-]+)$", g)
    if m:
        # Appendix material (court rules, some acts). search() upgrades rule cites
        # to "Fed. R. Evid. 1005" etc. once it knows which set of rules this is.
        unit = "Rule" if m[2] == "rule" else "§"
        return f"{m[1]} U.S.C. app. {unit} {m[3]}", f"text {package} {g}"
    m = re.match(r"USCODE-\d{4}-title(\w+)-(?:.*-)?sec([\w-]+)$", g)
    if m:
        return f"{m[1]} U.S.C. {m[2]}", f"usc {m[1]} {m[2]}"
    m = re.match(r"PLAW-(\d+)publ(\d+)$", package or "")
    if m:
        return f"Pub. L. {m[1]}-{m[2]}", f"plaw {m[1]}-{m[2]}"
    if re.match(r"FR-\d{4}-\d\d-\d\d$", package or "") and g:
        return f"FR Doc. {g}", f"text {package} {g}"
    return None, None


def demojibake(s):
    # Some eCFR API strings are UTF-8 decoded as Windows-1252 ("Â§" for "§"),
    # and headings carry search-highlight tags.
    s = html.unescape(re.sub(r"<[^>]+>", "", s or ""))
    try:
        return s.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


NOTE_TAG = "[note] "


def matches_in(lines, pattern, limit, width=160):
    """Snippets around each match of `pattern` in `lines`, at most `limit` of them.
    Lines tagged NOTE_TAG keep the tag at the front of their snippet."""
    out = []
    for line in lines:
        tag = NOTE_TAG if line.startswith(NOTE_TAG) else ""
        line = line[len(tag):]
        m = pattern.search(line)
        if m:
            start = max(0, m.start() - width)
            snippet = line[start: m.end() + width]
            out.append(tag + ("…" if start else "") + snippet
                       + ("…" if m.end() + width < len(line) else ""))
            if len(out) == limit:
                break
    return out


RULE_SETS = {
    "FEDERAL RULES OF APPELLATE PROCEDURE": "Fed. R. App. P.",
    "FEDERAL RULES OF BANKRUPTCY PROCEDURE": "Fed. R. Bankr. P.",
    "FEDERAL RULES OF CIVIL PROCEDURE": "Fed. R. Civ. P.",
    "FEDERAL RULES OF CRIMINAL PROCEDURE": "Fed. R. Crim. P.",
    "FEDERAL RULES OF EVIDENCE": "Fed. R. Evid.",
}


def rule_set(lines):
    """The citation abbreviation for the set of rules a U.S. Code appendix page belongs to."""
    for line in lines or []:
        name = re.sub(r"\s+", " ", line).strip().upper()
        if name in RULE_SETS:
            return RULE_SETS[name]
        if name.startswith(("RULE ", "§")):
            break
    return None


def parallel(fn, items, workers=6):
    """fn over items concurrently; a failure (including sys.exit) yields None for that item."""
    from concurrent.futures import ThreadPoolExecutor

    def safe(item):
        try:
            return fn(item)
        except BaseException:
            return None
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(safe, items))


def raw_lines(hit):
    """A GovInfo hit's text rendition, one non-blank line per entry; None if unavailable."""
    link = request(summary_url(hit.get("packageId"), hit.get("granuleId"))).get(
        "download", {}).get("txtLink")
    if not link:
        return None
    return [line.strip() for line in strip_html(request(link, raw=True)).splitlines() if line.strip()]


def hit_lines(hit, lines=None):
    """Text of a GovInfo search hit, one paragraph per line; None if unavailable.
    For the U.S. Code: drop the page banner, and tag editorial and statutory notes
    (everything after the source credit) with NOTE_TAG."""
    package, granule = hit.get("packageId"), hit.get("granuleId")
    if hit.get("collectionCode") == "CFR" and granule:
        xml = request(f"{BASE}/packages/{package}/granules/{granule}/xml", raw=True)
        return cfr_xml_text(xml)
    lines = lines if lines is not None else raw_lines(hit)
    if lines is None or hit.get("collectionCode") != "USCODE":
        return lines
    # The provision proper starts at its own heading: "§552. ..." or "Rule 1005. ...".
    start = next((i for i, line in enumerate(lines)
                  if re.match(r"(§ ?[\w.-]+\.|Rule [\w.()-]+\.) ", line)), 0)
    lines = lines[start:]
    # Notes follow the source credit ("(Pub. L. ..., 80 Stat. 383 ...)", or for court
    # rules "(As amended ...)"). Without a credit, they start at the first notes heading.
    credit = next((i + 1 for i, line in enumerate(lines)
                   if re.match(r"\((As amended|Added|.*\d+ Stat\. \d+)", line)), None)
    if credit is None:
        credit = next((i for i, line in enumerate(lines) if re.match(
            r"(Notes of Advisory Committee|Committee Notes|Editorial Notes|Statutory Notes)", line)), None)
    if credit is None:
        return lines
    return lines[:credit] + [NOTE_TAG + line for line in lines[credit:]]


def appendix_rule_cites(hits, texts=None):
    """{granule: "Fed. R. Evid. 1005"} for U.S. Code appendix court rules among the hits.
    Reads each rule set's name from one page of its text, fetched once per set."""
    groups = {}
    for i, hit in enumerate(hits):
        m = re.match(r"(USCODE-\d{4}-title\w+-app-.*)-rule([\w.-]+)$", hit.get("granuleId") or "")
        if m:
            groups.setdefault(m[1], []).append((i, m[2]))
    if not groups:
        return {}
    firsts = [members[0][0] for members in groups.values()]
    if texts is None:
        fetched = parallel(lambda i: raw_lines(hits[i]), firsts)
    else:
        fetched = [texts[i] for i in firsts]
    cites = {}
    for members, lines in zip(groups.values(), fetched):
        abbrev = rule_set(lines)
        if abbrev:
            for i, number in members:
                cites[hits[i]["granuleId"]] = f"{abbrev} {number}"
    return cites


def print_grep(label, lines, pattern, limit):
    if lines is None:
        print(f"{label}\n  (no text available to scan)\n")
        return False
    found = matches_in(lines, pattern, limit)
    if found:
        print(label)
        for snippet in found:
            print(f"  · {snippet}")
        print()
    return bool(found)


def search(args):
    hits, offset, total = [], args.offset, 0
    page_size = min(args.n, 100) if not args.all else 100
    while True:
        body = {"query": args.query, "pageSize": page_size, "offsetMark": offset,
                "sorts": [{"field": "score", "sortOrder": "DESC"}]}
        r = request(f"{BASE}/search", body)
        total = max(total, r.get("count", 0))  # the last page reports 0
        hits += r.get("results", [])
        offset = r.get("offsetMark")
        if not args.all or not offset or not r.get("results") or len(hits) >= args.limit:
            break
    hits = hits[: args.limit if args.all else args.n]
    print(f"{total} results; showing {len(hits)}\n")

    def cite_of(hit):
        cite, cmd = cite_for(hit.get("packageId"), hit.get("granuleId"))
        return rule_cites.get(hit.get("granuleId"), cite), cmd

    if args.grep:
        pattern = re.compile(args.grep, re.I)

        def fetch(hit):
            if hit.get("collectionCode") == "CFR" and hit.get("granuleId"):
                return None, hit_lines(hit)
            raw = raw_lines(hit)
            return raw, (hit_lines(hit, raw) if raw is not None else None)
        fetched = [f or (None, None) for f in parallel(fetch, hits)]
        texts = [lines for _, lines in fetched]
        rule_cites = appendix_rule_cites(hits, [raw for raw, _ in fetched])
        misses = []
        for hit, lines in zip(hits, texts):
            cite, cmd = cite_of(hit)
            label = f"{cite or hit.get('packageId')} — {hit.get('title', '')}"
            label += f"   [{hit.get('dateIssued', '')}]" + (f"  → {cmd}" if cmd else "")
            if not print_grep(label, lines, pattern, args.lines):
                misses.append(cite or hit.get("granuleId") or hit.get("packageId"))
        if misses:
            print(f"No match for /{args.grep}/ in the text of: {', '.join(misses)}")
    else:
        rule_cites = appendix_rule_cites(hits)
        for hit in hits:
            cite, cmd = cite_of(hit)
            print(hit.get("title", "(untitled)"))
            if cite:
                print(f"  cite:    {cite}" + (f"   → {cmd}" if cmd else ""))
            print(f"  date:    {hit.get('dateIssued', '')}   collection: {hit.get('collectionCode', '')}")
            print(f"  package: {hit.get('packageId', '')}")
            if hit.get("granuleId"):
                print(f"  granule: {hit['granuleId']}")
            print()
    if offset and not args.all and len(hits) < total:
        print(f"next page: --offset '{offset}'   (or use --all)")


def summary_url(package, granule):
    if granule:
        return f"{BASE}/packages/{package}/granules/{granule}/summary"
    return f"{BASE}/packages/{package}/summary"


def summary(args):
    print(json.dumps(request(summary_url(args.package, args.granule)), indent=2))


def strip_html(markup):
    markup = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", markup)
    markup = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</h\d>|</li>", "\n", markup)
    text = html.unescape(re.sub(r"<[^>]+>", "", markup))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def text(args):
    info = request(summary_url(args.package, args.granule))
    link = info.get("download", {}).get("txtLink")
    if not link:
        sys.exit("no text rendition available; try `summary` for PDF and XML links")
    body = strip_html(request(link, raw=True))
    print(body[: args.max])
    if len(body) > args.max:
        print(f"\n[truncated at {args.max} of {len(body)} characters; raise --max]")


def granules(args):
    r = request(f"{BASE}/packages/{args.package}/granules?offsetMark=*&pageSize={args.n}")
    for g in r.get("granules", []):
        print(f"{g['granuleId']}\n  {g.get('title', '')}")
    print(f"\n{r.get('count', 0)} granules total")


# --- U.S. Code: GPO edition via GovInfo's link service, current text via the
# Office of the Law Revision Counsel (uscode.house.gov). Both publish the same
# OLRC-generated HTML, with <!-- field-start:NAME --> markers around each part.

def field(markup, name):
    m = re.search(rf"<!-- field-start:{name} -->(.*?)<!-- field-end:{name} -->", markup, re.S)
    return strip_html(m.group(1)) if m else ""


def gpo_section(title, section, year=None):
    """A U.S. Code section from GovInfo: the latest GPO edition, or the edition for `year`."""
    link = f"{LINK}/uscode/{title}/{section}?link-type=html" + (f"&year={year}" if year else "")
    url = redirect_target(link)
    m = re.search(r"/pkg/(USCODE-(\d{4})-[^/]+)/html/([^/?#]+)\.htm", url or "")
    markup = fetch_page(url)[1] if m else ""
    if not m or "field-start:statute" not in markup:
        edition = f" in the {year} edition" if year else ""
        sys.exit(f"GovInfo has no U.S. Code text for {title} U.S.C. {section}{edition}. The section "
                 "may not exist, or may have been repealed, transferred, or omitted from the Code; "
                 "check uscode.house.gov, or find where it went with: search 'collection:USCODE "
                 f"\"{title} U.S.C. {section}\"'")
    return {"package": m.group(1), "edition": int(m.group(2)), "granule": m.group(3), "html": markup}


def olrc_section(title, section):
    url = f"{OLRC}?req=granuleid:USC-prelim-title{title}-section{section}&num=0&edition=prelim"
    _, markup = fetch_page(url)
    if "field-start:statute" not in markup:
        sys.exit(f"uscode.house.gov returned no text for {title} U.S.C. {section}")
    m = re.search(r"laws in effect on ([A-Z][a-z]+ \d{1,2}, \d{4})", markup)
    return {"url": url, "in_effect": m.group(1) if m else "unknown date", "html": markup}


_positive_law = {}


def positive_law_titles():
    """{title: True/False}: which U.S. Code titles Congress has enacted as positive law.
    Read live from the OLRC download page, which marks those titles with a footnote."""
    if not _positive_law:
        _, page = fetch_page(OLRC_DOWNLOAD)
        for number, mark in re.findall(
                r'Title (\d+[A-Za-z]?) - [^<\n]+?\s*(<span class="footnote">)?\s*<', page):
            _positive_law.setdefault(number, bool(mark))
    return _positive_law


def positive_law_note(title):
    try:
        enacted = positive_law_titles().get(str(title))
    except SystemExit:
        enacted = None
    if enacted is None:
        return f"Title {title}: couldn't confirm whether it has been enacted as positive law."
    if enacted:
        return (f"Title {title} is positive law: this text is itself legal evidence of the law "
                "(1 U.S.C. 204(a)).")
    return (f"Title {title} is NOT positive law: the Code is only prima facie evidence of the law, "
            "and the Statutes at Large control where they differ (1 U.S.C. 204(a)). "
            "For the enacted wording, check the public law.")


def usc_editions():
    """Every U.S. Code edition as (in-effect date, GovInfo year, label), oldest first,
    from the edition menu on uscode.house.gov. GovInfo files each edition under the
    year before its in-effect date: the 2018 Main Ed. (1/14/2019) is USCODE-2018."""
    _, page = fetch_page(OLRC_BROWSE)
    found = set()
    for label, month, day, year in re.findall(
            r"(\d{4} (?:Main Ed\.|Ed\. and Supplement [IVX]+)) \((\d{1,2})/(\d{1,2})/(\d{4})\)", page):
        found.add((f"{year}-{int(month):02d}-{int(day):02d}", int(year) - 1, label))
    if not found:
        sys.exit("couldn't read the list of U.S. Code editions from uscode.house.gov")
    return sorted(found)


def check_date(value):
    if not re.fullmatch(r"\d{4}-\d\d-\d\d", value or ""):
        sys.exit(f"dates are YYYY-MM-DD, like 2019-06-01 (got {value!r})")
    return value


# --- Pinpoint citations: pull (b)(6) out of a section's paragraphs.

ROMAN = [(1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"),
         (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")]


def roman_to_int(s):
    s, total = s.lower(), 0
    for value, numeral in ROMAN:
        while s.startswith(numeral):
            total, s = total + value, s[len(numeral):]
    return total if not s else None


def int_to_roman(n):
    out = ""
    for value, numeral in ROMAN:
        while n >= value:
            out, n = out + numeral, n - value
    return out


def pin_tokens(pin):
    tokens = re.findall(r"\(([A-Za-z0-9]{1,6})\)", pin or "")
    if not tokens or "".join(f"({t})" for t in tokens) != re.sub(r"\s+", "", pin):
        sys.exit(f"a pinpoint looks like (b)(6) or (a)(1)(i) (got {pin!r})")
    return tokens


def token_kinds(tokens):
    """Label each pinpoint level. Lowercase i, v, x are letters at the top level and
    roman numerals below it; uppercase I, V, X are roman only right under a roman level."""
    kinds = []
    for tok in tokens:
        prev = kinds[-1] if kinds else None
        if tok.isdigit():
            kinds.append("num")
        elif re.fullmatch(r"\d+[A-Z]+", tok):
            kinds.append("numalpha")  # inserted paragraphs: (10A), (51D)
        elif tok.islower():
            kinds.append("lroman" if prev and roman_to_int(tok) else "lower")
        elif tok.isupper():
            kinds.append("uroman" if prev == "lroman" and roman_to_int(tok) else "upper")
        else:
            kinds.append("other")
    return kinds


def next_siblings(tok, kind):
    """Designations that can follow `tok` at the same level: (6) is followed by (7) or an
    inserted (6A); (10A) by (10B) or (11)."""
    if kind == "num":
        return {str(int(tok) + 1), tok + "A"}
    if kind == "numalpha":
        number, suffix = re.fullmatch(r"(\d+)([A-Z]+)", tok).groups()
        return {str(int(number) + 1), number + suffix[:-1] + chr(ord(suffix[-1]) + 1)}
    if kind in ("lroman", "uroman"):
        nxt = int_to_roman(roman_to_int(tok) + 1)
        return {nxt if kind == "lroman" else nxt.upper()}
    if kind in ("lower", "upper") and len(set(tok)) == 1:  # a -> b, aa -> bb
        return {chr(ord(tok[0]) + 1) * len(tok)}
    return set()


def leading_tokens(line):
    """The paragraph designations a line opens with. A leading "[" is allowed, as in
    "[(j) Repealed. Pub. L. 97-248 ...]"."""
    m = re.match(r"\[?((?:\([A-Za-z0-9]{1,6}\))+)", line)
    return re.findall(r"\(([A-Za-z0-9]+)\)", m.group(1)) if m else []


def is_table_row(line):
    return line.rstrip().endswith("|") or " | " in line


def is_roman_here(lines, idx, tok, since):
    """Is the "(i)", "(v)", or "(x)" at lines[idx] a roman numeral rather than the next
    top-level letter? `since` is the index of the last top-level paragraph.
    Look back: "(iv)" before a "(v)", or "(ix)" before an "(x)", since that paragraph
    means the roman list is continuing. Then look at the next numbered line: (ii)/(vi)/
    (xi) or a child like (A) or (I) means roman; (j)/(w)/(y) or a child (1) means the
    letter, which starts its own subparagraphs at (1)."""
    value = roman_to_int(tok)
    if value > 1:
        before = int_to_roman(value - 1)
        if any(before in leading_tokens(line) for line in lines[since + 1:idx]):
            return True
    roman_next, letter_next = int_to_roman(value + 1), chr(ord(tok) + 1)
    for line in lines[idx + 1:]:
        toks = leading_tokens(line)
        if not toks or is_table_row(line):
            continue
        first = toks[0]
        if first == roman_next or (first.isupper() and first in ("A", "I")):
            return True
        if first in (letter_next, "1"):
            return False
        return False  # anything else: take it as the letter
    return False


def top_levels(lines):
    """[(index, designation)] for a section's top-level paragraphs. Most run (a), (b),
    (c); definition sections such as 11 U.S.C. 101 run (1), (2), (2A), (3). Stray "(i)"s
    further down are roman numerals, and table rows (a contents table) are skipped."""
    tops, style = [], None
    for i, line in enumerate(lines):
        if is_table_row(line):
            continue
        toks = leading_tokens(line)
        if not toks:
            continue
        tok = toks[0]
        if style is None:
            style = {"a": "letter", "1": "number"}.get(tok)
            if style:
                tops.append((i, tok))
            continue
        last = tops[-1][1]
        if style == "letter":
            ok = len(tok) == 1 and tok.islower() and tok == chr(ord(last) + 1)
            if ok and tok in "ivx" and is_roman_here(lines, i, tok, tops[-1][0]):
                ok = False  # a roman numeral inside the previous subsection
        else:
            m, lm = re.fullmatch(r"(\d+)([A-Z]*)", tok), re.fullmatch(r"(\d+)([A-Z]*)", last)
            ok = bool(m) and (int(m[1]), m[2]) > (int(lm[1]), lm[2])
        if ok:
            tops.append((i, tok))
    return tops


def pinpoint(lines, pin):
    """The lines making up one pinpointed provision, e.g. (b)(6); None if not found.
    Second value is True when unnumbered text at the end may belong to a higher level."""
    want = pin_tokens(pin)
    kinds = token_kinds(want)
    tops = top_levels(lines)
    starts = [i for i, tok in tops if tok == want[0]]
    if not starts:
        return None, False
    top_at = starts[0]
    top_end = next((i for i, _ in tops if i > top_at), len(lines))

    # Walk down from the top-level paragraph, one level at a time. A line can open
    # several levels at once ("(1)(A) text").
    start, depth = None, 1
    toks = leading_tokens(lines[top_at])
    j = 1
    while j < len(toks) and depth < len(want) and toks[j] == want[depth]:
        depth, j = depth + 1, j + 1
    if depth == len(want):
        start = top_at
    else:
        for k in range(top_at + 1, top_end):
            toks = leading_tokens(lines[k])
            if not toks or is_table_row(lines[k]):
                continue
            j = 0
            while j < len(toks) and depth < len(want) and toks[j] == want[depth]:
                depth, j = depth + 1, j + 1
            if depth == len(want):
                start = k
                break
            passed = set().union(*(next_siblings(want[m], kinds[m]) for m in range(1, depth)))
            if j == 0 and toks[0] in passed:
                return None, False  # reached a sibling of a matched level: not here
    if start is None:
        return None, False

    own_next = next_siblings(want[-1], kinds[-1])
    stops = set().union(*(next_siblings(t, k) for t, k in zip(want, kinds)))
    out, ended_by_own_sibling = [lines[start]], False
    for line in lines[start + 1:top_end]:
        toks = leading_tokens(line)
        if (toks and toks[0] in stops) or re.match(r"\[\d+ FR \d+", line):
            ended_by_own_sibling = bool(toks) and toks[0] in own_next
            break
        out.append(line)
    # Unnumbered text after the last numbered paragraph belongs to the pinpoint only if
    # its own next sibling follows. If a higher level's sibling (or the end) follows, the
    # text may be flush language closing that higher level, like the sentence after 5
    # U.S.C. 552(b)(9) that governs all of subsection (b).
    trailing_unnumbered = len(out) > 1 and not leading_tokens(out[-1])
    return out, len(want) > 1 and trailing_unnumbered and not ended_by_own_sibling


def split_inline_paragraphs(lines):
    """CFR runs paragraphs into their parent's heading, after a dash ("(e) Methods—(1)
    Milk—(i) Milkfat. ...") or a period ("(i) Trade secrets. (1) The chemical ...").
    Split them so each numbered paragraph starts its own line. After a period, split
    only before a list's first item, (1), (i), (A), or (a), so a sentence that merely
    ends near a cross-reference isn't cut."""
    out = []
    for line in lines:
        for part in re.split(r"(?<=[—–-])\s*(?=\([A-Za-z0-9]{1,6}\) )", line):
            out += [p for p in re.split(r"(?<=\.)\s+(?=\((?:1|i|A|a)\) [A-Z])", part) if p]
    return out


def print_pinpoint(cite, lines, pin):
    found, flush = pinpoint(lines, pin)
    if found is None:
        seen = ", ".join(f"({tok})" for _, tok in top_levels(lines)) or "none found"
        sys.exit(f"no {pin} in {cite}. Top-level paragraphs: {seen}")
    print(cite + pin.replace(" ", "") + "\n")
    print("\n\n".join(found))
    if flush:
        print("\n[Unnumbered text at the end may be flush language belonging to a higher level; "
              "check it against the full section.]")


def normalized_lines(text):
    # Dashes and spacing differ cosmetically between the two sites.
    lines = []
    for line in text.splitlines():
        line = re.sub(r"[‐-―−-]", "-", line)
        line = re.sub(r" (?=[),.;:\]])", "", re.sub(r"\s+", " ", line)).strip()
        if line:
            lines.append(line)
    return lines


def flatten(lines):
    # Line breaks also differ (e.g. inside "[Repealed ...]" brackets).
    return re.sub(r" (?=[),.;:\]])", "", " ".join(lines))


def public_laws(source_credit):
    return [f"{a}-{b}" for a, b in re.findall(r"Pub\. L\. (\d+)[‐-―-](\d+)", source_credit)]


def amendments_by_year(notes):
    years, current = {}, None
    for line in notes.splitlines():
        m = re.match(r"\s*((?:19|20)\d\d)\s*[‐-―-]\s*(.*)", line)
        if m:
            current = int(m.group(1))
            line = m.group(2)
        if current and line.strip():
            years.setdefault(current, []).append(line.strip())
    return years


def laws_after_edition(title, section, edition_html):
    """Public laws in the section's current source credit that the edition's source
    credit lacks, with their enactment dates: [(\"116-92\", \"2019-12-20\"), ...]."""
    current = olrc_section(title, section)
    have = set(public_laws(field(edition_html, "sourcecredit")))
    later = [pl for pl in public_laws(field(current["html"], "sourcecredit")) if pl not in have]

    def enacted(pl):
        congress, number = pl.split("-")
        return request(summary_url(f"PLAW-{congress}publ{number}", None)).get("dateIssued")
    return list(zip(later, parallel(enacted, later)))


def usc(args):
    cite = f"{args.title} U.S.C. {args.section}"
    edition = None
    if args.as_of:
        as_of = check_date(args.as_of)
        editions = [e for e in usc_editions() if e[0] <= as_of]
        if not editions:
            sys.exit(f"GovInfo's U.S. Code editions start with the 1994 edition (laws in effect "
                     f"Jan. 4, 1995). For {as_of}, use the Statutes at Large (collection STATUTE).")
        edition = editions[-1]
    gpo = gpo_section(args.title, args.section, year=edition[1] if edition else None)

    if edition:
        print(f"{cite} as of {args.as_of} — {edition[2]}, laws in effect as of {edition[0]} "
              f"({gpo['package']} / {gpo['granule']})")
    else:
        print(f"{cite} — GPO {gpo['edition']} edition ({gpo['package']} / {gpo['granule']})")
    print(positive_law_note(args.title) + "\n")

    if args.pin:
        print_pinpoint(cite, [ln for ln in field(gpo["html"], "statute").splitlines() if ln.strip()],
                       args.pin)
    else:
        parts = ["head", "statute", "sourcecredit"] + (["notes"] if args.notes else [])
        body = "\n\n".join(filter(None, (field(gpo["html"], p) for p in parts)))
        print(body[: args.max])
        if len(body) > args.max:
            print(f"\n[truncated at {args.max} of {len(body)} characters; raise --max, "
                  "or use --pin for one subsection]")

    if edition:
        # The edition is a snapshot at its in-effect date; flag laws enacted between
        # that snapshot and the requested date, which its text can't reflect.
        gap = [(pl, d) for pl, d in laws_after_edition(args.title, args.section, gpo["html"])
               if d is None or edition[0] < d <= args.as_of]
        print()
        if not gap:
            print(f"AS-OF CHECK: no public law amending this section was enacted between "
                  f"{edition[0]} and {args.as_of}; the text above is the section as of {args.as_of} "
                  "(subject to effective-date provisions in the amending laws).")
        else:
            for pl, d in gap:
                when = f"enacted {d}" if d else "enactment date not found"
                print(f"AS-OF CHECK: Pub. L. {pl} ({when}) amended this section after this edition "
                      f"and may have taken effect by {args.as_of}; the text above does not reflect it. "
                      f"Read it with: plaw {pl} --grep 'section {args.section}'")


def currency(args):
    cite = f"{args.title} U.S.C. {args.section}"
    gpo = gpo_section(args.title, args.section)
    olrc = olrc_section(args.title, args.section)

    print(cite)
    print(f"  GPO edition:       {gpo['edition']} ({gpo['package']} / {gpo['granule']})")
    print(f"  uscode.house.gov:  laws in effect on {olrc['in_effect']}")
    print(f"  {olrc['url']}")
    print(f"  {positive_law_note(args.title)}\n")

    old = normalized_lines(field(gpo["html"], "statute"))
    new = normalized_lines(field(olrc["html"], "statute"))
    same_text = flatten(old) == flatten(new)
    if same_text:
        print("Statute text: identical (ignoring dash, spacing, and line-break differences)")
    else:
        print("Statute text: DIFFERENT — lines marked - are GPO, + are current:")
        diff = [line for line in difflib.unified_diff(old, new, n=0, lineterm="")
                if not line.startswith(("---", "+++", "@@"))]
        for line in diff[: args.diff]:
            print(f"  {line[:400]}")
        if len(diff) > args.diff:
            print(f"  [{len(diff) - args.diff} more changed lines; raise --diff]")

    added = [pl for pl in public_laws(field(olrc["html"], "sourcecredit"))
             if pl not in public_laws(field(gpo["html"], "sourcecredit"))]
    print("Source credit: " + (f"NEW since GPO edition: Pub. L. {', '.join(added)}"
                               if added else "no public laws beyond the GPO edition"))

    notes = amendments_by_year(field(olrc["html"], "amendment-note"))
    print("Amendment notes (years): " + (", ".join(map(str, sorted(notes))) or "none"))
    recent = {y: n for y, n in notes.items() if y >= gpo["edition"]}
    for year in sorted(recent):
        print(f"\n{year} amendments (may postdate the GPO edition):")
        for line in recent[year]:
            print(f"  {line[:600]}")

    print()
    if same_text and not added:
        print(f"VERDICT: no change since the GPO {gpo['edition']} edition, "
              f"through laws in effect on {olrc['in_effect']}.")
    else:
        print(f"VERDICT: the section has changed since the GPO {gpo['edition']} edition; "
              "quote the current text from uscode.house.gov.")


# --- CFR: annual GPO edition via GovInfo's link service, current text and
# point-in-time history via the eCFR versioner API (ecfr.gov).

def ecfr_json(path):
    return json.loads(fetch_page(f"{ECFR}/{path}")[1])


def cfr_xml_text(xml):
    """Readable text from GPO or eCFR section XML, one paragraph per line."""
    xml = re.sub(r"(?is)<FDSYS>.*?</FDSYS>|<PRTPAGE[^>]*/?>", "", xml)
    xml = re.sub(r"\s+", " ", xml)  # GPO's XML is pretty-printed inside paragraphs
    xml = re.sub(r"(?i)</(t[dh]|ent)>", " | ", xml)
    xml = re.sub(r"(?i)</(p|head|hed|hd\d?|fp|cita|note|subject|tr|row|auth|source)>", "\n", xml)
    text = html.unescape(re.sub(r"<[^>]+>", "", xml))
    lines = (re.sub(r"\s+", " ", line).strip() for line in text.splitlines())
    return [line for line in lines if line]


# A CFR "unit" is one section or one appendix (including supplements such as
# "Supplement I to Part 1026"). Every CFR command works on a unit.

def ecfr_appendices(title, part):
    """eCFR identifiers of every appendix in a part, e.g. "Appendix A to Part 210"."""
    tree = ecfr_json(f"structure/{ecfr_current(title)}/title-{title}.json?part={part}")
    found = []

    def walk(node):
        if node.get("type") == "appendix" and node.get("identifier"):
            found.append(node["identifier"])
        for child in node.get("children") or []:
            walk(child)
    walk(tree)
    return found


def resolve_appendix(title, part, wanted):
    """Match "A", "M1", "Supplement I", or a full identifier to eCFR's identifier."""
    idents = ecfr_appendices(title, part)
    w = re.sub(r"\s+", " ", wanted).strip().lower()
    exact = [i for i in idents if i.lower() == w]
    matches = exact or [i for i in idents
                        if re.match(rf"(appendix )?{re.escape(w)} to ", i.lower())]
    if len(matches) == 1:
        return matches[0]
    listing = "\n  ".join(idents) or "(none)"
    why = "is ambiguous" if matches else "matches nothing"
    sys.exit(f'"{wanted}" {why} in {title} CFR part {part}. Its appendices in eCFR:\n  {listing}\n'
             f'Pass one of these (or the part of it before " to"), e.g. --appendix "{idents[0] if idents else "A"}"')


def cfr_unit(title, spec, appendix=None, command="cfr"):
    if appendix is None:
        part, _, num = spec.partition(".")
        if not num:
            sys.exit(f"give a section number with its part, like: {command} 5 2635.502 "
                     f"(or a part with --appendix, like: {command} 7 210 --appendix A)")
        return {"title": title, "part": part, "section": spec, "appendix": None,
                "cite": f"{title} CFR {spec}",
                "url": f"https://www.ecfr.gov/current/title-{title}/section-{spec}",
                "query": urllib.parse.urlencode({"part": part, "section": spec})}
    part = spec
    if "." in part:
        sys.exit(f"with --appendix, give the part alone, like: {command} {title} {part.split('.')[0]} "
                 f"--appendix {appendix}")
    ident = resolve_appendix(title, part, appendix)
    label = re.sub(r" to (Subpart \S+ of )?Part \S+$", "", ident)
    return {"title": title, "part": part, "section": None, "appendix": ident,
            "cite": f"{title} CFR part {part}, {label}",
            "url": f"https://www.ecfr.gov/current/title-{title}/part-{part}/appendix-"
                   + urllib.parse.quote(ident),
            "query": urllib.parse.urlencode({"part": part, "appendix": ident})}


def ecfr_text(unit, date):
    """A unit's text as eCFR shows it on a date; None if absent."""
    _, xml = fetch_page(f"{ECFR}/full/{date}/title-{unit['title']}.xml?{unit['query']}",
                        allow_missing=True)
    return None if xml is None else cfr_xml_text(xml)


def ecfr_lines(unit, date):
    text = ecfr_text(unit, date)
    return None if text is None else normalized_lines("\n".join(text))


def package_granules(package):
    """Every granule ID in a GovInfo package, in the package's order."""
    ids, offset = [], "*"
    while True:
        r = request(f"{BASE}/packages/{package}/granules?offsetMark={offset}&pageSize=1000")
        ids += [g["granuleId"] for g in r.get("granules", [])]
        m = re.search(r"offsetMark=([^&]+)", r.get("nextPage") or "")
        if not m or not r.get("granules"):
            return ids
        offset = urllib.parse.unquote(m[1])


def gpo_heading(xml):
    """The heading GPO's XML gives a granule; "" for a continuation of the previous one."""
    m = re.search(r'<HD SOURCE="HED">(.*?)</HD>', xml, re.S)
    if m is None:
        m = re.search(r"<TITLE>(.*?)</TITLE>", xml, re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", m[1] if m else ""))).strip()


def same_heading(heading, ident):
    norm = lambda s: re.sub(r"[\s‐-―-]+", " ", s).strip().lower()
    return norm(heading).startswith(norm(ident))


def annual_cfr(unit, year="mostrecent"):
    """The unit in the most recent annual CFR edition on GovInfo:
    {"package", "granules", "revised"}. An appendix can span several granules
    (GPO splits long ones, e.g. Supplement I to Part 1026), and GPO sometimes
    files one under another appendix's name, so appendices are matched by the
    heading inside the XML, not by granule ID."""
    title, part = unit["title"], unit["part"]
    if unit["section"]:
        num = unit["section"].partition(".")[2]
        link = f"{LINK}/cfr/{title}/{part}?sectionnum={num}&year={year}&link-type=pdf"
    else:
        link = f"{LINK}/cfr/{title}/{part}?year={year}&link-type=pdf"
    m = re.search(r"/pkg/(CFR-\d{4}-[^/]+)/pdf/([^/?#]+)\.pdf", redirect_target(link) or "")
    if not m and unit["section"] and "(" in unit["section"]:
        m = find_cfr_granule(title, part, unit["section"], year)
    if not m:
        sys.exit(f"GovInfo has no annual CFR text for {unit['cite']}")
    package, granule = m.groups()
    if unit["section"]:
        granules = [granule]
    else:
        prefix = f"{package}-part{part}-app"
        candidates = [g for g in package_granules(package) if g.startswith(prefix)]
        letter = re.match(r"Appendix (\S+) to", unit["appendix"])
        direct = f"{prefix}{letter[1]}" if letter else None
        xml = {}
        if direct in candidates:  # the common case: one fetch settles it
            xml[direct] = request(f"{BASE}/packages/{package}/granules/{direct}/xml", raw=True)
        if not (direct in xml and same_heading(gpo_heading(xml[direct]), unit["appendix"])):
            fetched = parallel(lambda g: request(
                f"{BASE}/packages/{package}/granules/{g}/xml", raw=True), candidates)
            xml.update({g: x for g, x in zip(candidates, fetched) if x})
        granules = []
        for g in candidates:
            if g not in xml:
                continue
            heading = gpo_heading(xml[g])
            if same_heading(heading, unit["appendix"]):
                granules = [g]
            elif granules and granules[-1] == candidates[candidates.index(g) - 1] and not heading:
                granules.append(g)  # continuation of the matched appendix
            elif granules:
                break
        if not granules:
            sys.exit(f"The annual CFR on GovInfo ({package}) has no text for {unit['cite']} "
                     f"(it may be reserved there); try --current")
        unit["_xml"] = [xml[g] for g in granules]
    revised = request(summary_url(package, granules[0]))["dateIssued"]
    return {"package": package, "granules": granules, "revised": revised}


_ecfr_titles = {}


def ecfr_current(title):
    """The date eCFR's text of a title is up to date as of."""
    if not _ecfr_titles:
        _ecfr_titles.update({str(t["number"]): t for t in ecfr_json("titles.json")["titles"]})
    if str(title) not in _ecfr_titles:
        sys.exit(f"eCFR has no title {title}")
    return _ecfr_titles[str(title)]["up_to_date_as_of"]


def find_cfr_granule(title, part, section, year):
    """GovInfo's link service can't resolve sections with parentheses, like the tax
    regulation 26 CFR 1.401(k)-1, though GovInfo has them, filed with the parentheses
    dropped (…-sec1-401k-1). Find the edition's year from the part, then try that
    granule in each volume of the title at once. Returns a match whose groups() are
    (package, granule), or None."""
    target = redirect_target(f"{LINK}/cfr/{title}/{part}?year={year}&link-type=pdf") or ""
    found = re.search(r"/pkg/CFR-(\d{4})-title", target)
    if not found:
        return None
    edition = found[1]
    suffix = "sec" + section.replace(".", "-").replace("(", "").replace(")", "")

    def probe(volume):
        package = f"CFR-{edition}-title{title}-vol{volume}"
        request(summary_url(package, f"{package}-{suffix}"))  # exits (caught) if absent
        return package
    hits = [p for p in parallel(probe, range(1, 61), workers=8) if p]
    if not hits:
        return None
    return re.match(r"(.*)\|(.*)", f"{hits[0]}|{hits[0]}-{suffix}")


def ecfr_changes(unit, since):
    """eCFR's currency date for the title, and the unit's versions dated after `since`."""
    current = ecfr_current(unit["title"])
    versions = ecfr_json(f"versions/title-{unit['title']}.json?{unit['query']}")["content_versions"]
    later = sorted((v for v in versions if v["date"] > since), key=lambda v: v["date"])
    return current, later


def fr_documents(title, part, since=None, until=None, rules_only=True, n=20):
    """Federal Register documents that affect a CFR part (federalregister.gov API)."""
    params = [("conditions[cfr][title]", title), ("conditions[cfr][part]", part),
              ("order", "newest"), ("per_page", n)]
    if since:
        params.append(("conditions[publication_date][gte]", since))
    if until:
        params.append(("conditions[publication_date][lte]", until))
    if rules_only:
        params.append(("conditions[type][]", "RULE"))
    for f in ("title", "type", "citation", "publication_date", "effective_on",
              "document_number", "html_url", "action"):
        params.append(("fields[]", f))
    data = json.loads(fetch_page(f"{FEDREG}?{urllib.parse.urlencode(params)}")[1])
    return data.get("count", 0), data.get("results") or []


def fr_line(doc):
    eff = f", effective {doc['effective_on']}" if doc.get("effective_on") else ""
    return (f"{doc.get('citation') or '(no FR cite yet)'} ({doc['publication_date']}{eff}) "
            f"[{doc.get('type', '')}] {doc.get('title', '')} — FR Doc. {doc['document_number']}")


def cfr_currency(args):
    unit = cfr_unit(args.title, args.section, args.appendix, "cfr-currency")
    title, part, cite = unit["title"], unit["part"], unit["cite"]
    annual = annual_cfr(unit)
    package, revised = annual["package"], annual["revised"]
    current, later = ecfr_changes(unit, revised)

    print(cite)
    print(f"  Annual CFR (GPO):  revised as of {revised} ({package} / {', '.join(annual['granules'])})")
    print(f"  eCFR:              up to date as of {current}")
    print(f"  {unit['url']}\n")

    if not later:
        print(f"eCFR changes after {revised}: none")
    else:
        print(f"eCFR changes after {revised}:")
        for v in later:
            flags = [f for f, on in (("substantive", v["substantive"]), ("removed", v["removed"]),
                                     ("effective in the future", v["date"] > current)) if on]
            print(f"  {v['date']}  (published {v['issue_date']}; {', '.join(flags) or 'non-substantive'})")

        old = ecfr_lines(unit, revised)
        new = ecfr_lines(unit, current)
        noun = "section" if unit["section"] else "appendix"
        if old is None:
            print(f"\nThe {noun} did not exist in eCFR on {revised}.")
        elif new is None:
            print(f"\nThe {noun} is not in eCFR as of {current} (removed or moved).")
        elif flatten(old) == flatten(new):
            print("\nText: no wording change between those dates.")
        else:
            print(f"\nText: lines marked - are as of {revised}, + are as of {current}:")
            diff = [line for line in difflib.unified_diff(old, new, n=0, lineterm="")
                    if not line.startswith(("---", "+++", "@@"))]
            for line in diff[: args.diff]:
                print(f"  {line[:400]}")
            if len(diff) > args.diff:
                print(f"  [{len(diff) - args.diff} more changed lines; raise --diff]")

        # Which Federal Register rules explain those versions? A rule published
        # before the revision date can take effect after it, so look back a year.
        since = f"{int(revised[:4]) - 1}{revised[4:]}"
        _, docs = fr_documents(title, part, since=since, n=50)
        version_dates = {v["date"] for v in later}
        matched = [d for d in docs if d.get("effective_on") in version_dates
                   or d.get("publication_date") in version_dates]
        print(f"\nFederal Register rules affecting {title} CFR part {part} "
              f"that match these versions (by effective or publication date):")
        for d in matched:
            print(f"  {fr_line(d)}")
        unexplained = sorted(version_dates - {d.get("effective_on") for d in matched}
                             - {d.get("publication_date") for d in matched})
        if not matched:
            print("  none")
        if unexplained:
            print(f"  No rule matches the eCFR version(s) dated {', '.join(unexplained)}. "
                  "That usually means an editorial correction by eCFR, not a new rule; "
                  f"run `fr-rules {title} {part}` to see every rule affecting the part.")

    print()
    if not later:
        print(f"VERDICT: no change since the annual CFR revised as of {revised}, "
              f"through eCFR up to date as of {current}.")
    else:
        print(f"VERDICT: amended since the annual CFR revised as of {revised} "
              f"(latest eCFR version {later[-1]['date']}); quote the current eCFR text.")


ECFR_START = "2017-01-03"  # eCFR's point-in-time history begins here


def annual_cfr_as_of(unit, as_of):
    """The latest annual CFR edition of a unit revised on or before `as_of`."""
    year = int(as_of[:4])
    for y in (year, year - 1, year - 2):
        try:
            annual = annual_cfr(unit, year=y)
        except SystemExit:
            continue
        if annual["revised"] <= as_of:
            return annual
    sys.exit(f"GovInfo has no annual CFR edition of {unit['cite']} revised on or before {as_of} "
             "(its annual CFR starts in 1996).")


def cfr(args):
    unit = cfr_unit(args.title, args.section, args.appendix)
    cite = unit["cite"]
    as_of = check_date(args.as_of) if args.as_of else None
    if as_of and args.current:
        sys.exit("use --current or --as-of, not both")
    annual = None

    if args.current or (as_of and as_of >= ECFR_START):
        date = as_of or ecfr_current(unit["title"])
        lines = ecfr_text(unit, date)
        if lines is None:
            sys.exit(f"eCFR has no {cite} as of {date} (removed, moved, or not yet in effect)")
        if as_of:
            print(f"{cite} as of {as_of} — eCFR point-in-time text")
        else:
            print(f"{cite} — eCFR, up to date as of {date}")
        print("(eCFR is an editorial compilation, not an official legal edition of the CFR)")
        print(f"{unit['url']}\n")
    else:
        annual = annual_cfr_as_of(unit, as_of) if as_of else annual_cfr(unit)
        xmls = unit.get("_xml") or [
            request(f"{BASE}/packages/{annual['package']}/granules/{g}/xml", raw=True)
            for g in annual["granules"]]
        parents = re.findall(r'<PARENT HEADING="([^"]+)"[^>]*>([^<]*)</PARENT>', xmls[0])
        lines = [line for xml in xmls for line in cfr_xml_text(xml)]
        print((f"{cite} as of {as_of} — " if as_of else f"{cite} — ")
              + f"annual CFR revised as of {annual['revised']} "
              f"({annual['package']} / {', '.join(annual['granules'])})")
        if parents:
            print(" > ".join(f"{h}: {t.strip()}" for h, t in parents[1:]))
        print()

    if args.pin:
        print_pinpoint(cite, split_inline_paragraphs(lines), args.pin)
    elif args.grep:
        pattern = re.compile(args.grep, re.I)
        hits = [i for i, line in enumerate(lines) if pattern.search(line)][: args.lines]
        print(f"{len(hits)} matching paragraph(s) for /{args.grep}/"
              + (" (raise --lines for more)" if len(hits) == args.lines else "")
              + (f", each with the {args.context} paragraph(s) after it" if args.context else "") + "\n")
        for i in hits:
            print(f"· {matches_in([lines[i]], pattern, 1, width=300)[0]}")
            for follow in lines[i + 1: i + 1 + args.context]:
                print(f"    {follow[:800]}")
            print()
    else:
        body = "\n\n".join(lines)
        print(body[: args.max])
        if len(body) > args.max:
            print(f"\n[truncated at {args.max} of {len(body)} characters; raise --max, "
                  f"or use --grep to pull just the paragraphs you need]")

    if as_of and annual:
        # A pre-eCFR date: the annual edition is a snapshot at its revision date.
        # Rules published between that date and the requested one could have changed it.
        count, docs = fr_documents(unit["title"], unit["part"], since=annual["revised"],
                                   until=as_of, n=10)
        print()
        if not count:
            print(f"AS-OF CHECK: no final rule affecting {unit['title']} CFR part {unit['part']} was "
                  f"published between {annual['revised']} and {as_of}; the text above is the "
                  f"{'section' if unit['section'] else 'appendix'} as of {as_of}.")
        else:
            print(f"AS-OF CHECK: {count} final rule(s) affecting {unit['title']} CFR part {unit['part']} "
                  f"were published between {annual['revised']} and {as_of}. The text above doesn't "
                  "reflect any that changed this provision; check each:")
            for d in docs:
                print(f"  {fr_line(d)}")
    elif annual:
        current, later = ecfr_changes(unit, annual["revised"])
        print()
        if later:
            print(f"CURRENCY: AMENDED since this edition — {len(later)} eCFR version(s) after "
                  f"{annual['revised']}, latest {later[-1]['date']}. This text is out of date: "
                  f"rerun with --current for today's text, or cfr-currency for the changes.")
        else:
            print(f"CURRENCY: no change since this edition, through eCFR up to date as of {current}.")


def ecfr_search(args):
    """Search the current eCFR text; one row per section."""
    params = [("query", args.query), ("date", "current"), ("per_page", 100)]
    if args.title:
        params.append(("hierarchy[title]", args.title))
    seen, rows, page, total = set(), [], 1, 0
    while len(rows) < args.n:
        url = f"{ECFR_SEARCH}?{urllib.parse.urlencode(params + [('page', page)])}"
        data = json.loads(fetch_page(url)[1])
        total = data.get("meta", {}).get("total_count", 0)
        for r in data.get("results", []):
            h = r["hierarchy"]
            key = (h["title"], h.get("section") or h.get("appendix") or h.get("part"))
            if key not in seen:
                seen.add(key)
                rows.append(r)
        if page >= data.get("meta", {}).get("total_pages", 0):
            break
        page += 1
    rows = rows[: args.n]
    print(f"{len(seen)} sections in current eCFR ({total} matching versions); showing {len(rows)}\n")

    def unit_of(h):
        """A CFR unit built straight from eCFR's hierarchy (no lookups needed)."""
        t, part, sec, app = h["title"], h["part"], h.get("section"), demojibake(h.get("appendix"))
        if sec:
            return {"title": t, "part": part, "section": sec, "appendix": None,
                    "query": urllib.parse.urlencode({"part": part, "section": sec})}
        if app:
            return {"title": t, "part": part, "section": None, "appendix": app,
                    "query": urllib.parse.urlencode({"part": part, "appendix": app})}
        return None

    def cite_of(h):
        if h.get("section"):
            return f"{h['title']} CFR {h['section']}", f"cfr {h['title']} {h['section']} --current"
        if h.get("appendix"):
            app = demojibake(h["appendix"])
            label = re.sub(r" to (Subpart \S+ of )?Part \S+$", "", app)
            return (f"{h['title']} CFR part {h['part']}, {label}",
                    f"cfr {h['title']} {h['part']} --appendix \"{label}\" --current")
        return f"{h['title']} CFR part {h['part']}", None

    def heading_of(r):
        return demojibake(r["headings"].get("section") or r["headings"].get("appendix") or "")

    if args.grep:
        pattern = re.compile(args.grep, re.I)

        def fetch(r):
            unit = unit_of(r["hierarchy"])
            return ecfr_text(unit, ecfr_current(unit["title"])) if unit else None
        texts = parallel(fetch, rows)
        misses = []
        for r, lines in zip(rows, texts):
            cite, cmd = cite_of(r["hierarchy"])
            label = f"{cite} — {heading_of(r)}" + (f"  → {cmd}" if cmd else "")
            if not print_grep(label, lines, pattern, args.lines):
                misses.append(cite)
        if misses:
            print(f"No match for /{args.grep}/ in the current text of: {', '.join(misses)}")
        return

    for r in rows:
        h, heads = r["hierarchy"], r["headings"]
        cite, cmd = cite_of(h)
        print(f"{cite} — {demojibake(heads.get('section') or heads.get('appendix') or '')}")
        print(f"  {demojibake(heads.get('part') or '')}  (in effect since {r['starts_on']})"
              + (f"  → {cmd}" if cmd else ""))
        excerpt = re.sub(r"\s+", " ", demojibake(r.get("full_text_excerpt")))
        if excerpt:
            print(f"  · {excerpt[:400]}")
        print()


def fr_rules(args):
    count, docs = fr_documents(args.title, args.part, since=args.since, until=args.until,
                               rules_only=not args.all_types, n=args.n)
    kind = "documents" if args.all_types else "final rules"
    print(f"{count} Federal Register {kind} affecting {args.title} CFR part {args.part}"
          + (f" since {args.since}" if args.since else "") + (f" through {args.until}" if args.until else "")
          + f"; showing {len(docs)}, newest first\n")
    for d in docs:
        print(fr_line(d))
        pub = d["publication_date"]
        print(f"  → text FR-{pub} {d['document_number']}    {d.get('html_url', '')}\n")


def law_missing(kind, congress, number):
    message = f"GovInfo has no {kind} law {congress}-{number}."
    if int(congress) < 104:
        message += (" Its public and private laws start with the 104th Congress (1995). Earlier "
                    "laws are in the Statutes at Large, as scanned PDFs without text. With the "
                    "law's Stat. cite, get the PDF link from its page: for 81 Stat. 54, "
                    "summary STATUTE-81 STATUTE-81-Pg54.")
    return message


def plaw(args):
    m = re.fullmatch(r"(\d+)[-\s](\d+)", " ".join(args.law).strip())
    if not m:
        sys.exit("give the law as CONGRESS-NUMBER, like: plaw 119-21")
    congress, number = m.groups()
    kind = "private" if args.private else "public"
    target = redirect_target(f"{LINK}/plaw/{congress}/{kind}/{number}?link-type=html")
    pm = re.search(r"/pkg/(PLAW-\d+\w+?\d+)/", target or "")
    if not pm:
        sys.exit(law_missing(kind, congress, number))
    _, markup = fetch_page(target)
    info = request(summary_url(pm[1], None))
    body = strip_html(markup)
    stat = re.search(r"(\d+) STAT\. (\d+)", body)
    bill = re.search(r"\[((?:H\.\s*R\.|S\.|H\.\s*J\.\s*Res\.|S\.\s*J\.\s*Res\.)\s*\d+)\]", body)
    label = "Pub. L." if kind == "public" else "Priv. L."
    bill_name = re.sub(r"\s+", " ", bill[1]) if bill else None
    print(f"{label} {congress}-{number}" + (f", {stat[1]} Stat. {stat[2]}" if stat else "")
          + f" ({info.get('dateIssued', '')})"
          + (f" — enacted as {bill_name}" if bill_name else ""))
    print(f"{info.get('title', '')}")
    print(f"{info.get('pages', '?')} pages   package: {pm[1]}   {info.get('detailsLink', '')}\n")
    if args.grep:
        # The text is preformatted; rejoin each blank-line-separated paragraph.
        paras = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", body)]
        found = matches_in([p for p in paras if p], re.compile(args.grep, re.I), args.lines, width=300)
        print(f"{len(found)} matching paragraph(s) for /{args.grep}/" +
              (" (raise --lines for more)" if len(found) == args.lines else "") + "\n")
        for snippet in found:
            print(f"· {snippet}\n")
        return
    print(body[: args.max])
    if len(body) > args.max:
        print(f"\n[truncated at {args.max} of {len(body)} characters; raise --max]")


# --- Legislative history: GovInfo's "related documents" for a public law and its bill.

MONTHS = ["Jan.", "Feb.", "Mar.", "Apr.", "May", "June", "July", "Aug.", "Sept.", "Oct.",
          "Nov.", "Dec."]
BILL_TYPES = {"hr": "H.R.", "s": "S.", "hjres": "H.J. Res.", "sjres": "S.J. Res.",
              "hconres": "H. Con. Res.", "sconres": "S. Con. Res.", "hres": "H. Res.", "sres": "S. Res."}
# Record entries that only note a step (messages, enrollment, digests), not debate.
ROUTINE_RECORD = re.compile(
    r"MESSAGES? FROM|ENROLLED|APPROVED BY THE PRESIDENT|SIGNED|PRESENTED|ADDITIONAL COSPONSORS|"
    r"INTRODUCTION OF BILLS|PUBLIC BILLS AND RESOLUTIONS|REPORTS OF COMMITTEES|MEASURES? (REFERRED|"
    r"PLACED|READ)|EXECUTIVE AND OTHER COMMUNICATIONS|ORDERS? FOR|PRIVILEGES OF THE FLOOR|"
    r"AUTHORITY FOR COMMITTEES|NEW PUBLIC LAWS|DAILY DIGEST|CONSTITUTIONAL AUTHORITY|"
    r"COMMUNICATIONS? FROM THE CLERK|GENERAL LEAVE|ANNOUNCEMENT BY THE SPEAKER|MISSED VOTES?|"
    r"PERSONAL EXPLANATION", re.I)


def report_cite(citation):
    """GovInfo's "114 S.Rept. 4" as "S. Rep. No. 114-4" (and H.R. Rep., S. Doc., H.R. Doc.)."""
    m = re.fullmatch(r"(\d+) (S|H)\.(Rept|Doc)\. (\d+)", citation or "")
    if not m:
        return citation
    chamber = "S." if m[2] == "S" else "H.R."
    kind = "Rep." if m[3] == "Rept" else "Doc."
    return f"{chamber} {kind} No. {m[1]}-{m[4]}"


def long_date(d):
    y, m, day = d[:10].split("-")
    return f"{MONTHS[int(m) - 1]} {int(day)}, {y}"


def related(pid, collection=None):
    """GovInfo's related documents; {"message": ...} (no results) if GovInfo errored."""
    try:
        return request(f"{BASE}/related/{pid}" + (f"/{collection}" if collection else ""))
    except SystemExit as e:
        return {"message": str(e)}


def bill_label(package):
    m = re.match(r"BILLS-(\d+)([a-z]+?)(\d+)([a-z]+)$", package or "")
    return f"{BILL_TYPES.get(m[2], m[2])} {m[3]} ({m[1]}th Cong.)" if m else package


def history(args):
    m = re.fullmatch(r"(\d+)[-\s](\d+)", " ".join(args.law).strip())
    if not m:
        sys.exit("give the law as CONGRESS-NUMBER, like: history 114-185")
    congress, number = m.groups()
    kind = "pvtl" if args.private else "publ"
    pid = f"PLAW-{congress}{kind}{number}"
    try:
        info = request(summary_url(pid, None))
    except SystemExit:
        sys.exit(law_missing("private" if args.private else "public", congress, number))
    groups = {r["collection"]: r["relationship"] for r in related(pid).get("relationships", [])}
    fetched = dict(zip(groups, parallel(lambda c: related(pid, c).get("results", []), list(groups))))

    stat = next((r.get("citation") for r in fetched.get("STATUTE") or []), None)
    label = "Pub. L." if kind == "publ" else "Priv. L."
    print(f"Legislative history: {label} {congress}-{number}" + (f", {stat}" if stat else "")
          + f" (enacted {long_date(info['dateIssued'])})")
    print(f"{info.get('title', '')}\n")
    if not groups:
        print("GovInfo lists no related documents for this law (coverage is thin before the 1990s).")
        return

    bills = sorted(fetched.get("BILLS") or [], key=lambda r: r.get("dateIssued", ""))
    if bills:
        print(f"BILL: {bill_label(bills[-1]['packageId'])}")
        for b in bills:
            print(f"  {b.get('dateIssued', '')}  {b.get('billVersionLabel', b.get('billVersion', ''))}"
                  f"   → text {b['packageId']}")
        print()

    for coll, heading in (("CRPT", "COMMITTEE REPORTS"), ("CPRT", "COMMITTEE PRINTS"),
                          ("CPD", "PRESIDENTIAL SIGNING STATEMENTS AND REMARKS")):
        rows = sorted(fetched.get(coll) or [], key=lambda r: r.get("dateIssued", ""))
        if rows:
            print(heading)
            for r in rows:
                cite = report_cite(r.get("citation")) or r["packageId"]
                cmd = f"text {r['packageId']}" + (f" {r['granuleId']}" if r.get("granuleId")
                                                  and r["granuleId"] != r["packageId"] else "")
                doubt = ("  [dated before enactment; GovInfo may have linked the wrong document]"
                         if coll == "CPD" and r.get("dateIssued", "9") < info["dateIssued"] else "")
                print(f"  {r.get('dateIssued', '')}  {cite}: {r.get('title', '')}{doubt}   → {cmd}")
            print()

    # Floor proceedings hang off the bill, not the law.
    enrolled = next((b["packageId"] for b in reversed(bills) if b["packageId"].endswith("enr")),
                    bills[-1]["packageId"] if bills else None)
    bill_links = ({r["collection"] for r in related(enrolled).get("relationships", [])}
                  if enrolled else set())
    record_data = related(enrolled, "CREC") if "CREC" in bill_links else {}
    record = record_data.get("results", [])
    record_error = "CREC" in bill_links and not record and bool(record_data.get("message"))
    if record_error:
        # GovInfo lists a Record relationship, then errors out listing it; it does this
        # for bills with very long floor histories (e.g. H.R. 3590, the ACA).
        m = re.match(r"BILLS-(\d+)([a-z]+?)(\d+)", enrolled)
        bill = f"{BILL_TYPES.get(m[2], m[2])} {m[3]}" if m else enrolled
        print(f"CONGRESSIONAL RECORD: GovInfo returned an error listing the Record entries for "
              f"this bill (it does this for some bills with very long floor histories). Search "
              f"the Record directly; the congress filter matters, since bill numbers repeat:\n"
              f"  search 'collection:CREC congress:{m[1] if m else congress} \"{bill}\"' --all\n")
    if record:
        titles = parallel(lambda r: request(summary_url(r["packageId"], r["granuleId"])).get("title", ""),
                          record)
        entries = []
        for r, title in zip(record, titles):
            pages = r.get("pages") or {}
            prefix, start, end = r.get("pagePrefix", ""), pages.get("start", ""), pages.get("end", "")
            span = f"{prefix}{start}" + (f"-{prefix}{end}" if end and end != start else "")
            volume = int(r["dateIssued"][:4]) - 1854
            cite = f"{volume} Cong. Rec. {span} (daily ed. {long_date(r['dateIssued'])})"
            routine = (r.get("granuleClass") == "DAILYDIGEST"
                       or bool(ROUTINE_RECORD.search(title or "")))
            entries.append((r["dateIssued"], cite, title or "(untitled)", routine,
                            f"text {r['packageId']} {r['granuleId']}"))
        entries.sort()
        shown = [e for e in entries if args.all_record or not e[3]]
        print(f"CONGRESSIONAL RECORD ({len(entries)} entries on the bill; "
              + ("all shown)" if args.all_record else f"{len(entries) - len(shown)} routine ones "
                 "hidden: messages, enrollment, digest; --all-record shows them)"))
        for date, cite, title, routine, cmd in shown:
            print(f"  {cite}: {title}{'  [routine]' if routine else ''}   → {cmd}")
        print()

    if fetched.get("HOB"):
        years = ", ".join(sorted(r["packageId"].replace("HOB-", "") for r in fetched["HOB"]))
        print(f"HISTORY OF BILLS entries: {years}   → text <HOB package> <granule> "
              f"(e.g. text {fetched['HOB'][0]['packageId']} {fetched['HOB'][0]['granuleId']})\n")

    titles = fetched.get("USCODE") or []
    if titles:
        def sections(t):
            link = t.get("granulesLink") or f"{BASE}/related/{pid}/USCODE/{t['packageId']}"
            try:
                return request(link).get("results", [])
            except SystemExit:
                return []
        found = [s for group in parallel(sections, titles) for s in (group or [])]
        edition = titles[0]["packageId"].split("-")[1]
        print(f"U.S. CODE SECTIONS THIS LAW AFFECTS (GovInfo's classification, {edition} edition; "
              f"{len(found)})")
        for s in found[: args.n]:
            cite, cmd = cite_for(s["packageId"], s["granuleId"])
            print(f"  {cite or s.get('citation')}: {s.get('title', '')}" + (f"   → {cmd}" if cmd else ""))
        if len(found) > args.n:
            print(f"  [{len(found) - args.n} more; raise -n]")
        print()

    missing = [c for c in ("CRPT", "CREC") if not (fetched.get(c) or (c == "CREC" and record))
               and not (c == "CREC" and record_error)]
    if missing:
        print("Not found on GovInfo: " + ", ".join({"CRPT": "committee reports",
                                                     "CREC": "Congressional Record entries"}[c]
                                                    for c in missing)
              + ". Many laws have none; for recent laws, GovInfo may not have linked them yet.")


def main():
    p = argparse.ArgumentParser(description="GovInfo API client")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("collections").set_defaults(fn=collections)

    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("-n", type=int, default=10)
    s.add_argument("--offset", default="*")
    s.add_argument("--all", action="store_true", help="page through every hit (up to --limit)")
    s.add_argument("--limit", type=int, default=300)
    s.add_argument("--grep", help="regex; pull each hit's text and show the matching lines")
    s.add_argument("--lines", type=int, default=3, help="matching lines shown per hit")
    s.set_defaults(fn=search)

    e = sub.add_parser("ecfr-search")
    e.add_argument("query")
    e.add_argument("--title")
    e.add_argument("-n", type=int, default=20)
    e.add_argument("--grep", help="regex; pull each section's current text and show the matching lines")
    e.add_argument("--lines", type=int, default=3)
    e.set_defaults(fn=ecfr_search)

    fr = sub.add_parser("fr-rules")
    fr.add_argument("title")
    fr.add_argument("part")
    fr.add_argument("--since")
    fr.add_argument("--until")
    fr.add_argument("--all-types", action="store_true", help="include proposed rules and notices")
    fr.add_argument("-n", type=int, default=20)
    fr.set_defaults(fn=fr_rules)

    pl = sub.add_parser("plaw")
    pl.add_argument("law", nargs="+", help="119-21 or 119 21")
    pl.add_argument("--private", action="store_true")
    pl.add_argument("--grep", help="regex; show matching paragraphs instead of the full text")
    pl.add_argument("--lines", type=int, default=10)
    pl.add_argument("--max", type=int, default=20000)
    pl.set_defaults(fn=plaw)

    for name, fn in (("summary", summary), ("text", text)):
        c = sub.add_parser(name)
        c.add_argument("package")
        c.add_argument("granule", nargs="?")
        if name == "text":
            c.add_argument("--max", type=int, default=20000)
        c.set_defaults(fn=fn)

    g = sub.add_parser("granules")
    g.add_argument("package")
    g.add_argument("-n", type=int, default=100)
    g.set_defaults(fn=granules)

    u = sub.add_parser("usc")
    u.add_argument("title")
    u.add_argument("section")
    u.add_argument("--notes", action="store_true")
    u.add_argument("--pin", help="just one subsection, like (b)(6)")
    u.add_argument("--as-of", help="the section as it read on a date (YYYY-MM-DD), from 1995 on")
    u.add_argument("--max", type=int, default=20000)
    u.set_defaults(fn=usc)

    h = sub.add_parser("history")
    h.add_argument("law", nargs="+", help="114-185 or 114 185")
    h.add_argument("--private", action="store_true")
    h.add_argument("--all-record", action="store_true",
                   help="also list routine Congressional Record entries")
    h.add_argument("-n", type=int, default=40, help="U.S. Code sections to list")
    h.set_defaults(fn=history)

    c = sub.add_parser("currency")
    c.add_argument("title")
    c.add_argument("section")
    c.add_argument("--diff", type=int, default=40)
    c.set_defaults(fn=currency)

    appendix_help = ('pull an appendix of the part given instead of a section: "A", "M1", '
                     '"Supplement I", or the full "Appendix A to Part 210"')

    r = sub.add_parser("cfr-currency")
    r.add_argument("title")
    r.add_argument("section", help="PART.SECTION, or PART with --appendix")
    r.add_argument("--appendix", help=appendix_help)
    r.add_argument("--diff", type=int, default=40)
    r.set_defaults(fn=cfr_currency)

    f = sub.add_parser("cfr")
    f.add_argument("title")
    f.add_argument("section", help="PART.SECTION, or PART with --appendix")
    f.add_argument("--appendix", help=appendix_help)
    f.add_argument("--current", action="store_true")
    f.add_argument("--as-of", help="the provision as it read on a date (YYYY-MM-DD), from 1996 on")
    f.add_argument("--pin", help="just one paragraph, like (a)(1)(i)")
    f.add_argument("--grep", help="regex; show matching paragraphs instead of the full text")
    f.add_argument("--lines", type=int, default=10)
    f.add_argument("--context", type=int, default=0,
                   help="with --grep, also show this many paragraphs after each match")
    f.add_argument("--max", type=int, default=20000)
    f.set_defaults(fn=cfr)

    args = p.parse_args()
    # Legal text is full of §, —, and “quotes”; don't let a Windows console codepage
    # or a pipe's locale encoding turn that into a crash.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    args.fn(args)


if __name__ == "__main__":
    main()
