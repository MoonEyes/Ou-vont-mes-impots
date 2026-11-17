#!/usr/bin/env bash
# Installation de la collecte hebdomadaire sur un VPS Debian/Ubuntu (a lancer en root, relancable) :
#   curl -fsSLO https://raw.githubusercontent.com/MoonEyes/Ou-vont-mes-impots/main/deploy/installer_vps.sh
#   sudo bash installer_vps.sh
# Fait : utilisateur systeme « ovmi » sans shell ni sudo, depot public clone dans /var/lib/ovmi,
# venv Python (requirements.lock a empreintes verifiees quand la plateforme le permet, sinon requirements.txt ;
# plus duckdb + xlrd), outils PDF/OCR de l'orchestrateur pipeline/tout.py, rclone officiel (somme SHA256
# verifiee), extension DuckDB httpfs, /etc/ovmi/stockage.env (modele vide, 640 root:ovmi), /etc/ovmi/alerte.env
# (600 root:root), unites systemd + minuterie (verifiees par systemd-analyze).
# Ne fait pas : saisir ou deplacer des cles (signale seulement un jeton d'alerte reste dans stockage.env, constat I5),
# lancer une collecte.
set -euo pipefail

UTILISATEUR=${OVMI_UTILISATEUR:-ovmi}
RACINE=${OVMI_RACINE:-/var/lib/ovmi}
DEPOT_URL=${OVMI_DEPOT_URL:-https://github.com/MoonEyes/Ou-vont-mes-impots.git}
BRANCHE=${OVMI_BRANCHE:-main}
DEPOT=$RACINE/ou-vont-mes-impots
CONF=/etc/ovmi

die() { echo "ERREUR : $*" >&2; exit 1; }
etape() { echo; echo "==> $*"; }
en_ovmi() { runuser -u "$UTILISATEUR" -- env HOME="$RACINE" "$@"; }

[[ $(id -u) -eq 0 ]] || die "a lancer en root (sudo bash $0)"
command -v apt-get >/dev/null || die "Debian ou Ubuntu attendu (apt-get)"

etape "paquets systeme"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends python3 python3-venv python3-pip git curl unzip \
    ca-certificates util-linux coreutils findutils gzip >/dev/null
# outils systeme des etapes PDF et OCR de pipeline/tout.py (memes paquets que .github/workflows/data.yml)
apt-get install -y -qq --no-install-recommends poppler-utils tesseract-ocr tesseract-ocr-fra >/dev/null

etape "utilisateur dedie $UTILISATEUR (sans shell, sans sudo)"
if ! id -u "$UTILISATEUR" >/dev/null 2>&1; then
    useradd --system --home-dir "$RACINE" --create-home --shell /usr/sbin/nologin \
        --comment "Ou vont mes impots, collecte" "$UTILISATEUR"
fi
install -d -m 750 -o "$UTILISATEUR" -g "$UTILISATEUR" "$RACINE" "$RACINE/journaux"

etape "rclone (binaire officiel, somme SHA256 verifiee)"
case "$(uname -m)" in
    x86_64) ARCH=amd64 ;;
    aarch64|arm64) ARCH=arm64 ;;
    *) die "architecture non geree : $(uname -m)" ;;
