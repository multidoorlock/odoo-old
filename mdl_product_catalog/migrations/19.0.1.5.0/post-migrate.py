from odoo import SUPERUSER_ID, api


OLD_DEFAULT = "מק״ט [מק״ט] — [שם הפריט]"
NEW_DEFAULT = "[מק״ט] [שם הפריט]"
PARAM = "mdl_product_catalog.variant_display_format"


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    parameters = env["ir.config_parameter"].sudo()
    current = parameters.get_param(PARAM)
    if not current or current == OLD_DEFAULT:
        parameters.set_param(PARAM, NEW_DEFAULT)
