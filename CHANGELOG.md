# Changelog

## florida-citation 1.3.4 (2026-10-10)

Fewer false flags and better-named findings, from a third precision batch of 14 filings run on 1.3.3. Footnotes numbered with a slash (`7/The court ...`) are read as footnotes, and a footnote that runs over to the next page is found there above the next one, so an Id. isn't linked to a footnote's case. A quotation that ends a page takes its citation from the top of the next page, past the page's footnotes. A brief or petition cited on Westlaw (`Reply Brief of Able in Baker, 2012 WL 1 (Fla., filed June 1, 2012)`) is read as a filing from another case: no docket number is asked for, and it isn't taken for a case's short form. A block quotation whose lead-in gives its source and page (`As stated in Able, 1 So. 3d 1, 5 (Fla. 2013):`) takes that source, not a `See also` citation after the block. A record document's name in prose (`the Declaration of Condominium`) is no longer read as a record cite; with a pinpoint (`Declaration ¶ 4`, `Section 2.2 of the Declaration`) it still is. A table of authorities whose entries hang, the case name on one line and the citation indented below, isn't reported as missing the name's comma. A record cite whose page reads as a year (`(T. 1975)`) is counted with the record cites. And several findings now name the right problem: a circuit court written without `Ct.` (`(Fla. 8th Cir. 2016)`), `U.S` or `US.` for `U.S.`, a period after `DCA`, the Florida Public Employee Reporter's name spelled out, a note on a case's first page (`410 n.12`) read as its pinpoint, the amendment fix taking a list (`amend. IV, XIV`), `f-name-first`'s fix taking spaced subsections, and a statute's year after a stray comma.

## florida-citation 1.3.3 (2026-10-10)

