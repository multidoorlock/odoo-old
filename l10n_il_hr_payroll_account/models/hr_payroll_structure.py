# -*- coding: utf-8 -*-
from odoo import Command, api, fields, models


# Accounts are looked up by code first and then by their exact translated
# name.  This keeps upgrades idempotent and avoids creating a duplicate when a
# customer already has an account for the same purpose under a different code.
IL_PAYROLL_ACCOUNT_SPECS = {
    'salary_expense': ('630000', 'Salary Expenses', 'הוצאות שכר', 'expense'),
    'overtime_expense': ('630100', 'Overtime Expenses', 'הוצאות שכר - שעות נוספות', 'expense'),
    'additional_days_expense': ('630110', 'Additional Days Expenses', 'הוצאות שכר - ימים נוספים', 'expense'),
    'salary_adjustment_expense': ('630120', 'Salary Adjustment Expenses', 'הוצאות התאמות שכר', 'expense'),
    'employer_ni_expense': ('630200', 'Employer National Insurance Expenses', 'הוצאות ביטוח לאומי - מעסיק', 'expense'),
    'employer_pension_expense': ('630300', 'Employer Pension Expenses', 'הוצאות פנסיה - מעסיק', 'expense'),
    'employer_severance_expense': ('630400', 'Employer Severance Expenses', 'הוצאות פיצויים - מעסיק', 'expense'),
    'employer_study_expense': ('630500', 'Employer Study Fund Expenses', 'הוצאות קרן השתלמות - מעסיק', 'expense'),
    'equalization_expense': ('630600', 'Equalization Levy Expenses', 'הוצאות היטל השוואה', 'expense'),
    'payroll_rounding': ('630900', 'Payroll Rounding Differences', 'הפרשי עיגול שכר', 'expense'),
    'salary_payable': ('230000', 'Salaries Payable', 'משכורות לתשלום', 'liability_current'),
    'outstanding_payments': ('101404', 'Outstanding Payments', 'תשלומים בדרך', 'asset_current'),
    'income_tax_payable': ('230110', 'Income Tax Payable', 'מס הכנסה לשלם', 'liability_current'),
    'national_insurance_payable': ('230120', 'National Insurance Payable', 'ביטוח לאומי לשלם', 'liability_current'),
    'health_insurance_payable': ('230130', 'Health Insurance Payable', 'ביטוח בריאות לשלם', 'liability_current'),
    'health_stamp_payable': ('230140', 'Health Stamp Payable', 'בול בריאות לשלם', 'liability_current'),
    'organization_tax_payable': ('230150', 'Organization Tax Payable', 'מס ארגון לשלם', 'liability_current'),
    'pension_payable': ('230300', 'Pension Funds Payable', 'קופות פנסיה לשלם', 'liability_current'),
    'study_fund_payable': ('230400', 'Study Fund Payable', 'קרן השתלמות לשלם', 'liability_current'),
    'severance_payable': ('230500', 'Severance Payable', 'פיצויים לשלם', 'liability_current'),
    'equalization_payable': ('230600', 'Equalization Levy Payable', 'היטל השוואה לשלם', 'liability_current'),
}


