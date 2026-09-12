from datetime import date

from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged

from . import test_payment_reconciliation as payment_fixtures
from . import test_reconciliation_editor as editor_fixtures


@tagged('post_install', '-at_install', 'il_payroll_link_coalescing')
class TestPayrollLinkCoalescing(TransactionCase):

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
            'name': 'Single Logical Payment Link Employee', 'company_id': cls.company.id,
            'contract_date_start': date(2026, 1, 1), 'date_version': date(2026, 1, 1),
            'mdl_wage_type': 'mdl_monthly', 'structure_type_id': cls.monthly_type.id,
            'il_salary_structure_id': cls.monthly_structure.id, 'schedule_pay': 'monthly',
        })

    _payment = payment_fixtures.TestEmployeePaymentReconciliation._payment
    _payslip_with_posted_net = payment_fixtures.TestEmployeePaymentReconciliation._payslip_with_posted_net
    _settle = editor_fixtures.TestPayrollReconciliationEditor._settle
    _editor = editor_fixtures.TestPayrollReconciliationEditor._editor
    _add = editor_fixtures.TestPayrollReconciliationEditor._add
    _financial_snapshot = editor_fixtures.TestPayrollReconciliationEditor._financial_snapshot

    def _edit_amount(self, payment, slip, amount):
        payment = payment.with_context(il_payslip_id=slip.id)
        payment._il_update_payslip_link(amount, payment._il_payslip_link_token(slip))

    def _linked_rows(self, payment, slip):
        return payment.il_split_line_ids.filtered(
            lambda line: line.reconcile_id.credit_move_id.il_payslip_id == slip)

    def _assert_one_link(self, payment, slip, amount):
        rows = self._linked_rows(payment, slip)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.amount, amount)
        self.assertEqual(len(rows.reconcile_id), 1)
        self.assertEqual(rows.reconcile_id.debit_amount_currency, amount)

    def test_immediate_500_to_400_to_500_remains_one_link_and_preserves_bank(self):
        payment = self._payment(500.0)
        bank = self._settle(payment)
        slip = self._payslip_with_posted_net(500.0)
        payment.il_split_line_ids._il_reconcile_with_payslip(slip)
        financial = self._financial_snapshot(payment, slip)
        bank_values = bank.read(['amount', 'debit_move_id', 'credit_move_id'])
        self._edit_amount(payment, slip, 400.0)
        self._assert_one_link(payment, slip, 400.0)
        self.assertEqual(payment.il_split_line_ids.filtered(lambda row: not row.reconcile_id).amount, 100.0)
        self._edit_amount(payment, slip, 500.0)
        self._assert_one_link(payment, slip, 500.0)
        self.assertEqual(len(payment.il_split_line_ids), 1)
        self.assertEqual(payment.state, 'paid')
        self.assertEqual(slip.il_net_amount_to_pay, 0.0)
        self.assertEqual(self._financial_snapshot(payment, slip), financial)
        self.assertEqual(bank.read(['amount', 'debit_move_id', 'credit_move_id']), bank_values)

    def test_planned_chunks_coalesce_without_changing_future_rows_or_other_payslip(self):
        payment = self._payment(2500.0, post=False)
        payment.write({'il_spread_type': 'planned', 'il_split_line_ids': [
            Command.clear(), *(Command.create({'amount': amount}) for amount in (400.0, 100.0, 300.0, 700.0, 1000.0)),
        ]})
        payment.action_post()
        slip = self._payslip_with_posted_net(500.0)
        other = self._payslip_with_posted_net(300.0)
        other_row = payment.il_split_line_ids.filtered(lambda row: row.amount == 300.0)
        other_row._il_reconcile_with_payslip(other)
        other_partial = other_row.reconcile_id
        future = payment.il_split_line_ids.filtered(lambda row: row.amount in (700.0, 1000.0))
        future_values = [(line.id, line.amount, line.il_pending_payslip_move_line_id.id) for line in future]
        other_values = (other.state, other.il_net_amount_to_pay)
        wizard = self._editor(slip=slip)
        self._add(wizard, payment, slip, 500.0)
        wizard.action_apply()
        self._assert_one_link(payment, slip, 500.0)
        self._edit_amount(payment, slip, 400.0)
        self._edit_amount(payment, slip, 500.0)
        self._assert_one_link(payment, slip, 500.0)
        self.assertEqual([(line.id, line.amount, line.il_pending_payslip_move_line_id.id) for line in future],
                         future_values)
        self.assertEqual(other_row.reconcile_id, other_partial)
        self.assertEqual((other.state, other.il_net_amount_to_pay), other_values)
        self.assertEqual(payment.amount, 2500.0)
        self.assertEqual(payment.il_remaining_amount, 1700.0)
        self.assertEqual(payment.il_split_line_ids.mapped('sequence'), [1, 2, 3, 4])

    def _duplicate_fixture(self):
        payment = self._payment(800.0)
        bank = self._settle(payment)
        slip = self._payslip_with_posted_net(500.0)
        other = self._payslip_with_posted_net(300.0)
        Split = self.env['account.payment.split.line']
        for amount, target in ((400.0, slip), (100.0, slip), (300.0, other)):
            Split._il_take_open_amount(payment, amount)._il_reconcile_with_payslip(target)
        (slip | other)._il_sync_paid_state_from_balance()
        self.assertEqual(len(self._linked_rows(payment, slip)), 2)
        return payment, slip, other, bank

    def test_guarded_repair_consolidates_only_requested_pair_with_same_total(self):
        payment, slip, other, bank = self._duplicate_fixture()
        old_pair = self._linked_rows(payment, slip).reconcile_id
        retained = self._linked_rows(payment, other)
        retained_partial = retained.reconcile_id
        states = (slip | other).read(['state', 'il_net_amount_to_pay'])
        bank_values = bank.read(['amount', 'debit_move_id', 'credit_move_id'])
        financial = self._financial_snapshot(payment, slip)
        self._editor(slip=slip)._il_rebuild_duplicate_link(payment)
        self._assert_one_link(payment, slip, 500.0)
        self.assertFalse(old_pair.exists())
        self.assertEqual(retained.reconcile_id, retained_partial)
        self.assertEqual((slip | other).read(['state', 'il_net_amount_to_pay']), states)
        self.assertEqual(self._financial_snapshot(payment, slip), financial)
        self.assertEqual(bank.read(['amount', 'debit_move_id', 'credit_move_id']), bank_values)
        self.assertEqual(payment.state, 'paid')
        # A second run is a no-op, preserving the new native match identity.
        current = self._linked_rows(payment, slip).reconcile_id
        self._editor(slip=slip)._il_rebuild_duplicate_link(payment)
        self.assertEqual(self._linked_rows(payment, slip).reconcile_id, current)

    def test_guarded_repair_obeys_native_period_lock(self):
        payment, slip, other, bank = self._duplicate_fixture()
        old_pair = self._linked_rows(payment, slip).reconcile_id
        self.company.write({'hard_lock_date': date(2026, 8, 1)})
        with self.assertRaises(UserError), self.cr.savepoint():
            self._editor(slip=slip)._il_rebuild_duplicate_link(payment)
        self.assertEqual(self._linked_rows(payment, slip).reconcile_id, old_pair)
        self.assertEqual(payment.amount, 800.0)

    def _native_duplicate_pair(self, multiple_credit_items=False, foreign_currency=False):
        payment = self._payment(500.0)
        slip = self._payslip_with_posted_net(500.0)
        currency = self.company.currency_id
        if foreign_currency:
            currency = self.env.ref('base.USD')
            if currency == self.company.currency_id:
                currency = self.env.ref('base.EUR')
            currency.active = True
        amounts = (400.0, 100.0) if multiple_credit_items else (500.0,)
        credit_commands = [Command.create({
            'name': 'Native salary payable', 'account_id': self.payable.id,
            'partner_id': payment.partner_id.id, 'credit': amount,
            'currency_id': currency.id,
            'amount_currency': -amount / 10.0 if foreign_currency else -amount,
            'il_payslip_id': slip.id,
        }) for amount in amounts]
        move = self.env['account.move'].create({
            'journal_id': self.general_journal.id, 'date': date(2026, 7, 31),
            'line_ids': [Command.create({'name': 'Native salary expense',
                                         'account_id': self.expense.id, 'debit': 500.0}),
                         *credit_commands],
        })
        move.action_post()
        slip.move_id = move
        debit = payment._il_recognition_items()
        credits = move.line_ids.filtered('il_payslip_id').sorted('id')
        values = []
        for index, amount in enumerate((400.0, 100.0)):
            credit = credits[index] if multiple_credit_items else credits
            values.append({'debit_move_id': debit.id, 'credit_move_id': credit.id,
                           'amount': amount, 'debit_amount_currency': amount,
                           'credit_amount_currency': amount / 10.0 if foreign_currency else amount})
        partials = self.env['account.partial.reconcile'].create(values)
        return payment, slip, partials

    def test_repair_refuses_native_matches_across_multiple_journal_items(self):
        payment, slip, partials = self._native_duplicate_pair(multiple_credit_items=True)
        before = partials.read(['amount', 'debit_move_id', 'credit_move_id'])
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self._editor(slip=slip)._il_rebuild_duplicate_link(payment)
        self.assertEqual(partials.read(['amount', 'debit_move_id', 'credit_move_id']), before)
        self.assertEqual(len(partials.credit_move_id), 2)

    def test_repair_refuses_foreign_currency_matches_without_replacing_partials(self):
        payment, slip, partials = self._native_duplicate_pair(foreign_currency=True)
        before = partials.read(['amount', 'debit_amount_currency', 'credit_amount_currency',
                                'debit_move_id', 'credit_move_id'])
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self._editor(slip=slip)._il_rebuild_duplicate_link(payment)
        self.assertEqual(partials.read(['amount', 'debit_amount_currency', 'credit_amount_currency',
                                       'debit_move_id', 'credit_move_id']), before)
        self.assertNotEqual(partials.credit_move_id.currency_id, self.company.currency_id)
