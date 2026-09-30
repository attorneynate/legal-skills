---
name: federal-law
license: MIT
compatibility: Requires Python 3.9+, internet access to govinfo.gov, uscode.house.gov, ecfr.gov, and federalregister.gov, and a free GovInfo (api.data.gov) API key.
description: Find, read, and verify U.S. federal statutes and regulations from official sources — the U.S. Code, the Code of Federal Regulations (including appendices and official interpretations), the Federal Register, public laws and the Statutes at Large, and legislative history (bills, committee reports, Congressional Record) — through GovInfo (GPO), uscode.house.gov, eCFR, and the Federal Register API. Checks whether a provision is current, shows it as it read on a past date, pulls a single subsection by pinpoint cite, and traces amendments to the law or rule that made them. Use whenever the user asks for federal statutory or regulatory text, which federal statutes or regulations define or govern something, whether a federal provision is current or was amended, what the law said on a date, a Federal Register rule, or legislative history — even if they never name GovInfo or eCFR. Not for state law or case law.
---

# Federal statutes and regulations

This skill answers federal statutory and regulatory questions from official sources, through `scripts/federal_law.py` in this skill's directory (Python 3.9 or later, standard library only). It draws on four free public sources:

- **GovInfo** (Government Publishing Office): official editions of the U.S. Code, CFR, Federal Register, public laws, bills, committee reports, and the Congressional Record, plus GovInfo's links between them. Needs an API key.
- **uscode.house.gov** (Office of the Law Revision Counsel): the current U.S. Code, its edition history, and which titles are positive law.
- **eCFR** (ecfr.gov): current regulations, and their text on any date since January 2017.
- **Federal Register API** (federalregister.gov): which rules changed which CFR parts.

## Setup

