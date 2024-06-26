import inspect

from ..hdl import *
from ..hdl._ast import Statement, Assign, SignalSet, ValueCastable
from .core import Tick, Settle, Delay, Passive, Active
from ._base import BaseProcess, BaseMemoryState
from ._pyeval import eval_value, eval_assign


__all__ = ["PyCoroProcess"]


class PyCoroProcess(BaseProcess):
    def __init__(self, state, domains, constructor, *, default_cmd=None, testbench=False,
                 on_command=None):
        self.state = state
        self.domains = domains
        self.constructor = constructor
        self.default_cmd = default_cmd
        self.testbench = testbench
        self.on_command = on_command

        self.reset()

    def reset(self):
        self.runnable = True
        self.passive = False

        self.coroutine = self.constructor()
        self.waits_on = SignalSet()

    def src_loc(self):
        coroutine = self.coroutine
        if coroutine is None:
            return None
        while coroutine.gi_yieldfrom is not None and inspect.isgenerator(coroutine.gi_yieldfrom):
            coroutine = coroutine.gi_yieldfrom
        if inspect.isgenerator(coroutine):
            frame = coroutine.gi_frame
        if inspect.iscoroutine(coroutine):
            frame = coroutine.cr_frame
        return f"{inspect.getfile(frame)}:{inspect.getlineno(frame)}"

    def add_trigger(self, signal, trigger=None):
        self.state.add_trigger(self, signal, trigger=trigger)
        self.waits_on.add(signal)

    def clear_triggers(self):
        for signal in self.waits_on:
            self.state.remove_trigger(self, signal)
        self.waits_on.clear()

    def run(self):
        if self.coroutine is None:
            return

        self.clear_triggers()

        response = None
        exception = None
        while True:
            try:
                if exception is None:
                    command = self.coroutine.send(response)
                else:
                    command = self.coroutine.throw(exception)
            except StopIteration:
                self.passive = True
                self.coroutine = None
                return False # no assignment

            try:
                if command is None:
                    command = self.default_cmd
                response = None
                exception = None

                if self.on_command is not None:
                    self.on_command(self, command)

                if isinstance(command, ValueCastable):
                    command = Value.cast(command)
                if isinstance(command, Value):
                    response = eval_value(self.state, command)

                elif isinstance(command, Assign):
                    eval_assign(self.state, command.lhs, eval_value(self.state, command.rhs))
                    if self.testbench:
                        return True # assignment; run a delta cycle

                elif type(command) is Tick:
                    domain = command.domain
                    if isinstance(domain, ClockDomain):
                        pass
                    elif domain in self.domains:
                        domain = self.domains[domain]
                    else:
                        raise NameError("Received command {!r} that refers to a nonexistent "
                                        "domain {!r} from process {!r}"
                                        .format(command, command.domain, self.src_loc()))
                    self.add_trigger(domain.clk, trigger=1 if domain.clk_edge == "pos" else 0)
                    if domain.rst is not None and domain.async_reset:
                        self.add_trigger(domain.rst, trigger=1)
                    return False # no assignments

                elif self.testbench and (command is None or isinstance(command, Settle)):
                    raise TypeError(f"Command {command!r} is not allowed in testbenches")

                elif type(command) is Settle:
                    self.state.wait_interval(self, None)
                    return False # no assignments

                elif type(command) is Delay:
                    # Internal timeline is in 1 fs integeral units, intervals are public API and in floating point
                    interval = int(command.interval * 1e15) if command.interval is not None else None
                    self.state.wait_interval(self, interval)
                    return False # no assignments

                elif type(command) is Passive:
                    self.passive = True

                elif type(command) is Active:
                    self.passive = False

                elif command is None: # only possible if self.default_cmd is None
                    raise TypeError("Received default command from process {!r} that was added "
                                    "with add_process(); did you mean to use Tick() instead?"
                                    .format(self.src_loc()))

                else:
                    raise TypeError("Received unsupported command {!r} from process {!r}"
                                    .format(command, self.src_loc()))

            except Exception as exn:
                response = None
                exception = exn
