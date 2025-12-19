import logging

import streamlit as st  # type: ignore
import pandas as pd

from apis_calls.admin_apis import get_files_data


logger = logging.getLogger(__name__)


def run_file_viewer(card_title, card_table, card_details=None):
    container_title = card_title.container()
    container_table = card_table.container()
    if card_details:
        container_details = card_details.container()

    with container_title:
        st.header("Uploaded Files")

    with container_table:
        st.write("Select a file to view its details from the table below.")

        if len(df) == 0:
            st.warning("No files found.")
            return

        # Show relevant columns in the main table (including dynamic metadata)
        base_columns = ["Filename", "Size (KB)", "Upload Date", "Status", "File Type"]

        # Dynamically find metadata columns (any column not in base columns or excluded columns)
        excluded_columns = [
            "Size (Bytes)",
            "Processed Date",
            "File URI",
            "metadata",
            "Open File",
            "file_name",
        ]
        all_columns = df.columns.tolist()

        # Find metadata columns that have meaningful data
        available_metadata_columns = []
        for col in all_columns:
            if (
                col not in base_columns
                and col not in excluded_columns
                and col in df.columns
                and not df[col].isna().all()
                and not (df[col] == "").all()
            ):
                available_metadata_columns.append(col)

        # Include action column if available
        display_columns = base_columns + available_metadata_columns
        display_df = df[display_columns]

        # Show the dataframe
        event = st.dataframe(
            display_df,
            selection_mode="single-cell",
            hide_index=True,
            on_select="rerun",
            key="file_table",
        )

    # Check if event has cells selected
    # Don't process selection if we just closed the details (to prevent immediate re-selection)
    if (
        event
        and event.selection.cells
        and not st.session_state.get("just_closed", False)
    ):
        logger.debug("Event selection cells: %s", event.selection.cells)

        # Get the row index from the selected cell
        selected_row_index = event.selection.cells[0][
            0
        ]  # cells[0] gives (row, col), we want row
        current_selection = st.session_state.get("selected_file")
        logger.debug(
            "Selected cell row: %s, Current session state: %s",
            selected_row_index,
            current_selection,
        )

        if current_selection != selected_row_index:
            # Different row clicked - update selection and rerun to show details
            logger.debug(
                "Different row clicked - showing details for row %s",
                selected_row_index,
            )
            st.session_state["selected_file"] = selected_row_index
            st.rerun()

    # Clear the "just_closed" flag after checking
    if st.session_state.get("just_closed", False):
        st.session_state["just_closed"] = False

    if card_details:
        with container_details:
            st.write("### File Details")
            if st.session_state.get("selected_file") is not None:
                selected_row_index = st.session_state["selected_file"]
                logger.debug("Selected row index: %s", selected_row_index)

                # Get the selected file details from DataFrame
                if selected_row_index is not None and selected_row_index < len(df):
                    file_details = df.iloc[selected_row_index]

                    # Basic file information (read-only)
                    st.write("#### Basic Information")
                    st.write(f"**Filename:** {file_details['Filename']}")
                    st.write(f"**Upload Date:** {file_details['Upload Date']}")
                    st.write(f"**Status:** {file_details['Status']}")
                    st.write(f"**File Type:** {file_details['File Type']}")

                    # Define base fields that should not be editable
                    base_fields = [
                        "Filename",
                        "Size (KB)",
                        "Size (Bytes)",
                        "Upload Date",
                        "Processed Date",
                        "Status",
                        "File Type",
                        "File URI",
                        "metadata",
                    ]

                    # Get all metadata fields dynamically (fields that are not base fields)
                    metadata_fields = [
                        col
                        for col in file_details.index
                        if col not in base_fields
                        and file_details[col]
                        and str(file_details[col]).strip()
                    ]

                    if metadata_fields:
                        st.write("#### Metadata Information (Editable)")

                        # Initialize edited metadata in session state if not exists
                        if "edited_metadata" not in st.session_state:
                            st.session_state.edited_metadata = {}

                        # If this is a newly selected file, initialize its metadata
                        file_key = f"file_{selected_row_index}"
                        if file_key not in st.session_state.edited_metadata:
                            st.session_state.edited_metadata[file_key] = {}
                            for field in metadata_fields:
                                st.session_state.edited_metadata[file_key][field] = str(
                                    file_details[field]
                                )

                        # Create editable input fields for each metadata column
                        for field in metadata_fields:
                            current_value = st.session_state.edited_metadata[
                                file_key
                            ].get(field, str(file_details[field]))

                            # Use text_input for editable fields
                            new_value = st.text_input(
                                label=field,
                                value=current_value,
                                key=f"metadata_{file_key}_{field}",
                                help=f"Edit the value for {field}",
                            )

                            # Update the edited metadata in session state
                            st.session_state.edited_metadata[file_key][
                                field
                            ] = new_value

                        # Show if there are unsaved changes
                        has_changes = False
                        for field in metadata_fields:
                            original_value = str(file_details[field])
                            edited_value = st.session_state.edited_metadata[file_key][
                                field
                            ]
                            if original_value != edited_value:
                                has_changes = True
                                break

                        if has_changes:
                            st.info("⚠️ You have unsaved changes")

                    with st.container():
                        col1, col2, col3, col4 = st.columns(4)
                        with col1:
                            # Delete button with confirmation
                            if "confirm_delete_file" not in st.session_state:
                                st.session_state["confirm_delete_file"] = False

                            if not st.session_state["confirm_delete_file"]:
                                if st.button(
                                    "Delete", key="delete_button", type="primary"
                                ):
                                    st.session_state["confirm_delete_file"] = True
                                    st.rerun()
                            else:
                                # Show confirmation state
                                if st.button(
                                    "⚠️ Confirm Delete",
                                    key="confirm_delete_button",
                                    type="primary",
                                ):
                                    # Import the delete function
                                    from apis_calls.admin_apis import delete_file

                                    # Call delete API
                                    result = delete_file(file_details["Filename"])
                                    if result:
                                        st.success(
                                            f"✅ File '{file_details['Filename']}' deleted successfully!"
                                        )
                                        st.session_state["confirm_delete_file"] = False
                                        st.session_state["selected_file"] = None
                                        if file_key in st.session_state.edited_metadata:
                                            del st.session_state.edited_metadata[
                                                file_key
                                            ]
                                        st.rerun()
                                    else:
                                        st.error("❌ Failed to delete file")
                                        st.session_state["confirm_delete_file"] = False
                        with col2:
                            # Cancel delete if in confirmation mode
                            if st.session_state.get("confirm_delete_file", False):
                                if st.button(
                                    "Cancel Delete", key="cancel_delete_button"
                                ):
                                    st.session_state["confirm_delete_file"] = False
                                    st.rerun()
                            elif st.button(
                                "Save Changes",
                                key="save_metadata_button",
                                disabled=not has_changes if metadata_fields else True,
                            ):
                                # TODO: Implement backend API call to save metadata changes
                                st.success(
                                    "✅ Changes saved! (Backend integration pending)"
                                )
                                # Clear the edited metadata for this file after saving
                                if file_key in st.session_state.edited_metadata:
                                    del st.session_state.edited_metadata[file_key]
                                st.rerun()
                        with col3:
                            if not st.session_state.get("confirm_delete_file", False):
                                if st.button(
                                    "Reset",
                                    key="reset_button",
                                    disabled=(
                                        not has_changes if metadata_fields else True
                                    ),
                                ):
                                    # Reset to original values
                                    if file_key in st.session_state.edited_metadata:
                                        del st.session_state.edited_metadata[file_key]
                                    st.rerun()
                        with col4:
                            if not st.session_state.get("confirm_delete_file", False):

                                def close_file_details():
                                    """Close file details and clear state"""
                                    st.session_state["selected_file"] = None
                                    st.session_state["just_closed"] = (
                                        True  # Flag to prevent immediate re-selection
                                    )
                                    st.session_state["confirm_delete_file"] = False

                                # Clear any edited metadata for this file
                                if (
                                    "edited_metadata" in st.session_state
                                    and file_key in st.session_state.edited_metadata
                                ):
                                    del st.session_state.edited_metadata[file_key]

                                st.button(
                                    "Close",
                                    key="close_button",
                                    on_click=close_file_details,
                                )

                    # Show warning message when in delete confirmation mode
                    if st.session_state.get("confirm_delete_file", False):
                        st.warning(
                            f"⚠️ Are you sure you want to delete **{file_details['Filename']}**? Click 'Confirm Delete' to proceed or 'Cancel Delete' to abort."
                        )


