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
