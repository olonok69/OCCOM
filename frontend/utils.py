from pathlib import Path
import streamlit as st


def generate_streamlit_config():
    """Generate .streamlit/config.toml from bot configuration, preserving other settings"""
    cfg = st.session_state["bot_config"] or {}

    # Create .streamlit directory if it doesn't exist
    config_dir = Path(".streamlit")
    config_dir.mkdir(exist_ok=True)

    config_path = config_dir / "config.toml"

    # Read existing config if it exists
    existing_content = ""
    existing_sections = {}
    current_section = None

    if config_path.exists():
        with open(config_path, "r") as f:
            existing_content = f.read()

        # Parse existing TOML content to preserve non-theme sections
        for line in existing_content.split("\n"):
            line_stripped = line.strip()
            if line_stripped.startswith("[") and line_stripped.endswith("]"):
                current_section = line_stripped[1:-1]
                if current_section not in existing_sections:
                    existing_sections[current_section] = []
            elif current_section and current_section != "theme":
                existing_sections.setdefault(current_section, []).append(line)

    # Ensure all color values have defaults and are never None
    primary_color = cfg.get("primary_color") or "#D3D3D3"
    background_color = cfg.get("background_color") or "#FFFFFF"
    secondary_bg_color = cfg.get("secondary_background_color") or "#F0F2F6"
    text_color = cfg.get("text_color") or "#262730"

    # Generate theme section with updated values
    theme_content = f"""[theme]
base = "light"
primaryColor = "{primary_color}"
backgroundColor = "{background_color}"
secondaryBackgroundColor = "{secondary_bg_color}"
textColor = "{text_color}"
"""

    # Reconstruct the full config content
    new_content_parts = [theme_content]

    # Add back other sections
    for section, lines in existing_sections.items():
        if section and section != "theme":
            new_content_parts.append(f"\n[{section}]")
            new_content_parts.extend(lines)

    # Write to config.toml
    with open(config_path, "w") as f:
        f.write("\n".join(new_content_parts))

    return config_path
