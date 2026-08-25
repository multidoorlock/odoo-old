#!/usr/bin/env python3
"""Normalize legacy values and consolidate products into native Odoo templates.

The source workbook used different word orders and different SKU fragments for
the same semantic value.  Odoo should keep one global attribute value and store
the exceptional text/SKU on the product-template attribute value instead.
"""

import base64
import gzip
import itertools
import json
import math
import re
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

FILTER_MODEL_ATTRIBUTE = "דגם מערכת סינון"
FILTER_CAPACITY_ATTRIBUTE = "קיבולת נפשות"
FILTER_GROUP = "40 - מערכת סינון"
FILTER_TEMPLATE_KEY = "40 - מערכת סינון"
FILTER_TARGET_SPECS = (
    {
        "company_key": "01 - רב בריח | חברה",
        "model_key": "— - לביא PRO | דגם מערכת סינון",
        "company_name": "רב בריח",
        "model_name": "לביא PRO",
        "company_code": "01",
    },
    {
        "company_key": "01 - רב בריח | חברה",
        "model_key": "— - כפיר+ | דגם מערכת סינון",
        "company_name": "רב בריח",
        "model_name": "כפיר+",
        "company_code": "01",
    },
    {
        "company_key": "09 - בית אל | חברה",
        "model_key": "— - Rainbow | דגם מערכת סינון",
        "company_name": "בית אל",
        "model_name": "Rainbow",
        "company_code": "09",
    },
    {
        "company_key": "09 - בית אל | חברה",
        "model_key": "— - Hidden | דגם מערכת סינון",
        "company_name": "בית אל",
        "model_name": "Hidden",
        "company_code": "09",
    },
)
FILTER_FORMAT = "[שם קבוצת פריטים] [דגם] [קיבולת נפשות]"

ALUMINUM_WINDOW_GROUP = "41 - חלון אלומיניום"
ALUMINUM_WINDOW_TARGET_KEY = "41 - חלון אלומיניום"
ALUMINUM_WINDOW_ATTRIBUTES = {
    "רוחב חלון": 20,
    "גובה חלון": 30,
    "גוון": 40,
    "חברה": 70,
}
NO_WINDOW_WIDTH_KEY = "— - ללא מידה | רוחב חלון"
NO_WINDOW_HEIGHT_KEY = "— - ללא מידה | גובה חלון"
GENERIC_COMPANY_KEY = "— - כללי | חברה"
ALUMINUM_WINDOW_FORMAT = (
    "[שם קבוצת פריטים] [דגם] [רוחב חלון]/[גובה חלון] [גוון] [חברה]"
)

