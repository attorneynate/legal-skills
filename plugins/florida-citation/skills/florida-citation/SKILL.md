---
name: florida-citation
license: MIT
compatibility: Requires Python 3.9+ (standard library only). Works offline; only the optional self-test (scripts/selftest.py) uses the network. Reading PDFs directly needs pdftotext (Poppler or Xpdf); a scanned PDF needs OCR first, such as OCRmyPDF, which runs on the user's own machine.
description: Format and check legal citations under Florida's Uniform Citation System, Fla. R. App. P. 9.800, as amended effective September 1, 2026. Shows the text of any subdivision of the rule, gives the Florida form for courts, reporters, rule sets, counties, and months, converts appellate case numbers to the four-digit form, and builds a citation from its parts. Checks every citation in a brief or motion (.txt, .md, .docx, or .pdf), short forms and Id. included, giving each departure's page, authority, and fix. Reviews the other side's filing, ranking case facts that don't match what a case-law tool finds, pinpoints outside a case, and quotations to verify ahead of form. Use whenever the user asks how to cite something in a Florida filing, whether a citation or filing follows Rule 9.800, to check an opposing brief's citations, or what a Florida citation abbreviation is, even if they never name the rule. Doesn't decide whether a case exists or supports its point (a case-law tool does); not for law-review style.
---

# Florida citation (Rule 9.800)

This skill answers Florida citation-form questions from Rule 9.800 itself, through `scripts/fl_cite.py` in this skill's folder (Python 3.9 or later, standard library only, no network). The rule's text, as amended by *In re Amendments to Florida Rules of Appellate Procedure*, No. SC2025-0241 (Fla. June 11, 2026) (corrected opinion), is bundled in `references/rule-9.800.md`. Rules of court carry no copyright.

References in `references/`, read as needed:

- `rule-9.800.md`: the rule's text. Prefer `fl_cite.py rule`, which prints the part asked for with its as-of date.
- `indigo-practitioner.md`: the Bluebook-system forms briefs use (signals, short forms, case names, parentheticals, subsequent history, federal courts, record cites), condensed from the public-domain Indigo Book with its rule numbers. Read it for any form Rule 9.800 doesn't cover.
- `bluebook-22-changes.md`: what the Bluebook's 22nd edition (2025) changed, where the Indigo Book is behind, and how the skill handles County (`Cnty.` in case names, `Cty. Ct.` in a Florida county court's parenthetical) and September. Check it before stating a Bluebook-system form as current.
- `florida-style-manual.md`: what the third tier covers (bills, staff analyses, journals, executive orders), section by section, with the link.
- `opposing-filing.md`: the workflow for reviewing another side's filing: opposing mode, the facts loop, verifying quotations, and how to report. Read it before running `check --mode opposing`.

Run the script from a POSIX shell (bash or zsh; on Windows, Git Bash). The examples use `python3`; where that command doesn't exist, use `python`.

```bash
S=scripts/fl_cite.py            # relative to this skill's folder
# Claude Code: S="${CLAUDE_SKILL_DIR}/scripts/fl_cite.py"
```

## Commands

- `rule [SUBDIVISION]` prints Rule 9.800 or one part of it: `rule f`, `rule "(j)(3)"`, `rule "9.800(d)(4)(A)"`, `rule intro`, `rule notes`. With no argument it lists the subdivisions. Each answer starts with the rule's amendment date and source. Quote the rule from this output rather than from memory.
- `abbrev QUERY` gives the Florida form for a court, county, reporter, rule set, Florida Law Weekly edition, or month, with the subdivision that sets it and common wrong variants: `abbrev "judicial administration"`, `abbrev "Palm Beach"`, `abbrev So.2d`, `abbrev 11th`.
- `casenum NUMBER [...]` converts old Florida appellate case numbers to the four-digit form the rule's examples use since September 1, 2026: `casenum SC09-839 1D01-2734`. It refuses numbers that can't exist (a Seventh District, a Sixth District number before 2023, more than four digits) instead of guessing.
- `checks [--authority 9.800(f)] [--kind pattern]` lists the check records in `data/checks.json`: what each looks for, its severity, and the subdivision behind it.
- `build TYPE ...` builds a citation from its parts and checks it. Types: `case`, `agency`, `statute`, `annotated`, `const`, `admin`, `law`, `rule`, `ago`; each takes `--help`. Examples:
  - `build case "Fenelon v. State" --court SC --year 1992 --cite "594 So. 2d 292" --pin 293`
  - `build case "Myers v. State" --court 4D --date 1991-06-05 --flw "16 Fla. L. Weekly D1507"`
  - `build case "Singh v. State" --court SC --date 2014-12-30 --docket SC10-1544 --westlaw "2014 WL 7463592"`
  - `build statute 48.031 --year 2014`, `build const V --section "3(b)(3)"`, `build rule civ 1.180`, `build ago 73-178`

  Courts are `SC`, `1D` to `6D`, `circuit:17`, `county:Miami-Dade`, `US`, `CA1` to `CA11`, `CADC`, `CAFED`, and `N.D.`/`M.D.`/`S.D. Fla.`. Case-name words are abbreviated as the Bluebook system requires in citations (Indigo Book Table T11, with County as `Cnty.` per the current Bluebook; `--no-abbreviate` keeps them whole). Old case numbers are converted. Statutes, constitutions, rules, the Administrative Code, and Laws of Florida also get their spelled-out form for use inside a sentence. Parts that can't all be right (So. 3d in 1992, a Sixth District case before 2023, a criminal rule number in the civil rules) are refused with the reason. A fact the script can't know, such as an exact date or a docket number, is left as `___` and named; find it with a case-law tool.
