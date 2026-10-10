# florida-citation

An [Agent Skill](https://agentskills.io) for formatting and checking legal citations under Florida's Uniform Citation System, Fla. R. App. P. 9.800, as amended effective September 1, 2026. It works in Claude and in any AI agent that supports the Agent Skills standard (ChatGPT and Codex, Gemini CLI, GitHub Copilot, Cursor, and many more).

Ask your agent how to cite something in a Florida filing, and it answers from the rule's own text. Hand it a brief or motion, and it checks every citation in the document and reports each departure with its page, the authority, and a fix. Hand it the other side's brief, and it ranks what matters there (cases whose facts don't match, pinpoints outside the case, quotations to verify) ahead of form.

It is a citation-form tool, not legal advice. Check anything you rely on against the rule and the cited sources, and see [What it doesn't do](#what-it-doesnt-do).

## Which rule governs

Every answer and every finding names its authority, in the order Rule 9.800(p) sets:

1. **Rule 9.800.** Florida's rule governs everything it covers: Florida and federal courts, Florida statutes, the constitution, the Administrative Code, Laws of Florida, the 23 sets of Florida rules, agency decisions, and Attorney General opinions. The skill bundles the rule's full text, checked word for word against The Florida Bar's September 1, 2026 edition.
2. **The Bluebook system,** for what Rule 9.800 doesn't cover: short forms (Id., supra, short case cites), signals, parentheticals, subsequent history, case-name abbreviations, and sources such as the U.S. Code, other states' courts, and secondary sources. The Bluebook is copyrighted, so the skill works from the public-domain **Indigo Book**, which implements the same system, and bundles a condensed practitioner's version with its rule numbers. It also bundles a list of what the Bluebook's 22nd edition (2025) changed, so the agent knows where the Indigo Book is behind.
3. **The Florida Style Manual,** for Florida materials neither covers: bills, staff analyses, legislative journals, executive orders. The Manual is copyrighted, so the skill describes what it covers, points to the right section, and never guesses a form.

**Where Rule 9.800 and the Bluebook differ, Rule 9.800 wins.** For example, the 22nd edition abbreviates September as `Sep.`, but Rule 9.800 writes `Sept.`, so the skill uses `Sept.` A county court's parenthetical is `(Miami-Dade Cty. Ct. ...)`, the rule's form, even though the Bluebook writes `Cnty.` in case names. In a case name, which Rule 9.800 leaves to the Bluebook, `build` writes `Cnty.`

## What it does

### Answers citation questions

- **Shows the rule.** The text of Rule 9.800 or any part of it (`rule f`, `rule "(j)(3)"`, `rule notes`), headed by its amendment date and source, so the agent quotes the rule instead of its memory.
- **Gives the Florida form** of a court, county, reporter, Florida Law Weekly edition, rule set, or month. It names the subdivision that sets each and lists the common wrong variants: `Fla. 3rd DCA` for `Fla. 3d DCA`, `So.2d` for `So. 2d`, and `Fla. R. Jud. Admin.` for the renamed `Fla. R. Gen. Prac. & Jud. Admin.`
- **Converts case numbers** to the four-digit form the rule's examples use since September 1, 2026 (`SC09-839` becomes `SC2009-0839`, `1D01-2734` becomes `1D2001-2734`). It refuses numbers that can't exist, such as a Seventh District, or a Sixth District number before 2023.
- **Builds a citation from its parts.** It handles cases (Florida courts at every level, federal courts, and agencies), statutes, the Florida Statutes Annotated, the constitution, the Administrative Code, Laws of Florida, all 23 rule sets, and Attorney General opinions. Given `Fenelon v. State`, the Supreme Court, 1992, `594 So. 2d 292`, and pinpoint 293, it gives `Fenelon v. State, 594 So. 2d 292, 293 (Fla. 1992).`
  - Case names are abbreviated as the Bluebook system requires (`Insurance Company` becomes `Ins. Co.`).
  - Statutes, the constitution, and rules also come with their spelled-out form for use inside a sentence ("section 48.031, Florida Statutes (2014)").
  - Every citation it builds is checked before it's given. Parts that can't all be right (So. 3d in 1992, a Sixth District case before 2023, a criminal rule number in the civil rules) are refused with the reason.
  - A fact the script can't know, such as an exact date or a docket number, is left as a visible blank for the agent to fill from a case-law tool.
  - It rebuilds exactly all 50 of Rule 9.800's own examples that its citation types cover.

### Checks your own brief or motion

It reads `.txt`, `.md`, `.docx` (footnotes included), and `.pdf`. It finds every case, statute, constitution, rule, Administrative Code, session-law, and Attorney General citation, and documents from other cases cited in full (`Def.'s Mot. to Dismiss at 4, Able v. Baker, No. 1:20-cv-1 (S.D. Fla. Mar. 1, 2021)`); decides which tier governs each; and reports three kinds of finding:

- **Error:** clearly departs from Rule 9.800's form. Examples: `So.2d`, `Fla. 3rd DCA`, `F.S. 48.031`, `§ 48.031, Fla. Stat. Ann.`, `AGO 73-178`, `Id` without its period, a filing from another case with its pinpoint after the case's parenthetical instead of after its title.
- **Check:** probably wrong, or right only in some contexts, so the agent or you decide. Examples: no year on a Florida Statutes citation (reported once per document, since courts often leave it off), an old-form case number, a Florida Law Weekly cite more than a year old, an abbreviated form used inside a sentence, an Id. for a filing from another case.
- **Unrecognized:** a citation outside the script's forms, listed under the tier that governs it for the agent to check by hand. Cases in reporters the rule doesn't name (the regional reporters, F.R.D., B.R., Fed. Cl., T.C.) are listed here too, but the script still reads them, so their Id. citations are checked and their spacing (`N.E. 2d`) is an error.

**What it doesn't read, it counts.** Anything else that looks like a citation (a secondary source, a legislative document, a web page, a filing, or a citation in a form the script doesn't know) gets no check, so the report says how many such passages there are and on which pages, with record and transcript cites counted on a line of their own. Exhibits, the certificates, and the table of authorities are left out of the count. So "no finding" means checked and fine, not never read.

Each finding gives its location, the authority (a subdivision of Rule 9.800 or an Indigo Book rule number), what was found, and the fix. In a PDF, the location is the brief's printed page number, as in `p. 12 (PDF p. 19)`; in a Word file, the paragraph or footnote. A repeated error (`So.2d` forty times) is reported once with its count and every location.

What it checks, beyond abbreviations and spacing:

- **Facts the rule's tables can test.** A reporter series that doesn't fit the year (a 2015 case in So. 2d), a district court decision dated before that court existed, a Florida Law Weekly volume or section that doesn't fit the year or court, a docket number from a different court, an Eleventh Circuit case dated before 1981.
- **Date-dependent forms.** Old case numbers after September 1, 2026; Florida Law Weekly cites old enough to have a Southern Reporter cite; a statute year in the future; a Supreme Court case cited to S. Ct. alone years after it would be in U.S. Reports. The document's date comes from `--date`, else the e-filing stamp or the caption, else today, and the report says which.
- **Westlaw and LEXIS cites** without the docket number the rule pairs with them, or with that number missing its `No.`
- **Spelled-out forms:** "§ 48.031, Fla. Stat." used as part of a sentence, where the rule wants "section 48.031, Florida Statutes," and "Florida Constitution Article IV, § 8" for "article IV, section 8 of the Florida Constitution."
- **Pinpoints and dates in full citations:** `594 So. 2d 292 at 293` for `292, 293`; a case name with no comma before the volume (`Doe v. Roe, Inc. 594 So. 2d 292`); `(Fla.1992)` with no space; a month and day on a case published in a reporter, where the year alone belongs (a date that doesn't fit can mean a different ruling in the same case).
- **Court parentheticals in a database's style:** Westlaw's `(Fla. App. 4th Dist. 2012)` for `(Fla. 4th DCA 2012)`, and `4thDCA` or `Fla.4th` run together.
- **Punctuation that hides where a citation ends** (to check): parentheses that don't pair, a quotation mark that opens and never closes before a citation, and a statute subsection that can't be read, for which no fix is offered rather than one that drops it.
- **Quotations without a page** (to check): a quotation from a case whose citation gives no pinpoint, directly, through Id., or through a short form. A defined term in a parenthetical, `(the "Agreement")`, isn't taken for a quotation.
- **Signals and ellipses:** a signal capitalized after a semicolon inside a citation sentence (`; See also`), and an ellipsis in the document's own quotation that isn't three spaced periods (`...` or `…` for `. . .`).
- **Record-cite forms** (to check, once per document with a count): several paragraphs under one `¶` (`¶ 8, 12` for `¶¶ 8, 12`), and Id. used for record cites, which the Indigo Book advises against (with `Id. at 79` for `Id. ¶ 79` where it's used anyway). An Id. counts as repeating a record cite only when nothing else comes between: no authority the script didn't read, and no footnote's number. A court's own rules on citing the record govern over these.
- **Short forms across the whole document,** which no model holds well in a long brief:
  - an Id. after a string citation;
  - an Id. whose pinpoint doesn't fit what it refers to (a page after a statute);
  - a short form before the case's full citation, or for a case never cited in full (a full citation with a placeholder volume, `— So. 3d —, 2023 WL 1234567`, counts);
  - a section cited without its code (`See § 48.031(2).`) before the code's first full citation, and a constitution cited without its name (`Art. V, § 6(b)`), which has no short form;
  - a short form whose volume differs from the full citation's;
  - a short form missing `at` (`Fenelon, 594 So. 2d 294.` after the full citation);
  - a pinpoint before the case's first page;
  - supra used for a case;
  - a full citation repeated on the same page where a short form would do (one in a section heading, or after a new heading, doesn't count).
- **Case-name typeface** (9.800(q)) in Word and Markdown files, where italics survive.

### Reviews the other side's filing

In someone else's brief, a citation that's wrong in substance matters far more than one in the wrong form. Opposing mode orders the report that way:

1. **Facts that don't match:** the court, year, party names, volume, or first page differ from what a case-law research tool finds, or the case can't be found. Cases the agent looked up but found in none of its databases are listed apart, with what was searched.
2. **Pinpoints out of range:** a pinpoint page before the case's first page or past its last, including pinpoints on short forms and Id.
3. **Quotations to verify:** every quotation of four words or more, tied to the citation that gives its source and that citation's pinpoint, for the agent to check with a quote-verification tool, or by fetching each source by citation and comparing locally, which keeps a confidential filing's text private. A quotation whose citation gives no page is marked. Quotations with no citation (often record quotes) are listed separately.
4. **Form errors,** summarized last by check and authority, since they're rarely worth raising.

The count of what the script doesn't read heads the report, since in another side's filing those authorities are the ones to look up by hand.

The facts loop:

- The skill lists each case once, as a citation alone, for a citation tool that checks a whole list in one request (CourtListener's citation lookup takes up to 250 at a time). The list holds nothing from the brief but its citations.
- The agent looks up, one at a time, only the cases that tool doesn't find, and records what it finds in a facts file the skill writes (full citations, short forms, and Id. merged, with what the brief claims).
- The skill compares claim with finding and does the page arithmetic.
- Filings from other cases (a brief or motion cited by its case's docket) aren't cases, so they're left out of the list and the lookups, and listed apart, under the facts, to confirm by docket if needed.

**What it costs.** The script's report is free: it runs offline in about a second. Confirming cases costs case-law lookups, and a free tier allows only so many (CourtListener's: a few a minute, about a hundred a day), which is why the batch comes first. Verifying a quotation means reading its source, often several thousand tokens each. So the agent gives you the free report first, says what confirming the cases and the quotations would take, and goes only as far as you choose.

**Exhibits.** A filing with exhibits attached (a slip sheet such as "Exhibit 1", a short cover sheet such as "Exhibit A Proposed Order", or a Westlaw or Lexis printout of an opinion) gets a note at the top of the report: their citations and quotations are another writer's. `--last-page N` checks only the filing.

The judgment stays with the agent and the arithmetic with the script. The report frames every item as something to confirm: a mismatch can be a typo, a parallel cite, the wrong case, or a case that doesn't exist. It never calls a case fake.

## What it doesn't do

- **Form, not substance.** It doesn't decide whether a case exists, supports the point it's cited for, or is still good law. The facts loop compares what a case-law tool finds with what the brief claims; the lookup is the agent's, with its own tools.
- **Practitioner forms only.** No law-review typefaces or footnote conventions.
- **Precision over recall.** It flags only what it can tell is a departure; a checker that flags correct citations gets ignored. So it skips, by design:
  - citations outside its forms that it can't read at all (secondary sources, legislative documents, web pages, filings): counted, with their pages, as above;
  - citations inside quotation marks or block quotes (they're the quoted writer's form; the report counts them, with their pages);
  - an Id. whose antecedent it can't see: after something that looks like an authority it didn't read (a record cite, a report or web page, a filing, an unrecognized citation), a quotation, or a page split. These are counted in the report;
  - a quotation's source across such an authority: the quotation is listed with no citation rather than tied to the wrong one;
  - pinpoint checks on a citation whose page may come after what it read (`..., 2020 WL 1234567 (M.D. Fla. Mar. 1, 2020), at 19`);
  - "never cited in full" for a short form whose volume and reporter turn up in a passage it didn't read (a table's cells, for instance), where the full citation may be.
- **Record citations are checked only for form.** `(R. 45)` and appendix cites follow each court's own practice, so the script reports only the paragraph-sign and Id. forms above, as things to check, and never whether a record cite points where it should. A record cite is never read as a court and year: `(R.1850)` is a page of the record, not a parenthetical missing its space.
- **The Bluebook system is checked through the Indigo Book,** which tracks an earlier Bluebook edition. The 22nd edition's changes are listed for the agent, but the script's short-form checks follow the Indigo Book's rules. The skill quotes no Bluebook text.
- **It doesn't edit your file.** It reports locations and fixes; you or your agent make the changes.
- **OCR is a separate step.** A scanned PDF stops with a message that it needs OCR, with the OCRmyPDF command to run (see Setup). OCR misreads some characters (`Id.` as `ld.`, `5th` as `Sth`, a dropped hyphen in a page range), and the script doesn't guess around them, so read an OCR'd finding's pinpoint against the page.
- **Known limits of reading text:**
  - Block quotations are found by a PDF's indentation or a Word file's paragraph formatting. Plain or piped text shows neither, so there a quotation's end can't always be seen, and a citation just after one may be skipped. A quoted list whose first lines hang left of the rest can be missed in a PDF.
  - A citation split across pages inside a footnote is checked in two halves.
  - A certified-copy view from a clerk's portal carries a corner-to-corner watermark (NOT A CERTIFIED COPY). The script drops diagonal text, so it doesn't land inside citations, unless dropping it would take more than a watermark's worth from a page (a pdftotext quirk seen in a hand-built file); then every character is kept.
- **Rule 9.800 isn't mandatory.** Its 1977 committee note says so. The skill presents its forms as Florida's standard, and calls departures departures, not violations.

## How it was tested

Before release, it was run against 28 Florida court opinions and 18 Florida Supreme Court briefs. The opinions come from the Supreme Court and all six District Courts of Appeal, 13 of them filed after the September 1, 2026 amendment. Courts follow Rule 9.800, so every flag on an opinion was treated as a false positive until shown otherwise; each flag left is a confirmed departure by the court itself, such as `(Fla. 2nd DCA 2013)` or a 1925 case cited to So. 2d. Planted errors in 65 citations and in four altered briefs (a wrong pinpoint, year, court, and quotation) are all found. Five trial-court motions (one scanned and OCR'd, two image-only, two born digital, one of those a certified copy from a clerk's portal with a diagonal watermark, one with five exhibits attached) were then run through the workflow; every false flag they surfaced was fixed and is covered by a test. The corpus and the motions read the same under both pdftotext builds (Poppler and Xpdf).

## Setup

1. **Python 3.9 or later.** The scripts use only the standard library; there is nothing to install.
2. **For PDFs, `pdftotext`** (optional). The skill runs it to read a PDF:
   - macOS: `brew install poppler`
   - Debian or Ubuntu: `sudo apt-get install poppler-utils`
   - Fedora: `sudo dnf install poppler-utils`
   - Windows: Git for Windows includes one (Xpdf's), available in Git Bash.

   Without it, the agent can extract the PDF's text another way, with a form feed between pages, and pipe it in (with `pdftotext`, add `-nodiag`, which drops a diagonal watermark).
3. **For scanned PDFs, OCRmyPDF** (optional). It adds a text layer on your own machine, so a confidential filing isn't uploaded anywhere: `ocrmypdf --output-type pdf --deskew brief.pdf brief-ocr.pdf`, then check `brief-ocr.pdf` (add `--skip-text` when only some pages are scanned).
   - macOS: `brew install ocrmypdf`
   - Debian or Ubuntu: `sudo apt-get install ocrmypdf`
   - Fedora: `sudo dnf install ocrmypdf tesseract-osd`
   - Windows: `winget install -e --id tesseract-ocr.tesseract`, `winget install -e --id astral-sh.uv`, then `uv tool install ocrmypdf` (Ghostscript is recommended too). See OCRmyPDF's [installation guide](https://ocrmypdf.readthedocs.io/en/latest/installation.html).
4. **Install the skill** (see the repository README).

Everything runs offline. Only the optional self-test uses the network.

## Try it

Ask your agent things like:

- "How do I cite a Fourth DCA case that's only in Florida Law Weekly?"
- "What's the current abbreviation for the Rules of Judicial Administration?"
- "Convert SC09-839 to the new case-number form."
- "Build the citation for section 768.28, Florida Statutes (2025), the way it should read inside a sentence."
- "Check the citations in my initial brief," with the file attached.
- "Review the citations in the answer brief we were served. Which cases or pinpoints don't hold up?"

The script also works on its own: `python3 scripts/fl_cite.py --help`. Its commands are `rule`, `abbrev`, `casenum`, `checks` (the check records), `build`, and `check` (with `--json`, `--last-page`, `--mode opposing`, `--cite-list`, `--facts-template`, and `--facts`).

## Sources

| Source | Used for | License |
|---|---|---|
| Fla. R. App. P. 9.800, as amended by *In re Amendments to Florida Rules of Appellate Procedure*, No. SC2025-0241 (Fla. June 11, 2026) (corrected opinion), effective September 1, 2026 | The rule's text (`references/rule-9.800.md`), checked word for word against The Florida Bar's September 1, 2026 edition, and the forms behind every check | Public domain: court rules carry no copyright |
| [The Indigo Book](https://indigobook.github.io/), 2d ed. (2021), 2023 update | The Bluebook-system forms Rule 9.800(p) sends there: short forms, case-name abbreviations (Table T11), and the condensed reference in `references/indigo-practitioner.md` | CC0 public-domain dedication |
| [The Florida Style Manual](https://www.floridastylemanual.com/) (Florida State University Law Review, 9th ed. 2024) | Described and linked for the third tier, not copied | Copyrighted; not bundled |
| Public descriptions of the Bluebook's 22nd edition (2025) | `references/bluebook-22-changes.md`, a list of changes stated in the skill's own words, with sources | No Bluebook text is quoted |

The self-test reads two court opinions from the Florida courts' website and runs one search on [CourtListener](https://www.courtlistener.com/) (Free Law Project) for new amendments to Rule 9.800. It identifies itself in its User-Agent and makes a handful of requests per run.

This project is not affiliated with or endorsed by the Supreme Court of Florida, The Florida Bar, the Florida State University Law Review, the publishers of The Bluebook, or the editors of the Indigo Book.

## Testing

`python3 scripts/selftest.py` runs 17 checks in a few seconds:

- every command on fixed input: the rule, abbreviations, case numbers, building citations, checking documents, short forms, page numbers, and the facts loop;
- two District Court of Appeal opinions filed after the September 1, 2026 amendment, fetched live and checked (they should come back clean);
- a search for new Florida Supreme Court opinions amending Rule 9.800.

Each reports one of:

- **ok**;
- **FAIL:** the script broke;
- **CHANGED:** a court replaced an opinion, or a new amendment appeared. That's the law moving, not a bug;
- **FLAKY:** a source hiccupped and the rerun passed;
- **BLOCKED:** a source couldn't be reached, or `pdftotext` isn't installed.

## License

This skill is licensed under the MIT License; copyright 2026 Attorney Nate.
