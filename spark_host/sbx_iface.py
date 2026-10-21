import os
import time
import subprocess
import argparse
from fnmatch import fnmatch
import re
import sys
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import traceback
import socket
import telnetlib
import numpy as np

from datetime import date
from random import randint

#OUTPUT_CSV = "/home/mitlab-ai-edge-server/Documents/oai/python_scripts/RANalyzer_output/rfsim_parsed_data"
OUTPUT_PLOT = "output_plot_oai.png"
RESPFILE="OAI_API.txt"
TNET_IP='127.0.0.1'
TNET_PORT='9090'
GNODEB_LOG_FILE='/tmp/gnb_log.txt'
GNODEB_STATUS_FILE='/tmp/station_status.txt'
LOCKFILE='/tmp/sbx_iface_API.lock'
OAI_LOCK='/tmp/oai.lock'

def log_msg(msg, verbose, path='/tmp/sbx_iface.log'):
    logmsg = f"[{time.strftime("%Y/%m/%d-%H:%M:%S", time.localtime(time.time()))}] "+msg
    if verbose:
        print(logmsg)
    with open(path, 'a') as log:
        log.write(logmsg+"\n")

def parse_oai_log(filepath):
    #Helper Variables
    current_ue_list = {}
    ue_sync_states = {}
    current_ue = None
    #Regexes
    ue_header_regex = re.compile(r"UE RNTI ([a-f0-9]+) CU-UE-ID \d+ ([\w-]+)")
    dlsch_regex = re.compile(r"UE [a-f0-9]+: dlsch_rounds .*?\(SNR ([\d.]+)\+.*?BLER ([\d.]+) MCS \(\d+\) \d+ \(Qm (\d+)\)")
    ulsch_regex = re.compile(r"UE [a-f0-9]+: ulsch_rounds .*?BLER ([\d.]+) MCS \(\d+\) \d+ \(Qm (\d+).*?NPRB (\d+) SNR ([\d.]+)")
    with open(filepath, "r", encoding="utf-8") as logs:
        for line in logs:
            line = line.strip()
            ue_match = ue_header_regex.search(line)
            if ue_match:
                ue_id = str(ue_match.group(1))
                sync_status = str(ue_match.group(2))
                ue_sync_states[ue_id] = sync_status
                if ue_id not in current_ue_list:
                    current_ue_list[ue_id] = {
                        "Sync_Status": [],
                        "DL_SNR": [],
                        "DL_BLER": [],
                        "DL_Qm": [],
                        "UL_SNR": [],
                        "UL_BLER": [],
                        "UL_Qm": [],
                        "UL_NPRB": []
                    }
                current_ue = ue_id
                continue
            if not current_ue:
                continue
            dlsch_match = dlsch_regex.search(line)
            if dlsch_match:
                status_str = ue_sync_states.get(current_ue, "out-of-sync")
                status_val = 1.0 if status_str == "in-sync" else 0.0
                current_ue_list[current_ue]["Sync_Status"].append(status_val)
                current_ue_list[current_ue]["DL_SNR"].append(float(dlsch_match.group(1)))
                current_ue_list[current_ue]["DL_BLER"].append(float(dlsch_match.group(2)))
                current_ue_list[current_ue]["DL_Qm"].append(float(dlsch_match.group(3)))
                continue
            ulsch_match = ulsch_regex.search(line)
            if ulsch_match:
                current_ue_list[current_ue]["UL_SNR"].append(float(ulsch_match.group(4)))
                current_ue_list[current_ue]["UL_BLER"].append(float(ulsch_match.group(1)))
                current_ue_list[current_ue]["UL_Qm"].append(float(ulsch_match.group(2)))
                current_ue_list[current_ue]["UL_NPRB"].append(float(ulsch_match.group(3)))
    return current_ue_list

