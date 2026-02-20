# -*- coding: utf-8 -*-

import hmac
import hashlib
import json
import time
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from odoo import _, fields, models
from odoo.exceptions import UserError


class MnfWhatsappInvoiceWizard(models.TransientModel):
    _name = "mnf.whatsapp.invoice.wizard"
    _description = "Send Invoice via WhatsApp (Web)"

    move_id = fields.Many2one("account.move", string="Invoice", required=True, readonly=True)
    partner_id = fields.Many2one("res.partner", string="Customer", required=True, readonly=True)
    phone = fields.Char(string="Phone", required=True, readonly=True)

    def _get_invoice_report_name(self):
        if self.move_id.state == "posted":
            return "account.account_invoices"
        return "account.account_invoices_without_payment"

    def action_download_invoice_pdf(self):
        """Invoice ka PDF generate karke download/new tab mein open kare."""
        self.ensure_one()
        report_name = self._get_invoice_report_name()
        return self.env.ref(report_name).report_action(self.move_id)

    def _get_pdf_url_for_whatsapp(self):
        """Signed URL banata hai jisse WhatsApp PDF fetch kar sake."""
        self.ensure_one()
        base_url = (
            self.env["ir.config_parameter"].sudo().get_param("web.base.url", "").rstrip("/")
        )
        if not base_url:
            return None
        api_token = (
            self.env["ir.config_parameter"].sudo().get_param("mnf_whatsapp.api_token") or ""
        )
        if not api_token:
            return None
        ts = int(time.time())
        raw = "%s%d" % (self.move_id.id, ts)
        token = hmac.new(
            api_token.encode("utf-8"),
            raw.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return "%s/mnf_whatsapp/invoice_pdf?id=%s&ts=%s&token=%s" % (
            base_url,
            self.move_id.id,
            ts,
            token,
        )

    def _send_document_via_whatsapp_api(self, pdf_url):
        """WhatsApp Cloud API se document (PDF) bhejta hai. Returns (True, None) ya (False, error_msg)."""
        self.ensure_one()
        api_token = (
            self.env["ir.config_parameter"].sudo().get_param("mnf_whatsapp.api_token") or ""
        )
        phone_number_id = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("mnf_whatsapp.phone_number_id")
            or ""
        )
        if not api_token or not phone_number_id:
            return False, _("WhatsApp API not configured. Set mnf_whatsapp.api_token and mnf_whatsapp.phone_number_id in System Parameters.")
        to = (self.phone or "").strip().lstrip("+").replace(" ", "").replace("-", "")
        if not to:
            return False, _("Invalid phone number.")
        api_url = "https://graph.facebook.com/v18.0/%s/messages" % phone_number_id
        body = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "document",
            "document": {
                "link": pdf_url,
                "caption": _("Please find your invoice attached."),
            },
        }
        data = json.dumps(body).encode("utf-8")
        req = Request(
            api_url,
            data=data,
            headers={
                "Authorization": "Bearer %s" % api_token,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            resp = urlopen(req, timeout=30)
            return True, None
        except HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            msg = _("WhatsApp API error (HTTP %s): %s") % (e.code, err_body or str(e))
            return False, msg
        except (URLError, OSError) as e:
            return False, _("Network error: %s") % str(e)

    def action_open_whatsapp_web(self):
        """Pehle PDF API se bhejte hain, phir chat kholte hain — attachment saath hi dikhega."""
        self.ensure_one()
        phone = (self.phone or "").strip().lstrip("+")
        if not phone:
            return None
        base_url = (
            self.env["ir.config_parameter"].sudo().get_param("web.base.url", "").rstrip("/")
        )
        pdf_url = self._get_pdf_url_for_whatsapp()
        if not pdf_url:
            raise UserError(
                _(
                    "PDF attachment ke liye WhatsApp API set karein.\n\n"
                    "1. Settings → Technical → Parameters → System Parameters\n"
                    "2. mnf_whatsapp.api_token = your WhatsApp Cloud API token\n"
                    "3. mnf_whatsapp.phone_number_id = your Phone Number ID\n\n"
                    "Aur ye zaroori hai: web.base.url = public HTTPS URL (e.g. https://yourdomain.com), "
                    "localhost nahi — WhatsApp server ko PDF download karne ke liye URL reachable hona chahiye."
                )
            )
        ok, err_msg = self._send_document_via_whatsapp_api(pdf_url)
        if not ok:
            raise UserError(
                _(
                    "Invoice PDF WhatsApp par nahi bheji ja saki. Sirf text isliye aa raha hai.\n\n%s\n\n"
                    "Check: (1) web.base.url public HTTPS URL ho (localhost mat use karein), "
                    "(2) API token aur Phone Number ID sahi hon, (3) PDF URL internet se open ho."
                )
                % (err_msg or "")
            )
        # PDF bhej diya, ab chat kholo
        default_text = _("Please find your invoice attached.")
        text_param = quote(default_text)
        url = "https://web.whatsapp.com/send?phone=%s&text=%s" % (phone, text_param)
        return {
            "type": "ir.actions.act_url",
            "url": url,
            "target": "new",
        }
