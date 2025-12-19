import streamlit as st
from apis_calls.admin_apis import get_meta_file_template
from apis_calls.admin_apis import upload_file
from apis_calls.admin_apis import get_upload_status


import pandas as pd


def run_upload_documents(title_meta_card, title_file_card, progress_card):
    container_meta_title = title_meta_card.container()
    container_files_title = title_file_card.container()
    progress_files = progress_card.container()

    with container_meta_title:
        st.header("Upload Files with Metadata")
        metadata_enabled = st.checkbox(
            "Enable metadata file upload",
            value=st.session_state.get("enable_metadata_uploads", True),
        )
        if metadata_enabled:
            if st.session_state.get("enable_metadata_uploads") is not True:
                st.session_state["enable_metadata_uploads"] = True
                st.rerun()
        else:
            if st.session_state.get("enable_metadata_uploads") is not False:
                st.session_state["enable_metadata_uploads"] = False
                st.rerun()

        if st.session_state.get("enable_metadata_uploads"):
            uploaded_metafile = st.file_uploader(
                "Upload files with metadata", accept_multiple_files=False, type=["xlsx"]
            )
            st.download_button(
                "Download Metadata Template",
                data=get_meta_file_template(),
                file_name="metadata_template.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        else:
            uploaded_metafile = None

    with container_files_title:
        if st.session_state.get("enable_metadata_uploads"):
            st.header("Upload Files with Metadata")
        else:
            st.header("Upload Files without Metadata")

        files_uploaded = st.file_uploader(
            "Upload files without metadata", accept_multiple_files=True
        )

    def click():
        if uploaded_metafile:
            upload_file(uploaded_metafile)
        if files_uploaded:
            for idx, uploaded_file in enumerate(files_uploaded):
                upload_file(uploaded_file)

    with progress_files:
        if st.session_state.get("worker_id"):
            st.write("File ingestion progress:")
            # Fragment now handles all progress display and controls
            upload_progress_dataframe()
        else:
            st.info("No file ingestion tasks running.")

            # Show upload history button even when no active workers
            if st.button(
                "📋 View Upload History", help="Show recently completed uploads"
            ):
                if "upload_history" not in st.session_state:
                    st.session_state["upload_history"] = []

                if st.session_state.get("upload_history"):
                    st.subheader("📁 Recent Upload History")
                    history_df = pd.DataFrame(st.session_state["upload_history"])
                    st.dataframe(history_df, width="stretch", hide_index=True)
                else:
                    st.info("No upload history available.")

    st.button("Start Uploading Documents", on_click=click)


@st.fragment(run_every=5)
def upload_progress_dataframe():
    if "worker_id" in st.session_state and st.session_state["worker_id"]:
        status_data = []
        active_workers = []  # Track workers that are still active

        for worker_id in st.session_state["worker_id"]:
            status = get_upload_status(worker_id)
            status_data.append(
                {
                    "Worker ID": worker_id,
                    "Status": status.get("status", "unknown"),
                    "Progress": f"{status.get('progress_percentage', 0)}%",
                    "Filename": status.get("original_filename", "Unknown"),
                    "Error": status.get("error_message", ""),
                }
            )

            # Keep track of workers that are still active
            if status.get("status") not in ["completed", "success", "failed", "error"]:
                active_workers.append(worker_id)

        df = pd.DataFrame(status_data)
        st.dataframe(df, width="stretch")

        # Calculate overall progress
        total_workers = len(status_data)
        completed_workers = sum(
            1 for item in status_data if item["Status"] in ["completed", "success"]
        )
        in_progress_workers = sum(
            1 for item in status_data if item["Status"] == "in_progress"
        )
        failed_workers = sum(
            1 for item in status_data if item["Status"] in ["failed", "error"]
        )

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Jobs", total_workers)
        with col2:
            st.metric("Completed", completed_workers)
        with col3:
            st.metric("In Progress", in_progress_workers)
        with col4:
            st.metric("Failed", failed_workers)

        # Calculate overall progress based on individual worker progress - MOVED INTO FRAGMENT
        total_progress_sum = 0
        for worker_data in status_data:
            # Extract percentage from the "Progress" field (e.g., "75%" -> 75)
            progress_str = worker_data.get("Progress", "0%")
            progress_value = int(progress_str.replace("%", ""))
            total_progress_sum += progress_value

        # Calculate average progress across all workers
        overall_progress = (
            total_progress_sum // total_workers if total_workers > 0 else 0
        )

        # Check if all workers are completed
        all_completed = all(
            worker["Status"] in ["completed", "success"] for worker in status_data
        )

        # Set progress to 100% if all completed, otherwise show calculated progress
        if all_completed:
            overall_progress = 100

        # Display overall progress bar - NOW IN FRAGMENT FOR REAL-TIME UPDATES
        st.progress(
            overall_progress / 100, text=f"Overall Progress: {overall_progress}%"
        )

        # Show completion status
        if all_completed:
            st.success("All file ingestion tasks completed!")
        elif any(worker["Status"] in ["failed", "error"] for worker in status_data):
            st.warning("Some tasks have failed. Check the details above.")

        # Add manual control buttons - MOVED INTO FRAGMENT
        if st.button(
            "🗑️ Clear All Tracking", help="Stop monitoring and clear all worker IDs"
        ):
            st.session_state["worker_id"] = []
            st.success("Worker tracking cleared!")
            st.rerun()

        # Show completed files summary - MOVED INTO FRAGMENT
        completed_files = [
            worker
            for worker in status_data
            if worker["Status"] in ["completed", "success"]
        ]
        if completed_files:
            st.subheader("📁 Completed Uploads")
            completed_df = pd.DataFrame(completed_files)[["Filename", "Status"]]
            st.dataframe(completed_df, width="stretch", hide_index=True)

        # If all workers are completed, clear the worker_id list to stop the fragment
        if len(active_workers) == 0 and len(status_data) > 0:
            # Save completed uploads to history before clearing
            if "upload_history" not in st.session_state:
                st.session_state["upload_history"] = []

            # Add completed files to history (avoid duplicates)
            existing_filenames = {
                item.get("Filename", "") for item in st.session_state["upload_history"]
            }
            for worker in status_data:
                if (
                    worker["Filename"] not in existing_filenames
                    and worker["Filename"] != "Unknown"
                ):
                    st.session_state["upload_history"].append(
                        {
                            "Filename": worker["Filename"],
                            "Status": worker["Status"],
                            "Completed At": pd.Timestamp.now().strftime(
                                "%Y-%m-%d %H:%M:%S"
                            ),
                        }
                    )

            # Only clear if we actually had workers to check
            st.success(
                "All tasks completed! You can manually clear the tracking below."
            )
        elif len(active_workers) > 0:
            # Continue running fragment if there are active workers
            st.info(
                f"Fragment running - {len(active_workers)} active workers remaining"
            )

        # Return data for external progress calculation
        return status_data
    else:
        st.write("No upload workers found.")
        return []


st.set_page_config(page_title="Upload Page", layout="wide")
st.title("Upload Page")

row1 = st.columns(1)
row2 = st.columns(1)
row3 = st.columns(1)

if "enable_metadata_uploads" not in st.session_state:
    st.session_state["enable_metadata_uploads"] = False

if st.session_state.get("worker_id") is None:
    st.session_state["worker_id"] = []

# Check if there are existing worker IDs that need monitoring when page loads
if st.session_state.get("worker_id"):
    # Check if any workers are still active (not completed/failed)
    active_workers_on_load = []
    for worker_id in st.session_state["worker_id"]:
        try:
            status = get_upload_status(worker_id)
            if status.get("status") not in ["completed", "success", "failed", "error"]:
                active_workers_on_load.append(worker_id)
        except Exception:
            # If we can't check status, assume it might still be active
            active_workers_on_load.append(worker_id)

    # If no active workers found, clean up the worker_id list
    if not active_workers_on_load:
        st.session_state["worker_id"] = []
    else:
        st.info(
            f"Resuming monitoring of {len(active_workers_on_load)} active upload tasks..."
        )

if st.session_state.get("enable_metadata_uploads"):
    grid = [col.container(height=300) for col in row1]
    grid.extend([col.container(height=300) for col in row2 + row3])
else:
    grid = [col.container(height=150) for col in row1]
    grid.extend([col.container(height=300) for col in row2 + row3])


safe_grid = [card.empty() for card in grid]

run_upload_documents(grid[0].empty(), grid[1].empty(), grid[2].empty())
