# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    il_employee_payment_debit_account_id = fields.Many2one(
        'account.account', string='חשבון חובה לתשלומי עובד',
        check_company=True)
    il_employee_payment_credit_account_id = fields.Many2one(
        'account.account', string='חשבון זכות לתשלומי עובד',
        check_company=True)

    def _il_enable_employee_payment_account_reconciliation(self):
        accounts = (
            self.mapped('il_employee_payment_debit_account_id')
            | self.mapped('il_employee_payment_credit_account_id')
        )
        accounts.filtered(lambda account: not account.reconcile).write({
            'reconcile': True,
        })

    @api.model_create_multi
    def create(self, vals_list):
        companies = super().create(vals_list)
        companies._il_enable_employee_payment_account_reconciliation()
        return companies

    def write(self, vals):
        result = super().write(vals)
        if {
            'il_employee_payment_debit_account_id',
            'il_employee_payment_credit_account_id',
        } & vals.keys():
            self._il_enable_employee_payment_account_reconciliation()
        return result
