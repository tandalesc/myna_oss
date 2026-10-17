"""Interrupt controller and timer models."""
from .clock import Clock
from .vic import Vic, VicPair
from .timer import SleepTimer
from .system import IrqTimerSystem
