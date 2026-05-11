import io
import os
import requests
import reflex as rx
from dotenv import load_dotenv
from collections import Counter
from reflex_intersection_observer import intersection_observer

from configuration import *

# Load credentials
# load_dotenv("../.env.dev")
load_dotenv()
API_KEY = os.getenv("API_KEY")
PIN_NUMBER = os.getenv("PIN_NUMBER")
BACKEND_INTERNAL_URL = os.getenv("BACKEND_INTERNAL_URL")
BACKEND_ENTRY = os.getenv("BACKEND_ENTRY")
HEADERS = {"header_key": API_KEY}

# Reflex's backend state management
class State(rx.State):
    """
    State variables and functions declared at class level for Reflex to track before runtime.
    """

    # Connectivity
    pin_input: str = ""
    pin_error: str = ""
    backend_ok: bool = False
    database_ok: bool = False
    garage_ok: bool = False
    # Authentication
    authenticated: str = rx.Cookie("false", max_age=3600, name="authenticated")
    # Check pin
    is_checking_pin: bool = False
    # Upload
    upload_status: list[str] = []
    upload_current: int = 0
    is_uploading: bool = False
    # Gallery
    is_loading_gallery: bool = True
    # Lightbox (selected file viewer)
    selected_file: str = ""
    selected_url: str = ""
    # Metadata
    selected_metadata: dict = {}
    show_metadata: bool = False
    # In State
    selected_file_summary: str = ""
    selected_file_count: int = 0
    # Filter
    filter_start_date: str = ""
    filter_end_date: str = ""
    filter_tag: str = ""
    filter_is_img: str = ""  # Use "" for all, "true" for images only, "false" for videos only
    show_filter: bool = False
    # Settings
    column_count: str = "3"
    show_settings: bool = False
    # Selection
    selection_mode: bool = False
    selected_items: list[str] = []  # Store filenames of selected items
    tag_input: str = ""
    show_tag_dialog: bool = False
    # Floating menu
    show_floating_menu: bool = False
    current_dialog: str = ""  # Tracks which dialog is open
    # Video
    @rx.var
    def is_video(self) -> bool:
        """Check if selected file is a video"""
        if not self.selected_file:
            return False
        ext = self.selected_file.split('.')[-1].lower()
        return ext in VIDEO_EXTS
    # Lazy loading
    media_keys: list[str] = [] # Just filenames, no URLs
    loaded_urls: dict[str, str] = {} # Only what's been lazy-loaded
    gallery_key: int = 0 # Used to trigger gallery re-render when keys change

    def set_pin_input(self, value: str):
        self.pin_input = value
        if len(value) == 6:
            return State.check_pin()

    def check_pin(self):
        self.is_checking_pin = True
        if self.pin_input == PIN_NUMBER:
            self.authenticated = "true"
            self.is_checking_pin = False
            return rx.redirect("/gallery")
        else:
            self.pin_error = "Wrong password. Please try again."
            self.is_checking_pin = False

    def check_backend(self):
        try:
            res = requests.get(f"{BACKEND_INTERNAL_URL}/", timeout=3, headers=HEADERS)
            self.backend_ok = res.status_code == 200
        except Exception:
            self.backend_ok = False
        try: # For now, this will not handle edge case of 'backend is down but db is up'
            res = requests.get(f"{BACKEND_INTERNAL_URL}/db-health", timeout=3, headers=HEADERS)
            self.database_ok = res.status_code == 200
        except Exception:
            self.database_ok = False
        try:
            res = requests.get(f"{BACKEND_INTERNAL_URL}/garage-health", timeout=3, headers=HEADERS)
            self.garage_ok = res.status_code == 200
        except Exception:
            self.garage_ok = False

    def load_gallery(self, filtered_keys: list[str] = None):
        self.is_loading_gallery = True
        try:
            if filtered_keys is None:
                res = requests.get(f"{BACKEND_INTERNAL_URL}/objects/", headers=HEADERS)
                if res.status_code != 200: return
                raw_files = res.json().get("files", [])
                self.media_keys = [f["filename"] for f in raw_files][::-1]
            else:
                self.media_keys = list(reversed(filtered_keys))
            self.loaded_urls = {}
            self.gallery_key += 1
            self.check_backend()
        except Exception as e:
            print(f"Error loading gallery: {e}")
        finally:
            self.is_loading_gallery = False

    def load_item(self, filename: str):
        if filename in self.loaded_urls:
            return
        ext = filename.split('.')[-1].lower()
        if ext in IMAGE_EXTS:
            self.loaded_urls[filename] = f"{BACKEND_ENTRY}/object/{filename}?query_key={API_KEY}"
        elif ext in VIDEO_EXTS:
            self.loaded_urls[filename] = "__video__"

    def open_file(self, filename: str):
        self.selected_file = filename
        ext = filename.split('.')[-1].lower()
        if ext in VIDEO_EXTS:
            try:
                res = requests.get(f"{BACKEND_INTERNAL_URL}/object/{filename}/stream-url", headers=HEADERS)
                if res.status_code == 200:
                    self.selected_url = f"{BACKEND_INTERNAL_URL}{res.json()['url']}"
                else:
                    self.selected_url = ""
            except Exception:
                self.selected_url = ""
        else:
            self.selected_url = self.loaded_urls.get(filename, "")

    def load_metadata(self):
        try:
            res = requests.get(f"{BACKEND_INTERNAL_URL}/object/{self.selected_file}/metadata", headers=HEADERS)
            if res.status_code == 200:
                metadata = res.json()
                # Format metadata for display
                self.selected_metadata = {
                    **metadata,
                    "file_type": metadata.get("file_type", "-").upper(),
                    "size": round(metadata.get("size", 0) / (1024 * 1024), 2),
                    "uploaded_date": str(metadata.get("uploaded_date", "-"))[:19].replace("T", " "),
                    "created_date": str(metadata.get("created_date", "-"))[:19].replace("T", " "),
                    "tag": metadata.get("tag", "-") or "None",
                }
                self.show_metadata = True
        except Exception:
            pass

    def apply_filter(self):
        """Apply current filter settings and reload gallery with filtered results"""
        # Build query parameters
        params = []
        if self.filter_start_date:
            params.append(f"created_date_start={self.filter_start_date}")
        if self.filter_end_date:
            params.append(f"created_date_end={self.filter_end_date}")
        if self.filter_tag:
            params.append(f"tag={self.filter_tag}")
        if self.filter_is_img:
            params.append(f"is_img={self.filter_is_img}")
        
        # If no filters, load all
        if not params:
            self.clear_filter()
            return
        
        try:
            query_string = "&".join(params)
            res = requests.get(f"{BACKEND_INTERNAL_URL}/objects/filter?{query_string}", headers=HEADERS)
            if res.status_code == 200:
                filtered_keys = res.json().get("files", [])
                self.load_gallery(filtered_keys)
                self.show_filter = False  # Close filter dialog after applying
            else:
                self.load_gallery()  # Fallback to all
        except Exception as e:
            print(f"Filter error: {e}")
            self.load_gallery()  # Fallback to all
    
    def clear_filter(self):
        """Clear all filters and reload all objects"""
        self.filter_start_date = ""
        self.filter_end_date = ""
        self.filter_tag = ""
        self.filter_is_img = ""
        self.load_gallery()  # Load all
        self.show_filter = False
    
    def set_filter_start_date(self, value: str):
        self.filter_start_date = value
    
    def set_filter_end_date(self, value: str):
        self.filter_end_date = value
    
    def set_filter_tag(self, value: str):
        self.filter_tag = value
    
    def set_filter_is_img(self, value: str):
        self.filter_is_img = value

    def close_lightbox(self):
        self.selected_file = ""
        self.selected_url = ""
        self.selected_metadata = {}
        self.show_metadata = False

    def delete_selected(self):
        try:
            res = requests.delete(f"{BACKEND_INTERNAL_URL}/object/{self.selected_file}", headers=HEADERS)
            if res.status_code == 200:
                self.media_keys = [k for k in self.media_keys if k != self.selected_file]
                self.loaded_urls.pop(self.selected_file, None)
                self.close_lightbox()
        except Exception:
            pass

    async def handle_upload(self, files: list[rx.UploadFile]):
        self.upload_status = []
        self.upload_current = 0
        self.is_uploading = True
        exts = [f.filename.split('.')[-1].lower() for f in files]
        counts = Counter(exts)
        self.selected_file_count = len(files)
        self.selected_file_summary = ", ".join(f"{v} {k}" for k, v in counts.items())
        yield  # flush spinner to UI
        failed = 0
        for file in files:
            self.upload_current += 1
            yield  # update counter in UI
            data = await file.read()
            try:
                res = requests.post(
                    f"{BACKEND_INTERNAL_URL}/object/",
                    files={"file": (file.filename, io.BytesIO(data), "application/octet-stream")},
                    headers=HEADERS,
                )
                if res.status_code == 200:
                    returned_key = res.json()["key"]
                    ext = returned_key.split('.')[-1].lower()
                    if ext in IMAGE_EXTS:
                        url = f"{BACKEND_ENTRY}/object/{returned_key}?query_key={API_KEY}"
                    elif ext in VIDEO_EXTS:
                        url = "__video__"
                    self.media_keys.insert(0, file.filename)       # ← prepend to keys (newest first)
                    self.loaded_urls[file.filename] = url           # ← store url in dict
                else:
                    failed += 1
            except Exception:
                failed += 1
        self.is_uploading = False
        if failed:
            self.upload_status = [f"{failed} file(s) failed to upload."]
        else:
            self.upload_status = ["done"]
        yield  # final flush

    def set_column_count(self, count: int):
        """Set the number of columns for the grid"""
        self.column_count = str(count)

    def toggle_selection_mode(self):
        self.selection_mode = not self.selection_mode
        if not self.selection_mode:
            self.selected_items = []  # Clear selections when exiting mode

    def toggle_item_selection(self, filename: str):
        if filename in self.selected_items:
            self.selected_items.remove(filename)
        else:
            self.selected_items.append(filename)

    def delete_selected_items(self):
        try:
            for filename in self.selected_items:
                requests.delete(f"{BACKEND_INTERNAL_URL}/object/{filename}", headers=HEADERS)
            deleted = set(self.selected_items)
            self.media_keys = [k for k in self.media_keys if k not in deleted]
            for f in deleted:
                self.loaded_urls.pop(f, None)
            self.selected_items = []
            self.selection_mode = False
        except Exception as e:
            print(f"Error deleting items: {e}")

    def set_tag_input(self, value: str):
        self.tag_input = value

    def apply_tag_to_selected(self):
        if not self.tag_input.strip():
            return
        try:
            for filename in self.selected_items:
                requests.patch(
                    f"{BACKEND_INTERNAL_URL}/object/{filename}/tag",
                    headers=HEADERS,
                    json={"tag": self.tag_input.strip()}
                )
            self.selected_items = []
            self.selection_mode = False
            self.show_tag_dialog = False
            self.tag_input = ""
        except Exception as e:
            print(f"Error applying tag: {e}")

    def toggle_floating_menu(self):
        self.show_floating_menu = not self.show_floating_menu

    def set_current_dialog(self, dialog_name: str):
        self.current_dialog = dialog_name
        
    def close_current_dialog(self):
        self.current_dialog = ""

