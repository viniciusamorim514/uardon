import threading
import time
import webbrowser

from app import app, ensure_data_file


def open_browser():
    time.sleep(1.2)
    url = "http://127.0.0.1:5000"
    chrome_paths = [
        "C:/Program Files/Google/Chrome/Application/chrome.exe",
        "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
    ]
    for path in chrome_paths:
        try:
            webbrowser.register("chrome", None, webbrowser.BackgroundBrowser(path))
            webbrowser.get("chrome").open(url)
            return
        except Exception:
            pass
    webbrowser.open(url)


if __name__ == "__main__":
    ensure_data_file()
    threading.Thread(target=open_browser, daemon=True).start()
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)