Fewer false flags from how a PDF is read, how a quotation finds its source, and which record cites the script sees, from the two precision batches. A hyphen at a line's end between digits is kept, where `pdftotext` drops it as if a word were broken: `Rule 4-1.5` no longer reads as `41.5`, nor a range `476-77` as `47677`. A footnote marker set before a dash (`law11--and`) is read as one, so a footnote's citation isn't taken for the body's. A quotation takes its source from the citation sentence right after its own sentence, before a case the sentence only names (`In Able, 1 So. 3d 1 (Fla. 2010), the court read "..." Id. at 3.`); when that citation sentence is one the script can't read, the quotation is left for you to source rather than reported as having no page. Record cites in the shapes briefs use, an abbreviation and a page (`App'x 7`, `ROR:41`, `IB. P. 30`, `DAR Vol. 2 at 30`), are read as record cites, so an Id. after one isn't linked past it, and the count lists them with the record cites.

## florida-citation 1.3.2 (2026-10-10)

Fewer false flags, from a second precision batch of 17 filings (Florida Supreme Court briefs in new kinds of cases, older briefs, and Fifth District briefs) run on 1.3.1. A record cite with no space, such as `(R.1850)`, is no longer read as a court and a year missing its space. An agency order's docket and order numbers (`Docket No. 20200001-EI, Order No. PSC-2020-0001-FOF-EI`) are read as its numbers, not as part of its name, so the name isn't reported as missing a comma. A full citation repeated after a new heading (`ARGUMENT`, `B. Standard of Review`) isn't reported as a repeat. A district's ordinal (`1st DCA`) is no longer read as a pinpoint. And five findings now name the right problem: `Fla.` run into the district (`(Fla.4th DCA 2005)`) is a district court missing a space, not a court outside Rule 9.800 (new check `b-fla-glued`); `F. Supp` without its period is the rule's reporter misspelled; a docket number given without `No.` (`17-12345`) is read, so the finding asks for `No.` rather than for a docket that's there; and the fixes for an arabic article with no comma (`Fla. Const. Art. 1 § 2`) and for a statute's name written twice now cover the whole citation.

## florida-citation 1.3.1 (2026-10-10)

Fewer false flags, from a precision batch of 13 Florida Supreme Court filings run on 1.3.0. A district court's designation (`2nd DCA`, `D.C.A.`, `4thDCA`) is checked only in a citation's court parenthetical, not in sentences or headings that name the court. An Id. is listed as repeating a record cite only when nothing else comes between: no source the script doesn't read, and no footnote whose text may be what the Id. refers to. A full citation in a section heading no longer makes the body's citation under it a "repeat." A recent case cited with a placeholder for its volume (`— So. 3d —, 2023 WL 1234567`) counts as cited in full, so its Westlaw short form isn't reported as never cited in full; and that finding is withheld when a passage the script didn't read may hold the full citation. A district court's parenthetical with its district missing or after `DCA` (`(Fla. DCA 2020)`, `(Fla. DCA 3rd 2020)`) is reported as a court to check under Rule 9.800, not as a court outside it.

## florida-citation 1.3.0 (2026-10-09)

Fewer false flags, and a count of what the script doesn't read. A claim that depends on context (what an Id. refers to, which citation a quotation comes from, whether a pinpoint is in range) is now withheld across text the script can't read: a report cited by page ("Agency Report, at 3"), a short name given in brackets, a filing, a web page, a record cite in a shape it doesn't know. Where that happens the report says "find the source by hand" instead of guessing. The report ends with two "Not checked" lines, with pages: the passages that look like citations the script doesn't read (secondary sources, legislative materials, web pages, filings, forms it doesn't know), and the record or transcript cites. Filings from other cases ("Initial Br., Able v. Baker, No. ...") are read as court documents: the pinpoint belongs after the title, Id.s to them are listed, and they stay out of the case list your agent looks up. Six Rule 9.800 forms are read and flagged now: an arabic article in a constitution cite ("Art. 1, § 16"), a constitution cite with no comma before the section, statute subsections written with spaces ("§ 1.01 (7) (f)"), "Fla. Stat." run into the section sign, a code's missing period ("Fla Stat."), and a short statute cite with no code named ("See § 1.01(2).") before any full citation; a constitution has no short form. Read without a finding now: a footnote number glued after "Fla. Stat.", and session laws citing several sections.

## florida-citation 1.2.0 (2026-10-06)

Two new checks: a short form missing "at" (Fenelon, 594 So. 2d 294.), and a case name with no comma before the volume (Doe v. Roe, Inc. 594 So. 2d 292). An abbreviated statute or rule cited as part of a sentence is now also caught when it ends the sentence ("as required by § 48.031, Fla. Stat.") or when the sentence goes on after it with no comma. A quotation introduced by a citation ("In Smith, 594 So. 2d 292, the court held that '...'") is now tied to that citation, so a quotation with no page is reported there too. Case names that were lost before are read (a rule number inside a name, "Ctys.", "Inc. etc. v."), and a short form's name no longer runs back into the sentence before it.

## florida-citation 1.1.2 (2026-10-05)

A rule citation after "to" or "of" (pursuant to Fla.R.Crim.P. 3.852) is checked again; only a rule named inside a case name, followed by that case's citation, is skipped.

## florida-citation 1.1.1 (2026-10-05)

A citation that opens its sentence (or follows a short opener such as "Similarly,") is now read as part of the sentence; docket numbers with an OCR'd symbol inside are read; exhibit cover sheets are recognized as the start of exhibits.

## federal-law 1.0.5 (2026-10-05)

Never reports a rate limit or a GovInfo link-service error as a missing citation: a 429 now stops with a RATE LIMITED message saying nothing was looked up, and only GovInfo's 'no such citation' answer reads as missing.

## federal-law 1.0.4 (2026-10-05)

Says plainly when uscode.house.gov is down for maintenance (it serves a maintenance page with HTTP 200 for every URL), instead of reporting missing text or editions; the self-test reports such cases as DOWN rather than failing.

## florida-citation 1.1.0 (2026-10-05)

Opposing review is cheap by default: report first, then batch case lookups (--cite-list) and quotation checks only as far as you choose. Exhibits are detected, and --last-page leaves them out. Fixes a false 'pinpoint out of range' on an Id. after an OCR'd footnote.

## florida-citation 1.0.0 (2026-10-05)

First public release: Rule 9.800's forms from the rule's own text, Florida abbreviations and case-number conversion, citations built from their parts, whole-document checks of briefs and motions (.txt, .md, .docx, .pdf) with short forms and Id., and opposing-filing review with the facts loop. Tested against 28 Florida court opinions, 18 Florida Supreme Court briefs, and four trial-court motions.

## federal-law 1.0.3 (2026-09-30)

Setup points to GovInfo's own sign-up page for the free API key (govinfo.gov/api-signup). No change to the script.

## federal-law 1.0.2 (2026-09-30)

Follows the open Agent Skills standard more closely, so the skill works in any compatible agent, not only Claude: the script is referenced by its path relative to the skill's folder, and a compatibility field lists what the skill needs. The README now describes it as an Agent Skill. No change to the script.

## federal-law 1.0.1 (2026-09-30)

The repository is now legal-skills (install with federal-law@legal-skills); the script's User-Agent links there.

## federal-law 1.0.0 (2026-09-30)

First public release: search, citation pulls with pinpoints, currency checks against uscode.house.gov and eCFR, as-of-date pulls, CFR appendices and official interpretations, public laws, and legislative history.

