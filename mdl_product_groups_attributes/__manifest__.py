{
    "name": "Multi Doorlock - Product Groups & Attributes",
    "summary": "Native product groups, attributes, combination rules, names, and SKUs",
    "version": "19.0.3.2.0",
    "category": "Inventory/Inventory",
    "author": "Multi Doorlock",
    "license": "LGPL-3",
    "depends": ["product", "sale", "purchase"],
    "data": [
        "security/ir.model.access.csv",
        "data/product_attribute_data.xml",
        "views/product_groups_attributes_views.xml",
        "views/product_variant_views.xml",
        "views/blocked_variant_preview_views.xml",
        "views/sale_order_views.xml",
        "views/res_config_settings_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "mdl_product_groups_attributes/static/src/scss/product_groups_attributes.scss",
        ],
    },
    "pre_init_hook": "pre_init_hook",
    "post_init_hook": "post_init_hook",
    "uninstall_hook": "uninstall_hook",
    "installable": True,
    "application": False,
    "auto_install": True,
}
