"""Small desktop controller for the Paychain Playwright monitor.

Run with the virtual environment Python: .venv\Scripts\python.exe gui.py
"""

from __future__ import annotations

import subprocess
import sys
import tkinter as tk
from decimal import Decimal, InvalidOperation
from pathlib import Path
from tkinter import messagebox, ttk


ROOT = Path(__file__).parent


class MonitorWindow:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.process: subprocess.Popen[str] | None = None
        self.start_signal = ROOT / ".start_monitoring.signal"
        log_dir = ROOT / "logs"
        log_dir.mkdir(exist_ok=True)
        (log_dir / "activity.log").touch(exist_ok=True)
        self.auto_accept = tk.BooleanVar(value=False)
        self.minimum_amount = tk.StringVar(value="5000")
        self.status = tk.StringVar(value="Натисни «Відкрити Paychain», потім увійди у браузері.")

        root.title("Paychain monitor")
        root.resizable(False, False)
        frame = ttk.Frame(root, padding=18)
        frame.grid()

        ttk.Label(frame, text="Paychain monitor", font=("Segoe UI", 14, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(frame, textvariable=self.status, wraplength=380).grid(row=1, column=0, columnspan=2, pady=(10, 14), sticky="w")
        ttk.Label(frame, text="Приймати оффери від суми (UAH):").grid(row=2, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.minimum_amount, width=14).grid(row=2, column=1, sticky="e")
        ttk.Checkbutton(
            frame,
            text="Автоматично натискати «Подтвердить»",
            variable=self.auto_accept,
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(10, 14))

        self.open_button = ttk.Button(frame, text="1. Відкрити Paychain", command=self.open_paychain)
        self.open_button.grid(row=4, column=0, sticky="ew", padx=(0, 6))
        self.start_button = ttk.Button(frame, text="2. Почати моніторинг", command=self.start_monitoring, state="disabled")
        self.start_button.grid(row=4, column=1, sticky="ew")
        self.stop_button = ttk.Button(frame, text="Зупинити", command=self.stop, state="disabled")
        self.stop_button.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        root.protocol("WM_DELETE_WINDOW", self.close)

    def open_paychain(self) -> None:
        if self.process and self.process.poll() is None:
            return
        try:
            threshold = Decimal(self.minimum_amount.get().strip().replace(",", "."))
            if threshold < 0:
                raise InvalidOperation
        except InvalidOperation:
            messagebox.showerror("Неправильна сума", "Введи невід’ємне число, наприклад 5000 або 5000.50.")
            return

        self.start_signal.unlink(missing_ok=True)
        command = [
            str(Path(sys.executable)), str(ROOT / "main.py"),
            "--minimum-amount", str(threshold),
            "--start-signal", str(self.start_signal),
        ]
        if self.auto_accept.get():
            command.append("--auto-accept")
        try:
            self.process = subprocess.Popen(
                command,
                cwd=ROOT,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except OSError as error:
            messagebox.showerror("Не вдалося запустити", str(error))
            return
        self.status.set("Увійди у Paychain у відкритому браузері. Потім натисни «Почати моніторинг».")
        self.open_button.configure(state="disabled")
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="normal")

    def start_monitoring(self) -> None:
        if not self.process or self.process.poll() is not None:
            self.status.set("Спочатку відкрий Paychain.")
            return
        try:
            self.start_signal.write_text("start", encoding="utf-8")
        except OSError:
            self.status.set("Процес завершився. Відкрий Paychain повторно.")
            self.reset_buttons()
            return
        mode = "Автоматичне підтвердження увімкнено." if self.auto_accept.get() else "Тестовий режим: підтвердження вимкнено."
        self.status.set(f"Моніторинг працює для сум понад {self.minimum_amount.get()} UAH. {mode}")
        self.start_button.configure(state="disabled")

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.status.set("Моніторинг зупинено.")
        self.reset_buttons()

    def reset_buttons(self) -> None:
        self.process = None
        self.start_signal.unlink(missing_ok=True)
        self.open_button.configure(state="normal")
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="disabled")

    def close(self) -> None:
        self.stop()
        self.root.destroy()


if __name__ == "__main__":
    app = tk.Tk()
    MonitorWindow(app)
    app.mainloop()
