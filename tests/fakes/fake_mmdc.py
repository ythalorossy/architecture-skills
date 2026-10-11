"""
Stand-in for mermaid-cli, run as `python fake_mmdc.py -i in.mmd -o out.svg ...`.

It takes the same arguments as mmdc, so svg_render can drive it like the real
tool. FAKE_MMDC_MODE picks the behaviour:

    ok          write a small SVG to the -o path and exit 0 (default)
    syntax      print a mermaid parse error and exit 1
    hang        start a child that sleeps, write its pid to FAKE_MMDC_PID_FILE,
                then sleep (for timeout and process-tree tests)
    enotcached  fail like `npx` with an empty cache when npm_config_offline is
                set; otherwise behave like ok
    no-output   exit 0 without writing anything

Each call writes one JSON file into the folder FAKE_MMDC_LOG, if set, so tests
can count invocations and see whether they ran offline. (One file per call:
parallel appends to a shared file can lose lines on Windows.)
"""
import json
import os
import subprocess
import sys
import time
import uuid


def main(argv):
    args = dict(zip(argv[::2], argv[1::2]))
    mode = os.environ.get("FAKE_MMDC_MODE", "ok")
    offline = os.environ.get("npm_config_offline") == "true"

    log = os.environ.get("FAKE_MMDC_LOG")
    if log:
        with open(os.path.join(log, f"{uuid.uuid4().hex}.json"), "w", encoding="utf-8") as fh:
            json.dump({"input": args.get("-i"), "output": args.get("-o"), "offline": offline}, fh)

    if mode == "syntax":
        sys.stderr.write("Error: Parse error on line 9:\n...Unexpected token 'end'\n")
        return 1
    if mode == "hang":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        pid_file = os.environ.get("FAKE_MMDC_PID_FILE")
        if pid_file:
            with open(pid_file, "w", encoding="utf-8") as fh:
                fh.write(str(child.pid))
        time.sleep(60)
        return 0
    if mode == "enotcached" and offline:
        sys.stderr.write("npm error code ENOTCACHED\nnpm error request to https://registry.npmjs.org failed: cache mode is 'only-if-cached'\n")
        return 1
    if mode == "no-output":
        return 0

    with open(args["-o"], "w", encoding="utf-8") as fh:
        fh.write('<svg xmlns="http://www.w3.org/2000/svg"><text>fake</text></svg>\n')
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
