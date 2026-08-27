import base64
import gzip
import hashlib
import json
import logging
import os
from pathlib import Path

from odoo import Command
from odoo.exceptions import UserError
from odoo.addons.mdl_product_groups_attributes.models.catalog_utils import (
    normalize_token,
    split_direction_marker,
    split_legacy_name_format,
)


_logger = logging.getLogger("mdl_product_groups_attributes_import")
XMLID_NAMESPACE = "mdl_product_catalog_import"
LEGACY_XMLID_NAMESPACE = "mdl_product_catalog_test_data"
DATA_FILE = Path(__file__).parent / "catalog.json.gz.b64"

# Product records from Odoo 19's official product_demo.xml. We archive their
# templates instead of unlinking them because demo documents may reference them.
ODOO_DEMO_PRODUCT_XMLIDS = (
    "expense_product", "expense_hotel", "product_product_1",
    "product_product_2", "product_delivery_01", "product_delivery_02",
    "product_order_01", "product_product_3",
    "product_product_4_product_template", "product_product_4",
    "product_product_4b", "product_product_4c", "product_product_5",
    "product_product_6", "product_product_7", "product_product_8",
    "product_product_8_glass", "product_product_8_metal",
    "product_product_9", "product_product_10",
    "product_product_11_product_template", "product_product_11",
    "product_product_11b", "product_product_12", "product_product_13",
    "product_product_16", "product_product_20", "product_product_22",
    "product_product_24", "product_template_acoustic_bloc_screens",
    "product_product_acoustic_bloc_screens_black", "product_product_27",
    "consu_delivery_03", "consu_delivery_02", "consu_delivery_01",
    "consu_delivery_01_velvet", "consu_delivery_01_leather",
    "product_product_local_delivery", "product_product_furniture",
    "product_template_dining_table", "desk_organizer", "desk_pad",
    "monitor_stand", "office_combo",
)


def _clean(value):
    return " ".join(str(value or "").split())


def _xmlid_name(prefix, key):
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def _register_xmlid(env, prefix, key, record):
    env["ir.model.data"].create(
        {
            "module": XMLID_NAMESPACE,
            "name": _xmlid_name(prefix, key),
            "model": record._name,
            "res_id": record.id,
            "noupdate": True,
        }
    )


def _load_source():
    compressed = base64.b64decode(DATA_FILE.read_text(encoding="ascii"))
    return json.loads(gzip.decompress(compressed).decode("utf-8"))


def _archive_odoo_demo_products(env):
    xmlids = env["ir.model.data"].sudo().search(
        [
            ("module", "=", "product"),
            ("name", "in", ODOO_DEMO_PRODUCT_XMLIDS),
            ("model", "in", ("product.product", "product.template")),
        ]
    )
    product_xmlids = xmlids.filtered(
        lambda item: item.model == "product.product"
    )
    template_xmlids = xmlids.filtered(
        lambda item: item.model == "product.template"
    )
    products = env["product.product"].with_context(active_test=False).browse(
        product_xmlids.mapped("res_id")
    ).exists()
    templates = (
        products.product_tmpl_id
        | env["product.template"].with_context(active_test=False).browse(
            template_xmlids.mapped("res_id")
        ).exists()
    )
    if templates:
        templates.with_context(skip_mdl_catalog_sync=True).write(
            {"active": False}
        )
        _logger.info("Archived %s Odoo demo product templates", len(templates))


def _check_existing_skus(env, data):
    expected_skus = [
        variant["sku"]
        for template in data["templates"]
        for variant in template["variants"]
    ] + [item["sku"] for item in data["unique_items"]]
    existing = env["product.product"].with_context(active_test=False).search(
        [("default_code", "in", expected_skus)], limit=20
    )
    if existing:
        examples = ", ".join(existing.mapped("default_code")[:10])
        raise UserError(
            "לא ניתן לייבא את הקטלוג: קיימים כבר פריטים עם מק״טים "
            f"מהקובץ ({examples}) אך הם אינם שייכים לייבוא מזוהה."
        )


def _create_categories(env, data):
    Category = env["product.category"]
    result = {}
    for item in data["groups"]:
        category = Category.create(
            {
                "name": item["name"],
                "mdl_sku_component": item["code"],
            }
        )
        _register_xmlid(env, "category", item["key"], category)
        result[item["key"]] = category
    unique_category = Category.create({"name": "פריטים ייחודיים"})
    _register_xmlid(env, "category", "unique_items", unique_category)
    return result, unique_category


