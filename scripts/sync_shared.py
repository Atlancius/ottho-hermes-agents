"""Recopie le socle commun (shared/) dans chaque plugin : chaque plugin s'installe seul, il doit tout contenir.
  python scripts/sync_shared.py          copie
  python scripts/sync_shared.py --check  échoue si une copie diffère de sa source (utilisé par les tests)
"""
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
ALL = ("agent-mail", "agent-updates", "agent-securite")
VEILLE = ("agent-updates", "agent-securite")
MAP = {
    "scripts/agent-vps.sh": ("scripts/agent-vps.sh", ALL),
    "kit/lib/common.sh": ("kit/lib/common.sh", ALL),
    "kit/lib/profile_apply.py": ("kit/lib/profile_apply.py", ALL),
    "kit/lib/render.py": ("kit/lib/render.py", ALL),
    "kit/lib/deny.json": ("kit/lib/deny.json", ALL),
    "kit/lib/veille.sh": ("kit/lib/veille.sh", VEILLE),
    "kit/lib/veille_cli.sh": ("kit/lib/veille_cli.sh", VEILLE),
    "kit/lib/watch.py": ("kit/lib/watch.py", VEILLE),
    "kit/lib/review.py": ("kit/lib/review.py", VEILLE),
    "kit/lib/monitor.py": ("kit/lib/monitor.py", VEILLE),
    "kit/lib/perimeter_hook.py": ("kit/lib/perimeter_hook.py", VEILLE),
    "references/regles.md": ("references/regles.md", ALL),
}


def main():
    check = "--check" in sys.argv
    bad = []
    for src_rel, (dst_rel, plugins) in MAP.items():
        src = ROOT / "shared" / src_rel
        for plugin in plugins:
            dst = ROOT / "plugins" / plugin / dst_rel
            if check:
                if not dst.exists() or dst.read_bytes() != src.read_bytes():
                    bad.append(str(dst.relative_to(ROOT)))
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dst)
    if check and bad:
        print("Copies différentes de shared/ : " + ", ".join(bad) + "\n→ python scripts/sync_shared.py")
        sys.exit(1)
    print("SYNC_OK" if not check else "SYNC_CHECK_OK")


if __name__ == "__main__":
    main()
