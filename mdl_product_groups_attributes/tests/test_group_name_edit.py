from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tests import Form, tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestGroupNameEdit(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context={**cls.env.context, "lang": "en_US"})
        cls.env.user.group_ids |= cls.env.ref("product.group_product_variant")
        for lang in ("en_US", "he_IL", "ar_001"):
            cls.env["res.lang"]._activate_lang(lang)
        category = cls.env["product.category"].create({
            "name": "Window", "mdl_sku_component": "REN",
        })
        attribute = cls.env["product.attribute"].create({
            "name": "Width", "create_variant": "always",
            "value_ids": [
                Command.create({"name": "80", "mdl_sku_component": "80"}),
                Command.create({"name": "100", "mdl_sku_component": "100"}),
            ],
        })
        cls.template = cls.env["product.template"].create({
            "name": "Window", "categ_id": category.id,
            "mdl_catalog_managed": True, "mdl_model_as_attribute": True,
            "mdl_group_default_name": "Window",
            "mdl_group_name_override": "Legacy window",
            "attribute_line_ids": [Command.create({
                "attribute_id": attribute.id,
                "value_ids": [Command.set(attribute.value_ids.ids)],
            })],
        })
        # Reproduce historical group translations without applying edit logic.
        historical = cls.template.with_context(skip_mdl_catalog_sync=True)
        historical.update_field_translations("mdl_group_default_name", {
            "en_US": "Window", "he_IL": "חלון נגרר", "ar_001": "نافذة منزلقة",
        })
        historical.update_field_translations("mdl_group_name_override", {
            "en_US": "Legacy window", "he_IL": "חלון", "ar_001": "نافذة",
        })
        historical.update_field_translations("name", {
            "en_US": "Window", "he_IL": "חלון נגרר", "ar_001": "نافذة منزلقة",
        })
        historical.update_field_translations("mdl_native_name_override", {
            "en_US": "", "he_IL": "", "ar_001": "",
        })
        # Seed the stored generated names as they existed before this edit.
        # The historical import above intentionally skipped recomputation.
        for lang in ("en_US", "he_IL", "ar_001"):
            translated = cls.template.with_context(lang=lang)
            translated.env.add_to_compute(translated._fields["mdl_effective_base_name"], translated)
            translated._recompute_recordset(["mdl_effective_base_name"])
            translated._mdl_sync_variant_codes()
        cls.products = cls.template.product_variant_ids.sorted("id")
        cls.identity = {p.id: (p.default_code, p.active) for p in cls.products}

    def _snapshot(self, lang):
        template = self.template.with_context(lang=lang)
        return (
            template.name, template.mdl_group_default_name,
            template.mdl_group_name_override,
            tuple(self.products.with_context(lang=lang).mapped("mdl_effective_name")),
        )

    def _assert_names(self, lang, prefix):
        template = self.template.with_context(lang=lang)
        self.assertFalse(template.mdl_group_name_override)
        self.assertEqual(template.mdl_effective_base_name, prefix)
        self.env.flush_all()
        self.env.invalidate_all()
        for product in self.products.with_context(lang=lang):
            self.assertTrue(product.mdl_automatic_name.startswith(prefix + " "))
            self.assertEqual(product.mdl_generated_name, product.mdl_automatic_name)
            self.assertEqual(product.mdl_variant_list_name, product.mdl_effective_name)
            self.assertIn(product.mdl_effective_name, product.display_name)
        self.assertEqual({p.id: (p.default_code, p.active) for p in self.products}, self.identity)

    def test_group_write_updates_variants_in_edited_language_only(self):
        english, hebrew = self._snapshot("en_US"), self._snapshot("he_IL")
        self.template.with_context(lang="ar_001").write({"mdl_group_default_name": "شباك"})
        self._assert_names("ar_001", "شباك")
        self.assertEqual(self.template.with_context(lang="ar_001").name, "شباك")
        self.assertEqual(self._snapshot("en_US"), english)
        self.assertEqual(self._snapshot("he_IL"), hebrew)

    def test_group_form_edit_clears_stale_title_and_group_overrides(self):
        self.template.write({"name": "Old manual title"})
        hebrew, arabic = self._snapshot("he_IL"), self._snapshot("ar_001")
        with Form(self.template, view="product.product_template_only_form_view") as form:
            form.mdl_group_default_name = "Renamed window"
        self._assert_names("en_US", "Renamed window")
        self.assertEqual(self.template.name, "Renamed window")
        self.assertFalse(self.template.mdl_native_name_override)
        self.assertEqual(self._snapshot("he_IL"), hebrew)
        self.assertEqual(self._snapshot("ar_001"), arabic)

    def test_translation_dialog_updates_only_changed_language(self):
        english, hebrew = self._snapshot("en_US"), self._snapshot("he_IL")
        self.assertTrue(self.template.update_field_translations("mdl_group_default_name", {
            "en_US": "Window", "he_IL": "חלון נגרר", "ar_001": "شباك",
        }))
        self._assert_names("ar_001", "شباك")
        self.assertEqual(self._snapshot("en_US"), english)
        self.assertEqual(self._snapshot("he_IL"), hebrew)

    def test_multiple_translations_preserve_manual_variant_name(self):
        hebrew = self._snapshot("he_IL")
        manual = self.products[0].with_context(lang="ar_001")
        manual.mdl_effective_name = "اسم خاص"
        self.template.update_field_translations("mdl_group_default_name", {
            "en_US": "New window", "ar_001": "شباك",
        })
        self._assert_names("en_US", "New window")
        self._assert_names("ar_001", "شباك")
        self.assertEqual(manual.mdl_effective_name, "اسم خاص")
        manual.action_mdl_reset_variant_name()
        self.assertEqual(manual.mdl_effective_name, manual.mdl_automatic_name)
        self.assertEqual(self._snapshot("he_IL"), hebrew)

    def test_unchanged_translation_dialog_keeps_existing_overrides(self):
        before = {lang: self._snapshot(lang) for lang in ("en_US", "he_IL", "ar_001")}
        self.template.update_field_translations("mdl_group_default_name", {
            "en_US": "Window", "he_IL": "חלון נגרר", "ar_001": "نافذة منزلقة",
        })
        self.assertEqual({lang: self._snapshot(lang) for lang in before}, before)

    def test_group_rename_updates_archived_variants_without_reactivation(self):
        self.products[0].active = False
        self.identity = {p.id: (p.default_code, p.active) for p in self.products}
        self.template.with_context(lang="ar_001").write({"mdl_group_default_name": "شباك"})
        self._assert_names("ar_001", "شباك")
        self.assertFalse(self.products[0].active)

    def test_translation_edit_preserves_legacy_model_suffix(self):
        template = self.env["product.template"].create({
            "name": "Panel", "mdl_catalog_managed": True,
            "mdl_group_default_name": "Window", "mdl_group_default_sku": "RENP",
            "mdl_group_name_override": "Legacy window",
        })
        self.assertEqual(template.name, "Window Panel")
        template.update_field_translations("mdl_group_default_name", {"en_US": "Door"})
        self.assertEqual(template.name, "Door Panel")
        self.assertEqual(template.mdl_effective_base_name, "Door Panel")

    def test_explicit_override_and_internal_sync_remain_supported(self):
        self.template.write({
            "mdl_group_default_name": "New source", "mdl_group_name_override": "Explicit name",
        })
        self.assertEqual(self.template.mdl_effective_base_name, "Explicit name")
        self.template.with_context(skip_mdl_catalog_sync=True).write({"mdl_group_default_name": "Imported source"})
        self.assertEqual(self.template.mdl_group_name_override, "Explicit name")

    def test_invalid_translation_language_does_not_change_names(self):
        before = self._snapshot("en_US")
        with self.assertRaises(UserError):
            self.template.update_field_translations("mdl_group_default_name", {"xx_YY": "Invalid"})
        self.assertEqual(self._snapshot("en_US"), before)
