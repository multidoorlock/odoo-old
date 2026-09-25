from odoo import _, fields, models
from odoo.exceptions import ValidationError


class SignSendRequest(models.TransientModel):
    _inherit = 'sign.send.request'

    form_101_employee_id = fields.Many2one(
        'hr.employee',
        string='עובד/ת לטופס 101',
        help='שדה טכני פנימי המקשר את בקשת החתימה לעובד/ת שנבחר/ה.',
    )

    def _is_form_101_request(self):
        self.ensure_one()
        return self.env['hr.employee.form.101']._is_form_101_sign_template(
            self.template_id)

    def _form_101_employee_candidates(self):
        self.ensure_one()
        if self.reference_doc and self.reference_doc._name == 'hr.employee':
            return self.reference_doc
        partners = self.signer_ids.partner_id or self.signer_id
        if not partners:
            return self.env['hr.employee']
        return self.env['hr.employee'].search([
            ('work_contact_id', 'in', partners.ids),
        ])

    def _resolve_form_101_employee(self):
        self.ensure_one()
        if self.form_101_employee_id:
            return self.form_101_employee_id
        candidates = self._form_101_employee_candidates()
        if len(candidates) == 1:
            self.form_101_employee_id = candidates
            return candidates
        if not candidates:
            raise ValidationError(_(
                'איש הקשר שנבחר אינו מקושר לעובד/ת. יש לשלוח את הטופס '
                'מכרטיס העובד או לקשר את איש הקשר לעובד.'))
        return self.env['hr.employee']

    def _open_form_101_employee_selection(self, continuation):
        self.ensure_one()
        candidates = self._form_101_employee_candidates()
        return {
            'type': 'ir.actions.act_window',
            'name': _('בחירת עובד/ת לטופס 101'),
            'res_model': 'hr.employee.form.101.sign.employee.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_send_request_id': self.id,
                'default_candidate_employee_ids': candidates.ids,
                'default_continuation': continuation,
            },
        }

    def _set_form_101_signer(self):
        self.ensure_one()
        employee = self.form_101_employee_id
        if not employee:
            return
        partner = employee.work_contact_id
        if not partner or not partner.email:
            raise ValidationError(_(
                'לעובד/ת חייב להיות איש קשר לעבודה עם כתובת דואר אלקטרוני.'))
        if self.signer_ids:
            self.signer_ids.partner_id = partner
        else:
            self.signer_id = partner

    def create_request(self):
        self.ensure_one()
        form_model = self.env['hr.employee.form.101']
        is_form_101 = form_model._is_form_101_sign_template(self.template_id)
        reference = self.reference_doc
        form = (
            reference
            if reference and reference._name == 'hr.employee.form.101'
            else form_model
        )
        employee = self.form_101_employee_id
        if is_form_101:
            if form:
                if form.state != 'draft':
                    raise ValidationError(_(
                        'ניתן לשלוח לחתימה רק טופס 101 שנמצא במצב טיוטה.'))
                form._validate_for_send()
                employee = form.employee_id
            employee = employee or self._resolve_form_101_employee()
            if not employee:
                raise ValidationError(_(
                    'איש הקשר מקושר למספר עובדים. יש לבחור עובד/ת בחלון הבחירה.'))
            self._set_form_101_signer()
        request = super().create_request()
        if is_form_101:
            source = form or employee
            if request.reference_doc != source:
                request.reference_doc = source
            if form:
                form.with_context(form_101_system_write=True).write({
                    'state': 'sent',
                    'sign_request_id': request.id,
                })
            form_model._prefill_sign_request(request, source)
        return request

    def send_request(self):
        self.ensure_one()
        if self._is_form_101_request() and not self._resolve_form_101_employee():
            return self._open_form_101_employee_selection('send')
        return super().send_request()

    def sign_directly(self):
        self.ensure_one()
        if self._is_form_101_request() and not self._resolve_form_101_employee():
            return self._open_form_101_employee_selection('sign')
        return super().sign_directly()


class HrEmployeeForm101SignEmployeeWizard(models.TransientModel):
    _name = 'hr.employee.form.101.sign.employee.wizard'
    _description = 'בחירת עובד/ת לבקשת חתימה על טופס 101'

    send_request_id = fields.Many2one(
        'sign.send.request', required=True, readonly=True, ondelete='cascade')
    candidate_employee_ids = fields.Many2many(
        'hr.employee', string='עובדים אפשריים', readonly=True)
    employee_id = fields.Many2one(
        'hr.employee', string='עובד/ת', required=True,
        domain="[('id', 'in', candidate_employee_ids)]")
    continuation = fields.Selection([
        ('send', 'שליחה'),
        ('sign', 'חתימה עכשיו'),
    ], required=True, readonly=True)

    def action_confirm(self):
        self.ensure_one()
        if self.employee_id not in self.candidate_employee_ids:
            raise ValidationError(_('יש לבחור עובד/ת מתוך הרשימה המוצגת.'))
        self.send_request_id.form_101_employee_id = self.employee_id
        if self.continuation == 'sign':
            return self.send_request_id.sign_directly()
        return self.send_request_id.send_request()


class SignRequest(models.Model):
    _inherit = 'sign.request'

    def _sign(self):
        result = super()._sign()
        form_model = self.env['hr.employee.form.101']
        for request in self:
            if form_model._is_form_101_sign_template(request.template_id):
                form_model._create_from_sign_request(request)
        return result


class SignRequestItem(models.Model):
    _inherit = 'sign.request.item'

    def _sign(self, signature, **kwargs):
        self.ensure_one()
        form_model = self.env['hr.employee.form.101']
        if form_model._is_form_101_sign_template(
                self.sign_request_id.template_id):
            form_model._validate_sign_submission(self, signature)
        return super()._sign(signature, **kwargs)
