"""Launch only an owned temporary-profile companion; no devices or host."""
import socket
from pathlib import Path

from hermes_gaze.browser.cdp_bridge import GazeSession


def private_session(profile, *, chrome_args=(), url="about:blank", port=None, executable=None):
    if port is None:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
    session = GazeSession(f"http://127.0.0.1:{port}", profile_dir=Path(profile))
    try:
        session.cdp.chrome.start(url, chrome_args=tuple(chrome_args), executable=executable)
    except BaseException:
        process = session.cdp.chrome.process
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(10)
        session.close()
        raise
    return session
