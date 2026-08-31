from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    mdl_shift_morning_hours = fields.Float(
        related='company_id.mdl_shift_morning_hours', readonly=False)
    mdl_shift_evening_hours = fields.Float(
        related='company_id.mdl_shift_evening_hours', readonly=False)
    mdl_shift_cutoff = fields.Float(related='company_id.mdl_shift_cutoff', readonly=False)
