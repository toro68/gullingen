Git er som et spill med lagringspunkter:
1. Working Directory (der du jobber)
Som et dokument du skriver på
Alle endringer er her først
Dette er filene du ser i VS Code/editoren din
Staging Area (mellomlagring)
Som å markere hva du vil lagre
Bruker git add filnavn for å legge til filer her
Dette er som å si "disse endringene vil jeg ta vare på"
3. Repository (permanent lagring)
Som å lage et lagringspunkt i spillet
Bruker git commit -m "beskjed" for å lagre
Du kan alltid gå tilbake til disse punktene

# Se status på filene dine
git status

# Legg til filer for lagring
git add filnavn

# Lag et lagringspunkt
git commit -m "Hva jeg har endret"

# Send endringer til GitHub/nett
git push

# Hent endringer fra GitHub/nett
git pull