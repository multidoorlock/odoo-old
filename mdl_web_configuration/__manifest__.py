{
    "name": "Multi Doorlock - Web Configuration",
    "version": "19.0.1.0.5",
    "summary": "Custom Odoo web title, favicon, and branding",
    "category": "Hidden/Configuration",
    "license": "LGPL-3",
    "depends": [
        "web"
    ],
    "data": [
        "views/webclient_templates.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "mdl_web_configuration/static/src/js/web_configuration.js",
        ],
    },
    "installable": True,
    "application": False,
    "author": "Multi Doorlock",
    "maintainer": "Itay Yosef",
}
