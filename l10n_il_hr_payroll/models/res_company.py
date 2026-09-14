from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ResCompany(models.Model):
    _inherit = 'res.company'

    mdl_additional_day_work_entry_type_id = fields.Many2one(
        'hr.work.entry.type', string='סוג עבודה ליום נוסף',
        default=lambda self: self.env.ref(
            'l10n_il_hr_payroll.work_entry_type_additional_day',
            raise_if_not_found=False),
        help='שעות בסוג עבודה זה יחושבו בתלוש לפי תעריף יום נוסף של העובד, '
             'בהתאם לשעות העבודה ולסוג השכר (ברוטו או נטו).')

    def _mdl_additional_day_type(self):
        self.ensure_one()
        return (self.mdl_additional_day_work_entry_type_id
                or self.env.ref('l10n_il_hr_payroll.work_entry_type_additional_day'))

    @api.constrains('mdl_additional_day_work_entry_type_id')
    def _check_mdl_additional_day_work_entry_type(self):
        for company in self:
            entry_type = company.mdl_additional_day_work_entry_type_id
            if entry_type and (entry_type.is_leave or not entry_type.is_extra_hours):
                raise ValidationError(
                    'סוג העבודה ליום נוסף חייב להיות סוג שעות נוספות שאינו היעדרות.')

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
