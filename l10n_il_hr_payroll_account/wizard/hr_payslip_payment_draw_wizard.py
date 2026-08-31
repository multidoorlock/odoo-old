# -*- coding: utf-8 -*-
from odoo import Command, fields, models
from odoo.exceptions import ValidationError


class HrPayslipPaymentDrawWizard(models.TransientModel):
    _name = 'hr.payslip.payment.draw.wizard'
    _description = 'Draw Open Payments into Payslip'

    payslip_id = fields.Many2one('hr.payslip', required=True, readonly=True)
    line_ids = fields.One2many(
        'hr.payslip.payment.draw.wizard.line', 'wizard_id', string='תשלומים פתוחים')
    currency_id = fields.Many2one(related='payslip_id.currency_id', readonly=True)

    def action_apply(self):
        self.ensure_one()
        available_net = max(
            self.payslip_id._il_compute_net_total()
            - self.payslip_id._il_applied_payment_amount(), 0.0)
        requested = sum(self.line_ids.mapped('amount_to_draw'))
        if self.currency_id.compare_amounts(requested, available_net) > 0:
            raise ValidationError('סכום המשיכה הכולל גבוה מהנטו הזמין בתלוש.')
        Split = self.env['account.payment.split.line']
        for wizard_line in self.line_ids.filtered(lambda line: line.amount_to_draw > 0):
            payment = wizard_line.payment_id
            if payment.currency_id.compare_amounts(
                    wizard_line.amount_to_draw, payment.il_remaining_amount) > 0:
                raise ValidationError(
                    'סכום המשיכה גבוה מיתרת המשיכה בתשלום %s.' % payment.display_name)
            next_sequence = max(payment.il_split_line_ids.mapped('sequence'), default=0) + 1
            Split.with_context(il_system_split_create=True).create({
                'payment_id': payment.id,
                'sequence': next_sequence,
                'amount': wizard_line.amount_to_draw,
                'payslip_id': self.payslip_id.id,
            })
        self.payslip_id.compute_sheet()
        return {'type': 'ir.actions.act_window_close'}


class HrPayslipPaymentDrawWizardLine(models.TransientModel):
    _name = 'hr.payslip.payment.draw.wizard.line'
    _description = 'Open Payment Draw Line'

    wizard_id = fields.Many2one(
        'hr.payslip.payment.draw.wizard', required=True, ondelete='cascade')
    payment_id = fields.Many2one('account.payment', required=True, readonly=True)
    payment_amount = fields.Monetary(related='payment_id.amount', readonly=True)
    applied_amount = fields.Monetary(related='payment_id.il_applied_amount', readonly=True)
    remaining_amount = fields.Monetary(related='payment_id.il_remaining_amount', readonly=True)
    amount_to_draw = fields.Monetary(string='סכום למשיכה')
    currency_id = fields.Many2one(related='payment_id.currency_id', readonly=True)
