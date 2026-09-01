from odoo import SUPERUSER_ID, api

from odoo.addons.mdl_product_groups_attributes.hooks import (
    migrate_catalog_structure,
)


def migrate(cr, version):
    """Run the same idempotent conversion used by a first-time install."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    migrate_catalog_structure(env)
