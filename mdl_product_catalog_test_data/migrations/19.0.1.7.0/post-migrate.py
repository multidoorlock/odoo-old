from odoo import SUPERUSER_ID, api

from odoo.addons.mdl_product_catalog_test_data.hooks import (
    MODULE,
    _xmlid_name,
    post_init_hook,
)


def migrate(cr, version):
    """Rebuild the generated test catalog with the logical product layout."""
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

    fallback_category = env.ref(
        "product.product_category_all", raise_if_not_found=False
    )
    for template in templates:
        values = {
            "active": False,
            "name": f"ארכיון — {template.name}",
        }
        if fallback_category:
            values["categ_id"] = fallback_category.id
        template.with_context(skip_mdl_catalog_sync=True).write(values)

    attribute_xmlids = xmlids.filtered(
        lambda item: item.model == "product.attribute"
    )
    attributes = env["product.attribute"].browse(
        attribute_xmlids.mapped("res_id")
    ).exists()
    if "active" in attributes._fields:
        attributes.write({"active": False})

    category_xmlids = xmlids.filtered(
        lambda item: item.model == "product.category"
    )
    categories = env["product.category"].browse(
        category_xmlids.mapped("res_id")
    ).exists()
    for category in categories.sorted(
        key=lambda item: len(item.parent_path or ""), reverse=True
    ):
        if not env["product.template"].with_context(active_test=False).search_count(
            [("categ_id", "child_of", category.id)]
        ):
            category.unlink()

    root_xmlid = xmlids.filtered(
        lambda item: item.model == "product.category"
        and item.name == _xmlid_name("category", "test_root")
    )[:1]
    if root_xmlid:
        root = env["product.category"].browse(root_xmlid.res_id).exists()
        if root and not env["product.category"].search_count(
            [("parent_id", "=", root.id)]
        ):
            root.unlink()

    xmlids.exists().unlink()
    env.flush_all()
    env.invalidate_all()
    post_init_hook(env)

