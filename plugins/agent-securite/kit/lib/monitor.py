#!/usr/bin/env python3
"""Script moniteur des tâches de veille (cron create --monitor-script monitor.py) : sortie stable, aucun horodatage.
(copie identique, source : shared/kit/lib/monitor.py)"""
import os
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.exit(subprocess.call([sys.executable, os.path.join(here, "watch.py"), "--monitor"]))
