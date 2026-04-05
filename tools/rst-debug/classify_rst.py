#!/usr/bin/env python3
import os
import re
import subprocess
import sys
import time
from collections import deque

IFACE = os.environ.get("RST_DEBUG_IFACE", "eth0")
PORT = os.environ.get("RST_DEBUG_PORT", "443")
LOG_PATH = sys.argv[1] if len(sys.argv) > 1 else os.environ.get(
    "RST_DEBUG_LOG", "/var/log/transithub-rst-debug/rst443.log"
)
FLOW_WINDOW = int(os.environ.get("RST_DEBUG_FLOW_WINDOW", "180"))
SRC_WINDOW = int(os.environ.get("RST_DEBUG_SRC_WINDOW", "180"))
TTL_DELTA_SUSPICIOUS = int(os.environ.get("RST_DEBUG_TTL_DELTA", "6"))
DUP_WINDOW = float(os.environ.get("RST_DEBUG_DUP_WINDOW", "1.5"))
MAX_EVENTS = int(os.environ.get("RST_DEBUG_MAX_EVENTS", "4000"))

line1_re = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)\s+IP\s+\(.*ttl\s+(?P<ttl>\d+),.*length\s+(?P<ip_len>\d+)\)$"
)
line2_re = re.compile(
    r"^\s*(?P<src_ip>\d+\.\d+\.\d+\.\d+)\.(?P<src_port>\d+)\s+>\s+"
    r"(?P<dst_ip>\d+\.\d+\.\d+\.\d+)\.(?P<dst_port>\d+):\s+Flags\s+\[(?P<flags>[^\]]+)\].*length\s+(?P<payload_len>\d+)"
)
state_re = re.compile(
    r"\b(SYN_SENT|SYN_RECV|ESTABLISHED|FIN_WAIT|CLOSE_WAIT|LAST_ACK|TIME_WAIT|CLOSE)\b"
)

flows = {}
src_seen = {}
order = deque()
last_rst = {}


def now_ts():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def prune(now):
    while order and now - order[0][0] > max(FLOW_WINDOW, SRC_WINDOW):
        ts0, kind, key = order.popleft()
        if kind == "flow":
            cur = flows.get(key)
            if cur and cur["seen_at"] == ts0:
                flows.pop(key, None)
        else:
            cur = src_seen.get(key)
            if cur and cur == ts0:
                src_seen.pop(key, None)
    for key, seen_at in list(last_rst.items()):
        if now - seen_at > DUP_WINDOW:
            last_rst.pop(key, None)


def conntrack_state(src_ip, src_port, dst_ip, dst_port):
    try:
        with open("/proc/net/nf_conntrack", "r", encoding="utf-8", errors="replace") as fh:
            needle = f"src={src_ip} dst={dst_ip} sport={src_port} dport={dst_port}"
            for line in fh:
                if needle in line:
                    match = state_re.search(line)
                    return match.group(1) if match else "present"
    except FileNotFoundError:
        return "-"
    return "-"


def log(message):
    with open(LOG_PATH, "a", encoding="utf-8") as fh:
        fh.write(message + "\n")
    print(message, flush=True)


os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
open(LOG_PATH, "w", encoding="utf-8").close()
log(f"[{now_ts()}] classifying inbound TCP traffic on {IFACE} dst port {PORT}")
cmd = ["tcpdump", "-ni", IFACE, "-l", "-tttt", "-nn", "-v", f"tcp dst port {PORT}"]
proc = subprocess.Popen(
    cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1
)

