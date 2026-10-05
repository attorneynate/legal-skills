# Reviewing the other side's filing

Part of the florida-citation skill: the workflow behind `check --mode opposing`, the facts loop, and quotation verification. Read it before reviewing another side's brief. `S` is the script, as in SKILL.md:

```bash
S=scripts/fl_cite.py            # relative to this skill's folder
# Claude Code: S="${CLAUDE_SKILL_DIR}/scripts/fl_cite.py"
```

In someone else's brief, a citation that's wrong in substance matters far more than one in the wrong form. Opposing mode orders the findings that way.

The script's part is free: it runs offline in about a second. Confirming the cases and verifying the quotations are your part, and they cost lookups and tokens. Case-law tools limit requests (a free tier may allow a few a minute and a hundred or so a day), and verifying a quotation means reading its source, often several thousand tokens each; a brief with 40 quotations can cost hundreds of thousands. So give the user the free result first, and do the costly steps only as far as the user wants.

1. **Run it on the filing alone:** `python3 "$S" check brief.pdf --mode opposing`.
   - If the report's header starts a line with `Exhibits?`, the PDF carries exhibits or an appendix (a slip sheet such as "Exhibit 1", or a printout from Westlaw or Lexis). Their citations and quotations are another writer's: an attached opinion's quotations are the court's. Rerun with `--last-page N` as the header suggests, unless the user wants the exhibits reviewed too.
   - Without confirmed facts, section 1 lists only what the script's own tables show can't be right (a 2015 case in So. 2d, a district court decision dated before that court existed).
2. **Report that result, then ask before going further.** Say what each next step would take, from the report's counts: confirming the N cases (step 3: one batch request where the tool allows it, then a search for each case it misses), and verifying the M quotations (step 5: reading each source). Offer choices such as: cases only; quotations from the cases the argument rests on; everything. Do only what the user picks.
3. **Confirm the cases, batch first.**
   - `python3 "$S" check brief.pdf --cite-list` prints each case once, as a citation alone (name, cite, court, and year), one per line. Give that list to a citation tool that checks many citations in one request, such as CourtListener's citation lookup (up to 250 citations a request, counted against its own citation quota rather than the request quota). The list holds nothing from the filing but its citations.
   - Then look up only the cases the batch didn't find, one at a time, by name as well as by cite. Slip opinions without a reporter cite yet, and Westlaw-only federal orders, are the usual misses.
   - Check the tool's quota before you start, if it reports one. If a rate limit stops you, don't wait it out: record what you have, leave the rest `found: null`, rerun, and tell the user which cases are left.
4. **Record what you found and rerun.** `python3 "$S" check brief.pdf --facts-template > facts.json` writes one entry per case, with full citations, short forms, and Id. merged, and what the brief claims for each. Fill in `found`, `case_name`, `court`, `year`, `first_page`, `last_page`, `volume` (only if it differs), `source`, and `note`. Then `python3 "$S" check brief.pdf --mode opposing --facts facts.json`.
   - Set `found` to false only after searching by name as well as by cite. Leave `found` null for a case you didn't look up. For one you looked up that's in none of the databases (a table disposition, an unpublished order), leave `found` null, name the databases in `source`, and say what you tried in `note`; the report lists it as "looked up but not in the databases."
   - A cite lookup can report a match when the cited page falls inside an opinion, even if the document gives the wrong first page. Compare the database's own cite (its parallel citations) with the document's first page before calling it confirmed.
   - A federal district court ruling missing from the opinion database may be on its docket. Search the docket's entries around the cited date (only the docket number and dates are sent). The decision date is the date the judge signed, not the date the clerk entered it.
   - A database may date a case by a later order (rehearing denied, a corrected opinion). When the year is off by one, read the opinion's heading before recording it.
   - Leave `last_page` null rather than guess it. The pinpoint is then checked only against the first page and marked "upper bound unconfirmed." Find a last page from the opinion's star pagination only when asked; it costs a full fetch per case.
   - `court` takes a code (`SC`, `1D` to `6D`, `CA11`, `US`), another state's court by its citation abbreviation (`Del. Ch.`), or the court's name as the tool gives it. Leave it null when the tool doesn't give one (many batch lookups don't); the court then isn't compared. Some tools name only "District Court of Appeal of Florida," not the district; that matches any district. If the district matters, read it from the opinion's heading.
   - The rerun's report comes in four sections:
     1. facts that don't match: court, year, party names, volume, or first page, and cases not found;
     2. pinpoints out of range: below the first page or past the last;
     3. quotations to verify, each tied to the citation that gives its source, with the pinpoint;
     4. form errors, summarized by check and authority with counts and pages.
5. **Verify the quotations the user chose** with a quote-verification tool against the case and page given. A quotation tied to an Id. the script can't resolve, or tied to nothing, needs its source found by hand; many come from the record. A quotation marked "no pinpoint" has a citation that gives no page; find the page in the source.
   - **Privacy:** sending a filing's quotations to a quote tool shares its text with that service. For a confidential filing, fetch each source by its citation or database ID instead and compare the words locally.
   - **"citing" or "quoting":** when the source is itself quoting another case, the parenthetical should say `quoting`, not `citing`. Report a `(citing X)` where the words are X's.
6. **Report by significance, with printed page numbers.** Frame every item as something to confirm. A mismatch may be a typo, a parallel cite, the wrong case, or a case that can't be found. Never call a case fake or a lawyer dishonest. Form errors in another side's filing are rarely worth raising; mention them only if asked. Say what wasn't confirmed: cases not looked up, quotations not verified.

Limits to state plainly: the script reads record cites only for their form (`¶¶`, Id.), so it can't check what they point to. OCR'd text can garble citations and page numbers, so read the passage before relying on a finding there. The script never judges whether a case supports the proposition it's cited for or is still good law. `--facts` also works without `--mode opposing`; the facts section then comes before the form report.
