import json
import logging

from time import time
##
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant

from .const import DOMAIN

from .filter import match_filter


_LOGGER = logging.getLogger(__name__)


def read_history_file(filename: str) -> list:
    """
    Liest die JSON History-Datei.
    """

    _LOGGER.debug(
        "Reading history file: %s",
        filename,
    )

    with open(filename, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError(
            "History file is not a JSON array"
        )

    return data


def prepare_history(history: list) -> list:
    """
    Bereitet die Datensätze für interne Verarbeitung vor.
    Die JSON-Datei bleibt unverändert.
    """

    prepared = []

    for row in history:

        item = row.copy()

        try:

            if item.get("timestamp_utc") is not None:

                item["_timestamp"] = int(item["timestamp_utc"])

            else:

                dt = datetime.strptime(
                    item["timestamp"],
                    "%a %d.%m.%Y %H:%M:%S %z"
                )

                item["_timestamp"] = dt.timestamp()
                
                # Rückwärtskompatibilität:
                # alten Records ebenfalls einen timestamp_utc geben
                item["timestamp_utc"] = item["_timestamp"]

        except Exception:

            _LOGGER.warning(
                "Invalid timestamp in record: %s",
                item
            )

            item["_timestamp"] = 0

        item["_text"] = (
            item.get("text", "")
            .lower()
        )

        item["_name"] = (
            item.get("name", "")
            .lower()
        )


        prepared.append(item)


    _LOGGER.debug(
        "Prepared %d history records",
        len(prepared),
    )

    return prepared


def get_filters(hass: HomeAssistant) -> dict:
    """
    Liest die Filterwerte aus HA.
    """

    cfg = hass.data[DOMAIN]

    result = {
        "hours": 0,
        "text": "",
    }


    entity = cfg.get("filter_hours")

    if entity:

        state = hass.states.get(entity)

        if state:

            try:
                result["hours"] = float(state.state)

            except Exception:
                pass


    entity = cfg.get("filter_text")

    if entity:

        state = hass.states.get(entity)

        if state:

            result["text"] = (
                state.state
                .strip()
                .lower()
            )


    _LOGGER.debug(
        "Current filters: %s",
        result,
    )

    return result


def match_hours(
    row: dict,
    hours: float,
) -> bool:

    if hours <= 0:
        return True

    ts = row.get("_timestamp")

    if not ts:
        return False

    limit = time() - hours * 3600

    return ts >= limit


def match_text(
    row: dict,
    text: str,
) -> bool:

    search_text = (
        row.get("_text", "")
        + " "
        + row.get("_name", "")
    )
    _LOGGER.debug(
        "Filter input received: %s",
        search_text
    )


    return match_filter(
        search_text.lower(),
        text,
    )
    

def match_record(
    row: dict,
    filters: dict,
) -> bool:

    return (
        match_hours(
            row,
            filters["hours"],
        )
        and
        match_text(
            row,
            filters["text"],
        )
    )



def filter_history(
    history: list,
    filters: dict,
) -> list:
    """
    Wendet alle Filter an.
    """

    result = [
        row
        for row in history
        if match_record(
            row,
            filters,
        )
    ]


    _LOGGER.debug(
        "Filtered history: %d of %d records",
        len(result),
        len(history),
    )


    return result



def sort_history(history: list) -> list:

    return sorted(
        history,
        key=lambda x: x.get("_timestamp", 0),
        reverse=True,
    )



def build_view(
    hass: HomeAssistant,
    rows: list,
):
    """Synchronisiert die History-Ansicht mit den vorhandenen States."""

    cfg = hass.data[DOMAIN]
    prefix = cfg.get("history_prefix", DOMAIN)

    old_entities = set(cfg["entities"])
    new_entities = []

    #
    # Vorhandene States aktualisieren bzw. neue anlegen
    #
    for idx, row in enumerate(rows, start=1):

        entity_id = f"{prefix}.log_{idx:06d}"

        hass.states.async_set(
            entity_id,
            row.get("text", ""),
            {
                "timestamp": row.get("timestamp"),
                "timestamp_utc": row.get("timestamp_utc"),
                "name": row.get("name"),
                "typ": row.get("typ"),
                "link": row.get("link"),
            },
        )

        new_entities.append(entity_id)

    #
    # Nur nicht mehr benötigte States entfernen
    #
    new_entity_set = set(new_entities)

    for entity_id in old_entities - new_entity_set:
        hass.states.async_remove(entity_id)

    cfg["entities"] = new_entities

    _LOGGER.info(
        "History view synchronized: %d entities, %d removed",
        len(new_entities),
        len(old_entities - new_entity_set),
    )
    


async def load_history(
    hass: HomeAssistant,
):
    """
    Kompletter Reload der History.
    """

    cfg = hass.data[DOMAIN]

    filename = cfg["history_file"]


    try:

        raw = await hass.async_add_executor_job(
            read_history_file,
            filename,
        )


    except Exception as err:

        _LOGGER.error(
            "Cannot read history: %s",
            err,
        )

        return


    history = prepare_history(
        raw
    )


    cfg["history"] = history


    filters = get_filters(
        hass
    )


    filtered = filter_history(
        history,
        filters,
    )


    filtered = sort_history(
        filtered
    )


    build_view(
        hass,
        filtered,
    )


    _LOGGER.info(
        "History reload finished",
    )
