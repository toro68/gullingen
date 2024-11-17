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
- innlogging er hyttenummer og passord som ligger i .secrets lokalt og online i settings > secrets

## Passordstruktur
i "142" = "passord til hytte 142"  er 142 id for hytte og bruker_id for bruker. Tilsvarende for alle hyttene.

Droppet weather-funksjonalitet, dette er en del av en ny app.

Ved feil - debug og legg til logging

FutureWarning:

Setting an item of incompatible dtype is deprecated and will raise in a future error of pandas. Value '<DatetimeArray>
['NaT', 'NaT', 'NaT']

Ikke implementer mange nye funksjoner, men forbedre eksisterende funksjoner.

NB: Alltid oppgi hvilken fil funksjonen ligger i.

# config.py:
DATABASE_PATH = os.path.dirname(os.path.abspath(__file__))



Streamlit is an open-source Python framework

Mappestruktur
.
├── DEVELOPMENT.md
├── README.md
├── __pycache__
│   ├── admin_utils.cpython-311.pyc
│   ├── alert_utils.cpython-311.pyc
│   ├── api.cpython-311.pyc
│   ├── app.cpython-311.pyc
│   ├── auth_utils.cpython-311.pyc
│   ├── config.cpython-311.pyc
│   ├── constants.cpython-311.pyc
│   ├── customer_utils.cpython-311.pyc
│   ├── db_utils.cpython-311.pyc
│   ├── feedback_utils.cpython-311.pyc
│   ├── gps_utils.cpython-311.pyc
│   ├── logging_config.cpython-311.pyc
│   ├── map_utils.cpython-311.pyc
│   ├── menu_utils.cpython-311.pyc
│   ├── stroing_utils.cpython-311.pyc
│   ├── tun_utils.cpython-311.pyc
│   ├── util_functions.cpython-311.pyc
│   ├── utils.cpython-311.pyc
│   ├── validation_utils.cpython-311.pyc
│   ├── weather_display_utils.cpython-311.pyc
│   └── weather_utils.cpython-311.pyc
├── app.log
├── components
│   └── ui
│       └── __pycache__
├── data
│   ├── Background.jpg
│   ├── Logo.png
│   ├── app.log.1
│   ├── app.log.2
│   ├── app.log.3
│   ├── app.log.4
│   └── app.log.5
├── database
│   ├── customer.db
│   ├── feedback.db
│   ├── login_history.db
│   ├── stroing.db
│   └── tunbroyting.db
├── docs
├── git.md
├── gullingen.egg-info
│   ├── PKG-INFO
│   ├── SOURCES.txt
│   ├── dependency_links.txt
│   ├── requires.txt
│   └── top_level.txt
├── logs
│   └── app.log
├── mapmarker.js
├── node_modules
│   ├── js-tokens
│   │   ├── CHANGELOG.md
│   │   ├── LICENSE
│   │   ├── README.md
│   │   ├── index.js
│   │   └── package.json
│   ├── loose-envify
│   │   ├── LICENSE
│   │   ├── README.md
│   │   ├── cli.js
│   │   ├── custom.js
│   │   ├── index.js
│   │   ├── loose-envify.js
│   │   ├── package.json
│   │   └── replace.js
│   ├── lucide-react
│   │   ├── LICENSE
│   │   ├── README.md
│   │   ├── dist
│   │   ├── dynamicIconImports.d.ts
│   │   ├── dynamicIconImports.js
│   │   ├── dynamicIconImports.js.map
│   │   └── package.json
│   └── react
│       ├── LICENSE
│       ├── README.md
│       ├── cjs
│       ├── index.js
│       ├── jsx-dev-runtime.js
│       ├── jsx-runtime.js
│       ├── package.json
│       ├── react.shared-subset.js
│       └── umd
├── package-lock.json
├── package.json
├── requirements-dev.txt
├── requirements.txt
├── setup.py
├── src
│   ├── __init__.py
│   ├── __pycache__
│   │   └── __init__.cpython-311.pyc
│   ├── app.py
│   └── components
│       ├── __init__.py
│       ├── __pycache__
│       └── ui
├── tests
│   ├── __pycache__
│   │   ├── test_api.cpython-311.pyc
│   │   ├── test_app.cpython-311.pyc
│   │   ├── test_config.cpython-311.pyc
│   │   ├── test_error_handling.cpython-311.pyc
│   │   ├── test_integration.cpython-311.pyc
│   │   ├── test_performance.cpython-311.pyc
│   │   ├── test_streamlit_app.cpython-311.pyc
│   │   ├── test_tun.cpython-311.pyc
│   │   ├── test_weather_elements.cpython-311.pyc
│   │   └── test_weather_utils.cpython-311.pyc
│   ├── conftest.py
│   ├── fixtures
│   │   └── test_data.json
│   ├── integration
│   │   ├── test_api.py
│   │   └── test_streamlit_integration.py
│   ├── test.py
│   ├── test_app.py
│   ├── test_integration.py
│   ├── test_tun.py
│   ├── test_weather_elements.py
│   ├── test_weather_utils.py
│   └── unit
│       ├── test_auth_utils.py
│       ├── test_basic.py
│       ├── test_database.py
│       ├── test_db_utils.py
│       ├── test_map.py
│       └── test_map_utils.py
├── utils
│   ├── __pycache__
│   │   ├── __init__.cpython-311.pyc
│   │   └── validation.cpython-311.pyc
│   ├── core
│   │   ├── __init__.py
│   │   ├── __pycache__
│   │   ├── auth_utils.py
│   │   ├── config.py
│   │   ├── constants.py
│   │   ├── encryption_utils.py
│   │   ├── logging_config.py
│   │   ├── logging_utils.py
│   │   ├── menu_utils.py
│   │   ├── util_functions.py
│   │   └── validation_utils.py
│   ├── db
│   │   ├── __init__.py
│   │   ├── db_utils.py
│   │   ├── migrations.py
│   │   ├── schemas.py
│   │   └── setup_database.py
│   └── services
│       ├── __pycache__
│       ├── admin_utils.py
│       ├── alert_utils.py
│       ├── customer_utils.py
│       ├── feedback_utils.py
│       ├── gps_utils.py
│       ├── map_utils.py
│       ├── stroing_utils.py
│       ├── tun_utils.py
│       ├── utils.py
│       ├── weather_display_utils.py
│       └── weather_utils.py
└── venv
    ├── bin
    │   ├── Activate.ps1
    │   ├── activate
    │   ├── activate.csh
    │   ├── activate.fish
    │   ├── dotenv
    │   ├── f2py
    │   ├── fastapi
    │   ├── fonttools
    │   ├── httpx
    │   ├── isort
    │   ├── isort-identify-imports
    │   ├── jsonschema
    │   ├── markdown-it
    │   ├── normalizer
    │   ├── numpy-config
    │   ├── pip
    │   ├── pip3
    │   ├── pip3.11
    │   ├── py.test
    │   ├── pyftmerge
    │   ├── pyftsubset
    │   ├── pygmentize
    │   ├── pytest
    │   ├── python -> python3.11
    │   ├── python3 -> python3.11
    │   ├── python3.11 -> /opt/homebrew/opt/python@3.11/bin/python3.11
    │   ├── streamlit
    │   ├── streamlit.cmd
    │   ├── ttx
    │   ├── vba_extract.py
    │   └── watchmedo
    ├── etc
    │   └── jupyter
    ├── include
    │   └── python3.11
    ├── lib
    │   └── python3.11
    ├── pyvenv.cfg
    └── share
        ├── jupyter
        └── man