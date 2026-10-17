import os


def get_report_url() -> str:
    configured = os.getenv("REPORT_PUBLIC_URL", "").strip()
    if configured:
        return configured
    path = os.path.join("data", "public_report_url.txt")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = handle.read().strip()
            if value:
                return value
    except OSError:
        pass
    return "http://127.0.0.1:8091/latest.html"