def status_indicator():
    return rx.hstack(
        rx.cond(
            State.backend_ok,
            rx.box(width="10px", height="10px", border_radius="50%", background="green"),
            rx.box(width="10px", height="10px", border_radius="50%", background="red"),
        ),
        rx.text(
            rx.cond(State.backend_ok, "Backend: Online", "Backend: Offline"),
            font_size="1em",
            color="white",
        ),
        rx.cond(
            State.database_ok,
            rx.box(width="10px", height="10px", border_radius="50%", background="green"),
            rx.box(width="10px", height="10px", border_radius="50%", background="red"),
        ),
        rx.text(
            rx.cond(State.database_ok, "DB: Online", "DB: Offline"),
            font_size="1em",
            color="white",
        ),
        rx.cond(
            State.garage_ok,
            rx.box(width="10px", height="10px", border_radius="50%", background="green"),
            rx.box(width="10px", height="10px", border_radius="50%", background="red"),
        ),
        rx.text(
            rx.cond(State.garage_ok, "Garage: Online", "Garage: Offline"),
            font_size="1em",
            color="white",
        ),
        spacing="2",
        align="center",
    )

def filter_indicator():
    return rx.cond(
        (State.filter_start_date != "") | (State.filter_end_date != "") | (State.filter_tag != "") | (State.filter_is_img != ""),
        rx.hstack(
            rx.badge(
                rx.hstack(
                    rx.icon("filter", size=12),
                    rx.text("Filter Active", size="1"),  # Changed from "0.7em" to "1"
                    spacing="1",
                ),
                variant="soft",
                color_scheme="blue",
            ),
            rx.button(
                "Clear",
                size="1",
                variant="ghost",
                on_click=State.clear_filter,
            ),
            spacing="1",
            align="center",
        ),
    )

