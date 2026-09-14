from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    mdl_additional_day_work_entry_type_id = fields.Many2one(
        related='company_id.mdl_additional_day_work_entry_type_id',
        readonly=False)

    mdl_shift_morning_hours = fields.Float(
        related='company_id.mdl_shift_morning_hours', readonly=False)
    mdl_shift_evening_hours = fields.Float(
        related='company_id.mdl_shift_evening_hours', readonly=False)
    mdl_shift_cutoff = fields.Float(related='company_id.mdl_shift_cutoff', readonly=False)
