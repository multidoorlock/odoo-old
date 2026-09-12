from datetime import date

from odoo import Command
from odoo.tests.common import TransactionCase, new_test_user, tagged

from . import test_payment_reconciliation as payment_fixtures


@tagged('post_install', '-at_install', 'il_payslip_payment_toolbar')
class TestPayslipPaymentToolbar(TransactionCase):
    """Simulate the native view-service and selected Actions RPC contracts.

    The view request intentionally drops arbitrary action context, exactly
    as web/static/src/views/view_service.js does. Action execution retains
    the full context and selected IDs, as native ActionMenus.executeAction.
    """

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
            'name': 'Native Toolbar Simulation Employee', 'company_id': cls.company.id,
            'contract_date_start': date(2026, 1, 1), 'date_version': date(2026, 1, 1),
            'mdl_wage_type': 'mdl_monthly', 'structure_type_id': cls.monthly_type.id,
            'il_salary_structure_id': cls.monthly_structure.id, 'schedule_pay': 'monthly',
        })
        user_values = {
            'company_id': cls.company.id, 'company_ids': [Command.set(cls.company.ids)],
            'lang': 'en_US',
        }
        UsersEnv = cls.env(context=dict(cls.env.context, no_reset_password=True))
        cls.payroll_user = new_test_user(
            UsersEnv, login='il_native_toolbar_hr',
            groups='base.group_user,hr_payroll.group_hr_payroll_manager,account.group_account_manager',
            **user_values)
        cls.accounting_user = new_test_user(
            UsersEnv, login='il_native_toolbar_accounting',
            groups='base.group_user,account.group_account_manager', **user_values)
        prefix = 'l10n_il_hr_payroll_account.'
        cls.linked_view = cls.env.ref(prefix + 'view_account_payment_list_payslip_links')
        cls.candidate_view = cls.env.ref(prefix + 'view_account_payment_list_payslip_candidates')
        cls.normal_view = cls.env.ref(prefix + 'view_account_payment_list_employee')
        cls.form_view = cls.env.ref('account.view_account_payment_form')
        cls.edit_action = cls.env.ref(prefix + 'action_payslip_change_recognized_amount')
        cls.remove_action = cls.env.ref(prefix + 'action_payslip_remove_payment_links')
        cls.payroll_action_ids = {cls.edit_action.id, cls.remove_action.id}

    _payment = payment_fixtures.TestEmployeePaymentReconciliation._payment
    _payslip_with_posted_net = payment_fixtures.TestEmployeePaymentReconciliation._payslip_with_posted_net

    def _client_views(self, view, context=None, user=None, toolbar=True, include_form=False):
        full_context = dict(context or {}, lang='en_US')
        filtered_context = {key: value for key, value in full_context.items()
                            if key == 'lang' or key.endswith('_view_ref')}
        Payment = self.env['account.payment'].with_user(user or self.payroll_user)
        views = [(view.id, 'list')]
        if include_form:
            views.append((self.form_view.id, 'form'))
        return Payment.with_context(filtered_context).get_views(views, options={
            'action_id': False, 'embedded_action_id': False,
            'embedded_parent_res_id': False, 'load_filters': False, 'toolbar': toolbar,
        })['views']

    @staticmethod
    def _action_ids(views):
        return {action['id'] for action in views['list'].get('toolbar', {}).get('action', [])}

    def test_native_filtered_view_context_still_exposes_selected_actions(self):
        context = {'il_payslip_id': 123, 'il_payslip_link_list': True,
                   'allowed_company_ids': self.company.ids, 'create': False}
        self.assertEqual(self._action_ids(self._client_views(self.linked_view, context)),
                         self.payroll_action_ids)
        # No payslip ID is needed for cacheable view metadata. The actual
        # selected action checks the source payslip at execution time.
        self.assertEqual(self._action_ids(self._client_views(self.linked_view)),
                         self.payroll_action_ids)

    def test_toolbar_roles_do_not_leak_between_cached_view_request_orders(self):
        baseline = self._client_views(self.normal_view, include_form=True)
        ordinary_ids = self._action_ids(baseline)
        self.assertFalse(ordinary_ids & self.payroll_action_ids)
        self.assertTrue(ordinary_ids)
        for order in (
            (self.linked_view, self.candidate_view, self.normal_view),
            (self.normal_view, self.linked_view, self.candidate_view),
            (self.candidate_view, self.normal_view, self.linked_view),
        ):
            for view in order:
                result = self._client_views(view, include_form=True)
                expected = (self.payroll_action_ids if view == self.linked_view else
                            set() if view == self.candidate_view else ordinary_ids)
                self.assertEqual(self._action_ids(result), expected)
                self.assertEqual(result['form'].get('toolbar'), baseline['form'].get('toolbar'))
                self.assertEqual(result['list']['toolbar'].get('print'),
                                 baseline['list']['toolbar'].get('print'))

    def test_ordinary_bindings_ignore_payroll_flags_and_respect_native_groups(self):
        Actions = self.env['ir.actions.actions'].with_user(self.payroll_user)
        ordinary = Actions.get_bindings('account.payment')
        for flags in ({}, {'il_payslip_id': 123, 'il_payslip_link_list': True},
                      {'il_payslip_id': 123, 'il_payslip_candidate_list': True}):
            self.assertEqual(Actions.with_context(**flags).get_bindings('account.payment'), ordinary)
        self.assertFalse(self.accounting_user.has_group('hr_payroll.group_hr_payroll_user'))
        self.assertFalse(self.env['ir.actions.actions'].with_user(
            self.accounting_user)._il_payslip_payment_bindings())
        accounting = self._client_views(self.linked_view, user=self.accounting_user)
        self.assertFalse(self._action_ids(accounting))
        self.assertEqual(self._action_ids(self._client_views(self.linked_view)), self.payroll_action_ids)

    def test_toolbar_not_requested_remains_absent(self):
        result = self._client_views(self.linked_view, toolbar=False)
        self.assertNotIn('toolbar', result['list'])

    def _run_selected_action(self, action, payment, source_action):
        # Native ActionMenus loads bindings with stripped view context, then
        # merges original action context with the current selection to run.
        context = dict(source_action['context'], active_id=payment.id,
                       active_ids=payment.ids, active_model='account.payment',
                       active_domain=source_action['domain'])
        returned = action.with_user(self.payroll_user).with_context(context).run()
        self.assertEqual(returned['target'], 'new')
        wizard = self.env[returned['res_model']].with_user(self.payroll_user).browse(returned['res_id'])
        self.assertEqual(wizard.source_payslip_id.id, context['il_payslip_id'])
        self.assertEqual(wizard.line_ids.payment_id.ids, payment.ids)
        return wizard

    def test_selected_native_server_actions_change_and_remove_only_the_selected_link(self):
        slip = self._payslip_with_posted_net(2000.0)
        payment = self._payment(1000.0)
        retained = self._payment(300.0)
        (payment | retained).il_split_line_ids._il_reconcile_with_payslip(slip)
        source_action = slip.with_user(self.payroll_user).action_il_open_payments()
        toolbar = self._client_views(self.linked_view, source_action['context'])
        self.assertEqual(self._action_ids(toolbar), self.payroll_action_ids)
        financial = (payment.amount, payment.move_id.state,
                     payment.move_id.line_ids.mapped('balance'), slip.line_ids.mapped('total'))
        retained_partial = retained._il_payslip_link_partials()
        edit = self._run_selected_action(self.edit_action, payment, source_action)
        self.assertEqual(edit.operation, 'edit')
        edit.line_ids.amount = 400.0
        edit.action_apply()
        self.assertEqual(payment.with_context(il_payslip_id=slip.id).il_payslip_linked_amount, 400.0)
        self.assertEqual(retained._il_payslip_link_partials(), retained_partial)
        self.assertEqual(slip.il_net_amount_to_pay, 1300.0)
        removal = self._run_selected_action(self.remove_action, payment, source_action)
        self.assertEqual(removal.operation, 'remove')
        removal.action_apply()
        self.assertFalse(payment._il_payslip_link_partials())
        self.assertEqual(retained._il_payslip_link_partials(), retained_partial)
        self.assertEqual(slip.il_net_amount_to_pay, 1700.0)
        self.assertEqual((payment.amount, payment.move_id.state,
                          payment.move_id.line_ids.mapped('balance'), slip.line_ids.mapped('total')),
                         financial)
