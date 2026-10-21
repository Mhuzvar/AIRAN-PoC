import selectors
import subprocess
import sys
import time
import os

WRITE_INTERVAL = 2*60
OUTDIR = 'RANalyzer_output'
TMP = '/tmp'

def read_message(cmd, quiet_ms=200):
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    sel = selectors.DefaultSelector()
    sel.register(proc.stdout, selectors.EVENT_READ)

    buf = []
    while True:
        events = sel.select(timeout=quiet_ms / 1000)
        if events:
            line = proc.stdout.readline()
            if line == "" and proc.poll() is not None:
                break
            buf.append(line)
        else:
            if buf:
                yield "".join(buf)
                buf = []
    if buf:
        yield "".join(buf)



if __name__=="__main__":
    cmd = sys.argv[1:]
    if not cmd:
        sys.exit("usage: RANalyzer.py <nr-softmodem command and args...>")
    os.makedirs(OUTDIR, exist_ok=True)
    timecheckpoint = time.time()

    frame = ''
    for message in read_message(cmd):
        with open(os.path.join(TMP, 'gnb_log.txt'), 'a') as logfile:
            logfile.write(message)
        frame+=message
        if time.time()-timecheckpoint>WRITE_INTERVAL:
            with open(os.path.join(OUTDIR, f'diagdata_{time.strftime("%Y%m%d%H%M%S.txt", time.localtime(time.time()))}'), 'w') as dumpfile:
                dumpfile.write(frame)
            frame = ''
            timecheckpoint = time.time()
