from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Expose every local native exclusion as one two-value catalog row."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    exclusions = env["product.template.attribute.exclusion"].search([])
    normalized = exclusions._mdl_expand_native_rules()
    normalized._mdl_merge_duplicate_pairs()
