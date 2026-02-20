# -*- coding: utf-8 -*-
"""
Start and supervise the Node.js WhatsApp automation server.
Node runs as a subprocess; we start it when the WhatsApp button is clicked and ensure it is up before sending.
"""

import logging
import os
import subprocess
import time

_logger = logging.getLogger(__name__)

# Paths: this file is in mnf_whatsapp_aretx/, whatsapp-automation/ is sibling under custom_addons
_ADDON_DIR = os.path.dirname(os.path.abspath(__file__))
_CUSTOM_ADDONS = os.path.dirname(_ADDON_DIR)
_NODE_DIR = os.path.join(_CUSTOM_ADDONS, "whatsapp-automation")
_SERVER_JS = os.path.join(_NODE_DIR, "server.js")


def _node_available():
    if not os.path.isfile(_SERVER_JS):
        return False
    return True


def start_node_server():
    """Start the Node WhatsApp server if not already running. Non-blocking. Returns True if started."""
    if not _node_available():
        _logger.warning(
            "mnf_whatsapp_aretx: Node server not found at %s; WhatsApp send will fail until started manually.",
            _SERVER_JS,
        )
        return False
    try:
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0x00000010)
        subprocess.Popen(
            ["node", "server.js"],
            cwd=_NODE_DIR,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        _logger.info("mnf_whatsapp_aretx: Node WhatsApp server started from %s", _NODE_DIR)
        return True
    except (OSError, ValueError) as e:
        _logger.warning("mnf_whatsapp_aretx: Could not start Node server: %s", e)
        return False


def ensure_node_running(base_url, timeout=5, start_wait=3, ready_timeout=45):
    """
    If the Node service at base_url is not responding, start it and wait until
    it reports ready (browser open, QR shown if needed) or ready_timeout seconds.
    """
    from urllib.error import HTTPError
    from urllib.request import urlopen

    url = "%s/health" % base_url.rstrip("/")
    try:
        urlopen(url, timeout=timeout)
        return
    except Exception:
        pass
    start_node_server()
    time.sleep(start_wait)
    for _ in range(ready_timeout // 2):
        try:
            urlopen(url, timeout=timeout)
            return
        except HTTPError as e:
            if e.code == 503:
                time.sleep(2)
                continue
            return
        except Exception:
            time.sleep(2)