st.set_page_config(page_title="File Viewer", layout="wide")

st.title("File Viewer")

st.write("This is the file viewer page.")

try:
    files_data = get_files_data()[
        "file_list"
    ]  # Extract the files array from the dictionary and convert to DataFrame
except Exception:
    files_data = {"files": []}

if (
    isinstance(files_data, dict)
    and "files" in files_data
    and len(files_data["files"]) > 0
):
    # Convert the files array to a DataFrame
    df = pd.DataFrame(files_data["files"])

    # Dynamically extract all metadata fields into separate columns
    metadata_columns = {}
    if "metadata" in df.columns:
        # Collect all unique metadata keys across all files
        all_metadata_keys = set()
        for metadata in df["metadata"]:
            if metadata and isinstance(metadata, dict):
                # Recursively collect all keys from nested dictionaries
                def collect_keys(data, prefix=""):
                    for key, value in data.items():
                        if isinstance(value, dict) and key == "additional_info":
                            # Handle nested additional_info
                            collect_keys(value, f"{prefix}{key}.")
                        else:
                            full_key = f"{prefix}{key}" if prefix else key
                            all_metadata_keys.add(full_key)

                collect_keys(metadata)

        # Convert keys to user-friendly column names
        def key_to_column_name(key):
            # Convert snake_case to Title Case and handle special cases
            if "." in key:
                parts = key.split(".")
                return " > ".join([part.replace("_", " ").title() for part in parts])
            else:
                return key.replace("_", " ").title()

        # Extract all metadata fields dynamically
        for key in sorted(all_metadata_keys):
            column_name = key_to_column_name(key)
            column_data = []

            for metadata in df["metadata"]:
                if metadata and isinstance(metadata, dict):
                    # Handle nested keys
                    value = metadata
                    for part in key.split("."):
                        if isinstance(value, dict) and part in value:
                            value = value[part]
                        else:
                            value = ""
                            break

                    # Format the value appropriately
                    if isinstance(value, list):
                        formatted_value = ", ".join(str(item) for item in value if item)
                    elif value is None:
                        formatted_value = ""
                    else:
                        formatted_value = str(value)

                    column_data.append(formatted_value)
                else:
                    column_data.append("")

            # Add column if it has any non-empty values
            if any(val.strip() for val in column_data):
                metadata_columns[column_name] = column_data

        # Add metadata columns to DataFrame
        for col_name, col_data in metadata_columns.items():
            if len(col_data) == len(df):
                df[col_name] = col_data

    # Rename columns to be more user-friendly
    df = df.rename(
        columns={
            "name": "Filename",
            "size": "Size (Bytes)",
            "uploaded_at": "Upload Date",
            "processed_at": "Processed Date",
            "status": "Status",
            "content_type": "File Type",
            "file_uri": "File URI",
        }
    )

    # Convert bytes to KB for better readability (only if column exists)
    if "Size (Bytes)" in df.columns:
        df["Size (KB)"] = (df["Size (Bytes)"] / 1024).round(2)

    # Format dates to be more readable (only if columns exist)
    if "Upload Date" in df.columns:
        df["Upload Date"] = pd.to_datetime(
            df["Upload Date"], errors="coerce"
        ).dt.strftime("%Y-%m-%d %H:%M:%S")
    if "Processed Date" in df.columns:
        df["Processed Date"] = pd.to_datetime(
            df["Processed Date"], errors="coerce"
        ).dt.strftime("%Y-%m-%d %H:%M:%S")

    # Simplify File Type to show just the extension (e.g., "pdf" instead of "application/pdf")
    if "File Type" in df.columns:
        df["File Type"] = df["File Type"].apply(
            lambda x: x.split("/")[-1].upper() if isinstance(x, str) and "/" in x else x
        )

    # Add metadata info
    st.info(
        f"Bot ID: {files_data.get('bot_id', 'Unknown')} | Total Files: {files_data.get('total_files', 0)} | Last Updated: {files_data.get('updated_at', 'Unknown')}"
    )

else:
    # No files uploaded - show a simple message
    st.write("📁 No files have been uploaded yet.")
    df = pd.DataFrame()

row1 = st.columns(1)

if "selected_file" not in st.session_state:
    st.session_state["selected_file"] = None

# Create grid based on current selection state
if st.session_state.get("selected_file") is not None:
    # When file is selected, show title + table + details
    card_title = row1[0].container(height=100)
    row2 = st.columns([1, 2])
    card_table = row2[0].container()
    card_details = row2[1].container()
    run_file_viewer(card_title, card_table, card_details)
else:
    # When no file is selected, show title + table only
    card_title = row1[0].container(height=100)
    card_table = st.container()
    run_file_viewer(card_title, card_table)
