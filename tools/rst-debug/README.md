# RST Debug Monitor

This is a host-side TCP RST monitor for `443/tcp`.
It is designed for quick diagnostics on Debian-like VPS hosts where you need to understand whether incoming `RST` packets look normal or suspicious.

## What It Does

- Watches inbound TCP traffic on one interface, default `eth0`
- Looks only at traffic to one destination port, default `443`
- Tracks recent non-RST packets for each observed client flow
- Reads `/proc/net/nf_conntrack` to check whether the kernel knows the flow
- Writes short verdict lines to a log file
- Does not insert firewall rules, block IPs, or change routing

## Verdict Labels

- `[normal  ]`: looks like a normal close
- `[norm-fin]`: looks like a normal close after `FIN`
- `[has-conn]`: kernel knows the flow, but local observations are thin
- `[unknown ]`: not enough evidence either way
- `[susp-ttl]`: `RST TTL` differs sharply from recent packets of the same flow
- `[no-flow?]`: no recent flow context and no matching conntrack state

## Requirements

- Linux host with root access
- `python3`
- `tcpdump`
- `/proc/net/nf_conntrack` available

## Install

```bash
apt-get update
apt-get install -y python3 tcpdump
cd tools/rst-debug
bash install.sh
```

## Watch

Plain log:

```bash
tail -f /var/log/transithub-rst-debug/rst443.log
```

Colorized:

```bash
/usr/local/bin/transithub-rst-debug-watch-color
```

## Configure

Edit:

```bash
/etc/default/transithub-rst-debug
```

Defaults:

```bash
RST_DEBUG_IFACE=eth0
RST_DEBUG_PORT=443
RST_DEBUG_LOG=/var/log/transithub-rst-debug/rst443.log
```

Then restart:

```bash
systemctl restart transithub-rst-debug.service
```

## Remove

```bash
cd tools/rst-debug
bash uninstall.sh
```

This removes the service and binaries, but leaves:

- `/etc/default/transithub-rst-debug`
- `/var/log/transithub-rst-debug`

## Notes

- The monitor is generic and is not tied to Docker or TransitHub runtime internals.
- It works best on a host that terminates or forwards public `443/tcp` traffic.
- It is passive by design and does not block anything.
