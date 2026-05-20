"""
TalkShow Generator — entry point.

Run with:  python app.py
"""
import sys
from ui.main_window import MainWindow


def main():
    app = MainWindow()
    try:
        # Use system theme if available
        from tkinter import ttk
        style = ttk.Style()
        for theme in ("vista", "aqua", "clam"):
            if theme in style.theme_names():
                style.theme_use(theme)
                break
    except Exception:
        pass
    app.mainloop()


if __name__ == "__main__":
    sys.exit(main() or 0)