GovInfo requires an API key (sign up at https://www.govinfo.gov/api-signup; it's a free api.data.gov key and takes a minute to get). Save it in `~/.govinfo_api_key`, or set the `GOVINFO_API_KEY` environment variable; the script reads it itself. Never print, echo, or paste the key. Without a key the script falls back to `DEMO_KEY` and warns on stderr (`using DEMO_KEY`); the demo key's rate limit is too low for real research, so stop and tell the user how to set one up.

Run the script from a POSIX shell (bash or zsh; on Windows, Git Bash). Windows PowerShell 5.1 strips the double quotes inside arguments, which breaks phrase searches. The examples use `python3`; where that command doesn't exist (some Windows installs), use `python`.

The script retries a request twice when a site times out or returns a server error. If a command still reports a network error, the site is down or unreachable; say so rather than working around it. An `ACCESS BLOCKED` message means eCFR or FederalRegister.gov refused the network the script is running on (the Office of the Federal Register blocks some cloud servers and VPNs, even for its developer APIs). Tell the user; commands that use only GovInfo and uscode.house.gov (`usc`, `currency`, `plaw`, `history`, `search`, and `cfr` without its currency line) still work. On macOS with Python from python.org, a certificate error on every request means Python's certificates were never installed; run `Install Certificates.command` in the Python folder under Applications.

## Commands

Paths in this skill are relative to its own folder, the one containing this `SKILL.md`. `S` below is the script's full path: that folder plus `scripts/federal_law.py`. Claude Code provides the folder as `${CLAUDE_SKILL_DIR}`, as in the second line.

```bash
S="<this skill's folder>/scripts/federal_law.py"
# In Claude Code: S="${CLAUDE_SKILL_DIR}/scripts/federal_law.py"

# Find
python3 "$S" ecfr-search '"yogurt" means' --grep yogurt            # current regulations
python3 "$S" search 'collection:USCODE "public records"' --all --grep 'public records'   # official editions

# Pull by cite
python3 "$S" usc 5 552                          # U.S. Code section (latest GPO edition)
python3 "$S" usc 5 552 --pin '(b)(6)'           # one subsection
python3 "$S" usc 5 552 --as-of 2016-01-01       # as it read on a date
python3 "$S" cfr 21 131.200                     # CFR section (official annual edition) + currency line
python3 "$S" cfr 21 131.200 --current           # as eCFR shows it today
python3 "$S" cfr 21 131.200 --as-of 2020-06-01 --pin '(a)'
python3 "$S" cfr 7 210 --appendix A             # an appendix (give the part, then the appendix)
python3 "$S" cfr 12 1026 --appendix "Supplement I" --current --grep '^19\(e\)\(3\)\(i\) ' --context 3
python3 "$S" plaw 119-21 --grep 'Section 24\(h\)'   # a public law, or just the paragraphs that matter

# Check currency, trace amendments, legislative history
python3 "$S" currency 5 552                     # U.S. Code vs. uscode.house.gov
python3 "$S" cfr-currency 21 131.200            # CFR vs. eCFR, with the matching Federal Register rules
python3 "$S" fr-rules 21 131 --since 2020-01-01 # every final rule that affected a CFR part
python3 "$S" history 114-185                    # bill versions, reports, floor debate, sections affected

# Utilities
python3 "$S" text FR-2021-06-11 2021-12220      # any document with a text rendition
python3 "$S" summary PACKAGE_ID [GRANULE_ID]    # metadata and download links (JSON)
python3 "$S" granules USCODE-2024-title5 -n 200 # the parts of a package
python3 "$S" collections
```

### Finding provisions

- `ecfr-search QUERY [--title N] [-n 20] [--grep REGEX] [--lines 3]` searches the **current** CFR through eCFR, one row per section or appendix, with cite, heading, part, date in effect, and an excerpt. With `--grep` it pulls each hit's current text and prints the matching lines. It is the first choice for regulations: it is current, and it catches sections GovInfo's search misses.
- `search QUERY [-n 10] [--all [--limit 300]] [--grep REGEX] [--lines 3]` searches GovInfo's official editions, every collection. Each hit shows a cite and a follow-up command (`7 CFR 220.2 → cfr 7 220.2`, `5 U.S.C. 552 → usc 5 552`, `Pub. L. 114-185 → plaw 114-185`, `Fed. R. Evid. 1005`, `7 CFR part 210, Appendix A → cfr 7 210 --appendix A`). `--all` pages through every hit; `--grep` pulls each hit's text and prints the matching lines, then names hits whose text doesn't match.
- `--grep` takes a case-insensitive regex. Hits are leads; the matching lines show whether a provision defines a term, regulates it, or merely mentions it.
- In U.S. Code hits, matches after the source credit (editorial, statutory, and amendment notes; Advisory Committee notes on court rules) are tagged `[note]`. Notes are not the law's text; never describe a provision as saying what only its notes say.

### Pulling text by cite

- `usc TITLE SECTION [--pin (b)(6)] [--as-of DATE] [--notes] [--max N]` prints a U.S. Code section from the latest GPO edition, with a line saying whether the title is positive law (see Legal cautions). Letters in section numbers work (`usc 5 552a`). Court rules in the Title 18 and 28 appendices are pulled with the `text` command `search` prints beside them.
- `cfr TITLE PART.SECTION [--current | --as-of DATE] [--pin (a)(1)] [--grep REGEX [--lines 10] [--context N]] [--max N]` prints a CFR section from the most recent official annual edition, with its revision date and chapter/part/subpart path, ending with a CURRENCY line from eCFR. If that line says AMENDED, the annual text is stale: rerun with `--current` and quote that. Use `cfr`, not `text`, for CFR sections; GovInfo has no plain-text rendition of CFR granules. Quote a section number with parentheses so the shell leaves it alone: `cfr 26 '1.401(k)-1'` (tax regulations; GovInfo's citation service can't resolve these, so the script finds them by volume, which takes a few seconds).
- `cfr TITLE PART --appendix X` does the same for an appendix or supplement: `A`, `M1`, `"Supplement I"`, or eCFR's full name (`"Appendix A to Part 210"`). An unknown or ambiguous X lists the part's appendices; pick from the list rather than guessing. Appendices are matched by the heading inside GovInfo's documents, not by file name, and split documents are joined (GovInfo stores Supplement I to Part 1026 as two continuations of the reserved Appendix I). Official interpretations run to a million characters: match the commentary heading with `--grep` and take its comments with `--context`.
- `plaw CONGRESS-NUMBER [--private] [--grep REGEX [--lines 10]] [--max N]` prints a public or private law with its Statutes at Large cite, enactment date, and originating bill. For omnibus laws, use `--grep` to pull only the paragraphs that amend the provision in question. GovInfo's public laws start with the 104th Congress (1995); earlier laws exist only as scanned Statutes at Large PDFs, reachable with `summary STATUTE-<volume> STATUTE-<volume>-Pg<page>` when you know the Stat. cite.
- `text PACKAGE [GRANULE]` prints anything with a text rendition (U.S. Code, Federal Register, public laws, bills, reports, Congressional Record). Raise `--max` rather than guessing what was cut.

### Pinpoints

- `--pin` takes a pinpoint like `(b)(6)`, `(b)(3)(A)(ii)`, or `(e)(1)(ii)` and prints just that provision, cited as `5 U.S.C. 552(b)(6)`. Lowercase `i`, `v`, `x` are read as letters at the top level and roman numerals below it. CFR paragraphs whose headings run together (`(e) Methods—(1) Milk—(i) Milkfat`) are split first.
- If unnumbered text follows the pinned provision and the next thing is a higher level's paragraph, the command warns that the text may be flush language belonging to that higher level (like the sentence after 5 U.S.C. 552(b)(9), which governs all of subsection (b)). Check it against the whole section before attributing it.
- Sections numbered (1), (2), (2A) at the top level, like the definitions in 11 U.S.C. 101, work the same way (`--pin '(10A)'`). Bracketed repealed paragraphs (`[(j) Repealed ...]`) and contents tables at the head of long CFR sections are accounted for.
- An unknown pinpoint lists the section's top-level paragraphs.

### The law on a past date

- `usc … --as-of DATE` picks the U.S. Code edition in effect on that date from uscode.house.gov's edition list (main editions and supplements back to the 1994 edition, in effect Jan. 4, 1995) and pulls it from GovInfo. It then checks for laws enacted **between that edition and the date**: any public law in the section's current source credit that the edition lacks, dated by GovInfo. An AS-OF CHECK line names each one, because the edition's text can't reflect it. Enactment is not effectiveness; read the amending law's effective-date provisions before concluding what applied. For dates before 1995, use the Statutes at Large.
- `cfr … --as-of DATE` uses eCFR's point-in-time text for dates from 2017-01-03 on. For earlier dates, it uses the latest annual edition revised on or before the date and lists any final rules affecting the part that were published between the revision date and the date (the AS-OF CHECK). GovInfo's annual CFR starts in 1996.

### Currency and amendments

- `currency TITLE SECTION` compares the GPO U.S. Code edition with uscode.house.gov: the date the current text runs through, wording differences, public laws in the current source credit that the edition lacks, and recent amendment notes. Ends with a VERDICT.
- `cfr-currency TITLE PART.SECTION` (or `TITLE PART --appendix X`) compares the annual CFR edition with eCFR: how current eCFR is, each later version, a diff of the text between the revision date and today, and the Federal Register rules that match those versions by effective or publication date. A version no rule matches is usually an editorial correction by eCFR; check `fr-rules` before saying so. Ends with a VERDICT.
- `fr-rules TITLE PART [--since DATE] [--until DATE] [--all-types] [-n 20]` lists Federal Register documents that affected a CFR part, newest first, with the command to pull each. Final rules only unless `--all-types`.

### Legislative history

- `history CONGRESS-NUMBER [--private] [--all-record] [-n 40]` assembles a law's history from GovInfo's links: every version of the bill, committee reports (cited `S. Rep. No. 114-4`) and prints, presidential signing statements, Congressional Record entries on the bill (cited `162 Cong. Rec. H3714 (daily ed. June 13, 2016)`), and the U.S. Code sections the law affects, each with the command to pull it. Routine Record entries (messages between chambers, enrollment, digests, general leave) are hidden unless `--all-record`.
- GovInfo's links are thin before the 1990s and lag for very recent laws, and GovInfo occasionally links the wrong document; a signing statement dated before enactment is flagged. For bills with very long floor histories (the Affordable Care Act, the 2025 reconciliation act), GovInfo errors when listing the Record entries; `history` says so and prints a Congressional Record search, limited to the right Congress, to use instead. Read each item before relying on it.

## Recipes

**"Which federal regulations (or statutes) define or govern X?"**
1. `ecfr-search '"X" means' --grep X`, then `ecfr-search X --grep X` for the broader set. Add `--title` when the field is known (21 food and drugs, 7 agriculture, 40 environment, 29 labor, 26 tax, …).
2. For statutes, `search 'collection:USCODE "X"' --all --grep X`.
3. Sort hits by their matching lines: (a) the standard or definition of X itself, (b) definitions elsewhere that adopt or cross-reference it, (c) rules that regulate X without defining it, (d) passing mentions. Report in that order; give (d) one line.
4. Pull the core provisions in full before characterizing them.
5. Run `currency` or `cfr-currency` on every provision you describe, and report the result with its date.
6. Check cross-references in definitions against current law. A cited section `cfr … --current` can't find (removed or revoked) is a stale cross-reference; say so.

**"Has this changed, and what changed it?"** Run `currency` or `cfr-currency`. For a statute, quote the amending language with `plaw … --grep 'section NNN'`. For a regulation, pull the matched rule with the `text FR-… …` command it prints, and cite the Federal Register, not eCFR, as the authority for the change. To pin down when a change took effect, compare `--as-of` pulls on either side of the date.

**"What did the law say when X happened?"** `usc … --as-of DATE` or `cfr … --as-of DATE`, plus `--pin` for the provision at issue. Read every AS-OF CHECK line, and check the amending laws' or rules' effective dates.

**Legislative history.** `history CONGRESS-NUMBER`, then pull the committee reports and the substantive Record entries with the commands it prints.

## Legal cautions

- **Positive law.** Only some U.S. Code titles have been enacted as positive law; in those, the Code's text is legal evidence of the law. In the rest, the Code is only prima facie evidence, and the Statutes at Large control where they differ (1 U.S.C. 204(a)). `usc` and `currency` print which kind a title is, read live from uscode.house.gov. For a non-positive-law title, check the enacted wording in the public law when precision matters.
- **eCFR is not an official edition.** It is an editorial compilation. Quote it for current text, but name the official annual edition or the Federal Register rule as the authority.
- **Codified is not the same as valid.** The CFR can keep a rule a court has vacated or enjoined, sometimes for years, and the U.S. Code can keep a provision a court has held unconstitutional. Nothing here checks case law; before relying on a provision, especially a recent or contested one, check whether a court has set it aside.
- **Enactment is not effectiveness.** Amending laws and rules often take effect on a later date or apply only to some transactions. Read the effective-date provisions before saying what applied on a date.

## Research practice

1. Start narrow: pick the source and collection, then search a phrase. Widen only if hits are thin.
2. Read the text before characterizing it. Search hits and excerpts are leads, not holdings.
3. Say which version you read and check currency. The annual GPO U.S. Code edition can trail amendments by a year or more; the annual CFR is revised once a year on a date that depends on the title (Jan. 1 for titles 1–16, Apr. 1 for 17–27, July 1 for 28–41, Oct. 1 for 42–50) and published months later.
4. Cite properly, and keep the package and granule ID (or the follow-up command) alongside so the source can be pulled again.

## GovInfo `search` syntax

Field operators combine with free text and quoted phrases. Each one below has been tested.

| Want | Query |
|---|---|
| One collection | `collection:CFR "public records"` |
| Words in the title | `collection:USCODE title:"public records"` |
| Date range | `collection:FR publishdate:range(2025-01-01,2025-12-31) "public records"` |
| One Congress | `collection:BILLS congress:118 "public records"` |
| Federal court by name | `collection:USCOURTS courtname:"Texas" "Freedom of Information Act"` |

| Code | Contents |
|---|---|
| USCODE | United States Code (annual GPO editions; note the edition year) |
| CFR | Code of Federal Regulations (annual edition; use `ecfr-search` for current text) |
| FR | Federal Register |
| PLAW, STATUTE | Public and private laws; Statutes at Large |
| BILLS, BILLSTATUS | Bill text and bill status |
| CRPT, CHRG, CPRT, CDOC | Committee reports, hearings, prints, documents |
| CREC, CRECB | Congressional Record (daily, bound) |
| CPD, PPP | Presidential documents |
| GAOREPORTS | GAO reports and Comptroller General decisions |

## Limits

- Federal statutes and regulations only: no state law, and no case law (GovInfo's USCOURTS collection is partial and has no citator; use a case-law tool for cases and their treatment).
- Currency checks are only as current as their sources, and each prints its date (uscode.house.gov's "laws in effect on", eCFR's "up to date as of"). Give the date so the reader knows where the check stops.
- `cfr-currency` trusts eCFR's version history rather than comparing GPO's annual text word for word, and its Federal Register matching relies on the FR's "CFR parts affected" metadata and on dates lining up.
- Search is keyword search. A provision that defines a term without your exact phrase (21 CFR 131.200 never says "yogurt means") won't match a `"X" means` query; that is why the recipe also runs a broad search.
- `--grep` on `search` and `ecfr-search` pulls every hit's full text; narrow a query with hundreds of hits first.

## Maintenance

`python3 scripts/selftest.py`, run from the skill's folder, runs 39 live checks, at least one per command and feature plus the unusual citation formats that once broke it, in about a minute. Run it after editing `federal_law.py` or when a command gives odd output. Each check reports:
- **ok**
- **FAIL:** the script broke, or a source changed its format. Fix the script.
- **CHANGED:** a fact recorded on 2026-09-29 has moved, such as a new GPO edition or a new amendment. That's the law changing, not a bug; update the check's expected facts.
- **FLAKY:** failed once, then passed when rerun: a live source hiccupped. Not a failure, but a check that keeps showing up here needs a look.
- **BLOCKED:** eCFR or FederalRegister.gov refused the network running the test (HTTP 403) on both tries. That's the network, not the script; rerun those checks from another network.
