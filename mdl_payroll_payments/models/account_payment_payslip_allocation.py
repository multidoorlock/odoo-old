# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class AccountPaymentPayslipAllocation(models.Model):
    """חלוקה בפועל של חלק מתשלום לתלוש נוסף (סעיפים 21–27 באפיון).
    המודל מייצג את החלוקה הנוכחית של ה-Payment בלבד — אין שדות
    Source/Target קבועים."""
    _name = 'account.payment.payslip.allocation'
    _description = 'הקצאת תשלום לתלוש שכר'

    payment_id = fields.Many2one(
        'account.payment', string='תשלום', required=True, index=True,
        ondelete='cascade')
    payslip_id = fields.Many2one(
        'hr.payslip', string='תלוש שכר', required=True, index=True)
    amount = fields.Monetary(string='סכום', required=True)
    currency_id = fields.Many2one(
        related='payment_id.currency_id', store=True, readonly=True)
    company_id = fields.Many2one(
        related='payment_id.company_id', store=True, readonly=True, index=True)

    @api.constrains('amount', 'payment_id', 'payslip_id')
    def _check_il_allocation(self):
        for allocation in self:
            payment = allocation.payment_id
            slip = allocation.payslip_id
            currency = payment.currency_id
            if currency.compare_amounts(allocation.amount, 0.0) <= 0:
                raise ValidationError('סכום ההקצאה חייב להיות גדול מאפס.')
            if slip == payment.payslip_id:
                raise ValidationError(
                    'אין ליצור הקצאה לתלוש הראשי של התשלום — חלקו של התלוש '
                    'הראשי הוא היתרה שאינה מוקצית.')
            if slip.employee_id.work_contact_id != payment.partner_id:
                raise ValidationError(
                    'ניתן להקצות תשלום רק לתלוש של אותו עובד.')
            if slip.company_id != payment.company_id:
                raise ValidationError('ההקצאה חייבת להיות באותה חברה.')
            if slip.currency_id != payment.currency_id:
                raise ValidationError('אין לבצע הקצאה בין מטבעות שונים.')
            allocated = sum(payment.payslip_allocation_ids.mapped('amount'))
            if currency.compare_amounts(allocated, payment.amount) > 0:
                raise ValidationError(
                    'סך ההקצאות לתלושים אינו יכול לעלות על סכום התשלום.')
