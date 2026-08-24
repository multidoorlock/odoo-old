from odoo import SUPERUSER_ID, api

from odoo.addons.mdl_product_catalog_test_data.hooks import (
    MODULE,
    _xmlid_name,
    post_init_hook,
)


def migrate(cr, version):
    """Replace the generated test catalog with the normalized model structure.

    This module is explicitly test data.  Existing generated products are
    archived (not deleted, so quotation references remain valid), their old
    internal references are released, and a clean normalized catalog is loaded.
    No production or manually created product is selected by this migration.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    xmlids = env["ir.model.data"].search([("module", "=", MODULE)])

    template_xmlids = xmlids.filtered(
        lambda item: item.model == "product.template"
    )
    templates = env["product.template"].with_context(active_test=False).browse(
        template_xmlids.mapped("res_id")
    ).exists()
    products = templates.with_context(active_test=False).product_variant_ids
    for product in products:
        old_code = product.default_code
        product.with_context(skip_mdl_catalog_sync=True).write(
            {
                "active": False,
                "default_code": (
                    f"ARCHIVE-{product.id}-{old_code}" if old_code else False
                ),
            }
        )
    for template in templates:
        template.with_context(skip_mdl_catalog_sync=True).write(
            {
                "active": False,
                "name": f"ארכיון — {template.name}",
            }
        )

    attribute_xmlids = xmlids.filtered(
        lambda item: item.model == "product.attribute"
    )
    attributes = env["product.attribute"].browse(
        attribute_xmlids.mapped("res_id")
    ).exists()
    if "active" in attributes._fields:
        attributes.write({"active": False})

    root_xmlid = xmlids.filtered(
        lambda item: item.model == "product.category"
        and item.name == _xmlid_name("category", "test_root")
    )[:1]
    if root_xmlid:
        root = env["product.category"].browse(root_xmlid.res_id).exists()
        if root:
            root.name = f"ארכיון — {root.name}"

    # Free the deterministic XML IDs before the clean catalog is recreated.
    xmlids.unlink()
    env.flush_all()
    env.invalidate_all()
    post_init_hook(env)
