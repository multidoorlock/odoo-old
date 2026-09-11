from datetime import date

from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged

from . import test_payment_reconciliation as payment_fixtures


@tagged('post_install', '-at_install', 'l10n_il_hr_payroll_account_split_editor')
class TestEmployeePaymentSplitEditor(TransactionCase):
    """Confirmation repairs immediate drafts; explicit schedules stay explicit."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.env['hr.payroll.structure']._il_ensure_payroll_accounting_configuration(
            overwrite=True)
        cls.payable = cls.company.il_employee_payment_debit_account_id
        cls.outstanding = cls.company.il_employee_payment_credit_account_id
        cls.expense = cls.env['account.account'].search([
            ('company_ids', 'in', cls.company.id),
            ('account_type', '=', 'expense'),
        ], limit=1)
        cls.bank_journal = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id),
            ('type', 'in', ('bank', 'cash')),
        ], limit=1)
        cls.general_journal = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id),
            ('type', '=', 'general'),
        ], limit=1)
        cls.monthly_type = cls.env.ref(
            'l10n_il_hr_payroll_account.hr_payroll_structure_type_il')
        cls.monthly_structure = cls.env.ref(
            'l10n_il_hr_payroll_account.hr_payroll_structure_il')
        cls.monthly_structure.journal_id = cls.general_journal
        if not cls.general_journal.default_account_id:
            cls.general_journal.default_account_id = cls.expense
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Split Editor Employee',
            'company_id': cls.company.id,
            'contract_date_start': date(2026, 1, 1),
        })
        cls.employee.version_id.write({
            'structure_type_id': cls.monthly_type.id,
            'il_salary_structure_id': cls.monthly_structure.id,
            'schedule_pay': 'monthly',
        })

    # Reuse record factories without inheriting and rerunning the entire suite.
    _payment = payment_fixtures.TestEmployeePaymentReconciliation._payment
    _payslip_with_posted_net = (
        payment_fixtures.TestEmployeePaymentReconciliation._payslip_with_posted_net)

    def test_confirm_immediate_payment_restores_missing_split(self):
        payment = self._payment(250.0, post=False)
        payment.il_split_line_ids.with_context(
            il_system_split_unlink=True).unlink()
        self.assertFalse(payment.il_split_line_ids)

        payment.action_post()

        self.assertEqual(payment.state, 'in_process')
        self.assertEqual(payment.move_id.state, 'posted')
        self.assertEqual(len(payment.il_split_line_ids), 1)
        self.assertEqual(payment.il_split_line_ids.amount, 250.0)
        self.assertEqual(payment.amount, 250.0)
        self.assertFalse(payment.il_split_line_ids.reconcile_id)

    def test_confirm_repairs_stale_free_immediate_amount(self):
        payment = self._payment(250.0, post=False)
        split = payment.il_split_line_ids
        split.with_context(il_sync_from_payment=True).amount = 100.0
        self.assertEqual(payment.amount, 250.0)

        payment.action_post()

        self.assertEqual(payment.il_split_line_ids, split)
        self.assertEqual(split.amount, 250.0)
        self.assertEqual(payment.amount, 250.0)

    def test_confirmation_does_not_invent_planned_instalments(self):
        payment = self._payment(250.0, post=False)
        payment.write({
            'il_spread_type': 'planned',
            'il_split_line_ids': [
                Command.clear(), Command.create({'amount': 250.0}),
            ],
        })
        payment.il_split_line_ids.unlink()

        with self.assertRaises(ValidationError), self.cr.savepoint():
            payment.action_post()

        self.assertEqual(payment.state, 'draft')
        self.assertFalse(payment.il_split_line_ids)

    def test_immediate_repair_preserves_reconciled_allocation(self):
        payment = self._payment(1000.0, post=False)
        allocated = payment.il_split_line_ids
        allocated.with_context(il_sync_from_payment=True).amount = 400.0
        free = self.env['account.payment.split.line'].with_context(
            il_system_split_create=True).create({
                'payment_id': payment.id, 'amount': 600.0,
            })
        payment.action_post()
        slip = self._payslip_with_posted_net(400.0)
        allocated._il_reconcile_with_payslip(slip)
        reconciliation = allocated.reconcile_id
        payment.action_draft()
        free.with_context(il_system_split_unlink=True).unlink()

        payment._il_sync_immediate_split_before_post()

        self.assertEqual(allocated.reconcile_id, reconciliation)
        self.assertTrue(reconciliation.exists())
        self.assertEqual(allocated.amount, 400.0)
        self.assertEqual(slip.il_net_amount_to_pay, 0.0)
        self.assertEqual(len(payment.il_split_line_ids), 2)
        self.assertEqual((payment.il_split_line_ids - allocated).amount, 600.0)
        self.assertEqual(payment.amount, 1000.0)
        split_ids = payment.il_split_line_ids.ids
        payment._il_sync_immediate_split_before_post()
        self.assertEqual(payment.il_split_line_ids.ids, split_ids)

    def test_immediate_repair_preserves_pending_target(self):
        payment = self._payment(1000.0, post=False)
        split = payment.il_split_line_ids
        split.with_context(il_sync_from_payment=True).amount = 400.0
        slip = self._payslip_with_posted_net(400.0)
        target = slip._il_salary_payable_lines()
        split.il_pending_payslip_move_line_id = target

        payment._il_sync_immediate_split_before_post()

        self.assertEqual(split.amount, 400.0)
        self.assertEqual(split.il_pending_payslip_move_line_id, target)
        self.assertEqual((payment.il_split_line_ids - split).amount, 600.0)
        self.assertEqual(payment.amount, 1000.0)