# Values are ``(account_debit, account_credit)`` field keys.  Employee
# deductions are negative salary-rule amounts.  Odoo therefore produces their
# desired credit entry from ``account_debit`` (the native payroll accounting
# engine reverses debit/credit for negative amounts).
IL_RULE_ACCOUNT_MAP = {
    'BASIC': ('salary_expense', False),
    'IL_OVERTIME': ('overtime_expense', False),
    'IL_WEEKEND_GROSS': ('overtime_expense', False),
    'IL_ADDITIONAL_DAY_GROSS': ('additional_days_expense', False),
    'IL_ADJUSTMENT_GROSS': ('salary_adjustment_expense', False),
    'IL_ADJUSTMENT_NET_GROSSUP': ('salary_adjustment_expense', False),
    'IL_ISR_INCOME_TAX': ('income_tax_payable', False),
    'IL_PAL_INCOME_TAX': ('income_tax_payable', False),
    'IL_ISR_NI_EE': ('national_insurance_payable', False),
    'IL_PAL_NI_EE': ('national_insurance_payable', False),
    'IL_ISR_HEALTH_EE': ('health_insurance_payable', False),
    'IL_PAL_HEALTH_STAMP': ('health_stamp_payable', False),
    'IL_PAL_ORGANIZATION_TAX': ('organization_tax_payable', False),
    'IL_ISR_PENSION_EE': ('pension_payable', False),
    'IL_PAL_PENSION_EE': ('pension_payable', False),
    'IL_ISR_STUDY_EE': ('study_fund_payable', False),
    'IL_PAL_STUDY_EE': ('study_fund_payable', False),
    'IL_ISR_NI_ER': ('employer_ni_expense', 'national_insurance_payable'),
    'IL_PAL_NI_ER': ('employer_ni_expense', 'national_insurance_payable'),
    'IL_ISR_PENSION_ER': ('employer_pension_expense', 'pension_payable'),
    'IL_PAL_PENSION_ER': ('employer_pension_expense', 'pension_payable'),
    'IL_ISR_SEVERANCE_ER': ('employer_severance_expense', 'severance_payable'),
    'IL_PAL_SEVERANCE_ER': ('employer_severance_expense', 'severance_payable'),
    'IL_ISR_STUDY_ER': ('employer_study_expense', 'study_fund_payable'),
    'IL_PAL_STUDY_ER': ('employer_study_expense', 'study_fund_payable'),
    'IL_PAL_EQUALIZATION_ER': ('equalization_expense', 'equalization_payable'),
    'NET': (False, 'salary_payable'),
}


IL_STRUCTURE_XMLIDS = {
    'IL_ISR_MONTHLY': 'hr_payroll_structure_il',
    'IL_PAL_MONTHLY': 'hr_payroll_structure_il_pal_monthly',
    'IL_ISR_DAILY': 'hr_payroll_structure_il_isr_daily',
    'IL_PAL_DAILY': 'hr_payroll_structure_il_pal_daily',
}


IL_RULE_XMLIDS = {
    'BASIC': 'hr_salary_rule_il_basic',
    'IL_WAGE_ROUNDING': 'hr_salary_rule_il_wage_rounding',
    'IL_OVERTIME': 'hr_salary_rule_il_overtime',
    'IL_ADDITIONAL_DAY_GROSS': 'hr_salary_rule_il_additional_day_gross',
    'IL_ADJUSTMENT_GROSS': 'hr_salary_rule_il_adjustment_gross',
    'IL_ADJUSTMENT_NET_GROSSUP': 'hr_salary_rule_il_adjustment_net_grossup',
    'GROSS': 'hr_salary_rule_il_gross',
    'IL_TAX_BASE': 'hr_salary_rule_il_tax_base',
    'IL_NI_BASE': 'hr_salary_rule_il_ni_base',
    'IL_PENSION_BASE': 'hr_salary_rule_il_pension_base',
    'IL_SEVERANCE_BASE': 'hr_salary_rule_il_severance_base',
    'IL_STUDY_FUND_BASE': 'hr_salary_rule_il_study_fund_base',
    'IL_PAL_EQUALIZATION_BASE': 'hr_salary_rule_il_pal_equalization_base',
    'IL_ISR_INCOME_TAX': 'hr_salary_rule_il_isr_income_tax',
    'IL_ISR_NI_EE': 'hr_salary_rule_il_isr_ni_ee',
    'IL_ISR_HEALTH_EE': 'hr_salary_rule_il_isr_health_ee',
    'IL_ISR_PENSION_EE': 'hr_salary_rule_il_isr_pension_ee',
    'IL_ISR_STUDY_EE': 'hr_salary_rule_il_isr_study_ee',
    'IL_ISR_NI_ER': 'hr_salary_rule_il_isr_ni_er',
    'IL_ISR_PENSION_ER': 'hr_salary_rule_il_isr_pension_er',
    'IL_ISR_SEVERANCE_ER': 'hr_salary_rule_il_isr_severance_er',
    'IL_ISR_STUDY_ER': 'hr_salary_rule_il_isr_study_er',
    'IL_PAL_INCOME_TAX': 'hr_salary_rule_il_pal_income_tax',
    'IL_PAL_NI_EE': 'hr_salary_rule_il_pal_ni_ee',
    'IL_PAL_HEALTH_STAMP': 'hr_salary_rule_il_pal_health_stamp',
    'IL_PAL_ORGANIZATION_TAX': 'hr_salary_rule_il_pal_organization_tax',
    'IL_PAL_PENSION_EE': 'hr_salary_rule_il_pal_pension_ee',
    'IL_PAL_STUDY_EE': 'hr_salary_rule_il_pal_study_ee',
    'IL_PAL_NI_ER': 'hr_salary_rule_il_pal_ni_er',
    'IL_PAL_EQUALIZATION_ER': 'hr_salary_rule_il_pal_equalization_er',
    'IL_PAL_PENSION_ER': 'hr_salary_rule_il_pal_pension_er',
    'IL_PAL_SEVERANCE_ER': 'hr_salary_rule_il_pal_severance_er',
    'IL_PAL_STUDY_ER': 'hr_salary_rule_il_pal_study_er',
    'IL_FOR_INCOME_TAX': 'hr_salary_rule_il_for_income_tax',
    'IL_FOR_NI_EE': 'hr_salary_rule_il_for_ni_ee',
    'IL_FOR_PRIVATE_HEALTH_EE': 'hr_salary_rule_il_for_private_health_ee',
    'IL_FOR_HOUSING_EE': 'hr_salary_rule_il_for_housing_ee',
    'IL_FOR_HOUSING_EXPENSES_EE': 'hr_salary_rule_il_for_housing_expenses_ee',
    'IL_FOR_PENSION_EE': 'hr_salary_rule_il_for_pension_ee',
    'IL_FOR_STUDY_EE': 'hr_salary_rule_il_for_study_ee',
    'IL_FOR_NI_ER': 'hr_salary_rule_il_for_ni_er',
    'IL_FOR_PENSION_ER': 'hr_salary_rule_il_for_pension_er',
    'IL_FOR_SEVERANCE_ER': 'hr_salary_rule_il_for_severance_er',
    'IL_FOR_DEPOSIT_ER': 'hr_salary_rule_il_for_deposit_er',
    'IL_FOR_STUDY_ER': 'hr_salary_rule_il_for_study_er',
    'IL_PAYSLIP_ROUNDING': 'hr_salary_rule_il_payslip_rounding',
    'NET': 'hr_salary_rule_il_net',
    'IL_PAYMENTS': 'hr_salary_rule_il_payments',
    'IL_NET_TO_PAY': 'hr_salary_rule_il_net_to_pay',
    'IL_EMPLOYER_COST': 'hr_salary_rule_il_employer_cost',
}


