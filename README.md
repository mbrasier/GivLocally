# GivLocally

Local control and monitoring of GivEnergy Gen3 inverters — no cloud, no account, no internet required.

Communicates directly with the inverter over your local network using Modbus TCP.

---

## Requirements

- Python 3.10 or later
- A GivEnergy inverter on your local network with Modbus TCP accessible (port 8899 by default)
- The inverter's local IP address

---

## Installation

```bash
pip install git+https://github.com/mbrasier/GivLocally.git
```

This installs the `givlocally` command.

---

## Quick start

```bash
givlocally read --host 192.168.0.100
```

Connects to the inverter and prints a full status report covering real-time power, battery state, charge schedule, and lifetime energy totals.

---

## Commands

### `read` — display inverter status

```
givlocally read [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--host` | `192.168.0.100` | IP address or hostname of the inverter |
| `--port` | `8899` | Modbus TCP port |
| `--batteries` | `1` | Number of battery packs connected |
| `--output` | `pretty` | Output format: `pretty` or `json` |
| `--retries` | `3` | Connection attempts before giving up |
| `-v, --verbose` | | Enable debug logging |

**Examples**

```bash
# Pretty-printed output
givlocally read --host 192.168.0.100

# JSON output (useful for scripting)
givlocally read --host 192.168.0.100 --output json

# Two battery packs
givlocally read --host 192.168.0.100 --batteries 2
```

---

### `charge-slot` — manage timed charge slots

GivEnergy Gen3 inverters support up to 10 timed charge slots. Each slot defines a window during which the inverter will charge the battery from the grid, up to a target state of charge.

#### `charge-slot set` — configure a slot

```
givlocally charge-slot set SLOT START END SOC [OPTIONS]
```

| Argument | Description |
|---|---|
| `SLOT` | Slot number (1–10) |
| `START` | Start time in `HH:MM` format |
| `END` | End time in `HH:MM` format |
| `SOC` | Target state of charge in percent (4–100) |

| Option | Default | Description |
|---|---|---|
| `--host` | `192.168.0.100` | IP address or hostname of the inverter |
| `--port` | `8899` | Modbus TCP port |
| `--retries` | `3` | Connection attempts before giving up |
| `--inv-type` | _(standard)_ | Inverter variant: blank = standard Gen3, `3ph` = three-phase, `ems` = EMS |
| `-v, --verbose` | | Enable debug logging |

**Examples**

```bash
# Charge slot 1 from 01:00 to 05:00, fill to 100%
givlocally charge-slot set 1 01:00 05:00 100 --host 192.168.0.100

# Charge slot 2 from 23:30 to 06:00, stop at 80%
givlocally charge-slot set 2 23:30 06:00 80 --host 192.168.0.100
```

> **Overnight slots:** A start time later than the end time (e.g. `23:30` to `06:00`) spans midnight — the inverter handles this correctly.

#### `charge-slot clear` — disable a slot

```
givlocally charge-slot clear SLOT [OPTIONS]
```

Resets the slot's start and end times to `00:00`, which disables it.

```bash
givlocally charge-slot clear 1 --host 192.168.0.100
```

---

## Environment variables

All connection options can be set via environment variables so you don't have to repeat them on every command.

| Variable | Option |
|---|---|
| `GIVENERGY_HOST` | `--host` |
| `GIVENERGY_PORT` | `--port` |
| `GIVENERGY_BATTERIES` | `--batteries` |
| `GIVENERGY_INV_TYPE` | `--inv-type` |

**Example**

```bash
export GIVENERGY_HOST=192.168.0.100
givlocally read
givlocally charge-slot set 1 01:00 05:00 100
```

---

## Finding your inverter's IP address

Check your router's DHCP client list for a device named something like `GivEnergy` or `SolarEdge`. Alternatively, the GivEnergy app shows the local IP under **Settings → WiFi**.

It is worth assigning a static (reserved) IP to the inverter so the address does not change.

---

## Supported hardware

Tested against GivEnergy Gen3 inverters (firmware 912 and above). Other generations may work but are not the primary target.

Three-phase and EMS variants are supported via the `--inv-type` option.
