# GitHub Implementation Profile
## Software Lifecycle Status Declaration for Open Source Projects

**Status:** Draft — Community Feedback Welcome  
**Related:** [Well-Known URI Internet-Draft](./ietf-internet-draft.md)  
**Repo:** https://github.com/askmcconnell/s3c-tool

---

## Overview

This profile defines a lightweight convention for open source maintainers to publish machine-readable software lifecycle information directly in their GitHub repository. It complements the proposed IETF Well-Known URI (`/.well-known/software-status.json`) by covering projects that are distributed as source code rather than operated as services.

A project that publishes `.github/software-status.json` is saying:

> "Here is authoritative, structured information about the support lifecycle of this software — directly from the people who maintain it."

Security tools, SBOMs, and software inventory platforms (like S3C-Tool) can consume this file to answer EOL/EOS questions without relying on AI inference or scraped data.

---

## File Location

```
{repository-root}/.github/software-status.json
```

This location was chosen because:
- `.github/` is already the established convention for repo-level metadata (issue templates, workflows, funding, etc.)
- It is distinct from application source code and unlikely to conflict with build artifacts
- GitHub renders the `.github/` directory specially in the UI

---

## Schema

### Minimal (single-version project)

```json
{
  "schema_version": "1.0",
  "name": "My Project",
  "vendor": "Example Corp",
  "homepage": "https://example.com/myproject",
  "versions": [
    {
      "version": "3.2",
      "status": "active",
      "support_ends": null
    }
  ]
}
```

### Full (multi-version with EOL history)

```json
{
  "schema_version": "1.0",
  "name": "My Project",
  "vendor": "Example Corp",
  "homepage": "https://example.com/myproject",
  "source": "https://github.com/example/myproject",
  "package_identifiers": {
    "pypi": "myproject",
    "npm": null,
    "rubygems": null,
    "cargo": null,
    "apt": "myproject",
    "brew": "myproject"
  },
  "versions": [
    {
      "version": "4.0",
      "release_date": "2025-01-15",
      "status": "active",
      "support_ends": null,
      "lts": false,
      "notes": "Current stable release"
    },
    {
      "version": "3.2",
      "release_date": "2023-06-01",
      "status": "security-only",
      "support_ends": "2026-06-01",
      "lts": true,
      "notes": "LTS — security patches only until June 2026"
    },
    {
      "version": "3.1",
      "release_date": "2022-01-10",
      "status": "eol",
      "eol_date": "2024-01-10",
      "support_ends": "2024-01-10",
      "lts": false
    },
    {
      "version": "2.x",
      "release_date": null,
      "status": "eol",
      "eol_date": "2022-12-31",
      "support_ends": "2022-12-31",
      "lts": false
    }
  ],
  "release_cycle_url": "https://example.com/support-policy",
  "last_updated": "2026-04-14"
}
```

---

## Field Reference

### Root object

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `schema_version` | string | ✅ | Always `"1.0"` |
| `name` | string | ✅ | Human-readable project name |
| `vendor` | string | ✅ | Organization or individual maintainer |
| `homepage` | string | — | Project website |
| `source` | string | — | Canonical source repository URL |
| `package_identifiers` | object | — | Package manager names (see below) |
| `versions` | array | ✅ | One entry per supported or historical release series |
| `release_cycle_url` | string | — | URL to the project's official support/EOL policy page |
| `last_updated` | string (ISO 8601 date) | — | When this file was last reviewed |

### `versions[]` entries

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `version` | string | ✅ | Version number or series (e.g. `"3.2"`, `"2.x"`, `"LTS 22.04"`) |
| `status` | string | ✅ | One of: `active`, `lts`, `security-only`, `eol`, `unmaintained` |
| `release_date` | string (ISO 8601) | — | Initial GA release date |
| `support_ends` | string or null | — | Date security support ends; `null` = no planned EOL |
| `eol_date` | string | — | Date the version reached EOL (past tense; omit if still supported) |
| `lts` | boolean | — | Whether this is a Long-Term Support release |
| `notes` | string | — | Free-text note for human readers |

### `package_identifiers` object

Maps ecosystem names to the package identifier used in that registry. Use `null` if the project is not distributed through that package manager.

```json
{
  "pypi": "requests",
  "npm": null,
  "rubygems": null,
  "cargo": "reqwest",
  "apt": "python3-requests",
  "brew": "python-requests",
  "nuget": null,
  "maven": "com.squareup.okhttp3:okhttp",
  "docker": "library/python"
}
```

