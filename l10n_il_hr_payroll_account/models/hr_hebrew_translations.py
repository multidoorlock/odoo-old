# -*- coding: utf-8 -*-
"""Hebrew-only additions to native HR translations; English remains the source."""

import json
from functools import lru_cache

from odoo import api, models
from odoo.tools import file_open
from odoo.tools.translate import TranslationImporter, code_translations, translation_file_reader


LANG = 'he_IL'
DATA_PATH = 'l10n_il_hr_payroll_account/i18n/hr_ui_he.json'
NAMED_MODELS = frozenset({'hr.leave.type', 'hr.work.entry.type'})


@lru_cache(maxsize=1)
def _hebrew_ui_data():
    with file_open(DATA_PATH, mode='r') as source:
        return json.load(source)


class IrModuleModule(models.Model):
    _inherit = 'ir.module.module'

    def _register_hook(self):
        result = super()._register_hook()
        _hebrew_ui_data.cache_clear()
        self._il_load_hr_hebrew_python_translations()
        return result

    @api.model
    def _il_load_hr_hebrew_python_translations(self):
        """Extend Odoo's native per-module/language code cache at startup.

        The database importer intentionally ignores code terms. Native code
        dictionaries are process-local and immutable; replace only he_IL
        dictionaries with copied mappings, keeping native translations.
        """
        if not self.env['res.lang']._lang_get(LANG):
            return 0
        added = 0
        for path in _hebrew_ui_data().get('python_files', []):
            with file_open(path, mode='r') as source:
                additions = json.load(source)
            for module, terms in additions.items():
                native = code_translations.get_python_translations(module, LANG)
                messages = dict(native)
                for source, value in terms.items():
                    if messages.get(source) in (None, '', source):
                        messages[source] = value
                        added += 1
                code_translations.python_translations[(module, LANG)] = type(native)(messages)
        return added

    @api.model
    def _il_import_hr_hebrew_ui_translations(self):
        """Called by module data after views load, never through a public RPC.

        Odoo's importer merges the he_IL JSON key. Prune already translated
        terms first so upgrades retain local Hebrew edits and changed sources.
        """
        if not self.env['res.lang']._lang_get(LANG):
            return {'model_terms': 0, 'model_values': 0, 'named_values': 0}
        _hebrew_ui_data.cache_clear()
        importer = TranslationImporter(self.env.cr, verbose=False)
        source_values = {}
        for path in _hebrew_ui_data()['po_files']:
            with file_open(path, mode='rb') as source:
                importer.load(source, 'po', LANG)
                source.seek(0)
                for row in translation_file_reader(source, fileformat='po'):
                    if row['type'] == 'model':
                        source_values[(row['name'], row['module'] + '.' + row['imd_name'])] = row['src']

        model_count = 0
        term_count = 0
        for model, fields in importer.model_translations.items():
            for field_name, records in fields.items():
                for xmlid in list(records):
                    record = self.env.ref(xmlid, raise_if_not_found=False)
                    values = record._fields[field_name]._get_stored_translations(record) if record else {}
                    source = source_values.get((model + ',' + field_name, xmlid))
                    if (not values or values.get('en_US') != source
                            or values.get('_he_IL', values.get(LANG)) not in (None, '', source)):
                        records.pop(xmlid)
                    else:
                        model_count += 1

        for model, fields in importer.model_terms_translations.items():
            for field_name, records in fields.items():
                for xmlid, terms in list(records.items()):
                    record = self.env.ref(xmlid, raise_if_not_found=False)
                    if not record:
                        records.pop(xmlid)
                        continue
                    field = record._fields[field_name]
                    values = field._get_stored_translations(record) or {}
                    source = values.get('_en_US', values.get('en_US'))
                    if not source:
                        records.pop(xmlid)
                        continue
                    existing = field.get_translation_dictionary(source, {
                        LANG: values.get('_he_IL', values.get(LANG, source)),
                    })
                    for term in list(terms):
                        if term not in existing or existing[term].get(LANG, term) != term:
                            terms.pop(term)
                        else:
                            term_count += 1
                    if not terms:
                        records.pop(xmlid)
        # The strict pruning above also protects local edits on noupdate
        # records. Force is needed to replace an explicitly stored English
        # fallback on such records, rather than retaining that missing value.
        importer.save(overwrite=True, force_overwrite=True)

        # Some manually configured types have no external ID. Their exact
        # English names form a portable, tightly scoped translation fallback.
        named_count = 0
        for entry in _hebrew_ui_data().get('named_records', []):
            model = entry['model']
            if model not in NAMED_MODELS or model not in self.env:
                continue
            Model = self.env[model].with_context(lang='en_US')
            records = Model.search([('name', '=', entry['source']), ('active', '=', True)])
            for record in records:
                values = record._fields['name']._get_stored_translations(record) or {}
                if values.get('en_US') != entry['source']:
                    continue
                if values.get('_he_IL', values.get(LANG)) not in (None, '', entry['source']):
                    continue
                record.update_field_translations('name', {LANG: entry['translation']})
                named_count += 1
        self._il_load_hr_hebrew_python_translations()
        return {'model_terms': term_count, 'model_values': model_count, 'named_values': named_count}


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @api.model
    def _get_translations_for_webclient(self, modules, lang):
        lang = lang or self.env.context.get('lang')
        translations, lang_params = super()._get_translations_for_webclient(modules, lang)
        if lang != LANG:
            return translations, lang_params
        additions = _hebrew_ui_data().get('web', {})
        result = dict(translations)
        for module in modules:
            if module not in additions:
                continue
            current = translations.get(module, {})
            messages = {item['id']: item['string'] for item in current.get('messages', [])}
            for source, value in additions[module].items():
                if messages.get(source) in (None, '', source):
                    messages[source] = value
            # Do not modify objects returned by native translation caches.
            result[module] = dict(current, messages=[
                {'id': source, 'string': value} for source, value in messages.items()
            ])
        return result, lang_params
