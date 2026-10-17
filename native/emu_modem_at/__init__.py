"""The AT modem stand-in: the modem end of the link for a firmware of our own that speaks standard protocols (3GPP TS 27.010
multiplexing, TS 27.007 / 27.005 AT commands) on link channel 0, backed by the cell network that it shares with the
stock stand-in (emu_cell/cell.py). The interface for firmware writers: myna/spec/14-modem-at.md. Selftest: selftest.py.

    peer = attach_peer(link.b, app_irq_system, log)       the launcher's --peer emu_modem_at:attach_peer (profile PEER)

app_irq_system is the application's emu_irq.IrqTimerSystem: its clock is the stand-in's time, its step() drives the stand-in
(wrap_step, with a due time), and the stand-in is in its `timers` list so that a sleeping CPU wakes when the stand-in has
something due. The stand-in never starts the modem CPU and sends nothing until the firmware has sent something.
"""
from .modem import AtModem


def attach_peer(side, irq, log=print, **kw):
    modem = AtModem(side, lambda: irq.clock.now_ns, log, irq=irq, **kw)
    irq.timers.append(modem)

    def tick():
        modem.tick()
        irq.m.irq_pending = irq.vic.irq_out

    def due():                  # bytes from the firmware wait in the link: now; else the next event
        return 0 if modem.has_input() else modem.next_event_ns()
    if hasattr(irq, 'wrap_step'):
        irq.wrap_step(tick, due)
    else:
        orig = irq.step
        def step():
            orig()
            tick()
        irq.step = step
    log('[sim] modem-at: AT modem stand-in on link channel 0 (3GPP TS 27.010 / 27.007 / 27.005), cell network of emu_cell')
    modem.start()
    return modem
