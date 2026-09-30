# legal-research-skills

Claude skills for legal research from official sources. Each skill is a self-contained plugin you can install on its own.

These are research aids, not legal advice. Verify anything you rely on against the official source.

## Skills

| Skill | What it does |
|---|---|
| [federal-law](plugins/federal-law/skills/federal-law/) | Finds, reads, and verifies U.S. federal statutes and regulations from official sources (GovInfo, uscode.house.gov, eCFR, and the Federal Register API): searches that show where a term appears, text by citation down to a pinpoint subsection, currency checks that name the amending law or rule, the law as it read on a past date, and legislative history. |

## Install

### Claude Code

```
/plugin marketplace add attorneynate/legal-research-skills
/plugin install federal-law@legal-research-skills
```

Or from a terminal:

```bash
claude plugin marketplace add attorneynate/legal-research-skills
claude plugin install federal-law@legal-research-skills
```

To get later releases, update the marketplace: `/plugin marketplace update legal-research-skills`.

### By hand

Copy a skill's folder (for example `plugins/federal-law/skills/federal-law/`) into `~/.claude/skills/`. Claude Code loads it at the start of the next session.

### Setup each skill needs

Each skill's README lists its own requirements. `federal-law` needs Python 3.9 or later and a free GovInfo API key; see [its setup section](plugins/federal-law/skills/federal-law/README.md#setup).

These skills run scripts that call government websites, so they need a machine with Python and open network access. Hosted environments that restrict outbound network access can't run them.

## Status and testing

Every skill ships with a self-test that runs against the live sources. GitHub Actions runs it on Windows, macOS, and Linux with Python 3.9 and 3.13 on every change and weekly, and validates the plugin manifests with `claude plugin validate --strict`.

## Contributing

Bug reports and suggestions are welcome as GitHub issues; please include the exact command or question and what you expected. Skills are developed in a separate workspace and released here, so a pull request may be applied by hand in the next release rather than merged directly.

## Not affiliated

This project is not affiliated with or endorsed by the Government Publishing Office, the Office of the Law Revision Counsel, the Office of the Federal Register, or any other government agency. The legal text these skills retrieve is a work of the U.S. government and in the public domain.

## License

MIT; see [LICENSE](LICENSE). Copyright 2026 Attorney Nate.
