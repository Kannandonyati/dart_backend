"""How many source applications a recon may carry.

Old DART created two apps with the recon (`app_type` 0 and 1) and let
the Dimension Linking UI add more, up to 5 (`ReconAppdetails.jsx`).
The same cap lives here so Add Application matches that UI.
"""

MAX_RECON_APPS = 5
BOOTSTRAP_APP_NUMBERS = (1, 2)