def navbar():
    return rx.hstack(
        rx.text("GGallery", font_weight="bold", font_size="1.2em"),
        rx.spacer(),
        rx.hstack(
            status_indicator(),
            spacing="2",
        ),
        width="100%",
        padding="0.9em 1.5em",
        position="sticky",
        top="0",
        z_index="50",
        background="var(--gray-1)",
    )

def action_button(icon: str, label: str, dialog_func=None, click_func=None, disabled_condition=None, color_scheme=None):
    """
    Standardized circular action button for floating menu
    Either opens a dialog (dialog_func) or executes an action (click_func)
    """
    # Determine what happens on click
    if dialog_func is not None:
        # Button opens a dialog
        button_content = rx.button(
            rx.icon(icon, size=23),
            on_click=lambda: State.set_current_dialog(label.lower()),
            size="3",
            border_radius="50%",
            width="64px",
            height="64px",
            disabled=disabled_condition if disabled_condition is not None else False,
            color_scheme=color_scheme if color_scheme is not None else "indigo"
        )
    else:
        # Button executes direct action
        button_content = rx.button(
            rx.icon(icon, size=23),
            on_click=click_func,
            size="3",
            border_radius="50%",
            width="64px",
            height="64px",
            disabled=disabled_condition if disabled_condition is not None else False,
            color_scheme=color_scheme if color_scheme is not None else "indigo"
        )
    
    return rx.box(
        button_content,
        # rx.text(label, font_size="0.75em", color="gray", margin_top="4px"),
        display="flex",
        flex_direction="column",
        align_items="center",
    )

