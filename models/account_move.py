# -*- coding: utf-8 -*-

import json
import logging
import os
import re
import tempfile
import threading
from contextlib import contextmanager
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from odoo import _, api, fields, models
from odoo.exceptions import UserError


@contextmanager
def _suppress_wkhtmltopdf_network_warning():
    """Temporarily suppress wkhtmltopdf UnknownContentError/network warning during our PDF render."""
    base_report_logger = logging.getLogger("odoo.addons.base.models.ir_actions_report")

    class _Filter(logging.Filter):
        def filter(self, record):
            try:
                msg = record.getMessage() or ""
            except Exception:
                msg = str(getattr(record, "msg", ""))
            if "wkhtmltopdf" in msg and ("UnknownContentError" in msg or "network error" in msg):
                return False
            return True

    f = _Filter()
    base_report_logger.addFilter(f)
    try:
        yield
    finally:
        base_report_logger.removeFilter(f)


class AccountMove(models.Model):
    _inherit = "account.move"

    has_whatsapp_contact = fields.Boolean(
        string="Has WhatsApp Contact",
        compute="_compute_has_whatsapp_contact",
        help="True if partner has phone or mobile in contacts",
    )
    whatsapp_phone = fields.Char(
        string="WhatsApp Number",
        compute="_compute_whatsapp_phone",
        help="Partner phone number for WhatsApp (phone or mobile)",
    )

    @api.depends("partner_id")
    def _compute_has_whatsapp_contact(self):
        for move in self:
            move.has_whatsapp_contact = bool(move._get_partner_phone())

    @api.depends("partner_id")
    def _compute_whatsapp_phone(self):
        for move in self:
            move.whatsapp_phone = move._get_partner_phone() or ""

    def _get_partner_phone(self):
        """Partner ke contacts mein phone ya mobile return kare (digits only, country code ke sath)."""
        self.ensure_one()
        if not self.partner_id:
            return ""
        partner = self.partner_id
        phone = getattr(partner, "mobile", None) or partner.phone or ""
        if not phone or not str(phone).strip():
            return ""
        cleaned = re.sub(r"[^\d+]", "", str(phone).strip())
        return cleaned if len(cleaned) >= 10 else ""

    def _get_invoice_report_name(self):
        if self.state == "posted":
            return "account.account_invoices"
        return "account.account_invoices_without_payment"

    def _send_invoice_via_node_whatsapp(self, pdf_content, file_path, phone, message):
        """POST to Node.js WhatsApp service (phone, file_path, message). Call ensure_node_running before this."""
        node_url = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("mnf_whatsapp.node_service_url", "http://127.0.0.1:3000")
            .rstrip("/")
        )
        payload = {
            "phone": phone,
            "file_path": file_path,
            "message": message,
        }
        data = json.dumps(payload).encode("utf-8")
        req = Request(
            "%s/send-invoice" % node_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            resp = urlopen(req, timeout=180)
            return True, None
        except HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            return False, _("Node service error (HTTP %s): %s") % (e.code, err_body or str(e))
        except (URLError, OSError) as e:
            return False, _("Cannot reach WhatsApp service at %s: %s") % (node_url, str(e))

    def action_open_whatsapp_invoice_wizard(self):
        """
        Ensure Node server is on (start and show QR if needed), then generate PDF,
        POST to Node, send via WhatsApp Web automatically.
        """
        self.ensure_one()
        if not self.partner_id:
            raise UserError(_("Add number for this customer."))
        phone = self._get_partner_phone()
        if not phone:
            raise UserError(_("Add number for this customer."))
        if self.move_type != "out_invoice":
            raise UserError(_("Only customer invoices can be sent via WhatsApp."))

        from odoo.addons.mnf_whatsapp_aretx import node_server

        node_url = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("mnf_whatsapp.node_service_url", "http://127.0.0.1:3000")
            .rstrip("/")
        )
        node_server.ensure_node_running(node_url)

        report_name = self._get_invoice_report_name()
        report = self.env.ref(report_name)
        with _suppress_wkhtmltopdf_network_warning():
            pdf_content, _report_type = report._render_qweb_pdf(report_name, res_ids=[self.id])

        temp_dir = tempfile.gettempdir()
        file_path = os.path.join(temp_dir, "invoice_%s.pdf" % self.id)
        try:
            with open(file_path, "wb") as f:
                f.write(pdf_content)
        except OSError as e:
            raise UserError(_("Could not write PDF to temp: %s") % str(e))

        message = _("Please find your invoice %s attached.") % (self.name or "")
        ok, err_msg = self._send_invoice_via_node_whatsapp(
            pdf_content, file_path, phone, message
        )

        def _remove_later():
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except OSError:
                pass

        threading.Timer(90, _remove_later).start()

        if not ok:
            raise UserError(
                _("Invoice could not be sent via WhatsApp.\n\n%s")
                % (err_msg or _("Check that Node.js WhatsApp service is running (e.g. http://localhost:3000)."))
            )

        self.message_post(
            body=_("Invoice sent on WhatsApp to %s")
            % (getattr(self.partner_id, "mobile", None) or self.partner_id.phone or phone),
            message_type="notification",
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Success"),
                "message": _("Invoice sent on WhatsApp."),
                "type": "success",
                "sticky": False,
            },
        }
