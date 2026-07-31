"""
network.py

Captures browser network activity:
- Requests
- Responses
- Failed Requests
- Console Messages
- JavaScript Errors
"""

requests = []
responses = []
failed_requests = []
console_logs = []
page_errors = []


def clear():
    """
    Clears all collected network data before every execution.
    """
    requests.clear()
    responses.clear()
    failed_requests.clear()
    console_logs.clear()
    page_errors.clear()


async def register(page):
    """
    Register all browser event listeners.
    """

    clear()

    # ----------------------------
    # Requests
    # ----------------------------
    def handle_request(request):
        requests.append({
            "method": request.method,
            "url": request.url,
            "resource_type": request.resource_type,
        })

    # ----------------------------
    # Responses
    # ----------------------------
    def handle_response(response):

        data = {
            "url": response.url,
            "status": response.status,
            "status_text": response.status_text,
            "ok": response.ok,
        }

        responses.append(data)

        if response.status >= 400:
            failed_requests.append(data)

    # ----------------------------
    # Console Logs
    # ----------------------------
    def handle_console(message):

        console_logs.append({
            "type": message.type,
            "text": message.text,
        })

    # ----------------------------
    # JavaScript Errors
    # ----------------------------
    def handle_page_error(error):

        page_errors.append(str(error))

    page.on("request", handle_request)
    page.on("response", handle_response)
    page.on("console", handle_console)
    page.on("pageerror", handle_page_error)


def summary():
    """
    Returns a summarized view of network activity.
    """

    return {
        "total_requests": len(requests),
        "total_responses": len(responses),
        "failed_requests": len(failed_requests),
        "console_messages": len(console_logs),
        "page_errors": len(page_errors),
    }