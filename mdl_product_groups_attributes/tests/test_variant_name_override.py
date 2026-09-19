from lxml import etree

from odoo.exceptions import AccessError, ValidationError
from odoo.fields import Command
from odoo.tests import Form, tagged
from odoo.tests.common import TransactionCase
from odoo.tools.safe_eval import safe_eval


@tagged("post_install", "-at_install")
class TestVariantNameOverride(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context={**cls.env.context, "lang": "en_US"})
        cls.env.user.group_ids |= cls.env.ref("product.group_product_variant")
        for lang in ("en_US", "he_IL", "ar_001"):
            cls.env["res.lang"]._activate_lang(lang)
        category = cls.env["product.category"].create({
            "name": "Override test doors", "mdl_sku_component": "OVR",
        })
        attribute = cls.env["product.attribute"].create({
            "name": "Size", "create_variant": "always",
            "value_ids": [
                Command.create({"name": "Small", "mdl_sku_component": "S"}),
                Command.create({"name": "Large", "mdl_sku_component": "L"}),
            ],
        })
        cls.template = cls.env["product.template"].create({
            "name": "Door", "categ_id": category.id,
            "mdl_catalog_managed": True, "mdl_model_sku_component": "N",
            "mdl_group_default_name": "Door",
            "attribute_line_ids": [Command.create({
                "attribute_id": attribute.id,
                "value_ids": [Command.set(attribute.value_ids.ids)],
            })],
        })
        cls.template.update_field_translations("mdl_group_default_name", {
            "en_US": "Door", "he_IL": "דלת", "ar_001": "باب",
        })
        cls.variant, cls.sibling = cls.template.product_variant_ids.sorted("id")
        cls.skus = {p.id: p.default_code for p in cls.template.product_variant_ids}

    def test_language_isolation_and_reset_through_form_write(self):
        p = self.variant
        automatic = {lang: p.with_context(lang=lang).mdl_automatic_name for lang in ("en_US", "he_IL", "ar_001")}
        p.mdl_name_override = "Custom English"
        p.with_context(lang="he_IL").mdl_name_override = "שם מותאם בעברית"
        self.assertEqual(p.mdl_effective_name, "Custom English")
        self.assertEqual(p.with_context(lang="he_IL").mdl_effective_name, "שם מותאם בעברית")
        self.assertFalse(p.with_context(lang="ar_001").mdl_name_override)
        self.assertEqual(p.with_context(lang="ar_001").mdl_effective_name, automatic["ar_001"])
        self.assertFalse(self.sibling.mdl_name_overrides)
        p.with_context(lang="he_IL").mdl_name_override = False
        self.assertEqual(p.with_context(lang="he_IL").mdl_effective_name, automatic["he_IL"])
        self.assertEqual(p.mdl_effective_name, "Custom English")
        p.mdl_name_override = " \n\t "
        self.assertEqual(p.mdl_effective_name, automatic["en_US"])
        self.assertFalse(p.mdl_name_overrides)
        self.assertEqual({p.id: p.default_code for p in self.template.product_variant_ids}, self.skus)

    def test_native_language_dialog_handles_empty_base_and_partial_updates(self):
        p = self.variant
        self.assertTrue(p.update_field_translations("mdl_name_override", {"he_IL": "שם עברי"}))
        rows, context = p.get_field_translations("mdl_name_override")
        values = {row["lang"]: row["value"] for row in rows}
        self.assertEqual(values["en_US"], "")
        self.assertEqual(values["he_IL"], "שם עברי")
        self.assertEqual(values["ar_001"], "")
        self.assertEqual(context, {"translation_type": "char", "translation_show_source": False})
        p.update_field_translations("mdl_name_override", {"en_US": "English name", "ar_001": "اسم خاص"})
        p.update_field_translations("mdl_name_override", {"en_US": False})
        self.assertFalse(p.mdl_name_override)
        self.assertEqual(p.with_context(lang="he_IL").mdl_name_override, "שם עברי")
        self.assertEqual(p.with_context(lang="ar_001").mdl_name_override, "اسم خاص")
        p.update_field_translations("mdl_name_override", {})
        p.invalidate_recordset()
        self.assertEqual(p.with_context(lang="he_IL").mdl_name_override, "שם עברי")
        self.assertFalse(p.mdl_name_override)

    def test_newly_activated_language_does_not_inherit_override(self):
        self.variant.mdl_name_override = "English only"
        self.env["res.lang"]._activate_lang("fr_FR")
        french = self.variant.with_context(lang="fr_FR")
        self.assertFalse(french.mdl_name_override)
        self.assertEqual(french.mdl_effective_name, french.mdl_automatic_name)

    def test_display_list_search_and_reload_follow_current_override(self):
        p = self.variant
        # Prime caches before editing, including another language.
        _ = p.display_name, p.mdl_variant_list_name, p.with_context(lang="he_IL").display_name
        p.update_field_translations("mdl_name_override", {"en_US": "OVR unique English", "he_IL": "שם ייחודי לבדיקה"})
        self.assertEqual(p.mdl_variant_list_name, "OVR unique English")
        self.assertEqual(p.with_context(lang="he_IL").mdl_variant_list_name, "שם ייחודי לבדיקה")
        self.assertIn("OVR unique English", p.display_name)
        self.assertEqual(p.with_context(formatted_display_name=True).display_name, f"OVR unique English\t--{p.default_code}--")
        Products = self.env["product.product"]
        self.assertEqual(Products.search([("mdl_effective_name", "=", "OVR unique English")]), p)
        self.assertEqual(Products.search([("display_name", "ilike", "OVR unique English")]), p)
        self.assertIn(p.id, dict(Products.name_search("OVR unique English")))
        search_view = p.get_view(view_id=self.env.ref("product.product_search_form_view").id, view_type="search")
        node = etree.fromstring(search_view["arch"]).xpath("//field[@name='name']")[0]
        self.assertEqual(Products.search(safe_eval(node.get("filter_domain"), {"self": "OVR unique English"})), p)
        self.assertIn(self.template.id, dict(self.env["product.template"].name_search("OVR unique English")))
        self.assertFalse(Products.with_context(lang="he_IL").search([("mdl_effective_name", "ilike", "OVR unique English")]))
        self.assertNotIn(p, Products.search([("mdl_effective_name", "not ilike", "OVR unique English")]))
        p.invalidate_recordset()
        self.assertEqual(p.mdl_variant_list_name, "OVR unique English")
        p.update_field_translations("mdl_name_override", {"en_US": False})
        self.assertEqual(p.mdl_variant_list_name, p.mdl_automatic_name)
        self.assertFalse(Products.search([("mdl_effective_name", "=", "OVR unique English")]))

    def test_source_changes_preserve_override_and_reset_uses_new_automatic_name(self):
        p = self.variant
        p.mdl_name_override = "Keep this name"
        self.template.mdl_group_default_name = "Updated automatic group"
        self.assertEqual(p.mdl_effective_name, "Keep this name")
        self.assertIn("Updated automatic group", p.mdl_automatic_name)
        p.mdl_name_override = False
        self.assertEqual(p.mdl_effective_name, p.mdl_automatic_name)
        self.assertEqual(p.default_code, self.skus[p.id])

    def test_customer_language_is_used_for_new_sale_description(self):
        self.variant.update_field_translations("mdl_name_override", {"en_US": "English sales name", "he_IL": "שם להצעת מחיר"})
        customer = self.env["res.partner"].create({"name": "Override test customer", "lang": "he_IL"})
        order = self.env["sale.order"].create({"partner_id": customer.id})
        line = self.env["sale.order.line"].create({"order_id": order.id, "product_id": self.variant.id, "product_uom_qty": 1})
        self.assertIn("שם להצעת מחיר", line.name)
        self.assertNotIn("English sales name", line.name)
        # Renaming a product alone must not rewrite an existing document.
        description = line.name
        self.variant.update_field_translations("mdl_name_override", {"he_IL": "שם חדש לעתיד"})
        self.assertEqual(line.name, description)

    def test_full_form_exposes_editable_translatable_title(self):
        for view_xmlid in ("product.product_normal_form_view", "product.product_variant_easy_edit_view"):
            result = self.variant.get_view(view_id=self.env.ref(view_xmlid).id, view_type="form")
            arch = etree.fromstring(result["arch"])
            node = arch.xpath("//div[contains(@class, 'oe_title')]//field[@name='mdl_effective_name']")[0]
            self.assertFalse(safe_eval(node.get("readonly", "False"), {"id": self.variant.id}))
            self.assertFalse(arch.xpath("//field[@name='mdl_name_override']"))
            automatic = arch.xpath("//field[@name='mdl_automatic_name']")[0]
            self.assertTrue(safe_eval(automatic.get("invisible", "False")))
            button = arch.xpath("//div[contains(@class, 'oe_title')]//button[@name='action_mdl_reset_variant_name']")[0]
            for title, expected in (("Automatic", True), ("Custom", False)):
                self.assertEqual(safe_eval(button.get("invisible"), {
                    "mdl_effective_name": title, "mdl_automatic_name": "Automatic",
                }), expected)
            with Form(self.variant, view=view_xmlid) as form:
                form.mdl_effective_name = "Name entered in form"
            self.assertEqual(self.variant.mdl_effective_name, "Name entered in form")
            self.variant.action_mdl_reset_variant_name()
        self.assertTrue(self.variant._fields["mdl_effective_name"].translate)

    def test_title_edit_and_undo_preserve_other_languages_and_siblings(self):
        p = self.variant
        p.mdl_effective_name = "Custom English title"
        hebrew = p.with_context(lang="he_IL")
        hebrew.mdl_effective_name = "כותרת בעברית"
        self.assertEqual(p.mdl_effective_name, "Custom English title")
        self.assertEqual(hebrew.mdl_effective_name, "כותרת בעברית")
        self.template.mdl_group_default_name = "New automatic group"
        hebrew.action_mdl_reset_variant_name()
        self.assertEqual(hebrew.mdl_effective_name, hebrew.mdl_automatic_name)
        self.assertEqual(p.mdl_effective_name, "Custom English title")
        p.mdl_effective_name = p.mdl_automatic_name
        self.assertFalse(p.mdl_name_override)
        p.mdl_effective_name = "Temporary title"
        p.mdl_effective_name = False
        self.assertEqual(p.mdl_effective_name, p.mdl_automatic_name)
        self.assertFalse(p.mdl_name_overrides)
        self.assertFalse(self.sibling.mdl_name_overrides)
        self.assertEqual({p.id: p.default_code for p in self.template.product_variant_ids}, self.skus)

    def test_title_edit_does_not_rename_template_or_sibling(self):
        template_name = self.template.name
        sibling_name = self.sibling.mdl_effective_name
        self.variant.mdl_effective_name = "Only this variant"
        self.assertEqual(self.template.name, template_name)
        self.assertEqual(self.sibling.mdl_effective_name, sibling_name)

    def test_title_translation_dialog_normalizes_automatic_names(self):
        p = self.variant
        rows, _context = p.get_field_translations("mdl_effective_name")
        values = {row["lang"]: row["value"] for row in rows}
        for lang, value in values.items():
            self.assertEqual(value, p.with_context(lang=lang).mdl_automatic_name)
        p.update_field_translations("mdl_effective_name", values)
        self.assertFalse(p.mdl_name_overrides)
        p.update_field_translations("mdl_effective_name", {
            "en_US": "English title", "he_IL": "כותרת מתורגמת",
        })
        p.update_field_translations("mdl_effective_name", {"he_IL": False})
        p.invalidate_recordset()
        self.assertEqual(p.mdl_effective_name, "English title")
        self.assertEqual(p.with_context(lang="he_IL").mdl_effective_name,
                         p.with_context(lang="he_IL").mdl_automatic_name)
        public = p.with_user(self.env.ref("base.public_user"))
        with self.assertRaises(AccessError):
            public.action_mdl_reset_variant_name()
        with self.assertRaises(AccessError):
            public.update_field_translations("mdl_effective_name", {"en_US": "Forbidden"})

    def test_translation_access_and_input_validation(self):
        public = self.variant.with_user(self.env.ref("base.public_user"))
        with self.assertRaises(AccessError):
            public.update_field_translations("mdl_name_override", {"en_US": "Not allowed"})
        with self.assertRaises(AccessError):
            public.get_field_translations("mdl_name_override")
        with self.assertRaises(ValidationError):
            self.variant.update_field_translations("mdl_name_override", {"xx_XX": "Invalid language"})
        with self.assertRaises(ValidationError):
            self.variant.update_field_translations("mdl_name_override", {"en_US": {"term": "Invalid type"}})

    def test_archive_and_copy_do_not_leak_overrides(self):
        p = self.variant
        p.mdl_name_override = "Archived custom name"
        p.active = False
        p.active = True
        self.assertEqual(p.mdl_effective_name, "Archived custom name")
        copied = p.copy_data()[0]
        self.assertNotIn("mdl_name_overrides", copied)
        self.assertNotIn("mdl_name_override", copied)