STANDARD_WING_HEIGHT_KEY = "— - גובה רגיל | גובה כנף"
SWING_WING_SOURCE_KEYS = {
    '1201 - כנף לדלת ממ"ד לבן — +ידית',
    '1201 - כנף לדלת ממ"ד לבן — +ידית, גובה משתנה, מקוצר',
    '1201 - כנף לדלת ממ"ד לבן — +ידית, גובה משתנה',
}
SLIDING_WING_SOURCE_KEYS = {
    '1201 - כנף לדלת ממ"ד לבן — כולל מנגנון',
    '1201 - כנף לדלת ממ"ד לבן — כולל מנגנון, גובה משתנה, מקוצר',
    '1201 - כנף לדלת ממ"ד לבן — כולל מנגנון, גובה משתנה',
}
SWING_WING_TARGET_KEY = '1201 - כנף לדלת ממ"ד לבן — פתיחה רגילה'
SLIDING_WING_TARGET_KEY = '1201 - כנף לדלת ממ"ד לבן — הזזה'
RAV_BARIACH_KEY = "01 - רב בריח | חברה"
BEIT_EL_KEY = "09 - בית אל | חברה"
FILTER_MODEL_MAPPING = {
    "01 - דגם ר.ב לביא PRO | חברה": {
        "company_key": RAV_BARIACH_KEY,
        "company_name": "רב בריח",
        "model_key": "— - לביא PRO | דגם מערכת סינון",
        "model_name": "לביא PRO",
    },
    "01 - דגם ר.ב כפיר+ | חברה": {
        "company_key": RAV_BARIACH_KEY,
        "company_name": "רב בריח",
        "model_key": "— - כפיר+ | דגם מערכת סינון",
        "model_name": "כפיר+",
    },
    "09 - דגם ב.א Rainbow | חברה": {
        "company_key": BEIT_EL_KEY,
        "company_name": "בית אל",
        "model_key": "— - Rainbow | דגם מערכת סינון",
        "model_name": "Rainbow",
    },
    "09 - דגם ב.א Hidden סמויה אחודה | חברה": {
        "company_key": BEIT_EL_KEY,
        "company_name": "בית אל",
        "model_key": "— - Hidden סמויה אחודה | דגם מערכת סינון",
        "model_name": "Hidden סמויה אחודה",
    },
}
GENERATED_FILTER_MODEL_ALIASES = {
    "— - דגם לביא PRO | דגם מערכת סינון": "— - לביא PRO | דגם מערכת סינון",
    "— - דגם כפיר+ | דגם מערכת סינון": "— - כפיר+ | דגם מערכת סינון",
    "— - דגם Rainbow | דגם מערכת סינון": "— - Rainbow | דגם מערכת סינון",
    "— - דגם Hidden סמויה אחודה | דגם מערכת סינון": (
        "— - Hidden | דגם מערכת סינון"
    ),
    "— - Hidden סמויה אחודה | דגם מערכת סינון": (
        "— - Hidden | דגם מערכת סינון"
    ),
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


def split_filter_company_and_model(data):
    """Separate filter-system models from their actual manufacturers.

    The legacy workbook stored values such as "דגם ר.ב לביא PRO" inside
    the Company attribute. In Odoo these are two independent facts: the
    company is Rav-Bariach or Beit-El, while Lavi/Kfir/Rainbow/Hidden is the
    filter-system model.
    """
    source_values = {item["key"]: item for item in data["values"]}
    active_keys = set(FILTER_MODEL_MAPPING) & set(source_values)
    if not active_keys:
        return

    if not any(
        item["key"] == FILTER_MODEL_ATTRIBUTE for item in data["attributes"]
    ):
        data["attributes"].append(
            {
                "key": FILTER_MODEL_ATTRIBUTE,
                "name": FILTER_MODEL_ATTRIBUTE,
                "sequence": 80,
                "display_type": "select",
            }
        )

    if BEIT_EL_KEY not in source_values:
        data["values"].append(
            {
                "key": BEIT_EL_KEY,
                "attribute_key": "חברה",
                "name": "בית אל",
                "name_component": "בית אל",
                "sku_component": "09",
                "sequence": 640,
            }
        )
    if RAV_BARIACH_KEY not in source_values:
        raise RuntimeError("The Rav-Bariach company value is missing")

    for sequence, mapping in enumerate(FILTER_MODEL_MAPPING.values(), start=10):
        if mapping["model_key"] not in source_values:
            data["values"].append(
                {
                    "key": mapping["model_key"],
                    "attribute_key": FILTER_MODEL_ATTRIBUTE,
                    "name": mapping["model_name"],
                    "name_component": mapping["model_name"],
                    "sku_component": "",
                    "sequence": sequence,
                }
            )

    for template in data["templates"]:
        company_line = next(
            (
                line
                for line in template["attribute_lines"]
                if line["attribute_key"] == "חברה"
                and any(
                    value["value_key"] in active_keys for value in line["values"]
                )
            ),
            None,
        )
        if not company_line:
            continue
        if any(
            value["value_key"] not in active_keys
            for value in company_line["values"]
        ):
            raise RuntimeError(
                f"Mixed legacy filter companies in {template['key']}"
            )

        company_values = {}
        model_values = {}
        for value_data in company_line["values"]:
            mapping = FILTER_MODEL_MAPPING[value_data["value_key"]]
            company_values.setdefault(
                mapping["company_key"], {"value_key": mapping["company_key"]}
            )
            model_values.setdefault(
                mapping["model_key"], {"value_key": mapping["model_key"]}
            )
        company_line["values"] = list(company_values.values())
        template["attribute_lines"].append(
            {
                "attribute_key": FILTER_MODEL_ATTRIBUTE,
                "sequence": 80,
                "values": list(model_values.values()),
            }
        )
        if f"[{FILTER_MODEL_ATTRIBUTE}]" not in template["name_format"]:
            template["name_format"] = template["name_format"].replace(
                "[חברה]", f"[חברה] דגם [{FILTER_MODEL_ATTRIBUTE}]"
            )

        for variant in template["variants"]:
            legacy_key = next(
                (key for key in variant["value_keys"] if key in active_keys),
                None,
            )
            if not legacy_key:
                raise RuntimeError(
                    f"Missing legacy filter company in {template['key']}"
                )
            mapping = FILTER_MODEL_MAPPING[legacy_key]
            variant["name"] = replace_component(
                variant["name"],
                source_values[legacy_key]["name_component"],
                f"{mapping['company_name']} דגם {mapping['model_name']}",
            )
            selected = {
                key.split(" | ")[-1]: key
                for key in variant["value_keys"]
                if key != legacy_key
            }
            selected["חברה"] = mapping["company_key"]
            selected[FILTER_MODEL_ATTRIBUTE] = mapping["model_key"]
            variant["value_keys"] = [
                selected[line["attribute_key"]]
                for line in template["attribute_lines"]
            ]
        recompute_pairs(template)

    data["values"] = [
        item for item in data["values"] if item["key"] not in active_keys
    ]


def normalize_filter_model_labels(data):
    """Keep only the actual filter model name in the reusable value."""
    values = {item["key"]: item for item in data["values"]}
    active_aliases = {
        source: target
        for source, target in GENERATED_FILTER_MODEL_ALIASES.items()
        if source in values
    }
    if not active_aliases:
        return

    for source_key, target_key in active_aliases.items():
        if target_key not in values:
            source = deepcopy(values[source_key])
            source["key"] = target_key
            target_name = target_key.split(" - ", 1)[1].split(" | ", 1)[0]
            source["name"] = target_name
            source["name_component"] = target_name
            data["values"].append(source)

    for template in data["templates"]:
        changed = False
        for line in template["attribute_lines"]:
            for value_data in line["values"]:
                source_key = value_data["value_key"]
                if source_key in active_aliases:
                    value_data["value_key"] = active_aliases[source_key]
                    changed = True
        for variant in template["variants"]:
            variant["value_keys"] = [
                active_aliases.get(key, key) for key in variant["value_keys"]
            ]
        if changed:
            template["name_format"] = template["name_format"].replace(
                f"[חברה] [{FILTER_MODEL_ATTRIBUTE}]",
                f"[חברה] דגם [{FILTER_MODEL_ATTRIBUTE}]",
            )
            recompute_pairs(template)

    data["values"] = [
        item for item in data["values"] if item["key"] not in active_aliases
    ]


def _filter_capacity_key(code):
    return f"{code} - {int(code)} נפשות | {FILTER_CAPACITY_ATTRIBUTE}"


def _filter_area(source_name):
    match = re.search(r'לממ"מ עד ([0-9.]+) מ"ר', clean(source_name))
    return float(match.group(1)) if match else None


def split_filter_systems(data):
    """Create one Odoo template for each manufacturer/model combination.

    Capacity remains the only variant axis. The company code stays at the end
    of the historical SKU through a model-specific capacity override.
    """
    target_keys = {
        f"{FILTER_GROUP} — {spec['company_name']} — {spec['model_name']}"
        for spec in FILTER_TARGET_SPECS
    }
    source_templates = [
        item for item in data["templates"] if item["group_key"] == FILTER_GROUP
    ]
    if {item["key"] for item in source_templates} == target_keys:
        return
    if len(source_templates) != 1:
        raise RuntimeError(
            f"Expected one consolidated filter template, got {len(source_templates)}"
        )

    source = source_templates[0]
    values = {item["key"]: item for item in data["values"]}
    targets = []
    for spec in FILTER_TARGET_SPECS:
        variants = []
        for variant in source["variants"]:
            if (
                spec["company_key"] not in variant["value_keys"]
                or spec["model_key"] not in variant["value_keys"]
            ):
                continue
            updated = deepcopy(variant)
            capacity_key = next(
                key
                for key in updated["value_keys"]
                if key.endswith(f"| {FILTER_CAPACITY_ATTRIBUTE}")
            )
            updated["value_keys"] = [capacity_key]
            updated["name"] = clean(
                " ".join(
                    (
                        "מערכת סינון",
                        spec["company_name"],
                        spec["model_name"],
                        values[capacity_key]["name_component"],
                    )
                )
            )
            variants.append(updated)
        if not variants:
            raise RuntimeError(
                f"No filter variants for {spec['company_name']} {spec['model_name']}"
            )

        capacity_keys = sorted(
            {variant["value_keys"][0] for variant in variants},
            key=lambda key: values[key]["sequence"],
        )
        target = deepcopy(source)
        target.update(
            {
                "key": (
                    f"{FILTER_GROUP} — {spec['company_name']} — "
                    f"{spec['model_name']}"
                ),
                "name": f"{spec['company_name']} {spec['model_name']}",
                "model_code": "",
                "group_name_component": "מערכת סינון",
                "model_name_component": (
                    f"{spec['company_name']} {spec['model_name']}"
                ),
                "suppress_model_name": False,
                "name_format": FILTER_FORMAT,
                "attribute_lines": [
                    {
                        "attribute_key": FILTER_CAPACITY_ATTRIBUTE,
                        "sequence": 60,
                        "values": [
                            {
                                "value_key": key,
                                "sku_override": (
                                    f"{values[key]['sku_component']}"
                                    f"{spec['company_code']}"
                                ),
                            }
                            for key in capacity_keys
                        ],
                    }
                ],
                "variants": sorted(
                    variants, key=lambda item: (item["source_row"], item["sku"])
                ),
            }
        )
        recompute_pairs(target)
        targets.append(target)

    data["templates"] = [
        item
        for item in data["templates"]
        if item["group_key"] != FILTER_GROUP
    ] + targets

    if not any(
        line["attribute_key"] == FILTER_MODEL_ATTRIBUTE
        for template in data["templates"]
        for line in template["attribute_lines"]
    ):
        data["attributes"] = [
            item for item in data["attributes"]
            if item["key"] != FILTER_MODEL_ATTRIBUTE
        ]
        data["values"] = [
            item for item in data["values"]
            if item["attribute_key"] != FILTER_MODEL_ATTRIBUTE
        ]


def _merge_wing_family(data, source_keys, target_key, model_name, sliding):
    source_templates = [
        item for item in data["templates"] if item["key"] in source_keys
    ]
    if len(source_templates) != 3:
        raise RuntimeError(
            f"Expected three wing templates for {target_key}, "
            f"got {len(source_templates)}"
        )

    values = {item["key"]: item for item in data["values"]}
    attributes = ("צורת פתיחה לדלת", "פתח אור לדלת", "גובה כנף")
    values_by_attribute = {key: {} for key in attributes}
    variants = []
    for source in source_templates:
        source_lines = {
            line["attribute_key"]: line for line in source["attribute_lines"]
        }
        for attribute_key in attributes[:2]:
            for value_data in source_lines[attribute_key]["values"]:
                values_by_attribute[attribute_key].setdefault(
                    value_data["value_key"], deepcopy(value_data)
                )
        for value_data in source_lines.get("גובה כנף", {}).get("values", []):
            values_by_attribute["גובה כנף"].setdefault(
                value_data["value_key"], deepcopy(value_data)
            )

        for variant in source["variants"]:
            updated = deepcopy(variant)
            selected = {
                key.split(" | ")[-1]: key for key in updated["value_keys"]
            }
            selected.setdefault("גובה כנף", STANDARD_WING_HEIGHT_KEY)
            updated["value_keys"] = [
                selected[attribute_key] for attribute_key in attributes
            ]
            variants.append(updated)

    values_by_attribute["גובה כנף"][STANDARD_WING_HEIGHT_KEY] = {
        "value_key": STANDARD_WING_HEIGHT_KEY,
        "name_override": "—",
        "sku_override": "—",
    }
    for value_key, value_data in values_by_attribute["גובה כנף"].items():
        value_name = values[value_key]["name"]
        if value_name in {"200", "201", "202"}:
            value_data["name_override"] = f"מקוצר {value_name}"

    if sliding:
        for value_key, value_data in values_by_attribute[
            "צורת פתיחה לדלת"
        ].items():
            value_data["name_override"] = clean(
                re.sub(r"^הזזה\s+", "", values[value_key]["name"])
            )

    target = deepcopy(source_templates[0])
    target.update(
        {
            "key": target_key,
            "name": model_name,
            "model_code": "01",
            "group_name_component": "כנף",
            "model_name_component": model_name,
            "suppress_model_name": False,
            "name_format": (
                '[שם קבוצת פריטים] [דגם] [צורת פתיחה לדלת] '
                '[פתח אור לדלת] [גובה כנף] ***כולל מנגנון***'
                if sliding
                else '[שם קבוצת פריטים] [דגם] [צורת פתיחה לדלת] '
                '[פתח אור לדלת] [גובה כנף] [+ידית]'
            ),
            "attribute_lines": [
                {
                    "attribute_key": attribute_key,
                    "sequence": sequence,
                    "values": sorted(
                        values_by_attribute[attribute_key].values(),
                        key=lambda item: values[item["value_key"]]["sequence"],
                    ),
                }
                for attribute_key, sequence in zip(attributes, (10, 20, 30))
            ],
            "variants": sorted(
                variants, key=lambda item: (item["source_row"], item["sku"])
            ),
        }
    )
    recompute_pairs(target)
    return target


def merge_white_mamad_wings(data):
    """Represent the white MAMAD wing as two logical products, not six."""
    existing_keys = {item["key"] for item in data["templates"]}
    if {
        SWING_WING_TARGET_KEY,
        SLIDING_WING_TARGET_KEY,
    }.issubset(existing_keys):
        return
    if not SWING_WING_SOURCE_KEYS.issubset(existing_keys):
        raise RuntimeError("The regular white-MAMAD wing templates are incomplete")
    if not SLIDING_WING_SOURCE_KEYS.issubset(existing_keys):
        raise RuntimeError("The sliding white-MAMAD wing templates are incomplete")

    if not any(
        item["key"] == STANDARD_WING_HEIGHT_KEY for item in data["values"]
    ):
        data["values"].append(
            {
                "key": STANDARD_WING_HEIGHT_KEY,
                "attribute_key": "גובה כנף",
                "name": "גובה רגיל",
                "name_component": "",
                "sku_component": "",
                "sequence": 250,
            }
        )

    swing = _merge_wing_family(
        data,
        SWING_WING_SOURCE_KEYS,
        SWING_WING_TARGET_KEY,
        'לדלת ממ"ד לבן',
        False,
    )
    sliding = _merge_wing_family(
        data,
        SLIDING_WING_SOURCE_KEYS,
        SLIDING_WING_TARGET_KEY,
        'לדלת ממ"ד לבן הזזה',
        True,
    )
    all_source_keys = SWING_WING_SOURCE_KEYS | SLIDING_WING_SOURCE_KEYS
    result = []
    inserted = False
    for template in data["templates"]:
        if template["key"] in all_source_keys:
            if not inserted:
                result.extend((swing, sliding))
                inserted = True
            continue
        result.append(template)
    data["templates"] = result


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


def merge_aluminum_windows(data):
    """Keep every aluminium-window SKU under one logical Odoo template."""
    source_templates = [
        item
        for item in data["templates"]
        if item["group_key"] == ALUMINUM_WINDOW_GROUP
    ]
    if len(source_templates) <= 1:
        return

    values = {item["key"]: item for item in data["values"]}
    technical_values = (
        {
            "key": NO_WINDOW_WIDTH_KEY,
            "attribute_key": "רוחב חלון",
            "name": "ללא מידה",
            "name_component": "ללא מידה",
            "sku_component": "",
        },
        {
            "key": NO_WINDOW_HEIGHT_KEY,
            "attribute_key": "גובה חלון",
            "name": "ללא מידה",
            "name_component": "ללא מידה",
            "sku_component": "",
        },
        {
            "key": GENERIC_COMPANY_KEY,
            "attribute_key": "חברה",
            "name": "כללי",
            "name_component": "כללי",
            "sku_component": "",
        },
    )
    next_sequence = max(item["sequence"] for item in data["values"]) + 10
    for value_data in technical_values:
        if value_data["key"] in values:
            continue
        value_data = {**value_data, "sequence": next_sequence}
        next_sequence += 10
        data["values"].append(value_data)
        values[value_data["key"]] = value_data

    values_by_attribute = {
        key: {} for key in ALUMINUM_WINDOW_ATTRIBUTES
    }
    variants = []
    for source in source_templates:
        for line in source["attribute_lines"]:
            for value_data in line["values"]:
                values_by_attribute[line["attribute_key"]].setdefault(
                    value_data["value_key"], deepcopy(value_data)
                )
        for variant in source["variants"]:
            updated = deepcopy(variant)
            selected = {
                key.split(" | ")[-1]: key for key in updated["value_keys"]
            }
            selected.setdefault("רוחב חלון", NO_WINDOW_WIDTH_KEY)
            selected.setdefault("גובה חלון", NO_WINDOW_HEIGHT_KEY)
            selected.setdefault("חברה", GENERIC_COMPANY_KEY)
            updated["value_keys"] = [
                selected[attribute_key]
                for attribute_key in ALUMINUM_WINDOW_ATTRIBUTES
            ]
            variants.append(updated)

    for attribute_key, value_key in (
        ("רוחב חלון", NO_WINDOW_WIDTH_KEY),
        ("גובה חלון", NO_WINDOW_HEIGHT_KEY),
        ("חברה", GENERIC_COMPANY_KEY),
    ):
        values_by_attribute[attribute_key].setdefault(
            value_key,
            {
                "value_key": value_key,
                "name_override": "—",
                "sku_override": "—",
            },
        )

    target = source_templates[0]
    target.update(
        {
            "key": ALUMINUM_WINDOW_TARGET_KEY,
            "source_model_lookup": "4100 - חלון אלומיניום",
            "model_code": "",
            "name": "חלון אלומיניום",
            "model_name_component": "",
            "suppress_model_name": True,
            "name_format": ALUMINUM_WINDOW_FORMAT,
            "variants": sorted(
                variants, key=lambda item: (item["source_row"], item["sku"])
            ),
        }
    )
    target["attribute_lines"] = []
    for attribute_key, sequence in ALUMINUM_WINDOW_ATTRIBUTES.items():
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
    if len({item["sku"] for item in variants}) != len(variants):
        raise RuntimeError("Duplicate SKU after merging aluminium windows")
    if len({tuple(item["value_keys"]) for item in variants}) != len(variants):
        raise RuntimeError("Duplicate combination after merging aluminium windows")
    recompute_pairs(target)

    source_keys = {item["key"] for item in source_templates[1:]}
    data["templates"] = [
        item for item in data["templates"] if item["key"] not in source_keys
    ]


def refresh_metadata(data):
    skus = [
        variant["sku"]
        for template in data["templates"]
        for variant in template["variants"]
    ] + [item["sku"] for item in data["unique_items"]]
    data["metadata"].update(
        {
            "groups": len(data["groups"]),
            "templates": len(data["templates"]),
            "attributes": len(data["attributes"]),
            "values": len(data["values"]),
            "structured_variants": sum(
                len(item["variants"]) for item in data["templates"]
            ),
            "unique_items": len(data["unique_items"]),
            "total_products": len(skus),
            "cartesian_mismatches": sum(
                item["cartesian_count"] != len(item["variants"])
                for item in data["templates"]
            ),
            "templates_with_exclusions": sum(
                item["allowed_count_after_exclusions"] != item["cartesian_count"]
                for item in data["templates"]
            ),
            "forbidden_pairs": sum(
                len(item["forbidden_pairs"]) for item in data["templates"]
            ),
            "exclusion_mismatches": sum(
                not item["exclusions_exact"] for item in data["templates"]
            ),
            "output_mismatches": 0,
            "duplicate_skus": len(skus) - len(set(skus)),
            "duplicate_model_keys": 0,
        }
    )


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
    split_filter_company_and_model(data)
    normalize_filter_model_labels(data)
    split_filter_systems(data)
    consolidate_windows(data)
    merge_aluminum_windows(data)
    merge_white_mamad_wings(data)
    for template in data["templates"]:
        recompute_pairs(template)
    refresh_metadata(data)
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
