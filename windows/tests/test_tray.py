import os
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tray import TrayIcon


class TrayTests(unittest.TestCase):
    def test_start_confirms_icon_visibility_and_stop_releases_it(self):
        tray = TrayIcon.__new__(TrayIcon)
        tray.icon = Mock()
        tray.icon.run_detached.side_effect = lambda setup: setup(tray.icon)
        tray.start()
        self.assertTrue(tray.icon.visible)
        tray.stop()
        tray.icon.stop.assert_called_once()

    def test_tray_menu_callbacks_dispatch_back_to_ui_instead_of_touching_tk(self):
        actions = []
        entries = []
        def item(text, callback, **kwargs):
            entries.append((text, callback))
            return Mock()
        menu = Mock(side_effect=lambda *items: items)
        menu.SEPARATOR = object()
        pystray = SimpleNamespace(Icon=Mock(), Menu=menu, MenuItem=item)
        pillow = SimpleNamespace(Image=Mock(), ImageDraw=Mock())
        with patch.dict(sys.modules, {"pystray": pystray, "PIL": pillow}):
            TrayIcon(actions.append)
        for _, callback in entries:
            callback(None, None)
        self.assertEqual(actions, ["show", "instructions", "quit"])
