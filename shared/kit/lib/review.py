#!/usr/bin/env python3
"""Script de pré-exécution de la revue hebdomadaire : imprime l'instantané complet sans toucher à l'état de veille.
(copie identique, source : shared/kit/lib/review.py)"""
import os
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.exit(subprocess.call([sys.executable, os.path.join(here, "watch.py"), "--full"]))
