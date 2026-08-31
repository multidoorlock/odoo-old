from odoo import fields, models


class HrWorkEntry(models.Model):
    _inherit = 'hr.work.entry'

    # שדות ביקורת (סעיף 19 באפיון). הרשומה עצמה נשמרת ברמת תאריך עסקי + משך,
    # ולכן mdl_work_date הוא שדה תצוגה של תאריך הרשומה.
    mdl_work_date = fields.Date(related='date', string='תאריך עסקי')
    mdl_actual_hours = fields.Float(string='שעות בפועל', readonly=True)
    mdl_normalized_hours = fields.Float(string='שעות מנורמלות', readonly=True)
    mdl_rate_category = fields.Selection([
        ('regular', 'רגיל'),
        ('additional_day', 'יום נוסף'),
        ('weekend', 'סוף שבוע'),
    ], string='קטגוריית תעריף', readonly=True)
    mdl_shift_type = fields.Selection([
        ('none', 'ללא משמרת'),
        ('morning', 'בוקר'),
        ('evening', 'ערב'),
    ], string='סוג משמרת', default='none', readonly=True)
    mdl_rounding_reason = fields.Selection([
        ('half_day', 'חצי יום'),
        ('full_day', 'יום מלא'),
        ('shift', 'משמרת'),
        ('overtime_threshold', 'סף שעות נוספות'),
        ('sleep', 'שינה'),
    ], string='סיבת עיגול', readonly=True)
    mdl_source_attendance_ids = fields.Many2many(
        'hr.attendance', 'mdl_work_entry_attendance_rel',
        'work_entry_id', 'attendance_id', string='החתמות מקור', readonly=True)
