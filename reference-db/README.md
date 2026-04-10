# SVRT Reference Database — Community YAML Files

This directory contains community-curated software EOL/support definitions. Each YAML file covers one software product (all versions/majors in a single file).

The Pi research agent ingests these files and stores entries at **confidence=90** — below manual authoritative entries (95) but above AI-only results (50–80). This means a community YAML entry will always win over a Claude guess.

---

## File Format

**Filename**: `{vendor-slug}-{product-slug}.yaml`
Example: `microsoft-internet-explorer.yaml`

```yaml
# Required top-level fields
software_name: Internet Explorer        # Display name (matches scanner output)
vendor: Microsoft Corporation           # Vendor as it appears in software inventories
platform: windows                       # windows | macos | linux | cross-platform

# One entry per major version
versions:
  - major: "11"                         # Major version number (string)
    eol_status: eol                     # eol | supported | lts | no_patch
    eol_date: "2022-06-15"             # ISO 8601 date, omit if ongoing
    latest_version: ""                  # Latest patch in this major, if known
    source_url: https://learn.microsoft.com/en-us/lifecycle/products/internet-explorer-11
    notes: "IE11 end of support June 15, 2022"  # Optional human note

  - major: "10"
    eol_status: eol
    eol_date: "2016-01-12"
    source_url: https://learn.microsoft.com/en-us/lifecycle/products/internet-explorer-10

# Optional: aliases that scanners might report this product as
aliases:
  - "MSIE"
  - "Internet Explorer 11"
```

### eol_status values

| Value | Meaning |
|-------|---------|
| `eol` | End of life — no longer patched |
| `supported` | Actively supported |
| `lts` | Long-term support release |
| `no_patch` | Known vulnerability, no fix available |

---

## Validation

Run the validator before submitting a PR:

```bash
python3 reference-db/validate.py
```

---

## Sources

Only use authoritative sources:
- Vendor lifecycle pages (Microsoft, Apple, Google, Mozilla, etc.)
- [endoflife.date](https://endoflife.date/) — community-vetted EOL data
- Official security advisories (CERT, CVE)

Do not cite news articles, blog posts, or forum posts as sources.
