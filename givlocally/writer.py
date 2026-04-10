"""Write charge-slot settings to a GivEnergy inverter over local Modbus TCP."""

from __future__ import annotations

import asyncio
import logging
from datetime import time

from givenergy_modbus_async.client.client import Client
from givenergy_modbus_async.client.commands import _set_charge_slot, set_soc_target, set_system_date_time
from givenergy_modbus_async.model import TimeSlot

from .config import InverterConfig

log = logging.getLogger(__name__)

MAX_SLOTS = 10


def _parse_hhmm(value: str) -> time:
    """Parse a time string in HH:MM format into a :class:`datetime.time`."""
    try:
        h, m = value.split(":")
        return time(int(h), int(m))
    except (ValueError, AttributeError):
        raise ValueError(f"Invalid time '{value}' — expected HH:MM (e.g. 01:30)")


async def _write_async(
    config: InverterConfig,
    requests: list,
) -> None:
    client = Client(host=config.host, port=config.port, connect_timeout=config.timeout)
    for attempt in range(1, config.retries + 1):
        try:
            log.debug("Connection attempt %d/%d to %s:%d", attempt, config.retries, config.host, config.port)
            await client.one_shot_command(requests)
            return
        except Exception as exc:
            log.warning("Attempt %d failed: %s", attempt, exc)
            if attempt == config.retries:
                raise
            await asyncio.sleep(1)
        finally:
            try:
                await client.close()
            except BaseException:
                pass


class InverterWriter:
    """Send write commands to a GivEnergy inverter."""

    def __init__(self, config: InverterConfig, inv_type: str = "") -> None:
        self._config = config
        # inv_type: "" = standard Gen3, "3ph" = three-phase, "ems" = EMS
        self._inv_type = inv_type

    def set_charge_slot(self, slot: int, start: str, end: str, target_soc: int = 100) -> None:
        """
        Set a charge slot's start/end times and target SOC.

        Args:
            slot:       Slot index, 1–10.
            start:      Start time as "HH:MM".
            end:        End time as "HH:MM".
            target_soc: Stop charging when battery reaches this SOC (4–100).
        """
        if not (1 <= slot <= MAX_SLOTS):
            raise ValueError(f"Slot must be 1–{MAX_SLOTS}, got {slot}")
        if not (4 <= target_soc <= 100):
            raise ValueError(f"Target SOC must be 4–100, got {target_soc}")
        t_start = _parse_hhmm(start)
        t_end = _parse_hhmm(end)
        timeslot = TimeSlot(start=t_start, end=t_end)
        requests = _set_charge_slot(discharge=False, idx=slot, slot=timeslot, inv_type=self._inv_type)
        requests += set_soc_target(discharge=False, idx=slot, target_soc=target_soc, inv_type=self._inv_type)
        log.info("Setting charge slot %d: %s → %s @ %d%%", slot, start, end, target_soc)
        asyncio.run(_write_async(self._config, requests))

    def clear_charge_slot(self, slot: int) -> None:
        """
        Disable a charge slot by resetting its times to 00:00.

        Args:
            slot: Slot index, 1–10.
        """
        if not (1 <= slot <= MAX_SLOTS):
            raise ValueError(f"Slot must be 1–{MAX_SLOTS}, got {slot}")
        requests = _set_charge_slot(discharge=False, idx=slot, slot=None, inv_type=self._inv_type)
        log.info("Clearing charge slot %d", slot)
        asyncio.run(_write_async(self._config, requests))

    def set_discharge_slot(self, slot: int, start: str, end: str, floor_soc: int = 4) -> None:
        """
        Set a discharge slot's start/end times and floor SOC.

        Args:
            slot:      Slot index, 1–10.
            start:     Start time as "HH:MM".
            end:       End time as "HH:MM".
            floor_soc: Stop discharging when battery reaches this SOC (4–100).
        """
        if not (1 <= slot <= MAX_SLOTS):
            raise ValueError(f"Slot must be 1–{MAX_SLOTS}, got {slot}")
        if not (4 <= floor_soc <= 100):
            raise ValueError(f"Floor SOC must be 4–100, got {floor_soc}")
        t_start = _parse_hhmm(start)
        t_end = _parse_hhmm(end)
        timeslot = TimeSlot(start=t_start, end=t_end)
        requests = _set_charge_slot(discharge=True, idx=slot, slot=timeslot, inv_type=self._inv_type)
        requests += set_soc_target(discharge=True, idx=slot, target_soc=floor_soc, inv_type=self._inv_type)
        log.info("Setting discharge slot %d: %s → %s, floor %d%%", slot, start, end, floor_soc)
        asyncio.run(_write_async(self._config, requests))

    def sync_time(self, dt: datetime) -> None:
        """
        Set the inverter's clock to the given datetime.

        Args:
            dt: The datetime to set (typically datetime.now()).
        """
        requests = set_system_date_time(dt)
        log.info("Syncing inverter time to %s", dt.strftime("%Y-%m-%d %H:%M:%S"))
        asyncio.run(_write_async(self._config, requests))

    def clear_discharge_slot(self, slot: int) -> None:
        """
        Disable a discharge slot by resetting its times to 00:00.

        Args:
            slot: Slot index, 1–10.
        """
        if not (1 <= slot <= MAX_SLOTS):
            raise ValueError(f"Slot must be 1–{MAX_SLOTS}, got {slot}")
        requests = _set_charge_slot(discharge=True, idx=slot, slot=None, inv_type=self._inv_type)
        log.info("Clearing discharge slot %d", slot)
        asyncio.run(_write_async(self._config, requests))