pending = None
for raw in proc.stdout:
    line = raw.rstrip("\n")
    match1 = line1_re.match(line)
    if match1:
        pending = {
            "ts": match1.group("ts"),
            "ttl": int(match1.group("ttl")),
            "ip_len": int(match1.group("ip_len")),
        }
        continue
    if pending is None:
        continue
    match2 = line2_re.match(line)
    if not match2:
        pending = None
        continue

    pkt = pending | match2.groupdict()
    pending = None
    pkt["payload_len"] = int(pkt["payload_len"])
    now = time.time()
    prune(now)
    flow_key = (pkt["src_ip"], pkt["src_port"], pkt["dst_ip"], pkt["dst_port"])
    src_key = pkt["src_ip"]
    flags = pkt["flags"]

    if "R" not in flags:
        flow = flows.get(flow_key) or {
            "first_ttl": pkt["ttl"],
            "last_ttl": pkt["ttl"],
            "last_flags": flags,
            "last_payload_len": pkt["payload_len"],
            "seen_fin": False,
            "seen_syn": "S" in flags,
        }
        flow["seen_at"] = now
        flow["last_ttl"] = pkt["ttl"]
        flow["last_flags"] = flags
        flow["last_payload_len"] = pkt["payload_len"]
        flow["seen_fin"] = flow["seen_fin"] or ("F" in flags)
        flow["seen_syn"] = flow["seen_syn"] or ("S" in flags)
        flows[flow_key] = flow
        src_seen[src_key] = now
        order.append((now, "flow", flow_key))
        order.append((now, "src", src_key))
        if len(order) > MAX_EVENTS:
            prune(now)
        continue

    dedup_key = (pkt["src_ip"], pkt["src_port"], pkt["dst_ip"], pkt["dst_port"], pkt["ttl"])
    if dedup_key in last_rst:
        continue
    last_rst[dedup_key] = now

    flow_info = flows.get(flow_key)
    flow_seen = bool(flow_info and (now - flow_info["seen_at"]) <= FLOW_WINDOW)
    src_recent = bool(src_key in src_seen and (now - src_seen[src_key]) <= SRC_WINDOW)
    conn_state = conntrack_state(
        pkt["src_ip"], pkt["src_port"], pkt["dst_ip"], pkt["dst_port"]
    )
    ttl_base = flow_info["last_ttl"] if flow_info else None
    ttl_delta = abs(pkt["ttl"] - ttl_base) if ttl_base is not None else -1
    gap_ms = int((now - flow_info["seen_at"]) * 1000) if flow_info else -1
    fin_seen = bool(flow_info and flow_info.get("seen_fin"))

    if conn_state == "-" and not flow_seen:
        verdict = "suspicious-no-flow"
    elif ttl_delta >= TTL_DELTA_SUSPICIOUS and conn_state in {
        "ESTABLISHED",
        "CLOSE",
        "TIME_WAIT",
        "CLOSE_WAIT",
        "LAST_ACK",
        "FIN_WAIT",
    }:
        verdict = "suspicious-ttl"
    elif fin_seen and conn_state in {"CLOSE", "TIME_WAIT", "LAST_ACK", "FIN_WAIT"}:
        verdict = "likely-normal-after-fin"
    elif conn_state in {"CLOSE", "TIME_WAIT", "LAST_ACK", "FIN_WAIT"} and src_recent:
        verdict = "likely-normal"
    elif conn_state == "ESTABLISHED" and not flow_seen:
        verdict = "suspicious-no-local-observation"
    elif conn_state != "-":
        verdict = "has-conntrack"
    else:
        verdict = "unknown"

    ttl_base_text = str(ttl_base) if ttl_base is not None else "-"
    ttl_delta_text = str(ttl_delta) if ttl_delta >= 0 else "-"
    gap_text = str(gap_ms) if gap_ms >= 0 else "-"
    verdict_label = {
        "likely-normal": "normal  ",
        "likely-normal-after-fin": "norm-fin",
        "has-conntrack": "has-conn",
        "unknown": "unknown ",
        "suspicious-no-flow": "no-flow?",
        "suspicious-ttl": "susp-ttl",
        "suspicious-no-local-observation": "no-local?",
    }.get(verdict, verdict[:8].ljust(8))
    log(
        f"{now_ts()} [{verdict_label}] src={pkt['src_ip']} spt={pkt['src_port']} ttl={pkt['ttl']} "
        f"flow={'yes' if flow_seen else 'no'} recent={'yes' if src_recent else 'no'} ct={conn_state} "
        f"gap={gap_text}ms first_ttl={flow_info['first_ttl'] if flow_info else '-'} "
        f"last_ttl={ttl_base_text} dttl={ttl_delta_text} fin={'yes' if fin_seen else 'no'}"
    )
