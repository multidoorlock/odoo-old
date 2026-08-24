#!/usr/bin/env python3
"""Normalize legacy value aliases and consolidate optional window variants.

The source workbook used different word orders and different SKU fragments for
the same semantic value.  Odoo should keep one global attribute value and store
the exceptional text/SKU on the product-template attribute value instead.
"""

import base64
import gzip
import itertools
import json
import math
import sys
from copy import deepcopy
from pathlib import Path


ALIASES = {
    # Door opening: one semantic value, regardless of RTL word order.
    "1 - L שמאל | צורת פתיחה לדלת": "1 - שמאל L | צורת פתיחה לדלת",
    "2 - דו צדדי | צורת פתיחה לדלת": "2 - דו צדדי D | צורת פתיחה לדלת",
    "3 - R ימין | צורת פתיחה לדלת": "3 - ימין R | צורת פתיחה לדלת",
    "4 - הזזה L שמאל | צורת פתיחה לדלת": "4 - הזזה שמאל L | צורת פתיחה לדלת",
    "6 - הזזה R ימין | צורת פתיחה לדלת": "6 - הזזה ימין R | צורת פתיחה לדלת",
    # The 8 mm shelter door uses 2 for right; this becomes a model override.
    "2 - R ימין | צורת פתיחה לדלת": "3 - ימין R | צורת פתיחה לדלת",
    # Same color/company written differently in separate sections.
    "01 - ר.ב | חברה": "01 - רב בריח | חברה",
    "03 - פל-רז | חברה": "02 - פל-רז | חברה",
    "— - מלאי - לבן - גוון 9016\nשחור - גוון 9005\nשמנת -גוון 1013\nאפור כהה -גוון 9007\nאפור בהיר -גוון 9006 | גוון": (
        "— - מלאי - לבן - גוון 9016 שחור - גוון 9005 שמנת -גוון 1013 "
        "אפור כהה -גוון 9007 אפור בהיר -גוון 9006 | גוון"
    ),
}

WINDOW_GROUP = "20 - חלון"
WINDOW_MODEL_CODES = {"18", "20", "24", "32"}
NO_DRESSING_KEY = "— - ללא הלבשה | עומק הלבשה"
MULTIDOORLOCK_KEY = "— - מולטי דורלוק | חברה"
WINDOW_FORMAT = (
    "[שם קבוצת פריטים] [דגם] [צורת פתיחה לחלון] "
    "[רוחב חלון]/[גובה חלון]/[עובי קיר]+[עומק הלבשה] [חברה]"
)
WINDOW_SEQUENCES = {
    "צורת פתיחה לחלון": 10,
    "רוחב חלון": 20,
    "גובה חלון": 30,
    "עובי קיר": 40,
    "עומק הלבשה": 50,
    "חברה": 70,
}


def clean(value):
    return " ".join(str(value or "").split())


def replace_component(text, old_component, new_component):
    old_component = clean(old_component)
    new_component = clean(new_component)
    if not old_component or old_component == new_component:
        return text
    return clean(str(text).replace(old_component, new_component))


