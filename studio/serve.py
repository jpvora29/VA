"""Serving the Studio app on a socket that answers ``localhost`` at full speed.

On Windows ``localhost`` resolves to ``::1`` BEFORE ``127.0.0.1``. Werkzeug picks its
address family from the host string, so ``app.run(host="localhost")`` resolves to an
IPv4-only socket — and every browser request then pays for an ``::1`` attempt that nothing
is listening on before it retries on IPv4. Measured on this machine:

    127.0.0.1  →  1-30 ms per request
    localhost  →  ~300 ms in Chrome, ~2000 ms from Python

That is a flat tax on EVERY Dash callback, and on the Setup page (four callbacks per filter
change, all fired at once) it was the largest single component of the wait — larger than the
queries. It is invisible in server-side timings, which is why it survived so long.

The fix is one dual-stack listener: bind ``::`` with ``IPV6_V6ONLY`` off so the same socket
answers ``::1`` and ``127.0.0.1``. Werkzeug's own server class does everything else, so this
module is a socket option and a fallback — a host without usable IPv6 gets the plain IPv4
bind and behaves exactly as before.
"""
from __future__ import annotations

import socket
from typing import Any, Optional

from logger import get_logger

logger = get_logger(__name__)


def _dual_stack_server(port: int, wsgi_app) -> Optional[Any]:
    """A threaded WSGI server listening on IPv6 AND IPv4, or None if that is not possible."""
    from werkzeug.serving import ThreadedWSGIServer

    class DualStackWSGIServer(ThreadedWSGIServer):
        """``::`` with ``IPV6_V6ONLY`` cleared — one listener, both stacks.

        The option has to be set on the socket AFTER it exists and BEFORE it binds, which
        is exactly the window ``server_bind`` occupies.
        """

        def server_bind(self):
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            super().server_bind()

    if not socket.has_ipv6:
        return None
    try:
        return DualStackWSGIServer("::", port, wsgi_app)
    except OSError as exc:
        logger.info("serve: no dual-stack socket on port %s (%s); using IPv4 only", port, exc)
        return None


def run_app(app, *, port: int, debug: bool = True, **dev_tools) -> None:
    """Run the Dash ``app`` on a dual-stack socket, falling back to the IPv4 bind.

    ``debug`` and ``dev_tools`` mean what they do on ``Dash.run`` — they are handed to
    ``enable_dev_tools``, which is the half of ``run`` that is about the app rather than
    about the socket.
    """
    app.enable_dev_tools(debug=debug, **dev_tools)
    server = _dual_stack_server(port, app.server)
    if server is None:
        app.run(host="127.0.0.1", port=port, debug=debug, **dev_tools)
        return
    logger.info("serve: dual-stack (IPv6 + IPv4) — http://localhost:%s", port)
    print(f"Dash is running on http://localhost:{port}/ (dual-stack)\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
