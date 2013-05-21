#!/usr/bin/env python

# Written in 2012 by Joe Tsai <joetsai@digital-static.net>
#
# ===================================================================
# The contents of this file are dedicated to the public domain. To
# the extent that dedication to the public domain is not available,
# everyone is granted a worldwide, perpetual, royalty-free,
# non-exclusive license to exercise all rights associated with the
# contents of this file for any purpose whatsoever.
# No rights are reserved.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
# BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
# ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
# ===================================================================

import re
import os
import sys
import time
import stat
import fcntl
import errno
import signal
import tempfile
import optparse
import subprocess

################################################################################
############################### Global variables ###############################
################################################################################

# Dictionary of streams to hijack
#  Key: 0 for stdin, 1 for stdout, 2 for stderr
#  Values: [local terminal file object, remote terminal file object, FIFO file object, target process original file descriptor]
streams = {0:[sys.stdin,None,None,None], 1:[sys.stdout,None,None,None], 2:[sys.stderr,None,None,None]}
hijack = [False, False, False] # Streams to hijack
mirror = [False, False, False] # Streams to reflect
pid = None # Target process
tempdir = None # Temporary directory, will clean-up at the end
sys_exit = False

################################################################################
################################ Helper classes ################################
################################################################################

class GDB_Client():
    def __init__(self):
        # Start a GDB process
        self.proc = subprocess.Popen(['gdb'], stdin = subprocess.PIPE, stdout = subprocess.PIPE, stderr = subprocess.PIPE)
        non_blocking(self.proc.stdout)
        non_blocking(self.proc.stderr)

        # Flush initial text
        self.proc.stdin.write("set prompt \\033[X\\n\n")
        while True:
            try:
                if '\x1b[X' in readline(self.proc.stdout): break
            except: pass
        while True:
            try: lines += self.proc.stderr.readline()
            except: break

    def command(self, cmd):
        self.proc.stdin.write(cmd+'\n')
        lines = ''
        while True:
            line = ''
            try: line = readline(self.proc.stdout)
            except: pass
            if '\x1b[X' in line: break
            lines += line
        while True:
            try: lines += self.proc.stderr.readline()
            except: break
        return lines

    def close(self):
        self.proc.stdin.write("set confirm off\n")
        self.proc.stdin.write("quit\n")

################################################################################
############################### Helper functions ###############################
################################################################################

def show_help(message):
    print message
    print "Try '%s --help' for more information" % sys.argv[0].strip()
    sys.exit(1)

def safe_exit(ret_code = 0, message = None):
    if message:
        print message

    # Perform clean-up on the target process
    gdb = GDB_Client()
    gdb.command('attach %s' % pid)
    for stream_num in range(3):
        # Copy temporary holders back into original stream and close the swap
        if streams[stream_num][3]:
            ret_text = gdb.command('call dup2(%s,%s)' % (streams[stream_num][3],str(stream_num)))
            ret_text = gdb.command('call close(%s)' % streams[stream_num][3])
    gdb.close()

    # Close the files opened for mirror reflection operations
    for stream_num in range(3):
        if streams[stream_num][1]:
            streams[stream_num][1].close()

    # Close each FIFO
    for stream_num in range(3):
        if streams[stream_num][2]:
            streams[stream_num][2].close()

    # Delete each FIFO and the temporary directory
    if tempdir:
        for stream_num in range(3):
            if streams[stream_num][2]:
                os.remove(os.path.join(tempdir,str(stream_num)))
        os.removedirs(tempdir)

    sys.exit(ret_code)

def interrupt_handler(sig_num, frame):
    global sys_exit
    if not sys_exit:
        sys_exit = True
        safe_exit(0, "\r----------\nDetached from target process!")

def check_pid(pid):
    try: os.kill(pid, 0)
    except OSError: return False
    else: return True

def non_blocking(file):
    file_desc = file.fileno()
    file_flags = fcntl.fcntl(file_desc, fcntl.F_GETFL)
    fcntl.fcntl(file_desc, fcntl.F_SETFL, file_flags | os.O_NONBLOCK)

