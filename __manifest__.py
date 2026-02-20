# -*- coding: utf-8 -*-
{
    "name": "Invoice WhatsApp (Web)",
    "version": "1.0",
    "category": "Accounting",
    "summary": "Send invoice PDF via WhatsApp Web without API",
    "description": """
        Invoice par WhatsApp smart button. Customer ke contact mein number
        check karke WhatsApp Web open karta hai aur invoice PDF download option.
        Koi WhatsApp API use nahi hota.
    """,
    "depends": ["account"],
    "data": [
        "security/ir.model.access.csv",
        "wizard/whatsapp_invoice_wizard_views.xml",
        "views/account_move_views.xml",
    ],
    "installable": True,
    "auto_install": False,
    "license": "LGPL-3",
}
