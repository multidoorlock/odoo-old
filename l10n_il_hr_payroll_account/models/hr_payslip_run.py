from odoo import fields, models


class HrPayslipRun(models.Model):
    _inherit = 'hr.payslip.run'

    def action_paid(self):
        result = super().action_paid()
        self.mapped('slip_ids')._il_check_nonnegative_net_to_pay()
        return result

    def action_il_pay(self):
        self.ensure_one()
        return self.env['il.payslip.run.payment.wizard']._action_open(self)


class AccountBatchPayment(models.Model):
    _inherit = 'account.batch.payment'

    il_payslip_run_id = fields.Many2one(
        'hr.payslip.run', string='אצוות תלושים', readonly=True,
        copy=False, index=True, ondelete='set null', check_company=True)
