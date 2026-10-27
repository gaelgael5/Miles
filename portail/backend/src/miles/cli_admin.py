from __future__ import annotations

import argparse
import sys

from miles_socle.auth.passwords import WeakPasswordError, check_password_policy, hash_password

EXIT_OK = 0
EXIT_REFUSED = 2


def main(argv: list[str] | None = None) -> int:
    """`miles-admin hash-password` : empreinte argon2id d'un mot de passe lu sur stdin.

    Utilisé par dev-deploy.sh pour déclarer le compte d'amorçage d'une machine de
    test. Le mot de passe arrive par stdin, jamais en argument : l'argv de tout
    processus est lisible par `ps`.
    """
    parser = argparse.ArgumentParser(prog="miles-admin")
    parser.add_argument("command", choices=["hash-password"])
    parser.parse_args(argv)
    password = sys.stdin.readline().rstrip("\n")
    try:
        check_password_policy(password)
    except WeakPasswordError as exc:
        sys.stderr.write(f"mot de passe refusé : {exc}\n")
        return EXIT_REFUSED
    sys.stdout.write(hash_password(password) + "\n")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
