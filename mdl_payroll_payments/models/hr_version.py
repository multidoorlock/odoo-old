# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError

# ענפי משק (מוצג לעובד פלסטיני / זר בלבד)
IL_EMPLOYMENT_SECTORS = [
    ('construction', 'בניין'),
    ('industry', 'תעשייה'),
    ('agriculture', 'חקלאות'),
    ('hospitality', 'מלונאות'),
    ('trade_services', 'מסחר ושירותים'),
    ('restaurants', 'מסעדות'),
    ('nursing', 'סיעוד'),
    ('other', 'אחר'),
]


class HrVersion(models.Model):
    _inherit = 'hr.version'

    # ------------------------------------------------------------------
    # פרטים אישיים (סעיף "פרטים אישיים" באפיון חלק ב')
    # ------------------------------------------------------------------
    il_employee_type = fields.Selection([
        ('israeli', 'ישראלי'),
        ('palestinian', 'פלסטיני'),
        ('foreign', 'עובד זר'),
    ], string='סוג עובד בישראל', default='israeli', tracking=True)
    il_tax_credit_points = fields.Float(string='נקודות זיכוי במס', digits=(6, 2))
    il_primary_employer = fields.Boolean(string='מעסיק עיקרי לתשלומי שכר', default=True)
    il_tax_coordination = fields.Boolean(string='יש תיאום מס')
    il_tax_coordination_valid_from = fields.Date(string='תוקף תיאום מס מ-')
    il_tax_coordination_valid_until = fields.Date(string='תוקף תיאום מס עד-')

    # ------------------------------------------------------------------
    # הפרשות סוציאליות (תנאי עבודה)
    # ------------------------------------------------------------------
    il_pension_enabled = fields.Boolean(string='פנסיה')
    il_pension_start_date = fields.Date(string='תאריך תחילת הפרשות לפנסיה')
    il_employee_pension_rate = fields.Float(string='הפרשת עובד לפנסיה (%)', digits=(6, 2))
    il_employer_pension_rate = fields.Float(string='הפרשת מעסיק לפנסיה (%)', digits=(6, 2))
    il_severance_rate = fields.Float(string='הפרשה לפיצויים (%)', digits=(6, 2))

    il_study_fund_enabled = fields.Boolean(string='קרן השתלמות פעילה')
    il_employee_study_fund_rate = fields.Float(string='הפרשת עובד לקרן השתלמות (%)', digits=(6, 2))
    il_employer_study_fund_rate = fields.Float(string='הפרשת מעסיק לקרן השתלמות (%)', digits=(6, 2))

    il_employment_sector = fields.Selection(
        IL_EMPLOYMENT_SECTORS, string='ענף העסקה')

    # הפעלת מס ארגון לעובד פלסטיני (בהתאם להסדר החל על מקום העבודה).
    il_pal_organization_tax = fields.Boolean(string='חל מס ארגון')
    # פיקדון עובד זר — פעיל מתאריך תחילת ההסדר; כשהוא פעיל הוא מחליף את
    # הפרשות הפנסיה/פיצויים של המעסיק (ראו חוקי השכר).
    il_for_deposit_start_date = fields.Date(string='תאריך תחילת הסדר פיקדון')

    @api.constrains('il_tax_coordination', 'il_tax_coordination_valid_from',
                    'il_tax_coordination_valid_until')
    def _check_il_tax_coordination(self):
        for version in self:
            if not version.il_tax_coordination:
                continue
            if (version.il_tax_coordination_valid_from
                    and version.il_tax_coordination_valid_until
                    and version.il_tax_coordination_valid_from > version.il_tax_coordination_valid_until):
                raise ValidationError('תוקף תיאום המס: תאריך הסיום קודם לתאריך ההתחלה.')

    @api.constrains('il_pension_enabled', 'il_employee_pension_rate',
                    'il_employer_pension_rate', 'il_severance_rate')
    def _check_il_pension_rates(self):
        for version in self:
            if not version.il_pension_enabled:
                continue
            for rate in (version.il_employee_pension_rate,
                         version.il_employer_pension_rate,
                         version.il_severance_rate):
                if rate < 0 or rate > 100:
                    raise ValidationError('שיעורי ההפרשה לפנסיה חייבים להיות בין 0 ל-100 אחוזים.')

    @api.constrains('il_study_fund_enabled', 'il_employee_study_fund_rate',
                    'il_employer_study_fund_rate')
    def _check_il_study_fund_rates(self):
        for version in self:
            if not version.il_study_fund_enabled:
                continue
            for rate in (version.il_employee_study_fund_rate,
                         version.il_employer_study_fund_rate):
                if rate < 0 or rate > 100:
                    raise ValidationError('שיעורי ההפרשה לקרן השתלמות חייבים להיות בין 0 ל-100 אחוזים.')

    @api.model
    def _get_whitelist_fields_from_template(self):
        return super()._get_whitelist_fields_from_template() + [
            'il_employee_type', 'il_tax_credit_points', 'il_primary_employer',
            'il_tax_coordination', 'il_tax_coordination_valid_from',
            'il_tax_coordination_valid_until',
            'il_pension_enabled', 'il_pension_start_date',
            'il_employee_pension_rate', 'il_employer_pension_rate', 'il_severance_rate',
            'il_study_fund_enabled', 'il_employee_study_fund_rate',
            'il_employer_study_fund_rate', 'il_employment_sector',
            'il_pal_organization_tax', 'il_for_deposit_start_date',
        ]