def main_action_button():
    return rx.box(
        # Render all dialogs (hidden until opened)
        filter_dialog(),
        settings_dialog(),
        upload_dialog(),
        tag_dialog(),
        
        # Action buttons stack
        rx.cond(
            State.show_floating_menu,
            rx.vstack(
                action_button(
                    icon="trash-2",
                    label="Delete",
                    click_func=State.delete_selected_items,
                    disabled_condition=rx.cond(State.selected_items.length() == 0, True, False),
                    color_scheme=rx.cond(State.selected_items.length() > 0, "indigo", "gray"),
                ),
                action_button(
                    icon="tag",
                    label="Tag",
                    dialog_func=True,
                    disabled_condition=rx.cond(State.selected_items.length() == 0, True, False),
                    color_scheme=rx.cond(State.selected_items.length() > 0, "indigo", "gray"),
                ),
                action_button(
                    icon="mouse-pointer-click",
                    label="Select",
                    click_func=State.toggle_selection_mode,
                    color_scheme=rx.cond(State.selection_mode, "red", "indigo"),
                ),
                action_button(
                    icon="settings",
                    label="Settings",
                    dialog_func=True,
                ),
                action_button(
                    icon="filter",
                    label="Filter",
                    dialog_func=True,
                ),
                action_button(
                    icon="upload",
                    label="Upload",
                    dialog_func=True,
                ),
                spacing="3",
                margin_bottom="1em",
            ),
        ),
        # Main floating button
        rx.button(
            rx.icon("sparkles", size=30),
            on_click=State.toggle_floating_menu,
            size="4",
            border_radius="50%",
            width="80px",
            height="80px",
            box_shadow="0 0 12px 2px rgba(255, 255, 255, 0.4)",
            color_scheme="indigo",
        ),
        position="fixed",
        bottom="124px",
        right="48px",
        z_index="99",
        display="flex",
        flex_direction="column",
        align_items="center",
    )

