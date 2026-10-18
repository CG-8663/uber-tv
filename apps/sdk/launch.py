"""Starts an app inside its sandbox: the toolkit and the app's own folder go
first on the path Python built (-I -S: its zip, its standard library and
lib-dynload, which ssl needs), stdout is kept for the protocol and print
goes to the app's log, then the app's main file runs."""

import os
import runpy
import sys

sys.path[:0] = ["/sdk", "/app"]

import uber_tv  # noqa: E402

uber_tv._take_stdout()
main = os.environ.get("UBER_TV_MAIN", "main.py")
if "/" in main or not main.endswith(".py"):
    sys.exit("launch: main must be a .py file at the top of the app")
runpy.run_path("/app/" + main, run_name="__main__")
uber_tv.app.run()   # if main.py didn't (it returns at once if it did)
