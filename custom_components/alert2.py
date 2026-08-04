"""Build Pending and Overview views from Alert2 states."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant, State

from .const import DOMAIN
from .parser import (
    format_alert_timestamp,
    parse_alert2_message,
    priority_to_typ,
)

_LOGGER = logging.getLogger(__name__)


def _alert2_states(hass: HomeAssistant, alert_domain: str) -> list[State]:
    """Return all current states belonging to the configured Alert2 domain."""

    prefix = f"{alert_domain}."
    states = [
        state
        for state in hass.states.async_all()
        if state.entity_id.startswith(prefix)
    ]

    _LOGGER.debug(
        "Found %d states in Alert2 domain %s",
        len(states),
        alert_domain,
    )

    return states


def _record_name(state: State) -> str:
    """Return the stable Alert2 name attribute with a safe fallback."""

    return str(
        state.attributes.get("name")
        or state.attributes.get("friendly_name")
        or state.entity_id.split(".", 1)[-1]
    )


def build_pending_records(
    hass: HomeAssistant,
    alert_domain: str,
) -> list[dict[str, Any]]:
    """Build records for all currently active Alert2 alarms."""

    records: list[dict[str, Any]] = []

    for state in _alert2_states(hass, alert_domain):
        if state.state.lower() != "on":
            continue

        parsed = parse_alert2_message(
            state.attributes.get("last_fired_message")
        )

        if parsed is None:
            _LOGGER.warning(
                "Active Alert2 entity %s has no parseable last_fired_message",
                state.entity_id,
            )
            continue

        timestamp, timestamp_utc = format_alert_timestamp(
            state.attributes.get("last_fired_time")
        )

        records.append(
            {
                "timestamp": timestamp,
                "timestamp_utc": timestamp_utc,
                "name": _record_name(state),
                "typ": parsed["typ"],
                "text": parsed["text"],
                "link": parsed["link"],
                "source_entity": state.entity_id,
            }
        )

    records.sort(
        key=lambda row: int(row.get("timestamp_utc") or 0),
        reverse=True,
    )

    _LOGGER.info("Pending view prepared: %d records", len(records))
    return records


def build_overview_records(
    hass: HomeAssistant,
    alert_domain: str,
) -> list[dict[str, Any]]:
    """Build records for every defined Alert2 entity."""

    records: list[dict[str, Any]] = []

    for state in _alert2_states(hass, alert_domain):
        timestamp, timestamp_utc = format_alert_timestamp(
            state.attributes.get("last_fired_time")
        )

        friendly_name = str(
            state.attributes.get("friendly_name")
            or state.attributes.get("name")
            or state.entity_id
        )

        parsed = parse_alert2_message(
            state.attributes.get("last_fired_message")
        )

        if parsed:
            fired_message = parsed["text"] or None
            notify = parsed["notify"] or None
            pushover = parsed["pushover"] or None
            link = parsed["link"] or None
        else:
            fired_message = None
            notify = None
            pushover = None
            link = None
           

        records.append(
            {
                "timestamp": timestamp,
                "timestamp_utc": timestamp_utc,
                "name": _record_name(state),
                "typ": priority_to_typ(state.attributes.get("priority")),
                "text": friendly_name,
                "source_entity": state.entity_id,
                "alert_state": state.state,
                "fired_message": fired_message,
                "notify": notify,
                "pushover": pushover,
                "link": link,
            }
        )

    records.sort(key=lambda row: str(row.get("text", "")).casefold())

    _LOGGER.info("Overview view prepared: %d records", len(records))
    return records


# def _remove_states(
    # hass: HomeAssistant,
    # entity_ids: list[str],
# ) -> None:
    # """Remove states created by one generated view."""

    # for entity_id in entity_ids:
        # hass.states.async_remove(entity_id)


def _sync_records(
    hass: HomeAssistant,
    prefix: str,
    records: list[dict[str, Any]],
    old_entity_ids: list[str],
) -> list[str]:
    """Synchronize generated states without deleting and recreating all IDs."""

    old_entities = set(old_entity_ids)
    new_entities = []

    for index, row in enumerate(records, start=1):

        entity_id = f"{prefix}.log_{index:06d}"

        hass.states.async_set(
            entity_id,
            str(row.get("text", "")),
            {
                "timestamp": row.get("timestamp", "N/A"),
                "timestamp_utc": int(row.get("timestamp_utc") or 0),
                "name": row.get("name"),
                "typ": str(row.get("typ", "5")),
                "link": row.get("link"),
                "source_entity": row.get("source_entity"),
                **(
                    {"alert_state": row.get("alert_state")}
                    if "alert_state" in row
                    else {}
                ),
                **(
                    {"fired_message": row.get("fired_message")}
                    if "fired_message" in row
                    else {}
                ),
                **(
                    {"notify": row.get("notify")}
                    if "notify" in row
                    else {}
                ),
                **(
                    {"pushover": row.get("pushover")}
                    if "pushover" in row
                    else {}
                ),
            },
        )

        new_entities.append(entity_id)

    new_entity_set = set(new_entities)

    for entity_id in old_entities - new_entity_set:
        hass.states.async_remove(entity_id)

    _LOGGER.debug(
        "Synchronized prefix %s: %d states, %d removed",
        prefix,
        len(new_entities),
        len(old_entities - new_entity_set),
    )

    return new_entities
    
    

async def load_alert2_views(hass: HomeAssistant) -> None:
    """Rebuild Pending and Overview states from the current Alert2 states."""

    cfg = hass.data[DOMAIN]
    alert_domain = cfg["alert_domain"]

    pending_records = build_pending_records(hass, alert_domain)
    overview_records = build_overview_records(hass, alert_domain)

    # _remove_states(hass, cfg["pending_entities"])
    # _remove_states(hass, cfg["overview_entities"])

    cfg["pending_entities"] = _sync_records(
        hass,
        cfg["pending_prefix"],
        pending_records,
        cfg["pending_entities"],
    )

    cfg["overview_entities"] = _sync_records(
        hass,
        cfg["overview_prefix"],
        overview_records,
        cfg["overview_entities"],
    )

#
# Anzahl erst nach vollständig abgeschlossener Synchronisation setzen
#
    hass.states.async_set(
        "sensor.alert_pending_count",
        len(pending_records),
        {
            "friendly_name": "Alert Pending Count",
            # "unit_of_measurement": "Alarme",
        },
    )

    hass.states.async_set(
        "sensor.alert_overview_count",
        len(overview_records),
        {
            "friendly_name": "Alert Overview Count",
            # "unit_of_measurement": "Alarme",
        },
    )

    # _LOGGER.info(
        # "Alert2 views synchronized: %d pending, %d overview",
        # len(cfg["pending_entities"]),
        # len(cfg["overview_entities"]),
    # )
    
    _LOGGER.info(
        "Alert2 views synchronized: %d pending, %d overview",
        len(pending_records),
        len(overview_records),
    )   