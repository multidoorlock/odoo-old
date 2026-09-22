# -*- coding: utf-8 -*-
from odoo import fields, models


class HrPayslipInput(models.Model):
    _inherit = 'hr.payslip.input'

    # קישור להתאמת השכר שיצרה את השורה — כל התאמה מיוצגת בשורת קלט נפרדת
    # (אין איחוד לפי סוג), כדי שגילום נטו פרטני יישאר אפשרי.
    il_salary_attachment_id = fields.Many2one(
        'hr.salary.attachment', string='התאמת שכר', index=True, ondelete='set null')

    # Snapshot שהועבר מההתאמה בזמן בניית התלוש — החישוב אינו מסתמך על
    # תצורה עתידית של סוג הקלט.
    il_effect_type = fields.Selection([
        ('gross', 'ברוטו'),
        ('net', 'נטו'),
        ('taxable_benefit', 'שווי חייב (לא משולם)'),
    ], string='סוג השפעה')
    il_adjustment_direction = fields.Selection([
        ('positive', 'חיובי'),
        ('negative', 'שלילי'),
    ], string='כיוון ההתאמה')
    il_net_adjustment_treatment = fields.Selection([
        ('gross_up', 'גילום נטו'),
        ('direct_net', 'השפעה ישירה על הנטו'),
    ], string='אופן הטיפול בנטו')
    il_income_taxable = fields.Boolean(string='חייב במס הכנסה')
    il_national_insurance_applicable = fields.Boolean(string='חייב בביטוח לאומי')
    il_pensionable = fields.Boolean(string='נכלל בשכר לפנסיה')
    il_severance_applicable = fields.Boolean(string='נכלל בשכר לפיצויים')
    il_study_fund_applicable = fields.Boolean(string='נכלל בבסיס קרן השתלמות')
    il_equalization_levy_applicable = fields.Boolean(string='נכלל בבסיס היטל השוואה')
    il_ni_payment_treatment = fields.Selection([
        ('regular', 'תשלום רגיל'),
        ('additional_payment', 'תשלום נוסף'),
        ('none', 'ללא'),
    ], string='סיווג לביטוח לאומי')

    # הסכום המקורי שהוזן בהתאמה. בשורת גילום נטו שדה amount מחזיק את
    # שווי הברוטו שחושב על ידי מנוע הגילום, וכאן נשמר הנטו המקורי.
    il_original_amount = fields.Float(string='סכום מקורי', digits='Payroll Rate')

    def _il_is_gross_up(self):
        self.ensure_one()
        return self.il_effect_type == 'net'

    def _il_signed_amount(self):
        """Effective signed amount for rule computation (+/- per direction)."""
        self.ensure_one()
        sign = -1 if self.il_adjustment_direction == 'negative' else 1
        return sign * self.amount
