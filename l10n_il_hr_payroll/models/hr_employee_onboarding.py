from odoo import _, api, fields, models
from odoo.tools import email_normalize


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    section_14_ids = fields.One2many(
        'hr.employee.section.14', 'employee_id', string='הסכמי סעיף 14')
    section_14_count = fields.Integer(compute='_compute_onboarding_status')
    onboarding_form_101_done = fields.Boolean(compute='_compute_onboarding_status')
    onboarding_section_14_done = fields.Boolean(compute='_compute_onboarding_status')
    onboarding_employee_fields_done = fields.Boolean(compute='_compute_onboarding_status')
    onboarding_odoo_user_done = fields.Boolean(compute='_compute_onboarding_status')
    onboarding_form_101_id = fields.Many2one(
        'hr.employee.form.101', compute='_compute_onboarding_status', string='טופס 101 מקושר')
    # Kept as a computed compatibility alias so existing inherited/Studio
    # views can be validated safely while the module view is upgraded.
    onboarding_active_form_101_id = fields.Many2one(
        'hr.employee.form.101', compute='_compute_onboarding_status', string='טופס 101 פעיל')
    onboarding_section_14_id = fields.Many2one(
        'hr.employee.section.14', compute='_compute_onboarding_status', string='סעיף 14 מקושר')
    onboarding_user_id = fields.Many2one(
        'res.users', compute='_compute_onboarding_status', string='משתמש Odoo')

    @api.depends(
        'form_101_ids.state', 'section_14_ids.state', 'section_14_ids.form_file',
        'name', 'image_1920', 'work_email', 'work_phone', 'mobile_phone',
        'company_id',
    )
    def _compute_onboarding_status(self):
        users = self.env['res.users'].sudo().with_context(active_test=False)
        for employee in self:
            form_records = employee.form_101_ids.sorted(
                key=lambda form: form.id, reverse=True)
            form_record = form_records[:1]
            active_form = form_records.filtered(
                lambda form: form.state == 'active')[:1]
            section_records = employee.section_14_ids.sorted(
                key=lambda record: (
                    {'active': 4, 'signed': 3, 'sent': 2, 'draft': 1}.get(record.state, 0),
                    record.id,
                ),
                reverse=True,
            )
            section_record = section_records[:1]
            active_section = section_records.filtered(
                lambda record: record.state == 'active' and bool(record.form_file))[:1]
            linked_user = self.env['res.users']
            normalized_email = email_normalize(employee.work_email or '')
            if normalized_email and employee.company_id:
                linked_user = users.search([
                    ('email', '=ilike', normalized_email),
                    ('company_ids', 'in', employee.company_id.id),
                ], order='active desc, id desc', limit=1)

            employee.section_14_count = len(employee.section_14_ids)
            employee.onboarding_form_101_id = form_record
            employee.onboarding_active_form_101_id = active_form
            employee.onboarding_form_101_done = bool(active_form)
            employee.onboarding_section_14_id = active_section or section_record
            # Section 14 is optional until a record is linked.  Once the
            # employee has a Section 14 record, the onboarding task is only
            # complete when that record is active and has its signed file.
            employee.onboarding_section_14_done = (
                not section_records or bool(active_section)
            )
            employee.onboarding_employee_fields_done = bool(
                employee.name
                and employee.image_1920
                and employee.work_email
                and (employee.work_phone or employee.mobile_phone)
            )
            employee.onboarding_user_id = linked_user
            employee.onboarding_odoo_user_done = bool(linked_user)

    def action_open_section_14(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'l10n_il_hr_payroll.action_hr_employee_section_14')
        action['domain'] = [('employee_id', '=', self.id)]
        action['context'] = {'default_employee_id': self.id}
        return action

    def action_configure_onboarding_form_101(self):
        self.ensure_one()
        if self.onboarding_form_101_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'hr.employee.form.101',
                'res_id': self.onboarding_form_101_id.id,
                'view_mode': 'form',
            }
        return self.action_send_form_101_for_completion()

    def action_configure_onboarding_section_14(self):
        self.ensure_one()
        if self.onboarding_section_14_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'hr.employee.section.14',
                'res_id': self.onboarding_section_14_id.id,
                'view_mode': 'form',
            }
        return {
            'type': 'ir.actions.act_window',
            'name': _('סעיף 14 חדש'),
            'res_model': 'hr.employee.section.14',
            'view_mode': 'form',
            'target': 'current',
            'context': {'default_employee_id': self.id},
        }

    def action_configure_onboarding_employee_fields(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hr.employee',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_configure_onboarding_user(self):
        self.ensure_one()
        if self.onboarding_user_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'res.users',
                'res_id': self.onboarding_user_id.id,
                'view_mode': 'form',
            }
        return self.action_create_user()
