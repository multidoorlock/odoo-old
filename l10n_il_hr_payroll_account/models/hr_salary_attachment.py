# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError

IL_SNAPSHOT_FIELDS = [
    'il_adjustment_direction', 'il_net_adjustment_treatment',
    'il_income_taxable', 'il_national_insurance_applicable',
    'il_pensionable', 'il_severance_applicable',
    'il_study_fund_applicable', 'il_equalization_levy_applicable',
    'il_ni_payment_treatment',
]


class HrSalaryAttachment(models.Model):
    _inherit = 'hr.salary.attachment'

    def record_payment(self, *args, **kwargs):
        # Limit the date correction to the native payment workflow; ordinary
        # edits must continue to enforce the standard date constraint.
        return super(HrSalaryAttachment, self.with_context(
            il_salary_attachment_payment_closure=True,
        )).record_payment(*args, **kwargs)

    def write(self, vals):
        if not self.env.context.get('il_salary_attachment_payment_closure') or not vals.get('date_end'):
            return super().write(vals)
        effective_date = fields.Date.to_date(
            self.env.context.get('il_payroll_payment_date'))
        result = True
        for attachment in self:
            values = dict(vals)
            # Native closure uses today's date. A future payroll payment must
            # never close an adjustment before that adjustment has started.
            if values.get('state', attachment.state) == 'close':
                values['date_end'] = max(filter(None, (
                    fields.Date.to_date(values['date_end']),
                    fields.Date.to_date(values.get('date_start')) or attachment.date_start,
                    effective_date,
                )))
            result = super(HrSalaryAttachment, attachment).write(values) and result
        return result

    # ------------------------------------------------------------------
    # סוג השפעה (סעיף "שדה חדש ב-Salary Adjustment" באפיון)
    # ------------------------------------------------------------------
    # אין default= בכוונה: שדה compute+store עם default קבוע נכתב מיידית
    # בעת היצירה ומדלג על החישוב שכופה 'net' לסוגי direct_net (ראו
    # ה-fallback ל-'gross' בתוך החישוב עצמו).
    il_effect_type = fields.Selection([
        ('gross', 'ברוטו'),
        ('net', 'נטו'),
    ], string='סוג השפעה על התשלום', required=True, tracking=True,
       compute='_compute_il_effect_type', store=True, readonly=False, precompute=True)

    # "Salary Adjustment זה נוצר במחזור X" — קישור תיעודי בלבד, ללא קשר
    # ל-Payment כלשהו (איסור Pair Relationship).

    # ------------------------------------------------------------------
    # Snapshot מהגדרות סוג ההתאמה — מתעדכן בהחלפת סוג כל עוד ההתאמה לא
    # שימשה בתלוש; לאחר מכן קפוא (אין השפעה רטרואקטיבית של שינויי הגדרה).
    # החישוב תלוי בשדה הקישור בלבד ולא בשדות התצורה של הסוג, ולכן שינוי
    # תצורה עתידי בסוג אינו מחלחל להתאמות קיימות.
    # ------------------------------------------------------------------
    il_adjustment_direction = fields.Selection([
        ('positive', 'חיובי'),
        ('negative', 'שלילי'),
    ], string='כיוון ההתאמה', compute='_compute_il_snapshot', store=True)
    il_net_adjustment_treatment = fields.Selection([
        ('gross_up', 'גילום נטו'),
        ('direct_net', 'השפעה ישירה על הנטו'),
    ], string='אופן הטיפול בנטו', compute='_compute_il_snapshot', store=True)
    il_income_taxable = fields.Boolean(
        string='חייב במס הכנסה', compute='_compute_il_snapshot', store=True)
    il_national_insurance_applicable = fields.Boolean(
        string='חייב בביטוח לאומי', compute='_compute_il_snapshot', store=True)
    il_pensionable = fields.Boolean(
        string='נכלל בשכר לפנסיה', compute='_compute_il_snapshot', store=True)
    il_severance_applicable = fields.Boolean(
        string='נכלל בשכר לפיצויים', compute='_compute_il_snapshot', store=True)
    il_study_fund_applicable = fields.Boolean(
        string='נכלל בבסיס קרן השתלמות', compute='_compute_il_snapshot', store=True)
    il_equalization_levy_applicable = fields.Boolean(
        string='נכלל בבסיס היטל השוואה', compute='_compute_il_snapshot', store=True)
    il_ni_payment_treatment = fields.Selection([
        ('regular', 'תשלום רגיל'),
        ('additional_payment', 'תשלום נוסף'),
        ('none', 'ללא'),
    ], string='סיווג לביטוח לאומי', compute='_compute_il_snapshot', store=True)

    # הכיווניות נקבעת אוטומטית מסוג ההתאמה — שדה הליבה הופך מחושב.
    is_refund = fields.Boolean(compute='_compute_is_refund', store=True, readonly=True)

    @api.depends('other_input_type_id')
    def _compute_il_snapshot(self):
        for attachment in self:
            if attachment.payslip_ids:
                # ההתאמה כבר שימשה בתלוש — ה-Snapshot קפוא.
                continue
            input_type = attachment.other_input_type_id
            if not input_type:
                continue
            snapshot = input_type._il_applicability_snapshot()
            for field_name in IL_SNAPSHOT_FIELDS:
                attachment[field_name] = snapshot[field_name]

    @api.depends('il_adjustment_direction')
    def _compute_is_refund(self):
        for attachment in self:
            attachment.is_refund = attachment.il_adjustment_direction == 'negative'

    @api.depends('other_input_type_id.il_net_adjustment_treatment')
    def _compute_il_effect_type(self):
        # סוג שהטיפול בו הוגדר כ"השפעה ישירה על הנטו" חייב תמיד להיות נטו
        # (לא ניתן לבחור ברוטו עבור מקדמה/הלוואה/עיקול וכדומה); עבור סוגים
        # אחרים משתמרת בחירת המשתמש (ברירת המחדל היא ברוטו). קורא ישירות
        # מהשדה על hr.payslip.input.type (לא מה-Snapshot) — שדה רגיל, זמין
        # תמיד גם בשלב precompute, ללא תלות בסדר חישוב.
        for attachment in self:
            if attachment.payslip_ids:
                continue
            if attachment.other_input_type_id.il_net_adjustment_treatment == 'direct_net':
                attachment.il_effect_type = 'net'
            elif not attachment.il_effect_type:
                attachment.il_effect_type = 'gross'

    @api.constrains('il_effect_type', 'il_net_adjustment_treatment')
    def _check_il_effect_type_direct_net(self):
        for attachment in self:
            if (attachment.il_net_adjustment_treatment == 'direct_net'
                    and attachment.il_effect_type != 'net'):
                raise ValidationError(
                    'סוג ההתאמה "%s" מוגדר עם השפעה ישירה על הנטו — לא ניתן '
                    'לבחור עבורו סוג השפעה "ברוטו".' % attachment.other_input_type_id.name)
