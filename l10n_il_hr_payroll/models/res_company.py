from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ResCompany(models.Model):
    _inherit = 'res.company'

    # Shift duration is the paid, normalized duration. Sleep/break time is
    # derived exclusively from non-work attendance segments.
    mdl_shift_morning_hours = fields.Float(string='משך משמרת בוקר', default=9.5)
    mdl_shift_evening_hours = fields.Float(string='משך משמרת ערב', default=9.5)
    mdl_shift_cutoff = fields.Float(
        string='שעת חיתוך לזיהוי משמרת', default=13.0,
        help='כניסה לפני שעה זו מסווגת כמשמרת בוקר, החל משעה זו — משמרת ערב.')

    @api.constrains(
        'mdl_shift_morning_hours', 'mdl_shift_evening_hours', 'mdl_shift_cutoff')
    def _check_mdl_shift_settings(self):
        for company in self:
            if company.mdl_shift_morning_hours <= 0:
                raise ValidationError('משך משמרת בוקר חייב להיות גדול מאפס.')
            if company.mdl_shift_evening_hours <= 0:
                raise ValidationError('משך משמרת ערב חייב להיות גדול מאפס.')
            if not 0.0 <= company.mdl_shift_cutoff < 24.0:
                raise ValidationError('שעת החיתוך לזיהוי משמרת חייבת להיות בין 0 ל־24.')
