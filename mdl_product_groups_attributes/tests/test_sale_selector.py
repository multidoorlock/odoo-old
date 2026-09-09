from lxml import etree

from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools.safe_eval import safe_eval


@tagged('post_install', '-at_install')
class TestCatalogSaleSelector(TransactionCase):
    def test_native_product_selector_and_optional_variant_are_available(self):
        result = self.env['sale.order'].get_view(
            view_id=self.env.ref('sale.view_order_form').id, view_type='form',
        )
        arch = etree.fromstring(result['arch'])
        template = arch.xpath("//field[@name='order_line']/list/field[@name='product_template_id']")[0]
        variant = arch.xpath("//field[@name='order_line']/list/field[@name='product_id']")[0]
        self.assertEqual(template.get('optional'), 'show')
        self.assertEqual(variant.get('optional'), 'hide')
        for node in (template, variant):
            self.assertEqual(node.get('widget'), 'sol_product_many2one')
            self.assertTrue(safe_eval(node.get('options'))['no_create'])

    def test_regular_product_remains_searchable_by_reference(self):
        template = self.env['product.template'].create({
            'name': 'Catalog compatibility desk',
            'default_code': 'MDL-COMPAT-DESK',
            'mdl_catalog_managed': False,
        })
        matches = dict(self.env['product.template'].name_search('MDL-COMPAT-DESK'))
        self.assertIn(template.id, matches)
        self.assertIn('MDL-COMPAT-DESK', matches[template.id])

    def test_helper_labels_and_translated_index_are_distinct(self):
        for model, pairs in (
            ('product.template', [('mdl_group_name_value', 'mdl_group_default_name'),
                                  ('mdl_group_sku_value', 'mdl_group_default_sku')]),
            ('product.product', [('mdl_effective_name', 'mdl_generated_name')]),
            ('product.template.attribute.value', [('mdl_attribute_group_id', 'attribute_id')]),
        ):
            for first, second in pairs:
                self.assertNotEqual(self.env[model]._fields[first].string,
                                    self.env[model]._fields[second].string)
        self.assertEqual(self.env['product.template']._fields['mdl_group_default_name'].index, 'trigram')
