from __future__ import annotations

from collections.abc import Callable


class WidgetRegistry:
    """Keeps duplicate controls for one setting synchronized.

    Settings exposes a few values on Home, normal pages, and advanced dialogs.
    One canonical widget is retained for persistence while every mirror receives
    changes immediately.
    """

    def __init__(self, on_change: Callable[[], None]) -> None:
        self._on_change = on_change
        self._groups: dict[str, list[object]] = {}
        self._syncing = False

    def register(self, key: str, widget: object, signal_name: str) -> object:
        group = self._groups.setdefault(key, [])
        if group:
            self._write(widget, self._read(group[0]))
        group.append(widget)
        signal = getattr(widget, signal_name)
        signal.connect(lambda *_args, k=key, source=widget: self.changed(k, source))
        return widget

    def canonical(self, key: str) -> object:
        return self._groups[key][0]

    def contains(self, key: str) -> bool:
        return bool(self._groups.get(key))

    def groups(self) -> dict[str, list[object]]:
        return self._groups

    def changed(self, key: str, source: object) -> None:
        if self._syncing:
            return
        self._syncing = True
        try:
            value = self._read(source)
            for widget in self._groups.get(key, []):
                if widget is not source:
                    self._write(widget, value)
        finally:
            self._syncing = False
        self._on_change()

    @staticmethod
    def _read(widget: object):
        if hasattr(widget, "isChecked"):
            return widget.isChecked()
        if hasattr(widget, "value"):
            return widget.value()
        if hasattr(widget, "currentData"):
            value = widget.currentData()
            if value is not None:
                return value
        if hasattr(widget, "currentText"):
            return widget.currentText()
        if hasattr(widget, "toPlainText"):
            return widget.toPlainText()
        if hasattr(widget, "text"):
            return widget.text()
        raise TypeError(f"Unsupported settings widget: {type(widget).__name__}")

    @staticmethod
    def _write(widget: object, value) -> None:
        previous = widget.blockSignals(True) if hasattr(widget, "blockSignals") else False
        try:
            if hasattr(widget, "setChecked"):
                widget.setChecked(bool(value))
            elif hasattr(widget, "setValue"):
                widget.setValue(value)
            elif hasattr(widget, "findData") and hasattr(widget, "setCurrentIndex"):
                index = widget.findData(value)
                if index >= 0:
                    widget.setCurrentIndex(index)
                elif hasattr(widget, "setCurrentText"):
                    widget.setCurrentText(str(value))
            elif hasattr(widget, "setCurrentText"):
                widget.setCurrentText(str(value))
            elif hasattr(widget, "setPlainText"):
                widget.setPlainText(str(value))
            elif hasattr(widget, "setText"):
                widget.setText(str(value))
            else:
                raise TypeError(f"Unsupported settings widget: {type(widget).__name__}")
        finally:
            if hasattr(widget, "blockSignals"):
                widget.blockSignals(previous)
