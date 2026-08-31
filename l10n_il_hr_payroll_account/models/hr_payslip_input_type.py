# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class HrPayslipInputType(models.Model):
    _inherit = 'hr.payslip.input.type'

    # ------------------------------------------------------------------
    # התנהגות התאמות שכר (רלוונטי כאשר Available in Adjustments)
    # ------------------------------------------------------------------
    il_adjustment_direction = fields.Selection([
        ('positive', 'חיובי'),
        ('negative', 'שלילי'),
    ], string='כיוון ההתאמה', default='positive')
    il_net_adjustment_treatment = fields.Selection([
        ('gross_up', 'גילום נטו'),
        ('direct_net', 'השפעה ישירה על הנטו'),
    ], string='אופן הטיפול בהתאמת נטו', default='gross_up')

    # ------------------------------------------------------------------
    # מיפוי בסיסי חישוב — קובע על אילו בסיסים משפיעה התאמה מסוג זה
    # ------------------------------------------------------------------
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
    ], string='סיווג לביטוח לאומי', default='none')

    def _il_applicability_snapshot(self):
        """Snapshot dict of the applicability configuration, copied onto
        salary adjustments and payslip inputs at creation time."""
        self.ensure_one()
        return {
            'il_adjustment_direction': self.il_adjustment_direction or 'positive',
            'il_net_adjustment_treatment': self.il_net_adjustment_treatment or 'gross_up',
            'il_income_taxable': self.il_income_taxable,
            'il_national_insurance_applicable': self.il_national_insurance_applicable,
            'il_pensionable': self.il_pensionable,
            'il_severance_applicable': self.il_severance_applicable,
            'il_study_fund_applicable': self.il_study_fund_applicable,
            'il_equalization_levy_applicable': self.il_equalization_levy_applicable,
            'il_ni_payment_treatment': self.il_ni_payment_treatment or 'none',
        }

    @api.constrains('il_net_adjustment_treatment', 'il_income_taxable',
                    'il_national_insurance_applicable', 'il_pensionable',
                    'il_severance_applicable', 'il_study_fund_applicable',
                    'il_equalization_levy_applicable', 'available_in_attachments')
    def _check_il_direct_net_flags(self):
        # התאמת נטו ישירה אינה משנה שום בסיס מס/הפרשה — כל הדגלים חייבים
        # להיות כבויים (כלל מחייב מהאפיון).
        for input_type in self:
            if not input_type.available_in_attachments:
                continue
            if input_type.il_net_adjustment_treatment != 'direct_net':
                continue
            if any([input_type.il_income_taxable,
                    input_type.il_national_insurance_applicable,
                    input_type.il_pensionable,
                    input_type.il_severance_applicable,
                    input_type.il_study_fund_applicable,
                    input_type.il_equalization_levy_applicable]):
                raise ValidationError(
                    'סוג התאמה בטיפול "השפעה ישירה על הנטו" אינו יכול להשפיע '
                    'על בסיסי מס או הפרשות — יש לכבות את כל דגלי הבסיסים.')
