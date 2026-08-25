from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Collapse duplicate local exclusions that describe the same pair."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    exclusions = env["product.template.attribute.exclusion"].search([])
    exclusions._mdl_merge_duplicate_pairs()
