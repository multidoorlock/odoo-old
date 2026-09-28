from datetime import date

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import tagged

from . import test_payment_reconciliation as payment_fixtures
from .common import HebrewTransactionCase


@tagged('post_install', '-at_install', 'l10n_il_hr_payroll_account_payslip_payment_list')
class TestPayslipPaymentList(HebrewTransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.env['hr.payroll.structure']._il_ensure_payroll_accounting_configuration(overwrite=True)
        cls.payable = cls.company.il_employee_payment_debit_account_id
        cls.outstanding = cls.company.il_employee_payment_credit_account_id
        cls.expense = cls.env['account.account'].search([
            ('company_ids', 'in', cls.company.id), ('account_type', '=', 'expense')], limit=1)
        cls.bank_journal = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id), ('type', 'in', ('bank', 'cash'))], limit=1)
        cls.general_journal = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id), ('type', '=', 'general')], limit=1)
        cls.monthly_type = cls.env.ref('l10n_il_hr_payroll_account.hr_payroll_structure_type_il')
        cls.monthly_structure = cls.env.ref('l10n_il_hr_payroll_account.hr_payroll_structure_il')
        cls.monthly_structure.journal_id = cls.general_journal
        if not cls.general_journal.default_account_id:
            cls.general_journal.default_account_id = cls.expense
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Payslip Payment List Employee', 'company_id': cls.company.id,
            'contract_date_start': date(2026, 1, 1), 'date_version': date(2026, 1, 1),
            'mdl_wage_type': 'mdl_monthly', 'structure_type_id': cls.monthly_type.id,
            'il_salary_structure_id': cls.monthly_structure.id, 'schedule_pay': 'monthly',
        })

    _payment = payment_fixtures.TestEmployeePaymentReconciliation._payment
    _payslip_with_posted_net = payment_fixtures.TestEmployeePaymentReconciliation._payslip_with_posted_net
    _set_hard_lock_date = payment_fixtures.TestEmployeePaymentReconciliation._set_hard_lock_date

    def _linked(self):
        payment = self._payment(1000.0)
        slip = self._payslip_with_posted_net(1500.0)
        payment.il_split_line_ids._il_reconcile_with_payslip(slip)
        return payment.with_context(il_payslip_id=slip.id), slip

    def _edit(self, payment, amount, token=None):
        payment.write({
            'il_payslip_linked_amount': amount,
            'il_payslip_link_write_token': token or payment.il_payslip_link_snapshot,
        })

    def test_inline_amount_changes_only_payslip_link(self):
        payment, slip = self._linked()
        payment_values = (payment.amount, payment.date, payment.partner_id,
                          payment.move_id, payment.move_id.line_ids.mapped('balance'))
        salary_values = slip.line_ids.mapped('total')
        self.assertEqual(payment.il_payslip_linked_amount, 1000.0)
        self._edit(payment, 400.0)
        self.assertEqual(payment.il_payslip_linked_amount, 400.0)
        self.assertEqual(payment.il_remaining_amount, 600.0)
        self.assertEqual(slip.il_net_amount_to_pay, 1100.0)
        self.assertEqual((payment.amount, payment.date, payment.partner_id,
                          payment.move_id, payment.move_id.line_ids.mapped('balance')), payment_values)
        self.assertEqual(slip.line_ids.mapped('total'), salary_values)

    def test_stale_inline_amount_cannot_overwrite_a_newer_link(self):
        payment, slip = self._linked()
        old_token = payment.il_payslip_link_snapshot
        self._edit(payment, 600.0, old_token)
        with self.assertRaises(UserError), self.cr.savepoint():
            self._edit(payment, 400.0, old_token)
        self.assertEqual(payment.il_payslip_linked_amount, 600.0)
        self.assertEqual(slip.il_net_amount_to_pay, 900.0)

    def test_inline_edit_requires_source_and_token_and_rejects_financial_payload(self):
        payment, slip = self._linked()
        token = payment.il_payslip_link_snapshot
        with self.assertRaises(UserError), self.cr.savepoint():
            payment.write({'il_payslip_linked_amount': 400.0})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            payment.write({'il_payslip_linked_amount': 400.0,
                           'il_payslip_link_write_token': token, 'amount': 400.0})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self._edit(payment.with_context(il_payslip_id=False), 400.0, token)
        self.assertEqual(payment.amount, 1000.0)
        self.assertEqual(slip.il_net_amount_to_pay, 500.0)

    def test_inline_zero_and_over_allocation_leave_existing_link_intact(self):
        payment, slip = self._linked()
        old_partial = payment.il_split_line_ids.reconcile_id
        for amount in (0.0, -1.0, 1001.0):
            with self.assertRaises(ValidationError), self.cr.savepoint():
                self._edit(payment, amount)
        self.assertEqual(payment.il_split_line_ids.reconcile_id, old_partial)
        self.assertEqual(payment.il_payslip_linked_amount, 1000.0)

    def test_row_removal_keeps_payment_and_refreshes_live_domain(self):
        payment, slip = self._linked()
        action = slip.action_il_open_payments()
        self.assertIn(payment, self.env['account.payment'].search(action['domain']))
        result = payment.with_context(
            il_payslip_link_expected=payment.il_payslip_link_snapshot,
        ).action_il_remove_from_payslip()
        self.assertEqual(result['tag'], 'reload')
        self.assertTrue(payment.exists())
        self.assertEqual(payment.amount, 1000.0)
        self.assertEqual(payment.move_id.state, 'posted')
        self.assertEqual(slip.il_net_amount_to_pay, 1500.0)
        self.assertNotIn(payment, self.env['account.payment'].search(action['domain']))

    def test_another_payment_row_does_not_stale_an_unchanged_row(self):
        first, slip = self._linked()
        second = self._payment(200.0).with_context(il_payslip_id=slip.id)
        second.il_split_line_ids._il_reconcile_with_payslip(slip)
        second_token = second.il_payslip_link_snapshot
        self._edit(first, 600.0)
        self._edit(second, 100.0, second_token)
        self.assertEqual(first.il_payslip_linked_amount, 600.0)
        self.assertEqual(second.il_payslip_linked_amount, 100.0)
        self.assertEqual(slip.il_net_amount_to_pay, 800.0)

    def test_add_payment_header_opens_native_eligible_payment_list(self):
        payment, slip = self._linked()
        available = self._payment(600.0)
        action = self.env['account.payment'].with_context(
            il_payslip_id=slip.id).action_il_add_payslip_payment()
        self.assertEqual(action['res_model'], 'account.payment')
        self.assertEqual(action['target'], 'new')
        self.assertEqual(action['views'][0], (self.env.ref(
            'l10n_il_hr_payroll_account.view_account_payment_list_payslip_candidates').id, 'list'))
        candidates = self.env['account.payment'].search(action['domain'])
        self.assertNotIn(payment, candidates)
        self.assertIn(available, candidates)
        self.assertEqual(available.il_recognition_available_amount, 600.0)
        self.assertTrue(action['context']['il_payslip_candidate_list'])

    def test_payslip_action_drops_unrelated_grouping_context(self):
        slip = self._payslip_with_posted_net(1500.0)
        action = slip.with_context(group_by='employee_id', search_default_old_filter=1).action_il_open_payments()
        self.assertEqual(action['name'], 'תשלומים מקושרים')
        self.assertNotIn('group_by', action['context'])
        self.assertNotIn('search_default_old_filter', action['context'])
        self.assertIn('הוסף תשלום', action['help'])

    def test_inline_context_cannot_change_a_different_payslip(self):
        payment, original_slip = self._linked()
        other_slip = self._payslip_with_posted_net(1500.0)
        with self.assertRaises(UserError), self.cr.savepoint():
            self._edit(payment.with_context(il_payslip_id=other_slip.id),
                       400.0, payment.il_payslip_link_snapshot)
        self.assertEqual(original_slip.il_net_amount_to_pay, 500.0)
        self.assertEqual(other_slip.il_net_amount_to_pay, 1500.0)

    def test_payslip_list_exposes_only_link_editing_and_hr_labels(self):
        view = self.env.ref('l10n_il_hr_payroll_account.view_account_payment_list_payslip_links')
        arch = view._get_combined_arch()
        self.assertEqual(arch.get('editable'), 'bottom')
        self.assertEqual(arch.get('edit'), '1')
        self.assertEqual(arch.get('create'), '0')
        self.assertEqual(arch.get('delete'), '0')
        self.assertEqual(arch.get('multi_edit'), '0')
        self.assertEqual(arch.xpath('./header/button/@name'), [
            'action_il_add_payslip_payment', 'action_il_remove_payslip_links'])
        self.assertEqual(arch.xpath(
            "./header/button[@name='action_il_add_payslip_payment']/@display"), ['always'])
        self.assertFalse(arch.xpath(
            "./header/button[@name='action_il_remove_payslip_links']/@display"))
        self.assertFalse(arch.xpath('./button'))
        visible = arch.xpath("./field[not(@column_invisible='True')]")
        editable = [field.get('name') for field in visible if field.get('readonly') != '1']
        self.assertEqual(editable, ['il_payslip_linked_amount'])
        amount = arch.xpath("./field[@name='il_payslip_linked_amount']")[0]
        self.assertEqual(amount.get('readonly'), '0')
        self.assertEqual(amount.get('widget'), 'il_payslip_link_amount')
        self.assertEqual(amount.get('sum'), 'סה״כ משויך לתלוש')
        for name in ('il_payslip_link_snapshot', 'il_payslip_link_write_token'):
            self.assertEqual(arch.xpath("./field[@name='%s']/@column_invisible" % name), ['True'])
        self.assertEqual(arch.xpath(
            "./field[@name='il_payslip_link_write_token']/@force_save"), ['1'])
        self.assertFalse(arch.xpath("./field[@name='il_recognition_available_amount']"))
        names = arch.xpath('./field/@name')
        self.assertEqual(names[names.index('amount') + 1], 'il_payslip_linked_amount')
        self.assertEqual(arch.xpath("./field[@name='il_payslip_linked_amount']/@string"), ['סכום משויך לתלוש'])
        self.assertTrue(arch.xpath("./field[@name='amount']"))
        self.assertFalse(arch.xpath("./field[@name='amount_company_currency_signed']"))
        payment_form = self.env.ref(
            'l10n_il_hr_payroll_account.view_account_payment_form_employee')._get_combined_arch()
        self.assertFalse(payment_form.xpath("//button[@name='action_il_manage_reconciliation']"))
        self.assertTrue(payment_form.xpath("//field[@name='il_linked_payslip_id']"))
        self.assertFalse(payment_form.xpath("//field[@name='reconcile_id']"))

    def _selection(self, payments, slip, operation):
        # Retain atomic/stale/period-lock coverage of the reconciliation
        # service even though the UI now edits inline and adds in one popup.
        action = self.env['il.payslip.payment.selection.wizard']._action_open(
            payments.with_context(il_payslip_id=slip.id), operation)
        return self.env[action['res_model']].browse(action['res_id'])

    def test_selected_add_reviews_amounts_and_preserves_existing_links(self):
        current, slip = self._linked()
        old_partial = current._il_payslip_link_partials()
        first = self._payment(400.0)
        second = self._payment(400.0)
        wizard = self._selection(first | second, slip, 'add')
        self.assertEqual(wizard.line_ids.mapped('amount'), [400.0, 100.0])
        self.assertEqual(wizard.line_ids.mapped('available_amount'), [400.0, 400.0])
        wizard.action_apply()
        self.assertEqual(current._il_payslip_link_partials(), old_partial)
        self.assertEqual(first.il_applied_amount, 400.0)
        self.assertEqual(second.il_applied_amount, 100.0)
        self.assertEqual(second.il_remaining_amount, 300.0)
        self.assertEqual(slip.il_net_amount_to_pay, 0.0)
        self.assertEqual((first.amount, second.amount), (400.0, 400.0))
        with self.assertRaises(UserError):
            wizard.action_apply()

    def test_selected_edit_applies_increases_and_decreases_atomically(self):
        slip = self._payslip_with_posted_net(1500.0)
        first = self._payment(2000.0)
        second = self._payment(1000.0)
        Split = self.env['account.payment.split.line']
        Split._il_take_open_amount(first, 1000.0)._il_reconcile_with_payslip(slip)
        Split._il_take_open_amount(second, 500.0)._il_reconcile_with_payslip(slip)
        wizard = self._selection(first | second, slip, 'edit')
        wizard.line_ids.filtered(lambda line: line.payment_id == first).amount = 1200.0
        wizard.line_ids.filtered(lambda line: line.payment_id == second).amount = 300.0
        wizard.action_apply()
        self.assertEqual((first.il_applied_amount, second.il_applied_amount), (1200.0, 300.0))
        self.assertEqual((first.amount, second.amount), (2000.0, 1000.0))
        self.assertEqual(slip.il_net_amount_to_pay, 0.0)

    def test_selected_remove_affects_only_selected_links(self):
        current, slip = self._linked()
        second = self._payment(200.0)
        second.il_split_line_ids._il_reconcile_with_payslip(slip)
        retained = second._il_payslip_link_partials()
        self._selection(current, slip, 'remove').action_apply()
        self.assertFalse(current._il_payslip_link_partials())
        self.assertEqual(second._il_payslip_link_partials(), retained)
        self.assertEqual(slip.il_net_amount_to_pay, 1300.0)
        self.assertEqual((current.amount, current.move_id.state), (1000.0, 'posted'))

    def test_selected_invalid_amount_is_atomic(self):
        current, slip = self._linked()
        available = self._payment(600.0)
        partial = current._il_payslip_link_partials()
        wizard = self._selection(available, slip, 'add')
        wizard.line_ids.amount = 501.0
        with self.assertRaises(ValidationError):
            wizard.action_apply()
        self.assertEqual(current._il_payslip_link_partials(), partial)
        self.assertFalse(available._il_payslip_link_partials())
        self.assertEqual(slip.il_net_amount_to_pay, 500.0)
        self.assertFalse(wizard.applied)

    def test_selected_dialog_rejects_stale_payment_residual(self):
        slip = self._payslip_with_posted_net(1000.0)
        other = self._payslip_with_posted_net(300.0)
        payment = self._payment(1000.0)
        wizard = self._selection(payment, slip, 'add')
        wizard.line_ids.amount = 500.0
        self.env['account.payment.split.line']._il_take_open_amount(
            payment, 300.0)._il_reconcile_with_payslip(other)
        with self.assertRaises(UserError):
            wizard.action_apply()
        self.assertEqual(slip.il_net_amount_to_pay, 1000.0)
        self.assertEqual(payment.il_applied_amount, 300.0)

    def test_selected_dialog_rejects_changed_selection_and_period_lock(self):
        payment, slip = self._linked()
        wizard = self._selection(payment, slip, 'edit')
        with self.assertRaises(ValidationError), self.cr.savepoint():
            wizard.line_ids.write({'payment_id': self._payment(100.0).id})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            wizard.write({'source_payslip_id': self._payslip_with_posted_net(500.0).id})
        wizard.line_ids.amount = 500.0
        partial = payment._il_payslip_link_partials()
        self._set_hard_lock_date(date(2026, 8, 1))
        with self.assertRaises(UserError):
            wizard.action_apply()
        self.assertEqual(payment._il_payslip_link_partials(), partial)

    def test_payment_link_lists_use_header_controls_without_actions(self):
        Actions = self.env['ir.actions.actions']
        expected = {self.env.ref('l10n_il_hr_payroll_account.' + name).id for name in (
            'action_payslip_change_recognized_amount', 'action_payslip_remove_payment_links')}
        general = {action['id'] for action in Actions.get_bindings('account.payment').get('action', [])}
        linked = {action['id'] for action in Actions.with_context(
            il_payslip_id=1, il_payslip_link_list=True).get_bindings('account.payment').get('action', [])}
        candidates = Actions.with_context(il_payslip_id=1, il_payslip_candidate_list=True).get_bindings(
            'account.payment').get('action', [])
        self.assertEqual(linked, general)
        self.assertFalse(general & expected)
        self.assertEqual({action['id'] for action in candidates}, general)
        linked_view = self.env.ref('l10n_il_hr_payroll_account.view_account_payment_list_payslip_links')
        # Match the actual web view service: payroll action context is stripped.
        toolbar = self.env['account.payment'].with_context(lang='he_IL').get_views(
                [(linked_view.id, 'list')], {'toolbar': True})['views']['list']['toolbar']
        self.assertFalse(toolbar.get('action'))
        self.assertEqual(linked_view._get_combined_arch().xpath('./header/button/@name'), [
            'action_il_add_payslip_payment', 'action_il_remove_payslip_links'])
        candidate_arch = self.env.ref(
            'l10n_il_hr_payroll_account.view_account_payment_list_payslip_candidates')._get_combined_arch()
        self.assertEqual(candidate_arch.xpath('./header/button/@name'), ['action_il_select_payslip_payments'])
        self.assertFalse(candidate_arch.xpath('./button'))
        self.assertFalse(candidate_arch.xpath("./field[@name='il_payslip_linked_amount']"))
        for name in ('date', 'partner_id', 'memo', 'amount', 'il_recognition_available_amount'):
            self.assertTrue(candidate_arch.xpath("./field[@name='%s']" % name))
        self.assertEqual(candidate_arch.xpath(
            "./field[@name='amount']/@readonly"), ['1'])
        self.assertEqual(candidate_arch.xpath(
            "./field[@name='il_recognition_available_amount']/@readonly"), ['1'])
        proposal = candidate_arch.xpath("./field[@name='il_payslip_candidate_amount']")[0]
        self.assertEqual(proposal.get('readonly'), '0')
        self.assertTrue(proposal.get('sum'))

    def test_linked_payment_footer_totals_only_amount_used_by_current_payslip(self):
        payment = self._payment(3000.0)
        linked_slip = self._payslip_with_posted_net(1000.0)
        (linked_slip._il_salary_payable_lines() | payment._il_recognition_items()).reconcile()
        linked_payment = payment.with_context(il_payslip_id=linked_slip.id)
        self.assertEqual(linked_payment.amount, 3000.0)
        self.assertEqual(linked_payment.il_payslip_linked_amount, 1000.0)
        self.assertEqual(linked_payment.il_recognition_available_amount, 2000.0)

        # A different payslip sees the same 2,000 remaining as a candidate,
        # despite the original payment document still having a 3,000 value.
        candidate_slip = self._payslip_with_posted_net(4000.0)
        candidates = self.env['il.payroll.reconciliation.wizard']._eligible_payments(candidate_slip)
        self.assertIn(payment, candidates)
        prefix = 'l10n_il_hr_payroll_account.'
        linked_arch = self.env.ref(prefix + 'view_account_payment_list_payslip_links')._get_combined_arch()
        summed_fields = linked_arch.xpath('./field[@sum]/@name')
        self.assertEqual(summed_fields, ['il_payslip_linked_amount'])
        self.assertFalse(linked_arch.xpath("./field[@name='il_recognition_available_amount']"))
        values = linked_payment.web_read({
            'amount': {}, 'il_payslip_linked_amount': {}, 'il_recognition_available_amount': {},
        })[0]
        self.assertEqual(values['amount'], 3000.0)
        self.assertEqual(values['il_recognition_available_amount'], 2000.0)
        self.assertEqual(sum(values[name] for name in summed_fields), 1000.0)
        field_names = linked_arch.xpath('./field/@name')
        self.assertEqual(field_names[field_names.index('amount') + 1], 'il_payslip_linked_amount')
        candidate_arch = self.env.ref(prefix + 'view_account_payment_list_payslip_candidates')._get_combined_arch()
        self.assertFalse(candidate_arch.xpath("./field[@name='il_payslip_linked_amount']"))
        self.assertTrue(candidate_arch.xpath("./field[@name='il_recognition_available_amount']"))
        self.assertFalse(candidate_arch.xpath("./field[@name='amount']/@sum"))
        self.assertEqual(candidate_arch.xpath('./field[@sum]/@name'), ['il_payslip_candidate_amount'])
        # Normal payment and batch navigation retain the native full-payment
        # totals; the change is confined to the payslip allocation views.
        normal_arch = self.env.ref(prefix + 'view_account_payment_list_employee')._get_combined_arch()
        self.assertTrue(normal_arch.xpath("./field[@name='amount']/@sum"))
        review_arch = self.env.ref(prefix + 'view_il_payslip_payment_selection_wizard')._get_combined_arch()
        self.assertEqual(review_arch.xpath("//field[@name='line_ids']/list/field[@sum]/@name"), ['amount'])
