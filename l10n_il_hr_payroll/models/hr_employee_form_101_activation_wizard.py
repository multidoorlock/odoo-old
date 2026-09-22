from odoo import fields, models, _


class HrEmployeeForm101ActivationWizard(models.TransientModel):
    _name = 'hr.employee.form.101.activation.wizard'
    _description = 'אישור החלפת טופס 101 פעיל'

    form_id = fields.Many2one(
        'hr.employee.form.101', string='הטופס החדש', required=True, readonly=True)
    active_form_id = fields.Many2one(
        'hr.employee.form.101', string='הטופס הפעיל כעת', required=True, readonly=True)
    warning_message = fields.Text(string='אזהרה', compute='_compute_warning_message')

    def _compute_warning_message(self):
        for wizard in self:
            wizard.warning_message = _(
                'לעובד %(employee)s כבר קיים טופס 101 פעיל לשנת %(year)s. '
                'המשך הפעולה יחזיר את הטופס הקיים לטיוטה ויפעיל במקומו את הטופס החדש.',
                employee=wizard.form_id.employee_id.name or '',
                year=wizard.active_form_id.tax_year or '',
            )

    def action_confirm(self):
        self.ensure_one()
        self.form_id.with_context(
            form_101_replace_confirmed=True,
            expected_active_form_id=self.active_form_id.id,
        ).action_activate()
        return {'type': 'ir.actions.client', 'tag': 'reload'}
