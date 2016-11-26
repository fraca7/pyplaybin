#!/usr/bin/env python
#-*- coding: ISO-8859-1 -*-

# This software is released under the terms of the MIT license. See the LICENSE file for details.

"""
Thin wrapper around GStreamer's playbin2, using asyncio-style asynchronous methods.
"""

import gi
gi.require_version('Gst', '1.0')
gi.require_version('GstVideo', '1.0')
gi.require_version('GstTag', '1.0')

from gi.repository import Gst, GstVideo, GstTag, GObject
import os, threading, functools, asyncio, sys, collections, platform


def create_future():
    if sys.version_info >= (3, 5, 2):
        return asyncio.get_event_loop().create_future()
    return asyncio.Future()


class PlaybinError(Exception):
    """
    Generic error
    """


class PlaybinGstError(PlaybinError):
    """
    GStreamer error
    """
    def __init__(self, code, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.code = code

    def __str__(self):
        return '%s: %s' % (self.code, super().__str__())


class StreamTrack(collections.namedtuple('StreamTrack', ['index', 'lang'])):
    def __str__(self):
        return 'Unknown' if self.lang is None else self.lang


def state_change(func):
    """
    This decorator changes a regular synchronous method that returns a
    Gst.StateChangeReturn into an asynchronous one which will yield
    when the state change has actually happened.
    """
    @functools.wraps(func)
    @asyncio.coroutine
    def wrapper(self, *args, **kwargs):
        ret = func(self, *args, **kwargs)
        if ret == Gst.StateChangeReturn.ASYNC:
            ft = create_future()
            self._async_response.append(ft)
            yield from ft
        elif ret != Gst.StateChangeReturn.SUCCESS:
            raise PlaybinGstError(ret)
    return wrapper


def gst_async(func):
    """
    This decorator changes a regular synchronous method into an
    asynchronous one which will yield when the underlying operation
    has actually completed. The assumption is that the underlying
    operation will trigger an ASYNC_DONE message.
    """
    @functools.wraps(func)
    @asyncio.coroutine
    def wrapper(self, *args, **kwargs):
        func(self, *args, **kwargs)
        ft = create_future()
        self._async_response.append(ft)
        return (yield from ft)
    return wrapper


class BasePlaybinWrapper(object):
    """
    Base class for objects that encapsulate access details to the playbin element
    """

    def __init__(self, element):
        self._element = element

    def setup(self):
        pass

    def get_property(self, name):
        return self._element.get_property(name)

    def set_property(self, name, value):
        self._element.set_property(name, value)

    def _isEnabled(self, value):
        return (self._element.get_property('flags') & value) != 0

    def _enable(self, value, enabled):
        flags = self._element.get_property('flags')
        if enabled:
            flags |= value
        else:
            flags &= ~value
        self._element.set_property('flags', flags)

    def isAudioEnabled(self):
        return self._isEnabled(2)

    def enableAudio(self, enabled=True):
        self._enable(2, enabled)

    def isSubtitleEnabled(self):
        return self._isEnabled(4)

    def enableSubtitle(self, enabled=True):
        self._enable(4, enabled)


class PlaybinWrapper(BasePlaybinWrapper):
    """
    Wrapper for the 'playbin' element
    """

    def __init__(self, element):
        super().__init__(element)
        self._subtitles = None
        self._audio = None

    def setup(self):
        self._subtitles = list(self._parse_tags('text'))
        self._audio = list(self._parse_tags('audio'))

    def subtitle_tracks(self):
        return self._subtitles[:]

    def _get_subtitle(self):
        if self.isSubtitleEnabled():
            return self._subtitles[self._element.get_property('current-text')]
        return None
    def _set_subtitle(self, track):
        self.enableSubtitle(track is not None)
        if track is not None:
            self._element.set_property('current-text', track.index)
    subtitle = property(_get_subtitle, _set_subtitle)

    def audio_tracks(self):
        return self._audio[:]

    def _get_audio_track(self):
        if self.isAudioEnabled():
            return self._audio[self._element.get_property('current-audio')]
        return None
    def _set_audio_track(self, track):
        self.enableAudio(track is not None)
        if track is not None:
            self._element.set_property('current-audio', track.index)
    audio_track = property(_get_audio_track, _set_audio_track)

    def _parse_tags(self, trackname):
        count = self._element.get_property('n-%s' % trackname)
        for index in range(count):
            tags = self._element.emit('get-%s-tags' % trackname, index)
            if tags is not None:
                for tagidx in range(tags.n_tags()):
                    name = tags.nth_tag_name(tagidx)
                    if name == 'language-code':
                        code = tags.get_string(name)[1]
                        lang = GstTag.tag_get_language_name(code)
                        yield StreamTrack(index, lang or code)
                        break



class Playbin(object):
    """
    Wrapper around a GStreamer pipeline base on the playbin element.
    """

    glib_loop = None
    glib_thread = None

    def __init__(self, win_id=None):
        """
        Builds a new GStreamer pipeline. If `win_id` is specified, it
        is used as a window ID to embed the video sink using the
        GstOverlay interface.
        """
        super().__init__()

        self._async_loop = asyncio.get_event_loop()
        self._async_response = []

        if platform.system() == 'Darwin':
            evt = threading.Event()
            error = [None]
            GObject.timeout_add(1, self._build, win_id, evt, error)
            evt.wait()
            if error[0]:
                raise PlaybinError from error[0]
        else:
            self._build(win_id, None, None)

    @classmethod
    def start_glib_loop(cls):
        """
        If your program does not use the GLib loop, call this first.
        """
        GObject.threads_init()
        Gst.init(None)

        cls.glib_loop = GObject.MainLoop()
        cls.glib_thread = threading.Thread(target=cls.glib_loop.run)
        cls.glib_thread.start()

    @classmethod
    def stop_glib_loop(cls):
        """
        Call this before exiting.
        """
        cls.glib_loop.quit()
        cls.glib_thread.join()
        cls.glib_loop = cls.glib_thread = None

    def call_from_thread(self, callback, *args, **kwargs):
        self._async_loop.call_soon_threadsafe(functools.partial(callback, *args, **kwargs))

    def _build(self, win_id, evt, error):
        try:
            vsink = None

            self.pipeline = Gst.Pipeline.new('pyplaybin')

            bus = self.pipeline.get_bus()
            bus.add_signal_watch()
            bus.connect('message::error', self._error)
            bus.connect('message::eos', self._EOS)
            bus.connect('message::async-done', self._async_done)

            playbin = Gst.ElementFactory.make('playbin', 'playbin')
            self._playbin = PlaybinWrapper(playbin)
            self.pipeline.add(playbin)

            vsink = self.create_video_sink('videosink')
            asink = self.create_audio_sink('audiosink')

            self._playbin.set_property('video-sink', vsink)
            self._playbin.set_property('audio-sink', asink)
        except Exception as exc:
            if error is None:
                raise
            error[0] = exc

        if evt is not None:
            evt.set()
        if win_id is not None and vsink is not None:
            vsink.set_window_handle(win_id)

    def create_video_sink(self, name):
        """
        Override this to create a custom video sink. Warning: this
        will be called from GLib's main loop thread.
        """
        return None

    def create_audio_sink(self, name):
        """
        Override this to create a custom audio sink. Warning: this
        will be called from GLib's main loop thread.
        """
        return None

    def end_of_stream(self):
        """
        This will be called on EOS.
        """

    def async_error(self, exc):
        """
        This will be called if an error occurs asynchronously.
        """

    @asyncio.coroutine
    def play(self, filename=None):
        """
        Starts playing.
        """
        yield from self._play(filename=filename)
        if filename is not None:
            self._playbin.setup()

    @state_change
    def _play(self, filename=None):
        if filename is not None:
            self._playbin.enableAudio()
            self._playbin.enableSubtitle()
            self._playbin.set_property('uri', 'file://%s' % os.path.abspath(filename))
        return self.pipeline.set_state(Gst.State.PLAYING)

    @state_change
    def pause(self):
        """
        Pauses playback
        """
        return self.pipeline.set_state(Gst.State.PAUSED)

    @state_change
    def stop(self):
        """
        Stops playback
        """
        return self.pipeline.set_state(Gst.State.NULL)

    @property
    def position(self):
        """The current stream position, in native GStreamer units. Divide by Gst.SECOND to get seconds."""
        ret, pos = self.pipeline.query_position(Gst.Format.TIME)
        if not ret:
            raise PlaybinError('Cannot get position')
        return pos

    @property
    def duration(self):
        """The current stream duration, in native GStreamer units. Divide by Gst.SECOND to get seconds."""
        ret, dur = self.pipeline.query_duration(Gst.Format.TIME)
        if not ret:
            raise PlaybinError('Cannot get duration')
        return dur

    def _get_subtitle(self):
        return self._playbin.subtitle
    def _set_subtitle(self, index):
        self._playbin.subtitle = index
    subtitle = property(_get_subtitle, _set_subtitle, doc="""Current subtitle track, or None""")

    def _get_subtitle_file(self):
        uri = self._playbin.get_property('suburi')
        return None if uri is None else uri[7:]

    def _set_subtitle_file(self, filename):
        self._playbin.enableSubtitle()
        self._playbin.set_property('suburi', 'file://%s' % os.path.abspath(filename))

    subtitle_file = property(_get_subtitle_file, _set_subtitle_file, doc="""Subtitle file name""")

    def _get_audio_track(self):
        return self._playbin.audio_track
    def _set_audio_track(self, index):
        self._playbin.audio_track = index
    audio_track = property(_get_audio_track, _set_audio_track, """Current audio track, or None""")

    def subtitle_tracks(self):
        """
        Returns available subtitle tracks
        """
        return self._playbin.subtitle_tracks()

    def audio_tracks(self):
        """
        Returns available audio tracks
        """
        return self._playbin.audio_tracks()

    @gst_async
    def seek(self, position):
        """
        Seek to specified position, in GStreamer units.
        """
        self.pipeline.seek(1.0, Gst.Format.TIME, Gst.SeekFlags.FLUSH|Gst.SeekFlags.KEY_UNIT, Gst.SeekType.SET, position, Gst.SeekType.NONE, -1)

    @asyncio.coroutine
    def rewind(self, duration):
        """
        Rewind by specified duration, in seconds.
        """
        pos = self.position
        pos -= duration * Gst.SECOND
        yield from self.seek(max(0, pos))

    @asyncio.coroutine
    def forward(self, duration):
        """
        Forward by specified duration, in seconds.
        """
        pos = self.position
        dur = self.duration
        pos += duration * Gst.SECOND
        yield from self.seek(min(dur, pos))

    def _error(self, bus, msg):
        err, dbg = msg.parse_error()
        try:
            ft = self._async_response.pop(0)
        except IndexError:
            self.call_from_thread(self.async_error, PlaybinError('Unexpected async error (%s[%s])' % (err, dbg)))
        else:
            self._async_loop.call_soon_threadsafe(ft.set_exception, PlaybinError('%s: %s' % (err, dbg)))

    def _EOS(self, bus, msg):
        self.call_from_thread(self.end_of_stream)

    def _async_done(self, bus, msg):
        try:
            ft = self._async_response.pop(0)
        except IndexError:
            self.call_from_thread(self.async_error, PlaybinError('Unexpected ASYNC_DONE response'))
        else:
            self._async_loop.call_soon_threadsafe(ft.set_result, None)
