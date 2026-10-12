r"""
Verify a document loses focus like stock Firefox when focus moves into an iframe.

Juggler used to set docShell.overrideHasFocus on every frame, and the Playwright
patch to nsFocusManager then never blurs a document focus leaves. Typing in a
page and clicking a cross-origin iframe -- an hCaptcha checkbox after a form --
then fired no `blur` on the field or the window, and a second `window.focus`
with no blur in between, which no real browser does. Any script in the page can
record that.

The guard serves a page and a cross-origin iframe on two ports, launches camoufox
through Playwright, headed on a private Xvfb display, and has the page focus its
own input, the iframe's input, and its own input again. It asserts the page saw
input.blur and window.blur when focus left it, as stock Firefox does. The window
must have been focused first, or the events cannot fire and the check is vacuous.

    python browser/tests/playwright/patches/focus-leaves-document.py
"""

import http.server
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import free_port, hidden_display, resolve_binary  # noqa: E402

TOP = """<!DOCTYPE html><html><body>
<input id="i"><iframe id="f" src="http://localhost:{frame_port}/frame"></iframe>
<script>
const log = [];
for (const t of ["focus", "blur"]) window.addEventListener(t, () => log.push("window." + t));
const inp = document.getElementById("i");
for (const t of ["focus", "blur"]) inp.addEventListener(t, () => log.push("input." + t));
const tick = () => new Promise(r => setTimeout(r, 300));
document.getElementById("f").onload = async () => {{
  await tick();
  inp.focus(); await tick();
  log.push("-- focus moves into the iframe");
  document.getElementById("f").contentWindow.postMessage("focus", "*"); await tick();
  log.push("-- focus moves back");
  inp.focus(); await tick();
  document.documentElement.dataset.log = log.join(",");
}};
</script></body></html>"""

FRAME = b"""<!DOCTYPE html><html><body><input id="fi">
<script>onmessage = () => document.getElementById("fi").focus();</script></body></html>"""


def serve(port, body_for):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = body_for(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main() -> int:
    from camoufox.sync_api import Camoufox

    top_port, frame_port = free_port(), free_port()
    top = TOP.format(frame_port=frame_port).encode()
    servers = [serve(top_port, lambda _: top), serve(frame_port, lambda _: FRAME)]
    try:
        with hidden_display(), Camoufox(headless=False, executable_path=str(resolve_binary()),
                                        i_know_what_im_doing=True) as browser:
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{top_port}/")
            page.wait_for_function("document.documentElement.dataset.log !== undefined", timeout=20000)
            log = page.evaluate("document.documentElement.dataset.log").split(",")
    finally:
        for server in servers:
            server.shutdown()

    print("  events: " + " ".join(log))
    left = log[log.index("-- focus moves into the iframe") + 1:log.index("-- focus moves back")]
    failures = []
    if "window.focus" not in log:
        failures.append("the window never had focus, so no focus event could fire -- check is vacuous")
    for event in ("input.blur", "window.blur"):
        if event not in left:
            failures.append(f"{event} did not fire when focus moved into the iframe; stock Firefox fires it")
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: the document loses focus when focus moves into an iframe, as in stock Firefox.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
