from datetime import date

from odoo import Command, fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install", "l10n_il_hr_payroll_account_payment_splits")
class TestPayrollPaymentSplits(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        monthly_type = cls.env.ref(
            "l10n_il_hr_payroll_account.hr_payroll_structure_type_il"
        )
        monthly_structure = cls.env.ref(
            "l10n_il_hr_payroll_account.hr_payroll_structure_il"
        )
        employee_vals = {
            "company_id": cls.company.id,
            "contract_date_start": date(2026, 1, 1),
            "structure_type_id": monthly_type.id,
            "il_salary_structure_id": monthly_structure.id,
            "mdl_wage_type": "mdl_monthly",
        }
        cls.employee = cls.env["hr.employee"].create({
            **employee_vals,
            "name": "Payment Split Employee",
        })
        cls.other_employee = cls.env["hr.employee"].create({
            **employee_vals,
            "name": "Other Payment Employee",
        })
        cls.journal = cls.env["account.journal"].search([
            ("company_id", "=", cls.company.id),
            ("type", "in", ("bank", "cash")),
        ], limit=1)
        cls.payment_debit_account = cls.env['account.account'].search([
            ('company_ids', 'in', cls.company.id),
            ('account_type', 'in', ('expense', 'asset_current')),
        ], limit=1)
        cls.payment_credit_account = cls.env['account.account'].search([
            ('company_ids', 'in', cls.company.id),
            ('account_type', 'in', ('liability_current', 'liability_payable')),
        ], limit=1)
        cls.company.write({
            'il_employee_payment_debit_account_id': cls.payment_debit_account.id,
            'il_employee_payment_credit_account_id': cls.payment_credit_account.id,
        })

    def _payment_values(self, employee=None, **extra):
        employee = employee or self.employee
        values = {
            "partner_id": employee.work_contact_id.id,
            "company_id": self.company.id,
            "payment_type": "outbound",
            "partner_type": "supplier",
            "journal_id": self.journal.id,
            "date": date(2026, 7, 1),
            "amount": 1000.0,
            "il_spread_type": "none",
        }
        values.update(extra)
        return values

    def _payslip(self, employee=None):
        employee = employee or self.employee
        return self.env["hr.payslip"].create({
            "name": "Split Test Payslip",
            "employee_id": employee.id,
            "company_id": self.company.id,
            "date_from": date(2026, 7, 1),
            "date_to": date(2026, 7, 31),
        })

    def _validate_payslip(self, slip, net_amount=1000.0):
        rule = self.env.ref('l10n_il_hr_payroll_account.hr_salary_rule_il_net')
        self.env['hr.payslip.line'].create({
            'slip_id': slip.id,
            'name': 'NET',
            'code': 'NET',
            'salary_rule_id': rule.id,
            'category_id': rule.category_id.id,
            'amount': net_amount,
            'total': net_amount,
            'quantity': 1.0,
            'rate': 100.0,
        })
        # These focused payment tests do not run the full payroll engine. Keep
        # the stored dashboard total coherent with the synthetic NET line and
        # populate the confirmation timestamp expected by Odoo 19.
        slip.write({
            'state': 'validated',
            'done_date': fields.Datetime.now(),
            'net_wage': net_amount,
        })
        return slip

    def _add_payment_summary_lines(self, slip):
        for xmlid, code, name in (
            ('hr_salary_rule_il_payments', 'IL_PAYMENTS', 'תשלומים'),
            ('hr_salary_rule_il_net_to_pay', 'IL_NET_TO_PAY', 'נטו לתשלום'),
        ):
            rule = self.env.ref(f'l10n_il_hr_payroll_account.{xmlid}')
            self.env['hr.payslip.line'].create({
                'slip_id': slip.id,
                'name': name,
                'code': code,
                'salary_rule_id': rule.id,
                'category_id': rule.category_id.id,
                'amount': slip.net_wage,
                'quantity': 1.0,
                'rate': 100.0,
            })
        slip.invalidate_recordset(['line_ids'])
        slip.line_ids.invalidate_recordset(['amount', 'total'])
        slip.net_wage = 1000.0

    def test_new_payslip_state_display_without_currency(self):
        slip = self.env["hr.payslip"].new({})
        self.assertEqual(slip.state_display, "draft")

    def test_no_spread_has_one_synchronized_line(self):
        payment = self.env["account.payment"].create(self._payment_values())
        self.assertEqual(len(payment.il_split_line_ids), 1)
        self.assertEqual(payment.il_split_line_ids.amount, 1000.0)
        payment.amount = 800.0
        self.assertEqual(payment.il_split_line_ids.amount, 800.0)
        payment.il_split_line_ids.amount = 700.0
        self.assertEqual(payment.amount, 700.0)
        with self.assertRaises(ValidationError):
            payment.il_split_line_ids.unlink()

    def test_pay_from_payslip_rejects_amount_above_remaining_net(self):
        slip = self._validate_payslip(self._payslip(), 1000.0)
        self._add_payment_summary_lines(slip)
        action = slip.action_il_register_payment()
        self.assertEqual(action["target"], "new")
        self.assertEqual(action["context"]["default_il_spread_type"], "none")
        self.assertTrue(action["context"]["il_lock_immediate_spread"])
        payment = self.env["account.payment"].with_context(
            **action["context"]).create(self._payment_values(amount=1000.0))
        slip.invalidate_recordset(['line_ids'])
        slip.line_ids.invalidate_recordset(['amount', 'total'])
        self.assertEqual(payment.il_split_line_ids.payslip_id, slip)
        self.assertNotEqual(payment.state, 'draft')
        self.assertEqual(slip.il_net_amount_to_pay, 0.0)
        self.assertEqual(slip.state, 'paid')
        self.assertEqual(slip.line_ids.filtered(
            lambda line: line.code == 'IL_PAYMENTS').total, -1000.0)
        self.assertEqual(slip.line_ids.filtered(
            lambda line: line.code == 'IL_NET_TO_PAY').total, 0.0)

        payment_action = slip.action_il_open_payments()
        self.assertEqual(payment_action['res_model'], 'account.payment.split.line')
        self.assertEqual(payment_action['domain'], [('payslip_id', '=', slip.id)])

        other_slip = self._validate_payslip(
            self._payslip(self.other_employee), 1000.0)
        other_action = other_slip.action_il_register_payment()
        with self.assertRaises(ValidationError):
            self.env["account.payment"].with_context(
                **other_action["context"]).create(self._payment_values(
                    employee=self.other_employee, amount=1000.01))

    def test_applied_splits_create_separate_posted_moves(self):
        first_slip = self._validate_payslip(self._payslip(), 400.0)
        second_slip = self._validate_payslip(self._payslip(), 600.0)
        payment = self.env['account.payment'].create(self._payment_values(
            il_spread_type='planned',
            il_split_line_ids=[
                Command.create({'amount': 400.0}),
                Command.create({'amount': 600.0}),
            ],
        ))
        payment.action_post()
        first, second = payment.il_split_line_ids

        first.payslip_id = first_slip
        first_move = first.account_move_id
        self.assertTrue(first_move)
        self.assertEqual(first_move.state, 'posted')
        self.assertEqual(first_move.il_employee_payment_id, payment)
        self.assertEqual(first_move.il_employee_payment_split_line_id, first)
        self.assertEqual(sum(first_move.line_ids.mapped('debit')), 400.0)
        self.assertEqual(sum(first_move.line_ids.mapped('credit')), 400.0)
        self.assertFalse(payment.move_id)

        second.payslip_id = second_slip
        second_move = second.account_move_id
        self.assertTrue(second_move)
        self.assertNotEqual(second_move, first_move)
        self.assertEqual(second_move.state, 'posted')
        self.assertEqual(sum(second_move.line_ids.mapped('debit')), 600.0)
        self.assertEqual(sum(second_move.line_ids.mapped('credit')), 600.0)
        self.assertEqual(payment.il_split_move_ids, first_move | second_move)

    def test_payslip_move_posts_at_zero_and_returns_to_draft(self):
        slip = self._validate_payslip(self._payslip(), 1000.0)
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'date': date(2026, 7, 31),
            'journal_id': self.journal.id,
            'line_ids': [
                Command.create({
                    'name': 'Payroll debit',
                    'account_id': self.payment_debit_account.id,
                    'debit': 1000.0,
                }),
                Command.create({
                    'name': 'Payroll credit',
                    'account_id': self.payment_credit_account.id,
                    'credit': 1000.0,
                }),
            ],
        })
        slip.move_id = move
        payment = self.env['account.payment'].create(self._payment_values())

        payment.il_split_line_ids.payslip_id = slip
        self.assertEqual(slip.state, 'paid')
        self.assertEqual(move.state, 'posted')

        payment.il_split_line_ids.payslip_id = False
        self.assertEqual(slip.state, 'validated')
        self.assertEqual(move.state, 'draft')

    def test_daily_rate_onchange_copies_additional_day_rate(self):
        daily_version = self.env['hr.version'].new({
            'company_id': self.company.id,
            'mdl_wage_type': 'mdl_daily',
            'mdl_daily_wage': 475.0,
        })
        daily_version._onchange_mdl_daily_wage_copy_additional_day_rate()
        self.assertEqual(daily_version.mdl_additional_day_wage, 475.0)

        monthly_version = self.env['hr.version'].new({
            'company_id': self.company.id,
            'mdl_wage_type': 'mdl_monthly',
            'resource_calendar_id': self.company.resource_calendar_id.id,
            'wage': 10000.0,
        })
        monthly_day_rate = monthly_version.mdl_daily_wage
        monthly_version._onchange_mdl_daily_wage_copy_additional_day_rate()
        self.assertGreater(monthly_day_rate, 0.0)
        self.assertEqual(
            monthly_version.mdl_additional_day_wage, monthly_day_rate)

    def test_wage_type_rejects_mismatched_salary_category(self):
        monthly_type = self.env.ref(
            'l10n_il_hr_payroll_account.hr_payroll_structure_type_il')
        daily_type = self.env.ref(
            'l10n_il_hr_payroll_account.hr_payroll_structure_type_il_daily')
        version = self.employee.version_id
        version.write({
            'mdl_wage_type': 'mdl_daily',
            'mdl_daily_wage': 400.0,
            'structure_type_id': daily_type.id,
        })
        with self.assertRaises(ValidationError):
            version.write({'structure_type_id': monthly_type.id})

    def test_draft_payslip_cannot_receive_a_payment_link(self):
        slip = self._payslip()
        payment = self.env["account.payment"].create(self._payment_values())
        with self.assertRaises(ValidationError):
            payment.il_split_line_ids.payslip_id = slip

    def test_payrun_pay_automatically_marks_zero_balance_paid(self):
        run = self.env['hr.payslip.run'].create({
            'name': 'Payment Validation Run',
            'date_start': date(2026, 7, 1),
            'date_end': date(2026, 7, 31),
        })
        slip = self._validate_payslip(self._payslip(), 1000.0)
        slip.payslip_run_id = run

        action = run.action_il_pay()

        self.assertEqual(action['res_model'], 'account.payment')
        self.assertEqual(slip.state, 'paid')
        self.assertEqual(run.state, '03_paid')
        self.assertEqual(slip.il_net_amount_to_pay, 0.0)
        self.assertEqual(len(slip.il_split_line_ids), 1)
        self.assertEqual(slip.il_split_line_ids.amount, 1000.0)
        self.assertEqual(slip.il_split_line_ids.payment_id.il_spread_type, 'none')

        slip.il_split_line_ids.payslip_id = False
        self.assertEqual(slip.state, 'validated')
        self.assertEqual(run.state, '02_close')

    def test_planned_distribution_must_close_payment(self):
        payment = self.env["account.payment"].create(self._payment_values(
            il_spread_type="planned",
            il_split_line_ids=[
                Command.create({"sequence": 1, "amount": 400.0}),
                Command.create({"sequence": 2, "amount": 600.0}),
            ],
        ))
        self.assertEqual(payment.il_planned_amount, 1000.0)
        with self.assertRaises(ValidationError):
            self.env["account.payment"].create(self._payment_values(
                il_spread_type="planned",
                il_split_line_ids=[Command.create({"sequence": 1, "amount": 900.0})],
            ))

    def test_planned_distribution_validates_current_one2many_lines(self):
        """A new payment must not depend on a pending stored recomputation."""
        payment = self.env["account.payment"].create(self._payment_values(
            amount=1000.01,
            il_spread_type="planned",
            il_split_line_ids=[
                Command.create({"sequence": 1, "amount": 333.33}),
                Command.create({"sequence": 2, "amount": 333.33}),
                Command.create({"sequence": 3, "amount": 333.35}),
            ],
        ))
        self.assertEqual(
            payment.currency_id.compare_amounts(
                sum(payment.il_split_line_ids.mapped("amount")), payment.amount),
            0,
        )

    def test_edit_existing_planned_payment_to_five_times_1200(self):
        payment = self.env["account.payment"].create(self._payment_values(
            amount=5000.0,
            il_spread_type="planned",
            il_split_line_ids=[
                Command.create({"sequence": sequence, "amount": 1000.0})
                for sequence in range(1, 6)
            ],
        ))
        payment.write({
            "amount": 6000.0,
            "il_split_line_ids": [
                Command.update(line.id, {"amount": 1200.0})
                for line in payment.il_split_line_ids
            ],
        })
        self.assertEqual(payment.amount, 6000.0)
        self.assertEqual(payment.il_split_line_ids.mapped("amount"), [1200.0] * 5)
        payment._check_il_spread_complete()

    def test_edit_replaces_existing_rows_with_five_times_1200(self):
        payment = self.env["account.payment"].create(self._payment_values(
            amount=6000.0,
            il_spread_type="planned",
            il_split_line_ids=[
                Command.create({"amount": 3000.0}),
                Command.create({"amount": 3000.0}),
            ],
        ))
        old_lines = payment.il_split_line_ids
        # Prime the one2many cache, matching an existing payment opened in the
        # form before its rows are replaced by the editable list.
        self.assertEqual(old_lines.mapped("amount"), [3000.0, 3000.0])

        payment.write({
            "il_split_line_ids": [
                *(Command.delete(line.id) for line in old_lines),
                *(Command.create({"amount": 1200.0}) for _index in range(5)),
            ],
        })

        current_lines = self.env["account.payment.split.line"].search([
            ("payment_id", "=", payment.id),
        ])
        self.assertEqual(current_lines.mapped("sequence"), [1, 2, 3, 4, 5])
        self.assertEqual(current_lines.mapped("amount"), [1200.0] * 5)
        payment._check_il_spread_complete()

    def test_edit_immediate_payment_to_planned_preserves_submitted_rows(self):
        payment = self.env["account.payment"].create(self._payment_values(
            amount=1200.0,
            il_spread_type="none",
        ))
        immediate_line = payment.il_split_line_ids

        payment.write({
            "il_spread_type": "planned",
            "il_split_line_ids": [
                Command.update(immediate_line.id, {"amount": 600.0}),
                Command.create({"amount": 600.0}),
            ],
        })

        current_lines = self.env["account.payment.split.line"].search([
            ("payment_id", "=", payment.id),
        ])
        self.assertEqual(payment.il_spread_type, "planned")
        self.assertEqual(current_lines.mapped("sequence"), [1, 2])
        self.assertEqual(current_lines.mapped("amount"), [600.0, 600.0])
        payment._check_il_spread_complete()

    def test_draft_line_edits_may_be_temporarily_unbalanced(self):
        payment = self.env["account.payment"].create(self._payment_values(
            amount=6000.0,
            il_spread_type="planned",
            il_split_line_ids=[
                Command.create({"sequence": sequence, "amount": 1200.0})
                for sequence in range(1, 6)
            ],
        ))
        first, second = payment.il_split_line_ids[:2]
        first.amount = 1100.0
        second.amount = 1300.0
        payment._check_il_spread_complete()

    def test_planned_edit_resequences_and_still_closes_payment(self):
        payment = self.env["account.payment"].create(self._payment_values(
            il_spread_type="planned",
            il_split_line_ids=[
                Command.create({"sequence": 1, "amount": 200.0}),
                Command.create({"sequence": 2, "amount": 300.0}),
                Command.create({"sequence": 3, "amount": 500.0}),
            ],
        ))
        middle = payment.il_split_line_ids.filtered(lambda line: line.sequence == 2)
        last = payment.il_split_line_ids.filtered(lambda line: line.sequence == 3)
        payment.write({
            "il_split_line_ids": [
                Command.delete(middle.id),
                Command.update(last.id, {"amount": 800.0}),
            ],
        })
        self.assertEqual(payment.il_split_line_ids.mapped("sequence"), [1, 2])
        self.assertEqual(payment.il_split_line_ids.mapped("amount"), [200.0, 800.0])
        self.assertEqual(payment.il_planned_amount, 1000.0)

    def test_installment_numbers_are_automatic_and_follow_order(self):
        payment = self.env["account.payment"].create(self._payment_values(
            il_spread_type="planned",
            il_split_line_ids=[
                Command.create({"sequence": 1, "amount": 200.0}),
                Command.create({"sequence": 1, "amount": 300.0}),
                Command.create({"sequence": 1, "amount": 500.0}),
            ],
        ))
        self.assertEqual(payment.il_split_line_ids.mapped("sequence"), [1, 2, 3])

        first = payment.il_split_line_ids[0]
        first.sequence = 99
        ordered_lines = self.env["account.payment.split.line"].search([
            ("payment_id", "=", payment.id),
        ])
        self.assertEqual(ordered_lines.mapped("amount"), [300.0, 500.0, 200.0])
        self.assertEqual(ordered_lines.mapped("sequence"), [1, 2, 3])

        ordered_lines[1].unlink()
        remaining_lines = self.env["account.payment.split.line"].search([
            ("payment_id", "=", payment.id),
        ])
        self.assertEqual(remaining_lines.mapped("sequence"), [1, 2])

    def test_per_payslip_lines_are_system_created_and_capped(self):
        payment = self.env["account.payment"].create(self._payment_values(
            il_spread_type="per_payslip"))
        self.assertFalse(payment.il_split_line_ids)
        with self.assertRaises(ValidationError):
            self.env["account.payment.split.line"].create({
                "payment_id": payment.id, "sequence": 1, "amount": 100.0,
            })
        slip = self._validate_payslip(self._payslip(), 1000.0)
        line = self.env["account.payment.split.line"].with_context(
            il_system_split_create=True).create({
                "payment_id": payment.id,
                "sequence": 1,
                "amount": 600.0,
                "payslip_id": slip.id,
            })
        self.assertTrue(line.is_applied)
        self.assertEqual(payment.il_applied_amount, 600.0)
        self.assertEqual(payment.il_remaining_amount, 400.0)
        with self.assertRaises(ValidationError):
            self.env["account.payment.split.line"].with_context(
                il_system_split_create=True).create({
                    "payment_id": payment.id,
                    "sequence": 2,
                    "amount": 401.0,
                    "payslip_id": self._validate_payslip(
                        self._payslip(), 1000.0).id,
                })

    def test_split_cannot_link_to_another_employee(self):
        payment = self.env["account.payment"].create(self._payment_values(
            il_spread_type="per_payslip"))
        with self.assertRaises(ValidationError):
            self.env["account.payment.split.line"].with_context(
                il_system_split_create=True).create({
                    "payment_id": payment.id,
                    "sequence": 1,
                    "amount": 100.0,
                    "payslip_id": self._validate_payslip(
                        self._payslip(self.other_employee), 1000.0).id,
                })

    def test_returning_paid_payslip_to_draft_keeps_payment_linked(self):
        slip = self._validate_payslip(self._payslip(), 1000.0)
        payment = self.env["account.payment"].create(self._payment_values())
        line = payment.il_split_line_ids
        line.payslip_id = slip
        old_move = self.env['account.move'].create({
            'journal_id': self.journal.id,
            'date': slip.date_to,
        })
        slip.move_id = old_move
        self.assertTrue(line.is_applied)
        self.assertEqual(payment.il_applied_amount, 1000.0)
        self.assertEqual(payment.il_remaining_amount, 0.0)

        self.assertEqual(slip.state, 'paid')
        slip.action_payslip_draft()

        self.assertEqual(slip.state, 'draft')
        self.assertFalse(slip.move_id)
        self.assertFalse(old_move.exists())
        self.assertEqual(line.payslip_id, slip)
        self.assertTrue(line.is_applied)
        self.assertEqual(payment.il_applied_amount, 1000.0)
        self.assertEqual(payment.il_remaining_amount, 0.0)

    def test_reapproval_rebuilds_accounting_lines_from_rule_accounts(self):
        rule = self.env.ref('l10n_il_hr_payroll_account.hr_salary_rule_il_net')
        accounts = self.env['account.account'].search([], limit=2)
        self.assertEqual(len(accounts), 2)
        rule.struct_id.journal_id = self.journal

        slip = self._payslip()
        slip.struct_id = rule.struct_id
        self._validate_payslip(slip, 1000.0)
        old_move = self.env['account.move'].create({
            'journal_id': self.journal.id,
            'date': slip.date_to,
        })
        slip.move_id = old_move

        slip.action_payslip_draft()
        rule.account_debit = accounts[0]
        rule.account_credit = accounts[1]
        slip.write({
            'state': 'validated',
            'done_date': fields.Datetime.now(),
        })
        slip._action_create_account_move()

        self.assertTrue(slip.move_id)
        self.assertNotEqual(slip.move_id, old_move)
        self.assertEqual(len(slip.move_id.line_ids), 2)
        self.assertEqual(
            set(slip.move_id.line_ids.mapped('account_id').ids),
            set(accounts.ids),
        )

    def test_compute_sheet_removes_stale_move_from_draft_payslip(self):
        slip = self._payslip()
        old_move = self.env['account.move'].create({
            'journal_id': self.journal.id,
            'date': slip.date_to,
        })
        slip.move_id = old_move

        slip.compute_sheet()

        self.assertFalse(slip.move_id)
        self.assertFalse(old_move.exists())

    def test_il_rule_account_mapping_is_complete_and_reconcilable(self):
        self.env['hr.payroll.structure']._il_ensure_payroll_accounting_configuration(
            overwrite=True,
        )
        structures = self.env['hr.payroll.structure'].search([('code', 'in', (
            'IL_ISR_MONTHLY', 'IL_ISR_DAILY',
            'IL_PAL_MONTHLY', 'IL_PAL_DAILY',
        ))])
        mapped_codes = {
            'BASIC', 'IL_OVERTIME', 'IL_ADDITIONAL_DAY_GROSS',
            'IL_ADJUSTMENT_GROSS', 'IL_ADJUSTMENT_NET_GROSSUP',
            'IL_ISR_INCOME_TAX', 'IL_ISR_NI_EE', 'IL_ISR_HEALTH_EE',
            'IL_ISR_PENSION_EE', 'IL_ISR_STUDY_EE', 'IL_ISR_NI_ER',
            'IL_ISR_PENSION_ER', 'IL_ISR_SEVERANCE_ER', 'IL_ISR_STUDY_ER',
            'IL_PAL_INCOME_TAX', 'IL_PAL_NI_EE', 'IL_PAL_HEALTH_STAMP',
            'IL_PAL_ORGANIZATION_TAX', 'IL_PAL_PENSION_EE',
            'IL_PAL_STUDY_EE', 'IL_PAL_NI_ER', 'IL_PAL_EQUALIZATION_ER',
            'IL_PAL_PENSION_ER', 'IL_PAL_SEVERANCE_ER', 'IL_PAL_STUDY_ER',
            'NET',
        }
        rules = structures.mapped('rule_ids').filtered(
            lambda rule: rule.active and rule.code in mapped_codes
        )
        for journal in structures.mapped('journal_id'):
            self.assertTrue(journal.default_account_id)
            self.assertTrue(journal.default_account_id.reconcile)
        self.assertTrue(rules)
        for rule in rules:
            self.assertTrue(
                rule.account_debit or rule.account_credit,
                f'Missing accounting mapping for {rule.struct_id.code}/{rule.code}',
            )
            for account in rule.account_debit | rule.account_credit:
                self.assertTrue(account.reconcile)

        technical_codes = {
            'GROSS', 'IL_TAX_BASE', 'IL_NI_BASE', 'IL_PENSION_BASE',
            'IL_SEVERANCE_BASE', 'IL_STUDY_FUND_BASE',
            'IL_PAL_EQUALIZATION_BASE', 'IL_PAYMENTS', 'IL_NET_TO_PAY',
            'IL_EMPLOYER_COST',
        }
        technical_rules = structures.mapped('rule_ids').filtered(
            lambda rule: rule.active and rule.code in technical_codes
        )
        for rule in technical_rules:
            self.assertFalse(rule.account_debit)
            self.assertFalse(rule.account_credit)

    def test_approval_draws_only_available_net_from_open_payment(self):
        slip = self._validate_payslip(self._payslip(), 1000.0)
        payment = self.env["account.payment"].create(self._payment_values(
            amount=1500.0,
            il_spread_type="per_payslip",
        ))
        payment.action_post()

        eligible = self.env['account.payment'].search([
            ('partner_id', '=', slip.employee_id.work_contact_id.id),
            ('company_id', '=', slip.company_id.id),
            ('payment_type', '=', 'outbound'),
            ('state', 'not in', ('draft', 'canceled')),
            ('date', '<=', slip.date_to),
            ('il_spread_type', 'in', ('planned', 'none', 'per_payslip')),
            ('il_remaining_amount', '>', 0),
        ])
        self.assertIn(payment, eligible)

        slip._il_attach_automatic_split_lines()

        self.assertEqual(len(payment.il_split_line_ids), 1)
        self.assertEqual(payment.il_split_line_ids.amount, 1000.0)
        self.assertEqual(payment.il_split_line_ids.payslip_id, slip)
        self.assertEqual(slip.il_net_amount_to_pay, 0.0)
        self.assertEqual(payment.il_remaining_amount, 500.0)
