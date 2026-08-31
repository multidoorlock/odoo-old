from odoo import api, fields, models
from odoo.exceptions import ValidationError

# Mapping between the weekend boolean fields and python's date.weekday()
# numbering (Monday = 0 ... Sunday = 6), which matches Odoo's dayofweek codes.
MDL_WEEKEND_FIELD_TO_WEEKDAY = {
    'mdl_weekend_monday': 0,
    'mdl_weekend_tuesday': 1,
    'mdl_weekend_wednesday': 2,
    'mdl_weekend_thursday': 3,
    'mdl_weekend_friday': 4,
    'mdl_weekend_saturday': 5,
    'mdl_weekend_sunday': 6,
}


class ResCompany(models.Model):
    _inherit = 'res.company'

    # --- ימי סוף שבוע (סעיף 20 באפיון) ---
    mdl_weekend_sunday = fields.Boolean(string='ראשון')
    mdl_weekend_monday = fields.Boolean(string='שני')
    mdl_weekend_tuesday = fields.Boolean(string='שלישי')
    mdl_weekend_wednesday = fields.Boolean(string='רביעי')
    mdl_weekend_thursday = fields.Boolean(string='חמישי')
    mdl_weekend_friday = fields.Boolean(string='שישי', default=True)
    mdl_weekend_saturday = fields.Boolean(string='שבת', default=True)

    # --- הגדרות משמרות ברמת החברה (סעיף 9 באפיון) ---
    mdl_shift_morning_start = fields.Float(string='תחילת משמרת בוקר', default=6.5)
    mdl_shift_morning_end = fields.Float(string='סיום משמרת בוקר', default=16.0)
    mdl_shift_evening_start = fields.Float(string='תחילת משמרת ערב', default=16.0)
    mdl_shift_evening_end = fields.Float(string='סיום משמרת ערב בתשלום', default=1.5)
    mdl_shift_sleep_start = fields.Float(string='תחילת שינה', default=1.5)
    mdl_shift_sleep_end = fields.Float(string='סיום שינה', default=6.5)
    mdl_shift_paid_hours = fields.Float(string='שעות משמרת בתשלום', default=9.5)
    mdl_shift_sleep_hours = fields.Float(string='שעות שינה', default=5.0)
    mdl_shift_cutoff = fields.Float(
        string='שעת חיתוך לזיהוי משמרת', default=13.0,
        help='כניסה לפני שעה זו מסווגת כמשמרת בוקר, החל משעה זו — משמרת ערב.')

    def _mdl_weekend_weekdays(self):
        """Return the set of python weekday numbers configured as weekend."""
        self.ensure_one()
        return {
            weekday for field_name, weekday in MDL_WEEKEND_FIELD_TO_WEEKDAY.items()
            if self[field_name]
        }

    @api.constrains('mdl_shift_paid_hours', 'mdl_shift_sleep_hours', 'mdl_shift_cutoff')
    def _check_mdl_shift_settings(self):
        for company in self:
            if company.mdl_shift_paid_hours <= 0:
                raise ValidationError('שעות משמרת בתשלום חייבות להיות גדולות מאפס.')
            if company.mdl_shift_sleep_hours < 0:
                raise ValidationError('שעות שינה אינן יכולות להיות שליליות.')
            if not 0.0 <= company.mdl_shift_cutoff < 24.0:
                raise ValidationError('שעת החיתוך לזיהוי משמרת חייבת להיות בין 0 ל־24.')
