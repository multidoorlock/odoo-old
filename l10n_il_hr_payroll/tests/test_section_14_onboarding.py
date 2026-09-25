import base64

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import Form, TransactionCase, tagged

from ..models.hr_employee_section_14 import (
    SECTION_14_ITEMS,
    section_14_definition_for_item,
)


@tagged('post_install', '-at_install', 'l10n_il_section_14')
class TestSection14Onboarding(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write({
            'company_registry': '515151515',
        })
        cls.employee = cls.env['hr.employee'].create({
            'name': 'עובד בדיקה סעיף 14',
            'company_id': cls.company.id,
            'work_email': 'section14.employee@example.com',
            'work_phone': '03-5555555',
            'identification_id': '123456782',
            'image_1920': (
                'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC'
                'AAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
            ).encode(),
        })
        cls.employee.work_contact_id.email = cls.employee.work_email
        cls.section = cls.env['hr.employee.section.14'].create({
            'employee_id': cls.employee.id,
        })

    def test_template_keeps_exact_layout_and_correct_role_order(self):
        template = self.env.ref('l10n_il_hr_payroll.sign_template_section_14')
        self.assertEqual(template.model_name, 'hr.employee.section.14')
        self.assertEqual(len(template.sign_item_ids), 8)
        items = {
            section_14_definition_for_item(item)[0]: item
            for item in template.sign_item_ids
        }
        self.assertEqual(set(items), {definition[0] for definition in SECTION_14_ITEMS})
        employer_role = self.env.ref(
            'l10n_il_hr_payroll.sign_item_role_section_14_employer')
        employee_role = self.env.ref(
            'l10n_il_hr_payroll.sign_item_role_section_14_employee')
        self.assertEqual(items['employer_name'].responsible_id, employer_role)
        self.assertEqual(items['employer_signature'].responsible_id, employer_role)
        self.assertEqual(items['employee_name'].responsible_id, employee_role)
        self.assertEqual(items['employee_signature'].responsible_id, employee_role)
        self.assertEqual(items['employer_name'].posY * 297, 136.917)
        self.assertEqual(items['employee_signature'].posX * 210, 30.24)

    def test_native_sign_popup_has_employer_then_employee(self):
        action = self.section.action_send_for_signature()
        self.assertEqual(action['res_model'], 'sign.send.request')
        self.assertEqual(action['target'], 'new')
        wizard = Form(
            self.env['sign.send.request'].with_context(action['context'])
        ).save()
        self.assertEqual(wizard.section_14_id, self.section)
        employer_role = self.env.ref(
            'l10n_il_hr_payroll.sign_item_role_section_14_employer')
        employee_role = self.env.ref(
            'l10n_il_hr_payroll.sign_item_role_section_14_employee')
        employer = wizard.signer_ids.filtered(lambda signer: signer.role_id == employer_role)
        employee = wizard.signer_ids.filtered(lambda signer: signer.role_id == employee_role)
        self.assertEqual(employer.partner_id, self.env.user.partner_id)
        self.assertEqual(employee.partner_id, self.employee.work_contact_id)
        self.assertEqual(employer.mail_sent_order, 1)
        self.assertEqual(employee.mail_sent_order, 2)

    def test_form_101_setup_reuses_native_sign_popup(self):
        action = self.employee.action_configure_onboarding_form_101()
        self.assertEqual(action['res_model'], 'sign.send.request')
        self.assertEqual(action['target'], 'new')
        self.assertEqual(
            action['context']['default_reference_doc'],
            f'hr.employee,{self.employee.id}',
        )

    def test_onboarding_shows_latest_form_101_even_when_not_active(self):
        def create_form(year):
            return self.env['hr.employee.form.101'].create({
                'employee_id': self.employee.id,
                'tax_year': year,
                'last_name': 'Test',
                'birthday': fields.Date.from_string('1990-01-01'),
                'employer_address': 'Employer address',
                'employer_phone': '03-5555555',
                'employer_withholding_file': '935000000',
                'private_street': 'Test street',
                'private_house_number': '1',
                'private_city': 'Test city',
                'mobile_phone': '050-5555555',
                'sex': 'male',
                'marital': 'single',
                'employer_income_main_type': 'monthly',
                'employment_start_date': fields.Date.from_string(f'{year}-01-01'),
                'has_other_income': 'no',
                'declaration_confirmed': True,
                'declaration_date': fields.Date.from_string(f'{year}-01-01'),
            })

        first = create_form('2025')
        latest = create_form('2026')
        self.employee.invalidate_recordset()
        self.assertFalse(self.employee.onboarding_form_101_done)
        self.assertEqual(self.employee.onboarding_form_101_id, latest)

        action = self.employee.action_configure_onboarding_form_101()
        self.assertEqual(action['res_model'], 'hr.employee.form.101')
        self.assertEqual(action['res_id'], latest.id)
        self.assertNotEqual(action['res_id'], first.id)

    def test_full_signing_flow_creates_file_and_completes_onboarding(self):
        action = self.section.action_send_for_signature()
        wizard = Form(
            self.env['sign.send.request'].with_context(
                action['context'], no_sign_mail=True)
        ).save()
        request = wizard.with_context(no_sign_mail=True).create_request()
        self.assertEqual(self.section.state, 'sent')
        self.assertEqual(self.section.sign_request_id, request)

        pixel = 'data:image/png;base64,' + base64.b64encode(
            base64.b64decode(
                'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC'
                'AAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
            )
        ).decode()
        for request_item in request.request_item_ids.sorted('mail_sent_order'):
            values = {
                str(value.sign_item_id.id): value.value
                for value in request_item.sign_item_value_ids
            }
            for item in request.template_id.sign_item_ids.filtered(
                    lambda sign_item: sign_item.responsible_id == request_item.role_id):
                definition = section_14_definition_for_item(item)
                if item.type_id.item_type == 'signature':
                    values[str(item.id)] = pixel
                elif definition and definition[0].endswith('_date'):
                    values[str(item.id)] = fields.Date.to_string(fields.Date.today())
            request_item.sudo()._sign(values)

        self.assertEqual(request.state, 'signed')
        self.assertEqual(self.section.state, 'signed')
        self.assertTrue(self.section.form_file)
        self.assertTrue(self.section.employee_signature)
        self.assertTrue(self.section.employer_signature)
        self.section.action_activate()
        self.employee.invalidate_recordset()
        self.assertTrue(self.employee.onboarding_section_14_done)
        self.assertEqual(self.employee.onboarding_section_14_id, self.section)

    def test_employee_fields_and_odoo_user_are_computed_from_real_data(self):
        self.assertTrue(self.employee.onboarding_employee_fields_done)
        self.assertFalse(self.employee.onboarding_odoo_user_done)
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': self.employee.name,
            'login': self.employee.work_email,
            'email': self.employee.work_email,
            'company_id': self.company.id,
            'company_ids': [(6, 0, self.company.ids)],
        })
        self.employee.invalidate_recordset()
        self.assertTrue(self.employee.onboarding_odoo_user_done)
        self.assertEqual(self.employee.onboarding_user_id, user)

    def test_section_14_task_is_done_when_absent_but_not_when_inactive(self):
        employee_without_section = self.env['hr.employee'].create({
            'name': 'Employee without Section 14',
            'company_id': self.company.id,
            'identification_id': '987654324',
        })
        self.assertTrue(employee_without_section.onboarding_section_14_done)
        self.assertFalse(employee_without_section.onboarding_section_14_id)

        section = self.env['hr.employee.section.14'].create({
            'employee_id': employee_without_section.id,
        })
        employee_without_section.invalidate_recordset()
        self.assertFalse(employee_without_section.onboarding_section_14_done)
        self.assertEqual(employee_without_section.onboarding_section_14_id, section)

    def test_reset_to_draft_cancels_pending_request(self):
        action = self.section.action_send_for_signature()
        wizard = Form(
            self.env['sign.send.request'].with_context(
                action['context'], no_sign_mail=True)
        ).save()
        request = wizard.with_context(no_sign_mail=True).create_request()
        self.section.action_reset_to_draft()
        self.assertEqual(self.section.state, 'draft')
        self.assertFalse(self.section.sign_request_id)
        self.assertEqual(request.state, 'canceled')

    def test_section_14_cannot_activate_without_signed_file(self):
        self.section.with_context(section_14_system_write=True).write({
            'state': 'signed',
        })
        with self.assertRaises(ValidationError):
            self.section.action_activate()

    def test_signed_legal_record_cannot_be_deleted(self):
        self.section.with_context(section_14_system_write=True).write({
            'state': 'signed',
            'form_file': base64.b64encode(b'signed-pdf'),
        })
        with self.assertRaises(ValidationError):
            self.section.unlink()

    def test_replacing_active_section_requires_confirmation(self):
        self.section.with_context(section_14_system_write=True).write({
            'state': 'active',
            'form_file': base64.b64encode(b'old-signed-pdf'),
        })
        replacement = self.env['hr.employee.section.14'].create({
            'employee_id': self.employee.id,
        })
        replacement.with_context(section_14_system_write=True).write({
            'state': 'signed',
            'form_file': base64.b64encode(b'new-signed-pdf'),
        })
        action = replacement.action_activate()
        self.assertEqual(
            action['res_model'],
            'hr.employee.section.14.activation.wizard',
        )
        wizard = self.env[action['res_model']].browse(action['res_id'])
        wizard.action_confirm()
        self.assertEqual(replacement.state, 'active')
        self.assertEqual(self.section.state, 'draft')
