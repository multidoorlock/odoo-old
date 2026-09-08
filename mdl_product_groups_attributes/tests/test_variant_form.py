from lxml import etree

from odoo.fields import Command
from odoo.tests import Form, tagged
from odoo.tests.common import TransactionCase
from odoo.tools.safe_eval import safe_eval


@tagged("post_install", "-at_install")
class TestVariantForm(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids |= (
            cls.env.ref("product.group_product_variant")
            | cls.env.ref("product.group_product_pricelist")
            | cls.env.ref("purchase.group_purchase_manager")
        )
        attribute = cls.env["product.attribute"].create({
            "name": "Variant form size", "create_variant": "always",
            "value_ids": [Command.create({"name": "Small"}), Command.create({"name": "Large"})],
        })
        cls.template = cls.env["product.template"].create({
            "name": "Variant form test",
            "mdl_catalog_managed": False,
            "purchase_ok": True,
            "list_price": 100,
            "attribute_line_ids": [Command.create({
                "attribute_id": attribute.id,
                "value_ids": [Command.set(attribute.value_ids.ids)],
            })],
        })
        cls.variant, cls.sibling = cls.template.product_variant_ids.sorted("id")
        cls.vendor = cls.env["res.partner"].create({"name": "Variant form vendor"})
        cls.pricelist = cls.env["product.pricelist"].create({"name": "Variant form prices"})

    def _variant_arch(self):
        result = self.env["product.product"].get_view(
            view_id=self.env.ref("product.product_normal_form_view").id,
            view_type="form",
        )
        return etree.fromstring(result["arch"])

    def test_smart_button_round_trip_uses_full_forms(self):
        view = self.template.get_view(
            view_id=self.env.ref("product.product_template_only_form_view").id,
            view_type="form",
        )
        arch = etree.fromstring(view["arch"])
        self.assertTrue(arch.xpath("//button[@name='action_mdl_open_product_variants'][@type='object']"))
        action = self.template.action_mdl_open_product_variants()
        self.assertIn((self.env.ref("product.product_normal_form_view").id, "form"), action["views"])
        self.assertEqual(self.env["product.product"].search(action["domain"]), self.template.product_variant_ids)
        self.assertFalse(action["context"]["create"])
        self.assertTrue(action["context"]["active_test"])

        arch = self._variant_arch()
        self.assertTrue(arch.xpath("//page[@name='purchase']"))
        self.assertTrue(arch.xpath("//button[@name='action_mdl_open_product_template']"))
        back = self.variant.action_mdl_open_product_template()
        self.assertEqual(back["res_model"], "product.template")
        self.assertEqual(back["res_id"], self.template.id)
        self.assertEqual(back["target"], "current")
        self.assertIn((self.env.ref("product.product_template_only_form_view").id, "form"), back["views"])

    def test_vendor_form_creates_variant_price_without_changing_shared_prices(self):
        shared = self.env["product.supplierinfo"].create({
            "partner_id": self.vendor.id, "product_tmpl_id": self.template.id,
            "price": 50,
        })
        sibling_price = self.env["product.supplierinfo"].create({
            "partner_id": self.vendor.id, "product_id": self.sibling.id, "price": 60,
        })
        with Form(self.variant, view="product.product_normal_form_view") as form:
            with form.mdl_variant_seller_ids.new() as row:
                row.partner_id = self.vendor
                row.price = 70
        price = self.variant.mdl_variant_seller_ids
        self.assertEqual(len(price), 1)
        self.assertEqual(price.product_id, self.variant)
        self.assertEqual(price.product_tmpl_id, self.template)
        self.assertEqual(price.price, 70)
        self.assertEqual(self.sibling.mdl_variant_seller_ids, sibling_price)
        price.write({"price": 75})
        self.variant.write({"mdl_variant_seller_ids": [Command.delete(price.id)]})
        self.assertTrue(shared.exists())
        self.assertTrue(sibling_price.exists())
        self.assertEqual(shared.price, 50)
        self.assertFalse(shared.product_id)
        self.assertEqual(sibling_price.price, 60)
        # Hiding shared rows in this UI must not change native purchase fallback.
        self.assertIn(shared, self.variant._prepare_sellers())
        self.assertNotIn(sibling_price, self.variant._prepare_sellers())

    def test_sales_price_form_creates_variant_rule_without_changing_shared_rule(self):
        shared = self.env["product.pricelist.item"].create({
            "pricelist_id": self.pricelist.id, "product_tmpl_id": self.template.id,
            "applied_on": "1_product", "fixed_price": 100,
        })
        sibling_rule = self.env["product.pricelist.item"].create({
            "pricelist_id": self.pricelist.id, "product_id": self.sibling.id,
            "applied_on": "0_product_variant", "fixed_price": 110,
        })
        with Form(self.variant, view="product.product_normal_form_view") as form:
            with form.mdl_variant_pricelist_item_ids.new() as row:
                row.pricelist_id = self.pricelist
                row.fixed_price = 120
        rule = self.variant.mdl_variant_pricelist_item_ids
        self.assertEqual(len(rule), 1)
        self.assertEqual(rule.product_id, self.variant)
        self.assertEqual(rule.product_tmpl_id, self.template)
        self.assertEqual(rule.applied_on, "0_product_variant")
        self.assertEqual(rule.fixed_price, 120)
        self.assertEqual(self.sibling.mdl_variant_pricelist_item_ids, sibling_rule)
        self.variant.write({"mdl_variant_pricelist_item_ids": [Command.delete(rule.id)]})
        self.assertTrue(shared.exists())
        self.assertTrue(sibling_rule.exists())
        self.assertEqual(shared.fixed_price, 100)
        self.assertEqual(sibling_rule.fixed_price, 110)
        self.assertEqual(self.template.list_price, 100)

    def test_shared_settings_readonly_variant_fields_editable(self):
        arch = self._variant_arch()
        for name in ("name", "categ_id", "uom_id", "list_price", "lst_price", "sale_ok", "purchase_ok"):
            nodes = arch.xpath(f"//field[@name='{name}'][not(ancestor::field)]")
            self.assertTrue(nodes, name)
            for node in nodes:
                self.assertTrue(safe_eval(node.get("readonly", "False"), {"id": self.variant.id, "product_variant_count": 2}), name)
        for name in ("standard_price", "weight", "volume", "mdl_variant_seller_ids", "mdl_variant_pricelist_item_ids"):
            node = arch.xpath(f"//field[@name='{name}'][not(ancestor::field)]")[0]
            self.assertFalse(safe_eval(node.get("readonly", "False"), {"id": self.variant.id, "product_variant_count": 2}), name)
        self.assertTrue(arch.xpath("//field[@name='image_variant_1920']"))
        self.assertFalse(arch.xpath("//field[@name='image_1920']"))
        with Form(self.variant, view="product.product_normal_form_view") as form:
            form.standard_price = 12
            form.weight = 3
        self.assertEqual(self.variant.standard_price, 12)
        self.assertEqual(self.variant.weight, 3)
        self.assertEqual(self.sibling.standard_price, 0)
        self.assertEqual(self.sibling.weight, 0)

    def test_documents_domain_is_variant_only(self):
        Document = self.env["product.document"]
        own, sibling, shared = Document.create([
            {"name": "Own", "type": "url", "url": "https://example.com/own", "res_model": "product.product", "res_id": self.variant.id},
            {"name": "Sibling", "type": "url", "url": "https://example.com/sibling", "res_model": "product.product", "res_id": self.sibling.id},
            {"name": "Shared", "type": "url", "url": "https://example.com/shared", "res_model": "product.template", "res_id": self.template.id},
        ])
        action = self.variant.action_open_documents()
        self.assertEqual(Document.search(action["domain"]), own)
        self.assertEqual(self.variant.product_document_count, 1)
        self.assertEqual(action["context"]["default_res_id"], self.variant.id)
        self.assertEqual(action["context"]["default_res_model"], "product.product")
