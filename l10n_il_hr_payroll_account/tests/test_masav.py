import base64
from datetime import date
from decimal import Decimal

from odoo import Command
from odoo.tests.common import TransactionCase, tagged

from ..lib.masav import MasavFile, MasavPayment, build_masav_file


@tagged('post_install', '-at_install', 'l10n_il_hr_payroll_account_masav')
class TestMasavExport(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write({
            'il_masav_institution_number': '12345678',
            'il_masav_sender_number': '12345',
            'il_masav_hebrew_code': 'b',
        })
        cls.env['hr.payroll.structure']._il_ensure_payroll_accounting_configuration(
            overwrite=True)
        cls.journal = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id),
            ('type', 'in', ('bank', 'cash')),
        ], limit=1)
        cls.monthly_type = cls.env.ref(
            'l10n_il_hr_payroll_account.hr_payroll_structure_type_il')
        cls.monthly_structure = cls.env.ref(
            'l10n_il_hr_payroll_account.hr_payroll_structure_il')
        cls.employee = cls.env['hr.employee'].create({
            'name': 'עובד בדיקה',
            'company_id': cls.company.id,
            'identification_id': '123456789',
            'contract_date_start': date(2026, 1, 1),
            'date_version': date(2026, 1, 1),
            'mdl_wage_type': 'mdl_monthly',
            'structure_type_id': cls.monthly_type.id,
            'il_salary_structure_id': cls.monthly_structure.id,
            'schedule_pay': 'monthly',
        })
        cls.bank = cls.env['res.partner.bank'].create({
            'partner_id': cls.employee.work_contact_id.id,
            'acc_number': '123456',
            'clearing_number': '10-800',
            'allow_out_payment': True,
        })

    def _payment(self, amount):
        payment = self.env['account.payment'].with_context(
            il_employee_payment=True,
        ).create({
            'partner_id': self.employee.work_contact_id.id,
            'company_id': self.company.id,
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'partner_bank_id': self.bank.id,
            'journal_id': self.journal.id,
            'date': date(2026, 9, 10),
            'amount': amount,
        })
        payment.action_post()
        return payment

    def test_pure_builder_uses_fixed_records_and_control_totals(self):
        content = build_masav_file(MasavFile(
            institution_number='12345678',
            sender_number='12345',
            institution_name='חברת בדיקה',
            payment_date=date(2026, 9, 10),
            creation_date=date(2026, 9, 9),
            payments=[MasavPayment(
                bank_code='10',
                branch_code='800',
                account_number='123456',
                beneficiary_id='123456789',
                beneficiary_name='עובד בדיקה',
                amount=Decimal('1234.56'),
                reference='42',
                period_from=date(2026, 9, 1),
                period_to=date(2026, 9, 30),
            )],
        ))
        records = content.split(b'\r\n')[:-1]
        self.assertEqual([len(record) for record in records], [128, 128, 128])
        self.assertEqual([record[:1] for record in records], [b'K', b'1', b'5'])
        self.assertEqual(records[1][61:74], b'0000000123456')
        self.assertEqual(records[2][21:36], b'000000000123456')
        self.assertEqual(records[2][51:58], b'0000001')

    def test_popup_selects_eligible_payments_and_saves_file_per_selection(self):
        first = self._payment(4000)
        second = self._payment(6000)
        cycle_type = self.env['il.payment.cycle.type'].create({'name': 'Salary'})
        batch = self.env['account.batch.payment'].create({
            'name': 'September Salaries',
            'date': date(2026, 9, 10),
            'journal_id': self.journal.id,
            'batch_type': 'outbound',
            'payment_method_id': first.payment_method_id.id,
            'il_payment_cycle_type_ids': [Command.set(cycle_type.ids)],
            'payment_ids': [Command.set((first | second).ids)],
        })

        action = batch.action_il_create_masav_file()
        wizard = self.env[action['res_model']].browse(action['res_id'])
        self.assertEqual(wizard.line_ids.payment_id, first | second)
        self.assertTrue(all(wizard.line_ids.mapped('selected')))

        wizard.line_ids.filtered(lambda line: line.payment_id == second).selected = False
        download = wizard.action_generate()
        content = base64.b64decode(wizard.file_data)
        self.assertEqual(download['type'], 'ir.actions.act_url')
        self.assertEqual(len(content), 390)
        self.assertEqual(first.il_masav_file, wizard.file_data)
        self.assertFalse(second.il_masav_file)
        self.assertEqual(batch.export_file, wizard.file_data)
