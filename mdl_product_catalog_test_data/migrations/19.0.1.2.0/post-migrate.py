from odoo import SUPERUSER_ID, api

from odoo.addons.mdl_product_catalog.models.product_template import (
    _name_with_group,
)
from odoo.addons.mdl_product_catalog_test_data.hooks import (
    MODULE,
    _clean,
    _load_source,
    _xmlid_name,
)


def migrate(cr, version):
    """Move legacy descriptive model names back to their real source values."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    updated_ids = []
    for item in _load_source()["templates"]:
        template = env.ref(
            f"{MODULE}.{_xmlid_name('template', item['key'])}",
            raise_if_not_found=False,
        )
        if not template:
            continue

        source_model_name = _clean(
            item["model_name_component"] or item["name"]
        )
        current_effective_name = _clean(template.mdl_model_name_value)
        if item["suppress_model_name"]:
            model_override = "—"
        elif current_effective_name == source_model_name:
            model_override = False
        else:
            model_override = current_effective_name or False

        template.with_context(skip_mdl_catalog_sync=True).write(
            {
                "name": _name_with_group(
                    template.categ_id.name,
                    source_model_name,
                ),
                "mdl_model_name_override": model_override,
            }
        )
        updated_ids.append(template.id)

    env.flush_all()
    env.invalidate_all()
    templates = env["product.template"].browse(updated_ids).exists()
    templates.with_context(skip_mdl_catalog_sync=False)._mdl_sync_variant_codes()
