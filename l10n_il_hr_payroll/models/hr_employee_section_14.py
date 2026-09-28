import base64

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.misc import file_open


PAGE_WIDTH_MM = 210.0
PAGE_HEIGHT_MM = 297.0

# The coordinates below are the exact fields positioned by the administrator
# on the authoritative three-page PDF template.  Only the role assignment is
# normalised: the employer signs first and the employee signs second.
SECTION_14_ITEMS = (
    ('employer_name', 'sign.sign_item_type_text', 'employer', 1, 32.76, 136.917, 119.91, 4.455),
    ('employer_registration', 'sign.sign_item_type_text', 'employer', 1, 32.76, 146.124, 125.16, 4.455),
    ('employee_name', 'sign.sign_item_type_text', 'employee', 1, 32.97, 174.933, 123.27, 4.455),
    ('employee_identification', 'sign.sign_item_type_text', 'employee', 1, 32.76, 184.437, 136.08, 4.455),
    ('employee_signature', 'sign.sign_item_type_signature', 'employee', 1, 30.24, 194.238, 53.13, 20.196),
    ('employer_signature', 'sign.sign_item_type_signature', 'employer', 1, 126.21, 194.238, 52.92, 20.196),
    ('employer_signature_date', 'sign.sign_item_type_date', 'employer', 1, 32.76, 237.600, 99.75, 4.455),
    ('employee_signature_date', 'sign.sign_item_type_date', 'employee', 1, 32.55, 247.104, 103.32, 4.455),
)


def section_14_definition_for_item(item):
    if not item or item.page != 1:
        return False
    left = item.posX * PAGE_WIDTH_MM
    top = item.posY * PAGE_HEIGHT_MM
    definition = min(
        SECTION_14_ITEMS,
        key=lambda candidate: abs(candidate[4] - left) + abs(candidate[5] - top),
    )
    return definition if (
        abs(definition[4] - left) <= 0.8
        and abs(definition[5] - top) <= 0.8
    ) else False


