from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    products = env["product.product"].search(
        [("product_tmpl_id.mdl_sku_prefix", "!=", False)]
    )
    products._compute_mdl_catalog_values()
    products._mdl_sync_default_code()
