import base64
from datetime import date, timedelta

from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..models.hr_employee_form_101 import (
    _SIGN_TEMPLATE_ITEMS,
    _SIGN_RADIO_GROUP_BY_KEY,
    _sign_definition_for_item,
)


@tagged('post_install', '-at_install', 'l10n_il_form_101')
class TestEmployeeForm101(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env['hr.employee'].create({
            'name': 'עובד בדיקה',
            'legal_name': 'עובד בדיקה',
            'company_id': cls.env.company.id,
            'identification_id': '123456789',
            'private_street': 'רחוב ישן',
            'private_city': 'תל אביב',
            'private_phone': '03-0000000',
            'birthday': date(1990, 1, 1),
        })

    def _new_form(self, **values):
        form_values = {
            'employee_id': self.employee.id,
            'tax_year': '2026',
            'last_name': 'בדיקה',
            'employer_phone': '03-5555555',
            'employer_withholding_file': '935000000',
            'private_house_number': '1',
            'mobile_phone': '050-5555555',
            'sex': 'male',
            'marital': 'single',
            'employer_income_main_type': 'monthly',
            'employment_start_date': date(2026, 1, 1),
            'has_other_income': 'no',
            'declaration_confirmed': True,
            'declaration_date': date(2026, 1, 1),
        }
        form_values.update(values)
        return self.env['hr.employee.form.101'].create(form_values)

    def _template_items_by_key(self, template):
        return {
            definition['key']: item
            for item in template.sign_item_ids
            if (definition := _sign_definition_for_item(item))
        }

    def _sign(self, form):
        template = self.env['hr.employee.form.101']._ensure_form_101_sign_template()
        role = (template.sign_item_ids.responsible_id[:1]
                or self.env.ref('sign.sign_item_role_default'))
        request = self.env['sign.request'].with_context(no_sign_mail=True).create({
            'template_id': template.id,
            'request_item_ids': [Command.create({
                'partner_id': self.env.user.partner_id.id,
                'role_id': role.id,
                'mail_sent_order': 1,
            })],
            'reference': form.display_name,
            'subject': form.display_name,
            'reference_doc': f'{form._name},{form.id}',
        })
        request.write({'state': 'signed'})
        form.write({
            'state': 'signed',
            'sign_request_id': request.id,
            'form_file': base64.b64encode(b'%PDF-1.4\n%%EOF'),
            'form_filename': 'signed-form-101.pdf',
            'employee_signature_date': date.today(),
        })
        return form

    def test_create_copies_employee_snapshot(self):
        form = self._new_form()
        self.assertEqual(form.identification_id, '123456789')
        self.assertEqual(form.private_street, 'רחוב ישן')
        self.assertEqual(form.private_phone, '03-0000000')
        self.assertEqual(form.birthday, date(1990, 1, 1))

    def test_changed_shared_field_creates_native_employee_version(self):
        form = self._new_form(private_street='רחוב חדש')
        initial_versions = len(self.employee.version_ids)
        old_version = self.employee.version_id
        old_version.date_version = date.today() - timedelta(days=1)

        form.write({'private_city': 'חיפה'})

        self.assertEqual(len(self.employee.version_ids), initial_versions)
        self.assertEqual(self.employee.version_id.private_street, 'רחוב ישן')

        self._sign(form).action_activate()

        self.assertEqual(len(self.employee.version_ids), initial_versions + 1)
        self.assertEqual(self.employee.version_id.private_street, 'רחוב חדש')
        self.assertEqual(self.employee.version_id.private_city, 'חיפה')
        self.assertEqual(old_version.private_street, 'רחוב ישן')
        self.assertEqual(form.employee_version_id, self.employee.version_id)

    def test_replacement_confirmation_precedes_validation(self):
        first = self._sign(self._new_form(private_city='חיפה'))
        first.action_activate()
        self.assertEqual(first.state, 'active')
        self.assertEqual(self.employee.version_id.private_city, 'חיפה')

        second = self._new_form(private_city='ירושלים')
        action = second.action_activate()
        self.assertEqual(action['res_model'], 'hr.employee.form.101.activation.wizard')
        self.assertEqual(second.state, 'draft')
        self.assertEqual(first.state, 'active')

        wizard = self.env[action['res_model']].browse(action['res_id'])
        with self.assertRaises(ValidationError):
            wizard.action_confirm()
        self.assertEqual(first.state, 'active')

        self._sign(second)
        action = second.action_activate()
        self.env[action['res_model']].browse(action['res_id']).action_confirm()
        self.assertEqual(second.state, 'active')
        self.assertEqual(first.state, 'draft')
        self.assertFalse(self.env['hr.employee.form.101'].search_count([
            ('employee_id', '=', self.employee.id), ('state', '=', 'active'),
            ('id', '!=', second.id),
        ]))
        self.assertEqual(self.employee.version_id.private_city, 'ירושלים')

    def test_non_draft_form_is_locked(self):
        form = self._sign(self._new_form())
        with self.assertRaises(ValidationError):
            form.private_city = 'באר שבע'
        form.action_activate()
        with self.assertRaises(ValidationError):
            form.private_city = 'אילת'

        form.action_reset_to_draft()
        form.private_city = 'אילת'
        self.assertEqual(form.private_city, 'אילת')

    def test_standard_sign_popup_is_used(self):
        partner = self.employee.work_contact_id
        partner.email = 'employee@example.com'
        template = self.env['hr.employee.form.101']._ensure_form_101_sign_template()
        action = self.employee.action_send_form_101_for_completion()
        self.assertEqual(action['res_model'], 'sign.send.request')
        self.assertEqual(action['target'], 'new')

        wizard = self.env[action['res_model']].with_context(
            **action['context']).create({})
        self.assertEqual(wizard.template_id, template)
        self.assertEqual(wizard.form_101_employee_id, self.employee)
        self.assertEqual(wizard.signer_ids.partner_id, partner)

        request = wizard.with_context(no_sign_mail=True).create_request()
        self.assertEqual(request.reference_doc, self.employee)
        self.assertTrue(request.request_item_ids.sign_item_value_ids)
        self.assertFalse(
            request.request_item_ids.sign_item_value_ids.filtered(
                lambda value: value.sign_item_id.type_id.item_type
                in ('radio', 'checkbox')
            ),
            'Prefilled choices become read-only in Odoo Sign',
        )

    def test_existing_form_moves_from_sent_to_signed_with_same_request(self):
        self.employee.work_contact_id.email = 'employee@example.com'
        form = self._new_form()
        action = form.action_send_for_signature()
        self.assertEqual(action['res_model'], 'sign.send.request')
        self.assertEqual(action['target'], 'new')

        wizard = self.env[action['res_model']].with_context(
            **action['context']).create({})
        request = wizard.with_context(no_sign_mail=True).create_request()
        self.assertEqual(form.state, 'sent')
        self.assertEqual(form.sign_request_id, request)
        self.assertEqual(request.reference_doc, form)

        items = self._template_items_by_key(request.template_id)
        request.request_item_ids.sudo()._fill({
            str(items['income_monthly'].id): 'true',
            str(items['sex_male'].id): 'true',
            str(items['marital_single'].id): 'true',
            str(items['resident_yes'].id): 'true',
            str(items['kibbutz_no'].id): 'true',
            str(items['other_income_no'].id): 'true',
        })

        request.request_item_ids.signature = base64.b64encode(b'signature')
        self.env['sign.completed.document'].create({
            'sign_request_id': request.id,
            'document_id': request.template_id.document_ids[:1].id,
            'file': base64.b64encode(b'%PDF-1.4\n%%EOF'),
        })
        request.state = 'signed'
        completed_form = self.env[
            'hr.employee.form.101']._create_from_sign_request(request)
        self.assertEqual(completed_form, form)
        self.assertEqual(form.state, 'signed')
        self.assertTrue(form.form_file)
        self.assertTrue(form.employee_signature)
        self.assertTrue(form.employee_signature_date)

    def test_old_request_cannot_complete_after_reset_to_draft(self):
        self.employee.work_contact_id.email = 'employee@example.com'
        form = self._new_form()
        action = form.action_send_for_signature()
        wizard = self.env[action['res_model']].with_context(
            **action['context']).create({})
        request = wizard.with_context(no_sign_mail=True).create_request()
        self.assertEqual(form.state, 'sent')

        form.action_reset_to_draft()
        self.assertEqual(form.state, 'draft')
        self.assertFalse(form.sign_request_id)
        self.assertEqual(request.state, 'canceled')

        request.state = 'signed'
        result = self.env[
            'hr.employee.form.101']._create_from_sign_request(request)
        self.assertEqual(result, form)
        self.assertEqual(form.state, 'draft')
        self.assertFalse(form.form_file)

    def test_direct_sign_template_send_resolves_a_unique_employee(self):
        partner = self.employee.work_contact_id
        partner.email = 'employee@example.com'
        template = self.env['hr.employee.form.101']._ensure_form_101_sign_template()
        action = template.with_context(
            default_signer_id=partner.id,
        ).open_sign_send_dialog()
        wizard = self.env[action['res_model']].with_context(
            **action['context']).create({})
        self.assertFalse(wizard.form_101_employee_id)
        request = wizard.with_context(no_sign_mail=True).create_request()
        self.assertEqual(request.reference_doc, self.employee)
        self.assertEqual(request.request_item_ids.partner_id, partner)
        self.assertTrue(request.request_item_ids.sign_item_value_ids)

    def test_direct_sign_template_opens_employee_choice_only_when_ambiguous(self):
        partner = self.employee.work_contact_id
        partner.email = 'shared@example.com'
        other_employee = self.env['hr.employee'].create({
            'name': 'עובד נוסף',
            'company_id': self.env.company.id,
            'work_contact_id': partner.id,
        })
        template = self.env['hr.employee.form.101']._ensure_form_101_sign_template()
        action = template.with_context(
            default_signer_id=partner.id,
        ).open_sign_send_dialog()
        send_wizard = self.env[action['res_model']].with_context(
            **action['context']).create({})

        choice_action = send_wizard.with_context(no_sign_mail=True).send_request()
        self.assertEqual(
            choice_action['res_model'],
            'hr.employee.form.101.sign.employee.wizard',
        )
        choice_wizard = self.env[choice_action['res_model']].with_context(
            **choice_action['context']).create({
                'employee_id': other_employee.id,
            })
        self.assertEqual(
            choice_wizard.candidate_employee_ids,
            self.employee | other_employee,
        )
        request_count = self.env['sign.request'].search_count([])
        choice_wizard.with_context(no_sign_mail=True).action_confirm()
        self.assertEqual(self.env['sign.request'].search_count([]), request_count + 1)
        request = self.env['sign.request'].search([], order='id desc', limit=1)
        self.assertEqual(request.reference_doc, other_employee)

    def test_sign_fields_have_no_visible_placeholder(self):
        template = self.env['hr.employee.form.101']._ensure_form_101_sign_template()
        item = self._template_items_by_key(template)['tax_year']
        self.assertEqual(item.type_id, self.env.ref('sign.sign_item_type_text'))
        self.assertFalse(item.name)

    def test_sign_checkbox_groups_reject_contradictory_choices(self):
        form_model = self.env['hr.employee.form.101']
        with self.assertRaisesRegex(ValidationError, 'מין'):
            form_model._validate_sign_checkbox_values({
                'sex_male': 'on',
                'sex_female': 'on',
            })
        with self.assertRaisesRegex(ValidationError, 'קופת חולים'):
            form_model._validate_sign_checkbox_values({
                'health_fund_yes': 'on',
                'health_fund_no': 'on',
            })
        with self.assertRaisesRegex(ValidationError, 'אין הכנסה'):
            form_model._validate_sign_checkbox_values({
                'spouse_no_income': 'on',
                'spouse_income_work': 'on',
            })

        self.employee.work_contact_id.email = 'checkbox@example.com'
        action = self.employee.action_send_form_101_for_completion()
        wizard = self.env[action['res_model']].with_context(
            **action['context']).create({})
        request = wizard.with_context(no_sign_mail=True).create_request()
        items = self._template_items_by_key(request.template_id)
        with self.assertRaisesRegex(ValidationError, 'מין'):
            request.request_item_ids.sudo()._sign({
                str(items['sex_male'].id): 'on',
                str(items['sex_female'].id): 'on',
            }, validation_required=True)

    def test_signing_requires_an_employer_income_type(self):
        self.employee.work_contact_id.email = 'income-required@example.com'
        action = self.employee.action_send_form_101_for_completion()
        wizard = self.env[action['res_model']].with_context(
            **action['context']).create({})
        request = wizard.with_context(no_sign_mail=True).create_request()

        with self.assertRaisesRegex(ValidationError, 'סוג הכנסה'):
            request.request_item_ids.sudo()._sign(
                {}, validation_required=True)

    def test_exclusive_checkbox_choices_are_native_radio_sets(self):
        template = self.env['hr.employee.form.101']._ensure_form_101_sign_template()
        items = self._template_items_by_key(template)
        for keys in (
            ('sex_male', 'sex_female'),
            ('health_fund_yes', 'health_fund_no'),
            ('resident_yes', 'resident_no'),
            ('credit_points_here', 'credit_points_elsewhere'),
        ):
            group_items = self.env['sign.item']
            for key in keys:
                group_items |= items[key]
            self.assertEqual(set(group_items.type_id.mapped('item_type')), {'radio'})
            self.assertEqual(len(group_items.radio_set_id), 1)
            self.assertTrue(all(group_items.mapped('l10n_il_form_101_radio')))

    def test_sign_values_are_converted_to_a_signed_form(self):
        partner = self.employee.work_contact_id
        partner.email = 'employee@example.com'
        action = self.employee.action_send_form_101_for_completion()
        wizard = self.env[action['res_model']].with_context(
            **action['context']).create({})
        request = wizard.with_context(no_sign_mail=True).create_request()
        definitions = {
            definition['key']: definition
            for definition in _SIGN_TEMPLATE_ITEMS
        }
        items = self._template_items_by_key(request.template_id)
        entered = {
            'tax_year': '2026',
            'last_name': 'בדיקה',
            'birthday': '1990-01-01',
            'employer_phone': '03-5555555',
            'employer_withholding_file': '935000000',
            'employment_start_date': '2026-01-01',
            'declaration_date': '2026-01-02',
            'private_house_number': '1',
            'sex_male': 'true',
            'marital_single': 'true',
            'resident_yes': 'true',
            'resident_no': 'off',
            'health_fund_no': 'true',
            'income_monthly': 'true',
            'other_income_yes': 'true',
            'other_income_monthly': 'true',
            'credit_points_here': 'true',
            'relief_resident': 'true',
            'other_employer_1_name': 'מעסיק נוסף',
            'other_employer_1_address': 'תל אביב',
            'other_employer_1_file': '123456789',
            'other_employer_1_type': 'עבודה',
            'other_employer_1_income': '1000',
            'other_employer_1_tax': '100',
        }
        request.request_item_ids.sudo()._fill({
            str(items[key].id): value
            for key, value in entered.items()
        })

        values = self.env[
            'hr.employee.form.101']._form_101_values_from_sign_request(request)
        self.assertEqual(values['employee_id'], self.employee.id)
        self.assertEqual(values['state'], 'signed')
        self.assertEqual(values['tax_year'], '2026')
        self.assertEqual(values['sex'], 'male')
        self.assertEqual(values['marital'], 'single')
        self.assertEqual(values['employer_income_main_type'], 'monthly')
        self.assertEqual(values['has_other_income'], 'yes')
        self.assertTrue(values['declaration_confirmed'])

        self.env['sign.completed.document'].create({
            'sign_request_id': request.id,
            'document_id': request.template_id.document_ids[:1].id,
            'file': base64.b64encode(b'%PDF-1.4\n%%EOF'),
        })
        form = self.env['hr.employee.form.101']._create_from_sign_request(request)
        self.assertEqual(form.state, 'signed')
        self.assertEqual(form.employee_id, self.employee)
        self.assertEqual(form.sign_request_id, request)
        self.assertTrue(form.form_file)
        self.assertEqual(form.other_employer_ids.name, 'מעסיק נוסף')
        self.assertEqual(form.other_employer_ids.income_type, 'work')

    def test_form_101_assets_and_sign_positions_are_installed(self):
        template = self.env['hr.employee.form.101']._ensure_form_101_sign_template()
        initial_item_count = len(template.sign_item_ids)
        self.env['hr.employee.form.101']._ensure_form_101_assets()
        self.env['hr.employee.form.101']._ensure_form_101_assets()
        self.assertEqual(len(template.sign_item_ids), initial_item_count)
        self.assertEqual(
            template,
            self.env.ref('l10n_il_hr_payroll.sign_template_form_101'),
        )
        self.assertTrue(template.active)
        self.assertEqual(template.model_id.model, 'hr.employee.form.101')
        self.assertEqual(template.document_ids.num_pages, 2)
        self.assertTrue(
            self.env.ref('l10n_il_hr_payroll.sign_item_role_form_101_employee'))

        document = template.document_ids
        signature = document.sign_item_ids.filtered(
            lambda item: item.page == 2 and item.type_id.item_type == 'signature')
        self.assertEqual(len(signature), 1)
        self.assertTrue(signature.required)
        self.assertFalse(signature.constant)
        self.assertEqual(signature.page, 2)
        self.assertEqual(signature.responsible_id.name, 'עובד/ת')

        items = self._template_items_by_key(template)
        child_checkbox = items['child_1_custody']
        relief_checkbox = items['relief_resident']
        self.assertGreater(child_checkbox.posX, 0.87)
        self.assertGreater(relief_checkbox.posX, 0.85)
        self.assertTrue({
            'health_fund_yes',
            'health_fund_no',
            'kibbutz_yes',
            'kibbutz_no',
            'kibbutz_not_transferred',
            'credit_points_here',
            'credit_points_elsewhere',
            'no_study_fund_elsewhere',
            'no_pension_elsewhere',
            'other_children_born',
            'other_children_age_1_2',
            'other_children_age_3',
            'other_children_age_4_5',
            'other_children_age_6_17',
        }.issubset(items))
        native_types = {
            self.env.ref(xmlid).id for xmlid in {
                definition['type_xmlid']
                for definition in _SIGN_TEMPLATE_ITEMS
            }
        } | {self.env.ref('sign.sign_item_type_radio').id}
        self.assertFalse(document.sign_item_ids.filtered(
            lambda item: item.page in (1, 2) and item.type_id.id not in native_types))
        self.assertFalse(self.env['sign.item.type'].search([
            ('model_id.model', '=', 'hr.employee.form.101'),
        ]))
        self.assertEqual(items['birthday'].type_id, self.env.ref('sign.sign_item_type_date'))
        self.assertEqual(items['private_email'].type_id, self.env.ref('sign.sign_item_type_email'))
        self.assertEqual(items['mobile_phone'].type_id, self.env.ref('sign.sign_item_type_phone'))
        self.assertEqual(items['sex_male'].type_id, self.env.ref('sign.sign_item_type_radio'))
        self.assertEqual(items['relief_resident'].type_id, self.env.ref('sign.sign_item_type_checkbox'))
        self.assertAlmostEqual(items['employer_name'].posX * 210, 148.05, places=2)
        self.assertAlmostEqual(items['employer_name'].posY * 297, 58.806, places=2)
        self.assertAlmostEqual(items['private_street'].posX * 210, 80.85, places=2)
        self.assertAlmostEqual(items['private_zip'].posX * 210, 10.50, places=2)
        # Sign stores positions on its own PDF grid, which rounds millimetres
        # by up to roughly 0.03 mm when values are written and read back.
        self.assertAlmostEqual(items['tax_year'].width * 210, 23.50, delta=0.03)
        self.assertNotIn('other_income_other_details', items)
        self.assertAlmostEqual(items['other_employer_1_tax'].posX * 210, 10.50, delta=0.10)
        self.assertAlmostEqual(items['other_employer_1_name'].posX * 210, 157.08, delta=0.10)
        self.assertAlmostEqual(items['other_employer_1_address'].width * 210, 47.04, delta=0.15)
        self.assertAlmostEqual(items['child_1_birthday'].posX * 210, 90.51, delta=0.10)
        self.assertAlmostEqual(items['child_1_birthday'].posY * 297, 134.53, delta=0.15)
        self.assertAlmostEqual(items['child_13_birthday'].posY * 297, 227.17, delta=0.15)
        self.assertAlmostEqual(items['health_fund_name'].posY * 297, 103.00, delta=0.10)
        self.assertEqual(items['health_fund_name'].type_id, self.env.ref('sign.sign_item_type_text'))
        self.assertAlmostEqual(items['spouse_income_other'].posX * 210, 28.56, delta=0.10)
        self.assertAlmostEqual(items['spouse_income_other'].posY * 297, 253.64, delta=0.10)
        self.assertEqual(
            items['spouse_income_other'].type_id,
            self.env.ref('sign.sign_item_type_checkbox'),
        )
        self.assertAlmostEqual(items['spouse_income_work'].posX * 210, 56.49, delta=0.10)
        self.assertEqual(
            items['spouse_income_work'].type_id,
            self.env.ref('sign.sign_item_type_checkbox'),
        )
        self.assertAlmostEqual(items['spouse_has_income_yes'].posX * 210, 99.54, delta=0.10)
        self.assertEqual(
            items['spouse_has_income_yes'].type_id,
            self.env.ref('sign.sign_item_type_radio'),
        )
        self.assertAlmostEqual(items['mobile_phone'].posX * 210, 26.67, delta=0.10)
        self.assertAlmostEqual(items['private_phone'].posX * 210, 85.68, delta=0.10)
        self.assertAlmostEqual(items['identity_number_page_2'].posX * 210, 33.39, delta=0.10)
        self.assertAlmostEqual(items['identity_number_page_2'].width * 210, 27.30, delta=0.10)
        self.assertAlmostEqual(items['relief_resident'].posX * 210, 181.06, delta=0.10)
        self.assertAlmostEqual(items['relief_resident'].posY * 297, 15.17, delta=0.10)
        self.assertAlmostEqual(items['employment_start_date'].posY * 297, 133.35, delta=0.15)
        self.assertAlmostEqual(items['reserve_combat_days'].posX * 210, 120.33, delta=0.15)
        self.assertAlmostEqual(items['disabled_children_count'].posX * 210, 157.98, delta=0.10)
        self.assertAlmostEqual(items['service_start_date'].posX * 210, 67.96, delta=0.10)
        self.assertAlmostEqual(items['service_end_date'].posX * 210, 20.75, delta=0.10)
        self.assertAlmostEqual(items['declaration_date'].posY * 297, 227.22, delta=0.10)
        self.assertFalse(document.sign_item_ids.filtered('name'))
        for item in document.sign_item_ids.filtered(lambda record: record.page in (1, 2)):
            self.assertGreaterEqual(item.posX, 0.0)
            self.assertGreaterEqual(item.posY, 0.0)
            self.assertLessEqual(item.posX + item.width, 1.0)
            self.assertLessEqual(item.posY + item.height, 1.0)
        self.assertEqual(
            self.env.ref('l10n_il_hr_payroll.sign_template_form_101'),
            self._new_form().sign_template_id,
        )
        form_model = self.env['ir.model']._get('hr.employee.form.101')
        self.assertEqual(self.env['sign.template'].search_count([
            ('active', '=', True),
            ('model_id', '=', form_model.id),
        ]), 1)

    def test_radio_hit_areas_are_separate_and_clickable(self):
        template = self.env['hr.employee.form.101']._ensure_form_101_sign_template()
        items = self._template_items_by_key(template)
        for group in set(_SIGN_RADIO_GROUP_BY_KEY.values()):
            group_items = [
                items[key]
                for key, item_group in _SIGN_RADIO_GROUP_BY_KEY.items()
                if item_group == group
            ]
            self.assertTrue(group_items[0].radio_set_id)
            self.assertTrue(all(item.l10n_il_form_101_radio for item in group_items))
            self.assertTrue(all(
                item.radio_set_id == group_items[0].radio_set_id
                for item in group_items
            ))
            for index, first in enumerate(group_items):
                self.assertGreaterEqual(first.width * 210, 3.55)
                self.assertGreaterEqual(first.height * 297, 3.55)
                first_rect = (
                    first.posX, first.posY,
                    first.posX + first.width, first.posY + first.height,
                )
                for second in group_items[index + 1:]:
                    if first.page != second.page:
                        continue
                    second_rect = (
                        second.posX, second.posY,
                        second.posX + second.width, second.posY + second.height,
                    )
                    overlaps = (
                        first_rect[0] < second_rect[2]
                        and second_rect[0] < first_rect[2]
                        and first_rect[1] < second_rect[3]
                        and second_rect[1] < first_rect[3]
                    )
                    self.assertFalse(
                        overlaps,
                        f'Radio controls {group} overlap: {first.id}, {second.id}',
                    )

    def test_sign_choice_autofill_covers_every_printed_option(self):
        form = self._new_form(
            kibbutz_status='income_not_transferred',
            health_fund_member='no',
            has_other_income='yes',
            other_income_monthly=True,
            credit_points_here='elsewhere',
            no_study_fund_elsewhere=True,
            no_pension_elsewhere=True,
        )
        self.assertFalse(form.sign_kibbutz_yes)
        self.assertFalse(form.sign_kibbutz_no)
        self.assertTrue(form.sign_kibbutz_not_transferred)
        self.assertFalse(form.sign_health_fund_yes)
        self.assertTrue(form.sign_health_fund_no)
        self.assertFalse(form.sign_credit_points_here)
        self.assertTrue(form.sign_credit_points_elsewhere)
        self.assertTrue(form.sign_no_study_fund_elsewhere)
        self.assertTrue(form.sign_no_pension_elsewhere)

    def test_signed_form_can_return_to_draft(self):
        form = self._sign(self._new_form())
        old_request = form.sign_request_id
        form.action_reset_to_draft()
        self.assertEqual(form.state, 'draft')
        self.assertFalse(form.sign_request_id)
        self.assertEqual(old_request.state, 'signed')

    def test_no_payroll_field_is_written(self):
        form = self._sign(self._new_form(
            relief_children_in_custody=True, custody_children_age_6_17=2))
        form.action_activate()
        self.assertEqual(form.custody_children_age_6_17, 2)

    def test_active_form_calculates_resident_and_child_credit_points(self):
        form = self._sign(self._new_form(
            relief_resident=True,
            relief_children_in_custody=True,
            custody_children_born=1,
            custody_children_age_1_2=1,
            custody_children_age_3=1,
            custody_children_age_4_5=1,
            custody_children_age_6_17=1,
            custody_children_age_18=1,
        ))
        form.action_activate()
        self.assertEqual(
            form._il_payroll_credit_points(date(2026, 6, 1)),
            17.75,
        )

    def test_female_resident_gets_additional_half_point(self):
        form = self._sign(self._new_form(
            sex='female', relief_resident=True))
        form.action_activate()
        self.assertEqual(
            form._il_payroll_credit_points(date(2026, 6, 1)), 2.75)

    def test_credits_elsewhere_make_this_a_secondary_payroll(self):
        form = self._sign(self._new_form(
            relief_resident=True,
            has_other_income='yes',
            other_income_monthly=True,
            credit_points_here='elsewhere',
        ))
        form.action_activate()
        self.assertFalse(form._il_is_primary_payroll_income())
        self.assertEqual(
            form._il_payroll_credit_points(date(2026, 6, 1)), 0.0)

    def test_credit_points_only_apply_in_form_tax_year_and_while_active(self):
        form = self._sign(self._new_form(relief_resident=True))
        form.action_activate()
        self.assertEqual(
            form._il_payroll_credit_points(date(2026, 6, 1)), 2.25)
        self.assertEqual(
            form._il_payroll_credit_points(date(2025, 6, 1)), 0.0)
        form.action_reset_to_draft()
        self.assertEqual(
            form._il_payroll_credit_points(date(2026, 6, 1)), 0.0)

    def test_reserve_credit_points_use_2026_temporary_table(self):
        form = self._sign(self._new_form(
            relief_resident=True,
            relief_reserve_combat=True,
            reserve_combat_days=55,
        ))
        form.action_activate()
        self.assertEqual(
            form._il_payroll_credit_points(date(2026, 6, 1)), 3.5)

    def test_legal_form_supporting_fields_are_available(self):
        form_fields = self.env['hr.employee.form.101']._fields
        self.assertTrue({
            'passport_country_id',
            'identity_card_file',
            'passport_file',
            'residence_permit_file',
            'separated_tax_officer_certificate',
            'other_income_other_details',
            'spouse_passport_country_id',
            'disabled_blind_certificate',
            'disabled_benefit_certificate',
            'eligible_settlement_certificate',
            'new_immigrant_certificate',
            'returning_resident_certificate',
            'spouse_disability_certificate',
            'child_support_judgment',
            'disabled_child_benefit_certificate',
            'former_spouse_alimony_judgment',
            'discharge_certificate',
            'studies_form_119',
            'reserve_combat_certificate',
            'tax_coordination_requested',
            'no_previous_income_certificate',
            'tax_officer_coordination_certificate',
        }.issubset(form_fields))
        self.assertIn(
            'payslip_file',
            self.env['hr.employee.form.101.other.employer']._fields,
        )

    def test_export_pdf_uses_form_101_report(self):
        form = self._new_form()
        action = form.action_export_pdf()
        self.assertEqual(action['type'], 'ir.actions.report')
        self.assertEqual(action['report_type'], 'qweb-pdf')
        self.assertEqual(
            action['report_name'],
            'l10n_il_hr_payroll.report_employee_form_101',
        )
        html, file_type = self.env['ir.actions.report']._render_qweb_html(
            'l10n_il_hr_payroll.report_employee_form_101', form.ids)
        self.assertEqual(file_type, 'html')
        self.assertIn(b'form101_page_1.png', html)
        self.assertIn(b'form101_page_2.png', html)
