import re
import logging

_LOGGER = logging.getLogger(__name__)


def tokenize_filter(text: str) -> list:
    """
    Zerlegt Filterstring.
    """

    pattern = r'"([^"]+)"|([^\s&|]+)|([&|])'

    tokens = []

    for quoted, word, operator in re.findall(
        pattern,
        text,
    ):

        if quoted:
            tokens.append(
                ("TERM", quoted.lower())
            )

        elif word:
            tokens.append(
                ("TERM", word.lower())
            )

        elif operator:
            tokens.append(
                (operator, operator)
            )

    return tokens



def parse_filter(text: str) -> list:
    """
    Erstellt OR-Gruppen mit AND-Terms.

    Beispiel:

    alarm & warnung | fehler

    ergibt:

    [
        ["alarm", "warnung"],
        ["fehler"]
    ]
    """

    tokens = tokenize_filter(
        text
    )


    groups = []
    current = []


    for token_type, value in tokens:

        if token_type == "TERM":

            current.append(
                value
            )


        elif token_type == "&":

            continue


        elif token_type == "|":

            if current:
                groups.append(
                    current
                )

            current = []


    if current:
        groups.append(
            current
        )


    return groups



def match_filter(
    record_text: str,
    filter_text: str,
) -> bool:
    """
    Prüft Suchausdruck.
    """

    if not filter_text:
        return True


    groups = parse_filter(
        filter_text
    )


    _LOGGER.debug(
        "Filter groups: %s",
        groups,
    )


    for group in groups:

        # AND innerhalb einer Gruppe

        if all(
            term in record_text
            for term in group
        ):
            return True


    return False
    