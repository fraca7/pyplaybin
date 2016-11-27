# pyplaybin

This is a slightly higher-level wrapper for
[GStreamer](https://gstreamer.freedesktop.org/)'s playbin element. It
uses asyncio coroutines to wrap GStreamer's asynchronous calls. A
simple media player using
[PyQt5](https://riverbankcomputing.com/software/pyqt/intro) is
provided as an example.

## Dependencies

- Python 3.4 at least (asyncio)
- python-gi
- GStreamer obviously

The example depends on

- [Quamash](https://pypi.python.org/pypi/Quamash).
- PyQt5

## Simple example

```python
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
```
