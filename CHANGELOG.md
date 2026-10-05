# Changelog

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

