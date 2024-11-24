# filter_todays_bookings

Denne funksjonen filtrerer bestillinger for å finne aktive bestillinger for dagens dato.

## Funksjonalitet

Funksjonen tar inn en pandas DataFrame med bestillinger og returnerer en ny DataFrame som kun inneholder:
- Vanlige bestillinger som starter i dag
- Aktive årsabonnementer (der ankomstdato har passert og avreisedato ikke er nådd eller ikke er satt)

## Parameter

- `bookings` (pandas.DataFrame): DataFrame med bestillinger som minimum må inneholde følgende kolonner:
  - `ankomst_dato`: Dato for ankomst
  - `avreise_dato`: Dato for avreise (valgfri for årsabonnementer)
  - `abonnement_type`: Type abonnement ("Årsabonnement" eller andre typer)

## Returverdi

- pandas.DataFrame: Filtrert DataFrame med dagens aktive bestillinger

## Håndtering av datoer

- Alle datoer normaliseres til tidssonen 'Europe/Oslo'
- Datoer uten tidssone får automatisk satt 'Europe/Oslo' som tidssone
- Datoer med annen tidssone konverteres til 'Europe/Oslo'

## Feilhåndtering

- Returnerer en tom DataFrame hvis det oppstår feil
- Logger feilmeldinger via logger.error
- Håndterer tomme DataFrames ved å returnere dem uendret

## Eksempel på bruk
