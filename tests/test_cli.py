"""The terminal version: its keys while recording."""

import contextlib

from ghostscribe import cli
from ghostscribe.i18n import translate
from ghostscribe.recorder import MeetingRecorder

from fakes import Clock, FakeBackend


def test_p_pauses_and_resumes_and_enter_stops(tmp_path, monkeypatch, capsys):
    clock = Clock()
    recorder = MeetingRecorder(output_dir=str(tmp_path), backend=FakeBackend(), clock=clock)
    recorder.start()
    pressed = iter(["p", None, "p", "\r"])
    paused_while_waiting = []

    def next_key(timeout=None):
        clock.now += 1  # a second per key
        paused_while_waiting.append(recorder.paused)
        return next(pressed)

    monkeypatch.setattr(cli.keys, "supported", lambda: True)
    monkeypatch.setattr(cli.keys, "reading_keys", contextlib.nullcontext)
    monkeypatch.setattr(cli.keys, "wait_for_key", next_key)

    cli.record(recorder)

    assert paused_while_waiting == [False, True, True, False]
    assert recorder.cuts == [1.0] and recorder.get_duration() == 2.0  # two of the four seconds were paused
    assert translate("cli.paused", duration="00:00:01") in capsys.readouterr().out
    recorder.cancel()
