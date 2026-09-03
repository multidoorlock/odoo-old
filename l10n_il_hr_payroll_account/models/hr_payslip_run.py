from odoo import models
from odoo.exceptions import UserError


class HrPayslipRun(models.Model):
    _inherit = 'hr.payslip.run'

    def action_paid(self):
        result = super().action_paid()
        self.mapped('slip_ids')._il_check_nonnegative_net_to_pay()
        return result

    def action_il_pay(self):
        Payment = self.env['account.payment']
        created = Payment
        for run in self:
            for slip in run.slip_ids.filtered(lambda item: item.state == 'validated'):
                remaining = slip.il_net_amount_to_pay
                currency = slip.currency_id or slip.company_id.currency_id
                if currency.compare_amounts(remaining, 0.0) <= 0:
                    continue
                partner = slip.employee_id.work_contact_id
                if not partner:
                    raise UserError('לעובד אין איש קשר מקושר ולכן לא ניתן ליצור תשלום.')
                journal = self.env['account.journal'].search([
                    ('company_id', '=', slip.company_id.id),
                    ('type', 'in', ('bank', 'cash')),
                ], limit=1)
                if not journal:
                    raise UserError('לא נמצא יומן בנק או מזומן ליצירת תשלומי השכר.')
                created |= Payment.with_context(
                    il_origin_payslip_id=slip.id,
                    il_max_payment_amount=remaining,
                ).create({
                    'partner_id': partner.id,
                    'company_id': slip.company_id.id,
                    'payment_type': 'outbound',
                    'partner_type': 'supplier',
                    'journal_id': journal.id,
                    'date': slip.date_to,
                    'amount': remaining,
                    'il_spread_type': 'none',
                })
        if not created:
            raise UserError('אין יתרת נטו לתשלום באף תלוש מאושר במחזור זה.')
        action = self.env['ir.actions.actions']._for_xml_id(
            'l10n_il_hr_payroll_account.il_action_employee_payments')
        action['domain'] = [('id', 'in', created.ids)]
        return action
