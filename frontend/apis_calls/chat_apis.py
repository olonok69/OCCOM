import logging
import uuid

import requests

try:
    from frontend.settings import settings
except Exception:  # Fallback when running with CWD=frontend
    from settings import settings


logger = logging.getLogger(__name__)


def fetch_llm_result(prompt, sessionID="asdasew12313"):
    message_id = str(uuid.uuid4())
    header = settings.build_headers(sessionID, message_id)
    payload = {"text": prompt}

    try:
        response = requests.post(
            f"{settings.backend_base_url}/v1/query",
            headers=header,
            json=payload,
            timeout=30,
        )
        if response.status_code == 200:
            result = response.json()

            # Return the full result dict so callers can access `data` and `references`
            # e.g. callers can read result["data"]["markdown"] and result.get("references", [])
            return result, message_id
        else:
            logger.error("[ERROR] API ERROR: %s - %s", response.status_code, response.text)
            return f"Error: {response.status_code} - {response.text}", None
    except requests.exceptions.Timeout:
        logger.error("[ERROR] API TIMEOUT: Request timed out after 30 seconds")
        return "Error: Request timed out. Please try again later.", None
    except requests.exceptions.RequestException as e:
        logger.error("[ERROR] API CONNECTION ERROR: %s", str(e))
        return f"Error: Connection failed - {str(e)}", None
    except Exception as e:
        logger.error("[ERROR] API ERROR: %s", str(e))
        return f"Error: {str(e)}", None
