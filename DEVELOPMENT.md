# Brøyteapp Utviklerdokumentasjon

## Formål
Appen håndterer:
- Bestillinger av tunbrøyting
- Strøing
- Tilbakemeldinger fra brukere
- Varsler fra brøytere og drift
- Kartvisning av bestillinger

## Viktige Merknader
- `get_bookings()` skal være standardfunksjon for tunbrøyting
- Unngå æ, ø, å i funksjonsnavn
- Bruker og hytte-ID er samme nummer (f.eks. "142")
Systemet bruker Streamlit for både frontend og backend

## Passordstruktur
i "142" = "passord til hytte 142"  er 142 id for hytte og bruker_id for bruker. Tilsvarende for alle hyttene.

Droppet weather-funksjonalitet, dette er en del av en ny app.

Ved feil - debug og legg til logging

FutureWarning:

Setting an item of incompatible dtype is deprecated and will raise in a future error of pandas. Value '<DatetimeArray>
['NaT', 'NaT', 'NaT']

Ikke implementer mange nye funksjoner, men forbedre eksisterende funksjoner.