"""Remplit un gabarit (SOUL.md, réglages) avec les valeurs de /etc/ottho-agents/<agent>.json.
  python3 render.py <gabarit> <conf.json> [--yaml]
Marqueurs : @@CLE@@ (clé du JSON en majuscules). Un marqueur sans valeur devient « (à préciser) ».
--yaml : chaque valeur est écrite comme une chaîne YAML entre guillemets, échappée (apostrophes, antislash, deux-points),
pour les gabarits de réglages où le marqueur est seul, sans guillemets autour.
(copie identique dans chaque plugin, source : shared/kit/lib/render.py)
"""
import json
import re
import sys

template = open(sys.argv[1], encoding="utf-8").read()
conf = json.load(open(sys.argv[2], encoding="utf-8")) if len(sys.argv) > 2 else {}
values = {str(k).upper(): str(v) for k, v in conf.items() if v not in (None, "")}
as_yaml = "--yaml" in sys.argv[3:]


def value(match):
    text = values.get(match.group(1), "" if as_yaml else "(à préciser)")
    return json.dumps(text, ensure_ascii=False) if as_yaml else text


sys.stdout.write(re.sub(r"@@([A-Z0-9_]+)@@", value, template))