- `check FILE|- [--json] [--date YYYY-MM-DD] [--citations]` checks every citation in a document: `.txt`, `.md`, `.docx`, `.pdf`, or `-` for text on standard input (form feeds mark page breaks). `--last-page N` checks only pages 1 to N, leaving out exhibits or an appendix after the document; the report suggests it when it sees a slip sheet ("Exhibit 1"), a short cover sheet ("Exhibit A Proposed Order"), or a Westlaw or Lexis printout. Add `--mode opposing` to review another side's filing, and `--cite-list`, `--facts-template`, and `--facts FILE` for the facts loop (see `references/opposing-filing.md`).
  - **PDFs** are read through `pdftotext`, which the script runs if it's installed. If it isn't, the script prints how to install it; or extract the text another way, with a form feed between pages, and pipe it to `check -`. The script drops diagonal text, so a clerk portal's corner-to-corner watermark (NOT A CERTIFIED COPY) doesn't land inside citations; if you extract the text yourself, use `pdftotext -nodiag`. A scanned PDF (images, no text) stops with a message that it needs OCR, which this script doesn't do.
  - **Scanned PDFs:** run OCRmyPDF first, as the message shows: `ocrmypdf --output-type pdf --deskew brief.pdf brief-ocr.pdf`, then check `brief-ocr.pdf`. It runs on the user's own machine, so a confidential filing goes nowhere. Install it like pdftotext: `brew install ocrmypdf` (macOS), `sudo apt-get install ocrmypdf` (Debian, Ubuntu), `sudo dnf install ocrmypdf tesseract-osd` (Fedora), or on Windows `winget install -e --id tesseract-ocr.tesseract`, `winget install -e --id astral-sh.uv`, then `uv tool install ocrmypdf`. For a PDF with only some pages scanned, add `--skip-text`. OCR misreads some characters (`Id.` as `ld.`, `5th` as `Sth`, a dropped hyphen in a page range); the script doesn't guess around them, so read an OCR'd finding's pinpoint against the page.

## Checking a document

`check` finds the case, statute, constitution, rule, administrative-code, session-law, and Attorney General citations Rule 9.800 covers; decides which tier governs each; and reports findings. Each finding gives its location (in PDF text, the brief's printed page first, as `p. 12 (PDF p. 19)`; otherwise line, or paragraph and footnote in a `.docx`), the authority, what was found, and a fix when the fix needs no outside fact.

- **error:** clearly departs from Rule 9.800's form (`Fla. 3rd DCA`, `So.2d`, `AGO 73-178`, `(Fla.1992)`, a month and day on a case published in a reporter, `§ 48.031, Fla. Stat. Ann.`) or the Bluebook system's (`292 at 293` for `292, 293`, `; See also` inside a citation sentence, an unspaced ellipsis in the document's own quotation).
- **check:** probably wrong, or right in some contexts; decide case by case. Examples: no statute year (reported once per document, since courts often omit it), an old-form case number after September 1, 2026, a Florida Law Weekly cite more than a year old, an abbreviated form used inside a sentence, parentheses that don't pair, a quotation that never closes, a quotation from a case whose citation gives no page, record-cite forms (`¶ 8, 12` for `¶¶ 8, 12`, and Id. used for record cites; reported once per document, since a court's own rules govern).
- **unrecognized:** a citation outside the script's forms. Its tier says where to check it: the Bluebook system (federal statutes, other states' courts, law reviews; check against the Indigo Book) or the Florida Style Manual (bills, staff analyses, executive orders). Cases in reporters the rule doesn't name (the regional reporters, F.R.D., B.R., Fed. Cl., T.C.) are listed here so you check their court and year by hand, but the script still reads them: they get facts-template entries, Id. links, and a spacing check (`N.E. 2d` should be `N.E.2d`).

Short forms are checked across the whole document. Rule 9.800 has none of its own, so 9.800(p) sends them to the Bluebook system, checked through the Indigo Book (findings name its rule, such as Indigo Book R15.3.3):

