from __future__ import annotations

import argparse
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from .backend import BackendUnavailableError, RageBackend, TextureSummary
from .dialogs import choose_folder, open_file, save_file


SUPPORTED_EXTENSIONS = {".cdr", ".wdr", ".xdr"}
CHANNELS = (
    ("all", "Full"),
    ("red", "R"),
    ("green", "G"),
    ("blue", "B"),
    ("alpha", "A"),
)


class TextureToolApp:
    def __init__(self, root: tk.Tk, project_root: str | Path):
        self.root = root
        self.project_root = Path(project_root).resolve()
        self.backend = RageBackend(self.project_root)

        self.root.title("Model Texture Tool - GTA IV")
        self.root.geometry("1200x800")
        self.root.minsize(980, 640)
        self.root.configure(background="#f0f0f0")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close_requested)

        self.texture_summaries: list[TextureSummary] = []
        self.texture_item_map: dict[str, TextureSummary] = {}
        self.texture_index_to_item: dict[int, str] = {}
        self.texture_list_images: dict[int, tk.PhotoImage] = {}
        self.preview_image: tk.PhotoImage | None = None
        self.preview_canvas_image_id: int | None = None
        self.last_directory: Path | None = None
        self._thumbnail_queue: list[TextureSummary] = []
        self._thumbnail_after_id: str | None = None
        self.about_window: tk.Toplevel | None = None

        self.status_var = tk.StringVar(
            value="Open a PS3 .cdr, PC .wdr or Xbox .xdr file to inspect embedded textures."
        )
        self.channel_var = tk.StringVar(value="all")
        self.name_var = tk.StringVar(value="")
        self.size_info_var = tk.StringVar(value="")
        self.format_info_var = tk.StringVar(value="")

        self._configure_style()
        self.placeholder_thumbnail = self._create_placeholder_thumbnail()
        self._build_ui()
        self._set_empty_state()
        self._update_button_state()

    def _configure_style(self) -> None:
        style = ttk.Style()
        style.configure("TextureList.Treeview", rowheight=56, font=("Segoe UI", 9))
        style.configure("TextureList.Treeview.Heading", font=("Segoe UI", 9, "bold"))

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        toolbar = tk.Frame(self.root, bd=1, relief="raised", bg="#f0f0f0")
        toolbar.grid(row=0, column=0, sticky="ew")

        self.open_button = tk.Button(toolbar, text="Open", width=10, command=self.open_dialog)
        self.import_button = tk.Button(toolbar, text="Import DDS", width=12, command=self.import_selected)
        self.export_button = tk.Button(toolbar, text="Export Selected", width=14, command=self.export_selected)
        self.export_all_button = tk.Button(toolbar, text="Export All", width=12, command=self.export_all)
        self.save_button = tk.Button(toolbar, text="Save", width=10, command=self.save)
        self.save_as_button = tk.Button(toolbar, text="Save As", width=10, command=self.save_as)
        self.about_button = tk.Button(toolbar, text="i", width=3, font=("Segoe UI", 9, "bold"), command=self.show_about)

        self.open_button.pack(side="left", padx=(6, 2), pady=4)
        self.import_button.pack(side="left", padx=2, pady=4)
        self.export_button.pack(side="left", padx=2, pady=4)
        self.export_all_button.pack(side="left", padx=2, pady=4)
        tk.Frame(toolbar, width=2, bd=1, relief="sunken", bg="#d4d0c8").pack(side="left", fill="y", padx=6, pady=4)
        self.save_button.pack(side="left", padx=2, pady=4)
        self.save_as_button.pack(side="left", padx=(2, 6), pady=4)
        self.about_button.pack(side="right", padx=(4, 6), pady=4)

        content = tk.PanedWindow(self.root, orient="horizontal", sashwidth=4, sashrelief="raised", bd=0)
        content.grid(row=1, column=0, sticky="nsew")

        left = tk.Frame(content, bd=1, relief="sunken", bg="white")
        right = tk.Frame(content, bd=0, relief="flat", bg="#f0f0f0")
        content.add(left, minsize=210, width=270)
        content.add(right)

        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)

        self.texture_tree = ttk.Treeview(left, show="tree", selectmode="browse", style="TextureList.Treeview")
        self.texture_tree.grid(row=0, column=0, sticky="nsew")
        self.texture_tree.bind("<<TreeviewSelect>>", lambda _event: self.on_texture_selected())

        list_scroll = ttk.Scrollbar(left, orient="vertical", command=self.texture_tree.yview)
        list_scroll.grid(row=0, column=1, sticky="ns")
        self.texture_tree.configure(yscrollcommand=list_scroll.set)

        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)

        preview_shell = tk.Frame(right, bg="#f0f0f0")
        preview_shell.grid(row=0, column=0, sticky="nsew")
        preview_shell.columnconfigure(0, weight=1)
        preview_shell.rowconfigure(0, weight=1)

        preview_frame = tk.Frame(preview_shell, bd=2, relief="sunken", bg="#a9a9a9")
        preview_frame.grid(row=0, column=0, sticky="nsew")
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)

        self.preview_canvas = tk.Canvas(
            preview_frame,
            bg="#a9a9a9",
            highlightthickness=0,
            xscrollincrement=1,
            yscrollincrement=1,
        )
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")
        self.preview_canvas.bind("<Configure>", lambda _event: self._render_preview())

        preview_vscroll = ttk.Scrollbar(preview_frame, orient="vertical", command=self.preview_canvas.yview)
        preview_vscroll.grid(row=0, column=1, sticky="ns")
        preview_hscroll = ttk.Scrollbar(preview_frame, orient="horizontal", command=self.preview_canvas.xview)
        preview_hscroll.grid(row=1, column=0, sticky="ew")
        self.preview_canvas.configure(yscrollcommand=preview_vscroll.set, xscrollcommand=preview_hscroll.set)

        info_panel = tk.Frame(preview_shell, height=70, bd=1, relief="raised", bg="#f0f0f0")
        info_panel.grid(row=1, column=0, sticky="ew")
        info_panel.grid_propagate(False)
        info_panel.columnconfigure(0, weight=1)

        text_info = tk.Frame(info_panel, bg="#f0f0f0")
        text_info.grid(row=0, column=0, sticky="nsew", padx=(8, 4), pady=6)
        text_info.columnconfigure(1, weight=1)
        text_info.columnconfigure(3, weight=1)

        self.name_label = tk.Label(text_info, textvariable=self.name_var, anchor="w", bg="#f0f0f0", font=("Segoe UI", 10, "bold"))
        self.name_label.grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 4))

        tk.Label(text_info, text="Size:", anchor="w", bg="#f0f0f0", font=("Segoe UI", 9, "bold")).grid(row=1, column=0, sticky="w")
        tk.Label(text_info, textvariable=self.size_info_var, anchor="w", bg="#f0f0f0", font=("Segoe UI", 9)).grid(row=1, column=1, sticky="w", padx=(4, 16))
        tk.Label(text_info, text="Pixel Format:", anchor="w", bg="#f0f0f0", font=("Segoe UI", 9, "bold")).grid(row=1, column=2, sticky="w")
        tk.Label(text_info, textvariable=self.format_info_var, anchor="w", bg="#f0f0f0", font=("Segoe UI", 9)).grid(row=1, column=3, sticky="w", padx=(4, 0))

        controls = tk.Frame(info_panel, bg="#f0f0f0")
        controls.grid(row=0, column=1, sticky="e", padx=(4, 6), pady=6)

        channels = tk.Frame(controls, bg="#f0f0f0")
        channels.grid(row=0, column=0, sticky="e")
        for column, (value, label) in enumerate(CHANNELS):
            button = tk.Radiobutton(
                channels,
                text=label,
                value=value,
                variable=self.channel_var,
                indicatoron=False,
                width=4 if label == "Full" else 2,
                command=self.refresh_preview,
                relief="raised",
                bd=1,
                bg="#f0f0f0",
                selectcolor="#d4d0c8",
                highlightthickness=0,
                padx=0,
                pady=0,
            )
            button.grid(row=0, column=column, padx=(0, 2))

        status_bar = tk.Frame(self.root, bd=1, relief="sunken", bg="#f0f0f0")
        status_bar.grid(row=2, column=0, sticky="ew")
        status_label = tk.Label(
            status_bar,
            textvariable=self.status_var,
            anchor="w",
            bg="#f0f0f0",
            padx=6,
            pady=2,
            font=("Segoe UI", 9),
        )
        status_label.pack(fill="x")

    @property
    def selected_texture(self) -> TextureSummary | None:
        selection = self.texture_tree.selection()
        if not selection:
            return None
        return self.texture_item_map.get(selection[0])

    def open_dialog(self) -> None:
        if not self._prompt_save_changes_if_needed():
            return

        filename = open_file(
            title="Open GTA IV Drawable",
            filter_text="Drawable Files (*.cdr;*.wdr;*.xdr)|*.cdr;*.wdr;*.xdr|All files (*.*)|*.*",
            initial_path=self.last_directory,
        )
        if filename:
            self.open_model(filename)

    def open_model(self, path: str | Path) -> None:
        try:
            self.texture_summaries = self.backend.open_model(path)
        except Exception as exc:
            messagebox.showerror("Unable to Open File", str(exc), parent=self.root)
            return

        self.last_directory = Path(path).resolve().parent
        self._populate_texture_list()

        if self.texture_summaries:
            first_item = self.texture_index_to_item.get(0)
            if first_item:
                self.texture_tree.selection_set(first_item)
                self.texture_tree.focus(first_item)
                self.texture_tree.see(first_item)

        self.on_texture_selected()
        self._update_status()
        self._update_button_state()

    def _populate_texture_list(self) -> None:
        self._cancel_thumbnail_loader()
        for item in self.texture_tree.get_children():
            self.texture_tree.delete(item)

        self.texture_item_map.clear()
        self.texture_index_to_item.clear()
        self.texture_list_images.clear()
        self._thumbnail_queue = []

        for summary in self.texture_summaries:
            item_id = self.texture_tree.insert(
                "",
                "end",
                text=self._format_tree_text(summary),
                image=self.placeholder_thumbnail,
            )
            self.texture_item_map[item_id] = summary
            self.texture_index_to_item[summary.index] = item_id
            self.texture_list_images[summary.index] = self.placeholder_thumbnail
            self._thumbnail_queue.append(summary)

        if self._thumbnail_queue:
            self._thumbnail_after_id = self.root.after(1, self._populate_next_thumbnail)

    def _populate_next_thumbnail(self) -> None:
        self._thumbnail_after_id = None
        if not self._thumbnail_queue:
            return

        summary = self._thumbnail_queue.pop(0)
        item_id = self.texture_index_to_item.get(summary.index)
        if item_id is not None and self.texture_tree.exists(item_id):
            image = self._build_texture_thumbnail(summary)
            self.texture_list_images[summary.index] = image
            self.texture_tree.item(item_id, image=image)

        if self._thumbnail_queue:
            self._thumbnail_after_id = self.root.after(1, self._populate_next_thumbnail)

    def _cancel_thumbnail_loader(self) -> None:
        if self._thumbnail_after_id is not None:
            self.root.after_cancel(self._thumbnail_after_id)
            self._thumbnail_after_id = None
        self._thumbnail_queue = []

    def _format_tree_text(self, summary: TextureSummary) -> str:
        format_label = "External Reference" if summary.is_external_reference else summary.texture_type
        return f"{summary.title_name}\n{summary.width}x{summary.height} ({format_label})"

    def _build_texture_thumbnail(self, summary: TextureSummary) -> tk.PhotoImage:
        if summary.is_external_reference:
            return self.placeholder_thumbnail

        try:
            image_data = self.backend.get_thumbnail_png_base64(summary.index)
            if not image_data:
                return self.placeholder_thumbnail
            image = tk.PhotoImage(data=image_data)
            return self._fit_photoimage(image, 40, 40)
        except Exception:
            return self.placeholder_thumbnail

    def _fit_photoimage(self, image: tk.PhotoImage, max_width: int, max_height: int) -> tk.PhotoImage:
        width = max(1, image.width())
        height = max(1, image.height())
        sample = max((width + max_width - 1) // max_width, (height + max_height - 1) // max_height, 1)
        return image if sample <= 1 else image.subsample(sample, sample)

    def _create_placeholder_thumbnail(self) -> tk.PhotoImage:
        image = tk.PhotoImage(width=40, height=40)
        colors = ("#c8c8c8", "#9d9d9d")
        tile = 8
        for y in range(0, 40, tile):
            for x in range(0, 40, tile):
                color = colors[((x // tile) + (y // tile)) % 2]
                image.put(color, to=(x, y, min(x + tile, 40), min(y + tile, 40)))
        return image

    def on_texture_selected(self) -> None:
        summary = self.selected_texture
        if summary is None:
            self._set_empty_state()
            self._update_button_state()
            return

        self.name_var.set(summary.title_name)
        self.size_info_var.set(f"{summary.width} x {summary.height}")

        flags: list[str] = []
        if summary.is_external_reference:
            flags.append("External")
        if summary.requires_ps3_reference_repair or summary.has_unsupported_ps3_write_layout:
            flags.append("PS3 partial")

        self.format_info_var.set(summary.texture_type)
        self.channel_var.set("all")
        self.refresh_preview()
        self._update_button_state()

    def _set_empty_state(self) -> None:
        self.name_var.set("")
        self.size_info_var.set("")
        self.format_info_var.set("")
        self.channel_var.set("all")
        self.preview_image = None
        self._render_preview(empty_text="No texture selected")

    def refresh_preview(self) -> None:
        summary = self.selected_texture
        if summary is None:
            self._set_empty_state()
            return

        try:
            image_data = self.backend.get_preview_png_base64(
                summary.index,
                mip_level=0,
                channel=self.channel_var.get(),
            )
            self.preview_image = tk.PhotoImage(data=image_data)
        except Exception as exc:
            self.preview_image = None
            self._render_preview(empty_text="Preview unavailable")
            messagebox.showerror("Preview Error", str(exc), parent=self.root)
            return

        self._render_preview()

    def _render_preview(self, empty_text: str | None = None) -> None:
        self.preview_canvas.delete("all")
        canvas_width = max(1, self.preview_canvas.winfo_width())
        canvas_height = max(1, self.preview_canvas.winfo_height())

        if self.preview_image is None:
            self.preview_canvas.configure(scrollregion=(0, 0, canvas_width, canvas_height))
            if empty_text:
                self.preview_canvas.create_text(
                    canvas_width // 2,
                    canvas_height // 2,
                    text=empty_text,
                    fill="#202020",
                    font=("Segoe UI", 10),
                )
            return

        image_width = self.preview_image.width()
        image_height = self.preview_image.height()
        region_width = max(canvas_width, image_width)
        region_height = max(canvas_height, image_height)
        origin_x = max(0, (region_width - image_width) // 2)
        origin_y = max(0, (region_height - image_height) // 2)

        self.preview_canvas_image_id = self.preview_canvas.create_image(
            origin_x,
            origin_y,
            anchor="nw",
            image=self.preview_image,
        )
        self.preview_canvas.configure(scrollregion=(0, 0, region_width, region_height))
        self.preview_canvas.xview_moveto(0)
        self.preview_canvas.yview_moveto(0)

    def import_selected(self) -> None:
        summary = self.selected_texture
        if summary is None:
            messagebox.showinfo("Import DDS", "Select a texture before importing.", parent=self.root)
            return

        filename = open_file(
            title="Import DDS",
            filter_text="DirectDraw Surface (*.dds)|*.dds|All files (*.*)|*.*",
            initial_path=self.last_directory,
            file_name=f"{summary.title_name}.dds",
        )
        if not filename:
            return

        try:
            self.backend.import_texture(summary.index, filename)
        except Exception as exc:
            messagebox.showerror("Import DDS", str(exc), parent=self.root)
            return

        self.last_directory = Path(filename).resolve().parent
        self.texture_summaries = self.backend.get_textures()
        self._refresh_texture_entry(summary.index)
        self._update_status()
        self._update_button_state()

    def _refresh_texture_entry(self, index: int) -> None:
        item_id = self.texture_index_to_item.get(index)
        if item_id is None or not self.texture_tree.exists(item_id):
            return

        updated_summary = self.texture_summaries[index]
        self.texture_item_map[item_id] = updated_summary
        self.texture_tree.item(item_id, text=self._format_tree_text(updated_summary), image=self.placeholder_thumbnail)
        self.texture_list_images[index] = self.placeholder_thumbnail
        image = self._build_texture_thumbnail(updated_summary)
        self.texture_list_images[index] = image
        self.texture_tree.item(item_id, image=image)
        self.texture_tree.selection_set(item_id)
        self.texture_tree.focus(item_id)
        self.texture_tree.see(item_id)
        self.on_texture_selected()

    def export_selected(self) -> None:
        summary = self.selected_texture
        if summary is None:
            messagebox.showinfo("Export Texture", "Select a texture before exporting.", parent=self.root)
            return

        filename = save_file(
            title="Export Texture",
            filter_text="DirectDraw Surface (*.dds)|*.dds",
            default_extension=".dds",
            initial_path=self.last_directory,
            file_name=f"{summary.title_name}.dds",
        )
        if not filename:
            return

        try:
            self.backend.export_texture(summary.index, filename)
        except Exception as exc:
            messagebox.showerror("Export Texture", str(exc), parent=self.root)
            return

        self.last_directory = Path(filename).resolve().parent
        messagebox.showinfo("Export Texture", "Texture exported successfully as DDS.", parent=self.root)

    def export_all(self) -> None:
        if not self.texture_summaries:
            messagebox.showinfo("Export All", "There are no textures available to export.", parent=self.root)
            return

        directory = choose_folder(
            description="Choose the folder where the extracted textures will be saved.",
            initial_path=self.last_directory,
        )
        if not directory:
            return

        try:
            count = self.backend.export_all(directory)
        except Exception as exc:
            messagebox.showerror("Export All", str(exc), parent=self.root)
            return

        self.last_directory = Path(directory).resolve()
        messagebox.showinfo("Export All", f"{count} texture(s) exported successfully as DDS.", parent=self.root)

    def save(self) -> bool:
        try:
            self.backend.save()
        except Exception as exc:
            messagebox.showerror("Save", str(exc), parent=self.root)
            return False

        if self.backend.current_path is not None:
            self.last_directory = self.backend.current_path.parent
        self._update_status()
        self._update_button_state()
        messagebox.showinfo("Save", "Texture changes saved successfully.", parent=self.root)
        return True

    def save_as(self) -> bool:
        if self.backend.current_path is None:
            return False

        current_path = self.backend.current_path
        filename = save_file(
            title="Save Drawable As",
            filter_text=f"GTA Drawable (*{current_path.suffix})|*{current_path.suffix}|All files (*.*)|*.*",
            default_extension=current_path.suffix,
            initial_path=self.last_directory or current_path.parent,
            file_name=current_path.name,
        )
        if not filename:
            return False

        try:
            self.backend.save(filename)
        except Exception as exc:
            messagebox.showerror("Save", str(exc), parent=self.root)
            return False

        self.last_directory = Path(filename).resolve().parent
        self._update_status()
        self._update_button_state()
        messagebox.showinfo("Save", "Texture changes saved successfully.", parent=self.root)
        return True

    def _prompt_save_changes_if_needed(self) -> bool:
        if not self.backend.has_unsaved_changes:
            return True

        result = messagebox.askyesnocancel(
            "Unsaved Changes",
            "There are unsaved texture changes. Do you want to save them before continuing?",
            parent=self.root,
        )
        if result is None:
            return False
        if result:
            return self.save()
        return True

    def show_about(self) -> None:
        if self.about_window is not None and self.about_window.winfo_exists():
            self.about_window.deiconify()
            self.about_window.lift()
            self.about_window.focus_force()
            return

        window = tk.Toplevel(self.root)
        self.about_window = window
        window.title("Information")
        window.resizable(False, False)
        window.transient(self.root)
        window.configure(background="#f0f0f0")
        window.protocol("WM_DELETE_WINDOW", self._close_about)

        container = tk.Frame(window, bd=1, relief="raised", bg="#f0f0f0", padx=18, pady=16)
        container.pack(fill="both", expand=True, padx=10, pady=10)

        tk.Label(
            container,
            text="Credits: HeitorSpectre, Giga and TicoDoido [GameLab Traduções]",
            anchor="w",
            justify="left",
            bg="#f0f0f0",
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w")
        tk.Label(
            container,
            text="Special Thanks: RAGE Console Texture Editor, SparkIV and IVPC2Xbox",
            anchor="w",
            justify="left",
            bg="#f0f0f0",
            font=("Segoe UI", 9),
            pady=8,
        ).pack(anchor="w")
        tk.Label(
            container,
            text="© Texture Model Tool - GTA IV",
            anchor="w",
            justify="left",
            bg="#f0f0f0",
            font=("Segoe UI", 9),
        ).pack(anchor="w")

        tk.Button(container, text="Close", width=10, command=self._close_about).pack(anchor="e", pady=(14, 0))

        window.update_idletasks()
        width = window.winfo_width()
        height = window.winfo_height()
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - width) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - height) // 2)
        window.geometry(f"{width}x{height}+{x}+{y}")
        window.grab_set()
        window.focus_force()

    def _close_about(self) -> None:
        if self.about_window is None:
            return
        if self.about_window.winfo_exists():
            self.about_window.grab_release()
            self.about_window.destroy()
        self.about_window = None

    def _update_status(self) -> None:
        if not self.texture_summaries or self.backend.current_path is None:
            self.status_var.set("Open a PS3 .cdr, PC .wdr or Xbox .xdr file to inspect embedded textures.")
            return

        dirty_suffix = " [modified]" if self.backend.has_unsaved_changes else ""
        platform_suffix = f" [{self.backend.get_platform_label()}]"
        self.status_var.set(
            f"{self.backend.current_path.name} loaded with {len(self.texture_summaries)} texture(s)."
            f"{platform_suffix}{dirty_suffix}"
        )

    def _update_button_state(self) -> None:
        has_textures = bool(self.texture_summaries)
        has_selection = self.selected_texture is not None

        self.import_button.configure(state="normal" if has_selection else "disabled")
        self.export_button.configure(state="normal" if has_selection else "disabled")
        self.export_all_button.configure(state="normal" if has_textures else "disabled")
        self.save_button.configure(state="normal" if has_textures and self.backend.has_unsaved_changes else "disabled")
        self.save_as_button.configure(state="normal" if has_textures else "disabled")

    def on_close_requested(self) -> None:
        if not self._prompt_save_changes_if_needed():
            return
        self._close_about()
        self._cancel_thumbnail_loader()
        self.backend.close()
        self.root.destroy()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Python version of the GTA IV Model Texture Tool.")
    parser.add_argument("file", nargs="?", help="Optional .cdr/.wdr/.xdr file to open on launch.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    root = tk.Tk()
    project_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))

    try:
        app = TextureToolApp(root, project_root)
    except BackendUnavailableError as exc:
        root.withdraw()
        messagebox.showerror("Runtime Error", str(exc), parent=root)
        return 1

    if args.file:
        candidate = Path(args.file)
        if candidate.suffix.lower() not in SUPPORTED_EXTENSIONS:
            messagebox.showerror("Open File", "Only .cdr, .wdr, and .xdr files are supported.", parent=root)
        else:
            app.open_model(candidate)

    root.mainloop()
    return 0
