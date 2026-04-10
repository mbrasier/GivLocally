# GivLocally

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

Local control and monitoring of GivEnergy Gen3 inverters — no cloud, no account, no internet required.

Communicates directly with the inverter over your local network using Modbus TCP.

---

## Requirements

- Python 3.10 or later
- A GivEnergy inverter on your local network with Modbus TCP accessible (port 8899 by default)
- The inverter's local IP address

---

## Installing Python

Skip this section if you already have Python 3.10 or later installed. You can check by running:

```
python --version
```

### Windows

1. Go to [python.org/downloads](https://www.python.org/downloads/) and download the latest Python 3 installer.
2. Run the installer. **Make sure to tick "Add python.exe to PATH"** on the first screen before clicking Install.
3. Open a new Command Prompt and confirm it works:

```
python --version
```

### macOS

The recommended way is via [Homebrew](https://brew.sh). If you don't have Homebrew, install it first by pasting this into Terminal:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Then install Python:

```bash
brew install python
```

Confirm it works:

```bash
python3 --version
```

> On macOS, use `python3` and `pip3` instead of `python` and `pip` in all commands below.

---

## Installation

```bash
pip install git+https://github.com/mbrasier/GivLocally.git
```

This installs the `givlocally` command.

---

## Quick start

Run the setup wizard to configure your inverter connection and solar panel details:

```bash
givlocally setup
```

Then read the current inverter status:

```bash
givlocally read
```

Once setup has been run, the `--host` and other connection options default to your saved settings so you don't need to type them on every command.

---

## Commands

### `setup` — configure GivLocally

```
givlocally setup
```

Runs an interactive wizard that saves your settings to a config file. Run this once after installing. The wizard asks for:

**Connection settings**
- Inverter IP address and Modbus port
- Number of battery packs
- Inverter type (standard Gen3, three-phase, or EMS)

**Solar panel details** _(used for future solar forecast features)_
- Total panel capacity in kWp
- Panel tilt (0° = flat, 90° = vertical)
- Panel azimuth (0°/360° = North, 90° = East, 180° = South, 270° = West)
- Latitude and longitude
- System efficiency factor (0.0–1.0, accounting for inverter losses, temperature, and soiling)

**Household usage** _(used to calculate required overnight charge level)_
- Expected daily household consumption in kWh

**Battery**
- Usable battery capacity in kWh
- Minimum SOC to keep in reserve (%)

**Auto charge** _(used by `givlocally auto`)_
- Charge slot number (1–10)
- Charge slot start and end time

Settings are saved to:

| Platform | Path |
|---|---|
| Windows | `%APPDATA%\givlocally\config.toml` |
| macOS | `~/Library/Application Support/givlocally/config.toml` |
| Linux | `~/.config/givlocally/config.toml` |

Re-running `givlocally setup` will show existing values as defaults, so you can update individual settings without re-entering everything.

---

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

### `time-sync` — synchronise the inverter clock

```
givlocally time-sync
```

Sets the inverter's internal clock to the current date and time of the computer running the command. Useful if the inverter clock has drifted or reset after a power cut.

The `read` command shows the inverter's current date and time in the Device Identity section so you can check whether a sync is needed.

| Option | Default | Description |
|---|---|---|
| `--host` | _(from setup)_ | IP address or hostname of the inverter |
| `--port` | `8899` | Modbus TCP port |
| `--retries` | `3` | Connection attempts before giving up |
| `--inv-type` | _(standard)_ | Inverter variant |
| `-v, --verbose` | | Enable debug logging |

---

### `auto` — set overnight charge automatically

```
givlocally auto [--dry-run]
```

Combines the solar forecast with your settings and writes the result directly to the inverter in one step:

1. Fetches tomorrow's solar generation forecast
2. Calculates the required overnight charge target
3. Programs the configured charge slot on the inverter to that SOC

```
Fetching solar forecast …
  Tomorrow's forecast: 1.8 kWh  Daily usage: 8.0 kWh  Shortfall: 6.2 kWh
  Charge slot 1 (01:00 → 05:00)  →  target 75%

Charge slot 1 set to 01:00 → 05:00 @ 75%
```

Use `--dry-run` to see what would be set without touching the inverter. This is useful for testing or scheduling via cron before going live.

The charge slot number and window are configured in `givlocally setup` under **Auto Charge**.

| Option | Description |
|---|---|
| `--dry-run` | Show what would be set without writing to the inverter |
| `-v, --verbose` | Enable debug logging |

---

### `predict` — overnight charge recommendation

```
givlocally predict
```

Fetches tomorrow's solar generation forecast from [forecast.solar](https://forecast.solar) (free, no account needed) and calculates what SOC the battery should be charged to overnight so that solar + battery together cover your expected daily household consumption.

```
Fetching solar forecast from forecast.solar …

  Today's predicted generation      3.2 kWh  (raw 4.0 kWh × 80% efficiency)
  Tomorrow's predicted generation   1.8 kWh  (raw 2.2 kWh × 80% efficiency)
  Expected daily consumption        8.0 kWh
  Shortfall solar cannot cover      6.2 kWh
  Battery capacity                  9.5 kWh
  Minimum SOC reserve               10%

  Recommended overnight charge target: 75%
```

Requires `givlocally setup` to have been completed with solar panel, household usage, and battery capacity values.

| Option | Description |
|---|---|
| `-v, --verbose` | Enable debug logging |

---

### `summary` — one-line status

```
givlocally summary [OPTIONS]
```

Prints a single line showing the most important inverter state at a glance:

```
Solar 2.41 kW  Load 0.87 kW  Grid exporting 1.20 kW  Battery charging 1.54 kW @ 62%
```

| Option | Default | Description |
|---|---|---|
| `--host` | `192.168.0.100` | IP address or hostname of the inverter |
| `--port` | `8899` | Modbus TCP port |
| `--retries` | `3` | Connection attempts before giving up |
| `-v, --verbose` | | Enable debug logging |

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

### `discharge-slot` — manage timed discharge slots

GivEnergy Gen3 inverters support up to 10 timed discharge slots. Each slot defines a window during which the inverter will discharge the battery (e.g. to avoid grid import during peak tariff periods), down to a floor state of charge.

#### `discharge-slot set` — configure a slot

```
givlocally discharge-slot set SLOT START END SOC [OPTIONS]
```

| Argument | Description |
|---|---|
| `SLOT` | Slot number (1–10) |
| `START` | Start time in `HH:MM` format |
| `END` | End time in `HH:MM` format |
| `SOC` | Floor state of charge in percent (4–100). The inverter stops discharging early if the battery reaches this level before END. |

| Option | Default | Description |
|---|---|---|
| `--host` | `192.168.0.100` | IP address or hostname of the inverter |
| `--port` | `8899` | Modbus TCP port |
| `--retries` | `3` | Connection attempts before giving up |
| `--inv-type` | _(standard)_ | Inverter variant: blank = standard Gen3, `3ph` = three-phase, `ems` = EMS |
| `-v, --verbose` | | Enable debug logging |

**Examples**

```bash
# Discharge slot 1 during evening peak, don't go below 10%
givlocally discharge-slot set 1 16:00 20:00 10 --host 192.168.0.100

# Discharge slot 2 during morning peak, don't go below 20%
givlocally discharge-slot set 2 07:00 09:00 20 --host 192.168.0.100
```

#### `discharge-slot clear` — disable a slot

```
givlocally discharge-slot clear SLOT [OPTIONS]
```

Resets the slot's start and end times to `00:00`, which disables it.

```bash
givlocally discharge-slot clear 1 --host 192.168.0.100
```

---

## Environment variables

All connection options can be set via environment variables. These take precedence over values saved by `givlocally setup`.

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
