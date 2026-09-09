from datetime import date

from odoo import Command, fields
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'l10n_il_hr_payroll_account_payment_reconciliation')
class TestEmployeePaymentReconciliation(TransactionCase):

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
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Residual Payment Employee',
            'company_id': cls.company.id,
            'contract_date_start': date(2026, 1, 1),
            'structure_type_id': cls.monthly_type.id,
            'il_salary_structure_id': cls.monthly_structure.id,
        })

    def _payslip_with_posted_net(self, amount):
        slip = self.env['hr.payslip'].create({
            'name': 'Residual Test Payslip',
            'employee_id': self.employee.id,
            'company_id': self.company.id,
            'date_from': date(2026, 7, 1),
            'date_to': date(2026, 7, 31),
        })
        move = self.env['account.move'].create({
            'journal_id': self.general_journal.id,
            'date': date(2026, 7, 31),
            'line_ids': [
                Command.create({
                    'name': 'Salary expense',
                    'account_id': self.expense.id,
                    'debit': amount,
                    'credit': 0.0,
                }),
                Command.create({
                    'name': 'NET',
                    'account_id': self.payable.id,
                    'partner_id': self.employee.work_contact_id.id,
                    'debit': 0.0,
                    'credit': amount,
                    'il_payslip_id': slip.id,
                }),
            ],
        })
        move.action_post()
        slip.write({
            'move_id': move.id,
            'state': 'validated',
            'done_date': fields.Datetime.now(),
            'net_wage': amount,
        })
        return slip

    def _payment(self, amount, origin_slip=None, post=True):
        context = {'il_employee_payment': True}
        if origin_slip:
            context['il_origin_payslip_id'] = origin_slip.id
        payment = self.env['account.payment'].with_context(**context).create({
            'partner_id': self.employee.work_contact_id.id,
            'company_id': self.company.id,
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'journal_id': self.bank_journal.id,
            'date': date(2026, 8, 1),
            'amount': amount,
        })
        if post:
            payment.with_context(**context).action_post()
        return payment

    def test_employee_payment_is_saved_as_draft_with_native_confirm_button(self):
        payment = self._payment(1200.0, post=False)
        self.assertEqual(payment.state, 'draft')
        view = self.env.ref(
            'l10n_il_hr_payroll_account.view_account_payment_form_employee')
        architecture = view._get_combined_arch()
        confirm_buttons = architecture.xpath(
            "//header/button[@name='action_post']")
        self.assertTrue(confirm_buttons)
        self.assertEqual(confirm_buttons[0].get('invisible'), "state != 'draft'")

    def test_payment_creates_one_full_two_line_journal_entry(self):
        payment = self._payment(12000.0)
        self.assertEqual(payment.state, 'in_process')
        self.assertEqual(payment.move_id.state, 'posted')
        self.assertEqual(len(payment.move_id.line_ids), 2)
        debit = payment.move_id.line_ids.filtered(
            lambda line: line.account_id == self.payable)
        credit = payment.move_id.line_ids.filtered(
            lambda line: line.account_id == self.outstanding)
        self.assertEqual(debit.debit, 12000.0)
        self.assertEqual(credit.credit, 12000.0)
        self.assertEqual(payment.move_id.origin_payment_id, payment)

    def test_employee_payment_with_cash_credit_stops_in_process(self):
        cash_account = self.bank_journal.default_account_id
        self.assertEqual(cash_account.account_type, 'asset_cash')
        self.company.il_employee_payment_credit_account_id = cash_account

        payment = self._payment(1200.0)

        self.assertEqual(payment.state, 'in_process')
        self.assertEqual(payment.move_id.state, 'posted')
        view = self.env.ref(
            'l10n_il_hr_payroll_account.view_account_payment_form_employee')
        validate_button = view._get_combined_arch().xpath(
            "//header/button[@name='action_validate']")[0]
        self.assertIn('il_is_employee_payment', validate_button.get('invisible'))
        payment.action_validate()
        self.assertEqual(payment.state, 'paid')

    def test_partial_then_multiple_payments_derive_residual_and_state(self):
        slip = self._payslip_with_posted_net(9000.0)
        first = self._payment(3000.0)
        (slip._il_salary_payable_lines() | first.move_id.line_ids.filtered(
            lambda line: line.account_id == self.payable)).reconcile()
        self.assertEqual(slip.il_net_amount_to_pay, 6000.0)
        self.assertEqual(slip.state, 'validated')
        self.assertEqual(slip._il_affecting_payments(), first)

        second = self._payment(6000.0)
        (slip._il_salary_payable_lines() | second.move_id.line_ids.filtered(
            lambda line: line.account_id == self.payable)).reconcile()
        self.assertEqual(slip.il_net_amount_to_pay, 0.0)
        self.assertEqual(slip.state, 'paid')
        self.assertEqual(slip.il_payment_count, 2)

        partial = slip._il_salary_payable_lines().matched_debit_ids.filtered(
            lambda item: item.debit_move_id.payment_id == second)
        partial.unlink()
        self.assertEqual(slip.il_net_amount_to_pay, 6000.0)
        self.assertEqual(slip.state, 'validated')
        self.assertEqual(first.move_id.state, 'posted')
        self.assertEqual(second.move_id.state, 'posted')

    def test_one_payment_can_reconcile_multiple_payslips(self):
        first = self._payslip_with_posted_net(4000.0)
        second = self._payslip_with_posted_net(6000.0)
        payment = self._payment(10000.0)
        payment_line = payment.move_id.line_ids.filtered(
            lambda line: line.account_id == self.payable)
        (first._il_salary_payable_lines()
         | second._il_salary_payable_lines()
         | payment_line).reconcile()
        self.assertEqual(first.il_net_amount_to_pay, 0.0)
        self.assertEqual(second.il_net_amount_to_pay, 0.0)
        self.assertEqual(first.state, 'paid')
        self.assertEqual(second.state, 'paid')

    def test_pay_button_context_reconciles_without_direct_link(self):
        slip = self._payslip_with_posted_net(2500.0)
        payment = self._payment(2500.0, origin_slip=slip)
        self.assertEqual(slip.il_net_amount_to_pay, 0.0)
        self.assertEqual(slip.state, 'paid')
        self.assertEqual(slip._il_affecting_payments(), payment)
        self.assertNotIn('account.payment.split.line', self.env.registry.models)

    def test_employee_payment_view_has_no_split_mechanism(self):
        view = self.env.ref(
            'l10n_il_hr_payroll_account.view_account_payment_form_employee')
        architecture = view._get_combined_arch()
        serialized = str(architecture)
        self.assertNotIn('il_split', serialized)
        self.assertNotIn('il_spread', serialized)
        self.assertNotIn('il_payroll', serialized)

    def test_multiple_cycle_types_create_one_batch_with_native_lines(self):
        other_employee = self.env['hr.employee'].create({
            'name': 'Second Cycle Employee',
            'company_id': self.company.id,
            'contract_date_start': date(2026, 1, 1),
            'structure_type_id': self.monthly_type.id,
            'il_salary_structure_id': self.monthly_structure.id,
        })
        first_type, second_type, paid_type, canceled_type = self.env[
            'il.payment.cycle.type'
        ].create([
            {'name': 'Advance', 'payment_state': 'in_process'},
            {'name': 'Allowance', 'payment_state': 'draft'},
            {'name': 'Paid Bonus', 'payment_state': 'paid'},
            {'name': 'Canceled Bonus', 'payment_state': 'canceled'},
        ])
        self.env['hr.employee.payment.cycle.type.line'].create([
            {
                'employee_id': self.employee.id,
                'cycle_type_id': first_type.id,
                'amount': 1000.0,
            },
            {
                'employee_id': self.employee.id,
                'cycle_type_id': second_type.id,
                'amount': 250.0,
            },
            {
                'employee_id': other_employee.id,
                'cycle_type_id': first_type.id,
                'amount': 800.0,
            },
            {
                'employee_id': self.employee.id,
                'cycle_type_id': paid_type.id,
                'amount': 125.0,
            },
            {
                'employee_id': self.employee.id,
                'cycle_type_id': canceled_type.id,
                'amount': 75.0,
            },
        ])
        method_line = self.bank_journal._get_available_payment_method_lines(
            'outbound')[:1]
        wizard = self.env['il.payment.cycle.wizard'].create({
            'name': 'Combined September Cycle',
            'company_id': self.company.id,
            'cycle_type_ids': [Command.set(
                (first_type | second_type | paid_type | canceled_type).ids)],
            'journal_id': self.bank_journal.id,
            'date': date(2026, 9, 1),
            'payment_method_id': method_line.payment_method_id.id,
        })
        reopen_action = wizard.action_next()
        self.assertEqual(len(wizard.employee_line_ids), 2)
        self.assertTrue(all(wizard.employee_line_ids.mapped('selected')))
        self.assertEqual(
            set(wizard.employee_line_ids.mapped('employee_id').ids),
            {self.employee.id, other_employee.id},
        )
        view = wizard.with_context(**reopen_action['context']).get_view(
            view_id=reopen_action['view_id'],
            view_type='form',
        )
        self.assertIn('string="Advance"', view['arch'])
        self.assertIn('string="Allowance"', view['arch'])
        self.assertIn('string="Paid Bonus"', view['arch'])
        self.assertIn('string="Canceled Bonus"', view['arch'])

        action = wizard.action_create_cycles()
        batch = self.env['account.batch.payment'].browse(action['res_id'])
        self.assertEqual(len(batch), 1)
        self.assertEqual(
            batch.il_payment_cycle_type_ids,
            first_type | second_type | paid_type | canceled_type,
        )
        self.assertEqual(len(batch.payment_ids), 5)
        self.assertEqual(sum(batch.payment_ids.mapped('amount')), 2250.0)
        self.assertEqual(len(batch.payment_ids.filtered(
            lambda payment: payment.state == 'in_process')), 2)
        draft_payment = batch.payment_ids.filtered(
            lambda payment: payment.state == 'draft')
        paid_payment = batch.payment_ids.filtered(
            lambda payment: payment.state == 'paid')
        canceled_payment = batch.payment_ids.filtered(
            lambda payment: payment.state == 'canceled')
        self.assertEqual(len(draft_payment), 1)
        self.assertFalse(draft_payment.move_id)
        self.assertEqual(len(paid_payment), 1)
        self.assertEqual(paid_payment.move_id.state, 'posted')
        self.assertEqual(len(canceled_payment), 1)
        self.assertFalse(canceled_payment.move_id)
        self.assertTrue(all(
            payment.move_id.state == 'posted'
            for payment in batch.payment_ids.filtered(
                lambda payment: payment.state == 'in_process')
        ))
