"""
network.py

Captures browser network activity:
- Requests
- Responses
- Failed Requests
- Console Messages
- JavaScript Errors
"""

import logging


logger = logging.getLogger(__name__)

requests = []
responses = []
failed_requests = []
console_logs = []
page_errors = []


def clear():
    """Clears all collected network data before every execution."""
    try:
        requests.clear()
        responses.clear()
        failed_requests.clear()
        console_logs.clear()
        page_errors.clear()
    except Exception:
        logger.exception("Error clearing network data")


async def register(page):
    """Register all browser event listeners."""
    clear()

    def handle_request(request):
        try:
            requests.append({
                "method": request.method,
                "url": request.url,
                "resource_type": request.resource_type,
            })
        except Exception:
            logger.exception("Error handling request event")

    def handle_response(response):
        try:
            data = {
                "url": response.url,
                "status": response.status,
                "status_text": response.status_text,
                "ok": response.ok,
            }

            responses.append(data)

            if response.status >= 400:
                failed_requests.append(data)

        except Exception:
            logger.exception("Error handling response event")

    def handle_console(message):
        try:
            console_logs.append({
                "type": message.type,
                "text": message.text,
            })
        except Exception:
            logger.exception("Error handling console event")

    def handle_page_error(error):
        try:
            page_errors.append(str(error))
        except Exception:
            logger.exception("Error handling page error event")

    try:
        page.on("request", handle_request)
        page.on("response", handle_response)
        page.on("console", handle_console)
        page.on("pageerror", handle_page_error)
    except Exception:
        logger.exception("Error registering network listeners")


def summary():
    """Returns a summarized view of network activity."""
    try:
        return {
            "total_requests": len(requests),
            "total_responses": len(responses),
            "failed_requests": len(failed_requests),
            "console_messages": len(console_logs),
            "page_errors": len(page_errors),
        }
    except Exception:
        logger.exception("Error building network summary")
        return {
            "total_requests": 0,
            "total_responses": 0,
            "failed_requests": 0,
            "console_messages": 0,
            "page_errors": 0,
        }


def details(max_failed: int = 200, max_console: int = 200):
    """Return detailed network events captured during a dashboard run."""
    try:
        return {
            "failed_requests": list(failed_requests[:max_failed]),
            "console_logs": list(console_logs[:max_console]),
            "page_errors": list(page_errors[:max_failed]),
        }
    except Exception:
        logger.exception("Error building network details")
        return {
            "failed_requests": [],
            "console_logs": [],
            "page_errors": [],
        }
