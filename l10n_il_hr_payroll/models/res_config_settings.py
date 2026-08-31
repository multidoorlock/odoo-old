from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    mdl_weekend_sunday = fields.Boolean(related='company_id.mdl_weekend_sunday', readonly=False)
    mdl_weekend_monday = fields.Boolean(related='company_id.mdl_weekend_monday', readonly=False)
    mdl_weekend_tuesday = fields.Boolean(related='company_id.mdl_weekend_tuesday', readonly=False)
    mdl_weekend_wednesday = fields.Boolean(related='company_id.mdl_weekend_wednesday', readonly=False)
    mdl_weekend_thursday = fields.Boolean(related='company_id.mdl_weekend_thursday', readonly=False)
    mdl_weekend_friday = fields.Boolean(related='company_id.mdl_weekend_friday', readonly=False)
    mdl_weekend_saturday = fields.Boolean(related='company_id.mdl_weekend_saturday', readonly=False)

    mdl_shift_morning_start = fields.Float(related='company_id.mdl_shift_morning_start', readonly=False)
    mdl_shift_morning_end = fields.Float(related='company_id.mdl_shift_morning_end', readonly=False)
    mdl_shift_evening_start = fields.Float(related='company_id.mdl_shift_evening_start', readonly=False)
    mdl_shift_evening_end = fields.Float(related='company_id.mdl_shift_evening_end', readonly=False)
    mdl_shift_sleep_start = fields.Float(related='company_id.mdl_shift_sleep_start', readonly=False)
    mdl_shift_sleep_end = fields.Float(related='company_id.mdl_shift_sleep_end', readonly=False)
    mdl_shift_paid_hours = fields.Float(related='company_id.mdl_shift_paid_hours', readonly=False)
    mdl_shift_sleep_hours = fields.Float(related='company_id.mdl_shift_sleep_hours', readonly=False)
    mdl_shift_cutoff = fields.Float(related='company_id.mdl_shift_cutoff', readonly=False)