def _create_attributes_and_values(env, data):
    Attribute = env["product.attribute"]
    Value = env["product.attribute.value"]
    attributes = {}
    for item in data["attributes"]:
        attribute = Attribute.create(
            {
                "name": item["name"],
                "sequence": item["sequence"],
                "display_type": item["display_type"],
                "create_variant": "always",
            }
        )
        _register_xmlid(env, "attribute", item["key"], attribute)
        attributes[item["key"]] = attribute

    values = {}
    for item in data["values"]:
        value = Value.with_context(skip_mdl_catalog_sync=True).create(
            {
                "name": item["name"],
                "attribute_id": attributes[item["attribute_key"]].id,
                "sequence": item["sequence"],
                # In the legacy source, an empty component is intentional: the
                # value changes the name but does not add digits to the SKU.
                # The catalog module uses an em dash to distinguish that case
                # from a genuinely missing code.
                "mdl_sku_component": item["sku_component"] or "—",
            }
        )
        _register_xmlid(env, "attribute_value", item["key"], value)
        values[item["key"]] = value
    return attributes, values


def _validate_and_register_variants(env, template, template_data, values):
    template._create_variant_ids()
    env.flush_all()
    env.invalidate_all()
    template = env["product.template"].with_context(active_test=False).browse(
        template.id
    )
    expected_by_tuple = {
        tuple(sorted(values[key].id for key in variant["value_keys"])): variant
        for variant in template_data["variants"]
    }
    actual_by_tuple = {
        tuple(
            sorted(
                product.product_template_attribute_value_ids
                .product_attribute_value_id.ids
            )
        ): product
        for product in template.product_variant_ids
    }
    missing = expected_by_tuple.keys() - actual_by_tuple.keys()
    if missing:
        raise UserError(
            "נתוני הקטלוג אינם מייצרים את כל השילובים בדגם "
            f"{template_data['key']}: חסרים {len(missing)} שילובים."
        )
    # Standard Odoo exclusions cover every pairwise rule.  If a legacy rule
    # depends on three or more values, archive only the remaining exact
    # combinations that cannot be expressed by ``Exclude for``.
    extra_products = env["product.product"].browse(
        [
            actual_by_tuple[value_tuple].id
            for value_tuple in actual_by_tuple.keys() - expected_by_tuple.keys()
        ]
    )
    if extra_products:
        extra_products.with_context(skip_mdl_catalog_sync=True).write(
            {"mdl_catalog_allowed": False, "active": False}
        )
    expected_products = env["product.product"].browse(
        [actual_by_tuple[value_tuple].id for value_tuple in expected_by_tuple]
    )
    expected_products.with_context(skip_mdl_catalog_sync=True).write(
        {"mdl_catalog_allowed": True, "active": True}
    )
    template = template.with_context(active_test=True)
    template._mdl_sync_variant_codes()
    for value_tuple, expected in expected_by_tuple.items():
        product = actual_by_tuple[value_tuple]
        actual_sku = _clean(product.default_code)
        actual_name = _clean(product.mdl_generated_name)
        expected_name, expected_marker = split_direction_marker(expected["name"])
        expected_name = _clean(
            f"{expected_name} {expected_marker}" if expected_marker else expected_name
        )
        if actual_sku != expected["sku"] or actual_name != expected_name:
            raise UserError(
                "אי־התאמה בנתוני הקטלוג עבור "
                f"{expected['sku']}: התקבל {actual_sku} - {actual_name}."
            )
        if product.default_code != expected["sku"]:
            raise UserError(
                f"המק״ט {expected['sku']} חושב אך לא נשמר בפריט."
            )
        technical_values = {}
        if "max_protected_area_m2" in expected:
            technical_values["mdl_max_protected_area_m2"] = expected[
                "max_protected_area_m2"
            ]
        if "installation_type" in expected:
            technical_values["mdl_installation_type"] = expected[
                "installation_type"
            ]
        if technical_values:
            product.with_context(skip_mdl_catalog_sync=True).write(
                technical_values
            )


