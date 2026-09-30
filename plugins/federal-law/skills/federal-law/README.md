# federal-law

A Claude skill for researching U.S. federal statutes and regulations from official sources. Ask Claude a federal-law question in plain English, and the skill finds the provisions, reads their text, checks that they are current, and cites them.

It is a research aid, not legal advice. Verify anything you rely on against the official source, and see [What it doesn't do](#what-it-doesnt-do).

## What it does

- **Finds provisions.** Searches the current Code of Federal Regulations (eCFR) and GovInfo's official editions of the U.S. Code, CFR, Federal Register, public laws, and congressional documents. For each hit it shows the lines where your term appears, so you can tell a definition from a passing mention, and a ready-to-use citation (`7 CFR 220.2`, `5 U.S.C. 552`, `Fed. R. Evid. 1005`, `Pub. L. 114-185`).
- **Pulls text by citation.** U.S. Code sections; CFR sections, appendices, and supplements (including official interpretations like Supplement I to Regulation Z); public laws; Federal Register rules; single subsections by pinpoint (`5 U.S.C. 552(b)(6)`).
- **Checks currency.** Compares GPO's annual U.S. Code and CFR editions with the current text on uscode.house.gov and eCFR, shows what changed, and names the public law or Federal Register rule that changed it.
- **Shows the law on a past date.** Pulls the U.S. Code edition in effect on a date (back to 1995) and flags laws enacted after that edition; pulls the CFR as it stood on a date (eCFR from 2017, annual editions back to 1996) and flags rules published in between.
- **Assembles legislative history.** For a public law: every version of the bill, committee reports, signing statements, Congressional Record debate on the bill, and the U.S. Code sections the law affected, each with a citation.
- **Flags legal-status issues the text won't show.** Whether a U.S. Code title is positive law, when eCFR (an unofficial compilation) is the source, and when unnumbered text after a pinpointed paragraph may belong to a higher level.

## What it doesn't do

- **No state law and no case law.** It covers federal statutes and regulations only. It does not check whether a court has vacated, enjoined, or struck down a provision; the CFR and U.S. Code can keep text a court has set aside. Use a case-law tool for that.
- **Some networks are blocked.** The Office of the Federal Register blocks some networks, often cloud servers and VPNs, from eCFR and FederalRegister.gov, even for their developer APIs. On such a network, commands that need those sites stop with an `ACCESS BLOCKED` message; the GovInfo and U.S. Code commands still work.
- **Currency stops where the sources stop.** uscode.house.gov and eCFR each state the date they are current through; the skill reports it. Anything after that date won't show up.
- **Enactment is not effectiveness.** The as-of checks work from enactment and publication dates. Read the amending law's or rule's effective-date provisions before concluding what applied on a date.
- **Keyword search.** A provision that defines a term without your exact words may not match a narrow query; the skill's instructions run a broad search as well.
- **GovInfo's legislative-history links are imperfect**: thin before the 1990s, slow for very recent laws, and occasionally wrong (the skill flags a signing statement dated before enactment).

## Setup

1. **Python 3.9 or later.** The script uses only the standard library; there is nothing to install.
2. **A free GovInfo API key.** Sign up at <https://api.data.gov/signup/>, then save the key where the script looks for it:
   - macOS / Linux (the key isn't shown as you paste it):
     ```bash
     read -rs -p "GovInfo API key: " k && printf '%s' "$k" > ~/.govinfo_api_key && chmod 600 ~/.govinfo_api_key; unset k; echo
     ```
   - Windows PowerShell (the key isn't shown as you paste it):
     ```powershell
     $k = Read-Host "GovInfo API key" -AsSecureString; [Net.NetworkCredential]::new('', $k).Password | Set-Content "$HOME\.govinfo_api_key" -NoNewline; Remove-Variable k
     ```

   Or set the `GOVINFO_API_KEY` environment variable. Without a key, the script falls back to api.data.gov's demo key, whose rate limit is too low for real use. The other three sources need no key.
3. **Install the skill** (see the repository README).

On macOS with Python from python.org, if every request fails with a certificate error, run `Install Certificates.command` in the Python folder under Applications.

## Try it

Ask Claude things like:

- "Which federal regulations define yogurt?"
- "Pull 5 U.S.C. 552(b)(6) and check that it's current."
- "What did 26 U.S.C. 24(h)(2) say on August 1, 2025, and what changed it?"
- "Give me the legislative history of the FOIA Improvement Act of 2016."
- "What does the Regulation Z commentary say about 1026.19(e)(3)(i)?"

The script also works on its own: `python3 scripts/federal_law.py --help`.

## Sources

| Source | Used for | Key |
|---|---|---|
| [GovInfo](https://www.govinfo.gov/) (Government Publishing Office) | Official editions: U.S. Code, CFR, Federal Register, public laws, bills, reports, Congressional Record; related-document links | Free api.data.gov key |
| [uscode.house.gov](https://uscode.house.gov/) (Office of the Law Revision Counsel) | Current U.S. Code text, edition history, positive-law titles | None |
| [eCFR API](https://www.ecfr.gov/developers/documentation/api/v1) | Current and point-in-time CFR text, version history, search | None |
| [Federal Register API](https://www.federalregister.gov/developers/documentation/api/v1) | Rules affecting a CFR part | None |

The skill makes a handful of requests per question, identifies itself in its User-Agent, retries politely on server errors, and uses eCFR's and the Federal Register's developer APIs, as those sites require for programmatic access. It is not a bulk downloader; for bulk data, use GovInfo's bulk data repository or the OLRC's downloadable XML.

This project is not affiliated with or endorsed by the Government Publishing Office, the Office of the Law Revision Counsel, the Office of the Federal Register, or any other government agency.

## Testing

`python3 scripts/selftest.py` runs 39 checks against the live sources, one or more per feature plus the unusual citation formats it has to handle (tax regulations like 26 CFR 1.401(k)-1, FAR clauses, numbered definition sections, repealed subsections), in about a minute. Each reports **ok**, **FAIL** (the script broke or a source changed its format), **CHANGED** (a recorded fact moved, such as a new edition or amendment; the law changing, not a bug), **FLAKY** (a source hiccupped and the rerun passed), or **BLOCKED** (eCFR or FederalRegister.gov refused the network running the test).

## License

This skill is licensed under the MIT License; copyright 2026 Attorney Nate.
