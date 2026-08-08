"""Command-line interface for easyNAMD.

The desktop app and this CLI are two front-ends over the same `core/` modules —
there is deliberately no second implementation of any file transformation here.
Commands are non-interactive and support --json so they can be driven by scripts
and agents as well as by people.
"""