- `Id` with no period, and `ibid.` (errors).
- An Id. after a string citation, or one whose pinpoint doesn't fit what it refers to: a page after a statute, a section after a case.
- A short form before the case's first full citation, a short form for a case never cited in full, a short form whose volume differs from the full citation's, and a short form missing `at` (`Fenelon, 594 So. 2d 294.`).
- A pinpoint before the case's first page.
- `supra` used for a case. Books and articles are left alone.
- A full citation repeated on the same page, within about ten citations, where a short form would do.

An Id. is checked only when the script can tell what it refers to. It is skipped when a record cite, an unrecognized citation, a quotation, a footnote, or a page split comes between; the report notes how many were skipped. A citation inside another's parenthetical (quoting ...) is not "the preceding citation." In `--json`, each short form and Id. carries `refers_to`, the full citation it stands for.

How to use the results:

- **Pass `--date`** when the document's date matters and isn't in the text. Otherwise the script reads it from an e-filing stamp or the caption, then falls back to today; the report says which. Case-number and Florida Law Weekly checks depend on it.
- **Citations inside quotation marks or block quotes are skipped,** since they're the quoted writer's form; the report counts what it skipped and on which pages. A PDF's block quotes are found by their indentation (a second `pdftotext -layout` pass), counted only when a colon introduces them or a citation follows them; a `.docx`'s by paragraph indents or a quote style. Plain or piped text has neither, so there a block quote is the paragraph after a colon, and it may end early or late. Read the passage before relying on a finding near one. A defined term in a parenthetical, `(the "Agreement")`, is the writer's label, not a quotation.
- **A fix of `null` needs a fact** (the exact date, the docket number, which district, the U.S. Reports cite). Find it with a case-law research tool; don't guess.
- **Case-name typeface (9.800(q))** is checked only in `.docx` and Markdown, where italics survive.
- **`--json`** adds every citation the script found, with its parts (case name, reporter, volume, page, pinpoints, court, date, docket number, tier), and every quotation of four or more words with the citation it's tied to.

## How to answer

- **Name the authority for every point:** the subdivision of Rule 9.800 (for example 9.800(b)(1)), or, for forms the rule doesn't cover, the Bluebook system as implemented by the Indigo Book, with its rule number from `references/indigo-practitioner.md`. Where `references/bluebook-22-changes.md` says the 22nd edition differs, give the 22nd edition's form and say the source.
- **The rule's own order of authority (9.800(p)):** Rule 9.800 first; then the latest Bluebook for anything it doesn't cover; then the Florida Style Manual for Florida materials neither covers (bills, staff analyses, legislative journals, executive orders). For those, say to check the Florida Style Manual rather than guessing a form, and name its section from `references/florida-style-manual.md`.
- **Rule 9.800 isn't mandatory.** Its 1977 committee note says so. Present its forms as Florida's standard, not as a requirement, and don't call a departure a violation.
- **Spell out in sentences:** citation forms other than case reporters are spelled out when they're part of a sentence ("section 48.031, Florida Statutes (2014), provides") and abbreviated when they stand alone (§ 48.031, Fla. Stat. (2014)).
- **Statute years:** the rule's form includes the year of the Florida Statutes edition. Courts often leave it off for current law, so recommend it where the version matters (a statute amended since the events) rather than insisting on it everywhere.
- **Case numbers:** some courts and filers still use old forms (the Third District's own captions did after September 1, 2026). Offer the converted form; don't treat the old one as an error.
- **Build citations with `build`, not from memory,** and give its output as is, with the case name italicized or underlined (9.800(q)). Fill any `___` with the fact from a case-law tool.
- **Facts are not form.** Whether a case exists, its correct volume, page, court, and year, and whether it supports the point cited are facts. Confirm them with a case-law research tool; the facts loop (`references/opposing-filing.md`) compares what you confirm with what the document says.

## Reviewing the other side's filing

In someone else's brief, a citation that's wrong in substance matters far more than one in the wrong form. `check FILE --mode opposing` orders the report that way: facts that don't match what a case-law tool finds, pinpoints outside the case, quotations to verify, then form errors summarized. The facts are yours to confirm: `--cite-list` prints the cases for a citation tool that checks a whole list in one request, `--facts-template` writes one entry per case for what you find, and `--facts FILE` compares it with what the brief claims. The script's part is free; lookups and quotation checks cost requests and tokens, so report the free result first and ask the user how far to go. Before running it, read `references/opposing-filing.md`: the six-step workflow, how to record each lookup (including a case found in no database), quotation privacy, and how to report findings as things to confirm, never as accusations.

This is a citation-form tool, not legal advice. It isn't affiliated with the Florida Supreme Court, The Florida Bar, or the publishers of the Bluebook or the Florida Style Manual.
