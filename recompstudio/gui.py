"""Tkinter desktop interface for RecompStudio.

All potentially long Git/build operations run on a worker thread; the UI stays responsive.
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .doctor import doctor_report
from .manager import FrameworkError, FrameworkManager
from .projects import (
    build_project, create_project, publish_project, push_project,
    recompile_project, set_project_inputs, update_project_framework,
)
from .registry import frameworks, refresh_catalog
from .toolchains import active_pack, install_latest, status as toolchain_status
from .bundles import bundled_toolchain
from .managed_tools import install_latest as install_managed_tool, status as managed_tool_status
from .startup import record_exception


class RecompStudioApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.report_callback_exception = self._report_tk_callback_exception
        self.manager = FrameworkManager()
        self.events: queue.Queue = queue.Queue()
        self.project_path: Path | None = None
        self.framework_rows: dict[str, str] = {}
        self.root.title(f"RecompStudio {__version__}")
        self.root.geometry("1120x760")
        self.root.minsize(900, 640)
        self._style()
        self._build()
        self.refresh_frameworks()
        self.root.after(120, self._poll_events)
        if bundled_toolchain() is not None:
            self.root.after(350, self._prepare_bundled_toolchain)

    def _report_tk_callback_exception(self, exc_type, exc_value, exc_traceback) -> None:
        log_path = record_exception(
            exc_value, context="GUI event callback", exc_traceback=exc_traceback
        )
        try:
            self._log(f"ERROR: An interface action failed. Details saved to {log_path}")
        except Exception:
            pass
        try:
            messagebox.showerror(
                "RecompStudio action failed",
                "An interface action failed. RecompStudio will remain open where possible. "
                f"Diagnostic details were saved to:\n\n{log_path}",
            )
        except tk.TclError:
            # Tk itself may be failing; the launcher will also capture an
            # exception that escapes the main event loop.
            pass

    def _style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        self.root.configure(bg="#10151f")
        style.configure(".", font=("Helvetica", 10))
        style.configure("TFrame", background="#10151f")
        style.configure("Panel.TFrame", background="#182131")
        style.configure("TLabel", background="#10151f", foreground="#e8edf5")
        style.configure("Muted.TLabel", background="#10151f", foreground="#98a6bb")
        style.configure("Title.TLabel", background="#10151f", foreground="#f4f7fb", font=("Helvetica", 22, "bold"))
        style.configure("Section.TLabel", background="#182131", foreground="#e8edf5", font=("Helvetica", 12, "bold"))
        style.configure("TButton", padding=(12, 7))
        style.configure("Accent.TButton", padding=(12, 7), font=("Helvetica", 10, "bold"))
        style.configure("Treeview", background="#182131", fieldbackground="#182131", foreground="#e8edf5", rowheight=28, borderwidth=0)
        style.configure("Treeview.Heading", background="#26354a", foreground="#eef3fa", padding=7)
        style.map("Treeview", background=[("selected", "#294a70")])
        style.configure("TNotebook", background="#10151f", borderwidth=0)
        style.configure("TNotebook.Tab", background="#1c293b", foreground="#c9d3e2", padding=(14, 9))
        style.map("TNotebook.Tab", background=[("selected", "#304967")], foreground=[("selected", "#ffffff")])
        style.configure("TEntry", fieldbackground="#182131", foreground="#e8edf5")
        style.configure("TCombobox", fieldbackground="#182131", foreground="#e8edf5")

    def _build(self) -> None:
        outer = ttk.Frame(self.root, padding=22)
        outer.pack(fill="both", expand=True)
        top = ttk.Frame(outer)
        top.pack(fill="x", pady=(0, 16))
        ttk.Label(top, text="RecompStudio", style="Title.TLabel").pack(side="left")
        ttk.Label(top, text="Framework manager · Project studio · CLI", style="Muted.TLabel").pack(side="left", padx=18, pady=(8, 0))
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(top, textvariable=self.status_var, style="Muted.TLabel").pack(side="right", pady=(8, 0))

        self.tabs = ttk.Notebook(outer)
        self.tabs.pack(fill="both", expand=True)
        self._build_home()
        self._build_frameworks()
        self._build_projects()
        self._build_tools()
        self._build_log(outer)

    def _build_home(self) -> None:
        page = ttk.Frame(self.tabs, padding=20)
        self.tabs.add(page, text="Overview")
        ttk.Label(page, text="One studio. Independent frameworks.", style="Title.TLabel").pack(anchor="w", pady=(2, 10))
        ttk.Label(
            page,
            text="Manage upstream recompilers, build game projects, and keep every framework revision under control.",
            style="Muted.TLabel", wraplength=900
        ).pack(anchor="w", pady=(0, 22))
        cards = ttk.Frame(page)
        cards.pack(fill="x", pady=(0, 18))
        for title, detail in (
            ("Frameworks", "Install and update each upstream separately. Local changes are never discarded."),
            ("Projects", "Create Git-ready game projects with a pinned framework submodule."),
            ("Three platforms", "Use the same project and CLI workflow on Windows, macOS, and Linux."),
        ):
            card = ttk.Frame(cards, style="Panel.TFrame", padding=16)
            card.pack(side="left", fill="both", expand=True, padx=(0, 10))
            ttk.Label(card, text=title, style="Section.TLabel").pack(anchor="w")
            ttk.Label(card, text=detail, background="#182131", foreground="#aebbd0", wraplength=260, justify="left").pack(anchor="w", pady=(8, 0))
        ttk.Label(page, text="Quick commands", style="Section.TLabel").pack(anchor="w", pady=(12, 8))
        commands = (
            "recompstudio frameworks list",
            "recompstudio frameworks update-all",
            "recompstudio project new --name MyGame --framework psxrecomp",
            "recompstudio doctor",
        )
        for command in commands:
            row = ttk.Frame(page, style="Panel.TFrame", padding=(12, 7))
            row.pack(fill="x", pady=3)
            ttk.Label(row, text=command, background="#182131", foreground="#dce8f7").pack(side="left")
            ttk.Button(row, text="Copy", command=lambda value=command: self._copy(value)).pack(side="right")

    def _build_frameworks(self) -> None:
        page = ttk.Frame(self.tabs, padding=16)
        self.tabs.add(page, text="Frameworks")
        toolbar = ttk.Frame(page)
        toolbar.pack(fill="x", pady=(0, 12))
        ttk.Button(toolbar, text="Refresh catalog", command=lambda: self._task("Refreshing catalog…", refresh_catalog)).pack(side="left")
        ttk.Button(toolbar, text="Check updates", command=lambda: self._task("Checking upstream…", lambda: self.manager.statuses(fetch=True), self._after_framework_task)).pack(side="left", padx=6)
        ttk.Button(toolbar, text="Update all installed", style="Accent.TButton", command=self._update_all).pack(side="right")
        table_frame = ttk.Frame(page)
        table_frame.pack(fill="both", expand=True)
        columns = ("platform", "category", "status", "version")
        self.framework_table = ttk.Treeview(table_frame, columns=columns, show="tree headings", selectmode="browse")
        self.framework_table.heading("#0", text="Framework / component")
        self.framework_table.column("#0", width=280, minwidth=200)
        for column, width in (("platform", 150), ("category", 140), ("status", 230), ("version", 110)):
            self.framework_table.heading(column, text=column.title())
            self.framework_table.column(column, width=width, minwidth=80)
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.framework_table.yview)
        self.framework_table.configure(yscrollcommand=scrollbar.set)
        self.framework_table.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        actions = ttk.Frame(page)
        actions.pack(fill="x", pady=(12, 0))
        ttk.Button(actions, text="Install selected", command=self._install_selected).pack(side="left")
        ttk.Button(actions, text="Update selected", command=self._update_selected).pack(side="left", padx=6)
        ttk.Button(actions, text="Open folder", command=self._open_framework).pack(side="left")
        ttk.Button(actions, text="Refresh view", command=self.refresh_frameworks).pack(side="right")

    def _build_projects(self) -> None:
        page = ttk.Frame(self.tabs, padding=18)
        self.tabs.add(page, text="Projects")
        ttk.Label(page, text="Create a new game project", style="Title.TLabel").pack(anchor="w", pady=(0, 14))
        form = ttk.Frame(page, style="Panel.TFrame", padding=16)
        form.pack(fill="x")
        self.name_var = tk.StringVar()
        self.framework_var = tk.StringVar()
        self.workspace_var = tk.StringVar(value=str(Path.home() / "RecompProjects"))
        self.input_var = tk.StringVar()
        self.bios_var = tk.StringVar()
        self.project_var = tk.StringVar(value="No project selected")
        self.commit_var = tk.StringVar(value="Update project")
        self.publish_var = tk.StringVar()
        self.visibility_var = tk.StringVar(value="private")
        self._form_row(form, 0, "Game / project name", ttk.Entry(form, textvariable=self.name_var, width=48))
        choices = [item["id"] for item in frameworks() if item.get("category") in {"framework", "integration-fork"}]
        self.framework_combo = ttk.Combobox(form, textvariable=self.framework_var, values=choices, state="readonly", width=45)
        self.framework_combo.grid(row=1, column=1, sticky="ew", pady=6)
        ttk.Label(form, text="Framework", background="#182131").grid(row=1, column=0, sticky="w", pady=6)
        self._form_row(form, 2, "Workspace folder", ttk.Entry(form, textvariable=self.workspace_var))
        ttk.Button(form, text="Browse", command=self._browse_workspace).grid(row=2, column=2, padx=6)
        self._form_row(form, 3, "Optional game image path", ttk.Entry(form, textvariable=self.input_var))
        ttk.Button(form, text="Browse", command=lambda: self._browse_file(self.input_var)).grid(row=3, column=2, padx=6)
        self._form_row(form, 4, "Optional BIOS / firmware path", ttk.Entry(form, textvariable=self.bios_var))
        ttk.Button(form, text="Browse", command=lambda: self._browse_file(self.bios_var)).grid(row=4, column=2, padx=6)
        form.columnconfigure(1, weight=1)
        ttk.Button(form, text="Create project", style="Accent.TButton", command=self._create_project).grid(row=5, column=1, sticky="e", pady=(14, 0))

        ttk.Label(page, text="Current project", style="Section.TLabel").pack(anchor="w", pady=(20, 6))
        current = ttk.Frame(page, style="Panel.TFrame", padding=12)
        current.pack(fill="x")
        ttk.Label(current, textvariable=self.project_var, background="#182131", wraplength=770).pack(side="left", fill="x", expand=True)
        ttk.Button(current, text="Open project…", command=self._choose_project).pack(side="right")
        buttons = ttk.Frame(page)
        buttons.pack(fill="x", pady=12)
        ttk.Button(buttons, text="Recompile", style="Accent.TButton", command=self._recompile_project).pack(side="left")
        ttk.Button(buttons, text="Build", command=self._build_project).pack(side="left", padx=6)
        ttk.Button(buttons, text="Update project framework", command=self._update_project_framework).pack(side="left")
        ttk.Button(buttons, text="Save local inputs", command=self._save_project_inputs).pack(side="left", padx=6)
        ttk.Button(buttons, text="Open in file manager", command=self._open_project).pack(side="right")
        publish = ttk.Frame(page, style="Panel.TFrame", padding=12)
        publish.pack(fill="x", pady=(8, 0))
        ttk.Label(publish, text="GitHub repository (owner/name)", background="#182131").grid(row=0, column=0, sticky="w")
        ttk.Entry(publish, textvariable=self.publish_var, width=38).grid(row=0, column=1, padx=8, sticky="ew")
        ttk.Combobox(publish, textvariable=self.visibility_var, values=["private", "public"], state="readonly", width=10).grid(row=0, column=2, padx=6)
        ttk.Button(publish, text="Create GitHub repo + push", command=self._publish_project).grid(row=0, column=3, padx=6)
        publish.columnconfigure(1, weight=1)
        ttk.Label(page, text="Publishing uses the GitHub CLI (gh) and the authenticated account. Private is the default.", style="Muted.TLabel").pack(anchor="w", pady=8)

    def _form_row(self, parent, row, label, widget) -> None:
        ttk.Label(parent, text=label, background="#182131").grid(row=row, column=0, sticky="w", pady=6)
        widget.grid(row=row, column=1, sticky="ew", pady=6)

    def _build_tools(self) -> None:
        page = ttk.Frame(self.tabs, padding=18)
        self.tabs.add(page, text="Toolchain")
        ttk.Label(page, text="Local build environment", style="Title.TLabel").pack(anchor="w", pady=(0, 12))
        ttk.Label(page, text="Detect the compiler and utilities each framework may need. RecompStudio reports missing tools but does not run privileged installers.", style="Muted.TLabel", wraplength=900).pack(anchor="w")
        tool_actions = ttk.Frame(page)
        tool_actions.pack(fill="x", pady=12)
        ttk.Button(tool_actions, text="Install / update shared toolchain", style="Accent.TButton", command=self._install_toolchain).pack(side="left")
        ttk.Button(tool_actions, text="Install Git + GitHub CLI", command=self._install_git_tools).pack(side="left", padx=8)
        ttk.Button(tool_actions, text="Install Java 21 + Ghidra", command=self._install_reverse_engineering_tools).pack(side="left", padx=8)
        ttk.Button(tool_actions, text="Run environment check", command=self._check_tools).pack(side="left", padx=8)
        self.tools_text = tk.Text(page, height=17, bg="#182131", fg="#e8edf5", insertbackground="white", relief="flat", wrap="word", padx=12, pady=12)
        self.tools_text.pack(fill="both", expand=True)
        self.tools_text.insert("1.0", "Select Run environment check to inspect Git, Python, CMake, Ninja, native compilers, Java, Ghidra, and GitHub CLI.")

    def _build_log(self, parent: ttk.Frame) -> None:
        frame = ttk.Frame(parent, style="Panel.TFrame", padding=(10, 7))
        frame.pack(fill="x", pady=(12, 0))
        title = ttk.Frame(frame, style="Panel.TFrame")
        title.pack(fill="x")
        ttk.Label(title, text="Activity", style="Section.TLabel").pack(side="left")
        ttk.Button(title, text="Clear", command=self._clear_log).pack(side="right")
        self.log = tk.Text(frame, height=5, bg="#10151f", fg="#b7c5d9", insertbackground="white", relief="flat", wrap="word", padx=8, pady=6)
        self.log.pack(fill="x", pady=(5, 0))
        self._log("Ready. Select a framework or create a project to get started.")

    def _log(self, message: str) -> None:
        self.log.insert("end", message.rstrip() + "\n")
        self.log.see("end")

    def _clear_log(self) -> None:
        self.log.delete("1.0", "end")

    def _copy(self, value: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(value)
        self.status_var.set("Copied command")

    def _task(self, label: str, operation, callback=None) -> None:
        self.status_var.set(label)
        self._log(label)

        def run():
            try:
                result = operation()
                self.events.put(("success", result, callback))
            except Exception as exc:
                self.events.put(("error", str(exc), callback))

        threading.Thread(target=run, daemon=True).start()

    def _poll_events(self) -> None:
        try:
            while True:
                kind, result, callback = self.events.get_nowait()
                if kind == "progress":
                    self.status_var.set(str(result))
                    continue
                if kind == "success":
                    self.status_var.set("Complete")
                    if isinstance(result, str) and result:
                        self._log(result)
                    elif isinstance(result, list):
                        self._log(f"Completed. {len(result)} result(s).")
                    elif isinstance(result, tuple):
                        self._log("Update operation finished.")
                    elif isinstance(result, dict):
                        self._log(f"Catalog refreshed: {len(result.get('frameworks', []))} entries.")
                    if callback:
                        callback(result)
                    if kind == "success" and callback is None:
                        self.refresh_frameworks()
                else:
                    self.status_var.set("Action failed")
                    self._log("ERROR: " + result)
                    if callback:
                        callback(None)
                    messagebox.showerror("RecompStudio", result)
        except queue.Empty:
            pass
        self.root.after(120, self._poll_events)

    def refresh_frameworks(self) -> None:
        self.framework_table.delete(*self.framework_table.get_children())
        self.framework_rows.clear()
        for item in frameworks():
            status = self.manager.status_one(str(item["id"]))
            iid = str(item["id"])
            self.framework_table.insert(
                "", "end", iid=iid,
                text=item["name"],
                values=(item.get("platform", ""), item.get("category", ""), status.summary, status.commit or "—")
            )
            self.framework_rows[iid] = iid

    def _selected_framework(self) -> str | None:
        selected = self.framework_table.selection()
        return selected[0] if selected else None

    def _install_selected(self) -> None:
        selected = self._selected_framework()
        if not selected:
            messagebox.showinfo("Choose a framework", "Select a framework or shared component first.")
            return
        self._task(f"Installing {selected}…", lambda: str(self.manager.install(selected)))

    def _update_selected(self) -> None:
        selected = self._selected_framework()
        if not selected:
            messagebox.showinfo("Choose a framework", "Select a framework or shared component first.")
            return
        self._task(f"Updating {selected}…", lambda: self.manager.update(selected))

    def _update_all(self) -> None:
        if not messagebox.askyesno("Update installed frameworks", "Fetch and fast-forward every installed framework? Local changes will be preserved and block that framework's update."):
            return
        self._task("Updating installed frameworks…", self.manager.update_all)

    def _after_framework_task(self, _result) -> None:
        self.refresh_frameworks()

    def _open_path(self, path: Path) -> None:
        try:
            if sys.platform == "win32":
                os.startfile(str(path))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            messagebox.showerror("Cannot open folder", str(exc))

    def _open_framework(self) -> None:
        selected = self._selected_framework()
        if not selected:
            return
        try:
            self._open_path(self.manager.open_folder(selected))
        except FrameworkError as exc:
            messagebox.showerror("Framework not installed", str(exc))

    def _browse_workspace(self) -> None:
        path = filedialog.askdirectory(initialdir=self.workspace_var.get() or str(Path.home()))
        if path:
            self.workspace_var.set(path)

    def _browse_file(self, variable: tk.StringVar) -> None:
        path = filedialog.askopenfilename()
        if path:
            variable.set(path)

    def _create_project(self) -> None:
        name = self.name_var.get().strip()
        framework_id = self.framework_var.get().strip()
        if not name or not framework_id:
            messagebox.showwarning("Project details required", "Enter a project name and choose a framework.")
            return

        def create():
            path = create_project(
                name, framework_id, Path(self.workspace_var.get()),
                Path(self.input_var.get()) if self.input_var.get().strip() else None,
                Path(self.bios_var.get()) if self.bios_var.get().strip() else None,
            )
            return str(path)

        self._task("Creating Git-ready project…", create, self._project_created)

    def _project_created(self, result) -> None:
        if result:
            self.project_path = Path(result)
            self.project_var.set(str(self.project_path))
            self._log("Project scaffold created. Complete the upstream game-specific setup before building.")

    def _choose_project(self) -> None:
        path = filedialog.askdirectory(title="Select a RecompStudio project")
        if path:
            self.project_path = Path(path)
            self.project_var.set(path)
            self._log(f"Selected project: {path}")

    def _recompile_project(self) -> None:
        if not self._require_project():
            return
        self._task("Running framework recompiler…", lambda: recompile_project(self.project_path))

    def _build_project(self) -> None:
        if not self._require_project():
            return
        self._task("Building game project…", lambda: build_project(self.project_path))

    def _save_project_inputs(self) -> None:
        if not self._require_project():
            return
        game_input = Path(self.input_var.get()).expanduser() if self.input_var.get().strip() else None
        bios_input = Path(self.bios_var.get()).expanduser() if self.bios_var.get().strip() else None
        if game_input is None and bios_input is None:
            messagebox.showinfo("No paths selected", "Choose a game image and/or BIOS path in the fields above first.")
            return
        self._task(
            "Saving host-local input paths…",
            lambda: (set_project_inputs(self.project_path, game_input, bios_input), "Local input paths saved; they are excluded from Git.")[1],
        )

    def _update_project_framework(self) -> None:
        if not self._require_project():
            return
        if not messagebox.askyesno("Update pinned framework", "Advance this game's framework submodule? The resulting pointer change must be committed to the game repository."):
            return
        self._task("Updating project framework…", lambda: update_project_framework(self.project_path))

    def _open_project(self) -> None:
        if self._require_project():
            self._open_path(self.project_path)

    def _publish_project(self) -> None:
        if not self._require_project():
            return
        repository = self.publish_var.get().strip()
        if not repository:
            messagebox.showwarning("Repository name required", "Enter a GitHub owner/repository name.")
            return
        visibility = self.visibility_var.get()
        if not messagebox.askyesno("Create GitHub repository", f"Create {repository} as {visibility} and push this project using gh?"):
            return
        self._task("Publishing project to GitHub…", lambda: publish_project(self.project_path, repository, visibility))

    def _require_project(self) -> bool:
        if self.project_path is None:
            messagebox.showinfo("No project selected", "Create or open a RecompStudio project first.")
            return False
        return True


    def _prepare_bundled_toolchain(self) -> None:
        try:
            current = active_pack()
        except Exception:
            current = None
        if current is not None:
            return

        def install():
            def status(message):
                self.events.put(("progress", message, None))
            return str(install_latest(status=status))

        self._task(
            "Preparing the bundled compiler toolchain…",
            install,
            lambda result: self._check_tools() if result else None,
        )

    def _install_toolchain(self) -> None:
        def install():
            def progress(done, total):
                if total and (done == total or done % (8 * 1024 * 1024) < 1024 * 1024):
                    message = f"Downloading shared toolchain: {done // (1024 * 1024)} / {total // (1024 * 1024)} MB"
                    self.events.put(("progress", message, None))
            return str(install_latest(progress=progress))

        self._task("Checking shared toolchain release…", install, lambda result: self._check_tools() if result else None)

    def _install_git_tools(self) -> None:
        def install():
            def status(message):
                self.events.put(("progress", message, None))
            git_path = install_managed_tool("git", status=status)
            gh_path = install_managed_tool("github-cli", status=status)
            return (
                f"Git: {git_path}\nGitHub CLI: {gh_path}\n"
                "Sign in from a terminal with: recompstudio tools auth"
            )

        self._task("Preparing Git and GitHub CLI…", install,
                   lambda result: self._check_tools() if result else None)

    def _install_reverse_engineering_tools(self) -> None:
        def install():
            def progress(done, total):
                if total and (done == total or done % (16 * 1024 * 1024) < 1024 * 1024):
                    message = f"Downloading reverse-engineering tools: {done // (1024 * 1024)} / {total // (1024 * 1024)} MB"
                    self.events.put(("progress", message, None))
            def status(message):
                self.events.put(("progress", message, None))
            result = install_managed_tool("reverse-engineering", progress=progress, status=status)
            return "\n".join(f"{name}: {path}" for name, path in result.items())

        self._task("Downloading Java 21 and Ghidra…", install,
                   lambda result: self._check_tools() if result else None)

    def _check_tools(self) -> None:
        report = doctor_report()
        pack = report.get("shared_toolchain", {})
        managed = report.get("managed_tools", {})
        lines = [
            f"Platform: {report['platform']}",
            f"Python: {report['python']}",
            f"Shared RetComM toolchain: {'installed' if pack.get('installed') else 'not installed'}",
            f"Toolchain version: {pack.get('version') or '—'}",
            f"Toolchain path: {pack.get('path') or '—'}",
            "",
            "Managed optional tools:",
            *[
                f"  {name}: {'FOUND' if info.get('installed') else 'MISSING'}"
                + (f" ({'managed ' if info.get('managed') else ''}{info.get('version') or info.get('path')})"
                   if info.get('version') or info.get('path') else "")
                for name, info in managed.items()
            ],
            "",
        ]
        for item in report["checks"]:
            state = "FOUND" if item["found"] else "MISSING"
            line = f"[{state}] {item['name']}"
            if item["version"]:
                line += " — " + item["version"]
            if item["required_for"]:
                line += "\n    " + item["required_for"]
            lines.append(line)
        lines.extend(["", report["guidance"], "", report["note"]])
        self.tools_text.delete("1.0", "end")
        self.tools_text.insert("1.0", "\n".join(lines))
        self._log("Environment check complete.")

    def run(self) -> None:
        self.root.mainloop()


def launch() -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        raise RuntimeError(
            "The desktop GUI could not start. Install a Python distribution with Tkinter; "
            "the RecompStudio CLI remains available."
        ) from exc
    app = RecompStudioApp(root)
    app.run()
