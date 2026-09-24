# Kept from the Decky plugin template so `decky plugin build` (the Decky
# store's builder) still works: it builds this image, runs entrypoint.sh
# inside it with the plugin root mounted at /plugin, and packages
# backend/out/ as the zip's bin/. entrypoint.sh builds the CLI from
# /plugin/cli/src with the image's python3 (SteamOS's own, as on a Deck).
# Nothing in this repo's own CI or release path uses Docker; see
# scripts/package.py and spec 3.6.2.
FROM ghcr.io/steamdeckhomebrew/holo-base:latest

# entrypoint.sh should always be located in the backend folder
ENTRYPOINT [ "/backend/entrypoint.sh" ]
