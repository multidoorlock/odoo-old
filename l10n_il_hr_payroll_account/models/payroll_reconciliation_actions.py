from odoo import models


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    def action_il_manage_reconciliation(self):
        self.ensure_one()
        return self.env['il.payroll.reconciliation.wizard']._action_open(
            payment=self)


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    def action_il_manage_reconciliation(self):
        self.ensure_one()
        return self.env['il.payroll.reconciliation.wizard']._action_open(
            payslip=self)