def convert_to_dataframe(raw_ue_data):
    rows_list = []
    for ue_id, metrics in raw_ue_data.items():
        min_len = min(len(v) for v in metrics.values())
        for i in range(min_len):
            row = {
                "UE_ID": ue_id,
                "Sync_status": metrics["Sync_Status"][i],
                "DL_SNR": metrics["DL_SNR"][i],
                "DL_BLER": metrics["DL_BLER"][i],
                "DL_Qm": metrics["DL_Qm"][i],
                "UL_SNR": metrics["UL_SNR"][i],
                "UL_BLER": metrics["UL_BLER"][i],
                "UL_Qm": metrics["UL_Qm"][i],
                "UL_NPRB": metrics["UL_NPRB"][i]
            }
            rows_list.append(row)
    return pd.DataFrame(rows_list)

def plot_radio_data(df, ue_id, output_filename):
    """
    Generates and saves a time-series plot of radio parameters for the specified UE to a file.
    """

    # Filtrujemy dane dla wybranego UE i bierzemy np. pierwsze 200 punktów, żeby wykres był czytelny
    #ue_df = df[df["UE_ID"] == ue_id].iloc[:200].reset_index(drop=True)
    ue_df = df[df["UE_ID"] == ue_id].tail(20).reset_index(drop=True)

    if ue_df.empty:
        print(f"No data to plot for UE: {ue_id}")
        return

    # Ustawienie ładnego stylu graficznego
    sns.set_theme(style="whitegrid")

    # Tworzymy dwa wykresy jeden pod drugim ze wspólną osią X (kroki czasowe)
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

    # ----------------------------------------------------
    # PANELI 1: Rząd Modulacji (DL_Qm) oraz Stopa Błędów (DL_BLER)
    # ----------------------------------------------------
    color_qm = '#1f77b4'  # Niebieski
    ax1.plot(ue_df.index, ue_df['DL_Qm'], color=color_qm, linewidth=2.5, label='Modulation (DL_Qm)')
    ax1.set_ylabel('Modulation Order (Qm)', color=color_qm, fontsize=12, fontweight='bold')
    ax1.tick_params(axis='y', labelcolor=color_qm)
    ax1.set_title(f'Link Adaptation and Bandwidth Allocation (OAI Device: {ue_id})', fontsize=14, fontweight='bold', pad=15)

    # Druga oś Y (prawa strona) dla BLER, bo ma zupełnie inną skalę (bliską 0)
    ax1_right = ax1.twinx()
    color_bler = '#d62728'  # Czerwony
    ax1_right.fill_between(ue_df.index, ue_df['DL_BLER'], color=color_bler, alpha=0.15, label='Errors (DL_BLER)')
    ax1_right.plot(ue_df.index, ue_df['DL_BLER'], color=color_bler, linewidth=1.2, linestyle='--')
    ax1_right.set_ylabel('Block Error Rate (DL_BLER)', color=color_bler, fontsize=12, fontweight='bold')
    ax1_right.tick_params(axis='y', labelcolor=color_bler)
    ax1_right.grid(False)

    # ----------------------------------------------------
    # PANEL 2: Przydział Bloków Zasobów (UL_NPRB)
    # ----------------------------------------------------
    color_nprb = '#2ca02c'  # Zielony
    ax2.plot(ue_df.index, ue_df['UL_NPRB'], color=color_nprb, linewidth=1.8, marker='o', markersize=3, label='Allocation NPRB')
    ax2.set_xlabel('Consecutive Frames / Measurements (Index)', fontsize=12, fontweight='bold')
    ax2.set_ylabel('Number of PRB Blocks (UL_NPRB)', color=color_nprb, fontsize=12, fontweight='bold')
    ax2.tick_params(axis='y', labelcolor=color_nprb)

    # Dopasowanie marginesów
    plt.tight_layout()
    
    # Zapis wykresu do pliku graficznego
    plt.savefig(output_filename, dpi=300)
    plt.close()

def display_dataframe(df):

    print("\n" + "=" * 50)
    print("PANDAS DATAFRAME SUMMARY:")
    print("=" * 50)
    print(f" -> Total parsed row records: {len(df)}")

    # Tymczasowe wymuszenie pokazania pełnej tabeli bez skracania
    pd.set_option('display.max_rows', None)
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 1000)

    print("\nComplete Table Content:")
    print(df)

    # Przywrócenie domyślnych ustawień (dobra praktyka programistyczna)
    pd.reset_option('display.max_rows')
    pd.reset_option('display.max_columns')
    pd.reset_option('display.width')

