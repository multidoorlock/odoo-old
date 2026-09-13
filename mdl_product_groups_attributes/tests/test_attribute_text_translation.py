from lxml import etree

from odoo.exceptions import ValidationError
from odoo.fields import Command
from odoo.tests import Form, tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestAttributeTextTranslation(TransactionCase):
    LANGS = ("en_US", "he_IL", "ar_001")

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context={**cls.env.context, "lang": "en_US"})
        cls.env.user.group_ids |= cls.env.ref("product.group_product_variant")
        for lang in cls.LANGS:
            cls.env["res.lang"]._activate_lang(lang)
        category = cls.env["product.category"].create({
            "name": "Window", "mdl_sku_component": "ATTR-T9N-",
        })
        attribute = cls.env["product.attribute"].create({
            "name": "Finish", "create_variant": "always",
            "value_ids": [Command.create({
                "name": "White", "mdl_sku_component": "W",
            })],
        })
        cls.source = attribute.value_ids
        cls.source.update_field_translations("name", {
            "en_US": "White", "he_IL": "לבן", "ar_001": "أبيض",
        })
        cls.templates = cls.env["product.template"]
        for index in (1, 2):
            cls.templates |= cls.env["product.template"].create({
                "name": "Display title %s" % index,
                "categ_id": category.id, "mdl_catalog_managed": True,
                "mdl_group_default_name": "Window",
                "mdl_group_default_sku": "ATTR-T9N-%s-" % index,
                "attribute_line_ids": [Command.create({
                    "attribute_id": attribute.id,
                    "value_ids": [Command.set(attribute.value_ids.ids)],
                })],
            })
        cls.value = cls.templates[0].mdl_attribute_value_ids
        cls.other_value = cls.templates[1].mdl_attribute_value_ids
        cls.products = cls.templates.with_context(active_test=False).product_variant_ids
        cls.skus = cls.products.read(["default_code", "active"])

    def _texts(self, value=None):
        value = self.value if value is None else value
        return {
            lang: value.with_context(lang=lang).mdl_name_component_value
            for lang in self.LANGS
        }

    def _names(self):
        return {
            lang: tuple(self.products.with_context(lang=lang).mapped("mdl_effective_name"))
            for lang in self.LANGS
        }

    def test_visible_text_fields_expose_native_translation_metadata(self):
        metadata = self.value.fields_get([
            "mdl_name_component_value", "mdl_default_name_component",
            "mdl_sku_component_value", "mdl_default_sku_component",
        ])
        self.assertTrue(metadata["mdl_name_component_value"]["translate"])
        self.assertTrue(metadata["mdl_default_name_component"]["translate"])
        self.assertFalse(metadata["mdl_sku_component_value"]["translate"])
        self.assertFalse(metadata["mdl_default_sku_component"]["translate"])
        view = self.templates[0].get_view(
            view_id=self.env.ref("product.product_template_only_form_view").id,
            view_type="form",
        )
        arch = etree.fromstring(view["arch"])
        nodes = arch.xpath("//field[@name='mdl_attribute_value_ids']/list/field[@name='mdl_name_component_value']")
        self.assertEqual(len(nodes), 1)
        self.assertNotEqual(nodes[0].get("readonly"), "1")

    def test_language_switch_and_dialog_show_localized_source_text(self):
        expected = {"en_US": "White", "he_IL": "לבן", "ar_001": "أبيض"}
        self.assertEqual(self._texts(), expected)
        terms, context = self.value.get_field_translations("mdl_name_component_value")
        self.assertEqual(
            {term["lang"]: term["value"] for term in terms if term["lang"] in self.LANGS},
            expected,
        )
        self.assertEqual(context, {"translation_type": "char", "translation_show_source": False})

    def test_first_translation_changes_only_its_group_and_language(self):
        before_texts, before_names = self._texts(), self._names()
        self.assertTrue(self.value.update_field_translations(
            "mdl_name_component_value", {"ar_001": "أبيض لامع"},
        ))
        self.env.flush_all()
        self.env.invalidate_all()
        self.assertEqual(self._texts(), {**before_texts, "ar_001": "أبيض لامع"})
        self.assertEqual(self._texts(self.other_value), before_texts)
        after_names = self._names()
        self.assertEqual(after_names["en_US"], before_names["en_US"])
        self.assertEqual(after_names["he_IL"], before_names["he_IL"])
        self.assertIn("أبيض لامع", after_names["ar_001"][0])
        self.assertEqual(self.products.read(["default_code", "active"]), self.skus)

    def test_english_edit_preserves_unedited_languages_and_dialog_close(self):
        before = self._texts()
        self.value.update_field_translations("mdl_name_component_value", {"en_US": "Gloss white"})
        self.assertEqual(self._texts(), {**before, "en_US": "Gloss white"})
        self.value.update_field_translations("mdl_name_component_value", {"ar_001": "أبيض لامع"})
        # The dialog reloads/saves the current language after another one changes.
        self.value.write({"mdl_name_component_value": self.value.mdl_name_component_value})
        self.assertEqual(self._texts(), {
            "en_US": "Gloss white", "he_IL": "לבן", "ar_001": "أبيض لامع",
        })
        self.assertEqual(self.products.read(["default_code", "active"]), self.skus)

    def test_form_edit_empty_text_and_reset_are_language_scoped(self):
        with Form(self.value.with_context(lang="he_IL"), view="product.product_template_attribute_value_view_form") as form:
            form.mdl_name_component_value = "לבן מבריק"
        before = self._texts()
        self.assertEqual(before["he_IL"], "לבן מבריק")
        self.value.with_context(lang="ar_001").write({"mdl_name_component_value": False})
        self.env.flush_all()
        self.env.invalidate_all()
        self.assertFalse(self.value.with_context(lang="ar_001").mdl_name_component_value)
        self.assertEqual(self._texts()["he_IL"], before["he_IL"])
        self.assertEqual(self._texts()["en_US"], before["en_US"])
        self.value.with_context(lang="ar_001").action_mdl_reset_name_component()
        self.assertEqual(self._texts(), before)
        self.value.update_field_translations("mdl_name_component_value", {"en_US": "Gloss white"})
        self.value.action_mdl_reset_name_component()
        self.assertEqual(self._texts(), before)
        self.assertEqual(self.products.read(["default_code", "active"]), self.skus)

    def test_matching_source_and_reset_preserve_other_overrides(self):
        self.value.update_field_translations("mdl_name_component_value", {
            "en_US": "Gloss white", "he_IL": "לבן מבריק", "ar_001": "أبيض لامع",
        })
        self.value.update_field_translations("mdl_name_component_value", {"he_IL": "לבן"})
        self.assertFalse(self.value.with_context(lang="he_IL").mdl_name_component_override)
        self.assertEqual(self._texts(), {
            "en_US": "Gloss white", "he_IL": "לבן", "ar_001": "أبيض لامع",
        })

    def test_default_value_translation_refreshes_all_groups_in_edited_language(self):
        before_names = self._names()
        self.source.update_field_translations("name", {"ar_001": "أبيض جديد"})
        self.env.flush_all()
        self.env.invalidate_all()
        for value in (self.value, self.other_value):
            self.assertEqual(value.with_context(lang="ar_001").mdl_name_component_value, "أبيض جديد")
        after_names = self._names()
        self.assertTrue(all("أبيض جديد" in name for name in after_names["ar_001"]))
        self.assertEqual(after_names["en_US"], before_names["en_US"])
        self.assertEqual(after_names["he_IL"], before_names["he_IL"])
        self.assertEqual(self.products.read(["default_code", "active"]), self.skus)

    def test_dialog_rejects_invalid_language_and_non_text_values(self):
        before = self._texts()
        for translations in ({"xx_XX": "Invalid"}, {"he_IL": {"text": "Invalid"}}, ["Invalid"]):
            with self.assertRaises(ValidationError):
                self.value.update_field_translations("mdl_name_component_value", translations)
        self.assertEqual(self._texts(), before)
