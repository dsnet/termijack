# Terminal Hijacker #

## Introduction ##

![terminal](http://code.digital-static.net/termijack/raw/tip/doc/terminal.gif)

Hijacks the standard streams (stdout, stdin, and/or stderr) from an already
running process and silently returns them back after finishing. While this
script is running and attached to another process, the user may interact with
the running process as if they were interacting with the original terminal.

This script also provides the ability to mirror hijacked streams. In the case
of standard input, this means that inputs from both this terminal and the
remote terminal will be forwarded to the target process. Similarly, standard
output and error coming from the target process will be forwarded to both this
terminal and the remote terminal.

While gdb is being used to hijack standard streams, there may be a small
latency during the transition where the target process is paused. Do _not_ use
this script on time-critical processes. Also, this script may need to be run as
root in order for gdb to do its business.

Lastly, this script performs poorly with programs using either the ncurses or
readline GNU libraries due to the special way they interact with input/output
streams. Support for them may be added in the future.

Requires the GNU Debugger (gdb) in order to run.

## Usage ##

Hijack stdin, stdout and stderr:

* ```./termijack.py -ioe $TARGET_PID```