def filter_dialog():
    return rx.dialog.root(
        rx.dialog.trigger(
            rx.box(display="none"),  # Hidden trigger, opened by state
        ),
        rx.dialog.content(
            rx.vstack(
                rx.hstack(
                    rx.dialog.title("Filter"),
                    rx.spacer(),
                    rx.dialog.close(
                        rx.button("✕", variant="ghost", size="1"),
                    ),
                    width="100%",
                    align="center",
                    margin_bottom="0.5em",
                ),
                rx.text("Created Date Range", font_weight="bold", size="2"),
                rx.hstack(
                    rx.input(
                        placeholder="Start date (YYYY-MM-DD)",
                        value=State.filter_start_date,
                        on_change=State.set_filter_start_date,
                        type="date",
                        width="100%",
                    ),
                    rx.input(
                        placeholder="End date (YYYY-MM-DD)",
                        value=State.filter_end_date,
                        on_change=State.set_filter_end_date,
                        type="date",
                        width="100%",
                    ),
                    spacing="2",
                    width="100%",
                ),
                rx.text("Tag", font_weight="bold", size="2", margin_top="1em"),
                rx.input(
                    placeholder="Enter tag to filter by",
                    value=State.filter_tag,
                    on_change=State.set_filter_tag,
                    width="100%",
                ),
                rx.text("Media Type", font_weight="bold", size="2", margin_top="1em"),
                rx.hstack(
                    rx.button(
                        "All",
                        on_click=lambda: State.set_filter_is_img(""),
                        variant=rx.cond(State.filter_is_img == "", "solid", "outline"),
                        size="2",
                    ),
                    rx.button(
                        "Images Only",
                        on_click=lambda: State.set_filter_is_img("true"),
                        variant=rx.cond(State.filter_is_img == "true", "solid", "outline"),
                        size="2",
                    ),
                    rx.button(
                        "Videos Only",
                        on_click=lambda: State.set_filter_is_img("false"),
                        variant=rx.cond(State.filter_is_img == "false", "solid", "outline"),
                        size="2",
                    ),
                    spacing="2",
                    width="100%",
                ),
                rx.hstack(
                    rx.dialog.close(
                        rx.button(
                            "Apply Filter",
                            on_click=State.apply_filter,
                            background="#1a1a4e",
                            color="white",
                            flex="1",
                        ),
                    ),
                    rx.dialog.close(
                        rx.button(
                            "Clear All",
                            on_click=State.clear_filter,
                            variant="outline",
                            flex="1",
                        ),
                    ),
                    spacing="2",
                    width="100%",
                    margin_top="1.5em",
                ),
                spacing="3",
                align="stretch",
                width="100%",
            ),
            width="400px",
        ),
        open=State.current_dialog == "filter",
        on_open_change=lambda _: State.close_current_dialog(),
    )

