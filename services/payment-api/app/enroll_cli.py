"""Enrôlement facial par un opérateur, depuis 5 photos (pool de poses), hors
parcours web.

Lie le pool d'empreintes d'un visage à un client existant, ou crée le client
(mot de passe haché par pgcrypto, comme le seed) et son compte. Exécuté DANS
le conteneur payment-api (accès à face-api et à la base, jamais exposé au
WAF) :

    scripts/enroll-face.sh jordan --create --password 'Jordan#2026' --consent \\
        --photo-face moi-face.jpg --photo-right moi-droite.jpg \\
        --photo-up moi-haut.jpg --photo-down moi-bas.jpg --photo-left moi-gauche.jpg

(le script copie les photos dans le conteneur, lance ce module, puis les
supprime : seules les empreintes sont stockées).
"""

from __future__ import annotations

import argparse
import base64
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from . import accounts, biometrics, face
from .config import settings

# Photo de téléphone pleine résolution : bien au-delà de la limite web.
MAX_PHOTO_BYTES = 15 * 1024 * 1024


def _embed_photo(pose: str, photo: Path) -> list[float]:
    raw = photo.read_bytes()
    if len(raw) > MAX_PHOTO_BYTES:
        raise SystemExit(f"photo '{pose}' trop lourde (15 Mo max)")
    try:
        return face.embed(base64.b64encode(raw).decode(), max_chars=MAX_PHOTO_BYTES * 2)
    except face.FaceRejected as exc:
        raise SystemExit(f"photo '{pose}' refusée : {exc.code}") from None
    except face.FaceUnavailable as exc:
        raise SystemExit(f"face-api indisponible (photo '{pose}') : {exc}") from None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--username", required=True)
    for pose in face.REQUIRED_POSES:
        ap.add_argument(
            f"--photo-{pose}", required=True, type=Path, help=f"JPEG/PNG, pose '{pose}'"
        )
    ap.add_argument("--create", action="store_true", help="crée le client et son compte")
    ap.add_argument("--password", help="mot de passe du nouveau client (--create)")
    ap.add_argument("--iban", help="IBAN fictif du nouveau compte (défaut : suivant libre)")
    ap.add_argument("--balance", type=Decimal, default=Decimal("2500.00"))
    ap.add_argument(
        "--consent",
        action="store_true",
        help=(
            "atteste que le consentement biométrique du client a été recueilli "
            "(requis avec --create)"
        ),
    )
    ap.add_argument("--replace", action="store_true", help="écrase le pool d'empreintes existant")
    args = ap.parse_args(argv)

    if args.create and not args.password:
        ap.error("--create exige --password")
    if args.create and not args.consent:
        ap.error("--create exige --consent (consentement biométrique recueilli)")

    # Empreintes d'abord : on ne crée pas de client si une seule photo est
    # inexploitable (fail-fast, aucune écriture partielle).
    embeddings = {
        pose: _embed_photo(pose, getattr(args, f"photo_{pose}")) for pose in face.REQUIRED_POSES
    }

    if args.create:
        iban = args.iban or accounts.next_iban()
        try:
            accounts.create_customer(
                args.username, args.password, iban, args.balance, consent_at=datetime.now(UTC)
            )
        except accounts.AccountError:
            raise SystemExit(
                f"le client {args.username!r} existe déjà (retirer --create)"
            ) from None
        print(f"client {args.username} créé, compte {iban} ({args.balance} EUR)")

    if args.replace:
        ok = biometrics.replace_enrollment(args.username, settings.face_model, embeddings)
    else:
        ok = biometrics.save_enrollment(args.username, settings.face_model, embeddings)
        if not ok and biometrics.get_enrollment(args.username) is not None:
            print("empreinte déjà enregistrée (utiliser --replace)", file=sys.stderr)
            return 4
    if not ok:
        print(f"client {args.username!r} introuvable (ajouter --create)", file=sys.stderr)
        return 4

    biometrics.log_attempt(
        args.username, purpose="enroll", result="enrolled_by_operator", distance=None
    )
    print(
        f"visage enregistré pour {args.username} "
        f"({settings.face_model}, {len(embeddings)} poses)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
