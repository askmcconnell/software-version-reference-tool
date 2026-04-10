#!/usr/bin/env python3
"""
Validate all YAML files in reference-db/products/.
Usage: python3 reference-db/validate.py
"""

import sys
import yaml
from pathlib import Path

REQUIRED_TOP = {'software_name', 'vendor', 'platform', 'versions'}
REQUIRED_VERSION = {'major', 'eol_status', 'source_url'}
VALID_STATUSES = {'eol', 'supported', 'lts', 'no_patch'}
VALID_PLATFORMS = {'windows', 'macos', 'linux', 'cross-platform'}

errors = []
checked = 0

products_dir = Path(__file__).parent / 'products'
for yaml_file in sorted(products_dir.glob('*.yaml')):
    checked += 1
    try:
        data = yaml.safe_load(yaml_file.read_text())
    except yaml.YAMLError as e:
        errors.append(f"{yaml_file.name}: YAML parse error — {e}")
        continue

    # Top-level required fields
    missing = REQUIRED_TOP - set(data.keys())
    if missing:
        errors.append(f"{yaml_file.name}: missing top-level fields: {missing}")

    platform = data.get('platform', '')
    if platform not in VALID_PLATFORMS:
        errors.append(f"{yaml_file.name}: invalid platform '{platform}' (must be one of {VALID_PLATFORMS})")

    versions = data.get('versions', [])
    if not isinstance(versions, list) or not versions:
        errors.append(f"{yaml_file.name}: 'versions' must be a non-empty list")
        continue

    for i, v in enumerate(versions):
        vmissing = REQUIRED_VERSION - set(v.keys())
        if vmissing:
            errors.append(f"{yaml_file.name} version[{i}]: missing fields: {vmissing}")
        status = v.get('eol_status', '')
        if status not in VALID_STATUSES:
            errors.append(f"{yaml_file.name} version[{i}]: invalid eol_status '{status}'")

if errors:
    print(f"FAILED — {len(errors)} error(s) across {checked} file(s):\n")
    for e in errors:
        print(f"  {e}")
    sys.exit(1)
else:
    print(f"OK — {checked} file(s) validated successfully.")