def readline(file, timeout = 5):
        line = ''
        start_mark = time.time()
        while True:
            try:
                char = file.read(1)
                line += char
                if char == '\n': break
            except:
                if time.time() - start_mark > timeout: break
        return line

################################################################################
################################# Script setup #################################
################################################################################

epilog = """
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
latency during the transition where the target process is paused. Do NOT use
this script on time-critical processes. Also, this script may need to be run as
root in order for gdb to do its business.

Lastly, this script performs poorly with programs using either the ncurses or
readline GNU libraries due to the special way they interact with input/output
streams. Support for them may be added in the future.

Requires the GNU Debugger (gdb) in order to run.
"""

# Create a option parser
opts_parser = optparse.OptionParser(usage = "%s [options] PID" % sys.argv[0].strip(), epilog = epilog, add_help_option = False)
def func_epilog(formatter): return epilog
opts_parser.format_epilog = func_epilog
opts_parser.add_option('-h', '--help', action = 'help', help = 'Display this help and exit')
opts_parser.add_option('-v', '--version', dest = 'version', action = 'store_true', help = 'Display the script version and exit')
opts_parser.add_option('-i', '--hijack_stdin',  dest = 'hijack_stdin',  action = 'store_true', help = 'Hijack the standard input stream going to the target process [Default: False]')
opts_parser.add_option('-o', '--hijack_stdout', dest = 'hijack_stdout', action = 'store_true', help = 'Hijack the standard output stream coming from the target process [Default: False]')
opts_parser.add_option('-e', '--hijack_stderr', dest = 'hijack_stderr', action = 'store_true', help = 'Hijack the standard error stream coming from the target process [Default: False]')
opts_parser.add_option('-I', '--mirror_stdin',  dest = 'mirror_stdin',  action = 'store_true', help = 'Mirror input streams from both local and remote terminals to the target process [Default: False]')
opts_parser.add_option('-O', '--mirror_stdout', dest = 'mirror_stdout', action = 'store_true', help = 'Mirror the output stream from the target process to both the local and remote terminals [Default: False]')
opts_parser.add_option('-E', '--mirror_stderr', dest = 'mirror_stderr', action = 'store_true', help = 'Mirror the error stream from the target process to both the local and remote terminals [Default: False]')
(opts, args) = opts_parser.parse_args()

# Display version and quit
if opts.version:
    print "Terminal Hijacking Script 1.0"
    print " This is free software: you are free to change and redistribute it."
    print " Written in 2012 by Joe Tsai <joetsai@digital-static.net>"
    sys.exit(0)

# Check the target process argument
if len(args) != 1:
    show_help("Invalid number of required arguments")
try:
    pid = str(int(args[0]))
except:
    show_help("Invalid target process: %s" % args[0])

# Check which streams to hijack (If mirror is enabled, assume a hijacking was on order)
opts.hijack_stdin = True if opts.mirror_stdin else opts.hijack_stdin
opts.hijack_stdout = True if opts.mirror_stdout else opts.hijack_stdout
opts.hijack_stderr = True if opts.mirror_stderr else opts.hijack_stderr
hijack = [opts.hijack_stdin, opts.hijack_stdout, opts.hijack_stderr] # Streams to hijack
mirror = [opts.mirror_stdin, opts.mirror_stdout, opts.mirror_stderr] # Streams to reflect
if True not in hijack:
    show_help("Must hijack at least one stream")

# Interrupt handler
signal.signal(signal.SIGTERM, interrupt_handler)
signal.signal(signal.SIGQUIT, interrupt_handler)
signal.signal(signal.SIGINT, interrupt_handler)

# Set local stdin as non-blocking
non_blocking(sys.stdin)

################################################################################
################################# Script start #################################
################################################################################

# Check that gdb is even installed
try:
    subprocess.Popen(['gdb','--version'], stdout = subprocess.PIPE, stderr = subprocess.PIPE).wait()
except:
    safe_exit(1, "Error: Could not find an installation of GNU Debugger (gdb) on this system")

