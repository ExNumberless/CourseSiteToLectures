"""Progress and usage reporting.

Library calls that take a reporter send it their progress, messages and API usage instead of
printing. A reporter is any object with Reporter's three methods: this is the same structural
protocol as SlidesToLectures', so one object serves both. The default, PrintReporter, prints what
the CLI has always printed and ignores progress and usage.

A reporter may also have warn(message), for messages the CLI prints to stderr; without it, warnings
go to log.
"""

import sys
from typing import Protocol


class Reporter(Protocol):
    def step(self, name: str, done: int, total: int) -> None:
        """Progress within a step: name is the item just finished, done of total.

        A step starts with a call where done is 0 and name is the step's name ("fetch", "materials"
        or "vision").
        """

    def log(self, message: str) -> None:
        """A line of output for the user: what print() said."""

    def usage(
        self,
        vendor: str,
        model: str,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_tokens: int = 0,
        characters: int = 0,
        requests: int = 1,
    ) -> None:
        """API usage: Claude tokens for each request, or text-to-speech characters."""


class PrintReporter:
    """Prints messages (warnings to stderr), as the CLI does; ignores progress and usage."""

    def step(self, name, done, total):
        pass

    def log(self, message):
        print(message)

    def warn(self, message):
        print(message, file=sys.stderr)

    def usage(self, vendor, model, **counts):
        pass


def warn(reporter, message):
    """Send a warning to reporter.warn if it has one, else to reporter.log."""
    getattr(reporter, "warn", reporter.log)(message)