def settings_dialog():
    return rx.dialog.root(
        rx.dialog.trigger(
            rx.box(display="none"),  # Hidden trigger
        ),
        rx.dialog.content(
            rx.vstack(
                rx.hstack(
                    rx.dialog.title("Settings"),
                    rx.spacer(),
                    rx.dialog.close(
                        rx.button("✕", variant="ghost", size="1"),
                    ),
                    width="100%",
                    align="center",
                    margin_bottom="0.5em",
                ),
                rx.text("Gallery Layout", font_weight="bold", size="2"),
                rx.hstack(
                    rx.button(
                        "1 Column",
                        on_click=lambda: State.set_column_count(1),
                        variant=rx.cond(State.column_count == "1", "solid", "outline"),
                        size="2",
                        flex="1",
                    ),
                    rx.button(
                        "3 Columns",
                        on_click=lambda: State.set_column_count(3),
                        variant=rx.cond(State.column_count == "3", "solid", "outline"),
                        size="2",
                        flex="1",
                    ),
                    rx.button(
                        "5 Columns",
                        on_click=lambda: State.set_column_count(5),
                        variant=rx.cond(State.column_count == "5", "solid", "outline"),
                        size="2",
                        flex="1",
                    ),
                    spacing="2",
                    width="100%",
                ),
                spacing="3",
                width="100%",
            ),
            width="350px",
        ),
        open=State.current_dialog == "settings",
        on_open_change=lambda _: State.close_current_dialog(),
    )

def upload_dialog():
    return rx.dialog.root(
        rx.dialog.trigger(
            rx.box(display="none"),  # Hidden trigger
        ),
        rx.dialog.content(
            rx.hstack(
                rx.dialog.title("Upload Files"),
                rx.spacer(),
                rx.dialog.close(
                    rx.button("✕", variant="ghost", size="1"),
                ),
                width="100%",
                align="center",
                margin_bottom="0.5em",
            ),
            rx.upload(
                rx.vstack(
                    rx.icon("upload", size=32),
                    rx.text("Drop files here or click to select"),
                    rx.text("Images & videos supported", font_size="0.78em", color="gray"),
                    spacing="2",
                    align="center",
                ),
                id="upload",
                multiple=True,
                border="2px dashed #ccc",
                padding="3em",
                width="100%",
                on_drop=State.handle_upload(rx.upload_files(upload_id="upload")),
            ),
            rx.cond(
                State.is_uploading,
                rx.hstack(
                    rx.spinner(size="2"),
                    rx.text(
                        "Uploading " + State.upload_current.to_string() + " of " + State.selected_file_count.to_string() + "...",
                        font_size="0.85em",
                    ),
                    spacing="2",
                    align="center",
                    margin_top="0.75em",
                ),
                rx.cond(
                    State.upload_status.length() > 0,
                    rx.box(
                        rx.text("Upload complete!", font_weight="bold", color="green"),
                        rx.foreach(
                            State.upload_status,
                            lambda msg: rx.text(msg, font_size="0.85em", color="gray"),
                        ),
                        margin_top="0.75em",
                    ),
                ),
            ),
            width="500px",
        ),
        open=State.current_dialog == "upload",
        on_open_change=lambda _: State.close_current_dialog(),
    )

def tag_dialog():
    return rx.dialog.root(
        rx.dialog.trigger(
            rx.box(display="none"),  # Hidden trigger
        ),
        rx.dialog.content(
            rx.vstack(
                rx.dialog.title("Add Tag"),
                rx.text(
                    f"Adding tag to {State.selected_items.length()} item(s)",
                    color="gray",
                    font_size="0.9em",
                ),
                rx.input(
                    placeholder="Enter tag name...",
                    value=State.tag_input,
                    on_change=State.set_tag_input,
                    width="100%",
                ),
                rx.hstack(
                    rx.dialog.close(
                        rx.button("Cancel", variant="soft", size="2"),
                    ),
                    rx.dialog.close(
                        rx.button(
                            "Apply Tag",
                            on_click=State.apply_tag_to_selected,
                            size="2",
                        ),
                    ),
                    spacing="2",
                    width="100%",
                    justify="end",
                ),
                spacing="4",
                width="100%",
            ),
        ),
        open=State.current_dialog == "tag",
        on_open_change=lambda _: State.close_current_dialog(),
    )

