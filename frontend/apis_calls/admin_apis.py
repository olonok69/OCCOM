import logging

import requests
import streamlit as st  # type: ignore

try:
    from frontend.settings import settings
except Exception:
    from settings import settings


logger = logging.getLogger(__name__)


def get_files_data():
    try:
        response = requests.get(
            f"{settings.backend_base_url}/v1/botids/{settings.bot_id}/listfiles",
            headers=settings.build_headers(),
        )

        response_data = response.json()
        # Return the file_list data, which contains the actual files array
        return response_data

    except requests.exceptions.RequestException:
        return {"files": [], "total_files": 0, "bot_id": settings.bot_id}
    except Exception:
        return {"files": [], "total_files": 0, "bot_id": settings.bot_id}


def get_stats_data():
    """Get statistics data from backend API"""
    try:
        # TODO: implement backend stats endpoint
        # For now, return empty stats structure
        return {
            "total_files": 0,
            "total_sessions": 0,
            "total_messages": 0,
            "active_users": 0,
            "storage_used": "0 MB",
            "last_updated": "N/A",
        }
    except Exception:
        logger.exception("Error getting stats data")
        return {
            "total_files": 0,
            "total_sessions": 0,
            "total_messages": 0,
            "active_users": 0,
            "storage_used": "0 MB",
            "last_updated": "Error",
        }


def get_meta_file_template():
    # Fetches xlsx metadata template from the backend API
    return requests.get(
        f"{settings.backend_base_url}/v1/metadata-template",
        headers=settings.build_headers(),
    ).content


def upload_file(file_obj):
    # Uploads a file (and optional metadata) to the backend API
    files = {"file": (file_obj.name, file_obj.getvalue(), file_obj.type)}

    try:
        # Create headers without Content-Type (requests will set it automatically for multipart/form-data)
        upload_headers = settings.build_headers().copy()
        upload_headers.pop(
            "Content-Type", None
        )  # Remove Content-Type to let requests set it with boundary

        response = requests.post(
            f"{settings.backend_base_url}/v1/upload",
            files=files,
            headers=upload_headers,
            timeout=10,
        )
        response.raise_for_status()  # Raise an exception for HTTP errors

        if st.session_state.get("worker_id") is None:
            st.session_state["worker_id"] = []

        response_data = response.json()

        # Check for work_id (regular files) or worker_id (if API changes)
        worker_id = response_data.get("work_id") or response_data.get("worker_id", "")

        if worker_id:  # Only append if worker_id is not empty
            st.session_state["worker_id"].append(worker_id)
        return response_data  # Return the response data

    except requests.exceptions.RequestException as e:
        st.error(f"Upload failed: {str(e)}")
        return None


def get_upload_status(worker_id):
    # Fetches the upload status from the backend API
    try:
        response = requests.get(
            f"{settings.backend_base_url}/v1/status/{worker_id}",
            headers=settings.build_headers(),
            timeout=10,
        )
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            # Treat 404 as completed (worker no longer exists)
            return {
                "status": "completed",
                "progress_percentage": 100,
                "original_filename": "Unknown",
                "error_message": "",
            }
        else:
            # Other HTTP errors
            return {
                "status": "error",
                "progress_percentage": 0,
                "original_filename": "Unknown",
                "error_message": f"HTTP {e.response.status_code}: {str(e)}",
            }
    except Exception as e:
        # Network or other errors
        return {
            "status": "error",
            "progress_percentage": 0,
            "original_filename": "Unknown",
            "error_message": str(e),
        }


def delete_file(file_name):
    """Delete a file from the backend"""
    try:
        response = requests.delete(
            f"{settings.backend_base_url}/v1/files/{file_name}",
            headers=settings.build_headers(),
            timeout=10,
        )
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        st.error(f"Delete failed: {str(e)}")
        return False
    except Exception as e:
        st.error(f"Unexpected error during delete: {str(e)}")
        return False
