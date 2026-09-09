from lxml import etree

from odoo.fields import Command
from odoo.tests import Form, tagged
from odoo.tests.common import TransactionCase
from odoo.tools.safe_eval import safe_eval


@tagged("post_install", "-at_install")
class TestNameOverridesUI(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context={**cls.env.context, "lang": "en_US"})
        cls.env.user.group_ids |= cls.env.ref("product.group_product_variant")
        for lang in ("en_US", "he_IL", "ar_001"):
            cls.env["res.lang"]._activate_lang(lang)
        category = cls.env["product.category"].create({
            "name": "Window", "mdl_sku_component": "UIR",
        })
        attribute = cls.env["product.attribute"].create({
            "name": "Width", "create_variant": "always",
            "value_ids": [
                Command.create({"name": "80", "mdl_sku_component": "80"}),
                Command.create({"name": "100", "mdl_sku_component": "100"}),
            ],
        })
        cls.template = cls.env["product.template"].create({
            "name": "Panel", "categ_id": category.id,
            "mdl_catalog_managed": True, "mdl_model_sku_component": "P",
            "attribute_line_ids": [Command.create({
                "attribute_id": attribute.id,
                "value_ids": [Command.set(attribute.value_ids.ids)],
            })],
        })
        for lang, group, model, custom_group, custom_model in [
            ("en_US", "Window", "Panel", "Old window", "Old panel"),
            ("he_IL", "חלון", "כנף", "חלון מותאם", "כנף מותאמת"),
            ("ar_001", "شباك", "ضلفة", "شباك مخصص", "ضلفة مخصصة"),
        ]:
            translated = cls.template.with_context(lang=lang)
            translated.with_context(skip_mdl_catalog_sync=True).write({
                "name": group + " " + model, "mdl_group_default_name": group,
                "mdl_group_name_override": custom_group,
                "mdl_model_name_override": custom_model,
                "mdl_native_name_override": "", "mdl_native_name_source": "",
            })
            translated.env.add_to_compute(translated._fields["mdl_effective_base_name"], translated)
            translated._recompute_recordset(["mdl_effective_base_name"])
            translated._mdl_sync_variant_codes()
        cls.products = cls.template.product_variant_ids.sorted("id")
        cls.skus = cls.products.read(["default_code", "active"])

    def _names(self, lang):
        return (
            self.template.with_context(lang=lang).name,
            tuple(self.products.with_context(lang=lang).mapped("mdl_effective_name")),
        )

    def test_settings_action_opens_current_record_and_language(self):
        action = self.template.with_context(lang="ar_001").action_mdl_open_name_sku_overrides()
        self.assertEqual(action["res_id"], self.template.id)
        self.assertEqual(action["res_model"], "product.template")
        self.assertEqual(action["context"]["lang"], "ar_001")
        self.assertEqual(action["target"], "new")
        view = self.template.get_view(view_id=action["views"][0][0], view_type="form")
        arch = etree.fromstring(view["arch"])
        for field in ("name", "mdl_group_name_override", "mdl_group_sku_override", "mdl_model_name_override", "mdl_model_sku_override", "mdl_name_suffix"):
            node = arch.xpath("//field[@name='%s']" % field)[0]
            self.assertNotEqual(node.get("readonly"), "1")
            self.assertNotEqual(node.get("invisible"), "1")
        self.assertTrue(arch.xpath("//button[@special='cancel']"))

    def test_all_component_overrides_can_be_edited_and_cleared_in_form(self):
        view = "mdl_product_groups_attributes.mdl_product_template_name_sku_form"
        ids = self.products.ids
        with Form(self.template, view=view) as form:
            form.mdl_group_name_override = "Edited group"
            form.mdl_model_name_override = "Edited model"
            form.mdl_group_sku_override = "UIEDIT"
            form.mdl_model_sku_override = "99"
        self.assertEqual(self.template.mdl_effective_base_name, "Edited group Edited model")
        self.assertTrue(all(p.default_code.startswith("UIEDIT99") for p in self.products))
        with Form(self.template, view=view) as form:
            form.mdl_group_name_override = False
            form.mdl_model_name_override = False
            form.mdl_group_sku_override = False
            form.mdl_model_sku_override = False
        self.assertEqual(self.template.mdl_effective_base_name, "Window Panel")
        self.assertEqual(self.products.read(["default_code", "active"]), self.skus)
        self.assertEqual(self.products.ids, ids)

    def test_template_title_has_undo_and_keeps_native_width(self):
        view = self.template.get_view(view_id=self.env.ref("product.product_template_only_form_view").id, view_type="form")
        arch = etree.fromstring(view["arch"])
        title = arch.xpath("//div[contains(@class, 'oe_title')]")[0]
        button = title.xpath(".//button[@name='action_mdl_reset_base_name']")[0]
        self.assertTrue(title.xpath(".//div[contains(@class, 'o_mdl_variant_name')]/field[@name='name' and contains(@class, 'flex-grow-1')]"))
        self.assertFalse(safe_eval(button.get("invisible"), {
            "mdl_catalog_managed": True, "mdl_model_as_attribute": False,
            "mdl_native_name_override": "", "mdl_group_name_override": "Old name", "mdl_model_name_override": "",
        }))
        with Form(self.template, view="product.product_template_only_form_view") as form:
            form.name = "Shared manual name"
        self.assertTrue(all(p.mdl_effective_name.startswith("Shared manual name ") for p in self.products))
        self.template.action_mdl_reset_base_name()
        self.assertEqual(self.template.name, "Window Panel")
        self.assertTrue(all(p.mdl_effective_name.startswith("Window Panel ") for p in self.products))
        self.assertEqual(self.products.read(["default_code", "active"]), self.skus)

    def test_group_and_model_override_translation_dialog_is_language_scoped(self):
        before = {lang: self._names(lang) for lang in ("en_US", "he_IL")}
        self.template.update_field_translations("mdl_group_name_override", {"ar_001": "نافذة"})
        self.template.update_field_translations("mdl_model_name_override", {"ar_001": "جديدة"})
        self.env.flush_all()
        self.env.invalidate_all()
        arabic = self.template.with_context(lang="ar_001")
        names = self.products.with_context(lang="ar_001").mapped("mdl_effective_name")
        self.assertTrue(all(name.startswith("نافذة جديدة ") for name in names), (names, arabic.read(["name", "mdl_group_name_override", "mdl_model_name_override", "mdl_effective_base_name", "mdl_native_name_override"])))
        self.assertEqual({lang: self._names(lang) for lang in before}, before)
        self.assertEqual(self.products.read(["default_code", "active"]), self.skus)

    def test_template_title_translation_and_undo_do_not_affect_other_languages(self):
        before = {lang: self._names(lang) for lang in ("en_US", "he_IL")}
        self.template.update_field_translations("name", {"ar_001": "اسم مشترك"})
        # Odoo's language dialog also saves the current language value on close.
        self.template.write({"name": self.template.name})
        self.assertFalse(self.template.mdl_native_name_override)
        arabic = self.template.with_context(lang="ar_001")
        self.assertEqual(arabic.mdl_native_name_override, "اسم مشترك")
        self.assertTrue(all(p.mdl_effective_name.startswith("اسم مشترك ") for p in self.products.with_context(lang="ar_001")))
        arabic.action_mdl_reset_base_name()
        self.assertEqual(arabic.name, "شباك ضلفة")
        self.assertTrue(all(p.mdl_effective_name.startswith("شباك ضلفة ") for p in self.products.with_context(lang="ar_001")))
        self.assertEqual({lang: self._names(lang) for lang in before}, before)
        self.assertEqual(self.products.read(["default_code", "active"]), self.skus)

    def test_suffix_is_editable_in_form_and_translation_dialog(self):
        with Form(self.template, view="mdl_product_groups_attributes.mdl_product_template_name_sku_form") as form:
            form.mdl_name_suffix = " +Handle"
        before = self._names("en_US")
        self.template.update_field_translations("mdl_name_suffix", {"ar_001": " +مقبض"})
        self.assertTrue(all(p.mdl_effective_name.endswith("+مقبض") for p in self.products.with_context(lang="ar_001")))
        self.assertEqual(self._names("en_US"), before)
