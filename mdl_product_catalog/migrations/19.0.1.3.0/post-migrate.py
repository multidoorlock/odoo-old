from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    templates = env["product.template"].search(
        [("mdl_sku_prefix", "!=", False)]
    )
    templates._mdl_ensure_full_model_names()