class HrEmployeeSection14(models.Model):
    _name = 'hr.employee.section.14'
    _description = 'הסכם סעיף 14'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_name = 'display_name'

    _unique_active_employee = models.UniqueIndex(
        "(employee_id) WHERE state = 'active'",
        'לעובד יכול להיות הסכם סעיף 14 פעיל אחד בלבד.',
    )

    display_name = fields.Char(compute='_compute_display_name')
    employee_id = fields.Many2one(
        'hr.employee', string='עובד', required=True, ondelete='cascade',
        index=True, tracking=True)
    company_id = fields.Many2one(
        'res.company', string='חברה', related='employee_id.company_id',
        store=True, readonly=True)
    state = fields.Selection([
        ('draft', 'טיוטה'),
        ('sent', 'נשלח לחתימה'),
        ('signed', 'נחתם'),
        ('active', 'פעיל'),
    ], string='סטטוס', default='draft', required=True, tracking=True, index=True)

    employee_name = fields.Char(string='שם העובד', required=True, tracking=True)
    employee_identification = fields.Char(string='תעודת זהות עובד', required=True, tracking=True)
    employer_name = fields.Char(string='שם המעסיק', required=True, tracking=True)
    employer_registration = fields.Char(string='ח.פ / ע.פ מעסיק', required=True, tracking=True)
    employee_signature = fields.Binary(string='חתימת עובד', attachment=True, readonly=True, copy=False)
    employer_signature = fields.Binary(string='חתימת מעסיק', attachment=True, readonly=True, copy=False)
    employee_signature_date = fields.Date(string='תאריך חתימת עובד', readonly=True, copy=False)
    employer_signature_date = fields.Date(string='תאריך חתימת מעסיק', readonly=True, copy=False)

    sign_template_id = fields.Many2one(
        'sign.template', string='תבנית חתימה', readonly=True, copy=False,
        default=lambda self: self._default_sign_template_id())
    sign_request_id = fields.Many2one(
        'sign.request', string='בקשת חתימה', readonly=True, copy=False,
        ondelete='set null', tracking=True)
    form_file = fields.Binary(
        string='קובץ סעיף 14 חתום', attachment=True, readonly=True, copy=False)
    form_filename = fields.Char(string='שם הקובץ', readonly=True, copy=False)

    @api.depends('employee_id', 'state')
    def _compute_display_name(self):
        state_labels = dict(self._fields['state'].selection)
        for record in self:
            record.display_name = _(
                'סעיף 14 - %(employee)s (%(state)s)',
                employee=record.employee_id.name or '',
                state=state_labels.get(record.state, ''),
            )

    @api.model
    def _default_sign_template_id(self):
        template = self.env.ref(
            'l10n_il_hr_payroll.sign_template_section_14',
            raise_if_not_found=False,
        )
        return template.id if template else False

    @api.model
    def _employee_snapshot(self, employee):
        company = employee.company_id
        return {
            'employee_name': employee.name,
            'employee_identification': employee.identification_id,
            'employer_name': company.name,
            'employer_registration': company.company_registry or company.vat,
        }

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            employee = self.env['hr.employee'].browse(vals.get('employee_id')).exists()
            if employee:
                snapshot = self._employee_snapshot(employee)
                for field_name, value in snapshot.items():
                    vals.setdefault(field_name, value)
                vals.setdefault('sign_template_id', self._default_sign_template_id())
        return super().create(vals_list)

    def write(self, vals):
        protected = {
            'employee_id', 'employee_name', 'employee_identification',
            'employer_name', 'employer_registration',
            'employee_signature', 'employer_signature',
            'employee_signature_date', 'employer_signature_date',
            'sign_template_id', 'sign_request_id',
            'form_file', 'form_filename', 'state',
        }
        if protected & vals.keys() and not self.env.context.get('section_14_system_write'):
            locked = self.filtered(lambda record: record.state != 'draft')
            if locked:
                raise ValidationError(_('ניתן לערוך את פרטי סעיף 14 רק במצב טיוטה.'))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_only_draft(self):
        if self.filtered(lambda record: record.state != 'draft'):
            raise ValidationError(_('ניתן למחוק רק רשומת סעיף 14 במצב טיוטה.'))

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        if self.employee_id:
            self.update(self._employee_snapshot(self.employee_id))

    def _validate_for_signature(self):
        for record in self:
            missing = [record._fields[name].string for name in (
                'employee_name', 'employee_identification',
                'employer_name', 'employer_registration',
            ) if not record[name]]
            if missing:
                raise ValidationError(_(
                    'לא ניתן לשלוח את סעיף 14 לחתימה. חסרים: %s',
                    ', '.join(missing),
                ))
            partner = record.employee_id.work_contact_id
            if not partner or not partner.email:
                raise ValidationError(_('לעובד חייב להיות איש קשר לעבודה עם כתובת דוא״ל.'))
            if not self.env.user.partner_id.email:
                raise ValidationError(_('למשתמש השולח חייבת להיות כתובת דוא״ל לצורך חתימת המעסיק.'))

    def action_send_for_signature(self):
        self.ensure_one()
        if self.state != 'draft':
            raise ValidationError(_('ניתן לשלוח לחתימה רק רשומת סעיף 14 במצב טיוטה.'))
        self._validate_for_signature()
        template = self._ensure_section_14_assets()
        return template.with_context(
            default_reference_doc=f'{self._name},{self.id}',
            default_section_14_id=self.id,
            default_set_sign_order=True,
            default_model=self._name,
            default_res_ids=str(self.ids),
        ).open_sign_send_dialog()

    def action_open_sign_request(self):
        self.ensure_one()
        if not self.sign_request_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sign.request',
            'res_id': self.sign_request_id.id,
            'view_mode': 'form',
        }

    def action_activate(self):
        self.ensure_one()
        if self.state != 'signed' or not self.form_file:
            raise ValidationError(_('ניתן להפעיל סעיף 14 רק לאחר ששני הצדדים חתמו ונוצר קובץ חתום.'))
        other_active = self.search([
            ('employee_id', '=', self.employee_id.id),
            ('state', '=', 'active'),
            ('id', '!=', self.id),
        ], limit=1)
        if other_active and not self.env.context.get('section_14_replace_confirmed'):
            wizard = self.env['hr.employee.section.14.activation.wizard'].create({
                'section_14_id': self.id,
                'active_section_14_id': other_active.id,
            })
            return {
                'type': 'ir.actions.act_window',
                'name': _('החלפת סעיף 14 פעיל'),
                'res_model': 'hr.employee.section.14.activation.wizard',
                'res_id': wizard.id,
                'view_mode': 'form',
                'target': 'new',
            }
        if other_active:
            other_active.with_context(section_14_system_write=True).write({'state': 'draft'})
        self.with_context(section_14_system_write=True).write({'state': 'active'})
        return True

    def action_reset_to_draft(self):
        for record in self:
            request = record.sign_request_id
            if request and request.state not in ('signed', 'canceled', 'expired'):
                request.cancel()
            record.with_context(section_14_system_write=True).write({
                'state': 'draft',
                'sign_request_id': False,
                'form_file': False,
                'form_filename': False,
                'employee_signature': False,
                'employer_signature': False,
                'employee_signature_date': False,
                'employer_signature_date': False,
            })
        return True

    @api.model
    def _set_xmlid(self, name, record):
        model_data = self.env['ir.model.data'].sudo().search([
            ('module', '=', 'l10n_il_hr_payroll'),
            ('name', '=', name),
        ], limit=1)
        values = {
            'module': 'l10n_il_hr_payroll',
            'name': name,
            'model': record._name,
            'res_id': record.id,
            'noupdate': True,
        }
        if model_data:
            model_data.write(values)
        else:
            self.env['ir.model.data'].sudo().create(values)

    @api.model
    def _ensure_section_14_assets(self):
        template = self.env.ref(
            'l10n_il_hr_payroll.sign_template_section_14',
            raise_if_not_found=False,
        )
        if not template:
            template = self.env['sign.template'].sudo().search([
                ('active', '=', True),
                ('name', 'ilike', '14'),
                ('sign_request_ids', '=', False),
            ], order='id desc', limit=1)
        if not template:
            with file_open(
                    'l10n_il_hr_payroll/static/src/pdf/section_14.pdf', 'rb') as pdf_file:
                pdf_data = base64.b64encode(pdf_file.read())
            result = self.env['sign.template'].sudo().with_context(
                default_model_name=self._name,
            ).create_from_attachment_data([{
                'name': _('תבנית סעיף 14.pdf'),
                'datas': pdf_data,
            }])
            template = self.env['sign.template'].sudo().browse(result['id'])
        template.sudo().write({
            'active': True,
            'model_id': self.env['ir.model']._get(self._name).id,
        })
        self._set_xmlid('sign_template_section_14', template)
        self._configure_section_14_template(template)
        other_templates = self.env['sign.template'].sudo().with_context(
            active_test=False,
        ).search([
            ('model_id', '=', self.env['ir.model']._get(self._name).id),
            ('id', '!=', template.id),
        ])
        if other_templates:
            other_templates.write({'active': False})
        self.search([('sign_request_id', '=', False)]).write({
            'sign_template_id': template.id,
        })
        return template

    @api.model
    def _configure_section_14_template(self, template):
        document = template.document_ids[:1]
        if not document or document.num_pages != 3:
            raise ValidationError(_('תבנית סעיף 14 חייבת להכיל בדיוק שלושה עמודים.'))
        if template.sign_request_ids:
            return template

        roles = {}
        for key, label in (('employer', _('מעסיק')), ('employee', _('עובד'))):
            role = self.env.ref(
                f'l10n_il_hr_payroll.sign_item_role_section_14_{key}',
                raise_if_not_found=False,
            )
            if not role:
                role = self.env['sign.item.role'].sudo().create({'name': label})
            elif role.name != label:
                role.sudo().name = label
            self._set_xmlid(f'sign_item_role_section_14_{key}', role)
            roles[key] = role

        existing = document.sign_item_ids.filtered(lambda item: item.page == 1)
        configured = len(existing) == len(SECTION_14_ITEMS)
        if configured:
            for definition in SECTION_14_ITEMS:
                matches = existing.filtered(
                    lambda item: section_14_definition_for_item(item)
                    and section_14_definition_for_item(item)[0] == definition[0])
                if (len(matches) != 1
                        or matches.type_id != self.env.ref(definition[1])
                        or matches.responsible_id != roles[definition[2]]):
                    configured = False
                    break
        if configured:
            return template

        document.sign_item_ids.unlink()
        for key, type_xmlid, role_key, page, left, top, width, height in SECTION_14_ITEMS:
            self.env['sign.item'].sudo().create({
                'document_id': document.id,
                'type_id': self.env.ref(type_xmlid).id,
                'responsible_id': roles[role_key].id,
                'page': page,
                'posX': left / PAGE_WIDTH_MM,
                'posY': top / PAGE_HEIGHT_MM,
                'width': width / PAGE_WIDTH_MM,
                'height': height / PAGE_HEIGHT_MM,
                'required': True,
                'constant': False,
                'alignment': 'center',
                'name': False,
            })
        return template

    @api.model
    def _is_section_14_template(self, template):
        installed = self.env.ref(
            'l10n_il_hr_payroll.sign_template_section_14',
            raise_if_not_found=False,
        )
        return bool(template and installed and template == installed)

    def _prefill_sign_request(self, request):
        self.ensure_one()
        values = {
            'employer_name': self.employer_name,
            'employer_registration': self.employer_registration,
            'employee_name': self.employee_name,
            'employee_identification': self.employee_identification,
        }
        for request_item in request.request_item_ids:
            sign_values = {}
            for item in request.template_id.sign_item_ids.filtered(
                    lambda sign_item: sign_item.responsible_id == request_item.role_id):
                definition = section_14_definition_for_item(item)
                if definition and definition[0] in values:
                    sign_values[str(item.id)] = values[definition[0]]
            if sign_values:
                request_item.sudo()._fill(sign_values)

    def _complete_from_sign_request(self, request):
        self.ensure_one()
        if request.state != 'signed':
            return self
        role_by_key = {
            key: self.env.ref(
                f'l10n_il_hr_payroll.sign_item_role_section_14_{key}',
                raise_if_not_found=False,
            ) for key in ('employer', 'employee')
        }
        signer_by_role = {item.role_id: item for item in request.request_item_ids}
        employer_signer = signer_by_role.get(role_by_key['employer'])
        employee_signer = signer_by_role.get(role_by_key['employee'])
        completed = request.completed_document_ids[:1]
        if not completed or not completed.file:
            request._generate_completed_documents()
            completed = request.completed_document_ids[:1]
        if not completed or not completed.file:
            raise ValidationError(_('בקשת החתימה הושלמה ללא קובץ חתום.'))
        self.with_context(section_14_system_write=True).write({
            'state': 'signed',
            'employer_signature': employer_signer.signature if employer_signer else False,
            'employee_signature': employee_signer.signature if employee_signer else False,
            'employer_signature_date': employer_signer.signing_date if employer_signer else False,
            'employee_signature_date': employee_signer.signing_date if employee_signer else False,
            'form_file': completed.file,
            'form_filename': _('סעיף 14 חתום - %s.pdf', self.employee_id.name),
        })
        return self
