# -*- coding: utf-8 -*-

import hmac
import hashlib
import time

from odoo import http
from odoo.http import request


class MnfWhatsappController(http.Controller):

    @http.route(
        ["/mnf_whatsapp/invoice_pdf"],
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def invoice_pdf(self, id=None, ts=None, token=None, **kw):
        """WhatsApp ke liye invoice PDF serve kare. Token se verify."""
        if not id or not ts or not token:
            return request.not_found()
        try:
            move_id = int(id)
            ts_int = int(ts)
        except (TypeError, ValueError):
            return request.not_found()
        # Token 10 min tak valid
        if abs(time.time() - ts_int) > 600:
            return request.not_found()
        api_token = (
            request.env["ir.config_parameter"].sudo().get_param("mnf_whatsapp.api_token") or ""
        )
        if not api_token:
            return request.not_found()
        expected = hmac.new(
            api_token.encode("utf-8"),
            ("%s%d" % (move_id, ts_int)).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, (token or "")):
            return request.not_found()
        report_name = "account.account_invoices_without_payment"
        move = request.env["account.move"].sudo().browse(move_id)
        if not move.exists() or move.move_type != "out_invoice":
            return request.not_found()
        if move.state == "posted":
            report_name = "account.account_invoices"
        report = request.env["ir.actions.report"].sudo().ref(report_name)
        pdf, _ = report._render_qweb_pdf(report_name, res_ids=[move_id])
        filename = "Invoice-%s.pdf" % (move.name or move_id)
        return request.make_response(
            pdf,
            headers=[
                ("Content-Type", "application/pdf"),
                ("Content-Disposition", 'attachment; filename="%s"' % filename),
            ],
        )
