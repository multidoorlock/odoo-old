from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Refresh every managed final name and SKU after the display fix."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    templates = (
        env["product.template"]
        .sudo()
        .with_context(active_test=False)
        .search([("mdl_catalog_managed", "=", True)])
    )
    templates._mdl_sync_variant_codes()

