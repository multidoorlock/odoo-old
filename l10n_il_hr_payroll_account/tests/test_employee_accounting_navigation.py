from datetime import date

from odoo import Command
from odoo.tests.common import TransactionCase, tagged
from odoo.tools.safe_eval import safe_eval


@tagged('post_install', '-at_install', 'l10n_il_employee_accounting_navigation')
class TestEmployeeAccountingNavigation(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.env['hr.payroll.structure']._il_ensure_payroll_accounting_configuration(overwrite=True)
        cls.journal = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id), ('type', '=', 'bank')], limit=1)
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Accounting Navigation Employee', 'company_id': cls.company.id,
            'contract_date_start': date(2026, 1, 1), 'date_version': date(2026, 1, 1),
            'mdl_wage_type': 'mdl_monthly', 'schedule_pay': 'monthly',
            'structure_type_id': cls.env.ref(
                'l10n_il_hr_payroll_account.hr_payroll_structure_type_il').id,
            'il_salary_structure_id': cls.env.ref(
                'l10n_il_hr_payroll_account.hr_payroll_structure_il').id,
        })
        cls.vendor = cls.env['res.partner'].create({
            'name': 'Accounting Navigation Vendor', 'supplier_rank': 1})

    def _payment(self, employee=False, amount=100.0):
        return self.env['account.payment'].create({
            'partner_id': (self.employee.work_contact_id if employee else self.vendor).id,
            'company_id': self.company.id, 'payment_type': 'outbound',
            'partner_type': 'supplier', 'journal_id': self.journal.id,
            'date': date(2026, 9, 1), 'amount': amount,
        })

    def _batch(self, payments):
        return self.env['account.batch.payment'].create({
            'name': 'Navigation batch', 'date': date(2026, 9, 1),
            'journal_id': self.journal.id, 'batch_type': 'outbound',
            'payment_method_id': payments[0].payment_method_id.id,
            'payment_ids': [Command.set(payments.ids)],
        })

    def _action(self, xmlid):
        return self.env['ir.actions.actions']._for_xml_id(xmlid)

    def _records(self, action):
        domain = action.get('domain') or []
        if isinstance(domain, str):
            domain = safe_eval(domain)
        return self.env[action['res_model']].search(domain)

    def test_historical_and_mixed_batches_reclassify_without_moving_payments(self):
        vendor = self._payment()
        employee = self._payment(employee=True, amount=250.0)
        batch = self._batch(vendor)
        self.assertFalse(batch.il_is_employee_batch)
        batch.payment_ids = [Command.link(employee.id)]
        self.assertFalse(batch.il_payment_cycle_type_ids)
        self.assertTrue(batch.il_is_employee_batch)
        self.assertEqual(batch.payment_ids, vendor | employee)
        self.assertEqual((vendor.amount, employee.amount), (100.0, 250.0))
        self.assertEqual((vendor.batch_payment_id, employee.batch_payment_id), (batch, batch))
        batch.payment_ids = [Command.unlink(employee.id)]
        self.assertFalse(batch.il_is_employee_batch)
        self.assertEqual(batch.payment_ids, vendor)
        self.assertTrue(employee.exists())
        batch.payment_ids = [Command.set(employee.ids)]
        self.assertTrue(batch.il_is_employee_batch)
        self.env.flush_all()
        batch.invalidate_recordset(['il_is_employee_batch'])
        self.assertTrue(batch.il_is_employee_batch)

    def test_cycle_type_marks_empty_or_historical_batch_and_recomputes_on_removal(self):
        batch = self._batch(self._payment())
        cycle = self.env['il.payment.cycle.type'].create({
            'name': 'Navigation weekly type', 'recurrence': 'week'})
        batch.il_payment_cycle_type_ids = [Command.link(cycle.id)]
        self.assertTrue(batch.il_is_employee_batch)
        batch.payment_ids = [Command.clear()]
        self.assertTrue(batch.il_is_employee_batch)
        batch.il_payment_cycle_type_ids = [Command.clear()]
        self.assertFalse(batch.il_is_employee_batch)

    def test_partner_change_updates_payment_and_batch_classification(self):
        payment = self._payment()
        batch = self._batch(payment)
        self.assertFalse(payment.il_is_employee_payment)
        self.assertFalse(batch.il_is_employee_batch)
        payment.partner_id = self.employee.work_contact_id
        self.assertTrue(payment.il_is_employee_payment)
        self.assertTrue(batch.il_is_employee_batch)
        payment.partner_id = self.vendor
        self.assertFalse(payment.il_is_employee_payment)
        self.assertFalse(batch.il_is_employee_batch)
        self.assertEqual(payment.batch_payment_id, batch)

    def test_vendor_and_employee_payment_actions_partition_existing_records(self):
        vendor = self._payment()
        employee = self._payment(employee=True)
        vendor_action = self._action('account.action_account_payments_payable')
        employee_action = self._action(
            'l10n_il_hr_payroll_account.action_il_accounting_employee_payments')
        self.assertEqual(vendor_action['res_model'], 'account.payment')
        self.assertIn(vendor, self._records(vendor_action))
        self.assertNotIn(employee, self._records(vendor_action))
        self.assertIn(employee, self._records(employee_action))
        self.assertNotIn(vendor, self._records(employee_action))
        # Action-specific navigation must not overwrite the source action.
        before = self.env.ref('account.action_account_payments_payable').read([
            'domain', 'context', 'view_mode', 'view_id'])[0]
        self.employee.action_il_open_payments()
        self.assertEqual(self.env.ref('account.action_account_payments_payable').read([
            'domain', 'context', 'view_mode', 'view_id'])[0], before)
        vendor_context = safe_eval(vendor_action.get('context') or '{}')
        self.assertEqual(vendor_context.get('default_partner_type'), 'supplier')
        self.assertEqual(vendor_context.get('default_payment_type'), 'outbound')

    def test_mixed_batch_is_visible_intact_only_in_employee_batch_actions(self):
        plain = self._batch(self._payment())
        employee = self._payment(employee=True)
        vendor = self._payment(amount=300.0)
        mixed = self._batch(employee | vendor)
        vendor_action = self._action('account_batch_payment.action_batch_payment_out')
        employee_action = self._action(
            'l10n_il_hr_payroll_account.action_il_accounting_employee_batches')
        payroll_action = self._action('l10n_il_hr_payroll_account.action_il_payment_cycles')
        self.assertIn(plain, self._records(vendor_action))
        self.assertNotIn(mixed, self._records(vendor_action))
        for action in (employee_action, payroll_action):
            self.assertIn(mixed, self._records(action))
            self.assertNotIn(plain, self._records(action))
        before = self.env.ref('account_batch_payment.action_batch_payment_out').read([
            'domain', 'context', 'view_mode', 'view_id'])[0]
        details = mixed.action_il_open_grouped_payments()
        self.assertEqual(set(self._records(details).ids), set((employee | vendor).ids))
        self.assertEqual(mixed.payment_ids, employee | vendor)
        self.assertEqual(self.env.ref('account_batch_payment.action_batch_payment_out').read([
            'domain', 'context', 'view_mode', 'view_id'])[0], before)

    def test_accounting_employee_menu_preserves_native_payslip_action_and_list_first(self):
        vendor_menu = self.env.ref('account.menu_finance_payables')
        employee_menu = self.env.ref('l10n_il_hr_payroll_account.menu_il_accounting_employees')
        self.assertEqual(employee_menu.parent_id, vendor_menu.parent_id)
        self.assertNotEqual(employee_menu, vendor_menu)
        self.assertIn(self.env.ref('hr_payroll.group_hr_payroll_user'), employee_menu.group_ids)
        payslip_menu = self.env.ref(
            'l10n_il_hr_payroll_account.menu_il_accounting_employee_payslips')
        self.assertEqual(payslip_menu.action, self.env.ref('hr_payroll.action_view_hr_payslip_month_form'))
        employee_action = self._action(
            'l10n_il_hr_payroll_account.action_il_accounting_employee_payments')
        self.assertEqual(employee_action['views'][0], (
            self.env.ref('l10n_il_hr_payroll_account.view_account_payment_list_employee').id, 'list'))
        self.assertIn((self.env.ref(
            'l10n_il_hr_payroll_account.view_account_payment_form_employee').id, 'form'),
            employee_action['views'])
        self.assertEqual(employee_action['search_view_id'][0], self.env.ref(
            'account.view_account_payment_search').id)
