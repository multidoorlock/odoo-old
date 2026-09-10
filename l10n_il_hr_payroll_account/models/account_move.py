# -*- coding: utf-8 -*-
from odoo import api, fields, models


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    # This identifies the payslip-owned payable item. It is not a direct link
    # from an employee payment to a payslip: allocation exists exclusively as
    # native account.partial.reconcile records.
    il_payslip_id = fields.Many2one(
        'hr.payslip', string='Payslip', copy=False, check_company=True,
        index='btree_not_null', ondelete='set null')


class AccountPartialReconcile(models.Model):
    _inherit = 'account.partial.reconcile'

    il_payment_id = fields.Many2one(
        related='debit_move_id.payment_id', string='Employee Payment',
        readonly=True)
    il_payment_move_id = fields.Many2one(
        related='debit_move_id.move_id', string='Payment Journal Entry',
        readonly=True)
    il_payslip_move_id = fields.Many2one(
        related='credit_move_id.move_id', string='Payslip Journal Entry',
        readonly=True)

    def _il_payslips_to_sync(self):
        return (
            self.debit_move_id.il_payslip_id
            | self.credit_move_id.il_payslip_id
        )

    @api.model_create_multi
    def create(self, vals_list):
        partials = super().create(vals_list)
        partials._il_payslips_to_sync().sudo()._il_sync_paid_state_from_balance()
        return partials

    def write(self, vals):
        payslips = self._il_payslips_to_sync()
        result = super().write(vals)
        (payslips | self._il_payslips_to_sync()).sudo().exists(
        )._il_sync_paid_state_from_balance()
        return result

    def unlink(self):
        payslips = self._il_payslips_to_sync()
        # Reconciliation is a general Accounting operation. Looking up our
        # optional payroll metadata must never require the accounting user to
        # also belong to a Payroll group. Use sudo only for this internal link
        # synchronization; the native reconciliation unlink itself keeps the
        # caller's original access checks.
        split_lines = self.env['account.payment.split.line'].sudo().search([
            ('reconcile_id', 'in', self.ids),
        ])
        if split_lines:
            if not self.env.context.get('il_discard_reconciliation_target'):
                for split_line in split_lines.filtered(
                        lambda line: line.payment_id.state == 'draft'):
                    target_line = (
                        split_line.reconcile_id.debit_move_id
                        | split_line.reconcile_id.credit_move_id
                    ).filtered('il_payslip_id')[:1]
                    if target_line:
                        split_line.with_context(
                            il_reconciliation_sync=True,
                            il_skip_draft_reconciliation_check=True,
                        ).il_pending_payslip_move_line_id = target_line
            split_lines.with_context(
                il_reconciliation_sync=True,
                il_skip_draft_reconciliation_check=True,
            ).write({'reconcile_id': False})
        result = super().unlink()
        payslips.sudo().exists()._il_sync_paid_state_from_balance()
        return result
