.. pyplaybin documentation master file, created by
   sphinx-quickstart on Sun Nov 27 15:50:44 2016.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Welcome to pyplaybin's documentation!
=====================================

.. toctree::
   :maxdepth: 2

Methods marked **asynchronous** are coroutines; you must call them
from a coroutine using `yield from` (Python 3.4) or `await` (Python 3.5).

API
===

.. automodule:: pyplaybin
   :members: PlaybinError, PlaybinGstError, StreamTrack

.. autoclass:: Playbin
   :members: __init__, start_glib_loop, stop_glib_loop,
	     create_video_sink, create_audio_sink, end_of_stream,
	     async_error, play, pause, stop, position, duration,
	     subtitle, subtitle_file, audio_track, subtitle_tracks,
	     audio_tracks, seek, rewind, forward, volume
   :member-order: bysource

Example
=======

.. code-block:: python

    import asyncio, signal
    from pyplaybin import Playbin

    @asyncio.coroutine
    def start(filename):
        loop = asyncio.get_event_loop()
        bin = Playbin()

        @asyncio.coroutine
        def stopAll():
            yield from bin.stop()
            loop.stop()
        loop.add_signal_handler(signal.SIGINT, loop.create_task, stopAll())

        yield from bin.play(filename)
        print('== Subtitle tracks:')
        for track in bin.subtitle_tracks():
            print('  %s' % str(track))
        print('== Audio tracks:')
        for track in bin.audio_tracks():
            print('  %s' % str(track))
        print('Type Ctrl-C in the console to stop playback.')

    Playbin.start_glib_loop()
    loop = asyncio.get_event_loop()
    loop.create_task(start('/home/jerome/test.mkv'))
    try:
        loop.run_forever()
    finally:
        Playbin.stop_glib_loop()


Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`

