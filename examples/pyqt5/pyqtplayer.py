#!/usr/bin/python

import sys, os, asyncio, platform, functools
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst

from pyplaybin import Playbin, StreamTrack
from PyQt5 import QtCore, QtGui, QtWidgets
from quamash import QEventLoop

#==============================================================================
# Utilities


def async_slot(func):
    @functools.wraps(func)
    def slot(self, *args, **kwargs):
        asyncio.ensure_future(func(self, *args, **kwargs))
    return slot


def formatSeconds(seconds, short=False, places=3):
    parts = list()
    if (seconds > 60*60 or short) and places >= 3:
        hours = seconds // (60*60)
        if short:
            parts.append('%02d' % hours)
        elif hours != 0:
            parts.append(('%d hours' % hours) if hours > 1 else '1 hour')
        seconds -= hours * 60 * 60
    if (seconds > 60 or short) and places >= 2:
        minutes = seconds // 60
        if short:
            parts.append('%02d' % minutes)
        elif minutes != 0:
            parts.append(('%d minutes' % minutes) if minutes > 1 else '1 minute')
        seconds -= minutes * 60
    if (seconds or short) and places >= 1:
        if short:
            parts.append('%02d' % seconds)
        else:
            parts.append(('%d seconds' % seconds) if seconds > 1 else ('%d second' % seconds))
    return ':'.join(parts) if short else ' '.join(parts)

#==============================================================================
# Stream position/seek widget


class SeekSlider(QtWidgets.QWidget):
    STATE_IDLE = 0
    STATE_PAUSING = 1
    STATE_SEEKING = 2

    def __init__(self, playbin, parent):
        super().__init__(parent)
        self._playbin = playbin
        self._state = self.STATE_IDLE
        self._started = None
        self._updater = None
        self._slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self._elapsed = QtWidgets.QLabel('00:00:00')
        self._remaining = QtWidgets.QLabel('00:00:00')
        self._slider.setMinimum(0)

        layout = QtWidgets.QHBoxLayout()
        layout.setContentsMargins(2, 2, 2, 2)
        layout.addWidget(self._elapsed)
        layout.addWidget(self._slider, stretch=1)
        layout.addWidget(self._remaining)
        self.setLayout(layout)

        self._slider.sliderPressed.connect(self._startDragging)
        self._slider.sliderMoved.connect(self._drag)
        self._slider.sliderReleased.connect(self._stopDragging)

        self._updater = asyncio.get_event_loop().create_task(self._poll())

    def elapsedWidget(self):
        return self._elapsed

    def remainingWidget(self):
        return self._remaining

    @asyncio.coroutine
    def stop(self):
        if self._updater is not None:
            self._updater.cancel()
            yield from self._updater
            self._updater = None
        self._state = self.STATE_IDLE

    @asyncio.coroutine
    def _poll(self):
        try:
            while True: # Exit on CancelledError actually
                if self._state == self.STATE_IDLE:
                    try:
                        position = self._playbin.position // Gst.SECOND
                        duration = self._playbin.duration // Gst.SECOND
                    except PlaybinError as exc:
                        pass
                    else:
                        self._slider.setMaximum(duration)
                        self._slider.setValue(position)
                        self._elapsed.setText(formatSeconds(position, short=True))
                        self._remaining.setText(formatSeconds(duration - position, short=True))
                yield from asyncio.sleep(1)
        except asyncio.CancelledError:
            pass

    @async_slot
    def _startDragging(self):
        self._state = self.STATE_PAUSING
        self._started = self._playbin.position // Gst.SECOND
        yield from self._playbin.pause()
        if self._state == self.STATE_IDLE:
            yield from self._playbin.play()
        else:
            self._state = self.STATE_SEEKING

    @async_slot
    def _stopDragging(self):
        state, self._state = self._state, self.STATE_IDLE
        if state == self.STATE_SEEKING:
            yield from self._playbin.play()
        QtWidgets.QToolTip.hideText()

    @async_slot
    def _drag(self, value):
        delta = value - self._started
        text = formatSeconds(abs(delta), short=True)
        text = ('+' if delta >= 0 else '-') + text
        QtWidgets.QToolTip.showText(self.mapToGlobal(QtCore.QPoint(0, 0)), text)

        self._elapsed.setText(formatSeconds(value, short=True))
        self._remaining.setText(formatSeconds(self._slider.maximum() - value, short=True))
        yield from self._playbin.seek(value * Gst.SECOND)

