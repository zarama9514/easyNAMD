import tkinter as tk
import weakref

import customtkinter as ctk


class XYScrollableFrame(ctk.CTkFrame):
    """A CustomTkinter-friendly frame with horizontal and vertical scrolling."""

    _instances: "weakref.WeakSet[XYScrollableFrame]" = weakref.WeakSet()
    _global_wheel_bound = False

    def __init__(self, parent, *, height: int | None = None, fg_color="transparent", **kwargs):
        super().__init__(parent, fg_color=fg_color, **kwargs)
        self._instances.add(self)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        bg = self._apply_appearance_mode(ctk.ThemeManager.theme["CTkFrame"]["fg_color"])
        self.canvas = tk.Canvas(self, highlightthickness=0, bd=0, bg=bg, height=height)
        self.canvas.grid(row=0, column=0, sticky="nsew")

        self.vbar = ctk.CTkScrollbar(self, orientation="vertical", command=self.canvas.yview)
        self.hbar = ctk.CTkScrollbar(self, orientation="horizontal", command=self.canvas.xview)
        self.vbar.grid(row=0, column=1, sticky="ns")
        self.hbar.grid(row=1, column=0, sticky="ew")
        self.canvas.configure(xscrollcommand=self.hbar.set, yscrollcommand=self.vbar.set)

        self.content = ctk.CTkFrame(self.canvas, fg_color=fg_color)
        self._window = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self._sync_after_id: str | None = None

        self.content.bind("<Configure>", self._schedule_sync)
        self.canvas.bind("<Configure>", self._schedule_sync)
        self._bind_global_wheel_once()

    def configure(self, require_redraw=False, **kwargs):
        height = kwargs.pop("height", None)
        width = kwargs.pop("width", None)
        result = super().configure(require_redraw=require_redraw, **kwargs)
        if height is not None:
            self.canvas.configure(height=height)
        if width is not None:
            self.canvas.configure(width=width)
        self._schedule_sync()
        return result

    config = configure

    def _schedule_sync(self, _event=None):
        if self._sync_after_id is not None:
            return
        self._sync_after_id = self.after_idle(self._sync_canvas)

    def _sync_canvas(self):
        self._sync_after_id = None
        width = max(self.content.winfo_reqwidth(), self.canvas.winfo_width())
        self.canvas.itemconfigure(self._window, width=width)
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _bind_global_wheel_once(self):
        if self.__class__._global_wheel_bound:
            return
        self.__class__._global_wheel_bound = True
        self.canvas.bind_all("<MouseWheel>", self.__class__._dispatch_mousewheel, add="+")
        self.canvas.bind_all("<Shift-MouseWheel>", self.__class__._dispatch_shift_mousewheel, add="+")
        self.canvas.bind_all("<Button-4>", self.__class__._dispatch_linux_scroll_up, add="+")
        self.canvas.bind_all("<Button-5>", self.__class__._dispatch_linux_scroll_down, add="+")

    @classmethod
    def _target_for_event(cls, event) -> "XYScrollableFrame | None":
        candidates = [instance for instance in cls._instances if instance._contains_pointer(event)]
        if not candidates:
            return None
        return min(candidates, key=lambda instance: instance.winfo_width() * instance.winfo_height())

    @classmethod
    def _dispatch_mousewheel(cls, event):
        target = cls._target_for_event(event)
        if target is not None:
            target.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    @classmethod
    def _dispatch_shift_mousewheel(cls, event):
        target = cls._target_for_event(event)
        if target is not None:
            target.canvas.xview_scroll(int(-1 * (event.delta / 120)), "units")

    @classmethod
    def _dispatch_linux_scroll_up(cls, event):
        target = cls._target_for_event(event)
        if target is not None:
            target.canvas.yview_scroll(-1, "units")

    @classmethod
    def _dispatch_linux_scroll_down(cls, event):
        target = cls._target_for_event(event)
        if target is not None:
            target.canvas.yview_scroll(1, "units")

    def _contains_pointer(self, event) -> bool:
        left = self.winfo_rootx()
        top = self.winfo_rooty()
        right = left + self.winfo_width()
        bottom = top + self.winfo_height()
        return left <= event.x_root <= right and top <= event.y_root <= bottom
