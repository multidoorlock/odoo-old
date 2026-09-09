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

    def _il_payslips_to_sync(self):
        return (
            self.debit_move_id.il_payslip_id
            | self.credit_move_id.il_payslip_id
        )

    @api.model_create_multi
    def create(self, vals_list):
        partials = super().create(vals_list)
        partials._il_payslips_to_sync()._il_sync_paid_state_from_balance()
        return partials

    def write(self, vals):
        payslips = self._il_payslips_to_sync()
        result = super().write(vals)
        (payslips | self._il_payslips_to_sync()).exists()._il_sync_paid_state_from_balance()
        return result

    def unlink(self):
        payslips = self._il_payslips_to_sync()
        result = super().unlink()
        payslips.exists()._il_sync_paid_state_from_balance()
        return result