# Generated named pipes
tempdir = tempfile.mkdtemp(prefix = 'termijack_')
os.chmod(tempdir,0711) # Target process must be able to access this folder
try:
    for stream_num in range(3):
        if hijack[stream_num]:
            os.mkfifo(os.path.join(tempdir,str(stream_num)))
            os.chmod(os.path.join(tempdir,str(stream_num)),0666) # Target process must be able to read these pipes
            streams[stream_num][2] = open(os.path.join(tempdir,str(stream_num)), 'w+' if (stream_num == 0) else 'r+')
            non_blocking(streams[stream_num][2])
except:
    safe_exit(1, "Error: Could not create temporary FIFO pipes")

# Attach gdb to the target process
gdb = GDB_Client()
line = gdb.command('attach %s' % pid)
if "No such process" in line:
    safe_exit(1, "Error: The target process does not exist")
elif "Operation not permitted" in line:
    safe_exit(1, "Error: Attaching to target process not permitted")
elif "Could not attach" in line:
    safe_exit(1, "Error: Could not attach to target process")

# Redirect streams as necessary
for stream_num in range(3):
    if hijack[stream_num]:
        # Open named pipes on target process
        ret_text = gdb.command('call open("%s",66)' % os.path.join(tempdir,str(stream_num)))
        pipe_fd = re.search(r"\$[0-9]+ = ([0-9]+)",ret_text).groups()[0]

        # Copy original flags to the new pipes
        ret_text = gdb.command('call fcntl(%s,4,fcntl(%s,3))' % (pipe_fd,str(stream_num)))

        # Copy original stream into temporary holders
        ret_text = gdb.command('call dup(%s)' % str(stream_num))
        streams[stream_num][3] = re.search(r"\$[0-9]+ = ([0-9]+)",ret_text).groups()[0]

        # Copy new pipes into original stream
        ret_text = gdb.command('call dup2(%s,%s)' % (pipe_fd,str(stream_num)))

        # Close the opened pipe
        ret_text = gdb.command('call close(%s)' % pipe_fd)
gdb.close()
print  "Attached to target process %s" % pid

# Open virtual terminals for stealthy reflection tricks
for stream_num in range(3):
    if mirror[stream_num]:
        stream_type = {0:'stdin', 1:'stdout', 2:'stderr'}
        file_real = os.path.realpath(os.path.join("/proc",pid,'fd',streams[stream_num][3]))
        try:
            if re.search("^/dev/",file_real) and stat.S_ISCHR(os.stat(file_real).st_mode):
                streams[stream_num][1] = open(file_real,'rw+')
                non_blocking(streams[stream_num][1])
            else:
                print "Warning: The file %s does not represent a valid terminal for %s" % (file_real, stream_type[stream_num])
        except OSError, ex:
            print "Warning: %s while accessing %s for %s" % (ex.strerror, file_real, stream_type[stream_num])
print "----------"

while True:
    # Forward to target stdin from:
    if hijack[0]:
        # Local stdin
        try:
            streams[0][2].write(streams[0][0].read())
            streams[0][2].flush()
        except: pass
        # Remote stdin
        try:
            streams[0][2].write(streams[0][1].read())
            streams[0][2].flush()
        except: pass

    # Forward target stdout to:
    if hijack[1]:
        try:
            data = streams[1][2].read()
            # Local stdout
            if streams[1][0]:
                streams[1][0].write(data)
                streams[1][0].flush()
            # Remote stdout
            if streams[1][1]:
                streams[1][1].write(data)
                streams[1][1].flush()
        except: pass

    # Forward target stderr to:
    if hijack[2]:
        try:
            data = streams[2][2].read()
            # Local stderr
            if streams[2][0]:
                streams[2][0].write(data)
                streams[2][0].flush()
            # Remote stderr
            if streams[2][1]:
                streams[2][1].write(data)
                streams[2][1].flush()
        except: pass

    # Check if target process died
    if not check_pid(int(pid)):
        safe_exit(0,"\r----------\nTarget process died!")

    time.sleep(0.01)

# EOF
