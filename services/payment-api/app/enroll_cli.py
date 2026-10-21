"""Enrôlement facial par un opérateur, depuis une photo, hors parcours web.

Lie l'empreinte d'un visage à un client existant, ou crée le client (mot de
passe haché par pgcrypto, comme le seed) et son compte. Exécuté DANS le
conteneur payment-api (accès à face-api et à la base, jamais exposé au WAF) :

    scripts/enroll-face.sh moi.jpg jordan --create --password 'Jordan#2026'

(le script copie la photo dans le conteneur, lance ce module, puis supprime la
photo : seule l'empreinte est stockée).
"""

from __future__ import annotations

import argparse
import base64
import sys
from decimal import Decimal
from pathlib import Path

from . import accounts, biometrics, face
from .config import settings

# Photo de téléphone pleine résolution : bien au-delà de la limite web.
MAX_PHOTO_BYTES = 15 * 1024 * 1024


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--username", required=True)
    ap.add_argument("--photo", required=True, type=Path, help="JPEG ou PNG, un seul visage")
    ap.add_argument("--create", action="store_true", help="crée le client et son compte")
    ap.add_argument("--password", help="mot de passe du nouveau client (--create)")
    ap.add_argument("--iban", help="IBAN fictif du nouveau compte (défaut : suivant libre)")
    ap.add_argument("--balance", type=Decimal, default=Decimal("2500.00"))
    ap.add_argument("--replace", action="store_true", help="écrase une empreinte existante")
    args = ap.parse_args(argv)

    if args.create and not args.password:
        ap.error("--create exige --password")
    raw = args.photo.read_bytes()
    if len(raw) > MAX_PHOTO_BYTES:
        ap.error("photo trop lourde (15 Mo max)")

    # Empreinte d'abord : on ne crée pas de client si la photo est inexploitable.
    try:
        embedding = face.embed(base64.b64encode(raw).decode(), max_chars=MAX_PHOTO_BYTES * 2)
    except face.FaceRejected as exc:
        print(f"photo refusée : {exc.code}", file=sys.stderr)
        return 2
    except face.FaceUnavailable as exc:
        print(f"face-api indisponible : {exc}", file=sys.stderr)
        return 3

    if args.create:
        iban = args.iban or accounts.next_iban()
        try:
            accounts.create_customer(args.username, args.password, iban, args.balance)
        except accounts.AccountError:
            raise SystemExit(f"le client {args.username!r} existe déjà (retirer --create)") from None
        print(f"client {args.username} créé, compte {iban} ({args.balance} EUR)")

    if args.replace:
        ok = biometrics.replace_enrollment(args.username, settings.face_model, embedding)
    else:
        ok = biometrics.save_enrollment(args.username, settings.face_model, embedding)
        if not ok and biometrics.get_enrollment(args.username) is not None:
            print("empreinte déjà enregistrée (utiliser --replace)", file=sys.stderr)
            return 4
    if not ok:
        print(f"client {args.username!r} introuvable (ajouter --create)", file=sys.stderr)
        return 4

    biometrics.log_attempt(
        args.username, purpose="enroll", result="enrolled_by_operator", distance=None
    )
    print(f"visage enregistré pour {args.username} ({settings.face_model}, {len(embedding)} d)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
