from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['hr.employee.section.14'].sudo()._ensure_section_14_assets()
