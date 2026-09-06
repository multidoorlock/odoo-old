# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError

# ענפי משק (מוצג לעובד פלסטיני / זר בלבד)
IL_EMPLOYMENT_SECTORS = [
    ('construction', 'בניין'),
    ('industry', 'תעשייה'),
    ('agriculture', 'חקלאות'),
    ('hospitality', 'מלונאות'),
    ('trade_services', 'מסחר ושירותים'),
    ('restaurants', 'מסעדות'),
    ('nursing', 'סיעוד'),
    ('other', 'אחר'),
]


class HrVersion(models.Model):
    _inherit = 'hr.version'

    # ------------------------------------------------------------------
    # פרטים אישיים (סעיף "פרטים אישיים" באפיון חלק ב')
    # ------------------------------------------------------------------
    il_salary_structure_id = fields.Many2one(
        'hr.payroll.structure', string='מבנה שכר', tracking=True,
        domain="[('type_id', '=', structure_type_id)]")
    il_is_israel_payroll = fields.Boolean(compute='_compute_il_is_israel_payroll')
    il_tax_credit_points = fields.Float(string='נקודות זיכוי במס', digits=(6, 2))
    il_primary_employer = fields.Boolean(string='מעסיק עיקרי לתשלומי שכר', default=True)
    il_tax_coordination = fields.Boolean(string='יש תיאום מס')
    il_tax_coordination_valid_from = fields.Date(string='תוקף תיאום מס מ-')
    il_tax_coordination_valid_until = fields.Date(string='תוקף תיאום מס עד-')

    # ------------------------------------------------------------------
    # הפרשות סוציאליות (תנאי עבודה)
    # ------------------------------------------------------------------
    il_pension_enabled = fields.Boolean(string='פנסיה')
    il_pension_start_date = fields.Date(string='תאריך תחילת הפרשות לפנסיה')
    il_employee_pension_rate = fields.Float(string='הפרשת עובד לפנסיה (%)', digits=(6, 2))
    il_employer_pension_rate = fields.Float(string='הפרשת מעסיק לפנסיה (%)', digits=(6, 2))
    il_severance_rate = fields.Float(string='הפרשה לפיצויים (%)', digits=(6, 2))

    il_study_fund_enabled = fields.Boolean(string='קרן השתלמות פעילה')
    il_employee_study_fund_rate = fields.Float(string='הפרשת עובד לקרן השתלמות (%)', digits=(6, 2))
    il_employer_study_fund_rate = fields.Float(string='הפרשת מעסיק לקרן השתלמות (%)', digits=(6, 2))

    il_employment_sector = fields.Selection(
        IL_EMPLOYMENT_SECTORS, string='ענף העסקה')

    # הפעלת מס ארגון לעובד פלסטיני (בהתאם להסדר החל על מקום העבודה).
    il_pal_organization_tax = fields.Boolean(string='חל מס ארגון')
    # פיקדון עובד זר — פעיל מתאריך תחילת ההסדר; כשהוא פעיל הוא מחליף את
    # הפרשות הפנסיה/פיצויים של המעסיק (ראו חוקי השכר).
    il_for_deposit_start_date = fields.Date(string='תאריך תחילת הסדר פיקדון')

    @api.depends('structure_type_id')
    def _compute_il_is_israel_payroll(self):
        types = self.env['hr.payroll.structure.type'].search([('country_id.code', '=', 'IL')])
        for version in self:
            version.il_is_israel_payroll = version.structure_type_id in types

    @api.onchange('structure_type_id')
    def _onchange_il_salary_structure(self):
        for version in self:
            version.il_salary_structure_id = version.structure_type_id.default_struct_id
            version.schedule_pay = 'monthly'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals['schedule_pay'] = 'monthly'
            structure_type = self.env['hr.payroll.structure.type'].browse(
                vals.get('structure_type_id'))
            if structure_type.country_id.code == 'IL':
                # Odoo does not generate any work entries when this field is
                # empty, even though date_start falls back to date_version in
                # the UI. Israeli payroll versions must therefore have a real
                # contract boundary from their first version date.
                if not vals.get('contract_date_start') and vals.get('date_version'):
                    vals['contract_date_start'] = vals['date_version']
                vals.setdefault('il_salary_structure_id', structure_type.default_struct_id.id)
                vals.setdefault(
                    'mdl_wage_type',
                    'mdl_monthly' if structure_type.wage_type == 'monthly' else 'mdl_daily',
                )
        versions = super().create(vals_list)
        versions._il_ensure_contract_start()
        return versions

    def write(self, vals):
        structure_type = self.env['hr.payroll.structure.type'].browse(
            vals.get('structure_type_id')) if vals.get('structure_type_id') else False
        if structure_type and structure_type.country_id.code == 'IL':
            vals['schedule_pay'] = 'monthly'
            vals.setdefault('il_salary_structure_id', structure_type.default_struct_id.id)
        vals['schedule_pay'] = 'monthly'
        result = super().write(vals)
        if not self.env.context.get('il_ensuring_contract_start'):
            self._il_ensure_contract_start()
        return result

    def _il_ensure_contract_start(self):
        """Repair payroll versions that have a version date but no contract."""
        if self.env.context.get('il_ensuring_contract_start'):
            return
        for version in self.sudo().filtered(
                lambda item: not item.contract_date_start
                and item.date_version
                and item.structure_type_id.country_id.code == 'IL'):
            version.with_context(
                il_ensuring_contract_start=True,
                sync_contract_dates=True,
            ).write({'contract_date_start': version.date_version})

    @api.constrains('structure_type_id', 'il_salary_structure_id', 'schedule_pay')
    def _check_il_salary_structure(self):
        for version in self:
            if version.il_salary_structure_id and version.structure_type_id and \
                    version.il_salary_structure_id.type_id != version.structure_type_id:
                raise ValidationError(
                    'מבנה השכר חייב להשתייך לקטגוריית השכר שנבחרה. '
                    f'נבחרה הקטגוריה "{version.structure_type_id.display_name}", '
                    f'אך המבנה שייך לקטגוריה '
                    f'"{version.il_salary_structure_id.type_id.display_name}".')
            if version.schedule_pay != 'monthly':
                raise ValidationError('מחזור התשלום לעובד חייב להיות חודשי.')

    @api.constrains('il_tax_coordination', 'il_tax_coordination_valid_from',
                    'il_tax_coordination_valid_until')
    def _check_il_tax_coordination(self):
        for version in self:
            if not version.il_tax_coordination:
                continue
            if (version.il_tax_coordination_valid_from
                    and version.il_tax_coordination_valid_until
                    and version.il_tax_coordination_valid_from > version.il_tax_coordination_valid_until):
                raise ValidationError('תוקף תיאום המס: תאריך הסיום קודם לתאריך ההתחלה.')

    @api.constrains('il_pension_enabled', 'il_employee_pension_rate',
                    'il_employer_pension_rate', 'il_severance_rate')
    def _check_il_pension_rates(self):
        for version in self:
            if not version.il_pension_enabled:
                continue
            for rate in (version.il_employee_pension_rate,
                         version.il_employer_pension_rate,
                         version.il_severance_rate):
                if rate < 0 or rate > 100:
                    raise ValidationError('שיעורי ההפרשה לפנסיה חייבים להיות בין 0 ל-100 אחוזים.')

    @api.constrains('il_study_fund_enabled', 'il_employee_study_fund_rate',
                    'il_employer_study_fund_rate')
    def _check_il_study_fund_rates(self):
        for version in self:
            if not version.il_study_fund_enabled:
                continue
            for rate in (version.il_employee_study_fund_rate,
                         version.il_employer_study_fund_rate):
                if rate < 0 or rate > 100:
                    raise ValidationError('שיעורי ההפרשה לקרן השתלמות חייבים להיות בין 0 ל-100 אחוזים.')

    @api.model
    def _get_whitelist_fields_from_template(self):
        return super()._get_whitelist_fields_from_template() + [
            'il_salary_structure_id', 'il_tax_credit_points', 'il_primary_employer',
            'il_tax_coordination', 'il_tax_coordination_valid_from',
            'il_tax_coordination_valid_until',
            'il_pension_enabled', 'il_pension_start_date',
            'il_employee_pension_rate', 'il_employer_pension_rate', 'il_severance_rate',
            'il_study_fund_enabled', 'il_employee_study_fund_rate',
            'il_employer_study_fund_rate', 'il_employment_sector',
            'il_pal_organization_tax', 'il_for_deposit_start_date',
        ]
