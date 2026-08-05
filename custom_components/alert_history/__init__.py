"""Alert History integration setup."""

from __future__ import annotations

import asyncio
import logging

from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import (
    Event,
    HomeAssistant,
    ServiceCall,
    callback,
)
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.typing import ConfigType

from .alert2 import load_alert2_views
from .const import (
    CONF_ALERT_DOMAIN,
    CONF_FILTER_HOURS,
    CONF_FILTER_TEXT,
    CONF_HISTORY_FILE,
    CONF_HISTORY_PREFIX,
    CONF_OVERVIEW_PREFIX,
    CONF_PENDING_PREFIX,
    DEFAULT_ALERT_DOMAIN,
    DEFAULT_HISTORY_FILE,
    DEFAULT_HISTORY_PREFIX,
    DEFAULT_OVERVIEW_PREFIX,
    DEFAULT_PENDING_PREFIX,
    DOMAIN,
    SERVICE_RELOAD,
)
from .history import (
    build_view,
    filter_history,
    get_filters,
    load_history,
    sort_history,
)

_LOGGER = logging.getLogger(__name__)

STARTUP_DELAY_SECONDS = 30
ALERT2_REFRESH_DELAY_SECONDS = 0.5
PERIODIC_UPDATE = 60


async def async_update_view(hass: HomeAssistant) -> None:
    """Rebuild only the filtered History view from records held in memory."""

    _LOGGER.debug("Updating Alert History filtered view")

    history = hass.data[DOMAIN].get("history", [])

    if not history:
        _LOGGER.debug("No History records are available in memory")
        return

    filters = get_filters(hass)
    filtered = filter_history(history, filters)
    filtered = sort_history(filtered)

    build_view(hass, filtered)


async def async_reload_all(hass: HomeAssistant) -> None:
    """Immediately reload History, Pending and Overview."""

    _LOGGER.debug("Reloading all Alert History views")

    await load_history(hass)
    await load_alert2_views(hass)


async def async_reload_all_periodic(hass: HomeAssistant) -> None:
    """Periodically reload all Alert History views every minute."""
    await asyncio.sleep(PERIODIC_UPDATE)
    while True:
        try:
            await async_reload_all(hass)
        except Exception as e:
            _LOGGER.error(f"Error during reload: {e}")
        await asyncio.sleep(PERIODIC_UPDATE)


def async_setup_alert2_listener(hass: HomeAssistant) -> None:
    """Listen for state and attribute changes in the Alert2 domain."""

    cfg = hass.data[DOMAIN]

    # Listener nur einmal registrieren.
    if cfg.get("alert2_listener") is not None:
        _LOGGER.debug("Alert2 state listener is already registered")
        return

    async def async_delayed_alert2_refresh() -> None:
        """Combine rapid Alert2 state changes into one refresh."""

        current_task = asyncio.current_task()

        try:
            await asyncio.sleep(ALERT2_REFRESH_DELAY_SECONDS)

            _LOGGER.debug(
                "Refreshing Pending and Overview after Alert2 state change"
            )

            await load_alert2_views(hass)

        except asyncio.CancelledError:
            _LOGGER.debug(
                "Pending Alert2 refresh replaced by a newer state change"
            )
            raise

        except Exception:
            _LOGGER.exception(
                "Unexpected error while refreshing Alert2 views"
            )

        finally:
            # Eine ältere, abgebrochene Task darf die Referenz einer
            # inzwischen neu erstellten Task nicht löschen.
            if cfg.get("alert2_refresh_task") is current_task:
                cfg["alert2_refresh_task"] = None

    @callback
    def alert2_state_changed(event: Event) -> None:
        """Handle state_changed events belonging to the Alert2 domain."""

        entity_id = event.data.get("entity_id")

        if not isinstance(entity_id, str):
            return

        alert_domain = cfg["alert_domain"]

        if not entity_id.startswith(f"{alert_domain}."):
            return

        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")

        _LOGGER.debug(
            "Alert2 entity changed: %s, state %s -> %s",
            entity_id,
            old_state.state if old_state is not None else None,
            new_state.state if new_state is not None else None,
        )

        previous_task = cfg.get("alert2_refresh_task")

        if previous_task is not None and not previous_task.done():
            previous_task.cancel()

        cfg["alert2_refresh_task"] = hass.async_create_task(
            async_delayed_alert2_refresh(),
            "Alert History delayed Alert2 refresh",
        )

    cfg["alert2_listener"] = hass.bus.async_listen(
        EVENT_STATE_CHANGED,
        alert2_state_changed,
    )

    _LOGGER.info(
        "Alert2 state listener registered for domain: %s",
        cfg["alert_domain"],
    )


