# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    # התלוש הראשי שאליו קושר התשלום (סעיפים 11–13 באפיון).
    payslip_id = fields.Many2one(
        'hr.payslip', string='תלוש שכר', index=True, copy=False, tracking=True)
    # "Payment זה נוצר במחזור X" — תיעוד בלבד, ללא קשר להתאמת שכר.
    payroll_cycle_id = fields.Many2one(
        'hr.payroll.cycle', string='נוצר במחזור', index=True, copy=False, readonly=True)
    payslip_allocation_ids = fields.One2many(
        'account.payment.payslip.allocation', 'payment_id', string='הקצאות לתלושים')
    # לתצוגה בלבד — אזהרת תשלום-ביתר בזמן טיוטה (לפני שהתשלום הזה עצמו
    # נכלל בחישוב הנטו-לתשלום של התלוש המקושר).
    il_payslip_net_to_pay = fields.Monetary(
        related='payslip_id.il_net_amount_to_pay', string='נטו לתשלום בתלוש')
    # store=True: נדרש כדי לשמש ב-Domain של פעולת התפריט "תשלומי עובדים"
    # (שדה compute לא מאוחסן אינו ניתן לשימוש בחיפוש/Domain ב-SQL).
    il_is_employee_payment = fields.Boolean(
        string='תשלום לעובד', compute='_compute_il_is_employee_payment', store=True)

    @api.depends('partner_id', 'company_id')
    def _compute_il_is_employee_payment(self):
        for payment in self:
            payment.il_is_employee_payment = payment._il_is_employee_payment()

    def _il_employee(self):
        """The employee behind this payment's partner (same company), or empty."""
        self.ensure_one()
        if not self.partner_id:
            return self.env['hr.employee']
        return self.env['hr.employee'].with_context(active_test=False).search([
            ('work_contact_id', '=', self.partner_id.id),
            ('company_id', '=', self.company_id.id),
        ], limit=1)

    def _il_is_employee_payment(self):
        self.ensure_one()
        return bool(self._il_employee())

    def _il_is_open_employee_payment(self):
        """Open Employee Payment — ההגדרה המדויקת מסעיף 14 באפיון."""
        self.ensure_one()
        return (
            self._il_is_employee_payment()
            and not self.payslip_id
            and self.payment_type == 'outbound'
            and self.state in ('in_process', 'paid'))

    # ------------------------------------------------------------------
    # אכיפות Server Side (סעיפים 4, 12, 78 באפיון)
    # ------------------------------------------------------------------
    @api.constrains('payslip_id', 'partner_id', 'company_id', 'payment_type')
    def _check_il_payslip_link(self):
        for payment in self:
            if not payment.payslip_id:
                continue
            employee = payment._il_employee()
            if not employee:
                raise ValidationError(
                    'רק תשלום של עובד (Partner המקושר לעובד) יכול להיות מקושר לתלוש שכר.')
            if payment.payment_type != 'outbound':
                raise ValidationError('רק תשלום יוצא יכול להיות מקושר לתלוש שכר.')
            slip = payment.payslip_id
            if slip.employee_id.work_contact_id != payment.partner_id:
                raise ValidationError(
                    'אסור לקשר תשלום של עובד אחד לתלוש של עובד אחר.')
            if slip.company_id != payment.company_id:
                raise ValidationError('התלוש והתשלום חייבים להיות באותה חברה.')

    @api.constrains('payroll_cycle_id', 'partner_id', 'company_id')
    def _check_il_cycle_link(self):
        for payment in self:
            if not payment.payroll_cycle_id:
                continue
            if not payment._il_is_employee_payment():
                raise ValidationError(
                    'רק תשלום של עובד יכול להיות מקושר למחזור תשלומים.')
            if payment.payroll_cycle_id.company_id != payment.company_id:
                raise ValidationError('המחזור והתשלום חייבים להיות באותה חברה.')

    @api.constrains('amount', 'payslip_allocation_ids')
    def _check_il_allocation_total(self):
        for payment in self:
            allocated = sum(payment.payslip_allocation_ids.mapped('amount'))
            if payment.currency_id.compare_amounts(allocated, payment.amount) > 0:
                raise ValidationError(
                    'סך ההקצאות לתלושים אינו יכול לעלות על סכום התשלום.')
