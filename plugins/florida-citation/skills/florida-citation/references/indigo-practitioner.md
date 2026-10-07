# The Indigo Book for practitioners: a condensed reference

Rule 9.800(p) sends every form Rule 9.800 doesn't cover to the latest edition of the Bluebook. This skill checks those forms through **The Indigo Book**, an open implementation of the same citation system, because the Bluebook itself is copyrighted and can't be bundled.

- **Edition:** *The Indigo Book: A Manual of Legal Citation* (Christopher Sprigman & Jennifer Romig et al. eds., Public.Resource.Org 2d ed. 2021), 2023 update, published August 21, 2023.
- **License:** CC0 public-domain dedication. This file condenses and paraphrases it, with short examples taken from it or written for this skill.
- **Full text:** <https://indigobook.github.io/> (PDF: <https://indigobook.github.io/versions/indigobook-2.0-rev2023-2.pdf>; source: <https://github.com/indigobook/text>).
- **Not the Bluebook:** the Indigo Book tracks an earlier Bluebook edition. Where the 22nd edition (2025) changed a rule this file covers, see `bluebook-22-changes.md`. The Indigo Book isn't affiliated with or endorsed by the Bluebook's publishers.
- **Scope:** what briefs and motions use. No law-review typeface or footnote conventions. Rule numbers below are the Indigo Book's (R*n*), never the Bluebook's.
- **Florida first:** for Florida courts, statutes, rules, and agencies, Rule 9.800 governs; use `fl_cite.py rule` and `build`, not this file. The Indigo Book's own Florida entry (Table T3) is out of date: it counts five District Courts of Appeal (there are six since 2023) and cites "Fla. R. App. P. 8.800" for 9.800.