async def async_startup_alert2_refresh(
    hass: HomeAssistant,
) -> None:
    """Load Pending and Overview after Alert2 has initialized."""

    _LOGGER.info(
        "Waiting %d seconds before initial Alert2 refresh",
        STARTUP_DELAY_SECONDS,
    )

    try:
        await asyncio.sleep(STARTUP_DELAY_SECONDS)

        _LOGGER.info(
            "Loading Pending and Overview after startup delay"
        )

        await load_alert2_views(hass)

        # Erst nach dem initialen, verzögerten Aufbau auf Alert2-Änderungen
        # reagieren. Änderungen während der Startphase sind im abschließenden
        # load_alert2_views() bereits enthalten.
        async_setup_alert2_listener(hass)

        _LOGGER.info(
            "Initial Alert2 refresh finished"
        )

    except asyncio.CancelledError:
        _LOGGER.debug("Initial Alert2 startup refresh was cancelled")
        raise

    except Exception:
        _LOGGER.exception(
            "Initial Alert2 startup refresh failed"
        )


async def async_setup(
    hass: HomeAssistant,
    config: ConfigType,
) -> bool:
    """Set up the YAML-configured Alert History integration."""

    _LOGGER.info("Starting Alert History")

    cfg = config.get(DOMAIN, {})

    hass.data[DOMAIN] = {
        "history_file": cfg.get(
            CONF_HISTORY_FILE,
            DEFAULT_HISTORY_FILE,
        ),
        "filter_hours": cfg.get(CONF_FILTER_HOURS),
        "filter_text": cfg.get(CONF_FILTER_TEXT),
        "alert_domain": cfg.get(
            CONF_ALERT_DOMAIN,
            DEFAULT_ALERT_DOMAIN,
        ),
        "history_prefix": cfg.get(
            CONF_HISTORY_PREFIX,
            DEFAULT_HISTORY_PREFIX,
        ),
        "pending_prefix": cfg.get(
            CONF_PENDING_PREFIX,
            DEFAULT_PENDING_PREFIX,
        ),
        "overview_prefix": cfg.get(
            CONF_OVERVIEW_PREFIX,
            DEFAULT_OVERVIEW_PREFIX,
        ),
        "history": [],
        "entities": [],
        "pending_entities": [],
        "overview_entities": [],
        "alert2_listener": None,
        "alert2_refresh_task": None,
        "startup_task": None,
    }

    domain_data = hass.data[DOMAIN]

    _LOGGER.debug(
        "Configuration: history_file=%s, filter_hours=%s, filter_text=%s, "
        "alert_domain=%s, prefixes=(%s, %s, %s)",
        domain_data["history_file"],
        domain_data["filter_hours"],
        domain_data["filter_text"],
        domain_data["alert_domain"],
        domain_data["history_prefix"],
        domain_data["pending_prefix"],
        domain_data["overview_prefix"],
    )

    #
    # History ist dateibasiert und kann sofort geladen werden.
    #
    await load_history(hass)

    #
    # History-Filter überwachen.
    #
    filter_entities = [
        entity_id
        for entity_id in (
            domain_data["filter_hours"],
            domain_data["filter_text"],
        )
        if entity_id
    ]

    if filter_entities:

        async def filter_changed(event: Event) -> None:
            """Rebuild History when a configured filter changes."""

            _LOGGER.debug(
                "History filter changed: %s",
                event.data,
            )

            await async_update_view(hass)

        domain_data["filter_listener"] = (
            async_track_state_change_event(
                hass,
                filter_entities,
                filter_changed,
            )
        )

        _LOGGER.info(
            "History filter listener registered: %s",
            filter_entities,
        )

    #
    # Manueller Reload-Service.
    #
    async def reload_service(call: ServiceCall) -> None:
        """Handle alert_history.reload."""

        _LOGGER.debug(
            "Reload service requested: %s",
            call.data,
        )

        await async_reload_all(hass)

    hass.services.async_register(
        DOMAIN,
        SERVICE_RELOAD,
        reload_service,
    )

    #
    # Pending und Overview nicht während des frühen HA-Starts aufbauen.
    # Der Task läuft unabhängig weiter; async_setup wird nicht 30 Sekunden
    # blockiert.
    #
    domain_data["startup_task"] = hass.async_create_task(
        async_startup_alert2_refresh(hass),
        "Alert History initial Alert2 refresh",
    )


    # Starte den periodischen Reload NACH dem Startup
    @callback
    def schedule_periodic_reload(_):
        """Schedule periodic reload after startup."""
        async def periodic_reload_task():
            # Warte, bis HA wirklich läuft
            while not hass.is_running:
                await asyncio.sleep(1)
            
            _LOGGER.info("HA is running, starting periodic reload in 30 seconds")
            await asyncio.sleep(30)
            
            # Jetzt erst den periodischen Task starten
            _LOGGER.info("Starting periodic reload every %d seconds", PERIODIC_UPDATE)
            hass.data[DOMAIN]["periodic_reload_task"] = hass.async_create_task(
                async_reload_all_periodic(hass),
                "Alert History periodic reload",
            )
        
        hass.async_create_task(periodic_reload_task())
    
    # Registriere den Callback für den Startup
    hass.bus.async_listen_once("homeassistant_started", schedule_periodic_reload)
    
    _LOGGER.info("Alert History setup finished")
    return True
    