def normalize_aliases(data):
    source_values = {item["key"]: item for item in data["values"]}
    missing_canonical = set(ALIASES.values()) - set(source_values)
    if missing_canonical:
        raise RuntimeError(
            f"Missing canonical value keys: {sorted(missing_canonical)}"
        )
    active_aliases = {
        source: canonical
        for source, canonical in ALIASES.items()
        if source in source_values
    }

    aliases = []
    for source_key, canonical_key in active_aliases.items():
        source = source_values[source_key]
        canonical = source_values[canonical_key]
        aliases.append(
            {
                "source_key": source_key,
                "canonical_key": canonical_key,
                "source_name": source["name"],
                "source_name_component": source["name_component"],
                "source_sku_component": source["sku_component"],
            }
        )

    def canonical(key):
        while key in active_aliases:
            key = active_aliases[key]
        return key

    for template in data["templates"]:
        for line in template["attribute_lines"]:
            merged = {}
            for value_data in line["values"]:
                source_key = value_data["value_key"]
                canonical_key = canonical(source_key)
                updated = deepcopy(value_data)
                updated["value_key"] = canonical_key
                source = source_values[source_key]
                target = source_values[canonical_key]
                if source["sku_component"] != target["sku_component"]:
                    updated["sku_override"] = source["sku_component"] or "—"
                previous = merged.get(canonical_key)
                if previous and previous != updated:
                    raise RuntimeError(
                        f"Conflicting overrides in {template['key']}: "
                        f"{previous} / {updated}"
                    )
                merged[canonical_key] = updated
            line["values"] = list(merged.values())

        for variant in template["variants"]:
            original_keys = list(variant["value_keys"])
            for source_key in original_keys:
                canonical_key = canonical(source_key)
                if canonical_key != source_key:
                    variant["name"] = replace_component(
                        variant["name"],
                        source_values[source_key]["name_component"],
                        source_values[canonical_key]["name_component"],
                    )
            variant["value_keys"] = list(
                dict.fromkeys(canonical(key) for key in original_keys)
            )

        pairs = set()
        normalized_pairs = []
        for pair in template["forbidden_pairs"]:
            source = canonical(pair["value_key"])
            excluded = canonical(pair["excluded_value_key"])
            if source == excluded or (source, excluded) in pairs:
                continue
            pairs.add((source, excluded))
            normalized_pairs.append(
                {"value_key": source, "excluded_value_key": excluded}
            )
        template["forbidden_pairs"] = normalized_pairs

    data["values"] = [
        item for item in data["values"] if item["key"] not in active_aliases
    ]
    existing_aliases = {
        item["source_key"]: item for item in data.get("value_aliases", [])
    }
    existing_aliases.update({item["source_key"]: item for item in aliases})
    data["value_aliases"] = list(existing_aliases.values())


def ensure_optional_values(data):
    values = {item["key"]: item for item in data["values"]}
    if NO_DRESSING_KEY not in values:
        data["values"].append(
            {
                "key": NO_DRESSING_KEY,
                "attribute_key": "עומק הלבשה",
                "name": "ללא הלבשה",
                "name_component": "",
                "sku_component": "",
                "sequence": 490,
            }
        )
    if MULTIDOORLOCK_KEY not in values:
        raise RuntimeError("The Multi Doorlock company value is missing")


def recompute_pairs(template):
    lines = template["attribute_lines"]
    value_lists = [
        [item["value_key"] for item in line["values"]] for line in lines
    ]
    existing = {tuple(variant["value_keys"]) for variant in template["variants"]}
    expected_lengths = {len(item) for item in existing}
    if expected_lengths != {len(lines)}:
        raise RuntimeError(
            f"Invalid combination length in {template['key']}: {expected_lengths}"
        )

    allowed_pairs = {
        (left, right): {(row[left], row[right]) for row in existing}
        for left in range(len(lines))
        for right in range(left + 1, len(lines))
    }
    forbidden = []
    for left in range(len(lines)):
        for right in range(left + 1, len(lines)):
            for left_value in value_lists[left]:
                for right_value in value_lists[right]:
                    if (left_value, right_value) not in allowed_pairs[(left, right)]:
                        forbidden.append(
                            {
                                "value_key": left_value,
                                "excluded_value_key": right_value,
                            }
                        )

    pairwise_allowed = {
        row
        for row in itertools.product(*value_lists)
        if all(
            (row[left], row[right]) in allowed_pairs[(left, right)]
            for left in range(len(lines))
            for right in range(left + 1, len(lines))
        )
    }
    template["cartesian_count"] = math.prod(map(len, value_lists))
    template["forbidden_pairs"] = forbidden
    template["allowed_count_after_exclusions"] = len(pairwise_allowed)
    template["exclusions_exact"] = pairwise_allowed == existing


