import ast
from datetime import date
from unittest.mock import patch

from lxml import etree
from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user, tagged
from odoo.tools import convert_file, file_open

from . import test_payment_reconciliation as fixtures


@tagged('post_install', '-at_install', 'il_final_payroll_batch')
class TestLegacyPayrollBatchViewUpgrade(TransactionCase):
    def test_legacy_batch_form_is_replaced_before_new_sibling_is_validated(self):
        """Replay the native update path that failed upgrading from 1.4.28.

        A valid final registry alone misses this failure: Odoo validates all
        batch-form siblings while importing the new payslip-run origin view.
        Restore the retired field from the old sibling without asking the new
        model to accept it, then load the affected files in manifest order.
        """
        module = 'l10n_il_hr_payroll_account'
        env = self.env(context=dict(self.env.context, lang='en_US'))
        legacy = env.ref(module + '.view_batch_payment_form_il_cycle')
        self.assertNotIn('il_grouped_payment_view_id', env['account.batch.payment']._fields)
        old_arch = '''<data>
            <field name="batch_type" position="after">
                <field name="il_grouped_payment_view_id" invisible="1"/>
            </field>
        </data>'''
        env.cr.execute(
            "UPDATE ir_ui_view SET arch_db = jsonb_build_object('en_US', %s::text) WHERE id = %s",
            [old_arch, legacy.id])
        env.invalidate_all()
        env.registry.clear_cache()
        with self.assertRaisesRegex(ValidationError, 'il_grouped_payment_view_id'), env.cr.savepoint():
            legacy._check_xml()

        with file_open(module + '/__manifest__.py', 'r') as source:
            manifest = ast.literal_eval(source.read())
        affected_files = {'views/payment_cycle_views.xml', 'views/hr_payslip_run_views.xml'}
        sequence = [path for path in manifest['data'] if path in affected_files]
        self.assertEqual(set(sequence), affected_files)
        documents = ('account.payment', 'account.batch.payment', 'hr.payslip',
                     'account.move', 'account.partial.reconcile')
        before = {model: env[model].search_count([]) for model in documents}
        for path in sequence:
            convert_file(env, module, path, {}, mode='update', noupdate=False)

        legacy = env.ref(module + '.view_batch_payment_form_il_cycle')
        self.assertNotIn('il_grouped_payment_view_id', legacy.arch_db)
        legacy._check_xml()
        origin = env.ref(module + '.view_batch_payment_form_payslip_run_origin')
        origin._check_xml()
        arch = origin._get_combined_arch()
        self.assertTrue(arch.xpath("//field[@name='il_payslip_run_id']"))
        self.assertFalse(arch.xpath("//field[@name='il_grouped_payment_view_id']"))
        self.assertEqual({model: env[model].search_count([]) for model in documents}, before)


