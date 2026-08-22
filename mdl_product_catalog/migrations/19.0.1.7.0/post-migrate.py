from odoo import SUPERUSER_ID, api

from odoo.addons.mdl_product_catalog.models.catalog_utils import clean_text


def _without_group(group_name, model_name):
    group_name = clean_text(group_name)
    model_name = clean_text(model_name)
    prefix = f"{group_name} " if group_name else ""
    if prefix and model_name.startswith(prefix):
        return model_name[len(prefix):]
    return "" if model_name == group_name else model_name


def _base_overrides(template, desired_base):
    desired_base = clean_text(desired_base)
    group_name = clean_text(template.categ_id.name)
    model_name = _without_group(group_name, template.name)
    default_base = clean_text(f"{group_name} {model_name}")
    if desired_base == default_base:
        return False, False
    if desired_base == group_name:
        return False, "—"
    if group_name and desired_base.startswith(f"{group_name} "):
        return False, clean_text(desired_base[len(group_name):]) or "—"
    if model_name and desired_base.endswith(f" {model_name}"):
        group_override = clean_text(desired_base[: -len(model_name)])
        return group_override or "—", False
    if not desired_base:
        return "—", "—"
    # Preserve an unusual legacy base exactly. It remains editable in the two
    # new override fields even when it cannot be split safely automatically.
    return desired_base, "—"


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    templates = env["product.template"].with_context(
        active_test=False,
        skip_mdl_catalog_sync=True,
    ).search([("mdl_sku_prefix", "!=", False)])

    for template in templates:
        desired_base = clean_text(template.mdl_variant_base_name or template.name)
        displayed_lines = template.attribute_line_ids.filtered(
            lambda line: line.active and line.mdl_name_mode != "hidden"
        ).sorted(lambda line: (line.sequence, line.attribute_id.sequence, line.id))

        if displayed_lines:
            first_prefix = clean_text(displayed_lines[0].mdl_name_prefix)
            if first_prefix:
                desired_base = clean_text(f"{desired_base} {first_prefix}")

            previous_line = False
            for line in displayed_lines:
                raw_prefix = line.mdl_name_prefix or ""
                if previous_line and raw_prefix:
                    previous_line.mdl_name_suffix = (
                        (previous_line.mdl_name_suffix or "") + raw_prefix
                    )
                line.mdl_name_prefix = False
                previous_line = line

            if template.mdl_name_suffix:
                displayed_lines[-1].mdl_name_suffix = (
                    (displayed_lines[-1].mdl_name_suffix or "")
                    + template.mdl_name_suffix
                )

        group_override, model_override = _base_overrides(template, desired_base)
        template.write(
            {
                "mdl_group_name_override": group_override,
                "mdl_model_name_override": model_override,
                "mdl_variant_base_name": False,
                "mdl_name_suffix": False,
            }
        )

    templates._compute_mdl_sku_prefix()
    templates._compute_mdl_effective_base_name()
    templates._mdl_ensure_full_model_names()
    templates.with_context(skip_mdl_catalog_sync=False)._mdl_sync_variant_codes()

    products = templates.product_variant_ids
    products._compute_mdl_catalog_values()
    products._mdl_sync_default_code()
