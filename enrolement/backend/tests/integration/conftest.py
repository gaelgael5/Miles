from __future__ import annotations

from miles_socle.testing.db import blank_db_fixture

# Une base vierge par test, détruite après, et dont le nom porte celui du produit : une
# base oubliée sur la machine de test doit dire d'où elle vient. Le mécanisme est au socle,
# les trois produits le partageaient à l'identique.
blank_db = blank_db_fixture("enrolement_test")