@rx.memo
def lazy_thumb(filename: str, live_url: str, selection_mode: bool, is_selected: bool) -> rx.Component:
    return intersection_observer(
        rx.box(
            rx.cond(
                selection_mode,
                rx.box(
                    rx.cond(
                        is_selected,
                        rx.icon("circle-check", size=24, color="blue"),
                        rx.box(width="24px", height="24px", border="2px solid white", border_radius="50%"),
                    ),
                    position="absolute", top="8px", right="8px", z_index="10",
                ),
            ),
            rx.cond(
                live_url == "",
                rx.center(rx.spinner(size="1"), background="var(--gray-3)", width="100%", height="100%"),
                rx.cond(
                    live_url == "__video__",
                    rx.center(rx.icon("video", size=32, color="white"), background="black", width="100%", height="100%"),
                    rx.image(src=live_url, width="100%", height="100%", object_fit="cover"),
                ),
            ),
            width="100%",
            aspect_ratio="1",
            overflow="hidden",
            border_radius="4px",
            cursor="pointer",
            position="relative",
            on_click=rx.cond(
                selection_mode,
                State.toggle_item_selection(filename),
                State.open_file(filename),
            ),
            _hover={"opacity": "0.85"},
            border=rx.cond(is_selected, "3px solid blue", "none"),
        ),
        on_intersect=State.load_item(filename),
        root_margin="300px",
        threshold=0,
    )

def media_thumb(filename: str) -> rx.Component:
    live_url = State.loaded_urls.get(filename, "")  # "" if not yet loaded
    is_selected = State.selected_items.contains(filename)
    return lazy_thumb(
        filename=filename,
        live_url=live_url,
        selection_mode=State.selection_mode,
        is_selected=is_selected,
    )

def lightbox():
    return rx.cond(
        State.selected_file != "",
        rx.box(
            rx.hstack(
                # Left: media viewer
                rx.center(
                    rx.vstack(
                        rx.hstack(
                            rx.text(State.selected_file, font_weight="bold", color="white"),
                            rx.button(
                                "i",
                                on_click=State.load_metadata,
                                margin_top="2px",
                                style={
                                    "borderRadius": "100%",
                                    "width": "22px",
                                    "height": "22px",
                                    "minWidth": "22px",
                                    "background": "transparent",
                                    "border": "2px solid gray",
                                    "color": "gray",
                                    "fontSize": "14px",
                                    "fontStyle": "italic",
                                    "fontWeight": "bold",
                                    "padding": "0",
                                    "cursor": "pointer",
                                },
                            ),
                            rx.spacer(),
                            rx.button("✕", on_click=State.close_lightbox, variant="ghost", color="white"),
                            width="100%",
                            padding="1em",
                        ),
                        rx.center(
                            rx.cond(
                                State.is_video,
                                rx.box(
                                    rx.el.video(
                                        rx.el.source(src=State.selected_url, type="video/mp4"),
                                        controls=True,
                                        style={
                                            "maxWidth": "80vw",
                                            "maxHeight": "80vh",
                                            "width": "100%",
                                            "height": "auto",
                                        },
                                        custom_attrs={
                                            "disablePictureInPicture": "true",
                                        },
                                    ),
                                ),
                                rx.image(
                                    src=State.selected_url,
                                    max_height="80vh",
                                    max_width="80vw",
                                    width="80%",
                                    height="auto",
                                    object_fit="contain",
                                    margin="auto",
                                ),
                            ),
                            flex="1",
                            width="100%",
                            height="100%",
                        ),
                        height="100vh",
                        width="100%",
                    ),
                    flex="1",
                ),
                # Right: metadata panel
                rx.cond(
                    State.show_metadata,
                    rx.box(
                        rx.vstack(
                            rx.text("Metadata", font_weight="bold", color="white", font_size="1.1em"),
                            rx.divider(),
                            rx.text(f"Filename: {State.selected_metadata.get('original_filename', '-')}", color="white", font_size="0.85em"),
                            rx.text(f"Type: {State.selected_metadata.get('file_type', '-')}", color="white", font_size="0.85em"),
                            rx.text(f"Size: {State.selected_metadata.get('size', '-')} MB", color="white", font_size="0.85em"),
                            rx.text(f"Device: {State.selected_metadata.get('device', '-')}", color="white", font_size="0.85em"),
                            rx.text(f"Uploaded: {State.selected_metadata.get('uploaded_date', '-')}", color="white", font_size="0.85em"),
                            rx.text(f"Created: {State.selected_metadata.get('created_date', '-')}", color="white", font_size="0.85em"),
                            rx.text(f"Tag: {State.selected_metadata.get('tag', '-')}", color="white", font_size="0.85em"),
                            spacing="3",
                            align="start",
                            padding="1em",
                        ),
                        width="280px",
                        height="100vh",
                        background="rgba(255,255,255,0.05)",
                        border_left="1px solid rgba(255,255,255,0.1)",
                    ),
                ),
                on_click=rx.stop_propagation,
                width="100%",
                height="100vh",
                spacing="0",
            ),
            position="fixed",
            top="0",
            left="0",
            width="100vw",
            height="100vh",
            background="rgba(0,0,0,0.92)",
            z_index="100",
            on_click=State.close_lightbox,
        ),
    )