---

## Status Values

| Value | Meaning |
|-------|---------|
| `active` | Fully supported; bugs, security issues, and features accepted |
| `lts` | Long-Term Support; full support for an extended period |
| `security-only` | Only security vulnerabilities are patched; no new features |
| `eol` | End of Life — no patches of any kind |
| `unmaintained` | Project is abandoned but not formally EOL'd |

---

## How Tools Should Consume This File

1. **Discovery**: Check `{repo-root}/.github/software-status.json` when analyzing a GitHub-hosted dependency
2. **Caching**: Cache the result with a short TTL (7–14 days). The file changes infrequently.
3. **Conflict resolution**: This file takes precedence over scraped or AI-inferred data. Update your confidence score to `source=authoritative`.
4. **Version matching**: Match the installed version against `versions[].version` using semver prefix matching (e.g. installed `3.2.7` matches version series `3.2`)
5. **Fallback**: If the file is absent, fall back to your normal lookup chain

### GitHub API URL

```
https://raw.githubusercontent.com/{owner}/{repo}/HEAD/.github/software-status.json
```

---

## Example — Real Project (Redis)

```json
{
  "schema_version": "1.0",
  "name": "Redis",
  "vendor": "Redis Ltd",
  "homepage": "https://redis.io",
  "source": "https://github.com/redis/redis",
  "package_identifiers": {
    "apt": "redis-server",
    "brew": "redis",
    "docker": "library/redis"
  },
  "versions": [
    {
      "version": "7.4",
      "release_date": "2024-07-31",
      "status": "active",
      "support_ends": null,
      "lts": false
    },
    {
      "version": "7.2",
      "release_date": "2023-08-15",
      "status": "lts",
      "support_ends": "2026-01-01",
      "lts": true
    },
    {
      "version": "7.0",
      "release_date": "2022-04-27",
      "status": "eol",
      "eol_date": "2025-01-01",
      "support_ends": "2025-01-01",
      "lts": false
    },
    {
      "version": "6.2",
      "release_date": "2021-02-22",
      "status": "security-only",
      "support_ends": "2026-03-31",
      "lts": true,
      "notes": "Extended support for 6.2 through March 2026"
    }
  ],
  "release_cycle_url": "https://redis.io/docs/about/releases/",
  "last_updated": "2026-04-14"
}
```

---

## Relationship to the IETF Well-Known URI Proposal

| | Well-Known URI (`/.well-known/software-status.json`) | GitHub Profile (`.github/software-status.json`) |
|--|--|--|
| **For** | Software vendors operating services/websites | Open source maintainers on GitHub |
| **Scope** | Describes the software running at that domain | Describes the project in the repository |
| **Discovery** | Via domain + well-known path | Via GitHub repo URL |
| **Use case** | "Is the software at example.com EOL?" | "Is this npm/pip/apt package EOL?" |

Both formats share the same `versions[]` schema intentionally — tools that understand one can read the other.

---

## Adoption Recommendations

### For maintainers
- Add `.github/software-status.json` when you publish a new major version or EOL an old one
- Update `last_updated` when you review the file
- Link to it from your README: `[![Lifecycle Status](https://img.shields.io/badge/lifecycle-software--status-blue)](/.github/software-status.json)`

### For package registries (PyPI, npm, crates.io, etc.)
- Display EOL warnings on package pages when the linked GitHub repo declares `status: eol`
- Surface `support_ends` dates in package metadata

### For CI/CD and security tools
- Add a check step: "does any dependency declare `status: eol`?"
- Treat `source=authoritative` entries as ground truth, no re-verification needed

---

## S3C-Tool Integration

S3C-Tool checks `.github/software-status.json` as part of its reference lookup chain:

```
1. Local reference DB  →  instant, free
2. endoflife.date API  →  442 products
3. .github/software-status.json  →  authoritative source
4. Repology / package registries
5. Claude / Gemini / GPT (AI fallback)
```

When an authoritative `software-status.json` is found, S3C-Tool stores the result with `confidence=95` and `source=github-authoritative`, and will not re-verify until `last_updated` is more than 90 days old.

---

## Contributing

This profile is maintained in the [S3C-Tool repository](https://github.com/askmcconnell/s3c-tool). Open an issue or pull request to propose schema changes, report ambiguities, or share adoption experiences. The goal is to eventually submit this as an IETF Internet-Draft alongside the Well-Known URI proposal.
