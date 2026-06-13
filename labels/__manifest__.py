{
    "name": "תוויות",
    "version": "19.0.1.0.0",
    "category": "Productivity",
    "summary": "ניהול תוויות לפי טווח מספרים",
    "depends": ["base", "web"],
    "data": [
        "security/ir.model.access.csv",
        "views/label_views.xml",
        "views/label_batch_views.xml",
        "views/label_batch_wizard_views.xml",
        "views/menu.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "labels/static/src/scss/labels_backend.scss",
        ],
    },
    "application": True,
    "installable": True,
    "license": "LGPL-3",
}