IL_RETIRED_RULE_CODES = {
    'IL_WAGE_ROUNDING',
    'IL_PAYSLIP_ROUNDING',
    'IL_PAYMENTS',
    'IL_NET_TO_PAY',
    *[code for code in IL_RULE_XMLIDS if code.startswith('IL_FOR_')],
}


class HrPayrollStructure(models.Model):
    _inherit = 'hr.payroll.structure'

    # Odoo 19 structures are shared records and no longer expose the
    # ``company_id`` field used by older clients/views.  Keep a read-only,
    # context-aware compatibility value so a stale or external search_read
    # cannot crash the request.  The company-dependent salary journal remains
    # the authoritative source when one is configured.
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        compute='_compute_il_compat_company_id',
        readonly=True,
    )

    @api.depends_context('company')
    @api.depends('journal_id')
    def _compute_il_compat_company_id(self):
        for structure in self:
            structure.company_id = (
                structure.journal_id.company_id or structure.env.company
            )

    @api.model
    def _il_bind_existing_structure_xmlids(self):
        """Adopt existing Israeli payroll records before XML data is loaded.

        A database may already contain the structures and rules created by an
        earlier/manual setup while their module XML IDs are missing.  Binding
        the stable codes first lets the regular ``noupdate=0`` XML records
        update those rows in place instead of creating a second payroll setup.
        """
        module = 'l10n_il_hr_payroll_account'
        IrModelData = self.env['ir.model.data'].sudo()

        def bind(xml_name, record):
            if not record or IrModelData.search_count([
                ('module', '=', module), ('name', '=', xml_name),
            ]):
                return
            IrModelData._update_xmlids([{
                'xml_id': f'{module}.{xml_name}',
                'record': record,
                'noupdate': False,
            }])

        structures = self.with_context(active_test=False).search([
            ('code', 'in', tuple(IL_STRUCTURE_XMLIDS)),
        ])
        selected = {}
        for code, xml_name in IL_STRUCTURE_XMLIDS.items():
            matches = structures.filtered(lambda item: item.code == code)
            active = matches.filtered('active')
            record = (active or matches).sorted('id')[:1]
            if record:
                selected[code] = record
                bind(xml_name, record)

        monthly = selected.get('IL_ISR_MONTHLY') or selected.get('IL_PAL_MONTHLY')
        daily = selected.get('IL_ISR_DAILY') or selected.get('IL_PAL_DAILY')
        if monthly:
            bind('hr_payroll_structure_type_il', monthly.type_id)
        if daily:
            bind('hr_payroll_structure_type_il_daily', daily.type_id)

        country = self.env.ref('base.il')
        Category = self.env['hr.salary.rule.category'].with_context(active_test=False)
        bind('hr_salary_rule_category_il_adj', Category.search([
            ('code', '=', 'IL_ADJ'), ('country_id', '=', country.id),
        ], limit=1))
        bind('hr_salary_rule_category_il_base', Category.search([
            ('code', '=', 'IL_BASE'), ('country_id', '=', country.id),
        ], limit=1))

        template = selected.get('IL_ISR_MONTHLY')
        if template:
            rules = template.with_context(active_test=False).rule_ids
            for code, xml_name in IL_RULE_XMLIDS.items():
                matches = rules.filtered(lambda item: item.code == code)
                active = matches.filtered('active')
                bind(xml_name, (active or matches).sorted('id')[:1])
        return True

    @api.model
    def _il_ensure_payroll_accounting_configuration(self, overwrite=False):
        """Create missing payroll accounts and map existing IL salary rules.

        No salary rule is created here.  With the default ``overwrite=False``,
        an accountant's existing rule mapping is preserved.  ``overwrite`` is
        reserved for an explicit setup/reset operation.
        """
        company = self.env.company
        Account = self.env['account.account'].with_company(company).with_context(
            allowed_company_ids=[company.id],
        )
        hebrew_installed = bool(self.env['res.lang']._lang_get('he_IL'))
        accounts = {}
        for key, (code, name_en, name_he, account_type) in IL_PAYROLL_ACCOUNT_SPECS.items():
            account = Account.search([
                ('company_ids', 'in', company.id),
                ('code', '=', code),
            ], limit=1)
            if not account:
                account = Account.with_context(lang='en_US').search([
                    ('company_ids', 'in', company.id),
                    ('name', '=', name_en),
                ], limit=1)
            if not account and hebrew_installed:
                account = Account.with_context(lang='he_IL').search([
                    ('company_ids', 'in', company.id),
                    ('name', '=', name_he),
                ], limit=1)
            if not account:
                account = Account.with_context(lang='en_US').create({
                    'code': code,
                    'name': name_en,
                    'account_type': account_type,
                    'company_ids': [Command.set(company.ids)],
                    'reconcile': True,
                })
                if hebrew_installed:
                    account.with_context(lang='he_IL').name = name_he
            elif not account.reconcile:
                account.reconcile = True
            accounts[key] = account

        structures = self.with_context(active_test=False).search([
            ('code', 'in', (
                'IL_ISR_MONTHLY', 'IL_ISR_DAILY',
                'IL_PAL_MONTHLY', 'IL_PAL_DAILY',
            )),
        ])
        # Odoo uses the salary journal's default account only for the balancing
        # line when independently rounded salary components differ by a cent.
        # It is an accounting adjustment and does not add a rounding rule or a
        # visible rounding line to the payslip.
        for journal in structures.mapped('journal_id').filtered(
                lambda item: item.company_id == company and not item.default_account_id):
            journal.default_account_id = accounts['payroll_rounding']
        rules = structures.mapped('rule_ids').with_context(active_test=False).filtered(
            lambda rule: rule.code in IL_RULE_ACCOUNT_MAP
        )
        for rule in rules.with_company(company):
            debit_key, credit_key = IL_RULE_ACCOUNT_MAP[rule.code]
            desired = {
                'account_debit': accounts.get(debit_key) if debit_key else False,
                'account_credit': accounts.get(credit_key) if credit_key else False,
            }
            values = {
                field_name: account
                for field_name, account in desired.items()
                if overwrite or not rule[field_name]
            }
            if values:
                rule.write(values)
        payment_accounts = {
            'il_employee_payment_debit_account_id': accounts['salary_payable'],
            'il_employee_payment_credit_account_id': accounts['outstanding_payments'],
        }
        company_values = {
            field_name: account
            for field_name, account in payment_accounts.items()
            if overwrite or not company[field_name]
        }
        if company_values:
            company.write(company_values)
        return True

    @api.model
    def _il_sync_structures_and_rules(self):
        refs = {
            'isr_monthly': self.env.ref('l10n_il_hr_payroll_account.hr_payroll_structure_il'),
            'pal_monthly': self.env.ref('l10n_il_hr_payroll_account.hr_payroll_structure_il_pal_monthly'),
            'isr_daily': self.env.ref('l10n_il_hr_payroll_account.hr_payroll_structure_il_isr_daily'),
            'pal_daily': self.env.ref('l10n_il_hr_payroll_account.hr_payroll_structure_il_pal_daily'),
        }
        canonical_structures = self.browse(
            [structure.id for structure in refs.values()])
        canonical_structures.write({'active': True})
        country = self.env.ref('base.il')
        obsolete_structures = self.with_context(active_test=False).search([
            ('country_id', '=', country.id),
            ('id', 'not in', [structure.id for structure in refs.values()]),
        ])
        for structure in obsolete_structures:
            if self.env['hr.payslip'].search_count([('struct_id', '=', structure.id)]):
                structure.active = False
            else:
                structure.unlink()
        template = refs['isr_monthly']

        def retire(rule):
            """Never delete a salary rule referenced by historical payslip lines."""
            if self.env['hr.payslip.line'].search_count([('salary_rule_id', '=', rule.id)]):
                rule.write({
                    'active': False,
                    'appears_on_payslip': False,
                })
            else:
                rule.unlink()

        desired_codes = set(IL_RULE_XMLIDS) - IL_RETIRED_RULE_CODES
        canonical_rules = self.env['hr.salary.rule']
        for code in desired_codes:
            rule = self.env.ref(
                f'l10n_il_hr_payroll_account.{IL_RULE_XMLIDS[code]}')
            rule.write({'struct_id': template.id, 'active': True})
            canonical_rules |= rule

        # The module definitions are the complete source of truth. Remove
        # every other rule from the template, including old module versions,
        # manual additions and native Odoo defaults. A rule referenced by a
        # historical payslip is archived instead of deleted.
        template_rules = template.with_context(active_test=False).rule_ids
        for obsolete in template_rules - canonical_rules:
            retire(obsolete)

        # Every Israeli structure receives the exact same active rule set.
        # Population conditions decide which deductions apply; monthly/daily
        # structures now differ only in how BASIC is sourced from work days.
        rules = canonical_rules.sorted(lambda rule: (rule.sequence, rule.id))
        values_by_key = {}
        for key in ('pal_monthly', 'isr_daily', 'pal_daily'):
            values_by_key[key] = []
            for rule in rules:
                values = rule.copy_data(default={
                    'struct_id': False,
                    # copy_data adds "(copy)" by default. These are the same
                    # statutory rules in another structure, so keep the
                    # canonical user-facing name.
                    'name': rule.name,
                })[0]
                values_by_key[key].append((rule.code, values))
        inputs = template.input_line_type_ids

        # Keep XML-owned template rules stable across upgrades while retiring
        # the unsupported legacy population.
        for rule in template.with_context(active_test=False).rule_ids.filtered(
                lambda item: item.active and item.code.startswith('IL_FOR_')):
            retire(rule)
        for key, structure in refs.items():
            if key == 'isr_monthly':
                structure.input_line_type_ids = inputs
                continue
            existing_rules = structure.with_context(active_test=False).rule_ids
            structure_codes = {code for code, values in values_by_key[key]}
            for code, values in values_by_key[key]:
                matches = existing_rules.filtered(lambda item: item.code == code)
                values.update({'struct_id': structure.id, 'active': True})
                if matches:
                    matches[:1].write(values)
                    for duplicate in matches[1:]:
                        retire(duplicate)
                else:
                    self.env['hr.salary.rule'].create(values)
            refreshed = structure.with_context(active_test=False).rule_ids
            for code in structure_codes:
                matches = refreshed.filtered(lambda item: item.code == code)
                for duplicate in matches[1:]:
                    retire(duplicate)
            for rule in refreshed.filtered(
                    lambda item: item.code not in structure_codes):
                retire(rule)
            structure.input_line_type_ids = inputs
        return True
