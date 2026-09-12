import json
import re
from copy import deepcopy

from odoo.tests import TransactionCase, tagged
from odoo.tools import file_open
from odoo.tools.translate import code_translations, translation_file_reader

from ..models.hr_hebrew_translations import IrHttp, _hebrew_ui_data


@tagged('post_install', '-at_install')
class TestHebrewHrUiTranslations(TransactionCase):

    def _import(self):
        return self.env['ir.module.module']._il_import_hr_hebrew_ui_translations()

    def test_database_translation_preserves_english_and_other_languages(self):
        leave_type = self.env.ref('hr_holidays.leave_type_sick_time_off').with_context(lang='en_US')
        english = leave_type.name
        leave_type.update_field_translations('name', {'he_IL': english})
        before = leave_type._fields['name']._get_stored_translations(leave_type).copy()
        self._import()
        after = leave_type._fields['name']._get_stored_translations(leave_type)
        self.assertEqual(leave_type.name, english)
        self.assertEqual(leave_type.with_context(lang='he_IL').name, 'חופשת מחלה')
        self.assertEqual({k: v for k, v in before.items() if k != 'he_IL'},
                         {k: v for k, v in after.items() if k != 'he_IL'})

    def test_upgrade_preserves_custom_hebrew_and_is_idempotent(self):
        leave_type = self.env.ref('hr_holidays.leave_type_sick_time_off').with_context(lang='en_US')
        leave_type.update_field_translations('name', {'he_IL': 'נוסח עברי מותאם לבדיקה'})
        self._import()
        self.assertEqual(leave_type.with_context(lang='he_IL').name, 'נוסח עברי מותאם לבדיקה')
        self.assertEqual(self._import(), {'model_terms': 0, 'model_values': 0, 'named_values': 0})

    def test_changed_english_source_is_not_given_an_outdated_translation(self):
        leave_type = self.env.ref('hr_holidays.leave_type_sick_time_off').with_context(lang='en_US')
        leave_type.update_field_translations('name', {
            'en_US': 'New time off meaning', 'he_IL': 'New time off meaning',
        })
        self._import()
        self.assertEqual(leave_type.with_context(lang='he_IL').name, 'New time off meaning')
        self.assertEqual(leave_type.name, 'New time off meaning')

    def test_frontend_additions_are_hebrew_only_and_keep_native_english(self):
        http = self.env['ir.http']
        modules = ['hr_attendance', 'hr_payroll']
        english = http._get_translations_for_webclient(modules, 'en_US')
        native_english = super(IrHttp, http)._get_translations_for_webclient(modules, 'en_US')
        self.assertEqual(english, native_english)
        native_hebrew = deepcopy(super(IrHttp, http)._get_translations_for_webclient(modules, 'he_IL'))
        hebrew, _params = http._get_translations_for_webclient(modules, 'he_IL')
        messages = {item['id']: item['string'] for item in hebrew['hr_attendance']['messages']}
        self.assertEqual(messages['Proceed Anyway'], 'המשך בכל זאת')
        # Native cached results remain unmodified after requesting Hebrew.
        self.assertEqual(http._get_translations_for_webclient(modules, 'en_US'), native_english)
        self.assertEqual(super(IrHttp, http)._get_translations_for_webclient(modules, 'he_IL'), native_hebrew)
        context_hebrew, _params = http.with_context(lang='he_IL')._get_translations_for_webclient(modules, None)
        self.assertEqual(context_hebrew, hebrew)

    def test_frontend_does_not_inject_unrequested_hr_modules(self):
        result, _params = self.env['ir.http']._get_translations_for_webclient(['web'], 'he_IL')
        self.assertNotIn('hr_attendance', result)
        self.assertNotIn('hr_payroll', result)

    def test_python_code_translations_are_hebrew_only_and_preserve_native_cache(self):
        module, source = 'hr_payroll', 'This action is forbidden on validated payslips.'
        english = dict(code_translations.get_python_translations(module, 'en_US'))
        key = (module, 'he_IL')
        original = code_translations.get_python_translations(*key)
        missing = dict(original)
        missing.pop(source, None)
        code_translations.python_translations[key] = type(original)(missing)
        try:
            self.env['ir.module.module']._il_load_hr_hebrew_python_translations()
            translated = code_translations.get_python_translations(*key)
            self.assertEqual(translated[source], 'פעולה זו אינה מותרת בתלושים שאושרו.')
            self.assertNotIn(source, missing)
            self.assertEqual(dict(code_translations.get_python_translations(module, 'en_US')), english)
            custom = dict(translated, **{source: 'הודעה עברית מותאמת'})
            code_translations.python_translations[key] = type(original)(custom)
            self.env['ir.module.module']._il_load_hr_hebrew_python_translations()
            self.assertEqual(code_translations.get_python_translations(*key)[source], 'הודעה עברית מותאמת')
        finally:
            code_translations.python_translations[key] = original

    def test_translation_assets_preserve_placeholders_and_target_ui_only(self):
        allowed = {
            'ir.ui.view', 'ir.ui.menu', 'ir.actions.act_window', 'ir.actions.client',
            'ir.actions.report', 'ir.model.fields', 'ir.model.fields.selection',
            'hr.payroll.dashboard.warning', 'hr.leave.type', 'hr.work.entry.type',
        }
        pattern = re.compile(r'(?<!%)%(?!%)(?:\([^)]+\))?[#0+\-]*\d*(?:\.\d+)?[diouxXeEfFgGcrs]')
        rows = []
        for path in _hebrew_ui_data()['po_files']:
            with file_open(path, 'rb') as source:
                rows.extend(translation_file_reader(source, fileformat='po'))
        self.assertGreater(len(rows), 1000)
        for row in rows:
            self.assertIn(row['name'].split(',')[0], allowed)
            self.assertEqual(sorted(pattern.findall(row['src'])), sorted(pattern.findall(row['value'])), row['src'])
        for module, terms in _hebrew_ui_data()['web'].items():
            self.assertTrue(module.startswith(('hr', 'l10n_il_hr', 'documents_hr', 'spreadsheet_dashboard_hr')))
            for source, value in terms.items():
                self.assertEqual(sorted(pattern.findall(source)), sorted(pattern.findall(value)), source)
        for path in _hebrew_ui_data()['python_files']:
            with file_open(path, 'r') as source:
                modules = json.load(source)
            for module, terms in modules.items():
                self.assertTrue(module.startswith(('hr', 'l10n_il_hr', 'documents_hr', 'spreadsheet_dashboard_hr')))
                for source, value in terms.items():
                    self.assertEqual(sorted(pattern.findall(source)), sorted(pattern.findall(value)), source)
                    self.assertEqual(source.count('%%'), value.count('%%'), source)