def upload_to_sandbox(sandbox_name: str, local_path: str, remote_path: str = "/tmp/data.txt", verb=True):
    result = subprocess.run(
        ["nemoclaw", sandbox_name, "upload", local_path, remote_path],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        log_msg(f"Upload {local_path} to {remote_path} on {sandbox_name} successful.", verb, path=args.log_path)
        return 0
    else:
        log_msg(f"Upload ({local_path} local -> {remote_path} on {sandbox_name}) failed with code {result.returncode}!\nstdout:\n{result.stdout}\nstderr\n{result.stderr}", verb, path=args.log_path)
        return 1
    
def download_from_sandbox(sandbox_name: str, local_path: str, remote_path: str = "/tmp/commands.txt", verb=True):
    result = subprocess.run(
        ["nemoclaw", sandbox_name, "download", remote_path, local_path],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        log_msg(f"Download from {remote_path} on {sandbox_name} to {local_path} successful.", verb, path=args.log_path)
        return 0
    else:
        log_msg(f"Download ({remote_path} on {sandbox_name} -> {local_path} local) failed with code {result.returncode}!\nstdout:\n{result.stdout}\nstderr\n{result.stderr}", verb, path=args.log_path)
        return 1

def get_channel_dataframe(host, port):
    # 1. Pobranie danych z serwera
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((host, int(port)))
        s.settimeout(1.0)
        try:
            s.recv(1024)
        except socket.timeout:
            pass
        s.sendall("channelmod show current\n".encode("utf-8"))
        time.sleep(0.5)
        raw_output = s.recv(16384).decode("utf-8")

    # 2. Parsowanie regex
    pattern = (
        r"model\s+(\d+)\s+rfsimu_channel_(\w+).*?"
        r"path loss:\s*([-\d.]+).*?"
        r"noise:\s*([-\d.]+)"
    )
    records = [
        {
            "channel_id": int(m.group(1)),
            "ue_name": m.group(2),
            "ploss": float(m.group(3)),
            "noise_power_dB": float(m.group(4)),
        }
        for m in re.finditer(pattern, raw_output, re.DOTALL)
    ]

    data_obtained = False
    snr_list=[]
    rssi_list=[]
    ue_list=[]
    tail_len=80
    while not data_obtained:
        res = subprocess.run(['tail', '-n', str(tail_len), GNODEB_LOG_FILE], capture_output=True, text=True)
        if res.returncode==0:
            UE_idx = res.stdout.find('CU-UE-ID')
            uls_idx = res.stdout.find('ulsch_rounds')
            if UE_idx*uls_idx>1:
                msg = res.stdout[UE_idx:]
                if len(msg)>11:
                    tx_msg = msg[:50].split()
                    tx_p = int(tx_msg[7])-int(tx_msg[4])
                msg = res.stdout[uls_idx-6:]
                while len(msg)>11:
                    ue_list.append(msg.split()[0][:-1])
                    snr_list.append(float(msg[msg.find('SNR'):].split()[1]))
                    rssi_list.append(float(msg[msg.find('RSSI'):].split()[1]))
                    data_obtained=True
                    msg = msg[30:]
                    msg = msg[msg.find('ulsch_rounds')-6:]
            else:
                tail_len+=80
        else:
            time.sleep(0.1)
    return pd.DataFrame(records), ue_list, snr_list, rssi_list, tx_p

def update_state(upd_state, sysargs):
    try:
        with open(GNODEB_STATUS_FILE, 'w') as statefile:
            statefile.writelines(upd_state)
        log_msg('Updating station parameter state success',sysargs.verbose,sysargs.log_path)
    except:
        log_msg(f'Updating station parameter state failed:\n{traceback.format_exc()}',sysargs.verbose,sysargs.log_path)

def ai2telnet(inst, state, args):
    cmdok=False
    tn_cmds=[]
    problem=None
    instlist=inst.split(' ')
    if instlist[0]=='gNodeSteer':
        cdf, ues, snr, rssi, tx_p = get_channel_dataframe(TNET_IP, TNET_PORT)
        # there should be a check for when the dataframe comes back empty as that could break the run
        cmdok=True
    else:
        return (cmdok, None, (0, instlist[0]))
    i=1
    pl_current = cdf['ploss'].tolist()
    npwr_current = cdf['noise_power_dB'].tolist()
    state_new = state

    print(f"dataframe:\n{cdf}")

    while cmdok and i<len(instlist):
        inc=2
        match instlist[i]:
            case 'help':
                tn_cmds.append('help')
                inc=1
            case 'tx_amp_backoff_dB':
                # transmit power backoff of the gNB
                # affects transmitter (common) => same value change for every channel
                try:
                    oldval = float(state[0])
                    newval = float(instlist[i+1])
                    delta = newval-oldval
                    for j in range(len(cdf)):
                        pl_current[j]+=delta    # TX backoff only affects ploss (should recheck with the expert)
                    state_new[0] = str(newval)+'\n'
                except:
                    problem=(i, f'{instlist[i]}\n{traceback.format_exc()}')
                    cmdok=False
                    continue
            case 'beam_gains':
                # spatial modulation or some other radio voodoo
                # let's do this later
                problem=(i, instlist[i])
                cmdok=False
            case 'resource_block_admission':
                # if we find out how to do this
                problem=(i, instlist[i])
                cmdok=False
            case _:
                problem=(i, instlist[i])
                cmdok=False
        i+=inc
    if cmdok:
        for ch_idx in range(len(cdf)):
            if npwr_current[ch_idx]!=cdf['noise_power_dB'].tolist()[ch_idx]:
                tn_cmds.append(f'channelmod modify {ch_idx} noise_power_dB {npwr_current[ch_idx]}')
            else:
                log_msg('noise power remains unchanged.', args.verbose, args.log_path)
            if pl_current[ch_idx]!=cdf['ploss'].tolist()[ch_idx]:
                tn_cmds.append(f'channelmod modify {ch_idx} ploss {pl_current[ch_idx]}')
            else:
                log_msg('path loss remains unchanged.', args.verbose, args.log_path)
        update_state(state_new, args)

    return (cmdok,tn_cmds,problem)

def run_telnet(commands, ip_address, port, verb, logpath):
    try:
        with telnetlib.Telnet(ip_address, port) as tn:
            log_msg(f"Successfully connected to {ip_address}:{port}.", verb, logpath)
            time.sleep(1)
            for i, command in enumerate(commands, 1):
                log_msg(f"[{i}/{len(commands)}] Executing: {command}", verb, logpath)
                # Send command
                tn.write((command + "\n").encode("utf-8"))
                # Wait until the service returns its full prompt.
                output = tn.read_until(b"softmodem_gnb>")
                log_msg(output.decode("utf-8", errors="replace"), verb, logpath)
        log_msg("All commands were executed. Closing connection...", verb, logpath)
        tn.close()
    except:
        log_msg(f"An error encountered in telenet communication:\n{traceback.format_exc()}", verb, logpath)

if __name__=="__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-s", "--sandbox",
                        default="ayran-sgl",
                        help="Name of the sandbox to work with")
    parser.add_argument("-i", "--input_directory",
                        default="RANalyzer_output",
                        help="Path to dumpfile directory")
    parser.add_argument("-o", "--target_directory",
                        default="/tmp",
                        help="directory to upload to in sandbox")
    parser.add_argument("-d", "--download_directory",
                            default="/sandbox/agent_responses",
                            help="directory to download from in sandbox")
    parser.add_argument("-c", "--cleanup",
                        action='store_true',
                        help="Specifies whether to remove old dumpfiles")
    parser.add_argument("-w", "--wait_time",
                        type=int, default=60,
                        help="How many secods to wait between iterations.")
    parser.add_argument("-v", "--verbose",
                        action='store_true',
                        help="verbose mode")
    parser.add_argument("-l", "--log_path",
                        default="/tmp/sbx_iface.log",
                        help="Path to log")
    parser.add_argument("-a", "--api_cmd_path",
                        default="./oai_api_cmds.txt",
                        help="Path to file with API commands")
    parser.add_argument("-k", "--keep_api_history",
                        action='store_true',
                        help="Turn off logging old commands?")
    parser.add_argument("--api_history",
                        default='/tmp/oai_api_history.log',
                        help='old commands log')

    args = parser.parse_args()

    previous_content = None
    last_diag = None
    with open(GNODEB_STATUS_FILE, 'r') as statfile:
        station_state = statfile.readlines()
        log_msg(f"Base station state ({len(station_state)} values) loaded.", args.verbose, args.log_path)
    
    while True:
        ti = time.time()
        flist = sorted(os.listdir(args.input_directory))
        flist = [s for s in flist if fnmatch(s, "diagdata_??????????????.txt")]
        if flist and flist[-1]!=last_diag:
            last_diag = flist[-1]
            log_msg(f"Found {flist[-1]}, converting to pandas.", args.verbose, path=args.log_path)
            raw_data = parse_oai_log(os.path.join(args.input_directory, flist[-1]))
            df = convert_to_dataframe(raw_data)
            if args.verbose:
                display_dataframe(df)
            if 'UE_ID' in df.keys():
                ues = df["UE_ID"].unique()
                for ue in ues:
                    plot_name = f"output_plot_{ue}.png"
                    plot_radio_data(df, ue_id=ue, output_filename=OUTPUT_PLOT)
            df.to_csv(os.path.join(args.input_directory, 'temp.csv'), index=False, encoding='UTF-8')
            upload_to_sandbox(args.sandbox, os.path.join(args.input_directory, 'temp.csv'),
                              os.path.join(args.target_directory,flist[-1][:-3]+'csv'), verb=args.verbose)
            if args.cleanup:
                if flist:
                    log_msg(f"{len(flist)} files in directory, cleaning up.", args.verbose, path=args.log_path)
                else:
                    log_msg(f"Nothing to clean up.", args.verbose, path=args.log_path)
                for f in flist:
                    os.remove(os.path.join(args.input_directory, f))
        else:
            log_msg(f"No new data to pass.", args.verbose, path=args.log_path)

        #########################################################################
        # traffic steering
        is_new = False
        dlret=download_from_sandbox(args.sandbox, args.api_cmd_path, os.path.join(args.download_directory, RESPFILE), verb=args.verbose)
        if dlret==0:
            if os.path.exists(args.api_cmd_path):
                with open(args.api_cmd_path, "r") as f:
                        new_content = f.read()
                is_new=previous_content!=new_content
            else:
                log_msg(f"File not found: {args.api_cmd_path}!")
        if is_new:
            previous_content=new_content
            log_msg(f"New steering instructions detected, applying.", args.verbose, path=args.log_path)
            while os.path.exists(OAI_LOCK):
                time.sleep(1)
            open(LOCKFILE, "w").close()
            if not args.keep_api_history:
                cmdhistdate=time.localtime(time.time())
                log_msg(f"Saving commands to {args.api_history} dated {time.strftime("%Y/%m/%d-%H:%M", cmdhistdate)}.", args.verbose, path=args.log_path)
                with open(args.api_history, 'a') as api_hist:
                    for i in new_content.split('\n'):
                        if i=='':
                            continue
                        api_hist.write(f'[{time.strftime("%Y/%m/%d-%H:%M:%S", cmdhistdate)}] {i}\n')

            with open(GNODEB_STATUS_FILE, 'r') as statfile:
                station_state = statfile.readlines()
                log_msg(f"Base station state ({len(station_state)} values) loaded.", args.verbose, args.log_path)

            for i in new_content.split('\n'):
                if i=='':
                    continue
                log_msg(f"Decoding {i}.", args.verbose, path=args.log_path)
                telnet_cmd = ai2telnet(i, station_state, args)
                # returns (T/F whether the commands are valid, telnet commands, traceback message if occcured)
                if telnet_cmd[0]:
                    run_telnet(telnet_cmd[1], TNET_IP, TNET_PORT, args.verbose, args.log_path)
                else:
                    log_msg(f"Not recognised as a valid command: {i}\nProblem occured at parameter {telnet_cmd[2][0]}: {telnet_cmd[2][1]}", args.verbose, path=args.log_path)
            os.remove(LOCKFILE)
        else:
            log_msg(f"No steering applied.", args.verbose, path=args.log_path)

        time.sleep(max(0, args.wait_time - int(time.time()-ti)))
