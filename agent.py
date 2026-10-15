"""Asystent z narzędziami w Pydantic AI.

Uruchomienie:  python agent.py
Czat otworzy się pod adresem http://127.0.0.1:7932
"""

import json
import re
from datetime import date, datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import uvicorn
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry

load_dotenv()

# ---------------------------------------------------------------------------
# 1. INSTRUKCJA: to jest miejsce, które zmieniasz w pierwszej kolejności.
# ---------------------------------------------------------------------------

INSTRUKCJA = """
Jesteś pomocnym asystentem. Odpowiadaj po polsku.
"""

# Model, z którego korzysta asystent. Listę modeli znajdziesz na openrouter.ai/models.
MODEL = "openrouter:openai/gpt-5"

agent = Agent(MODEL, instructions=INSTRUKCJA)


# ---------------------------------------------------------------------------
# 2. NARZĘDZIA: zwykłe funkcje Pythona z dekoratorem @agent.tool_plain.
#    Asystent widzi nazwę funkcji, jej opis (docstring) i typy argumentów.
#    Na tej podstawie decyduje, kiedy i jak jej użyć.
# ---------------------------------------------------------------------------


def pobierz(adres: str, parametry: dict | None = None) -> str:
    """Pobiera zawartość spod podanego adresu jako tekst."""
    if parametry:
        adres = f"{adres}?{urlencode(parametry)}"
    try:
        zapytanie = Request(adres, headers={"User-Agent": "Mozilla/5.0 (warsztat-pydantic)"})
        with urlopen(zapytanie, timeout=20) as odpowiedz:
            kodowanie = odpowiedz.headers.get_content_charset() or "utf-8"
            return odpowiedz.read().decode(kodowanie, errors="replace")
    except (OSError, ValueError) as blad:
        # ModelRetry oddaje komunikat asystentowi, zamiast przerywać rozmowę.
        raise ModelRetry(f"Nie udało się pobrać {adres}: {blad}")


@agent.tool_plain
def kalendarz(data: date | None = None) -> str:
    """Podaje dzisiejszą datę, dzień tygodnia i godzinę w Polsce.

    Jeśli podasz datę, policzy też, ile dni zostało do tej daty.
    Użyj zawsze, gdy odpowiedź zależy od dzisiejszej daty lub od liczby dni.
    """
    dni_tygodnia = ["poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela"]
    try:
        teraz = datetime.now(ZoneInfo("Europe/Warsaw"))
    except ZoneInfoNotFoundError:
        # Bez pakietu tzdata Windows nie zna stref czasowych. Wtedy bierzemy zegar komputera.
        teraz = datetime.now()
    wynik = f"Dzisiaj jest {dni_tygodnia[teraz.weekday()]}, {teraz:%Y-%m-%d}, godzina {teraz:%H:%M}."
    if data:
        dni = (data - teraz.date()).days
        wynik += f" Data {data} to {dni_tygodnia[data.weekday()]}, za {dni} dni."
    return wynik


class DzienPrognozy(BaseModel):
    data: date
    temperatura_min: float
    temperatura_max: float
    szansa_opadow_procent: int


class Pogoda(BaseModel):
    miejsce: str
    temperatura_teraz: float
    wiatr_km_h: float
    prognoza: list[DzienPrognozy]


@agent.tool_plain
def pogoda(miasto: str, dni: int = Field(default=3, ge=1, le=7)) -> Pogoda:
    """Sprawdza aktualną pogodę i prognozę dla podanego miasta.

    Args:
        miasto: Nazwa miasta, np. "Gdańsk".
        dni: Na ile dni ma być prognoza (od 1 do 7).
    """
    miejsca = json.loads(
        pobierz(
            "https://geocoding-api.open-meteo.com/v1/search",
            {"name": miasto, "count": 1, "language": "pl"},
        )
    ).get("results")
    if not miejsca:
        raise ModelRetry(f"Nie znam miejsca o nazwie {miasto}.")
    miejsce = miejsca[0]

    dane = json.loads(
        pobierz(
            "https://api.open-meteo.com/v1/forecast",
            {
                "latitude": miejsce["latitude"],
                "longitude": miejsce["longitude"],
                "current": "temperature_2m,wind_speed_10m",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "forecast_days": dni,
                "timezone": "Europe/Warsaw",
            },
        )
    )
    dzienne = dane["daily"]
    return Pogoda(
        miejsce=f"{miejsce['name']}, {miejsce.get('country', '')}",
        temperatura_teraz=dane["current"]["temperature_2m"],
        wiatr_km_h=dane["current"]["wind_speed_10m"],
        prognoza=[
            DzienPrognozy(
                data=dzienne["time"][i],
                temperatura_min=dzienne["temperature_2m_min"][i],
                temperatura_max=dzienne["temperature_2m_max"][i],
                szansa_opadow_procent=dzienne["precipitation_probability_max"][i],
            )
            for i in range(len(dzienne["time"]))
        ],
    )


@agent.tool_plain
def czytaj_strone(adres: str) -> str:
    """Pobiera tekst strony internetowej spod podanego adresu.

    Użyj, gdy użytkownik poda link i poprosi o streszczenie albo o informację z tej strony.

    Args:
        adres: Pełny adres strony zaczynający się od https://
    """
    html = pobierz(adres)
    html = re.sub(r"(?is)<(script|style|nav|footer|header)\b.*?</\1>", " ", html)
    tekst = re.sub(r"(?s)<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", tekst).strip()[:8000]


# ---------------------------------------------------------------------------
# 3. URUCHOMIENIE: wbudowany w Pydantic AI czat w przeglądarce.
# ---------------------------------------------------------------------------

app = agent.to_web()

if __name__ == "__main__":
    # reload=True: po zapisaniu zmian w pliku asystent uruchamia się ponownie sam.
    uvicorn.run("agent:app", host="127.0.0.1", port=7932, reload=True)
