from datetime import date, timedelta

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user, tagged

from . import test_payment_reconciliation as payment_fixtures


@tagged('post_install', '-at_install', 'il_payslip_payment_candidates')
class TestPayslipPaymentCandidates(TransactionCase):

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
            'name': 'Candidate Proposal Employee', 'company_id': cls.company.id,
            'contract_date_start': date(2026, 1, 1), 'date_version': date(2026, 1, 1),
            'mdl_wage_type': 'mdl_monthly', 'structure_type_id': cls.monthly_type.id,
            'il_salary_structure_id': cls.monthly_structure.id, 'schedule_pay': 'monthly',
        })
        UserEnv = cls.env(context=dict(cls.env.context, no_reset_password=True))
        cls.other_user = new_test_user(
            UserEnv, login='il_candidate_proposal_other',
            groups='base.group_user,hr_payroll.group_hr_payroll_manager,account.group_account_manager',
            company_id=cls.company.id, company_ids=[Command.set(cls.company.ids)])

    _payment = payment_fixtures.TestEmployeePaymentReconciliation._payment
    _payslip_with_posted_net = payment_fixtures.TestEmployeePaymentReconciliation._payslip_with_posted_net

    _spec = {'id': {}, 'amount': {}, 'il_recognition_available_amount': {},
             'il_payslip_candidate_amount': {}}

    def _open(self, slip):
        action = self.env['account.payment'].with_context(
            il_payslip_id=slip.id).action_il_add_payslip_payment()
        self.assertEqual(action['res_model'], 'account.payment')
        self.assertEqual(action['target'], 'new')
        self.assertTrue(action['context']['edit'])
        Payment = self.env['account.payment'].with_context(**action['context'])
        session = self.env['il.payslip.payment.candidate.session'].browse(
            action['context']['il_payslip_candidate_session_id'])
        return Payment, session, action

    def _save(self, Payment, payment, amount):
        return Payment.browse(payment.id).web_save(
            {'il_payslip_candidate_amount': amount}, self._spec)[0]

    def _financial_values(self, payments, slips):
        return {
            'payments': payments.sorted('id').read([
                'amount', 'date', 'partner_id', 'currency_id', 'state', 'move_id', 'write_date']),
            'moves': (payments.move_id | slips.move_id).sorted('id').read(['state', 'date']),
            'items': (payments.move_id.line_ids | slips.move_id.line_ids).sorted('id').read([
                'debit', 'credit', 'account_id', 'partner_id', 'amount_currency']),
            'salary': slips.line_ids.sorted('id').read(['code', 'amount', 'total']),
        }

    def test_native_row_save_is_proposal_only_and_cancel_requires_no_accounting_change(self):
        slip = self._payslip_with_posted_net(1500.0)
        payment = self._payment(2000.0)
        baseline = self._financial_values(payment, slip)
        partials = self.env['account.partial.reconcile'].search([]).ids
        Payment, session, action = self._open(slip)
        self.assertEqual(Payment.browse(payment.id).il_payslip_candidate_amount, 1500.0)
        result = self._save(Payment, payment, 350.0)
        self.assertEqual(result['il_payslip_candidate_amount'], 350.0)
        self.assertEqual(result['amount'], 2000.0)
        self.assertEqual(self._financial_values(payment, slip), baseline)
        self.assertEqual(self.env['account.partial.reconcile'].search([]).ids, partials)
        self.assertFalse(session.applied)
        # Closing the native popup makes no accounting RPC. Opening it again
        # starts a separate proposal; the saved draft is not a payment link.
        reopened, fresh, _action = self._open(slip)
        self.assertNotEqual(fresh, session)
        self.assertEqual(reopened.browse(payment.id).il_payslip_candidate_amount, 1500.0)
        self.assertEqual(Payment.browse(payment.id).il_payslip_candidate_amount, 350.0)
        self.assertFalse(payment._il_payslip_link_partials())
        self.assertEqual(payment.with_context({}).il_payslip_candidate_amount, 0.0)

    def test_selected_rows_apply_the_saved_amounts_directly_and_ignore_zero(self):
        slip = self._payslip_with_posted_net(1500.0)
        first, second, zero, unselected = (self._payment(value) for value in (2000.0, 800.0, 400.0, 600.0))
        payments = first | second | zero | unselected
        baseline = self._financial_values(payments, slip)
        Payment, session, _action = self._open(slip)
        for payment, amount in ((first, 500.0), (second, 350.0), (zero, 0.0), (unselected, 300.0)):
            self._save(Payment, payment, amount)
        returned = Payment.browse((first | second | zero).ids).action_il_select_payslip_payments()
        self.assertEqual(returned['res_model'], 'account.payment')
        self.assertEqual(returned.get('target', 'current'), 'current')
        self.assertTrue(session.applied)
        self.assertEqual((first.il_applied_amount, second.il_applied_amount), (500.0, 350.0))
        self.assertFalse(zero._il_payslip_link_partials())
        self.assertFalse(unselected._il_payslip_link_partials())
        self.assertEqual(slip.il_net_amount_to_pay, 650.0)
        self.assertEqual(self._financial_values(payments, slip), baseline)
        with self.assertRaises(UserError), self.cr.savepoint():
            Payment.browse(first.id).action_il_select_payslip_payments()

    def test_sessions_are_isolated_and_cannot_be_reused_by_another_user_or_payslip(self):
        slip = self._payslip_with_posted_net(1500.0)
        other_slip = self._payslip_with_posted_net(900.0)
        payment = self._payment(1000.0)
        Payment, session, action = self._open(slip)
        other_session, _session, _other_action = self._open(other_slip)
        self._save(Payment, payment, 250.0)
        self._save(other_session, payment, 450.0)
        self.assertEqual(Payment.browse(payment.id).il_payslip_candidate_amount, 250.0)
        self.assertEqual(other_session.browse(payment.id).il_payslip_candidate_amount, 450.0)
        with self.assertRaises(AccessError), self.cr.savepoint():
            # Even a sudo call cannot bypass the explicit session creator.
            Payment.with_user(self.other_user).sudo().browse(payment.id).write({
                'il_payslip_candidate_amount': 50.0})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            Payment.with_context(il_payslip_id=other_slip.id).browse(payment.id).write({
                'il_payslip_candidate_amount': 50.0})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            session.write({'source_payslip_id': other_slip.id})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            session.line_ids.write({'payment_id': self._payment(200.0).id})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            Payment.browse(payment.id).write({'il_payslip_candidate_amount': 50.0, 'amount': 50.0})
        self.assertEqual(payment.amount, 1000.0)
        self.assertFalse(payment._il_payslip_link_partials())

    def test_expired_and_out_of_session_selection_are_rejected(self):
        slip = self._payslip_with_posted_net(1500.0)
        payment = self._payment(1000.0)
        Payment, session, _action = self._open(slip)
        later_payment = self._payment(300.0)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            Payment.browse(later_payment.id).action_il_select_payslip_payments()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self._save(Payment, later_payment, 150.0)
        self.env.cr.execute(
            'UPDATE il_payslip_payment_candidate_session SET create_date = %s WHERE id = %s',
            [fields.Datetime.now() - timedelta(hours=3), session.id])
        session.invalidate_recordset(['create_date'])
        with self.assertRaises(UserError), self.cr.savepoint():
            Payment.browse(payment.id).action_il_select_payslip_payments()
        self.assertFalse(payment._il_payslip_link_partials())

    def test_stale_payment_and_stale_payslip_cannot_apply_old_proposals(self):
        slip = self._payslip_with_posted_net(1500.0)
        other_slip = self._payslip_with_posted_net(500.0)
        payment = self._payment(1000.0)
        other_payment = self._payment(250.0)
        Payment, _session, _action = self._open(slip)
        self._save(Payment, payment, 350.0)
        self.env['account.payment.split.line']._il_take_open_amount(
            payment, 100.0)._il_reconcile_with_payslip(other_slip)
        with self.assertRaises(UserError), self.cr.savepoint():
            Payment.browse(payment.id).action_il_select_payslip_payments()
        self.assertEqual(payment.il_applied_amount, 100.0)
        self.assertEqual(slip.il_net_amount_to_pay, 1500.0)
        fresh, _fresh_session, _fresh_action = self._open(slip)
        self._save(fresh, payment, 350.0)
        other_payment.il_split_line_ids._il_reconcile_with_payslip(slip)
        with self.assertRaises(UserError), self.cr.savepoint():
            fresh.browse(payment.id).action_il_select_payslip_payments()
        self.assertEqual(payment.il_applied_amount, 100.0)
        self.assertEqual(slip.il_net_amount_to_pay, 1250.0)

    def test_invalid_and_over_capacity_selection_leave_every_link_unchanged(self):
        slip = self._payslip_with_posted_net(600.0)
        first, second = self._payment(800.0), self._payment(500.0)
        Payment, session, _action = self._open(slip)
        for amount in (-1.0, 801.0, float('inf'), float('nan')):
            with self.assertRaises(ValidationError), self.cr.savepoint():
                self._save(Payment, first, amount)
        self._save(Payment, first, 500.0)
        self._save(Payment, second, 200.0)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            Payment.browse((first | second).ids).action_il_select_payslip_payments()
        self.assertFalse((first | second).il_split_line_ids.reconcile_id)
        self.assertFalse(session.applied)
        self._save(Payment, first, 0.0)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            Payment.browse(first.id).action_il_select_payslip_payments()
        self._save(Payment, first, 300.0)
        Payment.browse((first | second).ids).action_il_select_payslip_payments()
        self.assertEqual((first.il_applied_amount, second.il_applied_amount), (300.0, 200.0))
        self.assertEqual(slip.il_net_amount_to_pay, 100.0)
