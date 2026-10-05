# legal-skills

[Agent Skills](https://agentskills.io) for legal research and legal work.

Agent Skills is an open standard for giving AI agents new abilities: a skill is a folder with a `SKILL.md` file of instructions and any scripts it needs. The same folder works in Claude and Claude Code, ChatGPT and Codex, Gemini CLI, GitHub Copilot, VS Code, Cursor, and [many other agents](https://agentskills.io/clients). Each skill here is self-contained and can be installed on its own.

These are research aids, not legal advice. Verify anything you rely on against the official source.

**Before you start:** both skills need Python 3.9 or later. `federal-law` also needs a free GovInfo API key: sign up at [govinfo.gov/api-signup](https://www.govinfo.gov/api-signup) (it takes a minute), then save the key as its [setup section](plugins/federal-law/skills/federal-law/README.md#setup) shows. `florida-citation` needs no key and works offline; to read PDFs it uses `pdftotext`, which its [setup section](plugins/florida-citation/skills/florida-citation/README.md#setup) shows how to install.

## Skills

| Skill | What it does |
|---|---|
| [federal-law](plugins/federal-law/skills/federal-law/) | Finds, reads, and verifies U.S. federal statutes and regulations from official sources (GovInfo, uscode.house.gov, eCFR, and the Federal Register API): searches that show where a term appears, text by citation down to a pinpoint subsection, currency checks that name the amending law or rule, the law as it read on a past date, and legislative history. |
| [florida-citation](plugins/florida-citation/skills/florida-citation/) | Formats and checks legal citations under Florida's Uniform Citation System, Fla. R. App. P. 9.800 (as amended effective September 1, 2026), with the Bluebook system, through the public-domain Indigo Book, for what the rule doesn't cover. Shows the rule's text, gives the Florida form of a court, reporter, or rule set, converts case numbers, builds a citation from its parts, checks every citation in a brief or motion (`.txt`, `.md`, `.docx`, or `.pdf`) with its page, authority, and fix, short forms and Id. included, and reviews the other side's filing with the facts that don't match, pinpoints out of range, and quotations to verify ranked ahead of form. |

## Install

### Any agent that supports Agent Skills

1. Download the skill's ZIP file from the [latest release](https://github.com/attorneynate/legal-skills/releases) (`federal-law-<version>.zip` or `florida-citation-<version>.zip`), or copy the skill's folder from this repository (`plugins/<name>/skills/<name>/`).
2. Put the skill's folder (`federal-law` or `florida-citation`) in your agent's skills folder. Where that is depends on the agent; each one's instructions are linked from [agentskills.io/clients](https://agentskills.io/clients).
3. Do the skill's setup. `federal-law`: get your free GovInfo API key at [govinfo.gov/api-signup](https://www.govinfo.gov/api-signup) and save it as its [setup section](plugins/federal-law/skills/federal-law/README.md#setup) shows. `florida-citation`: install `pdftotext` if you'll check PDFs, as its [setup section](plugins/florida-citation/skills/florida-citation/README.md#setup) shows.

### Claude Code (one step, with updates)

```
/plugin marketplace add attorneynate/legal-skills
/plugin install federal-law@legal-skills
/plugin install florida-citation@legal-skills
```

Or from a terminal:

```bash
claude plugin marketplace add attorneynate/legal-skills
claude plugin install federal-law@legal-skills
claude plugin install florida-citation@legal-skills
```

Then do each skill's setup (above). To get later releases: `/plugin marketplace update legal-skills`. (The `plugins/` folders are Claude Code's packaging; the skill itself is the `skills/<name>/` folder inside each one.)

### Setup each skill needs

Each skill's README lists its own requirements.

- `federal-law` needs Python 3.9 or later and a free GovInfo API key ([sign up](https://www.govinfo.gov/api-signup); see [its setup section](plugins/federal-law/skills/federal-law/README.md#setup) for saving it). The other sources it uses need no key. Its scripts call government websites, so it needs an agent that can run Python with open network access; hosted environments that restrict outbound network access can't run it.
- `florida-citation` needs Python 3.9 or later and nothing else to answer questions, build citations, or check `.txt`, `.md`, and `.docx` files. It works offline; only its optional self-test uses the network. Reading a PDF needs `pdftotext` (Poppler or Xpdf; Git for Windows includes one), and a scanned PDF needs OCR first, such as OCRmyPDF, which runs on your own machine so a confidential filing is never uploaded. Whether a case exists or supports its point is left to your agent's own case-law tools; the skill lists what to confirm and does the arithmetic. Those lookups cost requests and tokens, so your agent gives you the free report first, confirms cases in one batch where its tool allows, and goes only as far as you choose.

### Without an agent

The scripts are ordinary command-line tools. For example, from the `federal-law` folder: `python3 scripts/federal_law.py usc 5 552 --pin '(b)(6)'`. From the `florida-citation` folder: `python3 scripts/fl_cite.py check brief.pdf`, or `python3 scripts/fl_cite.py build case "Fenelon v. State" --court SC --year 1992 --cite "594 So. 2d 292" --pin 293`. Each script's `--help` lists every command.

## Status and testing

Every skill ships with a self-test, and every release passes it first. `federal-law`'s runs against the live sources. `florida-citation`'s runs every command offline, then reads two Florida court opinions and runs one CourtListener search live, to notice a new amendment to Rule 9.800. GitHub Actions runs the self-tests on Windows, macOS, and Linux with Python 3.9 and 3.13 on every change and weekly, checks each skill with the Agent Skills standard's validator (`skills-ref`), and validates the Claude Code plugin manifests with `claude plugin validate --strict`.

Before its first release, `florida-citation` was run against 28 Florida court opinions and 18 Florida Supreme Court briefs, then four trial-court motions, until every flag left on the opinions was a departure by the court itself. Its README's [testing section](plugins/florida-citation/skills/florida-citation/README.md#how-it-was-tested) says how.

## Contributing

Bug reports and suggestions are welcome as GitHub issues; please include the exact command or question and what you expected. Skills are developed in a separate workspace and released here, so a pull request may be applied by hand in the next release rather than merged directly.

## Not affiliated

This project is not affiliated with or endorsed by the Government Publishing Office, the Office of the Law Revision Counsel, the Office of the Federal Register, the Supreme Court of Florida, The Florida Bar, the Florida State University Law Review, the publishers of The Bluebook, the editors of the Indigo Book, or any other government agency or organization. The legal text `federal-law` retrieves is a work of the U.S. government and in the public domain. `florida-citation` bundles the text of Rule 9.800, a court rule that carries no copyright, and material from the Indigo Book under its CC0 public-domain dedication; it quotes no Bluebook text and does not bundle the Florida Style Manual.

## License

MIT; see [LICENSE](LICENSE). Copyright 2026 Attorney Nate.
