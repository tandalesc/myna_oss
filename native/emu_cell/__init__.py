"""The cell network behind a modem stand-in, for text messages (cell.py). Plain Python, standard library only: it imports no
other package of the simulator, so the AT stand-in of a firmware of our own (emu_modem_at) and the stock stand-in
(emu_modem_mock, whose cell.py re-exports it) share it without depending on each other. Checked by the selftests of both
stand-ins; myna/firmware/test/stock_free.py checks that a Myna run imports nothing of the stock stand-in.
"""
from .cell import (CellNetwork, Loopback, Host, NETWORKS, EPOCH, SERVICE_CENTRE, CAUSE_MEMORY_EXCEEDED,
                   CAUSE_SEMANTICALLY_INCORRECT, time_stamp, submit_to_deliver, address_field, digits)
