import os.path
import pytest
import uuid

from unittest.mock import MagicMock, patch

from PyQt6 import QtGui, QtWidgets


def pytest_configure(config):
    # Ignore logging configuration for threecolref during test runs. This
    # avoids logging to the regular log file and spamming test output
    # with debug messages.
    #
    # This needs to be done before the application code is even loaded since
    # logging configuration happens on module level
    import logging.config
    logging.config.dictConfig = MagicMock


@pytest.fixture(autouse=True)
def reset_threecolref_actions():
    from threecolref.actions.actions import actions
    for key in list(actions.keys()):
        if key.startswith('recent_files_'):
            actions.pop(key)


@pytest.fixture(autouse=True)
def commandline_args():
    config_patcher = patch('threecolref.view.commandline_args')
    config_mock = config_patcher.start()
    config_mock.filenames = []
    yield config_mock
    config_patcher.stop()


@pytest.fixture(autouse=True)
def settings(tmpdir):
    from threecolref.config import BeeSettings
    dir_patcher = patch('threecolref.config.BeeSettings.get_settings_dir',
                        return_value=tmpdir.dirname)
    dir_patcher.start()
    settings = BeeSettings()
    yield settings
    settings.clear()
    dir_patcher.stop()


@pytest.fixture(autouse=True)
def kbsettings(tmpdir):
    from threecolref.config import KeyboardSettings
    dir_patcher = patch('threecolref.config.BeeSettings.get_settings_dir',
                        return_value=tmpdir.dirname)
    dir_patcher.start()
    kbsettings = KeyboardSettings()
    yield kbsettings
    kbsettings.clear()
    dir_patcher.stop()


@pytest.fixture
def main_window(qtbot):
    from threecolref.__main__ import threecolrefMainWindow
    app = QtWidgets.QApplication.instance()
    main = threecolrefMainWindow(app)
    qtbot.addWidget(main)
    yield main


@pytest.fixture
def view(main_window):
    yield main_window.view


@pytest.fixture
def imgfilename3x3():
    root = os.path.dirname(__file__)
    yield os.path.join(root, 'assets', 'test3x3.png')


@pytest.fixture
def imgdata3x3(imgfilename3x3):
    with open(imgfilename3x3, 'rb') as f:
        imgdata3x3 = f.read()
    yield imgdata3x3


@pytest.fixture
def tmpfile(tmpdir):
    yield os.path.join(tmpdir, str(uuid.uuid4()))


@pytest.fixture
def item():
    from threecolref.items import BeePixmapItem
    yield BeePixmapItem(QtGui.QImage(10, 10, QtGui.QImage.Format.Format_RGB32))


@pytest.fixture(scope="session")
def qapp():
    from threecolref.__main__ import threecolrefApplication
    yield threecolrefApplication([])
