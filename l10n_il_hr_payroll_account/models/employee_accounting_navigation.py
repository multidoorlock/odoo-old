from odoo import api, fields, models


class AccountBatchPayment(models.Model):
    _inherit = 'account.batch.payment'

    il_is_employee_batch = fields.Boolean(
        string='Employee Batch', compute='_compute_il_is_employee_batch',
        store=True, index=True)

    @api.depends('payment_ids.il_is_employee_payment', 'il_payment_cycle_type_ids')
    def _compute_il_is_employee_batch(self):
        for batch in self:
            # Historical batches can predate cycle types. A mixed batch stays
            # visible as a complete batch under Employees, without splitting it.
            batch.il_is_employee_batch = bool(
                batch.il_payment_cycle_type_ids
                or any(batch.payment_ids.mapped('il_is_employee_payment')))

    @api.model
    def _il_place_accounting_employee_menu(self):
        # Enterprise Accounting reparents the native Vendors menu. Follow that
        # installed parent rather than bind the addon to an optional app root.
        vendor_menu = self.env.ref('account.menu_finance_payables')
        self.env.ref('l10n_il_hr_payroll_account.menu_il_accounting_employees').write({
            'parent_id': vendor_menu.parent_id.id,
        })