Contents: [Citation placement](#citation-placement) · [Signals](#signals) · [Pinpoints](#pages-sections-and-pinpoints) · [Full cases](#full-case-citations) · [Case names](#case-names) · [Courts and reporters](#courts-reporters-and-years) · [Parentheticals](#parentheticals) · [Subsequent history](#subsequent-history) · [Short forms](#short-forms) · [Statutes, rules, constitutions](#statutes-rules-and-constitutions) · [Record and court documents](#record-and-court-documents) · [Quotations](#quotations) · [What the checker enforces](#what-fl_citepy-enforces-from-this-file)

## Citation placement

- **R3.2 Citation sentence:** a citation standing alone after the text sentence it supports, ending in a period. Several authorities in one citation sentence are separated by semicolons (a string citation).
- **R3.3 Citation clause:** a citation set off by commas inside a sentence, supporting only part of it. A signal at its start stays lowercase.
- **R3.4 Embedded citation:** a citation read as part of the sentence's grammar (`Since Nelson v. Sears, Roebuck & Co., 312 U.S. 359 (1941), the Court ...`). Case names here are barely abbreviated (R11.4). Rule 9.800 adds its own spelled-out forms for Florida authorities used inside a sentence.

## Signals

**R4.2 Categories, in the order they must appear (R4.3):**

| Category | Signals |
|---|---|
| Support | [no signal], *E.g.*, *Accord*, *See*, *See also*, *Cf.* |
| Comparison | *Compare* ... *with* ... |
| Contradiction | *Contra*, *But see*, *But cf.* |
| Background | *See generally* |

- **R4.3 Combining:** in citation sentences, signals of one category share a sentence, separated by semicolons; a new category starts a new citation sentence. In a citation clause, all signals share the clause, separated by semicolons.
- **R4.4 Order within a signal:** a helpful, logical order, separated by semicolons. (The older strict hierarchy of authorities is now a guide, not a rule.)
- **R4.5 Capitalization:** capitalize a signal that begins a citation sentence; lowercase in a citation clause.
- **R4.6.1 No signal:** the source states the proposition, is quoted, or is named in the sentence.
- **R4.6.2 *E.g.*,** one of several sources stating the same thing. After another signal: *See, e.g.*, (the comma after *e.g.* isn't italicized).
- **R4.6.3 *Accord*:** further sources for a proposition quoted from one, or another jurisdiction's law agreeing.
- **R4.6.4 *See*:** the source clearly supports the proposition, but an inferential step is needed.
- **R4.6.5 *See also*:** additional support after supporting authority has been cited; a parenthetical is recommended.
- **R4.6.6 *Cf.*:** support by analogy; always add a parenthetical explaining the connection.
- **R4.6.7 *See generally*:** background; a parenthetical is recommended.
- **R4.7 *Compare* ... *with* ...:** a comparison that supports the point; parentheticals strongly recommended. A comma before *with*; several sources on a side are joined by commas and a final *and*.
- **R4.8 *Contra*, *But see*, *But cf.*:** direct contradiction; clear opposition; opposition by analogy (always with a parenthetical).

## Pages, sections, and pinpoints

- **R5.1.1 Pages:** the number alone, never "p." or "pp." Use "at" where needed for clarity (`Id. at 1512`, `Smith, 594 So. 2d at 293`).
- **R5.1.2 and R11.7.2 Spans:** a hyphen or en dash; drop repeated digits but keep the last two: `1240-41`, `799-801`.
- **R5.1.3 and R11.7.4 Footnotes:** page, space, `n.`, number with no space: `285 n.4`.
- **R5.2.1 Sections:** `§` and a space before the number; `§§` for more than one. Hyphens and parentheses in a section number are kept exactly: `§ 2000e-2(a)(1)`.
- **R5.2.3 Section spans:** a hyphen, en dash, or "to": `§§ 3681-82`, `§§ 51-30-20 to -26`. Never "et seq."
- **R5.3 Paragraphs:** `¶ 11`, never with "at."
- **R11.7 Pinpoint every case citation,** full or short, when it supports a specific point. If the point is on the case's first page, repeat it: `216 S.E.2d 356, 356`.
- **R11.7.1 Scattered pages:** commas: `1026, 1028`.
- **R11.7.3 Medium-neutral cases:** pinpoint by paragraph: `2021-Ohio-726, ¶ 9`.
- **R12.4.1 Westlaw and LEXIS:** star pages: `2013 WL 5811261, at *7`.

## Full case citations

**R11.1 Elements, in order:** case name (italicized or underscored; the comma after it isn't), volume, reporter, first page, pinpoint, then court and year in one parenthetical. Then any weight-of-authority and explanatory parentheticals (R10, R13), then subsequent history (R14).

```
Seltzer v. Green Day, Inc., 725 F.3d 1170, 1176 (9th Cir. 2013).
Mercer Univ. v. Stofer, 841 S.E.2d 224 (Ga. Ct. App. 2020).
```

- **R11.1.1 Parallel citations:** when a reporter shows the court unambiguously, the court is left out of the parenthetical; when a medium-neutral cite shows the year, the year may be too. Florida's own forms: Rule 9.800(a)-(c).
- **R12.4.1 Cases only on Westlaw or LEXIS:** add the docket number before the database cite and give the full date: `State v. Green, No. 2012AP1475-CR, 2013 WL 5811261, at *7 (Wis. Ct. App. Oct. 30, 2013).` Rule 9.800(a)(3) and (b)(2) give the Florida form, with the four-digit case number.
- **R12.4.2 Opinions only on a court's website:** docket number, `slip op. at` page, court and full date, and the URL.

## Case names

**R11.3 In citation sentences and clauses**, abbreviate:

- **R11.3.1** every word in Table T11, the common-word table (`Ins.`, `Dep't`, `Ass'n`, `Corp.`, `Int'l`, `Mut.`, `Prop.`). `build` applies it (408 words, in `data/florida.json` as `case_name_words`). "County" is discussed under [Counties](#counties).
- **R11.3.2** geographical words per Table T12 (`Fla.`, `Cal.`), but never a place that is itself a whole party: `South Dakota v. Fifteen Impounded Cats`, not `S.D. v. ...`.
- **R11.3.3** at discretion, other words of eight or more letters if the result is unambiguous.

**R11.4 In a textual sentence**, abbreviate only `&`, `Ass'n`, `Bros.`, `Co.`, `Corp.`, `Inc.`, `Ltd.`, `No.`, and widely known initials.

**R11.5 Truncation, in every context:**

- **R11.5.1-.2** surnames only (no first names or initials); only the first party on each side; no "et al."
- **R11.5.3** well-known initials stand alone: `FCC`, `SEC`, `NAACP`.
- **R11.5.6** one business designation is enough: `A.H. Robins Co. v. Piccinin`, not `Co., Inc.`
- **R11.5.7** "on the relation of" and the like become `ex rel.`; "in the matter of," "petition of" become `In re`. In bankruptcy, the adversary name comes first with the `In re` name in a parenthetical.
- **R11.5.8** `United States` is spelled out as a party, without "of America."
- **R11.5.9** drop "State of," "People of," "Commonwealth of." Keep `State` (or `People`, `Commonwealth`) alone when citing that state's own courts (`State v. Smith ... (Fla. 2010)`); otherwise use the state's name (`International Shoe v. Washington`).
- **R11.5.10** keep "City of" or "Town of" when it begins a party's name; drop it mid-name.
- **R11.5.11** drop most prepositional phrases of place, unless the party would be left with one word or the phrase is part of a business name or follows "City of."
- **R11.5.12** drop a leading "The" (except "The King" or "The Queen," and in rem objects).
- **R11.5.13** the Commissioner of Internal Revenue is `Comm'r` in citations.
- **R11.5.15** an identifier for a case decided more than once, in a parenthetical: `(Liriano II)`.

### Counties

- **In a Florida county court's parenthetical,** Rule 9.800(c)(2) governs: `(Miami-Dade Cty. Ct. Oct. 8, 2014)`. `fl_cite.py abbrev` and `build` give the form.
- **In a case name,** Table T11 lists `Cnty.`, with a note recommending the traditional `Cty.` The current Bluebook uses `Cnty.`, so `build` writes `Cnty.`; `check` accepts either. See `bluebook-22-changes.md`.

## Courts, reporters, and years

- **R12.1** court and year in one parenthetical: `(5th Cir. 1951)`, `(S.D.N.Y. 2011)`.
- **R12.3.1** leave the court out when the reporter shows it: U.S. Reports, a state's official reporter. `(1974)`, not `(U.S. 1974)`.
- **R12.3 (divisions)** generally omit an intermediate court's division, but Florida requires the district: Rule 9.800(b).
- **U.S. Supreme Court (Table T1):** cite U.S. when the case is there (including preliminary pagination); otherwise S. Ct.; otherwise L. Ed.; otherwise U.S.L.W.
- **Federal courts of appeals:** F., F.2d, F.3d, F.4th (F.4th from mid-2021). Unpublished decisions: F. App'x (2001-2021). Circuits: `1st Cir.`, `2d Cir.`, `3d Cir.`, `4th Cir.` ... `11th Cir.`, `D.C. Cir.`, `Fed. Cir.` Rule 9.800(m) gives the same forms.
- **District courts:** F. Supp., F. Supp. 2d, F. Supp. 3d, with the district: `(S.D. Fla. 2020)`, `(M.D. Fla. 2019)`. Rule 9.800(n).
- **R7.2 Ordinals:** `2d` and `3d`, never `2nd` or `3rd`; no superscripts.
- **State courts of other states:** the regional reporter (A., N.E., N.W., P., S.E., S.W., So., with their series) and the court as Table T3 abbreviates it: `(Ga. Ct. App. 2020)`, `(Colo. 1987)`.

## Parentheticals

- **R10.1.1** an explanatory parenthetical that doesn't quote begins lowercase, usually with a present participle: `(holding that ...)`.
- **R10.1.2** a quoting parenthetical starts with a capital and ends with a period only when the quotation reads as a full sentence.
- **R10.2 Order:** date; `[hereinafter ...]`; weight of authority (`(en banc)`, `(per curiam)`, `(plurality opinion)`, `(Smith, J., dissenting)`); quotation notes (`(alteration in original)`, `(emphasis added)`, `(citations omitted)`, `(internal quotation marks omitted)`); `(quoting ...)` or `(citing ...)`; explanatory parenthetical; then subsequent history.
- **R13.1** weight of authority goes after the date parenthetical: `(Fla. 2010) (per curiam)`, `(Marshall, J., dissenting)`, `(unpublished table decision)`.
- **R8.2.6 and the Inkling there:** no `(emphasis in original)`, and no `(citation omitted)` for a citation that only ended a quoted sentence. `(cleaned up)` isn't part of the Indigo Book's system yet, though courts use it.

## Subsequent history

- **R14.1** include a case's later history in the same litigation, with the explanatory phrase italicized (Table T14): `aff'd,` `rev'd,` `rev'd on other grounds,` `vacated,` `cert. granted,` `cert. denied,`.
- **R14.2** leave out denials of rehearing and of discretionary review (`reh'g denied`), and history on remand, unless they matter to the point. Include `cert. denied` only for a case decided within the last two years, or when the denial matters.
- **R14.2.2** include later negative history from other cases when it bears on the point: `overruled by`, `superseded by statute, ..., as recognized in ...`.
- **R14.3** a new case name in the history follows `sub nom.` (no comma after it), but not when the parties are merely reversed or for a cert. or rehearing denial.

```
Leonard v. Pepsico, Inc., 88 F. Supp. 2d 116, 127 (S.D.N.Y. 1999), aff'd, 210 F.3d 88 (2d Cir. 2000).
```

## Short forms

Rule 9.800 has no short forms; these are the Bluebook system's, and `check` enforces them (see the last section).

- **R6.1** cite every source in full the first time.
- **R6.2.1** after that, a short form that follows from the full citation.
- **R6.2.2 *Id.*:** the same source as the immediately preceding citation.
  - Capitalized when it starts a citation sentence; lowercase in a clause. Always with its period, never "Id" or "ibid."
  - Alone, it means the same pinpoint too; with a new pinpoint: `Id. at 1513` for pages, `Id. § 9` or `Id. ¶ 12` with no "at."
  - It may follow another Id. or a short form.
  - Not after a string citation, even for the string's last source (R15.3.3).
  - Not for record cites (`R. at 2`); see R26.
  - A citation inside the preceding citation's parenthetical (`(quoting ...)`) doesn't count as "the preceding citation" (R15.3.3's note).
- **R6.2.3 *Supra*:** for secondary sources (books, articles, internet sources), legislative hearings, and court documents (R26). Never for cases, statutes, constitutions, most legislative materials, Restatements, model codes, or regulations. Also fine as an internal cross-reference ("Part II, supra").
- **R15.1 In text:** once the case is named in the sentence, the citation after it can be just `233 N.E.2d at 219`.
- **R15.2.1 When a short form may be used:** after the full citation, when the reference is unambiguous and the full citation is easy to find earlier. A writer may repeat the full citation after a new heading or page break, or after several Ids.
- **R15.2.2 The form:** the first party's name (italicized), volume, reporter, `at`, pinpoint: `Fenton, 233 N.E.2d at 219.` No first page.
- **R15.2.3** use the other party's name when the first is a government or a common name (`United States`, `State`): `Carmel, 548 F.3d at 573`; `Raich, 545 U.S. at 8`.
- **R15.2.4** shorten a long party name if it stays clear; use `[hereinafter ...]` if needed.
- **R16.2, R17.5, R22** statutes and regulations: `§ 27.001`, `Id.`, `Id. § 209`. A different title of a code needs more than Id.
- **R23.3** constitutions have no short form; cite them in full each time, though `Id.` works for the same provision cited consecutively.

## Statutes, rules, and constitutions

For Florida ones, use Rule 9.800 (`fl_cite.py rule f`, `rule j`, `rule e`) and `build`. For others:

- **R16.1.1 U.S. Code:** `42 U.S.C. § 1983.` An act's name may precede it.
- **R16.1.2** no year for the current Code; give the edition's year for a historical version.
- **R16.1.4-.5 Annotated codes:** `5 U.S.C.A. § 572 (West)`, `5 U.S.C.S. § 572 (LexisNexis)`, adding a year only when it matters.
- **R16.1.7 Session laws:** `Pub. L. No. 111-148, § 1101, 124 Stat. 119, 141-43 (2010).`
- **R17 Other states' codes:** the form in Table T3, with the code's year in a parenthetical (`O.C.G.A. § 51-3-22 (2020)`). Many states' practice omits the year.
- **R17.4** a repealed statute: `(repealed 2015)`.
- **R18.1.1 Rules of procedure and evidence:** abbreviation and number, no `§`, no year for current rules: `Fed. R. Civ. P. 12(b)(1)`, `Fed. R. App. P. 1`, `Fed. R. Evid. 403`.
- **R19.1 Federal regulations:** `21 C.F.R. § 164.150 (2020)`, with the year of the edition.
- **R23.1 U.S. Constitution:** `U.S. Const. art. I, § 8, cl. 3.` `U.S. Const. amend. XIV, § 1.` No date for current provisions; `(repealed 1933)` for repealed ones. Rule 9.800(o) agrees.

## Record and court documents

- **R24.1** abbreviate document titles per Table T18 (`Compl.`, `Def.'s Mot. to Dismiss`, `Pl.'s Br.`, `Aff.`, `Dep.`); the record is `R.`
- **R24.2** pinpoint pages with "at" (`R. at 22`; `R. 22` to save words, if consistent); page and line with a colon: `Smith Dep. 5:21-6:10.`
- **R24.4** in federal court, add the ECF number: `Pl.'s Compl. ¶ 12, ECF No. 147.`
- **R24.5** record cites may sit in parentheses or brackets, with the period outside: `(R. 24).`
- **R25** a document from another case: the document, pinpoint, the case's citation, and the docket number in a parenthetical.
- **R26** short forms for court documents may use supra; avoid id. for them, and never use it for record citations.
- A Florida court's own rules and orders on citing the record and appendix govern over these.

## Quotations

- **R8.1.1** 49 words or fewer in quotation marks; 50 or more as a block quotation (R9.1) with no quotation marks, the citation starting at the left margin after it.
- **R8.1.2** periods and commas go inside the closing quotation mark.
- **R8.1.3** cite the quotation right after the sentence, or as a clause when only part of the sentence is quoted.
- **R8.2** alterations in brackets: `[T]he`, `claim[]`; `[sic]` for a significant error in the original.
- **R8.2.4** note changes in a parenthetical: `(emphasis added)`, `(alteration in original)`, `(citation omitted)`, `(internal quotation marks omitted)`, `(footnote omitted)`.
- **R8.3** ellipses are three spaced periods (`. . .`). None at the start of a quotation (bracket the capital instead) or after the last sentence quoted. At the end of a sentence, the ellipsis goes before the sentence's own period: `knowledge . . . .`

## What `fl_cite.py` enforces from this file

`check` reports these findings with the tier "Bluebook system (Indigo Book)":

| Check | Rule |
|---|---|
| `Id` without a period; `ibid.` | R6.2.2 |
| Id. whose pinpoint doesn't fit the antecedent (a page after a statute, a section after a case) | R6.2.2 |
| Id. after a string citation | R15.3.3 |
| `supra` for a case | R6.2.3 |
| A pinpoint before the case's first page | R11.7 |
| A short form before the full citation, or with no full citation at all | R15.2.1 |
| A full citation repeated on the same page, where a short form would do | R15.2.1 |
| A short form whose volume differs from the full citation's | R15.2.2 |
| A short form missing `at` (`Fenelon, 594 So. 2d 294.`) | R15.2.2 |
| Spacing in a reporter Rule 9.800 doesn't name (`N.E. 2d`, `F. R. D.`) | T1.1, T3 |
| `at` before a pinpoint in a full citation (`292 at 293`); no space after the comma (`292,293`) | R11.1 |
| A quotation from a case whose citation gives no page | R11.7 |
| A quotation mark that opens and never closes before a citation | R8.1 |
| A signal capitalized after a semicolon inside a citation sentence (`; See also`) | R4.5 |
| An ellipsis in the document's own quotation that isn't three spaced periods (`...`, `…`) | R8.3.1 |
| Several paragraphs under one `¶`; Id. for a record cite, and `Id. at` before a paragraph number (once per document, as a check) | R5.3, R26 |

Everything else in this file is for the agent to apply when building or reviewing a citation by hand. Citations outside Rule 9.800 that `check` doesn't recognize are listed as "unrecognized" under this tier; check them against this file, and against the full Indigo Book for anything not here.
