from datetime import date

from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install", "l10n_il_hr_payroll_account_payment_splits")
class TestPayrollPaymentSplits(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.employee = cls.env["hr.employee"].create({
            "name": "Payment Split Employee",
            "company_id": cls.company.id,
            "contract_date_start": date(2026, 1, 1),
        })
        cls.other_employee = cls.env["hr.employee"].create({
            "name": "Other Payment Employee",
            "company_id": cls.company.id,
            "contract_date_start": date(2026, 1, 1),
        })
        cls.journal = cls.env["account.journal"].search([
            ("company_id", "=", cls.company.id),
            ("type", "in", ("bank", "cash")),
        ], limit=1)

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

    def test_pay_from_payslip_creates_immediate_link_even_above_net(self):
        slip = self._payslip()
        action = slip.action_il_register_payment()
        self.assertEqual(action["target"], "current")
        self.assertEqual(action["context"]["default_il_spread_type"], "none")
        self.assertTrue(action["context"]["il_lock_immediate_spread"])
        payment = self.env["account.payment"].with_context(
            **action["context"]).create(self._payment_values(amount=2500.0))
        self.assertEqual(len(payment.il_split_line_ids), 1)
        self.assertEqual(payment.il_split_line_ids.payslip_id, slip)
        self.assertEqual(payment.il_split_line_ids.amount, 2500.0)
        self.assertEqual(slip.il_paid_amount, 2500.0)
        self.assertEqual(slip.il_net_amount_to_pay, -2500.0)
        self.assertEqual(slip.state_display, "overpayment")

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

    def test_per_payslip_lines_are_system_created_and_capped(self):
        payment = self.env["account.payment"].create(self._payment_values(
            il_spread_type="per_payslip"))
        self.assertFalse(payment.il_split_line_ids)
        with self.assertRaises(ValidationError):
            self.env["account.payment.split.line"].create({
                "payment_id": payment.id, "sequence": 1, "amount": 100.0,
            })
        slip = self._payslip()
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
                    "payslip_id": self._payslip().id,
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
                    "payslip_id": self._payslip(self.other_employee).id,
                })

    def test_deleting_payslip_reopens_linked_payment(self):
        slip = self._payslip()
        payment = self.env["account.payment"].create(self._payment_values())
        line = payment.il_split_line_ids
        line.payslip_id = slip
        self.assertTrue(line.is_applied)
        self.assertEqual(payment.il_applied_amount, 1000.0)
        self.assertEqual(payment.il_remaining_amount, 0.0)

        slip.unlink()

        self.assertFalse(line.payslip_id)
        self.assertFalse(line.is_applied)
        self.assertEqual(payment.il_applied_amount, 0.0)
        self.assertEqual(payment.il_remaining_amount, 1000.0)
