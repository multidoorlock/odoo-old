from odoo.tests.common import TransactionCase


class HebrewTransactionCase(TransactionCase):
    """Give Hebrew UI tests their declared language dependency."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['res.lang']._activate_lang('he_IL')
        # Odoo only imports a module's translations for languages that are
        # active while the module is installed.  Odoo.sh may install this
        # module before Hebrew is enabled, so make the test dependency fully
        # explicit after activating the language.
        cls.env['ir.module.module']._il_import_hr_hebrew_ui_translations()
