from __future__ import annotations

import os
import queue
import json
import subprocess
import threading
import webbrowser
from pathlib import Path
from tkinter import BooleanVar, IntVar, StringVar, Tk, messagebox
from tkinter import ttk
import tkinter as tk
from PIL import Image, ImageTk


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
OUTPUTS = ROOT / "outputs"
POST_NOW = OUTPUTS / "_postar_agora"
REPORTS = OUTPUTS / "relatorios" / "opus-local"
PREVIEW = OUTPUTS / "relatorios" / "pre-aprovacao"


COLORS = {
    "bg": "#eef3fb",
    "panel": "#ffffff",
    "sidebar": "#070b18",
    "sidebar_soft": "#121a2d",
    "text": "#111827",
    "muted": "#6b7280",
    "line": "#dce3ee",
    "accent": "#ff245b",
    "accent_dark": "#d9164a",
    "dark": "#0b1220",
    "success": "#0f9f6e",
    "blue": "#3563ff",
    "purple": "#7c3aed",
    "soft_blue": "#eaf0ff",
    "soft_green": "#e8fff5",
}


class PoderEmJogoApp:
    def __init__(self) -> None:
        self.root = Tk()
        self.root.title("Poder em Jogo Studio")
        self.root.geometry("1280x820")
        self.root.minsize(1120, 720)
        self.root.configure(bg=COLORS["bg"])

        self.url = StringVar()
        self.count = IntVar(value=3)
        self.min_score = IntVar(value=75)
        self.min_duration = IntVar(value=45)
        self.max_duration = IntVar(value=70)
        self.ai_mode = StringVar(value="auto")
        self.quality = StringVar(value="alta")
        self.focus = StringVar(value="auto")
        self.preview_only = BooleanVar(value=False)
        self.burn_subtitles = BooleanVar(value=False)
        self.cut_pauses = BooleanVar(value=False)
        self.allow_low_quality = BooleanVar(value=False)
        self.show_hook = BooleanVar(value=False)
        self.render_candidate = IntVar(value=0)
        self.status = StringVar(value="Pronto para criar cortes")
        self.progress = IntVar(value=0)
        self.progress_text = StringVar(value="Aguardando link")
        self.progress_percent = StringVar(value="0%")

        self.process: subprocess.Popen | None = None
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.log_lines: list[str] = []
        self.video_items: dict[str, Path] = {}
        self.candidate_items: dict[str, dict] = {}
        self.latest_candidates_json: Path | None = None
        self.preview_image = None
        self.pending_urls: list[str] = []
        self.current_url: str | None = None
        self.stage_labels: list[tk.Label] = []

        self._configure_style()
        self._build_ui()
        self.root.after(120, self._drain_logs)

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", font=("Segoe UI", 10), background=COLORS["bg"], foreground=COLORS["text"])
        style.configure("Card.TFrame", background=COLORS["panel"], relief="flat")
        style.configure("Muted.TLabel", background=COLORS["panel"], foreground=COLORS["muted"])
        style.configure("CardTitle.TLabel", background=COLORS["panel"], foreground=COLORS["text"], font=("Segoe UI", 13, "bold"))
        style.configure("Big.TLabel", background=COLORS["bg"], foreground=COLORS["text"], font=("Segoe UI", 22, "bold"))
        style.configure("Sub.TLabel", background=COLORS["bg"], foreground=COLORS["muted"], font=("Segoe UI", 10))
        style.configure("Accent.TButton", background=COLORS["accent"], foreground="#ffffff", borderwidth=0, padding=(18, 10), font=("Segoe UI", 10, "bold"))
        style.map("Accent.TButton", background=[("active", COLORS["accent_dark"]), ("pressed", COLORS["accent_dark"])])
        style.configure("Soft.TButton", background="#eef2f7", foreground=COLORS["text"], borderwidth=0, padding=(14, 9))
        style.map("Soft.TButton", background=[("active", "#e3e9f2")])
        style.configure("Danger.TButton", background="#fee2e2", foreground="#991b1b", borderwidth=0, padding=(14, 9))
        style.map("Danger.TButton", background=[("active", "#fecaca")])
        style.configure("TEntry", fieldbackground="#ffffff", bordercolor=COLORS["line"], lightcolor=COLORS["line"], darkcolor=COLORS["line"], padding=7)
        style.configure("TCombobox", fieldbackground="#ffffff", bordercolor=COLORS["line"], padding=5)
        style.configure("TSpinbox", fieldbackground="#ffffff", bordercolor=COLORS["line"], padding=5)
        style.configure("TCheckbutton", background=COLORS["panel"], foreground=COLORS["text"])
        style.configure("Treeview", background="#ffffff", fieldbackground="#ffffff", foreground=COLORS["text"], rowheight=32, borderwidth=0)
        style.configure("Treeview.Heading", background="#f1f5fb", foreground=COLORS["muted"], font=("Segoe UI", 9, "bold"), padding=8)
        style.map("Treeview", background=[("selected", COLORS["soft_blue"])], foreground=[("selected", COLORS["text"])])
        style.configure("TNotebook", background=COLORS["panel"], borderwidth=0)
        style.configure("TNotebook.Tab", background="#eef2f7", foreground=COLORS["muted"], padding=(18, 9), font=("Segoe UI", 10, "bold"))
        style.map("TNotebook.Tab", background=[("selected", "#ffffff")], foreground=[("selected", COLORS["text"])])
        style.configure("Modern.Horizontal.TProgressbar", troughcolor="#e5eaf3", background=COLORS["accent"], bordercolor="#e5eaf3", lightcolor=COLORS["accent"], darkcolor=COLORS["accent"])

    def _build_ui(self) -> None:
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        self._build_sidebar()

        main = ttk.Frame(self.root, padding=22)
        main.grid(row=0, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(5, weight=1)

        hero = tk.Frame(main, bg=COLORS["bg"])
        hero.grid(row=0, column=0, rowspan=2, sticky="ew", pady=(0, 18))
        hero.columnconfigure(0, weight=1)
        tk.Label(hero, text="Criar cortes virais", bg=COLORS["bg"], fg=COLORS["text"], font=("Segoe UI", 26, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(
            hero,
            text="Analise podcasts, aprove candidatos e gere pacotes prontos para TikTok.",
            bg=COLORS["bg"],
            fg=COLORS["muted"],
            font=("Segoe UI", 11),
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))
        tk.Label(hero, text="Studio Beta", bg=COLORS["soft_blue"], fg=COLORS["blue"], padx=12, pady=6, font=("Segoe UI", 9, "bold")).grid(row=0, column=1, sticky="e")

        self._build_link_card(main)
        self._build_settings_card(main)
        self._build_action_bar(main)
        self._build_progress_card(main)

    def _build_sidebar(self) -> None:
        sidebar = tk.Frame(self.root, bg=COLORS["sidebar"], width=245)
        sidebar.grid(row=0, column=0, sticky="ns")
        sidebar.grid_propagate(False)

        tk.Label(sidebar, text="Poder em Jogo", bg=COLORS["sidebar"], fg="#ffffff", font=("Segoe UI", 18, "bold")).pack(anchor="w", padx=22, pady=(24, 4))
        tk.Label(sidebar, text="@poderemjogo", bg=COLORS["sidebar"], fg="#9ca3af", font=("Segoe UI", 10)).pack(anchor="w", padx=22)

        tk.Frame(sidebar, bg="#243044", height=1).pack(fill="x", padx=18, pady=22)
        self._side_button(sidebar, "Novo corte", self._focus_url, active=True)
        self._side_button(sidebar, "Postar agora", lambda: self._open_path(POST_NOW))
        self._side_button(sidebar, "Relatorios", lambda: self._open_path(REPORTS / "ultimos-cortes.md"))
        self._side_button(sidebar, "Pre-aprovacao", lambda: self._open_path(PREVIEW))
        self._side_button(sidebar, "Outputs", lambda: self._open_path(OUTPUTS))

        tk.Frame(sidebar, bg=COLORS["sidebar"]).pack(expand=True, fill="both")
        status_box = tk.Frame(sidebar, bg=COLORS["sidebar_soft"])
        status_box.pack(fill="x", padx=16, pady=16)
        tk.Label(status_box, text="STATUS", bg=COLORS["sidebar_soft"], fg="#9ca3af", font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=12, pady=(10, 0))
        tk.Label(status_box, textvariable=self.status, bg=COLORS["sidebar_soft"], fg="#ffffff", wraplength=190, justify="left").pack(anchor="w", padx=12, pady=(3, 12))

    def _side_button(self, parent: tk.Frame, text: str, command, active: bool = False) -> None:
        bg = COLORS["accent"] if active else COLORS["sidebar"]
        fg = "#ffffff" if active else "#d1d5db"
        button = tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=COLORS["accent_dark"] if active else COLORS["sidebar_soft"],
            activeforeground="#ffffff",
            relief="flat",
            anchor="w",
            padx=16,
            pady=10,
            font=("Segoe UI", 10, "bold" if active else "normal"),
            cursor="hand2",
        )
        button.pack(fill="x", padx=14, pady=3)

    def _card(self, parent: ttk.Frame, row: int, title: str, subtitle: str) -> ttk.Frame:
        outer = tk.Frame(parent, bg=COLORS["panel"], padx=18, pady=16, highlightbackground="#e1e8f3", highlightthickness=1)
        outer.grid(row=row, column=0, sticky="ew", pady=(0, 14))
        outer.columnconfigure(0, weight=1)
        tk.Label(outer, text=title, bg=COLORS["panel"], fg=COLORS["text"], font=("Segoe UI", 13, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(outer, text=subtitle, bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 10)).grid(row=1, column=0, sticky="w", pady=(1, 12))
        return outer

    def _build_link_card(self, parent: ttk.Frame) -> None:
        card = self._card(parent, 2, "1. Link do podcast", "Use videos longos com conversa real. O robo baixa, transcreve e procura os melhores momentos.")
        row = ttk.Frame(card, style="Card.TFrame")
        row.grid(row=2, column=0, sticky="ew")
        row.columnconfigure(0, weight=1)
        self.url_entry = ttk.Entry(row, textvariable=self.url, font=("Segoe UI", 11))
        self.url_entry.grid(row=0, column=0, sticky="ew", padx=(0, 10), ipady=4)
        ttk.Button(row, text="Colar link", style="Soft.TButton", command=self._paste_url).grid(row=0, column=1)
        ttk.Button(row, text="Adicionar fila", style="Soft.TButton", command=self._add_to_queue).grid(row=0, column=2, padx=(10, 0))
        ttk.Button(row, text="Gerar cortes", style="Accent.TButton", command=self._run).grid(row=0, column=3, padx=(10, 0))

        queue_row = ttk.Frame(card, style="Card.TFrame")
        queue_row.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        queue_row.columnconfigure(0, weight=1)
        ttk.Label(queue_row, text="Fila de producao", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(queue_row, text="Remover selecionado", style="Soft.TButton", command=self._remove_from_queue).grid(row=0, column=1, padx=(10, 0))
        self.queue_list = tk.Listbox(queue_row, height=3, relief="flat", bg="#f8fafc", fg=COLORS["text"], selectbackground=COLORS["accent"])
        self.queue_list.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))

    def _build_settings_card(self, parent: ttk.Frame) -> None:
        card = self._card(parent, 3, "2. Configuracao do corte", "Padrao recomendado: score 75, 45 a 70 segundos, qualidade alta e foco automatico.")
        grid = ttk.Frame(card, style="Card.TFrame")
        grid.grid(row=2, column=0, sticky="ew")
        for idx in range(6):
            grid.columnconfigure(idx, weight=1)

        self._spin(grid, "Cortes", self.count, 1, 8, 0)
        self._spin(grid, "Score minimo", self.min_score, 0, 100, 1)
        self._spin(grid, "Min seg", self.min_duration, 20, 120, 2)
        self._spin(grid, "Max seg", self.max_duration, 20, 180, 3)
        self._combo(grid, "IA editorial", self.ai_mode, ("auto", "off", "required"), 4)
        self._combo(grid, "Qualidade", self.quality, ("alta", "tiktok", "4k"), 5)

        grid2 = ttk.Frame(card, style="Card.TFrame")
        grid2.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        for idx in range(6):
            grid2.columnconfigure(idx, weight=1)
        self._combo(grid2, "Foco do rosto", self.focus, ("auto", "left", "center", "right"), 0)
        self._spin(grid2, "Render candidato", self.render_candidate, 0, 20, 1)
        ttk.Checkbutton(grid2, text="So pre-aprovacao", variable=self.preview_only).grid(row=0, column=2, sticky="w", padx=8)
        ttk.Checkbutton(grid2, text="Legenda no video", variable=self.burn_subtitles).grid(row=0, column=3, sticky="w", padx=8)
        ttk.Checkbutton(grid2, text="Cortar pausas", variable=self.cut_pauses).grid(row=0, column=4, sticky="w", padx=8)
        ttk.Checkbutton(grid2, text="Aceitar baixa qualidade", variable=self.allow_low_quality).grid(row=0, column=5, sticky="w", padx=8)

    def _build_action_bar(self, parent: ttk.Frame) -> None:
        bar = ttk.Frame(parent)
        bar.grid(row=4, column=0, sticky="ew", pady=(0, 14))
        bar.columnconfigure(0, weight=1)
        ttk.Button(bar, text="Gerar cortes agora", style="Accent.TButton", command=self._run).grid(row=0, column=0, sticky="w")
        ttk.Button(bar, text="Analisar candidatos", style="Soft.TButton", command=self._run_preview).grid(row=0, column=1, padx=(10, 0))
        ttk.Button(bar, text="Parar", style="Danger.TButton", command=self._stop).grid(row=0, column=2, padx=(10, 0))
        ttk.Button(bar, text="Abrir pacote final", style="Soft.TButton", command=lambda: self._open_path(POST_NOW)).grid(row=0, column=3, padx=(10, 0))
        ttk.Button(bar, text="Abrir relatorio", style="Soft.TButton", command=lambda: self._open_path(REPORTS / "ultimos-cortes.md")).grid(row=0, column=4, padx=(10, 0))

    def _build_progress_card(self, parent: ttk.Frame) -> None:
        card = self._card(parent, 5, "3. Progresso e cortes", "Veja o andamento e abra os cortes prontos para assistir ou postar.")
        card.rowconfigure(4, weight=1)

        top = tk.Frame(card, bg=COLORS["dark"], padx=18, pady=16)
        top.grid(row=2, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)
        tk.Label(top, textvariable=self.progress_percent, bg=COLORS["dark"], fg="#ffffff", font=("Segoe UI", 30, "bold")).grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 18))
        tk.Label(top, textvariable=self.progress_text, bg=COLORS["dark"], fg="#ffffff", font=("Segoe UI", 13, "bold")).grid(row=0, column=1, sticky="w")
        tk.Label(top, textvariable=self.status, bg=COLORS["dark"], fg="#9ca3af", font=("Segoe UI", 9)).grid(row=0, column=2, sticky="e")
        self.progressbar = ttk.Progressbar(top, variable=self.progress, maximum=100, mode="determinate", style="Modern.Horizontal.TProgressbar")
        self.progressbar.grid(row=1, column=1, columnspan=2, sticky="ew", pady=(8, 0))

        stages = tk.Frame(top, bg=COLORS["dark"])
        stages.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(14, 0))
        for column in range(5):
            stages.columnconfigure(column, weight=1)
        self.stage_labels = []
        for idx, label in enumerate(["Fonte", "Transcricao", "Score", "Render", "Pronto"]):
            chip = tk.Label(
                stages,
                text=label,
                bg="#1f2937",
                fg="#9ca3af",
                padx=12,
                pady=7,
                font=("Segoe UI", 9, "bold"),
            )
            chip.grid(row=0, column=idx, sticky="ew", padx=4)
            self.stage_labels.append(chip)

        self.tabs = ttk.Notebook(card)
        self.tabs.grid(row=3, column=0, sticky="nsew", pady=(16, 0))

        self.preview_tab = ttk.Frame(self.tabs, style="Card.TFrame", padding=10)
        self.cuts_tab = ttk.Frame(self.tabs, style="Card.TFrame", padding=10)
        self.post_tab = ttk.Frame(self.tabs, style="Card.TFrame", padding=10)
        self.tabs.add(self.preview_tab, text="Previa Opus")
        self.tabs.add(self.cuts_tab, text="Cortes prontos")
        self.tabs.add(self.post_tab, text="Postagem")

        self._build_candidates_tab()
        self._build_cuts_tab()
        self._build_post_tab()
        self._refresh_candidates()
        self._refresh_videos()

    def _build_candidates_tab(self) -> None:
        self.preview_tab.columnconfigure(0, weight=1)
        self.preview_tab.columnconfigure(1, weight=1)
        self.preview_tab.rowconfigure(0, weight=1)

        left = ttk.Frame(self.preview_tab, style="Card.TFrame")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        self.candidates = ttk.Treeview(left, columns=("rank", "score", "duration", "title"), show="headings", height=9)
        self.candidates.heading("rank", text="#")
        self.candidates.heading("score", text="Score")
        self.candidates.heading("duration", text="Duracao")
        self.candidates.heading("title", text="Titulo")
        self.candidates.column("rank", width=45, anchor="center")
        self.candidates.column("score", width=70, anchor="center")
        self.candidates.column("duration", width=75, anchor="center")
        self.candidates.column("title", width=420)
        self.candidates.grid(row=0, column=0, sticky="nsew")
        self.candidates.bind("<<TreeviewSelect>>", lambda _event: self._show_candidate_details())
        candidate_scroll = ttk.Scrollbar(left, orient="vertical", command=self.candidates.yview)
        candidate_scroll.grid(row=0, column=1, sticky="ns")
        self.candidates.configure(yscrollcommand=candidate_scroll.set)

        right = ttk.Frame(self.preview_tab, style="Card.TFrame")
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        self.preview_label = tk.Label(right, text="Selecione um candidato", bg="#eef2f7", fg=COLORS["muted"], height=10)
        self.preview_label.grid(row=0, column=0, sticky="ew")
        self.candidate_title = StringVar(value="Nenhum candidato selecionado")
        ttk.Label(right, textvariable=self.candidate_title, style="CardTitle.TLabel", wraplength=430).grid(row=1, column=0, sticky="w", pady=(10, 4))
        self.candidate_meta = StringVar(value="")
        ttk.Label(right, textvariable=self.candidate_meta, style="Muted.TLabel", wraplength=430).grid(row=2, column=0, sticky="w")
        self.candidate_reason = tk.Text(right, height=5, wrap="word", bg="#f8fafc", fg=COLORS["text"], relief="flat", padx=8, pady=8)
        self.candidate_reason.grid(row=3, column=0, sticky="ew", pady=(8, 8))
        actions = ttk.Frame(right, style="Card.TFrame")
        actions.grid(row=4, column=0, sticky="ew")
        ttk.Button(actions, text="Aprovar", style="Accent.TButton", command=lambda: self._set_candidate_decision("APROVAR")).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Descartar", style="Danger.TButton", command=lambda: self._set_candidate_decision("REJEITAR")).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Renderizar", style="Soft.TButton", command=self._render_selected_candidate).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Atualizar", style="Soft.TButton", command=self._refresh_candidates).pack(side="left")

    def _build_cuts_tab(self) -> None:
        self.cuts_tab.columnconfigure(0, weight=1)
        self.cuts_tab.rowconfigure(0, weight=1)
        self.videos = ttk.Treeview(self.cuts_tab, columns=("score", "name", "folder"), show="headings", height=8)
        self.videos.heading("score", text="Score")
        self.videos.heading("name", text="Video")
        self.videos.heading("folder", text="Pasta")
        self.videos.column("score", width=70, anchor="center")
        self.videos.column("name", width=360)
        self.videos.column("folder", width=520)
        self.videos.grid(row=0, column=0, sticky="nsew")
        video_scroll = ttk.Scrollbar(self.cuts_tab, orient="vertical", command=self.videos.yview)
        video_scroll.grid(row=0, column=1, sticky="ns")
        self.videos.configure(yscrollcommand=video_scroll.set)
        buttons = ttk.Frame(self.cuts_tab, style="Card.TFrame")
        buttons.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        ttk.Button(buttons, text="Assistir corte", style="Accent.TButton", command=self._watch_selected).pack(side="left", padx=(0, 10))
        ttk.Button(buttons, text="Abrir legenda", style="Soft.TButton", command=self._open_selected_publication).pack(side="left", padx=(0, 10))
        ttk.Button(buttons, text="Abrir pasta", style="Soft.TButton", command=self._open_selected_folder).pack(side="left", padx=(0, 10))
        ttk.Button(buttons, text="Postar no TikTok", style="Soft.TButton", command=self._post_selected).pack(side="left", padx=(0, 10))
        ttk.Button(buttons, text="Atualizar lista", style="Soft.TButton", command=self._refresh_videos).pack(side="left", padx=(0, 10))
        ttk.Button(buttons, text="Detalhes tecnicos", style="Soft.TButton", command=self._show_details).pack(side="left")

    def _build_post_tab(self) -> None:
        self.post_tab.columnconfigure(0, weight=1)
        self.post_tab.rowconfigure(1, weight=1)
        ttk.Label(self.post_tab, text="Legenda, descricao e hashtags", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        self.post_text = tk.Text(self.post_tab, height=10, wrap="word", bg="#f8fafc", fg=COLORS["text"], relief="flat", padx=10, pady=10)
        self.post_text.grid(row=1, column=0, sticky="nsew", pady=(8, 10))
        buttons = ttk.Frame(self.post_tab, style="Card.TFrame")
        buttons.grid(row=2, column=0, sticky="ew")
        ttk.Button(buttons, text="Carregar do corte selecionado", style="Soft.TButton", command=self._load_post_from_selected).pack(side="left", padx=(0, 10))
        ttk.Button(buttons, text="Copiar texto", style="Accent.TButton", command=self._copy_post_text).pack(side="left", padx=(0, 10))
        ttk.Button(buttons, text="Abrir TikTok Studio", style="Soft.TButton", command=lambda: webbrowser.open("https://www.tiktok.com/tiktokstudio/upload")).pack(side="left")

    def _spin(self, parent: ttk.Frame, label: str, variable: IntVar, start: int, end: int, column: int) -> None:
        frame = ttk.Frame(parent, style="Card.TFrame")
        frame.grid(row=0, column=column, sticky="ew", padx=(0, 10))
        ttk.Label(frame, text=label, style="Muted.TLabel").pack(anchor="w")
        ttk.Spinbox(frame, from_=start, to=end, textvariable=variable, width=8).pack(fill="x", pady=(4, 0))

    def _combo(self, parent: ttk.Frame, label: str, variable: StringVar, values: tuple[str, ...], column: int) -> None:
        frame = ttk.Frame(parent, style="Card.TFrame")
        frame.grid(row=0, column=column, sticky="ew", padx=(0, 10))
        ttk.Label(frame, text=label, style="Muted.TLabel").pack(anchor="w")
        ttk.Combobox(frame, textvariable=variable, values=values, state="readonly", width=10).pack(fill="x", pady=(4, 0))

    def _focus_url(self) -> None:
        self.url_entry.focus_set()

    def _append_log(self, text: str) -> None:
        self.log_lines.append(text)

    def _set_progress(self, value: int, label: str | None = None) -> None:
        value = max(0, min(100, int(value)))
        self.progress.set(value)
        self.progress_percent.set(f"{value}%")
        if label:
            self.progress_text.set(label)
        self._update_stage_chips(value)

    def _update_stage_chips(self, value: int) -> None:
        thresholds = [8, 25, 45, 75, 100]
        for index, chip in enumerate(self.stage_labels):
            if value >= thresholds[index]:
                chip.configure(bg=COLORS["accent"], fg="#ffffff")
            elif index > 0 and value >= thresholds[index - 1]:
                chip.configure(bg=COLORS["blue"], fg="#ffffff")
            else:
                chip.configure(bg="#1f2937", fg="#9ca3af")

    def _paste_url(self) -> None:
        try:
            self.url.set(self.root.clipboard_get().strip())
        except Exception:
            messagebox.showwarning("Clipboard", "Nao consegui ler o texto copiado.")

    def _add_to_queue(self) -> None:
        url = self.url.get().strip()
        if not url:
            messagebox.showwarning("Fila", "Cole um link antes de adicionar.")
            return
        self.pending_urls.append(url)
        self.queue_list.insert("end", url)
        self.url.set("")
        self.status.set(f"{len(self.pending_urls)} link(s) na fila")

    def _remove_from_queue(self) -> None:
        selected = list(self.queue_list.curselection())
        for index in reversed(selected):
            self.queue_list.delete(index)
            if 0 <= index < len(self.pending_urls):
                self.pending_urls.pop(index)
        self.status.set(f"{len(self.pending_urls)} link(s) na fila")

    def _open_path(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True) if path.suffix else path.mkdir(parents=True, exist_ok=True)
        os.startfile(str(path))

    def _command(self) -> list[str]:
        if self.render_candidate.get() > 0:
            cmd = [str(PYTHON), str(ROOT / "src" / "render_candidate.py"), "--candidate", str(self.render_candidate.get())]
            preview_path = self.latest_candidates_json or self._latest_candidates_path()
            if preview_path:
                cmd.extend(["--preview-json", str(preview_path)])
            cmd.extend(["--quality", self.quality.get(), "--focus", self.focus.get()])
            if self.show_hook.get():
                cmd.append("--show-hook")
            return cmd

        url = self.current_url or self.url.get().strip()
        if not url:
            raise ValueError("Cole um link do YouTube.")

        cmd = [
            str(PYTHON),
            str(ROOT / "src" / "opus_local.py"),
            "--url",
            url,
            "--count",
            str(self.count.get()),
            "--min-score",
            str(self.min_score.get()),
            "--min-duration",
            str(self.min_duration.get()),
            "--max-duration",
            str(self.max_duration.get()),
            "--editorial-ai",
            self.ai_mode.get(),
            "--quality",
            self.quality.get(),
            "--focus",
            self.focus.get(),
        ]
        if self.preview_only.get():
            cmd.extend(["--preview-only", "--no-media-score"])
        if self.burn_subtitles.get():
            cmd.append("--burn-subtitles")
        if self.cut_pauses.get():
            cmd.append("--cut-pauses")
        if self.allow_low_quality.get():
            cmd.append("--allow-low-quality")
        if self.show_hook.get():
            cmd.extend(["--style", "hook"])
        return cmd

    def _run(self) -> None:
        if self.process and self.process.poll() is None:
            messagebox.showinfo("Rodando", "O robo ja esta rodando.")
            return
        if not PYTHON.exists():
            messagebox.showerror("Ambiente", "Ambiente .venv nao encontrado. Rode setup.ps1 uma vez.")
            return
        try:
            if self.render_candidate.get() <= 0 and self.pending_urls and not self.url.get().strip():
                self.current_url = self.pending_urls.pop(0)
                self.queue_list.delete(0)
            elif self.render_candidate.get() <= 0 and self.url.get().strip():
                self.current_url = self.url.get().strip()
                self.url.set("")
            else:
                self.current_url = None
            cmd = self._command()
        except ValueError as exc:
            messagebox.showwarning("Entrada", str(exc))
            return

        self.status.set("Rodando")
        self._set_progress(5, "Preparando o robo")
        self._refresh_candidates()
        self._refresh_videos()
        self._append_log("\n=== Rodando ===\n")
        self._append_log(" ".join(f'"{part}"' if " " in part else part for part in cmd) + "\n\n")
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        self.process = subprocess.Popen(
            cmd,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            bufsize=1,
        )
        threading.Thread(target=self._reader_thread, daemon=True).start()

    def _run_preview(self) -> None:
        previous_preview = self.preview_only.get()
        previous_count = self.count.get()
        self.preview_only.set(True)
        self.count.set(max(10, previous_count))
        self._run()
        self.preview_only.set(previous_preview)
        self.count.set(previous_count)

    def _reader_thread(self) -> None:
        assert self.process and self.process.stdout
        for line in self.process.stdout:
            self.log_queue.put(line)
        code = self.process.wait()
        self.log_queue.put(f"\n=== Processo terminou com codigo {code} ===\n")
        if code == 0:
            self.log_queue.put(f"Veja o pacote recomendado em: {POST_NOW}\n")
            self.log_queue.put("[[STATUS:Pronto]]\n")
            self.log_queue.put("[[PROGRESS:100|Concluido]]\n")
            self.log_queue.put("[[REFRESH_VIDEOS]]\n")
            self.log_queue.put("[[RUN_NEXT_QUEUE]]\n")
        else:
            self.log_queue.put("[[STATUS:Erro ou processo interrompido]]\n")

    def _drain_logs(self) -> None:
        while True:
            try:
                text = self.log_queue.get_nowait()
            except queue.Empty:
                break
            if text.startswith("[[STATUS:") and text.endswith("]]\n"):
                self.status.set(text.removeprefix("[[STATUS:").removesuffix("]]\n"))
            elif text.startswith("[[PROGRESS:") and text.endswith("]]\n"):
                payload = text.removeprefix("[[PROGRESS:").removesuffix("]]\n")
                value, _, label = payload.partition("|")
                self._set_progress(int(value), label)
            elif text == "[[REFRESH_VIDEOS]]\n":
                self._refresh_videos()
                self._refresh_candidates()
            elif text == "[[RUN_NEXT_QUEUE]]\n":
                self.render_candidate.set(0)
                self.current_url = None
                if self.pending_urls:
                    self.root.after(900, self._run)
            else:
                self._update_progress_from_line(text)
                self._append_log(text)
        self.root.after(120, self._drain_logs)

    def _stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self.status.set("Parando")
            self._set_progress(self.progress.get(), "Processo sendo interrompido")
            self._append_log("\nParando processo...\n")

    def _update_progress_from_line(self, line: str) -> None:
        lower = line.lower()
        steps = [
            (10, "1/5", "Preparando video fonte"),
            (25, "2/5", "Baixando transcricao"),
            (45, "3/5", "Calculando score dos trechos"),
            (65, "4/5", "Selecionando melhores candidatos"),
            (80, "5/5", "Renderizando e validando cortes"),
            (8, "baixando", "Baixando video do YouTube"),
            (18, "downloading", "Baixando video do YouTube"),
            (28, "writing video subtitles", "Baixando transcricao"),
            (32, "subtitles", "Baixando transcricao"),
            (42, "calculando score", "Encontrando trechos virais"),
            (48, "avaliando contexto editorial", "IA avaliando contexto"),
            (54, "analisando energia", "Analisando audio"),
            (58, "analisando movimento", "Analisando movimento visual"),
            (66, "gerando pre-aprovacao", "Gerando pre-aprovacao"),
            (72, "corte", "Preparando cortes"),
            (78, "renderizando", "Renderizando video final"),
            (84, "sincronia ok", "Validando audio e video"),
            (90, "pacote", "Montando pacote final"),
            (95, "pronto", "Finalizando"),
        ]
        for value, needle, label in steps:
            if needle in lower and value > self.progress.get():
                self._set_progress(value, label)
                break

    def _refresh_videos(self) -> None:
        if not hasattr(self, "videos"):
            return
        self.videos.delete(*self.videos.get_children())
        self.video_items.clear()
        videos = sorted(OUTPUTS.glob("**/*.mp4"), key=lambda path: path.stat().st_mtime, reverse=True)
        shown = 0
        for video in videos:
            if ".work" in video.parts or shown >= 20:
                continue
            folder = video.parent
            score = self._read_score(folder)
            name = video.stem.replace("-", " ").strip()
            if folder.name != "_postar_agora":
                name = folder.name.replace("-", " ")
            iid = str(video)
            self.video_items[iid] = video
            self.videos.insert("", "end", iid=iid, values=(score, name[:80], str(folder)))
            shown += 1
        if shown == 0:
            self.videos.insert("", "end", values=("-", "Nenhum corte gerado ainda", str(OUTPUTS)))

    def _latest_candidates_path(self) -> Path | None:
        folders: list[Path] = []
        for base in (PREVIEW, OUTPUTS / "pre-aprovacao"):
            if base.exists():
                folders.extend([path for path in base.iterdir() if path.is_dir()])
        for folder in sorted(folders, key=lambda path: path.stat().st_mtime, reverse=True):
            candidate_file = folder / "candidatos.json"
            if candidate_file.exists():
                return candidate_file
        return None

    def _refresh_candidates(self) -> None:
        if not hasattr(self, "candidates"):
            return
        self.candidates.delete(*self.candidates.get_children())
        self.candidate_items.clear()
        self.latest_candidates_json = self._latest_candidates_path()
        if not self.latest_candidates_json:
            self.candidates.insert("", "end", values=("-", "-", "-", "Nenhuma pre-aprovacao gerada ainda"))
            return
        data = json.loads(self.latest_candidates_json.read_text(encoding="utf-8"))
        for candidate in data.get("candidates", [])[:20]:
            iid = str(candidate.get("rank"))
            self.candidate_items[iid] = candidate
            self.candidates.insert(
                "",
                "end",
                iid=iid,
                values=(
                    candidate.get("rank", ""),
                    candidate.get("score", ""),
                    f"{candidate.get('duration', '')}s",
                    str(candidate.get("headline", ""))[:80],
                ),
            )

    def _selected_candidate(self) -> dict | None:
        selected = self.candidates.selection()
        if not selected:
            messagebox.showinfo("Selecione", "Selecione um candidato na aba Previa Opus.")
            return None
        return self.candidate_items.get(selected[0])

    def _show_candidate_details(self) -> None:
        candidate = self._selected_candidate_silent()
        if not candidate:
            return
        self.candidate_title.set(str(candidate.get("headline", "")))
        self.candidate_meta.set(
            f"Score {candidate.get('score', 0)}/100 | Gancho {candidate.get('hook_score', 0)}/100 | "
            f"Editorial {candidate.get('editorial_score', 0)}/100 | Inicio {candidate.get('start')} | "
            f"{candidate.get('duration')}s | {candidate.get('decision', '')}"
        )
        self.candidate_reason.configure(state="normal")
        self.candidate_reason.delete("1.0", "end")
        self.candidate_reason.insert("end", str(candidate.get("reason", ""))[:1200])
        self.candidate_reason.configure(state="disabled")
        frame = Path(str(candidate.get("frame", "")))
        if frame.exists():
            image = Image.open(frame)
            image.thumbnail((430, 240))
            self.preview_image = ImageTk.PhotoImage(image)
            self.preview_label.configure(image=self.preview_image, text="", height=240)
        else:
            self.preview_label.configure(image="", text="Thumbnail nao encontrado", height=10)
        self.post_text.delete("1.0", "end")
        self.post_text.insert("end", str(candidate.get("publication", "")).strip())

    def _selected_candidate_silent(self) -> dict | None:
        selected = self.candidates.selection()
        if not selected:
            return None
        return self.candidate_items.get(selected[0])

    def _set_candidate_decision(self, decision: str) -> None:
        candidate = self._selected_candidate()
        if not candidate or not self.latest_candidates_json:
            return
        data = json.loads(self.latest_candidates_json.read_text(encoding="utf-8"))
        rank = int(candidate.get("rank", 0))
        for item in data.get("candidates", []):
            if int(item.get("rank", 0)) == rank:
                item["decision"] = decision
        self.latest_candidates_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self._refresh_candidates()
        self.status.set(f"Candidato {rank} marcado como {decision}")

    def _render_selected_candidate(self) -> None:
        candidate = self._selected_candidate()
        if not candidate:
            return
        self.render_candidate.set(int(candidate.get("rank", 0)))
        self._run()

    def _read_score(self, folder: Path) -> str:
        for name in ("score-viral.txt", "score.txt"):
            path = folder / name
            if path.exists():
                text = path.read_text(encoding="utf-8", errors="ignore")
                for line in text.splitlines():
                    if "score" in line.lower():
                        value = line.split(":", 1)[-1] if ":" in line else line.split("=", 1)[-1]
                        return value.strip()[:12]
                return text.strip().splitlines()[0][:12] if text.strip() else "-"
        return "-"

    def _selected_video(self) -> Path | None:
        selected = self.videos.selection()
        if not selected:
            messagebox.showinfo("Selecione", "Selecione um corte na lista.")
            return None
        return self.video_items.get(selected[0])

    def _watch_selected(self) -> None:
        video = self._selected_video()
        if video:
            os.startfile(str(video))

    def _open_selected_folder(self) -> None:
        video = self._selected_video()
        if video:
            os.startfile(str(video.parent))

    def _open_selected_publication(self) -> None:
        video = self._selected_video()
        if not video:
            return
        publication = video.parent / "publicacao.txt"
        if not publication.exists() and POST_NOW.exists():
            publication = POST_NOW / "publicacao.txt"
        if publication.exists():
            os.startfile(str(publication))
        else:
            messagebox.showinfo("Legenda", "Nao encontrei publicacao.txt para esse corte.")

    def _load_post_from_selected(self) -> None:
        video = self._selected_video()
        text = ""
        if video:
            publication = video.parent / "publicacao.txt"
            if not publication.exists() and POST_NOW.exists():
                newest = sorted(POST_NOW.glob("**/publicacao.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
                publication = newest[0] if newest else publication
            if publication.exists():
                text = publication.read_text(encoding="utf-8-sig", errors="ignore")
        if not text:
            candidate = self._selected_candidate_silent()
            if candidate:
                text = str(candidate.get("publication", ""))
        self.post_text.delete("1.0", "end")
        self.post_text.insert("end", text.strip() or "Selecione um corte ou candidato para carregar o texto.")
        self.tabs.select(self.post_tab)

    def _copy_post_text(self) -> None:
        text = self.post_text.get("1.0", "end").strip()
        if not text:
            messagebox.showinfo("Copiar", "Nao ha texto para copiar.")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.status.set("Texto copiado")

    def _post_selected(self) -> None:
        video = self._selected_video()
        if video:
            os.startfile(str(video.parent))
        webbrowser.open("https://www.tiktok.com/tiktokstudio/upload")

    def _show_details(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("Detalhes tecnicos")
        window.geometry("920x520")
        text = tk.Text(window, wrap="word", bg=COLORS["dark"], fg="#e5e7eb", padx=12, pady=12, font=("Consolas", 10))
        text.pack(fill="both", expand=True)
        text.insert("end", "".join(self.log_lines) or "Sem detalhes ainda.")
        text.configure(state="disabled")

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    PoderEmJogoApp().run()
