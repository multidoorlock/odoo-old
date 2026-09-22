from odoo import Command, api, fields, models

from .hr_employee_section_14 import section_14_definition_for_item


class SignSendRequest(models.TransientModel):
    _inherit = 'sign.send.request'

    section_14_id = fields.Many2one(
        'hr.employee.section.14', readonly=True, ondelete='cascade')

    @api.depends('template_id', 'set_sign_order', 'template_id.sign_item_ids', 'section_14_id')
    def _compute_signer_ids(self):
        super()._compute_signer_ids()
        employer_role = self.env.ref(
            'l10n_il_hr_payroll.sign_item_role_section_14_employer',
            raise_if_not_found=False,
        )
        employee_role = self.env.ref(
            'l10n_il_hr_payroll.sign_item_role_section_14_employee',
            raise_if_not_found=False,
        )
        for wizard in self.filtered('section_14_id'):
            employee_partner = wizard.section_14_id.employee_id.work_contact_id
            employer_partner = self.env.user.partner_id
            wizard.signer_ids = [
                Command.clear(),
                Command.create({
                    'role_id': employer_role.id,
                    'partner_id': employer_partner.id,
                    'mail_sent_order': 1,
                }),
                Command.create({
                    'role_id': employee_role.id,
                    'partner_id': employee_partner.id,
                    'mail_sent_order': 2,
                }),
            ]

    def create_request(self):
        self.ensure_one()
        section = self.section_14_id
        if section:
            section._validate_for_signature()
        request = super().create_request()
        if section:
            if request.reference_doc != section:
                request.reference_doc = section
            section.with_context(section_14_system_write=True).write({
                'state': 'sent',
                'sign_request_id': request.id,
            })
            section._prefill_sign_request(request)
        return request


class SignRequest(models.Model):
    _inherit = 'sign.request'

    def _sign(self):
        result = super()._sign()
        for request in self:
            reference = request.reference_doc
            if reference and reference._name == 'hr.employee.section.14':
                reference._complete_from_sign_request(request)
        return result


class SignRequestItem(models.Model):
    _inherit = 'sign.request.item'

    def _sign(self, signature, **kwargs):
        self.ensure_one()
        reference = self.sign_request_id.reference_doc
        if (reference and reference._name == 'hr.employee.section.14'
                and isinstance(signature, dict)):
            signature = dict(signature)
            date_key = (
                'employer_signature_date'
                if self.role_id == self.env.ref(
                    'l10n_il_hr_payroll.sign_item_role_section_14_employer')
                else 'employee_signature_date'
            )
            for item in self.sign_request_id.template_id.sign_item_ids.filtered(
                    lambda sign_item: sign_item.responsible_id == self.role_id):
                definition = section_14_definition_for_item(item)
                if definition and definition[0] == date_key:
                    signature[str(item.id)] = fields.Date.to_string(
                        fields.Date.context_today(self))
                    break
        return super()._sign(signature, **kwargs)