def auth_guard(content: rx.Component) -> rx.Component:
    return rx.cond(
        State.authenticated == "true",
        content,
        rx.center(
            rx.vstack(
                rx.icon("lock", size=40, color="gray"),
                rx.text("You need to log in first.", color="gray"),
                rx.button("Go to Login", on_click=rx.redirect("/")),
                spacing="4",
                align="center",
            ),
            height="100vh",
        )
    )

def login():
    return rx.center(
        rx.vstack(
            rx.heading("Garage Gallery", size="7"),
            rx.text("Please enter the password.", color="gray"),
            rx.input(
                type="password",
                placeholder="······",
                on_change=State.set_pin_input,
                max_length=6,
                width="200px",
                text_align="center",
                font_size="1.5em",
                letter_spacing="0.4em",
            ),
            rx.cond(State.pin_error != "", rx.text(State.pin_error, color="red", font_size="0.85em")),
            rx.cond(
                State.is_checking_pin,
                rx.spinner(size="3"),
                rx.box(),  # empty placeholder to avoid layout shift
            ),
            spacing="4",
            align="center",
        ),
        height="100vh",
    )

def gallery():
    return auth_guard(
        rx.box(
            lightbox(),
            navbar(),
            main_action_button(),
            rx.cond(
                State.is_loading_gallery,
                rx.center(
                    rx.hstack(
                        rx.spinner(size="2"),
                        rx.text("Loading...", color="gray"),
                        spacing="3",
                        align="center",
                    ),
                    padding="4em",
                ),
                rx.cond(
                    State.media_keys.length() == 0,
                    rx.center(
                        rx.vstack(
                            rx.icon("image", size=48, color="gray"),
                            rx.text("No photos yet. Upload some!", color="gray"),
                            spacing="3",
                            align="center",
                        ),
                        padding="4em",
                    ),
                    rx.grid(
                        rx.foreach(State.media_keys, media_thumb),
                        columns=State.column_count.to(str),
                        spacing="1",
                        padding="1em",
                        width="100%",
                        key=State.gallery_key,  # Force re-render when gallery_key changes
                    ),
                ),
            ),
            width="100%",
        )
    )

# Initialize app
app = rx.App()
app.add_page(login, route="/")
app.add_page(gallery, route="/gallery", on_load=State.load_gallery)