esac
VERSION=$(curl -fsSL https://downloads.rclone.org/version.txt | awk '{print $2}')
[[ $VERSION =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "version rclone illisible : $VERSION"
ACTUELLE=$(rclone version 2>/dev/null | awk 'NR==1 {print $2}' || true)
if [[ "$ACTUELLE" != "$VERSION" ]]; then
    TMP=$(mktemp -d)
    trap 'rm -rf "$TMP"' EXIT
    ZIP=rclone-$VERSION-linux-$ARCH.zip
    curl -fsSL -o "$TMP/$ZIP" "https://downloads.rclone.org/$VERSION/$ZIP"
    curl -fsSL -o "$TMP/SHA256SUMS" "https://downloads.rclone.org/$VERSION/SHA256SUMS"
    (cd "$TMP" && grep " $ZIP\$" SHA256SUMS | sha256sum -c -) || die "somme SHA256 de rclone invalide"
    unzip -q -o "$TMP/$ZIP" -d "$TMP"
    install -m 755 "$TMP/rclone-$VERSION-linux-$ARCH/rclone" /usr/local/bin/rclone
fi
rclone version | head -1

etape "depot $DEPOT_URL ($BRANCHE)"
if [[ -d "$DEPOT/.git" ]]; then
    en_ovmi git -C "$DEPOT" pull --ff-only -q
else
    en_ovmi git clone -q --branch "$BRANCHE" --depth 50 "$DEPOT_URL" "$DEPOT"
fi
chmod 750 "$DEPOT"

etape "environnement Python"
[[ -x "$RACINE/venv/bin/python" ]] || en_ovmi python3 -m venv "$RACINE/venv"
en_ovmi "$RACINE/venv/bin/pip" install -q --upgrade pip
# requirements.lock est compile pour CPython 3.13 x86_64 (comme data.yml) : versions et empreintes identiques
# a la production de site/data. Ailleurs (autre Python, arm64), repli sur requirements.txt, signale.
if [[ -f "$DEPOT/requirements.lock" && "$(uname -m)" == x86_64 ]] \
    && "$RACINE/venv/bin/python" -c 'import sys; sys.exit(sys.version_info[:2] != (3, 13))' \
    && en_ovmi "$RACINE/venv/bin/pip" install -q --require-hashes --no-deps -r "$DEPOT/requirements.lock"; then
    echo "dependances figees installees (requirements.lock, empreintes verifiees)"
else
    echo "AVERTISSEMENT : requirements.lock inutilisable ici ($(uname -m), $("$RACINE/venv/bin/python" -V 2>&1)) :" \
        "repli sur requirements.txt (versions non figees)"
    en_ovmi "$RACINE/venv/bin/pip" install -q -r "$DEPOT/requirements.txt"
fi
en_ovmi "$RACINE/venv/bin/pip" install -q -r "$DEPOT/deploy/requirements-vps.txt"
en_ovmi "$RACINE/venv/bin/python" -c "import duckdb; duckdb.sql('INSTALL httpfs'); print('duckdb', duckdb.__version__)"

etape "configuration $CONF/stockage.env"
install -d -m 750 -o root -g "$UTILISATEUR" "$CONF"
if [[ ! -f "$CONF/stockage.env" ]]; then
    install -m 640 -o root -g "$UTILISATEUR" "$DEPOT/deploy/env.exemple" "$CONF/stockage.env"
    echo "modele copie : a completer (cles S3 et noms des buckets)"
else
    chown root:"$UTILISATEUR" "$CONF/stockage.env"; chmod 640 "$CONF/stockage.env"
    echo "deja present, conserve"
fi
# Constat I5 : la valeur n'est ni lue ni affichee, seule sa presence est signalee.
if grep -Eq '^[[:space:]]*OVMI_ALERTE_GITHUB_JETON=[^[:space:]#]' "$CONF/stockage.env"; then
    echo "AVERTISSEMENT (I5) : un jeton d'alerte est encore dans $CONF/stockage.env (lisible par le groupe $UTILISATEUR)."
    echo "  Le deplacer a la main vers $CONF/alerte.env (600 root:root), puis vider la ligne dans stockage.env."
    echo "  En attendant, ovmi-collecte.service le retire de son environnement (UnsetEnvironment=)."
fi

if [[ ! -f "$CONF/alerte.env" ]]; then
    install -m 600 -o root -g root /dev/null "$CONF/alerte.env"
    printf '%s\n' "# Alerte GitHub (lu par ovmi-collecte-alerte.service seulement). Jeton a portee issues: write sur le depot seul." \
        "OVMI_GITHUB_DEPOT=MoonEyes/Ou-vont-mes-impots" "OVMI_ALERTE_GITHUB=0" "OVMI_ALERTE_GITHUB_JETON=" > "$CONF/alerte.env"
else
    chown root:root "$CONF/alerte.env"; chmod 600 "$CONF/alerte.env"
fi

etape "unites systemd"
install -m 644 "$DEPOT"/deploy/systemd/ovmi-collecte.service "$DEPOT"/deploy/systemd/ovmi-collecte.timer \
    "$DEPOT"/deploy/systemd/ovmi-collecte-alerte.service /etc/systemd/system/
chmod 755 "$DEPOT/deploy/collecte-hebdo.sh"
systemd-analyze verify /etc/systemd/system/ovmi-collecte.service /etc/systemd/system/ovmi-collecte.timer \
    /etc/systemd/system/ovmi-collecte-alerte.service || die "unites systemd invalides (voir ci-dessus)"
systemctl daemon-reload
systemctl enable --now ovmi-collecte.timer
systemctl list-timers ovmi-collecte.timer --no-pager | head -3

cat <<FIN

Installation terminee. Etapes suivantes :
  1. sudo nano $CONF/stockage.env      (cles S3 OVH, OVMI_BUCKET_PUBLIC, OVMI_BUCKET_PRIVE)
     facultatif : sudo nano $CONF/alerte.env (jeton GitHub de l'alerte, OVMI_ALERTE_GITHUB=1)
  2. sudo -u $UTILISATEUR bash -c 'set -a; . $CONF/stockage.env; cd $DEPOT && $RACINE/venv/bin/python collecte/stockage.py config'
  3. premier passage a la main (sinon lundi 3 h) : sudo systemctl start ovmi-collecte.service
     suivi : journalctl -u ovmi-collecte -f ; journaux du script : $RACINE/journaux (12 gardes, compresses)
     confinement : systemd-analyze security ovmi-collecte.service
  4. facultatif : OVMI_PIPELINE=1 dans stockage.env pour lancer aussi pipeline/tout.py apres la collecte
FIN
