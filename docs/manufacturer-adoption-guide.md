# Manufacturer Adoption Guide
## Declaring Software Lifecycle Status in Your GitHub Repository

**5-minute read · No dependencies · One JSON file**

---

## Why This Matters

Every day, security teams across thousands of organizations are trying to answer one question about your software:

> *"Is the version we're running still supported — or is it end-of-life?"*

Right now, they're getting that answer from AI inference, scraped docs, or outdated third-party databases. Those sources lag behind reality, produce false positives, and create unnecessary remediation tickets for software that is actually supported.

You can fix that with a single file.

By publishing `.github/software-status.json` in your repository, you give your users — and every security tool they use — a direct, authoritative, machine-readable answer straight from the people who actually maintain the software.

---

## What You Add

One file, in one location:

```
your-repo/.github/software-status.json
```

That's it. No new infrastructure, no CI pipeline changes, no dependencies.

---

## Quickstart — 5 Minutes

### Step 1: Create the file

For most projects, the minimal version is all you need:

```json
{
  "schema_version": "1.0",
  "name": "Your Project Name",
  "vendor": "Your Organization",
  "homepage": "https://yourproject.example.com",
  "versions": [
    {
      "version": "3.0",
      "status": "active",
      "support_ends": null
    },
    {
      "version": "2.x",
      "status": "eol",
      "eol_date": "2024-06-30"
    }
  ],
  "last_updated": "2026-04-15"
}
```

### Step 2: Commit it

```bash
mkdir -p .github
# create .github/software-status.json with your content
git add .github/software-status.json
git commit -m "Add software-status.json lifecycle declaration"
git push
```

### Step 3: Done

Security tools that follow this convention — including [S3C-Tool](https://askmcconnell.com/s3c/) — will now use your file as the authoritative source for your software's lifecycle status.

---

## Status Values

| Value | Meaning |
|-------|---------|
| `active` | Current stable release, fully supported |
| `lts` | Long-term support — receiving security patches beyond normal EOL |
| `security-only` | No new features; security patches only |
| `eol` | End of life — no more patches of any kind |
| `unmaintained` | Project is no longer actively maintained but not formally EOL'd |

---

## Real-World Examples

### Single active release (most common)

```json
{
  "schema_version": "1.0",
  "name": "Nginx",
  "vendor": "F5, Inc.",
  "homepage": "https://nginx.org",
  "versions": [
    { "version": "1.27", "status": "active", "support_ends": null },
    { "version": "1.26", "status": "lts", "support_ends": "2027-04-01" },
    { "version": "1.24", "status": "eol", "eol_date": "2025-06-01" }
  ],
  "release_cycle_url": "https://nginx.org/en/download.html",
  "last_updated": "2026-04-15"
}
```

### Python-style versioned releases

```json
{
  "schema_version": "1.0",
  "name": "MyLibrary",
  "vendor": "Example Corp",
  "package_identifiers": {
    "pypi": "mylibrary",
    "apt": "python3-mylibrary"
  },
  "versions": [
    { "version": "4.x", "status": "active", "support_ends": null },
    { "version": "3.x", "status": "security-only", "support_ends": "2026-12-31", "lts": true },
    { "version": "2.x", "status": "eol", "eol_date": "2024-01-01" },
    { "version": "1.x", "status": "eol", "eol_date": "2022-06-01" }
  ],
  "last_updated": "2026-04-15"
}
```

### Enterprise software with rolling support windows

```json
{
  "schema_version": "1.0",
  "name": "SuperDB",
  "vendor": "BigCo Software",
  "homepage": "https://bigco.example.com/superdb",
  "versions": [
    { "version": "12.0", "status": "active",        "release_date": "2025-09-01", "support_ends": null },
    { "version": "11.0", "status": "lts",           "release_date": "2023-09-01", "support_ends": "2028-09-01", "lts": true },
    { "version": "10.0", "status": "security-only", "release_date": "2021-09-01", "support_ends": "2026-09-01" },
    { "version": "9.0",  "status": "eol",           "release_date": "2019-09-01", "eol_date": "2024-09-01" }
  ],
  "release_cycle_url": "https://bigco.example.com/support-lifecycle",
  "last_updated": "2026-04-15"
}
```

---

## Keeping It Current

The file is only as useful as it is accurate. A few suggestions:

**Automate the `last_updated` field** — add a step to your release workflow that bumps the date when you cut a new version:

```yaml
# .github/workflows/release.yml (example snippet)
- name: Update software-status.json date
  run: |
    DATE=$(date +%Y-%m-%d)
    jq --arg d "$DATE" '.last_updated = $d' .github/software-status.json > tmp.json
    mv tmp.json .github/software-status.json
```

**Mark EOL versions promptly** — when you stop supporting a release series, flip its status to `eol` and add the `eol_date`. This is the most security-critical update.

**Set a calendar reminder** — review the file once a year even if nothing changed. Update `last_updated` so downstream tools know the data isn't stale.

---

## FAQ

**Does this replace my release notes or CHANGELOG?**
No. This file is for *machine consumption* — structured status signals for security tooling. Your CHANGELOG remains the human-readable record of what changed. Think of `software-status.json` as the structured companion to your support policy page.

**What if I only have one version?**
That's fine — and common for smaller projects. A single entry with `"status": "active"` is perfectly valid and still useful. It tells security tools "yes, this is maintained" without requiring you to document historical versions.

**Should I include every version ever released?**
No. Include your current supported versions, your current LTS versions, and the last 1–2 EOL versions that are still likely to be in the wild. There's no benefit to documenting versions from 2012 that no one runs.

**What if our EOL policy is "we support the last N releases"?**
Use `"support_ends": null` on current active releases and update the file when a new release ships. You don't need exact dates to publish useful data.

**Can I use this for closed-source / commercial software?**
Absolutely. The convention is defined by file location and schema, not open-source status. Any GitHub-hosted project — public or private — can publish this file. If your repo is private, internal security tooling can still consume it directly.

**Will S3C-Tool automatically pick this up?**
Yes. S3C-Tool's research agent checks `.github/software-status.json` as a high-confidence source in its lookup chain. Once your file is published, any S3C-Tool user who scans an inventory containing your software will see accurate lifecycle data instead of AI-inferred guesses.

---

## The Bigger Picture

This convention is the basis of a proposed IETF Internet-Draft:
[**draft-mcconnell-software-status-wellknown**](https://datatracker.ietf.org/doc/draft-mcconnell-software-status-wellknown/)

The draft proposes `/.well-known/software-status.json` as an IETF-registered Well-Known URI (following RFC 8615) so that *any* software vendor — not just those on GitHub — can publish authoritative lifecycle data at a predictable URL.

The `.github/software-status.json` convention is the open-source-first implementation of the same idea. By adopting it now, you:

- Give your users accurate EOL data today
- Help establish the convention before it becomes a formal standard
- Position your project as a security-aware, responsible upstream

---

## Full Schema Reference

See the [GitHub Implementation Profile](./github-implementation-profile.md) for the complete field reference, package identifier registry, and validation rules.

---

## Questions or Feedback?

Open an issue at [github.com/askmcconnell/s3c-tool](https://github.com/askmcconnell/s3c-tool) or reach out via [askmcconnell.com](https://askmcconnell.com).

Schema feedback and pull requests to the reference database are welcome.

---

*S3C-Tool — Software Security Supply Chain · [askmcconnell.com/s3c](https://askmcconnell.com/s3c/)*
