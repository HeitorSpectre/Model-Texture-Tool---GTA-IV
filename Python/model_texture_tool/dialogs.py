from __future__ import annotations

import subprocess
from pathlib import Path
from tkinter import filedialog


def open_file(*, title: str, filter_text: str, initial_path: str | Path | None = None, file_name: str | None = None) -> str | None:
    script = _build_open_file_script(title, filter_text, initial_path, file_name)
    selected = _run_powershell_dialog(script)
    if selected is not None:
        return selected or None
    return _fallback_open_file(title=title, initial_path=initial_path, file_name=file_name)


def save_file(
    *,
    title: str,
    filter_text: str,
    default_extension: str | None = None,
    initial_path: str | Path | None = None,
    file_name: str | None = None,
) -> str | None:
    script = _build_save_file_script(title, filter_text, default_extension, initial_path, file_name)
    selected = _run_powershell_dialog(script)
    if selected is not None:
        return selected or None
    return _fallback_save_file(
        title=title,
        initial_path=initial_path,
        file_name=file_name,
        default_extension=default_extension,
    )


def choose_folder(*, description: str, initial_path: str | Path | None = None) -> str | None:
    script = _build_folder_script(description, initial_path)
    selected = _run_powershell_dialog(script)
    if selected is not None:
        return selected or None
    return filedialog.askdirectory(
        title=description,
        initialdir=_initial_dir(initial_path),
    ) or None


def _run_powershell_dialog(script: str) -> str | None:
    try:
        startupinfo = None
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if hasattr(subprocess, "STARTUPINFO"):
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0

        completed = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
            startupinfo=startupinfo,
            creationflags=creationflags,
        )
    except Exception:
        return None

    if completed.returncode != 0:
        return None

    # Empty stdout with exit code 0 means the user cancelled the native dialog.
    # Returning an empty string prevents us from opening the tkinter fallback.
    return (completed.stdout or "").strip()


def _build_open_file_script(title: str, filter_text: str, initial_path: str | Path | None, file_name: str | None) -> str:
    title_ps = _ps_string(title)
    filter_ps = _ps_string(filter_text)
    initial_dir = _ps_string(_initial_dir(initial_path))
    file_name_ps = _ps_string(file_name or "")
    return f"""
Add-Type -AssemblyName PresentationFramework
$dialog = New-Object Microsoft.Win32.OpenFileDialog
$dialog.Title = '{title_ps}'
$dialog.Filter = '{filter_ps}'
$dialog.Multiselect = $false
if ('{initial_dir}' -ne '') {{ $dialog.InitialDirectory = '{initial_dir}' }}
if ('{file_name_ps}' -ne '') {{ $dialog.FileName = '{file_name_ps}' }}
$result = $dialog.ShowDialog()
if ($result -eq $true) {{ [Console]::Out.Write($dialog.FileName) }}
"""


def _build_save_file_script(
    title: str,
    filter_text: str,
    default_extension: str | None,
    initial_path: str | Path | None,
    file_name: str | None,
) -> str:
    title_ps = _ps_string(title)
    filter_ps = _ps_string(filter_text)
    initial_dir = _ps_string(_initial_dir(initial_path))
    file_name_ps = _ps_string(file_name or "")
    default_ext_ps = _ps_string((default_extension or "").lstrip("."))
    return f"""
Add-Type -AssemblyName PresentationFramework
$dialog = New-Object Microsoft.Win32.SaveFileDialog
$dialog.Title = '{title_ps}'
$dialog.Filter = '{filter_ps}'
$dialog.OverwritePrompt = $true
$dialog.AddExtension = $true
if ('{default_ext_ps}' -ne '') {{ $dialog.DefaultExt = '{default_ext_ps}' }}
if ('{initial_dir}' -ne '') {{ $dialog.InitialDirectory = '{initial_dir}' }}
if ('{file_name_ps}' -ne '') {{ $dialog.FileName = '{file_name_ps}' }}
$result = $dialog.ShowDialog()
if ($result -eq $true) {{ [Console]::Out.Write($dialog.FileName) }}
"""


def _build_folder_script(description: str, initial_path: str | Path | None) -> str:
    description_ps = _ps_string(description)
    initial_dir = _ps_string(_initial_dir(initial_path))
    return f"""
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = '{description_ps}'
$dialog.ShowNewFolderButton = $true
if ('{initial_dir}' -ne '') {{ $dialog.SelectedPath = '{initial_dir}' }}
$result = $dialog.ShowDialog()
if ($result -eq [System.Windows.Forms.DialogResult]::OK) {{ [Console]::Out.Write($dialog.SelectedPath) }}
"""


def _fallback_open_file(*, title: str, initial_path: str | Path | None, file_name: str | None) -> str | None:
    return filedialog.askopenfilename(
        title=title,
        initialdir=_initial_dir(initial_path),
        initialfile=file_name or "",
    ) or None


def _fallback_save_file(
    *,
    title: str,
    initial_path: str | Path | None,
    file_name: str | None,
    default_extension: str | None,
) -> str | None:
    return filedialog.asksaveasfilename(
        title=title,
        initialdir=_initial_dir(initial_path),
        initialfile=file_name or "",
        defaultextension=default_extension or "",
    ) or None


def _initial_dir(initial_path: str | Path | None) -> str:
    if not initial_path:
        return ""
    path = Path(initial_path)
    if path.is_dir():
        return str(path)
    return str(path.parent)


def _ps_string(value: str) -> str:
    return value.replace("'", "''")