def consolidate_windows(data):
    values = {item["key"]: item for item in data["values"]}
    candidates = {}
    for template in data["templates"]:
        if (
            template["group_key"] == WINDOW_GROUP
            and str(template["model_code"]) in WINDOW_MODEL_CODES
        ):
            candidates.setdefault(str(template["model_code"]), []).append(template)

    removed = set()
    for model_code, source_templates in candidates.items():
        if len(source_templates) < 2:
            continue
        target = source_templates[0]
        removed.update(item["key"] for item in source_templates[1:])

        values_by_attribute = {key: {} for key in WINDOW_SEQUENCES}
        variants = []
        for source in source_templates:
            source_lines = {
                line["attribute_key"]: line for line in source["attribute_lines"]
            }
            for attribute_key, line in source_lines.items():
                for value_data in line["values"]:
                    existing = values_by_attribute[attribute_key].get(
                        value_data["value_key"]
                    )
                    if existing and existing != value_data:
                        raise RuntimeError(
                            f"Conflicting {attribute_key} value in model {model_code}: "
                            f"{existing} / {value_data}"
                        )
                    values_by_attribute[attribute_key][
                        value_data["value_key"]
                    ] = deepcopy(value_data)

            has_dressing = "עומק הלבשה" in source_lines
            has_company = "חברה" in source_lines
            for variant in source["variants"]:
                updated = deepcopy(variant)
                selected = {
                    key.split(" | ")[-1]: key for key in updated["value_keys"]
                }
                if not has_dressing:
                    selected["עומק הלבשה"] = NO_DRESSING_KEY
                if not has_company:
                    selected["חברה"] = MULTIDOORLOCK_KEY
                updated["value_keys"] = [
                    selected[attribute_key]
                    for attribute_key in WINDOW_SEQUENCES
                ]
                variants.append(updated)

        values_by_attribute["עומק הלבשה"].setdefault(
            NO_DRESSING_KEY,
            {
                "value_key": NO_DRESSING_KEY,
                "name_override": "—",
                "sku_override": "—",
            },
        )
        values_by_attribute["חברה"].setdefault(
            MULTIDOORLOCK_KEY,
            {
                "value_key": MULTIDOORLOCK_KEY,
                "name_override": "—",
                "sku_override": "—",
            },
        )

        target["name"] = target["model_name_component"]
        target["name_format"] = WINDOW_FORMAT
        target["attribute_lines"] = []
        for attribute_key, sequence in WINDOW_SEQUENCES.items():
            line_values = list(values_by_attribute[attribute_key].values())
            line_values.sort(
                key=lambda item: (
                    values[item["value_key"]]["sequence"], item["value_key"]
                )
            )
            target["attribute_lines"].append(
                {
                    "attribute_key": attribute_key,
                    "sequence": sequence,
                    "values": line_values,
                }
            )
        target["variants"] = sorted(
            variants, key=lambda item: (item["source_row"], item["sku"])
        )
        if len({item["sku"] for item in variants}) != len(variants):
            raise RuntimeError(f"Duplicate SKU after consolidating model {model_code}")
        if len({tuple(item["value_keys"]) for item in variants}) != len(variants):
            raise RuntimeError(
                f"Duplicate combination after consolidating model {model_code}"
            )
        recompute_pairs(target)

    data["templates"] = [
        item for item in data["templates"] if item["key"] not in removed
    ]


def validate(data):
    value_keys = [item["key"] for item in data["values"]]
    if len(value_keys) != len(set(value_keys)):
        raise RuntimeError("Duplicate global value keys remain")
    skus = [
        variant["sku"]
        for template in data["templates"]
        for variant in template["variants"]
    ] + [item["sku"] for item in data["unique_items"]]
    if len(skus) != data["metadata"]["total_products"]:
        raise RuntimeError(
            f"Expected {data['metadata']['total_products']} products, got {len(skus)}"
        )
    if len(skus) != len(set(skus)):
        raise RuntimeError("Duplicate final SKUs remain")


def main():
    json_path = Path(sys.argv[1])
    data = json.loads(json_path.read_text(encoding="utf-8"))
    normalize_aliases(data)
    ensure_optional_values(data)
    consolidate_windows(data)
    validate(data)

    json_text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    json_path.write_text(json_text, encoding="utf-8")
    compressed = gzip.compress(json_text.encode("utf-8"), mtime=0)
    encoded = base64.b64encode(compressed).decode("ascii") + "\n"
    json_path.with_name("catalog.json.gz.b64").write_text(
        encoded, encoding="ascii"
    )


if __name__ == "__main__":
    main()
