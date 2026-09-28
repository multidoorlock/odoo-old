from datetime import date

from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged

from . import test_payment_reconciliation as payment_fixtures


@tagged('post_install', '-at_install', 'l10n_il_hr_payroll_account_reconciliation_editor')
class TestPayrollReconciliationEditor(TransactionCase):

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
            'name': 'Allocation Editor Employee', 'company_id': cls.company.id,
            'contract_date_start': date(2026, 1, 1),
            'date_version': date(2026, 1, 1),
            'mdl_wage_type': 'mdl_monthly',
            'structure_type_id': cls.monthly_type.id,
            'il_salary_structure_id': cls.monthly_structure.id,
            'schedule_pay': 'monthly',
        })

    _payment = payment_fixtures.TestEmployeePaymentReconciliation._payment
    _payslip_with_posted_net = payment_fixtures.TestEmployeePaymentReconciliation._payslip_with_posted_net
    _set_hard_lock_date = payment_fixtures.TestEmployeePaymentReconciliation._set_hard_lock_date

    def _editor(self, payment=None, slip=None, add_only=False):
        return self.env['il.payroll.reconciliation.wizard'].create({
            'source_payment_id': payment.id if payment else False,
            'source_payslip_id': slip.id if slip else False,
            'add_only': add_only,
        })

    def _add(self, wizard, payment, slip, amount):
        wizard.write({'line_ids': [Command.create({
            'payment_id': payment.id, 'payslip_id': slip.id, 'amount': amount,
        })]})

    def _settle(self, payment):
        move = self.env['account.move'].create({
            'journal_id': self.bank_journal.id, 'date': payment.date,
            'line_ids': [Command.create({
                'name': 'Already transferred', 'account_id': self.outstanding.id,
                'partner_id': payment.partner_id.id, 'debit': payment.amount,
            }), Command.create({
                'name': 'Bank', 'account_id': self.bank_journal.default_account_id.id,
                'credit': payment.amount,
            })],
        })
        move.action_post()
        lines = (payment.move_id.line_ids | move.line_ids).filtered(
            lambda line: line.account_id == self.outstanding)
        lines.reconcile()
        payment._compute_state()
        return lines.matched_debit_ids | lines.matched_credit_ids

    def _financial_snapshot(self, payment, slip):
        return (payment.amount, payment.date, payment.partner_id.id,
                tuple((line.id, line.account_id.id, line.debit, line.credit)
                      for line in (payment.move_id.line_ids | slip.move_id.line_ids).sorted('id')),
                tuple((line.id, line.total) for line in slip.line_ids.sorted('id')))

    def test_change_and_remove_allocation_preserves_paid_payment_and_bank_settlement(self):
        payment = self._payment(3000.0)
        bank_partial = self._settle(payment)
        slip = self._payslip_with_posted_net(5000.0)
        financial = self._financial_snapshot(payment, slip)
        wizard = self._editor(slip=slip)
        self._add(wizard, payment, slip, 1000.0)
        wizard.action_apply()
        self.assertEqual(payment.state, 'paid')
        self.assertEqual(payment.il_remaining_amount, 2000.0)
        self.assertEqual(slip.il_net_amount_to_pay, 4000.0)

        wizard = self._editor(payment=payment)
        old_partial = payment.il_split_line_ids.reconcile_id
        wizard.line_ids.amount = 600.0
        wizard.action_apply()
        self.assertFalse(old_partial.exists())
        self.assertEqual(payment.il_applied_amount, 600.0)
        self.assertEqual(payment.il_remaining_amount, 2400.0)
        self.assertEqual(payment.state, 'paid')
        self.assertEqual(bank_partial.exists(), bank_partial)
        self.assertEqual(self._financial_snapshot(payment, slip), financial)

        wizard = self._editor(slip=slip)
        wizard.line_ids.unlink()
        wizard.action_apply()
        self.assertEqual(payment.il_applied_amount, 0.0)
        self.assertEqual(slip.il_net_amount_to_pay, 5000.0)
        self.assertEqual(payment.state, 'paid')
        self.assertEqual(payment.move_id.state, 'posted')
        self.assertEqual(slip.move_id.state, 'posted')
        self.assertEqual(bank_partial.exists(), bank_partial)
        self.assertEqual(self._financial_snapshot(payment, slip), financial)

    def test_changing_one_payslip_preserves_other_payslip_match(self):
        payment = self._payment(3000.0)
        first, second = self._payslip_with_posted_net(2000), self._payslip_with_posted_net(2000)
        wizard = self._editor(payment=payment)
        self._add(wizard, payment, first, 1000)
        self._add(wizard, payment, second, 1000)
        wizard.action_apply()
        second_partial = second._il_reconciliations()
        wizard = self._editor(slip=first)
        wizard.line_ids.amount = 500
        wizard.action_apply()
        self.assertEqual(second._il_reconciliations(), second_partial)
        self.assertEqual(payment.il_remaining_amount, 1500)
        self.assertEqual(sum(payment.il_split_line_ids.mapped('amount')), payment.amount)

    def test_overallocation_is_atomic(self):
        payment = self._payment(3000.0)
        slip = self._payslip_with_posted_net(2000)
        wizard = self._editor(payment=payment)
        self._add(wizard, payment, slip, 1000)
        wizard.action_apply()
        original_partial = slip._il_reconciliations()
        original_splits = payment.il_split_line_ids.sorted('id').read(
            ['amount', 'reconcile_id', 'sequence'])
        for amount in (2500, 3500):
            wizard = self._editor(payment=payment)
            wizard.line_ids.amount = amount
            with self.assertRaises(ValidationError):
                wizard.action_apply()
            self.assertEqual(slip._il_reconciliations(), original_partial)
            self.assertEqual(payment.il_split_line_ids.sorted('id').read(
                ['amount', 'reconcile_id', 'sequence']), original_splits)
            self.assertEqual(slip.il_net_amount_to_pay, 1000)

    def test_existing_links_remain_editable_and_legacy_approval_is_inert(self):
        payment = self._payment(3000.0)
        bank_partial = self._settle(payment)
        first, second = self._payslip_with_posted_net(1000), self._payslip_with_posted_net(1000)
        wizard = self._editor(slip=first)
        self._add(wizard, payment, first, 1000)
        wizard.action_apply()
        original = first._il_reconciliations()
        original.write({'il_payroll_finalized': True})
        wizard = self._editor(slip=first)
        wizard.line_ids.amount = 600
        wizard.action_apply()
        self.assertFalse(original.exists())
        self.assertEqual(first.il_net_amount_to_pay, 400)
        wizard = self._editor(slip=first)
        wizard.line_ids.amount = 1000
        wizard.action_apply()
        current = first._il_reconciliations()
        self.assertEqual(first.il_net_amount_to_pay, 0)

        wizard = self._editor(payment=payment)
        self._add(wizard, payment, second, 1000)
        wizard.action_apply()
        self.assertEqual(first._il_reconciliations(), current)
        self.assertEqual(payment.il_remaining_amount, 1000)
        self.assertEqual(payment.state, 'paid')
        current.write({'il_payroll_finalized': True})
        current.unlink()
        self.assertEqual(first.il_net_amount_to_pay, 1000)
        self.assertEqual(payment.il_remaining_amount, 2000)
        self.assertEqual(bank_partial.exists(), bank_partial)

    def test_add_candidates_use_open_balance_and_exclude_only_current_payslip_links(self):
        current, other = self._payslip_with_posted_net(5000), self._payslip_with_posted_net(5000)
        already_current, partly_other = self._payment(3000), self._payment(3000)
        exhausted, available, draft = self._payment(1000), self._payment(1000), self._payment(1000, post=False)
        for payment, slip, amount in [
            (already_current, current, 1000),
            (partly_other, other, 1000),
            (exhausted, other, 1000),
        ]:
            editor = self._editor(slip=slip, add_only=True)
            self._add(editor, payment, slip, amount)
            editor.action_apply()
        wizard = self._editor(slip=current, add_only=True)
        self.assertFalse(wizard.line_ids)
        self.assertNotIn(already_current, wizard.available_payment_ids)
        self.assertNotIn(exhausted, wizard.available_payment_ids)
        self.assertNotIn(draft, wizard.available_payment_ids)
        self.assertIn(partly_other, wizard.available_payment_ids)
        self.assertIn(available, wizard.available_payment_ids)
        old_current = current._il_reconciliations()
        self._add(wizard, partly_other, current, 500)
        self.assertEqual(wizard.line_ids.payment_available_amount, 2000)
        wizard.action_apply()
        self.assertEqual(old_current.exists(), old_current)
        self.assertIn(old_current, current._il_reconciliations())
        self.assertEqual(partly_other.il_applied_amount, 1500)

    def test_add_only_rejects_already_linked_payment_and_preserves_existing_rows(self):
        payment = self._payment(3000)
        slip = self._payslip_with_posted_net(3000)
        editor = self._editor(slip=slip, add_only=True)
        self._add(editor, payment, slip, 1000)
        editor.action_apply()
        original = slip._il_reconciliations()
        duplicate = self._editor(slip=slip, add_only=True)
        self._add(duplicate, payment, slip, 500)
        with self.assertRaises(ValidationError):
            duplicate.action_apply()
        self.assertEqual(slip._il_reconciliations(), original)
        self.assertEqual(payment.il_applied_amount, 1000)
        # A new proposal cannot impersonate the existing row after deleting it.
        replacement = self._editor(slip=slip)
        replacement.line_ids.unlink()
        self._add(replacement, payment, slip, 500)
        with self.assertRaises(ValidationError):
            replacement.action_apply()
        self.assertEqual(slip._il_reconciliations(), original)

    def test_add_rechecks_payment_balance_consumed_by_another_payslip(self):
        payment = self._payment(1000)
        current, other = self._payslip_with_posted_net(1000), self._payslip_with_posted_net(1000)
        pending = self._editor(slip=current, add_only=True)
        self.assertIn(payment, pending.available_payment_ids)
        self._add(pending, payment, current, 1000)
        concurrent = self._editor(slip=other, add_only=True)
        self._add(concurrent, payment, other, 1000)
        concurrent.action_apply()
        with self.assertRaises(ValidationError):
            pending.action_apply()
        self.assertFalse(current._il_reconciliations())
        self.assertEqual(other.il_net_amount_to_pay, 0)

    def test_fully_allocated_existing_link_is_editable_but_not_a_new_candidate(self):
        payment = self._payment(1000)
        slip = self._payslip_with_posted_net(1000)
        payment.il_split_line_ids._il_reconcile_with_payslip(slip)
        editor = self._editor(slip=slip)
        self.assertNotIn(payment, editor.available_payment_ids)
        self.assertEqual(editor.line_ids.payment_id, payment)
        editor.line_ids.amount = 500
        editor.action_apply()
        self.assertEqual(slip.il_net_amount_to_pay, 500)
        self.assertEqual(payment.il_remaining_amount, 500)
        self.assertEqual(payment.il_split_line_ids.filtered('reconcile_id').il_linked_payslip_id, slip)

    def test_stale_editor_cannot_overwrite_new_match_or_schedule(self):
        payment = self._payment(3000)
        slip = self._payslip_with_posted_net(3000)
        stale = self._editor(payment=payment)
        current = self._editor(slip=slip)
        self._add(current, payment, slip, 1000)
        current.action_apply()
        self._add(stale, payment, slip, 1500)
        with self.assertRaises(UserError):
            stale.action_apply()
        self.assertEqual(payment.il_applied_amount, 1000)

    def test_native_accounting_match_is_adopted_without_duplicate_partial(self):
        payment = self._payment(3000)
        slip = self._payslip_with_posted_net(1000)
        (payment.move_id.line_ids.filtered(lambda line: line.account_id == self.payable)
         | slip._il_salary_payable_lines()).reconcile()
        old_partial = slip._il_reconciliations()
        self.assertFalse(payment.il_split_line_ids.reconcile_id)
        wizard = self._editor(slip=slip)
        wizard.line_ids.amount = 500
        wizard.action_apply()
        self.assertFalse(old_partial.exists())
        self.assertEqual(len(slip._il_reconciliations()), 1)
        self.assertEqual(payment.il_applied_amount, 500)
        self.assertEqual(payment.il_remaining_amount, 2500)

    def test_wrong_employee_and_duplicate_pair_are_rejected(self):
        payment = self._payment(1000)
        slip = self._payslip_with_posted_net(1000)
        other = self.env['hr.employee'].create({
            'name': 'Other allocation employee',
            'company_id': self.company.id,
            'contract_date_start': date(2026, 1, 1),
            'date_version': date(2026, 1, 1),
            'mdl_wage_type': 'mdl_monthly',
            'structure_type_id': self.monthly_type.id,
            'il_salary_structure_id': self.monthly_structure.id,
            'schedule_pay': 'monthly',
        })
        other_slip = self._payslip_with_posted_net(1000)
        other_slip.employee_id = other
        wizard = self._editor(payment=payment)
        self._add(wizard, payment, other_slip, 100)
        with self.assertRaises(ValidationError):
            wizard.action_apply()
        wizard = self._editor(payment=payment)
        self._add(wizard, payment, slip, 100)
        self._add(wizard, payment, slip, 200)
        with self.assertRaises(ValidationError):
            wizard.action_apply()
        self.assertFalse(payment.il_split_line_ids.reconcile_id)

    def test_draft_journal_is_not_posted_by_allocation_editor(self):
        payment = self._payment(1000, post=False)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self._editor(payment=payment)
        self.assertEqual(payment.state, 'draft')
        self.assertFalse(payment.move_id)

    def test_noop_save_retains_reconciliation_identity(self):
        payment = self._payment(1000)
        slip = self._payslip_with_posted_net(1000)
        payment.il_split_line_ids._il_reconcile_with_payslip(slip)
        partial = slip._il_reconciliations()
        wizard = self._editor(payment=payment)
        wizard.action_apply()
        self.assertEqual(slip._il_reconciliations(), partial)

    def test_accounting_period_lock_prevents_new_payroll_allocation(self):
        payment = self._payment(1000)
        slip = self._payslip_with_posted_net(1000)
        wizard = self._editor(payment=payment)
        self._add(wizard, payment, slip, 1000)
        self._set_hard_lock_date(date(2026, 8, 1))
        with self.assertRaises(UserError):
            wizard.action_apply()
        self.assertFalse(payment.il_split_line_ids.reconcile_id)

    def test_accounting_period_lock_prevents_existing_link_changes_and_native_removal(self):
        payment = self._payment(1000)
        slip = self._payslip_with_posted_net(1000)
        payment.il_split_line_ids._il_reconcile_with_payslip(slip)
        partial = slip._il_reconciliations()
        editor = self._editor(slip=slip)
        editor.line_ids.amount = 500
        self._set_hard_lock_date(date(2026, 8, 1))
        with self.assertRaises(UserError):
            editor.action_apply()
        with self.assertRaises(UserError):
            partial.unlink()
        self.assertEqual(slip._il_reconciliations(), partial)
        self.assertEqual(slip.il_net_amount_to_pay, 0)

    def test_posted_payment_is_matchable_without_using_payment_approval_state(self):
        payment = self._payment(1000)
        payment.state = 'draft'
        slip = self._payslip_with_posted_net(1000)
        wizard = self._editor(payment=payment)
        self._add(wizard, payment, slip, 1000)
        wizard.action_apply()
        self.assertEqual(payment.state, 'draft')
        self.assertEqual(payment.move_id.state, 'posted')
        self.assertEqual(slip.il_net_amount_to_pay, 0)
