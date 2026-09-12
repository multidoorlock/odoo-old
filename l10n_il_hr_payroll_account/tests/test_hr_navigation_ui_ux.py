import json
from datetime import date
from pathlib import Path
from unittest import SkipTest

from odoo import Command
from odoo.tests.common import HttpCase, new_test_user, tagged


@tagged('post_install', '-at_install', 'il_payroll_frontend_simulation')
class TestHRNavigationUIUX(HttpCase):
    """Use the real web client and native controls on rollback-only fixtures."""

    browser_size = '1280x1000'

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        company = cls.env['res.company'].browse(2).exists()
        if not company:
            raise SkipTest('This STAGING UI simulation requires configured company 2.')
        cls.env = cls.env(context=dict(
            cls.env.context, allowed_company_ids=company.ids, tracking_disable=True,
            no_reset_password=True, mail_create_nolog=True))
        cls.company = cls.env['res.company'].browse(company.id)
        cls.payable = cls.company.il_employee_payment_debit_account_id
        assert cls.payable, 'Configure the STAGING employee payroll account first'
        cls.journal = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id), ('type', '=', 'bank')], limit=1)
        cls.general_journal = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id), ('type', '=', 'general')], limit=1)
        cls.expense = cls.env['account.account'].search([
            ('company_ids', 'in', cls.company.id), ('account_type', '=', 'expense')], limit=1)
        cls.employees = cls.env['hr.employee'].create([{
            'name': name, 'company_id': cls.company.id,
            'contract_date_start': date(2026, 1, 1), 'date_version': date(2026, 1, 1),
            'mdl_wage_type': 'mdl_monthly', 'schedule_pay': 'monthly',
            'structure_type_id': cls.env.ref(
                'l10n_il_hr_payroll_account.hr_payroll_structure_type_il').id,
            'il_salary_structure_id': cls.env.ref(
                'l10n_il_hr_payroll_account.hr_payroll_structure_il').id,
        } for name in ('UI Navigation Employee A', 'UI Navigation Employee B')])
        cls.employee, cls.other = cls.employees
        groups = [
            'base.group_user', 'base.group_allow_export',
            'hr_payroll.group_hr_payroll_manager', 'account.group_account_manager',
        ]
        for optional in ('documents.group_documents_user',
                         'maintenance.group_equipment_manager',
                         'hr_attendance.group_hr_attendance_manager'):
            if cls.env.ref(optional, raise_if_not_found=False):
                groups.append(optional)
        cls.browser_user = new_test_user(
            cls.env, login='il_hr_navigation_ui_simulation', name='HR Navigation UI Simulation',
            groups=','.join(groups), company_id=cls.company.id,
            company_ids=[Command.set(cls.company.ids)], lang='he_IL')

    def _payment(self, employee, amount, memo):
        return self.env['account.payment'].with_context(il_employee_payment=True).create({
            'partner_id': employee.work_contact_id.id, 'company_id': self.company.id,
            'payment_type': 'outbound', 'partner_type': 'supplier',
            'journal_id': self.journal.id, 'date': date(2026, 9, 1),
            'currency_id': self.company.currency_id.id, 'amount': amount, 'memo': memo,
        })

    def _net_move(self, employee, amount, name, posted=True):
        move = self.env['account.move'].create({
            'journal_id': self.general_journal.id, 'date': date(2026, 9, 1),
            'line_ids': [
                Command.create({'account_id': self.expense.id, 'debit': amount, 'name': name}),
                Command.create({'account_id': self.payable.id,
                                'partner_id': employee.work_contact_id.id,
                                'credit': amount, 'name': name}),
            ],
        })
        if posted:
            move.action_post()
        return move

    def _simulate(self, model, record, view_xmlid, settings):
        action = self.env['ir.actions.act_window'].create({
            'name': 'בדיקת ניווט בממשק', 'res_model': model, 'res_id': record.id,
            'view_mode': 'form', 'view_id': self.env.ref(view_xmlid).id,
            'context': repr({'allowed_company_ids': self.company.ids}),
        })
        code = 'window.hrNavigationSimulation = ' + json.dumps(settings) + ';\n'
        code += Path(__file__).with_name('hr_navigation_ui_ux.js').read_text(encoding='utf-8')
        self.browser_js(
            '/odoo/action-%s?debug=assets' % action.id, code,
            ready="document.querySelector('.o_web_client')",
            login=self.browser_user.login, timeout=180)
        self.env.invalidate_all()

    def test_batch_flat_tab_grouped_native_list_search_and_export_cancel(self):
        first = self._payment(self.employee, 100, 'UI-NAV-ALPHA')
        second = self._payment(self.employee, 500, 'UI-NAV-BETA')
        third = self._payment(self.other, 900, 'UI-NAV-GAMMA')
        # Same employee and date outside this batch detects a lost batch domain.
        outsider = self._payment(self.employee, 777, 'UI-NAV-OUTSIDE')
        payments = first | second | third
        batch = self.env['account.batch.payment'].create({
            'name': 'UI Navigation Batch', 'date': date(2026, 9, 1),
            'journal_id': self.journal.id, 'batch_type': 'outbound',
            'payment_method_id': first.payment_method_id.id,
            'payment_ids': [Command.set(payments.ids)],
        })
        fields = ['amount', 'state', 'memo', 'batch_payment_id', 'move_id']
        before = (payments | outsider).read(fields)
        self._simulate('account.batch.payment', batch,
                       'account_batch_payment.view_batch_payment_form', {
                           'scenario': 'batch', 'employeeA': self.employee.name,
                           'employeeB': self.other.name,
                           'flatTotal': sum(payments.mapped('amount_signed')),
                       })
        self.assertEqual((payments | outsider).read(fields), before)
        self.assertEqual(batch.payment_ids, payments)

    def test_employee_buttons_and_removable_native_ledger_filters(self):
        open_move = self._net_move(self.employee, 1200, 'UI-NAV-OPEN')
        paid_move = self._net_move(self.employee, 300, 'UI-NAV-CLOSED')
        draft = self._net_move(self.employee, 50, 'UI-NAV-DRAFT', posted=False)
        outsider = self._net_move(self.other, 999, 'UI-NAV-OTHER-EMPLOYEE')
        payment = self._payment(self.employee, 300, 'UI-NAV-SETTLED')
        payment.action_post()
        (paid_move | payment.move_id).line_ids.filtered(
            lambda line: line.account_id == self.payable).reconcile()
        moves = open_move | paid_move | draft | outsider | payment.move_id
        before = moves.line_ids.sorted('id').read([
            'account_id', 'partner_id', 'debit', 'credit', 'amount_residual', 'parent_state'])
        for count in ('document_count', 'equipment_count'):
            if count in self.employee._fields:
                self.assertEqual(self.employee[count], 0)
        equipment = self.env.ref('maintenance.hr_equipment_action', raise_if_not_found=False)
        search = self.env.ref('account.view_account_move_line_filter').with_context(
            lang='he_IL')._get_combined_arch()
        labels = {name: search.xpath("//filter[@name='%s']" % name)[0].get('string')
                  for name in ('posted', 'unreconciled')}
        self._simulate('hr.employee', self.employee, 'hr.view_employee_form', {
            'scenario': 'employee', 'employeeName': self.employee.name,
            'newPayslipAction': str(self.env.ref('hr_payroll.action_hr_payslip_new').id),
            'equipmentAction': str(equipment.id) if equipment else None,
            'filterLabels': labels,
        })
        self.assertEqual(moves.line_ids.sorted('id').read([
            'account_id', 'partner_id', 'debit', 'credit', 'amount_residual', 'parent_state']), before)
