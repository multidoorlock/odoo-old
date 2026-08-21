import hashlib
import json
import logging
from collections import defaultdict
from pathlib import Path

from odoo import Command
from odoo.exceptions import UserError


_logger = logging.getLogger(__name__)
MODULE = "mdl_product_catalog_test_data"
DATA_FILE = Path(__file__).parent / "data" / "catalog.json"


def _clean(value):
    return " ".join(str(value or "").split())


def _xmlid_name(prefix, key):
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def _register_xmlid(env, prefix, key, record):
    env["ir.model.data"].create(
        {
            "module": MODULE,
            "name": _xmlid_name(prefix, key),
            "model": record._name,
            "res_id": record.id,
            "noupdate": True,
        }
    )


def _load_source():
    with DATA_FILE.open("r", encoding="utf-8") as source_file:
        return json.load(source_file)


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
            "לא ניתן להתקין את נתוני הבדיקה: קיימים כבר פריטים עם מק״טים "
            f"מהקובץ ({examples}). יש לבצע את הבדיקה במסד נתוני בדיקות נקי."
        )


def _create_categories(env, data):
    Category = env["product.category"]
    parent = Category.create({"name": "בדיקת קטלוג MasterProducts"})
    _register_xmlid(env, "category", "test_root", parent)
    result = {}
    for item in data["groups"]:
        category = Category.create(
            {
                "name": item["name"],
                "parent_id": parent.id,
                "mdl_group_code": item["code"],
            }
        )
        _register_xmlid(env, "category", item["key"], category)
        result[item["key"]] = category
    unique_category = Category.create(
        {"name": "פריטים ייחודיים", "parent_id": parent.id}
    )
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
                "mdl_sku_component": item["sku_component"] or False,
                "mdl_name_component": item["name_component"] or False,
            }
        )
        _register_xmlid(env, "attribute_value", item["key"], value)
        values[item["key"]] = value
    return attributes, values


def _create_exclusions(env, template, template_data, values):
    if not template_data["forbidden_pairs"]:
        return
    template_values = {
        item.product_attribute_value_id.id: item
        for item in template.mdl_template_value_ids
    }
    excluded_by_source = defaultdict(set)
    for pair in template_data["forbidden_pairs"]:
        source = template_values[values[pair["value_key"]].id]
        excluded = template_values[values[pair["excluded_value_key"]].id]
        excluded_by_source[source.id].add(excluded.id)
    env["product.template.attribute.exclusion"].create(
        [
            {
                "product_tmpl_id": template.id,
                "product_template_attribute_value_id": source_id,
                "value_ids": [Command.set(sorted(excluded_ids))],
            }
            for source_id, excluded_ids in excluded_by_source.items()
        ]
    )


def _validate_and_register_variants(env, template, template_data, values):
    template._create_variant_ids()
    env.flush_all()
    env.invalidate_all()
    template = env["product.template"].browse(template.id)
    template._mdl_sync_variant_codes()
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
    if expected_by_tuple.keys() != actual_by_tuple.keys():
        raise UserError(
            "נתוני הבדיקה אינם מייצרים את אותם שילובים בדגם "
            f"{template_data['key']}: צפויים {len(expected_by_tuple)}, "
            f"נוצרו {len(actual_by_tuple)}."
        )
    for value_tuple, expected in expected_by_tuple.items():
        product = actual_by_tuple[value_tuple]
        actual_sku = _clean(product.mdl_generated_sku)
        actual_name = _clean(product.mdl_generated_name)
        if actual_sku != expected["sku"] or actual_name != _clean(expected["name"]):
            raise UserError(
                "אי־התאמה בנתוני הבדיקה עבור "
                f"{expected['sku']}: התקבל {actual_sku} - {actual_name}."
            )
        if product.default_code != expected["sku"]:
            raise UserError(
                f"המק״ט {expected['sku']} חושב אך לא נשמר בפריט."
            )


def _create_templates(env, data, categories, attributes, values):
    Template = env["product.template"].with_context(skip_mdl_catalog_sync=True)
    templates = []
    for item in data["templates"]:
        lines = []
        for line in item["attribute_lines"]:
            lines.append(
                Command.create(
                    {
                        "attribute_id": attributes[line["attribute_key"]].id,
                        "sequence": line["sequence"],
                        "value_ids": [
                            Command.set(
                                [values[value["value_key"]].id for value in line["values"]]
                            )
                        ],
                    }
                )
            )
        template = Template.create(
            {
                "name": item["name"],
                "categ_id": categories[item["group_key"]].id,
                "mdl_model_code": item["model_code"] or False,
                "mdl_name_format": item["name_format"],
                "mdl_group_name_component": item["group_name_component"] or False,
                "mdl_model_name_component": item["model_name_component"] or False,
                "mdl_suppress_model_name": item["suppress_model_name"],
                "attribute_line_ids": lines,
            }
        )
        _register_xmlid(env, "template", item["key"], template)
        _create_exclusions(env, template, item, values)
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


def post_init_hook(env):
    data = _load_source()
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
        raise UserError("נוצרו מק״טים כפולים בנתוני הבדיקה.")
    _logger.info(
        "MDL test catalog loaded: %s templates, %s products",
        len(structured_templates) + len(unique_templates),
        len(created_products),
    )
