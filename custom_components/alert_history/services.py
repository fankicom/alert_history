import logging

from homeassistant.core import HomeAssistant, ServiceCall

from .const import DOMAIN, SERVICE_RELOAD
from .history import load_history


_LOGGER = logging.getLogger(__name__)


async def async_setup_services(
    hass: HomeAssistant,
):
    """
    Services der Integration registrieren.
    """

    async def reload_service(call: ServiceCall):

        _LOGGER.info(
            "Reload requested"
        )

        await load_history(hass)


    hass.services.async_register(
        DOMAIN,
        SERVICE_RELOAD,
        reload_service,
    )
    