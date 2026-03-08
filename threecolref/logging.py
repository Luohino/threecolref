# This file is part of threecolref.
#
# threecolref is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# threecolref is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with threecolref.  If not, see <https://www.gnu.org/licenses/>.

import logging
import logging.handlers
import os.path

from PyQt6 import QtCore


logging.TRACE = 5


class BeeLogger(logging.Logger):

    def __init__(self, name, level=logging.NOTSET):
        super().__init__(name, level)
        logging.addLevelName(logging.TRACE, 'TRACE')

    def trace(self, msg, *args, **kwargs):
        self.log(logging.TRACE, msg, *args, **kwargs)


logging.setLoggerClass(BeeLogger)


class BeeRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """RotatingFileHandler that creates log directory if necessary and 
    gracefully handles log rotation errors on Windows (PermissionError).
    """

    def __init__(self, filename, **kwargs):
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        super().__init__(filename, **kwargs)

    def doRollover(self):
        try:
            super().doRollover()
        except (PermissionError, OSError):
            # On Windows, rotation fails if another process has the log open.
            # We ignore it to prevent the whole app from crashing.
            pass

    def emit(self, record):
        try:
            super().emit(record)
        except (PermissionError, OSError):
            # Same for emission if file is temporarily locked
            pass



qtlogger = logging.getLogger('Qt')


def qt_message_handler(mode, context, message):
    logfuncs = {
        QtCore.QtMsgType.QtDebugMsg: qtlogger.debug,
        QtCore.QtMsgType.QtInfoMsg: qtlogger.info,
        QtCore.QtMsgType.QtWarningMsg: qtlogger.warning,
        QtCore.QtMsgType.QtCriticalMsg: qtlogger.critical,
        QtCore.QtMsgType.QtFatalMsg: qtlogger.fatal,
    }
    if context and (context.file or context.line or context.function):
        message = (f'{message}: File {context.file}, line {context.line}, '
                   f'in {context.function}')

    logfuncs[mode](message)
