# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class AccountPaymentSplitLine(models.Model):
    _name = 'account.payment.split.line'
    _description = 'Payment Split Line'
    _order = 'payment_id, sequence, id'

    payment_id = fields.Many2one(
        'account.payment', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(string="פעימה מס'", required=True, default=1)
    amount = fields.Monetary(required=True)
    currency_id = fields.Many2one(
        related='payment_id.currency_id', store=True, readonly=True)
    payslip_id = fields.Many2one(
        'hr.payslip', string='תלוש', ondelete='set null', index=True)
    is_applied = fields.Boolean(
        string='קוזז', compute='_compute_is_applied', store=True)
    company_id = fields.Many2one(
        related='payment_id.company_id', store=True, readonly=True)
    employee_id = fields.Many2one(
        'hr.employee', compute='_compute_employee', store=True)

    _positive_amount = models.Constraint(
        'CHECK(amount > 0)', 'סכום פעימה חייב להיות גדול מאפס.')
    _positive_sequence = models.Constraint(
        'CHECK(sequence > 0)', 'מספר פעימה חייב להיות גדול מאפס.')
    _unique_payment_payslip = models.Constraint(
        'UNIQUE(payment_id, payslip_id)', 'תשלום יכול להימשך פעם אחת בלבד בכל תלוש.')

    @api.depends('payslip_id')
    def _compute_is_applied(self):
        for line in self:
            line.is_applied = bool(line.payslip_id)

    @api.depends('payment_id.partner_id', 'payment_id.company_id')
    def _compute_employee(self):
        for line in self:
            line.employee_id = line.payment_id._il_employee()

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get('il_system_split_create'):
            payment_ids = {vals.get('payment_id') for vals in vals_list if vals.get('payment_id')}
            payments = self.env['account.payment'].browse(payment_ids)
            if payments.filtered(lambda payment: payment.il_spread_type != 'planned'):
                raise ValidationError('יצירה ידנית של פעימות מותרת רק בפריסה מתוכננת.')
        lines = super().create(vals_list)
        lines._check_business_rules()
        if not self.env.context.get('il_skip_spread_total_check'):
            lines.mapped('payment_id')._check_il_spread_complete()
        return lines

    def write(self, vals):
        result = super().write(vals)
        self._check_business_rules()
        if 'amount' in vals and not self.env.context.get('il_sync_from_payment'):
            for line in self.filtered(lambda item: item.payment_id.il_spread_type == 'none'):
                line.payment_id.with_context(il_sync_from_line=True).amount = line.amount
        if not self.env.context.get('il_skip_spread_total_check'):
            self.mapped('payment_id')._check_il_spread_complete()
        return result

    def unlink(self):
        if not self.env.context.get('il_system_split_unlink') and \
                self.filtered(lambda line: line.payment_id.il_spread_type != 'planned'):
            raise ValidationError('מחיקת פעימות מותרת רק בפריסה מתוכננת.')
        payments = self.mapped('payment_id')
        result = super().unlink()
        payments._il_resequence_split_lines()
        if not self.env.context.get('il_system_split_unlink'):
            payments._check_il_spread_complete()
        return result

    def _check_business_rules(self):
        for line in self:
            payment = line.payment_id
            if line.payslip_id:
                if line.payslip_id.company_id != payment.company_id:
                    raise ValidationError('התשלום והתלוש חייבים להיות באותה חברה.')
                if line.payslip_id.employee_id != line.employee_id:
                    raise ValidationError('אסור לקשר פעימה לתלוש של עובד אחר.')
            applied = sum(payment.il_split_line_ids.filtered('payslip_id').mapped('amount'))
            if payment.currency_id.compare_amounts(applied, payment.amount) > 0:
                raise ValidationError('סכום הפעימות שקוזזו אינו יכול לעבור את סכום התשלום.')
            if payment.il_spread_type == 'none' and len(payment.il_split_line_ids) > 1:
                raise ValidationError('במצב פריסה מיידית מותרת שורת פריסה אחת בלבד.')