#==============================================================================
# Subtitle/audio track selection


class MultipleChoiceAction(QtWidgets.QAction):
    def __init__(self, playbin, parent):
        super().__init__(parent)
        self._playbin = playbin
        self.setIcon(QtGui.QIcon('../icons/%s.svg' % self.iconName()))

        menu = QtWidgets.QMenu()
        self.setMenu(menu)
        menu.aboutToShow.connect(self._checkActions)
        self.setEnabled(False)

    def populate(self):
        self.menu().clear()
        hasTracks = False
        for track in self._getTracks():
            hasTracks = True
            action = self.menu().addAction(track.lang or 'Unknown')
            self._bindAction(action, track)
        if hasTracks:
            action = self.menu().addAction('Disable')
            self._bindAction(action, StreamTrack(-1, 'Disable'))
        self.setEnabled(hasTracks)

    def currentValue(self):
        raise NotImplementedError

    def iconName(self):
        raise NotImplementedError

    def _getTracks(self):
        raise NotImplementedError

    def _bindAction(self, action, track):
        def callback():
            self.setTrack(track)
        action.triggered.connect(callback)
        action.setData(track)
        action.setCheckable(True)

    def _checkActions(self):
        current = self.currentValue()
        for action in self.menu().actions():
            if action.data():
                action.setChecked(current == action.data().index)


class SubtitleSelectionAction(MultipleChoiceAction):
    def currentValue(self):
        return self._playbin.subtitle

    def iconName(self):
        return 'text'

    def setTrack(self, track):
        self._playbin.subtitle = track.index

    def _getTracks(self):
        yield from self._playbin.subtitle_tracks()


class AudioSelectionAction(MultipleChoiceAction):
    def currentValue(self):
        return self._playbin.audio_track

    def iconName(self):
        return 'audio'

    def setTrack(self, track):
        self._playbin.audio_track = track.index

    def _getTracks(self):
        yield from self._playbin.audio_tracks()

#==============================================================================
# Video viewport


class Viewport(QtWidgets.QWidget):
    playback_stopped = QtCore.pyqtSignal()
    geometry_changed = QtCore.pyqtSignal()

    def __init__(self, filename):
        super().__init__()
        self.setWindowTitle(filename)
        self.show()
        self.raise_()

    @asyncio.coroutine
    def start_playing(self, filename):
        class QtPlaybin(Playbin, QtCore.QObject):
            eos = QtCore.pyqtSignal()

            def end_of_stream(self):
                self.eos.emit()

            def create_video_sink(self, name):
                # default (gl) sink does not play well with GstOverlay, at least not when using Qt
                if platform.system() == 'Darwin':
                    return Gst.ElementFactory.make('osxvideosink', name)
                return super().create_video_sink(name)

        self.playbin = QtPlaybin(win_id=self.winId())
        self.playbin.eos.connect(self.close)
        yield from self.playbin.play(filename)

    def closeEvent(self, event):
        asyncio.ensure_future(self.playbin.stop())
        event.accept()
        self.playback_stopped.emit()

    def resizeEvent(self, event):
        self.geometry_changed.emit()

    def moveEvent(self, event):
        self.geometry_changed.emit()

#==============================================================================
# Controls


