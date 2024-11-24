# Hovedfunksjoner som er avhengige av andre moduler:
kartet skal bare vise aktive bestillinger uavhengig av abonnement type. 

## vis_dagens_tunkart():
Bruker customer_utils for å hente koordinater
Bruker config.py for datohåndtering
Bruker Plotly for kartvisning
Bruker Streamlit for UI

## vis_stroingskart_kommende():
Bruker Plotly for kartvisning
Bruker Pandas for databehandling

## create_map():
Bruker customer_utils for koordinater
Bruker util_functions for markør-egenskaper
Bruker Plotly for kartvisning

## display_live_plowmap():
Bruker Streamlit for UI og iframe-visning

## Kritiske avhengigheter:
Mapbox token (for kartvisning)
Tilgang til kundedata med koordinater
Tilgang til bestillingsdata
Streamlit kjøremiljø
