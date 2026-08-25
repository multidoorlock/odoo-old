from odoo import SUPERUSER_ID, api
from odoo.addons.mdl_product_catalog.models.catalog_utils import (
    clean_text,
    normalize_token,
    split_legacy_name_format,
)


def _column_exists(cr, table_name, column_name):
    cr.execute(
        """
        SELECT EXISTS (
            SELECT 1
              FROM information_schema.columns
             WHERE table_name = %s
               AND column_name = %s
        )
        """,
        (table_name, column_name),
    )
    return cr.fetchone()[0]


def _without_group(group_name, model_name):
    group_name = clean_text(group_name)
    model_name = clean_text(model_name)
    prefix = f"{group_name} " if group_name else ""
    return model_name[len(prefix):] if prefix and model_name.startswith(prefix) else model_name


def migrate(cr, version):
    if not _column_exists(cr, "product_template", "mdl_name_format"):
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    cr.execute(
        """
        SELECT id,
               COALESCE(mdl_name_format, ''),
               COALESCE(mdl_group_name_component, ''),
               COALESCE(mdl_model_name_component, ''),
               COALESCE(mdl_suppress_model_name, FALSE)
          FROM product_template
         WHERE COALESCE(mdl_sku_prefix, '') <> ''
        """
    )
    migrated = env["product.template"]
    for template_id, old_format, group_text, model_text, suppress_model in cr.fetchall():
        template = env["product.template"].browse(template_id).exists()
        if not template:
            continue
        group_name = clean_text(group_text or template.categ_id.name)
        model_name = clean_text(
            model_text or _without_group(group_name, template.name)
        )
        base_name = clean_text(
            " ".join(
                part
                for part in (group_name, "" if suppress_model else model_name)
                if part
            )
        )
        line_names = template.attribute_line_ids.attribute_id.mapped("name")
        rules, final_suffix = split_legacy_name_format(old_format, line_names)
        template_updates = {
            "mdl_name_suffix": final_suffix or False,
        }
        if base_name and base_name != clean_text(template.name):
            template_updates["mdl_variant_base_name"] = base_name
        template.with_context(skip_mdl_catalog_sync=True).write(template_updates)
        for line in template.attribute_line_ids:
            rule = rules.get(normalize_token(line.attribute_id.name))
            if not rule:
                continue
            line.with_context(skip_mdl_catalog_sync=True).write(
                {
                    "mdl_name_mode": rule["name_mode"],
                    "mdl_name_prefix": rule["prefix"],
                    "mdl_name_suffix": rule["suffix"],
                }
            )
        migrated |= template

    migrated._mdl_ensure_full_model_names()
    migrated._mdl_sync_variant_codes()