def _create_standard_exclusions(env, template, template_data, values):
    """Create Odoo's native ``Exclude for`` rules from safe value pairs."""
    if not template_data.get("forbidden_pairs"):
        return
    template_values = {
        value.product_attribute_value_id.id: value
        for value in template.attribute_line_ids.product_template_value_ids
    }
    excluded_by_value = {}
    for pair in template_data["forbidden_pairs"]:
        source = template_values[values[pair["value_key"]].id]
        excluded = template_values[values[pair["excluded_value_key"]].id]
        excluded_by_value.setdefault(source.id, set()).add(excluded.id)
    env["product.template.attribute.exclusion"].create(
        [
            {
                "product_template_attribute_value_id": source_id,
                "product_tmpl_id": template.id,
                "value_ids": [Command.set(sorted(excluded_ids))],
            }
            for source_id, excluded_ids in excluded_by_value.items()
        ]
    )


def _create_templates(env, data, categories, attributes, values):
    Template = env["product.template"].with_context(skip_mdl_catalog_sync=True)
    templates = []
    for item in data["templates"]:
        attribute_names = [line["attribute_key"] for line in item["attribute_lines"]]
        name_rules, final_suffix = split_legacy_name_format(
            item["name_format"], attribute_names
        )
        visible_rules = sorted(
            (
                (rule["sequence"], key, rule)
                for key, rule in name_rules.items()
                if rule["sequence"] is not None
            ),
            key=lambda row: row[0],
        )
        first_visible_key = visible_rules[0][1] if visible_rules else None
        leading_text = (
            _clean(name_rules[first_visible_key]["prefix"])
            if first_visible_key
            else ""
        )
        lines = []
        for line in item["attribute_lines"]:
            rule_key = normalize_token(line["attribute_key"])
            rule = name_rules[rule_key]
            lines.append(
                Command.create(
                    {
                        "attribute_id": attributes[line["attribute_key"]].id,
                        "sequence": line["sequence"],
                        "mdl_name_mode": rule["name_mode"],
                        "mdl_name_suffix": rule["suffix"] or False,
                        "value_ids": [
                            Command.set(
                                [values[value["value_key"]].id for value in line["values"]]
                            )
                        ],
                    }
                )
            )
        group = categories[item["group_key"]]
        group_name_override = (
            item["group_name_component"]
            if _clean(item["group_name_component"]) != _clean(group.name)
            else False
        )
        source_model_name = _clean(
            item["model_name_component"] or item["name"]
        )
        effective_model_name = _clean(
            " ".join(
                part for part in (
                    "" if item["suppress_model_name"] else source_model_name,
                    leading_text,
                ) if part
            )
        )
        model_name_override = (
            effective_model_name
            if effective_model_name != source_model_name
            else False
        )
        if item["suppress_model_name"]:
            model_name_override = "—"
        template = Template.create(
            {
                # The native model record holds the real model source value.
                # Descriptions such as "מידה משתנה" belong to the legacy
                # grouping logic and must not become the model name.
                "name": source_model_name,
                "categ_id": group.id,
                "mdl_group_name_override": group_name_override,
                "mdl_model_sku_component": item["model_code"],
                "mdl_model_name_override": model_name_override,
                "mdl_name_suffix": final_suffix or False,
                "attribute_line_ids": lines,
            }
        )
        template_values = {
            value.product_attribute_value_id.id: value
            for value in template.attribute_line_ids.product_template_value_ids
        }
        for line in item["attribute_lines"]:
            for value_data in line["values"]:
                template_value = template_values[
                    values[value_data["value_key"]].id
                ]
                if value_data.get("name_override"):
                    template_value.mdl_name_component_override = value_data[
                        "name_override"
                    ]
                if value_data.get("sku_override"):
                    template_value.mdl_sku_component_override = value_data[
                        "sku_override"
                    ]
        _create_standard_exclusions(env, template, item, values)
        _register_xmlid(env, "template", item["key"], template)
        _validate_and_register_variants(env, template, item, values)
        templates.append(template)
    return env["product.template"].browse([template.id for template in templates])


def _create_unique_items(env, data, category):
    Template = env["product.template"]
    templates = []
    for item in data["unique_items"]:
        template = Template.create(
            {
                "name": item["name"],
                "categ_id": category.id,
                "default_code": item["sku"],
            }
        )
        _register_xmlid(env, "unique_template", item["sku"], template)
        templates.append(template)
    return Template.browse([template.id for template in templates])


