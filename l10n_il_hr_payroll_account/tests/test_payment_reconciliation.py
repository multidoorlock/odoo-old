from datetime import date

from odoo import Command, fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, new_test_user, tagged


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
        cls.monthly_structure.journal_id = cls.general_journal
        if not cls.general_journal.default_account_id:
            cls.general_journal.default_account_id = cls.expense
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Residual Payment Employee',
            'company_id': cls.company.id,
            'contract_date_start': date(2026, 1, 1),
            'date_version': date(2026, 1, 1),
            # Supply the matching wage/category/structure during creation:
            # hr.version validates before a later employee write can run.
            'mdl_wage_type': 'mdl_monthly',
            'structure_type_id': cls.monthly_type.id,
            'il_salary_structure_id': cls.monthly_structure.id,
            'schedule_pay': 'monthly',
        })

    def test_salary_structure_exposes_compatible_company_field(self):
        structure = self.monthly_structure.with_company(self.company)
        result = structure.search_read(
            [('id', '=', structure.id)],
            ['company_id'],
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['company_id'][0], self.company.id)

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
        net_rule = self.env.ref(
            'l10n_il_hr_payroll_account.hr_salary_rule_il_net')
        self.env['hr.payslip.line'].create({
            'slip_id': slip.id,
            'name': 'NET',
            'code': 'NET',
            'salary_rule_id': net_rule.id,
            'category_id': net_rule.category_id.id,
            'amount': amount,
            'total': amount,
            'quantity': 1.0,
            'rate': 100.0,
        })
        return slip

    def _payment(self, amount, origin_slip=None, post=True):
        context = {'il_employee_payment': True}
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

    def test_accounting_user_can_unlink_unrelated_reconciliation(self):
        accounting_user = new_test_user(
            self.env,
            login='reconciliation-accounting-only',
            groups='account.group_account_user',
        )
        self.assertFalse(accounting_user.has_group(
            'hr_payroll.group_hr_payroll_user'))
        # Even an empty native operation used to fail because our hook tried
        # to search payroll split lines with the caller's access rights.
        self.env['account.partial.reconcile'].with_user(
            accounting_user
        ).browse().unlink()

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

    def test_new_payment_waits_until_payslip_is_approved_again(self):
        slip = self._payslip_with_posted_net(2500.0)
        payment = self._payment(2500.0, origin_slip=slip)
        self.assertEqual(slip.il_net_amount_to_pay, 2500.0)
        self.assertFalse(payment.il_split_line_ids.reconcile_id)

        slip.action_payslip_draft()
        self.assertFalse(slip.move_id)
        slip.action_payslip_done()

        self.assertEqual(slip.move_id.state, 'posted')
        self.assertEqual(slip.il_net_amount_to_pay, 0.0)
        self.assertEqual(slip.state, 'paid')
        self.assertEqual(slip._il_affecting_payments(), payment)
        self.assertEqual(len(payment.il_split_line_ids), 1)
        split = payment.il_split_line_ids
        self.assertTrue(split.is_applied)
        self.assertTrue(split.reconcile_id)
        self.assertNotIn('payslip_id', split._fields)
        self.assertEqual(split.reconcile_id.full_reconcile_id.reconciled_line_ids,
                         split.reconcile_id.debit_move_id | split.reconcile_id.credit_move_id)

    def test_payment_created_from_payslip_pay_button_reconciles_immediately(self):
        slip = self._payslip_with_posted_net(2750.0)
        action = slip.action_il_register_payment()
        self.assertEqual(action['context']['il_origin_payslip_id'], slip.id)

        payment = self.env['account.payment'].with_context(
            **action['context'],
        ).create({
            'partner_id': self.employee.work_contact_id.id,
            'company_id': self.company.id,
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'journal_id': self.bank_journal.id,
            'date': date(2026, 8, 1),
            'amount': 2750.0,
        })
        payment.with_context(**action['context']).action_post()

        self.assertEqual(payment.state, 'in_process')
        self.assertEqual(payment.move_id.state, 'posted')
        self.assertTrue(payment.il_split_line_ids.reconcile_id)
        self.assertEqual(slip.il_net_amount_to_pay, 0.0)
        self.assertEqual(slip.state, 'paid')
        self.assertEqual(slip._il_affecting_payments(), payment)

    def test_payslip_approval_posts_journal_entry_without_payments(self):
        slip = self._payslip_with_posted_net(1800.0)
        slip.action_payslip_draft()
        self.assertFalse(slip.move_id)

        slip.action_payslip_done()

        self.assertEqual(slip.state, 'validated')
        self.assertTrue(slip.move_id)
        self.assertEqual(slip.move_id.state, 'posted')
        self.assertEqual(slip.il_net_amount_to_pay, 1800.0)

    def test_employee_payment_view_contains_reconciliation_splits(self):
        view = self.env.ref(
            'l10n_il_hr_payroll_account.view_account_payment_form_employee')
        architecture = view._get_combined_arch()
        self.assertTrue(architecture.xpath("//field[@name='il_split_line_ids']"))
        self.assertTrue(architecture.xpath("//field[@name='il_spread_type']"))
        self.assertTrue(architecture.xpath("//page[@name='il_payroll']"))
        self.assertTrue(architecture.xpath("//field[@name='reconcile_id']"))

        payslip_form = self.env.ref(
            'l10n_il_hr_payroll_account.view_hr_payslip_form'
        )._get_combined_arch()
        self.assertFalse(payslip_form.xpath(
            "//button[@name='action_il_handle_payments']"))
        summary_fields = payslip_form.xpath(
            "//page[@name='il_summary']//field/@name")
        self.assertEqual(summary_fields, [
            'currency_id', 'employer_cost', 'gross_wage', 'net_wage',
            'il_paid_amount', 'il_net_amount_to_pay',
        ])

        batch_form = self.env.ref(
            'l10n_il_hr_payroll_account.view_batch_payment_form_il_cycle'
        )._get_combined_arch()
        payment_list = batch_form.xpath(
            "//field[@name='payment_ids']/list")[0]
        self.assertEqual(
            batch_form.xpath("//field[@name='payment_ids']")[0].get('widget'),
            'il_grouped_batch_payments',
        )
        self.assertTrue(batch_form.xpath(
            "//field[@name='il_grouped_payment_view_id']"))
        self.assertFalse(batch_form.xpath(
            "//button[@name='action_il_open_grouped_payments']"))
        self.assertIn(
            "form_view_initial_mode",
            batch_form.xpath("//field[@name='payment_ids']")[0].get('context'),
        )
        self.assertEqual(
            payment_list.get('default_order'),
            'il_employee_id,il_payment_cycle_type_id,date,id',
        )
        visible_batch_fields = payment_list.xpath(
            "./field[not(@column_invisible='True')]/@name"
        )
        self.assertEqual(visible_batch_fields, [
            'name', 'date', 'il_employee_id',
            'il_payment_cycle_type_id', 'amount_signed',
        ])
        self.assertEqual(
            payment_list.xpath("./field[@name='amount_signed']")[0].get('sum'),
            'Total',
        )
        grouped_list = self.env.ref(
            'l10n_il_hr_payroll_account.view_account_payment_il_batch_grouped_list'
        )._get_combined_arch()
        self.assertEqual(
            grouped_list.get('default_group_by'),
            'il_batch_group,il_employee_id',
        )
        self.assertEqual(
            grouped_list.xpath("./field[@name='amount']")[0].get('sum'),
            'סה״כ',
        )
        payslip = self._payslip_with_posted_net(100.0)
        payment_action = payslip.action_il_open_payments()
        self.assertTrue(payment_action['context']['edit'])
        self.assertEqual(payment_action['context']['il_payslip_id'], payslip.id)
        self.assertEqual(
            payment_action['context']['form_view_initial_mode'], 'edit')
        payment_list = self.env.ref(
            'l10n_il_hr_payroll_account.view_account_payment_list_employee'
        )._get_combined_arch()
        self.assertFalse(payment_list.xpath("//field[@name='company_id']"))
        self.assertFalse(payment_list.xpath("//field[@name='amount_signed']"))
        currency_fields = payment_list.xpath("//field[@name='currency_id']")
        self.assertTrue(currency_fields)
        self.assertTrue(all(
            field.get('column_invisible') == 'True'
            for field in currency_fields
        ))
        self.assertFalse(payment_list.xpath("//field[@name='activity_ids']"))
        self.assertFalse(payment_list.xpath("//field[@name='create_date']"))
        self.assertTrue(payment_list.xpath(
            "//field[@name='il_relevant_installment_number']"))
        self.assertTrue(payment_list.xpath(
            "//field[@name='il_relevant_installment_amount']"))
        spread_types = dict(self.env['account.payment']._fields[
            'il_spread_type'].selection)
        self.assertEqual(set(spread_types), {'none', 'planned'})

    def test_planned_splits_control_separate_reconciliations(self):
        first = self._payslip_with_posted_net(4000.0)
        second = self._payslip_with_posted_net(6000.0)
        payment = self.env['account.payment'].with_context(
            il_employee_payment=True,
        ).create({
            'partner_id': self.employee.work_contact_id.id,
            'company_id': self.company.id,
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'journal_id': self.bank_journal.id,
            'date': date(2026, 8, 1),
            'amount': 10000.0,
            'il_spread_type': 'planned',
            'il_split_line_ids': [
                Command.create({'amount': 4000.0}),
                Command.create({'amount': 6000.0}),
            ],
        })
        payment.action_post()
        self.assertEqual(payment.state, 'in_process')
        self.assertFalse(payment.il_split_line_ids.mapped('reconcile_id'))
        self.assertEqual(payment.il_remaining_amount, 10000.0)
        self.assertEqual(len(payment.move_id.line_ids), 2)

        first_split, second_split = payment.il_split_line_ids
        first.write({'state': 'draft', 'done_date': False})
        first.action_payslip_done()
        self.assertTrue(first_split.reconcile_id)
        self.assertTrue(first_split.is_applied)
        self.assertFalse(second_split.reconcile_id)
        self.assertEqual(first.il_net_amount_to_pay, 0.0)
        self.assertEqual(second.il_net_amount_to_pay, 6000.0)
        self.assertEqual(payment.il_remaining_amount, 6000.0)

        second.write({'state': 'draft', 'done_date': False})
        second.action_payslip_done()
        self.assertTrue(second_split.reconcile_id)
        self.assertEqual(first.il_net_amount_to_pay, 0.0)
        self.assertEqual(second.il_net_amount_to_pay, 0.0)
        self.assertEqual(payment.il_remaining_amount, 0.0)
        self.assertEqual(len(payment.move_id.line_ids), 2)
        self.assertEqual(len(payment.il_split_line_ids.mapped('reconcile_id')), 2)
        first_context = payment.with_context(il_payslip_id=first.id)
        second_context = payment.with_context(il_payslip_id=second.id)
        self.assertEqual(first_context.il_relevant_installment_number, 1)
        self.assertEqual(first_context.il_relevant_installment_amount, 4000.0)
        self.assertEqual(second_context.il_relevant_installment_number, 2)
        self.assertEqual(second_context.il_relevant_installment_amount, 6000.0)

    def test_split_can_partially_reconcile_a_payslip(self):
        slip = self._payslip_with_posted_net(10000.0)
        payment = self.env['account.payment'].with_context(
            il_employee_payment=True,
        ).create({
            'partner_id': self.employee.work_contact_id.id,
            'company_id': self.company.id,
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'journal_id': self.bank_journal.id,
            'date': date(2026, 8, 1),
            'amount': 10000.0,
            'il_spread_type': 'planned',
            'il_split_line_ids': [
                Command.create({'amount': 4000.0}),
                Command.create({'amount': 6000.0}),
            ],
        })
        payment.action_post()
        slip.write({'state': 'draft', 'done_date': False})
        slip.action_payslip_done()
        applied = payment.il_split_line_ids.filtered('is_applied')
        self.assertEqual(applied.amount, 4000.0)
        self.assertFalse(applied.reconcile_id.full_reconcile_id)
        self.assertEqual(slip.il_net_amount_to_pay, 6000.0)
        self.assertEqual(payment.il_remaining_amount, 6000.0)
        contextual_payment = payment.with_context(il_payslip_id=slip.id)
        self.assertEqual(contextual_payment.il_relevant_installment_number, 1)
        self.assertEqual(contextual_payment.il_relevant_installment_amount, 4000.0)

        reconciliation = applied.reconcile_id
        reconciliation.unlink()
        self.assertFalse(applied.reconcile_id)
        self.assertFalse(applied.is_applied)
        self.assertEqual(slip.il_net_amount_to_pay, 10000.0)
        self.assertEqual(payment.il_remaining_amount, 10000.0)

    def test_split_cannot_exceed_open_payslip_residual(self):
        slip = self._payslip_with_posted_net(3000.0)
        payment = self.env['account.payment'].with_context(
            il_employee_payment=True,
        ).create({
            'partner_id': self.employee.work_contact_id.id,
            'company_id': self.company.id,
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'journal_id': self.bank_journal.id,
            'date': date(2026, 8, 1),
            'amount': 4000.0,
            'il_spread_type': 'planned',
            'il_split_line_ids': [Command.create({'amount': 4000.0})],
        })
        payment.action_post()
        slip.write({'state': 'draft', 'done_date': False})
        with self.assertRaises(ValidationError):
            slip.action_payslip_done()
        self.assertEqual(slip.il_net_amount_to_pay, 3000.0)
        self.assertFalse(payment.il_split_line_ids.reconcile_id)

    def test_draft_payment_edit_rebuilds_its_reconciliation_on_approval(self):
        slip = self._payslip_with_posted_net(10000.0)
        payment = self._payment(8000.0)
        split = payment.il_split_line_ids
        split._il_reconcile_with_payslip(slip)
        old_reconciliation = split.reconcile_id
        self.assertEqual(slip.il_net_amount_to_pay, 2000.0)

        payment.action_draft()
        self.assertTrue(old_reconciliation.exists())
        self.assertEqual(split.reconcile_id, old_reconciliation)
        self.assertEqual(slip.il_net_amount_to_pay, 2000.0)

        payment.amount = 4000.0
        self.assertFalse(old_reconciliation.exists())
        self.assertEqual(
            split.il_pending_payslip_move_line_id,
            slip._il_salary_payable_lines(),
        )
        self.assertEqual(split.amount, 4000.0)
        payment.action_post()

        self.assertTrue(split.reconcile_id)
        self.assertFalse(split.il_pending_payslip_move_line_id)
        self.assertEqual(split.amount, 4000.0)
        self.assertEqual(slip.il_net_amount_to_pay, 6000.0)

    def test_draft_payment_cannot_allocate_more_than_payslip_net(self):
        slip = self._payslip_with_posted_net(10000.0)
        payment = self._payment(8000.0)
        split = payment.il_split_line_ids
        split._il_reconcile_with_payslip(slip)
        payment.action_draft()

        with self.cr.savepoint(), self.assertRaises(ValidationError):
            payment.amount = 11000.0

    def test_draft_planned_lines_stay_linked_while_being_edited(self):
        slip = self._payslip_with_posted_net(1000.0)
        payment = self.env['account.payment'].with_context(
            il_employee_payment=True,
        ).create({
            'partner_id': self.employee.work_contact_id.id,
            'company_id': self.company.id,
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'journal_id': self.bank_journal.id,
            'date': date(2026, 8, 1),
            'amount': 1000.0,
            'il_spread_type': 'planned',
            'il_split_line_ids': [
                Command.create({'amount': 200.0}),
                Command.create({'amount': 800.0}),
            ],
        })
        payment.action_post()
        first, second = payment.il_split_line_ids
        first._il_reconcile_with_payslip(slip)
        reconciliation = first.reconcile_id

        payment.action_draft()
        second.amount = 700.0
        first.amount = 300.0

        self.assertEqual(first.reconcile_id, reconciliation)
        self.assertTrue(reconciliation.exists())
        payment.action_post()
        self.assertFalse(reconciliation.exists())
        self.assertTrue(first.reconcile_id)
        self.assertEqual(first.reconcile_id.amount, 300.0)
        self.assertEqual(slip.il_net_amount_to_pay, 700.0)

    def test_drafting_then_deleting_split_removes_reconciliation_and_target(self):
        slip = self._payslip_with_posted_net(5000.0)
        payment = self._payment(5000.0)
        split = payment.il_split_line_ids
        split._il_reconcile_with_payslip(slip)
        reconciliation = split.reconcile_id

        payment.action_draft()
        self.assertTrue(reconciliation.exists())
        self.assertEqual(split.reconcile_id, reconciliation)
        split.with_context(il_system_split_unlink=True).unlink()

        self.assertFalse(split.exists())
        self.assertFalse(reconciliation.exists())
        self.assertEqual(slip.il_net_amount_to_pay, 5000.0)

    def test_multiple_cycle_types_create_one_batch_with_native_lines(self):
        other_employee = self.env['hr.employee'].create({
            'name': 'Second Cycle Employee',
            'company_id': self.company.id,
            'contract_date_start': date(2026, 1, 1),
            'date_version': date(2026, 1, 1),
            'mdl_wage_type': 'mdl_monthly',
            'structure_type_id': self.monthly_type.id,
            'il_salary_structure_id': self.monthly_structure.id,
            'schedule_pay': 'monthly',
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
        self.assertEqual(wizard.step, 'selection')
        self.assertEqual(len(wizard.employee_selection_line_ids), 2)
        self.assertTrue(all(
            wizard.employee_selection_line_ids.mapped('selected')))
        employee_types = {
            line.employee_id: line.cycle_type_ids
            for line in wizard.employee_selection_line_ids
        }
        self.assertEqual(
            employee_types[self.employee],
            first_type | second_type | paid_type | canceled_type,
        )
        self.assertEqual(employee_types[other_employee], first_type)
        other_selection = wizard.employee_selection_line_ids.filtered(
            lambda line: line.employee_id == other_employee)
        other_selection.selected = False
        wizard.action_next()
        self.assertEqual(wizard.step, 'amounts')
        self.assertEqual(
            wizard.employee_line_ids.mapped('employee_id'), self.employee)
        wizard.action_previous()
        self.assertEqual(wizard.step, 'selection')
        other_selection.selected = True
        reopen_action = wizard.action_next()
        self.assertEqual(wizard.step, 'amounts')
        self.assertEqual(len(wizard.employee_line_ids), 5)
        self.assertTrue(all(wizard.employee_line_ids.mapped('selected')))
        self.assertEqual(
            set(wizard.employee_line_ids.mapped('employee_id').ids),
            {self.employee.id, other_employee.id},
        )
        view = wizard.with_context(**reopen_action['context']).get_view(
            view_id=reopen_action['view_id'],
            view_type='form',
        )
        from lxml import etree
        wizard_arch = etree.fromstring(view['arch'])
        selection_list = wizard_arch.xpath(
            "//field[@name='employee_selection_line_ids']/list"
        )[0]
        self.assertEqual(selection_list.get('editable'), 'bottom')
        self.assertEqual(selection_list.get('no_open'), 'True')
        self.assertEqual(selection_list.get('create'), '0')
        self.assertEqual(selection_list.get('delete'), '0')
        selection_fields = {
            field.get('name'): field
            for field in selection_list.xpath('./field')
        }
        self.assertIn(
            "'no_open': True",
            selection_fields['employee_id'].get('options'),
        )
        self.assertIn(
            "'no_open': True",
            selection_fields['cycle_type_ids'].get('options'),
        )
        visible_fields = wizard_arch.xpath(
            "//field[@name='employee_line_ids']/list/field"
            "[not(@column_invisible='True')]/@name"
        )
        self.assertEqual(visible_fields, [
            'selected', 'employee_id', 'cycle_type_id', 'amount',
            'partner_bank_id',
        ])
        ordered_pairs = [
            (line.employee_id.name, line.cycle_type_id.name)
            for line in wizard.employee_line_ids.sorted('sequence')
        ]
        self.assertEqual(ordered_pairs, sorted(ordered_pairs))

        action = wizard.action_create_cycles()
        batch = self.env['account.batch.payment'].browse(action['res_id'])
        self.assertEqual(len(batch), 1)
        self.assertEqual(
            batch.il_payment_cycle_type_ids,
            first_type | second_type | paid_type | canceled_type,
        )
        self.assertEqual(len(batch.payment_ids), 5)
        self.assertEqual(sum(batch.payment_ids.mapped('amount')), 2250.0)
        self.assertEqual(set(batch.payment_ids.mapped('il_batch_group')), {
            'payments',
        })
        self.assertEqual(
            set(batch.payment_ids.mapped('il_employee_id').ids),
            {self.employee.id, other_employee.id},
        )
        self.assertEqual(
            batch.payment_ids.mapped('il_payment_cycle_type_id'),
            first_type | second_type | paid_type | canceled_type,
        )
        self.assertEqual(
            dict(self.env['account.payment']._fields[
                'il_batch_group'].selection)['payments'],
            'תשלומים',
        )
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
