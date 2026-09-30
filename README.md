# legal-skills

[Agent Skills](https://agentskills.io) for legal research and legal work.

Agent Skills is an open standard for giving AI agents new abilities: a skill is a folder with a `SKILL.md` file of instructions and any scripts it needs. The same folder works in Claude and Claude Code, ChatGPT and Codex, Gemini CLI, GitHub Copilot, VS Code, Cursor, and [many other agents](https://agentskills.io/clients). Each skill here is self-contained and can be installed on its own.

These are research aids, not legal advice. Verify anything you rely on against the official source.

**Before you start:** `federal-law` needs Python 3.9 or later and a free GovInfo API key. Sign up at [govinfo.gov/api-signup](https://www.govinfo.gov/api-signup) (it takes a minute), then save the key as its [setup section](plugins/federal-law/skills/federal-law/README.md#setup) shows.

## Skills

| Skill | What it does |
|---|---|
| [federal-law](plugins/federal-law/skills/federal-law/) | Finds, reads, and verifies U.S. federal statutes and regulations from official sources (GovInfo, uscode.house.gov, eCFR, and the Federal Register API): searches that show where a term appears, text by citation down to a pinpoint subsection, currency checks that name the amending law or rule, the law as it read on a past date, and legislative history. |

## Install

### Any agent that supports Agent Skills

1. Download the skill's ZIP file from the [latest release](https://github.com/attorneynate/legal-skills/releases) (`federal-law-<version>.zip`), or copy the skill's folder from this repository (`plugins/federal-law/skills/federal-law/`).
2. Put the `federal-law` folder in your agent's skills folder. Where that is depends on the agent; each one's instructions are linked from [agentskills.io/clients](https://agentskills.io/clients).
3. Get your free GovInfo API key at [govinfo.gov/api-signup](https://www.govinfo.gov/api-signup) and save it as the skill's [setup section](plugins/federal-law/skills/federal-law/README.md#setup) shows.

### Claude Code (one step, with updates)

```
/plugin marketplace add attorneynate/legal-skills
/plugin install federal-law@legal-skills
```

Or from a terminal:

```bash
claude plugin marketplace add attorneynate/legal-skills
claude plugin install federal-law@legal-skills
```

Then get your free GovInfo API key at [govinfo.gov/api-signup](https://www.govinfo.gov/api-signup) and save it as the skill's [setup section](plugins/federal-law/skills/federal-law/README.md#setup) shows. To get later releases: `/plugin marketplace update legal-skills`. (The `plugins/` folders are Claude Code's packaging; the skill itself is the `skills/<name>/` folder inside each one.)

### Setup each skill needs

Each skill's README lists its own requirements. `federal-law` needs Python 3.9 or later and a free GovInfo API key ([sign up](https://www.govinfo.gov/api-signup); see [its setup section](plugins/federal-law/skills/federal-law/README.md#setup) for saving it). The other sources it uses need no key.

These skills run scripts that call government websites, so they need an agent that can run Python with open network access. Hosted environments that restrict outbound network access can't run them.

### Without an agent

The scripts are ordinary command-line tools. For example, from the `federal-law` folder: `python3 scripts/federal_law.py usc 5 552 --pin '(b)(6)'`, or `--help` for every command.

## Status and testing

Every skill ships with a self-test that runs against the live sources, and every release passes it first. GitHub Actions runs the self-test on Windows, macOS, and Linux with Python 3.9 and 3.13 on every change and weekly, checks each skill with the Agent Skills standard's validator (`skills-ref`), and validates the Claude Code plugin manifests with `claude plugin validate --strict`.

## Contributing

Bug reports and suggestions are welcome as GitHub issues; please include the exact command or question and what you expected. Skills are developed in a separate workspace and released here, so a pull request may be applied by hand in the next release rather than merged directly.

## Not affiliated

This project is not affiliated with or endorsed by the Government Publishing Office, the Office of the Law Revision Counsel, the Office of the Federal Register, or any other government agency. The legal text these skills retrieve is a work of the U.S. government and in the public domain.

## License

MIT; see [LICENSE](LICENSE). Copyright 2026 Attorney Nate.
