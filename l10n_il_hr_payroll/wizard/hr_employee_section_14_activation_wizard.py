from odoo import fields, models


class HrEmployeeSection14ActivationWizard(models.TransientModel):
    _name = 'hr.employee.section.14.activation.wizard'
    _description = 'אישור החלפת סעיף 14 פעיל'

    section_14_id = fields.Many2one(
        'hr.employee.section.14', required=True, readonly=True, ondelete='cascade')
    active_section_14_id = fields.Many2one(
        'hr.employee.section.14', required=True, readonly=True, ondelete='cascade')

    def action_confirm(self):
        self.ensure_one()
        return self.section_14_id.with_context(
            section_14_replace_confirmed=True,
        ).action_activate()
