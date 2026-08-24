from odoo import Command, SUPERUSER_ID, api

from odoo.addons.mdl_product_catalog_test_data.hooks import (
    MODULE,
    _load_source,
    _xmlid_name,
)


def _record(env, prefix, key):
    return env.ref(
        f"{MODULE}.{_xmlid_name(prefix, key)}",
        raise_if_not_found=False,
    )


def migrate(cr, version):
    """Restore generated pair exclusions without rebuilding the catalog."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    Exclusion = env["product.template.attribute.exclusion"]
    data = _load_source()

    for template_data in data["templates"]:
        pairs = template_data.get("forbidden_pairs", [])
        if not pairs:
            continue
        template = _record(env, "template", template_data["key"])
        if not template:
            continue

        template_values = {
            value.product_attribute_value_id.id: value
            for value in template.mdl_attribute_value_ids
        }
        desired_by_source = {}
        for pair in pairs:
            source_value = _record(
                env, "attribute_value", pair["value_key"]
            )
            excluded_value = _record(
                env, "attribute_value", pair["excluded_value_key"]
            )
            if not source_value or not excluded_value:
                continue
            source = template_values.get(source_value.id)
            excluded = template_values.get(excluded_value.id)
            if not source or not excluded:
                continue
            desired_by_source.setdefault(source.id, set()).add(excluded.id)

        for source_id, excluded_ids in desired_by_source.items():
            rules = Exclusion.search(
                [
                    (
                        "product_template_attribute_value_id",
                        "=",
                        source_id,
                    ),
                    ("product_tmpl_id", "=", template.id),
                ]
            )
            values = {"value_ids": [Command.set(sorted(excluded_ids))]}
            if rules:
                rules[:1].write(values)
                rules[1:].unlink()
            else:
                Exclusion.create(
                    {
                        "product_template_attribute_value_id": source_id,
                        "product_tmpl_id": template.id,
                        **values,
                    }
                )
