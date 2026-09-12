import json
from datetime import date
from pathlib import Path
from unittest import SkipTest

from odoo import Command
from odoo.tests.common import HttpCase, new_test_user, tagged

from . import test_payment_reconciliation as payment_fixtures
from . import test_reconciliation_editor as reconciliation_fixtures


@tagged('post_install', '-at_install', 'il_payroll_frontend_simulation')
class TestPayslipPaymentUI(HttpCase):
    """Actual native web client + real RPC on HttpCase rollback cursors.

    This uses Odoo's headless Chrome driver, never Edge, saved sessions or
    existing financial records. No test creates or commits production data.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].browse(2).exists()
        if not cls.company:
            raise SkipTest('This STAGING UI simulation requires configured company 2.')
        cls.env = cls.env(context=dict(cls.env.context, allowed_company_ids=[cls.company.id],
                                       tracking_disable=True, no_reset_password=True,
                                       mail_create_nolog=True))
        cls.company = cls.env['res.company'].browse(cls.company.id)
        cls.payable = cls.company.il_employee_payment_debit_account_id
        cls.outstanding = cls.company.il_employee_payment_credit_account_id
        assert cls.payable and cls.outstanding, 'Configure STAGING employee payment accounts first'
        cls.expense = cls.env['account.account'].search([
            ('company_ids', 'in', cls.company.id), ('account_type', '=', 'expense')], limit=1)
        cls.bank_journal = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id), ('type', '=', 'bank')], limit=1)
        cls.general_journal = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id), ('type', '=', 'general')], limit=1)
        cls.monthly_type = cls.env.ref('l10n_il_hr_payroll_account.hr_payroll_structure_type_il')
        cls.monthly_structure = cls.env.ref('l10n_il_hr_payroll_account.hr_payroll_structure_il')
        cls.employee = cls.env['hr.employee'].create({
            'name': 'UI Simulation Employee', 'company_id': cls.company.id,
            'contract_date_start': date(2026, 1, 1), 'date_version': date(2026, 1, 1),
            'mdl_wage_type': 'mdl_monthly', 'schedule_pay': 'monthly',
            'structure_type_id': cls.monthly_type.id,
            'il_salary_structure_id': cls.monthly_structure.id,
        })
        cls.browser_user = new_test_user(
            cls.env, login='il_payroll_ui_simulation', name='Payroll UI Simulation',
            groups='base.group_user,base.group_allow_export,hr_payroll.group_hr_payroll_manager,account.group_account_manager',
            company_id=cls.company.id, company_ids=[Command.set(cls.company.ids)],
            lang='he_IL')

    _payment = payment_fixtures.TestEmployeePaymentReconciliation._payment
    _payslip_with_posted_net = payment_fixtures.TestEmployeePaymentReconciliation._payslip_with_posted_net
    _settle = reconciliation_fixtures.TestPayrollReconciliationEditor._settle

    def _fixture(self):
        self.slip = self._payslip_with_posted_net(2000.0)
        self.other_slip = self._payslip_with_posted_net(1000.0)
        self.alpha = self._payment(3000.0)
        self.beta = self._payment(500.0)
        self.gamma = self._payment(700.0)
        self.delta = self._payment(1000.0)
        self.exhausted = self._payment(250.0)
        self.payments = self.alpha | self.beta | self.gamma | self.delta | self.exhausted
        for payment, memo in zip(self.payments, (
                'UI-ALPHA', 'UI-BETA', 'UI-GAMMA', 'UI-DELTA', 'UI-EXHAUSTED')):
            # Memos are fixture data, written before the browser begins.
            payment.memo = memo
        Split = self.env['account.payment.split.line']
        for payment, slip, amount in (
                (self.alpha, self.slip, 1000.0), (self.beta, self.slip, 200.0),
                (self.delta, self.other_slip, 400.0), (self.exhausted, self.other_slip, 250.0)):
            Split._il_take_open_amount(payment, amount)._il_reconcile_with_payslip(slip)
        self.bank_partials = self._settle(self.alpha)
        self.assertEqual(self.alpha.state, 'paid')
        self.baseline = self._financial_values()
        action = self.slip.action_il_open_payments()
        self.ui_action = self.env['ir.actions.act_window'].create({
            'name': 'תשלומים מקושרים — בדיקת ממשק', 'res_model': 'account.payment',
            'view_mode': 'list,form', 'domain': repr(action['domain']),
            'context': repr(dict(action['context'], allowed_company_ids=self.company.ids)),
            'search_view_id': self.env.ref('account.view_account_payment_search').id,
            'view_ids': [Command.create({'sequence': index + 1, 'view_mode': mode,
                                        'view_id': view_id})
                         for index, (view_id, mode) in enumerate(action['views'])],
        })
        self.env.flush_all()

    def _financial_values(self):
        return {
            'payments': self.payments.sorted('id').read([
                'amount', 'date', 'partner_id', 'currency_id', 'move_id', 'state']),
            'items': (self.payments.move_id.line_ids | self.slip.move_id.line_ids
                      | self.other_slip.move_id.line_ids).sorted('id').read([
                          'account_id', 'partner_id', 'debit', 'credit', 'currency_id', 'amount_currency']),
            'salary': (self.slip | self.other_slip).line_ids.sorted('id').read(['code', 'amount', 'total']),
            'bank': self.bank_partials.sorted('id').read(['amount', 'debit_move_id', 'credit_move_id']),
            'other_slip': self.other_slip._il_reconciliations().sorted('id').read([
                'amount', 'debit_move_id', 'credit_move_id']),
        }

    def _simulate(self, scenario):
        self._fixture()
        settings = {'scenario': scenario, 'slipId': self.slip.id, 'alphaId': self.alpha.id,
                    'companyId': self.company.id}
        code = 'window.payrollSimulation = ' + json.dumps(settings) + ';\n'
        code += Path(__file__).with_name('payslip_payment_ui.js').read_text(encoding='utf-8')
        self.browser_js(
            '/odoo/action-%s?debug=assets' % self.ui_action.id, code,
            ready="document.querySelector('.o_web_client')",
            login=self.browser_user.login, timeout=180)
        self.env.invalidate_all()
        self.assertEqual(self._financial_values(), self.baseline)

    def test_selected_edit_cancel_cap_and_stale_form_recovery(self):
        self._simulate('edit_recovery')
        self.assertEqual(self.alpha.il_applied_amount, 650.0)
        self.assertEqual(self.beta.il_applied_amount, 200.0)

    def test_multi_selection_remove_and_native_candidate_add(self):
        self._simulate('multi_add_remove')
        self.assertEqual(self.alpha.il_applied_amount, 1000.0)
        self.assertEqual(self.beta.il_applied_amount, 200.0)
        self.assertFalse(self.gamma.il_applied_amount)

    def test_native_filter_export_and_back_navigation(self):
        self._simulate('filter_export_back')
        self.assertEqual(self.alpha.il_applied_amount, 1000.0)
        self.assertEqual(self.beta.il_applied_amount, 200.0)
