from unittest.mock import patch

from odoo.fields import Command
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..models.catalog_utils import (
    DEFAULT_VARIANT_DISPLAY_FORMAT,
    VARIANT_DISPLAY_FORMAT_PARAM,
    ltr_isolate,
)


@tagged("post_install", "-at_install")
class TestDisplayTitleIsolation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context={**cls.env.context, "lang": "en_US"})
        cls.env["ir.config_parameter"].sudo().set_param(
            VARIANT_DISPLAY_FORMAT_PARAM, DEFAULT_VARIANT_DISPLAY_FORMAT,
        )
        attribute = cls.env["product.attribute"].create({
            "name": "Configuration without name text",
            "create_variant": "always",
            "value_ids": [
                Command.create({"name": "First", "mdl_sku_component": "A"}),
                Command.create({"name": "Second", "mdl_sku_component": "B"}),
            ],
        })
        cls.template = cls.env["product.template"].create({
            "name": "Display title only",
            "mdl_catalog_managed": True,
            "mdl_model_as_attribute": True,
            "mdl_group_default_name": False,
            "mdl_group_default_sku": "TITLEISO",
            "attribute_line_ids": [Command.create({
                "attribute_id": attribute.id,
                "value_ids": [Command.set(attribute.value_ids.ids)],
            })],
        })
        cls.template.attribute_line_ids.product_template_value_ids.write({
            "mdl_name_component_override": "—",
        })
        cls.products = cls.template.product_variant_ids.sorted("id")
        cls.product, cls.sibling = cls.products
        cls.identity = {p.id: (p.default_code, p.active) for p in cls.products}

    def _assert_empty_name_displays(self, product):
        self.assertFalse(product.mdl_automatic_name)
        self.assertFalse(product.mdl_effective_name)
        self.assertFalse(product.mdl_variant_list_name)
        self.assertEqual(product.display_name, ltr_isolate(f"[{product.default_code}]"))
        self.assertEqual(
            product.with_context(formatted_display_name=True).display_name,
            f"\t--{product.default_code}--",
        )
        self.assertFalse(product.with_context(
            display_default_code=False,
            mdl_hide_default_code=True,
        ).display_name)

    def test_empty_source_and_omitted_components_do_not_use_title(self):
        for product in self.products:
            self._assert_empty_name_displays(product)
        self.template.name = "A different display title"
        self.env.flush_all()
        self.env.invalidate_all()
        for product in self.products:
            self._assert_empty_name_displays(product)
        self.assertEqual(
            {p.id: (p.default_code, p.active) for p in self.products}, self.identity,
        )

    def test_manual_variant_name_resets_to_empty_configuration(self):
        self.product.mdl_effective_name = "Explicit variant name"
        self.assertEqual(self.product.mdl_effective_name, "Explicit variant name")
        self.assertIn("Explicit variant name", self.product.display_name)
        self.assertFalse(self.product.mdl_automatic_name)
        self._assert_empty_name_displays(self.sibling)
        self.template.name = "Another independent title"
        self.assertEqual(self.product.mdl_effective_name, "Explicit variant name")
        self.product.action_mdl_reset_variant_name()
        self._assert_empty_name_displays(self.product)
        self.assertEqual(
            {p.id: (p.default_code, p.active) for p in self.products}, self.identity,
        )

    def test_empty_current_render_does_not_use_stale_generated_name(self):
        self.template.mdl_group_default_name = "Previously generated base"
        self.assertTrue(self.product.mdl_generated_name)
        # During upgrade recomputation, the live renderer is authoritative even
        # if the stored helper still contains an earlier, non-empty name.
        with patch.object(
            type(self.template), "_mdl_render_catalog_values",
            return_value=(self.product.default_code, "", []),
        ):
            self.product.invalidate_recordset([
                "mdl_automatic_name", "mdl_effective_name", "display_name",
                "mdl_variant_list_name",
            ])
            self._assert_empty_name_displays(self.product)

    def test_unmanaged_product_keeps_native_name(self):
        template = self.env["product.template"].create({
            "name": "Ordinary product title", "mdl_catalog_managed": False,
        })
        product = template.product_variant_id
        product.default_code = "ORDINARY"
        self.assertEqual(product.mdl_automatic_name, "Ordinary product title")
        self.assertIn("Ordinary product title", product.display_name)
        self.assertIn("ORDINARY", product.display_name)

    def test_supplier_context_keeps_supplier_name(self):
        supplier = self.env["res.partner"].create({"name": "Title isolation supplier"})
        self.env["product.supplierinfo"].create({
            "partner_id": supplier.id,
            "product_tmpl_id": self.template.id,
            "product_id": self.product.id,
            "product_name": "Supplier product name",
            "product_code": "SUPPLIER-ISO",
        })
        label = self.product.with_context(partner_id=supplier.id).display_name
        self.assertIn("Supplier product name", label)
        self.assertIn("SUPPLIER-ISO", label)
        self._assert_empty_name_displays(self.product)

    def test_line_suffix_translation_refreshes_each_changed_language(self):
        for lang in ("he_IL", "ar_001"):
            self.env["res.lang"]._activate_lang(lang)
        self.template.mdl_group_default_name = "Configured base"
        line = self.template.attribute_line_ids
        line.product_template_value_ids.write({"mdl_name_component_override": ""})
        line.update_field_translations("mdl_name_suffix", {
            "en_US": " old suffix", "he_IL": " סיומת עברית",
        })
        hebrew_before = self.product.with_context(lang="he_IL").mdl_generated_name
        self.assertIn("old suffix", self.product.mdl_generated_name)
        self.assertIn("old suffix", self.product.with_context(lang="ar_001").mdl_generated_name)
        self.assertIn("old suffix", self.product.mdl_effective_name)
        self.assertIn("old suffix", self.product.display_name)

        line.with_context(lang="he_IL").update_field_translations(
            "mdl_name_suffix", {"en_US": " new suffix"},
        )

        for lang in ("en_US", "ar_001"):
            product = self.product.with_context(lang=lang)
            self.assertIn("new suffix", product.mdl_generated_name)
            self.assertIn("new suffix", product.mdl_effective_name)
            self.assertIn("new suffix", product.display_name)
            self.assertIn(product, self.env["product.product"].with_context(lang=lang).search([
                ("id", "=", product.id), ("mdl_effective_name", "ilike", "new suffix"),
            ]))
        self.assertEqual(
            self.product.with_context(lang="he_IL").mdl_generated_name, hebrew_before,
        )
        self.assertEqual(
            {p.id: (p.default_code, p.active) for p in self.products}, self.identity,
        )
        self.assertEqual(self.template.name, "Display title only")

    def test_blank_english_generation_preserves_other_stored_names(self):
        self.env["res.lang"]._activate_lang("he_IL")
        self.template.update_field_translations("mdl_group_default_name", {
            "en_US": "", "he_IL": "שם מוצר בעברית",
        })
        hebrew = self.product.with_context(lang="he_IL")
        self.assertEqual(hebrew.mdl_generated_name, "שם מוצר בעברית")
        self.product._compute_mdl_catalog_values()
        self.product.flush_recordset(["mdl_generated_name"])
        self.env.invalidate_all()
        self.assertFalse(self.product.mdl_generated_name)
        self.assertEqual(hebrew.mdl_generated_name, "שם מוצר בעברית")
        self.assertEqual(hebrew.mdl_effective_name, "שם מוצר בעברית")
        self.assertIn(hebrew, self.env["product.product"].with_context(lang="he_IL").search([
            ("id", "=", hebrew.id), ("mdl_effective_name", "=", "שם מוצר בעברית"),
        ]))
        self.assertEqual(
            {p.id: (p.default_code, p.active) for p in self.products}, self.identity,
        )

    def test_copy_retains_blank_current_and_inactive_name_translations(self):
        for lang in ("he_IL", "fr_FR"):
            self.env["res.lang"]._activate_lang(lang)
        self.template.update_field_translations("mdl_group_default_name", {
            "en_US": "", "he_IL": "בסיס עברי", "fr_FR": "Base française",
        })
        self.template.update_field_translations("mdl_name_suffix", {
            "en_US": "", "he_IL": " סיומת", "fr_FR": " suffixe",
        })
        source_line = self.template.attribute_line_ids
        source_line.update_field_translations("mdl_name_suffix", {
            "en_US": "", "he_IL": "/עברית/", "fr_FR": "/français/",
        })
        source_value = self.product.product_template_attribute_value_ids
        source_value.update_field_translations("mdl_name_component_override", {
            "en_US": "", "he_IL": "טקסט קבוצה", "fr_FR": "Texte du groupe",
        })
        self.env["res.lang"].search([("code", "=", "fr_FR")]).active = False
        copied = self.template.copy({"name": "Independent copied title"})
        self.assertEqual(copied.name, "Independent copied title")
        self.assertFalse(copied.mdl_group_default_name)
        self.assertTrue(copied.mdl_copy_requires_new_sku)
        self.assertTrue(all(not product.default_code for product in copied.product_variant_ids))
        target_line = copied.attribute_line_ids
        target_value = target_line.product_template_value_ids.filtered(
            lambda value: value.product_attribute_value_id == source_value.product_attribute_value_id
        )
        for source, target, field_name in (
            (self.template, copied, "mdl_group_default_name"),
            (self.template, copied, "mdl_name_suffix"),
            (source_line, target_line, "mdl_name_suffix"),
            (source_value, target_value, "mdl_name_component_override"),
        ):
            expected = source._fields[field_name]._get_stored_translations(source)
            actual = target._fields[field_name]._get_stored_translations(target)
            self.assertIn("fr_FR", expected)
            self.assertEqual(actual, expected)
        source_names = set(self.products.with_context(lang="he_IL").mapped("mdl_generated_name"))
        self.assertEqual(
            set(copied.product_variant_ids.with_context(lang="he_IL").mapped("mdl_generated_name")),
            source_names,
        )
        self.assertEqual(
            {p.id: (p.default_code, p.active) for p in self.products}, self.identity,
        )

    def test_copy_explicit_lower_name_is_not_replaced_by_source_translations(self):
        self.env["res.lang"]._activate_lang("he_IL")
        self.template.update_field_translations("mdl_group_default_name", {
            "en_US": "", "he_IL": "שם מקור בעברית",
        })
        copied = self.template.copy({
            "name": "Separate display title",
            "mdl_group_default_name": "Explicit new naming base",
        })
        self.assertEqual(copied.name, "Separate display title")
        self.assertEqual(copied.mdl_group_default_name, "Explicit new naming base")
        self.assertEqual(
            copied.with_context(lang="he_IL").mdl_group_default_name,
            "Explicit new naming base",
        )
        self.assertTrue(all(not product.default_code for product in copied.product_variant_ids))

    def test_group_name_english_edit_refreshes_inherited_languages(self):
        for lang in ("he_IL", "ar_001"):
            self.env["res.lang"]._activate_lang(lang)
        self.template.update_field_translations("mdl_group_default_name", {
            "en_US": "Old group base", "he_IL": "בסיס עברי",
        })
        hebrew_before = self.product.with_context(lang="he_IL").mdl_generated_name
        arabic = self.product.with_context(lang="ar_001")
        self.assertEqual(arabic.mdl_generated_name, "Old group base")
        self.assertIn("Old group base", arabic.display_name)
        self.assertEqual(arabic.mdl_effective_name, "Old group base")

        self.template.with_context(lang="he_IL").update_field_translations(
            "mdl_group_default_name", {"en_US": "New group base"},
        )

        for lang in ("en_US", "ar_001"):
            product = self.product.with_context(lang=lang)
            self.assertEqual(product.mdl_generated_name, "New group base")
            self.assertEqual(product.mdl_effective_name, "New group base")
            self.assertIn("New group base", product.display_name)
            self.assertIn(product, self.env["product.product"].with_context(lang=lang).search([
                ("id", "=", product.id), ("mdl_effective_name", "=", "New group base"),
            ]))
        self.assertEqual(
            self.product.with_context(lang="he_IL").mdl_generated_name, hebrew_before,
        )
        self.assertEqual(self.template.name, "Display title only")
        self.assertEqual(
            {p.id: (p.default_code, p.active) for p in self.products}, self.identity,
        )

    def test_attribute_name_english_edit_refreshes_inherited_languages(self):
        for lang in ("he_IL", "ar_001"):
            self.env["res.lang"]._activate_lang(lang)
        self.template.mdl_group_default_name = "Base"
        self.template.attribute_line_ids.product_template_value_ids.write({
            "mdl_name_component_override": "",
        })
        source_value = self.product.product_template_attribute_value_ids.product_attribute_value_id
        source_value.update_field_translations("name", {
            "en_US": "Old part", "he_IL": "חלק בעברית",
        })
        sibling_before = {
            lang: self.sibling.with_context(lang=lang).mdl_generated_name
            for lang in ("en_US", "he_IL", "ar_001")
        }
        hebrew_before = self.product.with_context(lang="he_IL").mdl_generated_name
        arabic = self.product.with_context(lang="ar_001")
        self.assertEqual(arabic.mdl_generated_name, "Base Old part")
        self.assertIn("Old part", arabic.display_name)
        self.assertIn("Old part", arabic.mdl_effective_name)

        source_value.with_context(lang="he_IL").update_field_translations(
            "name", {"en_US": "New part"},
        )

        for lang in ("en_US", "ar_001"):
            product = self.product.with_context(lang=lang)
            self.assertEqual(product.mdl_generated_name, "Base New part")
            self.assertEqual(product.mdl_effective_name, "Base New part")
            self.assertIn("New part", product.display_name)
            self.assertIn(product, self.env["product.product"].with_context(lang=lang).search([
                ("id", "=", product.id), ("mdl_effective_name", "ilike", "New part"),
            ]))
        self.assertEqual(
            self.product.with_context(lang="he_IL").mdl_generated_name, hebrew_before,
        )
        self.assertEqual(
            {
                lang: self.sibling.with_context(lang=lang).mdl_generated_name
                for lang in sibling_before
            },
            sibling_before,
        )
        self.assertEqual(
            {p.id: (p.default_code, p.active) for p in self.products}, self.identity,
        )

    def test_template_suffix_whitespace_edit_refreshes_inherited_languages(self):
        for lang in ("he_IL", "ar_001"):
            self.env["res.lang"]._activate_lang(lang)
        self.template.mdl_group_default_name = "Base"
        self.template.update_field_translations("mdl_name_suffix", {
            "en_US": "suffix", "he_IL": " סיומת בעברית",
        })
        hebrew_before = self.product.with_context(lang="he_IL").mdl_generated_name
        self.assertEqual(self.product.mdl_generated_name, "Basesuffix")
        arabic = self.product.with_context(lang="ar_001")
        self.assertEqual(arabic.mdl_generated_name, "Basesuffix")
        self.assertIn("Basesuffix", arabic.display_name)

        self.template.with_context(lang="he_IL").update_field_translations(
            "mdl_name_suffix", {"en_US": " suffix"},
        )

        for lang in ("en_US", "ar_001"):
            product = self.product.with_context(lang=lang)
            self.assertEqual(product.mdl_generated_name, "Base suffix")
            self.assertEqual(product.mdl_effective_name, "Base suffix")
            self.assertIn("Base suffix", product.display_name)
            self.assertIn(product, self.env["product.product"].with_context(lang=lang).search([
                ("id", "=", product.id), ("mdl_effective_name", "=", "Base suffix"),
            ]))
        self.assertEqual(
            self.product.with_context(lang="he_IL").mdl_generated_name, hebrew_before,
        )
        self.assertEqual(self.template.name, "Display title only")
        self.assertEqual(
            {p.id: (p.default_code, p.active) for p in self.products}, self.identity,
        )

    def _check_direct_english_name_write(self, record, field_name, old_text, new_text):
        for lang in ("he_IL", "ar_001"):
            self.env["res.lang"]._activate_lang(lang)
        self.template.mdl_group_default_name = "Configured base"
        self.template.attribute_line_ids.product_template_value_ids.write({
            "mdl_name_component_override": "",
        })
        record.update_field_translations(field_name, {
            "en_US": old_text, "he_IL": " טקסט עברי",
        })
        self.sibling.with_context(lang="he_IL").mdl_effective_name = "שם פריט מפורש"
        hebrew_names = {
            product.id: (product.mdl_generated_name, product.mdl_effective_name)
            for product in self.products.with_context(lang="he_IL")
        }
        titles = {
            lang: self.template.with_context(lang=lang).name
            for lang in ("en_US", "he_IL", "ar_001")
        }
        # Materialize the English fallback before the ordinary form/write path.
        arabic = self.product.with_context(lang="ar_001")
        self.assertIn(old_text.strip(), arabic.mdl_generated_name)
        # Consecutive edits in one transaction must not reuse the first edit's
        # cached fallback when refreshing the final translated search name.
        record.write({field_name: new_text + " intermediate"})
        record.write({field_name: new_text})
        self.env.flush_all()
        self.env.invalidate_all()
        for lang in ("en_US", "ar_001"):
            product = self.product.with_context(lang=lang)
            self.assertIn(new_text.strip(), product.mdl_generated_name)
            self.assertEqual(product.mdl_generated_name, product.mdl_automatic_name)
            self.assertIn(new_text.strip(), product.mdl_effective_name)
            self.assertIn(new_text.strip(), product.display_name)
            for name in (product.mdl_generated_name, product.mdl_effective_name, product.display_name):
                self.assertNotIn(" intermediate", name)
            self.assertIn(product, self.env["product.product"].with_context(lang=lang).search([
                ("id", "=", product.id), ("mdl_effective_name", "ilike", new_text.strip()),
            ]))
            self.assertFalse(self.env["product.product"].with_context(lang=lang).search([
                ("id", "=", product.id), ("mdl_effective_name", "ilike", " intermediate"),
            ]))
        self.assertEqual({
            product.id: (product.mdl_generated_name, product.mdl_effective_name)
            for product in self.products.with_context(lang="he_IL")
        }, hebrew_names)
        self.assertEqual({
            lang: self.template.with_context(lang=lang).name for lang in titles
        }, titles)
        self.assertEqual(
            {p.id: (p.default_code, p.active) for p in self.products}, self.identity,
        )

    def test_direct_group_name_write_refreshes_inherited_language_search(self):
        self._check_direct_english_name_write(
            self.template, "mdl_group_default_name", "Old group base", "New group base",
        )

    def test_direct_attribute_name_write_refreshes_inherited_language_search(self):
        self._check_direct_english_name_write(
            self.product.product_template_attribute_value_ids.product_attribute_value_id,
            "name", "Old attribute text", "New attribute text",
        )

    def test_direct_final_suffix_write_refreshes_inherited_language_search(self):
        self._check_direct_english_name_write(
            self.template, "mdl_name_suffix", " old final text", " new final text",
        )

    def test_direct_row_suffix_write_refreshes_inherited_language_search(self):
        self._check_direct_english_name_write(
            self.template.attribute_line_ids, "mdl_name_suffix", " old row text", " new row text",
        )