def _expected_skus(data):
    return {
        variant["sku"]
        for template in data["templates"]
        for variant in template["variants"]
    } | {item["sku"] for item in data["unique_items"]}


def _validate_existing_catalog(env, data):
    expected_skus = _expected_skus(data)
    products = env["product.product"].with_context(active_test=False).search(
        [("default_code", "in", list(expected_skus))]
    )
    actual_skus = products.mapped("default_code")
    actual_sku_set = set(actual_skus)
    missing = expected_skus - actual_sku_set
    duplicates = len(actual_skus) - len(actual_sku_set)
    if missing or duplicates or len(products) != len(expected_skus):
        raise UserError(
            "קטלוג קיים נמצא אך אינו שלם: "
            f"חסרים {len(missing)} מק״טים ונמצאו {duplicates} כפילויות."
        )
    return products


def _prepare_existing_import(env, data):
    ModelData = env["ir.model.data"].sudo()
    current_xmlids = ModelData.search(
        [("module", "=", XMLID_NAMESPACE)]
    )
    legacy_xmlids = ModelData.search(
        [("module", "=", LEGACY_XMLID_NAMESPACE)]
    )
    if current_xmlids:
        products = _validate_existing_catalog(env, data)
        return products, "already_imported"
    if legacy_xmlids:
        products = _validate_existing_catalog(env, data)
        legacy_xmlids.write({"module": XMLID_NAMESPACE})
        return products, "legacy_migrated"
    return env["product.product"], False


def import_catalog(env):
    """Import the catalog once, or validate a previous script import."""
    catalog_module = env["ir.module.module"].sudo().search(
        [
            ("name", "=", "mdl_product_groups_attributes"),
            ("state", "=", "installed"),
        ],
        limit=1,
    )
    if not catalog_module:
        raise UserError(
            "יש להתקין תחילה את המודול mdl_product_groups_attributes."
        )
    data = _load_source()
    existing_products, status = _prepare_existing_import(env, data)
    if status:
        _logger.info(
            "MDL catalog already present: %s products (%s)",
            len(existing_products),
            status,
        )
        return {
            "status": status,
            "products": len(existing_products),
        }

    _archive_odoo_demo_products(env)
    _check_existing_skus(env, data)
    categories, unique_category = _create_categories(env, data)
    attributes, values = _create_attributes_and_values(env, data)
    structured_templates = _create_templates(
        env, data, categories, attributes, values
    )
    unique_templates = _create_unique_items(env, data, unique_category)
    created_products = (
        structured_templates.product_variant_ids
        | unique_templates.product_variant_ids
    )
    expected_count = data["metadata"]["total_products"]
    if len(created_products) != expected_count:
        raise UserError(
            f"נוצרו {len(created_products)} פריטים במקום {expected_count}."
        )
    if len(set(created_products.mapped("default_code"))) != expected_count:
        raise UserError("נוצרו מק״טים כפולים בקטלוג.")
    _logger.info(
        "MDL catalog loaded: %s templates, %s products",
        len(structured_templates) + len(unique_templates),
        len(created_products),
    )
    return {
        "status": "imported",
        "templates": len(structured_templates) + len(unique_templates),
        "products": len(created_products),
    }


def run_from_odoo_shell(env, mode="check"):
    """Run transactionally; check mode always rolls back."""
    if mode not in {"check", "apply"}:
        raise UserError(
            "MDL_CATALOG_MODE חייב להיות check או apply."
        )
    try:
        result = import_catalog(env)
        if mode == "apply":
            env.cr.commit()
            _logger.info("MDL catalog import committed: %s", result)
        else:
            env.cr.rollback()
            _logger.info(
                "MDL catalog check passed and was rolled back: %s",
                result,
            )
        print(json.dumps(result, ensure_ascii=False))
        return result
    except Exception:
        env.cr.rollback()
        _logger.exception("MDL catalog import failed; transaction rolled back")
        raise


if "env" in globals():
    run_from_odoo_shell(
        env,
        mode=os.environ.get("MDL_CATALOG_MODE", "check").strip().lower(),
    )