@tagged('post_install', '-at_install', 'il_final_payroll_batch')
class TestFinalPayrollBatch(TransactionCase):
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
            ('company_id', '=', cls.company.id), ('type', '=', 'bank')], limit=1)
        cls.general_journal = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id), ('type', '=', 'general')], limit=1)
        if not cls.general_journal.default_account_id:
            cls.general_journal.default_account_id = cls.expense
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Final salary review employee', 'company_id': cls.company.id,
            'contract_date_start': date(2026, 1, 1), 'date_version': date(2026, 1, 1),
            'mdl_wage_type': 'mdl_monthly', 'schedule_pay': 'monthly',
            'structure_type_id': cls.env.ref(
                'l10n_il_hr_payroll_account.hr_payroll_structure_type_il').id,
            'il_salary_structure_id': cls.env.ref(
                'l10n_il_hr_payroll_account.hr_payroll_structure_il').id,
        })

    _payment = fixtures.TestEmployeePaymentReconciliation._payment
    _payslip_with_posted_net = fixtures.TestEmployeePaymentReconciliation._payslip_with_posted_net

    def _run(self, slips):
        return self.env['hr.payslip.run'].create({
            'name': 'Final July 2026', 'company_id': self.company.id,
            'date_start': date(2026, 7, 1), 'date_end': date(2026, 7, 31),
            'slip_ids': [Command.set(slips.ids)],
        })

    def _open(self, run):
        action = run.action_il_pay()
        self.assertEqual((action['res_model'], action['target']),
                         ('il.payslip.run.payment.wizard', 'new'))
        wizard = self.env[action['res_model']].browse(action['res_id'])
        wizard.journal_id = self.bank_journal
        wizard.payment_method_line_id = self.bank_journal._get_available_payment_method_lines('outbound')[:1]
        return wizard

    def _counts(self):
        return tuple(self.env[m].search_count([]) for m in (
            'account.payment', 'account.batch.payment', 'account.move', 'account.partial.reconcile'))

    def test_review_shows_actual_residual_and_cancel_creates_no_payments(self):
        slip = self._payslip_with_posted_net(700.0)
        advance = self._payment(200.0)
        advance.il_split_line_ids._il_reconcile_with_payslip(slip)
        run = self._run(slip)
        before = self._counts()
        wizard = self._open(run)
        self.assertEqual(self._counts(), before)
        self.assertEqual(wizard.total_amount, 500.0)
        self.assertEqual(wizard.line_ids.amount, 500.0)
        self.assertEqual(wizard.line_ids.net_wage, 700.0)
        self.assertIn(run.name, wizard.memo)
        self.assertIn('סגירת שכר סופי', wizard.memo)
        arch = etree.fromstring(wizard.get_views([(False, 'form')])['views']['form']['arch'])
        self.assertTrue(arch.xpath("//footer/button[@name='action_confirm']"))
        self.assertTrue(arch.xpath("//footer/button[@special='cancel']"))
        self.assertEqual(arch.xpath("//field[@name='line_ids']/list/@create"), ['0'])
        self.assertEqual(arch.xpath("//field[@name='line_ids']/list/field[@sum]/@name"), ['net_wage', 'amount'])
        wizard.unlink()
        self.assertEqual(self._counts(), before)
        self.assertEqual(slip.il_net_amount_to_pay, 500.0)

    def test_confirm_creates_one_batch_with_memo_and_closes_only_remaining_salary(self):
        first, second = self._payslip_with_posted_net(700.0), self._payslip_with_posted_net(300.0)
        advance = self._payment(200.0)
        advance.il_split_line_ids._il_reconcile_with_payslip(first)
        existing_partial = advance.il_split_line_ids.reconcile_id
        old_partial = existing_partial.read(['amount', 'debit_move_id', 'credit_move_id'])
        salary = (first | second).line_ids.read(['code', 'amount', 'quantity', 'rate', 'total'])
        move_lines = (first | second).move_id.line_ids.read(['account_id', 'debit', 'credit'])
        run = self._run(first | second)
        wizard = self._open(run)
        wizard.write({'name': 'July closing batch', 'memo': 'סגירת שכר סופי — יולי 2026'})
        action = wizard.action_confirm()
        batch = self.env['account.batch.payment'].browse(action['res_id'])
        self.assertEqual(action['res_model'], 'account.batch.payment')
        self.assertEqual(batch.il_payslip_run_id, run)
        self.assertEqual(batch.name, 'July closing batch')
        self.assertEqual(len(batch.payment_ids), 2)
        self.assertEqual(sorted(batch.payment_ids.mapped('amount')), [300.0, 500.0])
        self.assertEqual(set(batch.payment_ids.mapped('memo')), {wizard.memo})
        self.assertEqual(set(batch.payment_ids.mapped('state')), {'in_process'})
        self.assertFalse(any(batch.payment_ids.mapped('is_sent')))
        self.assertTrue(batch.il_is_employee_batch)
        self.assertEqual(batch.state, 'draft')
        self.assertEqual((first | second).mapped('il_net_amount_to_pay'), [0.0, 0.0])
        self.assertEqual(set((first | second).mapped('state')), {'paid'})
        self.assertEqual(existing_partial.read(['amount', 'debit_move_id', 'credit_move_id']), old_partial)
        self.assertEqual((first | second).line_ids.read(['code', 'amount', 'quantity', 'rate', 'total']), salary)
        self.assertEqual((first | second).move_id.line_ids.read(['account_id', 'debit', 'credit']), move_lines)
        grouped = batch.action_il_open_grouped_payments()
        self.assertEqual(grouped['domain'], [('batch_payment_id', '=', batch.id)])
        self.assertEqual(grouped['context']['group_by'], ['il_employee_id'])
        created = self._counts()
        batch.validate_batch()
        self.assertTrue(all(batch.payment_ids.mapped('is_sent')))
        self.assertEqual(self._counts(), created)

    def test_repeat_click_and_second_open_review_cannot_duplicate_payment(self):
        run = self._run(self._payslip_with_posted_net(500.0))
        first, second = self._open(run), self._open(run)
        action = first.action_confirm()
        after = self._counts()
        self.assertEqual(first.action_confirm()['res_id'], action['res_id'])
        self.assertEqual(self._counts(), after)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            second.action_confirm()
        self.assertEqual(self._counts(), after)

    def test_changed_residual_rejects_stale_review_without_creating_documents(self):
        slip = self._payslip_with_posted_net(500.0)
        wizard = self._open(self._run(slip))
        other_payment = self._payment(100.0)
        other_payment.il_split_line_ids._il_reconcile_with_payslip(slip)
        before = self._counts()
        with self.assertRaises(UserError), self.cr.savepoint():
            wizard.action_confirm()
        self.assertEqual(self._counts(), before)
        self.assertEqual(slip.il_net_amount_to_pay, 400.0)

    def test_draft_target_reservation_prevents_duplicate_final_salary(self):
        slip = self._payslip_with_posted_net(500.0)
        draft = self._payment(500.0, post=False)
        draft.il_split_line_ids.with_context(il_reconciliation_sync=True).write({
            'il_pending_payslip_move_line_id': slip._il_salary_payable_lines().id})
        before = self._counts()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self._open(self._run(slip))
        self.assertEqual(self._counts(), before)
        self.assertEqual(draft.state, 'draft')

    def test_second_payment_failure_rolls_back_whole_creation(self):
        run = self._run(self._payslip_with_posted_net(500.0) | self._payslip_with_posted_net(300.0))
        wizard = self._open(run)
        before = self._counts()
        payment_class = type(self.env['account.payment'])
        original = payment_class.action_post
        calls = []
        def failing_second(payments):
            calls.append(payments.ids)
            if len(calls) == 2:
                raise ValidationError('Simulated second payment failure')
            return original(payments)
        with patch.object(payment_class, 'action_post', failing_second):
            with self.assertRaises(ValidationError):
                wizard.action_confirm()
        self.assertEqual(self._counts(), before)
        self.assertEqual(sorted(run.slip_ids.mapped('il_net_amount_to_pay')), [300.0, 500.0])
        self.assertFalse(wizard.batch_id)

    def test_review_requires_payroll_access_and_protects_source_values(self):
        run = self._run(self._payslip_with_posted_net(500.0))
        wizard = self._open(run)
        before = self._counts()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            wizard.line_ids.write({'amount': 400.0})
        user = new_test_user(self.env(context=dict(self.env.context, no_reset_password=True)),
            login='final_payroll_accounting_only', groups='base.group_user,account.group_account_manager',
            company_id=self.company.id, company_ids=[Command.set(self.company.ids)])
        with self.assertRaises(AccessError), self.cr.savepoint():
            run.with_user(user).action_il_pay()
        self.assertEqual(self._counts(), before)