class Player(QtWidgets.QWidget):
    playback_stopped = QtCore.pyqtSignal()

    def __init__(self, filename):
        super().__init__()
        self.setWindowFlags(QtCore.Qt.WindowStaysOnTopHint|QtCore.Qt.FramelessWindowHint)
        asyncio.ensure_future(self._setup(filename))

    @asyncio.coroutine
    def _setup(self, filename):
        self._viewport = Viewport(filename)
        self._viewport.geometry_changed.connect(self._recenter)
        self._viewport.playback_stopped.connect(self._stop_playback)
        self._isPlaying = True
        yield from self._viewport.start_playing(filename)

        toolbar = QtWidgets.QToolBar(self)
        toolbar.setStyleSheet('QToolBar { background-color : rgba(255,255,255,100) ; color:white; border-color: transparent;} QToolButton{background-color : transparent;}')

        rewind = toolbar.addAction(QtGui.QIcon('../icons/rewind.svg'), 'Rewind')
        rewind.triggered.connect(self._rewind)

        self._playPause = toolbar.addAction(QtGui.QIcon('../icons/pause.svg'), 'Play/pause')
        self._playPause.triggered.connect(self._toggle_play_state)

        stop = toolbar.addAction(QtGui.QIcon('../icons/stop.svg'), 'Stop')
        stop.triggered.connect(self._stop_playback)

        forward = toolbar.addAction(QtGui.QIcon('../icons/forward.svg'), 'Forward')
        forward.triggered.connect(self._forward)

        for cls in [SubtitleSelectionAction, AudioSelectionAction]:
            action = cls(self._viewport.playbin, self)
            toolbar.addAction(action)
            btn = toolbar.widgetForAction(action)
            btn.setPopupMode(btn.InstantPopup)
            action.populate()

        self._seeker = SeekSlider(self._viewport.playbin, self)

        vlayout = QtWidgets.QVBoxLayout()
        vlayout.setContentsMargins(0, 0, 0, 0)
        vlayout.setSpacing(2)
        hlayout = QtWidgets.QHBoxLayout()
        hlayout.setContentsMargins(0, 0, 0, 0)
        hlayout.addWidget(self._seeker.elapsedWidget())
        hlayout.addWidget(toolbar, stretch=1)
        hlayout.addWidget(self._seeker.remainingWidget())
        vlayout.addLayout(hlayout)
        vlayout.addWidget(self._seeker)
        self.setLayout(vlayout)

        self._recenter()
        self.setWindowOpacity(0.3)
        self.show()

    def _recenter(self):
        rect = QtCore.QRect(QtCore.QPoint(0, 0), self.sizeHint())
        rect.moveCenter(self._viewport.mapToGlobal(self._viewport.rect().center()))
        dy = self._viewport.height() // 2 - rect.height() // 2
        rect.adjust(-20, -dy, 20, -dy)
        self.setGeometry(rect)

    @async_slot
    def _rewind(self, toggled=False):
        yield from self._viewport.playbin.rewind(60)

    @async_slot
    def _toggle_play_state(self, toggled=False):
        if self._isPlaying:
            self._playPause.setIcon(QtGui.QIcon('../icons/play.svg'))
            yield from self._viewport.playbin.pause()
            self._isPlaying = False
        else:
            self._playPause.setIcon(QtGui.QIcon('../icons/pause.svg'))
            yield from self._viewport.playbin.play()
            self._isPlaying = True

    @async_slot
    def _stop_playback(self, toggled=False):
        yield from self._seeker.stop()
        yield from self._viewport.playbin.stop()
        self.playback_stopped.emit()

    @async_slot
    def _forward(self, toggled=False):
        yield from self._viewport.playbin.forward(60)


class Application(QtWidgets.QApplication):
    def __init__(self):
        super().__init__([])

        self.setApplicationName('PyPlaybin example')
        self.setApplicationVersion('1.0.0')
        self.setOrganizationDomain('net.jeromelaheurte')

        Playbin.start_glib_loop()

        self._loop = QEventLoop()
        asyncio.set_event_loop(self._loop)

        self.askForFile()

    def run(self):
        with self._loop:
            self._loop.run_forever()

    def askForFile(self):
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(None, 'Choose video file')
        if filename:
            self._player = Player(filename)
            self._player.playback_stopped.connect(self.askForFile)
        else:
            Playbin.stop_glib_loop()
            self._loop.stop()


if __name__ == '__main__':
    app = Application()
    app.run()
